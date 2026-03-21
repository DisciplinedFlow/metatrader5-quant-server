"""
Lighter.xyz TSLA Session Momentum strategy.

Trades TSLA during US market hours only (14:30–21:00 UTC), using a triple-
confirmation approach suited to high-beta equities:

  1. EMA(8/21) crossover — trend direction
  2. RSI(14) momentum filter — avoids entries into weak/choppy trends
  3. Volume confirmation — requires above-average participation

Pre-market gap filter: skips the first candle after a gap > 1% to avoid
chasing gap-fill moves or getting caught in opening volatility.

SL/TP are wider than crypto peers (2%/4%) because TSLA gaps and sweeps
intraday more aggressively than crypto perps.

Signal prefix: 'lighter:tsla_' — independent position budget.
Cooldown: 4h per close to prevent whipsaw re-entries.
"""
import logging
from datetime import datetime, timezone

from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE, is_global_position_limit_reached
from .client import get_best_bid_ask, get_candles, place_market_order_usd, update_leverage, place_oco_sltp
from .sizing import calculate_position_usd
from .orderbook_signal import get_ob_imbalance, get_trade_flow
from .vwap import get_vwap_bias

logger = logging.getLogger('app.lighter')

TSLA_SIGNAL_PREFIX = 'lighter:tsla_'
PLATFORM_PREFIX = 'lighter:'

# ── Session filter ────────────────────────────────────────────────────────────
US_SESSION_START_UTC = 14   # 14:30 — but we check whole-hour bucket for simplicity
US_SESSION_START_MIN = 30
US_SESSION_END_UTC = 21     # 21:00 close

# ── Risk sizing ───────────────────────────────────────────────────────────────
SL_PCT = 0.020   # 2.0% stop-loss — equities gap and sweep more than crypto perps
TP_PCT = 0.040   # 4.0% take-profit — 1:2 R:R
MIN_FREE_COLLATERAL = 8.0

# ── Cooldown ──────────────────────────────────────────────────────────────────
TSLA_COOLDOWN_KEY = 'lighter:tsla_cooldown'
TSLA_COOLDOWN_SECONDS = 4 * 3600   # 4h

# ── Candle config ─────────────────────────────────────────────────────────────
CANDLE_RESOLUTION = '1h'
CANDLE_COUNT = 50
CANDLE_CACHE_KEY = 'lighter:tsla_candles'
CANDLE_CACHE_TTL = 300   # 5 min

# ── EMA parameters ────────────────────────────────────────────────────────────
EMA_FAST = 8
EMA_SLOW = 21

# ── RSI parameters ───────────────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_LONG_MIN = 55    # must show bullish momentum for a long
RSI_SHORT_MAX = 45   # must show bearish momentum for a short

# ── Volume parameters ────────────────────────────────────────────────────────
VOL_MA_PERIOD = 20
VOL_MULTIPLIER = 1.2   # current bar must exceed 1.2× avg volume

# ── Gap filter ────────────────────────────────────────────────────────────────
GAP_SKIP_PCT = 0.01   # skip entry if open vs prev_close gap > 1%


# ── Indicator helpers ─────────────────────────────────────────────────────────

