"""
Lighter.xyz EMA Momentum entry strategy.

Complements CVD divergence (reversal entries) by trading established trends:
EMA(8/21) cross direction on 1h candles, confirmed by order book imbalance
when available, and recent candle momentum.

Why this fills the gap:
  CVD divergence fires at turning points — it's silent during trending markets.
  EMA momentum fires DURING the trend — it catches the bulk of directional moves.
  Together they cover both regimes: CVD at reversals, momentum on continuations.

Pairs:
  OB-confirmed  (BTC, ETH, SOL, XAU): require OB imbalance in trade direction
  Non-OB        (AVAX, DOGE):         require stronger EMA separation as compensation

Rate limiting:
  Candles are cached 5min per symbol (1 Lighter API call per 5min per pair).
  Prices use the shared 'lighter:price:{symbol}' cache (20s TTL, shared with exit/cvd).
  6 pairs × 1 candle call per 5min = 1.2 candle calls/min. Negligible.

Risk model: RISK_PER_TRADE_USD / sl_pct — same as CVD, risk-normalised sizing.
Signal prefix: 'lighter:mom_' — own position budget, independent of CVD and RSI2.
"""
import logging
from datetime import datetime, timezone

from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from .client import get_best_bid_ask, get_candles, place_market_order_usd, update_leverage, place_oco_sltp
from .sizing import calculate_position_usd

logger = logging.getLogger('app.lighter')

MOM_PREFIX = 'lighter:mom_'
PLATFORM_PREFIX = 'lighter:'

# ── Position budget ──────────────────────────────────────────────────────
MOM_MAX_POSITIONS = 3       # Own budget — doesn't block CVD or RSI2

# ── Risk sizing ──────────────────────────────────────────────────────────
# Risk per trade: dynamic 20% of live balance (see sizing.py).
MIN_FREE_COLLATERAL = 8.0   # Skip entries if collateral below this

# ── Cooldown: prevent churning in and out of same symbol ─────────────────
MOM_COOLDOWN_SECONDS = 4 * 3600   # 4h per symbol

# ── EMA parameters ───────────────────────────────────────────────────────
EMA_FAST = 8
EMA_SLOW = 21
EMA_RESOLUTION = '1h'
EMA_CANDLE_COUNT = 60           # 60h lookback — enough for warm EMA
CANDLE_CACHE_TTL = 300          # 5min candle cache (1h bars don't need fresher)

# Minimum EMA spread to avoid trading choppy/sideways markets.
# OB pairs get a lower threshold because DOM data provides extra confirmation.
# BTC/ETH removed: outsized losses tank the account
OB_PAIRS = frozenset(['XAU'])  # SOL removed: 50% WR, net negative PnL
EMA_MIN_SEP_OB = 0.003          # 0.3% spread for OB-confirmed pairs
EMA_MIN_SEP_NOB = 0.005         # 0.5% spread for non-OB pairs (higher bar)

# OB imbalance thresholds for OB pairs (same convention as cvd_entry / entry_crypto)
OB_LONG_MIN = 0.55    # bids must dominate ≥55% for a long entry
OB_SHORT_MAX = 0.45   # bids must be ≤45% (asks dominate) for a short entry

# ── SL/TP by asset class ─────────────────────────────────────────────────
METALS = frozenset(['XAU', 'XAG', 'PAXG', 'WTI'])
SL_PCT = {True: 0.015, False: 0.020}   # metals: 1.5%, crypto: 2%
TP_PCT = {True: 0.030, False: 0.040}   # metals: 3%,   crypto: 4%

# ── Pairs to scan ────────────────────────────────────────────────────────
# Keep to 6 to stay well within CloudFront rate limits.
# OB pairs first — they get both EMA + DOM confirmation (highest conviction).
# BTC/ETH removed: outsized losses tank the account
MOM_PAIRS = ['XAU', 'XAG']  # Commodities only — war economy focus


# ── EMA calculation ───────────────────────────────────────────────────────

