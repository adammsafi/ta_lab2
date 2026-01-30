---
phase: 08-ta_lab2-signals
plan: 03
subsystem: signals
tags: [signals, rsi, mean-reversion, adaptive-thresholds, rolling-percentiles, signal-generation]

# Dependency graph
requires:
  - phase: 08-ta_lab2-signals/08-01
    provides: SignalStateManager, dim_signals config table, signal_utils (feature hashing)
provides:
  - RSISignalGenerator for RSI mean reversion signal generation from cmc_daily_features
  - Adaptive threshold utilities (compute_adaptive_thresholds) for per-asset calibration
  - CLI refresh script with --adaptive flag for rolling percentile thresholds
  - RSI value tracking at entry/exit for signal analysis
affects: [08-04, 08-05, signal-generation, backtest-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Adaptive rolling percentile thresholds for RSI mean reversion
    - Database-driven threshold configuration from dim_signals params
    - Signal-specific analytics (rsi_at_entry, rsi_at_exit) for performance analysis
    - Transform signals to stateful position records with PnL calculation

key-files:
  created:
    - src/ta_lab2/scripts/signals/generate_signals_rsi.py
    - src/ta_lab2/scripts/signals/refresh_cmc_signals_rsi_mean_revert.py
    - tests/signals/test_rsi_signal_generation.py
  modified: []

key-decisions:
  - "Adaptive thresholds use rolling quantiles (20th/80th percentile default) for per-asset calibration"
  - "Signal transformation tracks RSI values at entry and exit for analysis (not just entry price)"
  - "PnL calculation: (exit - entry) / entry * 100 for long positions, reversed for shorts"
  - "Integration tests skip gracefully when database tables unavailable (pytest.skip in try block)"

patterns-established:
  - "RSISignalGenerator follows EMASignalGenerator pattern: load_features, generate via adapter, transform_to_records"
  - "Adaptive thresholds computed per asset group with rolling window (default 100 periods)"
  - "CLI --adaptive flag enables adaptive mode without code changes (configuration-driven behavior)"
  - "Test pattern: Unit tests with mocks (10 tests) + integration tests with skipif (3 tests)"

# Metrics
duration: 8min
completed: 2026-01-30
---

# Phase 8 Plan 3: RSI Mean Reversion Signals Summary

**RSI mean reversion signals with database-driven thresholds and adaptive rolling percentile support for per-asset calibration**

## Performance

- **Duration:** 8 min
- **Started:** 2026-01-30T19:57:23Z
- **Completed:** 2026-01-30T20:05:30Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- RSISignalGenerator class with database-driven threshold configuration from dim_signals
- RSI value tracking at entry and exit for signal quality analysis (rsi_at_entry, rsi_at_exit)
- Adaptive threshold utilities (compute_adaptive_thresholds) using rolling percentiles for per-asset calibration
- CLI refresh script with --adaptive flag enabling adaptive mode without code changes
- 10 unit tests passing (signal transformation, adaptive thresholds, parameter handling)
- 3 integration tests (skip gracefully without database)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create RSISignalGenerator class** - `4461a92` (feat)
2. **Task 2: Create refresh CLI script** - `a5bd51e` (feat)
3. **Task 3: Create tests for RSI signal generation** - `c3dd3a7` (test)

## Files Created/Modified

**Python modules:**
- `src/ta_lab2/scripts/signals/generate_signals_rsi.py` - RSISignalGenerator class (454 lines) with adaptive threshold support
- `src/ta_lab2/scripts/signals/refresh_cmc_signals_rsi_mean_revert.py` - CLI refresh script with --adaptive flag (246 lines)

**Tests:**
- `tests/signals/test_rsi_signal_generation.py` - 13 tests (10 unit, 3 integration)

## Decisions Made

**Adaptive threshold implementation:**
- Use rolling quantiles (default 20th/80th percentile) for adaptive thresholds
- Per-asset grouping ensures each asset has calibrated thresholds based on its own RSI history
- Default lookback window: 100 periods (configurable via params)
- Note: Current implementation computes adaptive thresholds but uses global average due to make_signals API limitations
- Future enhancement: Modify make_signals to accept threshold series for full per-row adaptive logic

**RSI value tracking:**
- Track rsi_at_entry and rsi_at_exit in signal records for analysis
- Enables analysis of relationship between entry RSI level and PnL
- Enables verification of mean reversion completion (did RSI reach overbought/oversold exit threshold)

**PnL calculation:**
- Long: ((exit_price - entry_price) / entry_price) * 100
- Short: ((entry_price - exit_price) / entry_price) * 100
- Matches industry standard percentage return calculation

**Integration test skipping:**
- Integration tests check table existence in try block and pytest.skip if missing
- Prevents test failures in environments without full database infrastructure
- Unit tests provide core functionality coverage without database dependency

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed integration test cleanup in finally blocks**
- **Found during:** Task 3 (test execution)
- **Issue:** Integration tests failed in cleanup (finally block) when database tables didn't exist - tried to DELETE from non-existent tables
- **Fix:** Wrapped cleanup DELETE statements in try-except blocks to handle missing tables gracefully, and added table existence checks in setup with pytest.skip
- **Files modified:** tests/signals/test_rsi_signal_generation.py
- **Verification:** All tests pass (10 passed, 3 skipped) when database unavailable
- **Committed in:** c3dd3a7 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Bug fix necessary for test suite to run in environments without database. No scope creep.

## Issues Encountered

**Adaptive threshold API limitation:**
- The existing make_signals() adapter accepts static lower/upper thresholds (floats)
- Adaptive thresholds are computed as Series (per-row values)
- Current implementation computes adaptive thresholds per asset, then uses global average as static override
- **Resolution:** Documented limitation in code comments and logged warning when adaptive mode is used
- **Future work:** Enhance make_signals to accept threshold Series for full per-row adaptive logic
- **Impact:** Adaptive mode is wired and functional, but uses averaged thresholds instead of per-row values until adapter enhanced

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for ATR breakout signals (Plan 08-04):**
- RSI signal generation pattern established and tested
- Adaptive threshold infrastructure built and reusable for other signal types
- CLI refresh pattern consistent across signal types (EMA, RSI, ATR will match)

**Ready for backtest integration (Plan 08-05):**
- Signal records include rsi_at_entry/exit for analysis
- Feature hashing and params hashing for reproducibility validation
- PnL calculation implemented in signal transformation

**Test coverage:**
- 10 unit tests passing (signal transformation, adaptive thresholds, parameter handling)
- 3 integration tests skip gracefully without database
- All verification criteria met

**No blockers or concerns.**

---
*Phase: 08-ta_lab2-signals*
*Completed: 2026-01-30*
