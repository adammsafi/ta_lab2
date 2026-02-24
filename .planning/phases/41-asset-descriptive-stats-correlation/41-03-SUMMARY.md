---
phase: 41-asset-descriptive-stats-correlation
plan: "03"
subsystem: database
tags: [postgresql, correlation, scipy, pearson, spearman, rolling-window, materialized-view, multiprocessing, NullPool]

# Dependency graph
requires:
  - phase: 41-asset-descriptive-stats-correlation
    plan: "01"
    provides: "cmc_cross_asset_corr table with CHECK(id_a < id_b), cmc_cross_asset_corr_state watermark table, cmc_corr_latest materialized view"
provides:
  - "refresh_cmc_cross_asset_corr.py: CLI script that computes pairwise Pearson+Spearman rolling correlations across all N*(N-1)/2 asset pairs for 4 windows (30, 60, 90, 252 bars)"
  - "cmc_cross_asset_corr populated with pearson_r, pearson_p, spearman_r, spearman_p, n_obs per (id_a, id_b, ts, tf, window)"
  - "cmc_corr_latest materialized view refreshed at end of each run (CONCURRENTLY with non-concurrent fallback)"
  - "Watermark-based incremental refresh: only new bars appended per pair, full history on --full-rebuild"
affects:
  - "41-04 through 41-N plans that read correlation data for dashboard, notebook, or regime wiring"
  - "run_daily_refresh.py integration (future plan)"

# Tech tracking
tech-stack:
  added:
    - "scipy.stats.pearsonr / spearmanr (already in project, first use in desc_stats)"
  patterns:
    - "Pattern: cmc_returns_bars_multi_tf uses 'timestamp' column (PostgreSQL reserved word) -- must double-quote in raw SQL"
    - "Pattern: tz-aware timestamp from DB -- use .tz_localize('UTC') if naive, .tz_convert('UTC') if tz-aware (never pd.Timestamp(v, tz='UTC'))"
    - "Pattern: SpearmanrResult uses .statistic and .pvalue named tuple attributes (not positional indexing)"
    - "Pattern: Scoped DELETE + INSERT for correlation writes (delete by id_a, id_b, tf, ts >= start_ts)"
    - "Pattern: TF-level parallelism via multiprocessing.Pool with NullPool engine per worker"
    - "Pattern: REFRESH MATERIALIZED VIEW CONCURRENTLY with non-concurrent fallback on empty view"

key-files:
  created:
    - "src/ta_lab2/scripts/desc_stats/refresh_cmc_cross_asset_corr.py"
    - "src/ta_lab2/scripts/desc_stats/__init__.py (from wave-2 parallel 41-02)"
  modified: []

key-decisions:
  - "Window scope: 30, 60, 90, 252 bars as specified in 41-CONTEXT.md ('Same windows as stats: 30, 60, 90, 252')"
  - "Pair generation via list comprehension: [(a,b) for a in ids for b in ids if a < b] ensures id_a < id_b"
  - "Single wide-format DB load per TF (all assets in one query, pivot to wide), then loop over pairs in Python -- avoids N^2 DB round trips"
  - "Watermark stored as last ts in ts_index[-1] (last bar in data), not last ts written -- ensures continuity"
  - "Lookback for incremental loads: 2 * max_window * tf_days before earliest watermark to ensure window warm-up"

patterns-established:
  - "Pattern: compute_pairwise_rolling_corr returns DataFrame indexed by ts_index; caller uses reset_index() and ensures 'ts' column"
  - "Pattern: _worker_tf takes args tuple (not kwargs) for multiprocessing.Pool.imap_unordered compatibility"

# Metrics
duration: 5min
completed: "2026-02-24"
---

# Phase 41 Plan 03: Cross-Asset Correlation Refresh Summary

**Pairwise Pearson+Spearman rolling correlation script using scipy.stats, canonical pair ordering (id_a < id_b), watermark incremental refresh, and CONCURRENTLY-refreshed cmc_corr_latest materialized view**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-24T16:42:47Z
- **Completed:** 2026-02-24T16:48:04Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Created `refresh_cmc_cross_asset_corr.py` with full CLI, TF-level parallelism, and incremental watermarks
- Verified 22,452 rows written for 1 pair (id=1, id=52) across 4 windows on 1D TF
- All correctness checks pass: canonical pair order (0 bad pairs), NULL policy (0 violations), correlation bounds (0 out of range), all 4 windows present
- Incremental second run correctly writes 0 rows (watermark prevents reprocessing)
- `cmc_corr_latest` materialized view refreshed CONCURRENTLY at end of run

