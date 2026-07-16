#!/usr/bin/env python3
"""
Backtest Data Downloader
========================
Pulls historical forex/metals/energy data from multiple free sources:
  1. MT5 Flask API (via Docker container at localhost:5001)
  2. yfinance (Yahoo Finance) — requires yfinance >= 1.0

Output: research/backtest_data/{mt5,yfinance}/*.csv + summary.txt

Usage:
    python research/download_backtest_data.py

Requires:
    pip install requests 'yfinance>=1.0' pandas
"""

import os
import sys
import time
import json
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent / "backtest_data"
MT5_DIR = BASE_DIR / "mt5"
YF_DIR = BASE_DIR / "yfinance"

# MT5 API — accessible from host at localhost:5001
MT5_BASE_URL = os.environ.get("MT5_API_URL", "http://localhost:5001")

# Symbols to fetch from MT5
MT5_SYMBOLS = [
    "XAGUSD",
    "XAUUSD",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USOUSD",   # WTI Oil on Vantage
]

# MT5 timeframes — use string names (Flask API accepts them)
MT5_TIMEFRAMES = ["M15", "H1", "D1"]

# Bars to request per timeframe
MT5_BARS = {
    "M15": 5000,
    "H1": 5000,
    "D1": 5000,
}

# yfinance symbol mappings
YF_SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",     # Yahoo uses inverse for JPY
    "AUDUSD": "AUDUSD=X",
    "XAUUSD": "GC=F",      # Gold futures
    "XAGUSD": "SI=F",      # Silver futures
    "USOUSD": "CL=F",      # WTI Oil futures
}

# Request timeout for MT5 API (seconds)
MT5_TIMEOUT = 120

# Summary tracking
summary_lines = []


