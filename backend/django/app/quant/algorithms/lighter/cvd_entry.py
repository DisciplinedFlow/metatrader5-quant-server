"""
Lighter.xyz CVD Divergence entry algorithm.

Reads active CVD strategies from the CustomStrategy DB (domain=CRYPTO,
strategy_type=CVD_DIVERGENCE) and fires entries when Binance CVD signals confirm.

Supported cvd_type values:
  lack_of_participants — price extreme ≠ CVD extreme (exhaustion)
  absorption           — CVD extreme ≠ price extreme (iceberg orders absorbing)
  real_time_leading    — same divergence logic as LoP, treated identically here
  extremes             — price at range boundary + CVD momentum disagrees
  multi_timeframe      — LoP confirmed on both 15m AND 1h (highest conviction)
  spot_vs_perpetual    — proxy for LoP (no separate spot feed)

Risk model: position_usd = RISK_PER_TRADE_USD / sl_pct
  → equalises dollar risk regardless of SL width
  → e.g. 2% SL + $2 risk = $100 notional, 3% SL = $67 notional

Positions are tagged 'lighter:cvd_{cvd_type}_{label}' so CVD has its own
capacity budget independent of EMA (lighter:) and RSI2 (lighter:rsi2_).

HTF Trend Filter (added Mar 19 2026):
  CVD divergence is a reversal/timing signal — it fires at every temporary
  exhaustion of momentum. Without a trend context gate it catches falling
  knives repeatedly during persistent trends (BTC 75k→70.5k, 7+ losing longs).
  Fix: only take CVD signals in the direction of the 1h EMA(8/21) trend.
  Counter-trend signals are blocked. Fail-open (trend unavailable → proceed).

XAU removed (Mar 19 2026):
  7.8% live WR on 64 trades. Root cause: Binance CVD uses PAXGUSDT as proxy
  for XAU — a gold-backed token with completely different volume dynamics than
  Lighter's spot-gold perpetual. Signal is effectively noise during gold ATH regime.
"""
import logging
from datetime import datetime, timezone

from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from .client import get_best_bid_ask, get_candles, place_market_order_usd, update_leverage, place_oco_sltp
from .sizing import calculate_position_usd
from .cvd_calculator import detect_divergence, detect_multitf_divergence, get_cvd_dataframe

logger = logging.getLogger('app.lighter')

PLATFORM_PREFIX = 'lighter:'
CVD_PREFIX = 'lighter:cvd_'

# Maximum simultaneous CVD positions
CVD_MAX_POSITIONS = 2

# Dollar risk per trade — controls notional via risk-normalised sizing.
# At 2.00 risk, 2% SL → $100 notional, $6.67 margin at 15x. 2 positions = $13.33 margin.
# Session multiplier (0.6-1.2x) further scales: Asian=$1.20 min, US overlap=$2.40 max.
RISK_PER_TRADE_USD = 2.00

# Minimum free collateral before any new CVD entry is attempted.
# With $29.47 account and 2 max positions ($13.33 margin), $5 is the safe floor.
MIN_FREE_COLLATERAL = 5.0

# Cooldown after a CVD trade on (symbol, cvd_type) to avoid re-entering same signal
CVD_COOLDOWN_SECONDS = 300  # 5 min

# CVD strategies use 15m candles; lookback window for divergence detection
CVD_LOOKBACK = 20

# ── HTF trend filter constants ────────────────────────────────────────────────
# Reuses momentum_entry's candle cache (lighter:mom_candles:{symbol}, 5-min TTL).
# If momentum ran first this cycle, the cache hit is free — zero extra API calls.
_TREND_EMA_FAST = 8
_TREND_EMA_SLOW = 21
_TREND_CANDLE_COUNT = 40    # 40h lookback — sufficient to warm both EMAs
_TREND_CACHE_TTL = 300      # 5 min — same TTL as momentum candle cache


# ── HTF trend filter ──────────────────────────────────────────────────────────

