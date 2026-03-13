"""
Remote ML Training Orchestrator — SSH+rsync to training machine.

Flow:
1. Export training data from Django DB (TradeFeature CSV + LLM JSONL)
2. rsync data to remote training machine
3. SSH execute train.py on remote
4. rsync trained models back
5. Hot-load XGBoost model into Docker container
6. Register LLM in Ollama (if trained)

Called from Celery task (run_remote_training) triggered by Dashboard.
"""
import json
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger('app.quant.ml.remote')

LOCAL_EXPORT_DIR = '/app/ml_models/training_export'
CONTAINER_MODEL_DIR = '/app/ml_models'


def _run(cmd, timeout=600, log_run=None):
    """Run a command with logging."""
    logger.info(f"  CMD: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        shell=isinstance(cmd, str),
    )
    if log_run:
        if result.stdout:
            log_run.append_log(result.stdout[-2000:])
        if result.stderr and result.returncode != 0:
            log_run.append_log(f"STDERR: {result.stderr[-1000:]}")
    return result


def export_training_data(run):
    """Export TradeFeature records + LLM JSONL from Django DB."""
    from app.nexus.models import TradeFeature

    run.step = 'exporting'
    run.save(update_fields=['step'])
    run.append_log("Exporting training data from database...")

    os.makedirs(LOCAL_EXPORT_DIR, exist_ok=True)

    # 1. Export trade features as CSV
    features = TradeFeature.objects.filter(
        actual_win__isnull=False,
        features_json__isnull=False,
    ).select_related('trade').order_by('trade__entry_time')

    rows = []
    for tf in features:
        row = tf.features_json.copy() if tf.features_json else {}
        row['actual_win'] = tf.actual_win
        row['ml_score'] = tf.ml_score
        row['trade_id'] = tf.trade_id
        row['symbol'] = tf.trade.symbol
        row['pnl'] = tf.trade.pnl
        rows.append(row)

    csv_path = os.path.join(LOCAL_EXPORT_DIR, 'trade_features.csv')
    if rows:
        df = pd.DataFrame(rows)
        df.to_csv(csv_path, index=False)
        run.append_log(f"Exported {len(rows)} trade features to CSV")
    else:
        run.append_log("WARNING: No labeled trade features found")

    # 2. Copy LLM JSONL if it exists
    llm_jsonl = '/app/ml_models/llm_training_data/trade_analyses.jsonl'
    export_jsonl = os.path.join(LOCAL_EXPORT_DIR, 'trade_analyses.jsonl')
    if os.path.exists(llm_jsonl):
        import shutil
        shutil.copy2(llm_jsonl, export_jsonl)
        with open(llm_jsonl) as f:
            count = sum(1 for _ in f)
        run.append_log(f"Exported {count} LLM training examples")
    else:
        run.append_log("No LLM training JSONL found (skipping)")

    return {'trade_count': len(rows), 'export_dir': LOCAL_EXPORT_DIR}


def sync_data_to_remote(run, config):
    """rsync exported data to the remote training machine."""
    run.step = 'syncing_data'
    run.save(update_fields=['step'])
    run.append_log(f"Syncing data to {config.ssh_user}@{config.ssh_host}...")

    ssh_opts = _ssh_opts(config)
    remote_data = f"{config.ssh_user}@{config.ssh_host}:{config.remote_training_dir}/data/"

    cmd = [
        'rsync', '-avz', '--progress',
        '-e', f'ssh {ssh_opts}',
        f'{LOCAL_EXPORT_DIR}/',
        remote_data,
    ]
    result = _run(cmd, timeout=120, log_run=run)

    if result.returncode != 0:
        raise RuntimeError(f"rsync to remote failed: {result.stderr[:500]}")

    run.append_log("Data synced to remote successfully")


