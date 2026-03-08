import logging
from typing import Optional
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from .config import HYPERLIQUID_PRIVATE_KEY, HYPERLIQUID_WALLET_ADDRESS, HYPERLIQUID_TESTNET, HYPERLIQUID_AGENT_KEY

logger = logging.getLogger('app.crypto')

_info_instance: Optional[Info] = None
_exchange_instance: Optional[Exchange] = None


def get_base_url():
    return constants.TESTNET_API_URL if HYPERLIQUID_TESTNET else constants.MAINNET_API_URL


def get_info() -> Info:
    global _info_instance
    if _info_instance is None:
        _info_instance = Info(get_base_url(), skip_ws=True)
    return _info_instance


def get_exchange() -> Exchange:
    """Get the Exchange instance. Prefers agent key (trade-only, no withdrawals) over master key."""
    global _exchange_instance
    if _exchange_instance is None:
        trading_key = HYPERLIQUID_AGENT_KEY or HYPERLIQUID_PRIVATE_KEY
        if not trading_key:
            raise ValueError("Neither HYPERLIQUID_AGENT_KEY nor HYPERLIQUID_PRIVATE_KEY is set")
        _exchange_instance = Exchange(
            trading_key,
            get_base_url(),
            account_address=HYPERLIQUID_WALLET_ADDRESS or None,
        )
        key_type = "agent" if HYPERLIQUID_AGENT_KEY else "master"
        logger.info("Exchange initialized with %s key (testnet=%s)", key_type, HYPERLIQUID_TESTNET)
    return _exchange_instance


def create_agent_wallet(name: str = "quant_bot") -> dict:
    """Create an agent wallet using the master key. Run once, store the returned key securely.

    The agent key can only trade — it cannot withdraw funds. If compromised, revoke and recreate.
    Returns: {"status": ..., "agent_key": "0x..."}
    """
    if not HYPERLIQUID_PRIVATE_KEY:
        raise ValueError("HYPERLIQUID_PRIVATE_KEY (master key) required to create agent wallet")
    master_exchange = Exchange(HYPERLIQUID_PRIVATE_KEY, get_base_url())
    result = master_exchange.approve_agent(name=name)
    logger.info("Agent wallet created: name=%s, result=%s", name, result[0] if result else None)
    return {"status": result[0], "agent_key": result[1] if len(result) > 1 else None}


def get_all_mids() -> dict:
    info = get_info()
    return info.all_mids()


def get_user_state() -> dict:
    info = get_info()
    if not HYPERLIQUID_WALLET_ADDRESS:
        return {}
    return info.user_state(HYPERLIQUID_WALLET_ADDRESS)


def get_candles(symbol: str, interval: str = '1h', limit: int = 500) -> list:
    info = get_info()
    import time
    end_time = int(time.time() * 1000)
    interval_ms = {
        '1m': 60_000, '5m': 300_000, '15m': 900_000,
        '1h': 3_600_000, '4h': 14_400_000, '1d': 86_400_000,
    }
    ms = interval_ms.get(interval, 3_600_000)
    start_time = end_time - (limit * ms)
    return info.candles_snapshot(symbol, interval, start_time, end_time)


def place_market_order(symbol: str, is_buy: bool, size: float, leverage: int = 1):
    exchange = get_exchange()
    exchange.update_leverage(leverage, symbol)
    order_result = exchange.market_open(symbol, is_buy, size)
    logger.info(f"Market order placed: {symbol} {'BUY' if is_buy else 'SELL'} {size} - {order_result}")
    return order_result


def close_position(symbol: str):
    exchange = get_exchange()
    info = get_info()
    user_state = info.user_state(HYPERLIQUID_WALLET_ADDRESS)
    for pos in user_state.get('assetPositions', []):
        position = pos.get('position', {})
        if position.get('coin') == symbol:
            size = abs(float(position.get('szi', 0)))
            if size > 0:
                is_buy = float(position.get('szi', 0)) < 0  # close short = buy, close long = sell
                result = exchange.market_close(symbol)
                logger.info(f"Position closed: {symbol} - {result}")
                return result
    return None
