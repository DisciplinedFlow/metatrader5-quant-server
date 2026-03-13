"""
Generic CVD strategy live entry algorithm.

Reads the active CustomStrategy definition from the database and executes
live trades via MT5 when CVD divergence signals fire. Uses the same indicator
registry and condition operators as GenericBacktester for signal parity.

Adaptive Trading Intelligence layers (applied before order placement):
1. High-Impact Event Guard — blocks entries around NFP, FOMC, CPI, etc.
2. Circuit Breaker — pauses entries after consecutive losses
3. Symbol Performance Filter — skips symbols with poor recent win rates
4. Market Context Gate — macro news blocks + regime sizing (merged layer)
5. Group Tendency — cross-pair correlation check (Livermore's group rule)
6. ML Meta-Filter — accepts/rejects based on predicted win probability
7. Dynamic Position Sizing — vol-targeting + streak + symbol WR + regime + group
"""

import pandas as pd
import logging
import traceback
from datetime import timedelta

from app.utils.arithmetics import (
    calculate_order_size_usd,
    calculate_commission,
    get_price_at_pnl,
    get_pnl_at_price,
    convert_usd_to_lots,
    get_symbol_contract_info,
)
from app.utils.constants import MT5Timeframe
from app.utils.api.data import fetch_data_pos, symbol_info_tick
from app.utils.api.order import send_market_order
from app.utils.account import have_open_positions_in_symbol
from app.utils.market import is_market_open
from app.utils.api.positions import get_positions
from app.utils.db.create import create_trade
from app.quant.indicators.scalping import atr
from app.quant.backtester_generic import INDICATOR_REGISTRY, CONDITION_OPS
from app.quant.algorithms.cvd.config import (
    LEVERAGE,
    CAPITAL_PER_TRADE,
    MAX_LOT_SIZE,
    DEVIATION,
    MAX_OPEN_TRADES,
    ATR_PERIOD,
    SL_ATR_MULTIPLIER,
    TP_ATR_MULTIPLIER,
    ENERGY_SYMBOLS,
    NG_SYMBOLS,
    ENERGY_RISK_CONFIG,
)

logger = logging.getLogger(__name__)

# --- Adaptive Trading Thresholds ---
CIRCUIT_BREAKER_SYMBOL_LOSSES = 3    # Consecutive losses on same symbol → pause
CIRCUIT_BREAKER_GLOBAL_LOSSES = 5    # Consecutive losses across all symbols → pause
CIRCUIT_BREAKER_COOLDOWN_HOURS = 1   # How long to pause after circuit breaker trips
SYMBOL_FILTER_LOOKBACK = 10          # Trades to check for symbol performance
SYMBOL_FILTER_MIN_WR = 0.25          # Minimum win rate to continue trading a symbol
SYMBOL_FILTER_COOLDOWN_HOURS = 2     # How long to skip a poorly-performing symbol

# --- TRAINING MODE: full throttle, all filters bypassed ---
# Bypasses: trading session, high-impact events, circuit breakers,
# strategy router regime gate, correlation group limit, symbol filter,
# market context gate, ML meta-filter, confluence gates.
# Only hard guards remain: market closed, no tick data, insufficient bars.
# Set to False to re-enable all protection gates for live trading.
TRAINING_MODE = True
REGIME_MISMATCH_SIZE_PENALTY = 0.50  # Halve position when regime doesn't match strategy
GROUP_TENDENCY_SIZE_PENALTY = 0.50   # Halve position when peer pairs disagree with direction
GROUP_TENDENCY_CACHE_TTL = 300       # Cache correlation check for 5 minutes

# --- Hard Loss Ceiling (matches position_manager.MAX_LOSS_PER_TRADE_USD) ---
MAX_LOSS_PER_TRADE = 50.0            # Broker SL placed here — no software timing gaps

# --- Livermore Scale-In ("feeling-out bet") ---
INITIAL_SIZE_FRACTION = 0.60  # Enter at 60%, add remaining 40% on confirmation

# --- Cross-Pair Correlation (Livermore's "Group Tendency") ---
# Pairs/instruments that move together based on shared dynamics.
# USD_WEAKNESS pairs go UP when USD weakens; USD_STRENGTH pairs go UP when USD strengthens.
# METALS correlate (gold/silver); ENERGY instruments trade independently for now.
PAIR_CORRELATION_MAP = {
    # Forex — USD dynamics
    'EURUSD':   {'group': 'USD_WEAKNESS',  'check_peers': ['GBPUSD', 'AUDUSD']},
    'GBPUSD':   {'group': 'USD_WEAKNESS',  'check_peers': ['EURUSD', 'AUDUSD']},
    'AUDUSD':   {'group': 'USD_WEAKNESS',  'check_peers': ['EURUSD', 'GBPUSD']},
    'NZDUSD':   {'group': 'USD_WEAKNESS',  'check_peers': ['AUDUSD', 'EURUSD']},
    'USDJPY':   {'group': 'USD_STRENGTH',  'check_peers': ['USDCHF', 'USDCAD']},
    'USDCHF':   {'group': 'USD_STRENGTH',  'check_peers': ['USDJPY', 'USDCAD']},
    'USDCAD':   {'group': 'USD_STRENGTH',  'check_peers': ['USDJPY', 'USDCHF']},
    # Metals — gold/silver correlate strongly
    'XAUUSD':   {'group': 'METALS',        'check_peers': ['XAGUSD']},
    'XAGUSD':   {'group': 'METALS',        'check_peers': ['XAUUSD']},
    'XAUEUR':   {'group': 'METALS',        'check_peers': ['XAUUSD']},
    'XAUJPY':   {'group': 'METALS',        'check_peers': ['XAUUSD']},
    'XAUAUD':   {'group': 'METALS',        'check_peers': ['XAUUSD']},
    # Energy — oil pairs are highly correlated (0.95+), NG is independent
    'NG-C':     {'group': None,             'check_peers': []},
    'UKOUSDft': {'group': 'ENERGY_OIL',     'check_peers': ['USOUSD']},
    'USOUSD':   {'group': 'ENERGY_OIL',     'check_peers': ['UKOUSDft']},
}

# Symbols that are NOT forex — used to tag trades with the correct market_type.
# Everything else defaults to 'FOREX' (the MT5 broker's primary market).
_COMMODITY_SYMBOLS = frozenset(
    k for k, v in PAIR_CORRELATION_MAP.items()
    if v.get('group') in ('METALS', 'ENERGY') or k in ('NG-C',)
)


def _get_market_type(symbol):
    """Return 'FOREX' or 'OTHER' based on the symbol for Trade.market_type."""
    if symbol in _COMMODITY_SYMBOLS:
        return 'OTHER'
    return 'FOREX'


