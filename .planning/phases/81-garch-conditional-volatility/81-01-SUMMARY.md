---
phase: 81-garch-conditional-volatility
plan: "01"
subsystem: analysis
tags: [garch, arch, conditional-volatility, alembic, postgresql, statsmodels, student-t]

# Dependency graph
requires:
  - phase: 80-ic-analysis-feature-selection
    provides: analysis optional group in pyproject.toml (statsmodels)
  - phase: 74-foundation-shared-infra
    provides: dim_venues table (FK target for venue_id)
provides:
  - garch_forecasts table with PK (id, venue_id, ts, tf, model_type, horizon)
  - garch_diagnostics table with BIGSERIAL run_id and convergence tracking
  - garch_forecasts_latest materialized view with unique index
  - garch_engine.py core fitting/forecasting module
  - arch>=8.0.0 installed in [analysis] optional group
affects:
  - 81-02-PLAN (refresh script uses garch_engine and inserts to garch_forecasts)
  - 81-03-PLAN (evaluator reads garch_diagnostics)
  - 81-04-PLAN (blend logic reads garch_forecasts_latest)
  - 81-05-PLAN (vol_sizer integration reads garch_forecasts_latest)

# Tech tracking
tech-stack:
  added:
    - arch>=8.0.0 (GARCH/EGARCH/GJR-GARCH/FIGARCH fitting)
  patterns:
    - Lazy import of optional library (try/except at module level, matching vol_sizer.py)
    - Returns scaled by 100 before fitting, divided by 10000 after for decimal-space output
    - Student's t distribution for all GARCH variants (crypto fat tails)
    - EGARCH/FIGARCH use simulation method for multi-step forecasts (analytic unsupported)
    - arch_model fit options passed via options dict (not as top-level kwargs) in arch 8.x

key-files:
  created:
    - alembic/versions/i3j4k5l6m7n8_garch_tables.py
    - src/ta_lab2/analysis/garch_engine.py
  modified:
    - pyproject.toml

key-decisions:
  - "FIGARCH_MIN_OBS=200: research recommends 200-250, 200 maximises asset coverage while maintaining convergence"
  - "Student's t distribution for all variants: crypto returns have heavy tails"
  - "Returns scaled by 100 before fitting: convergence aid for daily crypto returns (~0.03)"
  - "arch 8.x API: maxiter/ftol go inside options dict, not as top-level fit() kwargs"
  - "EGARCH/FIGARCH simulation method: arch 8.x analytic multi-step not supported for these families"

patterns-established:
  - "GARCH fitting: scale returns * 100, unscale vol / 100, unscale variance / 10000"
  - "arch lazy import: try/except at top of module, check for None before use"
  - "garch_engine is pure computation (no DB) -- DB writes are in the refresh script (plan 02)"

# Metrics
duration: 12min
completed: 2026-03-22
---

# Phase 81 Plan 01: GARCH Foundation Summary

**GARCH/GJR-GARCH/EGARCH/FIGARCH DB schema plus core fitting engine using arch 8.0.0 with Student's-t, 100x return scaling, and simulation-based multi-step forecasts**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-22T16:31:24Z
- **Completed:** 2026-03-22T16:43:49Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `garch_forecasts` and `garch_diagnostics` tables with full PKs, CHECK constraints, FK, and indexes
- Created `garch_forecasts_latest` materialized view with unique index for fast latest-forecast lookups
- Implemented `garch_engine.py` with all four GARCH variants (GARCH, GJR-GARCH, EGARCH, FIGARCH)
- Added `arch>=8.0.0` to `[analysis]` optional group in pyproject.toml and installed

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration for GARCH tables and materialized view** - `ddb56849` (feat)
2. **Task 2: Core GARCH engine and arch dependency** - `3206b87c` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `alembic/versions/i3j4k5l6m7n8_garch_tables.py` - Migration creating garch_diagnostics, garch_forecasts, FK, and garch_forecasts_latest matview
- `src/ta_lab2/analysis/garch_engine.py` - Core GARCH fitting engine (290 lines): GARCHResult dataclass, MODEL_SPECS, fit_single_variant, fit_all_variants, generate_forecasts, compute_ljung_box_pvalue
- `pyproject.toml` - Added arch>=8.0.0 to [analysis] optional group

## Decisions Made

- **FIGARCH_MIN_OBS=200:** Research recommends 200-250 observations for FIGARCH due to its long-memory parameter estimation. Used 200 to maximise asset coverage while maintaining convergence reliability.
- **Student's t for all variants:** Crypto daily returns exhibit heavy tails; using Normal distribution would systematically underestimate tail risk.
- **Returns scaled by 100 before fitting:** Daily crypto returns (~0.03) are close to the numerical precision floor for GARCH optimizers. Scaling to percent space (~3.0) aids convergence significantly.
- **arch 8.x API change:** The `maxiter` parameter must be passed inside the `options` dict, not as a top-level `fit()` argument. Also `gtol` is not supported by the default L-BFGS-B solver so was removed to suppress OptimizeWarning.
- **EGARCH/FIGARCH use simulation forecasts:** In arch 8.x, analytic multi-step forecasting is not supported for EGARCH and FIGARCH families. Using `method='simulation'` with 500 paths.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed arch 8.x API: maxiter is inside options dict**
- **Found during:** Task 2 (garch_engine.py functional test)
- **Issue:** Plan specified `maxiter=500` as top-level `fit()` keyword; arch 8.0.0 raises `unexpected keyword argument 'maxiter'`
- **Fix:** Moved to `options={"maxiter": 500, "ftol": 1e-9}`. Also removed `gtol` (not supported by L-BFGS-B, caused OptimizeWarning)
- **Files modified:** src/ta_lab2/analysis/garch_engine.py
- **Verification:** All four variants converge cleanly on 300-obs test data
- **Committed in:** 3206b87c (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (API compatibility)
**Impact on plan:** Essential fix for correct operation. No scope creep.

## Issues Encountered

None beyond the arch 8.x API deviation documented above.

## User Setup Required

None - no external service configuration required. arch was installed automatically via `pip install -e ".[analysis]"`.

## Next Phase Readiness

- DB schema is fully deployed and verified (2 tables + 1 matview)
- `garch_engine.py` is importable and all exports are functional
- arch 8.0.0 is installed
- Plan 02 (refresh script) can proceed immediately

---
*Phase: 81-garch-conditional-volatility*
*Completed: 2026-03-22*
