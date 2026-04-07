"""
Position Manager — peak profit drawback + dynamic equity sizing.

Two exit rules:
  1. Hard loss ceiling (catches gaps past broker SL)
  2. Peak drawback: once trade peaks at €X and drops €5 from peak → close
     Captures ~85% of peak profits instead of riding back to SL

Dynamic sizing:
  Risk = 2% of account equity (not fixed €7.50)
  €200 equity → €4/trade, €500 → €10, €1000 → €20, €5000 → €100

Called every 15 seconds by Celery beat.
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
MAX_LOSS_PER_TRADE_EUR = 15.0     # Hard ceiling — catches gaps past broker SL

# Peak drawback exit — the core profit-capture mechanism
MIN_PROFIT_TO_PROTECT = 5.0       # Don't trigger drawback until trade made ≥€5
MAX_DRAWBACK_EUR = 5.0            # Close if profit drops €5 from peak
# Example: peak=€30, current=€25 → drawback=€5 → CLOSE at €25 (captured 83%)
# Example: peak=€10, current=€5  → drawback=€5 → CLOSE at €5  (captured 50%)
# Example: peak=€4,  current=€2  → drawback=€2 → NO (peak < MIN_PROFIT_TO_PROTECT)

# Dynamic position sizing
RISK_PCT = 0.02                   # 2% of account equity per trade
RISK_PCT_KEY = 'pm:risk_pct'      # Redis key (can be changed via API/dashboard)
EQUITY_CACHE_KEY = 'pm:equity'
EQUITY_CACHE_TTL = 300            # Refresh equity every 5 min


def get_dynamic_risk():
    """Calculate risk per trade based on account equity.

    Returns risk in EUR. Falls back to €7.50 if equity unavailable.
    """
    try:
        equity = cache.get(EQUITY_CACHE_KEY)
        if equity is None:
            # Fetch from MT5
            session = get_session()
            resp = session.get(f'{BASE_URL}/account_info', timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                equity = float(data.get('equity', 0))
                cache.set(EQUITY_CACHE_KEY, equity, timeout=EQUITY_CACHE_TTL)
            else:
                return 7.50  # Fallback

        risk_pct = cache.get(RISK_PCT_KEY) or RISK_PCT
        risk = float(equity) * float(risk_pct)
        # Clamp: min €2, max €20 (prevents oversizing on larger accounts during testing)
        return max(2.0, min(20.0, risk))
    except Exception as e:
        logger.debug('Equity fetch failed: %s', e)
        return 7.50


def manage_positions():
    """Check all open positions: drawback exit, hard ceiling."""
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

    # Track max profit / max drawdown (every 15s)
    _update_tracking(trade, current_pnl)

    # Layer 1: Hard loss ceiling
    if current_pnl < -MAX_LOSS_PER_TRADE_EUR:
        result = close_full(position.ticket, position.symbol, position.type, position.volume)
        if result is not None:
            logger.warning(
                'HARD CEILING: %s ticket=%s pnl=%.2f — CLOSED',
                position.symbol, position.ticket, current_pnl,
            )
        return

    # Layer 2: Peak drawback exit
    _check_drawback(position, trade, current_pnl)


def _check_drawback(position, trade, current_pnl):
    """Close trade if profit has dropped too far from peak.

    Logic:
      - Trade must have reached MIN_PROFIT_TO_PROTECT (€5)
      - If current profit is MAX_DRAWBACK_EUR (€5) below peak → close
      - This captures ~83-90% of peak profits on good trades
    """
    max_profit = trade.max_profit
    if max_profit is None or max_profit < MIN_PROFIT_TO_PROTECT:
        return  # Trade hasn't proven itself yet — let it run

    drawback = max_profit - current_pnl
    if drawback >= MAX_DRAWBACK_EUR:
        # Close the trade — lock in profits
        result = close_full(position.ticket, position.symbol, position.type, position.volume)
        if result is not None:
            captured_pct = (current_pnl / max_profit * 100) if max_profit > 0 else 0
            logger.info(
                'DRAWBACK EXIT: %s ticket=%s | peak=%.2f current=%.2f drawback=%.2f | '
                'captured %.0f%% of peak profit',
                position.symbol, position.ticket, max_profit, current_pnl,
                drawback, captured_pct,
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
