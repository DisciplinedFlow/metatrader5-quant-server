import logging
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

logger = logging.getLogger(__name__)

FINNHUB_BASE_URL = 'https://finnhub.io/api/v1'
FINNHUB_API_KEY = os.environ.get('FINNHUB_API_KEY', '')

# Finnhub uses OANDA-style symbols for forex
MT5_TO_FINNHUB = {
    'EURUSD': 'OANDA:EUR_USD',
    'GBPUSD': 'OANDA:GBP_USD',
    'USDJPY': 'OANDA:USD_JPY',
    'AUDUSD': 'OANDA:AUD_USD',
    'NZDUSD': 'OANDA:NZD_USD',
    'USDCAD': 'OANDA:USD_CAD',
    'USDCHF': 'OANDA:USD_CHF',
    'EURGBP': 'OANDA:EUR_GBP',
    'XAUUSD': 'OANDA:XAU_USD',
    'XAGUSD': 'OANDA:XAG_USD',
}

# Finnhub resolution codes
TIMEFRAME_MAP = {
    '1':  '1',   # 1 minute
    '5':  '5',   # 5 minutes
    '15': '15',  # 15 minutes
    '30': '30',  # 30 minutes
    '60': '60',  # 1 hour
    'D':  'D',   # Daily
    'W':  'W',   # Weekly
    'M':  'M',   # Monthly
    # MT5-style mappings
    'M1':  '1',
    'M5':  '5',
    'M15': '15',
    'M30': '30',
    'H1':  '60',
    'H4':  '60',  # H4 not native; fetch H1 and resample
    'D1':  'D',
}


def _get(endpoint, params=None):
    """Make authenticated GET request to Finnhub API."""
    if not FINNHUB_API_KEY:
        logger.warning('Finnhub: no API key configured')
        return None
    url = f'{FINNHUB_BASE_URL}/{endpoint}'
    p = params or {}
    p['token'] = FINNHUB_API_KEY
    try:
        resp = requests.get(url, params=p, timeout=10)
        if resp.status_code == 429:
            logger.warning('Finnhub: rate limited')
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error(f'Finnhub request failed: {e}')
        return None


def fetch_forex_candles(symbol, resolution='15', days_back=60):
    """Fetch forex OHLCV candles from Finnhub.

    Args:
        symbol: MT5 symbol name (e.g. 'EURUSD')
        resolution: Timeframe ('1','5','15','30','60','D')
        days_back: Number of days of history to fetch

    Returns:
        DataFrame with columns [open, high, low, close, volume] indexed by datetime,
        or None on failure.
    """
    finnhub_sym = MT5_TO_FINNHUB.get(symbol)
    if not finnhub_sym:
        logger.warning(f'Finnhub: unknown symbol {symbol}')
        return None

    resolved = TIMEFRAME_MAP.get(resolution, resolution)
    now = int(time.time())
    start = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp())

    data = _get('forex/candle', {
        'symbol': finnhub_sym,
        'resolution': resolved,
        'from': start,
        'to': now,
    })

    if not data or data.get('s') == 'no_data':
        logger.warning(f'Finnhub: no candle data for {symbol} ({finnhub_sym})')
        return None

    try:
        df = pd.DataFrame({
            'open': data['o'],
            'high': data['h'],
            'low': data['l'],
            'close': data['c'],
            'volume': data['v'],
        }, index=pd.to_datetime(data['t'], unit='s', utc=True))
        df.index.name = 'datetime'

        # Resample H4 from H1 data
        if resolution in ('H4',):
            df = df.resample('4h').agg({
                'open': 'first', 'high': 'max',
                'low': 'min', 'close': 'last', 'volume': 'sum',
            }).dropna()

        logger.info(f'Finnhub: fetched {len(df)} bars for {symbol} ({resolved}, {days_back}d)')
        return df
    except (KeyError, TypeError) as e:
        logger.error(f'Finnhub: parse error for {symbol}: {e}')
        return None


def get_forex_quote(symbol):
    """Get real-time forex quote from Finnhub.

    Returns dict with keys: bid, ask, mid, timestamp or None.
    """
    finnhub_sym = MT5_TO_FINNHUB.get(symbol)
    if not finnhub_sym:
        return None

    data = _get('forex/rates', {'base': 'USD'})
    if not data:
        return None

    # Alternative: use quote endpoint
    quote = _get('quote', {'symbol': finnhub_sym})
    if quote and quote.get('c'):
        return {
            'price': quote['c'],
            'high': quote['h'],
            'low': quote['l'],
            'open': quote['o'],
            'prev_close': quote['pc'],
            'timestamp': quote.get('t'),
        }
    return None


def get_economic_calendar(days_ahead=7):
    """Fetch upcoming economic events from Finnhub.

    Returns list of events with impact, country, event name, estimate, actual.
    """
    now = datetime.now(timezone.utc)
    data = _get('calendar/economic', {
        'from': now.strftime('%Y-%m-%d'),
        'to': (now + timedelta(days=days_ahead)).strftime('%Y-%m-%d'),
    })
    if not data or 'economicCalendar' not in data:
        return []

    events = []
    for evt in data['economicCalendar']:
        events.append({
            'country': evt.get('country', ''),
            'event': evt.get('event', ''),
            'impact': evt.get('impact', ''),
            'time': evt.get('time', ''),
            'estimate': evt.get('estimate'),
            'actual': evt.get('actual'),
            'previous': evt.get('prev'),
            'unit': evt.get('unit', ''),
        })
    return events


def get_market_news(category='forex', min_id=0):
    """Fetch latest market news headlines from Finnhub.

    Args:
        category: 'general', 'forex', 'crypto', 'merger'
        min_id: Only return news with id > min_id (for pagination)

    Returns list of news articles.
    """
    data = _get('news', {'category': category, 'minId': min_id})
    if not data:
        return []

    return [{
        'id': article.get('id'),
        'headline': article.get('headline', ''),
        'summary': article.get('summary', ''),
        'source': article.get('source', ''),
        'url': article.get('url', ''),
        'datetime': article.get('datetime'),
        'related': article.get('related', ''),
    } for article in data[:20]]


def get_aggregate_indicators(symbol, resolution='60'):
    """Get aggregate technical indicator signals (buy/sell/neutral) from Finnhub.

    Returns dict with signal counts and overall recommendation.
    """
    finnhub_sym = MT5_TO_FINNHUB.get(symbol)
    if not finnhub_sym:
        return None

    data = _get('scan/technical-indicator', {
        'symbol': finnhub_sym,
        'resolution': TIMEFRAME_MAP.get(resolution, resolution),
    })
    if not data or 'technicalAnalysis' not in data:
        return None

    ta = data['technicalAnalysis']
    return {
        'signal': ta.get('signal', 'neutral'),
        'buy': ta.get('count', {}).get('buy', 0),
        'sell': ta.get('count', {}).get('sell', 0),
        'neutral': ta.get('count', {}).get('neutral', 0),
    }
