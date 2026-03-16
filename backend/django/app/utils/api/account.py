"""
Django-side callers for MT5 account, margin, and order-check endpoints.

These let the entry algorithm:
  1. Check free margin before placing an order
  2. Dry-run an order to validate it will succeed
  3. Read account equity/balance for risk calculations
  4. Pre-calculate P&L using MT5's own math
"""

import traceback
from typing import Dict, Optional
import logging
from dotenv import load_dotenv

from app.utils.api.session import get_session, BASE_URL

load_dotenv()
logger = logging.getLogger(__name__)


def get_account_info() -> Optional[Dict]:
    """Fetch account info from MT5: balance, equity, margin, margin_free, leverage, profit.

    GET http://mt5:5001/account_info
    """
    try:
        url = f"{BASE_URL}/account_info"
        response = get_session().get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Exception fetching account info: {e}\n{traceback.format_exc()}")
        return None


# Backward-compatible alias (used in check_margin_safe and elsewhere)
account_info = get_account_info


def check_margin_for_order(symbol: str, volume: float, order_type: str = 'BUY',
                           price: float = None) -> Optional[Dict]:
    """Pre-calculate margin required for a trade.

    GET http://mt5:5001/order_calc_margin?action=BUY&symbol=EURUSD&volume=0.1&price=1.14

    Returns dict with keys: margin, margin_free, can_trade
    """
    try:
        url = f"{BASE_URL}/order_calc_margin"
        params = {
            "action": order_type,
            "symbol": symbol,
            "volume": volume,
        }
        if price is not None:
            params["price"] = price

        response = get_session().get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Exception calculating margin for {symbol}: {e}\n{traceback.format_exc()}")
        return None


# Backward-compatible alias
order_calc_margin = check_margin_for_order


def calc_profit(symbol: str, volume: float, price_open: float, price_close: float,
                order_type: str = 'BUY') -> Optional[float]:
    """Calculate P&L for a trade using MT5's own math.

    GET http://mt5:5001/order_calc_profit?action=BUY&symbol=EURUSD&volume=0.1&price_open=1.14&price_close=1.15

    Returns the profit as a float, or None on failure.
    """
    try:
        url = f"{BASE_URL}/order_calc_profit"
        params = {
            "action": order_type,
            "symbol": symbol,
            "volume": volume,
            "price_open": price_open,
            "price_close": price_close,
        }
        response = get_session().get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        # Endpoint returns {"profit": <float>} or the profit directly
        if isinstance(data, dict):
            return data.get('profit')
        return float(data)
    except Exception as e:
        logger.error(f"Exception calculating profit for {symbol}: {e}\n{traceback.format_exc()}")
        return None


def check_order(symbol: str, volume: float, order_type: str = 'BUY',
                sl: float = None, tp: float = None) -> Optional[Dict]:
    """Dry-run order validation - checks margin, stops, volume before sending.

    POST http://mt5:5001/order_check with order request body.

    Returns the full OrderCheckResult including retcode, margin impact,
    and comment explaining any rejection reason. retcode 0 = OK.
    """
    try:
        url = f"{BASE_URL}/order_check"
        payload = {
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
        }
        if sl is not None:
            payload["sl"] = sl
        if tp is not None:
            payload["tp"] = tp

        response = get_session().post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Exception in order_check for {symbol}: {e}\n{traceback.format_exc()}")
        return None


# Backward-compatible alias
order_check_dry_run = check_order


def terminal_info() -> Optional[Dict]:
    """Fetch MT5 terminal status — connected, trade_allowed, build."""
    try:
        url = f"{BASE_URL}/terminal_info"
        response = get_session().get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Exception fetching terminal info: {e}\n{traceback.format_exc()}")
        return None


def check_margin_safe(symbol: str, volume: float, action: str = 'BUY',
                      min_margin_level: float = 200.0) -> bool:
    """
    Pre-trade margin safety check.

    Returns True if placing this order keeps margin_level above min_margin_level (%).
    Default 200% = conservative buffer (broker margin call typically at 100%).
    """
    result = check_margin_for_order(symbol, volume, action)
    if result is None:
        logger.warning(f"Margin check failed for {symbol} — allowing trade (fail-open)")
        return True

    can_trade = result.get('can_trade')
    if can_trade is False:
        logger.warning(f"MARGIN BLOCKED {symbol} {action} {volume} lots: "
                       f"required={result.get('margin'):.2f} free={result.get('margin_free'):.2f}")
        return False

    # Check margin level stays healthy
    info = get_account_info()
    if info and info.get('margin_level') and info['margin_level'] < min_margin_level:
        logger.warning(f"MARGIN LEVEL LOW: {info['margin_level']:.1f}% < {min_margin_level}% — blocking trade")
        return False

    return True
