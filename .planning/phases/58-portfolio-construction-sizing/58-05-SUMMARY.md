---
phase: 58-portfolio-construction-sizing
plan: 05
subsystem: portfolio
tags: [portfolio, integration, refresh-script, backtest, daily-pipeline, topk-dropout, sharpe, NullPool]

# Dependency graph
requires:
  - phase: 58-01
    provides: cmc_portfolio_allocations table + configs/portfolio.yaml
  - phase: 58-02
    provides: PortfolioOptimizer (MV/CVaR/HRP)
  - phase: 58-03
    provides: BLAllocationBuilder, BetSizer, probability_bet_size
  - phase: 58-04
    provides: TopkDropoutSelector, TurnoverTracker, RebalanceScheduler, StopLadder

provides:
  - portfolio/__init__.py with all 9 public symbols exported
  - scripts/portfolio/__init__.py package stub
  - scripts/portfolio/refresh_portfolio_allocations.py: full refresh pipeline CLI
  - scripts/portfolio/run_portfolio_backtest.py: 4-strategy Sharpe comparison backtest
  - run_daily_refresh.py --portfolio flag wiring the refresh into the daily pipeline

affects:
  - Daily pipeline: --all now includes portfolio stage (after signals, before executor)
  - Phase 59+ (order generation can consume cmc_portfolio_allocations allocations)
  - Any backtest workflow comparing portfolio construction methods

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "NullPool engine in all batch scripts (refresh + backtest) -- consistent with pipeline"
    - "ON CONFLICT (ts, optimizer, asset_id) DO UPDATE for upsert to cmc_portfolio_allocations"
    - "CAST(:config_snapshot AS jsonb) for JSONB binding via SQLAlchemy text()"
    - "Sharpe delta printed as +X.XXX (+X.X%) comparing topk_dropout vs fixed_sizing"
    - "Pre-commit CRLF->LF hook requires re-stage on Windows (standard Phase 58 pattern)"

key-files:
  created:
    - src/ta_lab2/scripts/portfolio/__init__.py
    - src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py
    - src/ta_lab2/scripts/portfolio/run_portfolio_backtest.py
  modified:
    - src/ta_lab2/portfolio/__init__.py
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "portfolio/__init__.py imports all 9 symbols at module level -- enables star-import and IDE autocomplete"
  - "refresh script uses 'timestamp' column (NOT 'ts') from cmc_price_bars_multi_tf_u -- documented in CRITICAL comment"
  - "BL fallback: when no live signal scores available, use zero IC-IR scores so BL falls back to prior-only EfficientFrontier"
  - "Bet sizing fallback: use 0.6 uniform signal probability (slight edge) when no live probs available"
  - "Backtest per_asset strategy uses momentum (1-period return rank top-10) as stand-in for Phase 42 per-asset champion"
  - "Portfolio stage position in pipeline: after signals, before executor -- optimizer needs latest signals"
  - "--no-portfolio flag added for cases where portfolio stage should be skipped in --all"
  - "run_portfolio_backtest: trim returns to requested date range after loading with lookback buffer"

patterns-established:
  - "Portfolio script pattern: resolve IDs -> load prices (timestamp col) -> adaptive lookback -> filter thin -> run optimizer -> optional BL -> optional sizing -> upsert"
  - "Backtest pattern: load full history with buffer -> rolling window -> strategy fn -> 1-period forward return -> Sharpe"

# Metrics
duration: 5min
completed: 2026-02-28
---

# Phase 58 Plan 05: Portfolio Integration Scripts Summary

**Capstone plan wiring all portfolio components: 9-symbol __init__ exports, refresh_portfolio_allocations.py (MV/CVaR/HRP+BL+sizing pipeline), run_portfolio_backtest.py (4-strategy Sharpe comparison), and --portfolio flag in daily refresh orchestrator**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-28T08:08:00Z
- **Completed:** 2026-02-28T08:13:08Z
- **Tasks:** 2/2
- **Files modified:** 5

## Accomplishments

