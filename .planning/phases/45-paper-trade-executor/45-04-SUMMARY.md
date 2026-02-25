---
phase: 45-paper-trade-executor
plan: "04"
subsystem: executor
tags: [python, sqlalchemy, paper-trading, order-management, signal-processing, unittest-mock, decimal, position-sizing]

# Dependency graph
requires:
  - phase: 45-01-paper-trade-executor
    provides: cmc_positions PK (asset_id, exchange, strategy_id), dim_executor_config, cmc_executor_run_log
  - phase: 45-02-paper-trade-executor
    provides: FillSimulator, FillSimulatorConfig, FillResult
  - phase: 45-03-paper-trade-executor
    provides: SignalReader, PositionSizer, ExecutorConfig, compute_order_delta
  - phase: 44-order-fill-store
    provides: OrderManager (process_fill, promote_paper_order, update_order_status)
  - phase: 43-exchange-integration
    provides: CanonicalOrder (mutable dataclass with signal_id), PaperOrderLogger
provides:
  - FillData.strategy_id field (default 0, backward compat) for multi-strategy position isolation
  - OrderManager._do_process_fill position lock and upsert updated to (asset_id, exchange, strategy_id)
  - PaperExecutor class: complete signal-to-fill orchestrator for all active strategies
  - PaperExecutor.run(): dry_run mode, replay mode, per-strategy error handling
  - _load_active_configs(): queries dim_executor_config WHERE is_active=TRUE
  - _run_strategy(): freshness check -> read signals -> get_latest_per_asset -> process -> watermark update
  - _process_asset_signal(): CanonicalOrder (signal_id set) -> paper_orders -> cmc_orders -> fill -> position
  - _write_run_log(): INSERT cmc_executor_run_log per invocation (never raises)
  - executor __init__.py: exports PaperExecutor + SignalReader + PositionSizer + ExecutorConfig
  - 16 mock-based unit tests covering all execution paths
affects:
  - 45-05 (bootstrap will use PaperExecutor.run() via CLI)
  - any future parity checker or live executor (signal_id on cmc_orders enables traceability)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Two-phase paper fill: paper_orders -> cmc_orders -> FillSimulator -> cmc_fills -> cmc_positions
    - signal_id set on CanonicalOrder before PaperOrderLogger.log_order (propagates to cmc_orders)
    - strategy_id from config.config_id on FillData for multi-strategy position isolation
    - Per-strategy error catching: StaleSignalError + generic Exception both logged, other strategies continue
    - _write_run_log never raises (swallows exceptions) to prevent audit failure cascading
    - _try_telegram_alert never raises (swallows import and send failures)
    - conn.commit() called after watermark update and mark_signals_processed (explicit commit in connect() context)

key-files:
  created:
    - src/ta_lab2/executor/paper_executor.py
    - tests/executor/test_paper_executor.py
  modified:
    - src/ta_lab2/trading/order_manager.py
    - src/ta_lab2/executor/__init__.py

key-decisions:
  - "strategy_id default 0 on FillData preserves backward compat -- all Phase 44 tests pass unchanged"
  - "PaperOrderLogger created per _process_asset_signal call using str(engine.url) -- avoids circular engine sharing"
  - "conn.commit() explicit in _run_strategy connect() context -- engine.connect() does not auto-commit unlike engine.begin()"
  - "Extra config fields (environment, slippage_mode, etc.) attached as _-prefixed attrs on ExecutorConfig -- dataclass is frozen-friendly, avoids subclassing"
  - "abs(delta) < _MIN_ORDER_THRESHOLD=0.00001 skips order -- prevents negligible rebalance trades"
  - "pair derived from signal.get('pair', f'ASSET{asset_id}/USD') -- signals from cmc_signals tables have pair embedded via entry from signal generator"

patterns-established:
  - "Two-phase paper fill pattern: log_order -> promote_paper_order -> update_order_status(submitted) -> simulate_fill -> process_fill"
  - "Mutable container state tracking pattern in tests: state = {'order': []} for closures that need to append"
  - "Per-strategy isolation via strategy_id=config.config_id on both FillData and cmc_positions query"

# Metrics
duration: 8min
completed: 2026-02-25
---

# Phase 45 Plan 04: OrderManager Patch + PaperExecutor Orchestrator Summary