def run_training_on_remote(run, config):
    """SSH into remote machine and execute train.py."""
    mode = 'all'
    if run.train_xgboost and not run.train_llm:
        mode = 'xgboost'
    elif run.train_llm and not run.train_xgboost:
        mode = 'llm'

    if run.train_xgboost:
        run.step = 'training_xgboost'
        run.save(update_fields=['step'])
    if run.train_llm and not run.train_xgboost:
        run.step = 'training_llm'
        run.save(update_fields=['step'])

    run.append_log(f"Starting remote training (mode={mode})...")

    ssh_opts = _ssh_opts(config)
    remote_dir = config.remote_training_dir

    # Activate venv and run train.py
    remote_cmd = (
        f'cd {remote_dir} && '
        f'source .venv/bin/activate 2>/dev/null; '
        f'python3 train.py --mode {mode} --data-dir {remote_dir}/data'
    )

    cmd = [
        'ssh', *ssh_opts.split(),
        f'{config.ssh_user}@{config.ssh_host}',
        remote_cmd,
    ]

    # Stream output with timeout (2h for LLM training)
    timeout = 7200 if run.train_llm else 600
    run.append_log(f"SSH command: {remote_cmd}")

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    output_lines = []
    start = time.time()
    for line in process.stdout:
        line = line.rstrip()
        output_lines.append(line)
        # Log progress lines (every 10th or important ones)
        if any(kw in line.lower() for kw in ['step', 'iter', 'accuracy', 'error', 'fail', 'complete', '===']):
            run.append_log(line)
        # Update step based on output
        if 'LLM' in line and 'Step' in line and run.step != 'training_llm':
            run.step = 'training_llm'
            run.save(update_fields=['step'])

        if time.time() - start > timeout:
            process.kill()
            raise RuntimeError(f"Remote training timed out after {timeout}s")

    process.wait()
    if process.returncode != 0:
        tail = '\n'.join(output_lines[-20:])
        raise RuntimeError(f"Remote training failed (exit {process.returncode}):\n{tail}")

    run.append_log("Remote training completed successfully")


def sync_models_back(run, config):
    """rsync trained models from remote back to local."""
    run.step = 'syncing_models'
    run.save(update_fields=['step'])
    run.append_log("Syncing trained models back...")

    ssh_opts = _ssh_opts(config)
    remote_data = f"{config.ssh_user}@{config.ssh_host}:{config.remote_training_dir}/data/"
    local_dest = f'{LOCAL_EXPORT_DIR}/'

    cmd = [
        'rsync', '-avz', '--progress',
        '-e', f'ssh {ssh_opts}',
        remote_data,
        local_dest,
    ]
    result = _run(cmd, timeout=300, log_run=run)

    if result.returncode != 0:
        raise RuntimeError(f"rsync from remote failed: {result.stderr[:500]}")

    run.append_log("Models synced back successfully")


