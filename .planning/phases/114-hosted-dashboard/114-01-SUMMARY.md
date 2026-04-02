---
phase: 114
plan: "01"
name: sync-dashboard-to-vm
subsystem: etl-sync
tags: [sync, ssh, copy, postgresql, dashboard, vm, etl]
one-liner: "SSH+COPY pipeline pushing 37 local tables to Oracle VM with full-replace for dims, incremental watermark for large tables, batch-by-id for features"

dependency-graph:
  requires:
    - "113-07: executor live on VM (VM exists and is reachable)"
  provides:
    - "Local-to-VM data push script for dashboard tables"
    - "Full replace + incremental watermark sync strategies"
  affects:
    - "114-02: VM dashboard setup (needs this data on VM)"
    - "114-03+: dashboard pages rely on VM-side tables populated by this script"

tech-stack:
  added: []
  patterns:
    - "SSH+COPY inverted (local->VM) matching sync_cmc_from_vm.py pattern"
    - "Dynamic column discovery via information_schema (no hardcoded column lists)"
    - "Batch-by-id for large tables to avoid multi-hour single transactions"
    - "Staging table + ON CONFLICT DO UPDATE for incremental upsert on VM"

file-tracking:
  created:
    - src/ta_lab2/scripts/etl/sync_dashboard_to_vm.py
  modified: []

decisions:
  - "Full replace for 12 dim/config tables (<1K rows each) — simpler and safe"
  - "Incremental watermark for 25 large tables — avoids re-pushing millions of rows each run"
  - "features table batched by id — 17.5M rows cannot be done in one transaction"
  - "Dynamic column discovery — avoids maintenance burden of hardcoded column lists across 37 tables"
  - "VM sync_log reused (hyperliquid.sync_log) — no new infra needed"

metrics:
  duration: "7 minutes"
  completed: "2026-04-02"
  tasks-completed: 1
  tasks-total: 1
---

# Phase 114 Plan 01: sync-dashboard-to-vm Summary

## What Was Built

`src/ta_lab2/scripts/etl/sync_dashboard_to_vm.py` — a data bridge that pushes
local PostgreSQL tables to the Oracle Singapore VM for the hosted dashboard.

Follows the inverted SSH+COPY pattern of sync_cmc_from_vm.py: local DB runs
`COPY (SELECT ...) TO STDOUT WITH CSV`, data is piped via SSH, VM receives it
via `COPY ... FROM STDIN WITH CSV`.

## Table Coverage (37 tables)

**Full replace (12 tables):** dim_assets, dim_timeframe, dim_signals, dim_ama_params,
dim_venues, dim_sessions, dim_executor_config, dim_risk_limits, dim_risk_state,
cmc_da_info, cmc_da_ids, asset_data_coverage

**Incremental watermark (25 tables):** strategy_bakeoff_results, ic_results,
feature_experiments, regimes, regime_flips, regime_stats, regime_comovement,
macro_regimes, portfolio_allocations, asset_stats, features (batch_by_id),
7x signals tables, positions, fills, orders, executor_run_log, pipeline_run_log,
pipeline_stage_log, drift_metrics, risk_events

## Key Implementation Details

- `_get_local_columns()` uses information_schema for dynamic column discovery
- `_ensure_vm_table()` checks VM table existence before attempting sync (graceful skip)
- `_sync_incremental_batched()` iterates distinct id values for features (17.5M rows)
- `_vm_upsert_csv()` uses temp staging table + ON CONFLICT DO UPDATE on VM side
- `_log_sync_vm()` writes hyperliquid.sync_log entry after each table

## CLI

```bash
python -m ta_lab2.scripts.etl.sync_dashboard_to_vm              # incremental
python -m ta_lab2.scripts.etl.sync_dashboard_to_vm --full       # ignore watermarks
python -m ta_lab2.scripts.etl.sync_dashboard_to_vm --dry-run    # report only
python -m ta_lab2.scripts.etl.sync_dashboard_to_vm --table regimes  # single table
```

## Dry-Run Output

`--dry-run` reports all 37 tables with row counts and sync strategy without
writing anything to the VM. Verified: all tables found locally, row counts accurate.

## Deviations from Plan

None — plan executed exactly as written.

## Commits

| Hash | Message |
|------|---------|
| 892afc9d | feat(114-01): add sync_dashboard_to_vm.py — local-to-VM data push |
