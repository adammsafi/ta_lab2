---
phase: 81-garch-conditional-volatility
plan: "02"
subsystem: scripts
tags: [garch, arch, conditional-volatility, state-manager, refresh-script, postgresql, sqlalchemy]

# Dependency graph
requires:
  - phase: 81-garch-conditional-volatility
    plan: "01"
    provides: garch_forecasts, garch_diagnostics tables, garch_forecasts_latest matview, garch_engine.py
affects:
  - 81-03-PLAN (evaluator reads garch_diagnostics, uses state output)
  - 81-04-PLAN (blend logic reads garch_forecasts_latest)
  - 81-05-PLAN (vol_sizer integration reads garch_forecasts_latest)
provides:
  - scripts/garch package with __init__.py marker
  - GARCHStateManager: garch_state table DDL, load_state, update_state, get_assets_needing_refit
  - refresh_garch_forecasts.py: daily CLI script fitting 4 GARCH variants per asset

# Tech tracking
tech-stack:
  added: []
  patterns:
    - State manager dataclass pattern (frozen GARCHStateConfig + GARCHStateManager class)
    - Temp-table batch upsert for garch_forecasts (ON CONFLICT DO UPDATE)
    - INSERT RETURNING run_id for diagnostics FK linkage
    - 5-day half-life exponential decay for carry-forward fallback
    - Garman-Klass 21-bar fallback when no prior converged forecast exists
    - REFRESH MATERIALIZED VIEW CONCURRENTLY after all assets processed

key-files:
  created:
    - src/ta_lab2/scripts/garch/__init__.py
    - src/ta_lab2/scripts/garch/garch_state_manager.py
    - src/ta_lab2/scripts/garch/refresh_garch_forecasts.py

key-decisions:
  - "carry-forward half-life=5 days: 5-day exponential decay preserves meaningful vol signal without letting stale forecasts persist indefinitely"
  - "GK fallback uses 21-bar window: consistent with standard short-term vol estimation; non-annualised daily vol stored"
  - "INSERT RETURNING for diagnostics: clean FK linkage between garch_forecasts.model_run_id and garch_diagnostics.run_id"
  - "Sequential per-asset processing: GARCH fitting is CPU-bound; multiprocessing deferred to Phase 81-05 if needed"

patterns-established:
  - "GARCH state: garch_state PK=(id, venue_id, tf, model_type); consecutive_failures tracks convergence health"
  - "Fallback hierarchy: converged GARCH -> carry-forward (5d decay) -> GK fallback -> skip (non-fatal)"
  - "forecast_source CHECK constraint enforces: 'garch' | 'carry_forward' | 'fallback_gk' | 'fallback_parkinson'"

# Metrics
duration: 6min
completed: 2026-03-22
---

# Phase 81 Plan 02: GARCH Scripts Summary

**GARCHStateManager with consecutive-failure tracking, plus daily refresh script with carry-forward/GK fallback hierarchy and temp-table upsert to garch_forecasts**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-22T16:47:55Z
- **Completed:** 2026-03-22T16:53:36Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `scripts/garch` package with `__init__.py`
- Implemented `GARCHStateConfig` (frozen dataclass) and `GARCHStateManager` with `ensure_state_table`, `load_state`, `update_state`, `get_assets_needing_refit`
- Implemented `refresh_garch_forecasts.py` with full fallback hierarchy: converged GARCH -> 5-day decay carry-forward -> Garman-Klass 21-bar fallback
- All diagnostic rows inserted with `RETURNING run_id` for clean FK linkage to `garch_forecasts.model_run_id`
- Materialized view refreshed `CONCURRENTLY` after all assets

## Task Commits

Each task was committed atomically:

1. **Task 1: GARCH state manager and package init** - `4eb6fc8c` (feat)
2. **Task 2: Daily GARCH forecast refresh script** - `5d010865` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/garch/__init__.py` - Empty package marker
- `src/ta_lab2/scripts/garch/garch_state_manager.py` - GARCHStateConfig + GARCHStateManager (238 lines)
- `src/ta_lab2/scripts/garch/refresh_garch_forecasts.py` - Daily CLI refresh script (670 lines)

## Decisions Made

- **carry-forward half-life = 5 days:** When GARCH fails to converge, we use the last converged forecast decayed with a 5-day exponential half-life (`vol *= exp(-ln2/5)`). This keeps forecasts meaningful for ~1 week without letting stale values persist indefinitely.
- **GK fallback uses 21 bars:** When no prior converged forecast exists, we compute Garman-Klass volatility from the last 21 OHLC bars. 21 bars is ~1 trading month -- a standard short-window estimate.
- **INSERT RETURNING run_id:** Diagnostics are inserted first; the returned `run_id` is set as `model_run_id` in each forecast row, creating a clean FK linkage. This enables Plan 03 (evaluator) to join forecasts to diagnostics efficiently.
- **Sequential per-asset processing:** GARCH fitting is CPU-bound and the `arch` library uses its own internal threading. Multiprocessing would create contention. Deferred to Phase 81-05 if wall-clock time becomes a problem.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused variables flagged by ruff (F841)**
- **Found during:** Task 2 commit (pre-commit hook)
- **Issue:** `now_utc = datetime.now(tz=timezone.utc)` and `any_converged = any(...)` were assigned but never read after refactoring the flow
- **Fix:** Removed both assignments; also removed now-unused `timezone` import
- **Files modified:** src/ta_lab2/scripts/garch/refresh_garch_forecasts.py
- **Verification:** `ruff lint` passes cleanly; import test confirms no regression
- **Committed in:** 5d010865 (Task 2 commit, re-staged after fix)

---

**Total deviations:** 1 auto-fixed (linter cleanup)
**Impact on plan:** Trivial cleanup. No scope creep.

## Issues Encountered

None beyond the linter cleanup documented above.

## User Setup Required

None - no external service configuration required. All DB tables were created in Phase 81-01.

## Next Phase Readiness

- `scripts/garch` package is importable and all exports verified
- `GARCHStateManager` is ready for use by the refresh script and evaluator
- `refresh_garch_forecasts.py` is ready to run: `python -m ta_lab2.scripts.garch.refresh_garch_forecasts --ids all --tf 1D`
- Plan 03 (GARCH evaluator) can proceed: reads `garch_diagnostics` and `garch_state`
- Plan 04 (blend logic) can proceed: reads `garch_forecasts_latest`

---
*Phase: 81-garch-conditional-volatility*
*Completed: 2026-03-22*
