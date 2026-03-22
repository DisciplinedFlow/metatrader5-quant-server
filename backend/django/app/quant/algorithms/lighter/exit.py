"""
Lighter.xyz exit algorithm — monitors open positions for SL/TP/trailing/reversal exits
plus position management: breakeven, trailing stop, profit protection, and time exit.

Phases (applied in order):
1. BREAKEVEN: Move SL to entry price when profit exceeds 2%
2. TRAILING STOP: Ratchet SL upward as price makes new highs (3 tiers)
2.5 FIB EXTENSION TP: Close at Fibonacci extension levels (1.272, 1.618) after 2min hold
3. PROFIT PROTECTION: Close if profit drops below 40% of peak (after $0.50+ peak)
4. TIME EXIT: Close if open > 48 hours with less than 1% profit
5. SL/TP: Standard stop loss and take profit checks
"""
import logging
from datetime import timedelta
from django.utils import timezone

from .config import LIGHTER_MARKETS, FOREX_SYMBOLS, METALS_SYMBOLS
from .client import get_best_bid_ask, close_position, get_trade_fill
from .entry import PLATFORM_PREFIX

logger = logging.getLogger('app.lighter')

# -- Position management thresholds --
BREAKEVEN_PROFIT_PCT = 0.02        # Move SL to entry after 2% unrealized profit

# Tiered profit protection: (min_peak_usd, keep_fraction)
# Higher peaks get tighter protection to lock in more profit.
# Raised from 60/70/80 to 40/50/60 — let winners run, fees eat 37% of small exits.
PROFIT_TIERS = [
    (15.00, 0.70),  # $15+ peak → close if drops below 70% of peak
    (8.00, 0.60),   # $8+ peak → close if drops below 60% of peak
    (4.00, 0.50),   # $4+ peak → close if drops below 50% of peak
    # Old tiers ($0.50/$1/$3) triggered on normal price noise at 10% sizing
]
TIME_EXIT_HOURS = 48               # Close stale positions after 48 hours
TIME_EXIT_MIN_PROFIT_PCT = 0.01    # ...unless profit exceeds 1%

# -- Trailing stop tiers (per asset class) --
# Each tier: (activation_pct, trail_pct)
TRAIL_TIERS_CRYPTO = [
    (0.003, 0.002),  # Tier 1: at +0.3%, trail 0.2% below peak — lock in early
    (0.008, 0.003),  # Tier 2: at +0.8%, trail 0.3% — tighten as profit grows
    (0.015, 0.005),  # Tier 3: at +1.5%, trail 0.5% — let runners breathe slightly
    (0.030, 0.010),  # Tier 4: at +3.0%, trail 1.0% — near TP, wide trail for big moves
]
TRAIL_TIERS_METALS = [
    (0.01, 0.006),   # Tier 1: at +1%, trail 0.6% below peak
    (0.02, 0.008),   # Tier 2: at +2%, trail 0.8%
    (0.04, 0.012),   # Tier 3: at +4%, trail 1.2%
]
TRAIL_TIERS_FOREX = [
    (0.003, 0.002),  # Tier 1: at +0.3%, trail 0.2% below peak
    (0.005, 0.003),  # Tier 2: at +0.5%, trail 0.3%
    (0.008, 0.004),  # Tier 3: at +0.8%, trail 0.4%
]

def _get_trail_tiers(symbol):
    if symbol in FOREX_SYMBOLS:
        return TRAIL_TIERS_FOREX
    elif symbol in METALS_SYMBOLS:
        return TRAIL_TIERS_METALS
    return TRAIL_TIERS_CRYPTO


