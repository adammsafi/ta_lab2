---
phase: 49-tail-risk-policy
plan: 02
subsystem: risk
tags: [tail-risk, escalation, flatten-trigger, risk-engine, circuit-breaker, vol-spike, correlation]

# Dependency graph
requires:
  - phase: 49-01
    provides: dim_risk_state.tail_risk_state column (CHECK normal/reduce/flatten) + 3 audit columns + extended cmc_risk_events CHECK constraints
provides:
  - flatten_trigger.py: pure evaluation module with 4-trigger priority check returning EscalationState
  - RiskEngine.check_tail_risk_state(): reads tail_risk_state from dim_risk_state
  - RiskEngine.check_order(): Gate 1.5 -- FLATTEN blocks all orders, REDUCE halves buy qty
  - RiskEngine.evaluate_tail_risk_state(): daily evaluation with 21d/14d cooldown + 3-consecutive-day vol clear
  - ta_lab2.risk package: 13 exported symbols including EscalationState, FlattenTriggerResult, check_flatten_trigger
affects:
  - 49-03, 49-04: downstream plans that wire evaluate_tail_risk_state into daily refresh
  - paper trading executor: Gate 1.5 now enforced on every check_order() call

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure trigger evaluation module pattern: no DB/numpy deps, pure Python function returning typed result"
    - "TYPE_CHECKING guard for forward reference: avoids circular import while satisfying ruff F821"
    - "Gate 1.5 pattern: tail risk state inserted between kill switch and circuit breaker in check_order()"
    - "Cooldown + vol-clear de-escalation: dual requirement prevents premature state clearing"

key-files:
  created:
    - src/ta_lab2/risk/flatten_trigger.py
  modified:
    - src/ta_lab2/risk/risk_engine.py
    - src/ta_lab2/risk/__init__.py
    - tests/risk/test_risk_engine.py
    - tests/risk/test_integration.py

key-decisions:
  - "TYPE_CHECKING guard for FlattenTriggerResult return type -- avoids circular import while satisfying ruff F821"
  - "Test mock sequences updated with tail_risk_state result after kill switch check (not new tests -- existing tests updated)"
  - "De-escalation uses 3-consecutive trailing windows computed from 23 bars (most recent 3 x 20d windows overlap by 19 bars)"

patterns-established:
  - "Tail risk priority ordering: exchange halt > abs_return > vol_spike (3sig) > corr_breakdown > vol_spike (2sig) > normal"
  - "Gate numbering: 1=kill_switch, 1.5=tail_risk, 2=circuit_breaker, 3=pos_cap, 4=portfolio_cap, 5=all_pass"

# Metrics
duration: 8min
completed: 2026-02-25
---

# Phase 49 Plan 02: Tail-Risk Policy (Core Logic) Summary

**flatten_trigger.py pure evaluation module with 4 priority-ordered triggers + RiskEngine Gate 1.5 enforcing FLATTEN/REDUCE state + evaluate_tail_risk_state daily cooldown logic requiring 21d/14d cooldown AND 3 consecutive vol-clear days before de-escalation**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-25T21:24:45Z
- **Completed:** 2026-02-25T21:33:17Z
- **Tasks:** 2
- **Files modified:** 5 (1 created, 4 modified)

## Accomplishments

- Created `flatten_trigger.py` pure evaluation module: EscalationState enum, FlattenTriggerResult dataclass, check_flatten_trigger() with 4 trigger types in priority order (exchange halt > abs return > vol spike 3-sigma > correlation breakdown > vol spike 2-sigma > normal) using BTC-calibrated thresholds
- Extended RiskEngine with Gate 1.5: `check_tail_risk_state()` reads dim_risk_state, `check_order()` enforces FLATTEN (block) and REDUCE (halve buy qty) state
- Implemented `evaluate_tail_risk_state()` for daily tail risk evaluation with dual de-escalation gate: 21-day cooldown (flatten) or 14-day cooldown (reduce) AND 3 consecutive days of 20d rolling vol below 9.23% reduce threshold
- Updated `ta_lab2.risk` package to export 13 symbols including the 3 new flatten_trigger symbols
- Fixed 13 failing unit/integration tests by updating mock call sequences to include Gate 1.5 DB call

