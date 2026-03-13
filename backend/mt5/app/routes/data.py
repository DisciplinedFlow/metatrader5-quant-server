from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
import logging
from datetime import datetime
import pytz
import pandas as pd
from flasgger import swag_from
from lib import get_timeframe

data_bp = Blueprint('data', __name__)
logger = logging.getLogger(__name__)

@data_bp.route('/fetch_data_pos', methods=['GET'])
@swag_from({
    'tags': ['Data'],
    'parameters': [
        {
            'name': 'symbol',
            'in': 'query',
            'type': 'string',
            'required': True,
            'description': 'Symbol name to fetch data for.'
        },
        {
            'name': 'timeframe',
            'in': 'query',
            'type': 'string',
            'required': False,
            'default': 'M1',
            'description': 'Timeframe for the data (e.g., M1, M5, H1).'
        },
        {
            'name': 'bars',
            'in': 'query',
            'type': 'integer',
            'required': False,
            'default': 500,
            'description': 'Number of bars to fetch (alias: num_bars).'
        }
    ],
    'responses': {
        200: {
            'description': 'Data fetched successfully.',
            'schema': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'time': {'type': 'string', 'format': 'date-time'},
                        'open': {'type': 'number'},
                        'high': {'type': 'number'},
                        'low': {'type': 'number'},
                        'close': {'type': 'number'},
                        'tick_volume': {'type': 'integer'},
                        'spread': {'type': 'integer'},
                        'real_volume': {'type': 'integer'}
                    }
                }
            }
        },
        400: {
            'description': 'Invalid request parameters.'
        },
        404: {
            'description': 'Failed to get rates data.'
        },
        500: {
            'description': 'Internal server error.'
        }
    }
})
def fetch_data_pos_endpoint():
    """
    Fetch Data from Position
    ---
    description: Retrieve historical price data for a given symbol starting from a specific position.
    """
    try:
        symbol = request.args.get('symbol')
        timeframe = request.args.get('timeframe', 'M1')
        num_bars = int(request.args.get('bars', request.args.get('num_bars', 500)))
        
        if not symbol:
            return jsonify({"error": "Symbol parameter is required"}), 400

        mt5_timeframe = get_timeframe(timeframe)
        
        rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, num_bars)
        if rates is None:
            return jsonify({"error": "Failed to get rates data"}), 404
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        return jsonify(df.to_dict(orient='records'))
    
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error in fetch_data_pos: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@data_bp.route('/fetch_data_range', methods=['GET'])
@swag_from({
    'tags': ['Data'],
    'parameters': [
        {
            'name': 'symbol',
            'in': 'query',
            'type': 'string',
            'required': True,
            'description': 'Symbol name to fetch data for.'
        },
        {
            'name': 'timeframe',
            'in': 'query',
            'type': 'string',
            'required': False,
            'default': 'M1',
            'description': 'Timeframe for the data (e.g., M1, M5, H1).'
        },
        {
            'name': 'start',
            'in': 'query',
            'type': 'string',
            'required': True,
            'format': 'date-time',
            'description': 'Start datetime in ISO format.'
        },
        {
            'name': 'end',
            'in': 'query',
            'type': 'string',
            'required': True,
            'format': 'date-time',
            'description': 'End datetime in ISO format.'
        }
    ],
    'responses': {
        200: {
            'description': 'Data fetched successfully.',
            'schema': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'time': {'type': 'string', 'format': 'date-time'},
                        'open': {'type': 'number'},
                        'high': {'type': 'number'},
                        'low': {'type': 'number'},
                        'close': {'type': 'number'},
                        'tick_volume': {'type': 'integer'},
                        'spread': {'type': 'integer'},
                        'real_volume': {'type': 'integer'}
                    }
                }
            }
        },
        400: {
            'description': 'Invalid request parameters.'
        },
        404: {
            'description': 'Failed to get rates data.'
        },
        500: {
            'description': 'Internal server error.'
        }
    }
})
def fetch_data_range_endpoint():
    """
    Fetch Data within a Date Range
    ---
    description: Retrieve historical price data for a given symbol within a specified date range.
    """
    try:
        symbol = request.args.get('symbol')
        timeframe = request.args.get('timeframe', 'M1')
        start_str = request.args.get('start')
        end_str = request.args.get('end')
        
        if not all([symbol, start_str, end_str]):
            return jsonify({"error": "Symbol, start, and end parameters are required"}), 400

        mt5_timeframe = get_timeframe(timeframe)
        
        # Convert string dates to timezone-aware UTC datetimes
        utc = pytz.UTC
        start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        # Localize only if naive (no tzinfo); otherwise convert to UTC
        if start_date.tzinfo is None:
            start_date = utc.localize(start_date)
        else:
            start_date = start_date.astimezone(utc)
        if end_date.tzinfo is None:
            end_date = utc.localize(end_date)
        else:
            end_date = end_date.astimezone(utc)
        
        rates = mt5.copy_rates_range(symbol, mt5_timeframe, start_date, end_date)
        if rates is None:
            return jsonify({"error": "Failed to get rates data"}), 404
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        return jsonify(df.to_dict(orient='records'))
    
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error in fetch_data_range: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500


@data_bp.route('/fetch_ticks', methods=['GET'])
@swag_from({
    'tags': ['Data'],
    'parameters': [
        {
            'name': 'symbol',
            'in': 'query',
            'type': 'string',
            'required': True,
            'description': 'Symbol name to fetch ticks for.'
        },
        {
            'name': 'count',
            'in': 'query',
            'type': 'integer',
            'required': False,
            'default': 1000,
            'description': 'Maximum number of ticks to return.'
        },
        {
            'name': 'seconds_back',
            'in': 'query',
            'type': 'integer',
            'required': False,
            'default': 10,
            'description': 'How many seconds back to fetch ticks from.'
        }
    ],
    'responses': {
        200: {
            'description': 'Ticks fetched successfully.',
            'schema': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'time': {'type': 'string', 'format': 'date-time'},
                        'bid': {'type': 'number'},
                        'ask': {'type': 'number'},
                        'last': {'type': 'number'},
                        'volume': {'type': 'integer'},
                        'time_msc': {'type': 'integer'},
                        'flags': {'type': 'integer'},
                        'volume_real': {'type': 'number'}
                    }
                }
            }
        },
        400: {
            'description': 'Invalid request parameters.'
        },
        500: {
            'description': 'Internal server error.'
        }
    }
})
def fetch_ticks_endpoint():
    """
    Fetch Recent Ticks
    ---
    description: Fetch recent ticks for a symbol. REST fallback for tick data.
    """
    try:
        symbol = request.args.get('symbol')
        count = int(request.args.get('count', 1000))
        seconds_back = int(request.args.get('seconds_back', 10))

        if not symbol:
            return jsonify({"error": "Symbol parameter is required"}), 400

        from datetime import timedelta
        utc = pytz.UTC
        date_from = datetime.now(utc) - timedelta(seconds=seconds_back)

        ticks = mt5.copy_ticks_from(symbol, date_from, count, mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            return jsonify([])

        df = pd.DataFrame(ticks)
        # Convert time to ISO format, keep time_msc as-is
        df['time'] = pd.to_datetime(df['time'], unit='s')

        return jsonify(df.to_dict(orient='records'))
    except Exception as e:
        logger.error(f"Error in fetch_ticks: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500