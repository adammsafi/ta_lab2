#!/usr/bin/env bash
# deploy/vm/setup_dashboard_env.sh
#
# Idempotent bootstrap script for the ta_lab2 dashboard on the Oracle Singapore VM.
# Run as: bash /tmp/setup_dashboard_env.sh
#
# Prerequisites (completed separately before this script):
#   - Oracle VM running Ubuntu 22.04+ with PostgreSQL installed
#   - Code rsynced to /opt/ta_lab2/src/ (see deploy/scripts/rsync_to_vm.sh)
#   - This script is uploaded to VM or run via SSH heredoc
#
# Idempotency: all operations use -p flags, pip is inherently idempotent,
# and env file is guarded with a -f check. Re-running is safe.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INSTALL_DIR="/opt/ta_lab2"
SRC_DIR="${INSTALL_DIR}/src"
VENV_DIR="${INSTALL_DIR}/venv"
ENV_FILE="${INSTALL_DIR}/db_config.env"
STREAMLIT_CFG_DIR="${INSTALL_DIR}/.streamlit"
SERVICE_NAME="streamlit"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }
die() { echo "[ERROR] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
log "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3.11-venv \
    python3-pip \
    python3.11-dev \
    libpq-dev \
    build-essential

# ---------------------------------------------------------------------------
# 2. Directory structure
# ---------------------------------------------------------------------------
log "Creating directory structure..."
sudo mkdir -p "${INSTALL_DIR}"
sudo chown ubuntu:ubuntu "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
mkdir -p "${STREAMLIT_CFG_DIR}"

# ---------------------------------------------------------------------------
# 3. Python virtual environment
# ---------------------------------------------------------------------------
log "Creating virtual environment at ${VENV_DIR}..."
if [[ ! -f "${VENV_DIR}/bin/activate" ]]; then
    python3.11 -m venv "${VENV_DIR}"
    log "venv created."
else
    log "venv already exists, skipping creation."
fi

# ---------------------------------------------------------------------------
# 4. Install ta_lab2 from rsynced source
#
# pyproject.toml has no [dashboard] extras group, so we install the base
# package plus streamlit and psycopg2 explicitly.
# ---------------------------------------------------------------------------
log "Installing ta_lab2..."
"${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel

# Install from wheel if available (deploy_dashboard.sh uploads it), else fallback to editable src
WHEEL=$(ls -t "${INSTALL_DIR}"/ta_lab2-*.whl 2>/dev/null | head -1)
if [[ -n "$WHEEL" ]]; then
    log "Installing from wheel: $WHEEL"
    "${VENV_DIR}/bin/pip" install --force-reinstall "$WHEEL"
elif [[ -d "${SRC_DIR}" ]]; then
    log "No wheel found, installing from source: ${SRC_DIR}"
    "${VENV_DIR}/bin/pip" install -e "${SRC_DIR}"
else
    die "No wheel in ${INSTALL_DIR} and no source in ${SRC_DIR}. Run deploy_dashboard.sh first."
fi
# Install dashboard runtime dependencies (not in a named extras group)
"${VENV_DIR}/bin/pip" install \
    streamlit>=1.32 \
    psycopg2-binary \
    sqlalchemy>=2.0 \
    pandas>=2.0 \
    plotly>=5.0 \
    altair>=5.0

log "Package installation complete."

# ---------------------------------------------------------------------------
# 5. db_config.env — VM PostgreSQL (same instance as HL collector)
#    NOT overwritten if file already exists.
# ---------------------------------------------------------------------------
if [[ ! -f "${ENV_FILE}" ]]; then
    log "Creating ${ENV_FILE}..."
    cat > "${ENV_FILE}" <<'EOF'
# ta_lab2 dashboard — VM database connection
# Points to the local PostgreSQL instance on the Oracle Singapore VM.
# Edit credentials here if your hluser password differs.
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=hyperliquid
DB_USER=hluser
DB_PASS=hlpass
EOF
    chmod 600 "${ENV_FILE}"
    log "db_config.env created."
else
    log "db_config.env already exists — skipping (delete to reset credentials)."
fi

# ---------------------------------------------------------------------------
# 6. Public schema tables via Alembic
#
# Approach A (preferred): run alembic upgrade head from the source tree.
#   Works when the VM DB already has the alembic_version table or is fresh.
#
# Approach B (fallback): if alembic fails (e.g., legacy tables exist that
#   Alembic doesn't know about), dump the schema from local and pipe to VM:
#
#   # On local machine:
#   pg_dump --schema-only --schema=public -h localhost -U hluser hyperliquid \
#       | ssh -i ~/.ssh/oracle_sg_key ubuntu@161.118.209.59 \
#             "psql -h 127.0.0.1 -U hluser hyperliquid"
#
# ---------------------------------------------------------------------------
log "Running Alembic migrations..."
# Source db_config.env so alembic can pick up DB_HOST etc. via the env or
# the db_config.env file read by ta_lab2 settings.
set -a; source "${ENV_FILE}"; set +a

ALEMBIC_INI="${SRC_DIR}/alembic.ini"
if [[ -f "${ALEMBIC_INI}" ]]; then
    (
        cd "${SRC_DIR}"
        "${VENV_DIR}/bin/alembic" upgrade head
    ) && log "Alembic upgrade head succeeded." \
      || {
            log "WARNING: Alembic upgrade head failed. See Approach B in script comments."
            log "Continuing — dashboard may still work if tables already exist."
         }
else
    log "WARNING: alembic.ini not found at ${ALEMBIC_INI}. Skipping migrations."
    log "Ensure schema is populated manually (see Approach B in script comments)."
fi

# ---------------------------------------------------------------------------
# 7. Streamlit config
# ---------------------------------------------------------------------------
log "Installing Streamlit config..."
TOML_SRC="${SCRIPT_DIR}/streamlit_config.toml"
if [[ -f "${TOML_SRC}" ]]; then
    cp "${TOML_SRC}" "${STREAMLIT_CFG_DIR}/config.toml"
    log "Copied ${TOML_SRC} -> ${STREAMLIT_CFG_DIR}/config.toml"
else
    log "WARNING: streamlit_config.toml not found alongside this script."
    log "Writing inline default config to ${STREAMLIT_CFG_DIR}/config.toml..."
    cat > "${STREAMLIT_CFG_DIR}/config.toml" <<'EOF'
[server]
enableCORS = false
enableXsrfProtection = false
headless = true
address = "127.0.0.1"
port = 8501

[browser]
gatherUsageStats = false
EOF
fi

# ---------------------------------------------------------------------------
# 8. Systemd service
# ---------------------------------------------------------------------------
log "Installing systemd service..."
SERVICE_SRC="${SCRIPT_DIR}/streamlit.service"
if [[ ! -f "${SERVICE_SRC}" ]]; then
    die "streamlit.service not found at ${SERVICE_SRC}. Cannot install service."
fi

sudo cp "${SERVICE_SRC}" "${SERVICE_FILE}"
sudo chmod 644 "${SERVICE_FILE}"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"
sudo systemctl restart "${SERVICE_NAME}.service"

# Give it a moment to start
sleep 2
if sudo systemctl is-active --quiet "${SERVICE_NAME}.service"; then
    log "streamlit.service is ACTIVE."
else
    log "WARNING: streamlit.service failed to start. Check: journalctl -u ${SERVICE_NAME} -n 50"
fi

# ---------------------------------------------------------------------------
# 9. Status summary
# ---------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo " ta_lab2 Dashboard Bootstrap Complete"
echo "======================================================================"
echo " Install dir : ${INSTALL_DIR}"
echo " Source dir  : ${SRC_DIR}"
echo " Virtual env : ${VENV_DIR}"
echo " DB config   : ${ENV_FILE}"
echo " Streamlit   : ${STREAMLIT_CFG_DIR}/config.toml"
echo " Service     : ${SERVICE_FILE}"
echo ""
echo " Service status:"
sudo systemctl status "${SERVICE_NAME}.service" --no-pager -l | head -15
echo ""
echo " Verify Streamlit is listening on 127.0.0.1:8501:"
echo "   curl -s http://127.0.0.1:8501/healthz"
echo ""
echo " Next steps:"
echo "   1. Configure nginx reverse proxy (see deploy/vm/nginx_dashboard.conf)"
echo "   2. Set up Let's Encrypt SSL (see deploy/vm/setup_ssl.sh)"
echo "   3. Verify at https://dash.<yourdomain.com>"
echo "======================================================================"
