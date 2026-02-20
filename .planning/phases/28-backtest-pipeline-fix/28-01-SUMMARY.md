---
phase: 28-backtest-pipeline-fix
plan: 01
subsystem: signals
tags: [json, serialization, psycopg2, pandas, jsonb, signal-generators]

# Dependency graph
requires:
  - phase: 27-regime-integration
    provides: EMA and ATR signal generators with regime_key wiring

provides:
  - EMA signal generator with stdlib json.dumps serialization for feature_snapshot
  - ATR signal generator with stdlib json.dumps serialization for feature_snapshot
  - Consistent JSON serialization pattern across all 3 signal generators (RSI/EMA/ATR)

affects:
  - 28-02-PLAN (backtest runner fix — depends on signals being writable)
  - 28-03-PLAN (end-to-end validation — depends on signal tables having data)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "JSON serialization: always apply json.dumps(x) if isinstance(x, dict) else x before to_sql() for JSONB columns"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/signals/generate_signals_ema.py
    - src/ta_lab2/scripts/signals/generate_signals_atr.py

key-decisions:
  - "json.dumps with isinstance(x, dict) guard matches RSI generator pattern — consistent across all 3 generators"
  - "records.copy() before mutation prevents SettingWithCopyWarning on DataFrame slice"

patterns-established:
  - "JSONB serialization: json.dumps(x) if isinstance(x, dict) else x — defensive, handles pre-serialized strings and None"

# Metrics
duration: 4min
completed: 2026-02-20
---

# Phase 28 Plan 01: Backtest Pipeline Fix — Signal Generator Serialization Summary

**Fixed psycopg2 dict-serialization bug in EMA generator and pd.io.json.dumps AttributeError in ATR generator by replacing both with stdlib json.dumps, making all 3 signal generators consistent.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-20T22:01:14Z
- **Completed:** 2026-02-20T22:05:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- EMA signal generator `_write_signals()` now serializes `feature_snapshot` dicts via `json.dumps` before `to_sql()`, eliminating psycopg2 "can't adapt type 'dict'" errors
- ATR signal generator `_write_signals()` replaces non-existent `pd.io.json.dumps()` (removed in pandas 2.x) with stdlib `json.dumps`, eliminating AttributeError crashes
- All 3 signal generators (RSI, EMA, ATR) now use the identical `json.dumps(x) if isinstance(x, dict) else x` pattern for JSONB column serialization

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix EMA signal generator feature_snapshot serialization** - `d79817bc` (fix)
2. **Task 2: Fix ATR signal generator feature_snapshot serialization** - `e35018ff` (fix)

## Files Created/Modified

- `src/ta_lab2/scripts/signals/generate_signals_ema.py` — Added `import json`; replaced misleading comment + bare `to_sql()` with `records.copy()` + `json.dumps` serialization before write
- `src/ta_lab2/scripts/signals/generate_signals_atr.py` — Added `import json`; replaced `pd.io.json.dumps(x) if x is not None else None` with `json.dumps(x) if isinstance(x, dict) else x`

## Decisions Made

- Used `isinstance(x, dict)` guard (not `x is not None`) to match the RSI generator pattern — handles edge case where `feature_snapshot` may already be a JSON string (idempotent)
- Applied `records.copy()` before mutation in EMA generator to prevent pandas SettingWithCopyWarning

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. Both fixes were straightforward one-liners. Both generators imported cleanly after edits. No pre-commit hook failures.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 3 signal generators can now write `feature_snapshot` to their respective JSONB columns without errors
- EMA signals → `cmc_signals_ema_crossover`, ATR signals → `cmc_signals_atr_breakout`, RSI signals → `cmc_signals_rsi_divergence`
- Ready for Plan 28-02 (backtest runner vectorbt timestamp fix)

---
*Phase: 28-backtest-pipeline-fix*
*Completed: 2026-02-20*
