---
phase: 63-tech-debt-cleanup
plan: 02
subsystem: executor
tags: [paper-executor, alembic, dim_executor_config, position-sizer, drift-guard, run_daily_refresh]

# Dependency graph
requires:
  - phase: 45-paper-trade-executor
    provides: PaperExecutor, ExecutorConfig, dim_executor_config table
  - phase: 47-drift-guard
    provides: drift monitoring pipeline, run_daily_refresh drift stage
provides:
  - ExecutorConfig.initial_capital loaded from dim_executor_config DB column with NULL fallback to 100000
  - Alembic migration a1b2c3d4e5f7 adding initial_capital NUMERIC column with CHECK > 0
  - Visible [WARN] drift monitoring skip message with actionable --paper-start guidance
affects:
  - future executor plans that configure per-strategy capital
  - operators running --all without --paper-start (will now see WARN instead of silent [INFO])

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DB-driven config: operator-configurable values live in dim_executor_config, not hardcoded in Python"
    - "NULL fallback pattern: Decimal(str(row.col)) if row.col is not None else Decimal('default')"
    - "Visibility pattern: pipeline skips print [WARN] + actionable re-run instructions"

key-files:
  created:
    - alembic/versions/a1b2c3d4e5f7_add_initial_capital_to_executor_config.py
  modified:
    - sql/executor/088_dim_executor_config.sql
    - src/ta_lab2/executor/paper_executor.py
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "initial_capital column is nullable=True in Alembic migration (server_default=100000) so existing rows are unaffected; Python adds the NULL fallback for belt-and-suspenders safety"
  - "CHECK constraint initial_capital > 0 added in both migration and reference DDL to prevent misconfiguration"
  - "Drift skip upgraded from print('[INFO]...') to 3-line [WARN] block without changing logic or condition"

patterns-established:
  - "Executor config fields: add to SELECT list + ExecutorConfig constructor with NULL fallback"
  - "Pipeline skip messages: [WARN] prefix + blank line + actionable re-run instructions"

# Metrics
duration: 3min
completed: 2026-03-01
---

# Phase 63 Plan 02: Tech Debt Cleanup - ExecutorConfig.initial_capital + Drift Warning Summary

**DB-driven initial_capital wired into ExecutorConfig via Alembic migration on dim_executor_config, and drift monitor skip upgraded from silent [INFO] to visible [WARN] with actionable guidance**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-01T07:37:32Z
- **Completed:** 2026-03-01T07:39:40Z
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- Added `initial_capital NUMERIC` column to `dim_executor_config` via Alembic migration with server_default=100000 and CHECK > 0 constraint
- Updated `PaperExecutor._load_active_configs` SELECT and `ExecutorConfig` construction to read `initial_capital` from DB with NULL fallback to `Decimal("100000")`
- Upgraded run_daily_refresh.py drift skip from a single silent `[INFO]` line to a 3-line `[WARN]` block with `--paper-start YYYY-MM-DD` re-run instructions
- Updated `--paper-start` help text from "Optional: silently skipped" to "REQUIRED for drift monitoring"

## Task Commits

Each task was committed atomically:

1. **Task 1: Add initial_capital column to dim_executor_config** - `b28f425b` (feat)
2. **Task 2: Upgrade drift monitor skip message to WARNING** - `a0a2fbcd` (fix)

**Plan metadata:** (see final docs commit)

## Files Created/Modified

- `alembic/versions/a1b2c3d4e5f7_add_initial_capital_to_executor_config.py` - Alembic migration: add_column initial_capital + CHECK constraint, revises 3caddeff4691
- `sql/executor/088_dim_executor_config.sql` - Reference DDL: added initial_capital column (NUMERIC NOT NULL DEFAULT 100000) and chk_exec_config_initial_capital constraint
- `src/ta_lab2/executor/paper_executor.py` - _load_active_configs: SELECT now includes initial_capital; ExecutorConfig constructor reads it with NULL fallback to Decimal("100000")
- `src/ta_lab2/scripts/run_daily_refresh.py` - [WARN] drift skip block + updated --paper-start help text

## Decisions Made

- **nullable=True in migration, NOT NULL in DDL**: The Alembic migration uses `nullable=True` so existing rows receive the `server_default=100000` automatically without a data migration step. The reference DDL shows the intended final state (NOT NULL DEFAULT 100000).
- **NULL fallback in Python**: Even though server_default ensures the column is never NULL after migration, the Python fallback (`if row.initial_capital is not None else Decimal("100000")`) provides belt-and-suspenders protection for any edge cases (e.g., running against a DB before migration is applied).
- **3-line WARN block**: Added a blank line before the [WARN] to visually separate it from surrounding output. The three print statements follow the established pattern of other pipeline gate messages in run_daily_refresh.py.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit `mixed-line-ending` hook flagged the new Alembic migration file (CRLF vs LF on Windows). The hook auto-fixed line endings; file was re-staged and committed cleanly on the second attempt.
- Pre-commit `ruff-format` reformatted `run_daily_refresh.py` on first commit attempt. File was re-staged and committed cleanly on second attempt.

## User Setup Required

None - no external service configuration required. The Alembic migration must be applied to the live DB with `alembic upgrade head` before `PaperExecutor._load_active_configs` can read `initial_capital` from rows. Until then, the NULL fallback ensures existing behavior is preserved.

## Next Phase Readiness

- Executor is ready for per-strategy capital configuration via `dim_executor_config.initial_capital`
- Operators using `--all` without `--paper-start` will now see the [WARN] drift skip message
- Phase 63 Plan 03 (if planned) can proceed without blockers from this plan

---
*Phase: 63-tech-debt-cleanup*
*Completed: 2026-03-01*
