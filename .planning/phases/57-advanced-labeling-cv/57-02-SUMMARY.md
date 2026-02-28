---
phase: 57-advanced-labeling-cv
plan: "02"
subsystem: labeling
tags: [cusum, trend-scanning, ols, t-value, afml, event-filter, sample-weights]

# Dependency graph
requires:
  - phase: 57-01
    provides: "labeling package scaffold (triple_barrier.py, __init__.py base)"
provides:
  - "cusum_filter: symmetric CUSUM event filter returning pd.DatetimeIndex of triggered events"
  - "get_cusum_threshold: EWM volatility-based per-asset threshold calibration"
  - "validate_cusum_density: actionable density feedback for threshold tuning"
  - "trend_scanning_labels: OLS t-value based labels with optimal window selection"
  - "get_trend_weights: |t-value| normalized to [0,1] for sklearn sample_weight"
  - "get_t1_series: tz-aware t1 Series compatible with PurgedKFoldSplitter"
affects:
  - "57-04: CUSUM filter wired into signal generators as t_events pre-filter"
  - "Phase 60+: trend scanning consumed by trend-following strategy development"

# Tech tracking
tech-stack:
  added: [scipy.stats.linregress]
  patterns:
    - "Log-diff scale alignment: CUSUM filter and threshold both operate on log-return scale for consistency"
    - "tz-aware timestamp preservation: use .tolist() not .values to avoid numpy tz-stripping"
    - "Standalone library pattern: trend_scanning.py not wired to downstream in this phase"

key-files:
  created:
    - src/ta_lab2/labeling/cusum_filter.py
    - src/ta_lab2/labeling/trend_scanning.py
  modified:
    - src/ta_lab2/labeling/__init__.py

key-decisions:
  - "CUSUM operates on log-price diffs (not raw diffs) so scale matches log-return threshold"
  - "trend_scanning is a standalone library in Phase 57 -- no downstream wiring until Phase 60+"
  - "get_t1_series uses .tolist() not .values to preserve tz-aware Timestamp objects"

patterns-established:
  - "CUSUM-first pattern: run cusum_filter then pass t_events to apply_triple_barriers or trend_scanning_labels"
  - "Density validation: always call validate_cusum_density after cusum_filter to confirm calibration"

# Metrics
duration: 5min
completed: 2026-02-28
---

# Phase 57 Plan 02: CUSUM Event Filter and Trend Scanning Labels Summary

**Symmetric CUSUM event filter (AFML Ch.17) and OLS t-value trend scanning labels (AFML ML4AM Ch.2) as standalone library modules in src/ta_lab2/labeling/**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-28T07:04:21Z
- **Completed:** 2026-02-28T07:09:00Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- `cusum_filter`: symmetric CUSUM on log-price diffs returning sparse DatetimeIndex of event timestamps (201/1000 = 20.1% density on synthetic data -- within target)
- `trend_scanning_labels`: OLS regression over candidate windows [min_sample_length, look_forward_window], selects max |t-value|, assigns {-1, 0, +1} labels; t_events param for CUSUM-filtered efficiency
- `get_t1_series`: tz-aware t1 Series using `.tolist()` pattern to avoid numpy tz-stripping pitfall

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement CUSUM event filter** - `bf3e215b` (feat)
2. **Task 2: Implement trend scanning labels** - `d03ec7fd` (feat)

**Plan metadata:** (created below)

## Files Created/Modified

- `src/ta_lab2/labeling/cusum_filter.py` -- symmetric CUSUM filter, threshold calibration, density validation
- `src/ta_lab2/labeling/trend_scanning.py` -- OLS t-value trend scanning, sample weights, cv.py-compatible t1_series
- `src/ta_lab2/labeling/__init__.py` -- updated by 57-01 (triple_barrier exports already present); cusum + trend_scanning exports added

## Decisions Made

- **Log-diff scale alignment:** The plan specified `diff = raw_series.diff()` (raw price) but `get_cusum_threshold` uses EWM std of log-returns. For a price near 100 with 2% noise, raw diff ≈ 0.02 but log-return std ≈ 0.0002 -- a 50x scale mismatch causing 98% density. Fixed by computing `diff` on `log(raw_series)` so both filter and threshold operate in log-return units. This is the correct AFML implementation and produces 20.1% density (within target).
- **Standalone library:** `trend_scanning.py` is not wired to any downstream consumer in Phase 57. Plan explicitly states it will be consumed in Phase 60+ trend-following.
- **tz-aware preservation:** `get_t1_series` uses `.tolist()` instead of `.values` to preserve tz-aware Timestamp objects (numpy strips tz from `datetime64[ns, UTC]` when accessing `.values`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Log-diff scale alignment for cusum_filter**
- **Found during:** Task 1 (CUSUM smoke test)
- **Issue:** Plan specified `diff = raw_series.diff()` but threshold from `get_cusum_threshold` uses log-return std. On synthetic data (close ~100, noise 0.02), raw price diff ≈ 0.02 but log-return std ≈ 0.0002 -- threshold 50x too small, producing 98.4% density (target: 5-60%).
- **Fix:** Changed `diff` computation to `np.log(raw_series).diff()` so filter and threshold operate on consistent log-return scale. Result: 20.1% density, within target.
- **Files modified:** src/ta_lab2/labeling/cusum_filter.py
- **Verification:** Smoke test shows 201/1000 events (20.1% density, within_target=True)
- **Committed in:** bf3e215b (Task 1 commit)

**2. [Rule 1 - Bug] tz-aware timestamp stripping in get_t1_series**
- **Found during:** Task 2 (trend scanning smoke test)
- **Issue:** `pd.Series(t1_values.values, index=idx)` strips timezone from `datetime64[ns, UTC]` column -- `.values` returns tz-naive numpy array. Test showed `t1s.dt.tz is None`.
- **Fix:** Changed to `.tolist()` to preserve tz-aware Timestamp objects, then wraps in `pd.DatetimeIndex(t1_list)` -- consistent with MEMORY.md critical note about tz-aware timestamp pitfalls.
- **Files modified:** src/ta_lab2/labeling/trend_scanning.py
- **Verification:** `t1s.dt.tz is not None` now True; `t1s.dt.tz = UTC`
- **Committed in:** d03ec7fd (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both fixes necessary for correctness -- scale alignment for CUSUM density, tz preservation for PurgedKFoldSplitter compatibility. No scope creep.

## Issues Encountered

None beyond the two auto-fixed deviations documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- CUSUM filter ready for integration into signal generators (57-04)
- Trend scanning library complete and standalone -- available for Phase 60+ consumption
- Both modules handle tz-aware UTC timestamps correctly
- LABEL-04a (CUSUM) and LABEL-04b (trend scanning) core libraries complete
- Density validation helper enables per-asset threshold calibration workflow

---
*Phase: 57-advanced-labeling-cv*
*Completed: 2026-02-28*