def _ema(closes: list, period: int) -> float:
    """Exponential moving average over a list of closes."""
    k = 2.0 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def _rsi(closes: list, period: int) -> float:
    """Wilder-smoothed RSI over the last `period` closes."""
    if len(closes) < period + 1:
        return 50.0

    # Use last period+1 closes for RSI calculation
    subset = closes[-(period + 1):]
    gains, losses = [], []
    for i in range(1, len(subset)):
        delta = subset[i] - subset[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _volume_ok(volumes: list) -> bool:
    """Return True if the latest bar volume exceeds VOL_MULTIPLIER × 20-bar avg."""
    if len(volumes) < VOL_MA_PERIOD + 1:
        return False
    avg_vol = sum(volumes[-(VOL_MA_PERIOD + 1):-1]) / VOL_MA_PERIOD
    if avg_vol <= 0:
        return False
    return volumes[-1] > VOL_MULTIPLIER * avg_vol


def _has_gap(opens: list, closes: list) -> bool:
    """Return True if the latest bar opened with a > GAP_SKIP_PCT gap vs prev close."""
    if len(opens) < 2 or len(closes) < 2:
        return False
    prev_close = closes[-2]
    current_open = opens[-1]
    if prev_close <= 0:
        return False
    gap_pct = abs(current_open - prev_close) / prev_close
    return gap_pct > GAP_SKIP_PCT


# ── Signal evaluation ─────────────────────────────────────────────────────────

def _get_tsla_signal(candles: list) -> tuple:
    """Evaluate EMA cross + RSI + volume for TSLA.

    Returns:
        (signal, rsi_val) where signal is +1 (long), -1 (short), or 0 (no signal).
    """
    closes = [float(c['c']) for c in candles if c.get('c') is not None]
    volumes = [float(c.get('v', 0)) for c in candles]
    opens = [float(c['o']) for c in candles if c.get('o') is not None]

    if len(closes) < EMA_SLOW + 5:
        logger.debug("TSLA: insufficient close data (%d bars)", len(closes))
        return 0, 50.0

    # EMA crossover
    ema_fast = _ema(closes, EMA_FAST)
    ema_slow = _ema(closes, EMA_SLOW)
    ema_fast_prev = _ema(closes[:-1], EMA_FAST)

    # RSI
    rsi_val = _rsi(closes, RSI_PERIOD)

    # Volume
    vol_confirmed = _volume_ok(volumes)

    # Gap filter — skip if last bar opened with a large gap
    if _has_gap(opens, closes):
        logger.debug("TSLA: pre-market gap detected (open=%.2f prev_close=%.2f), skipping bar",
                     opens[-1] if opens else 0, closes[-2] if len(closes) >= 2 else 0)
        return 0, rsi_val

    bullish = (
        ema_fast > ema_slow           # fast EMA above slow
        and ema_fast > ema_fast_prev  # EMA still rising
        and rsi_val > RSI_LONG_MIN    # strong bullish momentum
        and vol_confirmed             # above-average participation
    )
    bearish = (
        ema_fast < ema_slow
        and ema_fast < ema_fast_prev  # EMA still falling
        and rsi_val < RSI_SHORT_MAX   # strong bearish momentum
        and vol_confirmed
    )

    if bullish:
        return +1, rsi_val
    if bearish:
        return -1, rsi_val
    return 0, rsi_val


# ── Main entry ────────────────────────────────────────────────────────────────

def run_tsla_entry():
    """TSLA session momentum entry. Called every 60s by Celery.

    Flow:
      1. US session gate (14:30–21:00 UTC)
      2. Global disabled flag + collateral guard
      3. Max 1 TSLA position check
      4. Global position limit check
      5. Cooldown check
      6. Candle fetch + signal evaluation (EMA cross + RSI + volume)
      7. Size → place order → record position
    """
    # ── 1. US session gate ────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    hour_utc = now_utc.hour
    minute_utc = now_utc.minute
    in_session = (
        (hour_utc > US_SESSION_START_UTC or (hour_utc == US_SESSION_START_UTC and minute_utc >= US_SESSION_START_MIN))
        and hour_utc < US_SESSION_END_UTC
    )
    if not in_session:
        logger.debug("TSLA: outside US session (%02d:%02d UTC), skipping", hour_utc, minute_utc)
        return

    # ── 2. Global disable + collateral ───────────────────────────────────
    if cache.get('lighter:disabled'):
        logger.debug("TSLA: trading disabled via dashboard toggle")
        return

    collateral = cache.get('lighter:collateral')
    if collateral is not None and float(collateral) < MIN_FREE_COLLATERAL:
        logger.info("TSLA: collateral $%.2f below minimum $%.2f, skipping",
                    float(collateral), MIN_FREE_COLLATERAL)
        return

    from app.crypto.models import CryptoPosition

    # ── 3. Max 1 TSLA position ────────────────────────────────────────────
    tsla_open = CryptoPosition.objects.filter(symbol='TSLA', status='OPEN').count()
    if tsla_open >= 1:
        logger.debug("TSLA: position already open, skipping")
        return

    # ── 4. Global position cap ────────────────────────────────────────────
    if is_global_position_limit_reached():
        logger.debug("TSLA: global position limit reached, skipping")
        return

    # ── 5. Cooldown ───────────────────────────────────────────────────────
    if cache.get(TSLA_COOLDOWN_KEY):
        logger.debug("TSLA: cooldown active, skipping")
        return

    # ── 6. Candle fetch ───────────────────────────────────────────────────
    candles = cache.get(CANDLE_CACHE_KEY)
    if candles is None:
        try:
            candles = get_candles('TSLA', resolution=CANDLE_RESOLUTION, count_back=CANDLE_COUNT)
        except Exception as e:
            logger.debug("TSLA: candle fetch failed: %s", e)
            return
        if candles and len(candles) >= EMA_SLOW + 5:
            cache.set(CANDLE_CACHE_KEY, candles, timeout=CANDLE_CACHE_TTL)

    if not candles or len(candles) < EMA_SLOW + 5:
        logger.debug("TSLA: insufficient candles (%d)", len(candles) if candles else 0)
        return

    # ── Signal evaluation ─────────────────────────────────────────────────
    signal, rsi_val = _get_tsla_signal(candles)
    if signal == 0:
        logger.debug("TSLA: no signal (rsi=%.1f)", rsi_val)
        return

    is_buy = signal > 0
    direction_str = 'BUY' if is_buy else 'SELL'
    side = 'LONG' if is_buy else 'SHORT'

    # ── Smart money confirmation (OB + trade flow + VWAP) ────────────────
    confirmations = 0
    ob_imbalance = 0.5

    try:
        ob_imbalance = get_ob_imbalance('TSLA')
        if is_buy and ob_imbalance > 0.55:
            confirmations += 1
        elif not is_buy and ob_imbalance < 0.45:
            confirmations += 1
        elif is_buy and ob_imbalance < 0.40:
            confirmations -= 1
        elif not is_buy and ob_imbalance > 0.60:
            confirmations -= 1
        logger.debug("TSLA: OB imbalance=%.3f", ob_imbalance)
    except Exception as e:
        logger.debug("TSLA: OB imbalance unavailable: %s", e)

    try:
        flow = get_trade_flow('TSLA')
        # Derive directional signal from CVD (positive = buy dominant)
        cvd = flow.get('cvd', 0.0)
        flow_signal = 1 if cvd > 0 else (-1 if cvd < 0 else 0)
        if (is_buy and flow_signal > 0) or (not is_buy and flow_signal < 0):
            confirmations += 1
        elif (is_buy and flow_signal < 0) or (not is_buy and flow_signal > 0):
            confirmations -= 1
        logger.debug("TSLA: trade flow cvd=%.2f signal=%d", cvd, flow_signal)
    except Exception as e:
        logger.debug("TSLA: trade flow unavailable: %s", e)

    try:
        vwap = get_vwap_bias('TSLA')
        vwap_bias = vwap.get('bias', 'AT')
        if (is_buy and vwap_bias == 'ABOVE') or (not is_buy and vwap_bias == 'BELOW'):
            confirmations += 1
        elif (is_buy and vwap_bias == 'BELOW') or (not is_buy and vwap_bias == 'ABOVE'):
            confirmations -= 1
        logger.debug("TSLA: VWAP bias=%s confirmations=%d", vwap_bias, confirmations)
    except Exception as e:
        logger.debug("TSLA: VWAP unavailable: %s", e)

    if confirmations < 0:
        logger.info("TSLA: smart money OPPOSED (confirmations=%d, ob=%.2f) — skipping %s",
                     confirmations, ob_imbalance, 'LONG' if is_buy else 'SHORT')
        return

    # ── 7. Sizing ─────────────────────────────────────────────────────────
    meta = LIGHTER_MARKETS.get('TSLA')
    if meta is None:
        logger.warning("TSLA: not found in LIGHTER_MARKETS")
        return

    position_usd = calculate_position_usd('TSLA', SL_PCT)
    if position_usd < meta['min_quote']:
        logger.debug("TSLA: position $%.2f below min $%.2f", position_usd, meta['min_quote'])
        return

    # ── Live price ────────────────────────────────────────────────────────
    prices = get_best_bid_ask('TSLA')
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        logger.warning("TSLA: no price data")
        return

    if is_buy:
        stop_loss = live_price * (1 - SL_PCT)
        take_profit = live_price * (1 + TP_PCT)
    else:
        stop_loss = live_price * (1 + SL_PCT)
        take_profit = live_price * (1 - TP_PCT)

    logger.info(
        "TSLA ENTRY: %s $%.2f (price=%.2f SL=%.2f TP=%.2f rsi=%.1f)",
        side, position_usd, live_price, stop_loss, take_profit, rsi_val,
    )

    # ── Set leverage ──────────────────────────────────────────────────────
    try:
        update_leverage('TSLA', LIGHTER_LEVERAGE)
    except Exception:
        pass

    # ── Place market order ────────────────────────────────────────────────
    result = place_market_order_usd('TSLA', is_buy, position_usd)
    if result.get('error'):
        logger.error("TSLA: order failed: %s", result['error'])
        return

    base_size = position_usd / live_price
    signal_tag = f'{TSLA_SIGNAL_PREFIX}ema_{"bull" if is_buy else "bear"}'

    # ── Record position ───────────────────────────────────────────────────
    from app.crypto.models import CryptoTrade

    position = CryptoPosition.objects.create(
        symbol='TSLA',
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

    # ── On-chain OCO SL/TP ────────────────────────────────────────────────
    try:
        oco_result = place_oco_sltp('TSLA', is_buy, base_size, stop_loss, take_profit)
        if oco_result.get('error'):
            logger.warning("TSLA OCO failed: %s", oco_result['error'])
        else:
            logger.info("TSLA OCO placed: SL=%.2f TP=%.2f", stop_loss, take_profit)
    except Exception as e:
        logger.warning("TSLA OCO exception: %s", e)

    # ── Set cooldown ──────────────────────────────────────────────────────
    cache.set(TSLA_COOLDOWN_KEY, True, timeout=TSLA_COOLDOWN_SECONDS)

    logger.info("TSLA position opened: %s size=%.4f rsi=%.1f tx=%s",
                side, base_size, rsi_val, result.get('tx_hash', '?'))
