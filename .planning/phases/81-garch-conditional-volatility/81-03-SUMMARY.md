---
phase: 81-garch-conditional-volatility
plan: "03"
subsystem: analysis
tags: [garch, volatility, rmse, qlike, mincer-zarnowitz, statsmodels, forecast-combination, bates-granger]

# Dependency graph
requires:
  - phase: 81-garch-conditional-volatility
    plan: "01"
    provides: garch_engine.py (fit_single_variant, fit_all_variants, MODEL_SPECS, GARCHResult)
  - phase: 80-ic-analysis-feature-selection
    provides: statsmodels in [analysis] optional group (OLS for MZ regression)
provides:
  - garch_evaluator.py with RMSE, QLIKE, MZ R2, realized vol proxy, rolling OOS evaluation
  - garch_blend.py with BlendConfig, inverse-RMSE blend weights, blended vol lookup
affects:
  - 81-04-PLAN (vol_sizer integration uses blend_vol_simple and get_blended_vol)
  - 81-05-PLAN (comparison report uses evaluate_all_models and rolling_oos_evaluate)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Iterative min-weight floor: floor low-weight estimators then redistribute mass (Bates-Granger)
    - QLIKE loss: clip sigma^2 and realized^2 to 1e-16 (not 1e-8) to avoid log(0)/div-by-zero
    - RMSE: clip both inputs to 1e-8 minimum before computation
    - Forecast alignment: h=1 forecast from fitting through bar t evaluates against realized at t+1
    - Lazy import of garch_engine inside rolling_oos_evaluate (arch optional dependency)

key-files:
  created:
    - src/ta_lab2/analysis/garch_evaluator.py
    - src/ta_lab2/analysis/garch_blend.py
  modified: []

key-decisions:
  - "QLIKE clips sigma^2 and realized^2 to 1e-16 (not sigma to 1e-8): prevents log(0) and div-by-zero at the variance level"
  - "Iterative floor for compute_blend_weights: clip-then-renormalize single-pass is wrong (renormalization can push high-weight estimators below floor); iterative redistribution is correct"
  - "get_blended_vol falls back to equal weights when no trailing RMSE available: RMSE history requires Plan 05 report infrastructure; equal-weight is safe default"
  - "rolling_oos_evaluate uses step=21 (monthly) by default: captures regime changes without excessive runtime"

patterns-established:
  - "garch_evaluator.py is pure computation (no DB, no CLI) -- same pattern as garch_engine.py"
  - "garch_blend.py has mixed pure (compute_blend_weights, blend_vol_simple) and DB-aware (get_blended_vol) functions"
  - "DB-aware functions take SQLAlchemy Engine as positional parameter, matching project-wide convention"

# Metrics
duration: 6min
completed: 2026-03-22
---

# Phase 81 Plan 03: GARCH Evaluation and Blend Weights Summary

**RMSE/QLIKE/Mincer-Zarnowitz evaluation framework plus iterative inverse-RMSE blend weights combining GARCH variants with range-based vol estimators**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-22T16:47:51Z
- **Completed:** 2026-03-22T16:53:51Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `garch_evaluator.py`: pure computation module with RMSE, QLIKE (Patton 2011), Mincer-Zarnowitz R2, realized vol proxy (5-day rolling std), rolling OOS evaluation with correct t+1 alignment, and full evaluate_all_models harness
- Created `garch_blend.py`: BlendConfig dataclass, iterative inverse-RMSE blend weights with proper min-weight floor, trailing RMSE computation, DB-aware `get_blended_vol` from garch_forecasts_latest, and `blend_vol_simple` for inline use in vol_sizer
- All verification checks pass: finite metric values, blend weights sum to 1.0, floor constraints respected, QLIKE handles zero-vol edge case

## Task Commits

Each task was committed atomically:

