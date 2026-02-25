---
phase: 45-paper-trade-executor
plan: "03"
subsystem: executor
tags: [python, sqlalchemy, decimal, unittest-mock, signal-processing, position-sizing]

# Dependency graph
requires:
  - phase: 44-order-fill-store
    provides: OrderManager, paper order schema, fill store
  - phase: 43-exchange-integration
    provides: exchange_price_feed table, exchange adapter pattern
  - phase: 35-ama-engine
    provides: cmc_signals_ema_crossover, cmc_signals_rsi_mean_revert, cmc_signals_atr_breakout tables
provides:
  - SignalReader class with watermark-based unprocessed signal queries
  - StaleSignalError exception for stale signal guard
  - SIGNAL_TABLE_MAP registry mapping signal types to table names
  - SQL injection guard via SIGNAL_TABLE_MAP.values() whitelist
  - PositionSizer class with fixed_fraction, regime_adjusted, signal_strength modes
  - ExecutorConfig dataclass mirroring dim_executor_config fields
  - REGIME_MULTIPLIERS dict (bull_low_vol=1.0 down to bear_high_vol=0.0)
  - compute_order_delta signed delta for rebalance-to-target execution
  - get_portfolio_value DB helper with initial_capital fallback
  - get_current_price DB helper (exchange_price_feed -> bar_close fallback chain)
affects:
  - 45-04 (executor runner will import SignalReader + PositionSizer)
  - any future signal processing or position management components

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Whitelist table name validation to prevent SQL injection in dynamic table queries
    - Decimal arithmetic for all position sizing to avoid float rounding errors
    - First-run bypass pattern: skip stale guard when watermark is None
    - Pure function get_latest_signal_per_asset for testable signal grouping
    - DB helper with two-source fallback chain (live feed -> bar close)
    - Module-level convenience wrappers delegating to static class methods

key-files:
  created:
    - src/ta_lab2/executor/signal_reader.py
    - src/ta_lab2/executor/position_sizer.py
    - tests/executor/test_signal_reader.py
    - tests/executor/test_position_sizer.py
  modified:
    - src/ta_lab2/executor/__init__.py

key-decisions:
  - "SQL injection guard: validate signal_table against SIGNAL_TABLE_MAP.values() frozenset before any interpolation"
  - "First-run bypass for stale check: last_watermark_ts=None skips freshness query entirely"
  - "Decimal arithmetic throughout PositionSizer to prevent float accumulation errors"
  - "Unknown regime label defaults to multiplier 1.0 (conservative, matches fixed_fraction behavior)"
  - "signal_strength minimum floor at 10% to prevent near-zero position sizes"
  - "get_current_price falls back to 1D bar close when exchange_price_feed is stale (>24h) or missing"

patterns-established:
  - "Whitelist validation pattern: validate string against frozenset before using in SQL"
  - "Decimal sizing pattern: Decimal(str(float_value)) to avoid float->Decimal precision loss"
  - "Two-source price fallback: try live feed, fall back to last bar close on staleness or error"

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 45 Plan 03: SignalReader and PositionSizer Summary

**Watermark-based signal deduplication (executor_processed_at IS NULL) and 3-mode position sizing (fixed_fraction/regime_adjusted/signal_strength) with Decimal arithmetic and SQL injection guard, 28 unit tests all pass without DB**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-25T05:07:59Z
- **Completed:** 2026-02-25T05:13:10Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- SignalReader prevents duplicate and stale signal processing via watermark + executor_processed_at IS NULL filter, with first-run bypass when watermark is None
- PositionSizer converts signals to target quantities via 3 configurable sizing modes; all arithmetic in Decimal for precision; regime multiplier table covers 5 regimes from bull_low_vol (1.0x) to bear_high_vol (0.0x)
- 28 unit tests (9 SignalReader + 15 PositionSizer + 4 bonus) all pass without a live database, using mock connections and pure function calls
- SQL injection guard implemented as frozenset whitelist check on all methods that interpolate table names

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement SignalReader and PositionSizer** - `f1519b02` (included in docs 45-02 commit alongside the source files)
2. **Task 2: Create unit tests for SignalReader and PositionSizer** - `1f96f827` (test)

## Files Created/Modified

- `src/ta_lab2/executor/__init__.py` - Package init for executor module
- `src/ta_lab2/executor/signal_reader.py` - SignalReader with watermark queries, stale guard, and SQL injection protection
- `src/ta_lab2/executor/position_sizer.py` - PositionSizer with 3 sizing modes, ExecutorConfig dataclass, REGIME_MULTIPLIERS, price/portfolio DB helpers
- `tests/executor/test_signal_reader.py` - 9 unit tests (283 lines), all mock-based
- `tests/executor/test_position_sizer.py` - 19 unit tests (413 lines), pure arithmetic with Decimal

## Decisions Made

- **SQL injection guard via frozenset whitelist**: All methods accepting `signal_table` validate it against `_VALID_SIGNAL_TABLES = frozenset(SIGNAL_TABLE_MAP.values())` before any f-string interpolation. Raises ValueError on invalid input.
- **First-run stale bypass**: `last_watermark_ts=None` causes `check_signal_freshness` to return silently with no DB query — prevents false StaleSignalError on initial executor startup.
- **Decimal arithmetic**: All sizing arithmetic uses `Decimal(str(float_value))` pattern to prevent float precision accumulation. Config fields (position_fraction, max_position_fraction) are stored as float but converted via `str()` before Decimal construction.
- **Unknown regime defaults to 1.0**: `REGIME_MULTIPLIERS.get(regime_label or "", Decimal("1.0"))` — unknown labels produce the same sizing as fixed_fraction, which is conservative.
- **signal_strength minimum floor**: `max(Decimal(str(signal_confidence)), Decimal("0.10"))` prevents signals with near-zero confidence from producing negligible but non-zero positions.
- **get_current_price fallback chain**: exchange_price_feed first (< 24h old); falls back to cmc_price_bars_multi_tf 1D bar close on staleness or table-not-found; raises ValueError when neither source has a price.

## Deviations from Plan

None - plan executed exactly as written. All 9 SignalReader tests and 15 PositionSizer tests implemented. Three bonus tests (module-level wrapper delegates + REGIME_MULTIPLIERS key/type sanity) added beyond the 15 required, bringing total to 28.

## Issues Encountered

Pre-commit hooks (ruff + mixed-line-ending) auto-fixed import ordering and CRLF line endings in test files on Windows. Re-staged after fixes. No logic changes required.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SignalReader and PositionSizer are ready for import by the executor runner (45-04)
- The executor runner will: load ExecutorConfig from dim_executor_config, call SignalReader.read_unprocessed_signals, call PositionSizer.compute_target_position per asset, and submit orders via OrderManager
- No blockers for 45-04

---
*Phase: 45-paper-trade-executor*
*Completed: 2026-02-25*
