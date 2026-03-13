#!/usr/bin/env python3
"""
Standalone LLM retraining script — runs on host Mac (not Docker).

Usage:
    # Copy JSONL from Docker, then run:
    python3 retrain_llm.py

    # Or with custom paths:
    python3 retrain_llm.py --jsonl /path/to/trade_analyses.jsonl
"""
import argparse
import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path
from datetime import datetime

# Paths
DEFAULT_MODELS_DIR = os.path.expanduser('~/ml_models/llm')
DEFAULT_JSONL_CONTAINER_PATH = '/app/ml_models/llm_training_data/trade_analyses.jsonl'

# MLX settings
HF_MODEL = 'Qwen/Qwen2.5-7B-Instruct'
LORA_ITERS = 500
LORA_LAYERS = 8
LORA_RANK = 16
BATCH_SIZE = 1
LEARNING_RATE = 1e-5

# Ollama
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


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def step1_export_from_docker(output_path):
    """Copy JSONL from Django container to host."""
    log("Step 1: Exporting training data from Docker...")

    cmd = ['docker', 'cp', f'django:{DEFAULT_JSONL_CONTAINER_PATH}', output_path]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        log(f"  ERROR: {result.stderr}")
        return False

    # Count examples
    with open(output_path) as f:
        count = sum(1 for _ in f)
    log(f"  Exported {count} training examples ({os.path.getsize(output_path) / 1024:.0f} KB)")
    return True


def step2_convert_to_mlx_format(jsonl_path, output_dir):
    """Convert JSONL to MLX chat training format."""
    log("Step 2: Converting to MLX format...")

    os.makedirs(output_dir, exist_ok=True)

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
        path = os.path.join(output_dir, f'{name}.jsonl')
        with open(path, 'w') as f:
            for ex in data:
                f.write(json.dumps(ex) + '\n')
        log(f"  {name}: {len(data)} examples")

    return True


