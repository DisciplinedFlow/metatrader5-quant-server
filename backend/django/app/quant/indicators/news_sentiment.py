"""News sentiment indicator — lightweight geopolitical/macro awareness.

Uses free RSS feeds to detect major market events that should modify trading behavior.
NOT a signal generator — modifies position sizing and risk parameters.

Replaces the disabled Claude API macro_analysis task ($10/day) with a $0 alternative.
"""
import logging
import time
from datetime import datetime, timezone
from django.core.cache import cache

logger = logging.getLogger('quant')

# Cache key for news state
NEWS_CACHE_KEY = 'news:market_risk_level'
NEWS_CACHE_TTL = 300  # 5 minutes

# Keywords that indicate high-impact events (geopolitical, central bank, key data)
HIGH_IMPACT_KEYWORDS = [
    'war', 'invasion', 'missile', 'nuclear', 'sanctions', 'embargo',
    'fed rate', 'interest rate decision', 'fomc', 'ecb rate', 'boe rate',
    'nfp', 'non-farm', 'payroll', 'unemployment',
    'cpi', 'inflation', 'ppi',
    'gdp', 'recession',
    'default', 'debt ceiling', 'shutdown',
    'oil embargo', 'opec', 'crude oil',
    'gold', 'safe haven', 'risk off',
    'iran', 'israel', 'china', 'taiwan', 'russia', 'ukraine',
]

MEDIUM_IMPACT_KEYWORDS = [
    'trade war', 'tariff', 'trade deal',
    'pmi', 'manufacturing', 'services',
    'retail sales', 'housing',
    'central bank', 'monetary policy',
    'earnings', 'quarterly results',
]

# Free RSS feeds — no API key required
RSS_FEEDS = [
    'https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US',
    'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114',
    'https://feeds.marketwatch.com/marketwatch/topstories',
    'https://feeds.bbci.co.uk/news/business/rss.xml',
]

# Feed fetch timeout (seconds) — keep short so it never blocks trading
FEED_TIMEOUT = 10


def get_market_risk_level() -> dict:
    """Get current market risk level from cached news analysis.

    Returns dict with:
        risk_level: 'NORMAL', 'ELEVATED', 'EXTREME'
        size_multiplier: 0.5 for EXTREME, 0.75 for ELEVATED, 1.0 for NORMAL
        reason: description of why risk is elevated
        headlines_checked: number of headlines analysed
        matched_keywords: list of matched keywords (max 10)
    """
    cached = cache.get(NEWS_CACHE_KEY)
    if cached:
        return cached

    result = _analyze_news()
    cache.set(NEWS_CACHE_KEY, result, timeout=NEWS_CACHE_TTL)
    return result


def _fetch_headlines() -> list[str]:
    """Fetch headlines from RSS feeds. Returns list of lowercased text blobs."""
    try:
        import feedparser
    except ImportError:
        logger.debug("feedparser not installed — news sentiment disabled")
        return []

    headlines = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:  # Last 10 headlines per feed
                title = entry.get('title', '').lower()
                summary = entry.get('summary', '').lower()
                headlines.append(f"{title} {summary}")
        except Exception as e:
            logger.debug(f"RSS feed error ({feed_url}): {e}")
            continue

    return headlines


def _score_headlines(headlines: list[str]) -> dict:
    """Score a list of headline text blobs for market-moving keywords.

    Returns dict with high_count, medium_count, matched_keywords.
    """
    if not headlines:
        return {'high_count': 0, 'medium_count': 0, 'matched_keywords': []}

    combined_text = ' '.join(headlines)
    high_count = 0
    medium_count = 0
    matched_keywords = []

    for kw in HIGH_IMPACT_KEYWORDS:
        if kw in combined_text:
            high_count += 1
            matched_keywords.append(kw)

    for kw in MEDIUM_IMPACT_KEYWORDS:
        if kw in combined_text:
            medium_count += 1
            matched_keywords.append(kw)

    return {
        'high_count': high_count,
        'medium_count': medium_count,
        'matched_keywords': matched_keywords,
    }


def _analyze_news() -> dict:
    """Fetch and analyze news headlines from free RSS feeds."""
    headlines = _fetch_headlines()

    if not headlines:
        return {
            'risk_level': 'NORMAL',
            'size_multiplier': 1.0,
            'reason': 'no news data available',
            'headlines_checked': 0,
            'matched_keywords': [],
        }

    scores = _score_headlines(headlines)
    high_count = scores['high_count']
    medium_count = scores['medium_count']
    matched_keywords = scores['matched_keywords']

    # Determine risk level
    if high_count >= 3:
        risk_level = 'EXTREME'
        size_mult = 0.5
    elif high_count >= 1 or medium_count >= 3:
        risk_level = 'ELEVATED'
        size_mult = 0.75
    else:
        risk_level = 'NORMAL'
        size_mult = 1.0

    reason = (
        f"{high_count} high-impact, {medium_count} medium-impact keywords: "
        f"{', '.join(matched_keywords[:5])}"
    )

    if risk_level != 'NORMAL':
        logger.info(f"NEWS SENTIMENT: {risk_level} — {reason}")

    return {
        'risk_level': risk_level,
        'size_multiplier': size_mult,
        'reason': reason,
        'headlines_checked': len(headlines),
        'matched_keywords': matched_keywords[:10],
    }