def _get_energy_overrides(symbol):
    """Return energy-specific risk parameter overrides for a symbol.

    When a symbol is in ENERGY_SYMBOLS, returns a dict with overridden
    CAPITAL_PER_TRADE, SL/TP multipliers, and a volatility regime sizing
    multiplier based on current ATR conditions.

    Returns None for non-energy symbols (use default params).
    """
    if symbol not in ENERGY_SYMBOLS:
        return None

    overrides = {
        'capital_per_trade': ENERGY_RISK_CONFIG['CAPITAL_PER_TRADE'],
        'sl_atr_multiplier': ENERGY_RISK_CONFIG['SL_ATR_MULTIPLIER'],
        'tp_atr_multiplier': ENERGY_RISK_CONFIG['TP_ATR_MULTIPLIER'],
        'vol_regime_mult': 1.0,
    }

    # Check ATR-based volatility regime for energy-specific sizing
    try:
        from app.quant.indicators.energy import energy_volatility_regime
        df = fetch_data_pos(symbol, MT5Timeframe.H4, 100)
        if df is not None and len(df) >= 55:
            regime = energy_volatility_regime(df)
            if regime == 'crisis':
                overrides['vol_regime_mult'] = 0.0  # No new positions
                logger.warning(
                    f"ENERGY RISK: {symbol} in CRISIS volatility regime — "
                    f"blocking new entries (ATR > 3.5x average)"
                )
            elif regime == 'high':
                overrides['vol_regime_mult'] = ENERGY_RISK_CONFIG['CRISIS_SIZE_MULT']
                logger.info(
                    f"ENERGY RISK: {symbol} in HIGH volatility — "
                    f"sizing at {ENERGY_RISK_CONFIG['CRISIS_SIZE_MULT']:.0%}"
                )
            elif regime == 'elevated':
                overrides['vol_regime_mult'] = ENERGY_RISK_CONFIG['HIGH_VOL_SIZE_MULT']
                logger.info(
                    f"ENERGY RISK: {symbol} in ELEVATED volatility — "
                    f"sizing at {ENERGY_RISK_CONFIG['HIGH_VOL_SIZE_MULT']:.0%}"
                )
            else:
                logger.debug(f"ENERGY RISK: {symbol} regime={regime}, normal sizing")
    except Exception as e:
        logger.debug(f"Energy volatility regime check failed for {symbol}: {e}")

    # Check energy session filter
    try:
        from app.quant.indicators.energy import energy_session_filter
        if df is not None and len(df) > 0:
            session = energy_session_filter(df)
            if session == 'dead_zone':
                overrides['vol_regime_mult'] = 0.0
                logger.info(
                    f"ENERGY RISK: {symbol} in dead zone session (21:00-01:59 UTC) — "
                    f"blocking new entries"
                )
            elif session == 'asian':
                overrides['vol_regime_mult'] *= 0.5
                logger.info(
                    f"ENERGY RISK: {symbol} in Asian session — halving size"
                )
    except Exception as e:
        logger.debug(f"Energy session check failed for {symbol}: {e}")

    # NG seasonal awareness
    if symbol in NG_SYMBOLS:
        try:
            from app.quant.indicators.energy import ng_seasonal_filter
            if df is not None and len(df) > 0:
                seasonal = ng_seasonal_filter(df)
                if seasonal == 'bearish':
                    overrides['vol_regime_mult'] *= 0.5
                    logger.info(
                        f"ENERGY RISK: {symbol} in BEARISH seasonal window — "
                        f"halving size (injection season)"
                    )
                elif seasonal == 'strong_bullish':
                    logger.info(
                        f"ENERGY RISK: {symbol} in STRONG BULLISH seasonal window — "
                        f"September rally, full size"
                    )
        except Exception as e:
            logger.debug(f"NG seasonal check failed for {symbol}: {e}")

    return overrides


def _check_energy_position_limits(symbol):
    """Check energy-specific position limits.

    Oil: Max 2 positions total across WTI+Brent (0.95 correlation).
    NG: Max 1 position (independent but very volatile).

    Returns (allowed: bool, reason: str).
    """
    if symbol not in ENERGY_SYMBOLS:
        return True, "Not energy — no limit"

    try:
        positions = get_positions()
        if positions is None or positions.empty:
            return True, "No open positions"

        open_symbols = positions['symbol'].tolist() if 'symbol' in positions.columns else []

        if symbol in NG_SYMBOLS:
            ng_open = sum(1 for s in open_symbols if s in NG_SYMBOLS)
            if ng_open >= ENERGY_RISK_CONFIG['MAX_OPEN_NG']:
                return False, (
                    f"Energy limit: {ng_open} NG position(s) open "
                    f"(max {ENERGY_RISK_CONFIG['MAX_OPEN_NG']})"
                )
        else:
            oil_symbols = ENERGY_SYMBOLS - NG_SYMBOLS
            oil_open = sum(1 for s in open_symbols if s in oil_symbols)
            if oil_open >= ENERGY_RISK_CONFIG['MAX_OPEN_OIL']:
                return False, (
                    f"Energy limit: {oil_open} oil position(s) open "
                    f"(max {ENERGY_RISK_CONFIG['MAX_OPEN_OIL']})"
                )

        return True, "Energy position limits OK"
    except Exception as e:
        logger.debug(f"Energy position limit check failed: {e}")
        return True, "Energy limit check failed, allowing trade"


# Build a reverse map from group name -> set of symbols in that group.
# Used for correlation-based position limiting (skip XAGUSD if XAUUSD is open).
_CORRELATION_GROUPS = {}
for _sym, _info in PAIR_CORRELATION_MAP.items():
    _grp = _info.get('group')
    if _grp:
        _CORRELATION_GROUPS.setdefault(_grp, set()).add(_sym)


def _match_strategy_name_to_router(config_name, selected_strategies):
    """Check if a StrategyConfig.name matches any name in the router's selected list.

    StrategyConfig.name includes a domain suffix like '(FOREX)' while the router's
    STRATEGY_POOL keys are bare names like 'CVD Lack of Participants'.
    We do a prefix match: 'CVD Lack of Participants (FOREX)' matches 'CVD Lack of Participants'.
    """
    for router_name in selected_strategies:
        if config_name == router_name or config_name.startswith(router_name):
            return True
    return False


def _check_correlation_group_limit(symbol):
    """Check if another symbol in the same correlation group already has an open position.

    Returns (allowed: bool, reason: str).

    Uses PairLock (fast DB check) to see if any peer in the same group is locked.
    E.g., if XAUUSD has an open position, skip XAGUSD/XAUEUR/XAUJPY/XAUAUD.
    """
    mapping = PAIR_CORRELATION_MAP.get(symbol)
    if mapping is None:
        return True, f"Correlation: {symbol} not in map (exempt)"

    group = mapping.get('group')
    if not group:
        return True, f"Correlation: {symbol} has no group (exempt)"

    group_symbols = _CORRELATION_GROUPS.get(group, set())
    peer_symbols = group_symbols - {symbol}
    if not peer_symbols:
        return True, f"Correlation: {symbol} group '{group}' has no peers"

    try:
        from app.nexus.models import PairLock
        locked_peers = PairLock.objects.filter(symbol__in=list(peer_symbols))
        if locked_peers.exists():
            locked_list = list(locked_peers.values_list('symbol', flat=True))
            return False, (
                f"Correlation limit: {symbol} blocked — peer(s) {locked_list} "
                f"in group '{group}' already have open positions"
            )
        return True, f"Correlation: {symbol} group '{group}' clear (no peer positions)"
    except Exception as e:
        logger.debug(f"Correlation group check failed: {e}")
        return True, "Correlation check failed, allowing trade"



def _check_high_impact_events():
    """Check if a high-impact economic event is imminent or just occurred.

    Returns (blocked: bool, event_name: str or None).

    Fast path — just a Redis cache.get(). The 'high_impact_event_block' key is
    populated by update_event_guards() in macro_analyst.py (called every 2 min
    via fetch_market_pulse). The key auto-expires after the post-event window.
    """
    try:
        from django.core.cache import cache
        event_name = cache.get('high_impact_event_block')
        if event_name:
            return True, event_name
        return False, None
    except Exception as e:
        logger.error(f"High-impact event check failed: {e}")
        return False, None


def _check_market_context(pair, order_type, strategy_config):
    """Unified market context gate — merges macro analysis + regime awareness.

    Returns (allowed: bool, size_multiplier: float, reason: str).

    Hard blocks (allowed=False):
    - High-impact news within 30 min (avoid_trading flag)
    - Strong opposing macro bias (confidence >= 7)

    Soft adjustments (size_multiplier < 1.0):
    - Regime mismatch with strategy's regime_filter → 50% size
    """
    size_mult = 1.0
    reasons = []

    # --- Macro analysis (hard block on news/strong opposing bias) ---
    try:
        from app.quant.macro_analyst import check_macro_for_trade
        macro_ok, macro_reason = check_macro_for_trade(pair, order_type)
        if not macro_ok:
            return False, 0.0, f"MACRO BLOCK: {macro_reason}"
        reasons.append(macro_reason)
    except Exception as e:
        logger.debug(f"Macro check unavailable: {e}")

    # --- Regime awareness (soft sizing adjustment, not hard block) ---
    try:
        regime_filter = strategy_config.regime_filter if strategy_config else ''
        if regime_filter:
            from app.quant.algorithms.regime import get_regime_for_pair
            current_regime = get_regime_for_pair(pair)
            if current_regime and current_regime != regime_filter:
                size_mult *= REGIME_MISMATCH_SIZE_PENALTY
                reasons.append(
                    f"regime mismatch ({current_regime} vs strategy expects {regime_filter}), "
                    f"sizing at {REGIME_MISMATCH_SIZE_PENALTY:.0%}"
                )
            elif current_regime:
                reasons.append(f"regime={current_regime} matches strategy")
    except Exception as e:
        logger.debug(f"Regime check unavailable: {e}")

    reason_str = "; ".join(reasons) if reasons else "Market context OK"
    return True, size_mult, reason_str


