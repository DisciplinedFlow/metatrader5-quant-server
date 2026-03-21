"""
Lighter.xyz NEAR Momentum Breakout entry strategy.

Uses Bollinger Band squeeze breakouts on 1h candles, optimised for NEAR's
speed profile (~1.4h per 1% move). Social sentiment filters prevent fighting
strong crowd bias.

Strategy logic:
  BB squeeze breakout  — squeeze detected (width < 0.8× avg), price breaks band
  BB expansion entry   — no squeeze, price strongly outside band (>1.5 std dev)
                         with volume confirmation

Signal prefix: 'lighter:near_' — own single-position budget.
Cooldown: 2h after close to prevent churn.
"""
import logging
import math
from datetime import datetime, timezone

from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from .client import get_best_bid_ask, get_candles, place_market_order_usd, update_leverage, place_oco_sltp
from .sizing import calculate_position_usd
from .social_sentiment import get_social_sentiment
from .orderbook_signal import get_ob_imbalance, get_trade_flow
from .vwap import get_vwap_bias

logger = logging.getLogger('app.lighter')

NEAR_PREFIX = 'lighter:near_'
PLATFORM_PREFIX = 'lighter:'

# ── Risk sizing ───────────────────────────────────────────────────────────
SL_PCT = 0.015   # 1.5% — backtest-validated for NEAR
TP_PCT = 0.030   # 3.0% — 1:2 R:R

MIN_FREE_COLLATERAL = 8.0   # Skip if collateral below this

# ── Cooldown ──────────────────────────────────────────────────────────────
NEAR_COOLDOWN_KEY = 'lighter:near_cooldown'
NEAR_COOLDOWN_SECONDS = 2 * 3600   # 2h post-close cooldown

# ── Bollinger Band parameters ─────────────────────────────────────────────
BB_PERIOD = 20
BB_STD_MULT = 2.0
BB_RESOLUTION = '1h'
BB_CANDLE_COUNT = 50   # warm-up buffer beyond 20-period
CANDLE_CACHE_TTL = 300   # 5min — 1h bars don't need fresher

# Squeeze: current width must be below this fraction of its 20-bar average
SQUEEZE_WIDTH_RATIO = 0.8

# Non-squeeze expansion entry: price must be this many std devs outside band
EXPANSION_STD_THRESHOLD = 1.5

# Volume confirmation: current bar volume must exceed this multiple of avg
VOLUME_RATIO_MIN = 1.5

# ── Social sentiment thresholds ───────────────────────────────────────────
SENTIMENT_LONG_BLOCK = -0.3   # bearish sentiment → skip LONG
SENTIMENT_SHORT_BLOCK = 0.3   # bullish sentiment → skip SHORT


# ── Bollinger Band helpers ────────────────────────────────────────────────

def _mean(values: list) -> float:
    return sum(values) / len(values)


def _stdev(values: list) -> float:
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _compute_bb(closes: list, period: int = BB_PERIOD) -> tuple:
    """Compute most-recent Bollinger Band values.

    Returns (mid, upper, lower, std, width) where width = upper - lower.
    """
    window = closes[-period:]
    mid = _mean(window)
    std = _stdev(window)
    upper = mid + BB_STD_MULT * std
    lower = mid - BB_STD_MULT * std
    width = upper - lower
    return mid, upper, lower, std, width


