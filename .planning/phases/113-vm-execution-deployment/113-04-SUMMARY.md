---
phase: 113-vm-execution-deployment
plan: 04
subsystem: infra
tags: [sync, ssh, psql-copy, vm, execution, orders, fills, positions, watermark]

# Dependency graph
requires:
  - phase: 113-01
    provides: VM execution deployment infrastructure and table layout decisions
  - phase: 113-02
    provides: WebSocket price feed infrastructure
provides:
  - sync_results_from_vm.py: pulls 9 execution tables from Oracle VM to local DB
  - sync_results_watermarks: auto-created local watermark tracking table
  - --full / --dry-run / --table / --skip-verify CLI flags
affects:
  - 113-05: dashboard and monitoring phases that need local execution state
  - 114-hosted-dashboard: dashboard phase needs local results populated

# Tech tracking
tech-stack:
  added: []
  patterns:
    - SSH+psql COPY VM→local incremental sync with per-table error isolation
    - Watermark table (sync_results_watermarks) auto-created on first run
    - TRUNCATE+COPY full-replace pattern for small stateless config tables

key-files:
  created:
    - src/ta_lab2/scripts/etl/sync_results_from_vm.py
  modified: []

key-decisions:
  - "Watermarks stored in local sync_results_watermarks table (not hyperliquid.sync_log) to keep execution sync state separate from HL data sync log"
  - "dim_risk_state uses TRUNCATE+COPY full-replace (small, stateless config table) — same pattern as sync_signals_to_vm.py config tables"
  - "positions and executor_run_log use DO UPDATE (mutable rows); orders/fills/events use DO NOTHING (append-only)"
  - "Per-table error isolation: exception in one table logged to stderr, sync continues to next table"
  - "Watermark advances to VM MAX after each successful table sync (not just to last pulled row)"

patterns-established:
  - "sync_results_watermarks: per-table watermark store, auto-created, upserted after each table"
  - "TableSpec NamedTuple: name, wm_col, pk_cols, update_cols, full_replace, timeout — same registry pattern as sync_signals_to_vm.py"
  - "Incremental tables query wm_col > watermark; full-replace tables TRUNCATE then COPY"

# Metrics
duration: 8min
completed: 2026-04-02
---

# Phase 113 Plan 04: VM Results Sync Summary

**SSH+psql COPY pull of 9 execution tables (orders, fills, positions, paper_orders, executor_run_log, drift_metrics, risk_events, order_events, dim_risk_state) from Oracle VM to local with per-table watermark tracking**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-02T04:17:38Z
- **Completed:** 2026-04-02T04:25:41Z
- **Tasks:** 1
- **Files modified:** 1 (created)

## Accomplishments

- Full execution state pull script using proven SSH+psql COPY pattern from sync_hl_from_vm.py
- 8 incremental tables (watermark-based) + 1 full-replace config table (dim_risk_state)
- Auto-created sync_results_watermarks table for per-table watermark tracking with upsert
- Per-table error isolation: one failure does not abort the rest of the sync
- CLI matches other sync scripts: --full, --dry-run, --table, --skip-verify

## Task Commits

1. **Task 1: Create sync_results_from_vm.py** - `e0a71c98` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `/c/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/etl/sync_results_from_vm.py` — VM→local pull script for all 9 execution result tables

## Decisions Made

- Watermarks stored in a standalone `sync_results_watermarks` table rather than in `hyperliquid.sync_log` — keeps execution sync state cleanly separated from HL data pipeline logs
- `positions` and `executor_run_log` use `ON CONFLICT DO UPDATE` because rows are mutable (status, unrealized_pnl, ended_at change); `orders`, `fills`, `risk_events`, `order_events`, `paper_orders` use `DO NOTHING` because they are append-only
- `dim_risk_state` uses TRUNCATE+COPY full-replace (identical to how `sync_signals_to_vm.py` handles `dim_executor_config`): small, stateless, and must mirror VM exactly
- Watermark advances to VM MAX(wm_col) after each successful table pull (not to last-row ts), ensuring no gap if rows arrive out of order on the VM

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - ruff format reformatted inline list literals to multi-line (expected pre-commit behavior), re-staged and committed cleanly.

## User Setup Required

None - no external service configuration required. The `sync_results_watermarks` table is auto-created on first run via `CREATE TABLE IF NOT EXISTS`.

Suggested crontab for VM results pull every 4 hours (as specified in plan):
```
0 */4 * * * /path/to/venv/bin/python -m ta_lab2.scripts.etl.sync_results_from_vm
```

## Next Phase Readiness

- sync_results_from_vm.py ready for use once Phase 113 VM tables exist (executor deployed)
- All 9 execution tables covered: orders, fills, positions, paper_orders, executor_run_log, drift_metrics, risk_events, order_events, dim_risk_state
- Script handles missing VM tables gracefully (skips with WARN) so it can be installed before VM executor is deployed

---
*Phase: 113-vm-execution-deployment*
*Completed: 2026-04-02*
