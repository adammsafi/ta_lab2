---
phase: 41-asset-descriptive-stats-correlation
plan: "06"
subsystem: regimes
tags: [regime, descriptive-stats, quality-checks, rolling-stats, augmentation, postgresql]

# Dependency graph
requires:
  - phase: 41-04
    provides: desc stats pipeline (cmc_asset_stats, cmc_cross_asset_corr tables populated)
provides:
  - Rolling stats loader function for regime augmentation
  - Optional stats augmentation in regime refresh loop with graceful fallback
  - --no-desc-stats flag on refresh_cmc_regimes.py
  - --no-desc-stats-in-regimes flag on run_daily_refresh.py propagated to regime subprocess
  - Inline quality checks for cmc_asset_stats and cmc_cross_asset_corr in stats runner
affects:
  - Future regime labeling phases that use stats columns
  - Stats monitoring and alerting pipeline

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Optional augmentation via graceful fallback (load returns None on empty/error, caller skips merge)
    - Inline quality check function returning list of dicts with table/check/status/detail keys
    - Flag propagation pattern: --no-desc-stats-in-regimes on orchestrator -> --no-desc-stats on subprocess

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/regimes/regime_data_loader.py
    - src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py
    - src/ta_lab2/scripts/run_daily_refresh.py
    - src/ta_lab2/scripts/stats/run_all_stats_runners.py

key-decisions:
  - "load_rolling_stats_for_asset returns None (not empty DataFrame) to distinguish unavailable from empty table"
  - "Stats augmentation added to main per-asset loop (not inside compute_regimes_for_id) to avoid modifying labeling functions"
  - "check_desc_stats_quality is inline (not in STATS_TABLES/ALL_STATS_SCRIPTS) because no subprocess runner script exists for desc stats"
  - "desc_fail triggers FAIL status, desc_warn triggers WARN in overall status determination"

patterns-established:
  - "Optional augmentation pattern: load returns None on empty/error, caller checks before merge"
  - "Quality check inline function pattern: returns list of {table, check, status, detail} dicts, no DB writes"

# Metrics
duration: 5min
completed: 2026-02-24
---

# Phase 41 Plan 06: Regime-Stats Integration and Desc Stats Quality Checks Summary

**Rolling stats augmentation wired into regime pipeline via left-join on ts index with graceful fallback, and cmc_asset_stats/cmc_cross_asset_corr registered in stats quality infrastructure.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-24T16:59:48Z
- **Completed:** 2026-02-24T17:04:21Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added `load_rolling_stats_for_asset()` to `regime_data_loader.py` -- queries cmc_asset_stats for 5 rolling stat columns (std_ret_30, std_ret_90, sharpe_ann_90, sharpe_ann_252, max_dd_from_ath) indexed by ts (UTC), returns None on empty/error
- Wired optional stats augmentation into `refresh_cmc_regimes.py` main loop: loads rolling stats and left-joins into daily_df; `--no-desc-stats` flag disables it; logs INFO with column count or "not available"
- Added `--no-desc-stats-in-regimes` flag to `run_daily_refresh.py` that propagates as `--no-desc-stats` to the regime subprocess
- Added `check_desc_stats_quality(engine)` inline function to `run_all_stats_runners.py` with 7 checks across 2 tables; integrated into PASS/WARN/FAIL status determination in `run_all_stats()`

## Task Commits

Each task was committed atomically:

1. **Task 1: Add rolling stats loader to regime_data_loader.py** - `92dd2766` (feat)
2. **Task 2: Wire optional stats augmentation into refresh_cmc_regimes.py and run_daily_refresh.py** - `fae71619` (feat)
3. **Task 3: Register desc stats tables in stats quality infrastructure** - `72a649a0` (feat)

**Plan metadata:** (pending final commit)

## Files Created/Modified

- `src/ta_lab2/scripts/regimes/regime_data_loader.py` - Added `load_rolling_stats_for_asset()` function; updated module docstring Exports section
- `src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py` - Added import, `--no-desc-stats` flag, rolling stats augmentation step in main loop
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added `--no-desc-stats-in-regimes` flag; propagates to regime subprocess in `run_regime_refresher()`
- `src/ta_lab2/scripts/stats/run_all_stats_runners.py` - Added `check_desc_stats_quality()` function; call site in `run_all_stats()`; status integration; inline result printing

## Decisions Made

- **Returns None not empty DataFrame:** `load_rolling_stats_for_asset` returns `None` when no rows found or on error. This allows callers to distinguish "stats unavailable" from "stats empty for this asset" -- cleaner conditional logic than checking `df.empty`.
- **Augmentation in main loop, not in compute_regimes_for_id:** The plan required not modifying label_layer_daily or other labeling functions. The augmentation is added after `load_regime_input_data` in the per-asset loop, where the daily_df is available for comovement computation.
- **Inline quality check, not in STATS_TABLES/ALL_STATS_SCRIPTS:** No subprocess stats runner script exists for desc stats tables. Inline function avoids the need to create one and keeps checks co-located with status determination logic.
- **FAIL for pearson_r out of range and id_pair ordering violations:** These are hard constraint violations (mathematical impossibility for correlation, primary key semantics). WARN for NULLs and empty tables which may be expected during initial data load.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Ruff formatter reformatted the refresh_cmc_regimes.py file after initial commit (split a chained method call across lines). Re-staged and committed the formatted version. No logic changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Rolling stats columns (std_ret_30, std_ret_90, sharpe_ann_90, sharpe_ann_252, max_dd_from_ath) are now available in the daily_df during regime computation as augmentation infrastructure
- Quality checks for cmc_asset_stats and cmc_cross_asset_corr are active in the stats runner pipeline
- Future labeling phases can consume the merged stats columns -- currently merged but unused by labelers
- A/B testing possible via `--no-desc-stats-in-regimes` flag for regime runs without stats augmentation

---
*Phase: 41-asset-descriptive-stats-correlation*
*Completed: 2026-02-24*
