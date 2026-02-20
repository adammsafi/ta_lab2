---
phase: 27-regime-integration
plan: 07
subsystem: regimes
tags: [regime, daily-refresh, orchestrator, inspection, subprocess, cli]

# Dependency graph
requires:
  - phase: 27-05
    provides: refresh_cmc_regimes.py full pipeline writing all 4 regime tables
  - phase: 27-06
    provides: signal generators with regime awareness and --no-regime flag
provides:
  - run_daily_refresh.py with --regimes flag and --all including regimes step
  - regime_inspect.py DB-backed CLI tool for ad-hoc regime analysis
affects: [phase-28-backtest, daily-operations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - run_regime_refresher() matches run_ema_refreshers() subprocess pattern exactly
    - Regime inspect dispatches to show_latest/show_live/show_history/show_flips by flag
    - --dry-run propagated to subprocess via getattr(args, 'dry_run', False)

key-files:
  created:
    - src/ta_lab2/scripts/regimes/regime_inspect.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "--regimes as standalone flag plus --all including regimes after EMAs (bars -> EMAs -> regimes)"
  - "EMA failure triggers early-stop before regimes unless --continue-on-error"
  - "regime_inspect default mode reads from DB; --live triggers compute_regimes_for_id on-the-fly"

patterns-established:
  - "Subprocess orchestration: all refresh scripts use same subprocess.run + ComponentResult pattern"
  - "Inspection tools: DB read as default, --live for on-the-fly verification before write"

# Metrics
duration: 4min
completed: 2026-02-20
---

# Phase 27 Plan 07: Orchestrator Integration and Inspection Tool Summary

**Regime refresh wired into run_daily_refresh.py (bars -> EMAs -> regimes via subprocess) plus DB-backed regime_inspect.py CLI with --live, --history, and --flips modes**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-20T19:50:58Z
- **Completed:** 2026-02-20T19:54:22Z
- **Tasks:** 2 (checkpoint Task 3 paused for human verification)
- **Files modified:** 2

## Accomplishments

- Extended run_daily_refresh.py with --regimes flag and --no-regime-hysteresis, updated --all to include regimes as third step after EMAs
- Added run_regime_refresher() function matching run_ema_refreshers() pattern (subprocess.run, ComponentResult, dry-run propagation)
- Created regime_inspect.py with 4 display modes: latest DB read, --live on-the-fly computation, --history N tabular history, --flips recent transitions
- Verified --dry-run is propagated to regime subprocess (both --verbose and --dry-run appear in command line shown)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add --regimes step to run_daily_refresh.py** - `cea3cd45` (feat)
2. **Task 2: Create regime_inspect.py DB-backed inspection tool** - `214dae1f` (feat)

## Files Created/Modified

- `src/ta_lab2/scripts/run_daily_refresh.py` - Added --regimes, --no-regime-hysteresis flags, run_regime_refresher() function, updated --all to bars->EMAs->regimes, added EMA early-stop before regimes
- `src/ta_lab2/scripts/regimes/regime_inspect.py` - New DB-backed inspection tool with 4 modes

## Decisions Made

- **--regimes as standalone plus --all inclusion**: Consistent with --bars/--emas pattern; --all becomes the single command for bars->EMAs->regimes pipeline
- **EMA early-stop before regimes**: Added check `if not ema_result.success and not args.continue_on_error` before running regimes - regimes depend on fresh EMAs
- **regime_inspect default reads from DB**: Operational check should be fast (DB read, no computation); --live flag available for testing changes before write

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - both tasks completed cleanly on first attempt. Ruff reformatted line endings in regime_inspect.py (Windows CRLF -> LF), required re-add before successful commit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Complete regime integration pipeline (all 7 plans in Phase 27) is ready for end-to-end verification
- Checkpoint Task 3 requires human verification of the full pipeline:
  1. Regime refresh for BTC/ETH/USDC
  2. DB table row counts
  3. regime_inspect output
  4. EMA signal generation with regime context
  5. A/B comparison with --no-regime
  6. RSI signal generation (tests feature_snapshot fix from Plan 06)
  7. Daily refresh orchestrator dry-run
- After verification, Phase 28 (Backtest Pipeline Fix) can begin

---
*Phase: 27-regime-integration*
*Completed: 2026-02-20*