def _ema(closes: list, period: int) -> float:
    """Exponential moving average from a list of closes."""
    k = 2.0 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def _get_ema_signal(symbol: str) -> tuple:
    """Compute EMA(8/21) cross signal for symbol.

    Returns:
        (signal, sep_pct) where signal is +1 (long), -1 (short), or 0 (no signal),
        and sep_pct is the EMA spread as a fraction.
    """
    cache_key = f'lighter:mom_candles:{symbol}'
    candles = cache.get(cache_key)
    if candles is None:
        try:
            candles = get_candles(symbol, resolution=EMA_RESOLUTION, count_back=EMA_CANDLE_COUNT)
        except Exception as e:
            logger.debug("MOM candle fetch failed for %s: %s", symbol, e)
            return 0, 0.0
        if candles and len(candles) >= EMA_SLOW + 5:
            cache.set(cache_key, candles, timeout=CANDLE_CACHE_TTL)

    if not candles or len(candles) < EMA_SLOW + 5:
        logger.debug("MOM %s: insufficient candles (%d)", symbol, len(candles) if candles else 0)
        return 0, 0.0

    closes = [float(c['c']) for c in candles if c.get('c') is not None]
    if len(closes) < EMA_SLOW + 5:
        return 0, 0.0

    ema_fast = _ema(closes, EMA_FAST)
    ema_slow = _ema(closes, EMA_SLOW)
    # Previous bar's EMA for slope direction
    ema_fast_prev = _ema(closes[:-1], EMA_FAST)

    sep_pct = abs(ema_fast - ema_slow) / ema_slow if ema_slow else 0.0

    # Recent momentum: count up/down moves among last 3 candle pairs
    recent = closes[-5:]
    up_moves = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
    dn_moves = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])

    bullish = (
        ema_fast > ema_slow           # fast above slow
        and ema_fast > ema_fast_prev  # EMA still rising
        and up_moves >= 3             # at least 3 of last 4 bars green
    )
    bearish = (
        ema_fast < ema_slow
        and ema_fast < ema_fast_prev  # EMA still falling
        and dn_moves >= 3             # at least 3 of last 4 bars red
    )

    if bullish:
        return +1, sep_pct
    if bearish:
        return -1, sep_pct
    return 0, sep_pct


# ── Cooldown helpers ──────────────────────────────────────────────────────

def _check_cooldown(symbol: str) -> bool:
    return not cache.get(f'lighter:mom_cooldown:{symbol}')


def _set_cooldown(symbol: str):
    cache.set(f'lighter:mom_cooldown:{symbol}', True, timeout=MOM_COOLDOWN_SECONDS)


# ── Main entry ────────────────────────────────────────────────────────────

def momentum_entry_algorithm():
    """EMA momentum entries for Lighter.xyz. Called every 60s by Celery.

    Flow:
      1. Collateral guard (cached from reconcile)
      2. Budget check (MOM_MAX_POSITIONS)
      3. For each pair: EMA signal → OB confirmation → size → place order
    """
    if cache.get('lighter:disabled'):
        logger.debug("MOM: trading disabled via dashboard toggle")
        return

    collateral = cache.get('lighter:collateral')
    if collateral is not None and float(collateral) < MIN_FREE_COLLATERAL:
        logger.info("MOM: collateral $%.2f below minimum $%.2f, skipping",
                    float(collateral), MIN_FREE_COLLATERAL)
        return

    from app.crypto.models import CryptoPosition

    mom_open = CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=MOM_PREFIX,
    ).count()

    if mom_open >= MOM_MAX_POSITIONS:
        logger.debug("MOM: max positions reached (%d/%d)", mom_open, MOM_MAX_POSITIONS)
        return

    # Global cap — enforces exchange OCO slot limit (2 positions × SL+TP = 4 orders max)
    from .config import is_global_position_limit_reached
    if is_global_position_limit_reached():
        logger.debug("MOM: global position limit reached, skipping")
        return

    # Block symbols that already have any open Lighter position
    open_symbols = set(
        CryptoPosition.objects.filter(
            status='OPEN',
            entry_signal__startswith=PLATFORM_PREFIX,
        ).values_list('symbol', flat=True)
    )

    hour_utc = datetime.now(timezone.utc).hour

    for symbol in MOM_PAIRS:
        if mom_open >= MOM_MAX_POSITIONS:
            break
        if symbol in open_symbols:
            continue
        if cache.get(f'lighter:vanish_cooldown:{symbol}'):
            continue
        if LIGHTER_MARKETS.get(symbol) is None:
            continue
        if not _check_cooldown(symbol):
            continue

        try:
            opened = _scan_symbol(symbol, hour_utc)
            if opened:
                mom_open += 1
                open_symbols.add(symbol)
        except Exception as e:
            logger.error("MOM entry error for %s: %s", symbol, e)


