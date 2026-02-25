---
phase: 48-loss-limits-policy
plan: 02
subsystem: analysis
tags: [vectorbt, stop-loss, trailing-stop, time-stop, simulation, portfolio, numpy]

# Dependency graph
requires:
  - phase: 48-loss-limits-policy/48-01
    provides: analysis package skeleton, __init__.py foundation
provides:
  - stop_simulator.py with simulate_hard_stop, simulate_trailing_stop, simulate_time_stop
  - sweep_stops: full sweep returning DataFrame of scenario results
  - compute_recovery_time: average bars from drawdown trough to equity peak recovery
  - extract_scenario_metrics: StopScenarioResult dataclass with all 9 metrics
  - STOP_THRESHOLDS and TIME_STOP_BARS constants
affects:
  - 48-03 (stop report CLI will import sweep_stops)
  - future signal evaluation phases that need stop sensitivity analysis

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "tz-strip pattern: price.index.tz_localize(None) before vectorbt ingestion"
    - "numpy vectorized time-stop: np.where(entries) + n_bars offset, clip to array length"
    - "recovery time: iterate equity, track cummax peak, record durations of completed drawdowns"
    - "wave-1 parallel __init__.py: both plans write identical content with noqa: F401"

key-files:
  created:
    - src/ta_lab2/analysis/stop_simulator.py
  modified:
    - src/ta_lab2/analysis/__init__.py

key-decisions:
  - "Time-stop implemented via custom numpy-vectorized exit arrays (vectorbt 0.28.1 has no native time-stop param)"
  - "Recovery time returns np.nan when equity never recovers from final drawdown (not zero)"
  - "sweep_stops returns empty DataFrame with correct columns when no entries exist (guard against ZeroDivisionError)"
  - "win_rate returns 0.0 (not NaN) when trade_count == 0 to avoid downstream type errors"
  - "opportunity_cost = baseline_return - stop_return (positive when stop reduces returns)"

patterns-established:
  - "Stop simulator is pure library: no DB, no CLI, no reports - only price+signal inputs, Portfolio/DataFrame outputs"
  - "All vbt.Portfolio.from_signals calls use init_cash=1000, freq=D, fees=fee_bps/1e4"
  - "sharpe_ratio(freq=365) for crypto 365-day annualization"

# Metrics
duration: 8min
completed: 2026-02-25
---

# Phase 48 Plan 02: Stop Simulator Library Summary

**Stop-loss simulation library using vectorbt 0.28.1: hard stop (sl_stop), trailing stop (sl_trail), and numpy-vectorized time-stop sweep across 6 thresholds returning Sharpe/MaxDD/recovery metrics**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-25T05:26:40Z
- **Completed:** 2026-02-25T05:34:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Built complete stop-loss simulation library with 3 stop types and full sweep capability
- Implemented time-stop via custom numpy-vectorized exit arrays (vectorbt has no native parameter)
- Computed recovery time as average bars from equity trough to peak (np.nan when never recovered)
- sweep_stops returns tidy DataFrame with 9 columns sorted by (stop_type, threshold) for downstream analysis

## Task Commits

Each task was committed atomically:

1. **Task 1: Stop simulator library module** - `daddfdf3` (feat)
2. **Task 2: Update analysis __init__.py with stop simulator exports** - `69955e6d` (chore)

## Files Created/Modified

- `src/ta_lab2/analysis/stop_simulator.py` - Pure simulation library: simulate_hard_stop, simulate_trailing_stop, simulate_time_stop, compute_recovery_time, extract_scenario_metrics, sweep_stops, StopScenarioResult dataclass
- `src/ta_lab2/analysis/__init__.py` - Re-exports both var_simulator and stop_simulator with try/except ImportError + noqa: F401

## Decisions Made

- **Time-stop via custom exits:** vectorbt 0.28.1 has no `n_bars` parameter. Built custom exit array: `entry_indices + n_bars` clipped to array length, ORed with original exits. Used `np.where(entries.values)` for vectorization.
- **recovery_time algorithm:** Iterate equity, track running cummax peak. When equity >= peak after a drawdown, record `i - drawdown_start`. Return mean. Return np.nan when no recoveries completed.
- **win_rate guard:** `pf.trades.win_rate()` raises ZeroDivisionError when trade_count == 0. Wrapped in try/except returning 0.0.
- **noqa: F401 in __init__.py:** ruff F401 fires on re-export imports. Added `# noqa: F401` on both import statements. Plan 01 had already written this correctly when this plan ran.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added noqa: F401 to __init__.py re-exports**

- **Found during:** Task 2 (Update analysis __init__.py)
- **Issue:** ruff pre-commit hook flagged F401 "imported but unused" on all re-export imports in __init__.py
- **Fix:** Added `# noqa: F401` to both import blocks (var_simulator and stop_simulator). Plan 01 had already written the correct version by the time this plan ran.
- **Files modified:** src/ta_lab2/analysis/__init__.py
- **Verification:** ruff lint passes in pre-commit
- **Committed in:** 69955e6d (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: ruff F401 lint error in __init__.py)
**Impact on plan:** Minor fix required for pre-commit compliance. No scope creep.

## Issues Encountered

- Pre-commit hooks (ruff-format, trailing-whitespace, mixed-line-ending) modified stop_simulator.py on first commit attempt due to Windows CRLF line endings. Resolved by re-staging after hook fixes and committing again. Standard Windows git behavior.
- __init__.py F401 ruff error on re-export pattern. Fixed with `# noqa: F401`. Plan 01 had already handled this correctly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- stop_simulator.py is complete and verified with synthetic price data
- sweep_stops returns correct DataFrame with all 3 stop types and 9 columns
- Ready for Plan 03 (stop report CLI and HTML report generation)
- Plan 01 (VaR simulator) ran in parallel — analysis package now has both VaR and stop simulator

---
*Phase: 48-loss-limits-policy*
*Completed: 2026-02-25*
