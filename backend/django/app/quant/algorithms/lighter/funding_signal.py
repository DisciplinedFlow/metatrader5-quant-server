"""
Funding rate contrarian signal — when funding is extreme, trade against the crowd.

Research shows:
- Extreme positive funding (>0.1%/hr, ~87% annualized) = longs overlevered -> SHORT signal
- Extreme negative funding = shorts overlevered -> LONG signal
- Funding rates are predictable and mean-revert within 4-24 hours
- Z-score > 2 or < -2 = actionable

Uses Lighter's CandlestickApi.fundings_without_preload_content() for historical data
+ exchange_stats for current rate fallback.

Funding model fields (from SDK): timestamp, value, rate, direction
"""
import datetime
import json
import logging
import statistics

import lighter
from django.core.cache import cache

from .config import LIGHTER_API_URL, LIGHTER_MARKETS, get_market_id

logger = logging.getLogger('app.lighter')

# ── Configuration ─────────────────────────────────────────
CACHE_KEY_PREFIX = 'lighter:funding_signal'
CACHE_TTL = 300              # 5 minutes
Z_SCORE_THRESHOLD = 2.0      # |z| > 2 = actionable contrarian signal
HOURS_PER_YEAR = 8760        # For annualization
DEFAULT_LOOKBACK_HOURS = 24  # Historical window for z-score baseline

# Forex/metals/stocks don't have perpetual funding
NON_FUNDING_SYMBOLS = {
    'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD',
    'XAU', 'XAG', 'PAXG', 'WTI',
    'TSLA', 'NVDA', 'AAPL', 'AMZN', 'MSFT', 'GOOGL', 'META',
    'SPY', 'QQQ',
}


