---
phase: 72-macro-observability
plan: 04
subsystem: drift
tags: [drift-attribution, macro-regime, cmc_drift_metrics, cmc_macro_regimes, DriftAttributor, AttributionResult, OAT]

# Dependency graph
requires:
  - phase: 72-01
    provides: "attr_macro_regime_delta column in cmc_drift_metrics via migration e6f7a8b9c0d1"
  - phase: 47
    provides: "DriftAttributor, AttributionResult, cmc_drift_metrics attr_* schema foundation"
provides:
  - "Step 7 macro regime attribution in DriftAttributor (OBSV-04)"
  - "persist_attribution() DB write path for all 9 attr_* columns to cmc_drift_metrics"
  - "attr_macro_regime_delta populated via run_drift_report.py --with-attribution"
  - "Drift Monitor dashboard shows 8 attribution sources including Macro Regime"
affects:
  - "72-macro-observability (plan 05 if any)"
  - "future drift attribution extensions"
  - "weekly drift report waterfall charts"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sequential OAT attribution extended: Step 7 macro regime delta via cmc_macro_regimes dominant state comparison"
    - "Heuristic penalty: state_distance * 0.005 * abs(step2_pnl) per macro state step"
    - "UPDATE-only persist pattern: attribution results written via UPDATE (not INSERT) requiring DriftMonitor base row"

key-files:
  created: []
  modified:
    - src/ta_lab2/drift/attribution.py
    - src/ta_lab2/scripts/drift/run_drift_report.py
    - src/ta_lab2/drift/drift_report.py
    - src/ta_lab2/dashboard/pages/8_drift_monitor.py

key-decisions:
  - "Heuristic scaling: -state_distance * 0.005 * abs(step2_pnl) per state step (0.5% of explained PnL) to avoid re-running full backtest"
  - "Backtest training period defined as 1 year before paper_start to paper_start-1d"
  - "Returns (0.0, {}) gracefully when cmc_macro_regimes has no data (table may be empty in early deployments)"
  - "persist_attribution() uses UPDATE not INSERT -- requires DriftMonitor base row to exist first"
  - "persist_attribution() called per week_end date only (not each day in window) to match report granularity"

patterns-established:
  - "Macro state ordering: favorable(0) < constructive(1) < neutral(2) < cautious(3) < adverse(4)"
  - "Attribution persist: UPDATE cmc_drift_metrics SET attr_* WHERE config_id AND asset_id AND metric_date"

# Metrics
duration: 9min
completed: 2026-03-03
---

# Phase 72 Plan 04: Macro Regime Drift Attribution Summary

**DriftAttributor Step 7 adds macro regime comparison between paper period and 1yr-prior backtest period, with persist_attribution() creating the previously-missing DB write path for all 9 attr_* columns**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-03T17:07:47Z
- **Completed:** 2026-03-03T17:17:07Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added `macro_regime_delta` field to `AttributionResult` dataclass as Step 7 source (after `regime_delta`, before `unexplained_residual`)
- Implemented `_compute_macro_regime_delta()` comparing dominant `macro_state` from `cmc_macro_regimes` between paper period and backtest training period (1 year prior); uses heuristic penalty of 0.5% of explained PnL per state distance step
- Implemented `persist_attribution()` that writes all 9 `attr_*` columns to `cmc_drift_metrics` via UPDATE -- fixing the previously-missing DB write path (attr_* columns were always NULL despite run_attribution() being called)
- Wired `persist_attribution()` call in `run_drift_report.py --with-attribution` after each `run_attribution()` call
- Added `attr_macro_regime_delta` to `_ATTR_COLUMNS` in `drift_report.py` for waterfall chart and markdown tables
- Added "Macro Regime" attribution source to drift monitor dashboard expander (8 sources total)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add macro_regime_delta to AttributionResult, DriftAttributor Step 7, and persist_attribution()** - `040d0626` (feat)
2. **Task 2: Wire persist_attribution in run_drift_report + update drift_report _ATTR_COLUMNS + dashboard display** - `48a9b6c5` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `src/ta_lab2/drift/attribution.py` - Added `macro_regime_delta` field to `AttributionResult`, `_MACRO_STATE_SCORE` dict, `_compute_macro_regime_delta()` method, `persist_attribution()` method, Step 7 in `run_attribution()`, updated total_explained calculation and logger.info format
- `src/ta_lab2/scripts/drift/run_drift_report.py` - Added `persist_attribution()` call after `run_attribution()` in `--with-attribution` block
- `src/ta_lab2/drift/drift_report.py` - Added `"attr_macro_regime_delta"` to `_ATTR_COLUMNS` list
- `src/ta_lab2/dashboard/pages/8_drift_monitor.py` - Added `"attr_macro_regime_delta"` to `attribution_cols` and `"Macro Regime"` label to `display_labels`

## Decisions Made

- **Heuristic scaling formula:** `-state_distance * 0.005 * abs(step2_pnl)`. Each state step = 0.5% of explained PnL. Negative because more adverse macro conditions reduce expected performance relative to favorable backtest conditions. Avoids re-running full backtest for macro attribution.
- **Backtest training period:** 1 year before `paper_start` to `paper_start - 1 day`. This is a pragmatic approximation -- the actual backtest training window would require querying `dim_executor_config` for training dates, which is not yet stored. Can be refined in a future plan.
- **Graceful degradation:** Returns `(0.0, {})` when `cmc_macro_regimes` has no matching rows. This covers early deployments before the macro classifier has populated data, and prevents Step 7 from breaking the attribution pipeline.
- **UPDATE-only persist:** `persist_attribution()` uses UPDATE not INSERT because `DriftMonitor._write_metrics()` must run first to create the base row. Logs a warning with row_count=0 to make the dependency visible in logs.
- **Per-week_end persist:** Attribution persisted for `week_end` date only (not each day in the window). Matches the report's granularity and the way `run_attribution()` aggregates the full period into a single result.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit `ruff-format` hook reformatted the file after the first write attempt, requiring a re-read and re-stage before the commit succeeded. This is expected behavior from the project's pre-commit configuration.

## User Setup Required

None - no external service configuration required. The `attr_macro_regime_delta` column already exists in `cmc_drift_metrics` from migration `e6f7a8b9c0d1` (Phase 72-01). Population requires running `python -m ta_lab2.scripts.drift.run_drift_report --with-attribution` after `cmc_macro_regimes` is populated by the macro classifier.

## Next Phase Readiness

- OBSV-04 requirement fully satisfied: DriftAttributor includes macro regime as drift attribution source
- attr_* columns in cmc_drift_metrics now have a complete write path (no longer always NULL)
- Dashboard attribution breakdown shows all 8 sources
- Phase 72 Wave 2 (plans 03 and 04) now both complete
- Remaining Phase 72 plans (if any) can build on the macro regime DB write path established here

---
*Phase: 72-macro-observability*
*Completed: 2026-03-03*
