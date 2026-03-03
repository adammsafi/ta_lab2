---
phase: 66-fred-derived-features-automation
plan: 02
subsystem: macro-features
tags: [pandas, fred, macro-features, rolling-zscore, fed-regime, credit-stress, carry-trade]

# Dependency graph
requires:
  - phase: 66-01
    provides: 25 new columns in fred.fred_macro_features, SERIES_TO_LOAD extended to 18, FFILL_LIMITS extended
  - phase: 65-fred-table-core-features
    provides: compute_derived_features() producing net_liquidity and us_jp_rate_spread
provides:
  - compute_derived_features_66() with 18 derived columns (FRED-08 through FRED-16)
  - _rolling_zscore() helper for reusable z-score computation with 80% min_periods
  - _compute_fed_regime() for structure/trajectory classification
  - _RENAME_MAP extended to 18 entries (7 new raw series)
  - db_columns whitelist extended with 25 new columns (7 raw + 18 derived)
  - compute_macro_features() pipeline producing ~50 columns end-to-end
affects: [66-03 (automation/summary log), 67 (macro regime classifier), 71 (risk gates)]

# Tech tracking
tech-stack:
  added: []
  patterns: [separate compute function per phase for test isolation, _rolling_zscore helper with min_fill_pct]

key-files:
  created: []
  modified:
    - src/ta_lab2/macro/feature_computer.py

key-decisions:
  - "Separate compute_derived_features_66() from Phase 65 compute_derived_features() for test isolation"
  - "carry_momentum uses binary 0/1 flag (not continuous zscore) per plan spec, with elevated 2.0 threshold when us_jp_rate_spread > 0"
  - "nfci_4wk_direction returns None for exact-zero diff (not 'neutral') -- matches NULL-over-spurious-labels convention"
  - "Fed regime thresholds: zero-bound <= 0.25, spread tolerance 0.001, trajectory +/-0.25 (one standard 25bp Fed move)"

patterns-established:
  - "_rolling_zscore(series, window, min_fill_pct=0.80): reusable z-score with configurable min_periods"
  - "Phase-specific compute functions called sequentially before rename step in compute_macro_features()"

# Metrics
duration: 5min
completed: 2026-03-03
---

# Phase 66 Plan 02: Feature Computation Logic Summary

**compute_derived_features_66() producing 18 macro features (credit stress, financial conditions, M2, carry trade, net liquidity z-score, fed regime, carry momentum, CPI proxy) with _rolling_zscore helper and data-driven fed regime classifier**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-03T04:19:51Z
- **Completed:** 2026-03-03T04:25:03Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- 18 derived columns computed from 7 new FRED series covering credit stress, financial conditions, M2 money supply, carry trade, net liquidity z-score/trend, fed regime structure/trajectory, carry momentum, and CPI surprise proxy
- _rolling_zscore() helper with configurable 80% min_periods for reuse across FRED-08 (30d) and FRED-12 (365d) windows
- Data-driven fed regime classifier: zero-bound/single-target/target-range structure plus hiking/holding/cutting trajectory from DFF 90d change
- Full pipeline end-to-end produces 50 lowercase columns with zero uppercase leaks
- All feature groups handle missing source series gracefully with NaN/None fallback

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _rolling_zscore, compute_derived_features_66(), _compute_fed_regime()** - `02a78407` (feat)
2. **Task 2: Update _RENAME_MAP, orchestration, and db_columns whitelist** - `3efccffe` (feat)

## Files Created/Modified
- `src/ta_lab2/macro/feature_computer.py` - Added _rolling_zscore(), _compute_fed_regime(), compute_derived_features_66(); extended _RENAME_MAP to 18 entries; added Step 3b to compute_macro_features(); extended db_columns whitelist with 25 new columns

## Decisions Made
- Separate compute_derived_features_66() from Phase 65 function for test isolation (each phase's features can be tested independently)
- carry_momentum stored as binary 0.0/1.0 flag with elevated threshold (2.0 when carry spread positive, 1.5 otherwise)
- nfci_4wk_direction uses None for exact-zero diff (NULL in DB) rather than a "neutral" label
- Fed regime structure classification is data-driven (DFEDTARU value-based, not date-range-based like archived fedtools2)
- M2 YoY uses pct_change(365) to correctly handle monthly forward-filled daily data

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ruff E741 ambiguous variable name**
- **Found during:** Task 1 (commit attempt)
- **Issue:** Variable `l` in list comprehension `for u, l in zip(upper, lower)` flagged by ruff E741
- **Fix:** Renamed to `lo` in the comprehension: `for u, lo in zip(upper, lower)`
- **Files modified:** src/ta_lab2/macro/feature_computer.py
- **Verification:** ruff check passes
- **Committed in:** 02a78407 (part of Task 1 commit, fixed before successful commit)

---

**Total deviations:** 1 auto-fixed (1 bug/lint)
**Impact on plan:** Trivial variable rename for lint compliance. No scope creep.

## Issues Encountered
- Pre-commit hook stash/unstash cycle caused Task 2 changes to be absorbed into a concurrent commit (3efccffe) that also includes unrelated 68-RESEARCH docs. Functionally correct but commit history is not perfectly isolated.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All 18 derived features computed and included in pipeline output
- Pipeline produces 50 columns end-to-end, ready for upsert to fred.fred_macro_features
- Plan 03 (automation, WARMUP_DAYS increase, summary log) can proceed immediately
- Phase 67 macro regime classifier has all required input features available

---
*Phase: 66-fred-derived-features-automation*
*Completed: 2026-03-03*
