"""
Multi-source OHLCV data fetcher for backtesting.

Sources (in priority order):
1. MT5 broker (most accurate - actual broker prices with spreads)
2. Yahoo Finance (via yfinance, already installed)
3. Finnhub (already have API key)

Usage:
    from app.quant.data_fetcher import fetch_ohlcv
    df = fetch_ohlcv('EURUSD', 'M15', days=180)

    # Force a specific source
    df = fetch_ohlcv('XAUUSD', 'H1', days=60, source='yahoo')

    # Cross-validate across all sources
    dfs = fetch_ohlcv('EURUSD', 'H1', days=30, source='all')
    report = validate_data(dfs)

    # Batch fetch multiple symbols
    results = fetch_ohlcv_batch(['EURUSD', 'GBPUSD', 'XAUUSD'], 'M15', days=60)
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from django.core.cache import cache

from app.utils.api.data import fetch_data_range
from app.utils.api.finnhub import fetch_forex_candles
from app.utils.api.yahoo import MT5_TO_YAHOO, fetch_yahoo_data
from app.utils.constants import MT5Timeframe

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timeframe mappings
# ---------------------------------------------------------------------------

TIMEFRAME_TO_MT5 = {
    'M1': MT5Timeframe.M1,
    'M5': MT5Timeframe.M5,
    'M15': MT5Timeframe.M15,
    'M30': MT5Timeframe.M30,
    'H1': MT5Timeframe.H1,
    'H4': MT5Timeframe.H4,
    'D1': MT5Timeframe.D1,
    'W1': MT5Timeframe.W1,
    'MN1': MT5Timeframe.MN1,
}

# Yahoo Finance interval strings + period limits
TIMEFRAME_TO_YAHOO = {
    'M1':  {'interval': '1m',  'max_days': 7},
    'M5':  {'interval': '5m',  'max_days': 60},
    'M15': {'interval': '15m', 'max_days': 60},
    'M30': {'interval': '30m', 'max_days': 60},
    'H1':  {'interval': '1h',  'max_days': 730},
    'H4':  {'interval': '1h',  'max_days': 730, 'resample': '4h'},
    'D1':  {'interval': '1d',  'max_days': 10000},
}

# Finnhub resolution strings (H4 handled via H1 + resample in fetch_forex_candles)
TIMEFRAME_TO_FINNHUB = {
    'M1':  '1',
    'M5':  '5',
    'M15': '15',
    'M30': '30',
    'H1':  '60',
    'H4':  'H4',   # fetch_forex_candles handles H4 resample internally
    'D1':  'D',
}

CACHE_TTL = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize_df(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Normalize a DataFrame to standard format: lowercase columns, UTC
    DatetimeIndex, and exactly the columns [open, high, low, close, volume]."""
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    # Lowercase all column names
    df.columns = [c.lower() for c in df.columns]

    # If there is a 'time' column (MT5 style), convert it to the index
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], utc=True)
        df = df.set_index('time')
    elif 'datetime' in df.columns:
        df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
        df = df.set_index('datetime')

    # Ensure the index is a DatetimeIndex in UTC
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index, utc=True)
        except Exception:
            pass

    if df.index.tz is None:
        try:
            df.index = df.index.tz_localize('UTC')
        except Exception:
            pass

    df.index.name = 'datetime'

    # Ensure volume column exists
    if 'volume' not in df.columns:
        if 'tick_volume' in df.columns:
            df['volume'] = df['tick_volume']
        elif 'real_volume' in df.columns:
            df['volume'] = df['real_volume']
        else:
            df['volume'] = 0

    # Keep only standard columns
    keep = ['open', 'high', 'low', 'close', 'volume']
    missing = [c for c in keep if c not in df.columns]
    if missing:
        logger.warning(f"Normalization: missing columns {missing} from {source}")
        return pd.DataFrame()

    df = df[keep].copy()

    # Drop rows with NaN OHLC
    df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)

    # Sort by time ascending
    df.sort_index(inplace=True)

    return df


# ---------------------------------------------------------------------------
# Individual source fetchers
# ---------------------------------------------------------------------------

