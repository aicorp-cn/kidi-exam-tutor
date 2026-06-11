#!/bin/bash
# Exam Tutor v5 — Single Process Deployment
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$SCRIPT_DIR/agent"

echo "============================================"
echo "  Exam Tutor v5 — Startup"
echo "============================================"

# Check tesseract
echo ""
echo "[1/3] Checking tesseract..."
if ! command -v tesseract &>/dev/null; then
    echo "  tesseract not found. Installing..."
    sudo apt-get install -y tesseract-ocr tesseract-ocr-eng
fi
echo "  $(tesseract --version | head -1)"

# Pre-flight config validation
echo ""
echo "[2/3] Validating configuration..."
cd "$SCRIPT_DIR"
python3 -c "from agent.config import validate; validate()"

# Start
echo ""
echo "[3/3] Starting Agent..."
echo "  Config: $SCRIPT_DIR/config.yaml"
echo "  Web UI: http://localhost:8080"
echo "  API:    http://localhost:8080/exams"
echo ""

cd "$AGENT_DIR"
exec python3 main.py
