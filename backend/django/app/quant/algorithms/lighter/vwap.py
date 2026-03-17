"""
VWAP (Volume Weighted Average Price) -- intraday support/resistance.

Research showed VWAP-RSI scalper had profit factor 1.37.
Price above VWAP = bullish bias, below = bearish bias.
VWAP acts as a magnet -- price tends to revert to it.

Used as:
1. Trend filter: only go LONG above VWAP, SHORT below
2. TP target: price tends to revert to VWAP
3. Confluence factor: +1 point when trade direction aligns with VWAP bias
"""
import logging
from datetime import datetime, timezone

from .client import get_candles, get_best_bid_ask

logger = logging.getLogger('app.lighter')

# Distance threshold: if price is within 0.05% of VWAP, consider it "AT"
AT_THRESHOLD_PCT = 0.0005


def calculate_vwap(candles: list) -> float:
    """Calculate VWAP from a list of candle dicts.

    VWAP = sum(typical_price * volume) / sum(volume)
    where typical_price = (high + low + close) / 3

    Session resets at 00:00 UTC for crypto (24h market).
    Only uses candles from the current UTC day.

    Args:
        candles: List of candle dicts with keys: t, o, h, l, c, v
                 where t is a Unix timestamp.

    Returns:
        VWAP as a float. Returns 0.0 if insufficient data.
    """
    if not candles:
        return 0.0

    # Filter candles to current UTC session (since 00:00 UTC today)
    now = datetime.now(timezone.utc)
    session_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    session_start_ts = int(session_start.timestamp())

    session_candles = [
        c for c in candles
        if int(c.get('t', 0)) >= session_start_ts
    ]

    if not session_candles:
        # If no candles match today's session, use all candles as fallback
        # (could be a data timing issue)
        session_candles = candles

    cumulative_tp_vol = 0.0
    cumulative_vol = 0.0

    for c in session_candles:
        high = float(c.get('h', 0))
        low = float(c.get('l', 0))
        close = float(c.get('c', 0))
        volume = float(c.get('v', 0))

        if volume <= 0:
            continue

        typical_price = (high + low + close) / 3.0
        cumulative_tp_vol += typical_price * volume
        cumulative_vol += volume

    if cumulative_vol <= 0:
        return 0.0

    return cumulative_tp_vol / cumulative_vol


def get_vwap_bias(symbol: str) -> dict:
    """Calculate VWAP and determine price bias relative to it.

    Fetches 5m candles for the current session, calculates VWAP,
    and compares the current price to determine bullish/bearish bias.

    Args:
        symbol: Trading pair (e.g. 'ETH', 'BTC', 'SOL')

    Returns:
        dict with keys:
            vwap: float -- the VWAP value
            price: float -- current mid price
            bias: str -- 'ABOVE', 'BELOW', or 'AT'
            distance_pct: float -- signed percentage distance from VWAP
    """
    result = {'vwap': 0.0, 'price': 0.0, 'bias': 'AT', 'distance_pct': 0.0}

    try:
        # Fetch 5m candles -- 288 candles covers a full 24h session
        candles = get_candles(symbol, resolution='5m', count_back=288)
        if not candles:
            logger.debug("VWAP %s: no candle data", symbol)
            return result

        vwap = calculate_vwap(candles)
        if vwap <= 0:
            logger.debug("VWAP %s: zero VWAP (no volume data)", symbol)
            return result

        # Get current price
        prices = get_best_bid_ask(symbol)
        price = prices.get('mid', 0.0)
        if not price or price <= 0:
            # Fallback to last candle close
            price = float(candles[-1].get('c', 0))

        if price <= 0:
            return result

        distance_pct = (price - vwap) / vwap

        if abs(distance_pct) < AT_THRESHOLD_PCT:
            bias = 'AT'
        elif distance_pct > 0:
            bias = 'ABOVE'
        else:
            bias = 'BELOW'

        result = {
            'vwap': vwap,
            'price': price,
            'bias': bias,
            'distance_pct': distance_pct,
        }

        logger.debug("VWAP %s: %.4f (price=%.4f, bias=%s, dist=%.4f%%)",
                      symbol, vwap, price, bias, distance_pct * 100)

    except Exception as e:
        logger.debug("VWAP calculation failed for %s: %s", symbol, e)

    return result
