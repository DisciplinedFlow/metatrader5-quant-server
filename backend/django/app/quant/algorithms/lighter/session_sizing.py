"""
Session-aware position sizing — adjusts trade size based on time of day.

Based on academic research (Amberdata, QuantPedia) + real bot data from Mar 16-17 2026:
- Asian session (22:00-08:00 UTC): Worst returns, range-bound -> 60% base size
- London (08:00-12:00 UTC): Deep liquidity, volatility ramp -> 100% base size
- US Overlap (12:00-17:00 UTC): Best risk-adjusted returns -> 120% base size
- Late NY (17:00-21:00 UTC): Declining vol -> 80% base size
- NY Close anomaly (21:00-23:00 UTC): Statistically significant positive returns -> 110% base size

Also integrates news sentiment from news_sentiment.py:
- NORMAL: 1.0x multiplier
- ELEVATED: 0.75x multiplier
- EXTREME: 0.5x multiplier

And per-symbol performance adjustment based on historical data:
- ETH: 1.2x (best performer, +$23.90 in day 1)
- SOL: 1.0x
- XAU: 1.0x (69% WR)
- BTC: 0.7x (negative P&L)
- EURUSD: 0.5x (25% WR)
- GBPUSD: 0.0x (DISABLED -- 0% WR, -$2.65)
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger('app.lighter')

# ── Session multipliers by UTC hour ────────────────────────
# Asian:     22:00-07:59 UTC -> 0.6
# London:    08:00-11:59 UTC -> 1.0
# US Overlap:12:00-16:59 UTC -> 1.2
# Late NY:   17:00-20:59 UTC -> 0.8
# NY Close:  21:00-21:59 UTC -> 1.1
# (22:00 wraps to Asian)

SESSION_MULTIPLIERS = {
    0: 0.6,   # Asian
    1: 0.6,
    2: 0.6,
    3: 0.6,
    4: 0.6,
    5: 0.6,
    6: 0.6,
    7: 0.6,
    8: 1.0,   # London open
    9: 1.0,
    10: 1.0,
    11: 1.0,
    12: 1.2,  # US overlap
    13: 1.2,
    14: 1.2,
    15: 1.2,
    16: 1.2,
    17: 0.8,  # Late NY
    18: 0.8,
    19: 0.8,
    20: 0.8,
    21: 1.1,  # NY close anomaly
    22: 0.6,  # Asian
    23: 0.6,
}

# ── Per-symbol multipliers from historical performance ─────
# Reset to 1.0 on Mar 19 2026: old penalties were derived from bad pre-fix strategy data
# (22.3% WR due to no trend filter + duplicate strategies). Recalibrate after 50+ trades.
SYMBOL_MULTIPLIERS = {
    'SOL': 1.0,
    'XAU': 1.0,
    'AVAX': 1.0,
    'LINK': 1.0,
    'DOGE': 1.0,
    'EURUSD': 0.5,
    'GBPUSD': 0.0,  # DISABLED
}

# Default for symbols not in the map
DEFAULT_SYMBOL_MULTIPLIER = 1.0


def get_session_multiplier() -> float:
    """Return position size multiplier (0.6-1.2) based on current UTC hour."""
    hour = datetime.now(timezone.utc).hour
    return SESSION_MULTIPLIERS.get(hour, 0.8)


def get_news_multiplier(symbol: str = '') -> float:
    """Return position size multiplier (0.5-1.0) based on sentiment risk level.

    Checks Santiment social sentiment first (real-time Twitter/social data).
    Falls back to RSS news sentiment if Santiment unavailable.
    """
    # Try Santiment social sentiment first (crypto-specific, real-time)
    if symbol:
        try:
            from .social_sentiment import get_social_sentiment
            social = get_social_sentiment(symbol)
            if social.get('source') not in ('default', 'skip_non_crypto', 'unknown_symbol', 'all_sources_failed'):
                multiplier = social.get('risk_multiplier', 1.0)
                if multiplier < 0.5:
                    multiplier = 0.5
                if multiplier != 1.0:
                    logger.debug(
                        "Session sizing %s: social sentiment risk_mult=%.2f (source=%s, score=%.2f, vol=%.1fx)",
                        symbol, multiplier, social.get('source'), social.get('sentiment_score', 0),
                        social.get('social_volume', 1.0),
                    )
                return multiplier
        except Exception as e:
            logger.debug("Session sizing: social sentiment unavailable for %s: %s", symbol, e)

    # Fall back to RSS news sentiment
    try:
        from app.quant.indicators.news_sentiment import get_market_risk_level
        risk = get_market_risk_level()
        multiplier = risk.get('size_multiplier', 1.0)
        if multiplier < 0.5:
            multiplier = 0.5
        return multiplier
    except Exception as e:
        logger.debug("Session sizing: news sentiment unavailable: %s", e)
        return 1.0


def get_symbol_multiplier(symbol: str) -> float:
    """Return position size multiplier (0.0-1.2) based on per-symbol historical performance."""
    return SYMBOL_MULTIPLIERS.get(symbol, DEFAULT_SYMBOL_MULTIPLIER)


def get_combined_sizing(symbol: str) -> float:
    """Return combined sizing multiplier.

    session (0.6-1.2) * symbol (0.0-1.2) * kelly (0.25-2.5)

    News removed: keyword filter was permanently EXTREME (war/iran/gold always in headlines)
    and was double-counted in rsi_scalper. Session time + kelly is sufficient.
    """
    session = get_session_multiplier()
    sym = get_symbol_multiplier(symbol)

    # Adaptive Kelly: uses recent trade history for mathematically optimal sizing
    try:
        from .kelly_sizing import get_adaptive_kelly_multiplier
        kelly = get_adaptive_kelly_multiplier(symbol)
    except Exception as e:
        logger.debug("Kelly sizing unavailable: %s", e)
        kelly = 1.0

    combined = session * sym * kelly

    if combined != 1.0:
        logger.debug("Session sizing %s: session=%.2f symbol=%.2f kelly=%.2f -> combined=%.3f",
                      symbol, session, sym, kelly, combined)

    return combined
