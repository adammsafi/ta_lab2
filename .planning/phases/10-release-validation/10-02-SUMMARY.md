---
phase: 10-release-validation
plan: 02
subsystem: testing
tags: [validation, pytest, data-consistency, time-alignment, ci-gates]

# Dependency graph
requires:
  - phase: 10-01
    provides: CI validation infrastructure with database fixtures
provides:
  - Time alignment validation tests (SIG-04): 6 tests
  - Data consistency validation tests (SIG-05): 8 tests
  - Zero-tolerance validation for critical data integrity issues
affects: [10-03, 10-04, 10-05, 10-06, 10-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Zero tolerance validation pattern for critical issues (duplicates, NULL values, orphan references)
    - Tolerance-based validation for operational variations (5% rowcount, 10% tf_days cadence)
    - Graceful table existence checks with pytest.skip for optional tables

key-files:
  created:
    - tests/validation/test_time_alignment.py
    - tests/validation/test_data_consistency.py
  modified: []

key-decisions:
  - "Zero tolerance for orphan timeframes: All EMA tables must reference valid dim_timeframe entries"
  - "Zero tolerance for duplicates and NULL EMAs: Critical data integrity issues"
  - "5% rowcount tolerance: Allows for delisted assets and data gaps"
  - "10% tf_days tolerance: Allows for holidays/missing days in cadence validation"
  - "1% price-EMA alignment tolerance: Allows for weekend/holiday differences"

patterns-established:
  - "Table existence checks: Query information_schema before validating, skip with pytest.skip if missing"
  - "Dual assertion pattern: Check both absolute count (zero tolerance) and percentage (with tolerance)"
  - "Helper functions for reusable validation logic: get_date_range, count_gaps"

# Metrics
duration: 4min
completed: 2026-02-01
---

# Phase 10 Plan 02: Validation Tests Summary

**Time alignment (SIG-04) and data consistency (SIG-05) validation tests with zero tolerance for critical issues and graceful degradation for optional tables**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-01T22:40:08Z
- **Completed:** 2026-02-01T22:44:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- 6 time alignment validation tests (SIG-04) verify all calculations use dim_timeframe
- 8 data consistency validation tests (SIG-05) verify no gaps, correct rowcounts, and EMA integrity
- Zero tolerance validation for critical issues: orphan timeframes, duplicates, NULL EMAs
- Tolerance-based validation for operational variations: 5% rowcount, 10% tf_days cadence, 1% alignment

## Task Commits

Each task was committed atomically:

1. **Task 1: Create time alignment validation tests** - `bc95102` (test)
   - 6 tests validating SIG-04 requirements
   - Verify dim_timeframe and dim_sessions populated
   - Zero tolerance for orphan timeframes (not in dim_timeframe)
   - Validate calendar vs trading timeframe separation
   - Check tf_days matches actual data cadence (10% tolerance)

2. **Task 2: Create data consistency validation tests** - `b48db4b` (test)
   - 8 tests validating SIG-05 requirements
   - Zero tolerance: no duplicates, no NULL EMAs
   - Verify EMA values positive and reasonable (<10x price)
   - Check price-EMA timestamp alignment (1% tolerance)
   - Gap detection for crypto 24/7 data (<5% gaps allowed)
   - Validate returns/volatility calculation correctness
   - Helper functions for date range and gap counting

**Plan metadata:** (pending final commit)

## Files Created/Modified

- `tests/validation/test_time_alignment.py` - Time alignment validation (SIG-04): dim_timeframe population, orphan timeframes, calendar vs trading separation, tf_days cadence
- `tests/validation/test_data_consistency.py` - Data consistency validation (SIG-05): duplicates, NULL values, rowcount ranges, EMA precision, price alignment, gap detection, returns/volatility correctness

## Decisions Made

**Zero tolerance for critical issues:**
- Orphan timeframes: All EMA tables must reference valid dim_timeframe entries (no orphans allowed)
- Duplicates: Each (id, ts, tf, period) must be unique (data corruption indicator)
- NULL EMAs: All EMAs must have values (calculation failure indicator)

**Tolerance-based for operational variations:**
- 5% rowcount tolerance: Accounts for delisted assets and data gaps
- 10% tf_days tolerance: Allows for holidays/missing days in actual data cadence
- 1% price-EMA alignment tolerance: Allows for weekend/holiday timestamp differences

**Graceful degradation:**
- Table existence checks via information_schema before validation
- pytest.skip for optional tables (cmc_ema_multi_tf_cal, cmc_returns_daily, cmc_vol_daily)
- Tests don't fail if TARGET_DB_URL not set (CI flexibility)

## Deviations from Plan

None - plan executed exactly as written.

All validation tests follow plan specifications:
- Time alignment tests validate SIG-04 (6 tests)
- Data consistency tests validate SIG-05 (8 tests)
- Zero tolerance for critical issues per CONTEXT.md
- Tolerance thresholds as specified in plan (5%, 10%, 1%)

## Issues Encountered

None - validation tests created without issues.

Test collection successful (70 total validation tests including 14 from this plan).
All tests have proper imports, pytest markers, and assertion messages.

## User Setup Required

None - no external service configuration required.

Validation tests require TARGET_DB_URL environment variable (set in CI, documented in 10-01).

## Next Phase Readiness

**Ready for 10-03 (Backtest Reproducibility Validation):**
- Time alignment validation (SIG-04) complete
- Data consistency validation (SIG-05) complete
- Zero tolerance pattern established for critical issues
- Tolerance-based pattern established for operational variations
- Table existence pattern established for graceful degradation

**CI validation gates:**
- All validation tests have @pytest.mark.validation_gate marker
- Tests use db_session fixture from 10-01 conftest
- Graceful skipping when TARGET_DB_URL not set (CI portability)

**Validation coverage:**
- Time alignment: 6 tests covering dim_timeframe population, orphan detection, calendar/trading separation, tf_days cadence
- Data consistency: 8 tests covering duplicates, NULL values, rowcount ranges, EMA precision, price alignment, gaps, returns/volatility correctness
- Total validation tests: 70 (including 49 from Phase 9, 7 from 10-01, 14 from 10-02)

**No blockers or concerns.**

---
*Phase: 10-release-validation*
*Completed: 2026-02-01*
