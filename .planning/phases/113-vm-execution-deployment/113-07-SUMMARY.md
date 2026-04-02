---
phase: 113-vm-execution-deployment
plan: 07
subsystem: infra
tags: [systemd, bash, deploy, oracle-vm, executor, websocket]

# Dependency graph
requires:
  - phase: 113-06
    provides: executor_service.py VM entry point with WebSocket feeds, StopMonitor, crash-loop detection
  - phase: 113-01
    provides: create_vm_tables.sh and vm_table_list.txt (executor table definitions)
provides:
  - "ta-executor.service: systemd unit with StartLimitBurst/StartLimitIntervalSec in [Unit], Restart=on-failure, RestartSec=30"
  - "setup_vm.sh: VM-side one-time setup (venv, requirements, ta_lab2 editable install, .env, systemd enable)"
  - "deploy.sh: local one-command deploy (SCP files + ta_lab2 source, run setup_vm.sh via SSH)"
affects:
  - "113-VERIFICATION: final phase verification uses these scripts"
  - "114-hosted-dashboard: VM deployment pattern is the reference"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "systemd crash-loop guard: StartLimitBurst=5 + StartLimitIntervalSec=300 in [Unit] (NOT [Service])"
    - "VM deploy: SCP deploy files + source tree, then SSH to run setup script"
    - "Editable install pattern: SCP src/ta_lab2 + pyproject.toml -> pip install -e on VM"

key-files:
  created:
    - deploy/executor/ta-executor.service
    - deploy/executor/setup_vm.sh
    - deploy/executor/deploy.sh
  modified: []

key-decisions:
  - "StartLimitBurst=5 and StartLimitIntervalSec=300 placed in [Unit] section — silently ignored in [Service]"
  - "Editable install (-e) of ta_lab2 source on VM keeps package in sync with SCPd source without wheel rebuilds"
  - "deploy.sh creates VM dir before SCP to avoid permission errors on fresh VMs"
  - "Telegram creds (BOT_TOKEN/CHAT_ID) match existing deploy/tvc/setup_vm.sh values for consistency"

patterns-established:
  - "deploy.sh pattern: SCP files, SCP source tree, SSH run setup — consistent with TVC/CMC/HL deploy pattern"
  - "setup_vm.sh idempotency: venv creation and .env write both guarded by [ ! -d ] / [ ! -f ] checks"

# Metrics
duration: 5min
completed: 2026-04-02
---

# Phase 113 Plan 07: VM Deployment Scripts Summary

**systemd unit (StartLimitBurst=5 in [Unit]), VM setup script (venv + editable ta_lab2 install + .env), and one-command local deploy script (SCP + SSH) — verified running on Oracle Singapore VM with HL WebSocket priced 536 symbols, StopMonitor active, signal loop polling every 30s**

## Performance

- **Duration:** ~15 min (including human verification)
- **Started:** 2026-04-02T04:33:50Z
- **Completed:** 2026-04-02T04:48:00Z
- **Tasks:** 2 (Task 1 auto + Task 2 human-verify checkpoint, approved)
- **Files created:** 3

## Accomplishments
- Systemd unit `ta-executor.service` with correct crash-loop guard (`StartLimitBurst=5`/`StartLimitIntervalSec=300` in `[Unit]`), `Restart=on-failure`, `RestartSec=30`, `SyslogIdentifier=ta-executor`
- VM setup script `setup_vm.sh` following `deploy/tvc/setup_vm.sh` pattern — creates venv, installs `requirements.txt`, editable installs `ta_lab2` source, writes `.env` with `EXECUTOR_DB_URL` + Telegram creds, installs + enables systemd service
- Local deploy script `deploy.sh` — SCP executor files and `src/ta_lab2/` source tree to VM, then SSH run `setup_vm.sh`; prints clear next-steps for table creation, signal sync, config push, service start, and log verification
- Human verification APPROVED: executor running as `active (running)` (PID 945320), HL WebSocket connected with 536 symbols priced in <1s, PriceCache warm at startup, StopMonitor daemon thread running (1s poll), signal loop polling every 30s (reports "no active configs" correctly since `dim_executor_config` was empty), crash-loop tracking 1/5 starts

## Task Commits

1. **Task 1: Create systemd unit, setup script, and deploy script** - `d02858de` (feat)

**Plan metadata (pre-verification):** `a1a1c9bc` (docs: complete deploy scripts plan — paused at human-verify checkpoint)

## Files Created/Modified
- `deploy/executor/ta-executor.service` - systemd unit for 24/7 executor service
- `deploy/executor/setup_vm.sh` - VM-side one-time setup (run via SSH from deploy.sh)
- `deploy/executor/deploy.sh` - local one-command deploy script

## Decisions Made
- `StartLimitBurst` and `StartLimitIntervalSec` placed in `[Unit]` section (not `[Service]`) — systemd silently ignores these in `[Service]`, which was a RESEARCH.md documented gotcha
- Editable install (`pip install -e`) of ta_lab2 source chosen over wheel build — simpler for iterative deploys; just re-run `deploy.sh` to push updated source
- `.env` write is guarded by `[ ! -f .env ]` to preserve any manual credentials changes made on the VM after initial setup
- Telegram credentials (`8590137517:AAFy7aSm05SInNOsUx6kmD6eWaLCgtkR2kg` / `5591688420`) match `deploy/tvc/setup_vm.sh` for consistency

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Two minor non-blocking items observed during verification (tracked as todos, not blockers):
1. `dim_assets` table name may differ on VM — executor logs noted this; not breaking since executor falls back gracefully
2. `dim_executor_config` was empty at verification time — executor correctly reports "no active configs" and polls; configs can be seeded separately

## Verification Results (Human-Verified, APPROVED)

```
systemctl status: active (running), PID 945320
HL WebSocket: connected, 536 symbols priced in <1s
PriceCache: 536 symbols cached at startup
StopMonitor: daemon thread running (1s poll)
Signal loop: polling every 30s, "no active configs" (dim_executor_config empty — expected)
Crash-loop tracking: 1/5 starts
```

## User Setup Required

None - deployment is complete and executor is running. To seed executor configs and activate trading:

```bash
# Push executor config from local to VM
python -m ta_lab2.scripts.etl.sync_config_to_vm

# Push signals (if needed after config seeding)
python -m ta_lab2.scripts.etl.sync_signals_to_vm --full
```

## Next Phase Readiness
- Phase 113 is COMPLETE — executor is live on Oracle Singapore VM as a 24/7 systemd service
- Phase 113 VERIFICATION.md can now be completed
- Phase 114 (hosted dashboard) can reference this deploy pattern for VM hosting
- To activate live trading: seed `dim_executor_config` entries on the VM and push signal data

---
*Phase: 113-vm-execution-deployment*
*Completed: 2026-04-02*