def _compute_sl_tp(symbol, entry_price, order_type, atr_val, sl_mult, tp_mult):
    """Compute SL/TP using multi-timeframe S/R levels, falling back to ATR.

    Attempts to place SL at the nearest structural support/resistance level
    and TP at the next significant level in the profit direction. If no valid
    S/R levels are found or R:R < 1.5, falls back to the fixed ATR method.

    Returns (sl_price, tp_price, source_description).
    """
    try:
        from app.quant.indicators.support_resistance import find_multi_tf_sr, get_dynamic_sl_tp

        sr_levels = find_multi_tf_sr(symbol, fetch_data_pos, atr_val)

        result = get_dynamic_sl_tp(
            entry_price, order_type, sr_levels, atr_val,
            min_rr=1.5, sl_buffer_atr=0.3,
        )

        if result is not None:
            logger.info(
                f"CVD S/R: {symbol} {order_type} — "
                f"SL={result['sl']:.5f} ({result['sl_source']}) "
                f"TP={result['tp']:.5f} ({result['tp_source']}) "
                f"R:R={result['rr_ratio']}:1"
            )
            return result['sl'], result['tp'], 'S/R'

    except Exception as e:
        logger.debug(f"S/R computation failed for {symbol}: {e}")

    # Fallback to ATR-based SL/TP (ensure min 3:1 R:R for tick-slippage headroom)
    sl_distance = atr_val * sl_mult
    tp_distance = max(atr_val * tp_mult, sl_distance * 3.0)
    if order_type == 'BUY':
        sl_price = entry_price - sl_distance
        tp_price = entry_price + tp_distance
    else:
        sl_price = entry_price + sl_distance
        tp_price = entry_price - tp_distance

    logger.info(f"CVD ATR fallback: {symbol} {order_type} SL={sl_price:.5f} TP={tp_price:.5f}")
    return sl_price, tp_price, 'ATR'


def _is_trading_session():
    """Check if current UTC hour is within allowed trading sessions.

    Currently disabled — trading 24/7 across all sessions to support
    commodities (XAUUSD, NG-C, UKOUSDft) which trade 23:00-22:00 UTC.
    Only blocks Sunday when all markets are closed.
    """
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)
    # Block all Sunday trading (weekday 6 = Sunday, markets closed)
    if now.weekday() == 6:
        return False
    return True


# ---------------------------------------------------------------------------
# Daily Profit Preservation (Livermore: "No profit is safe until banked")
# ---------------------------------------------------------------------------

DAILY_PROFIT_PRESERVATION_USD = 50.0   # After +$50 daily profit, switch to preservation
PRESERVATION_SIZE_MULT = 0.50          # Trade at 50% size to protect gains

def _get_daily_profit_preservation_mult():
    """Livermore: "No profit is safe until deposited in your bank."

    After a profitable day, reduce sizing to protect gains. Prevents the
    common pattern of making money in the morning, then giving it all back.
    Returns a size multiplier (1.0 = normal, 0.5 = preservation mode).
    """
    try:
        from django.core.cache import cache

        cached = cache.get('daily_profit_preservation_mult')
        if cached is not None:
            return float(cached)

        from app.nexus.models import Trade
        from django.utils import timezone
        from django.db.models import Sum
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(hours=24)
        daily_pnl = Trade.objects.filter(
            close_time__isnull=False,
            close_time__gte=cutoff,
            pnl__isnull=False,
        ).aggregate(total=Sum('pnl'))['total'] or 0.0

        if daily_pnl >= DAILY_PROFIT_PRESERVATION_USD:
            cache.set('daily_profit_preservation_mult', PRESERVATION_SIZE_MULT, timeout=300)
            return PRESERVATION_SIZE_MULT

        cache.set('daily_profit_preservation_mult', 1.0, timeout=300)
        return 1.0

    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# Adaptive Trading Filters
# ---------------------------------------------------------------------------

def _check_circuit_breaker(strategy_config, symbol=None):
    """Check if a losing streak should pause entries.

    Returns (allowed: bool, reason: str).
    Uses Redis for cooldown state to survive Celery restarts.
    """
    try:
        from django.core.cache import cache
        from app.nexus.models import Trade

        # Check if we're in a cooldown period
        if symbol:
            cooldown_key = f'circuit_breaker:symbol:{symbol}'
            if cache.get(cooldown_key):
                return False, f"Circuit breaker: {symbol} in cooldown"

        global_key = 'circuit_breaker:global'
        if cache.get(global_key):
            return False, "Circuit breaker: global cooldown active"

        # Respect the daily halt reset timestamp — old trades from parameter
        # changes should not re-trip the circuit breaker
        reset_ts = cache.get('daily_halt_reset_time')
        cb_filter = dict(close_time__isnull=False, pnl__isnull=False)
        if reset_ts:
            cb_filter['close_time__gte'] = reset_ts

        # Check per-symbol consecutive losses
        if symbol:
            symbol_trades = Trade.objects.filter(
                symbol=symbol,
                **cb_filter,
            ).order_by('-close_time')[:CIRCUIT_BREAKER_SYMBOL_LOSSES]

            symbol_losses = 0
            for t in symbol_trades:
                if t.pnl <= 0:
                    symbol_losses += 1
                else:
                    break

            if symbol_losses >= CIRCUIT_BREAKER_SYMBOL_LOSSES:
                cache.set(cooldown_key, True,
                          timeout=CIRCUIT_BREAKER_COOLDOWN_HOURS * 3600)
                return False, (
                    f"Circuit breaker: {symbol_losses} consecutive losses on {symbol}, "
                    f"pausing for {CIRCUIT_BREAKER_COOLDOWN_HOURS}h"
                )

        # Check global consecutive losses
        global_trades = Trade.objects.filter(
            **cb_filter,
        ).order_by('-close_time')[:CIRCUIT_BREAKER_GLOBAL_LOSSES]

        global_losses = 0
        for t in global_trades:
            if t.pnl <= 0:
                global_losses += 1
            else:
                break

        if global_losses >= CIRCUIT_BREAKER_GLOBAL_LOSSES:
            cache.set(global_key, True,
                      timeout=CIRCUIT_BREAKER_COOLDOWN_HOURS * 3600)
            return False, (
                f"Circuit breaker: {global_losses} consecutive global losses, "
                f"pausing all entries for {CIRCUIT_BREAKER_COOLDOWN_HOURS}h"
            )

        return True, "OK"
    except Exception as e:
        logger.error(f"Circuit breaker check failed: {e}")
        return True, "Circuit breaker check failed, allowing trade"


def _check_symbol_performance(symbol):
    """Check if a symbol's recent performance warrants continued trading.

    Returns (allowed: bool, size_multiplier: float, reason: str).
    """
    try:
        from django.core.cache import cache
        from app.nexus.models import Trade

        # Check cooldown
        cooldown_key = f'symbol_filter:{symbol}'
        if cache.get(cooldown_key):
            return False, 0.0, f"Symbol filter: {symbol} paused for poor performance"

        pnls = list(Trade.objects.filter(
            symbol=symbol,
            close_time__isnull=False,
            pnl__isnull=False,
        ).order_by('-close_time').values_list('pnl', flat=True)[:SYMBOL_FILTER_LOOKBACK])
        if len(pnls) < 5:
            return True, 1.0, "Not enough data for symbol filter"

        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / len(pnls)
        total_pnl = sum(pnls)

        # Hard block: poor win rate AND negative PnL
        if win_rate < SYMBOL_FILTER_MIN_WR and total_pnl < 0:
            cache.set(cooldown_key, True,
                      timeout=SYMBOL_FILTER_COOLDOWN_HOURS * 3600)
            return False, 0.0, (
                f"Symbol filter: {symbol} WR={win_rate:.0%} PnL=${total_pnl:.2f} "
                f"over last {len(pnls)} trades, pausing for {SYMBOL_FILTER_COOLDOWN_HOURS}h"
            )

        # Dynamic sizing based on win rate
        if win_rate >= 0.60:
            size_mult = 1.0
        elif win_rate >= 0.45:
            size_mult = 0.75
        else:
            size_mult = 0.50

        return True, size_mult, f"Symbol {symbol}: WR={win_rate:.0%}, size={size_mult:.0%}"
    except Exception as e:
        logger.error(f"Symbol performance check failed: {e}")
        return True, 1.0, "Symbol check failed, allowing trade"


