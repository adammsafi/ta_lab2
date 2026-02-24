---
phase: 36-psr-purged-k-fold
plan: 04
subsystem: backtests
tags: [psr, probabilistic-sharpe-ratio, backtest, vectorbt, scipy, sqlalchemy, trade-reconstruction]

# Dependency graph
requires:
  - phase: 36-01
    provides: psr_results table DDL and cmc_backtest_metrics.psr column (Alembic migrations adf582a23467 + 5f8223cfbf06)
  - phase: 36-02
    provides: compute_psr, min_trl, compute_dsr formulas in src/ta_lab2/backtests/psr.py
provides:
  - PSR auto-computed and persisted on every new backtest (cmc_backtest_metrics.psr + psr_results table)
  - Standalone compute_psr.py CLI for recomputing PSR on any historical run using trade-reconstructed returns
  - return_source column distinguishes 'portfolio' (auto-compute) from 'trade_reconstruction' (CLI)
affects:
  - future phases querying psr_results for strategy selection
  - Phase 37+ DSR CLI (multi-trial deflated Sharpe computation)
  - any tooling that reads cmc_backtest_metrics.psr

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_psr_* key prefix pattern: detail stats stuffed into metrics dict then stripped before SQL INSERT"
    - "trade reconstruction return approximation: pnl_pct / n_holding_bars evenly distributed across holding bars"
    - "return_source column distinguishes computation paths (portfolio vs trade_reconstruction)"

key-files:
  created:
    - src/ta_lab2/scripts/backtests/compute_psr.py
  modified:
    - src/ta_lab2/scripts/backtests/backtest_from_signals.py

key-decisions:
  - "Use _psr_* prefix pattern to pass PSR detail stats through the metrics dict without polluting cmc_backtest_metrics schema"
  - "return_source='portfolio' for online computation (pf.returns()), 'trade_reconstruction' for CLI (pnl_pct/n_bars approximation)"
  - "DSR CLI deferred to Phase 37+ - compute_dsr() library function satisfies formula requirements, but CLI needs multi-run returns simultaneously"
  - "sr_star=0.0 hardcoded for auto-compute path; CLI exposes --sr-star flag with per-bar conversion via /sqrt(365)"

patterns-established:
  - "PSR auto-compute pattern: compute in _compute_comprehensive_metrics, strip _psr_* before metrics INSERT, write psr_results inside same transaction"
  - "CLI pattern for historical recompute: argparse + NullPool + resolve_db_url() + ON CONFLICT DO UPDATE"

# Metrics
duration: 5min
completed: 2026-02-24
---

# Phase 36 Plan 04: PSR Integration Summary

**PSR auto-computed on every new backtest via pf.returns() and written to cmc_backtest_metrics.psr + psr_results; CLI recomputes historical runs using trade-reconstructed returns (pnl_pct/n_bars), distinguished by return_source column**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-24T00:11:36Z
- **Completed:** 2026-02-24T00:16:20Z
- **Tasks:** 2
- **Files modified:** 2 (1 modified, 1 created)

## Accomplishments

- Wired `compute_psr` + `min_trl` into `_compute_comprehensive_metrics`, adding PSR and distributional stats to the backtest pipeline
- Modified `save_backtest_results` to include `psr` in the cmc_backtest_metrics INSERT and write a full psr_results row with `return_source='portfolio'`
- Created 416-line `compute_psr.py` CLI with `--run-id`, `--all`, `--recompute`, `--sr-star`, `--dry-run`, `--verbose` flags using trade-reconstructed bar returns
- E2E verified: ema_crossover backtest for asset 1 produced `psr=0.987` (n_obs=364) in psr_results; CLI wrote `psr=1.000` (n_obs=5538) with `return_source=trade_reconstruction` for an older run

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire PSR into backtest_from_signals.py** - `fbb6456d` (feat)
2. **Task 2: Create standalone compute_psr.py CLI** - `06e67915` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/backtests/backtest_from_signals.py` - Added PSR imports (compute_psr, min_trl, skew, kurtosis, math); PSR computation in _compute_comprehensive_metrics; _psr_* stripping + psr_results INSERT in save_backtest_results
- `src/ta_lab2/scripts/backtests/compute_psr.py` - New standalone CLI: trade-reconstruction returns, argparse, NullPool, writes psr_results + cmc_backtest_metrics.psr

## Decisions Made

- Used `_psr_*` prefix pattern to piggyback distributional stats through the `metrics` dict without adding new method parameters - keeps `_compute_comprehensive_metrics` self-contained
- `return_source='portfolio'` for auto-compute (exact pf.returns() with fees), `'trade_reconstruction'` for CLI (pnl_pct/n_bars approximation) - column makes the difference explicit and queryable
- Annualised `sr_star` converted to per-bar inside the CLI via `/math.sqrt(365)` - user-facing interface stays in annualised units
- DSR CLI deferred to Phase 37+: `compute_dsr()` in psr.py already satisfies the formula requirement; CLI extension requires multiple runs' returns simultaneously

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - pre-commit hooks (ruff lint/format, mixed-line-ending) auto-fixed formatting on both files before final commits. No logic changes required.

## User Setup Required

None - no external service configuration required. Both scripts connect to existing PostgreSQL database using `TARGET_DB_URL` environment variable.

## Next Phase Readiness

- PSR integration complete. Plans 36-01 through 36-05 are done.
- psr_results table populated via both compute paths (portfolio + trade_reconstruction)
- Ready for Plan 36-06: CV-backed backtest runner (uses PurgedKFoldSplitter from 36-03 + PSR from 36-02/04)
- Future: DSR CLI (Phase 37+) will query psr_results to collect SR estimates across runs for deflation

---
*Phase: 36-psr-purged-k-fold*
*Completed: 2026-02-24*
