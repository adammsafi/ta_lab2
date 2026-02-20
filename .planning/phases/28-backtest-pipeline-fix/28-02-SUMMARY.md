---
phase: 28-backtest-pipeline-fix
plan: "02"
subsystem: backtests
tags: [vectorbt, pandas, sqlalchemy, psycopg2, timezone, jsonb]

requires:
  - phase: 28-01
    provides: DDL for cmc_backtest_runs, cmc_backtest_trades, cmc_backtest_metrics tables

provides:
  - _ensure_utc() helper for safe tz-aware/tz-naive timestamp handling
  - Fixed _extract_trades() with vbt 0.28.1 column names and direction strings
  - Tz-strip in run_backtest() protecting both run_vbt_on_split and _build_portfolio
  - json.dumps(cost_model) preventing psycopg2 JSONB adaptation failure

affects:
  - 28-03 (end-to-end validation will exercise all these fixes)

tech-stack:
  added: []
  patterns:
    - "_ensure_utc() helper pattern: tz-safe conversion (tz_localize if naive, tz_convert if aware)"
    - "Strip tz at ingestion boundary, re-localize at output boundary"
    - "json.dumps for explicit JSONB serialization rather than relying on psycopg2 dict adaptation"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/backtests/backtest_from_signals.py

key-decisions:
  - "tz-strip prices/entries/exits in run_backtest() before vectorbt (single strip covers both run_vbt_on_split and _build_portfolio)"
  - "str.lower() for direction mapping handles vbt string 'Long'/'Short' and integer 0/1 fallback"
  - "Entry Fees + Exit Fees first with backward compat fallback to Fees then 0.0"
  - "json.dumps(cost_model) explicit rather than relying on psycopg2 dict-to-JSONB auto-adaptation"

patterns-established:
  - "Tz boundary pattern: strip at ingestion (run_backtest), re-add at extraction (_ensure_utc in _extract_trades)"
  - "Backward compat fee extraction: new column names first, old names as fallback, zero as final default"

duration: 2min
completed: "2026-02-20"
---

# Phase 28 Plan 02: Backtest Pipeline Fix (vectorbt Compatibility) Summary

**Fixed 5 vectorbt 0.28.1 compatibility bugs in backtest_from_signals.py: tz-aware timestamp TypeError, NaN direction from integer map, missing 'Fees' column, dict JSONB adaptation error, and tz-aware index crash in vectorbt internals.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-20T22:02:01Z
- **Completed:** 2026-02-20T22:03:33Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Added `_ensure_utc()` module-level helper that safely handles both tz-naive (tz_localize) and tz-aware (tz_convert) timestamp Series without raising TypeError
- Fixed direction column extraction: replaced `{0:'long', 1:'short'}` integer map (produces NaN for vbt 0.28.1 strings) with `.astype(str).str.lower()` which handles both 'Long'/'Short' and 0/1
- Fixed fee extraction: vbt 0.28.1 uses 'Entry Fees' + 'Exit Fees' columns (not 'Fees'); added backward-compat fallback chain
- Fixed cost_model JSONB insertion: explicit `json.dumps()` prevents psycopg2 dict adaptation failure; added `import json` at top of file
- Added tz-strip block in `run_backtest()` after prices/entries/exits are loaded, before they reach vectorbt — covers both `run_vbt_on_split` and `_build_portfolio` call paths

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix _extract_trades vectorbt 0.28.1 compatibility** - `f4c72beb` (fix)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `src/ta_lab2/scripts/backtests/backtest_from_signals.py` - All 5 vectorbt 0.28.1 compatibility fixes applied

## Decisions Made

- **Single tz-strip point in run_backtest()**: Strip tz from prices/entries/exits once after load, before any vectorbt call. Both `run_vbt_on_split` and `_build_portfolio` receive the same variables so a single strip covers both paths — no need for per-method stripping.
- **str.lower() for direction**: Handles vbt 0.28.1 string output ('Long' -> 'long', 'Short' -> 'short') and also gracefully preserves integer fallback ('0', '1' as strings) without crashing.
- **Explicit json.dumps**: Rather than relying on psycopg2's dict-to-JSONB adaptation (which may silently fail or raise ProgrammingError), serialize explicitly for deterministic behavior.
- **Backward-compat fee fallback**: `Entry Fees + Exit Fees` (vbt 0.28.1) -> `Fees` (older vbt) -> `0.0` (no fee tracking). Maximizes compatibility across vbt versions.

## Deviations from Plan

None - plan executed exactly as written. All 5 fixes applied as specified.

## Issues Encountered

None. The linter (ruff) ran on the first `import json` edit and appeared to revert it momentarily, but a re-read confirmed the change was preserved. All subsequent edits applied cleanly and pre-commit hooks passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 4 documented vectorbt bugs are fixed; backtest runner should now execute end-to-end
- Plan 28-03 (end-to-end validation) can now run backtests against the database and verify actual trade extraction
- No blockers

---
*Phase: 28-backtest-pipeline-fix*
*Completed: 2026-02-20*
