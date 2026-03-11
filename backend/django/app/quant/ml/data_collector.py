"""
LLM Training Data Collector — builds instruction-tuning dataset.

Generates structured trade analyses that will be used to fine-tune
a local LLM (e.g., Llama 3.1 8B → GGUF → Ollama).

Data format: JSONL with instruction/input/output triplets.
Each closed trade produces one training example combining:
- Market context (features) as input
- Trade outcome + analysis as output

The model learns to predict and REASON about trade outcomes,
not just classify them. This is what makes it exportable as an LLM
rather than just a sklearn model.
"""

import json
import logging
import os
from datetime import datetime, timezone as tz

logger = logging.getLogger('app.quant.ml')

LLM_DATA_DIR = '/app/ml_models/llm_training_data'
SYSTEM_PROMPT = (
    "You are an expert forex trading analyst. Given market conditions and a "
    "proposed trade setup, analyze the probability of success and provide "
    "detailed reasoning. Consider technical indicators, market regime, macro "
    "context, recent performance patterns, and temporal factors."
)


def generate_training_example(trade, trade_feature):
    """Generate an instruction-tuning example from a closed trade.

    Args:
        trade: Closed Trade model instance
        trade_feature: TradeFeature instance with features_json

    Returns:
        dict with keys: system, instruction, input, output
    """
    if not trade_feature or not trade_feature.features_json:
        return None

    features = trade_feature.features_json
    if isinstance(features, str):
        features = json.loads(features)

    # Build human-readable input
    regime_names = {-1: 'TRENDING_DOWN', 0: 'RANGING', 1: 'TRENDING_UP', 2: 'VOLATILE'}
    session_names = {0: 'Asian', 1: 'London', 2: 'New York', 3: 'London-NY overlap'}

    # Reconstruct time from cyclical encoding for LLM readability
    import math
    hour_sin = features.get('hour_sin', 0)
    hour_cos = features.get('hour_cos', 0)
    hour_approx = round(math.atan2(hour_sin, hour_cos) * 24 / (2 * math.pi)) % 24

    hmm_names = {0: 'calm', 1: 'normal', 2: 'volatile', -1: 'unknown'}

    input_lines = [
        f"Symbol: {trade.symbol}",
        f"Direction: {trade.type}",
        f"Time: ~{hour_approx}:00 UTC",
        f"Session: {session_names.get(int(features.get('session', 0)), '?')}",
        f"Regime: {regime_names.get(int(features.get('regime_encoded', 0)), '?')} "
        f"(confidence={features.get('regime_confidence', 0):.2f})",
        f"HMM Regime: {hmm_names.get(int(features.get('hmm_regime', -1)), 'unknown')}",
        f"ADX: {features.get('adx', 0):.1f}",
        f"RSI: {features.get('rsi', 50):.1f}",
        f"ATR (normalized): {features.get('atr_normalized', 0):.5f}",
        f"Vol Ratio (ATR5/ATR21): {features.get('vol_ratio', 1.0):.2f}",
        f"Realized Vol: {features.get('realized_vol', 0):.5f}",
        f"Garman-Klass Vol: {features.get('garman_klass_vol', 0):.5f}",
        f"Frac Diff Close: {features.get('frac_diff_close', 0):.6f}",
        f"BB Width: {features.get('bb_width', 0):.4f}",
        f"EMA Alignment: {features.get('ema_alignment', 0):.5f}",
        f"Spread/ATR: {features.get('spread_atr_ratio', 0):.3f}",
        f"Macro Risk: {features.get('macro_risk_level', 5)}",
        f"Macro Bias: {'aligned' if features.get('macro_bias_aligned', 0) > 0 else 'opposing' if features.get('macro_bias_aligned', 0) < 0 else 'neutral'}",
        f"Recent Streak: {int(features.get('recent_streak', 0))}",
        f"Symbol WR (last 10): {features.get('symbol_wr_10', 0.5):.0%}",
        f"Strategy WR (last 20): {features.get('strategy_wr_20', 0.5):.0%}",
        f"Drawdown: {features.get('drawdown_pct', 0):.1f}%",
        f"Open Positions: {int(features.get('positions_open', 0))}",
        f"Signal Strength: {features.get('signal_strength', 0.5):.2f}",
    ]
    if trade_feature.ml_score:
        input_lines.append(f"ML Score at Entry: {trade_feature.ml_score:.2f}")
    input_text = "\n".join(input_lines)

    # Build output with reasoning based on actual outcome
    won = trade.pnl > 0 if trade.pnl else False
    pnl = trade.pnl or 0

    output_text = _generate_analysis(trade, features, won, pnl, trade_feature)

    return {
        'system': SYSTEM_PROMPT,
        'instruction': 'Analyze this forex trade setup and predict the outcome with detailed reasoning.',
        'input': input_text.strip(),
        'output': output_text,
        'metadata': {
            'trade_id': trade.id,
            'symbol': trade.symbol,
            'pnl': float(pnl),
            'won': won,
            'strategy': trade.strategy,
            'timestamp': trade.entry_time.isoformat() if trade.entry_time else None,
        }
    }


