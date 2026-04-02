---
phase: 114-hosted-dashboard
plan: 02
subsystem: infra
tags: [streamlit, systemd, nginx, vm, oracle, bash, deployment, postgresql, venv]

# Dependency graph
requires:
  - phase: 113-vm-execution-deployment
    provides: Oracle Singapore VM with PostgreSQL and ubuntu user established
  - phase: 114-01
    provides: nginx reverse proxy config and SSL setup (parallel wave 1)
provides:
  - Idempotent VM bootstrap script (venv, pip install, alembic, systemd)
  - Systemd unit for Streamlit on 127.0.0.1:8501 with auto-restart
  - Streamlit server config optimized for nginx reverse proxy deployment
affects:
  - 114-03 (data sync to VM, dashboard queries VM DB)
  - 114-04 (nginx integration references service port 8501)

# Tech tracking
tech-stack:
  added: [streamlit>=1.32, psycopg2-binary, bash deploy scripts]
  patterns:
    - Streamlit bound to 127.0.0.1 only; nginx handles external TLS and basic auth
    - enableCORS=false + enableXsrfProtection=false required for nginx WebSocket proxy
    - db_config.env guarded with -f check (never overwrite existing credentials)

key-files:
  created:
    - deploy/vm/setup_dashboard_env.sh
    - deploy/vm/streamlit.service
    - deploy/vm/streamlit_config.toml
  modified: []

key-decisions:
  - "No [dashboard] extras group in pyproject.toml — install streamlit and psycopg2-binary explicitly in setup script"
  - "Alembic upgrade head is primary; pg_dump --schema-only pipe documented as fallback for legacy tables"
  - "db_config.env uses hluser/hlpass pointing to same VM PostgreSQL as HL collector (port 5432)"
  - "Script resolves streamlit.service and streamlit_config.toml from its own directory (SCRIPT_DIR) for portability"

patterns-established:
  - "VM deploy artifacts live in deploy/vm/ alongside executor artifacts (deploy/executor/)"
  - "Bootstrap scripts print a status summary block at the end with next-step instructions"

# Metrics
duration: 2min
completed: 2026-04-01
---

# Phase 114 Plan 02: Hosted Dashboard VM Deployment Artifacts Summary

**Idempotent bash bootstrap (venv + pip + alembic + systemd) and nginx-proxy-safe Streamlit config for Oracle Singapore VM dashboard deployment**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-04-01T04:39:27Z
- **Completed:** 2026-04-01T04:41:39Z
- **Tasks:** 1/1
- **Files modified:** 3 created

## Accomplishments

- Created `setup_dashboard_env.sh` (220 lines): installs python3.11-venv, creates /opt/ta_lab2/venv, pip-installs ta_lab2 plus streamlit/psycopg2-binary/plotly/altair, guards db_config.env with -f check, runs alembic upgrade head with fallback comments, copies streamlit config, installs and enables systemd service, prints status summary
- Created `streamlit.service`: systemd unit binding exclusively to 127.0.0.1:8501 with Restart=always, RestartSec=5, StartLimitBurst guard, and postgresql.service dependency
- Created `streamlit_config.toml`: enableCORS=false + enableXsrfProtection=false (required for nginx WebSocket proxy), address=127.0.0.1, gatherUsageStats=false

## Task Commits

1. **Task 1: Create VM deployment artifacts** - `258ce6b4` (feat)

## Files Created/Modified

- `deploy/vm/setup_dashboard_env.sh` - Idempotent VM bootstrap: venv, pip install, db_config.env, alembic, streamlit service
- `deploy/vm/streamlit.service` - Systemd unit for Streamlit on 127.0.0.1:8501 with auto-restart
- `deploy/vm/streamlit_config.toml` - Streamlit server config for nginx reverse proxy deployment

## Decisions Made

- **No dashboard extras group**: pyproject.toml has no `[dashboard]` optional-dependencies group. Script installs `streamlit>=1.32`, `psycopg2-binary`, `plotly>=5.0`, and `altair>=5.0` explicitly rather than failing on a missing extras key.
- **Alembic + fallback**: Primary approach is `alembic upgrade head` from `/opt/ta_lab2/src`. Fallback (pg_dump --schema-only from local, piped via SSH) is documented in script comments but not automated — avoids the risk of overwriting live HL data on the VM.
- **db_config.env points to hluser/hlpass**: Same PostgreSQL instance as the HL data collector. Dashboard is read-only so sharing the user is acceptable for now.
- **SCRIPT_DIR resolution**: `streamlit.service` and `streamlit_config.toml` are located relative to the script's own directory so the deploy bundle (deploy/vm/) can be rsynced as a unit.

## Deviations from Plan

None - plan executed exactly as written. The only minor adaptation was documenting the missing `[dashboard]` extras group and installing runtime deps explicitly, which was anticipated in the plan's "check pyproject.toml for extras group; if none, use pip install -e ." guidance.

## Issues Encountered

None.

## Next Phase Readiness

- Three VM deployment artifacts ready for `rsync -avz deploy/vm/ ubuntu@161.118.209.59:/tmp/deploy_vm/`
- Streamlit will bind to 127.0.0.1:8501; nginx (114-01) proxies external HTTPS traffic to it
- 114-03 (data sync) can proceed: VM DB target (hluser/hlpass, hyperliquid) is established in db_config.env

---
*Phase: 114-hosted-dashboard*
*Completed: 2026-04-01*
