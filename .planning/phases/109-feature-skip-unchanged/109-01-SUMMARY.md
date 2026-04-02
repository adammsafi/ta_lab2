---
phase: 109-feature-skip-unchanged
plan: 01
subsystem: database
tags: [alembic, postgresql, watermark, feature-refresh, state-table, skip-logic]

# Dependency graph
requires:
  - phase: 108-pipeline-batch-performance
    provides: batch performance patterns and state table conventions
  - phase: 107-pipeline-stage-log
    provides: pipeline_stage_log migration (actual alembic head w6x7y8z9a0b1)
provides:
  - feature_refresh_state table with PK (id, tf, alignment_source)
  - Alembic migration u5v6w7x8y9z0 creating the state table
  - _load_bar_watermarks: batch MAX(ingested_at) per id from price_bars_multi_tf_u
  - _load_feature_state: batch last_bar_ts per id from feature_refresh_state (try/except for missing table)
  - compute_changed_ids: returns 3-tuple (changed_ids, unchanged_ids, bar_watermarks)
  - _update_feature_refresh_state: per-id upsert after successful refresh
affects:
  - phase 109-02 (wiring helpers into run_all_refreshes)
  - run_all_feature_refreshes orchestrator

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-asset watermark state table pattern: PK (id, tf, alignment_source), last_bar_ts TIMESTAMPTZ"
    - "compute_changed_ids 3-tuple return: (changed_ids, unchanged_ids, bar_watermarks) avoids redundant query"
    - "try/except on state load returns {} if table absent (graceful degradation)"

key-files:
  created:
    - alembic/versions/u5v6w7x8y9z0_phase109_feature_refresh_state.py
  modified:
    - src/ta_lab2/scripts/features/run_all_feature_refreshes.py

key-decisions:
  - "down_revision = w6x7y8z9a0b1 (actual alembic head, not t4u5v6w7x8y9 as plan specified -- multiple migrations added since 107)"
  - "No venue_id in PK: features currently use venue_id=1 only; can be added later via follow-up migration"
  - "compute_changed_ids returns 3-tuple including bar_watermarks to avoid redundant DB query in _update_feature_refresh_state"
  - "total_rows_written in _update_feature_refresh_state is batch total (not per-asset): sufficient for monitoring"
  - "Functions placed in new section between _should_skip_tf and _run_single_tf; NOT yet wired into run_all_refreshes (Plan 02)"

patterns-established:
  - "State management section placement: between TF-level skip (_should_skip_tf) and worker function (_run_single_tf)"
  - "Graceful table-not-exists: try/except on _load_feature_state returns {} so first run treats all ids as changed"

# Metrics
duration: 3min
completed: 2026-04-01
---

# Phase 109 Plan 01: Feature Refresh State Infrastructure Summary

**feature_refresh_state table (7 columns, PK id/tf/alignment_source) created via Alembic migration, with 4 watermark helper functions added to run_all_feature_refreshes.py for per-asset skip logic**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-01T21:53:13Z
- **Completed:** 2026-04-01T21:56:24Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created `feature_refresh_state` table in PostgreSQL with PK `(id, tf, alignment_source)` and 7 columns via Alembic migration `u5v6w7x8y9z0`
- Added 4 state management helper functions to `run_all_feature_refreshes.py`: `_load_bar_watermarks`, `_load_feature_state`, `compute_changed_ids`, `_update_feature_refresh_state`
- Verified alembic upgrade/downgrade round-trip is clean; `compute_changed_ids` returns correct 3-tuple

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration for feature_refresh_state** - `b0cf1495` (feat)
2. **Task 2: Add watermark helper functions to run_all_feature_refreshes.py** - `0cd9854c` (feat)

**Plan metadata:** (see docs commit below)

## Files Created/Modified
- `alembic/versions/u5v6w7x8y9z0_phase109_feature_refresh_state.py` - Alembic migration creating feature_refresh_state with PK (id, tf, alignment_source) and 7 columns
- `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` - Added `Any` to typing imports; added 4 state management helper functions in new section

## Decisions Made

- **down_revision = w6x7y8z9a0b1**: Plan specified `t4u5v6w7x8y9` but the actual alembic head as of 2026-04-01 is `w6x7y8z9a0b1` (Phases 100, 102, 103 added migrations after Phase 107). Used actual head per established precedent (same correction as Phase 102-01).
- **No venue_id in PK**: Intentional per CONTEXT.md -- features use venue_id=1 only. Can be added via follow-up migration if multi-venue feature support is added.
- **compute_changed_ids returns 3-tuple**: Plan requires `(changed_ids, unchanged_ids, bar_watermarks)`. The bar_watermarks dict is passed through so callers can feed it to `_update_feature_refresh_state` without a redundant DB query.
- **total_rows_written is batch total**: Stored as monitoring metric for the entire changed_ids batch, not per-asset. Sufficient for Plan 02 integration.

## Deviations from Plan

None - plan executed exactly as written (down_revision correction is standard alembic chain correction, not a deviation from plan intent).

## Issues Encountered

None. The ruff-format pre-commit hook reformatted line 694-697 (long `conn.execute` call) after initial commit, requiring a re-stage and second commit attempt. This is normal workflow behavior.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `feature_refresh_state` table exists in PostgreSQL and is ready for Plan 02 integration
- All 4 helper functions are importable and tested
- `compute_changed_ids` returns the correct 3-tuple signature Plan 02 expects
- Plan 02 wires `compute_changed_ids` and `_update_feature_refresh_state` into `run_all_refreshes()` main flow

---
*Phase: 109-feature-skip-unchanged*
*Completed: 2026-04-01*
