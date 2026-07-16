"""
Trade flow analysis — detect whale orders and buy/sell pressure from recent trades.

Uses Lighter's recentTrades endpoint to build:
1. Aggressor ratio (taker buy vs sell volume)
2. Large trade detection (>3x median size)
3. CVD proxy (cumulative volume delta)

The is_maker_ask field tells us the aggressor:
- is_maker_ask=True on a buy = buyer aggressed into ask = bullish (taker buy)
- is_maker_ask=False on a sell = seller aggressed into bid = bearish (taker sell)
"""
import json
import logging
import statistics

from django.core.cache import cache

from .config import LIGHTER_MARKETS, get_market_id

logger = logging.getLogger('app.lighter')

# ── Configuration ─────────────────────────────────────────
CACHE_KEY_PREFIX = 'lighter:trade_flow'
CACHE_TTL = 30                     # 30 seconds — trade flow changes fast
LARGE_TRADE_MULTIPLIER = 3.0      # Trade > 3x median = "large"
WHALE_THRESHOLD_USD = 5000.0      # Single trade > $5K = whale
AGGRESSOR_IMBALANCE = 0.60        # >60% one side = directional pressure
DEFAULT_TRADE_LIMIT = 100         # Number of recent trades to analyze


def _fetch_recent_trades_raw(market_id: int, limit: int = 100) -> list:
    """Fetch recent trades using raw JSON (same pattern as liquidation_detector).

    Returns list of trade dicts from the Lighter API.
    """
    import asyncio
    import lighter
    from .config import LIGHTER_API_URL

    async def _fetch():
        api = lighter.ApiClient(configuration=lighter.Configuration(host=LIGHTER_API_URL))
        try:
            order_api = lighter.OrderApi(api)
            resp = await order_api.recent_trades_without_preload_content(
                market_id=market_id, limit=limit,
            )
            body = await resp.read()
            data = json.loads(body.decode())
            return data.get('trades', [])
        finally:
            await api.close()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, _fetch()).result(timeout=30)
    else:
        return asyncio.run(_fetch())


