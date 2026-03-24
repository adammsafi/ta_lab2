---
phase: 92-ctf-ic-analysis-feature-selection
plan: 02
subsystem: analysis
tags: [ic, cross-timeframe, ctf, spearman, multiprocessing, ic_results]

# Dependency graph
requires:
  - phase: 92-01
    provides: load_ctf_features() pivot loader + dim_ctf_feature_selection table
  - phase: 90-91
    provides: ctf fact table with slope/divergence/agreement/crossover columns
  - phase: 80
    provides: ic_results table + batch_compute_ic() + save_ic_results()

provides:
  - run_ctf_ic_sweep.py CTF IC batch sweep CLI
  - IC results for all CTF features persisted to ic_results (tf=base_tf)
  - Fixed save_ic_results ON CONFLICT to include alignment_source column

affects:
  - 92-03 (CTF feature selection reads ic_results for CTF features)
  - run_ic_sweep.py (benefits from save_ic_results fix)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - CTFICWorkerTask frozen dataclass pattern for Windows-safe multiprocessing
    - venue_id=1 filter on features table close price load to avoid PK duplicate ts
    - save_ic_results alignment_source must be in both INSERT and ON CONFLICT clause

key-files:
  created:
    - src/ta_lab2/scripts/analysis/run_ctf_ic_sweep.py
  modified:
    - src/ta_lab2/analysis/ic.py

key-decisions:
  - "venue_id=1 filter on _load_close_for_asset: features PK includes venue_id, multiple venues produce duplicate ts rows — must filter to CMC_AGG (venue_id=1)"
  - "save_ic_results ON CONFLICT must include alignment_source: uq_ic_results_key unique index has 11 columns including alignment_source; save_ic_results was missing it causing InvalidColumnReference error"
  - "CTF sweep horizons [1, 5, 10, 21] matching CONTEXT.md Phase 80 forward return horizons (1d, 5d, 10d, 21d)"
  - "tf column in ic_results stores base_tf (not ref_tf): base_tf is the trading timeframe; ref_tf is embedded in feature name (e.g. rsi_14_7d_slope)"
  - "2 qualifying CTF pairs (BTC, XRP on 1D): Phase 91 CTF refresh was only run for these 2 assets; full coverage requires running refresh for all 109 assets before Plan 03"

patterns-established:
  - "CTFICWorkerTask: frozen dataclass with only picklable types (tuple not list for horizons/return_types) — MANDATORY for Windows spawn multiprocessing"
  - "_load_close_for_asset: always filter by venue_id=1 when querying features table for close prices"
  - "save_ic_results: alignment_source in INSERT column list + ON CONFLICT column list (matches uq_ic_results_key unique index)"

# Metrics
duration: 10min
completed: 2026-03-24
---

# Phase 92 Plan 02: CTF IC Sweep Summary

**CTF IC batch sweep script created; 1808 IC rows persisted for 2 assets x 113 CTF features across horizons [1, 5, 10, 21] using batch_compute_ic() via NullPool multiprocessing**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-03-24T02:27:37Z
- **Completed:** 2026-03-24T02:37:09Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created `run_ctf_ic_sweep.py` CLI following exact `run_ic_sweep.py` pattern with CTF-specific adaptations
- Full sweep executed: 2 qualifying (asset_id, base_tf) pairs discovered from ctf table, 1808 IC rows persisted
- Fixed `save_ic_results` in `ic.py` - ON CONFLICT clause was missing `alignment_source` column causing `InvalidColumnReference` error

## Task Commits

Each task was committed atomically:

