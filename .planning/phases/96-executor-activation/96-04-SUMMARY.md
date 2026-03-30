---
phase: 96-executor-activation
plan: 04
subsystem: executor
tags: [parity, pnl-attribution, sharpe, beta-alpha, monitoring, paper-trading, sqlalchemy]

# Dependency graph
requires:
  - phase: 96-01
    provides: "strategy_parity and pnl_attribution table DDL (Alembic migration)"
  - phase: 96-03
    provides: "dim_executor_config rows with signal_id linkage and config_name conventions"
  - phase: 82
    provides: "strategy_bakeoff_results table with sharpe_mean per strategy_name"
provides:
  - "run_parity_report.py CLI: fill-to-fill and MTM Sharpe vs bakeoff Sharpe per strategy"
  - "run_pnl_attribution.py CLI: per-asset-class beta-adjusted alpha decomposition"
  - "Both CLIs write to DB tables (strategy_parity, pnl_attribution) with dry-run support"
affects:
  - "96 success criteria 5 (parity tracking) and 6 (PnL attribution) are now satisfied"
  - "Phase 97 (FRED macro) may extend attribution to equity asset class"
  - "Dashboard phases may consume strategy_parity and pnl_attribution tables"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AVG(sharpe_mean) cross-asset aggregate from strategy_bakeoff_results (not per-asset noise)"
    - "regex strip _paper_v\\d+ from config_name to resolve strategy_name for bakeoff lookup"
    - "numpy cov[0,1]/var for OLS beta (2 lines, no hand-rolled regression)"
    - "NamedTuple for typed attribution results with _replace for immutable mutation"
    - "Date-aligned return series (inner join on common dates before beta computation)"

key-files:
  created:
    - src/ta_lab2/scripts/executor/run_parity_report.py
    - src/ta_lab2/scripts/executor/run_pnl_attribution.py
  modified: []

key-decisions:
  - "AVG(sharpe_mean) across all assets for cross-validated BT Sharpe reference (not per-asset rows which are noisy)"
  - "orders.signal_id (not strategy_id, which does not exist) is the join key to fills"
  - "BTC (asset_id=1) as benchmark for all current asset classes; extensible for Phase 97 SPX"
  - "Fill-to-fill round-trips use FIFO buy->sell pairing per asset_id"
  - "MTM Sharpe requires minimum 5 days; fill Sharpe requires minimum 2 round-trips"

patterns-established:
  - "Parity pattern: live_sharpe / bt_sharpe ratio with CPCV->PKF fallback"
  - "Attribution pattern: portfolio_ret - beta * benchmark_ret = alpha_daily per day"
  - "Asset classification: hl_assets.asset_type='perp' -> perp class; else -> crypto"
  - "No-data graceful exit: print informative message, skip INSERT, return 0"

# Metrics
duration: 7min
completed: 2026-03-30
---

# Phase 96 Plan 04: Parity Report and PnL Attribution CLIs Summary

**Strategy parity CLI (live vs bakeoff Sharpe ratio) and PnL attribution CLI (per-asset-class beta-adjusted alpha) with DB persistence, dry-run support, and graceful empty-fills handling**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-30T22:36:00Z
- **Completed:** 2026-03-30T22:43:36Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `run_parity_report.py`: computes fill-to-fill Sharpe and MTM daily Sharpe per strategy using the correct `orders.signal_id` join path, compares against `AVG(strategy_bakeoff_results.sharpe_mean)` cross-validated bakeoff reference by `strategy_name` (extracted via `_paper_v\d+` regex strip), writes to `strategy_parity` table
- Created `run_pnl_attribution.py`: classifies positions by asset class (perp vs crypto via hl_assets lookup), computes OLS beta using `numpy.cov/var`, decomposes PnL into alpha/beta per class (crypto, perp, all), writes to `pnl_attribution` table
- Both CLIs handle empty fills gracefully (no crash on first run before burn-in), support `--dry-run`, ASCII-only output, and `NullPool` engine per project convention

## Task Commits

Each task was committed atomically:

1. **Task 1: Create strategy parity report CLI** - `a3ef5340` (feat)
2. **Task 2: Create PnL attribution report CLI** - `a5bb35a5` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `src/ta_lab2/scripts/executor/run_parity_report.py` - Strategy parity CLI: fill-to-fill + MTM Sharpe vs bakeoff, writes to strategy_parity
- `src/ta_lab2/scripts/executor/run_pnl_attribution.py` - PnL attribution CLI: per-class beta-adjusted alpha, writes to pnl_attribution

## Decisions Made

- **Cross-asset aggregate BT Sharpe via AVG(sharpe_mean):** The bakeoff stores per-asset rows; using AVG across all assets for a given strategy_name gives the correct multi-asset reference rather than cherry-picking one asset's result.
- **orders.signal_id join path:** The orders table has no `strategy_id` column — `signal_id` (from `dim_executor_config.signal_id`) is the correct join key to filter fills per strategy.
- **BTC as universal benchmark for Phase 96:** All current asset classes (crypto spot + HL perps) are crypto-correlated; extending to SPX for equity class is Phase 97 scope.
- **FIFO buy->sell round-trip matching:** Simple and correct for swing trading; adequate for Phase 96 burn-in; can be upgraded to full lot-tracking later.
- **Minimum sample thresholds:** Fill Sharpe requires >= 2 round-trips; MTM Sharpe requires >= 5 days. Below threshold: returns NULL (not zero) to distinguish "no data" from "computed zero."

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - both scripts imported cleanly and passed ruff on first check (after removing unused `Optional` import in parity report). Pre-commit ruff-format reformatted both files on first commit attempt; re-staged and committed successfully.

## User Setup Required

None - no external service configuration required. Both CLIs read from existing DB tables (dim_executor_config, fills, orders, price_bars_multi_tf_u, strategy_bakeoff_results) and write to tables created in Plan 01 migration.

## Next Phase Readiness

- Phase 96 success criteria 5 (strategy_parity populated) and 6 (pnl_attribution populated) are now achievable once executor runs and fills accumulate
- Phase 97 (FRED macro) can extend `_BENCHMARK_MAP` and `_BENCHMARK_ASSET_ID` in run_pnl_attribution.py to add SPX/NASDAQ as equity benchmarks
- Both CLIs are runnable immediately: before burn-in they will print "No fills in window" and exit cleanly

---
*Phase: 96-executor-activation*
*Completed: 2026-03-30*
