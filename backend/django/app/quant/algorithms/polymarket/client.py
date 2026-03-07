import logging
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from .config import (POLYMARKET_PRIVATE_KEY, POLYMARKET_API_KEY, POLYMARKET_API_SECRET,
                     POLYMARKET_API_PASSPHRASE, POLYMARKET_CHAIN_ID, POLYMARKET_SIGNATURE_TYPE)

logger = logging.getLogger('app.polymarket')

_client = None


def get_client():
    """Singleton CLOB client."""
    global _client
    if _client is None:
        host = "https://clob.polymarket.com"
        _client = ClobClient(
            host,
            key=POLYMARKET_PRIVATE_KEY,
            chain_id=POLYMARKET_CHAIN_ID,
            signature_type=POLYMARKET_SIGNATURE_TYPE,
            funder=POLYMARKET_PRIVATE_KEY,
        )
        # Set API credentials if available
        if POLYMARKET_API_KEY:
            _client.set_api_creds(ClobClient.ApiCreds(
                api_key=POLYMARKET_API_KEY,
                api_secret=POLYMARKET_API_SECRET,
                api_passphrase=POLYMARKET_API_PASSPHRASE,
            ))
        logger.info("CLOB client initialized")
    return _client


def get_markets(limit=100, active=True):
    """Fetch markets from Polymarket CLOB API."""
    client = get_client()
    try:
        params = {"limit": limit, "active": active}
        response = client.get_markets(**params)
        return response if isinstance(response, list) else response.get('data', [])
    except Exception as e:
        logger.error(f"Error fetching markets: {e}")
        return []


def get_market(condition_id):
    """Fetch a single market by condition_id."""
    client = get_client()
    try:
        return client.get_market(condition_id)
    except Exception as e:
        logger.error(f"Error fetching market {condition_id}: {e}")
        return None


def get_order_book(token_id):
    """Fetch order book for a token."""
    client = get_client()
    try:
        return client.get_order_book(token_id)
    except Exception as e:
        logger.error(f"Error fetching order book: {e}")
        return None


def place_market_order(token_id, side, size):
    """Place a market order. side='BUY' or 'SELL', size in USDC."""
    client = get_client()
    try:
        order_args = OrderArgs(
            token_id=token_id,
            price=None,  # market order
            size=size,
            side=side,
        )
        response = client.create_and_post_order(order_args)
        logger.info(f"Order placed: token={token_id}, side={side}, size={size}, response={response}")
        return response
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return None


def cancel_order(order_id):
    """Cancel an open order."""
    client = get_client()
    try:
        return client.cancel(order_id)
    except Exception as e:
        logger.error(f"Error cancelling order {order_id}: {e}")
        return None
