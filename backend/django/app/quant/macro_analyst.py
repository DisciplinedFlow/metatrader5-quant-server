"""
Macro Market Analyst — Uses Claude to analyze forex news and geopolitical context.

Runs every 30 minutes via Celery Beat. Produces per-currency sentiment and risk
assessment that the entry algorithm consults before opening positions.

Think of this as the "morning briefing" a human trader reads before trading.
"""

import json
import logging
import os
from datetime import datetime

from django.core.cache import cache

logger = logging.getLogger('macro_analyst')

MACRO_MODEL = os.getenv('MACRO_ANALYST_MODEL', 'claude-haiku-4-5-20251001')
MACRO_MAX_TOKENS = 2048
CACHE_KEY = 'macro:analysis'
CACHE_TTL = 60 * 30  # 30 minutes


SYSTEM_PROMPT = """You are a senior forex macro analyst and trader with 20+ years of experience.
You analyze news, geopolitical events, and economic data to produce actionable trading intelligence.

You think in CAUSE → EFFECT chains:
- "Strait of Hormuz tensions → oil supply risk → crude rallies → CAD strengthens (oil exporter) → USDCAD bearish"
- "Fed hawkish surprise → USD strength → EURUSD bearish, USDJPY bullish"
- "War escalation in Middle East → risk-off → JPY and CHF strengthen as safe havens"

You understand:
- Commodity-currency links (CAD=oil, AUD=iron ore/China, NZD=dairy)
- Safe haven flows (JPY, CHF, USD in extreme risk-off)
- Central bank policy divergence effects
- Liquidity windows (London open, NY open, session overlaps)
- News impact timing (anticipation > reaction > fade)

RESPOND WITH ONLY valid JSON (no markdown, no backticks):
{
    "risk_level": 1-10,
    "avoid_trading": false,
    "avoid_reason": "only if avoid_trading is true",
    "market_narrative": "2-3 sentence macro summary a trader would tell a colleague",
    "currency_bias": {
        "USD": {"direction": "bullish|bearish|neutral", "confidence": 1-10, "reason": "brief"},
        "EUR": {"direction": "...", "confidence": 1-10, "reason": "..."},
        "GBP": {"direction": "...", "confidence": 1-10, "reason": "..."},
        "JPY": {"direction": "...", "confidence": 1-10, "reason": "..."},
        "AUD": {"direction": "...", "confidence": 1-10, "reason": "..."},
        "NZD": {"direction": "...", "confidence": 1-10, "reason": "..."},
        "CAD": {"direction": "...", "confidence": 1-10, "reason": "..."},
        "CHF": {"direction": "...", "confidence": 1-10, "reason": "..."}
    },
    "pair_signals": {
        "EURUSD": {"bias": "long|short|neutral", "strength": 1-10, "reason": "brief"},
        "GBPUSD": {"bias": "...", "strength": 1-10, "reason": "..."},
        "USDJPY": {"bias": "...", "strength": 1-10, "reason": "..."}
    },
    "upcoming_risks": [
        {"event": "name", "time": "when", "impact": "high|medium|low", "currencies_affected": ["USD"], "expected_direction": "brief"}
    ],
    "position_advice": {
        "SYMBOL": "brief advice for any open position"
    }
}

Rules:
- Be decisive. Neutral is valid but don't default to it out of caution.
- Confidence 7+ means you'd trade on this view alone.
- If a major high-impact news event is within 30 minutes, set avoid_trading=true.
- Factor in current day of week and time (Sunday/Monday early = low liquidity).
- If no news is particularly relevant, say so and keep risk_level low."""


def run_macro_analysis():
    """Main entry point — fetch context, analyze with Claude, cache results."""
    api_key = os.getenv('ANTHROPIC_API_KEY', '')
    if not api_key:
        logger.warning("No ANTHROPIC_API_KEY, skipping macro analysis")
        return None

    context = _gather_context()
    if not context.get('news') and not context.get('calendar'):
        logger.info("No news or calendar data available for macro analysis")
        return None

    analysis = _analyze_with_claude(context, api_key)
    if analysis:
        cache.set(CACHE_KEY, analysis, timeout=CACHE_TTL)
        logger.info(
            f"Macro analysis complete: risk={analysis.get('risk_level')}, "
            f"avoid={analysis.get('avoid_trading')}, "
            f"narrative={analysis.get('market_narrative', '')[:80]}"
        )
    return analysis


