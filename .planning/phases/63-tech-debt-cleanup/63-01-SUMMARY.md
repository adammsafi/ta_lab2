---
phase: 63-tech-debt-cleanup
plan: 01
subsystem: experiments
tags: [feature-promotion, ic-evaluation, cmc_ic_results, cmc_feature_experiments, sqlalchemy]

# Dependency graph
requires:
  - phase: 55-feature-signal-evaluation
    provides: cmc_ic_results table populated by run_ic_sweep.py for bar-level features
  - phase: 38-feature-experimentation
    provides: FeaturePromoter class and cmc_feature_experiments table
provides:
  - FeaturePromoter._load_ic_results() method querying cmc_ic_results with feature AS feature_name alias
  - _load_experiment_results(source='auto'|'feature_experiments'|'ic_results') dual-source IC loading
  - promote_feature(source=...) parameter for explicit source selection
  - batch_promote_features.py --source flag enabling bar-level feature promotion
affects:
  - Phase 63 plans 02+ (any future promotion workflows)
  - batch_promote_features.py usage docs and runbooks

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual-source fallback: try primary table, fall back to secondary if empty (auto mode)"
    - "Column aliasing in SELECT to normalize across differently-named tables"

key-files:
  created: []
  modified:
    - src/ta_lab2/experiments/promoter.py
    - src/ta_lab2/scripts/experiments/batch_promote_features.py

key-decisions:
  - "source='auto' as default ensures zero breaking changes to all existing callers"
  - "Column mapping via SELECT feature AS feature_name rather than post-query rename -- cleaner and SQL-level"
  - "Error message mentions both tables when source='auto' and no data found -- aids debugging"
  - "Dry-run path updated to pass source= so --dry-run --source ic_results works end-to-end"

patterns-established:
  - "Dual-source IC loading: _load_experiment_results tries cmc_feature_experiments; falls back to cmc_ic_results in auto mode"
  - "Source parameter pattern: 'auto'|'feature_experiments'|'ic_results' enum for explicit or fallback behavior"

# Metrics
duration: 3min
completed: 2026-03-01
---

# Phase 63 Plan 01: Tech Debt Cleanup - IC Results Source Bridge Summary

**FeaturePromoter gains dual-source IC loading so bar-level features in cmc_ic_results can be promoted via the same automated batch path as ExperimentRunner features in cmc_feature_experiments.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-01T07:36:42Z
- **Completed:** 2026-03-01T07:39:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added `_load_ic_results()` to FeaturePromoter that queries `cmc_ic_results` with `feature AS feature_name` alias, returning a DataFrame with the same schema as `_load_experiment_results()`
- Updated `_load_experiment_results()` to accept `source` parameter (`"auto"`, `"feature_experiments"`, `"ic_results"`) -- auto mode tries `cmc_feature_experiments` first then falls back to `cmc_ic_results`
- Updated `promote_feature()` to accept and pass `source` parameter through; error message now mentions both tables when `source="auto"` and no data is found
- Added `--source {auto,feature_experiments,ic_results}` CLI flag to `batch_promote_features.py` with default `"auto"` -- both dry-run and live paths pass `source=args.source`

## Task Commits

Each task was committed atomically:

1. **Task 1: Add cmc_ic_results loading to FeaturePromoter** - `fc910ff1` (feat)
2. **Task 2: Add --source flag to batch_promote_features.py** - `50f622a6` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/ta_lab2/experiments/promoter.py` - Added `_load_ic_results()`, updated `_load_experiment_results(source=...)` and `promote_feature(source=...)`
- `src/ta_lab2/scripts/experiments/batch_promote_features.py` - Added `--source` argparse argument; updated dry-run and live paths to pass `source=args.source`

## Decisions Made
- **source='auto' as default**: Ensures zero breaking changes to all existing callers. Old code calling `promote_feature("feat")` still works -- it tries `cmc_feature_experiments` first.
- **Column aliasing in SQL**: Used `SELECT feature AS feature_name` rather than renaming in Python post-query -- cleaner, happens at the DB boundary where it belongs.
- **Error messages**: When `source="auto"` and no data found, the error explicitly mentions both tables to aid debugging. When source is explicit, the error names only the queried table.
- **Dry-run source propagation**: The dry-run path calls `_load_experiment_results(name, source=args.source)` directly (not via `promote_feature`), so `--dry-run --source ic_results` works correctly end-to-end.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- FeaturePromoter can now promote bar-level features whose IC data lives only in `cmc_ic_results` (written by `run_ic_sweep.py`)
- The 60 bar-level features from `promotion_decisions.csv` can now be batch-promoted using `--source ic_results`
- All existing `cmc_feature_experiments` promotion paths continue to work unchanged
- Ready for plan 02 of phase 63

---
*Phase: 63-tech-debt-cleanup*
*Completed: 2026-03-01*
