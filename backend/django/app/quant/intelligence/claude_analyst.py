"""
Claude Haiku — Pattern Analyst for the Neo4j Trading Brain.

Uses claude-haiku-4-5 (cheapest/fastest) for two purposes:
  1. label_trade_pattern()  — called async after every trade closes.
     Haiku reads the OHLCV snapshot + conditions + outcome and writes a
     human-readable label onto the StrategyPattern node.
     Cost: ~$0.001 per call. On 100 trades = $0.10.

  2. weekly_edge_review()   — called once per week via Celery beat.
     Haiku reviews ALL active StrategyPattern nodes, identifies which
     are gaining vs losing edge, suggests deactivation candidates, and
     flags emerging patterns worth promoting to higher confidence.
     Cost: ~$0.05 per run. On 52 weeks = $2.60/year.

€100 API credits at Haiku rates = ~50,000 pattern labels + 500 weekly reviews.
We will never come close to exhausting this budget on the forex bot.

NO real-time news analysis. NO trade gating. Pure async brain enrichment.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger('quant')

MODEL = 'claude-haiku-4-5-20251001'
_MAX_TOKENS_LABEL = 120
_MAX_TOKENS_REVIEW = 1200


def _get_client():
    """Lazy-init Anthropic client."""
    try:
        import anthropic
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            return None
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        logger.warning("anthropic package not installed — Haiku calls disabled")
        return None


# ---------------------------------------------------------------------------
# 1. Pattern label — called after every trade close
# ---------------------------------------------------------------------------

def label_trade_pattern(
    symbol: str,
    direction: str,
    outcome: str,
    pnl_r: float,
    conditions: list,
    session: str,
    htf_bias: str,
    fingerprint: str,
) -> Optional[str]:
    """
    Ask Haiku to write a short human-readable label for a StrategyPattern.
    Returns the label string, or None on failure.

    Example output:
      "XAUUSD bullish FVG bounce at London open with CVD confirmation"
      "GBPUSD bearish session-open absorption — losing pattern"

    Stored on the StrategyPattern node so humans and future Haiku reviews
    can understand what each node actually represents without reading conditions.
    """
    client = _get_client()
    if not client:
        return None

    cond_str = ', '.join(conditions) if conditions else 'no specific conditions'
    outcome_str = f"{outcome} ({pnl_r:+.2f}R)"

    prompt = (
        f"You are labeling a forex trading pattern for a Neo4j knowledge graph.\n"
        f"Write a single concise label (max 12 words) describing this pattern:\n"
        f"Symbol: {symbol} | Direction: {direction} | Session: {session} | "
        f"HTF bias: {htf_bias} | Conditions: {cond_str} | Outcome: {outcome_str}\n\n"
        f"Return ONLY the label string. No explanation. No quotes."
    )

    try:
        response = _get_client().messages.create(
            model=MODEL,
            max_tokens=_MAX_TOKENS_LABEL,
            messages=[{'role': 'user', 'content': prompt}],
        )
        label = response.content[0].text.strip()
        logger.info(f"[haiku] Pattern label for {fingerprint[:40]}: {label}")
        return label
    except Exception as e:
        logger.debug(f"[haiku] label_trade_pattern failed: {e}")
        return None


# ---------------------------------------------------------------------------
# 2. Weekly edge review — batch pattern health scan
# ---------------------------------------------------------------------------

def weekly_edge_review(patterns: list) -> dict:
    """
    Send all active StrategyPattern summaries to Haiku for a weekly review.

    Haiku identifies:
      - Patterns losing edge → suggest deactivation
      - Patterns with strong emerging edge → suggest promotion
      - Observations about what market conditions are dominant

    patterns: list of dicts with keys:
      fingerprint, symbol, direction, win_rate, total, avg_r, source, label

    Returns:
      {'deactivate': [...fingerprints], 'promote': [...fingerprints], 'observations': str}
    """
    client = _get_client()
    if not client:
        return {'deactivate': [], 'promote': [], 'observations': 'Haiku unavailable'}

    if not patterns:
        return {'deactivate': [], 'promote': [], 'observations': 'No patterns to review'}

    rows = []
    for p in patterns:
        rows.append(
            f"{p.get('symbol')}/{p.get('direction', '')[:4]} | "
            f"WR={p.get('win_rate', 0):.0%} n={p.get('total', 0)} | "
            f"E(R)={p.get('avg_r', 0):.2f} | "
            f"src={p.get('source', '?')[:4]} | "
            f"label={p.get('label', 'unlabeled')[:30]} | "
            f"fp={p.get('fingerprint', '')[:40]}"
        )

    table = '\n'.join(rows)
    prompt = (
        f"You are reviewing active forex trading strategy patterns in a Neo4j brain. "
        f"Each row is one pattern node guiding a live bot:\n\n"
        f"{table}\n\n"
        f"Task:\n"
        f"1. List fingerprints to DEACTIVATE (WR < 40% with n >= 8, or clearly broken)\n"
        f"2. List fingerprints to PROMOTE (WR > 70% with n >= 10, strong confirmed edge)\n"
        f"3. 2-3 sentence observation about what's working and what isn't\n\n"
        f"Respond in this EXACT format:\n"
        f"DEACTIVATE: fp1, fp2 (or NONE)\n"
        f"PROMOTE: fp1, fp2 (or NONE)\n"
        f"OBSERVATIONS: your text here"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=_MAX_TOKENS_REVIEW,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = response.content[0].text.strip()
        logger.info(f"[haiku] Weekly edge review:\n{text}")
        return _parse_review(text)
    except Exception as e:
        logger.debug(f"[haiku] weekly_edge_review failed: {e}")
        return {'deactivate': [], 'promote': [], 'observations': f'Error: {e}'}


def _parse_review(text: str) -> dict:
    result = {'deactivate': [], 'promote': [], 'observations': ''}
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('DEACTIVATE:'):
            val = line.replace('DEACTIVATE:', '').strip()
            if val.upper() != 'NONE':
                result['deactivate'] = [v.strip() for v in val.split(',') if v.strip()]
        elif line.startswith('PROMOTE:'):
            val = line.replace('PROMOTE:', '').strip()
            if val.upper() != 'NONE':
                result['promote'] = [v.strip() for v in val.split(',') if v.strip()]
        elif line.startswith('OBSERVATIONS:'):
            result['observations'] = line.replace('OBSERVATIONS:', '').strip()
    return result
