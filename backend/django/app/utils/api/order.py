import os
import requests
import traceback
from typing import List, Dict
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import logging

from app.utils.constants import MT5Timeframe
from app.utils.api.data import symbol_info_tick
from app.utils.api.session import get_session, BASE_URL
from app.nexus.models import Trade, TradeClosePricesMutation  # Import models
from app.utils.arithmetics import get_pnl_at_price, calculate_commission, get_price_at_pnl, calculate_order_capital, calculate_order_size_usd

load_dotenv()
logger = logging.getLogger(__name__)

def send_market_order(symbol: str, volume: float, order_type: str, sl: float, tp: float = None,
                      deviation: int = 20, comment: str = 'From Django Server', magic: int = 234000, type_filling: str = 'ORDER_FILLING_IOC', position_size_usd: float = None, commission: float = None, capital: float = None, leverage: int = 500,
                      min_rr: float = 2.0
 ) -> Dict:
    try:
        order_type_str = order_type if isinstance(order_type, str) else order_type.name

        if order_type_str not in ('BUY', 'SELL'):
            error_msg = f"Invalid order type: {order_type_str}. Must be 'BUY' or 'SELL'"
            logger.error(error_msg)
            return None

        # ── R:R validation gate ──────────────────────────────────────
        if tp is not None and tp != 0 and sl != 0:
            tick = symbol_info_tick(symbol)
            if tick is not None and not tick.empty:
                entry_price = float(tick['ask'].iloc[0]) if order_type_str == 'BUY' else float(tick['bid'].iloc[0])
                risk = abs(entry_price - sl)
                reward = abs(tp - entry_price)
                if risk > 0:
                    rr = reward / risk
                    if rr < min_rr:
                        logger.warning(
                            f"R:R REJECTED {symbol} {order_type_str}: "
                            f"entry={entry_price} sl={sl} tp={tp} "
                            f"R:R={rr:.2f} < min_rr={min_rr} — trade not sent"
                        )
                        return None
                    logger.info(f"R:R OK {symbol} {order_type_str}: R:R={rr:.2f} (min={min_rr})")
                else:
                    logger.warning(f"R:R CHECK SKIPPED {symbol}: risk=0 (entry={entry_price} sl={sl})")
            else:
                logger.warning(f"R:R CHECK SKIPPED {symbol}: could not fetch tick data")
        elif tp is None:
            logger.warning(f"R:R CHECK SKIPPED {symbol} {order_type}: no TP provided — allowing trade")
        # ─────────────────────────────────────────────────────────────

        request = {
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type_str,
            "sl": float(sl),
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": str(comment),
            "type_filling": type_filling,
        }

        if tp is not None:
            request["tp"] = float(tp)

        logger.info(f"Sending market order: {request}")

        url = f"{BASE_URL}/order"
        response = get_session().post(url, json=request, timeout=10)
        response.raise_for_status()

        response_data = response.json()

        if 'error' in response_data:
            error_msg = response_data.get('error', 'Unknown error')
            logger.error(f"Order failed: {error_msg}")
            return None

        order = response_data.get('result')
        if order is None:
            logger.error("Order response missing 'result' field")
            return None

        # Verify order actually filled — deal>0 and price>0
        # MT5 can return retcode=10009 (DONE) with a valid order ticket
        # but deal=0/price=0 when the broker connection is flaky
        deal_ticket = order.get('deal', 0)
        fill_price = order.get('price', 0)
        if not deal_ticket or not fill_price:
            logger.error(
                "Order accepted but NOT FILLED: %s %s deal=%s price=%s order=%s — "
                "broker may be disconnected",
                symbol, order_type_str, deal_ticket, fill_price, order.get('order'),
            )
            return None

        return order
        
    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP error sending market order for {symbol}: {e.response.text}"
        logger.error(error_msg)

    except requests.exceptions.Timeout:
        error_msg = f"Timeout sending market order for {symbol}"
        logger.error(error_msg)
    
    except Exception as e:
        error_msg = f"Exception sending market order for {symbol}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
    
