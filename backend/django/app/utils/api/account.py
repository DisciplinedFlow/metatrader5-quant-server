"""
Django-side callers for MT5 account, margin, and order-check endpoints.

These let the entry algorithm:
  1. Check free margin before placing an order
  2. Dry-run an order to validate it will succeed
  3. Read account equity/balance for risk calculations
"""

import traceback
from typing import Dict, Optional
import logging
from dotenv import load_dotenv

from app.utils.api.session import get_session, BASE_URL

load_dotenv()
logger = logging.getLogger(__name__)


def account_info() -> Optional[Dict]:
    """Fetch account balance, equity, margin, free margin, leverage."""
    try:
        url = f"{BASE_URL}/account_info"
        response = get_session().get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Exception fetching account info: {e}\n{traceback.format_exc()}")
        return None


def order_calc_margin(symbol: str, volume: float, action: str = 'BUY', price: float = None) -> Optional[Dict]:
    """
    Calculate margin required for a hypothetical order.

    Returns dict with keys: margin, margin_free, can_trade
    """
    try:
        url = f"{BASE_URL}/order_calc_margin"
        payload = {
            "action": action,
            "symbol": symbol,
            "volume": volume,
        }
        if price is not None:
            payload["price"] = price

        response = get_session().post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Exception calculating margin for {symbol}: {e}\n{traceback.format_exc()}")
        return None


def order_check(symbol: str, volume: float, order_type: str = 'BUY',
                sl: float = None, tp: float = None) -> Optional[Dict]:
    """
    Dry-run an order without execution.

    Returns the full OrderCheckResult including retcode, margin impact,
    and comment explaining any rejection reason.
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
    result = order_calc_margin(symbol, volume, action)
    if result is None:
        logger.warning(f"Margin check failed for {symbol} — allowing trade (fail-open)")
        return True

    can_trade = result.get('can_trade')
    if can_trade is False:
        logger.warning(f"MARGIN BLOCKED {symbol} {action} {volume} lots: "
                       f"required={result.get('margin'):.2f} free={result.get('margin_free'):.2f}")
        return False

    # Check margin level stays healthy
    info = account_info()
    if info and info.get('margin_level') and info['margin_level'] < min_margin_level:
        logger.warning(f"MARGIN LEVEL LOW: {info['margin_level']:.1f}% < {min_margin_level}% — blocking trade")
        return False

    return True