def _run(coro):
    """Run an async coroutine from sync Django/Celery code."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result(timeout=30)
    else:
        return asyncio.run(coro)


# ── Data fetching ─────────────────────────────────────────

def get_funding_history(symbol: str, hours: int = 24) -> list:
    """Fetch historical funding rate data from Lighter.

    Uses fundings_without_preload_content (raw JSON) to avoid SDK Pydantic
    parsing bugs (same pattern as get_candles in client.py).

    Returns list of dicts: {timestamp, value, rate, direction}
    """
    if symbol in NON_FUNDING_SYMBOLS:
        return []

    market_id = get_market_id(symbol)

    async def _fetch():
        api = lighter.ApiClient(configuration=lighter.Configuration(host=LIGHTER_API_URL))
        try:
            candle_api = lighter.CandlestickApi(api)
            now = int(datetime.datetime.now().timestamp())
            start = now - (hours * 3600)
            resp = await candle_api.fundings_without_preload_content(
                market_id=market_id,
                resolution='1h',
                start_timestamp=start,
                end_timestamp=now,
                count_back=hours,
            )
            body = await resp.read()
            data = json.loads(body.decode())
            # Response structure: {code, message, resolution, fundings: [...]}
            fundings = data.get('fundings', [])
            return [
                {
                    'timestamp': f.get('timestamp', 0),
                    'value': f.get('value', '0'),
                    'rate': f.get('rate', '0'),
                    'direction': f.get('direction', ''),
                }
                for f in fundings
                if f.get('rate') is not None
            ]
        finally:
            await api.close()

    try:
        return _run(_fetch())
    except Exception as e:
        logger.warning("Funding history fetch failed for %s: %s", symbol, e)
        return []


def _get_current_rate_from_exchange_stats(symbol: str) -> float | None:
    """Fallback: extract current funding rate from exchange_stats endpoint."""
    try:
        from .client import get_exchange_stats

        stats = get_exchange_stats()
        stats_data = stats
        if hasattr(stats, 'to_dict'):
            stats_data = stats.to_dict()
        elif hasattr(stats, 'model_dump'):
            stats_data = stats.model_dump()

        market_id = LIGHTER_MARKETS.get(symbol, {}).get('id')
        if market_id is None:
            return None

        # Try common response structures
        market_stats = []
        if isinstance(stats_data, dict):
            market_stats = (
                stats_data.get('exchange_stats', []) or
                stats_data.get('market_stats', []) or
                stats_data.get('stats', []) or
                stats_data.get('order_book_details', []) or
                []
            )
        elif isinstance(stats_data, list):
            market_stats = stats_data

        for ms in market_stats:
            if not isinstance(ms, dict):
                if hasattr(ms, 'to_dict'):
                    ms = ms.to_dict()
                elif hasattr(ms, '__dict__'):
                    ms = vars(ms)
                else:
                    continue

            ms_id = ms.get('market_id') or ms.get('marketId')
            if ms_id is not None and int(ms_id) == market_id:
                funding = (
                    ms.get('funding_rate') or
                    ms.get('fundingRate') or
                    ms.get('predicted_funding_rate') or
                    ms.get('next_funding_rate') or
                    ms.get('funding') or
                    None
                )
                if funding is not None:
                    return float(funding)

    except Exception as e:
        logger.debug("Exchange stats funding fetch failed for %s: %s", symbol, e)
    return None


# ── Signal computation ────────────────────────────────────

def get_funding_rate_signal(symbol: str) -> dict:
    """Compute contrarian funding rate signal for a symbol.

    Returns dict with:
        signal: 1 (contrarian long), -1 (contrarian short), 0 (neutral)
        current_rate: current hourly funding rate
        z_score: how extreme current rate is vs 24h average
        direction_hint: 'CONTRARIAN_LONG', 'CONTRARIAN_SHORT', 'NEUTRAL'
        annualized_rate: current rate annualized for context
    """
    neutral_result = {
        'signal': 0,
        'current_rate': 0.0,
        'z_score': 0.0,
        'direction_hint': 'NEUTRAL',
        'annualized_rate': 0.0,
        'rates_count': 0,
    }

    # Non-funding assets always return neutral
    if symbol in NON_FUNDING_SYMBOLS:
        neutral_result['direction_hint'] = 'NO_FUNDING'
        return neutral_result

    # Check Redis cache first
    cache_key = f'{CACHE_KEY_PREFIX}:{symbol}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Fetch historical funding rates
    history = get_funding_history(symbol, hours=DEFAULT_LOOKBACK_HOURS)

    if not history or len(history) < 3:
        # Fallback: try exchange_stats for current rate only (no z-score)
        current = _get_current_rate_from_exchange_stats(symbol)
        if current is not None and current != 0.0:
            neutral_result['current_rate'] = current
            neutral_result['annualized_rate'] = current * HOURS_PER_YEAR
        cache.set(cache_key, neutral_result, timeout=CACHE_TTL)
        return neutral_result

    # Parse rates into floats
    rates = []
    for entry in history:
        try:
            rate = float(entry['rate'])
            rates.append(rate)
        except (ValueError, TypeError, KeyError):
            continue

    if len(rates) < 3:
        cache.set(cache_key, neutral_result, timeout=CACHE_TTL)
        return neutral_result

    # Current rate = most recent entry
    current_rate = rates[-1]

    # Calculate z-score: (current - mean) / std
    mean_rate = statistics.mean(rates)
    try:
        std_rate = statistics.stdev(rates)
    except statistics.StatisticsError:
        std_rate = 0.0

    if std_rate > 0:
        z_score = (current_rate - mean_rate) / std_rate
    else:
        z_score = 0.0

    annualized = current_rate * HOURS_PER_YEAR

    # Determine contrarian signal
    signal = 0
    direction_hint = 'NEUTRAL'

    if z_score > Z_SCORE_THRESHOLD:
        # Extremely positive funding = longs are overlevered = SHORT contrarian
        signal = -1
        direction_hint = 'CONTRARIAN_SHORT'
    elif z_score < -Z_SCORE_THRESHOLD:
        # Extremely negative funding = shorts are overlevered = LONG contrarian
        signal = 1
        direction_hint = 'CONTRARIAN_LONG'

    result = {
        'signal': signal,
        'current_rate': current_rate,
        'z_score': round(z_score, 3),
        'direction_hint': direction_hint,
        'annualized_rate': round(annualized, 4),
        'rates_count': len(rates),
        'mean_rate': round(mean_rate, 8),
        'std_rate': round(std_rate, 8),
    }

    if signal != 0:
        logger.info(
            "FUNDING SIGNAL %s: %s z=%.2f rate=%.6f ann=%.2f%% (mean=%.6f std=%.6f, %d samples)",
            symbol, direction_hint, z_score, current_rate,
            annualized * 100, mean_rate, std_rate, len(rates),
        )

    # Cache result for 5 minutes
    cache.set(cache_key, result, timeout=CACHE_TTL)
    return result