def _scan_symbol(symbol: str, hour_utc: int) -> bool:
    """Evaluate EMA momentum signal for one symbol and enter if confirmed.

    Returns True if a position was opened.
    """
    from app.crypto.models import CryptoPosition, CryptoTrade

    # ── EMA signal ─────────────────────────────────────────────────────
    signal, sep_pct = _get_ema_signal(symbol)
    if signal == 0:
        logger.debug("MOM %s: no EMA signal (sep=%.3f%%)", symbol, sep_pct * 100)
        return False

    is_ob_pair = symbol in OB_PAIRS
    min_sep = EMA_MIN_SEP_OB if is_ob_pair else EMA_MIN_SEP_NOB
    if sep_pct < min_sep:
        logger.debug("MOM %s: EMA spread %.3f%% < min %.3f%% (choppy market, skip)",
                     symbol, sep_pct * 100, min_sep * 100)
        return False

    is_buy = signal > 0
    direction_str = 'BUY' if is_buy else 'SELL'

    # ── OB imbalance gate (required for OB pairs, advisory for others) ──
    try:
        from .orderbook_signal import get_ob_imbalance
        imbalance = get_ob_imbalance(symbol)
        if is_ob_pair:
            # Hard block: DOM must confirm direction
            if is_buy and imbalance < OB_LONG_MIN:
                logger.info("MOM %s: OB blocked LONG (imbalance=%.2f < %.2f)",
                            symbol, imbalance, OB_LONG_MIN)
                return False
            if not is_buy and imbalance > OB_SHORT_MAX:
                logger.info("MOM %s: OB blocked SHORT (imbalance=%.2f > %.2f)",
                            symbol, imbalance, OB_SHORT_MAX)
                return False
        else:
            # For non-OB pairs, a strongly opposing DOM is still a block
            if is_buy and imbalance < 0.35:
                logger.info("MOM %s: OB strongly opposed LONG (imbalance=%.2f), skip",
                            symbol, imbalance)
                return False
            if not is_buy and imbalance > 0.65:
                logger.info("MOM %s: OB strongly opposed SHORT (imbalance=%.2f), skip",
                            symbol, imbalance)
                return False
        logger.debug("MOM %s: OB imbalance=%.2f OK for %s", symbol, imbalance, direction_str)
    except Exception as e:
        logger.debug("MOM OB gate unavailable for %s: %s", symbol, e)

    # ── Risk-normalised sizing ─────────────────────────────────────────
    is_metal = symbol in METALS
    sl_pct = SL_PCT[is_metal]
    tp_pct = TP_PCT[is_metal]

    # News removed — permanently EXTREME, irrelevant for crypto
    position_usd = calculate_position_usd(symbol, sl_pct)

    meta = LIGHTER_MARKETS[symbol]
    if position_usd < meta['min_quote']:
        logger.debug("MOM %s: position $%.2f below min $%.2f",
                     symbol, position_usd, meta['min_quote'])
        return False

    # ── Live price ────────────────────────────────────────────────────
    prices = get_best_bid_ask(symbol)
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        logger.warning("MOM %s: no price data", symbol)
        return False

    side = 'LONG' if is_buy else 'SHORT'
    if is_buy:
        stop_loss = live_price * (1 - sl_pct)
        take_profit = live_price * (1 + tp_pct)
    else:
        stop_loss = live_price * (1 + sl_pct)
        take_profit = live_price * (1 - tp_pct)

    logger.info(
        "MOM ENTRY: %s %s $%.2f (price=%.4f SL=%.4f TP=%.4f "
        "ema_sep=%.2f%% ob=%s)",
        symbol, side, position_usd, live_price, stop_loss, take_profit,
        sep_pct * 100, 'OB' if is_ob_pair else 'NO_OB',
    )

    # ── Set leverage ──────────────────────────────────────────────────
    try:
        update_leverage(symbol, LIGHTER_LEVERAGE)
    except Exception:
        pass

    # ── Place market order ────────────────────────────────────────────
    result = place_market_order_usd(symbol, is_buy, position_usd)
    if result.get('error'):
        logger.error("MOM %s: order failed: %s", symbol, result['error'])
        return False

    base_size = position_usd / live_price
    signal_tag = f'{MOM_PREFIX}ema_{"bull" if is_buy else "bear"}'

    # ── Record position ───────────────────────────────────────────────
    position = CryptoPosition.objects.create(
        symbol=symbol,
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

    # ── On-chain OCO SL/TP (initial backstop — exit.py trails from here) ──
    try:
        oco_result = place_oco_sltp(symbol, is_buy, base_size, stop_loss, take_profit)
        if oco_result.get('error'):
            logger.warning("MOM OCO failed for %s: %s", symbol, oco_result['error'])
        else:
            logger.info("MOM OCO placed: %s SL=%.4f TP=%.4f",
                        symbol, stop_loss, take_profit)
    except Exception as e:
        logger.warning("MOM OCO exception for %s: %s", symbol, e)

    _set_cooldown(symbol)

    logger.info("MOM position opened: %s %s size=%.6f ema_sep=%.2f%% tx=%s",
                symbol, side, base_size, sep_pct * 100, result.get('tx_hash', '?'))
    return True
