import traceback
import logging
import pandas as pd

from app.utils.constants import MT5Timeframe, METALS, OILS, CURRENCY_PAIRS, CRYPTOCURRENCIES
from app.utils.api.data import symbol_info

logger = logging.getLogger(__name__)

def get_price_at_pnl(desired_pnl: float, entry_price: float, order_size_usd: float, leverage: float, type: str, commission: float) -> tuple:
    """
    Calculate the price at which the desired PnL is achieved, with and without commission.

    :param desired_pnl: The desired profit or loss in USD.
    :param entry_price: The entry price of the trade.
    :param order_size_usd: The size of the position in USD.
    :param leverage: The leverage used for the trade.
    :param type: The type of position, either 'long' or 'short'.
    :param commission: The commission in USD.
    :return: A tuple containing two prices:
             - Price with commission
             - Price without commission
    :raises ValueError: If an unknown trade type is provided.
    """
    if type == 'BUY':
        price_including_commission = entry_price * (1 + (desired_pnl + commission) / order_size_usd)
        price_excluding_commission = entry_price * (1 + desired_pnl / order_size_usd)
    elif type == 'SELL':
        price_including_commission = entry_price * (1 - (desired_pnl + commission) / order_size_usd)
        price_excluding_commission = entry_price * (1 - desired_pnl / order_size_usd)
    else:
        raise ValueError(f"Unknown trade type: {type}")

    return price_including_commission, price_excluding_commission

def get_pnl_at_price(current_price: float, entry_price: float, order_size_usd: float, leverage: float, type: str, commission: float) -> tuple:
    if type == 'BUY':
        price_change = (current_price - entry_price) / entry_price
    elif type == 'SELL':
        price_change = (entry_price - current_price) / entry_price
    else:
        raise ValueError(f"Unknown trade type: {type}")
    
    # Calculate gross PNL
    pnl_including_commission = order_size_usd * price_change

    # Subtract commissions
    pnl_excluding_commission = pnl_including_commission - commission
    return pnl_including_commission, pnl_excluding_commission

def calculate_order_size_usd(capital: float, leverage: float) -> float:
    return capital * leverage

def calculate_price_with_spread(price: float, spread_multiplier: float, increase: bool) -> float:
    if increase:
        return price * (1 + spread_multiplier)
    else:
        return price * (1 - spread_multiplier)
    
def calculate_liquidation_price(entry_price: float, leverage: float, type: str) -> float:
    if type == 'BUY':
        liq_p = entry_price * (1 - (1 / leverage))
    elif type == 'SELL':
        liq_p = entry_price * (1 + (1 / leverage))
    else:
        raise ValueError(f"Unknown position type: {type}")
    
    return liq_p


def calculate_trade_volume(open_price: float, current_price: float, current_pnl: float, leverage: float) -> float:
    """
    Calculate the trade volume given the open price, current price, current PNL, and leverage.

    :param open_price: The opening price of the trade
    :param current_price: The current price of the asset
    :param current_pnl: The current profit/loss of the trade in USD
    :param leverage: The leverage used for the trade
    :return: The volume of the trade in USD
    """
    price_change = abs(current_price - open_price) / open_price
    trade_volume = abs(current_pnl / (price_change * leverage))
    return trade_volume

def calculate_order_capital(symbol, volume_lots, leverage, price_open):
    order_size_usd = convert_lots_to_usd(symbol, volume_lots, price_open)
    capital_used = order_size_usd / leverage
    return capital_used


def _extract_scalar(value, default=None):
    """Extract a scalar float from a pandas Series or return the value directly."""
    if isinstance(value, pd.Series):
        return float(value.iloc[0]) if not value.empty else default
    if value is None:
        return default
    return float(value)


def convert_lots_to_usd(symbol, lots, price_open):
    """
    Convert volume size from lots to USD amount.

    Uses trade_contract_size from MT5 — handles forex (100k), metals
    (XAUUSD=100, XAGUSD=5000), energy (NG-C=10000, oils=1000), etc.

    :param symbol: The trading symbol (e.g., 'EURUSD', 'XAGUSD', 'NG-C')
    :param lots: The volume size in lots
    :param price_open: The price at which to calculate notional value
    :return: The equivalent USD amount (notional)
    """
    # Get the contract size for the symbol
    symbol_info_data = symbol_info(symbol)
    if symbol_info_data is None:
        raise ValueError(f"Symbol {symbol} not found in MetaTrader 5")

    contract_size = _extract_scalar(symbol_info_data.get('trade_contract_size'), 100000)

    # For USD-base pairs (USDJPY, USDCHF, USDCAD), base currency is USD
    # so notional = lots * contract_size (already in USD).
    # For everything else (EURUSD, XAUUSD, XAGUSD, NG-C, oils...),
    # notional = lots * contract_size * price (converting base to USD).
    if symbol.startswith('USD') and symbol != 'USDX':
        usd_amount = lots * contract_size
    else:
        usd_amount = lots * contract_size * price_open

    return usd_amount