def exit_algorithm():
    """Monitor Lighter positions and exit on SL/TP/trailing + position management."""
    import time
    from app.crypto.models import CryptoPosition, CryptoTrade

    open_positions = CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=PLATFORM_PREFIX,
    )
    if not open_positions.exists():
        return

    from django.core.cache import cache as _price_cache
    seen_symbols = set()  # track which symbols already had a price fetched this cycle

    for position in open_positions:
        try:
            meta = LIGHTER_MARKETS.get(position.symbol)
            if meta is None:
                logger.warning("Lighter exit: unknown symbol %s", position.symbol)
                continue

            # Throttle: sleep only when a real API call is needed (cache hits are free)
            if position.symbol not in seen_symbols:
                seen_symbols.add(position.symbol)
                if not _price_cache.get(f'lighter:price:{position.symbol}'):
                    time.sleep(0.1)  # 100ms between uncached symbol fetches → ≤10 req/s

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

            # ── Phase 2.5: Fib Extension TP ──
            close_reason = _check_fib_extension_tp(position, current_price, profit_pct)

            # ── Phase 3: Track peak profit & profit protection ──
            _update_peak_profit(position, pnl_usd)
            if not close_reason:
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

            # Capture real fill from exchange via tx_hash
            tx_hash = result.get('tx_hash', '') if result else ''
            fill = get_trade_fill(tx_hash) if tx_hash else {}
            fill_price = fill.get('price', current_price)
            exchange_pnl = fill.get('pnl')

            # Use exchange PnL if available, otherwise calculate from fill price
            if exchange_pnl is not None:
                final_pnl = exchange_pnl
            else:
                final_pnl = _calc_pnl(position, fill_price)
                notional = position.size * fill_price
                final_pnl -= notional * 0.00028  # estimated taker fee

            position.status = 'CLOSED'
            position.close_price = fill_price
            position.pnl_usd = final_pnl
            position.close_reason = close_reason
            position.closed_at = timezone.now()
            position.save()

            if fill:
                logger.info("Lighter close fill captured: %s price=%.4f exch_pnl=%s",
                            position.symbol, fill_price,
                            f"${exchange_pnl:.4f}" if exchange_pnl is not None else "N/A")

            CryptoTrade.objects.create(
                position=position,
                order_id=tx_hash,
                side='SELL' if position.side == 'LONG' else 'BUY',
                price=fill_price,
                size=position.size,
                fee=fill.get('fee', 0.0) or 0.0,
                status='FILLED',
            )

            logger.info("Lighter position closed: %s pnl=$%.2f reason=%s",
                         position.symbol, pnl_usd, close_reason)

            # Record ML training data (features from entry + outcome)
            try:
                from django.core.cache import cache as _cache
                features = _cache.get(f'lighter:ml_features:{position.id}')
                if features:
                    import json as _json, os as _os
                    features['pnl'] = float(pnl_usd)
                    features['won'] = pnl_usd > 0
                    features['close_price'] = float(current_price)
                    features['close_reason'] = close_reason
                    features['duration_min'] = round((position.closed_at - position.opened_at).total_seconds() / 60) if position.opened_at and position.closed_at else 0
                    features['peak_pnl'] = float(position.peak_profit_usd or 0)
                    ml_dir = '/app/ml_models/crypto_training_data'
                    _os.makedirs(ml_dir, exist_ok=True)
                    with open(f'{ml_dir}/trades.jsonl', 'a') as f:
                        f.write(_json.dumps(features, default=str) + '\n')
                    _cache.delete(f'lighter:ml_features:{position.id}')
                    logger.info("ML training data saved: %s %s pnl=$%.4f",
                                position.symbol, 'WIN' if pnl_usd > 0 else 'LOSS', pnl_usd)
            except Exception as e:
                logger.debug("ML feature recording failed: %s", e)

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
    # Asset-class aware breakeven threshold
    be_pct = 0.003 if position.symbol in FOREX_SYMBOLS else (0.01 if position.symbol in METALS_SYMBOLS else BREAKEVEN_PROFIT_PCT)
    if profit_pct < be_pct:
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
    tiers = _get_trail_tiers(position.symbol)
    if profit_pct < tiers[0][0]:
        return  # Not yet at first tier

    peak = _get_peak_price(position)

    # Find the highest qualifying tier
    active_trail_pct = None
    for activation_pct, trail_pct in tiers:
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
# Phase 2.5: Fib Extension TP
# ---------------------------------------------------------------------------

# Minimum hold time before Fib TP can trigger (avoids premature exits)
FIB_MIN_HOLD_SECONDS = 120  # 2 minutes
# Fib ZigZag parameters per asset class
FIB_PARAMS = {
    'crypto':  {'min_deviation_pct': 0.5, 'depth': 10},
    'forex':   {'min_deviation_pct': 0.15, 'depth': 12},
    'metals':  {'min_deviation_pct': 0.3, 'depth': 10},
}


