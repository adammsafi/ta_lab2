---
phase: 08-ta_lab2-signals
plan: 05
subsystem: backtesting
tags: [vectorbt, backtesting, signals, database, vbt, metrics, sharpe, sortino, calmar]

# Dependency graph
requires:
  - phase: 08-02
    provides: EMA crossover signal generation in cmc_signals_ema_crossover
  - phase: 08-03
    provides: RSI mean revert signal generation in cmc_signals_rsi_mean_revert
  - phase: 08-04
    provides: ATR breakout signal generation in cmc_signals_atr_breakout
  - phase: 07-06
    provides: cmc_daily_features table for price data

provides:
  - SignalBacktester class reading signals from database and executing vectorbt backtests
  - Backtest result storage in cmc_backtest_runs, cmc_backtest_trades, cmc_backtest_metrics
  - CLI for running backtests with clean/realistic PnL modes
  - Comprehensive metrics extraction (Sharpe, Sortino, Calmar, VaR, profit factor, etc.)
  - Reproducibility via feature/params hashing

affects: [08-06, backtesting, performance-analysis, strategy-optimization]

# Tech tracking
tech-stack:
  added: []  # Reused existing vectorbt infrastructure
  patterns:
    - "Backtest from stored signals pattern (not on-the-fly generation)"
    - "Clean vs realistic PnL modes for theoretical vs practical analysis"
    - "Atomic transactions for multi-table result storage"
    - "Comprehensive metric extraction from vectorbt Portfolio"
    - "Reproducibility via feature/params hashing"

key-files:
  created:
    - sql/backtests/070_cmc_backtest_runs.sql
    - sql/backtests/071_cmc_backtest_trades.sql
    - sql/backtests/072_cmc_backtest_metrics.sql
    - src/ta_lab2/scripts/backtests/__init__.py
    - src/ta_lab2/scripts/backtests/backtest_from_signals.py
    - src/ta_lab2/scripts/backtests/run_backtest_signals.py
    - tests/backtests/test_backtest_from_signals.py
  modified: []

key-decisions:
  - "Backtest reads from signal tables (not on-the-fly generation) for reproducibility"
  - "Clean mode uses zero cost model for theoretical PnL comparison"
  - "Atomic transaction for runs/trades/metrics ensures consistency"
  - "Comprehensive metrics (15 fields) including Sharpe, Sortino, Calmar, VaR, CVaR, profit factor"
  - "Feature/params hashing enables cache validation and reproducibility checks"

patterns-established:
  - "SignalBacktester pattern: load_signals -> load_prices -> run_vbt -> extract_metrics -> save_results"
  - "Boolean Series conversion for vectorbt compatibility (entries/exits)"
  - "Timezone-aware timestamp handling with conditional localization"
  - "CLI with separate cost model flags (--clean-pnl, --fee-bps, --slippage-bps)"

# Metrics
duration: 11min
completed: 2026-01-30
---

# Phase 08 Plan 05: Backtest Execution Summary

**Vectorbt backtest integration reading signals from database with clean/realistic PnL modes, comprehensive metrics (Sharpe/Sortino/Calmar/VaR), and atomic result storage**

## Performance

- **Duration:** 11 min
- **Started:** 2026-01-30T20:09:06Z
- **Completed:** 2026-01-30T20:20:12Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- SignalBacktester class integrates with existing vbt_runner.py and costs.py infrastructure
- Backtest results stored in three tables (runs, trades, metrics) with foreign key constraints
- Clean mode (no costs) vs realistic mode (with fees/slippage) for theoretical vs practical analysis
- 15 comprehensive metrics extracted from vectorbt Portfolio (Sharpe, Sortino, Calmar, VaR, CVaR, profit factor, win rate, etc.)
- CLI with configurable cost model and JSON export
- 11 unit tests all passing (using mocks, no database required)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create backtest result DDLs** - `a2ba207` (feat)
   - cmc_backtest_runs: run metadata with versioning and summary metrics
   - cmc_backtest_trades: individual trade records with PnL and costs
   - cmc_backtest_metrics: comprehensive performance metrics

2. **Task 2: Create SignalBacktester class** - `448bae6` (feat)
   - load_signals_as_series: converts DB signals to entry/exit boolean Series
   - run_backtest: executes backtest via vbt_runner with clean/realistic modes
   - _compute_comprehensive_metrics: extracts all 15 metrics
   - save_backtest_results: atomic transaction with conflict handling
   - Feature/params hashing for reproducibility

