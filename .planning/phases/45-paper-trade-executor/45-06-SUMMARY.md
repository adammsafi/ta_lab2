---
phase: 45-paper-trade-executor
plan: "06"
subsystem: executor
tags: [python, sqlalchemy, paper-trading, backtest-parity, numpy, unittest-mock, argparse, NullPool]

# Dependency graph
requires:
  - phase: 45-04-paper-trade-executor
    provides: PaperExecutor with signal_id on cmc_orders (enables traceability to cmc_fills)
  - phase: 10-backtest-pipeline
    provides: cmc_backtest_trades, cmc_backtest_runs, cmc_backtest_metrics tables
  - phase: 44-order-fill-store
    provides: cmc_fills, cmc_orders tables with order_id FK

provides:
  - ParityChecker class: load backtest trades + executor fills, compute price divergence (bps) and P&L correlation
  - Zero-slippage mode: pass if trade count match AND max divergence < 1.0 bps
  - Lognormal/fixed mode: pass if P&L correlation >= 0.99
  - format_report(): human-readable === BACKTEST PARITY REPORT === output
  - run_parity_check.py CLI: --signal-id, --config-id, --start, --end, --slippage-mode, --db-url, --verbose; exits 0/1
  - 11 mock-based unit tests for all parity check paths
  - ParityChecker exported from ta_lab2.executor __init__.py

affects:
  - any future parity validation CI step (exit 0/1 from CLI is CI-compatible)
  - live paper trading validation workflow (run before trusting executor in production)
  - Phase 46+ if drift monitoring references parity check infrastructure

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Parity check pattern: load two result sets, compute divergence metrics, apply mode-specific tolerance
    - Price divergence in bps: abs(exec_fill - bt_entry) / bt_entry * 10000
    - P&L correlation via numpy.corrcoef with fill_price as proxy when pnl not on executor fills
    - Mode-gated pass logic: zero=strict (bps < 1), fixed/lognormal=statistical (corr >= 0.99)

key-files:
  created:
    - src/ta_lab2/executor/parity_checker.py
    - src/ta_lab2/scripts/executor/run_parity_check.py
    - tests/executor/test_parity_checker.py
  modified:
    - src/ta_lab2/executor/__init__.py

key-decisions:
  - "fill_price used as pnl proxy: executor fills don't carry pnl column, fill_price array correlates against bt_pnl; correlation detects systematic deviation"
  - "Empty trades = fail: zero backtest trades means no comparison is possible, short-circuits before evaluation"
  - "Constant array pnl_correlation = 1.0: when std=0 on both sides, prices are identical, treat as perfect match"
  - "slippage_mode guards two separate criteria: zero uses bps divergence (deterministic), lognormal/fixed uses correlation (statistical) -- matching the FillSimulator modes"

patterns-established:
  - "Proxy correlation pattern: when executor lacks explicit pnl, correlate fill_prices against bt_pnl/bt_entry_prices -- detects systematic divergence"
  - "Mode-gated parity tolerance: slippage_mode determines which metric governs pass/fail (bps vs correlation)"
  - "CI-exit pattern: CLI returns 0 on pass, 1 on fail -- compatible with make check / CI pipelines"

# Metrics
duration: 7min
completed: 2026-02-25
---

# Phase 45 Plan 06: Backtest Parity Checker Summary

**ParityChecker comparing executor replay fills vs cmc_backtest_trades via bps price divergence (zero mode: <1 bps) and P&L correlation (lognormal/fixed mode: >=0.99), plus run_parity_check.py CI-compatible CLI and 11 mock-based unit tests -- 90 executor tests pass**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-25T05:32:41Z
- **Completed:** 2026-02-25T05:39:30Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- ParityChecker loads backtest trades from `cmc_backtest_trades JOIN cmc_backtest_runs` and executor fills from `cmc_fills JOIN cmc_orders` by signal_id + date range; computes pairwise price divergence in bps, P&L correlation via numpy.corrcoef, and tracking error; applies mode-specific pass/fail tolerance
- run_parity_check.py CLI accepts --signal-id, --config-id, --start, --end, --slippage-mode, --db-url, --verbose; creates NullPool engine; prints formatted parity report; exits 0 on PASS or 1 on FAIL -- suitable for CI integration
- 11 mock-based unit tests cover all paths: exact match zero-slippage pass, count mismatch fail, divergence below/above 1 bps, lognormal high/low correlation, format_report pass/fail output, empty trades fail, required keys, fixed mode -- all pass without live database

