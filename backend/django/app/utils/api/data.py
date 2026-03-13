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
        response = get_session().get(url, timeout=5)
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
        response = get_session().get(url, timeout=5)
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
        response = get_session().get(url, timeout=5)
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
        url = f"{BASE_URL}/fetch_data_range"
        params = {
            'symbol': symbol,
            'timeframe': timeframe.value,
            'start': from_date.isoformat(),
            'end': to_date.isoformat()
        }
        response = get_session().get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        df = pd.DataFrame(data)
        return df
    except Exception as e:
        error_msg = f"Exception fetching data for {symbol} on {timeframe}: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)


# --- Cached data fetching for entry pipeline ---
_cycle_cache = {}
_cycle_cache_time = 0

def fetch_data_pos_cached(symbol: str, timeframe: MT5Timeframe, bars: int, cache_ttl: float = 30.0) -> pd.DataFrame:
    """Fetch OHLCV data with per-cycle caching to avoid redundant HTTP calls.

    Cache key includes symbol + timeframe. Cache invalidates after cache_ttl seconds.
    Used by the entry pipeline where multiple components need the same data within one cycle.
    """
    import time
    global _cycle_cache, _cycle_cache_time

    now = time.monotonic()
    # Invalidate entire cache if TTL expired (new cycle)
    if now - _cycle_cache_time > cache_ttl:
        _cycle_cache = {}
        _cycle_cache_time = now

    cache_key = f"{symbol}:{timeframe.value}:{bars}"
    if cache_key in _cycle_cache:
        return _cycle_cache[cache_key]

    df = fetch_data_pos(symbol, timeframe, bars)
    if df is not None:
        _cycle_cache[cache_key] = df
    return df


def fetch_ticks(symbol: str, count: int = 1000, seconds_back: int = 10) -> pd.DataFrame:
    """Fetch recent ticks from MT5 Flask API (REST fallback for tick data).

    Used when Redis tick stream is unavailable or for one-off tick requests.
    """
    try:
        url = f"{BASE_URL}/fetch_ticks?symbol={symbol}&count={count}&seconds_back={seconds_back}"
        response = get_session().get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data)
    except Exception as e:
        logger.error(f"Exception fetching ticks for {symbol}: {e}")
        return pd.DataFrame()


def fetch_ticks_batch(symbols: list, count: int = 1000, seconds_back: int = 10, max_workers: int = 8) -> dict:
    """Fetch ticks for multiple symbols in parallel."""
    results = {}
    def _fetch_one(sym):
        return sym, fetch_ticks(sym, count, seconds_back)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            try:
                sym, df = future.result()
                results[sym] = df
            except Exception as e:
                sym = futures[future]
                logger.error(f"Batch tick fetch failed for {sym}: {e}")
                results[sym] = pd.DataFrame()
    return results
