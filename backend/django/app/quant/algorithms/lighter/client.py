"""
Lighter.xyz DEX client — async wrapper for the zk-powered orderbook.

Provides account info, market data, order placement, and position management
via the Lighter Python SDK (SignerClient + ApiClient).
"""
import asyncio
import logging
from typing import Optional

import lighter

from .config import (
    LIGHTER_API_URL,
    LIGHTER_PRIVATE_KEY,
    LIGHTER_API_KEY_INDEX,
    LIGHTER_ACCOUNT_INDEX,
    LIGHTER_MARKETS,
)

logger = logging.getLogger('app.lighter')

_signer: Optional[lighter.SignerClient] = None
_api: Optional[lighter.ApiClient] = None


def _get_api() -> lighter.ApiClient:
    global _api
    if _api is None:
        _api = lighter.ApiClient(
            configuration=lighter.Configuration(host=LIGHTER_API_URL)
        )
    return _api


def _get_signer() -> lighter.SignerClient:
    global _signer
    if _signer is None:
        if not LIGHTER_PRIVATE_KEY:
            raise ValueError("LIGHTER_PRIVATE_KEY not set")
        _signer = lighter.SignerClient(
            url=LIGHTER_API_URL,
            api_private_keys={LIGHTER_API_KEY_INDEX: LIGHTER_PRIVATE_KEY},
            account_index=LIGHTER_ACCOUNT_INDEX,
        )
        err = _signer.check_client()
        if err is not None:
            _signer = None
            raise ConnectionError(f"Lighter SignerClient check failed: {err}")
        logger.info("Lighter SignerClient initialized (account=%s, key_index=%s)", LIGHTER_ACCOUNT_INDEX, LIGHTER_API_KEY_INDEX)
    return _signer


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


# ── Read APIs ──────────────────────────────────────────────

def get_account_info() -> dict:
    api = _get_api()
    account_api = lighter.AccountApi(api)
    return _run(account_api.account(by="index", value=str(LIGHTER_ACCOUNT_INDEX)))


def get_orderbooks() -> dict:
    api = _get_api()
    order_api = lighter.OrderApi(api)
    return _run(order_api.order_books())


def get_orderbook_detail(market_id: int = 0) -> dict:
    api = _get_api()
    order_api = lighter.OrderApi(api)
    return _run(order_api.order_book_details(market_id=market_id))


def get_recent_trades(market_id: int = 0, limit: int = 20) -> dict:
    api = _get_api()
    order_api = lighter.OrderApi(api)
    return _run(order_api.recent_trades(market_id=market_id, limit=limit))


def get_candles(market_id: int = 0, resolution: str = '1h', count_back: int = 100) -> dict:
    import datetime
    api = _get_api()
    candle_api = lighter.CandlestickApi(api)
    now = int(datetime.datetime.now().timestamp())
    start = now - (count_back * 3600)  # rough estimate
    return _run(candle_api.candles(
        market_id=market_id,
        resolution=resolution,
        start_timestamp=start,
        end_timestamp=now,
        count_back=count_back,
    ))


def get_exchange_stats() -> dict:
    api = _get_api()
    order_api = lighter.OrderApi(api)
    return _run(order_api.exchange_stats())


# ── Trade APIs ─────────────────────────────────────────────

def place_market_order(symbol: str, is_buy: bool, base_amount: int, max_price_cents: int):
    """Place a market order on Lighter.

    Args:
        symbol: e.g. 'ETH', 'BTC'
        is_buy: True for buy, False for sell
        base_amount: amount in smallest units (1000 = 0.1 ETH)
        max_price_cents: worst acceptable price in cents (4000_00 = $4000)
    """
    market_index = LIGHTER_MARKETS.get(symbol)
    if market_index is None:
        raise ValueError(f"Unknown symbol: {symbol}. Available: {list(LIGHTER_MARKETS.keys())}")

    signer = _get_signer()

    async def _place():
        tx, tx_hash, err = await signer.create_market_order(
            market_index=market_index,
            client_order_index=0,
            base_amount=base_amount,
            avg_execution_price=max_price_cents,
            is_ask=not is_buy,  # is_ask=True means SELL
        )
        return {'tx': tx, 'tx_hash': tx_hash, 'error': str(err) if err else None}

    result = _run(_place())
    if result['error']:
        logger.error("Lighter order failed: %s %s %s — %s", symbol, 'BUY' if is_buy else 'SELL', base_amount, result['error'])
    else:
        logger.info("Lighter order placed: %s %s base_amount=%s tx_hash=%s", symbol, 'BUY' if is_buy else 'SELL', base_amount, result['tx_hash'])
    return result


def update_leverage(symbol: str, leverage: int, cross: bool = True):
    """Update leverage for a market."""
    market_index = LIGHTER_MARKETS.get(symbol)
    if market_index is None:
        raise ValueError(f"Unknown symbol: {symbol}")

    signer = _get_signer()

    async def _update():
        margin_mode = signer.CROSS_MARGIN_MODE if cross else signer.ISOLATED_MARGIN_MODE
        tx, tx_hash, err = await signer.update_leverage(
            market_index=market_index,
            leverage=leverage,
            margin_mode=margin_mode,
        )
        return {'tx': tx, 'tx_hash': tx_hash, 'error': str(err) if err else None}

    result = _run(_update())
    logger.info("Lighter leverage update: %s %dx cross=%s — %s", symbol, leverage, cross, result.get('error') or 'OK')
    return result


async def close_client():
    """Clean up connections."""
    global _signer, _api
    if _signer:
        await _signer.close()
        _signer = None
    if _api:
        await _api.close()
        _api = None
