"""
LLM Trade Scorer — On-demand local inference via Ollama.

Calls the fine-tuned trade-brain model (or falls back to base model)
for deeper trade reasoning beyond what XGBoost can capture.

The LLM sees the full feature context and reasons about:
- Pattern matching with historical winners/losers
- Regime + session + direction alignment
- Risk management context (streak, drawdown, duration patterns)
"""
import logging
import requests
import json
from dataclasses import dataclass

logger = logging.getLogger('app.quant.ml.llm')


@dataclass
class LLMScore:
    decision: str  # 'ACCEPT' or 'REJECT'
    confidence: int  # 0-100
    reasoning: str
    model_used: str
    latency_ms: float
    raw_response: str


def format_trade_prompt(features_dict, symbol, order_type):
    """Format features into a human-readable prompt for the LLM."""
    session_names = {0: 'Asian', 1: 'London', 2: 'New York', 3: 'London-NY Overlap'}
    regime_names = {-1: 'TRENDING_DOWN', 0: 'RANGING', 1: 'TRENDING_UP', 2: 'VOLATILE'}

    lines = [
        f"Symbol: {symbol}",
        f"Direction: {order_type}",
    ]

    # Temporal
    session = features_dict.get('session', 0)
    lines.append(f"Session: {session_names.get(int(session), 'Unknown')}")

    # Regime
    regime = features_dict.get('regime_encoded', 0)
    confidence = features_dict.get('regime_confidence', 0)
    lines.append(f"Regime: {regime_names.get(int(regime), 'UNKNOWN')} (confidence={confidence:.2f})")

    hmm = features_dict.get('hmm_regime', -1)
    hmm_labels = {0: 'RANGING', 1: 'TRENDING', 2: 'VOLATILE'}
    lines.append(f"HMM Regime: {hmm_labels.get(int(hmm), 'unavailable')}")

    # Technical indicators
    lines.append(f"RSI: {features_dict.get('rsi', 50):.1f}")
    lines.append(f"ADX: {features_dict.get('adx', 20):.1f}")
    lines.append(f"ATR (normalized): {features_dict.get('atr_normalized', 0):.5f}")
    lines.append(f"Vol Ratio (5/21): {features_dict.get('vol_ratio', 1):.2f}")
    lines.append(f"Spread/ATR: {features_dict.get('spread_atr_ratio', 0):.4f}")

    # SMC features
    lines.append(f"Confluence Score: {features_dict.get('confluence_score', 0)}/11")
    lines.append(f"HTF Bias Aligned: {'Yes' if features_dict.get('htf_bias_aligned', 0) else 'No'}")
    lines.append(f"Kill Zone Weight: {features_dict.get('kill_zone_weight', 0.5):.1f}")
    lines.append(f"FVG Present: {'Yes' if features_dict.get('fvg_present', 0) else 'No'}")
    lines.append(f"Order Block: {'Yes' if features_dict.get('ob_present', 0) else 'No'}")
    lines.append(f"Liquidity Sweep: {'Yes' if features_dict.get('recent_sweep', 0) else 'No'}")

    # Performance context
    streak = features_dict.get('recent_streak', 0)
    streak_str = f"+{streak} wins" if streak > 0 else f"{streak} losses" if streak < 0 else "neutral"
    lines.append(f"Recent Streak: {streak_str}")
    lines.append(f"Symbol WR (last 10): {features_dict.get('symbol_wr_10', 0.5):.0%}")
    lines.append(f"Drawdown: {features_dict.get('drawdown_pct', 0):.1f}%")

    # New performance analytics features
    lines.append(f"Direction WR (last 10 {order_type}s): {features_dict.get('direction_wr_10', 0.5):.0%}")
    lines.append(f"Duration Ratio (loser/winner): {features_dict.get('duration_ratio', 1):.2f}")
    lines.append(f"MFE Capture: {features_dict.get('mfe_capture_pct', 0):.0%}")
    lines.append(f"Edge Ratio (MFE/MAE): {features_dict.get('edge_ratio', 1):.2f}")
    lines.append(f"P(Win|prev Win): {features_dict.get('p_win_after_win', 0.5):.0%}")
    lines.append(f"P(Win|prev Loss): {features_dict.get('p_win_after_loss', 0.5):.0%}")

    return "\n".join(lines)


