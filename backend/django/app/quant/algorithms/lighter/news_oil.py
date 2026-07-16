"""
WTI Oil-specific news sentiment — directional signal generator.

Unlike the generic news_sentiment.py (which only adjusts sizing), this module
generates DIRECTIONAL signals: bullish or bearish for oil specifically.

Oil moves on supply disruption narratives:
  - Supply REDUCTION (war, sanctions, Hormuz closure, pipeline attacks) → BULLISH
  - Supply INCREASE (ceasefire, OPEC hike, reserve release, sanction lift) → BEARISH

Architecture:
  _fetch_headlines() → _classify_oil_headlines() → get_oil_signal()
  Returns: direction (1=long, -1=short, 0=neutral), confidence (0-1), headlines matched

Data sources:
  - RSS feeds (Yahoo Finance, CNBC, BBC Business, MarketWatch) — free, no API key
  - Finnhub general news (if FINNHUB_API_KEY set) — free tier: 60 calls/min

Current geopolitical context (Mar 2026):
  - US/Israel-Iran war active (Day 21+)
  - Strait of Hormuz effectively closed (8M bpd offline)
  - WTI range: $92-$113 (extreme vol, 48% monthly swing)
  - OPEC+ resuming modest output increases (+206k bpd April)
  - IEA coordinated 400M barrel strategic reserve release
  - Trump signaling potential ceasefire ("winding down")
"""
import logging
import os
import time
from datetime import datetime, timezone
from django.core.cache import cache

logger = logging.getLogger('app.lighter')

# ── Cache ──────────────────────────────────────────────────
OIL_SIGNAL_CACHE_KEY = 'lighter:oil_news_signal'
OIL_SIGNAL_CACHE_TTL = 300  # 5 minutes
OIL_HEADLINES_CACHE_KEY = 'lighter:oil_headlines'

# ── RSS Feeds (free, no API key) ───────────────────────────
RSS_FEEDS = [
    'https://feeds.finance.yahoo.com/rss/2.0/headline?s=CL=F&region=US&lang=en-US',  # WTI futures
    'https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US',  # S&P (macro)
    'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114',  # CNBC top
    'https://feeds.marketwatch.com/marketwatch/topstories',
    'https://feeds.bbci.co.uk/news/business/rss.xml',
    'https://feeds.bbci.co.uk/news/world/middle_east/rss.xml',  # Middle East specific
]

FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY', '')
FEED_TIMEOUT = 10

# ── Oil-specific keyword classification ────────────────────
# Keywords are scored: positive = bullish for oil, negative = bearish for oil
# Score magnitude = conviction strength (1-3)

OIL_BULLISH_KEYWORDS = {
    # Supply disruption (strongest bullish signal)
    'hormuz closed': 3, 'hormuz blocked': 3, 'hormuz disruption': 3,
    'strait of hormuz': 2, 'shipping disruption': 2,
    'pipeline attack': 3, 'pipeline explosion': 3, 'pipeline sabotage': 3,
    'refinery attack': 3, 'refinery explosion': 2, 'refinery fire': 2,
    'oil facility attack': 3, 'energy infrastructure attack': 3,
    'iran strikes': 2, 'iran missile': 2, 'iran attacks': 2, 'iran retaliates': 2,
    'gulf strikes': 2, 'gulf attack': 2,
    'aramco attack': 3, 'aramco strike': 3,

    # War escalation
    'war escalat': 3, 'military escalation': 2,
    'ground invasion iran': 3, 'troops deploy': 2,
    'nuclear facility': 2, 'dimona': 2,
    'all-out war': 3,

    # Supply cuts
    'opec cut': 2, 'production cut': 2, 'output cut': 2,
    'oil embargo': 3, 'embargo': 2,
    'oil sanctions': 2, 'new sanctions iran': 2, 'sanctions tighten': 2,
    'supply shortage': 2, 'supply disruption': 2, 'supply crisis': 3,
    'inventory decline': 1, 'crude inventory drop': 1, 'stockpile decline': 1,
    'shut-in production': 2, 'production offline': 2,

    # Demand strength
    'demand surge': 1, 'oil demand': 1, 'economic recovery': 1,
}

OIL_BEARISH_KEYWORDS = {
    # Ceasefire / de-escalation (strongest bearish signal)
    'ceasefire': 3, 'peace deal': 3, 'peace talks': 2, 'peace agreement': 3,
    'winding down': 3, 'wind down': 3, 'de-escalation': 2, 'de-escalate': 2,
    'truce': 3, 'armistice': 3, 'diplomatic solution': 2,
    'war ends': 3, 'conflict resolution': 2,
    'troops withdraw': 2, 'pullback': 2,
    'hormuz reopen': 3, 'shipping resume': 2,

    # Supply increase
    'opec increase': 2, 'production increase': 2, 'output increase': 2,
    'opec hike': 2, 'output hike': 2,
    'strategic reserve release': 2, 'spr release': 2, 'reserve release': 2,
    'sanctions lifted': 2, 'sanctions eased': 2, 'sanctions relief': 2,
    'sanctions waiver': 2, 'sanctions exemption': 1,
    'oil supply increase': 2, 'supply surplus': 2, 'glut': 2,
    'inventory build': 1, 'crude inventory rise': 1, 'stockpile increase': 1,

    # Demand weakness
    'recession': 2, 'demand destruction': 2, 'demand decline': 1,
    'economic slowdown': 1, 'gdp contraction': 1,
    'oil price crash': 2, 'crude collapse': 2,
}