def analyze_trade_flow(symbol: str, lookback_trades: int = DEFAULT_TRADE_LIMIT) -> dict:
    """Analyze recent trade flow for a symbol.

    Returns dict with:
        buy_volume: total taker buy volume (USD)
        sell_volume: total taker sell volume (USD)
        aggressor_ratio: buy_volume / (buy_volume + sell_volume), 0-1
        cvd: cumulative volume delta (buy_vol - sell_vol)
        large_trades: list of trades > 3x median size
        whale_detected: True if any trade > $5K
        whale_direction: 'BUY', 'SELL', or None
        signal: 1 (buy pressure), -1 (sell pressure), 0 (balanced)
        trade_count: number of trades analyzed
    """
    neutral_result = {
        'buy_volume': 0.0,
        'sell_volume': 0.0,
        'aggressor_ratio': 0.5,
        'cvd': 0.0,
        'large_trades': [],
        'whale_detected': False,
        'whale_direction': None,
        'signal': 0,
        'trade_count': 0,
    }

    meta = LIGHTER_MARKETS.get(symbol)
    if meta is None:
        return neutral_result

    # Check Redis cache first
    cache_key = f'{CACHE_KEY_PREFIX}:{symbol}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    market_id = meta['id']

    try:
        trades = _fetch_recent_trades_raw(market_id, limit=lookback_trades)
    except Exception as e:
        logger.warning("Trade flow fetch failed for %s: %s", symbol, e)
        cache.set(cache_key, neutral_result, timeout=CACHE_TTL)
        return neutral_result

    if not trades:
        cache.set(cache_key, neutral_result, timeout=CACHE_TTL)
        return neutral_result

    # Parse trades into structured data
    parsed = []
    for t in trades:
        try:
            # usd_amount may be a string or number
            usd_amount = abs(float(t.get('usd_amount', 0)))
            price = float(t.get('price', 0))
            size = float(t.get('size', 0))

            # If usd_amount is 0 but we have price and size, calculate it
            if usd_amount == 0 and price > 0 and size > 0:
                usd_amount = price * size

            if usd_amount <= 0:
                continue

            # is_maker_ask=True means the maker was on the ask side,
            # so the taker was BUYING (aggressed into the ask)
            is_maker_ask = t.get('is_maker_ask', False)
            # Handle string booleans from JSON
            if isinstance(is_maker_ask, str):
                is_maker_ask = is_maker_ask.lower() == 'true'

            parsed.append({
                'usd_amount': usd_amount,
                'price': price,
                'size': size,
                'is_taker_buy': is_maker_ask,
                'timestamp': t.get('timestamp', 0),
                'trade_id': t.get('trade_id'),
                'type': t.get('type', 'trade'),
            })
        except (ValueError, TypeError):
            continue

    if not parsed:
        cache.set(cache_key, neutral_result, timeout=CACHE_TTL)
        return neutral_result

    # Calculate buy/sell volumes
    buy_volume = sum(t['usd_amount'] for t in parsed if t['is_taker_buy'])
    sell_volume = sum(t['usd_amount'] for t in parsed if not t['is_taker_buy'])
    total_volume = buy_volume + sell_volume

    # Aggressor ratio: 0 = all sells, 0.5 = balanced, 1 = all buys
    aggressor_ratio = buy_volume / total_volume if total_volume > 0 else 0.5

    # CVD (cumulative volume delta)
    cvd = buy_volume - sell_volume

    # Detect large trades (> 3x median size)
    amounts = [t['usd_amount'] for t in parsed]
    median_size = statistics.median(amounts) if amounts else 0

    large_trades = []
    whale_detected = False
    whale_buy_vol = 0.0
    whale_sell_vol = 0.0

    if median_size > 0:
        threshold = median_size * LARGE_TRADE_MULTIPLIER
        for t in parsed:
            if t['usd_amount'] > threshold:
                side = 'BUY' if t['is_taker_buy'] else 'SELL'
                large_trades.append({
                    'usd_amount': round(t['usd_amount'], 2),
                    'price': t['price'],
                    'side': side,
                    'timestamp': t['timestamp'],
                })
                # Track whale trades
                if t['usd_amount'] >= WHALE_THRESHOLD_USD:
                    whale_detected = True
                    if t['is_taker_buy']:
                        whale_buy_vol += t['usd_amount']
                    else:
                        whale_sell_vol += t['usd_amount']

    # Determine whale direction
    whale_direction = None
    if whale_detected:
        if whale_buy_vol > whale_sell_vol:
            whale_direction = 'BUY'
        elif whale_sell_vol > whale_buy_vol:
            whale_direction = 'SELL'
        else:
            whale_direction = 'MIXED'

    # Determine signal
    signal = 0
    if aggressor_ratio > AGGRESSOR_IMBALANCE:
        signal = 1   # Buy pressure dominates
    elif aggressor_ratio < (1 - AGGRESSOR_IMBALANCE):
        signal = -1  # Sell pressure dominates

    result = {
        'buy_volume': round(buy_volume, 2),
        'sell_volume': round(sell_volume, 2),
        'aggressor_ratio': round(aggressor_ratio, 4),
        'cvd': round(cvd, 2),
        'large_trades': large_trades[:10],  # Cap at 10 for logging sanity
        'whale_detected': whale_detected,
        'whale_direction': whale_direction,
        'signal': signal,
        'trade_count': len(parsed),
        'median_trade_usd': round(median_size, 2),
    }

    if signal != 0 or whale_detected:
        logger.info(
            "TRADE FLOW %s: signal=%d ratio=%.2f cvd=$%.0f buy=$%.0f sell=$%.0f "
            "whale=%s(%s) large=%d trades=%d",
            symbol, signal, aggressor_ratio, cvd, buy_volume, sell_volume,
            whale_detected, whale_direction or '-', len(large_trades), len(parsed),
        )

    # Cache for 30 seconds
    cache.set(cache_key, result, timeout=CACHE_TTL)
    return result
