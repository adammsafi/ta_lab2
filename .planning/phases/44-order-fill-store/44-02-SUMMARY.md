---
phase: 44-order-fill-store
plan: 02
subsystem: trading
tags: [decimal, position-math, tdd, pure-function, netting, position-tracking]

# Dependency graph
requires:
  - phase: 44-order-fill-store
    provides: "Phase research and context (NautilusTrader net-quantity pattern)"
provides:
  - "compute_position_update() pure function in position_math.py"
  - "Trading package __init__.py"
  - "16-test suite covering all 12 plan cases plus type/key/precision checks"
affects:
  - "44-03 (OrderManager class -- imports compute_position_update)"
  - "45-fill-simulator (will call OrderManager which calls position_math)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD RED-GREEN-REFACTOR cycle for pure financial math functions"
    - "Decimal-only arithmetic for position tracking (no float)"
    - "Net-quantity NETTING pattern for position flip detection"
    - "fill_qty sign (not new_qty sign) determines add vs reduce"

key-files:
  created:
    - src/ta_lab2/trading/__init__.py
    - src/ta_lab2/trading/position_math.py
    - tests/trading/__init__.py
    - tests/trading/test_position_math.py
  modified: []

key-decisions:
  - "Use fill_qty sign (not new_qty sign) to distinguish add vs reduce -- avoids misclassifying partial closes as additions"
  - "Partial close preserves current_avg_cost unchanged -- only flip and new positions set avg_cost = fill_price"
  - "All 4 branches explicit: new position / add / partial close / flip -- no implicit fallthrough"

patterns-established:
  - "Pattern: fill_adds_to_position = (current_qty > 0) == (fill_qty > 0) -- correct add detection"
  - "Pattern: is_flip = (current_qty > 0) != (new_qty > 0) -- correct flip detection after computing new_qty"

# Metrics
duration: 3min
completed: 2026-02-25
---

# Phase 44 Plan 02: Position Math Summary

**compute_position_update() pure function with Decimal arithmetic implementing NautilusTrader net-quantity NETTING model -- handles new position, add, partial close, full close, and long/short flips correctly**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-25T04:32:19Z
- **Completed:** 2026-02-25T04:35:37Z
- **Tasks:** 1 TDD task (RED + GREEN + partial refactor inline)
- **Files modified:** 4 created

## Accomplishments
- `compute_position_update()` pure function handles all 5 position scenarios with exact Decimal arithmetic
- 16 tests pass covering all 12 plan cases plus type/key/precision guards
- Correctly identified and fixed sign-check bug during GREEN phase (fill_qty sign, not new_qty sign, determines add vs reduce)
- Zero float usage in position_math.py confirmed by grep

## Task Commits

Each task was committed atomically:

1. **RED Phase: Failing tests** - `20d63c54` (test)
2. **GREEN Phase: Implementation** - `66d0de50` (feat)

_TDD task: 2 commits (test -> feat)_

## Files Created/Modified
- `src/ta_lab2/trading/__init__.py` - Trading package init (1 line docstring)
- `src/ta_lab2/trading/position_math.py` - compute_position_update() pure function (120 lines)
- `tests/trading/__init__.py` - Test package init (empty)
- `tests/trading/test_position_math.py` - 16 test cases (360 lines)

## Decisions Made

**fill_qty sign (not new_qty sign) determines add vs reduce:**

Initial implementation checked `same_direction = (current_qty > 0) == (new_qty > 0)` to detect adds. This caused a bug: partial close long 100 / sell 30 = long 70 has both current_qty and new_qty positive, so the check classified it as "add" and computed a weighted average cost instead of keeping the unchanged cost basis.

The correct check is `fill_adds_to_position = (current_qty > 0) == (fill_qty > 0)` -- if the fill is in the same direction as the current position, it's adding; otherwise it's reducing/flipping.

**Explicit 4-branch structure over single return at end:**

After computing realized PnL in the close/flip branch, an additional `is_flip` check distinguishes partial close (preserve avg_cost) from flip (set avg_cost = fill_price). This explicit branching makes the algorithm auditable and correct without implicit fallthrough logic.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed case 2 (add) condition using fill_qty sign instead of new_qty sign**

- **Found during:** GREEN phase (first run of tests)
- **Issue:** `same_direction = (current_qty > 0) == (new_qty > 0)` misclassified partial closes as additions because partial close preserves the position direction (long stays long, short stays short). Cases 5, 7, 11 failed.
- **Fix:** Changed to `fill_adds_to_position = (current_qty > 0) == (fill_qty > 0)` -- only true when fill is buying into a long or selling into a short. Added explicit `is_flip` check in Case 3 to distinguish partial close from flip.
- **Files modified:** `src/ta_lab2/trading/position_math.py`
- **Verification:** All 16 tests pass after fix
- **Committed in:** `66d0de50` (GREEN phase feat commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Fix was essential for correctness. Logic now matches NautilusTrader NETTING specification exactly. No scope creep.

## Issues Encountered

- Pre-commit hooks (mixed-line-ending) required re-staging files twice (once for RED commit, once for GREEN commit). Standard Windows CRLF handling -- expected and documented in project history.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `compute_position_update()` is ready for import by `OrderManager` in Plan 44-03
- Import path: `from ta_lab2.trading.position_math import compute_position_update`
- Function signature matches Plan 44-03's RESEARCH.md OrderManager design exactly
- No blockers for Plan 44-03

---
*Phase: 44-order-fill-store*
*Completed: 2026-02-25*
