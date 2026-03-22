---
phase: 81-garch-conditional-volatility
plan: "04"
subsystem: analysis
tags: [garch, volatility, position-sizing, var, student-t, risk-management]

# Dependency graph
requires:
  - phase: 81-garch-conditional-volatility
    plan: "01"
    provides: garch_engine.py core fitting/forecasting, arch dependency
  - phase: 81-garch-conditional-volatility
    plan: "03"
    provides: garch_blend.py (blend_vol_simple, BlendConfig, get_blended_vol)
provides:
  - vol_sizer.py extended with GARCH blend support (3 modes)
  - var_simulator.py with garch_var function using Student's t quantiles
  - VaRResult.garch_var_value field for conditional VaR
  - var_to_daily_cap supports garch_95 and garch_99 methods
affects:
  - 81-05-PLAN (comparison report may use garch_var for risk analysis)
  - Future risk/position-sizing consumers can pass garch_vol for blend

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Student's t quantile scaled to unit-variance convention (sigma = actual std dev)
    - Three GARCH modes: sizing_only (blend), sizing_and_limits (blend), advisory (log only)
    - Per-bar GARCH blending in backtest via garch_vol_series parameter
    - GARCH-VaR at 99% captures fat tails better than normal; at 95% unit-variance scaling dominates

key-files:
  created: []
  modified:
    - src/ta_lab2/analysis/vol_sizer.py
    - src/ta_lab2/analysis/var_simulator.py

key-decisions:
  - "Student's t unit-variance scaling: raw t quantile scaled by sqrt((df-2)/df) so sigma_forecast maps to actual standard deviation, not t-scale parameter"
  - "GARCH-VaR uses mu=mean(returns) in compute_var_suite: conservative but consistent with parametric_var_normal convention"
  - "var_to_daily_cap raises ValueError when garch method used but no garch_var_value populated: fail-fast rather than silent fallback"

patterns-established:
  - "GARCH integration via optional parameters with safe defaults: all new params default to None/sizing_only/1.0"
  - "Advisory mode for GARCH: log comparison data without affecting production behavior"
  - "Per-bar GARCH blending: garch_vol_series.reindex + NaN-safe masking for partial GARCH coverage"

# Metrics
duration: 5min
completed: 2026-03-22
---

# Phase 81 Plan 04: GARCH Integration into Position Sizing and VaR Summary

**GARCH conditional vol blend in vol_sizer (3 modes: sizing/limits/advisory) plus Student's t GARCH-VaR in var_simulator with unit-variance scaling**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-22T17:00:45Z
- **Completed:** 2026-03-22T17:05:45Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Extended `compute_realized_vol_position` with optional `garch_vol`, `garch_mode`, `blend_weight` parameters supporting three operational modes
- Extended `run_vol_sized_backtest` with per-bar GARCH blending via `garch_vol_series` parameter with NaN-safe masking
- Added `garch_var` function using Student's t distribution (default df=6) with proper unit-variance scaling
- Extended `VaRResult` dataclass with `garch_var_value` field and `compute_var_suite` with GARCH parameters
- Extended `var_to_daily_cap` to support `garch_95` and `garch_99` methods
- Full backward compatibility maintained: all existing callers work unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend vol_sizer with GARCH blend support** - `8b88eee4` (feat)
2. **Task 2: Add GARCH-VaR to var_simulator** - `bf32e92c` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/analysis/vol_sizer.py` - Extended compute_realized_vol_position and run_vol_sized_backtest with GARCH blend parameters (3 modes: sizing_only, sizing_and_limits, advisory)
- `src/ta_lab2/analysis/var_simulator.py` - Added garch_var function with Student's t quantiles, extended VaRResult/compute_var_suite/var_to_daily_cap

## Decisions Made

- **Student's t unit-variance scaling:** The raw Student's t quantile is scaled by `sqrt((df-2)/df)` so that `sigma_forecast` maps directly to the actual standard deviation, not the t-distribution scale parameter. At 95% confidence with df=6, the scaled quantile (-1.587) is actually less extreme than normal (-1.645), but at 99% the fat-tail effect dominates (-2.566 vs -2.326). This is mathematically correct and desirable for risk calibration.

- **GARCH-VaR uses mu=mean(returns):** In `compute_var_suite`, the GARCH-VaR uses the sample mean of the historical returns as mu, consistent with how `parametric_var_normal` computes VaR. This is slightly more aggressive than mu=0 but consistent across all parametric methods.

- **var_to_daily_cap raises ValueError for empty garch results:** When `garch_95` or `garch_99` method is requested but no results have `garch_var_value` populated, a `ValueError` is raised rather than silently falling back. This fail-fast approach prevents misconfiguration from going unnoticed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. All dependencies (scipy) were already installed.

## Next Phase Readiness

- `vol_sizer.py` is ready for production use with GARCH forecasts from `garch_blend.py`
- `var_simulator.py` provides `garch_var` for conditional risk assessment
- Plan 05 (comparison report) can use `compute_var_suite(garch_sigma=...)` to include GARCH-VaR in risk analysis
- Downstream consumers can pass `garch_vol` from `get_blended_vol()` into `compute_realized_vol_position()` for GARCH-aware position sizing

---
*Phase: 81-garch-conditional-volatility*
*Completed: 2026-03-22*
