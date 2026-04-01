---
phase: 102-indicator-research-framework
plan: 01
subsystem: database, analysis, statistics
tags: [postgresql, alembic, scipy, statsmodels, permutation-test, fdr, benjamini-hochberg, ic, multiple-testing]

# Dependency graph
requires:
  - phase: 99-backtest-scaling
    provides: strategy_bakeoff_results table (haircut_sharpe column added here)
  - phase: 98-ctf-graduation
    provides: ic_results table with alignment_source and venue_id (backfill source)
provides:
  - trial_registry table: persistent trial log for all IC sweep results
  - permutation_ic_test(): empirical p-value from shuffled null distribution
  - fdr_control(): BH FDR correction for batched p-values
  - log_trials_to_registry(): upsert IC rows preserving expensive stat columns
  - haircut_sharpe column on strategy_bakeoff_results
affects:
  - 102-indicator-research-framework (plans 02+: permutation sweep, FDR batch, haircut pipeline)
  - any phase that evaluates indicator significance or batch-tests IC values

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Permutation null distribution for empirical IC significance (no parametric assumptions)"
    - "BH FDR control via statsmodels fdrcorrection with 'indep' method"
    - "Upsert with column-level preservation: ON CONFLICT DO UPDATE only touches IC columns; perm/FDR/CI/haircut columns preserved"

key-files:
  created:
    - alembic/versions/u4v5w6x7y8z9_phase102_trial_registry.py
  modified:
    - src/ta_lab2/analysis/multiple_testing.py

key-decisions:
  - "tf column in trial_registry uses VARCHAR(32) not VARCHAR(16): actual tf values reach 18 chars ('10W_CAL_ANCHOR_ISO')"
  - "Backfill filters to horizon=1 AND return_type='arith' only: permutation scope reduction per research design"
  - "ON CONFLICT preserves perm_p_value, fdr_p_adjusted, passes_fdr, bb_ci columns, haircut_ic_ir: expensive computations must survive IC re-sweeps"
  - "Migration chains from t4u5v6w7x8y9 (actual head) not s3t4u5v6w7x8 as specified in plan: Phase 107 added t4u5v6w7x8y9 after Phase 99"
  - "757K rows backfilled from 10.6M ic_results qualifying rows: backfill was slow (~30 min) due to VARCHAR(16) error on first attempt then fix + rerun"

patterns-established:
  - "permutation_ic_test: seed RNG with np.random.default_rng(seed) for reproducibility; n_perms=10K default; passes = |ic_obs| >= pct_95"
  - "fdr_control: fdrcorrection with method='indep' (BH 1995); returns parallel arrays to be zipped by caller"
  - "log_trials_to_registry: filter to horizon=1+arith before upsert; alignment_source -> venue_id via lookup dict"

# Metrics
duration: 95min
completed: 2026-04-01
---

# Phase 102 Plan 01: Indicator Research Framework -- Trial Registry Summary

**trial_registry table created (757K rows backfilled from ic_results) + permutation_ic_test / fdr_control / log_trials_to_registry added to multiple_testing.py**

## Performance

- **Duration:** ~95 min (migration took ~35 min for 757K backfill; initial VARCHAR(16) error added ~30 min re-run)
- **Started:** 2026-04-01T15:53:00Z
- **Completed:** 2026-04-01T18:28:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `trial_registry` table with full schema: 20 columns including perm/FDR/CI/haircut columns, UNIQUE constraint, 2 indexes
- Backfilled 757,798 rows from ic_results (regime_col='all', regime_label='all', horizon=1, return_type='arith')
- Added `haircut_sharpe` column to `strategy_bakeoff_results` for Phase 102 haircut output
- Implemented `permutation_ic_test()`: 10K shuffles, empirical p-value, 95th percentile threshold, n_obs<20 edge case
- Implemented `fdr_control()`: BH correction via statsmodels, empty input edge case
- Implemented `log_trials_to_registry()`: upsert preserving expensive stat columns, horizon=1+arith filter

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration -- trial_registry table + backfill** - `d19c7004` (feat)
2. **Task 2: Core statistical functions** - `ca2bd0c4` (feat)

**Plan metadata:** (to be added after SUMMARY commit)

## Files Created/Modified

- `alembic/versions/u4v5w6x7y8z9_phase102_trial_registry.py` - Migration creating trial_registry, backfilling from ic_results, adding haircut_sharpe to strategy_bakeoff_results
- `src/ta_lab2/analysis/multiple_testing.py` - Three new functions appended: permutation_ic_test, fdr_control, log_trials_to_registry (plus supporting constants _ALIGNMENT_SOURCE_TO_VENUE_ID, _to_python)

## Decisions Made

- **tf column width VARCHAR(32)**: Plan specified VARCHAR(16) but actual tf values include '10W_CAL_ANCHOR_ISO' (18 chars). Fixed to VARCHAR(32).
- **Migration chains from t4u5v6w7x8y9**: Plan said chain from s3t4u5v6w7x8 (Phase 99 HEAD) but Phase 107 added t4u5v6w7x8y9 after Phase 99. Chained from actual head.
- **757K rows backfilled**: From 10.6M ic_results rows, filtering to horizon=1 + return_type='arith' + regime_col='all' + regime_label='all' yields 757,798 distinct rows (the UNIQUE constraint handles deduplication via ON CONFLICT DO NOTHING).
- **multiple_testing.py appended not rewritten**: File already contained haircut_sharpe, block_bootstrap_ic, get_trial_count functions. The three new functions were appended to preserve existing API.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] VARCHAR(16) too narrow for tf column**

- **Found during:** Task 1 (Alembic migration execution)
- **Issue:** Plan specified `tf VARCHAR(16)` but ic_results contains tf values up to 18 characters ('10W_CAL_ANCHOR_ISO'). Migration failed with `StringDataRightTruncation` on first upgrade attempt.
- **Fix:** Changed to `VARCHAR(32)` in migration file.
- **Files modified:** `alembic/versions/u4v5w6x7y8z9_phase102_trial_registry.py`
- **Verification:** Migration completed successfully with 757K rows backfilled.
- **Committed in:** `d19c7004` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Necessary for correctness. VARCHAR(32) is a superset of VARCHAR(16) and compatible with all current and future tf values.

## Issues Encountered

- Migration took ~30 min longer than expected: initial `alembic upgrade head` was run in background, hit VARCHAR(16) error, process died silently after output stopped. Second attempt (foreground) exposed error clearly and completed in ~35 min after fix.
- Lock contention during migration: `ALTER TABLE strategy_bakeoff_results ADD COLUMN` was blocked for ~12 min by a concurrent UPDATE (from another pipeline process). Resolved automatically when competing transaction committed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `trial_registry` table ready to receive permutation p-values and FDR results from Phase 102 plans 02+
- `permutation_ic_test()` and `fdr_control()` ready for use in the permutation sweep pipeline
- `log_trials_to_registry()` ready to be called from IC sweep scripts after each sweep run
- All 757K backfilled rows have `perm_p_value=NULL`, `fdr_p_adjusted=NULL`, `passes_fdr=NULL` -- ready for Phase 102-02 batch permutation run

---
*Phase: 102-indicator-research-framework*
*Completed: 2026-04-01*