1. **Task 1: GARCH evaluation framework** - `b2687ef9` (feat)
2. **Task 2: Inverse-RMSE blend weight system** - `08c49d4e` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/analysis/garch_evaluator.py` - RMSE loss, QLIKE loss, Mincer-Zarnowitz R2, compute_realized_vol_proxy, combined_score, rolling_oos_evaluate, evaluate_all_models (423 lines)
- `src/ta_lab2/analysis/garch_blend.py` - BlendConfig, compute_blend_weights, compute_trailing_rmse, get_blended_vol, blend_vol_simple (403 lines)

## Decisions Made

- **QLIKE clips variances to 1e-16:** Per Patton (2011), QLIKE is defined as `log(sigma^2) + realized^2/sigma^2`. Clipping sigma and realized individually to 1e-8 leaves sigma^2 at 1e-16 minimum, but it is cleaner to clip the squared quantities directly. This ensures `log(0)` and division-by-zero cannot occur regardless of floating-point behavior.

- **Iterative floor for blend weights:** The naive approach (clip all weights to min_weight then renormalize) is incorrect because renormalization can push previously-above-floor estimators below the floor. The correct approach iteratively: (1) identify estimators below the floor, (2) lock them at the floor, (3) redistribute remaining mass proportionally over unconstrained estimators, (4) repeat until convergence. This guarantees all weights >= min_weight AND sum to 1.0.

- **get_blended_vol uses equal weights as fallback:** Computing proper trailing RMSE weights requires a history of stored forecasts aligned with realized vol, which is the domain of Plan 05 (comparison report). Rather than block Plan 04 (vol_sizer integration), `get_blended_vol` falls back to equal weights when no trailing RMSE is provided. Plan 05 can replace this with dynamic RMSE-weighted blending once the forecast history exists.

- **rolling_oos_evaluate step=21 (monthly):** Monthly steps produce ~12 OOS points per year, sufficient to track regime-dependent performance while keeping runtime acceptable. The expanding window ensures the full available history is always used for fitting.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed iterative min-weight floor in compute_blend_weights**

- **Found during:** Task 2 verification (`assert all(v >= 0.05 - 1e-9 for v in w2.values())` failed)
- **Issue:** Single-pass clip-then-renormalize can push originally-above-floor estimators below the floor after renormalization. With RMSE dict `{'a': 0.01, 'b': 0.01, 'c': 0.5}` and min_weight=0.05, `c` should be floored to 0.05 but after renormalization ended up at 0.048 (below floor).
- **Fix:** Replaced with iterative redistribution: lock floored estimators at min_weight, rescale free estimators proportionally to absorb remaining mass, repeat until no estimators are below floor.
- **Files modified:** src/ta_lab2/analysis/garch_blend.py
- **Verification:** `compute_blend_weights({'a': 0.01, 'b': 0.01, 'c': 0.5}, min_weight=0.05)` returns `{'a': 0.475, 'b': 0.475, 'c': 0.05}` -- all >= 0.05, sums to 1.0.
- **Committed in:** 08c49d4e (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (logic bug in floor normalization)
**Impact on plan:** Essential correctness fix. The floor guarantee is a stated requirement of the Bates-Granger combination method. No scope creep.

## Issues Encountered

- ruff format reformatted both files on first commit attempt (long lines in f-string and list comprehension). Re-staged after format pass on both files. Pre-commit hook handled gracefully.

## User Setup Required

None - no external service configuration required. All dependencies (statsmodels, arch) were already installed in Plan 01.

## Next Phase Readiness

- `garch_evaluator.py` is importable, all 7 functions verified functional
- `garch_blend.py` is importable, all 5 functions verified functional
- Plan 04 (vol_sizer integration) can use `blend_vol_simple` and `get_blended_vol` immediately
- Plan 05 (comparison report) can use `evaluate_all_models` and `rolling_oos_evaluate` directly
- `compute_trailing_rmse` is ready to consume forecast history once Plan 02 populates `garch_forecasts`

---
*Phase: 81-garch-conditional-volatility*
*Completed: 2026-03-22*