def _get_1h_trend(symbol: str) -> int:
    """Return +1 (uptrend), -1 (downtrend), or 0 (unavailable) from 1h EMA(8/21).

    Reuses the shared 'lighter:mom_candles:{symbol}' cache written by momentum_entry.
    On a cache miss, fetches fresh 1h candles and writes the cache itself.
    Fails open (returns 0) so a proxy outage never silently blocks all entries.
    """
    cache_key = f'lighter:mom_candles:{symbol}'
    candles = cache.get(cache_key)
    if candles is None:
        try:
            candles = get_candles(symbol, resolution='1h', count_back=_TREND_CANDLE_COUNT)
        except Exception as e:
            logger.debug("CVD trend filter: candle fetch failed for %s: %s", symbol, e)
            return 0  # fail-open
        if candles and len(candles) >= _TREND_EMA_SLOW + 5:
            cache.set(cache_key, candles, timeout=_TREND_CACHE_TTL)

    if not candles or len(candles) < _TREND_EMA_SLOW + 5:
        return 0  # fail-open

    closes = [float(c['c']) for c in candles if c.get('c') is not None]
    if len(closes) < _TREND_EMA_SLOW + 5:
        return 0

    k_fast = 2.0 / (_TREND_EMA_FAST + 1)
    k_slow = 2.0 / (_TREND_EMA_SLOW + 1)
    ema_fast = ema_slow = closes[0]
    for p in closes[1:]:
        ema_fast = p * k_fast + ema_fast * (1 - k_fast)
        ema_slow = p * k_slow + ema_slow * (1 - k_slow)

    if ema_fast > ema_slow:
        return +1
    if ema_fast < ema_slow:
        return -1
    return 0


# ── Active strategy loader ────────────────────────────────────────────────

def _load_active_cvd_strategies():
    """Return active CustomStrategy records for CRYPTO CVD_DIVERGENCE.

    Uses ALL Lighter crypto pairs that have Binance CVD data — not just the 4
    in the DB definition field. The DB definition is used for signal type and
    exit params only.
    """
    # OB-covered pairs only (ws_streamer: BTC/ETH/SOL/XAU).
    # XAU removed Mar 19: 7.8% live WR on 64 trades. Root cause: Binance CVD uses
    # PAXGUSDT proxy (gold-backed token) whose volume dynamics differ entirely from
    # Lighter's XAU perpetual. Signal is noise during the current gold ATH regime.
    # BTC/ETH removed: outsized losses tank the account
    all_pairs = ['SOL']

    try:
        from app.nexus.models import CustomStrategy
        strategies = CustomStrategy.objects.filter(
            domain='CRYPTO',
            strategy_config__is_active=True,
        ).select_related('strategy_config')

        result = []
        for s in strategies:
            defn = s.definition or {}
            if defn.get('strategy_type') != 'CVD_DIVERGENCE':
                continue
            cvd_type = defn.get('cvd_type', '')
            if not cvd_type or cvd_type in ('pattern_training', 'overlay', 'yes_vs_no'):
                continue  # non-executable strategy types
            exit_rules = defn.get('exit_rules', {})
            params = exit_rules.get('params', {})
            sl_pct = params.get('stop_loss_pct')
            tp_pct = params.get('take_profit_pct')
            if sl_pct and tp_pct:
                result.append({
                    'id': s.id,
                    'name': s.name,
                    'cvd_type': cvd_type,
                    'sl_pct': float(sl_pct),
                    'tp_pct': float(tp_pct),
                    'pairs': all_pairs,  # all 17 Lighter crypto pairs with Binance CVD
                })
        return result
    except Exception as e:
        logger.error("CVD: failed to load strategies from DB: %s", e)
        return []


# ── Cooldown helpers ──────────────────────────────────────────────────────

def _check_cooldown(symbol, cvd_type):
    return not cache.get(f'lighter:cvd_cooldown:{cvd_type}:{symbol}')


def _set_cooldown(symbol, cvd_type):
    cache.set(f'lighter:cvd_cooldown:{cvd_type}:{symbol}', True, timeout=CVD_COOLDOWN_SECONDS)


# ── Main entry function ───────────────────────────────────────────────────