- `portfolio/__init__.py` now exports all 9 public symbols: PortfolioOptimizer, BLAllocationBuilder,
  BetSizer, probability_bet_size, TopkDropoutSelector, TurnoverTracker, RebalanceScheduler,
  StopLadder, load_portfolio_config -- verified via import check
- `refresh_portfolio_allocations.py`: full CLI refresh pipeline with --ids, --tf, --regime,
  --lookback, --dry-run, --config, --no-bl, --no-sizing; upserts to cmc_portfolio_allocations
  ON CONFLICT (ts, optimizer, asset_id) DO UPDATE; uses NullPool engine
- `run_portfolio_backtest.py`: 4-strategy comparison (topk_dropout, fixed_sizing,
  equal_weight, per_asset); prints Sharpe ratio table with explicit TopkDropout vs Fixed Sizing
  delta line; optional --output CSV export
- `run_daily_refresh.py`: added --portfolio / --no-portfolio flags, TIMEOUT_PORTFOLIO=600,
  run_portfolio_refresh_stage() function, pipeline stage after signals and before executor

## Task Commits

Each task was committed atomically:

1. **Task 1: portfolio __init__ exports + refresh_portfolio_allocations** - `7bee19ca` (feat)
2. **Task 2: portfolio backtest script + daily refresh wiring** - `26958b45` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/portfolio/__init__.py` - Added 8 new imports; expanded __all__ to 9 symbols
- `src/ta_lab2/scripts/portfolio/__init__.py` - New package stub
- `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py` - 307-line refresh CLI
- `src/ta_lab2/scripts/portfolio/run_portfolio_backtest.py` - 418-line backtest CLI
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added portfolio stage (72 lines added)

## Decisions Made

1. **9 symbols in __init__.py**: All module-level imports at bottom of __init__.py
   (after load_portfolio_config definition) to avoid circular import on the lazy `import yaml`
   inside load_portfolio_config.

2. **BL fallback with zero scores**: When no live signal data is available during refresh,
   the BL builder receives zero IC-IR which causes it to fall back to the prior-only
   EfficientFrontier path. This is by design -- BL degrades gracefully to market-cap prior.

3. **Uniform 0.6 probability for bet sizing**: When no live signal probabilities are available,
   a 0.6 confidence (slight edge) is used. At w=2.0, this produces bet_size = 2*N(0.2)-1 ~ 0.16,
   giving roughly 16% of raw optimizer weight. This is intentionally conservative.

4. **per_asset strategy = momentum top-10**: A simplified stand-in for the Phase 42 per-asset
   signal champion. Uses 1-period return rank (highest momentum = highest score).
   Full Phase 42 integration can replace this function in a later phase.

5. **Portfolio stage position**: After signals, before executor. This means the optimizer
   sees the latest signal data. The executor can optionally read from cmc_portfolio_allocations
   in future phases.

6. **--no-portfolio flag**: Added alongside --no-execute and --no-drift for symmetry.
   Allows --all mode to skip portfolio when it is not yet configured or the table does
   not exist on older deployments.

## Deviations from Plan

None - plan executed exactly as written. The BL fallback (zero IC-IR when no live signals)
and bet sizing fallback (0.6 uniform probability) are design choices, not deviations.

## Issues Encountered

- Pre-commit `mixed-line-ending` hook converted CRLF to LF on all new files.
  Required re-staging and second commit attempt (standard Windows workflow, identical to
  all prior Phase 58 plans).

## User Setup Required

None. All scripts are importable and runnable. Portfolio stage is automatically included
in `run_daily_refresh.py --all` from this point forward.

To skip the portfolio stage in --all:
  `python -m ta_lab2.scripts.run_daily_refresh --all --no-portfolio`

To run standalone:
  `python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations --ids all --dry-run`

## Next Phase Readiness

- Phase 58 is COMPLETE (5/5 plans).
- cmc_portfolio_allocations is populated by the daily refresh pipeline.
- TopkDropout vs fixed sizing comparison is runnable via run_portfolio_backtest.py.
- Phase 59+ can read from cmc_portfolio_allocations for order generation.

---
*Phase: 58-portfolio-construction-sizing*
*Completed: 2026-02-28*