def step3_lora_finetune(data_dir, adapters_dir):
    """Run MLX LoRA fine-tuning."""
    log(f"Step 3: LoRA fine-tuning ({LORA_ITERS} iterations)...")
    log(f"  Model: {HF_MODEL}")
    log(f"  LoRA rank: {LORA_RANK}, layers: {LORA_LAYERS}")

    os.makedirs(adapters_dir, exist_ok=True)

    # Write YAML config (mlx-lm 0.29+ uses config file for lora_parameters)
    import yaml
    config = {
        'model': HF_MODEL,
        'data': data_dir,
        'train': True,
        'iters': LORA_ITERS,
        'batch_size': BATCH_SIZE,
        'num_layers': LORA_LAYERS,
        'learning_rate': LEARNING_RATE,
        'adapter_path': adapters_dir,
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
    config_path = os.path.join(adapters_dir, 'train_config.yaml')
    with open(config_path, 'w') as f:
        yaml.dump(config, f)

    cmd = [sys.executable, '-m', 'mlx_lm.lora', '-c', config_path]
    log(f"  Config: {config_path}")

    # Stream output
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    last_lines = []
    for line in process.stdout:
        line = line.strip()
        if line:
            last_lines.append(line)
            last_lines = last_lines[-20:]  # keep last 20 lines
            # Print progress lines
            if 'Iter' in line or 'loss' in line.lower() or 'val' in line.lower():
                log(f"  {line}")

    process.wait()
    if process.returncode != 0:
        log(f"  ERROR: Training failed (exit code {process.returncode})")
        for line in last_lines:
            log(f"  {line}")
        return False

    log("  Training complete!")
    return True


def step4_fuse_model(adapters_dir, fused_dir):
    """Fuse LoRA adapters into base model."""
    log("Step 4: Fusing LoRA weights...")

    import shutil
    if os.path.exists(fused_dir):
        shutil.rmtree(fused_dir)
    os.makedirs(fused_dir, exist_ok=True)

    cmd = [
        sys.executable, '-m', 'mlx_lm.fuse',
        '--model', HF_MODEL,
        '--adapter-path', adapters_dir,
        '--save-path', fused_dir,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        log(f"  ERROR: Fuse failed: {result.stderr}")
        return False

    log(f"  Fused model saved to {fused_dir}")
    return True


def step5_create_ollama_model(fused_dir):
    """Convert to GGUF and register in Ollama."""
    log("Step 5: Creating Ollama model...")

    version = datetime.now().strftime('%Y%m%d_%H%M')
    model_tag = f"{OLLAMA_MODEL_NAME}:v{version}"

    # Create Modelfile pointing to the fused HF model directory
    # Ollama can import from HF safetensors directly (v0.17+)
    modelfile_path = os.path.join(fused_dir, 'Modelfile')
    with open(modelfile_path, 'w') as f:
        f.write(f'FROM {fused_dir}\n\n')
        f.write(f'SYSTEM """{SYSTEM_PROMPT}"""\n\n')
        f.write(f'PARAMETER temperature 0.3\n')
        f.write(f'PARAMETER num_predict 512\n')

    cmd = ['ollama', 'create', model_tag, '-f', modelfile_path]
    log(f"  Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        log(f"  ERROR: Ollama create failed: {result.stderr}")
        # Try alternative: convert to GGUF first
        log("  Trying GGUF conversion fallback...")
        return step5_gguf_fallback(fused_dir, version)

    # Tag as latest
    subprocess.run(['ollama', 'cp', model_tag, f'{OLLAMA_MODEL_NAME}:latest'],
                    capture_output=True, text=True)

    log(f"  Registered: {model_tag} (also tagged as {OLLAMA_MODEL_NAME}:latest)")
    return True


def step5_gguf_fallback(fused_dir, version):
    """Fallback: convert to GGUF then import."""
    try:
        gguf_path = os.path.join(fused_dir, f'{OLLAMA_MODEL_NAME}.gguf')

        # Try llama-cpp-python conversion
        cmd = [
            sys.executable, '-c',
            f'from llama_cpp import convert; convert.main(["--outtype", "q4_k_m", "--outfile", "{gguf_path}", "{fused_dir}"])'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            log(f"  GGUF conversion not available. Install: pip install llama-cpp-python")
            return False

        # Create Modelfile from GGUF
        model_tag = f"{OLLAMA_MODEL_NAME}:v{version}"
        modelfile_path = os.path.join(fused_dir, 'Modelfile.gguf')
        with open(modelfile_path, 'w') as f:
            f.write(f'FROM {gguf_path}\n\n')
            f.write(f'SYSTEM """{SYSTEM_PROMPT}"""\n\n')
            f.write(f'PARAMETER temperature 0.3\n')
            f.write(f'PARAMETER num_predict 512\n')

        cmd = ['ollama', 'create', model_tag, '-f', modelfile_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            log(f"  ERROR: GGUF import failed: {result.stderr}")
            return False

        subprocess.run(['ollama', 'cp', model_tag, f'{OLLAMA_MODEL_NAME}:latest'],
                        capture_output=True, text=True)
        log(f"  Registered (via GGUF): {model_tag}")
        return True
    except Exception as e:
        log(f"  GGUF fallback failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Retrain trade-brain LLM')
    parser.add_argument('--jsonl', help='Path to JSONL file (skips Docker export)')
    parser.add_argument('--skip-export', action='store_true', help='Skip Docker export step')
    parser.add_argument('--models-dir', default=DEFAULT_MODELS_DIR)
    args = parser.parse_args()

    models_dir = Path(args.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = args.jsonl or str(models_dir / 'trade_analyses.jsonl')
    data_dir = str(models_dir / 'training_data')
    adapters_dir = str(models_dir / 'adapters')
    fused_dir = str(models_dir / 'fused')

    log("=" * 60)
    log("TRADE-BRAIN LLM RETRAINING PIPELINE")
    log("=" * 60)

    # Step 1: Export from Docker
    if not args.skip_export and not args.jsonl:
        if not step1_export_from_docker(jsonl_path):
            log("FAILED at step 1")
            sys.exit(1)
    else:
        log(f"Step 1: Using existing JSONL at {jsonl_path}")

    # Step 2: Convert format
    if not step2_convert_to_mlx_format(jsonl_path, data_dir):
        log("FAILED at step 2")
        sys.exit(1)

    # Step 3: LoRA fine-tune
    if not step3_lora_finetune(data_dir, adapters_dir):
        log("FAILED at step 3")
        sys.exit(1)

    # Step 4: Fuse
    if not step4_fuse_model(adapters_dir, fused_dir):
        log("FAILED at step 4")
        sys.exit(1)

    # Step 5: Ollama
    if not step5_create_ollama_model(fused_dir):
        log("FAILED at step 5")
        sys.exit(1)

    log("")
    log("=" * 60)
    log("SUCCESS! trade-brain model registered in Ollama")
    log(f"Test with: ollama run {OLLAMA_MODEL_NAME}:latest")
    log("=" * 60)


if __name__ == '__main__':
    main()
