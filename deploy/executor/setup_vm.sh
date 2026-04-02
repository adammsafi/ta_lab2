#!/usr/bin/env bash
# setup_vm.sh — One-time setup for TA Lab2 Executor on Oracle Singapore VM.
#
# Run locally (via deploy.sh):
#   scp -i ~/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key \
#       deploy/executor/executor_service.py \
#       deploy/executor/requirements.txt \
#       deploy/executor/setup_vm.sh \
#       deploy/executor/ta-executor.service \
#       ubuntu@161.118.209.59:~/executor/
#
#   ssh -i ~/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key ubuntu@161.118.209.59 \
#       "cd ~/executor && chmod +x setup_vm.sh && ./setup_vm.sh"

set -euo pipefail

echo "=== TA Lab2 Executor VM Setup ==="

# ── 1. Create executor directory ──────────────────────────────────────
mkdir -p /home/ubuntu/executor
cd /home/ubuntu/executor

# ── 2. Python venv & deps ─────────────────────────────────────────────
echo "Setting up Python venv..."

if [ ! -d venv ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip

# ── 3. Install runtime requirements ──────────────────────────────────
echo "Installing requirements..."
pip install -r requirements.txt

# ── 4. Install ta_lab2 source package (editable install) ─────────────
if [ -d /home/ubuntu/executor/ta_lab2_src ]; then
    echo "Installing ta_lab2 package..."
    pip install -e /home/ubuntu/executor/ta_lab2_src/
else
    echo "WARNING: ta_lab2_src/ not found — re-run deploy.sh to copy source"
fi

# ── 5. Environment variables ──────────────────────────────────────────
if [ ! -f .env ]; then
    cat > .env <<'ENVEOF'
EXECUTOR_DB_URL=postgresql+psycopg2://hluser:hlpass@127.0.0.1:5432/hyperliquid
TELEGRAM_BOT_TOKEN=8590137517:AAFy7aSm05SInNOsUx6kmD6eWaLCgtkR2kg
TELEGRAM_CHAT_ID=5591688420
KRAKEN_SYMBOLS=
COINBASE_PRODUCT_IDS=
LOG_LEVEL=INFO
ENVEOF
    echo "Created .env"
else
    echo ".env already exists, skipping"
fi

# ── 6. Install systemd service ────────────────────────────────────────
echo "Installing systemd service..."
sudo cp /home/ubuntu/executor/ta-executor.service /etc/systemd/system/ta-executor.service
sudo systemctl daemon-reload
sudo systemctl enable ta-executor
echo "Systemd service installed and enabled (not yet started)"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Create tables:     bash /home/ubuntu/executor/create_vm_tables.sh"
echo "  2. Start service:     sudo systemctl start ta-executor"
echo "  3. Check status:      sudo systemctl status ta-executor"
echo "  4. View logs:         journalctl -u ta-executor -f"
