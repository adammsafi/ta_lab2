---
phase: 56-factor-analytics-reporting
plan: "07"
subsystem: backtests
tags: [quantstats, mae-mfe, monte-carlo, backtest, vectorbt, tearsheets]

# Dependency graph
requires:
  - phase: 56-02
    provides: quantstats_reporter.py (generate_tear_sheet, _load_btc_benchmark_returns)
  - phase: 56-05
    provides: mae_mfe.py (compute_mae_mfe, _load_close_prices) + monte_carlo.py (monte_carlo_trades)

provides:
  - BacktestResult.portfolio_returns and BacktestResult.tf fields
  - save_backtest_results() wired with QuantStats tear sheet (step 5), MAE/MFE (step 6), Monte Carlo (step 7)
  - run_quantstats_report.py CLI for retroactive tear sheet generation
  - run_monte_carlo.py CLI for retroactive Monte Carlo analysis

affects:
  - any consumer of BacktestResult (run_backtest callers gain tf and portfolio_returns)
  - cmc_backtest_runs.tearsheet_path now populated on every run
  - cmc_backtest_trades.mae/mfe now populated on every run with closed trades
  - cmc_backtest_metrics.mc_sharpe_lo/hi/median/n_samples now populated on every run

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Non-fatal analytics: each analytics step in save_backtest_results() wrapped in try/except so backtest save never fails due to tear sheet/MAE/MC errors"
    - "Trade-id matching: MAE/MFE UPDATE uses trade_id PK matched by (entry_ts, entry_price) sort key"
    - "Retroactive CLI pattern: standalone scripts reconstruct equity curve from trade records without re-running the backtest"

key-files:
  created:
    - src/ta_lab2/scripts/analysis/run_quantstats_report.py
    - src/ta_lab2/scripts/analysis/run_monte_carlo.py
  modified:
    - src/ta_lab2/scripts/backtests/backtest_from_signals.py

key-decisions:
  - "Each analytics step (QuantStats, MAE/MFE, Monte Carlo) is wrapped in try/except so a failure in any analytics step does not block the core backtest save"
  - "Empty BTC benchmark returns None (not empty Series) — _load_btc_benchmark_returns already handles this; we pass it through to generate_tear_sheet as-is"
  - "MAE/MFE trade matching uses deterministic sort key (entry_ts, entry_price) on both DB rows and computed DataFrame to align trade_ids with computed values"
  - "_load_close_prices uses result.tf (not hardcoded '1D') so non-daily backtests get correct price granularity"
  - "run_quantstats_report reconstructs equity curve from exit-date realized P&L (no backtest re-run) — simpler and safe for retroactive use"

patterns-established:
  - "Non-fatal analytics wrapper: try/except per analytics step inside the main DB transaction"
  - "Retroactive CLI: load run metadata + trades from DB, reconstruct analytics, optionally --write back"

# Metrics
duration: 4min
completed: 2026-02-28
---

# Phase 56 Plan 07: Analytics Pipeline Integration Summary

**QuantStats tear sheets, MAE/MFE excursions, and Monte Carlo Sharpe CIs wired into save_backtest_results() + two standalone retroactive CLI scripts**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-28T06:43:18Z
- **Completed:** 2026-02-28T06:47:16Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `BacktestResult` extended with `portfolio_returns: Optional[pd.Series]` and `tf: str = "1D"` fields; `run_backtest()` extracts `pf.returns()` and accepts `tf` parameter
- `save_backtest_results()` now runs 3 analytics steps after PSR: QuantStats HTML tear sheet to `reports/tearsheets/{run_id}.html` + `tearsheet_path` UPDATE, MAE/MFE per trade via `_load_close_prices(tf=result.tf)` + UPDATE via `trade_id` PK, Monte Carlo `mc_sharpe_lo/hi/median` UPDATE in `cmc_backtest_metrics`
- `run_quantstats_report.py` CLI generates tear sheet for existing `run_id` from trade records without re-running the backtest
- `run_monte_carlo.py` CLI runs bootstrap Sharpe CI for existing `run_id` with `--n-samples`, `--seed`, and `--write` flags

## Task Commits

Each task was committed atomically:

1. **Task 1: Add portfolio_returns/tf to BacktestResult and wire analytics into save_backtest_results()** - `bc0ba944` (feat)
2. **Task 2: Create standalone CLI scripts** - `4b2aad5a` (feat)

**Plan metadata:** (see docs commit below)

## Files Created/Modified

- `src/ta_lab2/scripts/backtests/backtest_from_signals.py` - Added `portfolio_returns`/`tf` fields; wired QuantStats/MAE-MFE/Monte Carlo into `save_backtest_results()` steps 5-7
- `src/ta_lab2/scripts/analysis/run_quantstats_report.py` - CLI for retroactive tear sheet generation from trade records
- `src/ta_lab2/scripts/analysis/run_monte_carlo.py` - CLI for retroactive Monte Carlo Sharpe CI analysis

## Decisions Made

- Each analytics step wrapped in individual `try/except` — a QuantStats import error or DB timeout never blocks the core backtest save (existing behavior preserved for zero-trade runs)
- Empty BTC benchmark: `_load_btc_benchmark_returns` already returns `None` when no data; we pass `None` directly to `generate_tear_sheet`, which generates a benchmark-free tear sheet
- MAE/MFE uses deterministic sort key `(entry_ts, entry_price, created_at)` in SQL and `(entry_ts, entry_price)` in DataFrame to match `trade_id` PKs without relying on DataFrame index order
- `_load_close_prices` called with `tf=result.tf` not hardcoded `'1D'` — supports future non-daily backtests correctly
- Retroactive CLI reconstructs equity curve from exit-date realized P&L (no `vectorbt` re-run needed) — safe to call on any historical run

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed incorrect DB module path**
- **Found during:** Task 2 (CLI creation)
- **Issue:** Plan sketched `from ta_lab2.db.db_config import get_engine` but that module does not exist in this codebase. Existing scripts use `resolve_db_url()` + `create_engine`.
- **Fix:** Used `from ta_lab2.scripts.refresh_utils import resolve_db_url` + `create_engine(db_url, poolclass=pool.NullPool)` matching established project pattern (same as `run_ic_eval.py`)
- **Files modified:** `run_quantstats_report.py`, `run_monte_carlo.py`
- **Verification:** `python -m ta_lab2.scripts.analysis.run_quantstats_report --help` and `run_monte_carlo --help` both succeed
- **Committed in:** `4b2aad5a` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Fix required to make CLIs importable. No scope change.

## Issues Encountered

None beyond the DB module path fix above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 56 complete: all 7 plans done
- Full analytics pipeline wired: every new `save_backtest_results()` call now generates a tear sheet, computes MAE/MFE per trade, and runs Monte Carlo Sharpe CI
- Retroactive CLIs available for any historical run in `cmc_backtest_runs`
- Concern: `tearsheet_path` column uses relative path (`reports/tearsheets/`); consumers should resolve to absolute path for cross-directory use

---
*Phase: 56-factor-analytics-reporting*
*Completed: 2026-02-28*
