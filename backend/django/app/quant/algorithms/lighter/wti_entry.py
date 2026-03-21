"""
WTI War Volatility Entry Strategy for Lighter.xyz.

Trades WTI crude oil using geopolitical news signals from news_oil.py.
Regime-adaptive parameters: wide stops in war crisis, tight stops on ceasefire plays.

Signal source:
  get_oil_signal() → regime + direction (1=long, -1=short, 0=skip) + confidence

EMA(8/21) on 1h candles provides trend confirmation — news signal must align
with the current trend direction to enter. This prevents trading against momentum.

Regime parameter table:
  WAR_SUPPLY_CRISIS    → SL=2.5%, TP=5.0%  (wide — oil is volatile in wartime)
  CEASEFIRE_IMMINENT   → SL=1.0%, TP=1.5%  (tight — quick reversal plays)
  SUPPLY_TIGHT         → SL=1.5%, TP=3.0%  (standard)
  SUPPLY_EASING        → SL=1.5%, TP=3.0%  (standard)
  MIXED/NORMAL/NO_DATA → skip entirely

Max 1 WTI position at a time.
Cooldown: 30min after closing a WTI position (cache key 'lighter:wti_cooldown').
"""
import logging
from datetime import datetime, timezone

from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE, is_global_position_limit_reached
from .client import get_best_bid_ask, get_candles, place_market_order_usd, update_leverage, place_oco_sltp
from .sizing import calculate_position_usd
from .news_oil import get_oil_signal
from .orderbook_signal import get_ob_imbalance, get_trade_flow
from .vwap import get_vwap_bias

logger = logging.getLogger('app.lighter')

SYMBOL = 'WTI'
SIGNAL_PREFIX = 'lighter:wti_'
WTI_COOLDOWN_KEY = 'lighter:wti_cooldown'
WTI_COOLDOWN_SECONDS = 30 * 60  # 30 minutes

# Minimum confidence from news_oil to enter
MIN_CONFIDENCE = 0.3

# Minimum free collateral to trade
MIN_FREE_COLLATERAL = 8.0

# EMA parameters (1h candles)
EMA_FAST = 8
EMA_SLOW = 21
EMA_RESOLUTION = '1h'
EMA_CANDLE_COUNT = 60
CANDLE_CACHE_TTL = 300  # 5 min — 1h bars don't need fresher

# Regime → (sl_pct, tp_pct)
REGIME_PARAMS = {
    'WAR_SUPPLY_CRISIS':  (0.025, 0.050),
    'CEASEFIRE_IMMINENT': (0.010, 0.015),
    'SUPPLY_TIGHT':       (0.015, 0.030),
    'SUPPLY_EASING':      (0.015, 0.030),
}
# Regimes that trigger a skip
SKIP_REGIMES = frozenset({'MIXED', 'NORMAL', 'NO_DATA'})


# ── EMA helpers ───────────────────────────────────────────────────────────────

def _ema(closes: list, period: int) -> float:
    """Exponential moving average from a list of closes."""
    k = 2.0 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def _get_ema_direction(symbol: str) -> int:
    """Compute EMA(8/21) trend direction for WTI on 1h candles.

    Returns:
        +1 (fast above slow → bullish), -1 (fast below slow → bearish), 0 (no data)
    """
    cache_key = f'lighter:wti_candles:{symbol}'
    candles = cache.get(cache_key)
    if candles is None:
        try:
            candles = get_candles(symbol, resolution=EMA_RESOLUTION, count_back=EMA_CANDLE_COUNT)
        except Exception as e:
            logger.debug("WTI candle fetch failed: %s", e)
            return 0
        if candles and len(candles) >= EMA_SLOW + 5:
            cache.set(cache_key, candles, timeout=CANDLE_CACHE_TTL)

    if not candles or len(candles) < EMA_SLOW + 5:
        logger.debug("WTI: insufficient candles (%d)", len(candles) if candles else 0)
        return 0

    closes = [float(c['c']) for c in candles if c.get('c') is not None]
    if len(closes) < EMA_SLOW + 5:
        return 0

    ema_fast = _ema(closes, EMA_FAST)
    ema_slow = _ema(closes, EMA_SLOW)

    if ema_fast > ema_slow:
        return +1
    if ema_fast < ema_slow:
        return -1
    return 0


