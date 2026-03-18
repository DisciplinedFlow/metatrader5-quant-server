"""
Brain Entry Algorithm — lightweight execution layer.

Python's job:
  - Fetch MT5 OHLCV bars and tick data (fast API endpoints)
  - Run pure-math signal detection (FVG, CVD proxy, HTF bias, session)
  - Execute order with ATR SL/TP
  - Simple circuit breaker (5 losses → 30min pause)

Neo4j brain's job:
  - Pattern matching against historical + live trade outcomes
  - Win rate / expectancy reference
  - Deciding confidence level
  - Learning from every closed trade

Haiku's job (async, non-blocking — see intelligence/claude_analyst.py):
  - Label the pattern after every close
  - Update StrategyPattern node with human-readable description
  - Weekly: scan all patterns, identify new edges, mark dead ones

The brain is the only gate.
"""

from __future__ import annotations

import logging
from typing import Optional

from django.core.cache import cache

from app.utils.api.data import fetch_data_pos_batch
from app.utils.api.order import send_market_order
from app.utils.arithmetics import calculate_risk_based_lots
from app.utils.api.positions import get_positions
from app.utils.constants import MT5Timeframe

logger = logging.getLogger('quant')

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCAN_SYMBOLS = [
    'XAUUSD', 'XAGUSD',           # Metals — highest brain WR
    'NG-C', 'UKOUSDft', 'USOUSD', # Energy
    'EURUSD', 'GBPUSD', 'USDJPY', # Forex
]

H4_BARS = 50                    # enough for EMA34 warmup + FVG lookback
SL_ATR_MULT = 1.8               # default
TP_ATR_MULT = 3.6               # 1:2 R:R
ENERGY_SL_ATR = 2.0
ENERGY_TP_ATR = 4.0

_ENERGY = frozenset(['USOUSD', 'UKOUSDft', 'NG-C', 'NATGAS', 'XNGUSD'])
_MAX_OPEN_POSITIONS = 5
_CIRCUIT_BREAKER_LOSSES = 5
_CIRCUIT_BREAKER_TTL = 1800     # 30 minutes
_SYMBOL_COOLDOWN_TTL = 300      # 5 minutes after any entry


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def brain_entry_algorithm():
    """
    Scan each symbol. Detect signals. Query brain. Execute if confident.
    Called every 5 minutes from Celery beat.
    """
    if _circuit_broken():
        return

    open_positions = _open_position_symbols()
    if len(open_positions) >= _MAX_OPEN_POSITIONS:
        logger.debug(f"[brain] Max positions reached ({_MAX_OPEN_POSITIONS})")
        return

    from app.quant.knowledge.connection import get_graph
    graph = get_graph()

    # Pre-fetch all symbol bars in one batch request
    bars_batch = fetch_data_pos_batch(SCAN_SYMBOLS, MT5Timeframe.H4, H4_BARS)

    for symbol in SCAN_SYMBOLS:
        if symbol in open_positions:
            continue
        if cache.get(f'brain_cooldown:{symbol}'):
            continue

        df = bars_batch.get(symbol)
        bars = df.to_dict('records') if (df is not None and not df.empty) else []
        if not bars:
            continue

        signals = _detect_signals(bars)
        if not signals:
            continue

        # Ask the brain for BOTH directions — take the stronger one
        best_advice = None
        best_direction = None

        for direction in ['bullish', 'bearish']:
            # Skip if HTF bias is strongly opposing
            if signals['htf_bias'] not in (direction, 'neutral'):
                continue

            conditions = _build_conditions(direction, signals)
            if graph:
                advice = graph.query_best_pattern(
                    symbol=symbol,
                    direction=direction,
                    active_conditions=conditions,
                    min_wr=0.58,
                    min_sample=3,
                )
            else:
                advice = None

            if advice and (best_advice is None or advice['score'] > best_advice['score']):
                best_advice = advice
                best_direction = direction

        if best_advice and best_direction:
            _execute(symbol, best_direction, signals, best_advice)


# ---------------------------------------------------------------------------
# Signal detection — pure math, no external calls beyond MT5
# ---------------------------------------------------------------------------

def _detect_signals(bars: list[dict]) -> Optional[dict]:
    """
    Compute all pattern signals from H4 OHLCV bars.
    Returns None if bars are insufficient.
    """
    if len(bars) < 36:
        return None

    try:
        from app.quant.knowledge.pattern_detector import (
            compute_htf_bias,
            detect_fvgs,
            mark_fvg_mitigations,
            compute_cvd_proxy,
            _compute_atr,
            _classify_session,
            _parse_bar_time,
        )
    except ImportError:
        return None

    atrs = _compute_atr(bars)
    atr = next((a for a in reversed(atrs) if a), None)
    if not atr:
        return None

    biases = compute_htf_bias(bars)
    htf_bias = biases[-1] or 'neutral'

    fvgs = detect_fvgs(bars)
    mark_fvg_mitigations(bars, fvgs)

    last_price = bars[-1]['close']
    last_bar_time = _parse_bar_time(bars[-1]['time'])
    session = _classify_session(last_bar_time)

    # Unmitigated FVGs within 2×ATR of current price
    fvg_bull = any(
        f for f in fvgs
        if f.direction == 'bullish' and not f.mitigated
        and abs(last_price - (f.high + f.low) / 2) <= 2 * atr
    )
    fvg_bear = any(
        f for f in fvgs
        if f.direction == 'bearish' and not f.mitigated
        and abs(last_price - (f.high + f.low) / 2) <= 2 * atr
    )

    # CVD proxy direction
    cvd_bars = compute_cvd_proxy(bars)
    cvd_direction = _cvd_direction(cvd_bars)

    return {
        'atr': atr,
        'htf_bias': htf_bias,
        'session': session,
        'fvg_bullish': fvg_bull,
        'fvg_bearish': fvg_bear,
        'cvd_direction': cvd_direction,
        'last_price': last_price,
    }


