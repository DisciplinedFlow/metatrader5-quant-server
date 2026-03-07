import logging
from typing import Optional
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from .config import HYPERLIQUID_PRIVATE_KEY, HYPERLIQUID_WALLET_ADDRESS, HYPERLIQUID_TESTNET

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
    global _exchange_instance
    if _exchange_instance is None:
        if not HYPERLIQUID_PRIVATE_KEY:
            raise ValueError("HYPERLIQUID_PRIVATE_KEY not set")
        _exchange_instance = Exchange(
            HYPERLIQUID_PRIVATE_KEY,
            get_base_url(),
            account_address=HYPERLIQUID_WALLET_ADDRESS or None,
        )
    return _exchange_instance


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
