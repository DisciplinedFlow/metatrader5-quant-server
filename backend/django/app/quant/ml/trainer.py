"""
ML Model Trainer — continuous learning with LightGBM + SHAP.

Model progression:
1. <50 trades: No model, all signals accepted
2. 50-200 trades: LightGBM with conservative hyperparams
3. 200+ trades: LightGBM with full feature set + SHAP analysis

Why LightGBM over sklearn GBM:
- 5-10x faster training (leaf-wise vs level-wise growth)
- Native categorical feature handling
- Better generalization through L1/L2 regularization
- Histogram-based splits reduce overfitting on small datasets
- scikit-learn compatible API (drop-in replacement)

SHAP (SHapley Additive exPlanations) replaces basic feature_importances_
because it shows HOW each feature contributes to individual predictions,
not just aggregate importance. This is critical for understanding why
the model accepts or rejects specific trades.

Reference: Ke et al., "LightGBM: A Highly Efficient Gradient Boosting
Decision Tree" (NeurIPS 2017)
"""

import json
import logging
import os
from datetime import datetime, timezone as tz

import numpy as np

from .features import FEATURE_NAMES, SELECTED_FEATURES, features_to_array

logger = logging.getLogger('app.quant.ml')

MODEL_DIR = '/app/ml_models'
MIN_TRADES_TO_TRAIN = 30
RETRAIN_AFTER_N_NEW = 10


def train_model():
    """Train or retrain the ML model on all available trade data.

    Uses LightGBM with auto-tuned hyperparams based on dataset size.
    Computes SHAP values for interpretable feature importance.
    """
    try:
        import lightgbm as lgb
        from sklearn.model_selection import cross_val_score
        import joblib
    except ImportError as e:
        logger.error(f"Required package not installed: {e}")
        # Fallback to sklearn if lightgbm not available
        return _train_sklearn_fallback()

    from app.nexus.models import TradeFeature, MLModel

    # Gather training data
    features_qs = TradeFeature.objects.filter(
        actual_win__isnull=False,
        features_json__isnull=False,
    ).exclude(features_json={})

    count = features_qs.count()
    if count < MIN_TRADES_TO_TRAIN:
        logger.info(f"ML Trainer: Only {count} trades, need {MIN_TRADES_TO_TRAIN}. Skipping.")
        return None

    X_list = []
    y_list = []
    for tf in features_qs:
        try:
            feat_dict = tf.features_json if isinstance(tf.features_json, dict) else json.loads(tf.features_json)
            X_list.append(features_to_array(feat_dict))
            y_list.append(1 if tf.actual_win else 0)
        except Exception as e:
            logger.debug(f"Skipping trade feature {tf.id}: {e}")

    if len(X_list) < MIN_TRADES_TO_TRAIN:
        return None

    X = np.array(X_list)
    y = np.array(y_list)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # Adaptive hyperparameters based on dataset size
    if len(X) < 100:
        params = {
            'n_estimators': 100,
            'max_depth': 4,
            'num_leaves': 15,
            'min_child_samples': 5,
            'learning_rate': 0.05,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'reg_alpha': 0.1,     # L1 regularization
            'reg_lambda': 1.0,    # L2 regularization
            'is_unbalanced': True,
            'random_state': 42,
            'verbose': -1,
        }
    elif len(X) < 500:
        params = {
            'n_estimators': 200,
            'max_depth': 5,
            'num_leaves': 31,
            'min_child_samples': 10,
            'learning_rate': 0.05,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'reg_alpha': 0.1,
            'reg_lambda': 1.0,
            'is_unbalanced': True,
            'random_state': 42,
            'verbose': -1,
        }
    else:
        params = {
            'n_estimators': 300,
            'max_depth': 6,
            'num_leaves': 63,
            'min_child_samples': 20,
            'learning_rate': 0.03,
            'subsample': 0.7,
            'colsample_bytree': 0.7,
            'reg_alpha': 0.3,
            'reg_lambda': 2.0,
            'is_unbalanced': True,
            'random_state': 42,
            'verbose': -1,
        }

    model = lgb.LGBMClassifier(**params)
    model_type = 'LightGBM'

    # Cross-validation
    cv_folds = min(5, len(X) // 5)
    if cv_folds >= 2:
        cv_scores = cross_val_score(model, X, y, cv=cv_folds, scoring='accuracy')
        cv_accuracy = cv_scores.mean()
        cv_std = cv_scores.std()
    else:
        cv_accuracy = 0.0
        cv_std = 0.0

    # Train on full dataset
    model.fit(X, y)

    # SHAP feature importance (more informative than split-based importance)
    importance_dict = _compute_shap_importance(model, X)

    # Fallback to native importance if SHAP fails
    if not importance_dict and hasattr(model, 'feature_importances_'):
        importance_dict = {
            name: round(float(imp), 4)
            for name, imp in sorted(
                zip(SELECTED_FEATURES, model.feature_importances_),
                key=lambda x: x[1], reverse=True,
            )
        }

    # Full dataset metrics
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    y_pred = model.predict(X)
    accuracy = accuracy_score(y, y_pred)
    precision = precision_score(y, y_pred, zero_division=0)
    recall = recall_score(y, y_pred, zero_division=0)
    f1 = f1_score(y, y_pred, zero_division=0)

    # Save model
    os.makedirs(MODEL_DIR, exist_ok=True)
    version = MLModel.objects.count() + 1
    model_path = os.path.join(MODEL_DIR, f'trade_scorer_v{version}.joblib')
    joblib.dump(model, model_path)

    # Learning curve
    learning_curve = _compute_learning_curve(X, y, params)

    # SHAP summary for dashboard (per-feature mean absolute SHAP values)
    shap_summary = _compute_shap_summary(model, X)

    # Store model metadata
    ml_model = MLModel.objects.create(
        version=version,
        model_type=model_type,
        trade_count=len(X),
        accuracy=round(accuracy, 4),
        cv_accuracy=round(cv_accuracy, 4),
        cv_std=round(cv_std, 4),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1_score=round(f1, 4),
        feature_importance=importance_dict,
        model_path=model_path,
        is_active=True,
        learning_curve=learning_curve,
        win_rate_baseline=round(sum(y) / len(y), 4),
    )

    # Store SHAP data in model's JSON field for dashboard
    if shap_summary:
        ml_model.feature_importance = {
            **importance_dict,
            '_shap_summary': shap_summary,
        }
        ml_model.save(update_fields=['feature_importance'])

    # Deactivate previous models
    MLModel.objects.exclude(id=ml_model.id).update(is_active=False)

    logger.info(
        f"ML Model v{version} trained: {model_type}, "
        f"trades={len(X)}, accuracy={accuracy:.1%}, "
        f"CV={cv_accuracy:.1%}±{cv_std:.1%}, "
        f"precision={precision:.1%}, recall={recall:.1%}, "
        f"top_features={list(importance_dict.keys())[:5]}"
    )

    return {
        'version': version,
        'model_type': model_type,
        'trade_count': len(X),
        'accuracy': accuracy,
        'cv_accuracy': cv_accuracy,
        'precision': precision,
        'recall': recall,
        'feature_importance': importance_dict,
    }


def _compute_shap_importance(model, X):
    """Compute SHAP-based feature importance (mean |SHAP| per feature)."""
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)

        # For binary classification, shap_values may be a list of 2 arrays
        if isinstance(shap_values, list):
            sv = np.abs(shap_values[1])  # Class 1 (win) SHAP values
        else:
            sv = np.abs(shap_values)

        mean_shap = sv.mean(axis=0)
        total = mean_shap.sum()
        if total > 0:
            normalized = mean_shap / total

        importance = {
            name: round(float(normalized[i]), 4)
            for i, name in enumerate(SELECTED_FEATURES)
            if i < len(normalized)
        }
        return dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))
    except Exception as e:
        logger.debug(f"SHAP importance failed: {e}")
        return {}


