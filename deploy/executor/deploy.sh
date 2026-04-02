#!/usr/bin/env bash
# deploy.sh — One-command local deploy: SCP all executor files to Oracle VM,
# then run VM-side setup (venv, deps, systemd service install).
#
# Usage (from repo root):
#   bash deploy/executor/deploy.sh
#
# Requirements:
#   - SSH key at ~/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key
#   - pyproject.toml and src/ta_lab2/ at repo root

set -euo pipefail

SSH_KEY=~/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key
VM_USER=ubuntu
VM_HOST=161.118.209.59
VM_DIR=/home/ubuntu/executor
SCP_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new"

echo "=== Deploying TA Lab2 Executor to Oracle VM ($VM_HOST) ==="

# ── 1. Ensure VM executor directory exists ────────────────────────────
echo "[1/4] Creating VM directory..."
ssh $SSH_OPTS $VM_USER@$VM_HOST "mkdir -p $VM_DIR"

# ── 2. SCP executor deploy files ─────────────────────────────────────
echo "[2/4] Copying executor files..."
scp $SCP_OPTS \
    deploy/executor/executor_service.py \
    deploy/executor/requirements.txt \
    deploy/executor/setup_vm.sh \
    deploy/executor/ta-executor.service \
    deploy/executor/vm_table_list.txt \
    deploy/executor/create_vm_tables.sh \
    $VM_USER@$VM_HOST:$VM_DIR/

# ── 3. Build wheel locally and SCP it (single file, no research artifacts) ─
echo "[3/4] Building and copying ta_lab2 wheel..."
python -m build --wheel --outdir dist/ 2>/dev/null || \
    "/c/Program Files/Python312/python.exe" -m build --wheel --outdir dist/ 2>/dev/null || \
    { echo "ERROR: 'python -m build' failed. Install: pip install build"; exit 1; }
WHEEL=$(ls -t dist/ta_lab2-*.whl 2>/dev/null | head -1)
if [ -z "$WHEEL" ]; then
    echo "ERROR: No wheel found in dist/"
    exit 1
fi
echo "  Built: $WHEEL"
scp $SCP_OPTS "$WHEEL" $VM_USER@$VM_HOST:$VM_DIR/

# ── 4. Run VM-side setup ──────────────────────────────────────────────
echo "[4/4] Running VM setup..."
ssh $SSH_OPTS $VM_USER@$VM_HOST \
    "cd $VM_DIR && chmod +x setup_vm.sh create_vm_tables.sh && ./setup_vm.sh"

echo ""
echo "=== Deploy complete ==="
echo ""
echo "NEXT STEPS:"
echo "  1. Create VM tables:"
echo "       bash deploy/executor/create_vm_tables.sh"
echo ""
echo "  2. Push initial signals to VM:"
echo "       python -m ta_lab2.scripts.etl.sync_signals_to_vm --full"
echo ""
echo "  3. Push executor config to VM:"
echo "       python -m ta_lab2.scripts.etl.sync_config_to_vm"
echo ""
echo "  4. Start the executor:"
echo "       ssh $SSH_OPTS $VM_USER@$VM_HOST 'sudo systemctl start ta-executor'"
echo ""
echo "  5. Verify it's running:"
echo "       ssh $SSH_OPTS $VM_USER@$VM_HOST 'sudo systemctl status ta-executor'"
echo ""
echo "  6. Tail logs:"
echo "       ssh $SSH_OPTS $VM_USER@$VM_HOST 'journalctl -u ta-executor --no-pager -n 50'"
