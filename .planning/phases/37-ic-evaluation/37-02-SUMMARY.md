---
phase: 37-ic-evaluation
plan: "02"
subsystem: analysis
tags: [spearman-ic, rolling-ic, ic-ir, feature-turnover, scipy, tdd, numpy, pandas]

# Dependency graph
requires:
  - phase: 37-01
    provides: cmc_ic_results Alembic migration and fillna deprecation fix in feature_eval.py
provides:
  - compute_ic() — full IC table (14 rows, 7 horizons x 2 return types) with required train_start/train_end
  - compute_forward_returns() — arithmetic and log forward returns on full series
  - _compute_single_ic() — Spearman IC + t-stat + p-value with boundary masking
  - compute_rolling_ic() — vectorized rolling IC + IC-IR + IC-IR t-stat
  - compute_feature_turnover() — rank autocorrelation proxy (1 - lag-1 spearmanr)
  - _ic_t_stat() and _ic_p_value() — significance testing helpers
  - 44-test suite covering all IC behaviors including boundary masking and edge cases
affects:
  - 37-03 (CLI run_ic_eval.py — uses compute_ic as scoring engine)
  - 38-feature-experimentation (ExperimentRunner uses compute_ic for feature promotion scoring)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - TDD Red-Green-Refactor with per-phase commits (test/feat/refactor)
    - scipy.stats.spearmanr with .statistic attribute (scipy 1.17.0 API)
    - Vectorized rolling IC via rolling().rank() then rolling().corr() (30x faster than per-window spearmanr loop)
    - Boundary masking via DatetimeIndex + Timedelta comparison (look-ahead bias prevention)
    - fwd_ret.reindex(feat_train.index) for safe index alignment across different-length series
    - 1e-15 floor on IC t-stat denominator to guard against |ic|=1 division-by-zero

key-files:
  created:
    - src/ta_lab2/analysis/ic.py
    - tests/analysis/__init__.py
    - tests/analysis/test_ic.py
  modified: []

key-decisions:
  - "fwd_ret.reindex() not boolean mask for index alignment — handles mismatched series lengths safely"
  - "DatetimeIndex + Timedelta comparison returns numpy bool array directly — no .to_numpy() call needed"
  - "boundary_mask computed via feat_train.index + horizon_delta > train_end — explicit look-ahead prevention"
  - "feat_train sliced once per compute_ic call (outside horizon loop) for efficiency"
  - "has_enough_for_rolling pre-computed guard avoids rolling IC setup for very short windows"
  - "_ic_t_stat and _ic_p_value exported as module-level functions for direct test assertions"

patterns-established:
  - "IC boundary masking pattern: compute fwd_ret on full series, then reindex+null boundary bars"
  - "Rolling IC via rank-then-correlate: rolling().rank() then rolling().corr() (vectorized Spearman)"
  - "IC-IR = mean(rolling_ic.dropna()) / std(rolling_ic.dropna(), ddof=1)"
  - "IC-IR t-stat = mean * sqrt(n) / std (equivalent to ttest_1samp t-stat on rolling IC values)"
  - "Turnover = 1 - spearmanr(ranks[:-1], ranks[1:]).statistic"
  - "TDD: test file committed first (RED), then implementation (GREEN), then cleanup (REFACTOR)"

# Metrics
duration: 6min
completed: "2026-02-24"
---

# Phase 37 Plan 02: IC Core Computation Library Summary

**Spearman IC library with vectorized rolling IC (rank-then-correlate), IC-IR, boundary masking for look-ahead prevention, feature turnover, and significance testing — 44 tests, TDD workflow**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-24T02:01:16Z
- **Completed:** 2026-02-24T02:07:44Z
- **Tasks:** 1 (TDD: 3 commits — test/feat/refactor)
- **Files modified:** 3 (ic.py created, tests/analysis/__init__.py + test_ic.py created)

## Accomplishments

- `compute_ic()` public API with REQUIRED train_start/train_end (TypeError if omitted), returning 14-row DataFrame (7 horizons x 2 return types) with columns: horizon, return_type, ic, ic_t_stat, ic_p_value, ic_ir, ic_ir_t_stat, turnover, n_obs
- Vectorized rolling Spearman IC using `rolling().rank()` + `rolling().corr()` — avoids 30-second per-window loop overhead
- Boundary masking: bars where `bar_ts + horizon_days > train_end` have forward returns nulled before computing IC, preventing look-ahead bias
- IC t-stat with 1e-15 denominator floor guard for |IC|=1 edge case; two-sided p-value via `norm.cdf`
- Feature turnover = 1 - rank_autocorrelation(lag=1) via `spearmanr`; NaN for n < 20
- 44-test suite covering all 6 behavioral categories (ForwardReturns, IC, BoundaryMasking, RollingIC, Significance, Turnover)

