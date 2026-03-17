"""
Adaptive Kelly Criterion position sizing.

Uses recent trade history to calculate mathematically optimal position size.
Quarter-Kelly (K/4) for safety -- 75% of full Kelly growth at 50% volatility.

Formula: K = W - [(1-W) / R]
where W = win rate, R = avg_win / avg_loss

The research says: "Half-Kelly is the professional standard."
We use Quarter-Kelly because crypto is more volatile than what Kelly assumes.
"""
import logging

from django.core.cache import cache

logger = logging.getLogger('app.lighter')

# Kelly constraints
KELLY_MIN = 0.05   # Minimum 5% of capital per trade
KELLY_MAX = 0.50   # Maximum 50% of capital per trade
KELLY_FRACTION = 0.25  # Quarter-Kelly

# Data requirements
MIN_TRADES = 10    # Need at least 10 closed trades for meaningful stats
TRADE_LOOKBACK = 20  # Use last 20 trades

# Cache
KELLY_CACHE_TTL = 1800  # 30 minutes


def calculate_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Calculate Quarter-Kelly position size fraction.

    Full Kelly: K = W - (1-W)/R where R = avg_win / |avg_loss|
    Quarter Kelly: K/4
    Clamped to [0.05, 0.50].

    Args:
        win_rate: Win rate as a decimal (0.0 to 1.0)
        avg_win: Average winning trade P&L (positive number)
        avg_loss: Average losing trade P&L (negative number, will be abs'd)

    Returns:
        Quarter-Kelly fraction clamped to [KELLY_MIN, KELLY_MAX].
        Returns KELLY_MIN if inputs are invalid or Kelly is negative.
    """
    if win_rate <= 0 or win_rate >= 1.0:
        return KELLY_MIN

    abs_avg_loss = abs(avg_loss)
    if abs_avg_loss <= 0 or avg_win <= 0:
        return KELLY_MIN

    # R = reward/risk ratio
    r = avg_win / abs_avg_loss

    # Full Kelly
    full_kelly = win_rate - (1 - win_rate) / r

    if full_kelly <= 0:
        # Negative Kelly means the edge is negative -- use minimum
        return KELLY_MIN

    # Quarter Kelly for safety
    quarter_kelly = full_kelly * KELLY_FRACTION

    # Clamp to bounds
    return max(KELLY_MIN, min(KELLY_MAX, quarter_kelly))


def get_adaptive_kelly_multiplier(symbol: str = None) -> float:
    """Get Kelly-based sizing multiplier from recent Lighter trade history.

    Pulls last 20 closed Lighter positions, calculates win rate and
    avg win/loss, then returns a Quarter-Kelly multiplier relative to
    the base position size.

    The multiplier is normalized so that the "default" base sizing
    corresponds to roughly 1.0. Quarter-Kelly above the default
    returns > 1.0 (up to a cap), below returns < 1.0.

    Args:
        symbol: Optional symbol filter. If None, uses all Lighter trades.

    Returns:
        Float multiplier (0.25 to 2.5). Returns 1.0 if insufficient data.
    """
    cache_key = f'lighter:kelly:{symbol or "all"}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        from app.crypto.models import CryptoPosition

        qs = CryptoPosition.objects.filter(
            status='CLOSED',
            entry_signal__startswith='lighter:',
            pnl_usd__isnull=False,
        )
        if symbol:
            qs = qs.filter(symbol=symbol)

        recent = qs.order_by('-closed_at')[:TRADE_LOOKBACK]
        pnls = [p.pnl_usd for p in recent]

        if len(pnls) < MIN_TRADES:
            logger.debug("Kelly %s: insufficient data (%d/%d trades), returning 1.0",
                          symbol or 'all', len(pnls), MIN_TRADES)
            cache.set(cache_key, 1.0, timeout=KELLY_CACHE_TTL)
            return 1.0

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        win_rate = len(wins) / len(pnls) if pnls else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0

        kelly_fraction = calculate_kelly(win_rate, avg_win, avg_loss)

        # Convert Kelly fraction to a multiplier relative to base sizing.
        # Base sizing uses LIGHTER_POSITION_SIZE_PCT (0.40 = 40%).
        # If Kelly says 0.40, multiplier = 1.0 (neutral).
        # If Kelly says 0.20, multiplier = 0.5 (reduce size).
        # If Kelly says 0.50, multiplier = 1.25 (increase size).
        from .config import LIGHTER_POSITION_SIZE_PCT
        base_fraction = LIGHTER_POSITION_SIZE_PCT if LIGHTER_POSITION_SIZE_PCT > 0 else 0.40

        multiplier = kelly_fraction / base_fraction

        # Clamp multiplier to reasonable bounds
        multiplier = max(0.25, min(2.5, multiplier))

        logger.info(
            "Kelly %s: WR=%.0f%% avg_win=$%.2f avg_loss=$%.2f R=%.2f "
            "full_K=%.3f quarter_K=%.3f mult=%.2f (from %d trades)",
            symbol or 'all', win_rate * 100, avg_win, avg_loss,
            avg_win / abs(avg_loss) if avg_loss != 0 else 0,
            kelly_fraction / KELLY_FRACTION if KELLY_FRACTION > 0 else 0,
            kelly_fraction, multiplier, len(pnls),
        )

        cache.set(cache_key, multiplier, timeout=KELLY_CACHE_TTL)
        return multiplier

    except Exception as e:
        logger.error("Kelly calculation failed for %s: %s", symbol or 'all', e)
        cache.set(cache_key, 1.0, timeout=KELLY_CACHE_TTL)
        return 1.0
