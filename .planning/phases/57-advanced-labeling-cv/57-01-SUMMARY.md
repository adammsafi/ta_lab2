---
phase: 57-advanced-labeling-cv
plan: 01
subsystem: labeling
tags: [triple-barrier, meta-labeling, afml, alembic, postgres, sqlalchemy, pandas, numpy]

# Dependency graph
requires:
  - phase: 56-factor-analytics-reporting
    provides: Alembic migration chain head (d4e5f6a1b2c3) that this plan extends
  - phase: 38-pbo-analysis
    provides: PurgedKFoldSplitter/CPCVSplitter in cv.py that t1_series feeds
provides:
  - cmc_triple_barrier_labels PostgreSQL table (UUID PK, vol-scaled barrier params, +1/-1/0 labels)
  - cmc_meta_label_results PostgreSQL table (UUID PK, signal_type, primary_side, meta_label, trade_probability)
  - Alembic migration e5f6a1b2c3d4 creating both tables
  - src/ta_lab2/labeling/triple_barrier.py with get_daily_vol, add_vertical_barrier, apply_triple_barriers, get_bins, get_t1_series
  - Updated src/ta_lab2/labeling/__init__.py exporting triple barrier functions alongside existing cusum/trend_scanning
affects:
  - 57-02 (meta-labeler that writes to cmc_meta_label_results)
  - 57-03 (CPCV integration using t1_series from triple barrier output)
  - Any future phase doing signal-level ML that needs labeled events

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Triple barrier labeling: vol-scaled barriers (EWM std of log returns) with bar-count vertical barrier"
    - "tz-aware UTC pattern: use .tolist() NOT .values when extracting tz-aware timestamps on Windows"
    - "Alembic revision chaining: each Phase 57 plan extends the head from the previous migration"

key-files:
  created:
    - src/ta_lab2/labeling/triple_barrier.py
    - sql/labeling/085_cmc_triple_barrier_labels.sql
    - sql/labeling/086_cmc_meta_label_results.sql
    - alembic/versions/e5f6a1b2c3d4_triple_barrier_meta_label_tables.py
  modified:
    - src/ta_lab2/labeling/__init__.py

key-decisions:
  - "down_revision = d4e5f6a1b2c3 (Phase 56 migration 4/4: add_cs_norms_to_features), NOT the value in the plan (30eac3660488)"
  - "Bar-count vertical barriers (not calendar time): avoids variable density around weekends/holidays"
  - "Use .tolist() not .values to extract tz-aware datetimes on Windows (numpy.datetime64 strips tz)"
  - "Added get_t1_series() helper as the canonical safe way to build t1_series for PurgedKFoldSplitter"
  - "No mlfinpy/mlfinlab dependency: full from-scratch AFML Ch.3 implementation"

patterns-established:
  - "Triple barrier output index is tz-aware UTC DatetimeIndex; t1 column is datetime64[ns, UTC]"
  - "get_t1_series(result) is the safe path from apply_triple_barriers output to cv.py input"

# Metrics
duration: 6min
completed: 2026-02-28
---

# Phase 57 Plan 01: Triple Barrier Foundation Summary

**AFML Ch.3 triple barrier labeler (get_daily_vol + vol-scaled barriers + bar-count VB) producing tz-aware {+1/-1/0} labels stored in two new Alembic-managed PostgreSQL tables**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-02-28T07:03:52Z
- **Completed:** 2026-02-28T07:09:51Z
- **Tasks:** 2/2
- **Files modified:** 5

## Accomplishments

- Created `cmc_triple_barrier_labels` and `cmc_meta_label_results` PostgreSQL tables via Alembic migration e5f6a1b2c3d4
- Implemented full AFML Ch.3 triple barrier labeler (357 lines, 5 functions) with no mlfinpy dependency
- Fixed critical tz-awareness pitfall: added `get_t1_series()` that uses `.tolist()` instead of `.values` to correctly preserve UTC timezone on Windows
- Verified PurgedKFoldSplitter compatibility: `get_t1_series(result)` feeds directly into cv.py splitters without TypeError

