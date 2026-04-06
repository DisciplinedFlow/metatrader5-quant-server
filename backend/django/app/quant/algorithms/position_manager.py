"""
Position Manager — dynamic trailing stop + safety net.

Three layers of protection:
  1. Hard loss ceiling at €50 (catches gaps past broker SL)
  2. Breakeven move: once trade reaches +1R profit, move SL to entry price
  3. Dynamic trail: once trade reaches +1.5R, trail SL at 50% of max profit

Called every 15 seconds by Celery beat.

Design rationale (2026-04-06):
  Extreme vol environment (Hormuz crisis, VIX 24+). Pure SL/TP gives back
  too much profit on reversals. This trail protects gains without cutting
  winners too early. The 1R/1.5R thresholds ensure the trade has proven
  itself before we interfere.
"""

import logging
from datetime import datetime, timezone

from django.core.cache import cache

from app.utils.api.positions import get_positions
from app.utils.api.order import close_full
from app.utils.api.session import get_session, BASE_URL
from app.utils.db.get import get_trade_with_mutations

logger = logging.getLogger('position_manager')

# --- Configuration ---
MAX_LOSS_PER_TRADE_EUR = 20.0

# Trailing stop thresholds (in multiples of initial risk)
# Aggressive protection — data showed trades peaking +€15-22 then reversing to SL
BREAKEVEN_TRIGGER_R = 0.5    # Move SL to entry when profit = 0.5x risk (~€7.50)
TRAIL_TRIGGER_R = 0.75       # Start trailing when profit = 0.75x risk (~€11)
TRAIL_GIVEBACK_PCT = 0.40    # Trail at 40% giveback (keep 60% of max profit)


def manage_positions():
    """Check all open positions: trail, breakeven, hard ceiling."""
    try:
        positions = get_positions()
        if positions is None or positions.empty:
            return

        for _, position in positions.iterrows():
            try:
                _check_position(position)
            except Exception as e:
                logger.error('Error checking ticket %s: %s', position.ticket, e)

    except Exception as e:
        logger.error('Position manager error: %s', e)


def _check_position(position):
    """Run all position management layers for a single position."""
    trade_data = get_trade_with_mutations(position.ticket)

    # Orphan protection: close orphan positions that are losing
    if trade_data is None:
        if position.profit < -MAX_LOSS_PER_TRADE_EUR:
            result = close_full(position.ticket, position.symbol, position.type, position.volume)
            if result is not None:
                logger.warning(
                    'ORPHAN CLOSED: %s ticket=%s loss=%.2f exceeded ceiling',
                    position.symbol, position.ticket, position.profit,
                )
        return

    trade = trade_data.get('trade')
    if trade is None:
        return

    current_pnl = position.profit

    # Track max profit / max drawdown
    _update_tracking(trade, current_pnl)

    # Layer 1: Hard loss ceiling
    if current_pnl < -MAX_LOSS_PER_TRADE_EUR:
        result = close_full(position.ticket, position.symbol, position.type, position.volume)
        if result is not None:
            logger.warning(
                'HARD CEILING: %s ticket=%s pnl=%.2f exceeded -%.0f — CLOSED',
                position.symbol, position.ticket, current_pnl, MAX_LOSS_PER_TRADE_EUR,
            )
        return

    # Layer 2 & 3: Breakeven + Dynamic trail (only if we know initial risk)
    _manage_trail(position, trade, current_pnl)


