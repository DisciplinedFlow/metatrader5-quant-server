import os
import traceback
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import logging

from app.utils.constants import MT5Timeframe
from app.utils.api.session import get_session, BASE_URL

load_dotenv()
logger = logging.getLogger(__name__)


def symbol_info_tick(symbol: str) -> pd.DataFrame:
    try:
        url = f"{BASE_URL}/symbol_info_tick/{symbol}"
        response = get_session().get(url, timeout=10)
        response.raise_for_status()

        data = response.json()
        df = pd.DataFrame([data])
        return df
    except Exception as e:
        error_msg = f"Exception fetching symbol info tick for {symbol}: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

def symbol_info(symbol) -> pd.DataFrame:
    try:
        url = f"{BASE_URL}/symbol_info/{symbol}"
        response = get_session().get(url, timeout=10)
        response.raise_for_status()

        data = response.json()
        df = pd.DataFrame([data])
        return df
    except Exception as e:
        error_msg = f"Exception fetching symbol info for {symbol}: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

def fetch_data_pos(symbol: str, timeframe: MT5Timeframe, bars: int) -> pd.DataFrame:
    try:
        url = f"{BASE_URL}/fetch_data_pos?symbol={symbol}&timeframe={timeframe.value}&bars={bars}"
        response = get_session().get(url, timeout=10)
        response.raise_for_status()

        data = response.json()
        df = pd.DataFrame(data)
        return df
    except Exception as e:
        error_msg = f"Exception fetching data for {symbol} on {timeframe}: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

def fetch_data_pos_batch(symbols: list, timeframe: MT5Timeframe, bars: int, max_workers: int = 8) -> dict:
    """
    Fetch OHLCV data for multiple symbols in parallel using ThreadPoolExecutor.

    Returns dict mapping symbol -> DataFrame (or None on failure).
    With 8 workers, 22 symbols that take ~250ms each finish in ~700ms
    instead of ~5.5s sequential.
    """
    results = {}

    def _fetch_one(sym):
        return sym, fetch_data_pos(sym, timeframe, bars)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            try:
                sym, df = future.result()
                results[sym] = df
            except Exception as e:
                sym = futures[future]
                logger.error(f"Batch fetch failed for {sym}: {e}")
                results[sym] = None

    return results

def fetch_data_range(symbol: str, timeframe: MT5Timeframe, from_date: datetime, to_date: datetime) -> pd.DataFrame:
    try:
        url = f"{BASE_URL}/copy_rates_range"
        params = {
            'symbol': symbol,
            'timeframe': timeframe.value,
            'from_date': from_date,
            'to_date': to_date
        }
        response = get_session().post(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        df = pd.DataFrame(data)
        return df
    except Exception as e:
        error_msg = f"Exception fetching data for {symbol} on {timeframe}: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)
