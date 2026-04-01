---
phase: 111-feature-polars-migration
plan: 03
subsystem: features
tags: [polars, performance, migration, ta, rsi, macd, stochastic, bollinger, atr, adx, regression]

dependency_graph:
  requires:
    - phase: 111-01
      provides: polars_feature_ops.py infrastructure, use_polars flag in FeatureConfig, polars_sorted_groupby
    - phase: 111-02
      provides: ATR null-propagation pattern (pl.when(prev_close.is_null()) + ignore_nulls=True), HAVE_POLARS guard pattern
  provides:
    - 6 polars-native indicator functions in indicators.py (rsi_polars, macd_polars, stoch_kd_polars, bollinger_polars, atr_polars, adx_polars)
    - TAFeature polars compute path (use_polars=True)
    - Bug fix: _compute_rsi/atr/adx used period= alias which always defaulted to window=14
  affects:
    - future polars migration phases (microstructure_feature)
    - ta sub-phase performance in production (opt-in via use_polars=True)
    - correctness of RSI-7, RSI-21, ATR-N, ADX-N when period != 14

tech-stack:
  added: []
  patterns:
    - "polars indicator functions: intermediate columns use dunder prefix (__col__) to avoid name collisions, dropped before return"
    - "atr_polars uses rolling_mean (NOT ewm_mean) matching indicators.py -- distinct from vol.py add_atr_polars which uses Wilder EWM"
    - "macd_polars uses span= parameter for EMA (polars 1.36.1+), matching pandas ewm(span=)"
    - "rsi_polars uses alpha=1/period (Wilder smoothing), matching pandas ewm(alpha=)"
    - "Phase 103 extended indicators fall back to pandas in polars path (convert->apply->convert); only 6 core indicators use native polars"

key-files:
  created: []
  modified:
    - src/ta_lab2/features/indicators.py
    - src/ta_lab2/scripts/features/ta_feature.py

key-decisions:
  - "atr_polars uses rolling_mean not ewm_mean: indicators.py atr() uses rolling().mean(), distinct from vol.py add_atr which uses Wilder EWM. Both patterns now available."
  - "Phase 103 extended indicators stay pandas in polars path: convert-apply-convert pattern avoids rewriting 20+ complex indicators; only 6 core indicators migrated"
  - "Rule 1 bug fix: _compute_rsi/atr/adx used period= keyword; rsi/atr/adx functions only apply alias when window=None, so window=14 default was always used. Fixed to window=period."
  - "Intermediate column dunder naming (__col__): prevents collision with user columns; all cleaned up before return"
  - "HAVE_POLARS in indicators.py: separate from polars_feature_ops.HAVE_POLARS -- indicators.py is a standalone module used independently"

patterns-established:
  - "Polars indicator functions: single-group pl.DataFrame in, pl.DataFrame out, intermediate columns dropped on exit"
  - "Polars path extension: TAFeature polars closure calls polars functions for 6 core indicators, falls back to pandas for Phase 103 extended indicators"

metrics:
  tasks_completed: 2
  tasks_total: 2
  duration: 14 min
  completed: "2026-04-01"
---

# Phase 111 Plan 03: Feature Polars Migration - TA Sub-Phase Summary

**6 polars-native indicator functions (RSI/MACD/Stoch/BB/ATR/ADX) with TAFeature polars path, all 16 TA columns within 1.42e-13 of corrected pandas path; pre-existing RSI/ATR/ADX period=N alias bug fixed.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-04-01T23:24:06Z
- **Completed:** 2026-04-01T23:38:42Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- 6 polars-native indicator functions added to `indicators.py` in `# === Polars Variants ===` section with zero changes to existing pandas functions
- TAFeature.compute_features() branches on `use_polars`: polars path handles 6 core indicators natively; Phase 103 extended indicators use convert-apply-convert pandas fallback
- Pre-existing bug fixed: `_compute_rsi`, `_compute_atr`, `_compute_adx` all used `period=` keyword which doesn't override `window=14` default; fixed to `window=period`
- Regression verified on 3-asset synthetic data (600 rows): all 16 TA columns pass < 1e-10 tolerance (worst case 1.42e-13 for MACD-8/17)

