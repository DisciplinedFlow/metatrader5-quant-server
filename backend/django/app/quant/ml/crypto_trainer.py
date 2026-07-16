"""
Crypto ML Trainer — XGBoost + LogisticRegression sanity check for Lighter.xyz trades.

Simplified version of the forex trainer (ml/trainer.py), designed for ~100 trades.
Heavy regularization to prevent overfitting on small crypto dataset.

Model progression:
1. <50 trades: No model, all signals accepted (permissive mode)
2. 50+ trades: XGBoost with extreme regularization + LR sanity check
3. Future: Expand features as trade count grows

Walk-forward validation (time-ordered, no shuffle) is the only honest evaluation
method for financial ML. Standard k-fold leaks future information.

Reference: Lopez de Prado, "Advances in Financial Machine Learning" (2018)
"""

import logging
import pickle

import numpy as np

from .crypto_features import (
    CRYPTO_FEATURES,
    extract_crypto_features,
    features_to_array,
)

logger = logging.getLogger('app.lighter')

MIN_TRADES = 50
REDIS_MODEL_KEY = 'lighter:ml_model'
REDIS_METRICS_KEY = 'lighter:ml_metrics'
REDIS_MODEL_TTL = 86400 * 7  # 7 days


def train_crypto_model():
    """Train XGBoost model on closed Lighter crypto trades.

    Returns dict with model metrics, or None if insufficient data.

    Pipeline:
    1. Extract features from all closed lighter: positions
    2. Walk-forward split (80% train, 20% test, time-ordered)
    3. Train XGBoost with heavy regularization
    4. Train LogisticRegression as sanity check (overfitting detector)
    5. Cache model in Redis
    6. Return metrics
    """
    X, y, trade_ids = extract_crypto_features()

    if X is None or len(X) < MIN_TRADES:
        count = 0 if X is None else len(X)
        logger.info(
            f"Crypto ML: Only {count} trades, need {MIN_TRADES}. Skipping training."
        )
        return None

    n = len(X)
    win_rate = sum(y) / len(y)
    neg_count = sum(y == 0)
    pos_count = sum(y == 1)
    scale_pos = neg_count / pos_count if pos_count > 0 else 1.0

    logger.info(
        f"Crypto ML: Training on {n} trades "
        f"(win_rate={win_rate:.1%}, pos={pos_count}, neg={neg_count})"
    )

    # ── Walk-forward split (80/20, time-ordered, NO shuffle) ──
    split_idx = int(n * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
        logger.warning("Crypto ML: Insufficient class diversity in train/test split.")
        return None

    # ── Train XGBoost with heavy regularization ──
    xgb_model = None
    xgb_accuracy = 0.0
    xgb_metrics = {}

    try:
        import xgboost as xgb

        xgb_model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=2,
            learning_rate=0.01,
            subsample=0.7,
            colsample_bytree=0.7,
            min_child_weight=5,
            reg_alpha=1.0,
            reg_lambda=2.0,
            scale_pos_weight=round(scale_pos, 2),
            eval_metric='logloss',
            use_label_encoder=False,
            random_state=42,
            verbosity=0,
        )
        xgb_model.fit(X_train, y_train)

        from sklearn.metrics import (
            accuracy_score, precision_score, recall_score, f1_score,
        )

        y_pred_xgb = xgb_model.predict(X_test)
        xgb_accuracy = accuracy_score(y_test, y_pred_xgb)
        xgb_metrics = {
            'accuracy': round(float(xgb_accuracy), 4),
            'precision': round(float(precision_score(y_test, y_pred_xgb, zero_division=0)), 4),
            'recall': round(float(recall_score(y_test, y_pred_xgb, zero_division=0)), 4),
            'f1': round(float(f1_score(y_test, y_pred_xgb, zero_division=0)), 4),
        }

        logger.info(
            f"Crypto ML XGBoost: accuracy={xgb_accuracy:.1%}, "
            f"precision={xgb_metrics['precision']}, recall={xgb_metrics['recall']}"
        )

    except ImportError:
        # Try LightGBM as fallback
        try:
            import lightgbm as lgb
            xgb_model = lgb.LGBMClassifier(
                n_estimators=100,
                max_depth=2,
                learning_rate=0.01,
                subsample=0.7,
                colsample_bytree=0.7,
                min_child_weight=5,
                reg_alpha=1.0,
                reg_lambda=2.0,
                scale_pos_weight=round(scale_pos, 2),
                random_state=42,
                verbose=-1,
            )
            xgb_model.fit(X_train, y_train)

            from sklearn.metrics import (
                accuracy_score, precision_score, recall_score, f1_score,
            )
            y_pred = xgb_model.predict(X_test)
            xgb_accuracy = accuracy_score(y_test, y_pred)
            xgb_metrics = {
                'accuracy': round(float(xgb_accuracy), 4),
                'precision': round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
                'recall': round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
                'f1': round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
            }
            logger.info(
                f"Crypto ML LightGBM: accuracy={xgb_accuracy:.1%}, "
                f"precision={xgb_metrics['precision']}, recall={xgb_metrics['recall']}"
            )
        except ImportError:
            logger.warning("Crypto ML: Neither XGBoost nor LightGBM available.")
        except Exception as e:
            logger.error(f"Crypto ML: LightGBM training failed: {e}")
    except Exception as e:
        logger.error(f"Crypto ML: XGBoost training failed: {e}")

    # ── LogisticRegression sanity check ──
    lr_accuracy = 0.0
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import accuracy_score

        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        lr_model = LogisticRegression(
            C=0.1,
            penalty='l1',
            solver='liblinear',
            random_state=42,
            max_iter=500,
        )
        lr_model.fit(X_train_scaled, y_train)
        y_pred_lr = lr_model.predict(X_test_scaled)
        lr_accuracy = accuracy_score(y_test, y_pred_lr)

        logger.info(f"Crypto ML LR sanity check: accuracy={lr_accuracy:.1%}")

        # Overfitting warning: if simple LR beats XGBoost, the tree model
        # is memorizing noise rather than learning signal.
        if lr_accuracy > xgb_accuracy and xgb_model is not None:
            logger.warning(
                f"Crypto ML WARNING: LR ({lr_accuracy:.1%}) > XGBoost ({xgb_accuracy:.1%}). "
                f"XGBoost is likely overfitting. Consider reducing complexity."
            )

    except ImportError:
        logger.debug("Crypto ML: sklearn not available for LR sanity check.")
    except Exception as e:
        logger.debug(f"Crypto ML: LR sanity check failed: {e}")

    # ── Select best model ──
    if xgb_model is None:
        logger.error("Crypto ML: No model could be trained.")
        return None

    # Retrain on full dataset for production use
    xgb_model.fit(X, y)

    # Feature importance
    importance_dict = {}
    if hasattr(xgb_model, 'feature_importances_'):
        importance_dict = {
            name: round(float(imp), 4)
            for name, imp in sorted(
                zip(CRYPTO_FEATURES, xgb_model.feature_importances_),
                key=lambda x: x[1],
                reverse=True,
            )
        }

    # ── Cache model in Redis ──
    # Note: pickle is used here intentionally — same pattern as the forex trainer
    # (joblib). The model is serialized by our own training code and deserialized
    # only by our own prediction code, so no untrusted data path exists.
    try:
        from django.core.cache import cache

        model_bytes = pickle.dumps(xgb_model)
        cache.set(REDIS_MODEL_KEY, model_bytes, timeout=REDIS_MODEL_TTL)

        model_name = type(xgb_model).__name__
        metrics = {
            'model_type': model_name,
            'train_size': n,
            'walk_forward_split': split_idx,
            'test_size': n - split_idx,
            'win_rate_baseline': round(float(win_rate), 4),
            'xgb_accuracy': round(float(xgb_accuracy), 4),
            'lr_accuracy': round(float(lr_accuracy), 4),
            'feature_importance': importance_dict,
            **xgb_metrics,
        }
        cache.set(REDIS_METRICS_KEY, metrics, timeout=REDIS_MODEL_TTL)

        logger.info(
            f"Crypto ML: Model cached in Redis ({len(model_bytes)} bytes), "
            f"accuracy={xgb_accuracy:.1%}, features={list(importance_dict.keys())[:5]}"
        )

    except Exception as e:
        logger.error(f"Crypto ML: Failed to cache model in Redis: {e}")

    return {
        'model_type': 'XGBoost',
        'train_size': n,
        'accuracy': xgb_accuracy,
        'lr_accuracy': lr_accuracy,
        'precision': xgb_metrics.get('precision', 0),
        'recall': xgb_metrics.get('recall', 0),
        'f1': xgb_metrics.get('f1', 0),
        'feature_importance': importance_dict,
        'win_rate_baseline': win_rate,
    }