## Task Commits

Each task was committed atomically:

1. **Task 1: DDL files and Alembic migration** - `14d846a8` (feat)
2. **Task 2: Labeling package with triple barrier library** - `5e892ebf` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `sql/labeling/085_cmc_triple_barrier_labels.sql` - DDL reference for triple barrier labels table (label_id UUID PK, vol-scaled params, +1/-1/0 bin)
- `sql/labeling/086_cmc_meta_label_results.sql` - DDL reference for meta-label results table (result_id UUID PK, signal_type, primary_side, trade_probability)
- `alembic/versions/e5f6a1b2c3d4_triple_barrier_meta_label_tables.py` - Alembic migration creating both tables (down_revision: d4e5f6a1b2c3)
- `src/ta_lab2/labeling/triple_barrier.py` - Core labeler: get_daily_vol, add_vertical_barrier, apply_triple_barriers, get_bins, get_t1_series
- `src/ta_lab2/labeling/__init__.py` - Extended to export triple barrier functions alongside existing cusum/trend_scanning

## Decisions Made

1. **down_revision corrected to d4e5f6a1b2c3** (plan said 30eac3660488): Phase 56 added 4 migrations, current head at execution was `d4e5f6a1b2c3` (add_cs_norms_to_features). Using the actual head is mandatory for a valid migration chain.

2. **Bar-count vertical barriers** (not calendar time): `close.index.searchsorted(t_events)` + `num_bars` advance gives consistent barrier width regardless of trading session gaps, weekends, and holidays. Aligns with AFML research note and avoids calendar-time pitfall.

3. **get_t1_series() added as 5th function**: The plan specified 4 functions. Added `get_t1_series()` because `pd.Series(result['t1'].values, ...)` strips tz-awareness on Windows (documented in MEMORY.md). The helper uses `.tolist()` to safely extract tz-aware t1 values. This is critical for cv.py compatibility.

4. **No mlfinpy/mlfinlab**: Implemented from scratch following AFML Ch.3 patterns. mlfinpy is discontinued with known bugs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added get_t1_series() helper to prevent tz-strip bug when passing output to PurgedKFoldSplitter**

- **Found during:** Task 2 verification
- **Issue:** `pd.Series(result['t1'].values, index=result.index)` drops tz-awareness on Windows (numpy.datetime64 strips UTC). The resulting tz-naive Series causes `TypeError: Cannot compare tz-naive and tz-aware datetime-like objects` in PurgedKFoldSplitter.split().
- **Fix:** Added `get_t1_series(df)` that uses `.tolist()` to build a `datetime64[ns, UTC]` Series without tz-loss. Also made the result DataFrame index tz-aware UTC via `pd.DatetimeIndex(valid_t0_list).tz_localize("UTC")`.
- **Files modified:** `src/ta_lab2/labeling/triple_barrier.py`, `src/ta_lab2/labeling/__init__.py`
- **Verification:** `PurgedKFoldSplitter(n_splits=3, t1_series=get_t1_series(result)).split(X)` produces 3 folds without error
- **Committed in:** 5e892ebf (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** The fix is essential for cv.py compatibility. Adds one extra exported function. No scope creep.

## Issues Encountered

- Pre-commit hooks fixed CRLF line endings and ruff formatting on both commits. Required re-staging and committing twice per task (standard Windows workflow).

## User Setup Required

None - no external service configuration required. Alembic migration runs against existing configured database.

## Next Phase Readiness

- `apply_triple_barriers()` is ready for Phase 57-02 (meta-labeler) to call and write results to `cmc_triple_barrier_labels`
- `get_t1_series(result)` is the correct way to extract t1_series for `PurgedKFoldSplitter` and `CPCVSplitter`
- Both DB tables exist in PostgreSQL with unique constraints enabling upsert semantics
- No blockers for Phase 57-02

---
*Phase: 57-advanced-labeling-cv*
*Completed: 2026-02-28*