def cvd_entry_algorithm():
    """CVD divergence entry for Lighter.xyz. Called every 60s by Celery.

    Flow:
      1. Load active CVD strategies from DB
      2. Check global CVD position budget
      3. For each (strategy × symbol): compute Binance CVD signal
      4. If signal: risk-normalised size → market order → OCO SL/TP
    """
    if cache.get('lighter:disabled'):
        logger.debug("CVD: trading disabled via dashboard toggle")
        return

    # Balance guard — read cached collateral from reconcile (no extra API call)
    collateral = cache.get('lighter:collateral')
    if collateral is not None and float(collateral) < MIN_FREE_COLLATERAL:
        logger.info("CVD: collateral $%.2f below minimum $%.2f, skipping entries",
                    float(collateral), MIN_FREE_COLLATERAL)
        return

    strategies = _load_active_cvd_strategies()
    if not strategies:
        logger.debug("CVD: no active CVD strategies in DB")
        return

    from app.crypto.models import CryptoPosition, CryptoTrade

    # Count open CVD positions (own budget — doesn't block EMA/RSI2)
    cvd_open = CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=CVD_PREFIX,
    ).count()

    if cvd_open >= CVD_MAX_POSITIONS:
        logger.debug("CVD: max positions reached (%d/%d)", cvd_open, CVD_MAX_POSITIONS)
        return

    # Build set of symbols with any open Lighter position (avoid doubling up)
    open_symbols = set(
        CryptoPosition.objects.filter(
            status='OPEN',
            entry_signal__startswith=PLATFORM_PREFIX,
        ).values_list('symbol', flat=True)
    )

    hour_utc = datetime.now(timezone.utc).hour

    for strategy in strategies:
        if cvd_open >= CVD_MAX_POSITIONS:
            break

        cvd_type = strategy['cvd_type']
        sl_pct = strategy['sl_pct']
        tp_pct = strategy['tp_pct']

        for symbol in strategy['pairs']:
            if cvd_open >= CVD_MAX_POSITIONS:
                break
            if symbol in open_symbols:
                continue
            if cache.get(f'lighter:vanish_cooldown:{symbol}'):
                continue
            if not _check_cooldown(symbol, cvd_type):
                continue
            if LIGHTER_MARKETS.get(symbol) is None:
                continue

            try:
                opened = _scan_symbol(
                    symbol=symbol,
                    cvd_type=cvd_type,
                    sl_pct=sl_pct,
                    tp_pct=tp_pct,
                    strategy_name=strategy['name'],
                    hour_utc=hour_utc,
                )
                if opened:
                    cvd_open += 1
                    open_symbols.add(symbol)
            except Exception as e:
                logger.error("CVD entry error for %s (%s): %s", symbol, cvd_type, e)


