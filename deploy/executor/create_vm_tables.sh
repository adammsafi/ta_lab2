#!/usr/bin/env bash
# create_vm_tables.sh — Extract DDL from local DB and create executor tables on Oracle Singapore VM.
#
# Run from the repo root on your local machine:
#   bash deploy/executor/create_vm_tables.sh
#
# What it does:
#   1. Reads deploy/executor/vm_table_list.txt for the canonical table list.
#   2. Extracts DDL from local DB using pg_dump --schema-only.
#   3. Post-processes DDL: strips FK constraints to non-VM tables, makes CREATE
#      TABLE statements idempotent (IF NOT EXISTS), updates exchange_price_feed
#      CHECK constraint to include 'hyperliquid'.
#   4. Pipes combined DDL to VM via SSH + psql.
#   5. Seeds dimension tables: dim_timeframe, dim_venues, dim_signals, dim_sessions.
#   6. Seeds config tables: dim_executor_config, dim_risk_limits.
#
# Prerequisites:
#   - db_config.env present in repo root with MARKETDATA_DB_URL
#   - pg_dump and psql available locally
#   - SSH key at ~/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key
#   - VM PostgreSQL accessible on 127.0.0.1:5432 as hluser/hlpass on hyperliquid DB
#
# Idempotent: safe to re-run. Tables are created with IF NOT EXISTS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TABLE_LIST="${SCRIPT_DIR}/vm_table_list.txt"
TMPDIR_WORK=$(mktemp -d)
trap 'rm -rf "${TMPDIR_WORK}"' EXIT

# Add PostgreSQL bin to PATH (Windows: pg_dump.exe needs explicit path)
PG_BIN=$(dirname "$(ls "/c/Program Files/PostgreSQL/"*/bin/pg_dump.exe 2>/dev/null | head -1)" 2>/dev/null || true)
if [ -n "${PG_BIN}" ] && [ -d "${PG_BIN}" ]; then
    export PATH="${PG_BIN}:$PATH"
fi

# ── VM connection details ──────────────────────────────────────────────────
SSH_KEY="${HOME}/Downloads/oracle_sg_keys/ssh-key-2026-03-10.key"
VM_HOST="161.118.209.59"
VM_USER="ubuntu"
VM_DB="hyperliquid"
VM_DB_USER="hluser"
VM_DB_PASS="hlpass"

SSH_OPTS=(
    -i "${SSH_KEY}"
    -o StrictHostKeyChecking=accept-new
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=5
    -o ConnectTimeout=15
)

# ── Load local DB credentials ─────────────────────────────────────────────
if [ -f "${REPO_ROOT}/db_config.env" ]; then
    # shellcheck disable=SC1091
    set -a; source <(tr -d '\r' < "${REPO_ROOT}/db_config.env"); set +a
fi

if [ -z "${MARKETDATA_DB_URL:-}" ]; then
    echo "ERROR: MARKETDATA_DB_URL not set. Source db_config.env or set it manually." >&2
    exit 1
fi

# Parse components from MARKETDATA_DB_URL for pg_dump and psql
# Format: postgresql+psycopg2://user:pass@host:port/dbname
# Strip the SQLAlchemy driver prefix first
_DB_URL=$(echo "${MARKETDATA_DB_URL}" | sed -E 's|postgresql\+[^:]+://|postgresql://|')
LOCAL_DB_USER=$(echo "${_DB_URL}" | sed -E 's|postgresql://([^:]+):.*|\1|')
LOCAL_DB_PASS=$(echo "${_DB_URL}" | sed -E 's|postgresql://[^:]+:([^@]+)@.*|\1|')
LOCAL_DB_HOST=$(echo "${_DB_URL}" | sed -E 's|postgresql://[^@]+@([^:/]+).*|\1|')
LOCAL_DB_PORT=$(echo "${_DB_URL}" | sed -E 's|postgresql://[^@]+@[^:]+:([0-9]+)/.*|\1|')
LOCAL_DB_NAME=$(echo "${_DB_URL}" | sed -E 's|postgresql://[^/]+/([^?]+).*|\1|')