3. **Task 3: Create CLI script and tests** - `a42c7b3` (feat)
   - run_backtest_signals.py: CLI with comprehensive argument parsing
   - 11 tests covering dataclass, signal loading, cost modes, metrics, database operations
   - Bug fixes for timezone-aware timestamp handling

## Files Created/Modified

**DDL files (sql/backtests/):**
- `070_cmc_backtest_runs.sql` - Backtest run metadata with versioning and summary metrics
- `071_cmc_backtest_trades.sql` - Individual trade records with PnL and costs
- `072_cmc_backtest_metrics.sql` - Comprehensive performance metrics (15 fields)

**Python modules (src/ta_lab2/scripts/backtests/):**
- `__init__.py` - Exports SignalBacktester, BacktestResult
- `backtest_from_signals.py` - SignalBacktester class with 644 lines of backtest logic
- `run_backtest_signals.py` - CLI with cost model configuration, JSON export, formatted output

**Tests (tests/backtests/):**
- `test_backtest_from_signals.py` - 11 unit tests (all passing) with mocks

## Decisions Made

**1. Backtest from stored signals (not on-the-fly)**
- Rationale: Reproducibility and auditability - signals frozen in database match backtest execution
- Trade-off: Requires signal generation step first, but ensures backtest matches production signals

**2. Clean vs realistic PnL modes**
- Rationale: Clean mode (no costs) for theoretical analysis, realistic mode for practical evaluation
- Implementation: `--clean-pnl` flag zeros out cost model, realistic mode uses configurable fees/slippage

**3. Atomic transaction for multi-table storage**
- Rationale: Consistency - runs/trades/metrics must all succeed or all fail
- Implementation: `engine.begin()` context manager with single transaction

**4. Comprehensive metrics extraction**
- Rationale: Enable multi-dimensional strategy evaluation (risk-adjusted returns, trade stats, tail risk)
- Metrics: total_return, CAGR, Sharpe, Sortino, Calmar, max_drawdown, win_rate, profit_factor, VaR, CVaR, etc.

**5. Feature/params hashing for reproducibility**
- Rationale: Detect configuration changes that invalidate backtest comparisons
- Implementation: SHA256 hash (first 16 chars) of signal params from dim_signals

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed timezone-aware timestamp handling in load_signals_as_series**
- **Found during:** Task 3 (Test execution)
- **Issue:** `pd.Timestamp(row[0], tz='UTC')` raises ValueError when row[0] already has tzinfo
- **Fix:** Conditional localization - check if `tz is None` before calling `tz_localize('UTC')`
- **Files modified:** src/ta_lab2/scripts/backtests/backtest_from_signals.py
- **Verification:** Test `test_load_signals_as_series_returns_entries_exits` passes
- **Committed in:** a42c7b3 (Task 3 commit with bug fixes note)

**2. [Rule 1 - Bug] Fixed timezone-aware timestamp handling in save_backtest_results**
- **Found during:** Task 3 (Test execution)
- **Issue:** `dt.tz_localize('UTC')` raises TypeError when timestamps already tz-aware
- **Fix:** Conditional localization - check if `dt.tz is None` before calling `tz_localize`
- **Files modified:** src/ta_lab2/scripts/backtests/backtest_from_signals.py
- **Verification:** Test `test_save_backtest_results_inserts_three_tables` passes
- **Committed in:** a42c7b3 (Task 3 commit with bug fixes note)

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both fixes essential for timezone-aware timestamp handling. No scope creep.

## Issues Encountered

**1. Mock context manager setup in tests**
- Problem: Initial tests used `Mock()` for engine, but context managers require `MagicMock()`
- Solution: Changed `mock_engine = Mock()` to `mock_engine = MagicMock()` for all tests using `engine.connect()` or `engine.begin()`
- Verification: All 11 tests passing

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Phase 08-06:**
- Backtest infrastructure complete and tested
- Signals can be backtested with clean or realistic PnL
- Results stored in database for historical comparison
- CLI ready for production use

**Foundation established:**
- SignalBacktester pattern for reading from signal tables
- Comprehensive metrics extraction from vectorbt Portfolio
- Atomic transaction pattern for multi-table storage
- Reproducibility via feature/params hashing

**No blockers or concerns.**

---
*Phase: 08-ta_lab2-signals*
*Completed: 2026-01-30*
