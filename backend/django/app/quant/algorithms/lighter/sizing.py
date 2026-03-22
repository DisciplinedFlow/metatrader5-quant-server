"""
Unified position sizing for all Lighter.xyz entry strategies.

Every entry algorithm MUST use calculate_position_usd() for sizing.
Dynamic compounding: risk = 10% of live account balance per trade.
As balance grows, position sizes grow. As it shrinks, they shrink.

    position_usd = risk_per_trade / sl_pct * combined_sizing(symbol)
"""
import logging

logger = logging.getLogger('app.lighter')

# ── Configuration ─────────────────────────────────────────
RISK_PCT = 0.10           # 10% of account balance per trade
BALANCE_CACHE_TTL = 60    # seconds between balance refreshes
MIN_RISK = 0.50           # floor: never risk less than $0.50
MAX_RISK = 500.00         # ceiling: safety cap


def _fetch_balance():
    """Fetch live account balance from Lighter API with 60s Redis cache.

    Uses Django's Redis-backed cache so all Celery workers share the same
    cached value (avoids duplicate API calls and stale per-process state).
    """
    from django.core.cache import cache

    cached = cache.get('lighter:balance')
    if cached is not None:
        return cached

    try:
        from .client import get_account_info
        acct = get_account_info()
        balance = float(acct.accounts[0].available_balance)
        cache.set('lighter:balance', balance, timeout=BALANCE_CACHE_TTL)
        logger.debug("Sizing: live balance $%.2f", balance)
        return balance
    except Exception as e:
        logger.warning("Sizing: balance fetch failed (%s)", e)
        return 0.0


def get_risk_per_trade():
    """Return dynamic risk = 10% of live Lighter balance, clamped."""
    balance = _fetch_balance()
    risk = balance * RISK_PCT
    risk = max(MIN_RISK, min(MAX_RISK, risk))
    return risk


def calculate_position_usd(symbol, sl_pct, risk_per_trade=None):
    """Unified position sizing: risk_usd / sl_distance x combined_sizing.

    This is the ONLY sizing function. All entry algorithms must use this.

    Args:
        symbol: Trading pair (e.g. 'SOL', 'XAU', 'WTI')
        sl_pct: Stop-loss distance as a fraction (e.g. 0.02 for 2%)
        risk_per_trade: Dollar risk per trade. If None, uses dynamic
                        10% of live Lighter account balance.

    Returns:
        Position size in USD (notional value).
    """
    from .session_sizing import get_combined_sizing

    if risk_per_trade is None:
        risk_per_trade = get_risk_per_trade()

    base = risk_per_trade / sl_pct
    combined = get_combined_sizing(symbol)
    return base * combined
