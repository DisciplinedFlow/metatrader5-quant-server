"""
Lighter DEX historical candle downloader.

Standalone script (no Django dependencies). Downloads 6 months of OHLCV
candles from the Lighter CandlestickApi and stores them as Parquet files.

Usage:
    python3 backtest/data_collector.py

Resumes from the last downloaded timestamp if a partial file exists.
"""
import json
import os
import sys
import time
from typing import Optional
import datetime
import logging
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────

API_URL = os.getenv("LIGHTER_API_URL", "https://mainnet.zklighter.elliot.ai")

SYMBOLS = {
    "SOL": 2,
    "XAU": 92,
    "AVAX": 9,
    "DOGE": 3,
}

TIMEFRAMES = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
}

LOOKBACK_DAYS = 180  # ~6 months
MAX_CANDLES_PER_REQUEST = 1000
RATE_LIMIT_SECONDS = 1.0

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


# ── Helpers ──────────────────────────────────────────────

def _candle_endpoint(market_id: int, resolution: str,
                     start_ts: int, end_ts: int, count_back: int) -> str:
    return (
        f"{API_URL}/api/v1/candlesticks"
        f"?market_id={market_id}"
        f"&resolution={resolution}"
        f"&start_timestamp={start_ts}"
        f"&end_timestamp={end_ts}"
        f"&count_back={count_back}"
    )


def fetch_candles(market_id: int, resolution: str,
                  start_ts: int, end_ts: int,
                  count_back: int = MAX_CANDLES_PER_REQUEST) -> list:
    """Fetch one page of candles via Lighter SDK (CloudFront blocks raw HTTP)."""
    import asyncio
    import lighter

    async def _fetch():
        api = lighter.ApiClient(configuration=lighter.Configuration(host=API_URL))
        try:
            candle_api = lighter.CandlestickApi(api)
            resp = await candle_api.candles_without_preload_content(
                market_id=market_id,
                resolution=resolution,
                start_timestamp=start_ts,
                end_timestamp=end_ts,
                count_back=count_back,
            )
            body = await resp.read()
            data = json.loads(body.decode())
            candles = data.get("c", [])
            return [
                {
                    "timestamp": int(c["t"]) // 1000,  # API returns ms, store as seconds
                    "open": float(c["o"]),
                    "high": float(c["h"]),
                    "low": float(c["l"]),
                    "close": float(c["c"]),
                    "volume": float(c.get("V", c.get("v", 0))),
                }
                for c in candles
                if c.get("o") is not None
            ]
        finally:
            await api.close()

    return asyncio.run(_fetch())


def _output_path(symbol: str, timeframe: str) -> str:
    return os.path.join(DATA_DIR, f"{symbol}_{timeframe}.parquet")


def _csv_fallback_path(symbol: str, timeframe: str) -> str:
    return os.path.join(DATA_DIR, f"{symbol}_{timeframe}.csv")


def _load_existing(symbol: str, timeframe: str):
    """Load existing data and return (DataFrame-or-None, last_timestamp)."""
    try:
        import pandas as pd
        pq_path = _output_path(symbol, timeframe)
        if os.path.exists(pq_path):
            df = pd.read_parquet(pq_path)
            if len(df) > 0:
                return df, int(df["timestamp"].max())
        csv_path = _csv_fallback_path(symbol, timeframe)
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            if len(df) > 0:
                return df, int(df["timestamp"].max())
    except ImportError:
        csv_path = _csv_fallback_path(symbol, timeframe)
        if os.path.exists(csv_path):
            last_ts = _last_ts_from_csv(csv_path)
            if last_ts:
                return None, last_ts
    return None, None


def _last_ts_from_csv(path: str) -> Optional[int]:
    """Read last timestamp from CSV without pandas."""
    last_line = None
    with open(path, "r") as f:
        for line in f:
            last_line = line
    if last_line and last_line.strip():
        try:
            return int(last_line.split(",")[0])
        except (ValueError, IndexError):
            return None
    return None


def _save_data(rows: list[dict], symbol: str, timeframe: str):
    """Save candle rows to Parquet (preferred) or CSV (fallback)."""
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        pq_path = _output_path(symbol, timeframe)
        df.to_parquet(pq_path, index=False, engine="pyarrow")
        log.info("  Saved %d candles → %s", len(df), pq_path)
    except ImportError:
        log.warning("  pandas/pyarrow not available — falling back to CSV")
        _save_csv(rows, symbol, timeframe)


