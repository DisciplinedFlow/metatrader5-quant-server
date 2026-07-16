from typing import Dict
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging
import traceback
from app.utils.constants import MT5Timeframe
from app.utils.constants import TIMEZONE
from app.utils.api.session import get_session, BASE_URL

load_dotenv()
logger = logging.getLogger(__name__)

def history_deals_get(from_date: datetime, to_date: datetime, position: int = None) -> Dict:
    try:
        params = {
            'from_date': from_date.isoformat(),
            'to_date': to_date.isoformat()
        }
        
        if position is not None:
            params['position'] = position
            
        url = f"{BASE_URL}/history_deals_get"
        response = get_session().get(url, params=params, timeout=10)
        response.raise_for_status()
        
        return response.json()
    except Exception as e:
        error_msg = f"Exception fetching history deals: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

def history_orders_get(ticket: int) -> Dict:
    try:
        params = {'ticket': ticket}
            
        url = f"{BASE_URL}/history_orders_get"
        response = get_session().get(url, params=params, timeout=10)
        response.raise_for_status()
        
        return response.json()
    except Exception as e:
        error_msg = f"Exception fetching history orders for ticket {ticket}: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

def get_deal_from_ticket(ticket: int, from_date: datetime, to_date: datetime) -> Dict:
    """Get deal history for a position ticket from MT5.

    Filters the raw deal list to only include deals matching this position_id,
    then separates entry (entry=0) and exit (entry=1) deals.
    """
    deals = history_deals_get(from_date, to_date, position=ticket)
    if not deals:
        logger.debug(f"No deal history for position {ticket}")
        return None

    # Filter to only deals for THIS position (MT5 returns broad matches)
    pos_deals = [d for d in deals if d.get('position_id') == ticket]
    if not pos_deals:
        logger.debug(f"No deals matching position_id={ticket}")
        return None

    # Separate entry and exit deals
    entry_deals = [d for d in pos_deals if d.get('entry') == 0]
    exit_deals = [d for d in pos_deals if d.get('entry') == 1]

    if not entry_deals:
        logger.debug(f"No entry deal found for position {ticket}")
        return None

    entry = entry_deals[0]
    symbol = entry['symbol']

    # If no exit deal yet, position is still open
    if not exit_deals:
        return {
            'ticket': ticket,
            'symbol': symbol,
            'type': 'BUY' if entry.get('type') == 0 else 'SELL',
            'volume': entry.get('volume', 0),
            'open_time': datetime.fromtimestamp(entry['time'], tz=TIMEZONE),
            'open_price': entry['price'],
            'close_time': None,
            'close_price': None,
            'profit': 0,
            'commission': sum(d.get('commission', 0) for d in pos_deals),
            'swap': sum(d.get('swap', 0) for d in pos_deals),
            'comment': entry.get('comment', ''),
            'still_open': True,
        }

    exit_deal = exit_deals[-1]  # Last exit deal (handles partial closes)
    total_profit = sum(d.get('profit', 0) for d in pos_deals)
    total_commission = sum(d.get('commission', 0) for d in pos_deals)
    total_swap = sum(d.get('swap', 0) for d in pos_deals)

    return {
        'ticket': ticket,
        'symbol': symbol,
        'type': 'BUY' if entry.get('type') == 0 else 'SELL',
        'volume': entry.get('volume', 0),
        'open_time': datetime.fromtimestamp(entry['time'], tz=TIMEZONE),
        'close_time': datetime.fromtimestamp(exit_deal['time'], tz=TIMEZONE),
        'open_price': entry['price'],
        'close_price': exit_deal['price'],
        'profit': total_profit,
        'commission': total_commission,
        'swap': total_swap,
        'comment': exit_deal.get('comment', ''),
        'still_open': False,
    }


def history_deals_bulk(from_date: datetime, to_date: datetime) -> list:
    """Fetch ALL deals in date range (no position filter). For reconciliation.

    GET http://mt5:5001/history_deals_get?from_date=...&to_date=...
    The position parameter is now optional on the MT5 side, so omitting it
    returns every deal in the window — much more efficient than per-ticket queries.

    Returns a list of deal dicts, or an empty list on failure.
    """
    try:
        params = {
            'from_date': from_date.isoformat(),
            'to_date': to_date.isoformat(),
        }
        url = f"{BASE_URL}/history_deals_get"
        response = get_session().get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data is None:
            return []
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Exception fetching bulk deal history: {e}\n{traceback.format_exc()}")
        return []


def get_order_from_ticket(ticket: int) -> Dict:
    # Get the order history
    orders = history_orders_get(ticket=ticket)
    if orders is None or len(orders) == 0:
        error_msg = f"No order history found for ticket {ticket}"
        logger.error(error_msg)
        return None

    # Directly use the dictionary without calling _asdict()
    order_dict = orders[0]

    return order_dict