def load_trained_models(run):
    """Load trained models into the running system."""
    run.step = 'loading_models'
    run.save(update_fields=['step'])
    run.append_log("Loading trained models...")

    models_dir = os.path.join(LOCAL_EXPORT_DIR, 'models')
    result_path = os.path.join(LOCAL_EXPORT_DIR, 'training_result.json')

    # Read training results
    training_result = {}
    if os.path.exists(result_path):
        with open(result_path) as f:
            training_result = json.load(f)

    # Load XGBoost model
    xgb_result = training_result.get('xgboost', {})
    if xgb_result.get('success'):
        latest_model = os.path.join(models_dir, 'trade_scorer_latest.joblib')
        if os.path.exists(latest_model):
            # Copy to Docker model directory with version
            import shutil
            version = xgb_result.get('version', int(time.time()))
            dest = os.path.join(CONTAINER_MODEL_DIR, f'trade_scorer_v{version}.joblib')
            shutil.copy2(latest_model, dest)

            # Register in Django
            from app.nexus.models import MLModel
            MLModel.objects.update(is_active=False)
            # Store walk-forward accuracy inside feature_importance dict
            # (same pattern as trainer.py — MLModel has no walk_forward_accuracy field)
            fi = xgb_result.get('feature_importance', {})
            fi['_walk_forward_accuracy'] = xgb_result.get('walk_forward_accuracy', 0)
            MLModel.objects.create(
                version=version,
                model_type=xgb_result.get('model_type', 'xgboost'),
                trade_count=xgb_result.get('trade_count', 0),
                accuracy=xgb_result.get('accuracy', 0),
                cv_accuracy=xgb_result.get('cv_accuracy', 0),
                cv_std=xgb_result.get('cv_std', 0),
                precision=xgb_result.get('precision', 0),
                recall=xgb_result.get('recall', 0),
                f1_score=xgb_result.get('f1_score', 0),
                feature_importance=fi,
                model_path=dest,
                is_active=True,
                win_rate_baseline=xgb_result.get('win_rate_baseline', 0),
            )
            run.append_log(f"XGBoost v{version} loaded: {xgb_result['accuracy']:.1%} accuracy")
            run.xgboost_result = xgb_result
        else:
            run.append_log("WARNING: XGBoost model file not found after sync")
    else:
        run.append_log(f"XGBoost: {xgb_result.get('error', 'not trained')}")

    # LLM model — register in Ollama on the Mac mini host
    llm_result = training_result.get('llm', {})
    if llm_result.get('success'):
        fused_dir = os.path.join(LOCAL_EXPORT_DIR, 'llm', 'fused')
        if os.path.exists(fused_dir):
            run.append_log("Registering LLM in Ollama...")
            try:
                version = llm_result.get('version', datetime.now().strftime('%Y%m%d_%H%M'))
                modelfile = os.path.join(fused_dir, 'Modelfile')

                if os.path.exists(modelfile):
                    # Use host.docker.internal to reach host Ollama from Docker
                    # But we need to run ollama create on the HOST, not in Docker
                    # Write a trigger file for the host to pick up
                    trigger = {
                        'fused_dir': fused_dir,
                        'version': version,
                        'modelfile': modelfile,
                        'timestamp': datetime.now().isoformat(),
                    }
                    trigger_path = os.path.join(CONTAINER_MODEL_DIR, 'ollama_register_trigger.json')
                    with open(trigger_path, 'w') as f:
                        json.dump(trigger, f)
                    run.append_log(f"LLM v{version} ready — Ollama registration trigger created")
                    run.append_log("NOTE: Run on host: ollama create trade-brain:latest -f <modelfile>")
                else:
                    run.append_log("WARNING: LLM Modelfile not found")
            except Exception as e:
                run.append_log(f"LLM Ollama registration error: {e}")
        else:
            run.append_log("WARNING: LLM fused model directory not found after sync")

        run.llm_result = llm_result
    else:
        run.append_log(f"LLM: {llm_result.get('error', 'not trained')}")

    run.save(update_fields=['xgboost_result', 'llm_result'])


def execute_training(run_id):
    """Main orchestrator — called from Celery task."""
    from app.nexus.models import TrainingConfig, TrainingRun
    from django.utils import timezone

    run = TrainingRun.objects.get(pk=run_id)
    config = TrainingConfig.load()

    run.status = 'running'
    run.mode = config.mode
    run.save(update_fields=['status', 'mode'])
    run.append_log(f"Training started (mode={config.mode})")

    try:
        # Step 1: Export data
        export_result = export_training_data(run)

        if config.mode == 'remote':
            # Step 2: Sync to remote
            sync_data_to_remote(run, config)

            # Step 3: Run training remotely
            run_training_on_remote(run, config)

            # Step 4: Sync models back
            sync_models_back(run, config)
        else:
            # Local mode — future Mac Studio
            run.append_log("Local training mode — running train.py locally...")
            run.step = 'training_xgboost'
            run.save(update_fields=['step'])

            mode = 'all'
            if run.train_xgboost and not run.train_llm:
                mode = 'xgboost'
            elif run.train_llm and not run.train_xgboost:
                mode = 'llm'

            cmd = ['python3', '/app/training/train.py', '--mode', mode, '--data-dir', LOCAL_EXPORT_DIR]
            result = _run(cmd, timeout=7200, log_run=run)
            if result.returncode != 0:
                raise RuntimeError(f"Local training failed: {result.stderr[:500]}")

        # Step 5: Load models
        load_trained_models(run)

        run.step = 'done'
        run.status = 'success'
        run.completed_at = timezone.now()
        run.save(update_fields=['step', 'status', 'completed_at'])
        run.append_log("=== Training pipeline completed successfully ===")

    except Exception as e:
        logger.exception("Training failed")
        run.status = 'failed'
        run.error = str(e)
        run.completed_at = timezone.now()
        run.save(update_fields=['status', 'error', 'completed_at'])
        run.append_log(f"FAILED: {e}")


def _ssh_opts(config):
    """Build SSH options string."""
    opts = f'-o StrictHostKeyChecking=no -o ConnectTimeout=10 -p {config.ssh_port}'
    if config.ssh_key_path:
        key = os.path.expanduser(config.ssh_key_path)
        opts += f' -i {key}'
    return opts
