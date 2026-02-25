---
phase: 47-drift-guard
plan: 01
subsystem: database
tags: [alembic, postgresql, drift-guard, materialized-view, schema-migration]

# Dependency graph
requires:
  - phase: 46-risk-controls
    provides: "dim_risk_state, dim_risk_limits, cmc_risk_events, cmc_risk_overrides tables; b5178d671e38 as Alembic head"
  - phase: 45-paper-executor
    provides: "dim_executor_config, cmc_executor_run_log, cmc_orders/fills/positions tables"
provides:
  - "cmc_drift_metrics table: daily per-strategy drift measurements (32 cols, UUID PK, 3 indexes)"
  - "v_drift_summary materialized view: aggregated drift trends with UNIQUE INDEX for REFRESH CONCURRENTLY"
  - "dim_risk_state: 4 drift-pause columns (drift_paused, drift_paused_at, drift_paused_reason, drift_auto_escalate_after_days)"
  - "dim_risk_limits: 3 drift threshold columns (tracking_error 5d/30d, window_days) with seed values"
  - "dim_executor_config: fee_bps NUMERIC column for cost model and drift attribution"
  - "cmc_risk_events: 3 new drift event types + drift_monitor trigger source in CHECK constraints"
  - "cmc_executor_run_log: data_snapshot JSONB column for PIT replay state"
  - "Alembic migration ac4cf1223ec7 as new head (down from b5178d671e38)"
  - "Reference DDL: sql/drift/094_cmc_drift_metrics.sql, sql/drift/095_v_drift_summary.sql"
affects:
  - 47-02 (replay engine reads data_snapshot from cmc_executor_run_log)
  - 47-03 (DriftMonitor writes to cmc_drift_metrics, reads dim_risk_limits thresholds, dim_risk_state drift_paused)
  - 47-04 (attribution report reads cmc_drift_metrics attribution columns, uses dim_executor_config.fee_bps)
  - 47-05 (drift report CLI queries v_drift_summary and cmc_drift_metrics)
  - 52-operational-dashboard (queries v_drift_summary for drift monitoring page)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Materialized view via op.execute() with raw SQL (Alembic has no native MATVIEW op)"
    - "UNIQUE INDEX on all GROUP BY columns for REFRESH MATERIALIZED VIEW CONCURRENTLY support"
    - "DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT pattern for extending CHECK constraint allowed values"
    - "ADD COLUMN IF NOT EXISTS for idempotent ALTER TABLE in migrations"
    - "Reference DDL files in sql/drift/ mirror migration content for human readability"

key-files:
  created:
    - alembic/versions/ac4cf1223ec7_drift_guard.py
    - sql/drift/094_cmc_drift_metrics.sql
    - sql/drift/095_v_drift_summary.sql
  modified: []

key-decisions:
  - "Materialized view via op.execute() raw SQL -- Alembic has no native MATVIEW op (Phase 41-01 established pattern)"
  - "UNIQUE INDEX on (config_id, asset_id, signal_type) covers all 3 GROUP BY columns -- required for REFRESH CONCURRENTLY"
  - "DROP CONSTRAINT IF EXISTS before ADD CONSTRAINT for idempotent CHECK constraint extension"
  - "fee_bps on dim_executor_config not dim_risk_limits -- executor cost model config belongs with executor config"
  - "data_snapshot JSONB NULL on cmc_executor_run_log -- PIT replay needs snapshot of data visibility at run time"

patterns-established:
  - "sql/drift/ directory as reference DDL home for Phase 47 drift guard objects"
  - "ASCII-only comments in all SQL and Python migration files (Windows cp1252 compatibility)"

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 47 Plan 01: Drift Guard DB Schema Summary

**Alembic migration ac4cf1223ec7 adds cmc_drift_metrics (32-column drift measurements table), v_drift_summary materialized view, and extends 5 existing tables with drift guard columns and CHECK constraints for Phase 47 foundation.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-25T19:10:40Z
- **Completed:** 2026-02-25T19:15:37Z
- **Tasks:** 2
- **Files modified:** 3 created

## Accomplishments

