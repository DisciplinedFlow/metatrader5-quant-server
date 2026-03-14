"""
Funding Rate Arbitrage Monitor — compares perpetual funding rates between
Lighter.xyz and Hyperliquid to identify cross-venue arbitrage opportunities.

When one venue pays longs and the other pays shorts (or the spread is large
enough), there is a delta-neutral arb: go long on the cheaper venue and short
on the expensive one, collecting the funding differential.

This module is monitoring/alerting only — no auto-execution.
"""
import json
import logging
from datetime import datetime, timezone

import redis
from django.conf import settings

logger = logging.getLogger('app.crypto')

# ── Config ────────────────────────────────────────────────
# Overlapping symbols available on both Lighter and Hyperliquid
ARB_SYMBOLS = ['ETH', 'BTC', 'SOL']

# Minimum absolute spread (in rate terms) to flag as an opportunity.
# Funding rates are typically expressed as 8h rates, e.g. 0.0001 = 0.01%.
# A 0.005% (0.00005) spread is roughly 2.3% annualized — worth flagging.
MIN_SPREAD_THRESHOLD = float(0.00005)

REDIS_KEY = 'crypto:funding_arb:latest'
REDIS_TTL = 600  # 10 minutes — stale after 2 missed scans


def _get_redis():
    return redis.Redis.from_url(settings.CELERY_BROKER_URL)


# ── Data Fetchers ─────────────────────────────────────────

def _fetch_hyperliquid_funding() -> dict:
    """Fetch current predicted funding rates from Hyperliquid.

    Uses info.meta_and_asset_ctxs() which returns:
      [meta_dict, [asset_ctx, ...]]
    where each asset_ctx has 'funding' (current 8h predicted rate).
    """
    from .client import get_info

    info = get_info()
    result = info.meta_and_asset_ctxs()

    meta = result[0]       # {'universe': [{'name': 'BTC', ...}, ...]}
    ctxs = result[1]       # [{'funding': '0.00001234', 'openInterest': ...}, ...]

    universe = meta.get('universe', [])
    rates = {}
    for asset_meta, ctx in zip(universe, ctxs):
        symbol = asset_meta.get('name', '')
        if symbol in ARB_SYMBOLS:
            try:
                rate = float(ctx.get('funding', 0))
                rates[symbol] = rate
            except (ValueError, TypeError):
                logger.warning("HL: could not parse funding for %s: %s", symbol, ctx.get('funding'))

    return rates


def _fetch_lighter_funding() -> dict:
    """Fetch current funding rates from Lighter.xyz exchange stats.

    get_exchange_stats() returns an object with order_book_details or similar
    stats per market. The funding rate field varies by SDK version.
    """
    from ..lighter.client import get_exchange_stats
    from ..lighter.config import LIGHTER_MARKETS

    rates = {}
    try:
        stats = get_exchange_stats()
        # The Lighter SDK returns exchange stats with a list of market stats.
        # Access the raw data — it may be a Pydantic model or dict.
        stats_data = stats
        if hasattr(stats, 'to_dict'):
            stats_data = stats.to_dict()
        elif hasattr(stats, 'model_dump'):
            stats_data = stats.model_dump()

        # Build market_id -> symbol lookup for our target symbols
        id_to_symbol = {}
        for sym in ARB_SYMBOLS:
            if sym in LIGHTER_MARKETS:
                id_to_symbol[LIGHTER_MARKETS[sym]['id']] = sym

        # Parse the stats response — adapt to actual SDK response shape
        market_stats = []
        if isinstance(stats_data, dict):
            # Try common keys the SDK might use
            market_stats = (
                stats_data.get('exchange_stats', []) or
                stats_data.get('market_stats', []) or
                stats_data.get('stats', []) or
                stats_data.get('order_book_details', []) or
                []
            )
            # If top-level dict has funding data directly
            if not market_stats and 'funding_rate' in stats_data:
                market_stats = [stats_data]
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

            # Try to match this stat entry to one of our symbols
            market_id = ms.get('market_id') or ms.get('marketId')
            symbol = ms.get('symbol') or ms.get('name')

            matched_sym = None
            if market_id is not None:
                matched_sym = id_to_symbol.get(int(market_id))
            elif symbol and symbol in ARB_SYMBOLS:
                matched_sym = symbol

            if matched_sym is None:
                continue

            # Extract funding rate — try common field names
            funding = (
                ms.get('funding_rate') or
                ms.get('fundingRate') or
                ms.get('predicted_funding_rate') or
                ms.get('next_funding_rate') or
                ms.get('funding') or
                None
            )
            if funding is not None:
                try:
                    rates[matched_sym] = float(funding)
                except (ValueError, TypeError):
                    logger.warning("Lighter: could not parse funding for %s: %s", matched_sym, funding)

    except Exception as e:
        logger.error("Failed to fetch Lighter exchange stats: %s", e)

    return rates