def modify_sl_tp(position, sl: float, tp: float = None) -> Dict:
    try:
        request = {
            "position": position.ticket,
            "symbol": position.symbol,
            "sl": float(sl),
        }

        if tp is not None:
            request['tp'] = float(tp)

        logger.info(f"Sending modify SL/TP request: {request}")

        url = f"{BASE_URL}/modify_sl_tp"
        response = get_session().post(url, json=request, timeout=10)

        # Check for market-closed before raising status errors
        if response.status_code == 400:
            try:
                err_data = response.json()
                err_msg = err_data.get('error', '')
                if 'market closed' in err_msg.lower() or 'market is closed' in err_msg.lower():
                    logger.debug(f"Modify SL/TP skipped (market closed): {position.symbol}")
                    return 'MARKET_CLOSED'
            except Exception:
                pass

        response.raise_for_status()

        response_data = response.json()

        if 'error' in response_data:
            error_msg = response_data.get('error', 'Unknown error')
            logger.error(f"Modify SL/TP failed: {error_msg}")
            return None

        result = response_data.get('result')
        if result:
            logger.info(f"Modify SL/TP successful: {result}")
            return result
        else:
            logger.error("No result returned from modify_sl_tp endpoint.")
            return None

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP error sending modify SL/TP for {position.ticket}: {e.response.text}"
        logger.error(error_msg)
       
    except requests.exceptions.Timeout:
        error_msg = f"Timeout sending modify SL/TP for {position.ticket}"
        logger.error(error_msg)
        return None
    
    except Exception as e:
        error_msg = f"Exception sending modify SL/TP for {position.ticket}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)


def close_partial(ticket, symbol, order_type, volume):
    """
    Close a partial volume of an open MT5 position.

    The MT5 Flask API's close_position endpoint supports partial closes
    by specifying a volume smaller than the full position size.

    Args:
        ticket: MT5 position ticket number.
        order_type: Position type as int (0=BUY, 1=SELL).
        symbol: Trading symbol (e.g. 'GBPUSD').
        volume: Lot volume to close (must be >= 0.01).
    """
    try:
        request = {
            "position": {
                "type": int(order_type),
                "ticket": int(ticket),
                "symbol": symbol,
                "volume": float(volume),
            }
        }

        logger.info(f"Sending partial close: ticket={ticket} symbol={symbol} volume={volume}")

        url = f"{BASE_URL}/close_position"
        response = get_session().post(url, json=request, timeout=10)
        response.raise_for_status()

        response_data = response.json()

        if 'error' in response_data:
            error_msg = response_data.get('error', 'Unknown error')
            logger.error(f"Partial close failed: {error_msg}")
            return None

        result = response_data.get('result')
        if result:
            logger.info(f"Partial close successful: {result}")
            return result
        else:
            logger.error("No result returned from close_position endpoint.")
            return None

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP error sending partial close for {ticket}: {e.response.text}"
        logger.error(error_msg)

    except requests.exceptions.Timeout:
        error_msg = f"Timeout sending partial close for {ticket}"
        logger.error(error_msg)
        return None

    except Exception as e:
        error_msg = f"Exception sending partial close for {ticket}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)


def close_full(ticket, symbol, order_type, volume):
    """
    Close the full volume of an open MT5 position.

    Convenience wrapper around close_position endpoint that closes
    the entire remaining position volume.

    Args:
        ticket: MT5 position ticket number.
        symbol: Trading symbol (e.g. 'GBPUSD').
        order_type: Position type as int (0=BUY, 1=SELL).
        volume: Full remaining lot volume of the position.
    """
    try:
        request = {
            "position": {
                "type": int(order_type),
                "ticket": int(ticket),
                "symbol": symbol,
                "volume": float(volume),
            }
        }

        logger.info(f"Sending full close: ticket={ticket} symbol={symbol} volume={volume}")

        url = f"{BASE_URL}/close_position"
        response = get_session().post(url, json=request, timeout=10)
        response.raise_for_status()

        response_data = response.json()

        if 'error' in response_data:
            error_msg = response_data.get('error', 'Unknown error')
            logger.error(f"Full close failed: {error_msg}")
            return None

        result = response_data.get('result')
        if result:
            logger.info(f"Full close successful: {result}")
            return result
        else:
            logger.error("No result returned from close_position endpoint.")
            return None

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP error sending full close for {ticket}: {e.response.text}"
        logger.error(error_msg)

    except requests.exceptions.Timeout:
        error_msg = f"Timeout sending full close for {ticket}"
        logger.error(error_msg)
        return None

    except Exception as e:
        error_msg = f"Exception sending full close for {ticket}: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)