def _save_csv(rows: list[dict], symbol: str, timeframe: str):
    """CSV fallback when pandas is not installed."""
    # Deduplicate and sort
    seen = set()
    unique = []
    for r in rows:
        if r["timestamp"] not in seen:
            seen.add(r["timestamp"])
            unique.append(r)
    unique.sort(key=lambda x: x["timestamp"])

    csv_path = _csv_fallback_path(symbol, timeframe)
    with open(csv_path, "w") as f:
        f.write("timestamp,open,high,low,close,volume\n")
        for r in unique:
            f.write(f"{r['timestamp']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}\n")
    log.info("  Saved %d candles → %s", len(unique), csv_path)


# ── Main download loop ──────────────────────────────────

def download_symbol_timeframe(symbol: str, market_id: int,
                              timeframe: str, tf_seconds: int):
    """Download full history for one symbol+timeframe pair."""
    log.info("Downloading %s %s (market_id=%d) ...", symbol, timeframe, market_id)

    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    start_ts = now_ts - (LOOKBACK_DAYS * 86400)

    # Resume from last downloaded timestamp
    existing_df, last_ts = _load_existing(symbol, timeframe)
    existing_rows = []
    if existing_df is not None:
        try:
            existing_rows = existing_df.to_dict("records")
        except Exception:
            pass

    if last_ts and last_ts > start_ts:
        log.info("  Resuming from %s (%d existing candles)",
                 datetime.datetime.fromtimestamp(last_ts, tz=datetime.timezone.utc).isoformat(),
                 len(existing_rows))
        # Start from last timestamp + 1 candle interval to avoid overlap
        start_ts = last_ts + tf_seconds

    if start_ts >= now_ts:
        log.info("  Already up to date.")
        return

    all_rows = list(existing_rows)
    cursor = start_ts
    page = 0
    consecutive_empty = 0

    while cursor < now_ts:
        page_end = min(cursor + MAX_CANDLES_PER_REQUEST * tf_seconds, now_ts)
        count_back = min(MAX_CANDLES_PER_REQUEST, (page_end - cursor) // tf_seconds + 1)

        try:
            candles = fetch_candles(market_id, timeframe, cursor, page_end, count_back)
        except Exception as e:
            err_str = str(e)
            if '429' in err_str:
                log.warning("  Rate limited — waiting 5s ...")
                time.sleep(5)
                continue
            log.error("  Error fetching %s %s page %d: %s", symbol, timeframe, page, e)
            if all_rows:
                _save_data(all_rows, symbol, timeframe)
            break

        if not candles:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                log.info("  No more data available (3 consecutive empty pages).")
                break
            cursor = page_end
            time.sleep(RATE_LIMIT_SECONDS)
            continue

        consecutive_empty = 0
        all_rows.extend(candles)
        page += 1

        # Advance cursor past the last candle we received
        max_ts = max(c["timestamp"] for c in candles)
        cursor = max_ts + tf_seconds

        log.info("  Page %d: %d candles (latest %s, total %d)",
                 page, len(candles),
                 datetime.datetime.fromtimestamp(max_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                 len(all_rows))

        # Save intermediate progress every 10 pages
        if page % 10 == 0 and all_rows:
            _save_data(all_rows, symbol, timeframe)

        time.sleep(RATE_LIMIT_SECONDS)

    if all_rows:
        _save_data(all_rows, symbol, timeframe)
    else:
        log.warning("  No candles downloaded for %s %s", symbol, timeframe)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    total = len(SYMBOLS) * len(TIMEFRAMES)
    log.info("Downloading %d symbol×timeframe combinations (%d-day lookback)",
             total, LOOKBACK_DAYS)
    log.info("API: %s", API_URL)
    log.info("Output: %s", DATA_DIR)

    count = 0
    for symbol, market_id in SYMBOLS.items():
        for tf_name, tf_seconds in TIMEFRAMES.items():
            count += 1
            log.info("─── [%d/%d] %s %s ───", count, total, symbol, tf_name)
            download_symbol_timeframe(symbol, market_id, tf_name, tf_seconds)

    log.info("Done. Files in %s:", DATA_DIR)
    for f in sorted(os.listdir(DATA_DIR)):
        if f.endswith((".parquet", ".csv")):
            size = os.path.getsize(os.path.join(DATA_DIR, f))
            log.info("  %s (%s)", f, _human_size(size))


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


if __name__ == "__main__":
    main()