def _compute_shap_summary(model, X):
    """Compute per-feature SHAP summary for dashboard visualization.

    Returns a list of {feature, importance, direction} dicts showing
    which features push toward WIN vs LOSS.
    """
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)

        if isinstance(shap_values, list):
            sv = shap_values[1]
        else:
            sv = shap_values

        summary = []
        for i, name in enumerate(SELECTED_FEATURES):
            if i >= sv.shape[1]:
                break
            vals = sv[:, i]
            summary.append({
                'feature': name,
                'mean_abs': round(float(np.abs(vals).mean()), 6),
                'mean_signed': round(float(vals.mean()), 6),
                'std': round(float(vals.std()), 6),
            })

        summary.sort(key=lambda x: x['mean_abs'], reverse=True)
        return summary[:15]  # Top 15 features
    except Exception as e:
        logger.debug(f"SHAP summary failed: {e}")
        return []


def _compute_learning_curve(X, y, params):
    """Compute accuracy at different training set sizes."""
    try:
        import lightgbm as lgb
        from sklearn.model_selection import cross_val_score
    except ImportError:
        return []

    curve = []
    sizes = [20, 30, 50, 75, 100, 150, 200, 300, 500]

    # Lighter params for learning curve to avoid overfitting small subsets
    lc_params = {**params, 'n_estimators': 50, 'max_depth': 4, 'num_leaves': 15}

    for size in sizes:
        if size > len(X):
            break
        X_sub = X[:size]
        y_sub = y[:size]

        m = lgb.LGBMClassifier(**lc_params)
        cv_folds = min(3, size // 5)
        if cv_folds >= 2:
            scores = cross_val_score(m, X_sub, y_sub, cv=cv_folds, scoring='accuracy')
            curve.append({'trades': size, 'accuracy': round(float(scores.mean()), 4)})

    return curve


def _train_sklearn_fallback():
    """Fallback to sklearn if LightGBM is not available."""
    try:
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.model_selection import cross_val_score
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
        import joblib
    except ImportError:
        logger.error("Neither LightGBM nor scikit-learn available")
        return None

    from app.nexus.models import TradeFeature, MLModel

    features_qs = TradeFeature.objects.filter(
        actual_win__isnull=False,
        features_json__isnull=False,
    ).exclude(features_json={})

    count = features_qs.count()
    if count < MIN_TRADES_TO_TRAIN:
        return None

    X_list, y_list = [], []
    for tf in features_qs:
        try:
            feat_dict = tf.features_json if isinstance(tf.features_json, dict) else json.loads(tf.features_json)
            X_list.append(features_to_array(feat_dict))
            y_list.append(1 if tf.actual_win else 0)
        except Exception:
            pass

    if len(X_list) < MIN_TRADES_TO_TRAIN:
        return None

    X = np.array(X_list)
    y = np.array(y_list)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    if len(X) < 200:
        model = RandomForestClassifier(
            n_estimators=100, max_depth=5, min_samples_leaf=3,
            random_state=42, class_weight='balanced',
        )
        model_type = 'RandomForest'
    else:
        model = GradientBoostingClassifier(
            n_estimators=150, max_depth=4, min_samples_leaf=5,
            learning_rate=0.1, subsample=0.8, random_state=42,
        )
        model_type = 'GradientBoosting'

    cv_folds = min(5, len(X) // 5)
    cv_accuracy, cv_std = 0.0, 0.0
    if cv_folds >= 2:
        cv_scores = cross_val_score(model, X, y, cv=cv_folds, scoring='accuracy')
        cv_accuracy = cv_scores.mean()
        cv_std = cv_scores.std()

    model.fit(X, y)

    importance_dict = {}
    if hasattr(model, 'feature_importances_'):
        importance_dict = {
            name: round(float(imp), 4)
            for name, imp in sorted(
                zip(SELECTED_FEATURES, model.feature_importances_),
                key=lambda x: x[1], reverse=True,
            )
        }

    y_pred = model.predict(X)
    accuracy = accuracy_score(y, y_pred)
    precision = precision_score(y, y_pred, zero_division=0)
    recall = recall_score(y, y_pred, zero_division=0)
    f1 = f1_score(y, y_pred, zero_division=0)

    os.makedirs(MODEL_DIR, exist_ok=True)
    version = MLModel.objects.count() + 1
    model_path = os.path.join(MODEL_DIR, f'trade_scorer_v{version}.joblib')
    joblib.dump(model, model_path)

    MLModel.objects.create(
        version=version, model_type=model_type, trade_count=len(X),
        accuracy=round(accuracy, 4), cv_accuracy=round(cv_accuracy, 4),
        cv_std=round(cv_std, 4), precision=round(precision, 4),
        recall=round(recall, 4), f1_score=round(f1, 4),
        feature_importance=importance_dict, model_path=model_path,
        is_active=True, learning_curve=[],
        win_rate_baseline=round(sum(y) / len(y), 4),
    )
    MLModel.objects.filter(is_active=True).exclude(version=version).update(is_active=False)

    logger.info(f"ML Model v{version} (sklearn fallback): {model_type}, accuracy={accuracy:.1%}")
    return {
        'version': version, 'model_type': model_type,
        'trade_count': len(X), 'accuracy': accuracy,
        'cv_accuracy': cv_accuracy, 'precision': precision,
        'recall': recall, 'feature_importance': importance_dict,
    }


def get_active_model():
    """Load the currently active ML model from disk."""
    try:
        import joblib
        from app.nexus.models import MLModel

        ml_model = MLModel.objects.filter(is_active=True).first()
        if ml_model is None:
            return None, None

        if not os.path.exists(ml_model.model_path):
            logger.warning(f"Model file not found: {ml_model.model_path}")
            return None, None

        model = joblib.load(ml_model.model_path)
        return model, ml_model
    except ImportError:
        logger.error("joblib not installed")
        return None, None
    except Exception as e:
        logger.error(f"Error loading ML model: {e}")
        return None, None


def should_retrain():
    """Check if enough new trades have accumulated to warrant retraining."""
    from app.nexus.models import TradeFeature, MLModel

    active = MLModel.objects.filter(is_active=True).first()
    if active is None:
        total = TradeFeature.objects.filter(actual_win__isnull=False).count()
        return total >= MIN_TRADES_TO_TRAIN

    new_trades = TradeFeature.objects.filter(
        actual_win__isnull=False,
        created_at__gt=active.trained_at,
    ).count()

    return new_trades >= RETRAIN_AFTER_N_NEW
