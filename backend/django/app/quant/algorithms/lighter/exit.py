"""
Lighter.xyz exit algorithm — monitors open positions for SL/TP/trailing/reversal exits
plus position management: breakeven, trailing stop, profit protection, and time exit.

Phases (applied in order):
1. BREAKEVEN: Move SL to entry price when profit exceeds 2%
2. TRAILING STOP: Ratchet SL upward as price makes new highs (3 tiers)
3. PROFIT PROTECTION: Close if profit drops below 40% of peak (after $0.50+ peak)
4. TIME EXIT: Close if open > 48 hours with less than 1% profit
5. SL/TP: Standard stop loss and take profit checks
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

# -- Trailing stop tiers --
# Each tier: (activation_pct, trail_pct)
# activation_pct = profit % that activates this tier
# trail_pct = how far below the peak price to set the SL
TRAIL_TIERS = [
    (0.03, 0.015),   # Tier 1: at +3% profit, trail 1.5% below peak
    (0.06, 0.02),    # Tier 2: at +6% profit, trail 2% below peak (tighter)
    (0.10, 0.025),   # Tier 3: at +10% profit, trail 2.5% below peak (wider to let runners run)
]


def exit_algorithm():
    """Monitor Lighter positions and exit on SL/TP/trailing + position management."""
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

            # ── Phase 2: Trailing stop ──
            _update_peak_price(position, current_price)
            _check_trailing_stop(position, current_price, profit_pct)

            # ── Phase 3: Track peak profit & profit protection ──
            _update_peak_profit(position, pnl_usd)
            close_reason = _check_profit_protection(position, pnl_usd)

            # ── Phase 4: Time exit ──
            if not close_reason:
                close_reason = _check_time_exit(position, profit_pct)

            # ── Phase 5: Standard SL/TP checks (trailing SL is checked here) ──
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
# Phase 2: Trailing stop
# ---------------------------------------------------------------------------

def _get_peak_price(position):
    """Get cached peak price for trailing stop calculation."""
    from django.core.cache import cache
    key = f'lighter:peak:{position.id}'
    return cache.get(key, position.entry_price)


def _update_peak_price(position, current_price):
    """Track the highest (for longs) or lowest (for shorts) price seen."""
    from django.core.cache import cache
    key = f'lighter:peak:{position.id}'
    peak = cache.get(key, position.entry_price)

    if position.side == 'LONG' and current_price > peak:
        cache.set(key, current_price, timeout=7 * 86400)  # 7 day TTL
    elif position.side == 'SHORT' and current_price < peak:
        cache.set(key, current_price, timeout=7 * 86400)


def _check_trailing_stop(position, current_price, profit_pct):
    """Ratchet the SL upward based on trailing tiers.

    Finds the highest tier the position qualifies for and sets
    the SL at (peak_price * (1 - trail_pct)) for longs.
    The SL only moves up, never down.
    """
    if profit_pct < TRAIL_TIERS[0][0]:
        return  # Not yet at first tier

    peak = _get_peak_price(position)

    # Find the highest qualifying tier
    active_trail_pct = None
    for activation_pct, trail_pct in TRAIL_TIERS:
        if profit_pct >= activation_pct:
            active_trail_pct = trail_pct

    if active_trail_pct is None:
        return

    # Calculate new trailing SL
    if position.side == 'LONG':
        new_sl = peak * (1 - active_trail_pct)
    else:
        new_sl = peak * (1 + active_trail_pct)

    # SL only moves in the profitable direction
    old_sl = position.stop_loss or 0
    if position.side == 'LONG' and new_sl > old_sl:
        position.stop_loss = new_sl
        position.save(update_fields=['stop_loss'])
        logger.info(
            "TRAILING: %s %s SL %.4f -> %.4f (peak=%.4f, trail=%.1f%%, profit=%.1f%%)",
            position.symbol, position.side, old_sl, new_sl, peak,
            active_trail_pct * 100, profit_pct * 100,
        )
    elif position.side == 'SHORT' and (new_sl < old_sl or old_sl == 0):
        position.stop_loss = new_sl
        position.save(update_fields=['stop_loss'])
        logger.info(
            "TRAILING: %s %s SL %.4f -> %.4f (peak=%.4f, trail=%.1f%%, profit=%.1f%%)",
            position.symbol, position.side, old_sl, new_sl, peak,
            active_trail_pct * 100, profit_pct * 100,
        )


# ---------------------------------------------------------------------------
# Phase 3: Profit protection
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
# Phase 4: Time exit
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
        "TIME EXIT: %s %s open %.1f hours, profit %.2f%% < %.0f%% threshold",
        position.symbol, position.side,
        hours_open, profit_pct * 100, TIME_EXIT_MIN_PROFIT_PCT * 100,
    )
    return 'TIME_EXIT'


# ---------------------------------------------------------------------------
# Phase 5: Standard SL/TP
# ---------------------------------------------------------------------------

def _check_sl_tp(position, current_price):
    """Check stop loss (including trailing) and take profit levels.

    Returns close_reason string or None.
    """
    # Stop loss (covers both initial SL and trailing SL)
    if position.stop_loss:
        if position.side == 'LONG' and current_price <= position.stop_loss:
            # Distinguish trailing from initial
            if position.stop_loss > position.entry_price:
                return 'TRAILING_STOP'
            return 'STOP_LOSS'
        elif position.side == 'SHORT' and current_price >= position.stop_loss:
            if position.stop_loss < position.entry_price:
                return 'TRAILING_STOP'
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