def score_with_llm(features_dict, symbol, order_type):
    """Score a trade setup using the local LLM via Ollama.

    Returns LLMScore or None if LLM is unavailable/disabled.
    Falls back to base model if fine-tuned model doesn't exist.
    """
    from . import llm_config

    if not llm_config.LLM_ENABLED:
        return None

    import time
    start = time.time()

    prompt = format_trade_prompt(features_dict, symbol, order_type)

    # Try fine-tuned model first, fall back to base
    model = llm_config.OLLAMA_TRADE_MODEL + ':latest'

    try:
        response = _call_ollama(
            model=model,
            prompt=prompt,
            system=llm_config.TRADE_SYSTEM_PROMPT,
            host=llm_config.OLLAMA_HOST,
            temperature=llm_config.LLM_SCORE_TEMPERATURE,
            max_tokens=llm_config.LLM_SCORE_MAX_TOKENS,
            timeout=llm_config.OLLAMA_TIMEOUT,
        )
    except Exception as e:
        logger.debug(f"Fine-tuned model unavailable ({e}), trying base model")
        try:
            model = llm_config.OLLAMA_BASE_MODEL
            response = _call_ollama(
                model=model,
                prompt=prompt,
                system=llm_config.TRADE_SYSTEM_PROMPT,
                host=llm_config.OLLAMA_HOST,
                temperature=llm_config.LLM_SCORE_TEMPERATURE,
                max_tokens=llm_config.LLM_SCORE_MAX_TOKENS,
                timeout=llm_config.OLLAMA_TIMEOUT,
            )
        except Exception as e2:
            logger.warning(f"Ollama unavailable: {e2}")
            return None

    latency = (time.time() - start) * 1000

    # Parse response
    score = _parse_llm_response(response, model, latency)

    logger.info(
        f"LLM score: {score.decision} ({score.confidence}%) "
        f"model={score.model_used} latency={score.latency_ms:.0f}ms"
    )

    return score


def _call_ollama(model, prompt, system, host, temperature, max_tokens, timeout):
    """Call Ollama generate API."""
    resp = requests.post(
        f"{host}/api/generate",
        json={
            'model': model,
            'prompt': prompt,
            'system': system,
            'stream': False,
            'options': {
                'temperature': temperature,
                'num_predict': max_tokens,
            },
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get('response', '')


def _parse_llm_response(text, model_used, latency_ms):
    """Parse LLM response into structured LLMScore."""
    text = text.strip()

    # Extract decision
    decision = 'REJECT'  # default safe
    if 'DECISION: ACCEPT' in text.upper() or 'DECISION:ACCEPT' in text.upper():
        decision = 'ACCEPT'
    elif 'ACCEPT' in text.upper().split('\n')[0]:
        decision = 'ACCEPT'

    # Extract confidence
    confidence = 50
    for line in text.split('\n'):
        line_upper = line.upper().strip()
        if line_upper.startswith('CONFIDENCE:'):
            try:
                val = ''.join(c for c in line_upper.split(':')[1] if c.isdigit())
                if val:
                    confidence = min(100, max(0, int(val)))
            except (ValueError, IndexError):
                pass

    # Extract reasoning
    reasoning = ''
    for line in text.split('\n'):
        if line.upper().strip().startswith('REASONING:'):
            reasoning = line.split(':', 1)[1].strip()
            break
    if not reasoning:
        # Take the last non-empty line as reasoning
        for line in reversed(text.split('\n')):
            if line.strip() and not line.upper().startswith(('DECISION', 'CONFIDENCE')):
                reasoning = line.strip()
                break

    return LLMScore(
        decision=decision,
        confidence=confidence,
        reasoning=reasoning[:500],
        model_used=model_used,
        latency_ms=latency_ms,
        raw_response=text[:1000],
    )


def is_ollama_available():
    """Quick health check for Ollama."""
    from . import llm_config
    try:
        resp = requests.get(f"{llm_config.OLLAMA_HOST}/api/version", timeout=3)
        return resp.ok
    except Exception:
        return False
