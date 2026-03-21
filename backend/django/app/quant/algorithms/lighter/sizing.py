"""
Unified position sizing for all Lighter.xyz entry strategies.

Every entry algorithm MUST use calculate_position_usd() for sizing.
This ensures consistent risk-normalised sizing across all strategies:

    position_usd = risk_per_trade / sl_pct * combined_sizing(symbol)

Where combined_sizing includes session, symbol, and Kelly multipliers
(see session_sizing.py).
"""


def calculate_position_usd(symbol: str, sl_pct: float, risk_per_trade: float = 4.00) -> float:
    """Unified position sizing: risk_usd / sl_distance x combined_sizing.

    This is the ONLY sizing function. All entry algorithms must use this.

    Args:
        symbol: Trading pair (e.g. 'SOL', 'XAU', 'EURUSD')
        sl_pct: Stop-loss distance as a fraction (e.g. 0.02 for 2%)
        risk_per_trade: Dollar risk per trade (default $1.50)

    Returns:
        Position size in USD (notional value).
    """
    from .session_sizing import get_combined_sizing

    base = risk_per_trade / sl_pct
    combined = get_combined_sizing(symbol)
    return base * combined