def log(msg):
    """Print and record to summary."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    summary_lines.append(msg)


def ensure_dirs():
    """Create output directories."""
    MT5_DIR.mkdir(parents=True, exist_ok=True)
    YF_DIR.mkdir(parents=True, exist_ok=True)


def parse_mt5_time(series):
    """Parse MT5 time strings which come as RFC 2822 format from Flask jsonify.

    Example: 'Tue, 17 Mar 2026 03:00:00 GMT'
    Uses format='mixed' to handle edge cases across month boundaries.
    """
    return pd.to_datetime(series, format="mixed", utc=True).dt.tz_localize(None)


# ---------------------------------------------------------------------------
# MT5 Data Download
# ---------------------------------------------------------------------------

def download_mt5_data():
    """Download data from MT5 Flask API using /fetch_data_pos."""
    log("=" * 60)
    log("MT5 DATA DOWNLOAD (fetch_data_pos)")
    log("=" * 60)

    # Check if MT5 API is reachable
    try:
        r = requests.get(f"{MT5_BASE_URL}/health", timeout=5)
        log(f"MT5 API health check: {r.status_code}")
    except Exception as e:
        log(f"WARNING: MT5 API not reachable at {MT5_BASE_URL}: {e}")
        log("SKIPPING MT5 download -- ensure MT5 container is running and port 5001 is exposed")
        return

    for symbol in MT5_SYMBOLS:
        for tf_name in MT5_TIMEFRAMES:
            bars = MT5_BARS[tf_name]
            filename = f"{symbol}_{tf_name}.csv"
            filepath = MT5_DIR / filename

            log(f"\nFetching MT5: {symbol} {tf_name} ({bars} bars)...")
            try:
                start_time = time.time()

                url = f"{MT5_BASE_URL}/fetch_data_pos"
                params = {
                    "symbol": symbol,
                    "timeframe": tf_name,
                    "bars": bars,
                }
                response = requests.get(url, params=params, timeout=MT5_TIMEOUT)
                response.raise_for_status()

                data = response.json()
                elapsed = time.time() - start_time

                if not data:
                    log(f"  WARNING: No data returned for {symbol} {tf_name}")
                    continue

                df = pd.DataFrame(data)

                # Rename tick_volume -> volume
                if "tick_volume" in df.columns:
                    df = df.rename(columns={"tick_volume": "volume"})

                # Parse RFC 2822 time from Flask jsonify
                df["time"] = parse_mt5_time(df["time"])

                # Keep standard columns
                cols = [c for c in ["time", "open", "high", "low", "close", "volume"] if c in df.columns]
                df = df[cols]

                # Sort by time, deduplicate
                df = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)

                # Save
                df.to_csv(filepath, index=False)

                date_min = df["time"].min()
                date_max = df["time"].max()
                log(f"  OK: {len(df)} bars, {date_min} to {date_max} ({elapsed:.1f}s)")

            except requests.exceptions.Timeout:
                log(f"  ERROR: Timeout after {MT5_TIMEOUT}s for {symbol} {tf_name}")
            except requests.exceptions.HTTPError as e:
                log(f"  ERROR: HTTP {e.response.status_code} for {symbol} {tf_name}")
            except Exception as e:
                log(f"  ERROR: {symbol} {tf_name}: {e}")
                traceback.print_exc()

            # Small delay between requests
            time.sleep(0.5)


# ---------------------------------------------------------------------------
# MT5 Date-Range Download (for longer history)
# ---------------------------------------------------------------------------

def download_mt5_range():
    """
    Use /fetch_data_range to pull data in monthly chunks.
    Only runs for symbol/timeframe combos where fetch_data_pos got < 4000 bars
    (except D1, which always tries extended range for max history).
    """
    log("\n" + "=" * 60)
    log("MT5 DATE-RANGE DOWNLOAD (extended history)")
    log("=" * 60)

    try:
        r = requests.get(f"{MT5_BASE_URL}/health", timeout=5)
        if r.status_code != 200:
            log("MT5 API not healthy, skipping range download")
            return
    except Exception:
        log("MT5 API not reachable, skipping range download")
        return

    # Chunk configs per timeframe
    range_configs = {
        "M15": {"months_back": 6, "chunk_months": 1},
        "H1":  {"months_back": 12, "chunk_months": 2},
        "D1":  {"months_back": 60, "chunk_months": 12},
    }

    now = datetime.now(timezone.utc)

    for symbol in MT5_SYMBOLS:
        for tf_name, config in range_configs.items():
            existing = MT5_DIR / f"{symbol}_{tf_name}.csv"

            # Skip if we already have plenty of bars (except D1 where we want max history)
            if existing.exists():
                existing_df = pd.read_csv(existing)
                if len(existing_df) >= 4000 and tf_name != "D1":
                    log(f"\nSkipping range download for {symbol} {tf_name} -- already have {len(existing_df)} bars")
                    continue
                # For D1, skip if we already have 4500+ (close to max from fetch_data_pos)
                if tf_name == "D1" and len(existing_df) >= 4500:
                    log(f"\nSkipping range download for {symbol} {tf_name} -- already have {len(existing_df)} bars")
                    continue

            log(f"\nFetching MT5 range: {symbol} {tf_name} ({config['months_back']} months back)...")

            all_chunks = []
            months_back = config["months_back"]
            chunk_months = config["chunk_months"]

            start_date = now - timedelta(days=months_back * 30)
            current_start = start_date

            while current_start < now:
                current_end = min(current_start + timedelta(days=chunk_months * 30), now)

                try:
                    url = f"{MT5_BASE_URL}/fetch_data_range"
                    params = {
                        "symbol": symbol,
                        "timeframe": tf_name,
                        "start": current_start.isoformat(),
                        "end": current_end.isoformat(),
                    }
                    response = requests.get(url, params=params, timeout=MT5_TIMEOUT)
                    response.raise_for_status()
                    data = response.json()

                    if data:
                        chunk_df = pd.DataFrame(data)
                        all_chunks.append(chunk_df)
                        log(f"  Chunk {current_start.strftime('%Y-%m-%d')} to {current_end.strftime('%Y-%m-%d')}: {len(chunk_df)} bars")
                    else:
                        log(f"  Chunk {current_start.strftime('%Y-%m-%d')} to {current_end.strftime('%Y-%m-%d')}: empty")

                except Exception as e:
                    log(f"  ERROR chunk {current_start.strftime('%Y-%m-%d')}: {e}")

                current_start = current_end
                time.sleep(0.3)

            if all_chunks:
                df = pd.concat(all_chunks, ignore_index=True)
                if "tick_volume" in df.columns:
                    df = df.rename(columns={"tick_volume": "volume"})
                df["time"] = parse_mt5_time(df["time"])
                cols = [c for c in ["time", "open", "high", "low", "close", "volume"] if c in df.columns]
                df = df[cols]
                df = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)

                log(f"  TOTAL: {len(df)} bars, {df['time'].min()} to {df['time'].max()}")

                # If extended has more data, replace the basic file
                if existing.exists():
                    existing_df = pd.read_csv(existing)
                    if len(df) > len(existing_df):
                        df.to_csv(existing, index=False)
                        log(f"  Replaced basic file ({len(existing_df)} -> {len(df)} bars)")
                    else:
                        log(f"  Basic file already has more data ({len(existing_df)} >= {len(df)}), keeping it")
                else:
                    df.to_csv(existing, index=False)
                    log(f"  Saved as {existing.name}")
            else:
                log(f"  No data collected for {symbol} {tf_name}")


# ---------------------------------------------------------------------------
# yfinance Download
# ---------------------------------------------------------------------------

def download_yfinance_data():
    """Download data from Yahoo Finance via yfinance.

    yfinance >= 1.0 uses MultiIndex columns when downloading single tickers
    via Ticker.history(). We use yf.download() which also has MultiIndex
    columns in v1.x. The _normalize_yf_df helper flattens these.
    """
    log("\n" + "=" * 60)
    log("YFINANCE DATA DOWNLOAD")
    log("=" * 60)

    try:
        import yfinance as yf
        log(f"yfinance version: {yf.__version__}")
    except ImportError:
        log("ERROR: yfinance not installed. Run: pip install 'yfinance>=1.0'")
        return

    for our_symbol, yf_ticker in YF_SYMBOL_MAP.items():
        # --- Daily data (5+ years) ---
        log(f"\nFetching yfinance: {our_symbol} D1 (max history) [ticker: {yf_ticker}]...")
        try:
            df_d1 = yf.download(yf_ticker, period="max", interval="1d", progress=False)
            if df_d1.empty:
                log(f"  WARNING: No daily data for {yf_ticker}")
            else:
                df_d1 = _normalize_yf_df(df_d1, yf_ticker)
                filepath = YF_DIR / f"{our_symbol}_D1.csv"
                df_d1.to_csv(filepath, index=False)
                log(f"  OK: {len(df_d1)} bars, {df_d1['time'].min()} to {df_d1['time'].max()}")
        except Exception as e:
            log(f"  ERROR: {e}")
            traceback.print_exc()

        time.sleep(1)

        # --- Hourly data (60 days max) ---
        log(f"Fetching yfinance: {our_symbol} H1 (60d) [ticker: {yf_ticker}]...")
        try:
            df_h1 = yf.download(yf_ticker, period="60d", interval="1h", progress=False)
            if df_h1.empty:
                log(f"  WARNING: No hourly data for {yf_ticker}")
            else:
                df_h1 = _normalize_yf_df(df_h1, yf_ticker)
                filepath = YF_DIR / f"{our_symbol}_H1.csv"
                df_h1.to_csv(filepath, index=False)
                log(f"  OK: {len(df_h1)} bars, {df_h1['time'].min()} to {df_h1['time'].max()}")
        except Exception as e:
            log(f"  ERROR: {e}")
            traceback.print_exc()

        time.sleep(1)

        # --- 15-minute data (60 days max) ---
        log(f"Fetching yfinance: {our_symbol} M15 (60d) [ticker: {yf_ticker}]...")
        try:
            df_m15 = yf.download(yf_ticker, period="60d", interval="15m", progress=False)
            if df_m15.empty:
                log(f"  WARNING: No M15 data for {yf_ticker}")
            else:
                df_m15 = _normalize_yf_df(df_m15, yf_ticker)
                filepath = YF_DIR / f"{our_symbol}_M15.csv"
                df_m15.to_csv(filepath, index=False)
                log(f"  OK: {len(df_m15)} bars, {df_m15['time'].min()} to {df_m15['time'].max()}")
        except Exception as e:
            log(f"  ERROR: {e}")
            traceback.print_exc()

        time.sleep(1)


def _normalize_yf_df(df, ticker=None):
    """Normalize yfinance DataFrame to standard format.

    Handles both yfinance v1.x MultiIndex columns and older flat columns.
    """
    df = df.copy()

    # yfinance v1.x returns MultiIndex columns: (Price, Ticker)
    # Flatten to just price names
    if isinstance(df.columns, pd.MultiIndex):
        # Drop the ticker level, keep only the price level
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()

    # Find the time column (Date for daily, Datetime for intraday)
    time_col = None
    for col in ["Datetime", "Date", "datetime", "date"]:
        if col in df.columns:
            time_col = col
            break

    if time_col is None:
        # Fall back to first column if it looks like a date
        first_col = df.columns[0]
        if first_col not in ("Open", "High", "Low", "Close", "Volume"):
            time_col = first_col
        else:
            raise ValueError(f"Cannot find time column in: {list(df.columns)}")

    # Standardize column names
    rename_map = {time_col: "time"}
    for src, dst in [("Open", "open"), ("High", "high"), ("Low", "low"),
                     ("Close", "close"), ("Volume", "volume")]:
        if src in df.columns:
            rename_map[src] = dst
    df = df.rename(columns=rename_map)

    # Convert timezone-aware datetimes to UTC naive
    if df["time"].dtype.name.startswith("datetime64") or hasattr(df["time"].dt, "tz"):
        try:
            df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_localize(None)
        except Exception:
            df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    else:
        df["time"] = pd.to_datetime(df["time"])

    cols = [c for c in ["time", "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[cols]
    df = df.sort_values("time").reset_index(drop=True)

    return df


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def write_summary():
    """Write download summary to file."""
    summary_path = BASE_DIR / "summary.txt"

    extra_lines = [
        "",
        "=" * 60,
        "FILES PRODUCED",
        "=" * 60,
    ]

    total_files = 0
    total_bars = 0

    for subdir in [MT5_DIR, YF_DIR]:
        source = subdir.name
        csv_files = sorted(subdir.glob("*.csv"))
        if csv_files:
            extra_lines.append(f"\n--- {source}/ ---")
            for f in csv_files:
                try:
                    df_full = pd.read_csv(f)
                    size_kb = f.stat().st_size / 1024
                    date_min = df_full["time"].min() if "time" in df_full.columns else "?"
                    date_max = df_full["time"].max() if "time" in df_full.columns else "?"
                    extra_lines.append(
                        f"  {f.name}: {len(df_full):,} bars, {date_min} to {date_max}, {size_kb:.0f} KB"
                    )
                    total_files += 1
                    total_bars += len(df_full)
                except Exception as e:
                    extra_lines.append(f"  {f.name}: ERROR reading - {e}")
        else:
            extra_lines.append(f"\n--- {source}/ --- (no files)")

    extra_lines.append(f"\nTOTAL: {total_files} files, {total_bars:,} bars")

    all_lines = [
        "Backtest Data Download Summary",
        f"Generated: {datetime.now().isoformat()}",
        "",
    ] + summary_lines + extra_lines

    summary_path.write_text("\n".join(all_lines))
    log(f"\nSummary written to {summary_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log(f"Backtest Data Downloader -- {datetime.now().isoformat()}")
    log(f"Output directory: {BASE_DIR}")

    ensure_dirs()

    # 1. MT5 data (fetch_data_pos for up to 5000 bars per request)
    download_mt5_data()

    # 2. MT5 extended range data (monthly chunks for symbol/tf combos that need more)
    download_mt5_range()

    # 3. yfinance data (daily: max history, intraday: 60 days)
    download_yfinance_data()

    # 4. Write summary
    write_summary()

    log("\nDONE!")


if __name__ == "__main__":
    main()