def _get_bb_signal(symbol: str) -> tuple:
    """Compute Bollinger Band breakout signal for NEAR.

    Returns:
        (signal, context) where signal is +1 (long), -1 (short), or 0 (no signal),
        and context is a dict with diagnostic data for logging.
    """
    cache_key = f'lighter:near_candles:{symbol}'
    candles = cache.get(cache_key)
    if candles is None:
        try:
            candles = get_candles(symbol, resolution=BB_RESOLUTION, count_back=BB_CANDLE_COUNT)
        except Exception as e:
            logger.debug("NEAR candle fetch failed: %s", e)
            return 0, {}
        if candles and len(candles) >= BB_PERIOD + 5:
            cache.set(cache_key, candles, timeout=CANDLE_CACHE_TTL)

    if not candles or len(candles) < BB_PERIOD + 5:
        logger.debug("NEAR: insufficient candles (%d)", len(candles) if candles else 0)
        return 0, {}

    closes = [float(c['c']) for c in candles if c.get('c') is not None]
    volumes = [float(c.get('v', 0)) for c in candles]

    if len(closes) < BB_PERIOD + 5:
        return 0, {}

    # Current bar values
    current_close = closes[-1]
    current_volume = volumes[-1]

    # Current BB
    mid, upper, lower, std, width = _compute_bb(closes, BB_PERIOD)

    # Historical BB widths for squeeze detection (last 20 bars)
    widths = []
    for i in range(len(closes) - BB_PERIOD, len(closes)):
        window = closes[i - BB_PERIOD:i]
        if len(window) == BB_PERIOD:
            w_std = _stdev(window)
            widths.append(4.0 * w_std)   # BB width = 2 * 2 * std
    avg_width = _mean(widths) if widths else width

    # Volume confirmation
    vol_avg = _mean(volumes[-BB_PERIOD:]) if len(volumes) >= BB_PERIOD else current_volume
    volume_ok = vol_avg > 0 and (current_volume / vol_avg) >= VOLUME_RATIO_MIN

    squeeze_active = width < SQUEEZE_WIDTH_RATIO * avg_width

    ctx = {
        'close': current_close,
        'upper': upper,
        'lower': lower,
        'mid': mid,
        'std': std,
        'width': width,
        'avg_width': avg_width,
        'squeeze': squeeze_active,
        'vol_ratio': (current_volume / vol_avg) if vol_avg > 0 else 1.0,
        'volume_ok': volume_ok,
    }

    # ── Squeeze breakout ──────────────────────────────────────────────
    if squeeze_active:
        if current_close > upper:
            logger.debug("NEAR: squeeze LONG breakout close=%.5f upper=%.5f", current_close, upper)
            return +1, ctx
        if current_close < lower:
            logger.debug("NEAR: squeeze SHORT breakout close=%.5f lower=%.5f", current_close, lower)
            return -1, ctx
        logger.debug("NEAR: squeeze active but no breakout yet (%.5f in [%.5f, %.5f])",
                     current_close, lower, upper)
        return 0, ctx

    # ── Expansion entry (no squeeze) — requires volume confirmation ───
    if not volume_ok:
        logger.debug("NEAR: no squeeze, volume too low (ratio=%.2f < %.2f)",
                     ctx['vol_ratio'], VOLUME_RATIO_MIN)
        return 0, ctx

    std_distance_above = (current_close - upper) / std if std > 0 else 0.0
    std_distance_below = (lower - current_close) / std if std > 0 else 0.0

    if std_distance_above >= EXPANSION_STD_THRESHOLD:
        logger.debug("NEAR: expansion LONG entry (%.2f std above upper)", std_distance_above)
        return +1, ctx
    if std_distance_below >= EXPANSION_STD_THRESHOLD:
        logger.debug("NEAR: expansion SHORT entry (%.2f std below lower)", std_distance_below)
        return -1, ctx

    logger.debug("NEAR: no BB signal (close=%.5f not outside bands by %.1f std)",
                 current_close, EXPANSION_STD_THRESHOLD)
    return 0, ctx


# ── Main entry ────────────────────────────────────────────────────────────

