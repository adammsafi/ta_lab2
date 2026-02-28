---
phase: 58-portfolio-construction-sizing
plan: 04
subsystem: portfolio
tags: [portfolio, topk, dropout, turnover, rebalancing, stop-loss, take-profit, exit-scaling]

# Dependency graph
requires:
  - phase: 58-01
    provides: configs/portfolio.yaml with topk_selection, rebalancing, stop_laddering sections
  - phase: 58-02
    provides: PortfolioOptimizer producing weights that TopkDropoutSelector filters

provides:
  - TopkDropoutSelector: top-K asset selection with at-most-N-dropout per rebalance
  - TurnoverTracker: gross/cost/net return decomposition with cumulative cost history
  - RebalanceScheduler: time_based, signal_driven, threshold_based trigger modes
  - StopLadder: multi-tier SL/TP exit schedules with per-asset x per-strategy override hierarchy

affects:
  - 58-05 (consolidates exports of all 4 modules into __init__.py)
  - Any order generation layer consuming StopLadder schedules (Phase 59+)
  - Backtest layer using TurnoverTracker for realistic cost modeling

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TopkDropout: select top-K, dropout worst N held assets below threshold each cycle"
    - "4-layer override resolution: defaults -> per_strategy -> per_asset -> asset:strategy"
    - "Tier validation at construction time: len(stops)==len(sizes) and sum(sizes)~=1.0"
    - "Already-triggered set pattern: pass set to check_triggers to prevent re-firing"

key-files:
  created:
    - src/ta_lab2/portfolio/topk_selector.py
    - src/ta_lab2/portfolio/cost_tracker.py
    - src/ta_lab2/portfolio/rebalancer.py
    - src/ta_lab2/portfolio/stop_ladder.py

key-decisions:
  - "TopkDropout counts: to_buy == len(to_sell) to keep portfolio size stable at K"
  - "RebalanceScheduler time_based + drift_threshold > 0: EITHER condition triggers (not AND)"
  - "None last_rebalance_ts always triggers to handle initial portfolio construction"
  - "StopLadder falls back to load_portfolio_config() when config=None, consistent with other modules"
  - "already_triggered uses 'sl_N' / 'tp_N' string keys (not integers) to avoid type confusion"
  - "TurnoverTracker.cumulative_costs is a @property not a method to match natural read syntax"

patterns-established:
  - "TopkDropoutSelector: buy same count as sell to maintain portfolio size invariant"
  - "StopLadder override merges via dict.update() so partial overrides do not wipe unspecified keys"

# Metrics
duration: 4min
completed: 2026-02-28
---

# Phase 58 Plan 04: Portfolio Construction Selector/Rebalancer/Stops Summary

**TopkDropoutSelector (buy/sell sets), TurnoverTracker (gross/cost/net decomp), RebalanceScheduler (3-mode trigger), StopLadder (4-layer per-asset x per-strategy SL/TP tiers) -- 4 modules, 776 lines**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-28T08:00:20Z
- **Completed:** 2026-02-28T08:04:11Z
- **Tasks:** 3/3
- **Files modified:** 4

## Accomplishments

- TopkDropoutSelector: correctly returns (to_buy, to_sell) bounded to n_drop per cycle; handles initial portfolio (empty holdings = buy full top-K)
- TurnoverTracker: compute() math verified (turnover=1.0 on full rotation, cost=0.001 at 10bps); track() appends gross/cost/net records; cumulative_costs property sums history
- RebalanceScheduler: all three modes verified (time_based daily trigger, signal_driven passthrough, threshold_based 6% drift at 5% threshold); time_based + drift overlay triggers on EITHER
- StopLadder: 4-layer resolution verified (defaults -> per_strategy -> per_asset -> combined key); compute_exit_schedule verified for long and short sides; check_triggers with already_triggered set prevents re-firing

## Task Commits

Each task was committed atomically:

1. **Task 1: TopkDropoutSelector** - `824ddf00` (feat)
2. **Task 2: TurnoverTracker and RebalanceScheduler** - `00c02d3f` (feat)
3. **Task 3: StopLadder (PORT-05)** - `f722b3f3` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/portfolio/topk_selector.py` - TopkDropoutSelector with select() and get_target_universe(); 127 lines
- `src/ta_lab2/portfolio/cost_tracker.py` - TurnoverTracker with compute(), track(), cumulative_costs; 139 lines
- `src/ta_lab2/portfolio/rebalancer.py` - RebalanceScheduler with should_rebalance(), parse_frequency(), _drift_triggered(); 184 lines
- `src/ta_lab2/portfolio/stop_ladder.py` - StopLadder with get_tiers(), compute_exit_schedule(), check_triggers(); 326 lines

## Decisions Made

1. **TopkDropout maintains K invariant**: to_buy count equals to_sell count so portfolio always holds exactly K assets after rebalance (not K + new buys).

2. **Time_based + drift overlay uses OR not AND**: The plan spec says "rebalance if EITHER time OR drift triggers". Using AND would allow a portfolio to drift indefinitely if time hasn't elapsed yet.

3. **None last_rebalance_ts triggers immediately**: Simplifies caller logic -- no need for special-case initial construction checks outside the scheduler.

4. **StopLadder config=None falls back to load_portfolio_config()**: Consistent with all other Phase 58 modules. Avoids requiring callers to pass config explicitly in production.

5. **already_triggered string keys "sl_1", "tp_1"**: Avoids integer/string type confusion when callers persist triggered tier state to JSON/DB.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit `mixed-line-ending` hook (CRLF to LF) on all three new files required re-stage and second commit attempt per task. Standard Windows workflow, consistent with prior phases.

## User Setup Required

None - all modules are pure Python with no external service dependencies.

## Next Phase Readiness

- All 4 modules importable from their respective files (exports consolidated in 58-05)
- StopLadder tested with configs/portfolio.yaml defaults (3-tier sl/tp, sizes [0.33, 0.33, 0.34])
- TurnoverTracker ready to be wired into backtest loop for realistic cost modeling
- RebalanceScheduler ready to be integrated into paper trading execution loop (Phase 45/beyond)
- 58-05 can safely import TopkDropoutSelector, TurnoverTracker, RebalanceScheduler, StopLadder

---
*Phase: 58-portfolio-construction-sizing*
*Completed: 2026-02-28*
