"""
Lighter.xyz Liquidation Cascade Detector — mean reversion signal from mass liquidations.

When mass liquidations happen on a DEX, price overshoots and snaps back. This module
monitors liquidation volume and generates counter-trade signals when cascades are detected.

Logic:
- Track liquidation volume per symbol in rolling 1-minute buckets (Redis cache)
- Compare the last 5 minutes of liquidation volume against the 1-hour average
- When the 5-min volume exceeds 3x the hourly average, generate a counter-trade signal:
    - Mass LONG liquidations = price crashed (is_maker_ask=True → sell-side) = BUY signal
    - Mass SHORT liquidations = price spiked (is_maker_ask=False → buy-side) = SELL signal

Redis keys:
- lighter:liq_volume:{symbol}:{minute_ts}:long  — liquidated long volume in USD
- lighter:liq_volume:{symbol}:{minute_ts}:short — liquidated short volume in USD
- lighter:liq_last_scan:{symbol} — timestamp of last scan (dedup)

Called every 10s by Celery or from within mean_reversion_algorithm.
"""
import logging
import time

from django.core.cache import cache

from .config import LIGHTER_MARKETS, get_market_id
from .client import get_recent_liquidations

logger = logging.getLogger('app.lighter')

# ── Configuration ─────────────────────────────────────────
SCAN_INTERVAL_SECONDS = 10          # Minimum time between API polls per symbol
ROLLING_WINDOW_MINUTES = 5          # Recent window to detect spikes
BASELINE_WINDOW_MINUTES = 60        # Baseline average window
SPIKE_THRESHOLD = 3.0               # 3x average = cascade detected
BUCKET_TTL_SECONDS = 3900           # 65 minutes — keep buckets slightly longer than baseline
MIN_LIQUIDATION_USD = 50.0          # Ignore tiny liquidations (noise filter)
SIGNAL_COOLDOWN_SECONDS = 300       # 5 min cooldown after firing a signal

# ── Internal helpers ──────────────────────────────────────