def _cvd_direction(cvd_bars) -> Optional[str]:
    """Return 'bullish' or 'bearish' based on last 5-bar CVD trend."""
    if len(cvd_bars) < 6:
        return None
    recent = cvd_bars[-5:]
    delta = recent[-1].cumulative - recent[0].cumulative
    if delta > 0:
        return 'bullish'
    elif delta < 0:
        return 'bearish'
    return None


def _build_conditions(direction: str, signals: dict) -> list[str]:
    """Build the condition list to match against StrategyPattern nodes."""
    conds = []
    if signals.get(f'fvg_{direction}'):
        conds.append('fvg_present')
    if signals.get('cvd_direction') == direction:
        conds.append('cvd_divergence')
    if signals.get('htf_bias') == direction:
        conds.append('htf_aligned')
    sess = (signals.get('session') or 'unknown').lower()
    conds.append(f'session_{sess}')
    return conds


# ---------------------------------------------------------------------------
# Order execution
# ---------------------------------------------------------------------------

def _execute(symbol: str, direction: str, signals: dict, advice: dict):
    """Place order and cache pattern fingerprint for post-close update."""
    atr = signals['atr']
    sl_mult = ENERGY_SL_ATR if symbol in _ENERGY else SL_ATR_MULT
    tp_mult = ENERGY_TP_ATR if symbol in _ENERGY else TP_ATR_MULT

    sl_distance = sl_mult * atr
    tp_distance = tp_mult * atr
    entry = signals['last_price']

    order_type = 'buy' if direction == 'bullish' else 'sell'
    sl = entry - sl_distance if direction == 'bullish' else entry + sl_distance
    tp = entry + tp_distance if direction == 'bullish' else entry - tp_distance

    logger.info(
        f"[brain] {symbol} {direction.upper()} | "
        f"pattern={advice.get('fingerprint', '?')} | "
        f"WR={advice.get('win_rate', 0):.0%} n={advice.get('total', 0)} | "
        f"E(R)={advice.get('avg_r', 0):.2f} | "
        f"session={signals['session']} htf={signals['htf_bias']}"
    )

    try:
        volume = calculate_risk_based_lots(
            symbol=symbol,
            sl_distance=sl_distance,
            target_risk=50.0,
            order_type=order_type.upper(),
        )
        if not volume or volume <= 0:
            logger.warning(f"[brain] Could not calculate volume for {symbol}")
            return

        result = send_market_order(
            symbol=symbol,
            volume=volume,
            order_type=order_type.upper(),
            sl=round(sl, 5),
            tp=round(tp, 5),
            comment='brain',
            min_rr=1.85,
        )

        ticket = result.get('order') or result.get('ticket') if result else None
        if ticket:
            cache.set(f'brain_pattern:{ticket}', advice.get('fingerprint', ''), timeout=86400)
            cache.set(f'brain_cooldown:{symbol}', True, timeout=_SYMBOL_COOLDOWN_TTL)
            _increment_consecutive_losses(won=False, reset=True)
            logger.info(f"[brain] Order placed ticket={ticket} vol={volume}")
        else:
            logger.warning(f"[brain] Order rejected for {symbol}: {result}")

    except Exception as e:
        logger.error(f"[brain] Order error {symbol}: {e}")


def _open_position_symbols() -> set:
    """Return set of symbols with open MT5 positions."""
    try:
        positions = get_positions()
        if positions is None:
            return set()
        if hasattr(positions, 'empty'):
            return set() if positions.empty else set(positions['symbol'].values)
        if isinstance(positions, list):
            return {p.get('symbol') for p in positions if p.get('symbol')}
        return set()
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Circuit breaker — simple, no Redis complexity
# ---------------------------------------------------------------------------

_CB_KEY = 'brain:circuit_breaker'
_LOSS_KEY = 'brain:consecutive_losses'


def _circuit_broken() -> bool:
    active = bool(cache.get(_CB_KEY))
    if active:
        logger.debug("[brain] Circuit breaker active — skipping scan")
    return active


def _increment_consecutive_losses(won: bool, reset: bool = False):
    """Track consecutive losses. Trip breaker at threshold."""
    if reset:
        cache.set(_LOSS_KEY, 0, timeout=86400)
        return

    losses = (cache.get(_LOSS_KEY) or 0)
    if not won:
        losses += 1
        cache.set(_LOSS_KEY, losses, timeout=86400)
        if losses >= _CIRCUIT_BREAKER_LOSSES:
            cache.set(_CB_KEY, True, timeout=_CIRCUIT_BREAKER_TTL)
            logger.warning(f"[brain] Circuit breaker tripped — {losses} consecutive losses")
    else:
        cache.set(_LOSS_KEY, 0, timeout=86400)
