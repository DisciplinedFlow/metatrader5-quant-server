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

# def _fetch_hyperliquid_funding() -> dict:
#     """Fetch current predicted funding rates from Hyperliquid."""
#     from .client import get_info
#
#     info = get_info()
#     result = info.meta_and_asset_ctxs()
#
#     meta = result[0]
#     ctxs = result[1]
#
#     universe = meta.get('universe', [])
#     rates = {}
#     for asset_meta, ctx in zip(universe, ctxs):
#         symbol = asset_meta.get('name', '')
#         if symbol in ARB_SYMBOLS:
#             try:
#                 rate = float(ctx.get('funding', 0))
#                 rates[symbol] = rate
#             except (ValueError, TypeError):
#                 logger.warning("HL: could not parse funding for %s: %s", symbol, ctx.get('funding'))
#
#     return rates


def _fetch_lighter_funding() -> dict:
    """Fetch current funding rates from Lighter.xyz via FundingApi.

    Returns rates keyed by exchange, e.g. {'lighter': {'BTC': 0.005, ...}, 'hyperliquid': {...}}.
    The FundingApi returns rates for lighter + external exchanges (binance, bybit, hyperliquid).
    """
    import asyncio
    import json
    import lighter as lighter_sdk
    from ..lighter.client import _API_CONFIGURATION, _run

    all_rates = {}
    try:
        async def _fetch():
            api = lighter_sdk.ApiClient(configuration=_API_CONFIGURATION)
            try:
                funding_api = lighter_sdk.FundingApi(api)
                resp = await funding_api.funding_rates_without_preload_content()
                body = await resp.read()
                return json.loads(body.decode())
            finally:
                await api.close()

        data = _run(_fetch())
        for entry in data.get('funding_rates', []):
            exchange = entry.get('exchange', '')
            symbol = entry.get('symbol', '')
            if symbol in ARB_SYMBOLS:
                rate = entry.get('rate')
                if rate is not None:
                    all_rates.setdefault(exchange, {})[symbol] = float(rate)

    except Exception as e:
        logger.error("Failed to fetch Lighter funding rates: %s", e)

    return all_rates


# ── Arb Scanner ───────────────────────────────────────────

def scan_funding_arb() -> dict:
    """Compare funding rates across venues and identify arb opportunities.

    Returns a dict with scan metadata and a list of opportunities.
    The result is also stored in Redis for the API endpoint.
    """
    scan_time = datetime.now(timezone.utc).isoformat()
    opportunities = []
    all_rates = {}

    # Fetch all funding rates from Lighter FundingApi (includes lighter + external exchanges)
    all_exchange_rates = {}

    try:
        all_exchange_rates = _fetch_lighter_funding()
        for exchange, rates in all_exchange_rates.items():
            logger.info("Funding scan — %s rates: %s", exchange, rates)
    except Exception as e:
        logger.error("Funding scan — fetch failed: %s", e)

    lighter_rates = all_exchange_rates.get('lighter', {})
    # Use Hyperliquid rates from same API (no separate SDK call needed)
    hl_rates = all_exchange_rates.get('hyperliquid', {})

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