def _minute_bucket(ts: int) -> int:
    """Round a unix timestamp down to the nearest minute."""
    return (ts // 60) * 60


def _cache_key(symbol: str, minute_ts: int, side: str) -> str:
    """Redis cache key for liquidation volume bucket."""
    return f'lighter:liq_volume:{symbol}:{minute_ts}:{side}'


def _signal_cooldown_key(symbol: str) -> str:
    return f'lighter:liq_signal_cooldown:{symbol}'


def _last_scan_key(symbol: str) -> str:
    return f'lighter:liq_last_scan:{symbol}'


def _last_trade_id_key(symbol: str) -> str:
    return f'lighter:liq_last_trade_id:{symbol}'


# ── Core: ingest liquidation trades into Redis buckets ────

def ingest_liquidations(symbol: str) -> int:
    """Fetch recent liquidation trades for a symbol and store volumes in Redis buckets.

    Returns the number of new liquidation trades ingested.
    """
    meta = LIGHTER_MARKETS.get(symbol)
    if meta is None:
        return 0

    # Rate limit API calls
    now = int(time.time())
    last_scan = cache.get(_last_scan_key(symbol))
    if last_scan and (now - last_scan) < SCAN_INTERVAL_SECONDS:
        return 0

    cache.set(_last_scan_key(symbol), now, timeout=SCAN_INTERVAL_SECONDS + 5)

    market_id = meta['id']
    try:
        liq_trades = get_recent_liquidations(market_id=market_id, limit=100)
    except Exception as e:
        logger.error("Liquidation fetch failed for %s: %s", symbol, e)
        return 0

    if not liq_trades:
        return 0

    # Dedup: only process trades newer than last seen trade_id
    last_seen_id = cache.get(_last_trade_id_key(symbol)) or 0
    new_trades = [t for t in liq_trades if (t.get('trade_id') or 0) > last_seen_id]

    if not new_trades:
        return 0

    # Update last seen trade_id
    max_trade_id = max(t.get('trade_id', 0) for t in new_trades)
    cache.set(_last_trade_id_key(symbol), max_trade_id, timeout=BUCKET_TTL_SECONDS)

    ingested = 0
    for trade in new_trades:
        usd_amount = abs(float(trade.get('usd_amount', 0)))
        if usd_amount < MIN_LIQUIDATION_USD:
            continue

        ts = trade.get('timestamp', 0)
        if ts == 0:
            continue

        minute_ts = _minute_bucket(ts)

        # Determine if this was a long or short liquidation:
        # is_maker_ask=True means the liquidated order was on the ask side (was long, got liquidated = sell)
        # is_maker_ask=False means the liquidated order was on the bid side (was short, got liquidated = buy)
        is_maker_ask = trade.get('is_maker_ask', False)
        side = 'long' if is_maker_ask else 'short'

        # Accumulate USD volume into the minute bucket
        key = _cache_key(symbol, minute_ts, side)
        current = cache.get(key) or 0.0
        cache.set(key, current + usd_amount, timeout=BUCKET_TTL_SECONDS)
        ingested += 1

    if ingested > 0:
        logger.debug("LIQ ingest %s: %d new liquidation trades", symbol, ingested)

    return ingested


# ── Core: compute liquidation signal ─────────────────────

def check_liquidation_signal(symbol: str) -> tuple:
    """Check if a liquidation cascade signal is active for a symbol.

    Returns:
        (signal, volume_ratio) where:
            signal: 1 (buy — long cascade, price overshot down),
                   -1 (sell — short cascade, price overshot up),
                    0 (no signal)
            volume_ratio: how many times the recent volume exceeds the baseline.
                          0.0 if no data. > SPIKE_THRESHOLD means cascade detected.
    """
    meta = LIGHTER_MARKETS.get(symbol)
    if meta is None:
        return 0, 0.0

    # First, try to ingest fresh data
    ingest_liquidations(symbol)

    # Check signal cooldown
    if cache.get(_signal_cooldown_key(symbol)):
        return 0, 0.0

    now = int(time.time())
    current_minute = _minute_bucket(now)

    # Gather volumes for the recent window (last 5 minutes)
    recent_long = 0.0
    recent_short = 0.0
    for i in range(ROLLING_WINDOW_MINUTES):
        minute_ts = current_minute - (i * 60)
        recent_long += cache.get(_cache_key(symbol, minute_ts, 'long')) or 0.0
        recent_short += cache.get(_cache_key(symbol, minute_ts, 'short')) or 0.0

    recent_total = recent_long + recent_short
    if recent_total == 0:
        return 0, 0.0

    # Gather volumes for the full baseline window (last 60 minutes)
    baseline_long = 0.0
    baseline_short = 0.0
    for i in range(BASELINE_WINDOW_MINUTES):
        minute_ts = current_minute - (i * 60)
        baseline_long += cache.get(_cache_key(symbol, minute_ts, 'long')) or 0.0
        baseline_short += cache.get(_cache_key(symbol, minute_ts, 'short')) or 0.0

    baseline_total = baseline_long + baseline_short

    # Calculate hourly average per 5-minute window
    # The baseline has 12 non-overlapping 5-minute windows in 60 minutes
    num_windows = BASELINE_WINDOW_MINUTES // ROLLING_WINDOW_MINUTES
    if num_windows == 0:
        return 0, 0.0

    avg_5min_volume = baseline_total / num_windows
    if avg_5min_volume <= 0:
        # No historical data — if recent volume is significant, use absolute threshold
        if recent_total >= 500.0:  # $500+ in 5 min with no history = notable
            volume_ratio = SPIKE_THRESHOLD + 1  # Force trigger
        else:
            return 0, 0.0
    else:
        volume_ratio = recent_total / avg_5min_volume

    if volume_ratio < SPIKE_THRESHOLD:
        return 0, volume_ratio

    # Cascade detected! Determine direction.
    # Mass long liquidations = price dropped hard = buy signal (mean reversion up)
    # Mass short liquidations = price spiked hard = sell signal (mean reversion down)
    if recent_long > recent_short:
        signal = 1   # Buy the dip — longs got liquidated, price overshot down
        logger.info(
            "LIQ CASCADE %s: LONG liquidations $%.0f in %dmin (%.1fx avg) -> BUY signal",
            symbol, recent_long, ROLLING_WINDOW_MINUTES, volume_ratio,
        )
    elif recent_short > recent_long:
        signal = -1  # Sell the top — shorts got liquidated, price overshot up
        logger.info(
            "LIQ CASCADE %s: SHORT liquidations $%.0f in %dmin (%.1fx avg) -> SELL signal",
            symbol, recent_short, ROLLING_WINDOW_MINUTES, volume_ratio,
        )
    else:
        # Equal both sides — ambiguous, skip
        return 0, volume_ratio

    # Set cooldown to prevent rapid re-firing
    cache.set(_signal_cooldown_key(symbol), True, timeout=SIGNAL_COOLDOWN_SECONDS)

    return signal, volume_ratio


# ── Utility: scan all symbols (called by Celery) ─────────

def scan_all_liquidations(symbols: list = None) -> dict:
    """Scan all configured symbols for liquidation cascades.

    Returns dict of {symbol: (signal, volume_ratio)} for symbols with active signals.
    """
    if symbols is None:
        # Default to crypto majors — liquidations are most relevant there
        symbols = ['ETH', 'BTC', 'SOL']

    results = {}
    for symbol in symbols:
        try:
            signal, ratio = check_liquidation_signal(symbol)
            if signal != 0:
                results[symbol] = (signal, ratio)
        except Exception as e:
            logger.error("LIQ scan error for %s: %s", symbol, e)

    return results
