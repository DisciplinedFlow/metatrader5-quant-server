import logging
from .config import KELLY_FRACTION, MAX_KELLY_BET, CAPITAL_USD

logger = logging.getLogger('app.polymarket')


def kelly_size(model_prob, market_price, side='YES'):
    """Calculate Kelly criterion bet size.

    For YES side: f* = (b*p - q) / b
    where p = model_prob, q = 1-p, b = (1/market_price - 1) = payout odds

    Returns fractional Kelly as fraction of capital.
    """
    if side == 'YES':
        p = model_prob
        b = (1.0 / market_price) - 1.0 if market_price > 0 else 0
    else:
        p = 1.0 - model_prob
        b = (1.0 / (1.0 - market_price)) - 1.0 if market_price < 1 else 0

    if b <= 0:
        return 0.0

    q = 1.0 - p
    f_star = (b * p - q) / b

    if f_star <= 0:
        return 0.0

    # Apply fractional Kelly
    f_adjusted = f_star * KELLY_FRACTION

    # Cap at maximum bet size
    f_adjusted = min(f_adjusted, MAX_KELLY_BET)

    return f_adjusted


def calculate_position_size(model_prob, market_price, side='YES', capital=None):
    """Calculate position size in USD.

    Returns:
        dict with kelly_fraction, size_usd, shares
    """
    if capital is None:
        capital = CAPITAL_USD

    fraction = kelly_size(model_prob, market_price, side)
    size_usd = fraction * capital

    # Calculate shares: shares = size_usd / market_price
    price = market_price if side == 'YES' else (1.0 - market_price)
    shares = size_usd / price if price > 0 else 0

    logger.info(f"Position sizing: kelly={fraction:.4f}, size=${size_usd:.2f}, shares={shares:.2f}")

    return {
        'kelly_fraction': fraction,
        'size_usd': round(size_usd, 2),
        'shares': round(shares, 2),
    }