## Task Commits

Each task was committed atomically:

1. **Task 1: Flatten trigger module** - `a63c1c42` (feat)
2. **Task 2: RiskEngine extension with Gate 1.5 and evaluate_tail_risk_state** - `0ee3364f` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/risk/flatten_trigger.py` - Pure trigger evaluation: EscalationState, FlattenTriggerResult, check_flatten_trigger() with 4 priority-ordered triggers and calibrated BTC thresholds
- `src/ta_lab2/risk/risk_engine.py` - Extended with check_tail_risk_state(), Gate 1.5 in check_order(), evaluate_tail_risk_state() with cooldown logic; TYPE_CHECKING import for FlattenTriggerResult
- `src/ta_lab2/risk/__init__.py` - Added flatten_trigger imports, 13 total exports
- `tests/risk/test_risk_engine.py` - Updated 6 tests: added tail_risk_normal mock result after kill switch in side_effect sequences
- `tests/risk/test_integration.py` - Updated 5 tests: added _tail_risk_normal() helper + updated CB/position/all-gates test sequences

## Decisions Made

- **TYPE_CHECKING guard for FlattenTriggerResult**: Used `from typing import TYPE_CHECKING` with a guarded import block rather than a full module-level import, avoiding circular imports. The function body uses deferred `from ta_lab2.risk.flatten_trigger import ...` which works correctly at runtime.
- **De-escalation uses 23-bar window for 3-consecutive vol check**: Computing 20d rolling vol for 3 trailing days requires offsets [0:20], [1:21], [2:22] in the sorted-descending returns array, so 23 rows total.
- **Test updates are planned work**: Inserting Gate 1.5 into an existing gate sequence means all existing tests with active-state orders needed one additional mock result. Updated 13 tests across test_risk_engine.py and test_integration.py.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TYPE_CHECKING guard required for FlattenTriggerResult forward reference**

- **Found during:** Task 2 commit (ruff F821 error)
- **Issue:** Using `"FlattenTriggerResult"` as a string return type annotation raised ruff F821 even with `from __future__ import annotations`, because the string was not defined in the local scope
- **Fix:** Added `from typing import TYPE_CHECKING` and a guarded `if TYPE_CHECKING:` block importing FlattenTriggerResult from flatten_trigger; the actual runtime import remains deferred inside the method body
- **Files modified:** src/ta_lab2/risk/risk_engine.py
- **Verification:** ruff lint passes, all 82 tests pass
- **Committed in:** 0ee3364f (part of Task 2 commit)

**2. [Rule 1 - Bug] 13 existing tests failed after Gate 1.5 insertion**

- **Found during:** Task 2 verification (regression test run)
- **Issue:** All test mock `side_effect` sequences for `check_order()` calls that passed Gate 1 were missing the Gate 1.5 `SELECT tail_risk_state` DB call
- **Fix:** Added `tail_risk_normal_row()` / `_tail_risk_normal()` helper in both test files and inserted it as the second item in every affected test's mock sequence
- **Files modified:** tests/risk/test_risk_engine.py, tests/risk/test_integration.py
- **Verification:** 82/82 tests pass
- **Committed in:** 0ee3364f (part of Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - Bug)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered

None beyond the ruff lint issue and test regression, both handled as Rule 1 auto-fixes above.

## Next Phase Readiness

- flatten_trigger.py and RiskEngine tail risk extension are complete and tested
- Gate 1.5 is live in check_order() -- paper trading executor will automatically enforce FLATTEN/REDUCE states
- evaluate_tail_risk_state() is ready to be wired into run_daily_refresh.py (Phase 49-03 or 49-04)
- All 82 existing risk tests pass; no regressions

---
*Phase: 49-tail-risk-policy*
*Completed: 2026-02-25*
