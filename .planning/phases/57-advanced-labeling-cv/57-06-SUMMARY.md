---
phase: 57-advanced-labeling-cv
plan: 06
subsystem: labeling
tags: [cpcv, cross-validation, sharpe-distribution, ema-crossover, rsi, atr, afml, backtesting, pandas, numpy, sqlalchemy, purging, embargo]

# Dependency graph
requires:
  - phase: 57-advanced-labeling-cv
    plan: 01
    provides: cmc_triple_barrier_labels DDL + triple_barrier.py library
  - phase: 57-advanced-labeling-cv
    plan: 03
    provides: 5612 BTC 1D triple barrier labels in DB (t0/t1 timestamps for purging)
  - phase: 57-advanced-labeling-cv
    plan: 04
    provides: make_signals() functions for ema_crossover, rsi_mean_revert, atr_breakout
provides:
  - src/ta_lab2/scripts/labeling/run_cpcv_backtest.py (815 lines, CLI script)
  - CPCV(6,2) Sharpe distribution: 15 OOS Sharpe ratios per signal strategy
  - _build_features_with_ema(): pre-joins cmc_ema_multi_tf_u pivot into features_df
  - JSON output at .planning/phases/57-advanced-labeling-cv/cpcv_results_{id}_{signal}.json
  - LABEL-03 satisfied: CPCV produces distribution of OOS Sharpe ratios (not point estimate)
affects:
  - Future CPCV-based PBO (Probability of Backtest Overfitting) analysis
  - Any strategy evaluation that needs multiple OOS Sharpe paths vs. single full-sample Sharpe
  - Phase 57-05 (meta-labeling) if it wants CPCV-based OOS evaluation

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pre-join EMA pivot pattern: load cmc_ema_multi_tf_u, pivot period->ema_N columns, join into features_df BEFORE CPCV loop so iloc[test_idx] slicing preserves EMA columns"
    - "CPCVSplitter bridge pattern: integer indices from splitter.split() -> features_df.iloc[test_idx] -> make_signals() -> compute_oos_sharpe()"
    - "t1_series tz-aware construction: use .tolist() (NOT .values) on tz-aware pandas Series to preserve UTC timezone when building DatetimeIndex"
    - "Position series vectorization: (entries - exits).cumsum().clip(0,1) for continuous 0/1 position from discrete entry/exit signals"
    - "Transaction cost model: (fee_bps + slippage_bps) / 1e4 applied at each bar with entry or exit event"

key-files:
  created:
    - src/ta_lab2/scripts/labeling/run_cpcv_backtest.py
    - .planning/phases/57-advanced-labeling-cv/cpcv_results_1_ema_crossover.json
  modified: []

key-decisions:
  - "Pre-join EMA columns before CPCV loop (not per-fold): avoids repeated DB queries and ensures make_signals() receives the correct column layout on every test fold slice"
  - "Use make_signals() on test fold (not pre-computed signal records from cmc_signals_* tables): signal tables store event records, not continuous position series; make_signals() on the test feature slice is cleaner and avoids OOS contamination"
  - "position = (entries - exits).cumsum().clip(0,1): vectorized vs. Python loop; correct for next-bar execution semantics after shift(1) in _compute_oos_sharpe"
  - "Research output only (JSON file, no DB table): CPCV is a research/evaluation tool, not part of production signal pipeline"

patterns-established:
  - "CPCV runner pattern: pre-check -> build_features_with_ema -> load_t1_series -> align -> CPCVSplitter -> loop(make_signals, compute_oos_sharpe) -> aggregate distribution"

# Metrics
duration: 7min
completed: 2026-02-28
---

# Phase 57 Plan 06: CPCV Sharpe Distribution Runner Summary

**CPCV(6,2) runner producing 15 OOS Sharpe ratios per signal strategy: pre-joined EMA pivot, t1_series purging, make_signals() per fold, JSON output; BTC 1D ema_crossover verified at mean=-0.84 Sharpe, P10=-1.98, 5/15 splits positive**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-02-28T07:22:46Z
- **Completed:** 2026-02-28T07:29:30Z
- **Tasks:** 1/1
- **Files modified:** 2

## Accomplishments

