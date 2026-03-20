"""
Position Manager — minimal version.

Broker SL/TP handles exits. This is just a safety net:
  - Hard loss ceiling at €50 (catches gaps past SL)
  - Track max profit / max drawdown for analytics

Called every 15 seconds by Celery beat.
No trailing. No breakeven. No partial close. No time exit.
The backtest proved the edge with just SL/TP — that's what we run.
"""

import logging
from datetime import datetime, timezone

from app.utils.api.positions import get_positions
from app.utils.api.order import close_full
from app.utils.db.get import get_trade_with_mutations

logger = logging.getLogger('position_manager')

# Hard loss ceiling — the only management rule
MAX_LOSS_PER_TRADE_EUR = 50.0


def manage_positions():
    """Check all open positions. Close any that exceed the loss ceiling."""
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
    """Check a single position against the hard loss ceiling."""
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

    # Track max profit / max drawdown (analytics only, no action)
    _update_tracking(trade, current_pnl)

    # Hard loss ceiling — the only exit rule besides broker SL/TP
    if current_pnl < -MAX_LOSS_PER_TRADE_EUR:
        result = close_full(position.ticket, position.symbol, position.type, position.volume)
        if result is not None:
            logger.warning(
                'HARD CEILING: %s ticket=%s pnl=%.2f exceeded -%.0f — CLOSED',
                position.symbol, position.ticket, current_pnl, MAX_LOSS_PER_TRADE_EUR,
            )


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
