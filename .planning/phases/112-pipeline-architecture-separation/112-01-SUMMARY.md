---
phase: 112-pipeline-architecture-separation
plan: 01
subsystem: infra
tags: [pipeline, alembic, migration, sqlalchemy, refactor, shared-utilities]

# Dependency graph
requires:
  - phase: 107-pipeline-operations-dashboard
    provides: pipeline_run_log, pipeline_stage_log, kill switch, dead-man switch (Phase 107 original)
provides:
  - pipeline_utils.py with ComponentResult, STAGE_ORDER, all TIMEOUT_* constants,
    run log helpers, kill switch, dead-man switch, summary printer, completion alert
  - Alembic migration b1c2d3e4f5a6 adding pipeline_name discriminator column
affects:
  - 112-02-PLAN.md through 112-05-PLAN.md (all import pipeline_utils)
  - Future pipeline scripts (run_weekly_pipeline.py, run_ondemand_pipeline.py, etc.)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "pipeline_utils.py as shared infra layer: all pipeline scripts import from it, never the reverse"
    - "_start_pipeline_run with pipeline_name param + backward-compat fallback for pre-migration DB"
    - "_check_dead_man with optional pipeline_name filter: None = any pipeline, str = scoped check"

key-files:
  created:
    - src/ta_lab2/scripts/pipeline_utils.py
    - alembic/versions/b1c2d3e4f5a6_phase112_pipeline_name.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "Revision b1c2d3e4f5a6 used instead of plan-specified a0b1c2d3e4f5: a0b1c2d3e4f5 already taken by strip_cmc_prefix_add_venue_id on this branch"
  - "_start_pipeline_run backward-compat fallback: try INSERT with pipeline_name first, fall back to legacy INSERT on OperationalError/ProgrammingError for pre-migration deployments"
  - "_check_dead_man pipeline_name=None default: existing Phase 87 callers unchanged; new callers pass pipeline_name='daily' for scoped check"

patterns-established:
  - "One-way dependency: pipeline_utils <- run_daily_refresh <- future pipeline scripts"
  - "pipeline_name='daily' as default matches existing pipeline_run_log semantics"

# Metrics
duration: 8min
completed: 2026-04-01
---

# Phase 112 Plan 01: Pipeline Architecture Separation Summary

**Extracted ~550 lines of shared pipeline infrastructure from run_daily_refresh.py into pipeline_utils.py, plus Alembic migration adding pipeline_name discriminator to pipeline_run_log/pipeline_stage_log**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-01T00:04:23Z
- **Completed:** 2026-04-01T00:12:45Z
- **Tasks:** 2
- **Files modified:** 3 (1 created, 1 created, 1 modified)

## Accomplishments
- Created `pipeline_utils.py` with all shared infrastructure: ComponentResult, STAGE_ORDER, 26 TIMEOUT_* constants, 4 pipeline run log helpers, kill switch functions, dead-man switch with optional pipeline_name filter, summary printer, and pipeline completion alert
- Updated `run_daily_refresh.py` to import all shared items from `pipeline_utils`; removed ~550 lines of duplicate definitions
- Alembic migration `b1c2d3e4f5a6` adds `pipeline_name VARCHAR(30) NOT NULL DEFAULT 'daily'` to `pipeline_run_log`, nullable `pipeline_name` to `pipeline_stage_log`, and composite index `ix_pipeline_run_log_name_ts`

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract pipeline_utils.py** - `32f5acad` (feat)
2. **Task 2: Alembic migration for pipeline_name** - `0fb92f1f` (chore)

## Files Created/Modified
- `src/ta_lab2/scripts/pipeline_utils.py` - New shared infrastructure module (ComponentResult, TIMEOUT_*, STAGE_ORDER, pipeline run log helpers, kill switch, dead-man switch, summary printer, completion alert)
- `src/ta_lab2/scripts/run_daily_refresh.py` - Replaced duplicate definitions with imports from pipeline_utils; removed unused `dataclass` import
- `alembic/versions/b1c2d3e4f5a6_phase112_pipeline_name.py` - Migration adding pipeline_name to both pipeline log tables + composite index

## Decisions Made
- **Revision ID b1c2d3e4f5a6 instead of plan-specified a0b1c2d3e4f5:** The revision `a0b1c2d3e4f5` is already claimed by `strip_cmc_prefix_add_venue_id.py` on this branch. Used `b1c2d3e4f5a6` following the project's sequential hex-letter pattern.
- **_start_pipeline_run backward-compat fallback:** First attempts INSERT with `pipeline_name` column; on `OperationalError`/`ProgrammingError` falls back to legacy INSERT without it. Handles the pre-migration deployment window cleanly.
- **_check_dead_man pipeline_name=None default:** Existing Phase 87 call sites pass no arguments and continue to check any pipeline. New callers can pass `pipeline_name='daily'` for scoped dead-man queries.

## Deviations from Plan

None - plan executed exactly as written, except the revision ID substitution noted in Decisions Made (rule: alembic heads always determines actual revision, plan IDs treated as suggestions).

## Issues Encountered
- Pre-existing `a0b1c2d3e4f5` revision on branch collision: detected immediately via `alembic heads` warning, resolved by using next available ID `b1c2d3e4f5a6`
- Ruff auto-fixed one lint error on first commit attempt (unused import cleanup); re-staged and committed cleanly

## User Setup Required
None - no external service configuration required. Migration will be applied on next `alembic upgrade head`.

## Next Phase Readiness
- `pipeline_utils.py` is ready for Plans 02-05 to import from
- Alembic migration `b1c2d3e4f5a6` must be applied before `_start_pipeline_run(pipeline_name=...)` call is used (backward-compat fallback handles the interim period)
- No blockers for Phase 112 Plans 02+

---
*Phase: 112-pipeline-architecture-separation*
*Completed: 2026-04-01*