**strategy_id-isolated cmc_positions upsert (ON CONFLICT updated), PaperExecutor signal-to-fill orchestrator with two-phase paper fill pipeline (paper_orders -> cmc_orders -> FillSimulator -> process_fill), and 16 mock-based unit tests -- 150 tests pass (79 executor + 71 trading)**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-25T05:20:05Z
- **Completed:** 2026-02-25T05:28:23Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- OrderManager patched for new cmc_positions PK: FillData gains `strategy_id: int = 0` (backward compat), position lock query and upsert ON CONFLICT both updated to `(asset_id, exchange, strategy_id)` -- all 71 Phase 44 tests pass unchanged
- PaperExecutor implements the complete signal-to-fill pipeline: loads active configs from dim_executor_config, reads unprocessed signals per strategy via SignalReader watermark, computes target vs current position via PositionSizer, generates CanonicalOrder with signal_id set (blocker 2 fix), logs to paper_orders, promotes to cmc_orders, simulates fills, processes with strategy_id (blocker 1 fix), updates watermark, writes run log
- 16 mock-based unit tests verify all execution paths: no-configs, no-signals, stale signal, first-run bypass, buy/sell/close orders, dry-run, two-phase fill order, signal_id propagation, and strategy_id isolation -- all pass without a live database

## Task Commits

1. **Task 1: Patch OrderManager for strategy_id support** - `67dc5fe9` (feat)
2. **Task 2: Implement PaperExecutor class** - `0bf34d86` (feat)
3. **Task 3: Create unit tests for PaperExecutor** - `5f8a8532` (test)

## Files Created/Modified

- `src/ta_lab2/trading/order_manager.py` - Added `strategy_id: int = 0` to FillData; updated _do_process_fill position lock and upsert to use (asset_id, exchange, strategy_id) matching 45-01 migration
- `src/ta_lab2/executor/paper_executor.py` - Full PaperExecutor implementation (373 lines): run loop, config loading, per-strategy execution, _process_asset_signal two-phase pipeline, run log, Telegram alert helper
- `src/ta_lab2/executor/__init__.py` - Extended exports: PaperExecutor, SignalReader, StaleSignalError, PositionSizer, ExecutorConfig, compute_order_delta
- `tests/executor/test_paper_executor.py` - 16 mock-based unit tests (862 lines after ruff formatting)

## Decisions Made

- **strategy_id default 0 on FillData**: Default value means existing callers (Phase 44 tests, legacy code) continue to work without modification. Only PaperExecutor passes non-zero strategy_id values matching config.config_id.

- **PaperOrderLogger created per _process_asset_signal call**: PaperOrderLogger creates its own internal engine via resolve_db_url(). Passing str(engine.url) reuses the same DB connection settings without sharing engine state. Avoids complex engine plumbing while keeping test isolation clean.

- **Explicit conn.commit() in _run_strategy**: engine.connect() does not auto-commit (unlike engine.begin()). After watermark update and mark_signals_processed, explicit conn.commit() is required. This is correct SQLAlchemy behavior for non-transaction contexts.

- **Extra config fields as _-prefixed attrs**: dim_executor_config has slippage_mode, slippage_base_bps, etc. that are not in ExecutorConfig dataclass. Attaching them as _-prefixed attrs on the dataclass instance (post-construction) avoids subclassing or modifying the Phase 45-03 dataclass. getattr() with defaults makes _process_asset_signal resilient when attrs are absent.

- **abs(delta) < _MIN_ORDER_THRESHOLD = 0.00001 skips**: Prevents near-zero rebalance orders. 0.00001 BTC at $100K = $1 minimum notional. Prevents clogging paper_orders with trivially small trades.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_two_phase_fill_order used invalid list.append reassignment**

- **Found during:** Task 3 verification (pytest run)
- **Issue:** CPython 3.12 raises `AttributeError: 'list' object attribute 'append' is read-only` when trying to dynamically assign `call_order.append = lambda ...`. This was an error in the test scaffolding.
- **Fix:** Replaced direct list.append reassignment with a `state = {"order": []}` mutable container dict pattern. Inner functions append to `state["order"]` via closure. Standard Python pattern for shared mutable state in nested functions.
- **Files modified:** tests/executor/test_paper_executor.py
- **Verification:** 16/16 tests pass after fix
- **Committed in:** 5f8a8532 (after ruff auto-fixed imports and line endings)

---

**Total deviations:** 1 auto-fixed (Rule 1 -- test scaffolding bug)
**Impact on plan:** No logic changes required. Test structure corrected only.

## Issues Encountered

Pre-commit hooks (ruff lint + ruff format + mixed-line-ending) auto-fixed import ordering and CRLF line endings in both paper_executor.py and test_paper_executor.py on Windows (same pattern as Plans 45-02/45-03). Re-staged files after each hook run. No logic changes required by hooks.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- PaperExecutor is the primary Phase 45 deliverable -- COMPLETE
- 45-05 (Bootstrap CLI) can now:
  - Import PaperExecutor from ta_lab2.executor
  - Call `executor.run(dry_run=True)` for verification
  - Call `executor.run()` for live paper trading
- signal_id flows through paper_orders -> cmc_orders -- enables ParityChecker traceability in Phase 46+
- strategy_id on cmc_positions -- enables per-strategy P&L isolation in Phase 46+
- All 150 tests pass (79 executor + 71 trading)

---
*Phase: 45-paper-trade-executor*
*Completed: 2026-02-25*
