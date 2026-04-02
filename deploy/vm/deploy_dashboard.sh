#!/usr/bin/env bash
# deploy_dashboard.sh -- Master deployment orchestrator for the hosted dashboard.
#
# Usage:
#   bash deploy/vm/deploy_dashboard.sh <domain>              # Full deploy
#   bash deploy/vm/deploy_dashboard.sh <domain> --code-only  # Rsync + data sync only
#   bash deploy/vm/deploy_dashboard.sh <domain> --data-only  # Data sync only
#
# Pre-requisites:
#   1. DNS A record for <domain> points to 161.118.209.59
#   2. OCI Security List allows TCP inbound on ports 80 and 443
#   3. SSH key at ~/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key
#   4. Local ta_lab2 env active (for sync_dashboard_to_vm)

set -euo pipefail

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
DOMAIN="${1:?Usage: $0 <domain> [--code-only|--data-only]}"
MODE="${2:-full}"

CODE_ONLY=false
DATA_ONLY=false
case "$MODE" in
  --code-only) CODE_ONLY=true ;;
  --data-only) DATA_ONLY=true ;;
  full) ;;
  *) echo "Unknown flag: $MODE. Use --code-only or --data-only." >&2; exit 1 ;;
esac

# ---------------------------------------------------------------------------
# VM constants (matching sync scripts)
# ---------------------------------------------------------------------------
VM_HOST=161.118.209.59
VM_USER=ubuntu
# Resolve SSH key: try multiple paths (Git Bash, WSL, env var, $HOME)
_WIN_KEY="/mnt/c/Users/asafi/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key"
_WSL_KEY="$HOME/.ssh/oracle_sg_vm.key"
_GITBASH_KEY="/c/Users/asafi/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key"

if [[ -n "${SSH_KEY:-}" && -f "$SSH_KEY" ]]; then
  : # SSH_KEY already set via env var
elif [[ -f "$_WSL_KEY" ]]; then
  SSH_KEY="$_WSL_KEY"
elif [[ -f "$_WIN_KEY" ]]; then
  # WSL mounts Windows files as 0777; SSH rejects that. Copy to WSL with safe perms.
  echo "Copying SSH key to WSL home with correct permissions..."
  mkdir -p "$HOME/.ssh"
  cp "$_WIN_KEY" "$_WSL_KEY"
  chmod 600 "$_WSL_KEY"
  SSH_KEY="$_WSL_KEY"
elif [[ -f "$_GITBASH_KEY" ]]; then
  SSH_KEY="$_GITBASH_KEY"
elif [[ -f "$HOME/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key" ]]; then
  SSH_KEY="$HOME/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key"
else
  echo "ERROR: SSH key not found. Set SSH_KEY env var before running."
  echo "  export SSH_KEY=/path/to/ssh-key-2026-03-10.key"
  exit 1
fi
REMOTE_DIR=/opt/ta_lab2

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[$(date -u '+%H:%M:%S')] $*"; }
step() { echo; echo "==== $* ===="; }
ok()   { echo "  [OK] $*"; }
fail() { echo "  [FAIL] $*" >&2; exit 1; }

ssh_vm()  { ssh $SSH_OPTS "${VM_USER}@${VM_HOST}" "$@"; }
scp_vm()  { scp $SSH_OPTS "$@"; }

# ---------------------------------------------------------------------------
# Step 1: Build wheel + SCP to VM (fast single-file transfer)
# ---------------------------------------------------------------------------
if ! $DATA_ONLY; then
  step "Step 0: Ensure remote directory exists"
  ssh_vm "sudo mkdir -p ${REMOTE_DIR}/deploy && sudo chown -R ${VM_USER}:${VM_USER} ${REMOTE_DIR}"
  ok "Remote directory ready"

  step "Step 1: Build wheel and SCP to VM"
  # Try multiple Python paths (WSL, Git Bash, system)
  PYTHON=""
  for p in python3 python \
    "/mnt/c/Program Files/Python312/python.exe" \
    "/c/Program Files/Python312/python.exe" \
    "/mnt/c/Users/asafi/AppData/Local/Programs/Python/Python312/python.exe"; do
    if "$p" -m build --version &>/dev/null; then PYTHON="$p"; break; fi
  done
  if [[ -z "$PYTHON" ]]; then
    echo "ERROR: No python with 'build' module found. Run: pip install build"; exit 1
  fi
  log "Using: $PYTHON"
  "$PYTHON" -m build --wheel --outdir dist/ || { fail "Wheel build failed"; }
  WHEEL=$(ls -t dist/ta_lab2-*.whl 2>/dev/null | head -1)
  if [ -z "$WHEEL" ]; then
    fail "No wheel found in dist/"
  fi
  log "Built: $WHEEL"
  scp_vm "$WHEEL" "${VM_USER}@${VM_HOST}:${REMOTE_DIR}/"
  ok "Wheel uploaded"

  # Install wheel on VM
  ssh_vm "${REMOTE_DIR}/venv/bin/pip install --force-reinstall ${REMOTE_DIR}/$(basename $WHEEL) 2>/dev/null" || \
    log "Wheel install will happen during setup_dashboard_env.sh"

  # ---------------------------------------------------------------------------
  # Step 2: SCP deploy scripts to VM
  # ---------------------------------------------------------------------------
  step "Step 2: SCP deploy scripts to VM (${REMOTE_DIR}/deploy/)"
  scp_vm deploy/vm/setup_dashboard_env.sh \
         deploy/vm/setup_nginx_ssl.sh \
         deploy/vm/nginx_streamlit.conf \
         deploy/vm/streamlit.service \
         deploy/vm/streamlit_config.toml \
         "${VM_USER}@${VM_HOST}:${REMOTE_DIR}/deploy/"
  ok "Deploy scripts synced"
