---
phase: 78-table-drops-script-cleanup
plan: 05
subsystem: database
tags: [postgresql, ama, alignment_source, _u-tables, siloed-tables, bars-redirect]

# Dependency graph
requires:
  - phase: 77-ama-u-migration
    provides: "AMA builders write directly to ama_multi_tf_u with alignment_source; price_bars_multi_tf_u holds all 5 bar variants"
  - phase: 78-01
    provides: "alignment_source='multi_tf' (not 'default') confirmed for base table; pattern established for SQL filters"
provides:
  - "All 5 AMA feature classes default bars_table -> price_bars_multi_tf_u"
  - "All 9 bar-read SQL queries in feature classes include alignment_source filter when config.alignment_source is set"
  - "All 4 AMA builder scripts return price_bars_multi_tf_u from get_bars_table() / SCHEME_MAP"
  - "AMAWorkerTask.bars_table default -> price_bars_multi_tf_u"
  - "Zero runtime references to dropped siloed bar tables in AMA layer"
affects:
  - phase: 78-06
  - daily-refresh pipeline (AMA builders now operational post-table-drops)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "alignment_source filter in preload_all_bars and _load_bars: conditional on self.config.alignment_source being set"
    - "preload_all_bars uses alignment_filter string interpolation with conditional params dict extension"
    - "_load_bars uses where_clauses list append pattern for alignment_source filter"

key-files:
  created: []
  modified:
    - src/ta_lab2/features/ama/ama_multi_timeframe.py
    - src/ta_lab2/features/ama/ama_multi_tf_cal.py
    - src/ta_lab2/features/ama/ama_multi_tf_cal_anchor.py
    - src/ta_lab2/scripts/amas/base_ama_refresher.py
    - src/ta_lab2/scripts/amas/refresh_ama_multi_tf.py
    - src/ta_lab2/scripts/amas/refresh_ama_multi_tf_cal_from_bars.py
    - src/ta_lab2/scripts/amas/refresh_ama_multi_tf_cal_anchor_from_bars.py

key-decisions:
  - "alignment_source filter is conditional (not always applied): when config.alignment_source is None, reads all variants from _u table without filter"
  - "preload_all_bars SQL uses f-string alignment_filter injection (not parameterized clause list) to keep the WHERE clause structure readable"
  - "_load_bars SQL uses where_clauses list append (same pattern as existing timestamp filter) for consistency"

patterns-established:
  - "AMA feature preload_all_bars: alignment_filter = 'AND alignment_source = :alignment_source' injected via f-string when config.alignment_source is set"
  - "AMA feature _load_bars: alignment_source appended to where_clauses list conditionally, same as start_ts pattern"

# Metrics
duration: 5min
completed: 2026-03-21
---

# Phase 78 Plan 05: AMA Bar Source Redirect Summary

**All 5 AMA feature classes and 4 builder scripts redirected from dropped siloed price bar tables to price_bars_multi_tf_u with conditional alignment_source filters on all 9 SQL bar-read queries**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-21T14:36:07Z
- **Completed:** 2026-03-21T14:41:07Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Changed default `bars_table` parameter in all 5 AMA feature classes (MultiTFAMAFeature, CalUSAMAFeature, CalISOAMAFeature, CalAnchorUSAMAFeature, CalAnchorISOAMAFeature) from their respective siloed table names to `price_bars_multi_tf_u`
- Added `alignment_source` filter to all 9 bar-read SQL queries across the 3 feature files: `preload_all_bars` (5 total) and `_load_bars` fallback path (4 total in the cal/cal_anchor classes; MultiTF uses cache for its fallback)
- Updated `get_bars_table()` return value in `BaseAMARefresher` and `MultiTFAMARefresher` to `price_bars_multi_tf_u`
- Updated `AMAWorkerTask.bars_table` default field to `price_bars_multi_tf_u`
- Updated SCHEME_MAP `bars_table` in both cal refreshers (`refresh_ama_multi_tf_cal_from_bars.py` and `refresh_ama_multi_tf_cal_anchor_from_bars.py`) to `price_bars_multi_tf_u`

## Task Commits

Each task was committed atomically:

1. **Task 1: Update AMA feature classes to read from price_bars_multi_tf_u** - `5259fda9` (feat)
2. **Task 2: Update AMA builder scripts to pass price_bars_multi_tf_u** - `27b5ef61` (feat)

## Files Created/Modified

- `src/ta_lab2/features/ama/ama_multi_timeframe.py` - `bars_table` default -> `price_bars_multi_tf_u`; `preload_all_bars` adds conditional `alignment_source` filter via f-string injection
- `src/ta_lab2/features/ama/ama_multi_tf_cal.py` - `bars_table` defaults for CalUSAMAFeature and CalISOAMAFeature -> `price_bars_multi_tf_u`; both `preload_all_bars` and `_load_bars` get conditional alignment_source filters
- `src/ta_lab2/features/ama/ama_multi_tf_cal_anchor.py` - `bars_table` defaults for CalAnchorUSAMAFeature and CalAnchorISOAMAFeature -> `price_bars_multi_tf_u`; both `preload_all_bars` and `_load_bars` get conditional alignment_source filters
- `src/ta_lab2/scripts/amas/base_ama_refresher.py` - `get_bars_table()` default return and `AMAWorkerTask.bars_table` default field -> `price_bars_multi_tf_u`
- `src/ta_lab2/scripts/amas/refresh_ama_multi_tf.py` - `get_bars_table()` -> `price_bars_multi_tf_u`
- `src/ta_lab2/scripts/amas/refresh_ama_multi_tf_cal_from_bars.py` - SCHEME_MAP `bars_table` for 'us' and 'iso' -> `price_bars_multi_tf_u`
- `src/ta_lab2/scripts/amas/refresh_ama_multi_tf_cal_anchor_from_bars.py` - SCHEME_MAP `bars_table` for 'us' and 'iso' -> `price_bars_multi_tf_u`

## Decisions Made

- **Conditional filter pattern:** The alignment_source filter is only applied when `self.config.alignment_source` is set (non-None/non-empty). This preserves backward compatibility for cases where a feature class instance is constructed without an alignment_source (reads all variants from _u). The normal usage path always has alignment_source set via SCHEME_MAP or get_alignment_source().
- **Two SQL injection patterns used:** `preload_all_bars` uses f-string injection (`{alignment_filter}` appended inline) while `_load_bars` uses `where_clauses.append()` -- both are correct and consistent with existing patterns in each method.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- ruff-format reformatted one file (ama_multi_timeframe.py) during the Task 1 pre-commit hook run, requiring a re-stage and second commit attempt. This is the standard pre-commit behavior and resolved automatically.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- AMA layer is fully redirected: all daily AMA refreshes that were failing due to dropped siloed bar tables will now read from `price_bars_multi_tf_u` with the correct `alignment_source` filter
- Plan 78-06 (remaining gap closure) can proceed
- The pattern established here (conditional alignment_source in preload/load SQL) is consistent with the EMA feature class pattern from Phase 77

---
*Phase: 78-table-drops-script-cleanup*
*Completed: 2026-03-21*