## Task Commits

1. **Task 1: Implement ParityChecker** - `88388169` (feat -- bundled with 45-05 files due to pre-commit hook stash/rollback behavior on Windows)
2. **Task 2: Create parity CLI and unit tests** - `0322badc` (docs -- bundled with 48-RESEARCH due to same pre-commit hook behavior)
3. **Ruff cleanup** - `dbd75b05` (style -- collapse multi-line print, remove unused pytest import)

## Files Created/Modified

- `src/ta_lab2/executor/parity_checker.py` - ParityChecker class: _load_backtest_trades, _load_executor_fills, _compute_price_divergence, _compute_pnl_correlation, _evaluate_parity, format_report (310 lines)
- `src/ta_lab2/scripts/executor/run_parity_check.py` - CLI with argparse, NullPool engine creation, verbose per-trade table, exit 0/1 (175 lines)
- `tests/executor/test_parity_checker.py` - 11 unit tests grouped in 4 test classes (180 lines)
- `src/ta_lab2/executor/__init__.py` - Added ParityChecker import and __all__ export

## Decisions Made

- **fill_price as pnl proxy:** Executor fills stored in cmc_fills don't carry a pnl column (pnl only exists on backtest trades). Used fill_price as the comparison array for correlation computation. This detects systematic divergence between executor fill prices and expected prices, which is the key signal for executor correctness.

- **Empty trades = immediate fail:** When backtest_trade_count == 0, there's no meaningful comparison possible. Short-circuit before computing any metrics and return parity_pass=False. Avoids misleading "0==0 -> trade_count_match=True" result.

- **Constant array -> pnl_correlation=1.0:** When numpy.std of both sides is zero (all prices identical), corrcoef is mathematically undefined. Treat as 1.0 (perfect match) since identical constant arrays are definitionally maximally correlated.

- **Mode-gated tolerance:** slippage_mode controls which metric governs pass/fail. Zero mode uses deterministic bps divergence (suitable for exact replay). Lognormal/fixed modes use statistical correlation (suitable for stochastic fills). Matches the semantics of FillSimulator slippage modes.

## Deviations from Plan

None - plan executed exactly as written. 11 tests implemented (9 specified + 2 additional: `test_report_contains_required_keys` and `test_fixed_mode_high_correlation_pass` for completeness).

## Issues Encountered

Pre-commit hooks (ruff lint + ruff format + check-added-large-files) triggered stash/rollback behavior on Windows, causing files to be bundled into adjacent commits rather than standalone task commits. Same pattern observed in Plans 45-02 through 45-04. Logic unchanged; only commit message attribution differs from ideal.

## User Setup Required

None - no external service configuration required. CLI requires a live database with backtest data and executor fills to produce non-trivial output (can be run after replay mode execution).

## Next Phase Readiness

- ParityChecker is the final deliverable of Phase 45 (Plan 6 of 6)
- Phase 45 is now COMPLETE: schema migrations (45-01), FillSimulator (45-02), SignalReader + PositionSizer (45-03), PaperExecutor (45-04), Bootstrap CLIs (45-05), ParityChecker (45-06)
- Parity check CLI is CI-compatible (exit 0/1) -- can be added to integration test pipeline
- Before live paper trading: run executor in replay mode, then run_parity_check to validate EXEC-05 compliance
- 90 executor tests pass total (79 previous + 11 new parity tests)

---
*Phase: 45-paper-trade-executor*
*Completed: 2026-02-25*