- Created `sql/drift/094_cmc_drift_metrics.sql` and `sql/drift/095_v_drift_summary.sql` as ASCII-only reference DDL files with full table/view definitions, constraints, and indexes
- Created Alembic migration `ac4cf1223ec7_drift_guard.py` implementing all 7 Phase 47 DDL changes; applied cleanly to production database (`alembic upgrade head` succeeds, `alembic current = ac4cf1223ec7 (head)`)
- All 8 schema changes verified live: `cmc_drift_metrics` (32 cols), `v_drift_summary` with `UNIQUE INDEX uq_drift_summary ON (config_id, asset_id, signal_type)`, `dim_risk_state.drift_paused = FALSE`, `dim_risk_limits.drift_tracking_error_threshold_5d = 0.015`, `dim_executor_config.fee_bps` (numeric), `cmc_risk_events` constraints updated with drift types, `cmc_executor_run_log.data_snapshot` (jsonb)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create reference DDL files for drift tables** - `4a3b0a2f` (feat)
2. **Task 2: Create Alembic migration for all Phase 47 DDL** - `229a69a9` (feat)

**Plan metadata:** (forthcoming in docs commit)

## Files Created/Modified

- `sql/drift/094_cmc_drift_metrics.sql` - Reference DDL for cmc_drift_metrics: CREATE TABLE with 32 columns, UUID PK, UNIQUE(metric_date, config_id, asset_id), 3 indexes (date DESC, config+date, partial breach)
- `sql/drift/095_v_drift_summary.sql` - Reference DDL for v_drift_summary: CREATE MATERIALIZED VIEW aggregating 8 metrics per (config_id, asset_id, signal_type), UNIQUE INDEX for REFRESH CONCURRENTLY
- `alembic/versions/ac4cf1223ec7_drift_guard.py` - Alembic migration implementing all 7 DDL changes in upgrade() with full downgrade() reversal

## Decisions Made

- **Materialized view via op.execute()**: Alembic has no native materialized view op. Raw SQL via op.execute() used as established in Phase 41-01.
- **UNIQUE INDEX covers all 3 GROUP BY columns**: (config_id, asset_id, signal_type) -- REFRESH MATERIALIZED VIEW CONCURRENTLY requires unique index covering all projection columns used to identify rows.
- **DROP CONSTRAINT IF EXISTS pattern**: Used for idempotent CHECK constraint extension on cmc_risk_events. Drops existing constraint, adds new one with original values plus drift additions. Downgrade restores original constraint with original values only.
- **fee_bps on dim_executor_config**: Cost model config belongs with executor configuration, not risk limits. Plans 47-03 and 47-04 read it for CostModel and attribution.
- **data_snapshot JSONB NULL**: cmc_executor_run_log extended (not a new table) -- extends Phase 45's existing audit log with PIT data visibility snapshot needed by Plan 47-02 replay engine.

## Deviations from Plan

None - plan executed exactly as written. Pre-commit hooks auto-fixed line endings (CRLF->LF) in SQL files and ruff reformatted the migration Python file; these are routine formatting fixes, not deviations.

## Issues Encountered

- Pre-commit hook `mixed-line-ending` fixed CRLF line endings in the SQL files and ruff reformatted the migration file on first commit attempts. Re-staged files after auto-fix and committed successfully on second attempt. Standard Windows behavior.

## User Setup Required

None - no external service configuration required. Migration applied directly to the database via `python -m alembic upgrade head`.

## Next Phase Readiness

- All 47-01 must-haves satisfied: cmc_drift_metrics, v_drift_summary, dim_risk_state drift columns, dim_risk_limits thresholds, dim_executor_config.fee_bps, cmc_risk_events constraint extensions, cmc_executor_run_log.data_snapshot
- Plans 47-02 through 47-05 can proceed in dependency order:
  - 47-02 (replay engine) depends on: data_snapshot column, cmc_drift_metrics for output
  - 47-03 (DriftMonitor) depends on: cmc_drift_metrics, dim_risk_limits thresholds, dim_risk_state.drift_paused
  - 47-04 (attribution) depends on: cmc_drift_metrics attribution columns, dim_executor_config.fee_bps
  - 47-05 (report CLI) depends on: v_drift_summary, cmc_drift_metrics
- No blockers for subsequent plans

---
*Phase: 47-drift-guard*
*Completed: 2026-02-25*