## Task Commits

1. **Task 1: Polars-native indicator functions in indicators.py** - `1dd99f1c` (feat)
2. **Task 2: Wire polars indicators into TAFeature + bug fix** - `4ce58419` (feat)

**Plan metadata:** see below (docs commit)

## Files Created/Modified

- `src/ta_lab2/features/indicators.py` - Added `HAVE_POLARS` constant + conditional polars import + 6 polars-native indicator functions in `# === Polars Variants ===` section
- `src/ta_lab2/scripts/features/ta_feature.py` - Added polars imports, `compute_features()` polars branch dispatching via `polars_sorted_groupby`, Rule 1 bug fix in `_compute_rsi/_compute_atr/_compute_adx`

## Decisions Made

**`atr_polars` uses `rolling_mean`, not `ewm_mean`:**
- `indicators.py atr()` uses `rolling().mean()` (simple average True Range)
- `vol.py add_atr()` uses Wilder EWM (`ewm(alpha=1/period)`)
- These are different indicators; `atr_polars` matches `indicators.py atr()` exactly
- `vol.py add_atr_polars` (from 111-02) matches `vol.py add_atr()` with EWM

**Phase 103 extended indicators stay pandas in polars path:**
- 20 extended indicators (ichimoku, willr, keltner, cci, etc.) use complex computation via `indicators_extended.py`
- Convert-apply-convert pattern: `pl_df` → `pandas_to_polars_df` → `polars_to_pandas_df` → extended indicator → `pandas_to_polars_df`
- Avoids rewriting 20+ complex indicators; only core 6 are performance-critical
- Future plans can migrate extended indicators if profiling shows they're bottlenecks

**Intermediate column dunder naming:**
- `macd_polars` uses `__macd_ema_fast__`, `__macd_ema_slow__`, `__macd_line__` as intermediates
- `adx_polars` uses `__adx_tr__`, `__adx_atr__`, etc.
- All dropped before return to keep output clean and avoid downstream column surprises

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pre-existing RSI/ATR/ADX period alias bug in `_compute_rsi`, `_compute_atr`, `_compute_adx`**

- **Found during:** Task 2 regression test (all 3 RSI periods produced identical values)
- **Issue:** `rsi(df, period=period, ...)` passes `period=` keyword but `rsi()` signature has `window: int = 14` as primary arg with `period: int | None = None` as alias. The alias logic only applies when `window is None`. When called as `rsi(df, period=21)`, `window` stays as 14 (default), so RSI-21 and RSI-7 both computed RSI-14. Same bug in `_compute_atr` and `_compute_adx`.
- **Fix:** Changed to `rsi(df, window=period, ...)`, `atr(df, window=period, ...)`, `adx(df, window=period, ...)` — uses the primary `window` parameter directly
- **Files modified:** `src/ta_lab2/scripts/features/ta_feature.py`
- **Verification:** RSI-7 (77.389), RSI-14 (86.763), RSI-21 (90.739) now produce correct distinct values; confirmed against standalone `rsi(pd.Series(close), window=7)` call
- **Committed in:** `4ce58419` (part of Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Critical fix for correctness. All RSI/ATR/ADX computations with period != 14 were silently using period=14. The polars path (computing correctly from the start) served as the regression detector. The bug was pre-existing and masked because production DB never ran multi-period RSI through the TAFeature pandas path in unit tests.

## Issues Encountered

**RSI divergence during regression test:** The initial regression test showed RSI-7 and RSI-21 diverging between polars and pandas paths. Investigation revealed the polars path was CORRECT and the pandas path was wrong (pre-existing bug). Once the pandas bug was fixed, all indicators matched within 1.42e-13.

## Next Phase Readiness

Phase 111 Plan 04 (microstructure_feature polars migration) can proceed:
- Infrastructure from Plans 01-02 still in place
- Pattern for polars compute closures well-established (vol_feature, ta_feature)
- ATR null-propagation pattern documented from 111-02
- `polars_sorted_groupby` tested across 3 sub-phases

No blockers.

---
*Phase: 111-feature-polars-migration*
*Completed: 2026-04-01*