def _scan_symbol(symbol, cvd_type, sl_pct, tp_pct, strategy_name, hour_utc):
    """Detect CVD divergence on one symbol and enter if confirmed.

    Returns True if a position was opened.
    """
    from app.crypto.models import CryptoPosition, CryptoTrade

    # ── Detect signal ──────────────────────────────────────────────────
    if cvd_type == 'multi_timeframe':
        signal, label = detect_multitf_divergence(symbol, lookback=CVD_LOOKBACK)
    else:
        df = get_cvd_dataframe(symbol, interval='15m', limit=60)
        if df is None:
            return False
        signal, label = detect_divergence(df, cvd_type, lookback=CVD_LOOKBACK)

    if signal == 0:
        logger.debug("CVD %s %s: no signal", cvd_type, symbol)
        return False

    # ── HTF trend filter ───────────────────────────────────────────────
    # Block CVD signals that go against the 1h EMA(8/21) trend direction.
    # CVD divergence fires on every temporary momentum stall — in a sustained
    # trend these are just lower-probability bounces, not real reversals.
    # Fail-open: if trend unavailable (proxy down, cold cache) we proceed.
    trend = _get_1h_trend(symbol)
    if trend != 0:
        if signal > 0 and trend < 0:
            logger.info("CVD %s %s: trend filter blocked LONG (EMA downtrend, 1h EMA8 < EMA21)",
                        cvd_type, symbol)
            return False
        if signal < 0 and trend > 0:
            logger.info("CVD %s %s: trend filter blocked SHORT (EMA uptrend, 1h EMA8 > EMA21)",
                        cvd_type, symbol)
            return False
    logger.debug("CVD %s %s: trend=%+d — signal direction confirmed", cvd_type, symbol, trend)

    # ── OB imbalance gate (fail-open: 0.5 neutral means proceed) ──────
    # ws_streamer provides live DOM for BTC/ETH/SOL/XAU. Block entries
    # when the order book strongly opposes the CVD signal direction.
    try:
        from .orderbook_signal import get_ob_imbalance
        imbalance = get_ob_imbalance(symbol)
        is_buy_signal = signal > 0
        if is_buy_signal and imbalance < 0.35:
            logger.info("CVD %s %s: OB blocked BUY (imbalance=%.2f, ask-heavy DOM)",
                        cvd_type, symbol, imbalance)
            return False
        if not is_buy_signal and imbalance > 0.65:
            logger.info("CVD %s %s: OB blocked SELL (imbalance=%.2f, bid-heavy DOM)",
                        cvd_type, symbol, imbalance)
            return False
        logger.debug("CVD %s %s: OB imbalance=%.2f — %s unblocked",
                     cvd_type, symbol, imbalance, 'BUY' if is_buy_signal else 'SELL')
    except Exception as e:
        logger.debug("CVD OB gate unavailable for %s: %s", symbol, e)

    # ── Risk-normalised sizing ─────────────────────────────────────────
    position_usd = calculate_position_usd(symbol, sl_pct, risk_per_trade=RISK_PER_TRADE_USD)

    meta = LIGHTER_MARKETS[symbol]
    if position_usd < meta['min_quote']:
        logger.debug("CVD %s %s: position $%.2f below min $%.2f",
                     cvd_type, symbol, position_usd, meta['min_quote'])
        return False

    # ── Fetch live price ───────────────────────────────────────────────
    prices = get_best_bid_ask(symbol)
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        logger.warning("CVD %s %s: no price data", cvd_type, symbol)
        return False

    is_buy = signal > 0
    side = 'LONG' if is_buy else 'SHORT'
    direction_str = 'BUY' if is_buy else 'SELL'

    if is_buy:
        stop_loss = live_price * (1 - sl_pct)
        take_profit = live_price * (1 + tp_pct)
    else:
        stop_loss = live_price * (1 + sl_pct)
        take_profit = live_price * (1 - tp_pct)

    logger.info(
        "CVD ENTRY: %s %s $%.2f (price=%.4f SL=%.4f TP=%.4f type=%s label=%s)",
        symbol, side, position_usd, live_price, stop_loss, take_profit,
        cvd_type, label,
    )

    # ── Set leverage ───────────────────────────────────────────────────
    try:
        update_leverage(symbol, LIGHTER_LEVERAGE)
    except Exception:
        pass

    # ── Place market order ─────────────────────────────────────────────
    result = place_market_order_usd(symbol, is_buy, position_usd)
    if result.get('error'):
        logger.error("CVD %s %s: order failed: %s", cvd_type, symbol, result['error'])
        return False

    base_size = position_usd / live_price
    signal_tag = f'{CVD_PREFIX}{cvd_type}_{label}'

    # ── Record position ────────────────────────────────────────────────
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

    # ── Native on-chain OCO SL/TP ──────────────────────────────────────
    try:
        oco_result = place_oco_sltp(symbol, is_buy, base_size, stop_loss, take_profit)
        if oco_result.get('error'):
            logger.warning("CVD OCO failed for %s: %s", symbol, oco_result['error'])
        else:
            logger.info("CVD OCO placed: %s SL=%.4f TP=%.4f tx=%s",
                        symbol, stop_loss, take_profit, oco_result.get('tx_hash', '?'))
    except Exception as e:
        logger.warning("CVD OCO exception for %s: %s", symbol, e)

    _set_cooldown(symbol, cvd_type)

    logger.info("CVD position opened: %s %s size=%.6f strategy=%s tx=%s",
                symbol, side, base_size, strategy_name, result.get('tx_hash', '?'))
    return True
