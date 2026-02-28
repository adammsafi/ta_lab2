---
phase: 59-microstructural-advanced-features
plan: 02
subsystem: features
tags: [ffd, liquidity, adf, entropy, codependence, numpy, scipy, sklearn, microstructure]

# Dependency graph
requires:
  - phase: 59-01
    provides: "Research and DDL for microstructural feature tables"
provides:
  - "Pure math library for all 5 microstructural feature classes (14 functions)"
  - "Unit tests covering all algorithms on synthetic data (32 tests)"
affects:
  - 59-03 (MicrostructureFeature BaseFeature subclass imports from this module)
  - 59-04 (CodependenceFeature imports codependence functions)
  - 59-05 (Integration and evaluation uses all functions)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure math library pattern: all algorithms as stateless numpy/scipy functions, no DB/IO"
    - "FFD weight generation with threshold-based window sizing"
    - "Rolling OLS via scipy.stats.linregress for Kyle/Hasbrouck lambdas"
    - "ADF t-stat via scipy.linalg.lstsq for numerical stability"

key-files:
  created:
    - src/ta_lab2/features/microstructure.py
    - tests/features/test_microstructure.py
  modified: []

key-decisions:
  - "FFD threshold=1e-2 yields ~11 weights at d=0.4 — practical window size for rolling computation"
  - "ADF implemented via lstsq + manual XtX_inv rather than statsmodels dependency — keeps it lightweight"
  - "LZ complexity normalized by log2(window) for comparability across window sizes"
  - "Distance correlation uses double-centering (Szekely 2007), not the U-centered variant"
  - "Tests placed in tests/features/ (existing test directory) rather than tests/unit/features/"

patterns-established:
  - "Microstructure math pattern: pure functions in features/microstructure.py, DB wrapper in scripts/"
  - "Quantile encoding + Shannon entropy for distribution-level analysis; LZ complexity for temporal structure"

# Metrics
duration: 5min
completed: 2026-02-28
---

# Phase 59 Plan 02: Core Math Library Summary

**14 pure numpy/scipy functions for FFD, liquidity lambdas, rolling ADF, entropy, and distance correlation -- all tested on synthetic data (32/32 pass)**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-28T09:07:08Z
- **Completed:** 2026-02-28T09:12:30Z
- **Tasks:** 2/2
- **Files created:** 2

## Accomplishments
- Implemented all 5 microstructural feature class algorithms as pure functions (650 lines)
- FFD weights/differentiation with find_min_d search for optimal stationarity order
- Three liquidity impact measures (Amihud, Kyle, Hasbrouck) with rolling OLS
- Rolling ADF t-statistic for bubble/explosive behavior detection
- Shannon entropy, LZ complexity, quantile encoding for information-theoretic features
- Distance correlation, mutual information, variation of information for non-linear codependence
- 32 unit tests covering all algorithms on synthetic data with fixed RNG seeds

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement microstructure.py core math library** - `409a4960` (feat)
2. **Task 2: Write unit tests for all microstructure algorithms** - `7d1cd4d1` (test)

## Files Created/Modified
- `src/ta_lab2/features/microstructure.py` - Core math library: 14 functions across 5 sections (650 lines)
- `tests/features/test_microstructure.py` - Unit tests for all algorithms using synthetic data (369 lines, 32 tests)

## Decisions Made
- Used `scipy.stats.linregress` for Kyle/Hasbrouck OLS regressions (numerically stable, no extra dependency)
- Implemented ADF manually via `scipy.linalg.lstsq` instead of pulling in `statsmodels` -- lighter weight and sufficient for rolling window use case
- Set FFD default threshold to 1e-2 producing ~11 weights at d=0.4 -- matches Lopez de Prado's practical recommendation
- LZ complexity normalized by log2(window) so values are comparable across different window sizes
- Placed tests in `tests/features/` matching the existing project test structure rather than `tests/unit/features/` which does not exist

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed explosive ADF test synthetic data**
- **Found during:** Task 2 (unit tests)
- **Issue:** Pure linear log_prices (0.05*t) produced numerically zero ADF residuals instead of positive t-stats
- **Fix:** Changed to explosive AR(1) process (phi=1.02 + noise) which properly produces positive ADF t-statistics
- **Files modified:** tests/features/test_microstructure.py
- **Verification:** Test passes with ADF values > 0 for explosive process

**2. [Rule 1 - Bug] Fixed entropy differentiation test**
- **Found during:** Task 2 (unit tests)
- **Issue:** Quantile encoding normalizes any smooth marginal distribution to near-uniform, so Shannon entropy is identical for sine vs random returns
- **Fix:** Changed test to use LZ complexity (which captures temporal structure) with alternating +/- returns vs random
- **Files modified:** tests/features/test_microstructure.py
- **Verification:** LZ complexity correctly differentiates structured from random sequences

---

**Total deviations:** 2 auto-fixed (2 bugs in test design)
**Impact on plan:** Both fixes were in test synthetic data design, not in the algorithm implementations. No scope creep.

## Issues Encountered
- Pre-commit ruff lint caught an unused variable (`adf_result`) in `find_min_d` -- removed dead Jarque-Bera call that was left from an earlier implementation attempt
- Pre-commit ruff lint caught unused variable `i` in `lempel_ziv_complexity` -- removed

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 14 algorithm functions ready for import by Plan 03 (MicrostructureFeature BaseFeature subclass)
- Codependence functions (distance_correlation, pairwise_mi, variation_of_information) ready for Plan 04
- No new dependencies added -- uses existing numpy, scipy, sklearn

---
*Phase: 59-microstructural-advanced-features*
*Completed: 2026-02-28*
