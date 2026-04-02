---
phase: 93
plan: 01
subsystem: integration-testing
tags: [smoke-test, parity-check, garch, strategy-mapping]
dependency_graph:
  requires: [88]
  provides: [fixed-garch-queries, complete-strategy-signal-map]
  affects: []
tech_stack:
  added: []
  patterns: [fallback-signal-resolution]
key_files:
  created: []
  modified:
    - src/ta_lab2/scripts/integration/smoke_test.py
    - src/ta_lab2/scripts/executor/run_parity_check.py
decisions:
  - "7 explicit strategy-signal mappings plus fallback for unmapped strategies"
  - "Fallback uses strategy_name as signal_type with info-level log"
metrics:
  duration: 2 min
  completed: 2026-03-28
---

# Phase 93 Plan 01: Fix Integration Breaks Summary

**One-liner:** Fix GARCH column bug (asset_id -> id) in smoke test and expand parity check strategy map from 3 to 7 entries with fallback.

## What Was Done

### Task 1: Fix GARCH column bug in smoke_test.py
- Changed `asset_id=1` to `id=1` in both GARCH queries in `_build_garch_checks()`
- The `garch_forecasts` table PK is `(id, venue_id, ts, tf, model_type, horizon)` -- there is no `asset_id` column
- 2-line fix, no other changes
- Commit: `54697fb4`

### Task 2: Expand _STRATEGY_SIGNAL_MAP in run_parity_check.py
- Added 4 new entries: `ema_trend`, `macd_crossover`, `rsi_mean_revert`, `breakout_atr`
- Map now has 7 explicit entries (was 3)
- Added fallback: unmapped strategies (e.g., expression-engine strategies) try `strategy_name` as `signal_type` directly instead of silently skipping
- Existing `signal_row` None-check (line ~166) handles truly unknown signal_types with a warning
- 0 strategies silently skipped -- all are either resolved or logged
- Commit: `51a7df4b`

## Decisions Made

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | 7 explicit mappings + fallback | Covers all known bakeoff strategies; fallback handles expression-engine and future strategies without code changes |
| 2 | Fallback logs at INFO level (not WARNING) | Expected path for expression-engine strategies; WARNING reserved for actual signal_row lookup failures |

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- Both files parse without syntax errors
- `grep -n 'asset_id'` returns zero matches in GARCH section (lines 345-370)
- `grep -n 'WHERE id=1'` shows 2 matches in GARCH section (lines 356, 364)
- `_STRATEGY_SIGNAL_MAP` has 7 entries confirmed via import

## Audit Trail Closure

- **Break 1 (HIGH):** smoke_test GARCH `ProgrammingError` -- FIXED (asset_id -> id)
- **Break 3 (MEDIUM):** parity check silently skips 6/9 strategies -- FIXED (7 explicit + fallback)
- **REQ-15 (at risk):** Integration smoke test -- UNBLOCKED

## Next Phase Readiness

No blockers. Both scripts are ready for end-to-end verification with DB connection.