echo "=== Executor VM Table Setup ==="
echo "Local DB: ${LOCAL_DB_USER}@${LOCAL_DB_HOST}:${LOCAL_DB_PORT}/${LOCAL_DB_NAME}"
echo "VM: ${VM_USER}@${VM_HOST} -> ${VM_DB}"
echo ""

# ── Step 1: Build table list from vm_table_list.txt ───────────────────────
echo "[1/5] Reading table list from vm_table_list.txt..."

mapfile -t TABLES < <(grep -v '^#' "${TABLE_LIST}" | grep -v '^[[:space:]]*$')

if [ ${#TABLES[@]} -eq 0 ]; then
    echo "ERROR: No tables found in ${TABLE_LIST}" >&2
    exit 1
fi

echo "      Tables to create: ${#TABLES[@]}"

# Build pg_dump -t flags (one per table)
PG_TABLE_FLAGS=()
for t in "${TABLES[@]}"; do
    PG_TABLE_FLAGS+=(-t "${t}")
done

# ── Step 2: Extract DDL via pg_dump --schema-only ─────────────────────────
echo "[2/5] Extracting DDL from local DB via pg_dump --schema-only..."

DDL_RAW="${TMPDIR_WORK}/ddl_raw.sql"

PGPASSWORD="${LOCAL_DB_PASS}" pg_dump \
    --schema-only \
    --no-owner \
    --no-privileges \
    "${PG_TABLE_FLAGS[@]}" \
    "postgresql://${LOCAL_DB_USER}:${LOCAL_DB_PASS}@${LOCAL_DB_HOST}:${LOCAL_DB_PORT}/${LOCAL_DB_NAME}" \
    > "${DDL_RAW}"

echo "      Raw DDL size: $(wc -l < "${DDL_RAW}") lines"

# ── Step 3: Post-process DDL ──────────────────────────────────────────────
echo "[3/5] Post-processing DDL..."

DDL_PROCESSED="${TMPDIR_WORK}/ddl_processed.sql"

# Build a list of VM table names as a regex alternation for FK stripping
VM_TABLES_REGEX=$(IFS='|'; echo "${TABLES[*]}")

# Find a real Python (Windows App Execution Aliases are stubs that print errors)
PYTHON_CMD=""
for _p in "/c/Program Files/Python312/python.exe" \
          "/c/Program Files/Python311/python.exe" \
          "/c/Users/${USERNAME:-${USER:-nobody}}/AppData/Local/Programs/Python/Python312/python.exe" \
          "/c/Users/${USERNAME:-${USER:-nobody}}/AppData/Local/Programs/Python/Python311/python.exe"; do
    if [ -x "$_p" ]; then PYTHON_CMD="$_p"; break; fi
done
# Fallback for Linux/Mac
if [ -z "$PYTHON_CMD" ]; then
    PYTHON_CMD=$(which python3 2>/dev/null || which python 2>/dev/null || echo python3)
fi
"${PYTHON_CMD}" - "${DDL_RAW}" "${DDL_PROCESSED}" "${VM_TABLES_REGEX}" <<'PYEOF'
import sys
import re

raw_path = sys.argv[1]
out_path = sys.argv[2]
vm_tables_regex = sys.argv[3]

with open(raw_path, 'r', encoding='utf-8') as f:
    content = f.read()

# ── 3a. Make CREATE TABLE idempotent (IF NOT EXISTS) ──────────────────
content = re.sub(
    r'\bCREATE TABLE\b(?!\s+IF NOT EXISTS)',
    'CREATE TABLE IF NOT EXISTS',
    content
)

# ── 3b. Make CREATE INDEX idempotent (IF NOT EXISTS) ──────────────────
content = re.sub(
    r'\bCREATE (UNIQUE )?INDEX\b(?!\s+IF NOT EXISTS)',
    lambda m: f'CREATE {m.group(1) or ""}INDEX IF NOT EXISTS',
    content
)

# ── 3c. Strip FK constraints referencing tables NOT in the VM list ────
#   Matches multi-line ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ...
#   REFERENCES <non-vm-table> ...;
vm_table_pattern = re.compile(vm_tables_regex, re.IGNORECASE)

def strip_non_vm_fk(content, vm_pattern):
    """Remove ALTER TABLE ADD CONSTRAINT ... FOREIGN KEY ... REFERENCES non-vm-table lines."""
    lines = content.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect start of ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY
        if re.match(r'^\s*ALTER TABLE', line, re.IGNORECASE):
            # Collect the full statement (until semicolon)
            stmt_lines = [line]
            j = i + 1
            while j < len(lines) and ';' not in lines[j - 1]:
                stmt_lines.append(lines[j])
                j += 1
            # If last collected line has semicolon but we stopped before it
            if j < len(lines) and ';' not in stmt_lines[-1]:
                stmt_lines.append(lines[j])
                j += 1
            stmt = '\n'.join(stmt_lines)
            # Check if it's a FOREIGN KEY constraint
            if re.search(r'\bFOREIGN KEY\b', stmt, re.IGNORECASE):
                # Extract the REFERENCES target table
                ref_match = re.search(r'\bREFERENCES\s+([^\s(]+)', stmt, re.IGNORECASE)
                if ref_match:
                    ref_table = ref_match.group(1).strip('"')
                    if not vm_pattern.fullmatch(ref_table):
                        # Drop this FK — it references a table not on the VM
                        i = j
                        continue
            result.extend(stmt_lines)
            i = j
        else:
            result.append(line)
            i += 1
    return '\n'.join(result)

content = strip_non_vm_fk(content, vm_table_pattern)

# ── 3d. Update exchange_price_feed CHECK constraint ───────────────────
#   The existing CHECK only allows: 'coinbase', 'kraken', 'binance', 'bitfinex', 'bitstamp'
#   We need to add 'hyperliquid' for the WebSocket price feed writer.
#
#   Match patterns like:
#     CONSTRAINT exchange_price_feed_exchange_check CHECK ((exchange = ANY (ARRAY['coinbase'::text, ...])))
#   or inline in CREATE TABLE:
#     exchange text CHECK (exchange IN ('coinbase', 'kraken', ...))
#
#   Strategy: find any CHECK constraint on exchange_price_feed that lists exchange values
#   and inject 'hyperliquid' if not already present.

def add_hyperliquid_to_check(content):
    # Pattern 1: ARRAY[...] style (pg_dump default)
    def inject_array(m):
        full = m.group(0)
        if 'hyperliquid' in full:
            return full  # already present
        # Insert before the closing bracket
        return re.sub(r"(\])", r", 'hyperliquid'::text\1", full, count=1)

    content = re.sub(
        r"ARRAY\[(?:['\w:, ]+)\](?=\s*\)\s*\)?\s*(?:,|;|\n))",
        inject_array,
        content
    )

    # Pattern 2: IN (...) style
    def inject_in(m):
        full = m.group(0)
        if 'hyperliquid' in full:
            return full  # already present
        return re.sub(r"(\))", r", 'hyperliquid'\1", full, count=1)

    # Only on lines near exchange_price_feed or exchange column CHECK
    lines = content.split('\n')
    in_epf_block = False
    result = []
    for line in lines:
        if 'exchange_price_feed' in line.lower():
            in_epf_block = True
        if in_epf_block and re.search(r"CHECK\s*\(.*exchange.*IN\s*\(", line, re.IGNORECASE):
            if 'hyperliquid' not in line:
                line = re.sub(r"(\))\s*\)", r", 'hyperliquid'\1)", line, count=1)
            in_epf_block = False
        result.append(line)
    return '\n'.join(result)

content = add_hyperliquid_to_check(content)

with open(out_path, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"      Processed DDL: {content.count(chr(10))} lines")
PYEOF

echo "      Processed DDL size: $(wc -l < "${DDL_PROCESSED}") lines"

# ── Step 4: Pipe DDL to VM via SSH + psql ─────────────────────────────────
echo "[4/5] Creating tables on VM..."

cat "${DDL_PROCESSED}" | ssh "${SSH_OPTS[@]}" "${VM_USER}@${VM_HOST}" \
    "PGPASSWORD=${VM_DB_PASS} psql -h 127.0.0.1 -U ${VM_DB_USER} -d ${VM_DB} -v ON_ERROR_STOP=0"

echo "      Tables created (errors above, if any, are likely 'already exists' — safe to ignore)."

# ── Step 5: Seed dimension + config tables via COPY ───────────────────────
echo "[5/5] Seeding dimension and config tables..."

# Helper: export table from local via COPY TO STDOUT and pipe to VM COPY FROM STDIN
seed_table() {
    local table="$1"
    local copy_sql="${2:-SELECT * FROM ${table}}"

    echo "      Seeding ${table}..."

    # Export CSV from local
    local csv_data
    csv_data=$(PGPASSWORD="${LOCAL_DB_PASS}" psql \
        -h "${LOCAL_DB_HOST}" -p "${LOCAL_DB_PORT}" \
        -U "${LOCAL_DB_USER}" -d "${LOCAL_DB_NAME}" \
        -c "COPY (${copy_sql}) TO STDOUT WITH CSV HEADER" 2>&1)

    if [ -z "${csv_data}" ] || echo "${csv_data}" | grep -q "^ERROR:"; then
        echo "        WARNING: No data or error for ${table}: ${csv_data}" >&2
        return 0
    fi

    # Strip header line for COPY FROM STDIN
    local csv_body
    csv_body=$(echo "${csv_data}" | tail -n +2)

    if [ -z "${csv_body}" ]; then
        echo "        ${table}: 0 rows (empty table, skipping seed)"
        return 0
    fi

    local row_count
    row_count=$(echo "${csv_body}" | wc -l)

    # Pipe to VM: use staging + upsert pattern via temp table to handle conflicts
    # For dimension tables, ON CONFLICT DO NOTHING is appropriate (idempotent re-run)
    local vm_psql_cmd
    vm_psql_cmd=$(cat <<VMEOF
PGPASSWORD=${VM_DB_PASS} psql -h 127.0.0.1 -U ${VM_DB_USER} -d ${VM_DB} -v ON_ERROR_STOP=1 <<'SQLEOF'
CREATE TEMP TABLE _seed_${table} (LIKE ${table} INCLUDING ALL) ON COMMIT DROP;
COPY _seed_${table} FROM STDIN WITH CSV;
INSERT INTO ${table} SELECT * FROM _seed_${table} ON CONFLICT DO NOTHING;
SQLEOF
VMEOF
)

    echo "${csv_body}" | ssh "${SSH_OPTS[@]}" "${VM_USER}@${VM_HOST}" "${vm_psql_cmd}" \
        2>&1 | grep -v "^COPY\|^INSERT\|^CREATE\|^DROP" || true

    echo "        ${table}: ${row_count} rows pushed"
}

# Dimension tables (always safe to re-seed with ON CONFLICT DO NOTHING)
seed_table "dim_timeframe"
seed_table "dim_venues"
seed_table "dim_signals"

# dim_sessions: may have complex PK — seed with same pattern
seed_table "dim_sessions"

# Config tables: seed current values (executor needs these to start)
seed_table "dim_executor_config"
seed_table "dim_risk_limits"

echo ""
echo "=== VM table setup complete ==="
echo ""
echo "Verify on VM:"
echo "  ssh -i ${SSH_KEY} ${VM_USER}@${VM_HOST} \\"
echo "    \"PGPASSWORD=${VM_DB_PASS} psql -h 127.0.0.1 -U ${VM_DB_USER} -d ${VM_DB} \\"
echo "     -c '\\dt' | grep -E '$(IFS='|'; echo "${TABLES[*]}")'\" "
echo ""
echo "Next steps:"
echo "  1. Verify tables exist on VM (command above)"
echo "  2. Check exchange_price_feed allows 'hyperliquid' (exchange CHECK constraint)"
echo "  3. Run: bash deploy/executor/setup_vm.sh to install Python venv + executor service"