def _manage_trail(position, trade, current_pnl):
    """Breakeven move + dynamic trailing stop based on R-multiples."""
    entry_price = trade.entry_price
    if not entry_price:
        return

    is_buy = position.type == 0  # MT5: 0=BUY, 1=SELL
    ticket = int(position.ticket)

    # Cache original risk on first encounter — survives SL moves
    # Once we move SL to breakeven, position.sl changes and we'd lose the original risk
    cache_key = f'pm:risk:{ticket}'
    initial_risk_price = cache.get(cache_key)

    if initial_risk_price is None:
        # First time seeing this position — calculate and store original risk
        current_sl = position.sl
        if not current_sl or current_sl == 0:
            return
        initial_risk_price = abs(entry_price - current_sl)
        if initial_risk_price <= 0:
            return
        # Cache for 48h (covers weekend + overnight holds)
        cache.set(cache_key, initial_risk_price, timeout=172800)
        logger.info('TRAIL INIT: %s ticket=%s initial_risk=%.5f', position.symbol, ticket, initial_risk_price)

    # Current distance from entry in price terms
    current_price = position.price_current
    price_profit = (current_price - entry_price) if is_buy else (entry_price - current_price)

    # R-multiple: how many R's of profit
    r_multiple = price_profit / initial_risk_price

    # Current broker SL
    current_sl = position.sl

    # --- Breakeven: move SL to entry when trade reaches +1R ---
    if r_multiple >= BREAKEVEN_TRIGGER_R:
        # Target SL = entry price (+ tiny buffer for spread)
        buffer = initial_risk_price * 0.05  # 5% of risk as spread buffer
        be_sl = (entry_price + buffer) if is_buy else (entry_price - buffer)

        # Only move SL if it improves the position
        sl_improves = (is_buy and be_sl > current_sl) or (not is_buy and be_sl < current_sl)

        if sl_improves and not trade.breakeven_moved:
            new_sl = _move_sl(position, be_sl)
            if new_sl is not None:
                trade.breakeven_moved = True
                trade.save(update_fields=['breakeven_moved'])
                logger.info(
                    'BREAKEVEN: %s ticket=%s R=%.2f SL moved %s → %s',
                    position.symbol, position.ticket, r_multiple,
                    f'{current_sl:.5f}', f'{be_sl:.5f}',
                )

    # --- Dynamic trail: trail at 50% giveback once +1.5R ---
    if r_multiple >= TRAIL_TRIGGER_R and trade.max_profit is not None and trade.max_profit > 0:
        # Trail level = entry + (max_profit * keep_pct) converted to price
        max_price_profit = (trade.max_profit / position.volume) if position.volume > 0 else 0
        # Use tick value to convert EUR profit back to price distance
        # Simpler approach: trail at percentage of best price reached
        if is_buy:
            best_price = entry_price + max_price_profit
            trail_sl = best_price - (max_price_profit * TRAIL_GIVEBACK_PCT)
        else:
            best_price = entry_price - max_price_profit
            trail_sl = best_price + (max_price_profit * TRAIL_GIVEBACK_PCT)

        # Round to appropriate decimal places
        decimals = 2 if 'XAU' in position.symbol else 3 if 'XAG' in position.symbol else 5
        trail_sl = round(trail_sl, decimals)

        # Only move SL if it improves the position
        sl_improves = (is_buy and trail_sl > current_sl) or (not is_buy and trail_sl < current_sl)

        if sl_improves:
            new_sl = _move_sl(position, trail_sl)
            if new_sl is not None:
                logger.info(
                    'TRAIL: %s ticket=%s R=%.2f max_profit=%.2f SL moved %s → %s',
                    position.symbol, position.ticket, r_multiple,
                    trade.max_profit, f'{current_sl:.5f}', f'{trail_sl:.5f}',
                )


def _move_sl(position, new_sl):
    """Send SL modification to MT5."""
    try:
        session = get_session()
        response = session.post(f'{BASE_URL}/modify_sl_tp', json={
            'position': int(position.ticket),
            'sl': float(new_sl),
            'tp': float(position.tp),
        }, timeout=10)
        if response.status_code == 200:
            return new_sl
        logger.warning('SL modify failed %s: %s', position.ticket, response.text)
    except Exception as e:
        logger.error('SL modify error %s: %s', position.ticket, e)
    return None


def _update_tracking(trade, current_pnl):
    """Update max_profit and max_drawdown for post-trade analytics."""
    updates = []
    if trade.max_profit is None or current_pnl > trade.max_profit:
        trade.max_profit = current_pnl
        updates.append('max_profit')
    if trade.max_drawdown is None or current_pnl < trade.max_drawdown:
        trade.max_drawdown = current_pnl
        updates.append('max_drawdown')
    if updates:
        trade.save(update_fields=updates)
