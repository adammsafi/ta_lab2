---
phase: 107-pipeline-operations-dashboard
plan: 01
subsystem: database, infra, pipeline
tags: [alembic, postgresql, sqlalchemy, pipeline, kill-switch, stage-logging]

# Dependency graph
requires:
  - phase: 87-pipeline-wiring
    provides: pipeline_run_log table and _start_pipeline_run/_complete_pipeline_run helpers

provides:
  - pipeline_stage_log table with FK to pipeline_run_log (CASCADE)
  - pipeline_run_log.status CHECK extended to include 'killed'
  - _log_stage_start/_log_stage_complete helpers in run_daily_refresh.py
  - KILL_SWITCH_FILE constant + _check_pipeline_kill_switch() function
  - _maybe_kill() helper that marks run 'killed' and exits 2 on .pipeline_kill file detection
  - Every stage in run_daily_refresh.py wrapped with stage logging and kill switch check
  - .pipeline_kill gitignored

affects:
  - 107-02 (ops dashboard Streamlit page reads pipeline_stage_log for real-time progress)
  - Any future pipeline observability or alerting that wants per-stage timing

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Alembic DO $$ DECLARE block for constraint name discovery before DROP/ADD"
    - "_log_stage_start returns UUID so _log_stage_complete can update the row"
    - "_maybe_kill centralizes kill-switch logic: check, finalize DB run, delete file, return bool"

key-files:
  created:
    - alembic/versions/t4u5v6w7x8y9_phase107_pipeline_stage_log.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py
    - .gitignore

key-decisions:
  - "DO $$ DECLARE block in migration to look up CHECK constraint name dynamically; avoids hardcoding auto-generated name"
  - "stage_name VARCHAR(50) matches STAGE_ORDER values exactly; dashboard joins by stage_name string"
  - "_slid local variable pattern: each stage block declares _slid = _log_stage_start(...) before the run call; keeps the logging one-liner before and after each run_XYZ() call"
  - "Kill switch exits with code 2 (not 1): distinguishes 'killed intentionally' from 'stage failed'"
  - "_maybe_kill deletes .pipeline_kill after acting on it: prevents stale file triggering next run"
  - "KILL_SWITCH_FILE placed at repo root (4 x parent.parent from script): one canonical path for both run_daily_refresh.py and the dashboard to reference"

patterns-established:
  - "Stage log pattern: _slid = _log_stage_start(...) before run_XYZ(); results.append(...); _log_stage_complete(...) after; _maybe_kill check after that"
  - "Kill switch exit code 2 = intentional kill; exit code 1 = stage failure; exit code 0 = success"

# Metrics
duration: 18min
completed: 2026-04-01
---

# Phase 107 Plan 01: Pipeline Stage Log Summary

**pipeline_stage_log table + kill switch instrumentation: every stage in run_daily_refresh.py writes per-stage timing rows and checks .pipeline_kill for graceful stop**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-04-01T00:00:00Z
- **Completed:** 2026-04-01T00:18:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `pipeline_stage_log` table (FK to `pipeline_run_log` with CASCADE, ix on run_id+started_at) via Alembic migration `t4u5v6w7x8y9`
- Extended `pipeline_run_log.status` CHECK to allow `'killed'` (via DO $$ DECLARE dynamic DROP+ADD)
- Added `_log_stage_start` / `_log_stage_complete` helpers and `KILL_SWITCH_FILE` / `_check_pipeline_kill_switch` / `_maybe_kill` to `run_daily_refresh.py`
- Wrapped all 25 stages in `main()` with stage log calls and kill switch checks
- `.pipeline_kill` added to `.gitignore`

## Task Commits

1. **Task 1: Alembic migration for pipeline_stage_log and killed status** - `8117e519` (feat)
2. **Task 2: Instrument run_daily_refresh.py with stage logging and kill switch** - `ec241a9e` (feat)

## Files Created/Modified

- `alembic/versions/t4u5v6w7x8y9_phase107_pipeline_stage_log.py` - Migration creating pipeline_stage_log and updating pipeline_run_log.status CHECK
- `src/ta_lab2/scripts/run_daily_refresh.py` - Stage logging helpers, kill switch constant/functions, instrumented main()
- `.gitignore` - Added `.pipeline_kill` entry

## Decisions Made

- DO $$ DECLARE block in migration to look up CHECK constraint name dynamically: avoids hardcoding the auto-generated name (e.g., `pipeline_run_log_status_check`) which could differ across environments
- `_slid` local variable pattern: each stage block assigns `_slid = _log_stage_start(...)` before the `run_XYZ()` call, then calls `_log_stage_complete(_slid, ...)` after `results.append()` -- consistent and auditable
- Kill switch exits with code 2 (not 1): allows callers and dashboards to distinguish intentional kill from stage failure
- `_maybe_kill` deletes `.pipeline_kill` after acting on it to prevent stale file re-triggering next run
- `KILL_SWITCH_FILE` at repo root (4 parent-hops from script path): one canonical path shared by run_daily_refresh.py and future dashboard code

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- ruff-format reformatted both committed files (long lines in stage-logging calls); re-staged after hook modified files on both task commits -- standard workflow.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `pipeline_stage_log` table is live in DB with correct schema
- `run_daily_refresh.py` will write stage rows on next `--all` run
- Plan 02 (Streamlit ops dashboard) can now SELECT from `pipeline_stage_log` to show real-time stage progress
- Kill switch: create `.pipeline_kill` at repo root to stop a running pipeline after the current stage; it will be cleaned up automatically

---
*Phase: 107-pipeline-operations-dashboard*
*Completed: 2026-04-01*
