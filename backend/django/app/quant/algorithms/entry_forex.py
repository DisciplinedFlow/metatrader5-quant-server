"""
entry_forex.py — MTF-driven Forex Entry

Signal source: MTFEngine (tick consumer builds live M5/M15/H1 bars,
               evaluates ADX + MACD + RSI + structure + FVG/sweep).

Execution:     MT5 Flask API (port 5001), risk-based lot sizing.

Fires when:    H1 trend confirmed (ADX>20, MACD direction, RSI not extreme)
               AND (M15 structure OR M5 FVG/sweep) aligns.

Called from:   - Celery beat every 60s (safety net)
               - tick_consumer directly when MTF signal fires (fast path)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.core.cache import cache

from app.utils.api.order import send_market_order
from app.utils.api.positions import get_positions
from app.utils.arithmetics import calculate_risk_based_lots

logger = logging.getLogger('quant')

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYMBOLS = [
    # Metals — 24/7
    'XAUUSD', 'XAUEUR', 'XAUAUD', 'XAUJPY', 'XAGUSD',
    # Energy — 24/7
    'USOUSD', 'UKOUSDft', 'NG-C',
    # Forex — London + NY session
    'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD',
    'USDCAD', 'USDCHF', 'EURGBP', 'USDSEK',
    # US stocks — US session only
    'AMD', 'MSFT',
]

_ENERGY       = frozenset(['USOUSD', 'UKOUSDft', 'NG-C'])
_SILVER       = frozenset(['XAGUSD'])
_GOLD_CROSS   = frozenset(['XAUEUR', 'XAUAUD', 'XAUJPY'])
_US_STOCKS    = frozenset(['AMD', 'MSFT'])
# Exotic forex pairs: low tick_value + small ATR → huge lot sizes without a cap
_EXOTICS      = frozenset(['USDSEK'])
_NO_SESSION   = frozenset(['XAUUSD', 'XAGUSD', 'XAUEUR', 'XAUAUD', 'XAUJPY',
                            'USOUSD', 'UKOUSDft', 'NG-C'])  # 24/7

SL_ATR_MULT   = 1.8
TP_ATR_MULT   = 3.6
ENERGY_SL     = 2.0
ENERGY_TP     = 4.0

CAPITAL       = 2000.0
ENERGY_CAP    = 300.0
SILVER_CAP    = 150.0
GOLD_CROSS_CAP = 1000.0
STOCK_CAP     = 500.0
EXOTIC_CAP    = 200.0    # Low capital for exotics — their tick_value makes sizing unstable

# Hard lot cap per category: prevents formula blow-up on exotic/low-tick pairs
MAX_LOT_DEFAULT = 2.0    # Standard forex (EURUSD etc.)
MAX_LOT_EXOTIC  = 1.0    # USDCNH, USDSEK — tick_value too small for large lots
MAX_LOT_STOCK   = 5.0    # Stocks have higher notional but normal sizing

# Per-symbol daily loss limit — stop re-entering a bleeding symbol
SYMBOL_DAILY_LOSS_LIMIT = 150.0   # Skip symbol if it has lost >$150 today (UTC day)
_LOSS_CHECK_TTL = 60              # Cache the DB query result for 60s

MAX_OPEN      = 8         # more symbols → allow more concurrent positions
COOLDOWN_TTL  = 300

_SESSIONS     = [(7, 10), (13, 17)]   # London + London-NY overlap (UTC)
_US_SESSIONS  = [(14, 21)]            # US market hours (UTC)

# Circuit breaker
_CB_KEY       = 'forex_entry:circuit_breaker'
_LOSS_KEY     = 'forex_entry:consecutive_losses'
_CB_LOSSES    = 5
_CB_TTL       = 1800


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def entry_forex_algorithm():
    """Check MTF signals cached by tick_consumer and execute if valid."""
    if _circuit_broken():
        return

    open_positions = _open_symbols()
    if len(open_positions) >= MAX_OPEN:
        return

    for symbol in SYMBOLS:
        if symbol in open_positions:
            continue
        if cache.get(f'forex_cooldown:{symbol}'):
            continue
        if symbol in _US_STOCKS and not _in_us_session():
            continue
        if symbol not in _NO_SESSION and symbol not in _US_STOCKS and not _in_session():
            continue

        # Per-symbol daily loss gate — stop re-entering a bleeding symbol
        if _symbol_daily_loss_exceeded(symbol):
            continue

        # Atomically claim the signal — prevents race condition between Celery beat
        # and tick_consumer both grabbing the same signal simultaneously (→ duplicate orders)
        signal_key = f'mtf_signal:{symbol}'
        exec_key   = f'mtf_exec:{symbol}'
        if not cache.add(exec_key, 1, timeout=30):
            continue  # Another worker is already processing this signal
        signal = cache.get(signal_key)
        if not signal:
            cache.delete(exec_key)
            continue
        cache.delete(signal_key)   # consume before executing

        logger.info(
            '[entry_forex] %s %s setup=%s reason=%s level=%s atr=%.5f',
            symbol, signal['direction'].upper(),
            signal['setup'], signal['reason'],
            f"{signal['level']:.5f}" if signal.get('level') else 'market',
            signal['atr'],
        )
        _execute(symbol, signal)
        cache.delete(exec_key)  # release lock after execution


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _execute(symbol: str, signal: dict):
    direction = signal['direction']
    atr_val   = signal['atr']
    level     = signal.get('level')   # may be None → use market price

    if symbol in _ENERGY:
        sl_mult, capital = ENERGY_SL, ENERGY_CAP
    elif symbol in _SILVER:
        sl_mult, capital = 2.5, SILVER_CAP
    elif symbol in _GOLD_CROSS:
        sl_mult, capital = SL_ATR_MULT, GOLD_CROSS_CAP
    elif symbol in _US_STOCKS:
        sl_mult, capital = 1.5, STOCK_CAP
    elif symbol in _EXOTICS:
        sl_mult, capital = SL_ATR_MULT, EXOTIC_CAP
    else:
        sl_mult, capital = SL_ATR_MULT, CAPITAL

    sl_dist = sl_mult * atr_val

    # Fetch live price — needed for TP in both paths to guarantee 2:1 R:R from fill
    from app.utils.api.data import symbol_info_tick
    tick = symbol_info_tick(symbol)
    if tick is None or tick.empty:
        logger.warning('[entry_forex] No tick data for %s — cannot compute SL/TP, skipping', symbol)
        return
    fill_ref = float(tick['ask'].iloc[0]) if direction == 'buy' else float(tick['bid'].iloc[0])

    if level:
        # SL anchored to structural level (logical invalidation point)
        sl = level - sl_dist if direction == 'buy' else level + sl_dist
        # TP computed from fill price so R:R is always exactly 2:1 from entry
        risk = abs(fill_ref - sl)
        tp = fill_ref + risk * 2 if direction == 'buy' else fill_ref - risk * 2
    else:
        # No FVG/sweep level (structure or CVD signal) — anchor both to live price
        sl = fill_ref - sl_dist if direction == 'buy' else fill_ref + sl_dist
        tp = fill_ref + sl_dist * 2 if direction == 'buy' else fill_ref - sl_dist * 2

    try:
        volume = calculate_risk_based_lots(
            symbol=symbol,
            sl_distance=sl_dist,
            target_risk=capital,
            order_type=direction.upper(),
        )
        if not volume or volume <= 0:
            logger.warning('[entry_forex] Could not size %s', symbol)
            return

        # Hard lot cap — prevents formula blow-up on exotic/low-tick pairs
        if symbol in _EXOTICS:
            max_lot = MAX_LOT_EXOTIC
        elif symbol in _US_STOCKS:
            max_lot = MAX_LOT_STOCK
        else:
            max_lot = MAX_LOT_DEFAULT
        if volume > max_lot:
            logger.warning(
                '[entry_forex] %s lot cap: %.2f -> %.2f (capital=%.0f sl_dist=%.5f)',
                symbol, volume, max_lot, capital, sl_dist,
            )
            volume = max_lot

        result = send_market_order(
            symbol=symbol,
            volume=volume,
            order_type=direction.upper(),
            sl=round(sl, 5) if sl else None,
            tp=round(tp, 5) if tp else None,
            min_rr=1.95,
        )

        ticket = result.get('order') or result.get('ticket') if result else None
        if ticket:
            cache.set(f'forex_cooldown:{symbol}', True, timeout=COOLDOWN_TTL)
            _reset_losses()
            logger.info(
                '[entry_forex] ✓ %s %s ticket=%s vol=%s sl=%s tp=%s',
                symbol, direction.upper(), ticket, volume,
                f'{sl:.5f}' if sl else 'auto',
                f'{tp:.5f}' if tp else 'auto',
            )
            # Create Trade record immediately — avoids reconcile labelling as CVD_RECONCILED
            try:
                from app.utils.db.create import create_trade
                strategy_name = 'MTF_' + signal.get('reason', 'forex').upper().replace('+', '_')
                trade_obj, _ = create_trade(
                    order=result,
                    symbol=symbol,
                    capital=capital,
                    position_size_usd=0,
                    leverage=500,
                    commission=0,
                    type=direction.upper(),
                    broker='VantageInternational-Demo',
                    market='FOREX',
                    strategy=strategy_name,
                    timeframe='H1',
                    order_volume=volume,
                    sl=round(sl, 5) if sl else 0.0,
                    tp=round(tp, 5) if tp else None,
                )
                if trade_obj:
                    trade_obj.entry_atr = atr_val
                    trade_obj.entry_timeframe = 'H1'
                    trade_obj.save(update_fields=['entry_atr', 'entry_timeframe'])
            except Exception as e:
                logger.error('[entry_forex] Trade record creation failed %s: %s', symbol, e)
        else:
            logger.warning('[entry_forex] Order rejected %s: %s', symbol, result)

    except Exception as e:
        logger.error('[entry_forex] Error %s: %s', symbol, e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _in_session() -> bool:
    hour = datetime.now(timezone.utc).hour
    return any(start <= hour < end for start, end in _SESSIONS)


def _in_us_session() -> bool:
    hour = datetime.now(timezone.utc).hour
    return any(start <= hour < end for start, end in _US_SESSIONS)


def _open_symbols() -> set:
    try:
        data = get_positions()
        if isinstance(data, dict):
            positions = data.get('positions', [])
        elif hasattr(data, 'empty'):
            positions = [] if data.empty else data.to_dict('records')
        else:
            positions = data or []
        return {p.get('symbol') for p in positions if p.get('symbol')}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

def _circuit_broken() -> bool:
    if cache.get(_CB_KEY):
        logger.debug('[entry_forex] Circuit breaker active')
        return True
    return False


def _reset_losses():
    cache.set(_LOSS_KEY, 0, timeout=86400)


def _symbol_daily_loss_exceeded(symbol: str) -> bool:
    """Return True if symbol has already bled more than SYMBOL_DAILY_LOSS_LIMIT today.

    Queries Trade records for today (UTC midnight cutoff), cached for 60s to
    avoid a DB hit on every 60s Celery cycle.
    """
    db_key = f'symbol_loss_check:{symbol}'
    cached = cache.get(db_key)
    if cached is not None:
        return cached

    try:
        from app.nexus.models import Trade
        from django.db.models import Sum
        from datetime import timezone as _tz

        today_utc = datetime.now(_tz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        result = Trade.objects.filter(
            symbol=symbol,
            close_time__gte=today_utc,
            pnl__isnull=False,
        ).aggregate(total=Sum('pnl'))
        total = result['total'] or 0.0
        exceeded = total < -SYMBOL_DAILY_LOSS_LIMIT
        cache.set(db_key, exceeded, timeout=_LOSS_CHECK_TTL)
        if exceeded:
            logger.warning(
                '[entry_forex] %s daily loss gate: $%.2f < -$%.0f — skipping',
                symbol, total, SYMBOL_DAILY_LOSS_LIMIT,
            )
        return exceeded
    except Exception:
        return False  # Never block on error


def on_trade_closed(won: bool):
    """Call from close.py after every closed trade."""
    if won:
        cache.set(_LOSS_KEY, 0, timeout=86400)
        return
    losses = (cache.get(_LOSS_KEY) or 0) + 1
    cache.set(_LOSS_KEY, losses, timeout=86400)
    if losses >= _CB_LOSSES:
        cache.set(_CB_KEY, True, timeout=_CB_TTL)
        logger.warning('[entry_forex] Circuit breaker tripped — %d losses', losses)