def _fetch_headlines() -> list[str]:
    """Fetch headlines from RSS feeds + optional Finnhub."""
    headlines = []

    # RSS feeds (always available)
    try:
        import feedparser
        for feed_url in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:15]:
                    title = entry.get('title', '').lower()
                    summary = entry.get('summary', '').lower()
                    blob = f"{title} {summary}".strip()
                    if blob:
                        headlines.append(blob)
            except Exception:
                continue
    except ImportError:
        logger.debug("feedparser not installed")

    # Finnhub general news (if API key set)
    if FINNHUB_API_KEY:
        try:
            import requests
            resp = requests.get(
                'https://finnhub.io/api/v1/news',
                params={'category': 'general', 'token': FINNHUB_API_KEY},
                timeout=FEED_TIMEOUT,
            )
            if resp.status_code == 200:
                for item in resp.json()[:20]:
                    headline = item.get('headline', '').lower()
                    summary = item.get('summary', '').lower()
                    blob = f"{headline} {summary}".strip()
                    if blob:
                        headlines.append(blob)
        except Exception as e:
            logger.debug("Finnhub news fetch failed: %s", e)

    return headlines


def _classify_oil_headlines(headlines: list[str]) -> dict:
    """Classify headlines as bullish or bearish for oil.

    Returns:
        bullish_score: total bullish conviction points
        bearish_score: total bearish conviction points
        bullish_headlines: list of (headline_snippet, keyword, score)
        bearish_headlines: list of (headline_snippet, keyword, score)
    """
    combined = ' '.join(headlines)
    bullish_score = 0
    bearish_score = 0
    bullish_hits = []
    bearish_hits = []

    for kw, score in OIL_BULLISH_KEYWORDS.items():
        if kw in combined:
            bullish_score += score
            # Find the headline that matched
            for h in headlines:
                if kw in h:
                    bullish_hits.append((h[:80], kw, score))
                    break

    for kw, score in OIL_BEARISH_KEYWORDS.items():
        if kw in combined:
            bearish_score += score
            for h in headlines:
                if kw in h:
                    bearish_hits.append((h[:80], kw, score))
                    break

    return {
        'bullish_score': bullish_score,
        'bearish_score': bearish_score,
        'bullish_hits': bullish_hits,
        'bearish_hits': bearish_hits,
    }


def get_oil_signal() -> dict:
    """Get directional oil signal from news headlines.

    Returns:
        direction: 1 (long/bullish), -1 (short/bearish), 0 (neutral/skip)
        confidence: 0.0-1.0 (how strong the signal is)
        regime: 'WAR_SUPPLY_CRISIS' | 'CEASEFIRE_IMMINENT' | 'NORMAL'
        bullish_score: raw bullish conviction points
        bearish_score: raw bearish conviction points
        headlines_checked: total headlines analyzed
        top_signals: list of matched headlines with direction
        reason: human-readable explanation
    """
    cached = cache.get(OIL_SIGNAL_CACHE_KEY)
    if cached:
        return cached

    headlines = _fetch_headlines()
    if not headlines:
        result = {
            'direction': 0, 'confidence': 0.0, 'regime': 'NO_DATA',
            'bullish_score': 0, 'bearish_score': 0,
            'headlines_checked': 0, 'top_signals': [], 'reason': 'no headlines available',
        }
        cache.set(OIL_SIGNAL_CACHE_KEY, result, timeout=60)
        return result

    classification = _classify_oil_headlines(headlines)
    bull = classification['bullish_score']
    bear = classification['bearish_score']
    total = bull + bear

    # Determine direction and confidence
    if total == 0:
        direction = 0
        confidence = 0.0
        regime = 'NORMAL'
        reason = 'no oil-relevant headlines detected'
    else:
        net = bull - bear
        # Confidence: how lopsided is the signal? (0 = balanced, 1 = all one way)
        confidence = abs(net) / total
        confidence = min(confidence, 1.0)

        if net >= 3 and confidence >= 0.3:
            direction = 1  # LONG oil
            regime = 'WAR_SUPPLY_CRISIS' if bull >= 6 else 'SUPPLY_TIGHT'
            reason = f"bullish {bull} vs bearish {bear}: supply disruption dominant"
        elif net <= -3 and confidence >= 0.3:
            direction = -1  # SHORT oil
            regime = 'CEASEFIRE_IMMINENT' if bear >= 6 else 'SUPPLY_EASING'
            reason = f"bearish {bear} vs bullish {bull}: de-escalation / supply increase"
        else:
            direction = 0
            confidence = 0.0
            regime = 'MIXED'
            reason = f"mixed signals: bullish {bull} vs bearish {bear} (net {net})"

    # Compile top signals for logging
    top_signals = []
    for h, kw, s in classification['bullish_hits'][:5]:
        top_signals.append({'headline': h, 'keyword': kw, 'direction': 'BULLISH', 'score': s})
    for h, kw, s in classification['bearish_hits'][:5]:
        top_signals.append({'headline': h, 'keyword': kw, 'direction': 'BEARISH', 'score': s})

    result = {
        'direction': direction,
        'confidence': confidence,
        'regime': regime,
        'bullish_score': bull,
        'bearish_score': bear,
        'headlines_checked': len(headlines),
        'top_signals': top_signals,
        'reason': reason,
    }

    if direction != 0:
        logger.info("OIL NEWS: %s direction=%d conf=%.2f bull=%d bear=%d — %s",
                     regime, direction, confidence, bull, bear, reason)

    # Cache headlines separately for dashboard display
    cache.set(OIL_HEADLINES_CACHE_KEY, {
        'headlines': [h[:120] for h in headlines[:20]],
        'fetched_at': datetime.now(timezone.utc).isoformat(),
    }, timeout=OIL_SIGNAL_CACHE_TTL)

    cache.set(OIL_SIGNAL_CACHE_KEY, result, timeout=OIL_SIGNAL_CACHE_TTL)
    return result