def _check_group_tendency(symbol, direction):
    """Check if correlated currency pairs confirm the trade direction.

    Implements Livermore's "group tendency" principle: a pair that diverges
    from its currency group is trading against the broader flow.  We fetch
    the last 20 M15 bars of each peer pair and compare close[-1] vs
    close[-20] to determine simple directional tendency.

    Majority rule: at least 1 of 2 peers must agree.

    Returns (confirmed: bool, reason: str).
    Results are cached in Redis for GROUP_TENDENCY_CACHE_TTL seconds to
    avoid hammering the MT5 API on every signal evaluation.
    """
    mapping = PAIR_CORRELATION_MAP.get(symbol)
    if mapping is None or not mapping['check_peers']:
        return True, f"Group tendency: {symbol} has no peers (exempt)"

    peers = mapping['check_peers']
    cache_key = f'group_tendency:{symbol}:{direction}'

    # --- Redis cache: one key per (symbol, direction) ---
    try:
        from django.core.cache import cache
        cached = cache.get(cache_key)
        if cached is not None:
            return cached  # tuple (bool, str) stored earlier
    except Exception:
        pass  # cache unavailable — compute fresh

    confirming = 0
    peer_details = []

    for peer in peers:
        try:
            df = fetch_data_pos(peer, MT5Timeframe.M15, 20)
            if df is None or df.empty or len(df) < 20:
                # Insufficient data — give benefit of the doubt
                peer_details.append(f"{peer}=no_data")
                continue

            close_old = df['close'].iloc[0]
            close_new = df['close'].iloc[-1]

            if close_new > close_old:
                peer_dir = 'UP'
            elif close_new < close_old:
                peer_dir = 'DOWN'
            else:
                peer_dir = 'FLAT'

            # Does the peer's direction match what we expect?
            expected = direction  # BUY → UP, SELL → DOWN for same-group pairs
            if (expected == 'BUY' and peer_dir == 'UP') or \
               (expected == 'SELL' and peer_dir == 'DOWN'):
                confirming += 1
                peer_details.append(f"{peer}={peer_dir} (confirms)")
            else:
                peer_details.append(f"{peer}={peer_dir} (diverges)")

        except Exception as e:
            logger.debug(f"Group tendency: error fetching {peer}: {e}")
            peer_details.append(f"{peer}=error")

    detail_str = ", ".join(peer_details)

    # Majority rule: need at least 1 of 2 peers to confirm
    if confirming >= 1:
        result = (True, f"Group tendency confirmed: {symbol} {direction} — {detail_str}")
    else:
        result = (
            False,
            f"Group tendency DIVERGENCE: {symbol} {direction} but peers disagree — {detail_str}",
        )

    # Cache the result
    try:
        from django.core.cache import cache
        cache.set(cache_key, result, timeout=GROUP_TENDENCY_CACHE_TTL)
    except Exception:
        pass

    return result


def _store_rejected_features(symbol, ml_score, features):
    """Store ML features for a rejected trade (no Trade object to link to).

    We log these so the model can learn about conditions it rejected.
    Rejected trades don't get a TradeFeature row since there's no Trade.
    """
    logger.info(f"ML rejected {symbol} with score={ml_score:.2f}, features stored in log only")


def _get_dynamic_size_multiplier(strategy_config, atr_val=None, close_price=None):
    """Volatility-targeting + streak-based position sizing.

    Combines two proven approaches:
    1. Volatility targeting: scale position inversely with realized vol
       so that each trade has approximately the same dollar risk.
    2. Streak-based: reduce size after consecutive losses (Kelly-inspired).

    Returns a multiplier (0.1 to 1.0) applied to CAPITAL_PER_TRADE.

    Reference: AQR, Man Group — volatility targeting is the industry
    standard for systematic macro strategies.
    """
    streak_mult = 1.0
    vol_mult = 1.0

    # --- Streak-based multiplier ---
    try:
        from app.nexus.models import Trade

        trades = Trade.objects.filter(
            close_time__isnull=False,
            pnl__isnull=False,
        ).order_by('-close_time')[:10]

        pnls = [t.pnl for t in trades]
        if len(pnls) >= 3:
            consecutive_losses = 0
            for p in pnls:
                if p <= 0:
                    consecutive_losses += 1
                else:
                    break

            if consecutive_losses >= 4:
                streak_mult = 0.25
            elif consecutive_losses >= 3:
                streak_mult = 0.50
            elif consecutive_losses >= 2:
                streak_mult = 0.75
    except Exception as e:
        logger.error(f"Streak sizing check failed: {e}")

    # --- Volatility-targeting multiplier ---
    # Target: 0.5% of close price as ATR (median forex vol)
    # If current ATR is higher, scale down; if lower, scale up
    TARGET_ATR_RATIO = 0.005  # 0.5% of price = typical forex ATR
    try:
        if atr_val and close_price and close_price > 0:
            current_atr_ratio = atr_val / close_price
            if current_atr_ratio > 0:
                vol_mult = TARGET_ATR_RATIO / current_atr_ratio
                vol_mult = max(0.3, min(1.5, vol_mult))  # Clamp to [0.3, 1.5]
    except Exception as e:
        logger.debug(f"Vol targeting failed: {e}")

    combined = streak_mult * vol_mult
    return max(0.1, min(1.0, combined))  # Final clamp to [0.1, 1.0]


# ---------------------------------------------------------------------------
# Strategy loading helpers
# ---------------------------------------------------------------------------

def _load_active_custom_strategy():
    """Load the CustomStrategy linked to the currently active StrategyConfig."""
    from app.nexus.models import StrategyConfig, CustomStrategy
    active = StrategyConfig.objects.filter(is_active=True).first()
    if active is None:
        return None, None
    custom = CustomStrategy.objects.filter(strategy_config=active).first()
    return active, custom


def _load_custom_strategy_for_config(strategy_config):
    """Load the CustomStrategy linked to a specific StrategyConfig."""
    from app.nexus.models import CustomStrategy
    custom = CustomStrategy.objects.filter(strategy_config=strategy_config).first()
    return custom


def _count_open_trades():
    positions = get_positions()
    if positions is None or positions.empty:
        return 0
    return len(positions)


def _check_backtest_gate(strategy_config):
    """Verify a recent, profitable backtest exists for this strategy."""
    try:
        from app.nexus.models import BacktestResult
        from django.utils import timezone

        latest = BacktestResult.objects.filter(
            strategy=strategy_config
        ).order_by('-run_time').first()

        if latest is None:
            logger.warning(f"No backtest for {strategy_config.name}, allowing trading (new strategy).")
            return True

        age = timezone.now() - latest.run_time
        if age > timedelta(hours=24):
            logger.warning(f"Backtest for {strategy_config.name} is {age} old (>24h), blocking.")
            return False

        if latest.total_trades == 0:
            logger.warning(f"Latest backtest for {strategy_config.name} has 0 trades, blocking.")
            return False

        if latest.total_pnl < -0.5:
            logger.warning(f"Backtest PnL {latest.total_pnl:.4f} heavily negative, blocking.")
            return False

        logger.info(f"Backtest gate passed: PnL={latest.total_pnl:.4f}, WR={latest.win_rate:.2%}, age={age}")
        return True
    except Exception as e:
        logger.error(f"Backtest gate error: {e}")
        return True


# ---------------------------------------------------------------------------
# Indicator computation
# ---------------------------------------------------------------------------

def _resolve_cvd_variant(entry_rules):
    """Determine which CVD indicator variant to use based on entry rule conditions."""
    mapping = {
        'leading_divergence': 'CVD_LEADING',
        'extreme_divergence': 'CVD_EXTREMES',
        'mtf_divergence': 'CVD_MTF',
        'cross_market_divergence': 'CVD_CROSS_MARKET',
        'cross_side_divergence': 'CVD_CROSS_MARKET',
    }
    for side in ['long', 'short']:
        for rule in entry_rules.get(side, []):
            condition = rule.get('condition', '')
            if condition in mapping:
                return mapping[condition]
    return None


def _compute_indicators(df, indicators, entry_rules):
    """Compute all declared indicators on the dataframe."""
    cvd_variant = _resolve_cvd_variant(entry_rules)
    for ind in indicators:
        ind_type = ind['type']
        params = ind.get('params', {})

        if ind_type == 'CVD' and cvd_variant and cvd_variant in INDICATOR_REGISTRY:
            df[ind_type] = INDICATOR_REGISTRY[cvd_variant](df, params)
        elif ind_type in INDICATOR_REGISTRY:
            df[ind_type] = INDICATOR_REGISTRY[ind_type](df, params)
    return df


