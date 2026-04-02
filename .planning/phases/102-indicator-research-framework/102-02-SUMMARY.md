---
phase: 102-indicator-research-framework
plan: 02
subsystem: analysis
tags: [multiple-testing, bonferroni, harvey-liu, sharpe-haircut, ic-ir, block-bootstrap, arch, scipy, trial-registry]

# Dependency graph
requires:
  - phase: 102-01
    provides: "multiple_testing.py module with permutation_ic_test, fdr_control, log_trials_to_registry"
provides:
  - "haircut_sharpe(): Bonferroni HL 2015 Sharpe ratio haircut for data snooping"
  - "haircut_ic_ir(): Bonferroni HL 2015 IC-IR haircut with DB write to trial_registry.haircut_ic_ir"
  - "get_trial_count(): DB helper to fetch total trial count from trial_registry"
  - "block_bootstrap_ic(): autocorrelation-preserving 95% CI via arch StationaryBootstrap"
affects:
  - phase-102-03
  - indicator-research
  - research-harness

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bonferroni HL 2015: convert SR/IC-IR to t-stat, one-sided p-value, scale by n_trials, back-convert"
    - "Block bootstrap pair sampling: apply bs.index to both feature and returns to preserve alignment"
    - "arch 8.0.0: optimal_block_length() returns DataFrame with column 'stationary' (not 'b_sb')"

key-files:
  created:
    - src/ta_lab2/analysis/multiple_testing.py
  modified: []

key-decisions:
  - "Block bootstrap applied to (feature, returns) pair indices jointly (not returns-only): preserves IC signal across bootstrap samples"
  - "arch 8.0.0 column name 'stationary' explicitly used (not 'b_sb' from older versions)"
  - "haircut_ic_ir with conn=None and no indicator_name/tf skips DB write silently — enables pure-computation use in notebooks"
  - "FREQ_TO_MONTHLY mapping applied to n_obs to normalize to monthly scale before t-stat computation"

patterns-established:
  - "Bonferroni haircut pattern: sr_m = sr / sqrt(12), t = sr_m * sqrt(n_monthly), p * n_trials, back-convert"
  - "Block bootstrap CI: use bs.index to apply same block structure to all aligned arrays simultaneously"

# Metrics
duration: 8min
completed: 2026-04-01
---

# Phase 102 Plan 02: Indicator Research Framework - Haircut & Bootstrap Summary

**Bonferroni HL 2015 Sharpe/IC-IR haircuts and arch StationaryBootstrap IC confidence intervals added to multiple_testing.py**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-01T19:55:00Z
- **Completed:** 2026-04-01T20:03:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- haircut_sharpe(): Penalizes annualized Sharpe by total trial count via Bonferroni correction (HL 2015); verified monotonic with increasing n_trials; handles edge cases (negative SR, zero trials, zero obs)
- haircut_ic_ir(): Applies identical Bonferroni penalty to IC-IR (same t-stat structure); fetches n_trials from trial_registry via get_trial_count(); optionally writes haircut_ic_ir column back to trial_registry; safe with conn=None
- block_bootstrap_ic(): Stationary block bootstrap CI for IC with adaptive block length via arch 8.0.0 optimal_block_length(); pairs bootstrapped jointly (bs.index applied to both arrays); verified to produce wider CIs than naive IID bootstrap on AR(1) phi=0.7 series

## Task Commits

Each task was committed atomically:

1. **Task 1: haircut_sharpe, haircut_ic_ir, get_trial_count** - `ecc470c0` (feat)
2. **Task 2: block_bootstrap_ic** - included in `ecc470c0` (full file created in Task 1)

## Files Created/Modified

- `src/ta_lab2/analysis/multiple_testing.py` - New module with haircut_sharpe, haircut_ic_ir, get_trial_count, block_bootstrap_ic (plus module-level docstring noting arch 8.0.0 column naming)

## Decisions Made

- **Block bootstrap pair indexing:** Applied bs.index to both feat_clean and ret_clean simultaneously rather than bootstrapping ret_clean alone. Bootstrapping only returns breaks the feature-return alignment and destroys the IC signal, producing CIs centered near zero instead of near the observed IC.
- **arch 8.0.0 column 'stationary':** Explicitly documented in module docstring and enforced in code. Older arch had column 'b_sb'; this module is arch 8.0.0 only.
- **conn=None guard in haircut_ic_ir:** When conn is None, get_trial_count() returns 0 and n_trials=0 edge case returns ic_ir_haircut=ic_ir_observed (no penalty). This matches the use case where a notebook user wants to compute haircuts offline without a DB connection.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed block_bootstrap_ic CI computation — bootstrapped only ret_clean causing broken IC**

- **Found during:** Task 2 verification
- **Issue:** Initial implementation passed only `ret_clean` to StationaryBootstrap and then computed IC between fixed `feat_clean` and bootstrapped `boot_ret`. This destroyed the feature/return alignment (CI centered near zero, not near observed IC). Test assertion `ci_lo > 0` failed (ci_lo was -0.538).
- **Fix:** Changed bootstrap loop to use `bs.index` to resample both `feat_clean[idx]` and `ret_clean[idx]` jointly, preserving the pairing structure while applying block autocorrelation structure.
- **Files modified:** src/ta_lab2/analysis/multiple_testing.py
- **Verification:** ci_lo=0.827 > 0 with strong-signal test (IC=0.962); block CI width 0.42 > naive IID width 0.24 on AR(1) phi=0.7
- **Committed in:** ecc470c0 (Task 1 commit, file was corrected before separate Task 2 commit was attempted)

---

**Total deviations:** 1 auto-fixed (1 bug in bootstrap pair alignment)
**Impact on plan:** Essential correction for statistical correctness. No scope creep.

## Issues Encountered

- Task 2 had no separate commit because block_bootstrap_ic was part of the initial file write in Task 1's commit (both tasks modify the same file). The function was corrected before staging, so the committed version is correct.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All six functions (permutation_ic_test, fdr_control, log_trials_to_registry from 102-01; haircut_sharpe, haircut_ic_ir, block_bootstrap_ic from 102-02) will be available in multiple_testing.py after 102-01 completes
- 102-03 can proceed once both 102-01 and 102-02 are complete
- trial_registry DB table must exist (Alembic migration u4v5w6x7y8z9_phase102_trial_registry.py is already present in alembic/versions/)

---
*Phase: 102-indicator-research-framework*
*Completed: 2026-04-01*