fi

# ---------------------------------------------------------------------------
# Step 3: Run setup_dashboard_env.sh on VM
# ---------------------------------------------------------------------------
if ! $CODE_ONLY && ! $DATA_ONLY; then
  step "Step 3: Run setup_dashboard_env.sh on VM"
  ssh_vm "sudo bash ${REMOTE_DIR}/deploy/setup_dashboard_env.sh"
  ok "Dashboard environment setup complete"

  # ---------------------------------------------------------------------------
  # Step 4: Run setup_nginx_ssl.sh on VM
  # ---------------------------------------------------------------------------
  step "Step 4: Run setup_nginx_ssl.sh on VM (domain: ${DOMAIN})"
  ssh_vm "sudo bash ${REMOTE_DIR}/deploy/setup_nginx_ssl.sh ${DOMAIN}"
  ok "nginx + SSL configured for ${DOMAIN}"
fi

# ---------------------------------------------------------------------------
# Step 5: Push initial data from local
# ---------------------------------------------------------------------------
if ! $CODE_ONLY; then
  step "Step 5: Push data to VM (sync_dashboard_to_vm --full)"
  "$PYTHON" -m ta_lab2.scripts.etl.sync_dashboard_to_vm --full
  ok "Dashboard data pushed to VM"
fi

# ---------------------------------------------------------------------------
# Step 6: Verify Streamlit is running
# ---------------------------------------------------------------------------
step "Step 6: Verify Streamlit service"
STREAMLIT_STATUS=$(ssh_vm "systemctl is-active streamlit" 2>/dev/null || echo "unknown")
if [ "$STREAMLIT_STATUS" = "active" ]; then
  ok "streamlit.service is active"
else
  echo "  [WARN] streamlit.service status: $STREAMLIT_STATUS"
  log "Attempting to start Streamlit service..."
  ssh_vm "sudo systemctl enable streamlit && sudo systemctl start streamlit" || true
  sleep 3
  STREAMLIT_STATUS=$(ssh_vm "systemctl is-active streamlit" 2>/dev/null || echo "unknown")
  [ "$STREAMLIT_STATUS" = "active" ] && ok "streamlit.service started" || echo "  [WARN] streamlit still not active — check logs: journalctl -u streamlit -n 50"
fi

# ---------------------------------------------------------------------------
# Step 7: Verify nginx is running
# ---------------------------------------------------------------------------
step "Step 7: Verify nginx service"
NGINX_STATUS=$(ssh_vm "systemctl is-active nginx" 2>/dev/null || echo "unknown")
if [ "$NGINX_STATUS" = "active" ]; then
  ok "nginx.service is active"
else
  echo "  [WARN] nginx.service status: $NGINX_STATUS"
  log "Attempting to start nginx..."
  ssh_vm "sudo systemctl enable nginx && sudo systemctl start nginx" || true
  sleep 2
  NGINX_STATUS=$(ssh_vm "systemctl is-active nginx" 2>/dev/null || echo "unknown")
  [ "$NGINX_STATUS" = "active" ] && ok "nginx started" || echo "  [WARN] nginx still not active — check logs: journalctl -u nginx -n 50"
fi

# ---------------------------------------------------------------------------
# Step 8: Deployment summary
# ---------------------------------------------------------------------------
step "Deployment Summary"
cat <<EOF

  Dashboard URL : https://${DOMAIN}
  VM IP         : ${VM_HOST}
  Streamlit     : ${STREAMLIT_STATUS}
  nginx         : ${NGINX_STATUS}

  --- Pre-flight checklist ---
  [?] DNS A record  : ${DOMAIN} --> ${VM_HOST}
  [?] OCI ports     : TCP 80 and 443 open in Security List

  --- Day-to-day operations ---
  Add auth user   : ssh ${VM_USER}@${VM_HOST} -i ${SSH_KEY}
                    sudo htpasswd -b /etc/nginx/.htpasswd <user> <pass>
                    sudo systemctl reload nginx

  Sync data       : python -m ta_lab2.scripts.etl.sync_dashboard_to_vm
                    (runs automatically via cron; this triggers manual refresh)

  Update code     : bash deploy/vm/deploy_dashboard.sh ${DOMAIN} --code-only
                    (rsyncs src + deploy scripts, then syncs data; skips env/nginx setup)

  Full redeploy   : bash deploy/vm/deploy_dashboard.sh ${DOMAIN}
                    (idempotent; safe to re-run at any time)

  Streamlit logs  : ssh ${VM_USER}@${VM_HOST} -i ${SSH_KEY} journalctl -u streamlit -f
  nginx logs      : ssh ${VM_USER}@${VM_HOST} -i ${SSH_KEY} sudo tail -f /var/log/nginx/error.log

EOF
