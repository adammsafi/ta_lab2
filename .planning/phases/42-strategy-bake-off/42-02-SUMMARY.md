---
phase: 42-strategy-bake-off
plan: "02"
subsystem: backtests
tags: [walk-forward, purged-kfold, cpcv, psr, dsr, cost-matrix, kraken, vectorbt, bakeoff, oos-metrics]

# Dependency graph
requires:
  - phase: 42-01
    provides: IC sweep baseline for feature selection context
  - phase: 41
    provides: Existing signal generators (ema_trend, rsi_mean_revert, breakout_atr) in ta_lab2.signals
  - phase: 38
    provides: PSR/DSR library (ta_lab2.backtests.psr) + PurgedKFoldSplitter/CPCVSplitter (ta_lab2.backtests.cv)
provides:
  - strategy_bakeoff_results table (alembic migration e74f5622e710)
  - bakeoff_orchestrator.py: BakeoffOrchestrator, BakeoffConfig, StrategyResult, run_purged_kfold_backtest, run_cpcv_backtest
  - run_bakeoff.py CLI with --dry-run, --spot-only, --overwrite, --all-assets flags
  - 480 OOS metric rows in strategy_bakeoff_results (BTC/ETH 1D, 3 strategies, 12 cost scenarios, 2 CV methods)
affects:
  - 42-03 (composite scoring uses OOS metrics from strategy_bakeoff_results)
  - 42-04 (strategy selection uses purged_kfold Sharpe/PSR rankings)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CAST(:param AS jsonb) for JSONB parameters in SQLAlchemy text() queries (avoids :param::jsonb psycopg2 conflict)"
    - "De-annualize Sharpe before compute_dsr: sr_estimates_perbar = sharpe_mean / sqrt(365) -- PSR/DSR formula uses per-bar units"
    - "Deferred perps funding post-hoc: CostModel.to_vbt_kwargs() omits funding; deduct manually from OOS returns"
    - "Walk-forward fixed-parameter eval: signal params chosen once, applied to all folds without re-optimization"

key-files:
  created:
    - alembic/versions/e74f5622e710_add_strategy_bakeoff_results.py
    - src/ta_lab2/backtests/bakeoff_orchestrator.py
    - src/ta_lab2/scripts/backtests/run_bakeoff.py
  modified: []

key-decisions:
  - "Expanding-window re-optimization deliberately deferred: fixed-parameter walk-forward is standard baseline for V1"
  - "12-scenario cost matrix: spot maker (16 bps) + taker (26 bps) x 3 slippage + perps maker (2 bps) + taker (5 bps) + funding (3 bps/day) x 3 slippage"
  - "CAST(:param AS jsonb) pattern for SQLAlchemy+psycopg2: colon in :param conflicts with ::jsonb PostgreSQL cast syntax"
  - "DSR de-annualization: sr_estimates passed to compute_dsr must be per-bar (divide annualized Sharpe by sqrt(365))"
  - "No V1 gate strategies: none of the 3 signal types pass Sharpe >= 1.0 AND MaxDD <= 15% simultaneously on OOS 1D; ensemble/blending needed per CONTEXT.md"

patterns-established:
  - "CAST(:param AS jsonb) instead of :param::jsonb for SQLAlchemy JSONB parameters"
  - "Per-bar SR scaling: always divide annualized Sharpe by sqrt(freq_per_year) before PSR/DSR benchmark"
  - "Walk-forward deduplication: _row_exists() check before recomputing; --overwrite flag for forced refresh"
  - "BakeoffOrchestrator.run() groups results by (asset, tf, cost_scenario, cv_method) for cross-strategy DSR"

# Metrics
duration: 34min
completed: 2026-02-24
---

# Phase 42 Plan 02: Walk-Forward Bake-Off Summary

**Purged K-fold (10-fold, 20-bar embargo) + CPCV (45-combo) walk-forward bake-off across 3 signal types, 12 Kraken cost scenarios, BTC/ETH 1D -- 480 OOS metric rows with PSR/DSR in strategy_bakeoff_results**

## Performance

- **Duration:** 34 min
- **Started:** 2026-02-25T02:01:04Z
- **Completed:** 2026-02-25T02:35:00Z
- **Tasks:** 3/3
- **Files modified:** 3 created + 1 migration

## Accomplishments

- Alembic migration `e74f5622e710` creates `strategy_bakeoff_results` table with UNIQUE constraint on (strategy_name, asset_id, tf, params_json, cost_scenario, cv_method) and index on (strategy_name, asset_id, tf)
- `bakeoff_orchestrator.py` built with: BakeoffConfig, 12-scenario Kraken cost matrix, `run_purged_kfold_backtest` (10-fold), `run_cpcv_backtest` (45-combo PBO), PSR on concatenated OOS returns, cross-strategy DSR, and `BakeoffOrchestrator.run()` with deduplication
- `run_bakeoff.py` CLI with dry-run listing, spot-only flag, overwrite mode, all-assets discovery
- Bake-off executed: 480 rows for BTC/ETH 1D across ema_trend (4 params), rsi_mean_revert (3 params), breakout_atr (3 params) x 12 cost scenarios x 2 CV methods
- V1 gate result: No strategies pass Sharpe >= 1.0 AND MaxDD <= 15% simultaneously on purged_kfold OOS; ensemble/blending step warranted (per CONTEXT.md)

## Task Commits

