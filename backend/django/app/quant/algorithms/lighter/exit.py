"""
Lighter.xyz exit algorithm — monitors open positions for SL/TP/reversal exits
plus position management: breakeven, profit protection, and time exit.

Phases (applied in order):
1. BREAKEVEN: Move SL to entry price when unrealized profit exceeds 2% of entry
2. PROFIT PROTECTION: Close if profit was above $0.50 but dropped below 40% of peak
3. TIME EXIT: Close if open > 48 hours with less than 1% profit
4. SL/TP: Standard stop loss and take profit checks
"""
import logging
from datetime import timedelta
from django.utils import timezone

from .config import LIGHTER_MARKETS
from .client import get_best_bid_ask, close_position
from .entry import PLATFORM_PREFIX

logger = logging.getLogger('app.lighter')

# -- Position management thresholds --
BREAKEVEN_PROFIT_PCT = 0.02        # Move SL to entry after 2% unrealized profit
PROFIT_PROTECT_MIN_USD = 0.50      # Activate profit protection above $0.50
PROFIT_PROTECT_GIVEBACK = 0.40     # Close if profit drops below 40% of peak
TIME_EXIT_HOURS = 48               # Close stale positions after 48 hours
TIME_EXIT_MIN_PROFIT_PCT = 0.01    # ...unless profit exceeds 1%


def exit_algorithm():
    """Monitor Lighter positions and exit on SL/TP/signal reversal + position management."""
    from app.crypto.models import CryptoPosition, CryptoTrade

    open_positions = CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=PLATFORM_PREFIX,
    )
    if not open_positions.exists():
        return

    for position in open_positions:
        try:
            meta = LIGHTER_MARKETS.get(position.symbol)
            if meta is None:
                logger.warning("Lighter exit: unknown symbol %s", position.symbol)
                continue

            prices = get_best_bid_ask(position.symbol)
            current_price = prices.get('mid')
            if not current_price or current_price <= 0:
                continue

            # Calculate unrealized PnL
            pnl_usd = _calc_pnl(position, current_price)
            profit_pct = (current_price - position.entry_price) / position.entry_price
            if position.side == 'SHORT':
                profit_pct = -profit_pct

            # ── Phase 1: Breakeven move ──
            _check_breakeven(position, current_price, profit_pct)

            # ── Phase 2: Track peak profit & profit protection ──
            _update_peak_profit(position, pnl_usd)
            close_reason = _check_profit_protection(position, pnl_usd)

            # ── Phase 3: Time exit ──
            if not close_reason:
                close_reason = _check_time_exit(position, profit_pct)

            # ── Phase 4: Standard SL/TP checks ──
            if not close_reason:
                close_reason = _check_sl_tp(position, current_price)

            if not close_reason:
                continue

            # ── Execute close ──
            logger.info("Lighter EXIT: %s %s reason=%s price=%.4f pnl=$%.2f",
                         position.symbol, position.side, close_reason, current_price, pnl_usd)

            result = close_position(position.symbol)

            position.status = 'CLOSED'
            position.close_price = current_price
            position.pnl_usd = pnl_usd
            position.close_reason = close_reason
            position.closed_at = timezone.now()
            position.save()

            CryptoTrade.objects.create(
                position=position,
                order_id=result.get('tx_hash', '') if result else '',
                side='SELL' if position.side == 'LONG' else 'BUY',
                price=current_price,
                size=position.size,
                fee=0.0,
                status='FILLED',
            )

            logger.info("Lighter position closed: %s pnl=$%.2f reason=%s",
                         position.symbol, pnl_usd, close_reason)

        except Exception as e:
            logger.error("Lighter exit error for %s: %s", position.symbol, e)


# ---------------------------------------------------------------------------
# Phase 1: Breakeven
# ---------------------------------------------------------------------------