def _fetch_mt5(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    """Fetch OHLCV data from the MT5 broker via the Flask REST API."""
    mt5_tf = TIMEFRAME_TO_MT5.get(timeframe)
    if mt5_tf is None:
        logger.warning(f"MT5: unsupported timeframe '{timeframe}'")
        return pd.DataFrame()

    to_date = datetime.now(timezone.utc)
    from_date = to_date - timedelta(days=days)

    try:
        df = fetch_data_range(symbol, mt5_tf, from_date, to_date)
    except Exception as e:
        logger.warning(f"MT5: fetch failed for {symbol} {timeframe}: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        logger.info(f"MT5: no data for {symbol} {timeframe} ({days}d)")
        return pd.DataFrame()

    return _normalize_df(df, 'mt5')


def _fetch_yahoo(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    """Fetch OHLCV data from Yahoo Finance via yfinance."""
    cfg = TIMEFRAME_TO_YAHOO.get(timeframe)
    if cfg is None:
        logger.warning(f"Yahoo: unsupported timeframe '{timeframe}'")
        return pd.DataFrame()

    # Respect Yahoo's per-interval day limits
    effective_days = min(days, cfg['max_days'])
    if effective_days < days:
        logger.info(
            f"Yahoo: clamping {symbol} {timeframe} request from {days}d to "
            f"{effective_days}d (Yahoo limit)"
        )

    # Check that the symbol has a Yahoo mapping
    if symbol not in MT5_TO_YAHOO:
        logger.warning(f"Yahoo: no mapping for symbol '{symbol}'")
        return pd.DataFrame()

    period = f'{effective_days}d'
    interval = cfg['interval']

    try:
        df = fetch_yahoo_data(symbol, period=period, interval=interval)
    except Exception as e:
        logger.warning(f"Yahoo: fetch failed for {symbol} {timeframe}: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        logger.info(f"Yahoo: no data for {symbol} {timeframe} ({effective_days}d)")
        return pd.DataFrame()

    df = _normalize_df(df, 'yahoo')

    # Resample H4 from 1h data
    resample_rule = cfg.get('resample')
    if resample_rule and not df.empty:
        df = df.resample(resample_rule).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
        }).dropna()

    return df


def _fetch_finnhub(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    """Fetch OHLCV data from Finnhub."""
    resolution = TIMEFRAME_TO_FINNHUB.get(timeframe)
    if resolution is None:
        logger.warning(f"Finnhub: unsupported timeframe '{timeframe}'")
        return pd.DataFrame()

    try:
        df = fetch_forex_candles(symbol, resolution=resolution, days_back=days)
    except Exception as e:
        logger.warning(f"Finnhub: fetch failed for {symbol} {timeframe}: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        logger.info(f"Finnhub: no data for {symbol} {timeframe} ({days}d)")
        return pd.DataFrame()

    # fetch_forex_candles already returns normalized columns; ensure standard format
    return _normalize_df(df, 'finnhub')


# Source registry (priority order)
_SOURCES = {
    'mt5':     _fetch_mt5,
    'yahoo':   _fetch_yahoo,
    'finnhub': _fetch_finnhub,
}

_SOURCE_PRIORITY = ['mt5', 'yahoo', 'finnhub']


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    days: int = 60,
    source: str = 'auto',
    use_cache: bool = True,
) -> "pd.DataFrame | dict[str, pd.DataFrame]":
    """
    Fetch OHLCV data from one or more sources.

    Args:
        symbol: MT5-style symbol name (e.g. 'EURUSD', 'XAUUSD', 'BTC')
        timeframe: Candle period ('M1','M5','M15','M30','H1','H4','D1')
        days: Number of calendar days of history to fetch
        source: 'auto' (fallback chain), 'mt5', 'yahoo', 'finnhub', or 'all'
        use_cache: Whether to check/store in Django cache (default True)

    Returns:
        DataFrame with columns [open, high, low, close, volume] and a UTC
        DatetimeIndex.  If source='all', returns dict mapping source name to
        DataFrame.
    """
    timeframe = timeframe.upper()

    # --- source='all': fetch from every source ---
    if source == 'all':
        results = {}
        for src_name in _SOURCE_PRIORITY:
            cache_key = f'backtest_data:{src_name}:{symbol}:{timeframe}:{days}'
            if use_cache:
                cached = cache.get(cache_key)
                if cached is not None:
                    results[src_name] = cached
                    logger.info(
                        f"Fetched {len(cached)} bars for {symbol} {timeframe} "
                        f"from {src_name} (cached)"
                    )
                    continue
            try:
                df = _SOURCES[src_name](symbol, timeframe, days)
                if df is not None and not df.empty:
                    if use_cache:
                        cache.set(cache_key, df, CACHE_TTL)
                    results[src_name] = df
                    logger.info(
                        f"Fetched {len(df)} bars for {symbol} {timeframe} "
                        f"from {src_name}"
                    )
            except Exception as e:
                logger.warning(f"Source {src_name} failed for {symbol}: {e}")
        return results

    # --- Single source or auto-fallback ---
    if source == 'auto':
        sources_to_try = _SOURCE_PRIORITY
    else:
        source = source.lower()
        if source not in _SOURCES:
            raise ValueError(
                f"Unknown source '{source}'. "
                f"Choose from: {list(_SOURCES.keys())}, 'auto', or 'all'."
            )
        sources_to_try = [source]

    for src_name in sources_to_try:
        cache_key = f'backtest_data:{src_name}:{symbol}:{timeframe}:{days}'

        # Check cache first
        if use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.info(
                    f"Fetched {len(cached)} bars for {symbol} {timeframe} "
                    f"from {src_name} (cached)"
                )
                return cached

        # Fetch from source
        try:
            df = _SOURCES[src_name](symbol, timeframe, days)
        except Exception as e:
            logger.warning(f"Source {src_name} failed for {symbol}: {e}")
            continue

        if df is not None and not df.empty:
            if use_cache:
                cache.set(cache_key, df, CACHE_TTL)
            logger.info(
                f"Fetched {len(df)} bars for {symbol} {timeframe} from {src_name}"
            )
            return df

        logger.info(
            f"Source {src_name} returned no data for {symbol} {timeframe}, "
            f"trying next source..."
        )

    logger.warning(
        f"All sources exhausted for {symbol} {timeframe} ({days}d). "
        f"Returning empty DataFrame."
    )
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Cross-validation
# ---------------------------------------------------------------------------

def validate_data(
    dfs_dict: dict,
    threshold_pct: float = 0.1,
) -> dict:
    """
    Compare close prices across multiple sources and flag discrepancies.

    Args:
        dfs_dict: Dict mapping source name to DataFrame (from fetch_ohlcv
                  with source='all')
        threshold_pct: Percentage difference to flag (default 0.1%)

    Returns:
        Dict with:
            'sources': list of source names compared
            'overlapping_bars': number of bars with data in all sources
            'discrepancies': list of dicts with timestamp, source pair, and
                             percentage difference
            'max_discrepancy_pct': worst-case difference across all bars
            'mean_discrepancy_pct': average difference
            'is_valid': True if max discrepancy is within threshold
    """
    sources = list(dfs_dict.keys())
    if len(sources) < 2:
        return {
            'sources': sources,
            'overlapping_bars': 0,
            'discrepancies': [],
            'max_discrepancy_pct': 0.0,
            'mean_discrepancy_pct': 0.0,
            'is_valid': True,
        }

    # Align all sources to a common DatetimeIndex (inner join)
    close_frames = {}
    for src, df in dfs_dict.items():
        if df is not None and not df.empty:
            close_frames[src] = df['close'].rename(src)

    if len(close_frames) < 2:
        return {
            'sources': list(close_frames.keys()),
            'overlapping_bars': 0,
            'discrepancies': [],
            'max_discrepancy_pct': 0.0,
            'mean_discrepancy_pct': 0.0,
            'is_valid': True,
        }

    aligned = pd.concat(close_frames.values(), axis=1, join='inner').dropna()
    source_names = list(close_frames.keys())

    discrepancies = []
    all_diffs = []

    for i in range(len(source_names)):
        for j in range(i + 1, len(source_names)):
            s1, s2 = source_names[i], source_names[j]
            pct_diff = ((aligned[s1] - aligned[s2]).abs() / aligned[s1] * 100)
            all_diffs.append(pct_diff)

            # Flag individual bars above threshold
            flagged = pct_diff[pct_diff > threshold_pct]
            for ts, diff_val in flagged.items():
                discrepancies.append({
                    'timestamp': str(ts),
                    'sources': f'{s1} vs {s2}',
                    'pct_diff': round(float(diff_val), 4),
                    f'{s1}_close': round(float(aligned.loc[ts, s1]), 5),
                    f'{s2}_close': round(float(aligned.loc[ts, s2]), 5),
                })

    combined_diffs = pd.concat(all_diffs) if all_diffs else pd.Series(dtype=float)
    max_disc = float(combined_diffs.max()) if len(combined_diffs) > 0 else 0.0
    mean_disc = float(combined_diffs.mean()) if len(combined_diffs) > 0 else 0.0

    # Sort discrepancies by magnitude (worst first), limit to top 50
    discrepancies.sort(key=lambda d: d['pct_diff'], reverse=True)
    discrepancies = discrepancies[:50]

    return {
        'sources': source_names,
        'overlapping_bars': len(aligned),
        'discrepancies': discrepancies,
        'max_discrepancy_pct': round(max_disc, 4),
        'mean_discrepancy_pct': round(mean_disc, 4),
        'is_valid': max_disc <= threshold_pct,
    }


# ---------------------------------------------------------------------------
# Batch fetch
# ---------------------------------------------------------------------------

def fetch_ohlcv_batch(
    symbols: list,
    timeframe: str,
    days: int = 60,
    source: str = 'auto',
    max_workers: int = 6,
    use_cache: bool = True,
) -> dict:
    """
    Fetch OHLCV data for multiple symbols in parallel.

    Args:
        symbols: List of MT5-style symbol names
        timeframe: Candle period string
        days: Calendar days of history
        source: Data source selection (same options as fetch_ohlcv)
        max_workers: Thread pool size for parallel fetching
        use_cache: Whether to use Django cache

    Returns:
        Dict mapping symbol -> DataFrame (or empty DataFrame on failure)
    """
    results = {}

    def _fetch_one(sym):
        try:
            return sym, fetch_ohlcv(
                sym, timeframe, days=days, source=source, use_cache=use_cache
            )
        except Exception as e:
            logger.error(f"Batch fetch failed for {sym}: {e}")
            return sym, pd.DataFrame()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            try:
                sym, df = future.result()
                results[sym] = df
            except Exception as e:
                sym = futures[future]
                logger.error(f"Batch fetch error for {sym}: {e}")
                results[sym] = pd.DataFrame()

    fetched_count = sum(1 for df in results.values() if not df.empty)
    logger.info(
        f"Batch fetch complete: {fetched_count}/{len(symbols)} symbols, "
        f"{timeframe} {days}d from {source}"
    )

    return results