1. **Task 1+2: Alembic migration + bakeoff_orchestrator scaffolding + orchestrator class** - `4cdef3c9` (feat)
2. **Task 2+3: Walk-forward orchestrator fixes + run_bakeoff CLI + bakeoff execution** - `8f0a8eca` (feat)

## Files Created/Modified

- `alembic/versions/e74f5622e710_add_strategy_bakeoff_results.py` - Migration for strategy_bakeoff_results table
- `src/ta_lab2/backtests/bakeoff_orchestrator.py` - BakeoffOrchestrator, BakeoffConfig, StrategyResult, run_purged_kfold_backtest, run_cpcv_backtest, KRAKEN_COST_MATRIX, build_t1_series, load_strategy_data
- `src/ta_lab2/scripts/backtests/run_bakeoff.py` - CLI entry point: argparse, dry-run, spot-only, overwrite, all-assets

## Decisions Made

1. **CAST(:param AS jsonb) for JSONB columns**: SQLAlchemy's psycopg2 dialect converts `:name` to `%(name)s`, causing a syntax error when `::jsonb` (PostgreSQL cast) follows a named parameter. Fix: use `CAST(:param AS jsonb)` which SQLAlchemy leaves intact and PostgreSQL handles correctly.

2. **DSR de-annualization**: `compute_psr(returns, sr_star)` operates in per-bar units (sr_hat = mean(returns)/std(returns)). The `sr_estimates` passed to `expected_max_sr` must also be per-bar. Our `sharpe_mean` is annualized (multiplied by sqrt(365)). Fix: divide `sharpe_mean / sqrt(365)` before passing to `compute_dsr`. Without this fix, DSR computed ~0.0 for all strategies.

3. **12-scenario cost matrix**: Split spot and perps fees into separate maker/taker tiers to match Kraken's actual fee structure. Spot: maker 16 bps, taker 26 bps. Perps: maker 2 bps, taker 5 bps + funding 3 bps/day (0.01%/8h x 3).

4. **Fixed-parameter walk-forward only**: Expanding-window re-optimization deliberately deferred per plan note. The fixed-parameter baseline provides clean, interpretable OOS metrics for V1 strategy selection.

5. **V1 gate outcome**: Best OOS Sharpe for ema_trend on BTC 1D (purged_kfold) is 1.42 but max drawdown worst case is -70.1%, far exceeding the 15% gate. RSI mean-reversion has low drawdown but Sharpe below 1.0. Consistent with expectation that ensemble/blending needed for V1.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed SQLAlchemy JSONB parameter syntax error**

- **Found during:** Task 2 (first bakeoff run attempt)
- **Issue:** `_persist_results()` used `:params_json::jsonb` which conflicts with psycopg2's named parameter `%(params_json)s` substitution, causing `SyntaxError: syntax error at or near ":"`
- **Fix:** Changed to `CAST(:params_json AS jsonb)` and `CAST(:fold_metrics_json AS jsonb)` throughout the SQL. Also fixed `_row_exists()` which used `params_json::text` comparison (changed to `= CAST(:params_json AS jsonb)`)
- **Files modified:** src/ta_lab2/backtests/bakeoff_orchestrator.py
- **Verification:** Test insert via `engine.begin()` succeeded, then full bakeoff produced 480 rows
- **Committed in:** 8f0a8eca

**2. [Rule 1 - Bug] Fixed DSR returning near-zero for all strategies**

- **Found during:** Task 3 (reviewing bakeoff summary after first full run)
- **Issue:** `compute_dsr()` received annualized Sharpe estimates (e.g., 1.42) as `sr_estimates` but `compute_psr()` internally computes per-bar `sr_hat = mean(oos)/std(oos)` (~0.003). The expected_max_sr benchmark (~0.52) was in annualized units but compared against per-bar Sharpe, yielding DSR ~0 for all strategies.
- **Fix:** De-annualize `sr_estimates` before passing to `compute_dsr`: `sr_estimates_perbar = sharpe_mean / sqrt(365)`
- **Files modified:** src/ta_lab2/backtests/bakeoff_orchestrator.py
- **Verification:** Re-ran with `--overwrite`; DSR for ema_trend/BTC/purged_kfold now 0.995 (correctly high for best strategy), DSR for rsi on BTC 0.000 (correctly low when strategy underperforms benchmark)
- **Committed in:** 8f0a8eca

---

**Total deviations:** 2 auto-fixed (both Rule 1 - Bug)
**Impact on plan:** Both critical: without Fix 1, no results could be persisted. Without Fix 2, DSR metric was meaningless. No scope creep.

## Issues Encountered

- **Pre-commit hook stash on first commit attempt**: ruff found unused variable `dsr_val` and required reformatting. Fixed and recommitted cleanly.

## Next Phase Readiness

- **480 OOS rows ready:** strategy_bakeoff_results populated for BTC/ETH 1D x 3 strategies x 12 cost scenarios x 2 CV methods
- **V1 gate outcome documented:** No single strategy passes Sharpe >= 1.0 + MaxDD <= 15% on purged_kfold OOS. Plan 42-03 composite scoring step needed.
- **Ensemble/blending consideration flagged:** Per 42-CONTEXT.md, if no single strategy hits Sharpe >= 1.0, try ensemble/blending of top signals
- **Expanding-window deferred:** Implementation gap documented with rationale. Would require parameter re-optimization logic in fold loop.
- **No blockers for 42-03:** Composite scoring can proceed directly from strategy_bakeoff_results with the OOS metrics now available.

---
*Phase: 42-strategy-bake-off*
*Completed: 2026-02-24*
