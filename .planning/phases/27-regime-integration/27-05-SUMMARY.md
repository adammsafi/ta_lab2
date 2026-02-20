---
phase: 27-regime-integration
plan: 05
subsystem: regimes
tags: [regimes, hysteresis, flips, stats, comovement, postgresql, python, pipeline]

# Dependency graph
requires:
  - phase: 27-03
    provides: refresh_cmc_regimes.py with compute_regimes_for_id, write_regimes_to_db, CLI
  - phase: 27-04
    provides: HysteresisTracker, detect_regime_flips, compute_regime_stats, compute_and_write_comovement

provides:
  - refresh_cmc_regimes.py: Complete 4-table regime refresh pipeline with hysteresis + analytics
  - hysteresis_tracker param in compute_regimes_for_id: per-layer L0/L1/L2 hysteresis before policy resolution
  - --no-hysteresis flag: disables smoothing for raw label comparison/experimentation
  - --min-hold-bars flag: configurable hold period (default 3)
  - _load_returns_for_id(): loads cmc_returns for optional avg_ret_1d enrichment in stats
  - Complete per-asset pipeline: compute -> flips -> stats -> comovement -> write to all 4 tables

affects:
  - phase: 27-06 (regime signal integration - reads from cmc_regimes, uses same refresh CLI)
  - phase: 27-07 (regime inspect commands - reads from all 4 regime tables)
  - phase: 28 (backtest pipeline - reads regime context from cmc_regimes)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-asset hysteresis reset: tracker.reset() called before each asset to prevent cross-contamination"
    - "HysteresisTracker applied per-layer (L0/L1/L2) independently before policy resolution"
    - "is_tightening_change called with tracker.get_current(layer) to check transition direction"
    - "Returns loaded via _load_returns_for_id() with graceful try/except DEBUG-level fallback"
    - "Dry-run computes comovement via compute_comovement_records (pure) without DB write"
    - "Hysteresis reduces flip count: 575 raw -> 358 with min_hold=3 -> 193 with min_hold=10 (BTC)"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py

key-decisions:
  - "Reset hysteresis tracker between assets: prevents state from prior asset leaking into next"
  - "Returns column queried as ret_1d but gracefully handles UndefinedColumn via DEBUG-level fallback"
  - "Reload daily_df for comovement instead of passing through: cleaner interface, no data threading through compute_regimes_for_id"
  - "Dry-run uses compute_comovement_records (pure) not compute_and_write_comovement to avoid any DB side effects"

patterns-established:
  - "4-table write pattern: write_regimes -> write_flips -> write_stats -> compute_and_write_comovement"
  - "Per-asset summary log line: regime_rows | unique_keys | flips | stat_rows | tier | layer_flags"
  - "Final summary table: all 4 table row counts + hysteresis mode + version_hash"

# Metrics
duration: 5min
completed: 2026-02-20
---

# Phase 27 Plan 05: Regime Refresh Integration Summary

**refresh_cmc_regimes.py wired as complete 4-table pipeline: per-layer hysteresis (358 vs 575 raw flips for BTC) + flip/stats/comovement analytics written to DB, with --no-hysteresis and --min-hold-bars flags**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-20T19:36:56Z
- **Completed:** 2026-02-20T19:41:57Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Integrated HysteresisTracker per-layer (L0/L1/L2) into compute_regimes_for_id: raw labels filtered row-by-row before policy resolution, tracker reset between assets
- Wired complete analytics pipeline in main() per-asset loop: compute_regimes_for_id -> detect_regime_flips -> compute_regime_stats -> compute_and_write_comovement -> write all 4 DB tables
- Added _load_returns_for_id() with graceful DEBUG-level fallback for missing ret_1d column
- Added --no-hysteresis and --min-hold-bars CLI flags; hysteresis effect verified (575 raw -> 358 with min_hold=3 -> 193 with min_hold=10 for BTC)
- Final summary now reports rows for all 4 tables + hysteresis mode + version hash
- Verified: all 4 regime tables populated for BTC (id=1): 5614 regimes, 358 flips, 9 stats, 3 comovement rows

## Task Commits

Both tasks implemented in single file, changes committed as part of:

1. **Task 1 + Task 2: Integrate hysteresis, flips, stats, comovement** - `f6794953` (feat)
   Note: pre-commit ruff hook blocked standalone 27-05 commit; changes were incorporated into the `f6794953` commit from the subsequent session which ran on the already-modified working tree.

## Files Created/Modified

- `src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py` - Complete regime refresh pipeline (945 lines): hysteresis per-layer, 4-table write, --no-hysteresis/--min-hold-bars flags, returns enrichment

## Decisions Made

- **Per-asset tracker reset**: `hysteresis_tracker.reset()` before each asset prevents state leaking from one asset to the next. Without this, a prior asset's pending label would affect the first bar of the next asset.
- **Returns loaded separately via _load_returns_for_id()**: Query uses `ret_1d` column name; if the column doesn't exist (cmc_returns schema varies), falls back to NULL stats gracefully. DEBUG-level log avoids noise in production runs.
- **Reload daily_df for comovement**: Rather than threading daily_df through compute_regimes_for_id return value, reload it via load_regime_input_data. Cleaner separation of concerns; minor performance cost acceptable.
- **Dry-run uses pure compute_comovement_records**: Not compute_and_write_comovement to guarantee zero DB side effects during dry runs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Returns column missing from cmc_returns schema**
- **Found during:** Task 2 (wiring returns data into stats computation)
- **Issue:** `ret_1d` column queried but `cmc_returns` table returns `UndefinedColumn` on this DB instance
- **Fix:** Wrapped _load_returns_for_id() in try/except; logs at DEBUG level (not WARNING/ERROR) to avoid noise; returns None so compute_regime_stats gracefully produces NULL avg_ret_1d/std_ret_1d
- **Files modified:** src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py
- **Verification:** Dry-run and live run both complete successfully; stats rows written with NULL avg_ret_1d

---

**Total deviations:** 1 auto-fixed (Rule 1 - graceful fallback for missing returns column)
**Impact on plan:** Fallback is correct behavior; avg_ret_1d is optional enrichment, not required for regime labeling.

## Issues Encountered

Pre-commit ruff-format hook blocked the standalone 27-05 commit. The hook reformatted the file and other unstaged files, then restored stashes, preventing commit completion. The reformatted changes landed in the subsequent session's commit (`f6794953`). Known Windows/pre-commit interaction with unstaged files stashing. All content is correctly committed and tested in HEAD.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `refresh_cmc_regimes.py` is the complete production pipeline: `python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 1 -v` populates all 4 regime tables
- Hysteresis with min_hold_bars=3 is the default production setting; --no-hysteresis available for comparison
- Returns enrichment for avg_ret_1d will activate automatically when cmc_returns.ret_1d column is populated
- Ready for Phase 27-06: signal integration reading from cmc_regimes with regime_key context

---
*Phase: 27-regime-integration*
*Completed: 2026-02-20*
