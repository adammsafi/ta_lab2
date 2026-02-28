---
phase: 58-portfolio-construction-sizing
plan: 06
subsystem: portfolio
tags: [portfolio, backtest, turnover-tracking, bet-sizing, signal-probability, meta-label, gap-closure]

# Dependency graph
requires:
  - phase: 58-04
    provides: TurnoverTracker (cost_tracker.py)
  - phase: 58-05
    provides: run_portfolio_backtest.py with 4-strategy comparison
  - phase: 57-05
    provides: cmc_meta_label_results table with trade_probability

provides:
  - TurnoverTracker wired into _run_backtest() per-period loop
  - Decomposed per-strategy cost reporting (gross_ret, turnover_cost, net_ret)
  - _load_signal_probabilities() querying cmc_meta_label_results for per-asset probabilities
  - BetSizer receives varying probabilities so different assets get different position scales

affects:
  - Phase 58-07 (StopLadder gap closure)
  - Any future re-verification of Phase 58 PORT-03 and PORT-04 gaps

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TurnoverTracker.track() called per backtest period with old/new weights and gross return"
    - "_load_signal_probabilities: DISTINCT ON (asset_id) ORDER BY t0 DESC for latest probability"
    - "Graceful DB fallback: try/except around cmc_meta_label_results query, default_prob=0.6"
    - "TYPE_CHECKING import for TurnoverTracker to satisfy ruff F821 on string type annotations"
    - "Strategy functions accept **kwargs for forward-compatible signal_probs passthrough"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/portfolio/run_portfolio_backtest.py

key-decisions:
  - "TYPE_CHECKING import for TurnoverTracker: ruff F821 flags string annotations for names not in module scope; TYPE_CHECKING block resolves this cleanly"
  - "tracker.track() called EVERY period (not just rebalance periods): captures zero-turnover periods for complete cost history"
  - "signal_probs passed as kwarg to all strategy functions: topk_dropout uses it directly, others accept **kwargs"
  - "default_prob=0.6 retained as fallback: backward-compatible when cmc_meta_label_results is unpopulated"
  - "_load_signal_probabilities added in Task 1 (not Task 2): needed for module to import cleanly (blocking dependency)"

patterns-established:
  - "DB-sourced signal probability pattern: load once per backtest, pass through to strategy via kwarg"
  - "Decomposed cost reporting: gross_ret / turnover_cost / net_ret printed separately"

# Metrics
duration: 3min
completed: 2026-02-28
---

# Phase 58 Plan 06: TurnoverTracker Wiring + Real Signal Probabilities Summary

**TurnoverTracker wired into _run_backtest() per-period loop with decomposed gross/turnover/net cost reporting, and hardcoded 0.6 probability replaced with per-asset trade_probability from cmc_meta_label_results**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-28T08:44:21Z
- **Completed:** 2026-02-28T08:47:50Z
- **Tasks:** 2/2
- **Files modified:** 1

## Accomplishments

- TurnoverTracker instantiated in `_run_backtest()`, `track()` called every period with old/new weights and gross return for full cost history
- Per-strategy statistics now print decomposed: `gross_ret`, `turnover_cost`, `net_ret` (plus ann_vol, max_dd, n_periods)
- `_load_signal_probabilities()` queries `cmc_meta_label_results` for latest `trade_probability` per asset, with graceful fallback to 0.6 when table is empty or missing
- BetSizer in `_strategy_topk_dropout()` now receives per-asset varying probabilities so high-confidence assets get larger position scales
- Sharpe comparison section unchanged (uses gross returns for apples-to-apples delta)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire TurnoverTracker + decomposed cost reporting** - `65f37725` (feat)
2. **Task 2: Replace hardcoded 0.6 with real trade_probability** - `02c6f7e4` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/portfolio/run_portfolio_backtest.py` - Added TurnoverTracker wiring, _load_signal_probabilities(), decomposed cost stats, signal_probs passthrough to strategies

## Decisions Made

1. **TYPE_CHECKING import for TurnoverTracker**: ruff F821 flags string annotations for names not in module scope. Added `if TYPE_CHECKING: from ta_lab2.portfolio.cost_tracker import TurnoverTracker` to resolve without adding a runtime import at module level.

2. **tracker.track() called every period**: Not just on rebalance periods. When no rebalance occurs, old_weights == new_weights so turnover_pct = 0 and cost_pct = 0. This gives a complete per-period cost history.

3. **_load_signal_probabilities() added in Task 1**: Although the plan assigned it to Task 2, the function was needed for the module to import cleanly after Task 1 changes (run_backtest calls it). Added as a blocking fix (Deviation Rule 3).

4. **default_prob=0.6 retained as fallback**: When `cmc_meta_label_results` is empty or missing, all assets get 0.6 probability. This ensures backward compatibility with databases that haven't run Phase 57.

5. **Strategy kwargs pattern**: `_strategy_topk_dropout` takes explicit `signal_probs` parameter; other strategies accept `**kwargs` so they silently ignore it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added _load_signal_probabilities in Task 1 instead of Task 2**
- **Found during:** Task 1 (TurnoverTracker wiring)
- **Issue:** run_backtest() calls _load_signal_probabilities() which was planned for Task 2, but the module won't import without it after Task 1's changes
- **Fix:** Moved _load_signal_probabilities() into Task 1 commit
- **Files modified:** src/ta_lab2/scripts/portfolio/run_portfolio_backtest.py
- **Verification:** `python -c "from ta_lab2.scripts.portfolio.run_portfolio_backtest import _run_backtest; print('import OK')"` succeeds
- **Committed in:** 65f37725 (Task 1 commit)

**2. [Rule 1 - Bug] Fixed ruff F821 for TurnoverTracker string annotations**
- **Found during:** Task 1 (pre-commit hook)
- **Issue:** `"TurnoverTracker"` in return type annotation and dict type hint flagged as F821 (undefined name) by ruff since it's only imported inside the function body
- **Fix:** Added `TYPE_CHECKING` import block with `from ta_lab2.portfolio.cost_tracker import TurnoverTracker`
- **Files modified:** src/ta_lab2/scripts/portfolio/run_portfolio_backtest.py
- **Verification:** Pre-commit ruff lint passes
- **Committed in:** 65f37725 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep. Task 2 still handled the probability replacement logic.

## Issues Encountered

None beyond the deviations documented above.

## User Setup Required

None. The signal probability loading is fully automatic with graceful fallback. If `cmc_meta_label_results` has no data, the backtest runs exactly as before with 0.6 default probability.

## Next Phase Readiness

- PORT-03 (turnover tracking absent from backtest output) is now CLOSED
- PORT-04 (hardcoded uniform probability defeats bet sizing demonstration) is now CLOSED
- PORT-05 (StopLadder integration) remains open for 58-07 gap closure
- Phase 58 gap closure is 1/2 complete (58-06 done, 58-07 pending)

---
*Phase: 58-portfolio-construction-sizing*
*Completed: 2026-02-28*