def predict_crypto_trade(features_dict: dict) -> tuple:
    """Score a potential trade using the cached crypto ML model.

    Args:
        features_dict: Dict with keys from CRYPTO_FEATURES.

    Returns:
        (score: float, should_trade: bool) where:
        - score: probability of win (0.0 to 1.0)
        - should_trade: True if score >= 0.55 threshold

    Fails open: returns (0.5, True) if model is unavailable.
    """
    try:
        from django.core.cache import cache

        model_bytes = cache.get(REDIS_MODEL_KEY)
        if model_bytes is None:
            # No model trained yet — permissive mode
            return 0.5, True

        model = pickle.loads(model_bytes)  # noqa: S301 — trusted internal data only
        X = features_to_array(features_dict).reshape(1, -1)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        # predict_proba returns [[P(loss), P(win)]]
        proba = model.predict_proba(X)[0]
        score = float(proba[1])  # P(win)
        should_trade = score >= 0.55

        return score, should_trade

    except Exception as e:
        logger.warning(f"Crypto ML prediction failed: {e}")
        # Fail open — don't block trades if ML breaks
        return 0.5, True


def get_crypto_model_metrics() -> dict:
    """Get metrics for the currently cached crypto ML model.

    Returns empty dict if no model is trained.
    """
    try:
        from django.core.cache import cache
        metrics = cache.get(REDIS_METRICS_KEY)
        return metrics or {}
    except Exception:
        return {}
