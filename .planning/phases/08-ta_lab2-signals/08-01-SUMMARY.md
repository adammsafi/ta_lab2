---
phase: 08-ta_lab2-signals
plan: 01
subsystem: signals
tags: [signals, dim_signals, state-manager, feature-hashing, reproducibility, sqlalchemy]

# Dependency graph
requires:
  - phase: 07-ta_lab2-feature-pipeline
    provides: FeatureStateManager pattern, dim_features/dim_indicators config-driven approach
provides:
  - dim_signals configuration table with JSONB params for database-driven signal strategies
  - Signal table schemas (ema_crossover, rsi_mean_revert, atr_breakout) with position lifecycle tracking
  - SignalStateManager for stateful position tracking (load_open_positions, update_state, dirty_windows)
  - Reproducibility utilities (compute_feature_hash, compute_params_hash) for backtest validation
affects: [08-02, 08-03, 08-04, 08-05, signal-generation, backtest-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Database-driven signal configuration via dim_signals (JSONB params)
    - SignalStateManager for position lifecycle tracking (adapts FeatureStateManager pattern)
    - SHA256 feature hashing for reproducibility validation (first 16 chars)
    - State table schema: (id, signal_type, signal_id) PRIMARY KEY

key-files:
  created:
    - sql/lookups/030_dim_signals.sql
    - sql/signals/063_cmc_signal_state.sql
    - sql/signals/060_cmc_signals_ema_crossover.sql
    - sql/signals/061_cmc_signals_rsi_mean_revert.sql
    - sql/signals/062_cmc_signals_atr_breakout.sql
    - src/ta_lab2/scripts/signals/signal_state_manager.py
    - src/ta_lab2/scripts/signals/signal_utils.py
    - src/ta_lab2/scripts/setup/ensure_dim_signals.py
    - tests/signals/test_signal_state_manager.py
    - tests/signals/test_signal_utils.py
  modified: []

key-decisions:
  - "Required field must precede optional fields in dataclass (signal_type before state_schema)"
  - "Feature hash uses first 16 chars of SHA256 for balance between uniqueness and readability"
  - "Signal tables separate by type (not unified) for type-specific columns without schema bloat"
  - "State manager uses signal table queries (not state table) for load_open_positions to get full context"

patterns-established:
  - "SignalStateConfig dataclass with frozen=True for immutability (follows FeatureStateConfig)"
  - "State manager pattern: ensure_state_table, load_*, update_state_*, get_dirty_window_*"
  - "Feature hashing: Sort by 'ts' before CSV generation for deterministic ordering"
  - "Params hashing: JSON with sorted keys for order-independent hash"
  - "Unit tests with unittest.mock for database-free testing, integration tests with skipif"

# Metrics
duration: 8min
completed: 2026-01-30
---

# Phase 8 Plan 1: Signal Infrastructure Summary

**Signal configuration tables and state management with SHA256 feature hashing for reproducible backtesting**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-30T19:46:08Z
- **Completed:** 2026-01-30T19:54:33Z
- **Tasks:** 4
- **Files modified:** 13

## Accomplishments

- dim_signals configuration table with 6 seed strategies (3 EMA crossover, 2 RSI mean revert, 1 ATR breakout)
- Three signal tables with position lifecycle tracking (entry/exit prices, PnL, feature snapshots, version hashes)
- SignalStateManager for stateful position tracking (open positions, dirty windows, state updates)
- Reproducibility utilities: compute_feature_hash (SHA256 of features), compute_params_hash (SHA256 of params)
- 19 tests passing (8 state manager + 11 utilities, including integration tests)

## Task Commits

Each task was committed atomically:

1. **Task 1a: Create dim_signals and cmc_signal_state tables** - `646a038` (feat)
2. **Task 1b: Create signal tables DDLs** - `e2af7e3` (feat)
3. **Task 2: Create SignalStateManager and signal utilities** - `d4cc8bd` (feat)
4. **Task 3: Create tests for signal infrastructure** - `50e2a7e` (test)

## Files Created/Modified

**DDL files (SQL):**
- `sql/lookups/030_dim_signals.sql` - Signal configuration table with JSONB params, 6 seed strategies
- `sql/signals/063_cmc_signal_state.sql` - Position state tracking (id, signal_type, signal_id) PK
- `sql/signals/060_cmc_signals_ema_crossover.sql` - EMA crossover signals with position lifecycle
- `sql/signals/061_cmc_signals_rsi_mean_revert.sql` - RSI mean reversion with rsi_at_entry/exit
- `sql/signals/062_cmc_signals_atr_breakout.sql` - ATR breakout with breakout_type classification

**Python modules:**
- `src/ta_lab2/scripts/signals/signal_state_manager.py` - SignalStateManager class (250 lines)
- `src/ta_lab2/scripts/signals/signal_utils.py` - Feature/params hashing, load_active_signals (150 lines)
- `src/ta_lab2/scripts/setup/ensure_dim_signals.py` - Idempotent dim_signals setup script
- `src/ta_lab2/scripts/signals/__init__.py` - Module exports

**Tests:**
- `tests/signals/test_signal_state_manager.py` - 8 tests (state table, open positions, upserts, dirty windows)
- `tests/signals/test_signal_utils.py` - 11 tests (feature hash, params hash, load signals)

## Decisions Made

**Dataclass field ordering:**
- Required field `signal_type` must precede optional fields in dataclass
- Python dataclass requirement enforced at class definition time
- Fix: Moved `signal_type: str` to first position before defaults

**Feature hash length:**
- Use first 16 characters of SHA256 hash (128 bits)
- Balance between uniqueness (1 in 2^128 collision) and readability
- Sufficient for reproducibility validation in backtest context

**Signal tables separate by type:**
- Three separate tables (ema_crossover, rsi_mean_revert, atr_breakout) instead of unified cmc_signals_daily
- Enables type-specific columns (rsi_at_entry, breakout_type) without schema bloat
- Follows Phase 7 pattern: specialized tables per feature type

**State manager queries signal table:**
- `load_open_positions` queries signal table (not state table) for full context
- State table only has timestamps/counts, signal table has entry_price, feature_snapshot, etc.
- Full context needed for incremental signal generation

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed dataclass field ordering**
- **Found during:** Task 2 (SignalStateManager creation)
- **Issue:** `TypeError: non-default argument 'signal_type' follows default argument` - Python requires non-default args before defaults
- **Fix:** Moved `signal_type: str` to first position in SignalStateConfig dataclass
- **Files modified:** src/ta_lab2/scripts/signals/signal_state_manager.py
- **Verification:** Import test passed
- **Committed in:** d4cc8bd (Task 2 commit)

**2. [Rule 1 - Bug] Handle empty DataFrame in get_dirty_window_start**
- **Found during:** Task 3 (test_get_dirty_window_start_no_state_returns_none)
- **Issue:** KeyError when accessing state_df["id"] on empty DataFrame (no columns)
- **Fix:** Added `if state_df.empty: return {id_: None for id_ in ids}` guard before column access
- **Files modified:** src/ta_lab2/scripts/signals/signal_state_manager.py
- **Verification:** Test passes
- **Committed in:** 50e2a7e (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both auto-fixes necessary for correct operation. No scope creep.

## Issues Encountered

None - all tasks executed as planned.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for signal generation (Plan 08-02):**
- dim_signals configuration table populated and queryable
- Signal tables created with correct schemas
- SignalStateManager ready for position lifecycle tracking
- Feature hashing utilities ready for reproducibility validation

**No blockers or concerns.**

**Test coverage:**
- 19 tests passing (8 state manager + 11 utilities)
- Both unit tests (mocked) and integration tests (database)
- All verification criteria met

---
*Phase: 08-ta_lab2-signals*
*Completed: 2026-01-30*