## Task Commits

TDD cycle (RED-GREEN-REFACTOR):

1. **RED — Failing test suite** - `8341a35d` (test)
2. **GREEN — IC library implementation** - `21fecb17` (feat)
3. **REFACTOR — Hoist train-window slice out of loop** - `7781ef81` (refactor)

## Files Created/Modified

- `src/ta_lab2/analysis/ic.py` — IC computation library: compute_ic, compute_forward_returns, compute_rolling_ic, compute_feature_turnover, _compute_single_ic, _ic_t_stat, _ic_p_value (421 lines)
- `tests/analysis/__init__.py` — Empty package init for tests/analysis/
- `tests/analysis/test_ic.py` — Comprehensive test suite: 6 test classes, 44 tests (613 lines)

## Decisions Made

- **fwd_ret.reindex() not boolean mask**: When `fwd_ret` index differs in length from `feat_train.index` (e.g., boundary masking test), boolean indexing raises IndexError. `reindex()` aligns by label safely.
- **No .to_numpy() on DatetimeIndex arithmetic**: `(feat_train.index + horizon_delta) > train_end` returns a numpy bool array directly (not a pandas BooleanArray). Calling `.to_numpy()` on it raised AttributeError.
- **feat_train sliced once per compute_ic call**: The train-window mask is the same for all (horizon, return_type) combinations — hoisted outside the loop in REFACTOR phase.
- **_ic_t_stat and _ic_p_value as module-level functions**: Tests import them directly for formula correctness assertions without going through compute_ic. Cleaner than testing only through the public API.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `.to_numpy()` AttributeError on numpy bool array**
- **Found during:** GREEN phase — test run after implementing ic.py
- **Issue:** `boundary_mask = (feat_train.index + horizon_delta) > train_end` returns numpy bool array; calling `.to_numpy()` on it raised `AttributeError: 'numpy.ndarray' object has no attribute 'to_numpy'`
- **Fix:** Removed `.to_numpy()` call — use `boundary_mask` directly with `.iloc[]`
- **Files modified:** `src/ta_lab2/analysis/ic.py`
- **Verification:** 44/44 tests pass
- **Committed in:** `21fecb17` (GREEN feat commit)

**2. [Rule 1 - Bug] Fixed IndexError on mismatched boolean mask length**
- **Found during:** GREEN phase — `TestBoundaryMasking.test_boundary_prevents_look_ahead`
- **Issue:** Test passes `fwd_ret` with 100-bar index and `feature` with 50-bar index; `fwd_ret[mask]` where mask length = 50 but fwd_ret length = 100 raised `IndexError: Boolean index has wrong length: 50 instead of 100`
- **Fix:** Changed `fwd_train = fwd_ret[mask]` to `fwd_train = fwd_ret.reindex(feat_train.index).copy()` — aligns by label, not positional mask
- **Files modified:** `src/ta_lab2/analysis/ic.py`
- **Verification:** 44/44 tests pass after fix
- **Committed in:** `21fecb17` (GREEN feat commit)

---

**Total deviations:** 2 auto-fixed (Rule 1 - Bug x2)
**Impact on plan:** Both fixes were implementation bugs discovered during GREEN phase, not scope changes. Plan executed as designed.

## Issues Encountered

- Pre-commit `ruff format` hook reformatted both files (CRLF->LF line ending normalization on Windows + formatting). Required re-staging before commit. Standard workflow on this system.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `compute_ic()` library is ready for 37-03 (CLI `run_ic_eval.py`) to import and call
- All must-haves satisfied: IC-01 (Spearman IC per horizon), IC-02 (rolling IC + IC-IR), IC-03 (IC decay table as sorted DataFrame), IC-04 (train_start/train_end required + boundary masking), IC-06 (t-stat + p-value), IC-07 (feature turnover)
- Phase 38 (ExperimentRunner) can import `compute_ic` as its scoring engine
- No blockers

---
*Phase: 37-ic-evaluation*
*Completed: 2026-02-24*
