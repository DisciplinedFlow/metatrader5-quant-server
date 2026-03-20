"""
Lighter.xyz DEX client — read ops via ApiClient (pure Python, Docker-safe),
write ops via signer proxy (HTTP to native macOS process).

The SignerClient uses a Go native library that crashes under QEMU emulation
in Docker on arm64 Mac. Write operations go through a lightweight HTTP proxy
running natively on the host.

Note: The Lighter ApiClient uses aiohttp, which requires construction inside
an async context. All API calls create fresh clients per-request.
"""
import asyncio
import datetime
import logging
import requests

import lighter

from .config import (
    LIGHTER_API_URL,
    LIGHTER_ACCOUNT_INDEX,
    LIGHTER_SIGNER_PROXY_URL,
    LIGHTER_MARKETS,
    LIGHTER_MAX_SLIPPAGE,
    get_market_id,
)

logger = logging.getLogger('app.lighter')


def _run(coro):
    """Run an async coroutine from sync Django/Celery code."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result(timeout=30)
    else:
        return asyncio.run(coro)


# ── Read APIs (pure Python, Docker-safe) ─────────────────

def get_account_info() -> dict:
    async def _fetch():
        api = lighter.ApiClient(configuration=lighter.Configuration(host=LIGHTER_API_URL))
        try:
            account_api = lighter.AccountApi(api)
            return await account_api.account(by="index", value=str(LIGHTER_ACCOUNT_INDEX))
        finally:
            await api.close()
    return _run(_fetch())


def get_orderbook_detail(market_id: int = 0) -> dict:
    async def _fetch():
        api = lighter.ApiClient(configuration=lighter.Configuration(host=LIGHTER_API_URL))
        try:
            order_api = lighter.OrderApi(api)
            return await order_api.order_book_details(market_id=market_id)
        finally:
            await api.close()
    return _run(_fetch())


def get_recent_trades(market_id: int = 0, limit: int = 20) -> dict:
    async def _fetch():
        api = lighter.ApiClient(configuration=lighter.Configuration(host=LIGHTER_API_URL))
        try:
            order_api = lighter.OrderApi(api)
            return await order_api.recent_trades(market_id=market_id, limit=limit)
        finally:
            await api.close()
    return _run(_fetch())


def get_candles(symbol: str, resolution: str = '1h', count_back: int = 100) -> list:
    """Fetch candle data for a symbol. Returns list of candle dicts.

    Note: The SDK's Pydantic model has a bug where OHLC fields return None
    (field name collision between Candle.c and Candles.c). We parse raw JSON.
    """
    import json
    market_id = get_market_id(symbol)

    async def _fetch():
        api = lighter.ApiClient(configuration=lighter.Configuration(host=LIGHTER_API_URL))
        try:
            candle_api = lighter.CandlestickApi(api)
            now = int(datetime.datetime.now().timestamp())
            resolution_seconds = {
                '1m': 60, '5m': 300, '15m': 900, '30m': 1800,
                '1h': 3600, '4h': 14400, '1d': 86400,
            }
            secs = resolution_seconds.get(resolution, 3600)
            start = now - (count_back * secs)
            # Use raw response to work around SDK Pydantic parsing bug
            resp = await candle_api.candles_without_preload_content(
                market_id=market_id,
                resolution=resolution,
                start_timestamp=start,
                end_timestamp=now,
                count_back=count_back,
            )
            body = await resp.read()
            data = json.loads(body.decode())
            candles = data.get('c', [])
            return [{'t': c['t'], 'o': c['o'], 'h': c['h'], 'l': c['l'], 'c': c['c'], 'v': c.get('V', c.get('v', 0))}
                    for c in candles if c.get('o') is not None]
        finally:
            await api.close()

    return _run(_fetch())


def get_best_bid_ask(symbol: str) -> dict:
    """Get current best bid/ask from orderbook.

    Results are cached in Redis for 8 seconds. All Celery workers share
    this cache, so concurrent tasks (exit, entry, scalper) hitting the
    same symbol within one cycle make only ONE real API call instead of
    5+. This prevents CloudFront 429 rate-limiting under high position counts.
    """
    from django.core.cache import cache
    cache_key = f'lighter:price:{symbol}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    market_id = get_market_id(symbol)

    async def _fetch():
        api = lighter.ApiClient(configuration=lighter.Configuration(host=LIGHTER_API_URL))
        try:
            order_api = lighter.OrderApi(api)
            ob = await order_api.order_book_orders(market_id=market_id, limit=1)
            best_bid = float(ob.bids[0].price) if hasattr(ob, 'bids') and ob.bids else None
            best_ask = float(ob.asks[0].price) if hasattr(ob, 'asks') and ob.asks else None
            mid = (best_bid + best_ask) / 2 if best_bid and best_ask else None
            return {'bid': best_bid, 'ask': best_ask, 'mid': mid, 'last': mid}
        finally:
            await api.close()

    result = _run(_fetch())
    if result.get('mid'):  # only cache valid responses
        cache.set(cache_key, result, timeout=20)
    return result


def get_exchange_stats() -> dict:
    async def _fetch():
        api = lighter.ApiClient(configuration=lighter.Configuration(host=LIGHTER_API_URL))
        try:
            order_api = lighter.OrderApi(api)
            return await order_api.exchange_stats()
        finally:
            await api.close()
    return _run(_fetch())


def get_recent_liquidations(market_id: int = 0, limit: int = 100) -> list:
    """Fetch recent liquidation events from Lighter API.

    Uses recent_trades endpoint and filters for liquidation/deleverage types.
    Each trade has type in ('trade', 'liquidation', 'deleverage', 'market-settlement').
    Falls back to raw HTTP if SDK parsing fails.

    Returns list of dicts: {trade_id, type, market_id, price, size, usd_amount, timestamp, is_maker_ask}
    """
    import json

    async def _fetch():
        api = lighter.ApiClient(configuration=lighter.Configuration(host=LIGHTER_API_URL))
        try:
            order_api = lighter.OrderApi(api)
            # Use raw response to avoid SDK parsing issues (same pattern as candles)
            resp = await order_api.recent_trades_without_preload_content(
                market_id=market_id, limit=limit,
            )
            body = await resp.read()
            data = json.loads(body.decode())
            trades = data.get('trades', [])
            # Filter for liquidation and deleverage trades only
            liq_trades = []
            for t in trades:
                if t.get('type') in ('liquidation', 'deleverage'):
                    liq_trades.append({
                        'trade_id': t.get('trade_id'),
                        'type': t.get('type'),
                        'market_id': t.get('market_id'),
                        'price': t.get('price', '0'),
                        'size': t.get('size', '0'),
                        'usd_amount': t.get('usd_amount', '0'),
                        'timestamp': t.get('timestamp', 0),
                        'is_maker_ask': t.get('is_maker_ask', False),
                    })
            return liq_trades
        finally:
            await api.close()

    try:
        return _run(_fetch())
    except Exception as e:
        # Fallback: raw HTTP request
        logger.warning("SDK liquidation fetch failed, trying raw HTTP: %s", e)
        return _fetch_liquidations_http(market_id, limit)


def _fetch_liquidations_http(market_id: int = 0, limit: int = 100) -> list:
    """Fallback: fetch liquidations via raw HTTP to Lighter API."""
    url = f"{LIGHTER_API_URL}/api/v1/recent_trades"
    try:
        resp = requests.get(url, params={'market_id': market_id, 'limit': limit}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        trades = data.get('trades', [])
        return [
            {
                'trade_id': t.get('trade_id'),
                'type': t.get('type'),
                'market_id': t.get('market_id'),
                'price': t.get('price', '0'),
                'size': t.get('size', '0'),
                'usd_amount': t.get('usd_amount', '0'),
                'timestamp': t.get('timestamp', 0),
                'is_maker_ask': t.get('is_maker_ask', False),
            }
            for t in trades if t.get('type') in ('liquidation', 'deleverage')
        ]
    except Exception as e:
        logger.error("Raw HTTP liquidation fetch failed: %s", e)
        return []


# ── Write APIs (via signer proxy) ────────────────────────

def _proxy_post(endpoint: str, data: dict) -> dict:
    """Send a trading request to the native signer proxy."""
    url = f"{LIGHTER_SIGNER_PROXY_URL}{endpoint}"
    try:
        resp = requests.post(url, json=data, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get('error'):
            logger.error("Lighter proxy error on %s: %s", endpoint, result['error'])
        return result
    except requests.ConnectionError:
        logger.error("Lighter signer proxy not reachable at %s. Is it running?", LIGHTER_SIGNER_PROXY_URL)
        return {'error': 'Signer proxy not reachable'}
    except requests.HTTPError as e:
        try:
            result = e.response.json()
        except Exception:
            result = {'error': str(e)}
        logger.error("Lighter proxy HTTP error on %s: %s", endpoint, result.get('error', str(e)))
        return result
    except Exception as e:
        logger.error("Lighter proxy request failed: %s", e)
        return {'error': str(e)}


def place_market_order_usd(symbol: str, is_buy: bool, quote_amount_usd: float) -> dict:
    """Place a market order by USD amount. Routes through signer proxy."""
    result = _proxy_post('/order/market', {
        'symbol': symbol,
        'is_buy': is_buy,
        'quote_amount_usd': quote_amount_usd,
        'max_slippage': LIGHTER_MAX_SLIPPAGE,
    })
    action = 'BUY' if is_buy else 'SELL'
    if result.get('error'):
        logger.error("Lighter order failed: %s %s $%.2f — %s", symbol, action, quote_amount_usd, result['error'])
    else:
        logger.info("Lighter order placed: %s %s $%.2f tx=%s", symbol, action, quote_amount_usd, result.get('tx_hash', '?'))
    return result


def place_limit_order(symbol: str, is_buy: bool, base_amount: float, price: float) -> dict:
    """Place a limit order. Routes through signer proxy."""
    return _proxy_post('/order/limit', {
        'symbol': symbol,
        'is_buy': is_buy,
        'base_amount': base_amount,
        'price': price,
    })


def place_limit_order_post_only(symbol: str, is_buy: bool, base_amount: float, price: float) -> dict:
    """Place a post-only limit order (maker only). Routes through signer proxy."""
    return _proxy_post('/order/limit', {
        'symbol': symbol,
        'is_buy': is_buy,
        'base_amount': base_amount,
        'price': price,
        'post_only': True,
    })


def place_twap_order(symbol: str, is_buy: bool, quote_amount_usd: float, duration_seconds: int = 300) -> dict:
    """Place a TWAP order that executes over a duration. Routes through signer proxy."""
    return _proxy_post('/order/twap', {
        'symbol': symbol,
        'is_buy': is_buy,
        'quote_amount_usd': quote_amount_usd,
        'duration_seconds': duration_seconds,
    })


def place_batch_orders(orders: list) -> dict:
    """Place multiple limit orders in a single batch. Routes through signer proxy.

    Each order dict: {'symbol': str, 'is_buy': bool, 'base_amount': float,
                      'price': float, 'post_only': bool (optional)}
    """
    return _proxy_post('/order/batch', {'orders': orders})


def place_stop_loss(symbol: str, is_buy: bool, base_amount: float, trigger_price: float) -> dict:
    """Place a stop-loss order. Routes through signer proxy."""
    return _proxy_post('/order/stop-loss', {
        'symbol': symbol,
        'is_buy': is_buy,
        'base_amount': base_amount,
        'trigger_price': trigger_price,
    })


def place_take_profit(symbol: str, is_buy: bool, base_amount: float, trigger_price: float) -> dict:
    """Place a take-profit order. Routes through signer proxy."""
    return _proxy_post('/order/take-profit', {
        'symbol': symbol,
        'is_buy': is_buy,
        'base_amount': base_amount,
        'trigger_price': trigger_price,
    })


def place_oco_sltp(symbol: str, is_long: bool, base_amount: float, stop_loss_price: float, take_profit_price: float) -> dict:
    """Place SL + TP as a poor-man's OCO via individual orders.

    The proxy places separate SL and TP orders (native OCO is broken on
    Lighter) and registers the pair for cleanup tracking. When one fills,
    the reconciler cancels the other.

    If the first attempt fails due to pending order quota, cancels all open
    limit orders for this symbol and retries once.
    """
    payload = {
        'symbol': symbol,
        'is_long': is_long,
        'base_amount': base_amount,
        'stop_loss_price': stop_loss_price,
        'take_profit_price': take_profit_price,
    }
    result = _proxy_post('/order/oco-sltp', payload)

    # Retry once after clearing pending orders if quota exceeded.
    if result.get('error') and 'pending order count' in str(result.get('error', '')):
        logger.warning("Lighter OCO %s: order quota hit — cancelling pending orders and retrying", symbol)
        try:
            cancel_all_orders(symbol)
        except Exception as e:
            logger.debug("OCO retry: cancel failed: %s", e)
        result = _proxy_post('/order/oco-sltp', payload)

    if result.get('error'):
        logger.error("Lighter OCO SL/TP failed: %s %s SL=%.4f TP=%.4f — %s",
                      symbol, 'LONG' if is_long else 'SHORT',
                      stop_loss_price, take_profit_price, result['error'])
    else:
        logger.info("Lighter OCO SL/TP placed: %s %s SL=%.4f TP=%.4f sl_tx=%s tp_tx=%s",
                     symbol, 'LONG' if is_long else 'SHORT',
                     stop_loss_price, take_profit_price,
                     result.get('sl_tx_hash', '?'), result.get('tp_tx_hash', '?'))
    return result


def get_oco_pairs() -> list:
    """Get active OCO pairs from the signer proxy."""
    try:
        url = f"{LIGHTER_SIGNER_PROXY_URL}/oco/pairs"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json().get('pairs', [])
    except Exception as e:
        logger.debug("Failed to get OCO pairs: %s", e)
        return []


def remove_oco_pair(symbol: str) -> dict:
    """Remove an OCO pair after one side fills (called during reconcile)."""
    return _proxy_post('/oco/remove', {'symbol': symbol})


def close_position(symbol: str) -> dict:
    """Close entire position for a symbol. Routes through signer proxy."""
    return _proxy_post('/position/close', {'symbol': symbol})


def update_leverage(symbol: str, leverage: int, cross: bool = True) -> dict:
    """Update leverage for a market. Routes through signer proxy."""
    return _proxy_post('/leverage', {
        'symbol': symbol,
        'leverage': leverage,
        'cross': cross,
    })


def cancel_all_orders(symbol: str = None) -> dict:
    """Cancel all open orders (optionally for a specific symbol)."""
    data = {}
    if symbol:
        data['symbol'] = symbol
    return _proxy_post('/orders/cancel-all', data)


# ---------------------------------------------------------------------------
# Fill capture — query exchange for actual fill prices after order execution
# ---------------------------------------------------------------------------

_ID_TO_SYMBOL = {v['id']: k for k, v in LIGHTER_MARKETS.items()}


def get_position_fill(symbol: str) -> dict:
    """Get the current exchange position state for a symbol.

    Returns dict with 'entry_price', 'size', 'side' from the exchange,
    or empty dict if no position found.
    """
    try:
        acct = get_account_info()
        a = acct.accounts[0] if hasattr(acct, 'accounts') and acct.accounts else None
        if not a:
            return {}
        market_id = get_market_id(symbol)
        for pos in (a.positions or []):
            if int(pos.market_id) == market_id and float(pos.position) != 0:
                return {
                    'entry_price': float(pos.avg_entry_price),
                    'size': float(pos.position),
                    'side': 'LONG' if int(pos.sign) > 0 else 'SHORT',
                }
        return {}
    except Exception as e:
        logger.debug("get_position_fill failed for %s: %s", symbol, e)
        return {}


def get_trade_fill(tx_hash: str) -> dict:
    """Get actual fill data for a trade by its tx_hash from the exchange.

    Returns dict with 'price', 'size', 'pnl', 'fee' from the exchange,
    or empty dict if not found. Queries the authenticated /trades endpoint
    via the signer proxy.
    """
    try:
        url = f"{LIGHTER_SIGNER_PROXY_URL}/trades?limit=10"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        trades = data if isinstance(data, list) else data.get('trades', data.get('data', []))
        for t in trades:
            if t.get('tx_hash') == tx_hash:
                # Determine which side we are
                is_our_ask = t.get('ask_account_id') == LIGHTER_ACCOUNT_INDEX
                is_our_bid = t.get('bid_account_id') == LIGHTER_ACCOUNT_INDEX
                pnl = None
                fee = None
                if is_our_ask:
                    pnl = t.get('ask_account_pnl')
                    fee = t.get('taker_fee') or t.get('maker_fee')
                elif is_our_bid:
                    pnl = t.get('bid_account_pnl')
                    fee = t.get('taker_fee') or t.get('maker_fee')
                return {
                    'price': float(t['price']),
                    'size': float(t['size']),
                    'pnl': float(pnl) if pnl is not None else None,
                    'fee': float(fee) / 10000 if fee is not None else None,
                }
        return {}
    except Exception as e:
        logger.debug("get_trade_fill failed for tx %s: %s", tx_hash[:16], e)
        return {}
