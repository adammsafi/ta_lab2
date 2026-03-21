---
phase: 78-table-drops-script-cleanup
plan: 01
subsystem: database
tags: [postgresql, views, sql-migration, siloed-tables, _u-tables, alignment_source]

# Dependency graph
requires:
  - phase: 76-77-direct-to-u
    provides: "All 6 data families now write directly to _u tables; siloed tables are read-only"
provides:
  - "all_emas view recreated pointing at ema_multi_tf_u (safe to drop ema_multi_tf)"
  - "11 runtime Python files redirected from siloed table SQL to _u equivalents"
  - "Zero runtime references to 30 siloed data tables in Category E scope"
affects:
  - phase: 78-02
  - phase: 78-03

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Use alignment_source='multi_tf' filter when querying _u tables for base (non-cal) data"
    - "alignment_source values: 'multi_tf', 'multi_tf_cal_iso', 'multi_tf_cal_us', 'multi_tf_cal_anchor_iso', 'multi_tf_cal_anchor_us'"
    - "Calendar alignment uses format multi_tf_cal_{cal_scheme} (not 'default')"

key-files:
  created: []
  modified:
    - src/ta_lab2/features/m_tf/views.py
    - src/ta_lab2/scripts/regimes/regime_data_loader.py
    - src/ta_lab2/scripts/regimes/refresh_regimes.py
    - src/ta_lab2/scripts/desc_stats/refresh_asset_stats.py
    - src/ta_lab2/scripts/desc_stats/refresh_cross_asset_corr.py
    - src/ta_lab2/scripts/features/run_all_feature_refreshes.py
    - src/ta_lab2/scripts/features/validate_features.py
    - src/ta_lab2/scripts/features/stats/refresh_features_stats.py
    - src/ta_lab2/macro/cross_asset.py
    - src/ta_lab2/macro/lead_lag_analyzer.py
    - src/ta_lab2/experiments/runner.py

key-decisions:
  - "alignment_source for base table is 'multi_tf' not 'default' -- plan had wrong value, corrected from live DB"
  - "refresh_cross_asset_corr: removed DISTINCT ON deduplication now that alignment_source filter gives clean single-row PKs"
  - "experiments/runner.py: removed siloed names from both _ALLOWED_TABLES and _TABLES_WITH_TIMESTAMP_COL frozensets"
  - "regime_data_loader.py: cal EMA table references (ema_multi_tf_cal_{scheme}) also redirected to ema_multi_tf_u with alignment filter"

patterns-established:
  - "Queries targeting base (1D standard) data: WHERE alignment_source = 'multi_tf'"
  - "Queries targeting cal data: WHERE alignment_source = 'multi_tf_cal_{cal_scheme}'"

# Metrics
duration: 8min
completed: 2026-03-21
---

# Phase 78 Plan 01: View Migration and Runtime SQL Redirect Summary

**all_emas view migrated to ema_multi_tf_u (55.8M rows), and 10 runtime Python files redirected from 30 siloed table names to _u equivalents with alignment_source='multi_tf' filters**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-21T03:54:09Z
- **Completed:** 2026-03-21T04:02:00Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments

- Recreated `public.all_emas` VIEW in live DB pointing at `ema_multi_tf_u` (was `ema_multi_tf`) -- view now survives the siloed table DROP in Plan 78-03
- Updated `VIEW_ALL_EMAS_SQL` constant in `views.py` to match the live DB definition
- Redirected all 10 Category E runtime files: 4 `price_bars_multi_tf` refs, 6 `returns_bars_multi_tf` refs, 2 `ema_multi_tf_cal_*` refs -- all now query `_u` tables with proper `alignment_source` filters
- Removed siloed table names from `experiments/runner.py` `_ALLOWED_TABLES` security allowlist, eliminating the SQL injection risk from YAML experiments referencing dropped tables

## Task Commits

Each task was committed atomically:

1. **Task 1: Migrate all_emas view to ema_multi_tf_u** - `2e516143` (feat)
2. **Task 2: Redirect all runtime siloed-table refs to _u tables** - `24b692ca` (feat + style formatting fix)

**Plan metadata:** (see STATE.md update below)

## Files Created/Modified