def _gather_context():
    """Gather news, calendar, and current position data."""
    context = {
        'news': cache.get('market_pulse:news', []),
        'calendar': cache.get('market_pulse:calendar', []),
        'timestamp': datetime.utcnow().isoformat(),
    }

    # Add open positions so Claude can advise on them
    try:
        from app.utils.api.positions import get_positions
        positions = get_positions()
        if positions is not None and not positions.empty:
            context['open_positions'] = [
                {
                    'symbol': row.symbol,
                    'type': 'BUY' if row.type == 0 else 'SELL',
                    'profit': round(row.profit, 2),
                    'entry': round(row.price_open, 5),
                    'current': round(row.price_current, 5),
                }
                for _, row in positions.iterrows()
            ]
    except Exception as e:
        logger.debug(f"Could not fetch positions for macro context: {e}")

    return context


def _analyze_with_claude(context, api_key):
    """Send context to Claude and get structured macro analysis."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        news_text = json.dumps(context.get('news', [])[:10], default=str)
        calendar_text = json.dumps(context.get('calendar', [])[:10], default=str)
        positions_text = json.dumps(context.get('open_positions', []), default=str)

        user_msg = f"""Current time (UTC): {context['timestamp']}

FOREX NEWS (latest headlines):
{news_text}

ECONOMIC CALENDAR (today's events):
{calendar_text}

MY OPEN POSITIONS:
{positions_text}

Analyze the macro environment and produce your trading intelligence report."""

        response = client.messages.create(
            model=MACRO_MODEL,
            max_tokens=MACRO_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        text = response.content[0].text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()

        analysis = json.loads(text)
        analysis['_meta'] = {
            'model': MACRO_MODEL,
            'timestamp': context['timestamp'],
            'input_tokens': response.usage.input_tokens,
            'output_tokens': response.usage.output_tokens,
        }
        return analysis

    except json.JSONDecodeError as e:
        logger.error(f"Macro analysis: invalid JSON from Claude: {e}")
        return None
    except Exception as e:
        logger.error(f"Macro analysis error: {e}")
        return None


# ---------------------------------------------------------------------------
# Public API for entry algorithm
# ---------------------------------------------------------------------------

def get_macro_context():
    """Read cached macro analysis. Returns dict or None."""
    return cache.get(CACHE_KEY)


def check_macro_for_trade(pair, order_type):
    """Check if macro context supports opening a specific trade.

    Returns (allowed: bool, reason: str).
    Called by entry algorithm after signal detection, before order placement.
    """
    analysis = get_macro_context()
    if analysis is None:
        return True, "No macro data"

    # Block all trading if flagged (e.g., imminent high-impact news)
    if analysis.get('avoid_trading', False):
        return False, f"Macro blocked: {analysis.get('avoid_reason', 'high risk')}"

    # Check pair-specific signal from Claude
    pair_signals = analysis.get('pair_signals', {})
    pair_signal = pair_signals.get(pair, {})
    if pair_signal:
        bias = pair_signal.get('bias', 'neutral')
        strength = pair_signal.get('strength', 0)

        # Strong opposing signal = block trade
        if strength >= 7:
            if order_type == 'BUY' and bias == 'short':
                return False, f"Macro: strong SHORT bias on {pair} ({pair_signal.get('reason', '')})"
            if order_type == 'SELL' and bias == 'long':
                return False, f"Macro: strong LONG bias on {pair} ({pair_signal.get('reason', '')})"

    # Check individual currency bias
    base = pair[:3]
    quote = pair[3:]
    currency_bias = analysis.get('currency_bias', {})

    base_info = currency_bias.get(base, {})
    quote_info = currency_bias.get(quote, {})

    if order_type == 'BUY':
        # Buying base, selling quote — bad if base strongly bearish or quote strongly bullish
        if base_info.get('direction') == 'bearish' and base_info.get('confidence', 0) >= 7:
            return False, f"Macro: {base} strongly bearish — avoid BUY {pair}"
        if quote_info.get('direction') == 'bullish' and quote_info.get('confidence', 0) >= 7:
            return False, f"Macro: {quote} strongly bullish — avoid BUY {pair}"
    else:
        if base_info.get('direction') == 'bullish' and base_info.get('confidence', 0) >= 7:
            return False, f"Macro: {base} strongly bullish — avoid SELL {pair}"
        if quote_info.get('direction') == 'bearish' and quote_info.get('confidence', 0) >= 7:
            return False, f"Macro: {quote} strongly bearish — avoid SELL {pair}"

    return True, f"Macro OK (risk={analysis.get('risk_level', '?')})"
