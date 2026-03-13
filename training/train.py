#!/usr/bin/env python3
"""
Standalone ML Training Script — runs on the training machine (MacBook Pro / Mac Studio).

Triggered remotely via SSH from the Mac mini trading server.
Trains XGBoost meta-filter and/or LLM (MLX LoRA fine-tune) from exported data.

Usage:
    python3 train.py --mode all          # Train both XGBoost and LLM
    python3 train.py --mode xgboost      # XGBoost only
    python3 train.py --mode llm          # LLM only
    python3 train.py --data-dir ./data   # Custom data directory
"""
import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('train')

SCRIPT_DIR = Path(__file__).parent.resolve()

# ---------------------------------------------------------------------------
# XGBoost Training
# ---------------------------------------------------------------------------

# Features the live system selects (must match features.py SELECTED_FEATURES)
SELECTED_FEATURES = [
    'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos', 'session',
    'symbol_id', 'order_direction',
    'atr_normalized', 'rsi', 'ema_alignment', 'bb_width', 'adx',
    'frac_diff_close', 'vol_ratio', 'realized_vol', 'garman_klass_vol',
    'regime_encoded', 'regime_confidence', 'hmm_regime',
    'recent_streak', 'symbol_wr_10', 'strategy_wr_20', 'drawdown_pct',
]