- Created `run_cpcv_backtest.py` (815 lines): full CLI for CPCV Sharpe distribution over any signal strategy
- CPCV(6,2) -> 15 OOS Sharpe splits verified for BTC 1D ema_crossover (mean=-0.84, P10=-1.98, 33% positive)
- Pre-joined EMA columns (ema_9, ema_21, ema_50) from `cmc_ema_multi_tf_u` before CPCV loop using pivot pattern
- Pre-condition check catches missing triple barrier labels with actionable `refresh_triple_barrier_labels` command
- LABEL-03 satisfied: CPCV produces a genuine distribution of OOS Sharpe ratios (not a single point estimate)

## Task Commits

1. **Task 1: Create CPCV Sharpe distribution runner** - `24d25074` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/labeling/run_cpcv_backtest.py` - 815-line CLI script: CPCV pipeline, EMA pre-join, per-fold make_signals(), Sharpe aggregation, JSON output
- `.planning/phases/57-advanced-labeling-cv/cpcv_results_1_ema_crossover.json` - BTC 1D ema_crossover CPCV results (15 splits, verified distribution)

## Decisions Made

1. **Pre-join EMA columns before CPCV loop**: `_build_features_with_ema()` queries `cmc_ema_multi_tf_u` once for all periods, pivots `period -> ema_N` columns, and joins into the full `features_df`. Then `features_df.iloc[test_idx]` naturally includes the EMA columns for `make_signals()`. Alternative (per-fold EMA loading) would cause 15x DB queries and complexity.

2. **make_signals() on test fold, not pre-computed signal records**: Signal tables (`cmc_signals_ema_crossover`) store entry/exit event records with `position_state` — not a continuous position series that can be sliced by timestamp range and used directly for return computation. Calling `make_signals(test_features_df)` is clean and matches the CPCV intent of evaluating the signal strategy OOS.

3. **Vectorized position from (entries - exits).cumsum().clip(0,1)**: Simple and correct for the next-bar execution semantics. The position is shifted by 1 bar in `_compute_oos_sharpe()` via `position.shift(1).fillna(0)` to avoid lookahead.

4. **JSON output only, no DB table**: CPCV is a research/evaluation artifact, not a production pipeline. Storing to DB would require a new migration and table design. JSON at a known path is sufficient for analysis workflows.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] tz-aware Series .values strips timezone — intersection returned empty**

- **Found during:** Task 1 (first test run)
- **Issue:** `_load_t1_series()` used `pd.DatetimeIndex(labels_df['t0'].values)` which stripped the UTC timezone from the tz-aware `t0` Series (the MEMORY.md pitfall). This caused `features_df.index.intersection(t1_series.index)` to return empty (tz-aware vs. tz-naive datetime comparison always yields empty intersection).
- **Fix:** Changed `.values` -> `.tolist()` for both t0 and t1 when constructing the `t1_series` (both the index and values). `.tolist()` returns tz-aware `pd.Timestamp` objects that preserve UTC. Added inline comment referencing the MEMORY.md pitfall.
- **Files modified:** `src/ta_lab2/scripts/labeling/run_cpcv_backtest.py`
- **Verification:** `features_df.index.intersection(t1_series.index)` returned 5612 rows after fix; CPCV produced 15 splits as expected.
- **Committed in:** `24d25074` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Critical fix — without it, no splits would be produced. Single-line change (`.values` -> `.tolist()`), no scope change.

## Issues Encountered

- Pre-commit hooks (ruff-lint, ruff-format, mixed-line-ending) reformatted on first commit attempt. Required re-staging and committing twice — standard Windows CRLF->LF workflow.

## User Setup Required

None - no external service configuration required. Script reads from existing PostgreSQL tables and writes JSON to `.planning/` directory.

## Next Phase Readiness

- CPCV Sharpe distribution runner complete and verified for BTC 1D ema_crossover
- `run_cpcv_backtest.py --ids {id} --tf 1D --signal-type {type}` is the command for downstream PBO (Probability of Backtest Overfitting) analysis
- JSON results in `.planning/phases/57-advanced-labeling-cv/cpcv_results_{id}_{signal}.json` for any post-processing
- Phase 57 complete (all 6 plans done): triple barrier labeling, CUSUM filter, batch ETL, signal integration, CPCV distribution
- No blockers for Phase 58 or v1.0.0 milestone

---
*Phase: 57-advanced-labeling-cv*
*Completed: 2026-02-28*