def run_near_entry():
    """NEAR Bollinger Band momentum breakout entry. Called every 60s by Celery.

    Flow:
      1. Global guards (disabled flag, collateral, global position limit)
      2. NEAR-specific guard (max 1 position, cooldown)
      3. BB signal detection (squeeze breakout or strong expansion)
      4. Social sentiment filter
      5. Size → place order → record position → place OCO SL/TP
    """
    if cache.get('lighter:disabled'):
        logger.debug("NEAR: trading disabled via dashboard toggle")
        return

    collateral = cache.get('lighter:collateral')
    if collateral is not None and float(collateral) < MIN_FREE_COLLATERAL:
        logger.info("NEAR: collateral $%.2f below minimum $%.2f, skipping",
                    float(collateral), MIN_FREE_COLLATERAL)
        return

    from .config import is_global_position_limit_reached
    if is_global_position_limit_reached():
        logger.debug("NEAR: global position limit reached, skipping")
        return

    from app.crypto.models import CryptoPosition

    near_open = CryptoPosition.objects.filter(symbol='NEAR', status='OPEN').count()
    if near_open >= 1:
        logger.debug("NEAR: position already open, skipping")
        return

    if cache.get(NEAR_COOLDOWN_KEY):
        logger.debug("NEAR: in 2h cooldown after last close")
        return

    if cache.get(f'lighter:vanish_cooldown:NEAR'):
        return

    if LIGHTER_MARKETS.get('NEAR') is None:
        logger.warning("NEAR: symbol not in LIGHTER_MARKETS, skipping")
        return

    # ── BB signal ─────────────────────────────────────────────────────
    signal, ctx = _get_bb_signal('NEAR')
    if signal == 0:
        return

    is_buy = signal > 0
    direction_str = 'BUY' if is_buy else 'SELL'
    side = 'LONG' if is_buy else 'SHORT'

    # ── Social sentiment filter ────────────────────────────────────────
    try:
        sentiment = get_social_sentiment('NEAR')
        score = sentiment.get('sentiment_score', 0.0)
        if is_buy and score < SENTIMENT_LONG_BLOCK:
            logger.info(
                "NEAR: social sentiment blocks LONG (score=%.2f < %.2f)",
                score, SENTIMENT_LONG_BLOCK,
            )
            return
        if not is_buy and score > SENTIMENT_SHORT_BLOCK:
            logger.info(
                "NEAR: social sentiment blocks SHORT (score=%.2f > %.2f)",
                score, SENTIMENT_SHORT_BLOCK,
            )
            return
        logger.debug("NEAR: sentiment OK (score=%.2f, source=%s)",
                     score, sentiment.get('source', '?'))
    except Exception as e:
        logger.debug("NEAR: sentiment check failed (non-blocking): %s", e)

    # ── Smart money confirmation (OB + trade flow + VWAP) ────────────
    confirmations = 0
    ob_imbalance = 0.5

    try:
        ob_imbalance = get_ob_imbalance('NEAR')
        if is_buy and ob_imbalance > 0.55:
            confirmations += 1
        elif not is_buy and ob_imbalance < 0.45:
            confirmations += 1
        elif is_buy and ob_imbalance < 0.40:
            confirmations -= 1
        elif not is_buy and ob_imbalance > 0.60:
            confirmations -= 1
        logger.debug("NEAR: OB imbalance=%.3f", ob_imbalance)
    except Exception as e:
        logger.debug("NEAR: OB imbalance unavailable: %s", e)

    try:
        flow = get_trade_flow('NEAR')
        flow_cvd = flow.get('cvd', 0)
        if (is_buy and flow_cvd > 0) or (not is_buy and flow_cvd < 0):
            confirmations += 1
        elif (is_buy and flow_cvd < 0) or (not is_buy and flow_cvd > 0):
            confirmations -= 1
        logger.debug("NEAR: trade flow cvd=%.2f", flow_cvd)
    except Exception as e:
        logger.debug("NEAR: trade flow unavailable: %s", e)

    try:
        vwap = get_vwap_bias('NEAR')
        vwap_bias = vwap.get('bias', 'AT')
        if (is_buy and vwap_bias == 'ABOVE') or (not is_buy and vwap_bias == 'BELOW'):
            confirmations += 1
        elif (is_buy and vwap_bias == 'BELOW') or (not is_buy and vwap_bias == 'ABOVE'):
            confirmations -= 1
        logger.debug("NEAR: VWAP bias=%s confirmations=%d", vwap_bias, confirmations)
    except Exception as e:
        logger.debug("NEAR: VWAP unavailable: %s", e)

    if confirmations < 0:
        logger.info("NEAR: smart money OPPOSED (confirmations=%d, ob=%.2f) — skipping %s",
                     confirmations, ob_imbalance, 'LONG' if is_buy else 'SHORT')
        return

    # ── Risk-normalised sizing ─────────────────────────────────────────
    position_usd = calculate_position_usd('NEAR', SL_PCT)
    meta = LIGHTER_MARKETS['NEAR']
    if position_usd < meta['min_quote']:
        logger.debug("NEAR: position $%.2f below min $%.2f", position_usd, meta['min_quote'])
        return

    # ── Live price ────────────────────────────────────────────────────
    prices = get_best_bid_ask('NEAR')
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        logger.warning("NEAR: no price data")
        return

    if is_buy:
        stop_loss = live_price * (1 - SL_PCT)
        take_profit = live_price * (1 + TP_PCT)
    else:
        stop_loss = live_price * (1 + SL_PCT)
        take_profit = live_price * (1 - TP_PCT)

    logger.info(
        "NEAR ENTRY: %s $%.2f (price=%.5f SL=%.5f TP=%.5f "
        "squeeze=%s vol_ratio=%.2f bb_width=%.5f)",
        side, position_usd, live_price, stop_loss, take_profit,
        ctx.get('squeeze', '?'), ctx.get('vol_ratio', 0.0), ctx.get('width', 0.0),
    )

    # ── Set leverage ──────────────────────────────────────────────────
    try:
        update_leverage('NEAR', LIGHTER_LEVERAGE)
    except Exception:
        pass

    # ── Place market order ────────────────────────────────────────────
    result = place_market_order_usd('NEAR', is_buy, position_usd)
    if result.get('error'):
        logger.error("NEAR: order failed: %s", result['error'])
        return

    base_size = position_usd / live_price
    entry_type = 'squeeze' if ctx.get('squeeze') else 'expansion'
    signal_tag = f'{NEAR_PREFIX}bb_{entry_type}_{"bull" if is_buy else "bear"}'

    # ── Record position ───────────────────────────────────────────────
    from app.crypto.models import CryptoTrade

    position = CryptoPosition.objects.create(
        symbol='NEAR',
        side=side,
        entry_price=live_price,
        size=base_size,
        leverage=LIGHTER_LEVERAGE,
        entry_signal=signal_tag,
        stop_loss=stop_loss,
        take_profit=take_profit,
        status='OPEN',
        venue='LIGHTER',
    )

    CryptoTrade.objects.create(
        position=position,
        order_id=result.get('tx_hash', ''),
        side=direction_str,
        price=live_price,
        size=base_size,
        fee=0.0,
        status='FILLED',
    )

    # ── On-chain OCO SL/TP ────────────────────────────────────────────
    try:
        oco_result = place_oco_sltp('NEAR', is_buy, base_size, stop_loss, take_profit)
        if oco_result.get('error'):
            logger.warning("NEAR OCO failed: %s", oco_result['error'])
        else:
            logger.info("NEAR OCO placed: SL=%.5f TP=%.5f", stop_loss, take_profit)
    except Exception as e:
        logger.warning("NEAR OCO exception: %s", e)

    cache.set(NEAR_COOLDOWN_KEY, True, timeout=NEAR_COOLDOWN_SECONDS)

    logger.info("NEAR position opened: %s size=%.4f tx=%s",
                side, base_size, result.get('tx_hash', '?'))
