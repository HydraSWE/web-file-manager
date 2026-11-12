#!/usr/bin/env bash
# Web File Manager - Cross-Platform Linux/macOS Startup Script

set -e
cd "$(dirname "$0")"

# Check Python command
if [ -f "./.venv/bin/python" ]; then
    PYTHON_CMD="./.venv/bin/python"
elif [ -f "./venv/bin/python" ]; then
    PYTHON_CMD="./venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python 3 not found. Please install Python 3.10+."
    exit 1
fi

APP_TITLE="${APP_NAME:-Web File Manager}"

echo "========================================================"
echo "  $APP_TITLE"
echo "  Using Python: $($PYTHON_CMD --version)"
echo "========================================================"
echo ""

# 1. Self-healing configuration template check
if [ ! -f "config.json" ] && [ -f "config.example.json" ]; then
    echo "[HYDRA] First-time setup: Initializing config.json from template..."
    cp config.example.json config.json
fi

# 2. Pre-flight dependency check & binary-preferred installation
if ! $PYTHON_CMD -c "import fastapi, uvicorn, qrcode, multipart, cryptography, argon2, aiofiles" &>/dev/null; then
    echo "[HYDRA] Missing dependencies detected. Installing required packages..."
    $PYTHON_CMD -m pip install --prefer-binary -r requirements.txt || \
    $PYTHON_CMD -m pip install --only-binary :all: -r requirements.txt

    if ! $PYTHON_CMD -c "import fastapi, uvicorn, qrcode, multipart, cryptography, argon2, aiofiles" &>/dev/null; then
        echo ""
        echo "[ERROR] Failed to install required dependencies."
        echo "Please install manually by running: pip install --prefer-binary -r requirements.txt"
        exit 1
    fi
    echo "[HYDRA] Dependencies verified successfully."
    echo ""
fi

# Launch server
exec $PYTHON_CMD server.py
