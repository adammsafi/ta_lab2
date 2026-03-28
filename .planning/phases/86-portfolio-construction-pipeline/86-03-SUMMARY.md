---
phase: 86-portfolio-construction-pipeline
plan: "03"
subsystem: pipeline
tags: [calibrate-stops, parity-check, bakeoff, daily-pipeline, portfolio, signals]

# Dependency graph
requires:
  - phase: 86-01
    provides: stop_calibrations table, calibrate_stops.py script with --ids all support
  - phase: 86-02
    provides: per-asset IC-IR BL dispatch, target_vol sizing mode, paper_executor GARCH wiring
  - phase: 83
    provides: AMA strategy names map to ema_crossover signal_type in dim_signals
  - phase: 82
    provides: strategy_bakeoff_results table schema (strategy_name, asset_id, tf, sharpe_mean, cv_method)
provides:
  - calibrate_stops pipeline stage wired into run_daily_refresh.py (after signals, before portfolio)
  - TIMEOUT_CALIBRATE_STOPS = 300 constant
  - run_calibrate_stops_stage() function following portfolio stage pattern
  - --calibrate-stops and --no-calibrate-stops CLI flags
  - --bakeoff-winners flag in run_parity_check.py with auto-discovery via ROW_NUMBER ranking
  - _STRATEGY_SIGNAL_MAP and _discover_bakeoff_winners() for signal_id resolution
  - Clear diagnostic messages when backtest_trades linkage is missing
affects:
  - phase: 87 (live signal generation)
  - daily operations (run_daily_refresh.py --all now includes calibrate_stops stage)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Non-fatal pipeline stage pattern: stage failure logs warn + continues when --continue-on-error set
    - Timeout constant pattern: TIMEOUT_* = N at module top for each pipeline stage
    - ROW_NUMBER() OVER PARTITION BY ranking for "top-1 per group" winner selection
    - Strategy-to-signal-type mapping dict for cross-table name resolution

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py
    - src/ta_lab2/scripts/executor/run_parity_check.py

key-decisions:
  - "TIMEOUT_CALIBRATE_STOPS = 300 (5 min): iterates over asset x strategy combos, mostly SQL reads"
  - "calibrate_stops is non-fatal: warns and continues when --continue-on-error; hard-stops otherwise"
  - "_STRATEGY_SIGNAL_MAP: ama_momentum/ama_mean_reversion/ama_regime_conditional -> ema_crossover (Phase 83 decision)"
  - "CPCV cv_method first for bakeoff winner discovery; falls back to PKF if no CPCV rows exist"
  - "slippage_mode=fixed auto-applied when --bakeoff-winners used (historical replay has fill price diffs)"
  - "backtest_trades linkage gap logged as WARN (not error): expected behavior when Phase 82 results in strategy_bakeoff_results only"

patterns-established:
  - "Non-fatal pipeline stage: if not result.success and not args.continue_on_error: return 1; else: print WARN and continue"
  - "CLI flag pair: --calibrate-stops (standalone) + --no-calibrate-stops (skip in --all mode)"

# Metrics
duration: 5min
completed: 2026-03-24
---

# Phase 86 Plan 03: Pipeline Wiring & Parity Check Extension Summary

**calibrate_stops wired into daily pipeline (signals -> calibrate_stops -> portfolio -> executor -> drift -> stats) and parity check extended with --bakeoff-winners auto-discovery via sharpe_mean ROW_NUMBER ranking against strategy_bakeoff_results**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-24T02:38:16Z
- **Completed:** 2026-03-24T02:44:08Z
- **Tasks:** 2 of 2
- **Files modified:** 2

## Accomplishments

- Stop calibration stage wired into run_daily_refresh.py between signals and portfolio refresh, completing the end-to-end portfolio construction pipeline (roadmap criterion 5)
- Parity check extended with --bakeoff-winners flag: auto-discovers winning strategies from strategy_bakeoff_results, resolves signal IDs via _STRATEGY_SIGNAL_MAP + dim_signals, runs multi-signal parity loop with summary (roadmap criterion 4 tooling)
- Clear diagnostic messages when backtest_trades linkage is missing -- correctly identifies the Phase 82 bake-off result gap without masking it

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire calibrate_stops into daily pipeline** - `94dbb6cc` (feat)
2. **Task 2: Extend parity check for bake-off winner auto-discovery** - `8093cb75` (feat)

## Files Created/Modified

- `src/ta_lab2/scripts/run_daily_refresh.py` - Added TIMEOUT_CALIBRATE_STOPS constant, run_calibrate_stops_stage() function, --calibrate-stops/--no-calibrate-stops CLI flags, wired stage into execution flow after signals before portfolio
- `src/ta_lab2/scripts/executor/run_parity_check.py` - Added _STRATEGY_SIGNAL_MAP, _discover_bakeoff_winners(), --bakeoff-winners CLI flag, multi-signal parity loop with CPCV/PKF fallback and backtest_trades linkage gap warning

## Decisions Made

- `TIMEOUT_CALIBRATE_STOPS = 300` (5 min): iterates over asset x strategy combos, mostly SQL reads -- conservative but not excessive
- `calibrate_stops` is non-fatal by default: failure logs WARN and pipeline continues to portfolio when `--continue-on-error` is set; hard-stops without that flag -- matches GARCH stage pattern from Phase 81
- `_STRATEGY_SIGNAL_MAP`: ama_momentum/ama_mean_reversion/ama_regime_conditional all map to `ema_crossover` (Phase 83 decision: AMA strategies reuse EMA signal lifecycle in dim_signals)
- CPCV cv_method first for winner discovery; PKF as fallback -- CPCV is the preferred CV method from Phase 82
- `slippage_mode=fixed` auto-applied when `--bakeoff-winners` is used (historical replay has fill price differences; direction and timing are what matters for parity)
- backtest_trades linkage gap logged as WARN (not error): expected behavior until a backtest run linking step connects Phase 82 strategy_bakeoff_results to backtest_runs/backtest_trades

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- ruff-format reformatted both files on first commit attempt (standard pattern): re-staged and committed clean on second attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Full pipeline order ready: signals -> calibrate_stops -> portfolio -> executor -> drift -> stats
- Parity check tooling ready: --bakeoff-winners discovers strategies, resolves signal_ids, clearly identifies backtest_trades linkage gaps
- Phase 86 complete (3/3 plans done): portfolio construction pipeline fully wired
- Phase 87 (live signal generation) can consume the calibrate_stops output from stop_calibrations table

---
*Phase: 86-portfolio-construction-pipeline*
*Completed: 2026-03-24*