def _check_rules(df, idx, rules):
    """Check if all conditions in a rule set are met at bar idx."""
    for rule in rules:
        indicator = rule['indicator']
        condition = rule['condition']
        value = rule['value']
        if indicator not in df.columns:
            return False
        actual = df[indicator].iloc[idx]
        if pd.isna(actual):
            return False
        op = CONDITION_OPS.get(condition)
        if op is None:
            return False
        try:
            if not op(actual, value):
                return False
        except (ValueError, TypeError):
            return False
    return True


# ---------------------------------------------------------------------------
# Main entry algorithm
# ---------------------------------------------------------------------------

def cvd_entry_algorithm(strategy_config, remaining_slots):
    """Multi-strategy CVD entry algorithm with adaptive intelligence.

    Applies layered filters before each trade:
    1. Trading session filter (07:00-17:00 UTC)
    2. High-impact economic event guard (NFP, FOMC, CPI, etc.)
    3. Global + per-symbol circuit breaker
    4. Symbol performance filter with dynamic sizing
    5. Market context gate (macro news + regime — merged layer)
    6. Group tendency — cross-pair correlation (soft: 50% sizing penalty)
    7. ML meta-filter (accept/reject based on win probability)
    8. Dynamic position sizing (vol + streak + symbol + context + group)
    """
    from app.nexus.models import PairLock
    from django.db import IntegrityError

    # Cache symbol_info_tick results to avoid redundant HTTP calls (~250ms each)
    _tick_cache = {}

    def _get_cached_tick(symbol):
        if symbol not in _tick_cache:
            _tick_cache[symbol] = symbol_info_tick(symbol)
        return _tick_cache[symbol]

    try:
        custom = _load_custom_strategy_for_config(strategy_config)
        if custom is None:
            logger.warning(f"No CustomStrategy linked to StrategyConfig '{strategy_config.name}'.")
            return

        definition = custom.definition
        if not definition:
            logger.warning(f"CustomStrategy '{custom.name}' has empty definition.")
            return

        # Backtest gate disabled — let strategies trade freely while we
        # collect ML training data and fine-tune parameters from live results.
        # if not _check_backtest_gate(strategy_config):
        #     logger.info(f"CVD entry blocked by backtest gate for '{custom.name}'.")
        #     return

        if not TRAINING_MODE:
            if not _is_trading_session():
                logger.info(f"CVD: Outside trading session (07:00-17:00 UTC), skipping.")
                return

            # --- High-impact economic event guard (fast Redis check) ---
            event_blocked, event_name = _check_high_impact_events()
            if event_blocked:
                logger.warning(f"CVD: Entry blocked: high-impact event '{event_name}' within 30min window")
                return

        # --- Global circuit breaker check ---
        if not TRAINING_MODE:
            cb_ok, cb_reason = _check_circuit_breaker(strategy_config)
            if not cb_ok:
                logger.warning(f"CVD: {cb_reason}")
                return

        # --- Streak multiplier (computed once per cycle, vol-targeting is per-pair) ---
        streak_multiplier = _get_dynamic_size_multiplier(strategy_config)
        if streak_multiplier < 1.0:
            logger.info(f"CVD: Streak sizing active — {streak_multiplier:.0%} of normal capital")

        positions_opened = 0

        pairs = definition.get('pairs', [])
        indicators = definition.get('indicators', [])
        entry_rules = definition.get('entry_rules', {})
        exit_rules = definition.get('exit_rules', {})
        timeframe_str = definition.get('timeframe', 'M15')

        try:
            timeframe = MT5Timeframe(timeframe_str)
        except ValueError:
            timeframe = MT5Timeframe.M15

        # ATR params from strategy definition or defaults
        exit_params = exit_rules.get('params', {})
        atr_period = exit_params.get('atr_period', ATR_PERIOD)
        sl_mult = exit_params.get('sl_multiplier', SL_ATR_MULTIPLIER)
        tp_mult = exit_params.get('tp_multiplier', TP_ATR_MULTIPLIER)

        long_rules = entry_rules.get('long', [])
        short_rules = entry_rules.get('short', [])

        for pair in pairs:
            if positions_opened >= remaining_slots:
                logger.info(f"CVD ({custom.name}): Remaining slots exhausted ({remaining_slots}), stopping.")
                break

            # Fast DB check first — prevents cross-strategy conflicts without API call
            if PairLock.objects.filter(symbol=pair).exists():
                logger.info(f"CVD: Skipping {pair} — locked by another strategy.")
                continue

            if have_open_positions_in_symbol(pair):
                logger.info(f"CVD: Skipping {pair} — already has open position.")
                continue

            if not is_market_open(pair):
                logger.info(f"CVD: Skipping {pair} — market closed.")
                continue

            # --- Energy-specific position limits ---
            energy_ok, energy_reason = _check_energy_position_limits(pair)
            if not energy_ok:
                logger.info(f"CVD: {energy_reason}")
                continue

            # --- Energy risk overrides (vol regime, session, seasonal) ---
            energy_overrides = _get_energy_overrides(pair)
            if energy_overrides and energy_overrides['vol_regime_mult'] <= 0:
                logger.info(
                    f"CVD: Skipping {pair} — energy risk filter blocked "
                    f"(vol_regime_mult=0)"
                )
                continue

            # --- Strategy Router gate (regime-based strategy selection) ---
            if not TRAINING_MODE:
                try:
                    from app.quant.algorithms.strategy_router import route_symbol as _route_symbol
                    routing_decision = _route_symbol(pair)
                    if not _match_strategy_name_to_router(
                        strategy_config.name, routing_decision.selected_strategies
                    ):
                        logger.info(
                            f"CVD: ROUTER SKIP: '{strategy_config.name}' not valid for "
                            f"{pair} ({routing_decision.regime}, conf={routing_decision.regime_confidence:.2f}) "
                            f"— allowed strategies: {routing_decision.selected_strategies[:3]}"
                        )
                        continue
                except Exception as e:
                    logger.debug(f"Strategy router unavailable for {pair}: {e}")

            # --- Correlation-group position limit ---
            if not TRAINING_MODE:
                corr_ok, corr_reason = _check_correlation_group_limit(pair)
                if not corr_ok:
                    logger.info(f"CVD: {corr_reason}")
                    continue

            # --- Per-symbol circuit breaker ---
            if not TRAINING_MODE:
                cb_ok, cb_reason = _check_circuit_breaker(strategy_config, symbol=pair)
                if not cb_ok:
                    logger.warning(f"CVD: {cb_reason}")
                    continue

            # --- Symbol performance filter ---
            sym_ok, sym_mult, sym_reason = _check_symbol_performance(pair)
            if not sym_ok and not TRAINING_MODE:
                logger.debug(f"CVD: {sym_reason}")
                continue
            if sym_mult < 1.0:
                logger.info(f"CVD: {sym_reason}")

            # Fetch enough bars for indicator computation
            df = fetch_data_pos(pair, timeframe, 100)
            if df is None or df.empty or len(df) < 30:
                logger.info(f"CVD: Skipping {pair} — insufficient data ({0 if df is None else len(df)} bars).")
                continue

            # Compute CVD indicators
            df = _compute_indicators(df, indicators, entry_rules)

            # Compute ATR for exit levels
            df['_atr'] = atr(df, period=atr_period)

            # Check signal on last N completed bars (most recent first)
            SIGNAL_LOOKBACK = 4
            order_type = None
            signal_desc = None
            check_idx = None
            atr_val = None

            for offset in range(2, 2 + SIGNAL_LOOKBACK):
                idx = len(df) - offset
                if idx < 0:
                    break
                _atr_val = df['_atr'].iloc[idx]
                if pd.isna(_atr_val) or _atr_val <= 0:
                    continue
                if long_rules and _check_rules(df, idx, long_rules):
                    order_type = 'BUY'
                    check_idx = idx
                    atr_val = _atr_val
                    signal_desc = str(df.get('CVD', pd.Series()).iloc[idx] if 'CVD' in df.columns else 'long_signal')
                    logger.info(f"CVD: Signal found at bar offset {offset} for {pair}")
                    break
                if short_rules and _check_rules(df, idx, short_rules):
                    order_type = 'SELL'
                    check_idx = idx
                    atr_val = _atr_val
                    signal_desc = str(df.get('CVD', pd.Series()).iloc[idx] if 'CVD' in df.columns else 'short_signal')
                    logger.info(f"CVD: Signal found at bar offset {offset} for {pair}")
                    break

            if order_type is None:
                # --- REAL-TIME TICK CVD: Check for sub-bar signals ---
                try:
                    from django.core.cache import cache as _cache
                    import time as _time
                    rt_signal = _cache.get(f'realtime_cvd:{pair}')
                    if rt_signal and isinstance(rt_signal, dict):
                        signal_age = (_time.time() * 1000) - rt_signal.get('timestamp', 0)
                        if signal_age < 30_000:  # Signal is < 30 seconds old
                            order_type = rt_signal['direction']
                            signal_desc = f"RT_{rt_signal['signal']}"
                            check_idx = len(df) - 2  # Use most recent complete bar for ATR/levels
                            atr_val = df['_atr'].iloc[check_idx]
                            logger.info(
                                f"CVD: REALTIME TICK signal for {pair}: {signal_desc} "
                                f"(age={signal_age/1000:.1f}s, cvd={rt_signal.get('cvd_value', 'N/A')})"
                            )
                except Exception as e:
                    logger.debug(f"CVD: Realtime CVD check failed for {pair}: {e}")

                if order_type is None:
                    logger.debug(f"CVD ({custom.name}): No signal for {pair} on last {SIGNAL_LOOKBACK} bars.")
                    continue

            if atr_val is None:
                logger.info(f"CVD ({custom.name}): Signal found for {pair} but ATR not valid.")
                continue

            # --- Market Context Gate (macro + regime merged) ---
            ctx_mult = 1.0
            if not TRAINING_MODE:
                ctx_ok, ctx_mult, ctx_reason = _check_market_context(
                    pair, order_type, strategy_config,
                )
                if not ctx_ok:
                    logger.warning(f"CVD: {pair} {order_type} — {ctx_reason}")
                    continue
                if ctx_mult < 1.0:
                    logger.info(f"CVD: {pair} {order_type} — {ctx_reason}")

            logger.info(f"CVD SIGNAL: {pair} {order_type} — {signal_desc}")

            # --- Strategy Router parameters (sizing, SL, confluence thresholds) ---
            # Router validity was already enforced above (pre-signal gate).
            # Here we just read the regime-based parameters for sizing/SL/confluence.
            router_mult = 1.0
            router_min_confluence = 4
            router_sl_adj = 1.0
            try:
                from app.quant.algorithms.strategy_router import route_symbol
                routing = route_symbol(pair)
                router_mult = routing.size_multiplier
                router_min_confluence = routing.min_confluence
                router_sl_adj = routing.sl_multiplier_adj
                logger.info(f"CVD: ROUTER params: {routing.reason}")
            except Exception as e:
                logger.debug(f"Strategy router unavailable: {e}")

            # --- Group Tendency Check (Livermore's "never fight the group") ---
            group_mult = 1.0
            grp_ok, grp_reason = _check_group_tendency(pair, order_type)
            if not grp_ok:
                group_mult = GROUP_TENDENCY_SIZE_PENALTY
                logger.debug(
                    f"CVD: {grp_reason} — applying {GROUP_TENDENCY_SIZE_PENALTY:.0%} "
                    f"sizing penalty"
                )
            else:
                logger.debug(f"CVD: {grp_reason}")

            # --- ML Signal Scorer ---
            ml_score, ml_accept, ml_features = 0.5, True, {}
            try:
                from app.quant.ml.scorer import score_signal
                tick_info_for_ml = _get_cached_tick(pair)
                ml_score, ml_accept, ml_reason, ml_features = score_signal(
                    pair, order_type, df, atr_val,
                    strategy_config=strategy_config,
                    custom_strategy=custom,
                    tick_info=tick_info_for_ml,
                )
                if not ml_accept and not TRAINING_MODE:
                    logger.info(f"CVD: ML REJECT {pair} {order_type} score={ml_score:.2f} — {ml_reason}")
                    _store_rejected_features(pair, ml_score, ml_features)
                    continue
                if not ml_accept:
                    logger.info(f"CVD: TRAINING MODE — ML would reject {pair} {order_type} score={ml_score:.2f}, taking anyway")
                else:
                    logger.info(f"CVD: ML score={ml_score:.2f} — {ml_reason}")
            except Exception as e:
                logger.debug(f"ML scoring unavailable: {e}")

            # --- Confluence Scorer (quantifies setup quality 0-11) ---
            confluence_score = None
            try:
                from app.quant.algorithms.confluence_scorer import score_confluence, log_confluence_decision

                # Reuse SMC detection results from ML features (already computed
                # by score_signal -> extract_features on the same df) to avoid
                # redundant ~100ms SMC detector calls per symbol.
                has_displacement = bool(ml_features.get('displacement', 0))
                has_fvg = bool(ml_features.get('fvg_present', 0))
                has_ob = bool(ml_features.get('ob_present', 0))
                has_sweep = bool(ml_features.get('recent_sweep', 0))

                # Fallback: if ML features are empty (scorer failed), compute fresh
                if not ml_features:
                    try:
                        from app.quant.indicators.displacement import detect_displacement
                        _norm_df = df.rename(columns={
                            'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close',
                        })
                        disp_result = detect_displacement(_norm_df)
                        if disp_result is not None and len(disp_result) > 0:
                            last_disp = disp_result['displacement'].iloc[-1]
                            has_displacement = (
                                (last_disp == 1 and order_type == 'BUY') or
                                (last_disp == -1 and order_type == 'SELL')
                            )
                    except Exception:
                        pass

                    try:
                        from app.quant.indicators.smc_detector import detect_fair_value_gaps
                        fvg_df = detect_fair_value_gaps(df)
                        if fvg_df is not None and 'FVG' in fvg_df.columns and len(fvg_df) > 0:
                            last_fvg = fvg_df['FVG'].iloc[-1]
                            has_fvg = (
                                (last_fvg == 1 and order_type == 'BUY') or
                                (last_fvg == -1 and order_type == 'SELL')
                            )
                    except Exception:
                        pass

                    try:
                        from app.quant.indicators.smc_detector import detect_order_blocks
                        ob_df = detect_order_blocks(df)
                        if ob_df is not None and 'OB' in ob_df.columns:
                            for lookback_i in range(max(0, len(ob_df) - 5), len(ob_df)):
                                ob_val = ob_df['OB'].iloc[lookback_i]
                                if pd.notna(ob_val):
                                    has_ob = (
                                        (ob_val == 1 and order_type == 'BUY') or
                                        (ob_val == -1 and order_type == 'SELL')
                                    )
                                    if has_ob:
                                        break
                    except Exception:
                        pass

                    try:
                        from app.quant.indicators.smc_detector import detect_liquidity_sweeps
                        sweep_df = detect_liquidity_sweeps(df)
                        if sweep_df is not None and 'Liquidity' in sweep_df.columns:
                            for lookback_i in range(max(0, len(sweep_df) - 5), len(sweep_df)):
                                liq_val = sweep_df['Liquidity'].iloc[lookback_i]
                                if pd.notna(liq_val):
                                    has_sweep = (
                                        (liq_val == -1 and order_type == 'BUY') or
                                        (liq_val == 1 and order_type == 'SELL')
                                    )
                                    if has_sweep:
                                        break
                    except Exception:
                        pass

                # HTF bias (H4 EMA + swing structure — worth 2 confluence points)
                htf_bias = None
                try:
                    from app.quant.algorithms.mtf_analyzer import get_htf_bias_string
                    htf_bias = get_htf_bias_string(pair)
                except Exception:
                    pass

                # Regime favorability from router (strategy fits current regime?)
                regime_ok = None
                try:
                    regime_ok = _match_strategy_name_to_router(
                        strategy_config.name, routing.selected_strategies
                    )
                except Exception:
                    pass

                # CVD divergence is True if we got this far (signal IS the CVD)
                confluence_score = score_confluence(
                    symbol=pair,
                    direction='long' if order_type == 'BUY' else 'short',
                    htf_bias=htf_bias,
                    liquidity_sweep=has_sweep,
                    cvd_divergence=True,
                    displacement=has_displacement,
                    fvg_present=has_fvg,
                    order_block_at_entry=has_ob,
                    regime_favorable=regime_ok,
                    strategy_name=strategy_config.name,
                )
                log_confluence_decision(confluence_score)

                if not TRAINING_MODE:
                    if not confluence_score.should_trade:
                        logger.info(
                            f"CVD: Confluence too low for {pair} {order_type}: "
                            f"{confluence_score.total_score}/{confluence_score.max_possible} "
                            f"({confluence_score.band}) — skipping"
                        )
                        continue

                    if confluence_score.total_score < router_min_confluence:
                        logger.info(
                            f"CVD: Router requires min confluence {router_min_confluence} "
                            f"for {pair}, got {confluence_score.total_score} — skipping"
                        )
                        continue
                else:
                    logger.info(
                        f"CVD: TRAINING MODE — confluence {confluence_score.total_score}/{confluence_score.max_possible} "
                        f"({confluence_score.band}), taking trade regardless"
                    )
            except Exception as e:
                logger.debug(f"Confluence scoring unavailable: {e}")

            # Acquire PairLock before placing order
            try:
                PairLock.objects.create(symbol=pair, strategy=strategy_config, ticket=0)
            except IntegrityError:
                logger.info(f"CVD: Skipping {pair} — already locked by another strategy")
                continue

            try:
                # Get current tick price
                tick_info = _get_cached_tick(pair)
                if tick_info is None or tick_info.empty:
                    logger.info(f"CVD: Skipping {pair} — no tick info.")
                    PairLock.objects.filter(symbol=pair).delete()
                    continue

                last_tick_price = (
                    tick_info['ask'].iloc[0] if order_type == 'BUY' else tick_info['bid'].iloc[0]
                )
                price_decimals = len(str(last_tick_price).split('.')[-1])

                # --- Dynamic SL/TP: S/R levels first, ATR fallback ---
                # Energy symbols use wider stops from research config
                pair_sl_mult = sl_mult
                pair_tp_mult = tp_mult
                if energy_overrides:
                    pair_sl_mult = energy_overrides['sl_atr_multiplier']
                    pair_tp_mult = energy_overrides['tp_atr_multiplier']
                    logger.info(
                        f"CVD: Energy SL/TP override for {pair}: "
                        f"SL={pair_sl_mult}x ATR, TP={pair_tp_mult}x ATR"
                    )
                # router_sl_adj widens SL in volatile regimes (1.5x) for breathing room
                effective_sl_mult = pair_sl_mult * router_sl_adj
                sl_price, tp_price, sl_tp_source = _compute_sl_tp(
                    pair, last_tick_price, order_type, atr_val, effective_sl_mult, pair_tp_mult,
                )

                # --- Dynamic Position Sizing (vol + streak + symbol + context + group) ---
                vol_mult = _get_dynamic_size_multiplier(
                    strategy_config, atr_val=atr_val, close_price=last_tick_price,
                )
                # Combine all multipliers:
                # vol_mult: vol-targeting + streak (per-pair ATR + loss streak)
                # sym_mult: symbol win rate adjustment
                # ctx_mult: regime mismatch penalty (from market context gate)
                # group_mult: group tendency divergence penalty
                # orch_mult: strategy orchestrator regime/performance adjustment
                try:
                    from app.quant.strategy_orchestrator import get_orchestrator_size_multiplier
                    orch_mult = get_orchestrator_size_multiplier(strategy_config.name)
                except Exception:
                    orch_mult = 1.0
                # Daily profit preservation (Livermore: "no profit safe until banked")
                pres_mult = _get_daily_profit_preservation_mult()
                # Kill zone weighting — ICT session-aware sizing
                try:
                    from app.quant.indicators.kill_zones import get_kill_zone_weight, get_current_kill_zone
                    kz_mult = get_kill_zone_weight()
                    kz_name, _, kz_info = get_current_kill_zone()
                except Exception:
                    kz_mult = 1.0
                    kz_name, kz_info = None, None
                # Energy volatility regime multiplier
                energy_mult = energy_overrides['vol_regime_mult'] if energy_overrides else 1.0
                size_multiplier = vol_mult * sym_mult * ctx_mult * group_mult * orch_mult * pres_mult * kz_mult * router_mult * energy_mult
                size_multiplier = max(0.1, min(2.0, size_multiplier))
                base_capital = energy_overrides['capital_per_trade'] if energy_overrides else CAPITAL_PER_TRADE
                order_capital = base_capital * size_multiplier

                kz_desc = kz_info['description'] if kz_info else 'no kill zone'
                if size_multiplier != 1.0:
                    logger.info(
                        f"CVD: Sized capital for {pair}: "
                        f"${CAPITAL_PER_TRADE:.2f} x {size_multiplier:.2f} = ${order_capital:.2f} "
                        f"(vol={vol_mult:.2f}, sym={sym_mult:.2f}, ctx={ctx_mult:.2f}, "
                        f"grp={group_mult:.2f}, orch={orch_mult:.2f}, pres={pres_mult:.2f}, "
                        f"kz={kz_mult:.2f} [{kz_desc}], router={router_mult:.2f})"
                    )

                order_size_usd = calculate_order_size_usd(order_capital, LEVERAGE)
                commission = calculate_commission(order_size_usd, pair)

                # Clamp SL so max loss does not exceed $50 hard ceiling
                # (position_manager also enforces this, but broker SL is the real safety net)
                max_loss_allowed = min(order_capital, MAX_LOSS_PER_TRADE)
                pnl_at_sl, _ = get_pnl_at_price(
                    sl_price, last_tick_price, order_size_usd, LEVERAGE, order_type, commission
                )
                if pnl_at_sl < -max_loss_allowed:
                    sl_price, _ = get_price_at_pnl(
                        desired_pnl=-max_loss_allowed,
                        entry_price=last_tick_price,
                        order_size_usd=order_size_usd,
                        leverage=LEVERAGE,
                        type=order_type,
                        commission=commission,
                    )
                    logger.info(f"CVD: Clamped SL for {pair} to limit loss to ${max_loss_allowed:.2f}")

                # --- Fetch broker contract specs for this symbol ---
                # Contract sizes vary wildly: forex=100k, XAUUSD=100oz,
                # XAGUSD=5000oz, NG-C=10000, oils=1000 barrels.
                # We use these to validate volume_min/max from the broker.
                contract_info = get_symbol_contract_info(pair)
                if contract_info:
                    broker_volume_min = contract_info['volume_min']
                    broker_volume_max = contract_info['volume_max']
                    broker_volume_step = contract_info['volume_step']
                    broker_contract_size = contract_info['trade_contract_size']
                else:
                    # Fallback: assume forex defaults if MT5 info unavailable
                    broker_volume_min = 0.01
                    broker_volume_max = 100.0
                    broker_volume_step = 0.01
                    broker_contract_size = 100000

                # Convert to lots — uses trade_contract_size from MT5
                full_volume_lots = convert_usd_to_lots(pair, order_size_usd, order_type)
                if isinstance(full_volume_lots, (pd.Series, pd.DataFrame)):
                    full_volume_lots = full_volume_lots.iloc[0] if not full_volume_lots.empty else 0.0

                # Validate against broker's volume_min (not hard-coded 0.01)
                if full_volume_lots < broker_volume_min:
                    logger.error(
                        f"CVD: Order volume too low for {pair}: {full_volume_lots:.4f} lots "
                        f"< broker minimum {broker_volume_min} "
                        f"(contract_size={broker_contract_size}, notional=${order_size_usd:.2f})"
                    )
                    PairLock.objects.filter(symbol=pair).delete()
                    continue

                # Hard safety cap — use the stricter of MAX_LOT_SIZE and broker volume_max
                effective_max_lots = min(MAX_LOT_SIZE, broker_volume_max)
                if full_volume_lots > effective_max_lots:
                    logger.warning(
                        f"CVD: CAPPING {pair} from {full_volume_lots:.2f} to {effective_max_lots} lots "
                        f"(MAX_LOT_SIZE={MAX_LOT_SIZE}, broker_max={broker_volume_max}, "
                        f"contract_size={broker_contract_size}, capital=${order_capital:.2f})"
                    )
                    full_volume_lots = effective_max_lots

                # Livermore scale-in: enter at 60%, add 40% on confirmation
                # Round to broker's volume_step (e.g. 0.1 for NG-C, 0.01 for forex)
                order_volume_lots = round(full_volume_lots * INITIAL_SIZE_FRACTION / broker_volume_step) * broker_volume_step
                remaining_volume_lots = round((full_volume_lots - order_volume_lots) / broker_volume_step) * broker_volume_step

                # Ensure initial size is still tradeable (use broker volume_min)
                if order_volume_lots < broker_volume_min:
                    order_volume_lots = full_volume_lots  # Too small to split, use full size
                    remaining_volume_lots = 0.0

                if remaining_volume_lots > 0:
                    logger.info(
                        f"CVD: Livermore scale-in for {pair}: "
                        f"initial={order_volume_lots} lots (60%), "
                        f"remaining={remaining_volume_lots} lots (40%) pending confirmation"
                    )

                # Validate SL direction — if S/R-based SL is invalid, force ATR fallback
                bid_price = tick_info['bid'].iloc[0]
                ask_price = tick_info['ask'].iloc[0]
                spread = ask_price - bid_price

                sl_invalid = False
                if order_type == 'BUY' and sl_price >= bid_price:
                    sl_invalid = True
                if order_type == 'SELL' and sl_price <= ask_price:
                    sl_invalid = True

                if sl_invalid:
                    # Force ATR-based SL with minimum distance = 3x spread
                    min_distance = max(atr_val * pair_sl_mult * router_sl_adj, spread * 3)
                    # Target 3:1 R:R to survive tick slippage (send_market_order
                    # refetches price; XAGUSD can move $0.30+ in 500ms which
                    # degrades R:R from computation point to execution point)
                    fallback_rr = max(pair_tp_mult / pair_sl_mult, 3.0)
                    if order_type == 'BUY':
                        sl_price = last_tick_price - min_distance
                        tp_price = last_tick_price + (min_distance * fallback_rr)
                    else:
                        sl_price = last_tick_price + min_distance
                        tp_price = last_tick_price - (min_distance * fallback_rr)
                    logger.warning(
                        f"CVD: SL was invalid for {order_type} on {pair} "
                        f"(spread={spread:.5f}), forced ATR fallback: "
                        f"SL={sl_price:.5f}, TP={tp_price:.5f}"
                    )

                    # Re-validate after fix
                    if order_type == 'BUY' and sl_price >= bid_price:
                        logger.error(f"CVD: SL still invalid for BUY on {pair} after fix, skipping.")
                        PairLock.objects.filter(symbol=pair).delete()
                        continue
                    if order_type == 'SELL' and sl_price <= ask_price:
                        logger.error(f"CVD: SL still invalid for SELL on {pair} after fix, skipping.")
                        PairLock.objects.filter(symbol=pair).delete()
                        continue

                # --- Pre-trade margin safety check ---
                try:
                    from app.utils.api.account import check_margin_safe
                    if not check_margin_safe(pair, order_volume_lots, order_type):
                        logger.warning(f"CVD: MARGIN BLOCKED {pair} {order_type} {order_volume_lots} lots — skipping")
                        PairLock.objects.filter(symbol=pair).delete()
                        continue
                except Exception as e:
                    logger.debug(f"CVD: Margin check unavailable ({e}), proceeding with trade")

                # Send market order
                order = send_market_order(
                    symbol=pair,
                    volume=order_volume_lots,
                    order_type=order_type,
                    sl=round(sl_price, price_decimals),
                    tp=round(tp_price, price_decimals),
                    deviation=DEVIATION,
                    type_filling="ORDER_FILLING_IOC",
                    position_size_usd=order_size_usd,
                    commission=commission,
                    capital=order_capital,
                    leverage=LEVERAGE,
                )

                if order is not None:
                    # Update PairLock with actual ticket
                    order_ticket = order.get('order', 0)
                    PairLock.objects.filter(symbol=pair).update(ticket=order_ticket)
                    positions_opened += 1

                    logger.info({
                        'event': 'cvd_trade_opened',
                        'symbol': pair,
                        'type': order_type,
                        'strategy': custom.name,
                        'signal': signal_desc,
                        'capital': f"${order_capital:.2f}",
                        'size_multiplier': f"{size_multiplier:.2f}",
                        'kill_zone': kz_name or 'none',
                        'kz_weight': f"{kz_mult:.2f}",
                        'sl': f"{sl_price:.{price_decimals}f}",
                        'tp': f"{tp_price:.{price_decimals}f}",
                        'atr': f"{atr_val:.{price_decimals}f}",
                        'sl_tp_source': sl_tp_source,
                        'confluence_score': confluence_score.total_score if confluence_score else None,
                        'confluence_band': confluence_score.band if confluence_score else None,
                        'router_regime': routing.regime if 'routing' in dir() else None,
                        'router_mult': f"{router_mult:.2f}",
                        'router_sl_adj': f"{router_sl_adj:.2f}",
                    })

                    try:
                        trade_result = create_trade(
                            order, pair, order_capital, order_size_usd,
                            LEVERAGE, commission, order_type, 'Alpari',
                            _get_market_type(pair), f'CVD_{custom.name}', timeframe, order_volume_lots,
                            sl_price, tp_price,
                        )

                        # Save Phase 1C fields on the Trade record
                        if trade_result:
                            trade_obj = trade_result[0] if isinstance(trade_result, tuple) else trade_result
                            try:
                                update_fields = []
                                if hasattr(trade_obj, 'entry_atr'):
                                    trade_obj.entry_atr = atr_val
                                    update_fields.append('entry_atr')
                                if hasattr(trade_obj, 'entry_timeframe'):
                                    trade_obj.entry_timeframe = timeframe.value
                                    update_fields.append('entry_timeframe')
                                if hasattr(trade_obj, 'strategy_config'):
                                    trade_obj.strategy_config = strategy_config
                                    update_fields.append('strategy_config')
                                if update_fields:
                                    trade_obj.save(update_fields=update_fields)
                            except Exception as e:
                                logger.warning(f"CVD: Could not save Phase 1C trade fields: {e}")

                            # Store ML features linked to this trade
                            try:
                                from app.nexus.models import TradeFeature
                                TradeFeature.objects.create(
                                    trade=trade_obj,
                                    features_json=ml_features,
                                    ml_score=ml_score,
                                    ml_accepted=ml_accept,
                                )
                                logger.info(f"CVD: ML features stored for trade #{trade_obj.id}")
                            except Exception as e:
                                logger.warning(f"CVD: Could not save ML features: {e}")

                            # Store scale-in data in Redis for position manager
                            if remaining_volume_lots > 0:
                                try:
                                    from django.core.cache import cache
                                    ticket = order.get('order', 0)
                                    cache.set(
                                        f'scale_in_remaining:{ticket}',
                                        remaining_volume_lots,
                                        timeout=3600,  # 1 hour
                                    )
                                    cache.set(
                                        f'scale_in_atr:{ticket}',
                                        atr_val,
                                        timeout=3600,
                                    )
                                    cache.set(
                                        f'scale_in_full_volume:{ticket}',
                                        full_volume_lots,
                                        timeout=3600,
                                    )
                                    logger.info(
                                        f"CVD: Scale-in data stored for ticket {ticket}: "
                                        f"remaining={remaining_volume_lots} lots, "
                                        f"entry_atr={atr_val:.6f}"
                                    )
                                except Exception as e:
                                    logger.warning(f"CVD: Could not store scale-in data: {e}")

                    except Exception as e:
                        logger.error(f"CVD: Error creating trade record: {e}\n{traceback.format_exc()}")
                else:
                    # Order failed — release PairLock
                    PairLock.objects.filter(symbol=pair).delete()
                    logger.error({
                        'event': 'cvd_trade_failed',
                        'symbol': pair,
                        'type': order_type,
                        'strategy': custom.name,
                        'volume': order_volume_lots,
                        'sl': round(sl_price, price_decimals),
                        'tp': round(tp_price, price_decimals),
                        'last_tick': round(last_tick_price, price_decimals),
                        'hint': 'check R:R or MT5 rejection in order.py logs',
                    })

            except Exception as e:
                PairLock.objects.filter(symbol=pair).delete()
                logger.error(f"Order failed for {pair}: {e}\n{traceback.format_exc()}")

    except Exception as e:
        logger.error(f"Exception in cvd_entry_algorithm: {e}\n{traceback.format_exc()}")


def entry_algorithm():
    """Legacy entry point — backward compatible wrapper.

    Called by older code paths that don't pass strategy_config.
    Loads the first active custom strategy and delegates to cvd_entry_algorithm.
    """
    try:
        strategy_config, custom = _load_active_custom_strategy()
        if custom is None:
            logger.warning("No CustomStrategy linked to active StrategyConfig.")
            return
        cvd_entry_algorithm(strategy_config, MAX_OPEN_TRADES)
    except Exception as e:
        logger.error(f"Exception in legacy entry_algorithm: {e}\n{traceback.format_exc()}")
