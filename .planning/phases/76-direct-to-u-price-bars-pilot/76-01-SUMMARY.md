---
phase: 76-direct-to-u-price-bars-pilot
plan: "01"
subsystem: database
tags: [postgresql, sqlalchemy, price-bars, alignment_source, upsert, state-tables, watermark, bootstrap]

# Dependency graph
requires:
  - phase: 75-generalized-1d-bar-builder
    provides: dim_data_sources registry and generalized 1D bar builder pattern

provides:
  - alignment_source column preserved through upsert_bars() (not silently dropped)
  - delete_bars_for_id_tf() scoped delete via alignment_source parameter
  - All 5 price bar state tables populated with correct watermarks from price_bars_multi_tf_u actuals

affects:
  - 76-02 (direct-to-_u writer)
  - 76-03 (bar builder wiring)
  - All future bar builders writing to price_bars_multi_tf_u

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "alignment_source filter in delete_bars_for_id_tf mirrors the venue filter pattern"
    - "Bootstrap state from _u with ON CONFLICT DO UPDATE + GREATEST() for watermarks"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/bars/common_snapshot_contract.py

key-decisions:
  - "tz value for cal/cal_anchor state tables hardcoded to 'America/New_York' (only value in existing data)"
  - "PK for all 5 state tables confirmed as (id, tf, venue_id) - used in ON CONFLICT clauses"
  - "Bootstrap uses GREATEST() to only advance watermarks, never regress existing state"

patterns-established:
  - "alignment_source filter in delete_bars_for_id_tf: add AND alignment_source = :alignment_source when targeting _u tables"
  - "Bootstrap pattern: INSERT...SELECT...GROUP BY...ON CONFLICT DO UPDATE SET field = GREATEST(EXCLUDED.field, existing.field)"

# Metrics
duration: 7min
completed: 2026-03-20
---

# Phase 76 Plan 01: Direct-to-U Price Bars Pilot Infrastructure Summary

**alignment_source preserved through upsert_bars() valid_cols and scoped via delete_bars_for_id_tf() parameter; all 5 price bar state tables bootstrapped from price_bars_multi_tf_u actuals (1,442 to 5,610 rows each)**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-03-20T13:13:00Z
- **Completed:** 2026-03-20T13:19:44Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Added `"alignment_source"` to `valid_cols` list in `upsert_bars()` so the column is no longer silently dropped when builders set it on their DataFrames
- Added `alignment_source: str | None = None` parameter to `delete_bars_for_id_tf()` with `AND alignment_source = :alignment_source` filter, scoping deletes to a single alignment variant when targeting `_u` tables
- Bootstrapped all 5 price bar state tables from `price_bars_multi_tf_u` actual data using `ON CONFLICT DO UPDATE SET ... GREATEST()` — ensures incremental watermarks are correct on first direct-write run

## Task Commits

Each task was committed atomically:

1. **Task 1: Add alignment_source support to common_snapshot_contract.py** - `511d8055` (feat)
2. **Task 2: Bootstrap state tables from price_bars_multi_tf_u actual data** - DB-only migration (no code committed)

**Plan metadata:** (docs commit to follow)

## Files Created/Modified
- `src/ta_lab2/scripts/bars/common_snapshot_contract.py` - Added `"alignment_source"` to `valid_cols` (line 1009); added `alignment_source` parameter and WHERE clause to `delete_bars_for_id_tf()`

## Decisions Made
- **tz hardcoded to `'America/New_York'`**: The 4 cal/cal_anchor state tables have a NOT NULL `tz` column not present in `price_bars_multi_tf_u`. All existing state rows had `tz = 'America/New_York'`, so bootstrap uses that value. Builders will set correct tz when they write via state manager.
- **ON CONFLICT target confirmed `(id, tf, venue_id)`**: Pre-flight PK discovery query confirmed all 5 state tables share this PK, so a single bootstrap template was used for all.
- **Bootstrap did not commit a script**: The migration was run inline as a one-shot operation. No persistent migration script added to repo (not needed — state tables are idempotent after bootstrap).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Cal state tables have `tz` NOT NULL column not in bootstrap template**
- **Found during:** Task 2 (bootstrap SQL execution)
- **Issue:** `price_bars_multi_tf_cal_us_state` and the 3 other cal/cal_anchor state tables have a `tz TEXT NOT NULL` column (absent from `price_bars_multi_tf_state`). The plan's bootstrap SQL template didn't include it, causing a `NotNullViolation` on first run.
- **Fix:** Added `tz` to the INSERT column list with a hardcoded `'America/New_York'` literal for the 4 cal tables; kept base state table template without `tz`.
- **Verification:** Bootstrap completed successfully; all 5 tables show non-zero row counts in verification query.
- **Committed in:** DB-only (no code change required)

---

**Total deviations:** 1 auto-fixed (1 bug in bootstrap template)
**Impact on plan:** Fix was necessary for bootstrap to succeed. No scope creep.

## Issues Encountered
- Pre-existing test failures in `tests/test_bar_contract.py` (12 failures before and after our changes — confirmed identical failure set with `git stash`). None introduced by this plan.

## Next Phase Readiness
- `upsert_bars()` will preserve `alignment_source` when builders set it on their DataFrames
- `delete_bars_for_id_tf()` can scope deletes by `alignment_source` to avoid clobbering other variants in `_u`
- State tables have correct watermarks; builders will do incremental appends (not full-history rebuilds) on first direct-write run
- Ready for Plan 02 (direct-to-_u writer implementation)

---
*Phase: 76-direct-to-u-price-bars-pilot*
*Completed: 2026-03-20*
