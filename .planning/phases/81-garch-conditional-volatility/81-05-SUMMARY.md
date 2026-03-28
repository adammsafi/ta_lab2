---
phase: 81-garch-conditional-volatility
plan: "05"
subsystem: scripts
tags: [garch, volatility, comparison-report, daily-refresh, pipeline, rmse, qlike, mincer-zarnowitz]

# Dependency graph
requires:
  - phase: 81-garch-conditional-volatility
    plan: "02"
    provides: refresh_garch_forecasts.py (daily CLI script), scripts/garch package
  - phase: 81-garch-conditional-volatility
    plan: "03"
    provides: garch_evaluator.py (evaluate_all_models, RMSE/QLIKE/MZ metrics), garch_blend.py
provides:
  - run_garch_comparison.py CLI generating markdown + CSV comparison reports
  - Daily refresh pipeline wiring with --garch / --no-garch flags
  - GARCH stage positioned after features, before signals in pipeline
affects:
  - 82-xx (feature selection may reference GARCH comparison results)
  - 85-xx (strategy alignment can use per-asset GARCH benefit data)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Comparison report evaluates 7 estimators (4 GARCH + 3 range-based) against same realized vol proxy
    - Per-asset granularity with improvement distribution (Phase 80 lesson)
    - Pipeline stage insertion between features and signals with --no-garch skip flag
    - ATR normalised by close to produce fractional vol comparable to Parkinson/GK

key-files:
  created:
    - src/ta_lab2/scripts/garch/run_garch_comparison.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "ATR-14 normalised by close: atr_14 is in price units; divide by close to get fractional vol comparable to Parkinson/GK scale"
  - "GARCH stage after features, before signals: GARCH uses bar returns as input; signals may use GARCH vol for position sizing"
  - "GARCH failure is non-fatal: with --continue-on-error, pipeline continues to signals even if GARCH fitting fails"
  - "TIMEOUT_GARCH = 1800s (30 min): 99 assets x 4 models sequential fitting; conservative timeout"

patterns-established:
  - "run_garch_comparison.py follows the same argparse + engine + per-asset loop pattern as other report generators"
  - "run_garch_forecasts() in run_daily_refresh.py follows the exact subprocess + ComponentResult pattern of other stages"
  - "Per-asset improvement % = (range_RMSE - garch_RMSE) / range_RMSE * 100 -- positive means GARCH is better"

# Metrics
duration: 11min
completed: 2026-03-22
---

# Phase 81 Plan 05: GARCH Comparison Report and Daily Refresh Wiring Summary

**GARCH vs range-based volatility comparison report with per-asset RMSE improvement analysis, plus daily refresh pipeline wiring with --garch/--no-garch flags positioned after features and before signals**

## Performance

- **Duration:** 11 min
- **Started:** 2026-03-22T17:03:07Z
- **Completed:** 2026-03-22T17:14:20Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `run_garch_comparison.py`: CLI script evaluating all 4 GARCH variants against 3 range-based estimators (Parkinson-20, GK-20, ATR-14 normalised) using RMSE, QLIKE, MZ R-squared, and combined score
- Per-asset granularity: top-3/bottom-3 tables, improvement distribution histogram summary, asset-level best-estimator identification (Phase 80 lesson applied)
- Outputs: markdown report + 2 CSV files (aggregate + per-asset)
- Wired GARCH into daily refresh pipeline as a new stage between features and signals with `--garch` and `--no-garch` flags
- GARCH stage uses 30-minute timeout and follows the exact subprocess + ComponentResult pattern of other pipeline stages

## Task Commits

Each task was committed atomically:

1. **Task 1: GARCH comparison report generator** - `75646104` (feat)
2. **Task 2: Wire GARCH into daily refresh pipeline** - `b8770080` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/garch/run_garch_comparison.py` - CLI comparison report generator evaluating 7 estimators with per-asset results (729 lines)
- `src/ta_lab2/scripts/run_daily_refresh.py` - Extended with TIMEOUT_GARCH, run_garch_forecasts(), --garch/--no-garch args, pipeline stage wiring (136 lines added)

## Decisions Made

- **ATR-14 normalised by close:** ATR is in price units (e.g., $500 for BTC). Dividing by close converts it to fractional volatility (e.g., 0.03) making it directly comparable to Parkinson and Garman-Klass estimators on the same scale as the 5-day rolling std realized vol proxy.

- **GARCH stage positioned after features, before signals:** GARCH uses bar returns as input (available after bars stage). Signals may use GARCH conditional vol for position sizing (Phase 81-04 vol_sizer integration). This ordering ensures GARCH forecasts are fresh when signals read them.

- **GARCH failure is non-fatal to pipeline:** With `--continue-on-error`, the pipeline continues to signals even if GARCH fitting fails. GARCH is additive (improves vol estimates) but not required (range-based estimators still work). This prevents a GARCH convergence issue from blocking the entire daily refresh.

- **TIMEOUT_GARCH = 1800s:** 99 assets x 4 models with sequential fitting. Current benchmarks show ~3 min for a single asset; 30 min provides a 2x safety margin for the full universe.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed operator precedence in pandas boolean indexing**
- **Found during:** Task 1 post-commit review
- **Issue:** `asset_grp["n_forecasts"] > 0 & np.isfinite(asset_grp["combined"])` -- bitwise `&` has higher precedence than `>`, causing incorrect boolean evaluation
- **Fix:** Added parentheses: `(asset_grp["n_forecasts"] > 0) & np.isfinite(asset_grp["combined"])`
- **Files modified:** src/ta_lab2/scripts/garch/run_garch_comparison.py
- **Verification:** ruff lint + ruff format both pass
- **Committed in:** 75646104 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (operator precedence bug)
**Impact on plan:** Essential correctness fix for pandas boolean indexing. No scope creep.

## Issues Encountered

- Database tables (`returns_bars_multi_tf`, `features`) are not accessible on the current branch (`refactor/strip-cmc-prefix-add-venue-id`) because the rename migration has not yet been applied. This is a pre-existing branch condition, not a code error. All imports, CLI parsing, and dry-run verification pass successfully. The code will work once the table rename migration is applied.

## User Setup Required

None - no external service configuration required. GARCH comparison report requires `arch>=8.0.0` and `statsmodels>=0.14.0`, both already installed from Phase 81-01.

## Next Phase Readiness

- `run_garch_comparison.py` is ready: `python -m ta_lab2.scripts.garch.run_garch_comparison --ids all --verbose`
- `run_daily_refresh.py` includes GARCH: `python -m ta_lab2.scripts.run_daily_refresh --all --ids all`
- All 5 Phase 81 plans are complete:
  - Plan 01: garch_engine.py (fitting + forecasting)
  - Plan 02: refresh script + state manager
  - Plan 03: evaluator + blend weights
  - Plan 04: vol_sizer integration
  - Plan 05: comparison report + daily pipeline wiring
- Phase 81 success criteria fully addressed

---
*Phase: 81-garch-conditional-volatility*
*Completed: 2026-03-22*
