---
phase: 57-advanced-labeling-cv
plan: 03
subsystem: labeling
tags: [triple-barrier, afml, etl, batch-refresh, cusum, postgres, sqlalchemy, pandas, numpy]

# Dependency graph
requires:
  - phase: 57-advanced-labeling-cv
    plan: 01
    provides: triple_barrier.py (get_daily_vol, apply_triple_barriers), cmc_triple_barrier_labels DDL with uq_triple_barrier_key constraint
  - phase: 57-advanced-labeling-cv
    plan: 02
    provides: cusum_filter.py (cusum_filter, get_cusum_threshold) for optional event pre-filtering
provides:
  - src/ta_lab2/scripts/labeling/ package (scripts/labeling/__init__.py)
  - refresh_triple_barrier_labels.py CLI script: batch ETL from cmc_price_bars_multi_tf_u to cmc_triple_barrier_labels
  - 5612 triple barrier labels persisted for BTC (asset_id=1, tf=1D, pt=1.0, sl=1.0, vb=10)
affects:
  - 57-05 (meta-labeling script that reads from cmc_triple_barrier_labels)
  - 57-06 (CPCV cross-validation that queries persisted t0/t1 timestamps)
  - Any future script doing label-based ML training on persisted events

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "NullPool engine pattern: poolclass=NullPool for one-shot batch scripts"
    - "Upsert via ON CONFLICT ON CONSTRAINT uq_triple_barrier_key DO UPDATE for idempotent re-runs"
    - "Per-row UUID generation in Python before INSERT (uuid.uuid4()) to avoid RETURNING overhead"
    - "tz-aware UTC close Series from pd.to_datetime(utc=True) to handle both tz-naive and tz-aware DB returns"

key-files:
  created:
    - src/ta_lab2/scripts/labeling/__init__.py
    - src/ta_lab2/scripts/labeling/refresh_triple_barrier_labels.py
  modified: []

key-decisions:
  - "cmc_price_bars_multi_tf_u timestamp column is 'timestamp' (not 'ts') -- discovered at runtime, fixed immediately"
  - "Per-row INSERT loop (not bulk to_sql) chosen for upsert compatibility; 5612 rows in ~3s is acceptable for batch ETL"
  - "CUSUM filter produces 841 events vs 5612 all-bar for BTC 1D (85% reduction) -- plan said 20-40% but this is correct behavior for high-vol asset with multiplier=2.0"
  - "daily_vol and target columns both set to get_daily_vol(close)[t0] -- they are the same value (vol-scaled target IS daily_vol)"

patterns-established:
  - "Triple barrier ETL pattern: load_close -> get_daily_vol -> [optional cusum_filter] -> apply_triple_barriers -> write_labels with upsert"
  - "CLI arg pattern for labeling scripts: --ids/--all mutually exclusive required group, --tf, barrier params, --full-refresh, --dry-run, --cusum-filter"

# Metrics
duration: 3min
completed: 2026-02-28
---

# Phase 57 Plan 03: Triple Barrier Batch Refresh Script Summary

**ETL script bridging triple barrier library to DB: batch-computes vol-scaled AFML labels from close prices and upserts to cmc_triple_barrier_labels with 5612 BTC daily labels verified**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-28T07:13:49Z
- **Completed:** 2026-02-28T07:16:28Z
- **Tasks:** 1/1
- **Files modified:** 2

## Accomplishments

- Created `src/ta_lab2/scripts/labeling/` package with full CLI refresh script
- Verified 5612 triple barrier labels persisted for BTC (asset_id=1, 1D tf): dist {-1: 2132, 0: 594, +1: 2886}
- Confirmed idempotent upsert: re-run with same params keeps exactly 5612 rows, no duplicates
- CUSUM filter mode working: 841 events vs 5612 all-bar (BTC 1D with multiplier=2.0)

## Task Commits

1. **Task 1: Create scripts/labeling package and refresh_triple_barrier_labels.py** - `666a1b70` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/labeling/__init__.py` - Package init for labeling scripts
- `src/ta_lab2/scripts/labeling/refresh_triple_barrier_labels.py` - Batch ETL script (237 lines): full CLI, load/label/write per asset, CUSUM integration, upsert semantics

## Decisions Made

1. **timestamp column name**: cmc_price_bars_multi_tf_u uses `timestamp` not `ts`. Discovered at first dry-run, fixed immediately (Rule 3 - Blocking). This is consistent with the unified `_u` tables using `timestamp` as the bar datetime column.

2. **Per-row INSERT loop**: Used a loop over rows with individual `conn.execute(text(upsert_sql), row)` rather than `to_sql()` + temp table, because `to_sql()` does not support `ON CONFLICT` clauses natively. For 5612 rows in ~3s this is acceptable batch ETL performance.

3. **CUSUM event density**: BTC with multiplier=2.0 produces 841 events from 5712 bars (~14.7% density). The plan mentioned "20-40% reduction" but CUSUM is working as intended -- the density depends on asset volatility and multiplier. Higher volatility assets naturally produce sparser events with the same multiplier.

4. **daily_vol == target**: Both the `daily_vol` and `target` columns in the DDL are set to `get_daily_vol(close)[t0]`. They capture the same value (EWM std of log returns at the event entry bar) which is the vol-scaled barrier target. The DDL allows them to differ if a different target function is used later.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] cmc_price_bars_multi_tf_u uses 'timestamp' column, not 'ts'**

- **Found during:** Task 1 (first dry-run execution)
- **Issue:** `load_close()` query used `SELECT ts, close FROM ...` which raised `UndefinedColumn` -- the actual column name is `timestamp`
- **Fix:** Updated query to `SELECT timestamp, close FROM ... ORDER BY timestamp`; added inline comment documenting the column name
- **Files modified:** `src/ta_lab2/scripts/labeling/refresh_triple_barrier_labels.py`
- **Verification:** Dry-run succeeded producing 5612 label counts after fix
- **Committed in:** 666a1b70 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 - Blocking)
**Impact on plan:** One-line fix, no scope change. Column name now documented inline for future scripts.

## Issues Encountered

- Pre-commit hooks (ruff-format + mixed-line-ending) reformatted files on first commit attempt. Required re-staging and committing twice -- standard Windows workflow (CRLF -> LF conversion).

## User Setup Required

None - no external service configuration required. Script reads from and writes to existing PostgreSQL tables.

## Next Phase Readiness

- `refresh_triple_barrier_labels.py --ids N --tf 1D` is the command for 57-05 (meta-labeler) to use for populating the label store before training
- `cmc_triple_barrier_labels` now has 5612 BTC 1D labels ready for downstream consumption
- CUSUM filter integration verified -- 57-05 can pass `--cusum-filter` to produce sparser, less-overlapping training events
- `get_triple_barrier_t1_series` (from 57-01) combined with these persisted labels enables 57-06 CPCV splits
- No blockers for 57-04 or 57-05

---
*Phase: 57-advanced-labeling-cv*
*Completed: 2026-02-28*
