---
phase: 105-parameter-optimization
plan: 02
subsystem: analysis
tags: [param-optimizer, plateau-score, rolling-stability, dsr, overfitting, ic, optuna, scipy, psr]

# Dependency graph
requires:
  - phase: 105-01
    provides: run_sweep, trial_registry sweep columns, IC-based Optuna sweep infrastructure
  - phase: 102
    provides: compute_rolling_ic (ic.py), compute_dsr (psr.py), haircut_ic_ir
provides:
  - plateau_score: fraction of neighboring params within 80% of peak IC (broad vs sharp peak)
  - rolling_stability_test: 5-window non-overlapping IC stability check (sign flips, IC CV)
  - compute_dsr_over_sweep: rolling-IC-based DSR with full sweep space deflation
  - select_best_from_sweep: orchestrates top-N → plateau → stability → DSR selection pipeline
affects:
  - Phase 103 indicator research (validate_coverage, trial_registry updates)
  - Phase 100 ML signal combination (feature selection quality gate)
  - Any sweep caller needing overfitting-aware param selection

# Tech tracking
tech-stack:
  added: []
  patterns:
    - plateau_score uses L-infinity distance in normalized param space for multi-param scale-invariance
    - rolling_stability_test uses np.array_split for equal non-overlapping windows; scipy.stats.spearmanr directly per window
    - compute_dsr_over_sweep passes rolling IC series as best_trial_returns to compute_dsr
    - select_best_from_sweep max() key selects by (plateau_score, ic) for deterministic tie-breaking

key-files:
  created: []
  modified:
    - src/ta_lab2/analysis/param_optimizer.py

key-decisions:
  - "compute_rolling_ic and compute_dsr imported at module level (not lazy): both are lightweight stdlib-only; no circular import risk"
  - "plateau_score returns 0.0 when best_ic <= 0: prevents meaningless neighbor fraction for negative-IC peaks"
  - "rolling_stability_test uses np.array_split (equal row splits) not date-based splits: robust to irregular bar counts per window"
  - "compute_dsr_over_sweep: when valid_ics is empty, falls back to n_trials=len(all_sweep_ics) approximate mode"
  - "select_best_from_sweep slices to train window before calling rolling_stability_test and compute_dsr_over_sweep: prevents out-of-window leakage"
  - "DB UPDATE in select_best_from_sweep wrapped in try/except: registry failure must not abort the selection result"

patterns-established:
  - "Plateau-before-peak: select by plateau_score among top-N IC candidates, not simply the peak-IC parameter"
  - "Rolling IC as proxy returns: feed rolling Spearman IC series into compute_dsr as best_trial_returns for parameter-level DSR"
  - "try/except around optional DB side-effects: DB failures logged as WARNING, computation result unaffected"

# Metrics
duration: 4min
completed: 2026-04-01
---

# Phase 105 Plan 02: Parameter Optimization — Overfitting-Aware Selection Summary

**Four overfitting-aware selection functions: plateau_score, rolling_stability_test, compute_dsr_over_sweep, and select_best_from_sweep added to param_optimizer.py using L-infinity normalized neighborhood, split-window Spearman stability, and sweep-space-deflated DSR**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-01T22:46:24Z
- **Completed:** 2026-04-01T22:49:42Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- `plateau_score`: measures IC robustness of a parameter set by computing fraction of L-infinity neighbors within 80% of peak IC; single-param uses absolute distance, multi-param uses normalized space for scale-invariance
- `rolling_stability_test`: splits train window into 5 non-overlapping chunks via `np.array_split`, computes per-window Spearman IC directly (not rolling), and reports sign_flips/ic_cv/passes
- `compute_dsr_over_sweep`: wraps `compute_rolling_ic` + `compute_dsr` to produce a rolling-IC-based DSR deflated by the full sweep space (all tested IC values as sr_estimates)
- `select_best_from_sweep`: orchestrates the full pipeline — top-N by IC → plateau ranking → stability test → DSR → optional trial_registry UPDATE

## Task Commits

Each task was committed atomically:

1. **Task 1: plateau_score and rolling_stability_test** — included in `0f20c3a5` (feat)
2. **Task 2: compute_dsr_over_sweep and select_best_from_sweep** — included in `0f20c3a5` (feat)

Both tasks implemented together in one ruff-clean commit.

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/ta_lab2/analysis/param_optimizer.py` — Added four new public functions plus module-level imports of `compute_rolling_ic` and `compute_dsr`; updated module docstring to reflect new public API

## Decisions Made
- `compute_rolling_ic` and `compute_dsr` imported at module level (not lazily): both are lightweight, no circular import risk, cleaner API surface
- `plateau_score` returns `0.0` when `best_ic <= 0`: negative-IC peaks have no meaningful positive neighborhood to measure
- `rolling_stability_test` uses `np.array_split` (equal row splits) not date-based splits: robust to irregular bar frequencies and variable observation density across calendar windows
- `compute_dsr_over_sweep` falls back to `n_trials=len(all_sweep_ics)` approximate mode when no valid ICs exist: defensive against all-NaN sweep results
- `select_best_from_sweep` slices to train window before stability test: prevents out-of-window data leaking into stability/DSR computations
- DB UPDATE in `select_best_from_sweep` wrapped in `try/except`: registry failure must not abort the returned selection result

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered
- Pre-commit `ruff-format` reformatted the file on first commit attempt (whitespace adjustments in multi-line conditions). Re-staged and committed successfully on second attempt.

## Next Phase Readiness
- `select_best_from_sweep` is ready for integration into indicator sweep callers (Phase 103-03, future Phase 105-03 if planned)
- `trial_registry` UPDATE requires columns `plateau_score`, `rolling_stability_passes`, `ic_cv`, `sign_flips`, `dsr_adjusted_sharpe` to exist — these were added in the Phase 105-01 migration (`y8z9a0b1c2d3`)
- No blockers for Phase 105-03 or downstream ML phases

---
*Phase: 105-parameter-optimization*
*Completed: 2026-04-01*