## Task Commits

Each task was committed atomically:

1. **Task 1: Create refresh_cmc_cross_asset_corr.py** - `04ca0e47` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `src/ta_lab2/scripts/desc_stats/refresh_cmc_cross_asset_corr.py` - Pairwise rolling correlation computation and DB write with CLI
- `src/ta_lab2/scripts/desc_stats/__init__.py` - Package init (created by wave-2 parallel 41-02)

## Decisions Made

- **Wide load strategy**: Load all assets' `ret_arith` for a TF in one query, pivot to wide DataFrame (ts x asset_id), then loop over pairs. Avoids N*(N-1)/2 separate DB queries per TF.
- **Lookback buffer**: For incremental mode, load data starting from `min_watermark - 2 * max_window * tf_days` to ensure full window warm-up even on incremental runs.
- **scipy named tuple access**: `pearsonr(a, b).statistic` and `spearmanr(a, b).statistic` (not `[0]`) per plan requirement and scipy API.
- **CONCURRENTLY + fallback**: `REFRESH MATERIALIZED VIEW CONCURRENTLY` requires unique index (created in 41-01) and non-empty view. Fallback to non-concurrent handles first-run edge case.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed: cmc_returns_bars_multi_tf uses `timestamp` column, not `ts`**

- **Found during:** Task 1 (first run attempt)
- **Issue:** Script queried `SELECT id, ts, ret_arith` but the column is named `timestamp` (PostgreSQL reserved word that must be double-quoted in raw SQL)
- **Fix:** Changed to `SELECT id, "timestamp", ret_arith` and `ORDER BY "timestamp"`, `"timestamp" >= :start_ts` in WHERE clause
- **Files modified:** `src/ta_lab2/scripts/desc_stats/refresh_cmc_cross_asset_corr.py`
- **Verification:** Query succeeds, 22,452 rows loaded and written correctly
- **Committed in:** `04ca0e47` (Task 1 commit)

**2. [Rule 1 - Bug] Fixed: tz-aware timestamp pitfall in `pd.DatetimeIndex(idx, tz="UTC")`**

- **Found during:** Task 1 (second run, incremental path)
- **Issue:** After first run, watermarks exist as tz-aware timestamps from DB. `pd.DatetimeIndex(wide.index, tz="UTC")` raises `TypeError: Cannot pass a datetime or Timestamp with tzinfo with the tz parameter. Use tz_convert instead.` when index already has timezone info.
- **Fix:** Changed to conditional `if wide.index.tz is None: .tz_localize("UTC") else: .tz_convert("UTC")`. Same fix applied to `_load_watermarks` and `_load_all_watermarks` using `pd.Timestamp(v).tz_localize/tz_convert`.
- **Files modified:** `src/ta_lab2/scripts/desc_stats/refresh_cmc_cross_asset_corr.py`
- **Verification:** Incremental second run completes in 0.5s, writes 0 rows as expected
- **Committed in:** `04ca0e47` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - Bug)
**Impact on plan:** Both fixes necessary for correctness. First is a schema discovery fix (column naming), second is the known tz-aware timestamp pitfall documented in MEMORY.md.

## Issues Encountered

- Pre-commit hook (ruff lint) caught unused variable `dim = _get_dim.__module__` in `_load_tf_list()`. Removed the unused assignment and committed cleanly on second attempt.

## User Setup Required

None - no external service configuration required. Tables were created in 41-01.

## Next Phase Readiness

- `refresh_cmc_cross_asset_corr.py` is ready for use: `python -m ta_lab2.scripts.desc_stats.refresh_cmc_cross_asset_corr --ids all --tf 1D`
- For full population: `python -m ta_lab2.scripts.desc_stats.refresh_cmc_cross_asset_corr --ids all --full-rebuild`
- Plans 41-04+ can read from `cmc_cross_asset_corr` and `cmc_corr_latest` immediately
- Integration into `run_daily_refresh.py` can be added in a future plan
- No blockers

---
*Phase: 41-asset-descriptive-stats-correlation*
*Completed: 2026-02-24*
