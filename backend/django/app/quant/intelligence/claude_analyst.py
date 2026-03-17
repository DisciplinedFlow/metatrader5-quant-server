"""Claude API-powered trading intelligence.

Uses Claude Haiku for:
1. Causal news analysis -- "Iran sanctions -> oil spike -> gold rally" not just keyword matching
2. Trade reasoning -- explain WHY a setup is good/bad based on context
3. Daily performance reports -- auto-generated analysis
4. Market regime classification -- LLM reads price action description and classifies

Cost: ~$0.001 per analysis call. Budget: $30/month = 30,000 calls.
"""
import json
import logging
import os

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger('quant')

# Use env var for API key
ANTHROPIC_API_KEY = getattr(settings, 'ANTHROPIC_API_KEY', None) or os.getenv('ANTHROPIC_API_KEY', '')
MODEL = 'claude-haiku-4-5-20251001'  # Cheapest, fastest

client = None


def _get_client():
    """Lazy-init Anthropic client. Returns None if no API key configured."""
    global client
    if client is None and ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        except ImportError:
            logger.warning("anthropic package not installed -- Claude intelligence disabled")
            return None
    return client


# ---------------------------------------------------------------------------
# 1. News Causal Analysis
# ---------------------------------------------------------------------------

def analyze_news_impact(headlines: list, symbols: list = None) -> dict:
    """Analyze news headlines for trading impact using Claude.

    Instead of keyword matching, Claude reads the headlines and returns:
    - Per-symbol impact (bullish/bearish/neutral with confidence)
    - Causal chains (event -> effect -> market impact)
    - Risk level assessment
    - Recommended position adjustments

    Cached for 10 minutes.
    """
    cache_key = f'claude:news_impact:{hash(str(headlines[:5]))}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    c = _get_client()
    if not c:
        return {'risk_level': 'NORMAL', 'impacts': {}, 'reasoning': 'Claude API not configured'}

    symbols = symbols or ['XAGUSD', 'XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'USOUSD']

    prompt = f"""You are a forex/commodities trading analyst. Analyze these headlines and return JSON only.

Headlines:
{chr(10).join(f'- {h}' for h in headlines[:15])}

Symbols to analyze: {', '.join(symbols)}

Return this exact JSON structure:
{{
    "risk_level": "NORMAL" | "ELEVATED" | "EXTREME",
    "overall_sentiment": "RISK_ON" | "RISK_OFF" | "MIXED",
    "impacts": {{
        "XAGUSD": {{"direction": "BULLISH"|"BEARISH"|"NEUTRAL", "confidence": 0.0-1.0, "reason": "short reason"}},
        ... (for each symbol)
    }},
    "causal_chains": [
        "Iran tensions -> oil supply fears -> crude spike -> USD strength -> gold bid as safe haven",
        ...
    ],
    "size_multiplier": 0.3-1.5,
    "key_events": ["event1", "event2"]
}}

Be concise. JSON only, no markdown."""

    try:
        response = c.messages.create(
            model=MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()

        # Log token usage for cost monitoring
        usage = getattr(response, 'usage', None)
        if usage:
            logger.info(
                f"Claude news tokens: in={usage.input_tokens} out={usage.output_tokens} "
                f"(~${(usage.input_tokens * 0.25 + usage.output_tokens * 1.25) / 1_000_000:.4f})"
            )

        # Strip markdown code fences (```json ... ```)
        text = text.strip()
        if text.startswith('```'):
            # Remove opening fence (```json or ``` or ```JSON)
            first_newline = text.find('\n')
            text = text[first_newline + 1:] if first_newline > 0 else text[3:]
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()

        # Extract JSON block
        start = text.find('{')
        end = text.rfind('}') + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON found in response: {text[:200]}")
        json_str = text[start:end]

        # Parse with json5 (handles trailing commas, comments, etc)
        try:
            import pyjson5
            result = pyjson5.loads(json_str)
        except ImportError:
            import re
            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
            result = json.loads(json_str)

        cache.set(cache_key, result, timeout=600)
        logger.info(f"Claude news analysis: {result.get('risk_level')} | {result.get('overall_sentiment')}")
        return result
    except Exception as e:
        logger.warning(f"Claude news analysis failed: {e}")
        return {'risk_level': 'NORMAL', 'impacts': {}, 'reasoning': f'Error: {e}'}


# ---------------------------------------------------------------------------
# 2. Trade Setup Reasoning
# ---------------------------------------------------------------------------

def evaluate_trade_setup(symbol, direction, mtf_context, confluence_score, news_context=None) -> dict:
    """Ask Claude to evaluate a potential trade setup.

    Returns confidence score and reasoning.
    Cached per (symbol, direction) for 5 minutes.
    """
    cache_key = f'claude:setup:{symbol}:{direction}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    c = _get_client()
    if not c:
        return {'confidence': 0.5, 'reasoning': 'Claude not configured', 'should_trade': True}

    prompt = f"""Evaluate this forex trade setup. Return JSON only.

Symbol: {symbol} {direction}
HTF Trend: {mtf_context.get('htf_trend', 'UNKNOWN')}
HTF Phase: {mtf_context.get('htf_phase', 'UNKNOWN')}
LTF Trend: {mtf_context.get('ltf_trend', 'UNKNOWN')}
Alignment: {mtf_context.get('alignment', 'UNKNOWN')} (score: {mtf_context.get('alignment_score', 0)}/10)
Confluence: {confluence_score}/14
News: {news_context.get('risk_level', 'NORMAL') if news_context else 'NORMAL'}

Return:
{{
    "confidence": 0.0-1.0,
    "should_trade": true/false,
    "reasoning": "2 sentence max",
    "suggested_adjustments": "any SL/TP or sizing suggestions"
}}"""

    try:
        response = c.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()

        # Log token usage
        usage = getattr(response, 'usage', None)
        if usage:
            logger.debug(
                f"Claude setup tokens: in={usage.input_tokens} out={usage.output_tokens} "
                f"(~${(usage.input_tokens * 0.25 + usage.output_tokens * 1.25) / 1_000_000:.4f})"
            )

        start = text.find('{')
        end = text.rfind('}') + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON found in response: {text[:200]}")
        result = json.loads(text[start:end])
        cache.set(cache_key, result, timeout=300)
        return result
    except Exception as e:
        logger.debug(f"Claude setup eval failed: {e}")
        return {'confidence': 0.5, 'reasoning': f'Error: {e}', 'should_trade': True}


# ---------------------------------------------------------------------------
# 3. Daily Performance Report
# ---------------------------------------------------------------------------

def generate_daily_report(trades_today: list, overall_stats: dict) -> str:
    """Generate a daily trading performance report.

    Called once per day by a Celery task.
    """
    c = _get_client()
    if not c:
        return 'Claude API not configured'

    trade_summary = []
    for t in trades_today[:20]:
        trade_summary.append(
            f"{t['symbol']} {t['direction']} pnl=${t['pnl']:+.2f} strategy={t['strategy']}"
        )

    prompt = f"""You are a quant trading analyst. Write a brief daily report.

Today's trades:
{chr(10).join(trade_summary) if trade_summary else '(no trades today)'}

Overall stats:
- Win rate: {overall_stats.get('win_rate', 0):.1%}
- Total PnL: ${overall_stats.get('total_pnl', 0):.2f}
- Best: {overall_stats.get('best_strategy', 'N/A')}
- Worst: {overall_stats.get('worst_strategy', 'N/A')}
- R:R ratio: {overall_stats.get('rr_ratio', 0):.2f}

Write a 5-bullet report:
1. Performance summary
2. What worked
3. What didn't
4. Key observation
5. Recommendation for tomorrow

Be direct. No fluff."""

    try:
        response = c.messages.create(
            model=MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )

        # Log token usage
        usage = getattr(response, 'usage', None)
        if usage:
            logger.info(
                f"Claude report tokens: in={usage.input_tokens} out={usage.output_tokens} "
                f"(~${(usage.input_tokens * 0.25 + usage.output_tokens * 1.25) / 1_000_000:.4f})"
            )

        return response.content[0].text.strip()
    except Exception as e:
        return f'Report generation failed: {e}'


# ---------------------------------------------------------------------------
# 4. Smart News Sentiment (Claude + keyword fallback)
# ---------------------------------------------------------------------------

def get_smart_news_sentiment(headlines: list = None) -> dict:
    """Get news sentiment -- tries Claude first, falls back to keyword matching.

    Claude provides per-symbol directional bias and causal reasoning.
    Keyword matching provides generic risk level.
    """
    # Try Claude first
    if headlines and ANTHROPIC_API_KEY:
        claude_result = analyze_news_impact(headlines)
        if claude_result.get('impacts'):
            return claude_result

    # Fallback to keyword matching
    from app.quant.indicators.news_sentiment import get_market_risk_level
    return get_market_risk_level()
