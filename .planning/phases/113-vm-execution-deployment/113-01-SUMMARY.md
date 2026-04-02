---
phase: 113-vm-execution-deployment
plan: 01
subsystem: infra
tags: [postgresql, pg_dump, ssh, bash, vm-deployment, executor, oracle-vm]

# Dependency graph
requires:
  - phase: 112-pipeline-architecture-separation
    provides: pipeline scripts and sync infrastructure patterns
  - phase: 96-executor-activation
    provides: executor tables (orders, fills, positions, signal tables, dim_executor_config)
provides:
  - deploy/executor/vm_table_list.txt — canonical list of 25 VM executor tables
  - deploy/executor/create_vm_tables.sh — DDL extraction + VM deployment + dimension seeding script
affects:
  - 113-02 through 113-07 (all subsequent VM execution deployment plans)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "pg_dump --schema-only piped via SSH to remote psql for schema replication without Alembic"
    - "Python inline post-processor embedded in bash script for DDL transformation (FK stripping, CHECK constraint update)"
    - "COPY TO STDOUT + SSH pipe + COPY FROM STDIN via temp staging table for idempotent dimension seeding"

key-files:
  created:
    - deploy/executor/vm_table_list.txt
    - deploy/executor/create_vm_tables.sh
  modified: []

key-decisions:
  - "No Alembic on VM — SQL scripts only. pg_dump guarantees DDL matches local schema including indexes and constraints."
  - "FK stripping done in Python inline within bash (not sed/awk) for reliable multi-line statement parsing"
  - "exchange_price_feed CHECK constraint patched post-dump to add 'hyperliquid' (required for WebSocket feed writer)"
  - "Dimension seeding uses temp table + INSERT ON CONFLICT DO NOTHING for idempotency"

patterns-established:
  - "Pattern: pg_dump schema extraction for VM setup — use pg_dump --schema-only --no-owner --no-privileges -t <table> piped via SSH"
  - "Pattern: Inline Python in bash for DDL post-processing — embedded via heredoc, avoids separate .py file for one-off transforms"

# Metrics
duration: 2min
completed: 2026-04-02
---

# Phase 113 Plan 01: VM Table Setup Summary

**pg_dump --schema-only pipeline that extracts 25 executor table DDLs from local DB, strips non-VM FK constraints, patches exchange_price_feed CHECK for 'hyperliquid', and seeds dimension + config tables via SSH+COPY**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-04-02T04:11:07Z
- **Completed:** 2026-04-02T04:13:05Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Canonical vm_table_list.txt with exactly 25 tables across 8 categories (signals, execution, config, monitoring, price feed, dimensions, portfolio, order lifecycle)
- create_vm_tables.sh that extracts DDL via pg_dump, post-processes it (IF NOT EXISTS idempotency, FK stripping for non-VM tables, 'hyperliquid' injection into exchange_price_feed CHECK constraint), pipes to VM via SSH
- Dimension and config table seeding via reverse-direction SSH+COPY (mirrors sync_hl_from_vm.py pattern), with temp-table staging for ON CONFLICT DO NOTHING idempotency

## Task Commits

Each task was committed atomically:

1. **Task 1: Create vm_table_list.txt** - `52517b6c` (feat)
2. **Task 2: Create create_vm_tables.sh** - `aa4e5d70` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified
- `deploy/executor/vm_table_list.txt` - 25-table canonical list with category comments
- `deploy/executor/create_vm_tables.sh` - DDL extraction, post-processing, VM deployment, and dimension seeding script

## Decisions Made
- No Alembic on VM: pg_dump guarantees the schema matches local exactly (indexes, constraints, defaults) without maintaining a separate migration history on the VM.
- Python inline in bash for FK stripping: sed/awk can't reliably handle multi-line ALTER TABLE statements; a short Python script embedded via heredoc handles them correctly without adding a separate file.
- exchange_price_feed CHECK constraint patched at DDL post-process time (not at table creation time) so the fix is applied automatically whenever the script is re-run.
- Temp-table + ON CONFLICT DO NOTHING for seeding: direct COPY to tables with unique constraints would fail on re-run; staging pattern makes the script idempotent.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None for this plan — create_vm_tables.sh is the user-run artifact; no external service configuration required beyond what is already in db_config.env and the existing SSH key.

## Next Phase Readiness
- VM table setup script is complete and syntax-verified
- Depends on: pg_dump and psql available on local machine, SSH key at expected path
- Plan 113-02 (Python venv + executor service deployment) can proceed
- Plan 113-03 (signal push sync script) can proceed — vm_table_list.txt provides the canonical list of signal tables to push

---
*Phase: 113-vm-execution-deployment*
*Completed: 2026-04-02*
