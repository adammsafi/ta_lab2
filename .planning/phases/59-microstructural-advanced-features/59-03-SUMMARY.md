---
phase: 59-microstructural-advanced-features
plan: 03
subsystem: features
tags: [microstructure, ffd, kyle-lambda, amihud, hasbrouck, sadf, entropy, cmc_features]

# Dependency graph
requires:
  - phase: 59-01
    provides: "9 microstructure columns added to cmc_features DDL"
  - phase: 59-02
    provides: "14 pure numpy/scipy math functions for FFD, liquidity, ADF, entropy"
provides:
  - "MicrostructureFeature BaseFeature subclass computing MICRO-01 through MICRO-04"
  - "CLI: python -m ta_lab2.scripts.features.microstructure_feature --ids 1 --tf 1D"
  - "UPDATE-based write pattern for supplemental columns in cmc_features"
affects: [59-04, 59-05, run_all_feature_refreshes]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "UPDATE-based write for supplemental feature columns (vs DELETE+INSERT for base rows)"
    - "NaN -> SQL NULL conversion via explicit float NaN check in clean_row dict"

key-files:
  created:
    - "src/ta_lab2/scripts/features/microstructure_feature.py"
  modified:
    - "src/ta_lab2/features/microstructure.py"

key-decisions:
  - "UPDATE pattern for cmc_features: microstructure columns are supplemental to existing rows from daily_features_view, not standalone inserts"
  - "No z-score normalization or outlier flags for microstructure columns (add_normalizations and add_outlier_flags overridden to no-op)"
  - "Row-by-row UPDATE with executemany (batch size 5000) for precise PK matching on (id, ts, tf, venue, alignment_source)"

patterns-established:
  - "Supplemental UPDATE pattern: compute features, then UPDATE existing cmc_features rows by PK"
  - "NaN -> None: explicit isinstance(v, float) and np.isnan(v) check prevents PostgreSQL float NaN vs SQL NULL confusion"

# Metrics
duration: 8min
completed: 2026-02-28
---

# Phase 59 Plan 03: MicrostructureFeature Pipeline Wiring Summary

**MicrostructureFeature BaseFeature subclass computing FFD, liquidity lambdas, rolling ADF, and entropy -- writing 9 columns to cmc_features via UPDATE pattern**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-28T09:16:48Z
- **Completed:** 2026-02-28T09:24:50Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- MicrostructureFeature computes all 9 MICRO-01 through MICRO-04 columns for any set of asset IDs and TF
- CLI runs successfully: `python -m ta_lab2.scripts.features.microstructure_feature --ids 1 --tf 1D`
- UPDATE pattern writes only microstructure columns to existing cmc_features rows (no rows deleted)
- Idempotent: re-runs produce identical results
- BTC (id=1, tf=1D): 5614 rows updated, all 9 columns populated with correct NULL patterns

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement MicrostructureFeature BaseFeature subclass** - `fc03684b` (feat)

**Plan metadata:** (pending)

## Files Created/Modified
- `src/ta_lab2/scripts/features/microstructure_feature.py` - MicrostructureFeature class + MicrostructureConfig + CLI (629 lines)
- `src/ta_lab2/features/microstructure.py` - Bug fix: kyle_lambda/hasbrouck_lambda handle ValueError in linregress

## Decisions Made
- **UPDATE vs DELETE+INSERT:** Microstructure columns are supplemental to the base cmc_features rows created by daily_features_view. Using UPDATE preserves existing columns (returns, vol, TA) while filling in microstructure columns.
- **No normalization/outlier flags:** Microstructure features are inherently non-stationary (lambda values scale with price level) and application-specific. Z-score normalization and outlier flagging are overridden to no-op.
- **Row-by-row UPDATE:** Each row is updated individually with PK match (id, ts, tf, venue, alignment_source). This is slower than bulk SQL but ensures correctness with the 5-column composite PK and handles NaN->NULL conversion per-cell.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] kyle_lambda/hasbrouck_lambda crash on all-identical x values**
- **Found during:** Task 1 (first run for BTC id=1)
- **Issue:** `scipy.stats.linregress` throws `ValueError: Cannot calculate a linear regression if all x values are identical` when a rolling window has constant signed_volume. Early BTC history has zero/constant volume windows.
- **Fix:** Added try/except ValueError around linregress calls in both `kyle_lambda()` and `hasbrouck_lambda()` in `microstructure.py`. Windows with identical x values now produce NaN (skip) instead of crashing the entire function.
- **Files modified:** `src/ta_lab2/features/microstructure.py`
- **Verification:** Re-run for BTC produced no warnings; kyle_lambda column has 243 NULL rows (expected for early sparse data) instead of all-NULL.
- **Committed in:** fc03684b (Task 1 commit)

**2. [Rule 1 - Bug] NaN stored as PostgreSQL float NaN instead of SQL NULL**
- **Found during:** Task 1 (verification query after first run)
- **Issue:** `df.where(df.notna(), other=None)` does not reliably convert float64 NaN to None for SQL parameters. Result: 7 rows had float NaN in close_fracdiff column instead of SQL NULL, breaking `IS NULL` queries.
- **Fix:** Added explicit `isinstance(v, float) and np.isnan(v)` check in the clean_row dict comprehension, plus a secondary check after `.item()` conversion for numpy scalars.
- **Files modified:** `src/ta_lab2/scripts/features/microstructure_feature.py`
- **Verification:** After fix, `close_fracdiff IS NULL` returns 7 rows and `close_fracdiff = float8 'NaN'` returns 0.
- **Committed in:** fc03684b (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both fixes essential for correctness. No scope creep.

## Issues Encountered
None beyond the auto-fixed bugs documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- MicrostructureFeature is ready for integration into `run_all_feature_refreshes.py` orchestrator (plan 59-04 or 59-05)
- CodependenceFeature (MICRO-05) can follow same UPDATE pattern for pairwise codependence columns
- All 9 microstructure columns verified populated for BTC with correct NULL patterns matching window sizes

---
*Phase: 59-microstructural-advanced-features*
*Completed: 2026-02-28*
