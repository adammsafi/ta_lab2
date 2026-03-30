---
phase: 96-executor-activation
plan: "02"
subsystem: signals
tags: [macd, ama, signal-generator, two-batch, pandas, sqlalchemy]

# Dependency graph
requires:
  - phase: 96-01
    provides: new signal tables (signals_macd_crossover, signals_ama_*) + dim_signals rows

provides:
  - MACD crossover signal adapter (signals/macd_crossover.py make_signals function)
  - MACDSignalGenerator class following EMA/RSI/ATR pattern
  - AMASignalGenerator class wrapping all 3 AMA signal subtypes
  - Two-batch signal refresh orchestrator (BATCH_1_TYPES + BATCH_2_TYPES)

affects:
  - 96-03 (executor activation -- all 7 generators now available for executor config)
  - 96-04 (parity tracking -- depends on signal tables being populated)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Self-contained MACD computation in macd_crossover.py avoids circular import with registry
    - AMA generator loads from ama_multi_tf_u (never re-computes from price)
    - Two-batch signal refresh pattern separates price-only generators (Batch 1) from AMA-dependent (Batch 2)
    - run_parallel_refresh() accepts signal_types parameter for flexible batch composition

key-files:
  created:
    - src/ta_lab2/signals/macd_crossover.py
    - src/ta_lab2/scripts/signals/generate_signals_macd.py
    - src/ta_lab2/scripts/signals/generate_signals_ama.py
  modified:
    - src/ta_lab2/scripts/signals/run_all_signal_refreshes.py
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "Self-contained _compute_macd in macd_crossover.py (not imported from registry) to break circular import"
  - "AMASignalGenerator loads from ama_multi_tf_u with DISTINCT ON deduplication"
  - "BATCH_1_TYPES=[ema,rsi,atr,macd] BATCH_2_TYPES=[ama x3] split at module level for external use"

patterns-established:
  - "Pattern: Signal adapters must not import from registry.py (circular import risk)"
  - "Pattern: AMA generators MUST read pre-computed values from ama_multi_tf_u"
  - "Pattern: run_parallel_refresh accepts signal_types= for batch composition"

# Metrics
duration: 8min
completed: 2026-03-30
---

# Phase 96 Plan 02: Signal Generator Scripts Summary

**MACD crossover adapter + AMA generator wrapping 3 subtypes + two-batch orchestrator enabling all 7 signal types to populate their tables**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-30T22:23:13Z
- **Completed:** 2026-03-30T22:31:36Z
- **Tasks:** 2
- **Files created:** 3, modified: 2

## Accomplishments

- Created `signals/macd_crossover.py` with self-contained `make_signals` using in-memory MACD computation (avoids circular import with registry.py)
- Created `scripts/signals/generate_signals_macd.py` with `MACDSignalGenerator` dataclass following the established EMA/RSI/ATR pattern exactly
- Created `scripts/signals/generate_signals_ama.py` with `AMASignalGenerator` that loads pre-computed AMA columns from `ama_multi_tf_u` before calling signal functions
- Refactored `run_all_signal_refreshes.py` to two-batch architecture: `BATCH_1_TYPES` (4 price-only generators) then `BATCH_2_TYPES` (3 AMA generators)
- Updated `run_daily_refresh.py` docstring to reflect 7 signal types

## Task Commits

1. **Task 1: Create MACD crossover signal adapter and generator** - `9db5133e` (feat)
2. **Task 2: Create AMA generator and refactor run_all_signal_refreshes** - `a550fbcd` (feat)

## Files Created/Modified

- `src/ta_lab2/signals/macd_crossover.py` - MACD signal adapter with `make_signals` function; self-contained `_compute_macd` helper (no registry import)
- `src/ta_lab2/scripts/signals/generate_signals_macd.py` - `MACDSignalGenerator` dataclass; writes to `signals_macd_crossover`; includes `executor_processed_at=NULL`
- `src/ta_lab2/scripts/signals/generate_signals_ama.py` - `AMASignalGenerator` dataclass; loads AMA from `ama_multi_tf_u` via DISTINCT ON pivot; writes to `signals_ama_{subtype}`
- `src/ta_lab2/scripts/signals/run_all_signal_refreshes.py` - Two-batch orchestrator with `BATCH_1_TYPES`/`BATCH_2_TYPES` constants; `run_parallel_refresh` accepts `signal_types=` parameter
- `src/ta_lab2/scripts/run_daily_refresh.py` - Docstring updated (7 signal types, two-batch)

## Decisions Made

- **Self-contained MACD computation**: `macd_crossover.py` duplicates the `_ensure_macd` logic (does not import from `registry.py`) because `registry.py` tries to import `macd_crossover.py` -- importing back would create a circular dependency that Python's try/except at module level catches and silently sets the signal to None.
- **AMA loads from DB**: `AMASignalGenerator._load_ama_columns()` uses `DISTINCT ON (a.id, a.ts, a.indicator, LEFT(a.params_hash, 8))` to pivot pre-computed AMA values. The `alignment_source='multi_tf'` and `roll=FALSE` filters match the standard AMA query pattern from 82-RESEARCH.md.
- **Module-level batch constants**: `BATCH_1_TYPES` and `BATCH_2_TYPES` are exposed at module level so external code (CI scripts, tests) can reference them without re-parsing the orchestrator logic.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Circular import between macd_crossover.py and registry.py**

- **Found during:** Task 1 (Create MACD crossover signal adapter)
- **Issue:** The plan stated to use `_ensure_macd` from `registry.py`. However, `registry.py` imports from `macd_crossover.py` via a try/except block. If `macd_crossover.py` imports back from `registry.py`, Python catches the circular import in the try/except and silently sets `macd_crossover_signal = None`, making it invisible in the REGISTRY.
- **Fix:** Created a self-contained `_compute_macd()` function directly in `macd_crossover.py` that duplicates the MACD logic without importing from `registry.py`.
- **Files modified:** `src/ta_lab2/signals/macd_crossover.py`
- **Verification:** `from ta_lab2.signals.registry import REGISTRY; assert 'macd_crossover' in REGISTRY` passes in a fresh Python process.
- **Committed in:** `9db5133e` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug, circular import)
**Impact on plan:** Essential fix — without it, `macd_crossover` would not appear in REGISTRY and the executor would never process MACD signals. No scope creep.

## Issues Encountered

- ruff format reformatted both Task 1 and Task 2 files (long dict/function call lines), requiring a re-stage and second commit attempt in each case. No logic changed.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All 7 signal generators are importable and tested
- `run_all_signal_refreshes.py` runs Batch 1 (4 types) then Batch 2 (3 AMA types) sequentially
- REGISTRY contains all 7 strategies (ema_trend, rsi_mean_revert, macd_crossover, breakout_atr, ama_momentum, ama_mean_reversion, ama_regime_conditional)
- Ready for 96-03: executor config expansion (seed YAML + BL weight sizing)
- AMA generators will produce empty signals until `ama_multi_tf_u` has data for the assets being processed (graceful degradation already implemented)

---
*Phase: 96-executor-activation*
*Completed: 2026-03-30*
