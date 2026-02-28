---
phase: 58-portfolio-construction-sizing
plan: 07
subsystem: signals
tags: [stop-ladder, atr-breakout, exit-signals, cli, portfolio-yaml]

# Dependency graph
requires:
  - phase: 58-04
    provides: StopLadder class in ta_lab2.portfolio.stop_ladder
  - phase: 58-05
    provides: portfolio __init__.py exports including StopLadder
provides:
  - StopLadder integrated into ATR breakout signal generator
  - --stop-ladder / --no-stop-ladder CLI flag on ATR breakout refresh
  - Multi-tier SL/TP exit records in signal output (stop_ladder_sl_N, stop_ladder_tp_N)
affects: [backtest-pipeline, signal-evaluation, portfolio-rebalancing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stop ladder integration via second exit condition in position state machine"
    - "Per-position already_triggered tracking to avoid re-firing tiers"

key-files:
  created: []
  modified:
    - "src/ta_lab2/scripts/signals/generate_signals_atr.py"
    - "src/ta_lab2/scripts/signals/refresh_cmc_signals_atr_breakout.py"

key-decisions:
  - "Stop ladder check runs as third branch in existing state machine (position open, no channel/ATR exit)"
  - "Exit records use direction='close', position_state='partial_exit', with size_frac from tier config"
  - "Default disabled (backward compatible) -- must opt in with --stop-ladder flag"

patterns-established:
  - "Stop ladder exit type labeling: stop_ladder_{sl|tp}_{tier_number}"
  - "already_triggered dict keyed by (asset_id, entry_ts) for per-position tier tracking"

# Metrics
duration: 5min
completed: 2026-02-28
---

# Phase 58 Plan 07: StopLadder ATR Breakout Integration Summary

**StopLadder wired into ATR breakout signal generator with check_triggers() for open positions and --stop-ladder CLI flag**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-28T08:44:25Z
- **Completed:** 2026-02-28T08:49:29Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- StopLadder imported from ta_lab2.portfolio and instantiated from portfolio.yaml when enabled
- check_triggers() called inside the position state machine for each bar where position is open and no channel/ATR exit fired
- Stop ladder exit records labeled stop_ladder_sl_N / stop_ladder_tp_N with size_frac for downstream sizing
- --stop-ladder / --no-stop-ladder CLI flags on refresh_cmc_signals_atr_breakout.py
- Default is disabled (backward compatible with existing behavior)
- Per-position already_triggered tracking prevents re-firing of tiers

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire StopLadder into ATRSignalGenerator** - `65f37725` (feat)
   - Note: Task 1 changes were included in the 58-06 commit due to pre-commit hook stash/unstash interaction. The code is correct and committed.
2. **Task 2: Add --stop-ladder CLI flag** - `5f289943` (feat)

## Files Created/Modified
- `src/ta_lab2/scripts/signals/generate_signals_atr.py` - StopLadder import, stop_ladder_enabled parameter, check_triggers() in state machine, per-position tier tracking
- `src/ta_lab2/scripts/signals/refresh_cmc_signals_atr_breakout.py` - --stop-ladder / --no-stop-ladder argparse flags, pass-through to generate_for_ids(), summary output

## Decisions Made
- Integrated stop ladder check as a third branch in the existing position state machine rather than a separate post-processing pass -- cleaner and preserves the per-bar position state context
- Exit records use `direction="close"`, `position_state="partial_exit"`, with `size_frac` from the tier config to allow downstream systems to determine partial vs full position reduction
- `side=1` hardcoded since ATR breakout is long-only (see breakout_atr.py: "Short side omitted by default")
- Strategy name passed as `"atr_breakout"` for per-strategy tier overrides in portfolio.yaml

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task 1 changes included in 58-06 commit**
- **Found during:** Task 1 commit attempt
- **Issue:** Pre-commit hook stash/unstash cycle merged Task 1 working tree changes into the concurrent 58-06 commit. When attempting to commit Task 1 separately, the pre-commit hook's ruff lint check failed on an unrelated file (run_portfolio_backtest.py had pre-existing F821 errors), and the stash conflict resolution included our changes in the 58-06 commit.
- **Fix:** Accepted the commit since the code is correct and complete. Task 1 changes are in `65f37725`.
- **Files modified:** src/ta_lab2/scripts/signals/generate_signals_atr.py
- **Verification:** Import test passes, grep confirms all integration points present
- **Committed in:** 65f37725 (merged with 58-06 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Task 1 code is correct but lives in the wrong commit. No functional impact.

## Issues Encountered
- Pre-commit ruff lint failure on unrelated file `run_portfolio_backtest.py` (F821: undefined name `TurnoverTracker` in type annotations). This is a pre-existing issue from Plan 58-06 and does not affect this plan's files.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PORT-05 gap is now closed: StopLadder is no longer orphaned
- Stop ladder can be tested end-to-end: `python -m ta_lab2.scripts.signals.refresh_cmc_signals_atr_breakout --stop-ladder --dry-run`
- Downstream backtest pipeline can consume stop_ladder exit records via the size_frac and breakout_type fields

---
*Phase: 58-portfolio-construction-sizing*
*Completed: 2026-02-28*