# ── Main entry ────────────────────────────────────────────────────────────────

def run_wti_entry():
    """WTI war volatility entries for Lighter.xyz. Called every 60s by Celery.

    Flow:
      1. Disabled / collateral guard
      2. Cooldown check
      3. Max 1 WTI position check
      4. Global position cap
      5. News signal (direction + confidence + regime)
      6. EMA trend confirmation (must align with news direction)
      7. Regime params → sizing → place order
    """
    if cache.get('lighter:disabled'):
        logger.debug("WTI: trading disabled via dashboard toggle")
        return

    collateral = cache.get('lighter:collateral')
    if collateral is not None and float(collateral) < MIN_FREE_COLLATERAL:
        logger.info("WTI: collateral $%.2f below minimum $%.2f, skipping",
                    float(collateral), MIN_FREE_COLLATERAL)
        return

    # ── Cooldown ──────────────────────────────────────────────────────────────
    if cache.get(WTI_COOLDOWN_KEY):
        logger.debug("WTI: in cooldown, skipping")
        return

    from app.crypto.models import CryptoPosition

    # ── Max 1 WTI position ────────────────────────────────────────────────────
    wti_open = CryptoPosition.objects.filter(symbol=SYMBOL, status='OPEN').count()
    if wti_open >= 1:
        logger.debug("WTI: position already open (%d), skipping", wti_open)
        return

    # ── Global cap ────────────────────────────────────────────────────────────
    if is_global_position_limit_reached():
        logger.debug("WTI: global position limit reached, skipping")
        return

    # ── News signal ───────────────────────────────────────────────────────────
    signal = get_oil_signal()
    direction = signal.get('direction', 0)
    confidence = signal.get('confidence', 0.0)
    regime = signal.get('regime', 'NO_DATA')
    reason = signal.get('reason', '')

    if direction == 0:
        logger.debug("WTI: no directional signal (regime=%s conf=%.2f — %s)",
                     regime, confidence, reason)
        return

    if confidence < MIN_CONFIDENCE:
        logger.debug("WTI: confidence %.2f below minimum %.2f (regime=%s), skipping",
                     confidence, MIN_CONFIDENCE, regime)
        return

    if regime in SKIP_REGIMES:
        logger.debug("WTI: regime %s → skip (reason: %s)", regime, reason)
        return

    if regime not in REGIME_PARAMS:
        logger.warning("WTI: unknown regime %s, skipping", regime)
        return

    sl_pct, tp_pct = REGIME_PARAMS[regime]

    # ── EMA trend confirmation ────────────────────────────────────────────────
    ema_direction = _get_ema_direction(SYMBOL)
    if ema_direction == 0:
        logger.info("WTI: no EMA data, skipping entry")
        return

    is_buy = direction > 0
    if is_buy and ema_direction < 0:
        logger.info("WTI: news says LONG but EMA is bearish — blocked (regime=%s conf=%.2f)",
                    regime, confidence)
        return
    if not is_buy and ema_direction > 0:
        logger.info("WTI: news says SHORT but EMA is bullish — blocked (regime=%s conf=%.2f)",
                    regime, confidence)
        return

    direction_str = 'BUY' if is_buy else 'SELL'
    side = 'LONG' if is_buy else 'SHORT'

    # ── Smart money confirmation (OB + trade flow + VWAP) ────────────
    confirmations = 0
    ob_imbalance = 0.5
    flow = {}
    vwap = {}

    try:
        ob_imbalance = get_ob_imbalance(SYMBOL)
        if is_buy and ob_imbalance > 0.55:
            confirmations += 1
        elif not is_buy and ob_imbalance < 0.45:
            confirmations += 1
        elif is_buy and ob_imbalance < 0.40:
            confirmations -= 1
        elif not is_buy and ob_imbalance > 0.60:
            confirmations -= 1
        logger.debug("WTI: OB imbalance=%.3f (%s)", ob_imbalance,
                     "aligned" if confirmations > 0 else "neutral" if confirmations == 0 else "opposed")
    except Exception as e:
        ob_imbalance = 0.5
        logger.debug("WTI: OB imbalance unavailable: %s", e)

    try:
        flow = get_trade_flow(SYMBOL)
        cvd = flow.get('cvd', 0)
        flow_signal = 1 if cvd > 0 else (-1 if cvd < 0 else 0)
        if (is_buy and flow_signal > 0) or (not is_buy and flow_signal < 0):
            confirmations += 1
        elif (is_buy and flow_signal < 0) or (not is_buy and flow_signal > 0):
            confirmations -= 1
        logger.debug("WTI: trade flow cvd=%.2f signal=%d (%s)", cvd, flow_signal,
                     "aligned" if flow_signal != 0 and ((is_buy and flow_signal > 0) or (not is_buy and flow_signal < 0)) else "neutral/opposed")
    except Exception as e:
        logger.debug("WTI: trade flow unavailable: %s", e)

    try:
        vwap = get_vwap_bias(SYMBOL)
        vwap_bias = vwap.get('bias', 'AT')
        if (is_buy and vwap_bias == 'ABOVE') or (not is_buy and vwap_bias == 'BELOW'):
            confirmations += 1
        elif (is_buy and vwap_bias == 'BELOW') or (not is_buy and vwap_bias == 'ABOVE'):
            confirmations -= 1
        logger.debug("WTI: VWAP bias=%s (confirmations=%d)", vwap_bias, confirmations)
    except Exception as e:
        logger.debug("WTI: VWAP unavailable: %s", e)

    if confirmations < 0:
        logger.info("WTI: smart money OPPOSED (confirmations=%d, ob=%.2f) — skipping %s",
                     confirmations, ob_imbalance, side)
        return

    logger.info("WTI: smart money confirmed=%d (ob=%.3f flow_cvd=%s vwap=%s)",
                confirmations, ob_imbalance,
                flow.get('cvd', '?'),
                vwap.get('bias', '?'))

    # ── Sizing ────────────────────────────────────────────────────────────────
    position_usd = calculate_position_usd(SYMBOL, sl_pct)
    meta = LIGHTER_MARKETS[SYMBOL]
    if position_usd < meta['min_quote']:
        logger.debug("WTI: position $%.2f below min $%.2f", position_usd, meta['min_quote'])
        return

    # ── Live price ────────────────────────────────────────────────────────────
    prices = get_best_bid_ask(SYMBOL)
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        logger.warning("WTI: no price data")
        return

    if is_buy:
        stop_loss = live_price * (1 - sl_pct)
        take_profit = live_price * (1 + tp_pct)
    else:
        stop_loss = live_price * (1 + sl_pct)
        take_profit = live_price * (1 - tp_pct)

    logger.info(
        "WTI ENTRY: %s $%.2f regime=%s conf=%.2f "
        "(price=%.3f SL=%.3f TP=%.3f sl_pct=%.1f%% tp_pct=%.1f%%)",
        side, position_usd, regime, confidence,
        live_price, stop_loss, take_profit,
        sl_pct * 100, tp_pct * 100,
    )

    # ── Set leverage ──────────────────────────────────────────────────────────
    try:
        update_leverage(SYMBOL, LIGHTER_LEVERAGE)
    except Exception:
        pass

    # ── Place market order ────────────────────────────────────────────────────
    result = place_market_order_usd(SYMBOL, is_buy, position_usd)
    if result.get('error'):
        logger.error("WTI: order failed: %s", result['error'])
        return

    base_size = position_usd / live_price
    signal_tag = f'{SIGNAL_PREFIX}{"long" if is_buy else "short"}_{regime.lower()}'

    # ── Record position ───────────────────────────────────────────────────────
    from app.crypto.models import CryptoTrade

    position = CryptoPosition.objects.create(
        symbol=SYMBOL,
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

    # ── On-chain OCO SL/TP ────────────────────────────────────────────────────
    try:
        oco_result = place_oco_sltp(SYMBOL, is_buy, base_size, stop_loss, take_profit)
        if oco_result.get('error'):
            logger.warning("WTI OCO failed: %s", oco_result['error'])
        else:
            logger.info("WTI OCO placed: SL=%.3f TP=%.3f", stop_loss, take_profit)
    except Exception as e:
        logger.warning("WTI OCO exception: %s", e)

    cache.set(WTI_COOLDOWN_KEY, True, timeout=WTI_COOLDOWN_SECONDS)

    logger.info("WTI position opened: %s size=%.4f regime=%s conf=%.2f tx=%s",
                side, base_size, regime, confidence, result.get('tx_hash', '?'))
