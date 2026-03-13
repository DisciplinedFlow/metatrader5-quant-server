"""
LLM Fine-Tuning Pipeline — Local Llama 3.2 3B on Apple Silicon

Pipeline:
1. Export JSONL from Django DB → MLX chat format
2. LoRA fine-tune with MLX (native M4 Metal acceleration)
3. Fuse LoRA weights into base model
4. Convert fused model to GGUF
5. Register in Ollama as 'trade-brain-v{N}'

This module runs on the HOST (not in Docker) for Metal GPU access.
Django calls it via subprocess or management command.
"""
import json
import logging
import os
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

logger = logging.getLogger('app.quant.ml.llm')


def export_training_data(jsonl_path, output_dir, test_split=0.1):
    """Convert Django JSONL training data to MLX chat format.

    MLX expects JSONL with {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    examples = []
    with open(jsonl_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                # Convert to MLX chat format
                messages = [
                    {"role": "system", "content": data.get('system', '')},
                    {"role": "user", "content": f"{data.get('instruction', '')}\n\n{data.get('input', '')}"},
                    {"role": "assistant", "content": data.get('output', '')},
                ]
                examples.append({"messages": messages})
            except json.JSONDecodeError:
                continue

    if not examples:
        logger.error("No training examples found")
        return None

    # Shuffle deterministically
    import hashlib
    examples.sort(key=lambda x: hashlib.md5(json.dumps(x, sort_keys=True).encode()).hexdigest())

    # Split into train/valid/test
    n = len(examples)
    n_test = max(1, int(n * test_split))
    n_valid = max(1, int(n * test_split))

    test_data = examples[:n_test]
    valid_data = examples[n_test:n_test + n_valid]
    train_data = examples[n_test + n_valid:]

    # Write splits
    for name, data in [('train', train_data), ('valid', valid_data), ('test', test_data)]:
        path = output_dir / f'{name}.jsonl'
        with open(path, 'w') as f:
            for ex in data:
                f.write(json.dumps(ex) + '\n')
        logger.info(f"Wrote {len(data)} examples to {path}")

    return {
        'total': n,
        'train': len(train_data),
        'valid': len(valid_data),
        'test': len(test_data),
        'output_dir': str(output_dir),
    }


def run_lora_finetune(
    model_name='Qwen/Qwen2.5-3B-Instruct',
    data_dir='~/ml_models/llm/training_data',
    adapters_dir='~/ml_models/llm/adapters',
    iters=500,
    batch_size=1,
    lora_layers=8,
    lora_rank=16,
    learning_rate=1e-5,
):
    """Run MLX LoRA fine-tuning on the host Mac.

    Requires mlx-lm to be installed: pip install mlx-lm
    """
    import yaml

    data_dir = os.path.expanduser(data_dir)
    adapters_dir = os.path.expanduser(adapters_dir)
    os.makedirs(adapters_dir, exist_ok=True)

    # mlx-lm 0.29+ uses YAML config for lora_parameters
    config = {
        'model': model_name,
        'data': data_dir,
        'train': True,
        'iters': iters,
        'batch_size': batch_size,
        'num_layers': lora_layers,
        'learning_rate': learning_rate,
        'adapter_path': adapters_dir,
        'save_every': 100,
        'steps_per_report': 10,
        'steps_per_eval': 100,
        'max_seq_length': 1024,
        'lora_parameters': {
            'rank': lora_rank,
            'dropout': 0.05,
            'scale': 20.0,
        },
    }
    config_path = os.path.join(adapters_dir, 'train_config.yaml')
    with open(config_path, 'w') as f:
        yaml.dump(config, f)

    cmd = ['python3', '-m', 'mlx_lm.lora', '-c', config_path]
    logger.info(f"Starting LoRA fine-tune with config: {config_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)

    if result.returncode != 0:
        logger.error(f"LoRA training failed: {result.stderr}")
        return None

    logger.info(f"LoRA training complete:\n{result.stdout[-500:]}")
    return {
        'adapters_dir': adapters_dir,
        'stdout': result.stdout[-1000:],
        'success': True,
    }


def fuse_model(
    model_name='Qwen/Qwen2.5-3B-Instruct',
    adapters_dir='~/ml_models/llm/adapters',
    fused_dir='~/ml_models/llm/fused',
):
    """Fuse LoRA adapters into the base model."""
    adapters_dir = os.path.expanduser(adapters_dir)
    fused_dir = os.path.expanduser(fused_dir)

    # Clean previous fused model
    if os.path.exists(fused_dir):
        shutil.rmtree(fused_dir)
    os.makedirs(fused_dir, exist_ok=True)

    cmd = [
        'python3', '-m', 'mlx_lm.fuse',
        '--model', model_name,
        '--adapter-path', adapters_dir,
        '--save-path', fused_dir,
    ]

    logger.info(f"Fusing LoRA weights: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        logger.error(f"Fuse failed: {result.stderr}")
        return None

    logger.info("Model fused successfully")
    return {'fused_dir': fused_dir, 'success': True}


def convert_to_gguf(fused_dir='~/ml_models/llm/fused', output_path=None):
    """Convert fused HuggingFace model to GGUF format for Ollama.

    Uses llama-cpp-python's conversion tool or mlx_lm.convert.
    """
    fused_dir = os.path.expanduser(fused_dir)
    if output_path is None:
        output_path = os.path.join(fused_dir, 'trade-brain.gguf')

    # Try using llama.cpp convert script
    # First try: python convert_hf_to_gguf.py
    try:
        cmd = [
            'python3', '-m', 'llama_cpp.convert',
            '--outtype', 'q4_k_m',
            '--outfile', output_path,
            fused_dir,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            logger.info(f"GGUF conversion complete: {output_path}")
            return {'gguf_path': output_path, 'success': True}
    except Exception:
        pass

    # Fallback: try convert-hf-to-gguf.py from llama.cpp
    try:
        # Find the convert script
        import site
        for sp in site.getsitepackages():
            script = os.path.join(sp, 'llama_cpp', 'convert_hf_to_gguf.py')
            if os.path.exists(script):
                cmd = ['python3', script, fused_dir, '--outtype', 'q4_k_m', '--outfile', output_path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if result.returncode == 0:
                    return {'gguf_path': output_path, 'success': True}
    except Exception:
        pass

    logger.error("GGUF conversion failed — install llama-cpp-python: pip install llama-cpp-python")
    return None


def register_in_ollama(
    gguf_path,
    model_name='trade-brain',
    version=None,
    ollama_host='http://localhost:11434',
):
    """Create an Ollama model from the GGUF file using a Modelfile."""
    from . import llm_config

    if version is None:
        version = datetime.now().strftime('%Y%m%d_%H%M')

    versioned_name = f"{model_name}:v{version}"

    # Create Modelfile
    modelfile_content = f'''FROM {gguf_path}

SYSTEM """{llm_config.TRADE_SYSTEM_PROMPT}"""

PARAMETER temperature {llm_config.LLM_SCORE_TEMPERATURE}
PARAMETER num_predict {llm_config.LLM_SCORE_MAX_TOKENS}
PARAMETER stop "REASONING:"
'''

    modelfile_path = os.path.join(os.path.dirname(gguf_path), 'Modelfile')
    with open(modelfile_path, 'w') as f:
        f.write(modelfile_content)

    # Register with Ollama
    cmd = ['ollama', 'create', versioned_name, '-f', modelfile_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        logger.error(f"Ollama create failed: {result.stderr}")
        return None

    # Also tag as latest
    cmd_tag = ['ollama', 'cp', versioned_name, f"{model_name}:latest"]
    subprocess.run(cmd_tag, capture_output=True, text=True, timeout=60)

    logger.info(f"Registered Ollama model: {versioned_name}")
    return {'model_name': versioned_name, 'latest': f"{model_name}:latest", 'success': True}


def run_full_pipeline(jsonl_path=None):
    """Run the complete fine-tuning pipeline.

    Called from the host Mac (not Docker) via management command or script.

    1. Export & convert training data
    2. LoRA fine-tune with MLX
    3. Fuse weights
    4. Convert to GGUF
    5. Register in Ollama
    """
    from . import llm_config

    if jsonl_path is None:
        jsonl_path = os.path.join(llm_config.LLM_TRAINING_DATA_DIR, 'trade_analyses.jsonl')

    results = {'started_at': datetime.now().isoformat()}

    # Step 1: Export training data
    logger.info("=== Step 1: Exporting training data ===")
    export_result = export_training_data(
        jsonl_path=jsonl_path,
        output_dir=llm_config.LLM_TRAINING_DATA_DIR,
    )
    if not export_result:
        return {**results, 'error': 'Export failed', 'step': 1}
    results['export'] = export_result

    # Step 2: LoRA fine-tune
    logger.info("=== Step 2: LoRA fine-tuning ===")
    train_result = run_lora_finetune(
        model_name=llm_config.MLX_MODEL_HF,
        data_dir=llm_config.LLM_TRAINING_DATA_DIR,
        adapters_dir=llm_config.LLM_ADAPTERS_DIR,
        iters=llm_config.MLX_TRAIN_ITERS,
        batch_size=llm_config.MLX_BATCH_SIZE,
        lora_layers=llm_config.MLX_LORA_LAYERS,
        lora_rank=llm_config.MLX_LORA_RANK,
        learning_rate=llm_config.MLX_LEARNING_RATE,
    )
    if not train_result:
        return {**results, 'error': 'Training failed', 'step': 2}
    results['training'] = train_result

    # Step 3: Fuse
    logger.info("=== Step 3: Fusing LoRA weights ===")
    fuse_result = fuse_model(
        model_name=llm_config.MLX_MODEL_HF,
        adapters_dir=llm_config.LLM_ADAPTERS_DIR,
        fused_dir=llm_config.LLM_FUSED_DIR,
    )
    if not fuse_result:
        return {**results, 'error': 'Fuse failed', 'step': 3}
    results['fuse'] = fuse_result

    # Step 4: Convert to GGUF
    logger.info("=== Step 4: Converting to GGUF ===")
    gguf_result = convert_to_gguf(fused_dir=llm_config.LLM_FUSED_DIR)
    if not gguf_result:
        return {**results, 'error': 'GGUF conversion failed', 'step': 4}
    results['gguf'] = gguf_result

    # Step 5: Register in Ollama
    logger.info("=== Step 5: Registering in Ollama ===")
    register_result = register_in_ollama(
        gguf_path=gguf_result['gguf_path'],
        model_name=llm_config.OLLAMA_TRADE_MODEL,
    )
    if not register_result:
        return {**results, 'error': 'Ollama registration failed', 'step': 5}
    results['ollama'] = register_result

    results['completed_at'] = datetime.now().isoformat()
    results['success'] = True
    logger.info(f"=== Pipeline complete: {register_result['model_name']} ===")
    return results


def get_training_status():
    """Get current training pipeline status (callable from Django)."""
    from . import llm_config

    status = {
        'llm_enabled': llm_config.LLM_ENABLED,
        'base_model': llm_config.OLLAMA_BASE_MODEL,
        'trade_model': llm_config.OLLAMA_TRADE_MODEL,
    }

    # Check if trade-brain model exists in Ollama
    try:
        import requests
        resp = requests.get(
            f"{llm_config.OLLAMA_HOST}/api/tags",
            timeout=5,
        )
        if resp.ok:
            models = resp.json().get('models', [])
            brain_models = [m for m in models if llm_config.OLLAMA_TRADE_MODEL in m['name']]
            status['ollama_available'] = True
            status['trade_model_exists'] = len(brain_models) > 0
            if brain_models:
                latest = max(brain_models, key=lambda m: m.get('modified_at', ''))
                status['trade_model_version'] = latest['name']
                status['trade_model_size'] = latest['size']
        else:
            status['ollama_available'] = False
    except Exception:
        status['ollama_available'] = False

    # Check training data
    try:
        jsonl_path = '/app/ml_models/llm_training_data/trade_analyses.jsonl'
        if os.path.exists(jsonl_path):
            with open(jsonl_path) as f:
                count = sum(1 for _ in f)
            status['training_examples'] = count
            status['training_data_size_kb'] = os.path.getsize(jsonl_path) / 1024
        else:
            status['training_examples'] = 0
    except Exception:
        status['training_examples'] = 0

    return status