1. **Task 1: Create run_ctf_ic_sweep.py** - `53879328` (feat)
2. **Task 2: Run full CTF IC sweep** - no code changes (data-only task, 1808 rows in ic_results)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/ta_lab2/scripts/analysis/run_ctf_ic_sweep.py` - CTF IC sweep CLI script (340 lines); discovers ctf pairs, loads pivot features, computes IC, persists to ic_results
- `src/ta_lab2/analysis/ic.py` - Fixed `save_ic_results`: added `alignment_source` to INSERT column list and ON CONFLICT clause to match `uq_ic_results_key` unique index

## Decisions Made
- `venue_id=1` filter added to `_load_close_for_asset()`: features table PK includes venue_id, causing 1059 duplicate ts rows across 6781 total without filter; must scope to CMC_AGG
- `save_ic_results` ON CONFLICT fix: `uq_ic_results_key` unique index has 11 columns `(asset_id, tf, feature, horizon, return_type, regime_col, regime_label, train_start, train_end, alignment_source)` — save_ic_results was using only 9 columns, causing `InvalidColumnReference`
- CTF sweep horizons `[1, 5, 10, 21]` (days): matches CONTEXT.md Phase 80 forward return horizons
- `tf` column in ic_results stores `base_tf` (e.g. `1D`), not `ref_tf`; ref_tf is embedded in feature name (e.g. `rsi_14_7d_slope` = indicator `rsi_14` at ref_tf `7d`)
- Only 2 qualifying CTF pairs in db (BTC asset_id=1 and XRP asset_id=52, both 1D): Phase 91 CTF refresh was run for only these 2 assets; Plan 03 feature selection can proceed on this basis

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed duplicate ts rows in _load_close_for_asset**
- **Found during:** Task 1 (initial BTC 1D sweep)
- **Issue:** `features` table PK is `(id, venue_id, ts, tf)` — without `venue_id` filter, multiple venues produce same ts → 1059 duplicate timestamps across 6781 rows → `batch_compute_ic` raises `ValueError: cannot reindex on an axis with duplicate labels`
- **Fix:** Added `AND venue_id = 1` to `_load_close_for_asset()` SQL query
- **Files modified:** `src/ta_lab2/scripts/analysis/run_ctf_ic_sweep.py`
- **Verification:** BTC 1D sweep succeeds, close Series has unique index
- **Committed in:** `53879328`

**2. [Rule 1 - Bug] Fixed save_ic_results ON CONFLICT column mismatch**
- **Found during:** Task 1 (BTC 1D sweep — data computed but persistence failed)
- **Issue:** `uq_ic_results_key` unique index includes `alignment_source` as 10th column. `save_ic_results` ON CONFLICT clause listed only 9 columns, raising `psycopg2.errors.InvalidColumnReference: there is no unique or exclusion constraint matching the ON CONFLICT specification`
- **Fix:** Added `alignment_source` to INSERT column list, VALUES, and ON CONFLICT clause in both overwrite and append-only SQL paths; defaults to `'multi_tf'` when not in row dict
- **Files modified:** `src/ta_lab2/analysis/ic.py`
- **Verification:** `save_ic_results` test row inserts correctly; BTC 1D sweep persists 904 rows successfully
- **Committed in:** `53879328`

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both auto-fixes essential for correctness. The save_ic_results fix also benefits the existing `run_ic_sweep.py` (same function call path).

## Issues Encountered
- CTF coverage limited to 2 assets (BTC, XRP on 1D): Phase 91 CTF refresh was only run for 2 assets. The "6 base TFs" criterion in the success criteria requires running `run_ctf_refresh.py --all` before Plan 03. The sweep script is correct and complete for all available data.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `run_ctf_ic_sweep.py` is complete and runnable; auto-discovers qualifying pairs
- `ic_results` contains 1808 CTF IC rows for 2 assets x 113 features at 4 horizons x 2 return types
- Plan 03 (CTF feature selection) can proceed on available data; expanding CTF coverage requires running `python -m ta_lab2.scripts.analysis.run_ctf_refresh --all` first
- `save_ic_results` fix ensures `run_ic_sweep.py` also works correctly with the updated ic_results schema

---
*Phase: 92-ctf-ic-analysis-feature-selection*
*Completed: 2026-03-24*
