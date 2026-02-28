---
phase: 56-factor-analytics-reporting
plan: 05
subsystem: analysis
tags: [monte-carlo, mae, mfe, bootstrap, sharpe, backtest, trade-analytics]

# Dependency graph
requires:
  - phase: 56-01
    provides: "mae/mfe columns on cmc_backtest_trades, MC Sharpe CI columns on cmc_backtest_metrics (schema)"
provides:
  - "mae_mfe.py: compute_mae_mfe() and _load_close_prices() for per-trade MAE/MFE computation"
  - "monte_carlo.py: monte_carlo_trades() and monte_carlo_returns() for 95% bootstrap Sharpe CI"
affects:
  - 56-06-analytics-cli
  - 56-07-reporting-notebook

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bootstrap with replacement via numpy.random.default_rng(seed) for reproducibility"
    - "MAE/MFE via close_series.loc[entry_ts_naive:exit_ts_naive] window slicing"
    - "tz-naive timestamp normalization pattern: _to_naive_timestamp() before .loc[] slicing"
    - "_load_close_prices: tf parameter in SQL WHERE clause (not hardcoded)"

key-files:
  created:
    - src/ta_lab2/analysis/mae_mfe.py
    - src/ta_lab2/analysis/monte_carlo.py
  modified: []

key-decisions:
  - "MAE/MFE expressed as decimal fractions of entry_price (not percentage points) for direct portfolio math"
  - "monte_carlo_trades min=10 trades guard; monte_carlo_returns min=30 observations guard"
  - "Annualization constant sqrt(365) for calendar-day Sharpe (consistent with rest of codebase)"
  - "_to_naive_timestamp() helper isolates tz normalization logic; close_series stays tz-naive"
  - "Zero-std bootstrap samples skipped silently; mc_n_samples reflects valid count not requested count"

patterns-established:
  - "Bootstrap Sharpe: rng.choice(values, size=n_trades, replace=True) -> mean/std(ddof=1)*sqrt(365)"
  - "Open trade guard: pd.isnull(exit_ts) -> mae=None, mfe=None (not 0.0)"
  - "DB load helper: tf parameter always used in SQL (never hardcoded) for multi-TF compatibility"

# Metrics
duration: 8min
completed: 2026-02-28
---

# Phase 56 Plan 05: MAE/MFE and Monte Carlo Sharpe CI Modules Summary

**Bootstrap Sharpe 95% CI via trade PnL resampling (monte_carlo.py) and MAE/MFE per-trade window slicing with tf-parameterized close price loader (mae_mfe.py)**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-28T06:33:41Z
- **Completed:** 2026-02-28T06:41:30Z
- **Tasks:** 2
- **Files modified:** 2 (created)

## Accomplishments

- `compute_mae_mfe()`: iterates over trades, slices tz-naive close window `entry_ts:exit_ts`, computes directional MAE/MFE as decimal fractions; open trades (NaT exit_ts) receive None
- `_load_close_prices()`: queries `cmc_features` with `tf` in SQL WHERE clause (not hardcoded); normalizes timestamps to tz-naive via `pd.to_datetime(utc=True).dt.tz_localize(None)`
- `monte_carlo_trades()`: guards on fewer than 10 trades returning None CI; converts pnl_pct % to decimal, bootstraps via `rng.choice(..., replace=True)`, returns dict with mc_sharpe_lo/hi/median
- `monte_carlo_returns()`: same bootstrap logic on daily returns Series with 30-observation guard
- Pre-commit hooks (ruff unused-import removal + mixed-line-ending fix) handled across two re-stage cycles

## Task Commits

Each task was committed atomically:

1. **Task 1: Create mae_mfe.py module** - `1d8cfb06` (feat)
2. **Task 2: Create monte_carlo.py module** - `8773c734` (feat)

## Files Created/Modified

- `src/ta_lab2/analysis/mae_mfe.py` (264 lines) - compute_mae_mfe() + _load_close_prices(engine, asset_id, start_ts, end_ts, tf='1D')
- `src/ta_lab2/analysis/monte_carlo.py` (281 lines) - monte_carlo_trades() + monte_carlo_returns() + _bootstrap_sharpe() + _none_result()

## Decisions Made

- MAE/MFE returned as decimal fractions (e.g. -0.10 for -10%), not percentage points — consistent with how forward returns are expressed throughout the codebase
- `_to_naive_timestamp()` helper added to isolate tz normalization; avoids TypeError when slicing tz-naive `close_series` with tz-aware entry/exit timestamps
- `monte_carlo_trades` pnl_pct divided by 100 internally; callers pass percentage (matching cmc_backtest_trades column convention)
- Zero-std bootstrap samples silently skipped; `mc_n_samples` in result reflects valid sample count, not the requested `n_samples` — more honest for downstream consumption
- Short direction MAE formula: `entry/max(window)-1` (negative when price goes up); MFE: `entry/min(window)-1` (positive when price goes down)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hook (mixed-line-ending) required two re-stage cycles on both files (Windows CRLF -> LF normalization). Standard workflow: hook fixes file, re-stage, recommit.
- Ruff removed unused `Optional` import from monte_carlo.py during first commit attempt; re-staged and committed cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `compute_mae_mfe()` and `monte_carlo_trades()` ready for consumption by the analytics CLI (56-06) and reporting notebook (56-07)
- `_load_close_prices()` can be called directly from CLI scripts with engine from db_config.env
- Both modules follow existing analysis package conventions (logging, type hints, docstrings)

---
*Phase: 56-factor-analytics-reporting*
*Completed: 2026-02-28*
