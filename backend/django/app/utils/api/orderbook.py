"""MT5 Depth of Market (DOM) client.

Fetches Level 2 order book data showing pending buy/sell orders
at different price levels. Used to detect:
- Liquidity pools (clusters of orders at price levels)
- Stop clusters (where retail stops are concentrated)
- Institutional order blocks (large volume at specific levels)
"""
import logging
from app.utils.api.session import get_session, BASE_URL

logger = logging.getLogger('quant')

# Empty response template — used for graceful degradation
_EMPTY = {
    'symbol': '',
    'bids': [],
    'asks': [],
    'bid_depth': 0,
    'ask_depth': 0,
    'imbalance': 0,
    'largest_bid': {'price': 0, 'volume': 0},
    'largest_ask': {'price': 0, 'volume': 0},
}


def get_orderbook(symbol: str) -> dict:
    """Fetch DOM data for a symbol from MT5.

    Returns:
        {
            'symbol': 'XAGUSD',
            'bids': [{'price': 78.50, 'volume': 100}, ...],  # Buy orders
            'asks': [{'price': 78.55, 'volume': 50}, ...],   # Sell orders
            'bid_depth': total bid volume,
            'ask_depth': total ask volume,
            'imbalance': (bid_depth - ask_depth) / (bid_depth + ask_depth),  # -1 to +1
            'largest_bid': {'price': x, 'volume': y},
            'largest_ask': {'price': x, 'volume': y},
        }
    """
    try:
        resp = get_session().get(f'{BASE_URL}/market_book/{symbol}', timeout=5)
        resp.raise_for_status()
        data = resp.json()

        book = data.get('book', [])
        if not book:
            return {**_EMPTY, 'symbol': symbol}

        # MT5 book entries have 'type': 1 (sell/ask) or 2 (buy/bid), 'price', 'volume'
        bids = [{'price': e['price'], 'volume': e['volume']} for e in book if e.get('type') == 2]
        asks = [{'price': e['price'], 'volume': e['volume']} for e in book if e.get('type') == 1]

        bid_depth = sum(b['volume'] for b in bids)
        ask_depth = sum(a['volume'] for a in asks)
        total = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / total if total > 0 else 0

        largest_bid = max(bids, key=lambda x: x['volume']) if bids else {'price': 0, 'volume': 0}
        largest_ask = max(asks, key=lambda x: x['volume']) if asks else {'price': 0, 'volume': 0}

        return {
            'symbol': symbol,
            'bids': sorted(bids, key=lambda x: x['price'], reverse=True),
            'asks': sorted(asks, key=lambda x: x['price']),
            'bid_depth': bid_depth,
            'ask_depth': ask_depth,
            'imbalance': round(imbalance, 4),
            'largest_bid': largest_bid,
            'largest_ask': largest_ask,
        }
    except Exception as e:
        logger.debug(f"Orderbook unavailable for {symbol}: {e}")
        return {**_EMPTY, 'symbol': symbol}


def get_orderbook_bias(symbol: str) -> dict:
    """Get trading bias from orderbook imbalance.

    Returns:
        {
            'bias': 'BULLISH' | 'BEARISH' | 'NEUTRAL',
            'imbalance': float (-1 to +1),
            'bid_depth': int,
            'ask_depth': int,
            'liquidity_levels': [{'price': x, 'volume': y, 'side': 'bid'|'ask'}, ...],
        }
    """
    ob = get_orderbook(symbol)

    imbalance = ob['imbalance']
    if imbalance > 0.15:
        bias = 'BULLISH'   # More buy orders = bullish pressure
    elif imbalance < -0.15:
        bias = 'BEARISH'   # More sell orders = bearish pressure
    else:
        bias = 'NEUTRAL'

    # Find significant liquidity levels (top 3 by volume on each side)
    liquidity = []
    for b in sorted(ob['bids'], key=lambda x: x['volume'], reverse=True)[:3]:
        liquidity.append({'price': b['price'], 'volume': b['volume'], 'side': 'bid'})
    for a in sorted(ob['asks'], key=lambda x: x['volume'], reverse=True)[:3]:
        liquidity.append({'price': a['price'], 'volume': a['volume'], 'side': 'ask'})

    return {
        'bias': bias,
        'imbalance': imbalance,
        'bid_depth': ob['bid_depth'],
        'ask_depth': ob['ask_depth'],
        'liquidity_levels': sorted(liquidity, key=lambda x: x['volume'], reverse=True),
    }
