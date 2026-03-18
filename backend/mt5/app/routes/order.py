from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
import logging
from flasgger import swag_from

order_bp = Blueprint('order', __name__)
logger = logging.getLogger(__name__)

@order_bp.route('/order', methods=['POST'])
@swag_from({
    'tags': ['Order'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'symbol': {'type': 'string'},
                    'volume': {'type': 'number'},
                    'type': {'type': 'string', 'enum': ['BUY', 'SELL']},
                    'deviation': {'type': 'integer', 'default': 20},
                    'magic': {'type': 'integer', 'default': 0},
                    'comment': {'type': 'string', 'default': ''},
                    'type_filling': {'type': 'string', 'enum': ['ORDER_FILLING_IOC', 'ORDER_FILLING_FOK', 'ORDER_FILLING_RETURN']},
                    'sl': {'type': 'number'},
                    'tp': {'type': 'number'}
                },
                'required': ['symbol', 'volume', 'type']
            }
        }
    ],
    'responses': {
        200: {
            'description': 'Order executed successfully.',
            'schema': {
                'type': 'object',
                'properties': {
                    'message': {'type': 'string'},
                    'result': {
                        'type': 'object',
                        'properties': {
                            'retcode': {'type': 'integer'},
                            'order': {'type': 'integer'},
                            'magic': {'type': 'integer'},
                            'price': {'type': 'number'},
                            'symbol': {'type': 'string'},
                            # Add other relevant fields as needed
                        }
                    }
                }
            }
        },
        400: {
            'description': 'Bad request or order failed.'
        },
        500: {
            'description': 'Internal server error.'
        }
    }
})
def send_market_order_endpoint():
    """
    Send Market Order
    ---
    description: Execute a market order for a specified symbol with optional parameters.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Order data is required"}), 400

        required_fields = ['symbol', 'volume', 'type']
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing required fields"}), 400

        # Convert string order type to MT5 constant
        order_type_str = data['type']
        if order_type_str == 'BUY':
            order_type_mt5 = mt5.ORDER_TYPE_BUY
        elif order_type_str == 'SELL':
            order_type_mt5 = mt5.ORDER_TYPE_SELL
        else:
            return jsonify({"error": f"Invalid order type: {order_type_str}"}), 400

        # Convert string type_filling to MT5 constant
        filling_map = {
            'ORDER_FILLING_IOC': mt5.ORDER_FILLING_IOC,
            'ORDER_FILLING_FOK': mt5.ORDER_FILLING_FOK,
            'ORDER_FILLING_RETURN': mt5.ORDER_FILLING_RETURN,
        }
        type_filling = filling_map.get(data.get('type_filling', 'ORDER_FILLING_IOC'), mt5.ORDER_FILLING_IOC)

        # Prepare the order request
        request_data = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": data['symbol'],
            "volume": float(data['volume']),
            "type": order_type_mt5,
            "deviation": data.get('deviation', 20),
            "magic": data.get('magic', 0),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": type_filling,
        }

        # Get current price
        tick = mt5.symbol_info_tick(data['symbol'])
        if tick is None:
            return jsonify({"error": "Failed to get symbol price"}), 400

        # Set price based on order type
        if order_type_mt5 == mt5.ORDER_TYPE_BUY:
            request_data["price"] = tick.ask
        elif order_type_mt5 == mt5.ORDER_TYPE_SELL:
            request_data["price"] = tick.bid

        # Add optional SL/TP if provided
        if 'sl' in data:
            request_data["sl"] = data['sl']
        if 'tp' in data:
            request_data["tp"] = data['tp']

        # Send order
        result = mt5.order_send(request_data)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            error_code, error_str = mt5.last_error()
            
            return jsonify({
                "error": f"Order failed: {result.comment}",
                "mt5_error": error_str,
                "result": result._asdict()
            }), 400

        return jsonify({
            "message": "Order executed successfully",
            "result": result._asdict()
        })
    
    except Exception as e:
        logger.error(f"Error in send_market_order: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@order_bp.route('/order_check', methods=['POST'])
@swag_from({
    'tags': ['Order'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'symbol': {'type': 'string'},
                    'volume': {'type': 'number'},
                    'type': {'type': 'string', 'enum': ['BUY', 'SELL']},
                    'deviation': {'type': 'integer', 'default': 20},
                    'magic': {'type': 'integer', 'default': 0},
                    'comment': {'type': 'string', 'default': ''},
                    'type_filling': {'type': 'string', 'enum': ['ORDER_FILLING_IOC', 'ORDER_FILLING_FOK', 'ORDER_FILLING_RETURN']},
                    'sl': {'type': 'number'},
                    'tp': {'type': 'number'}
                },
                'required': ['symbol', 'volume', 'type']
            }
        }
    ],
    'responses': {
        200: {
            'description': 'Order check result.',
            'schema': {
                'type': 'object',
                'properties': {
                    'retcode': {'type': 'integer'},
                    'balance': {'type': 'number'},
                    'equity': {'type': 'number'},
                    'profit': {'type': 'number'},
                    'margin': {'type': 'number'},
                    'margin_free': {'type': 'number'},
                    'margin_level': {'type': 'number'},
                    'comment': {'type': 'string'},
                    'request': {'type': 'object'}
                }
            }
        },
        400: {
            'description': 'Bad request or order check failed.'
        },
        500: {
            'description': 'Internal server error.'
        }
    }
})
def order_check_endpoint():
    """
    Check Order Before Sending
    ---
    description: Validate an order without executing it. Returns margin, equity impact, and any error codes.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Order data is required"}), 400

        required_fields = ['symbol', 'volume', 'type']
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing required fields"}), 400

        # Convert string order type to MT5 constant
        order_type_str = data['type']
        if order_type_str == 'BUY':
            order_type_mt5 = mt5.ORDER_TYPE_BUY
        elif order_type_str == 'SELL':
            order_type_mt5 = mt5.ORDER_TYPE_SELL
        else:
            return jsonify({"error": f"Invalid order type: {order_type_str}"}), 400

        # Convert string type_filling to MT5 constant
        filling_map = {
            'ORDER_FILLING_IOC': mt5.ORDER_FILLING_IOC,
            'ORDER_FILLING_FOK': mt5.ORDER_FILLING_FOK,
            'ORDER_FILLING_RETURN': mt5.ORDER_FILLING_RETURN,
        }
        type_filling = filling_map.get(data.get('type_filling', 'ORDER_FILLING_IOC'), mt5.ORDER_FILLING_IOC)

        # Get current price
        tick = mt5.symbol_info_tick(data['symbol'])
        if tick is None:
            return jsonify({"error": "Failed to get symbol price"}), 400

        # Set price based on order type
        if order_type_mt5 == mt5.ORDER_TYPE_BUY:
            price = tick.ask
        else:
            price = tick.bid

        # Prepare the order request
        request_data = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": data['symbol'],
            "volume": float(data['volume']),
            "type": order_type_mt5,
            "price": price,
            "deviation": data.get('deviation', 20),
            "magic": data.get('magic', 0),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": type_filling,
        }

        if 'sl' in data:
            request_data["sl"] = data['sl']
        if 'tp' in data:
            request_data["tp"] = data['tp']

        # Check the order (does NOT execute)
        result = mt5.order_check(request_data)
        if result is None:
            error_code, error_str = mt5.last_error()
            return jsonify({
                "error": f"Order check failed: {error_str}",
                "mt5_error_code": error_code
            }), 400

        result_dict = result._asdict()
        # Convert the nested request named tuple to dict as well
        if hasattr(result.request, '_asdict'):
            result_dict['request'] = result.request._asdict()

        return jsonify(result_dict)

    except Exception as e:
        logger.error(f"Error in order_check: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@order_bp.route('/order_calc_margin', methods=['GET'])
@swag_from({
    'tags': ['Order'],
    'parameters': [
        {
            'name': 'action',
            'in': 'query',
            'type': 'string',
            'required': True,
            'enum': ['BUY', 'SELL'],
            'description': 'Order action type (BUY or SELL).'
        },
        {
            'name': 'symbol',
            'in': 'query',
            'type': 'string',
            'required': True,
            'description': 'Symbol name.'
        },
        {
            'name': 'volume',
            'in': 'query',
            'type': 'number',
            'required': True,
            'description': 'Trade volume in lots.'
        },
        {
            'name': 'price',
            'in': 'query',
            'type': 'number',
            'required': False,
            'description': 'Price to calculate margin at. If omitted, uses current ask/bid.'
        }
    ],
    'responses': {
        200: {
            'description': 'Margin calculated successfully.',
            'schema': {
                'type': 'object',
                'properties': {
                    'margin': {'type': 'number', 'description': 'Required margin in account currency.'}
                }
            }
        },
        400: {
            'description': 'Bad request or calculation failed.'
        },
        500: {
            'description': 'Internal server error.'
        }
    }
})
def order_calc_margin_endpoint():
    """
    Calculate Required Margin
    ---
    description: Calculate the margin required to open a position for a given symbol, volume, and price.
    """
    try:
        action_str = request.args.get('action')
        symbol = request.args.get('symbol')
        volume = request.args.get('volume')

        if not all([action_str, symbol, volume]):
            return jsonify({"error": "action, symbol, and volume parameters are required"}), 400

        volume = float(volume)

        if action_str == 'BUY':
            action = mt5.ORDER_TYPE_BUY
        elif action_str == 'SELL':
            action = mt5.ORDER_TYPE_SELL
        else:
            return jsonify({"error": f"Invalid action: {action_str}. Must be BUY or SELL"}), 400

        # Use provided price or get current price
        price_str = request.args.get('price')
        if price_str:
            price = float(price_str)
        else:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return jsonify({"error": f"Failed to get price for {symbol}"}), 400
            price = tick.ask if action == mt5.ORDER_TYPE_BUY else tick.bid

        margin = mt5.order_calc_margin(action, symbol, volume, price)
        if margin is None:
            error_code, error_str = mt5.last_error()
            return jsonify({
                "error": f"Margin calculation failed: {error_str}",
                "mt5_error_code": error_code
            }), 400

        return jsonify({"margin": margin})

    except ValueError:
        return jsonify({"error": "Invalid numeric parameter format"}), 400
    except Exception as e:
        logger.error(f"Error in order_calc_margin: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@order_bp.route('/order_calc_profit', methods=['GET'])
@swag_from({
    'tags': ['Order'],
    'parameters': [
        {
            'name': 'action',
            'in': 'query',
            'type': 'string',
            'required': True,
            'enum': ['BUY', 'SELL'],
            'description': 'Order action type (BUY or SELL).'
        },
        {
            'name': 'symbol',
            'in': 'query',
            'type': 'string',
            'required': True,
            'description': 'Symbol name.'
        },
        {
            'name': 'volume',
            'in': 'query',
            'type': 'number',
            'required': True,
            'description': 'Trade volume in lots.'
        },
        {
            'name': 'price_open',
            'in': 'query',
            'type': 'number',
            'required': True,
            'description': 'Position open price.'
        },
        {
            'name': 'price_close',
            'in': 'query',
            'type': 'number',
            'required': True,
            'description': 'Position close price.'
        }
    ],
    'responses': {
        200: {
            'description': 'Profit calculated successfully.',
            'schema': {
                'type': 'object',
                'properties': {
                    'profit': {'type': 'number', 'description': 'Profit/loss in account currency.'}
                }
            }
        },
        400: {
            'description': 'Bad request or calculation failed.'
        },
        500: {
            'description': 'Internal server error.'
        }
    }
})
def order_calc_profit_endpoint():
    """
    Calculate Potential Profit/Loss
    ---
    description: Calculate the profit or loss for a hypothetical position given open and close prices.
    """
    try:
        action_str = request.args.get('action')
        symbol = request.args.get('symbol')
        volume = request.args.get('volume')
        price_open = request.args.get('price_open')
        price_close = request.args.get('price_close')

        if not all([action_str, symbol, volume, price_open, price_close]):
            return jsonify({"error": "action, symbol, volume, price_open, and price_close parameters are required"}), 400

        volume = float(volume)
        price_open = float(price_open)
        price_close = float(price_close)

        if action_str == 'BUY':
            action = mt5.ORDER_TYPE_BUY
        elif action_str == 'SELL':
            action = mt5.ORDER_TYPE_SELL
        else:
            return jsonify({"error": f"Invalid action: {action_str}. Must be BUY or SELL"}), 400

        profit = mt5.order_calc_profit(action, symbol, volume, price_open, price_close)
        if profit is None:
            error_code, error_str = mt5.last_error()
            return jsonify({
                "error": f"Profit calculation failed: {error_str}",
                "mt5_error_code": error_code
            }), 400

        return jsonify({"profit": profit})

    except ValueError:
        return jsonify({"error": "Invalid numeric parameter format"}), 400
    except Exception as e:
        logger.error(f"Error in order_calc_profit: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500