def get_symbol_contract_info(symbol: str) -> dict:
    """Fetch contract specification from MT5 for position sizing.

    Returns a dict with:
        trade_contract_size, volume_min, volume_max, volume_step,
        ask, bid, point, digits
    or None if the symbol could not be found.
    """
    try:
        symbol_info_data = symbol_info(symbol)
        if symbol_info_data is None:
            logger.error(f"get_symbol_contract_info: {symbol} not found in MT5")
            return None

        return {
            'trade_contract_size': _extract_scalar(symbol_info_data.get('trade_contract_size'), 100000),
            'volume_min': _extract_scalar(symbol_info_data.get('volume_min'), 0.01),
            'volume_max': _extract_scalar(symbol_info_data.get('volume_max'), 100.0),
            'volume_step': _extract_scalar(symbol_info_data.get('volume_step'), 0.01),
            'ask': _extract_scalar(symbol_info_data.get('ask'), 0.0),
            'bid': _extract_scalar(symbol_info_data.get('bid'), 0.0),
            'point': _extract_scalar(symbol_info_data.get('point'), 0.00001),
            'digits': _extract_scalar(symbol_info_data.get('digits'), 5),
        }
    except Exception as e:
        logger.error(f"get_symbol_contract_info failed for {symbol}: {e}\n{traceback.format_exc()}")
        return None


def convert_usd_to_lots(symbol: str, usd_amount: float, type: str) -> float:
    """
    Convert USD amount to lots for a given symbol.

    Uses trade_contract_size from MT5 symbol info so that commodity CFDs
    (XAUUSD=100 oz, XAGUSD=5000 oz, NG-C=10000, oils=1000) are sized
    correctly alongside forex (contract_size=100,000 base currency).

    Also enforces volume_min/volume_max/volume_step from the broker.

    :param symbol: The trading symbol (e.g., 'EURUSD', 'XAGUSD', 'NG-C')
    :param usd_amount: The desired notional exposure in USD
    :param type: The type of order ('BUY' or 'SELL')
    :return: The equivalent amount in lots (clamped to broker limits)
    """
    try:
        # Get the symbol information
        symbol_info_data = symbol_info(symbol)
        if symbol_info_data is None:
            raise ValueError(f"Symbol {symbol} not found in MetaTrader 5")

        # Ensure that 'ask' and 'bid' are scalar values
        ask_price = _extract_scalar(symbol_info_data.get('ask'), 0.0)
        bid_price = _extract_scalar(symbol_info_data.get('bid'), 0.0)

        price_dict = {
            'BUY': ask_price,
            'SELL': bid_price
        }

        # Get the contract size — this is the key field that varies by asset class:
        # Forex: 100,000 (1 lot = 100k base currency)
        # XAUUSD: 100 (1 lot = 100 oz)
        # XAGUSD: 5,000 (1 lot = 5,000 oz)
        # NG-C: 10,000 (1 lot = 10,000 MMBtu)
        # Oils: 1,000 (1 lot = 1,000 barrels)
        contract_size = _extract_scalar(symbol_info_data.get('trade_contract_size'), 100000)

        # Broker volume constraints
        volume_min = _extract_scalar(symbol_info_data.get('volume_min'), 0.01)
        volume_max = _extract_scalar(symbol_info_data.get('volume_max'), 100.0)
        lot_step = _extract_scalar(symbol_info_data.get('volume_step'), 0.01)

        # Calculate lots: notional_usd = lots * contract_size * price
        # => lots = notional_usd / (contract_size * price)
        #
        # For USD-base pairs (USDJPY, USDCHF, USDCAD), base currency IS USD,
        # so 1 lot = contract_size USD (no price conversion needed).
        price = price_dict[type]
        if symbol.startswith('USD') and symbol != 'USDX':
            lots = usd_amount / contract_size
        else:
            lots = usd_amount / (contract_size * price)

        # Round to the nearest lot step
        lots = round(lots / lot_step) * lot_step

        # Clamp to broker volume limits
        if lots < volume_min:
            logger.warning(
                f"convert_usd_to_lots: {symbol} computed {lots:.4f} lots < volume_min {volume_min}, "
                f"clamping up (usd={usd_amount:.2f}, contract_size={contract_size}, price={price:.4f})"
            )
            lots = volume_min
        if lots > volume_max:
            logger.warning(
                f"convert_usd_to_lots: {symbol} computed {lots:.4f} lots > volume_max {volume_max}, "
                f"clamping down"
            )
            lots = volume_max

        notional_usd = lots * contract_size * price if not (symbol.startswith('USD') and symbol != 'USDX') else lots * contract_size

        logger.info({
            'message': 'Lots converted from USD to lots',
            'symbol': symbol,
            'usd_amount': usd_amount,
            'type': type,
            'lots': float(lots),
            'contract_size': contract_size,
            'price': float(price),
            'notional_usd': float(notional_usd),
            'volume_min': volume_min,
            'volume_max': volume_max,
            'volume_step': lot_step,
        })

        return lots
    except Exception as e:
        error_msg = f"Exception in convert_usd_to_lots: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return 0.0  # Return a default value or handle accordingly

def calculate_commission(order_size_usd: float, pair: str) -> float:
    """
    Calculate the total commission for a trade based on the notional value.
    :param order_size_usd: The notional value of the position in USD.
    :return: The total commission for opening and closing the trade.
    """
    try:
        if pair in CRYPTOCURRENCIES:
            commission_rate = 0.0005 # 0.05%
        elif pair in OILS:
            commission_rate = 0.00025
        elif pair in METALS:
            commission_rate = 0.00025
        elif pair in CURRENCY_PAIRS:
            commission_rate = 0.00025
        else:
            # Throw exception
            raise ValueError(f"Could not calculate commission for unknown pair: {pair}")

        commission = order_size_usd * commission_rate # Total commission for both open and close
        return commission
    except Exception as e:
        error_msg = f"Exception in calculate_commission: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)
