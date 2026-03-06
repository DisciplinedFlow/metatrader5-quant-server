from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
from flasgger import swag_from
import logging

symbol_bp = Blueprint('symbol', __name__)
logger = logging.getLogger(__name__)

@symbol_bp.route('/symbols_get', methods=['GET'])
@swag_from({
    'tags': ['Symbol'],
    'parameters': [
        {
            'name': 'visible',
            'in': 'query',
            'type': 'boolean',
            'required': False,
            'default': True,
            'description': 'If true, only return symbols visible in Market Watch.'
        }
    ],
    'responses': {
        200: {
            'description': 'List of symbol names.',
            'schema': {
                'type': 'array',
                'items': {'type': 'string'}
            }
        },
        500: {
            'description': 'Failed to retrieve symbols.'
        }
    }
})
def get_symbols():
    """
    Get All Symbols
    ---
    description: Retrieve symbol names from MT5, optionally filtered to Market Watch visible symbols.
    """
    visible = request.args.get('visible', 'true').lower() != 'false'
    symbols = mt5.symbols_get()
    if symbols is None:
        return jsonify({"error": "Failed to retrieve symbols"}), 500
    if visible:
        symbols = [s for s in symbols if s.visible]
    names = sorted(s.name for s in symbols)
    return jsonify(names)

@symbol_bp.route('/symbol_info_tick/<symbol>', methods=['GET'])
@swag_from({
    'tags': ['Symbol'],
    'parameters': [
        {
            'name': 'symbol',
            'in': 'path',
            'type': 'string',
            'required': True,
            'description': 'Symbol name to retrieve tick information.'
        }
    ],
    'responses': {
        200: {
            'description': 'Tick information retrieved successfully.',
            'schema': {
                'type': 'object',
                'properties': {
                    'bid': {'type': 'number'},
                    'ask': {'type': 'number'},
                    'last': {'type': 'number'},
                    'volume': {'type': 'integer'},
                    'time': {'type': 'integer'}
                }
            }
        },
        404: {
            'description': 'Failed to get symbol tick info.'
        }
    }
})
def get_symbol_info_tick_endpoint(symbol):
    """
    Get Symbol Tick Information
    ---
    description: Retrieve the latest tick information for a given symbol.
    """
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return jsonify({"error": "Failed to get symbol tick info"}), 404
    
    tick_dict = tick._asdict()
    return jsonify(tick_dict)

@symbol_bp.route('/symbol_info/<symbol>', methods=['GET'])
@swag_from({
    'tags': ['Symbol'],
    'parameters': [
        {
            'name': 'symbol',
            'in': 'path',
            'type': 'string',
            'required': True,
            'description': 'Symbol name to retrieve information.'
        }
    ],
    'responses': {
        200: {
            'description': 'Symbol information retrieved successfully.',
            'schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'path': {'type': 'string'},
                    'description': {'type': 'string'},
                    'volume_min': {'type': 'number'},
                    'volume_max': {'type': 'number'},
                    'volume_step': {'type': 'number'},
                    'price_digits': {'type': 'integer'},
                    'spread': {'type': 'number'},
                    'points': {'type': 'integer'},
                    'trade_mode': {'type': 'integer'},
                    # Add other relevant fields as needed
                }
            }
        },
        404: {
            'description': 'Failed to get symbol info.'
        }
    }
})
def get_symbol_info(symbol):
    """
    Get Symbol Information
    ---
    description: Retrieve detailed information for a given symbol.
    """
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return jsonify({"error": "Failed to get symbol info"}), 404
    
    symbol_info_dict = symbol_info._asdict()
    return jsonify(symbol_info_dict)