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

# Check dependencies
if ! $PYTHON_CMD -c "import fastapi, uvicorn, qrcode, multipart" &>/dev/null; then
    echo "Installing required dependencies..."
    $PYTHON_CMD -m pip install -r requirements.txt
    echo ""
fi

# Launch server
exec $PYTHON_CMD server.py