- `src/ta_lab2/features/m_tf/views.py` - VIEW_ALL_EMAS_SQL updated: `FROM ema_multi_tf` -> `FROM ema_multi_tf_u`
- `src/ta_lab2/scripts/regimes/regime_data_loader.py` - `load_bars_for_tf`: both 1D and cal variants redirect to `price_bars_multi_tf_u`; `load_emas_for_tf`: cal variant redirects to `ema_multi_tf_u` with alignment filter
- `src/ta_lab2/scripts/regimes/refresh_regimes.py` - `_get_all_asset_ids`: JOIN updated to `price_bars_multi_tf_u` with `alignment_source='multi_tf'`
- `src/ta_lab2/scripts/desc_stats/refresh_asset_stats.py` - `SOURCE_TABLE` -> `returns_bars_multi_tf_u`; both SQL queries + `--all-venues` query updated with alignment filter
- `src/ta_lab2/scripts/desc_stats/refresh_cross_asset_corr.py` - `SOURCE_TABLE` -> `returns_bars_multi_tf_u`; `DISTINCT ON` deduplication removed (alignment filter makes rows unique)
- `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` - `_load_asset_ids`: `price_bars_multi_tf` -> `price_bars_multi_tf_u` with alignment filter; help text updated
- `src/ta_lab2/scripts/features/validate_features.py` - 3 SQL queries updated: `returns_bars_multi_tf_u`, `price_bars_multi_tf_u` x2, all with alignment filter
- `src/ta_lab2/scripts/features/stats/refresh_features_stats.py` - `BAR_TABLE` -> `public.price_bars_multi_tf_u`; two SQL constants updated with `WHERE alignment_source = 'multi_tf'`
- `src/ta_lab2/macro/cross_asset.py` - 2 queries updated: `returns_bars_multi_tf_u` with alignment filter
- `src/ta_lab2/macro/lead_lag_analyzer.py` - `_get_table_columns` call and SQL query -> `returns_bars_multi_tf_u`
- `src/ta_lab2/experiments/runner.py` - Removed 6 siloed table names from `_ALLOWED_TABLES` and `_TABLES_WITH_TIMESTAMP_COL` frozensets

## Decisions Made

- **alignment_source correction:** The plan specified `'default'` as the alignment_source for base table data. Live DB query showed the actual value is `'multi_tf'`. All filters use `'multi_tf'` (verified from `SELECT DISTINCT alignment_source FROM public.price_bars_multi_tf_u`).
- **cross_asset_corr deduplication:** Removed `DISTINCT ON (id, "timestamp") ... ORDER BY id, "timestamp", venue_id` pattern since filtering to `alignment_source='multi_tf'` now guarantees unique (id, timestamp) rows. Cleaner and faster.
- **regime_data_loader cal EMA:** The plan said to redirect only `price_bars_multi_tf_cal_*` tables. Also redirected `ema_multi_tf_cal_*` table references in `load_emas_for_tf` (they were siloed tables, same category).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] alignment_source value is 'multi_tf' not 'default' as plan stated**

- **Found during:** Task 2, before writing any code (verified via live DB query)
- **Issue:** Plan 78-01 specified `AND alignment_source = 'default'` but live DB shows `alignment_source = 'multi_tf'` for base table data. Using `'default'` would return zero rows.
- **Fix:** Used `'multi_tf'` throughout all alignment_source filters
- **Verification:** `SELECT DISTINCT alignment_source FROM public.price_bars_multi_tf_u` returns `['multi_tf', 'multi_tf_cal_anchor_iso', 'multi_tf_cal_anchor_us', 'multi_tf_cal_iso', 'multi_tf_cal_us']`
- **Committed in:** `24b692ca`

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: wrong alignment_source value in plan)
**Impact on plan:** Critical correction -- using 'default' would have caused all queries to return empty results. All 10 files use the correct 'multi_tf' value.

## Issues Encountered

- ruff formatter reformatted `regime_data_loader.py` (long dict literal on one line), requiring a separate formatting commit after the main Task 2 commit. All 10 changed files ended up in the style commit `24b692ca` due to pre-commit hook behavior.

## User Setup Required

None - no external service configuration required. View recreation was executed in-place against the live DB.

## Next Phase Readiness

- Plan 78-02 (script cleanup) is already complete (completed prior to this plan in execution order)
- Plan 78-03 (table drops) is now safe to execute:
  - `all_emas` view no longer depends on `ema_multi_tf`
  - All Category E runtime Python files query `_u` tables only
  - `experiments/runner.py` allowlist no longer accepts siloed table names

---
*Phase: 78-table-drops-script-cleanup*
*Completed: 2026-03-21*
