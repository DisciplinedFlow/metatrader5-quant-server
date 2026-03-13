#!/bin/bash
# One-liner setup for the training machine (MacBook Pro / Mac Studio)
# Usage: bash setup.sh

set -e

echo "=== Quant Training Node Setup ==="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.11+."
    exit 1
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python: $PYVER"

# Check Apple Silicon
CHIP=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "unknown")
echo "Chip: $CHIP"

# Create venv
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q

echo ""
echo "=== Setup complete ==="
echo ""
echo "To activate: source $VENV_DIR/bin/activate"
echo "Training will be triggered remotely via SSH from the Mac mini."
echo ""

# Verify MLX
python3 -c "import mlx; print(f'MLX: {mlx.__version__}')" 2>/dev/null || echo "WARNING: MLX not available (not Apple Silicon?)"
python3 -c "import xgboost; print(f'XGBoost: {xgboost.__version__}')"