def _generate_analysis(trade, features, won, pnl, trade_feature):
    """Generate the model output text — the analysis the LLM should learn to produce."""
    score_str = f"{trade_feature.ml_score:.2f}" if trade_feature.ml_score else "N/A"
    verdict = "WIN" if won else "LOSS"
    action = "ACCEPT" if won else "REJECT"

    # Identify contributing factors
    factors = []

    hour = int(features.get('hour_utc', 12))
    session = int(features.get('session', 0))
    session_names = {0: 'Asian', 1: 'London', 2: 'New York', 3: 'London-NY overlap'}
    if session == 3:
        factors.append("London-NY overlap provides maximum liquidity — favorable for entries")
    elif session == 0:
        factors.append("Asian session has lower volatility — signals less reliable for major pairs")

    regime = int(features.get('regime_encoded', 0))
    direction = features.get('order_direction', 0)
    if regime == 1 and direction == 1:
        factors.append("BUY aligns with TRENDING_UP regime — trading with the trend")
    elif regime == -1 and direction == -1:
        factors.append("SELL aligns with TRENDING_DOWN regime — trading with the trend")
    elif regime == 2:
        factors.append("VOLATILE regime increases uncertainty — wider stops needed")
    elif (regime == 1 and direction == -1) or (regime == -1 and direction == 1):
        factors.append("Trade direction opposes the regime trend — counter-trend risk")

    streak = int(features.get('recent_streak', 0))
    if streak <= -3:
        factors.append(f"Losing streak of {abs(streak)} — increased risk of emotional or systematic failure")
    elif streak >= 3:
        factors.append(f"Winning streak of {streak} — confidence high but watch for mean reversion")

    sym_wr = features.get('symbol_wr_10', 0.5)
    if sym_wr < 0.35:
        factors.append(f"Symbol win rate ({sym_wr:.0%}) is below threshold — this pair has been underperforming")
    elif sym_wr > 0.65:
        factors.append(f"Symbol win rate ({sym_wr:.0%}) is strong — this pair has been favorable")

    macro_aligned = features.get('macro_bias_aligned', 0)
    if macro_aligned < 0:
        factors.append("Trade opposes macro bias — fundamental headwinds")
    elif macro_aligned > 0:
        factors.append("Trade aligns with macro bias — fundamental tailwinds")

    factors_text = "\n".join(f"- {f}" for f in factors) if factors else "- No strong contributing factors identified"

    return (
        f"PREDICTION: {action} (Score: {score_str})\n"
        f"ACTUAL OUTCOME: {verdict} (PnL: ${pnl:+.2f})\n\n"
        f"Analysis:\n{factors_text}\n\n"
        f"Key metrics at entry:\n"
        f"- ADX={features.get('adx', 0):.1f} ({'strong trend' if features.get('adx', 0) > 25 else 'weak/no trend'})\n"
        f"- RSI={features.get('rsi', 50):.1f} ({'overbought' if features.get('rsi', 50) > 70 else 'oversold' if features.get('rsi', 50) < 30 else 'neutral'})\n"
        f"- Spread/ATR={features.get('spread_atr_ratio', 0):.3f} ({'high entry cost' if features.get('spread_atr_ratio', 0) > 0.3 else 'acceptable'})\n\n"
        f"Conclusion: This {trade.symbol} {trade.type} "
        f"{'succeeded' if won else 'failed'} with ${pnl:+.2f}. "
        f"{'The setup aligned well with market conditions.' if won else 'Future signals with similar conditions should be scrutinized more carefully.'}"
    )


def save_training_example(example):
    """Append a training example to the JSONL file."""
    if example is None:
        return

    os.makedirs(LLM_DATA_DIR, exist_ok=True)
    filepath = os.path.join(LLM_DATA_DIR, 'trade_analyses.jsonl')

    try:
        with open(filepath, 'a') as f:
            f.write(json.dumps(example, default=str) + '\n')
        logger.info(f"LLM training data saved: {example['metadata']['symbol']} {example['metadata']['pnl']:+.2f}")
    except Exception as e:
        logger.error(f"Failed to save LLM training data: {e}")


def get_training_data_stats():
    """Return stats about collected LLM training data."""
    filepath = os.path.join(LLM_DATA_DIR, 'trade_analyses.jsonl')

    if not os.path.exists(filepath):
        return {'total_examples': 0, 'file_size_kb': 0, 'wins': 0, 'losses': 0}

    wins = 0
    losses = 0
    total = 0
    try:
        with open(filepath) as f:
            for line in f:
                total += 1
                data = json.loads(line)
                if data.get('metadata', {}).get('won'):
                    wins += 1
                else:
                    losses += 1
    except Exception:
        pass

    file_size = os.path.getsize(filepath) / 1024

    return {
        'total_examples': total,
        'file_size_kb': round(file_size, 1),
        'wins': wins,
        'losses': losses,
    }
