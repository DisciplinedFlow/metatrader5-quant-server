"""Configuration for local LLM fine-tuning and inference pipeline."""
import os

# Ollama settings
OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://host.docker.internal:11434')
OLLAMA_HOST_NATIVE = os.getenv('OLLAMA_HOST_NATIVE', 'http://localhost:11434')  # for host-side scripts
OLLAMA_BASE_MODEL = os.getenv('OLLAMA_BASE_MODEL', 'llama3.2:latest')
OLLAMA_TRADE_MODEL = os.getenv('OLLAMA_TRADE_MODEL', 'trade-brain')
OLLAMA_TIMEOUT = int(os.getenv('OLLAMA_TIMEOUT', '120'))  # seconds

# MLX fine-tuning settings (runs on host, not in Docker)
MLX_MODEL_HF = os.getenv('MLX_MODEL_HF', 'Qwen/Qwen2.5-7B-Instruct')
MLX_LORA_LAYERS = int(os.getenv('MLX_LORA_LAYERS', '8'))
MLX_LORA_RANK = int(os.getenv('MLX_LORA_RANK', '16'))
MLX_TRAIN_ITERS = int(os.getenv('MLX_TRAIN_ITERS', '500'))
MLX_BATCH_SIZE = int(os.getenv('MLX_BATCH_SIZE', '1'))
MLX_LEARNING_RATE = float(os.getenv('MLX_LEARNING_RATE', '1e-5'))
MLX_WARMUP_STEPS = int(os.getenv('MLX_WARMUP_STEPS', '50'))

# Paths (host-side, not Docker paths)
LLM_MODELS_DIR = os.getenv('LLM_MODELS_DIR', os.path.expanduser('~/ml_models/llm'))
LLM_TRAINING_DATA_DIR = os.getenv('LLM_TRAINING_DATA_DIR', os.path.expanduser('~/ml_models/llm/training_data'))
LLM_ADAPTERS_DIR = os.getenv('LLM_ADAPTERS_DIR', os.path.expanduser('~/ml_models/llm/adapters'))
LLM_FUSED_DIR = os.getenv('LLM_FUSED_DIR', os.path.expanduser('~/ml_models/llm/fused'))

# Retraining triggers
RETRAIN_MIN_NEW_TRADES = int(os.getenv('LLM_RETRAIN_MIN_TRADES', '50'))
RETRAIN_INTERVAL_HOURS = int(os.getenv('LLM_RETRAIN_INTERVAL_HOURS', '24'))

# Inference settings
LLM_SCORE_TEMPERATURE = float(os.getenv('LLM_SCORE_TEMPERATURE', '0.3'))
LLM_SCORE_MAX_TOKENS = int(os.getenv('LLM_SCORE_MAX_TOKENS', '80'))   # 3-line format only: DECISION+CONFIDENCE+REASONING
LLM_ENABLED = os.getenv('LLM_ENABLED', 'false').lower() == 'true'

# Trade reasoning system prompt
TRADE_SYSTEM_PROMPT = """Forex trade quality filter. ACCEPT if: confluence>=5 AND HTF aligned AND streak>=0 AND WR>=45%. REJECT otherwise."""