# ── Arb Scanner ───────────────────────────────────────────

def scan_funding_arb() -> dict:
    """Compare funding rates across venues and identify arb opportunities.

    Returns a dict with scan metadata and a list of opportunities.
    The result is also stored in Redis for the API endpoint.
    """
    scan_time = datetime.now(timezone.utc).isoformat()
    opportunities = []
    all_rates = {}

    # Fetch funding rates from both venues
    hl_rates = {}
    lighter_rates = {}

    try:
        hl_rates = _fetch_hyperliquid_funding()
        logger.info("Funding scan — Hyperliquid rates: %s", hl_rates)
    except Exception as e:
        logger.error("Funding scan — Hyperliquid fetch failed: %s", e)

    try:
        lighter_rates = _fetch_lighter_funding()
        logger.info("Funding scan — Lighter rates: %s", lighter_rates)
    except Exception as e:
        logger.error("Funding scan — Lighter fetch failed: %s", e)

    # Compare overlapping symbols
    for symbol in ARB_SYMBOLS:
        hl_rate = hl_rates.get(symbol)
        lt_rate = lighter_rates.get(symbol)

        entry = {
            'symbol': symbol,
            'hyperliquid_rate': hl_rate,
            'lighter_rate': lt_rate,
            'spread': None,
            'abs_spread': None,
            'direction': None,
            'is_opportunity': False,
        }

        if hl_rate is not None and lt_rate is not None:
            spread = hl_rate - lt_rate
            abs_spread = abs(spread)
            entry['spread'] = spread
            entry['abs_spread'] = abs_spread

            # Annualized: 8h rate * 3 * 365
            entry['annualized_pct'] = round(abs_spread * 3 * 365 * 100, 4)

            if abs_spread >= MIN_SPREAD_THRESHOLD:
                entry['is_opportunity'] = True
                if spread > 0:
                    # HL funding higher -> longs pay more on HL
                    # Strategy: SHORT on HL (receive funding), LONG on Lighter
                    entry['direction'] = 'SHORT HL / LONG Lighter'
                else:
                    # Lighter funding higher -> longs pay more on Lighter
                    # Strategy: SHORT on Lighter, LONG on HL
                    entry['direction'] = 'SHORT Lighter / LONG HL'

                logger.info(
                    "FUNDING ARB: %s spread=%.6f (%.4f%% ann.) | HL=%.6f Lighter=%.6f | %s",
                    symbol, abs_spread, entry['annualized_pct'],
                    hl_rate, lt_rate, entry['direction'],
                )

        all_rates[symbol] = entry
        if entry['is_opportunity']:
            opportunities.append(entry)

    result = {
        'scan_time': scan_time,
        'threshold': MIN_SPREAD_THRESHOLD,
        'symbols_scanned': ARB_SYMBOLS,
        'rates': all_rates,
        'opportunities': opportunities,
        'opportunity_count': len(opportunities),
    }

    # Store in Redis
    try:
        r = _get_redis()
        r.set(REDIS_KEY, json.dumps(result), ex=REDIS_TTL)
        logger.debug("Funding arb results stored in Redis key=%s", REDIS_KEY)
    except Exception as e:
        logger.error("Failed to store funding arb results in Redis: %s", e)

    return result


def get_latest_arb_data() -> dict | None:
    """Retrieve the most recent funding arb scan from Redis."""
    try:
        r = _get_redis()
        data = r.get(REDIS_KEY)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.error("Failed to read funding arb data from Redis: %s", e)
    return None
