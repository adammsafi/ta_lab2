---
phase: 36-psr-purged-k-fold
plan: "03"
subsystem: testing
tags: [sklearn, cross-validation, purged-kfold, cpcv, financial-ml, leakage-free, tdd]

# Dependency graph
requires:
  - phase: 36-psr-purged-k-fold plan 01
    provides: Alembic migration and psr_results DDL for PSR infrastructure
  - phase: 36-psr-purged-k-fold plan 02
    provides: PSR/DSR/MinTRL formula module
provides:
  - PurgedKFoldSplitter: sklearn-compatible CV splitter with purge + embargo for overlapping labels
  - CPCVSplitter: combinatorial purged CV generating C(n_splits, n_test_splits) path combinations
  - Leakage-free cross-validation infrastructure for Phase 37+ IC evaluation
affects:
  - Phase 37 (IC Evaluation): PurgedKFoldSplitter is the CV engine for IC rolling window splits
  - Phase 38 (Feature Experimentation): CPCVSplitter enables PBO analysis in ExperimentRunner

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD RED-GREEN: failing test commit before implementation commit"
    - "tz-aware comparison: use pandas comparison + .to_numpy() not .values (strips tz on Windows)"
    - "sklearn BaseCrossValidator: implement _iter_test_masks + split, override get_n_splits"
    - "Combinatorial CV: itertools.combinations(range(n_splits), n_test_splits) pre-computed at init"

key-files:
  created:
    - src/ta_lab2/backtests/cv.py
    - tests/backtests/test_cv.py
  modified: []

key-decisions:
  - "PurgedKFoldSplitter from scratch (no mlfinlab): t1_series required, embargo_frac=0.01 default"
  - "tz-aware fix: .to_numpy() on pandas Series comparison, not .values (per MEMORY.md pitfall)"
  - "CPCVSplitter named for ergonomic API; algorithm identical to Lopez de Prado CombPurgedKFoldCV"
  - "Library-only: no CLI, no pipeline integration in Phase 36 (deferred to Phase 38+)"
  - "Purge uses earliest test-group start across all CPCV combo groups (minimum test_start)"

patterns-established:
  - "Purge pattern: t1_complement <= test_start_ts using pandas comparison to handle tz-aware timestamps"
  - "Embargo pattern: position-based [test_end+1, test_end+embargo_size) complement exclusion"
  - "_fold_boundaries() helper returns [(start,end)] tuples for clean split math"

# Metrics
duration: 4min
completed: 2026-02-24
---

# Phase 36 Plan 03: PurgedKFoldSplitter and CPCVSplitter Summary

**sklearn-compatible PurgedKFoldSplitter + CPCVSplitter from scratch, with purge/embargo leakage prevention and C(n_splits, n_test_splits) combinatorial path generation for PBO analysis**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-24T00:03:21Z
- **Completed:** 2026-02-24T00:07:30Z
- **Tasks:** 2 (RED + GREEN TDD phases)
- **Files modified:** 2

## Accomplishments
- Implemented `PurgedKFoldSplitter(BaseCrossValidator)`: n_splits, mandatory t1_series, embargo_frac=0.01; purges training obs whose label-end bleeds into test window; embargos post-test window; validates monotonic index; full sklearn API compatibility (cross_val_score, GridSearchCV)
- Implemented `CPCVSplitter(BaseCrossValidator)`: generates all C(n_splits, n_test_splits) combinations; purge uses earliest test-group start; embargo after latest test-group end; correct combinatorial math for PBO path matrix (C(6,2)=15, C(10,2)=45)
- 33 passing tests covering interface, no-overlap guarantees, purge/embargo correctness, sklearn integration, and combinatorial math
- Avoided mlfinlab dependency (discontinued, known bug #295) by implementing from scratch

## Task Commits

Each TDD task was committed atomically:

1. **Task RED: failing tests** - `2ad9fd3d` (test)
2. **Task GREEN: cv.py implementation** - `51394b7f` (feat)

**Plan metadata:** (docs commit follows)

_Note: TDD task produced 2 commits (test RED -> feat GREEN)_

## Files Created/Modified
- `src/ta_lab2/backtests/cv.py` - PurgedKFoldSplitter and CPCVSplitter classes (384 lines)
- `tests/backtests/test_cv.py` - Comprehensive test suite: 33 tests across 9 test classes (471 lines)

## Decisions Made
- **tz-aware timestamp comparison fix**: Used `(t1_complement <= test_start_ts).to_numpy()` instead of `.values` — per MEMORY.md pitfall, `.values` on tz-aware datetime Series returns tz-naive numpy.datetime64 on Windows, causing `TypeError: Cannot compare tz-naive and tz-aware timestamps`
- **CPCVSplitter naming**: Shorter name for ergonomic API; the underlying algorithm is Lopez de Prado's CombPurgedKFoldCV (noted in docstring)
- **Library-only scope**: No CLI scripts, no pipeline integration, no imports from other pipeline modules — deferred to Phase 38+ per CONTEXT.md decision
- **Purge in CPCV uses min(test_start_ts) across all combo groups**: When multiple test fold groups are combined, the earliest start timestamp determines the purge boundary — prevents any label from any training obs bleeding into any test group
- **Pre-computed combos at init**: `itertools.combinations` list stored as `self._combos` at `__init__` — enables O(1) `get_n_splits()` and consistent iteration order

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] tz-aware timestamp comparison TypeError**
- **Found during:** GREEN phase (first test run)
- **Issue:** `self.t1.iloc[complement].values <= test_start_ts` raised `TypeError: Cannot compare tz-naive and tz-aware timestamps` — `.values` strips tz from tz-aware Series on Windows (documented in MEMORY.md)
- **Fix:** Replaced `.values` comparison with pandas Series comparison `(t1_complement <= test_start_ts).to_numpy()` — preserves tz context through pandas comparison layer, extracts clean boolean numpy array for masking
- **Files modified:** `src/ta_lab2/backtests/cv.py` (both PurgedKFoldSplitter and CPCVSplitter split methods)
- **Verification:** All 33 tests pass including purge correctness tests that use tz="UTC" series
- **Committed in:** `51394b7f` (GREEN implementation commit)

**2. [Rule 1 - Bug] Unused `indices` variable in `_iter_test_masks`**
- **Found during:** GREEN phase (pre-commit ruff lint)
- **Issue:** `indices = np.arange(n)` left over from initial draft, never used (F841)
- **Fix:** Removed the unused assignment
- **Files modified:** `src/ta_lab2/backtests/cv.py`
- **Verification:** ruff passes, tests still pass
- **Committed in:** `51394b7f` (GREEN implementation commit, fixed before final commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - Bug)
**Impact on plan:** Both fixes essential for correctness. No scope creep.

## Issues Encountered

The `cross_val_score` integration tests produce `UserWarning: Scoring failed` from `DummyClassifier` getting very small training sets (degenerate data after aggressive purge on a 100-sample series). This is expected behavior — the warning comes from the classifier, not the splitter; the tests pass. The splitter correctly yields train/test splits; DummyClassifier fails to score when the training set is near-empty after purge.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `PurgedKFoldSplitter` and `CPCVSplitter` are ready for Phase 37 IC evaluation
- Phase 37 will use `PurgedKFoldSplitter` as the CV engine for time-bounded IC scoring
- Phase 38 `ExperimentRunner` will use `CPCVSplitter` for PBO analysis path matrix generation
- No blockers identified

---
*Phase: 36-psr-purged-k-fold*
*Completed: 2026-02-24*