def _check_fib_extension_tp(position, current_price, profit_pct):
    """Close if price reaches a Fibonacci extension level (1.272 or 1.618).

    Only fires if the position has been profitable for at least 2 minutes
    to avoid premature exits on noise spikes. Uses 5m candles for swing
    detection to keep the Fib levels relevant to the current move.

    Returns close_reason string or None.
    """
    try:
        # Only check when position is in profit
        if profit_pct <= 0:
            return None

        # Enforce minimum hold time
        age_seconds = (timezone.now() - position.opened_at).total_seconds()
        if age_seconds < FIB_MIN_HOLD_SECONDS:
            return None

        from .fibonacci import get_fib_tp_targets
        from .client import get_candles
        from django.core.cache import cache as _fib_cache

        # Select ZigZag params by asset class
        if position.symbol in FOREX_SYMBOLS:
            params = FIB_PARAMS['forex']
        elif position.symbol in METALS_SYMBOLS:
            params = FIB_PARAMS['metals']
        else:
            params = FIB_PARAMS['crypto']

        direction = 'up' if position.side == 'LONG' else 'down'

        # Fetch 5m candles for swing detection — cached 60s (called every 15s per position)
        _fib_key = f'lighter:candles:5m:{position.symbol}'
        candles = _fib_cache.get(_fib_key)
        if candles is None:
            candles = get_candles(position.symbol, resolution='5m', count_back=100)
            if candles:
                _fib_cache.set(_fib_key, candles, timeout=60)
        if not candles or len(candles) < params['depth'] * 3:
            return None

        targets = get_fib_tp_targets(
            candles, direction,
            min_deviation_pct=params['min_deviation_pct'],
            depth=params['depth'],
        )
        if not targets:
            return None

        # Check if current price has reached or exceeded any Fib extension
        for target_price, label in targets:
            if direction == 'up' and current_price >= target_price:
                logger.info(
                    "FIB TP: %s %s hit %s at %.4f (target=%.4f, profit=%.1f%%, held=%ds)",
                    position.symbol, position.side, label, current_price,
                    target_price, profit_pct * 100, int(age_seconds),
                )
                return f'FIB_EXTENSION_{label.upper()}'
            elif direction == 'down' and current_price <= target_price:
                logger.info(
                    "FIB TP: %s %s hit %s at %.4f (target=%.4f, profit=%.1f%%, held=%ds)",
                    position.symbol, position.side, label, current_price,
                    target_price, profit_pct * 100, int(age_seconds),
                )
                return f'FIB_EXTENSION_{label.upper()}'

        return None

    except Exception as e:
        # Fib failures must never break the exit loop
        logger.debug("Fib extension check failed for %s: %s", position.symbol, e)
        return None


# ---------------------------------------------------------------------------
# Phase 3: Profit protection
# ---------------------------------------------------------------------------

def _update_peak_profit(position, current_pnl):
    """Track peak unrealized profit on the position."""
    if position.peak_profit_usd is None or current_pnl > position.peak_profit_usd:
        position.peak_profit_usd = current_pnl
        position.save(update_fields=['peak_profit_usd'])


def _check_profit_protection(position, current_pnl):
    """Tiered profit protection: higher peaks get tighter floors.

    PROFIT_TIERS checked top-down (highest threshold first):
      $15+ peak → keep 70%
      $8+ peak → keep 60%
      $4+ peak → keep 50%

    Returns close_reason string or None.
    """
    peak = position.peak_profit_usd
    if peak is None or peak < PROFIT_TIERS[-1][0]:
        return None

    # Find the tightest tier that applies (list is sorted highest-first)
    keep_fraction = PROFIT_TIERS[-1][1]  # default to loosest
    for min_peak, fraction in PROFIT_TIERS:
        if peak >= min_peak:
            keep_fraction = fraction
            break

    threshold = peak * keep_fraction
    if current_pnl > threshold:
        return None

    giveback_pct = (peak - current_pnl) / peak * 100
    logger.info(
        "PROFIT PROTECTION [tier %.0f%%]: %s %s peak=$%.2f current=$%.2f "
        "floor=$%.2f (gave back %.0f%%)",
        keep_fraction * 100, position.symbol, position.side,
        peak, current_pnl, threshold, giveback_pct,
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
    """Calculate unrealized PnL in USD.

    IMPORTANT: position.size is already the leveraged position size from Lighter
    (e.g. $12 collateral × 15x leverage / price = size). Do NOT multiply by
    leverage again — that would inflate PnL by 15x.
    """
    if position.side == 'LONG':
        return (current_price - position.entry_price) * position.size
    else:
        return (position.entry_price - current_price) * position.size
