import logging
import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from .config import (POLYMARKET_PRIVATE_KEY, POLYMARKET_FUNDER_ADDRESS, POLYMARKET_API_KEY,
                     POLYMARKET_API_SECRET, POLYMARKET_API_PASSPHRASE, POLYMARKET_CHAIN_ID,
                     POLYMARKET_SIGNATURE_TYPE)

logger = logging.getLogger('app.polymarket')

_client = None

DATA_API_BASE = "https://data-api.polymarket.com"


def get_client():
    """Singleton CLOB client."""
    global _client
    if _client is None:
        host = "https://clob.polymarket.com"
        funder = POLYMARKET_FUNDER_ADDRESS or None
        _client = ClobClient(
            host,
            key=POLYMARKET_PRIVATE_KEY,
            chain_id=POLYMARKET_CHAIN_ID,
            signature_type=POLYMARKET_SIGNATURE_TYPE,
            funder=funder,
        )
        # Set API credentials if available
        if POLYMARKET_API_KEY:
            _client.set_api_creds(ClobClient.ApiCreds(
                api_key=POLYMARKET_API_KEY,
                api_secret=POLYMARKET_API_SECRET,
                api_passphrase=POLYMARKET_API_PASSPHRASE,
            ))
        logger.info("CLOB client initialized (funder=%s)", funder[:10] + '...' if funder else 'None')
    return _client


def get_markets(next_cursor="MA=="):
    """Fetch markets from Polymarket CLOB API using cursor-based pagination."""
    client = get_client()
    try:
        response = client.get_markets(next_cursor=next_cursor)
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


# ─── Data API (positions, trades, activity) ───

def get_positions(wallet_address=None):
    """Fetch current positions from the Polymarket Data API.

    Returns list of positions with size, avgPrice, currentValue, cashPnl, percentPnl, etc.
    """
    address = wallet_address or POLYMARKET_FUNDER_ADDRESS
    if not address:
        logger.warning("No wallet address configured for position lookup")
        return []
    try:
        resp = requests.get(f"{DATA_API_BASE}/positions", params={"user": address}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        return []


def get_activity(wallet_address=None, activity_type=None, limit=50):
    """Fetch trade activity from the Polymarket Data API.

    activity_type: TRADE, SPLIT, MERGE, REDEEM, REWARD, CONVERSION (or None for all)
    """
    address = wallet_address or POLYMARKET_FUNDER_ADDRESS
    if not address:
        return []
    params = {"user": address, "limit": limit}
    if activity_type:
        params["type"] = activity_type
    try:
        resp = requests.get(f"{DATA_API_BASE}/activity", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error fetching activity: {e}")
        return []


def get_trades(wallet_address=None, limit=50):
    """Fetch trade history from the Polymarket Data API."""
    address = wallet_address or POLYMARKET_FUNDER_ADDRESS
    if not address:
        return []
    try:
        resp = requests.get(f"{DATA_API_BASE}/trades", params={"user": address, "limit": limit}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error fetching trades: {e}")
        return []
