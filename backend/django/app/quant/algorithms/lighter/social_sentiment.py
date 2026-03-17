"""
Social sentiment analysis -- real-time Twitter/social data via Santiment API.

Replaces slow RSS feeds with real-time social signals.
Research shows Twitter predicts crypto moves BEFORE mainstream media.
Negative sentiment causes immediate volatility; positive has delayed effect.

Uses Santiment's free tier via sanpy Python client.
Falls back to existing RSS news_sentiment if Santiment unavailable.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from django.core.cache import cache

logger = logging.getLogger('app.lighter')

# ── Santiment API key (free tier: 300 API calls/day) ─────
SANTIMENT_API_KEY = os.getenv('SANTIMENT_API_KEY', '')

# ── Cache settings ───────────────────────────────────────
SOCIAL_CACHE_TTL = 300  # 5 minutes — social data doesn't change every second
SOCIAL_CACHE_PREFIX = 'lighter:social:'

# ── Lighter symbol -> Santiment slug mapping ─────────────
# Only crypto assets have social sentiment on Santiment.
# Forex, metals, stocks are skipped (no crypto social sentiment available).
SYMBOL_TO_SLUG = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'SOL': 'solana',
    'DOGE': 'dogecoin',
    'XRP': 'ripple',
    'LINK': 'chainlink',
    'AVAX': 'avalanche-2',
    'NEAR': 'near-protocol',
    'DOT': 'polkadot-new',
    'TON': 'the-open-network',
    'SUI': 'sui',
    'HYPE': 'hyperliquid',
    'BNB': 'binance-coin',
    'AAVE': 'aave',
    'ADA': 'cardano',
    'ARB': 'arbitrum',
    'OP': 'optimism',
}

# Symbols that should skip social sentiment entirely
SKIP_SYMBOLS = {
    'XAU', 'XAG', 'PAXG', 'WTI',
    'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD',
    'TSLA', 'NVDA', 'AAPL', 'AMZN', 'MSFT', 'GOOGL', 'META',
    'SPY', 'QQQ',
}


def get_social_sentiment(symbol: str) -> dict:
    """Get social sentiment for a Lighter trading symbol.

    Returns dict with:
        sentiment_score: -1.0 to +1.0 (bearish to bullish)
        social_volume: relative social volume (1.0 = normal, >2.0 = viral)
        sentiment_trend: 'RISING', 'FALLING', or 'STABLE'
        risk_multiplier: 0.5-1.0 (for position sizing adjustment)
        source: 'santiment', 'rss_fallback', or 'default'
    """
    # Check cache first
    cache_key = f'{SOCIAL_CACHE_PREFIX}{symbol}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Skip non-crypto symbols
    if symbol in SKIP_SYMBOLS:
        result = _default_result('skip_non_crypto')
        cache.set(cache_key, result, timeout=SOCIAL_CACHE_TTL)
        return result

    slug = SYMBOL_TO_SLUG.get(symbol)
    if not slug:
        result = _default_result('unknown_symbol')
        cache.set(cache_key, result, timeout=SOCIAL_CACHE_TTL)
        return result

    # Try Santiment first
    result = _fetch_santiment(symbol, slug)
    if result is not None:
        cache.set(cache_key, result, timeout=SOCIAL_CACHE_TTL)
        return result

    # Fall back to RSS news sentiment
    result = _fallback_rss()
    cache.set(cache_key, result, timeout=SOCIAL_CACHE_TTL)
    return result


def _default_result(reason: str = 'default') -> dict:
    """Neutral default when sentiment data is unavailable."""
    return {
        'sentiment_score': 0.0,
        'social_volume': 1.0,
        'sentiment_trend': 'STABLE',
        'risk_multiplier': 1.0,
        'source': reason,
    }


def _fetch_santiment(symbol: str, slug: str) -> dict | None:
    """Fetch social sentiment from Santiment API via sanpy client.

    Returns None if Santiment is unavailable (triggers RSS fallback).
    """
    try:
        import san
    except ImportError:
        logger.debug(
            "Social sentiment: sanpy not installed. "
            "Install with: pip install sanpy"
        )
        return None

    # Set API key if available (free tier works without key but has lower limits)
    if SANTIMENT_API_KEY:
        san.ApiConfig.api_key = SANTIMENT_API_KEY

    now = datetime.now(timezone.utc)
    # Look back 24h for trend detection, last 4h for current reading
    from_date_24h = (now - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
    from_date_4h = (now - timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
    to_date = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    try:
        # ── 1. Sentiment balance (positive = bullish, negative = bearish) ──
        sentiment_df = san.get(
            'sentiment_balance',
            slug=slug,
            from_date=from_date_24h,
            to_date=to_date,
            interval='1h',
        )

        # ── 2. Social volume (how much people are talking about it) ──
        volume_df = san.get(
            'social_volume_total',
            slug=slug,
            from_date=from_date_24h,
            to_date=to_date,
            interval='1h',
        )

        # ── 3. Social dominance (% of all crypto social conversation) ──
        dominance_df = san.get(
            'social_dominance_total',
            slug=slug,
            from_date=from_date_4h,
            to_date=to_date,
            interval='1h',
        )

    except Exception as e:
        logger.debug("Social sentiment: Santiment API error for %s: %s", symbol, e)
        return None

    # ── Parse sentiment balance ──
    sentiment_score = 0.0
    sentiment_trend = 'STABLE'
    if sentiment_df is not None and not sentiment_df.empty:
        col = sentiment_df.columns[0] if len(sentiment_df.columns) > 0 else None
        if col is not None:
            values = sentiment_df[col].dropna()
            if len(values) >= 2:
                current_sentiment = float(values.iloc[-1])
                # Normalize to -1..+1 range. Santiment sentiment_balance
                # typically ranges from -20 to +20, with extremes at +-50.
                sentiment_score = max(-1.0, min(1.0, current_sentiment / 20.0))

                # Trend: compare last 4h average to prior 20h average
                recent = values.iloc[-4:].mean() if len(values) >= 4 else current_sentiment
                earlier = values.iloc[:-4].mean() if len(values) > 4 else current_sentiment
                diff = recent - earlier
                if diff > 2.0:
                    sentiment_trend = 'RISING'
                elif diff < -2.0:
                    sentiment_trend = 'FALLING'
                else:
                    sentiment_trend = 'STABLE'

    # ── Parse social volume ──
    social_volume = 1.0
    if volume_df is not None and not volume_df.empty:
        col = volume_df.columns[0] if len(volume_df.columns) > 0 else None
        if col is not None:
            values = volume_df[col].dropna()
            if len(values) >= 5:
                # Relative volume: current 4h avg vs prior 20h avg
                recent_vol = values.iloc[-4:].mean() if len(values) >= 4 else float(values.iloc[-1])
                baseline_vol = values.iloc[:-4].mean() if len(values) > 4 else recent_vol
                if baseline_vol > 0:
                    social_volume = recent_vol / baseline_vol
                else:
                    social_volume = 1.0

    # ── Parse social dominance (optional boost) ──
    dominance_boost = 0.0
    if dominance_df is not None and not dominance_df.empty:
        col = dominance_df.columns[0] if len(dominance_df.columns) > 0 else None
        if col is not None:
            values = dominance_df[col].dropna()
            if len(values) >= 1:
                current_dom = float(values.iloc[-1])
                # If an asset is dominating >20% of social conversation, it's viral
                if current_dom > 20.0:
                    dominance_boost = 0.5

    # Adjust social volume with dominance boost
    social_volume = social_volume + dominance_boost

    # ── Calculate risk multiplier ──
    risk_multiplier = _calculate_risk_multiplier(sentiment_score, social_volume, sentiment_trend)

    result = {
        'sentiment_score': round(sentiment_score, 3),
        'social_volume': round(social_volume, 2),
        'sentiment_trend': sentiment_trend,
        'risk_multiplier': round(risk_multiplier, 2),
        'source': 'santiment',
    }

    logger.debug(
        "Social sentiment %s: score=%.2f vol=%.1fx trend=%s risk_mult=%.2f",
        symbol, sentiment_score, social_volume, sentiment_trend, risk_multiplier,
    )
    return result


def _calculate_risk_multiplier(
    sentiment_score: float,
    social_volume: float,
    sentiment_trend: str,
) -> float:
    """Calculate position sizing risk multiplier from social signals.

    Returns 0.5-1.0:
    - 1.0 = normal conditions, no adjustment needed
    - 0.75 = elevated social activity OR strong negative sentiment
    - 0.5 = viral + strongly negative = maximum caution

    Logic:
    - Negative sentiment causes immediate volatility (reduce size)
    - Very high social volume = potential for erratic moves (reduce size)
    - Positive sentiment is slower-acting (no size boost, just normal)
    """
    multiplier = 1.0

    # Strong negative sentiment -> reduce size
    if sentiment_score < -0.5:
        multiplier *= 0.75
    elif sentiment_score < -0.3:
        multiplier *= 0.85

    # Viral social volume (>2x normal) -> reduce size (unpredictable)
    if social_volume > 3.0:
        multiplier *= 0.7
    elif social_volume > 2.0:
        multiplier *= 0.85

    # Rapidly falling sentiment is a warning sign
    if sentiment_trend == 'FALLING' and sentiment_score < 0:
        multiplier *= 0.85

    # Clamp to 0.5-1.0 range
    return max(0.5, min(1.0, multiplier))


def _fallback_rss() -> dict:
    """Fall back to existing RSS news_sentiment module.

    Maps the RSS risk level to our social sentiment format so the caller
    gets a consistent interface regardless of data source.
    """
    try:
        from app.quant.indicators.news_sentiment import get_market_risk_level
        risk = get_market_risk_level()

        risk_level = risk.get('risk_level', 'NORMAL')
        size_mult = risk.get('size_multiplier', 1.0)

        # Map RSS risk levels to sentiment-like values
        if risk_level == 'EXTREME':
            sentiment_score = -0.7
            sentiment_trend = 'FALLING'
        elif risk_level == 'ELEVATED':
            sentiment_score = -0.3
            sentiment_trend = 'FALLING'
        else:
            sentiment_score = 0.0
            sentiment_trend = 'STABLE'

        return {
            'sentiment_score': sentiment_score,
            'social_volume': 1.0,  # RSS doesn't measure social volume
            'sentiment_trend': sentiment_trend,
            'risk_multiplier': max(0.5, size_mult),
            'source': 'rss_fallback',
        }
    except Exception as e:
        logger.debug("Social sentiment: RSS fallback also failed: %s", e)
        return _default_result('all_sources_failed')
