import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

MT5_TO_YAHOO = {
    'EURUSD': 'EURUSD=X',
    'EURGBP': 'EURGBP=X',
    'USDJPY': 'USDJPY=X',
    'USDCAD': 'USDCAD=X',
    'USDCHF': 'USDCHF=X',
    'AUDUSD': 'AUDUSD=X',
    'NZDUSD': 'NZDUSD=X',
    'XAUUSD': 'XAUUSD=X',
    'XAGUSD': 'XAGUSD=X',
    'XAUEUR': 'XAUEUR=X',
    'NG': 'NG=F',
    'BRN': 'BZ=F',
    'WTI': 'CL=F',
}


def fetch_yahoo_data(symbol, period='30d', interval='5m'):
    """
    Fetch historical OHLCV data from Yahoo Finance.
    Maps MT5 symbol names to Yahoo Finance tickers.
    Returns a DataFrame with lowercase columns (open, high, low, close, volume)
    or None on failure.
    """
    ticker = MT5_TO_YAHOO.get(symbol)
    if ticker is None:
        logger.warning(f"Yahoo Finance: unknown symbol '{symbol}', no mapping found")
        return None

    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)

        if df is None or df.empty:
            logger.warning(f"Yahoo Finance: no data returned for {symbol} ({ticker})")
            return None

        # yfinance may return MultiIndex columns when downloading single ticker
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.columns = [c.lower() for c in df.columns]

        # Ensure required columns exist
        required = ['open', 'high', 'low', 'close']
        if not all(c in df.columns for c in required):
            logger.warning(f"Yahoo Finance: missing columns for {symbol}, got {list(df.columns)}")
            return None

        logger.info(f"Yahoo Finance: fetched {len(df)} bars for {symbol} ({ticker}, {period}, {interval})")
        return df

    except Exception as e:
        logger.error(f"Yahoo Finance: error fetching {symbol} ({ticker}): {e}")
        return None