def train_xgboost(data_dir: Path) -> dict:
    """Train XGBoost model from exported trade features CSV."""
    csv_path = data_dir / 'trade_features.csv'
    if not csv_path.exists():
        log.error(f"No trade features found at {csv_path}")
        return {'success': False, 'error': 'trade_features.csv not found'}

    df = pd.read_csv(csv_path)
    log.info(f"Loaded {len(df)} trade records from {csv_path}")

    # Filter to labeled trades only
    df = df.dropna(subset=['actual_win'])
    if len(df) < 30:
        log.warning(f"Only {len(df)} labeled trades — need at least 30")
        return {'success': False, 'error': f'Insufficient data: {len(df)} trades (need 30)'}

    # Extract features
    feature_cols = [c for c in SELECTED_FEATURES if c in df.columns]
    missing = set(SELECTED_FEATURES) - set(feature_cols)
    if missing:
        log.warning(f"Missing features (will be zero-filled): {missing}")

    X = df[feature_cols].fillna(0).values
    y = df['actual_win'].astype(int).values

    log.info(f"Features: {len(feature_cols)}, Samples: {len(X)}, Win rate: {y.mean():.1%}")

    # Walk-forward split (no future leakage)
    split_idx = int(len(X) * 0.7)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    # Try XGBoost → LightGBM → sklearn fallback
    model = None
    model_type = None
    try:
        import xgboost as xgb
        model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.5,
            reg_lambda=1.0,
            min_child_weight=3,
            eval_metric='logloss',
            random_state=42,
            use_label_encoder=False,
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
        model_type = 'xgboost'
        log.info("Trained XGBoost model")
    except Exception as e:
        log.warning(f"XGBoost failed: {e}, trying LightGBM...")
        try:
            import lightgbm as lgb
            model = lgb.LGBMClassifier(
                n_estimators=200, max_depth=4, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8, reg_alpha=0.5, reg_lambda=1.0,
                random_state=42, verbose=-1,
            )
            model.fit(X_train, y_train, eval_set=[(X_test, y_test)])
            model_type = 'lightgbm'
            log.info("Trained LightGBM model")
        except Exception as e2:
            log.warning(f"LightGBM failed: {e2}, using sklearn fallback")
            from sklearn.ensemble import GradientBoostingClassifier
            model = GradientBoostingClassifier(
                n_estimators=150, max_depth=4, learning_rate=0.05, random_state=42
            )
            model.fit(X_train, y_train)
            model_type = 'sklearn'
            log.info("Trained sklearn GradientBoosting model")

    # Evaluate
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    from sklearn.model_selection import cross_val_score

    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    cv_scores = cross_val_score(model, X, y, cv=min(5, len(X) // 10), scoring='accuracy')

    log.info(f"Walk-forward accuracy: {accuracy:.1%}")
    log.info(f"CV accuracy: {cv_scores.mean():.1%} (+/- {cv_scores.std():.1%})")

    # Feature importance
    feature_importance = {}
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test[:min(200, len(X_test))])
        if isinstance(shap_values, list):
            shap_values = shap_values[1]
        mean_abs = np.abs(shap_values).mean(axis=0)
        for i, fname in enumerate(feature_cols):
            feature_importance[fname] = float(mean_abs[i])
        log.info(f"SHAP importance computed for {len(feature_importance)} features")
    except Exception as e:
        log.warning(f"SHAP failed: {e}, using model native importance")
        if hasattr(model, 'feature_importances_'):
            for i, fname in enumerate(feature_cols):
                feature_importance[fname] = float(model.feature_importances_[i])

    # Save model
    models_dir = data_dir / 'models'
    models_dir.mkdir(exist_ok=True)

    version = int(time.time())
    model_path = models_dir / f'trade_scorer_v{version}.joblib'
    joblib.dump(model, model_path)
    log.info(f"Saved model: {model_path}")

    # Also save as 'latest' for easy pickup
    latest_path = models_dir / 'trade_scorer_latest.joblib'
    joblib.dump(model, latest_path)

    result = {
        'success': True,
        'model_type': model_type,
        'version': version,
        'model_path': str(model_path),
        'trade_count': len(df),
        'accuracy': round(accuracy, 4),
        'cv_accuracy': round(float(cv_scores.mean()), 4),
        'precision': round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        'recall': round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        'f1': round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
        'feature_importance': feature_importance,
    }
    # Write result JSON for the server to pick up
    with open(models_dir / 'xgboost_result.json', 'w') as f:
        json.dump(result, f, indent=2)

    return result


# ---------------------------------------------------------------------------
# LLM Fine-Tuning (MLX LoRA)
# ---------------------------------------------------------------------------

HF_MODEL = os.getenv('MLX_MODEL_HF', 'Qwen/Qwen2.5-3B-Instruct')
LORA_ITERS = int(os.getenv('MLX_TRAIN_ITERS', '500'))
LORA_LAYERS = int(os.getenv('MLX_LORA_LAYERS', '8'))
LORA_RANK = int(os.getenv('MLX_LORA_RANK', '16'))
BATCH_SIZE = int(os.getenv('MLX_BATCH_SIZE', '1'))
LEARNING_RATE = float(os.getenv('MLX_LEARNING_RATE', '1e-5'))

OLLAMA_MODEL_NAME = 'trade-brain'
SYSTEM_PROMPT = """You are a forex trade analyst for an automated trading system. You analyze trade setups using market features and historical performance patterns.

Given a trade setup with technical indicators, market regime, and performance context, you must:
1. Analyze the setup quality (confluence of signals)
2. Check if conditions match historically winning patterns
3. Output a clear ACCEPT or REJECT decision with confidence (0-100)

Format your response EXACTLY as:
DECISION: ACCEPT|REJECT
CONFIDENCE: <0-100>
REASONING: <2-3 sentences explaining why>

Be concise. Focus on edge — does this setup have positive expectancy based on the patterns you've learned?"""


def train_llm(data_dir: Path) -> dict:
    """Run MLX LoRA fine-tuning on trade analysis JSONL."""
    jsonl_path = data_dir / 'trade_analyses.jsonl'
    if not jsonl_path.exists():
        log.error(f"No LLM training data at {jsonl_path}")
        return {'success': False, 'error': 'trade_analyses.jsonl not found'}

    # Count examples
    with open(jsonl_path) as f:
        line_count = sum(1 for line in f if line.strip())
    log.info(f"LLM training data: {line_count} examples")

    if line_count < 10:
        log.warning("Too few examples for LLM fine-tuning")
        return {'success': False, 'error': f'Insufficient LLM data: {line_count} examples'}

    llm_dir = data_dir / 'llm'
    mlx_data_dir = llm_dir / 'training_data'
    adapters_dir = llm_dir / 'adapters'
    fused_dir = llm_dir / 'fused'

    # Step 1: Convert to MLX chat format
    log.info("LLM Step 1: Converting to MLX format...")
    mlx_data_dir.mkdir(parents=True, exist_ok=True)

    examples = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                messages = [
                    {"role": "system", "content": data.get('system', '')},
                    {"role": "user", "content": f"{data.get('instruction', '')}\n\n{data.get('input', '')}"},
                    {"role": "assistant", "content": data.get('output', '')},
                ]
                examples.append({"messages": messages})
            except json.JSONDecodeError:
                continue

    # Deterministic shuffle
    examples.sort(key=lambda x: hashlib.md5(json.dumps(x, sort_keys=True).encode()).hexdigest())

    n = len(examples)
    n_test = max(1, int(n * 0.1))
    n_valid = max(1, int(n * 0.1))

    splits = {
        'test': examples[:n_test],
        'valid': examples[n_test:n_test + n_valid],
        'train': examples[n_test + n_valid:],
    }
    for name, data in splits.items():
        path = mlx_data_dir / f'{name}.jsonl'
        with open(path, 'w') as f:
            for ex in data:
                f.write(json.dumps(ex) + '\n')
        log.info(f"  {name}: {len(data)} examples")

    # Step 2: LoRA fine-tune
    log.info(f"LLM Step 2: LoRA fine-tuning ({LORA_ITERS} iters, model: {HF_MODEL})...")
    adapters_dir.mkdir(parents=True, exist_ok=True)

    import yaml
    config = {
        'model': HF_MODEL,
        'data': str(mlx_data_dir),
        'train': True,
        'iters': LORA_ITERS,
        'batch_size': BATCH_SIZE,
        'num_layers': LORA_LAYERS,
        'learning_rate': LEARNING_RATE,
        'adapter_path': str(adapters_dir),
        'save_every': 100,
        'steps_per_report': 10,
        'steps_per_eval': 100,
        'max_seq_length': 1024,
        'lora_parameters': {
            'rank': LORA_RANK,
            'dropout': 0.05,
            'scale': 20.0,
        },
    }
    config_path = adapters_dir / 'train_config.yaml'
    with open(config_path, 'w') as f:
        yaml.dump(config, f)

    cmd = [sys.executable, '-m', 'mlx_lm.lora', '-c', str(config_path)]
    log.info(f"  Running: {' '.join(cmd)}")

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    train_output = []
    for line in process.stdout:
        line = line.strip()
        if line:
            train_output.append(line)
            if 'Iter' in line or 'loss' in line.lower() or 'val' in line.lower():
                log.info(f"  {line}")
    process.wait()

    if process.returncode != 0:
        log.error("LoRA training failed")
        return {'success': False, 'error': 'LoRA training failed', 'output': '\n'.join(train_output[-20:])}

    log.info("  LoRA training complete!")

    # Step 3: Fuse
    log.info("LLM Step 3: Fusing LoRA weights...")
    if fused_dir.exists():
        shutil.rmtree(fused_dir)
    fused_dir.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, '-m', 'mlx_lm.fuse',
           '--model', HF_MODEL,
           '--adapter-path', str(adapters_dir),
           '--save-path', str(fused_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        log.error(f"Fuse failed: {result.stderr}")
        return {'success': False, 'error': f'Fuse failed: {result.stderr[:500]}'}
    log.info(f"  Fused model saved to {fused_dir}")

    # Step 4: Create Ollama model (if Ollama is available on this machine)
    # The GGUF conversion and Ollama registration happens on the Mac mini after rsync
    # But we prepare the Modelfile here
    version = datetime.now().strftime('%Y%m%d_%H%M')
    modelfile_path = fused_dir / 'Modelfile'
    with open(modelfile_path, 'w') as f:
        f.write(f'FROM {fused_dir}\n\n')
        f.write(f'SYSTEM """{SYSTEM_PROMPT}"""\n\n')
        f.write(f'PARAMETER temperature 0.3\n')
        f.write(f'PARAMETER num_predict 512\n')

    llm_result = {
        'success': True,
        'version': version,
        'fused_dir': str(fused_dir),
        'modelfile': str(modelfile_path),
        'training_examples': n,
        'train_split': len(splits['train']),
        'train_output_tail': '\n'.join(train_output[-10:]),
    }

    # Write result JSON
    with open(llm_dir / 'llm_result.json', 'w') as f:
        json.dump(llm_result, f, indent=2)

    return llm_result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Quant Trading ML Training')
    parser.add_argument('--mode', choices=['all', 'xgboost', 'llm'], default='all')
    parser.add_argument('--data-dir', default=str(SCRIPT_DIR / 'data'))
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        log.error(f"Data directory not found: {data_dir}")
        sys.exit(1)

    log.info("=" * 60)
    log.info("QUANT TRADING ML TRAINING")
    log.info(f"Mode: {args.mode} | Data: {data_dir}")
    log.info("=" * 60)

    results = {'started_at': datetime.now().isoformat(), 'mode': args.mode}

    # XGBoost
    if args.mode in ('all', 'xgboost'):
        log.info("")
        log.info("=== XGBoost Training ===")
        xgb_result = train_xgboost(data_dir)
        results['xgboost'] = xgb_result
        if xgb_result['success']:
            log.info(f"XGBoost: {xgb_result['model_type']} — {xgb_result['accuracy']:.1%} accuracy, "
                     f"{xgb_result['cv_accuracy']:.1%} CV")
        else:
            log.error(f"XGBoost failed: {xgb_result.get('error')}")

    # LLM
    if args.mode in ('all', 'llm'):
        log.info("")
        log.info("=== LLM Fine-Tuning ===")
        llm_result = train_llm(data_dir)
        results['llm'] = llm_result
        if llm_result['success']:
            log.info(f"LLM: v{llm_result['version']} — {llm_result['training_examples']} examples")
        else:
            log.error(f"LLM failed: {llm_result.get('error')}")

    results['completed_at'] = datetime.now().isoformat()

    # Write combined result
    with open(data_dir / 'training_result.json', 'w') as f:
        json.dump(results, f, indent=2)

    log.info("")
    log.info("=" * 60)
    any_success = results.get('xgboost', {}).get('success') or results.get('llm', {}).get('success')
    if any_success:
        log.info("TRAINING COMPLETE")
    else:
        log.info("TRAINING FAILED")
    log.info("=" * 60)

    sys.exit(0 if any_success else 1)


if __name__ == '__main__':
    main()
