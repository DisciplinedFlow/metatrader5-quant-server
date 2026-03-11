"""
ML Signal Scorer — gates trade entries based on predicted win probability.

Called by the entry algorithm after signal detection, before order placement.
Returns a score (0.0 to 1.0) and accept/reject decision.

Threshold progression (auto-tightens as confidence grows):
- <50 trades:  No model, accept all (threshold=0.0)
- 50-200:      Permissive (threshold=0.40)
- 200-500:     Balanced (threshold=0.50)
- 500+:        Confident (threshold=0.55)
"""

import logging
import json

from .features import extract_features, features_to_array
from .trainer import get_active_model

logger = logging.getLogger('app.quant.ml')


def score_signal(symbol, order_type, df, atr_val,
                 strategy_config=None, custom_strategy=None, tick_info=None):
    """Score a trade signal and decide whether to accept it.

    Returns:
        (score: float, accept: bool, reason: str, features: dict)
        - score: 0.0 to 1.0 predicted win probability
        - accept: whether the trade should proceed
        - reason: human-readable explanation
        - features: extracted feature dict (to store in TradeFeature)
    """
    # Extract features regardless of model availability (for data collection)
    features = extract_features(
        symbol, order_type, df, atr_val,
        strategy_config, custom_strategy, tick_info,
    )

    if features is None:
        return 0.5, True, "Feature extraction failed, allowing trade", {}

    # Try to score with ML model
    model, ml_meta = get_active_model()

    if model is None:
        return 0.5, True, "No ML model yet, collecting data", features

    try:
        X = features_to_array(features).reshape(1, -1)

        # Handle NaN
        import numpy as np
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        # Get probability of winning
        probabilities = model.predict_proba(X)[0]
        # Class 1 = win
        win_idx = list(model.classes_).index(1) if 1 in model.classes_ else -1
        score = float(probabilities[win_idx]) if win_idx >= 0 else 0.5

        # Determine threshold based on data size
        threshold = _get_threshold(ml_meta.trade_count)

        accept = score >= threshold

        # Build explanation from top contributing features
        explanation = _explain_score(features, ml_meta, score, threshold)

        if not accept:
            logger.info(
                f"ML REJECT: {symbol} {order_type} score={score:.2f} "
                f"(threshold={threshold:.2f}) — {explanation}"
            )
        else:
            logger.info(
                f"ML ACCEPT: {symbol} {order_type} score={score:.2f} "
                f"(threshold={threshold:.2f})"
            )

        return score, accept, explanation, features

    except Exception as e:
        logger.error(f"ML scoring error: {e}")
        return 0.5, True, f"Scoring error: {e}", features


def _get_threshold(trade_count):
    """Auto-adjust threshold based on how much training data exists."""
    if trade_count < 50:
        return 0.0   # No filtering
    elif trade_count < 200:
        return 0.40   # Permissive
    elif trade_count < 500:
        return 0.50   # Balanced
    else:
        return 0.55   # Confident


def _explain_score(features, ml_meta, score, threshold):
    """Generate human-readable explanation of the score."""
    parts = []

    importance = ml_meta.feature_importance or {}
    top_features = list(importance.keys())[:3]

    for feat_name in top_features:
        val = features.get(feat_name, 0)
        if feat_name == 'hour_utc':
            parts.append(f"hour={int(val)}")
        elif feat_name == 'regime_encoded':
            regime_names = {-1: 'TREND_DOWN', 0: 'RANGING', 1: 'TREND_UP', 2: 'VOLATILE'}
            parts.append(f"regime={regime_names.get(int(val), '?')}")
        elif feat_name == 'symbol_wr_10':
            parts.append(f"sym_wr={val:.0%}")
        elif feat_name == 'recent_streak':
            parts.append(f"streak={int(val)}")
        elif feat_name == 'macro_bias_aligned':
            parts.append(f"macro={'aligned' if val > 0 else 'opposing' if val < 0 else 'neutral'}")
        else:
            parts.append(f"{feat_name}={val:.3f}")

    action = "ACCEPT" if score >= threshold else "REJECT"
    return f"{action} (top: {', '.join(parts)})"