def _check_breakeven(position, current_price, profit_pct):
    """Move SL to entry price when unrealized profit exceeds 2%.

    Once breakeven is set, we never move it back. We detect it's already done
    by checking if stop_loss equals entry_price (within a tiny tolerance).
    """
    if profit_pct < BREAKEVEN_PROFIT_PCT:
        return

    # Already at breakeven or better?
    if position.stop_loss is not None:
        if position.side == 'LONG' and position.stop_loss >= position.entry_price:
            return
        if position.side == 'SHORT' and position.stop_loss <= position.entry_price:
            return

    old_sl = position.stop_loss
    position.stop_loss = position.entry_price
    position.save(update_fields=['stop_loss'])

    logger.info(
        "BREAKEVEN: %s %s moved SL from %s to entry %.4f (profit %.1f%%)",
        position.symbol, position.side,
        f"{old_sl:.4f}" if old_sl else "None",
        position.entry_price,
        profit_pct * 100,
    )


# ---------------------------------------------------------------------------
# Phase 2: Profit protection
# ---------------------------------------------------------------------------

def _update_peak_profit(position, current_pnl):
    """Track peak unrealized profit on the position."""
    if position.peak_profit_usd is None or current_pnl > position.peak_profit_usd:
        position.peak_profit_usd = current_pnl
        position.save(update_fields=['peak_profit_usd'])


def _check_profit_protection(position, current_pnl):
    """Close if profit was above $0.50 but dropped below 40% of peak.

    Returns close_reason string or None.
    """
    if position.peak_profit_usd is None:
        return None
    if position.peak_profit_usd < PROFIT_PROTECT_MIN_USD:
        return None

    threshold = position.peak_profit_usd * PROFIT_PROTECT_GIVEBACK
    if current_pnl > threshold:
        return None

    giveback_pct = (position.peak_profit_usd - current_pnl) / position.peak_profit_usd * 100
    logger.info(
        "PROFIT PROTECTION: %s %s peak=$%.2f current=$%.2f (gave back %.0f%%)",
        position.symbol, position.side,
        position.peak_profit_usd, current_pnl, giveback_pct,
    )
    return 'PROFIT_PROTECTION'


# ---------------------------------------------------------------------------
# Phase 3: Time exit
# ---------------------------------------------------------------------------

def _check_time_exit(position, profit_pct):
    """Close stale positions: open > 48 hours with less than 1% profit.

    Returns close_reason string or None.
    """
    age = timezone.now() - position.opened_at
    if age < timedelta(hours=TIME_EXIT_HOURS):
        return None

    # If it's profitable enough, let it run
    if profit_pct >= TIME_EXIT_MIN_PROFIT_PCT:
        return None

    hours_open = age.total_seconds() / 3600
    logger.info(
        "TIME EXIT: %s %s open %.1f hours, profit %.2f%% < %.0f%% threshold — closing",
        position.symbol, position.side,
        hours_open, profit_pct * 100, TIME_EXIT_MIN_PROFIT_PCT * 100,
    )
    return 'TIME_EXIT'


# ---------------------------------------------------------------------------
# Phase 4: Standard SL/TP
# ---------------------------------------------------------------------------

def _check_sl_tp(position, current_price):
    """Check standard stop loss and take profit levels.

    Returns close_reason string or None.
    """
    # Stop loss
    if position.stop_loss:
        if position.side == 'LONG' and current_price <= position.stop_loss:
            return 'STOP_LOSS'
        elif position.side == 'SHORT' and current_price >= position.stop_loss:
            return 'STOP_LOSS'

    # Take profit
    if position.take_profit:
        if position.side == 'LONG' and current_price >= position.take_profit:
            return 'TAKE_PROFIT'
        elif position.side == 'SHORT' and current_price <= position.take_profit:
            return 'TAKE_PROFIT'

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_pnl(position, current_price):
    """Calculate unrealized PnL in USD."""
    if position.side == 'LONG':
        return (current_price - position.entry_price) * position.size * position.leverage
    else:
        return (position.entry_price - current_price) * position.size * position.leverage
