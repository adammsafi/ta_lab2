---
phase: 46-risk-controls
plan: 03
subsystem: risk
tags: [postgresql, sqlalchemy, risk-controls, override-manager, audit-trail, argparse, unittest-mock]

# Dependency graph
requires:
  - phase: 46-risk-controls/46-01
    provides: cmc_risk_overrides table (UUID PK, sticky/applied_at/reverted_at columns) and cmc_risk_events immutable audit log
  - phase: 46-risk-controls/46-02
    provides: risk/__init__.py package stub, scripts/risk/__init__.py, tests/risk/__init__.py
provides:
  - OverrideManager class: create/apply/revert/list override CRUD with dual audit trail
  - OverrideInfo dataclass: full override lifecycle snapshot
  - override_cli.py: CLI with create/revert/list subcommands and --sticky flag
  - 21 unit tests for OverrideManager covering all lifecycle states (no DB required)
affects:
  - 46-04 and later plans: executor integration point for apply_override + get_pending_non_sticky_overrides auto-revert loop
  - Any plan that processes signals and needs to check for active overrides before generating orders

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual audit trail: every override action touches both state table (cmc_risk_overrides) and immutable log (cmc_risk_events) in one engine.begin() transaction"
    - "Sticky/non-sticky override lifecycle: sticky=False overrides identified by get_pending_non_sticky_overrides() for executor auto-revert after signal cycle"
    - "No-op idempotency: apply_override and revert_override check rowcount=0 and skip event INSERT if already applied/reverted"

key-files:
  created:
    - src/ta_lab2/risk/override_manager.py
    - src/ta_lab2/scripts/risk/override_cli.py
    - tests/risk/test_override_manager.py
  modified:
    - src/ta_lab2/risk/__init__.py

key-decisions:
  - "try/except ImportError in __init__.py for parallel execution: when 46-02 ran concurrently, the __init__.py needed to handle kill_switch/risk_engine not yet present; ruff linter subsequently removed the try/except once those files existed"
  - "No-op on double apply/revert: apply_override with rowcount=0 logs warning and returns without event INSERT; prevents duplicate audit events from executor retry logic"
  - "get_pending_non_sticky_overrides() is executor-facing: sticky=FALSE AND applied_at IS NOT NULL AND reverted_at IS NULL identifies overrides that need auto-revert after the current signal cycle"

patterns-established:
  - "OverrideManager pattern: all mutation methods use engine.begin() for atomicity; all read methods use engine.connect()"
  - "CLI subcommand pattern: matches kill_switch_cli.py -- argparse with subparsers, build_parser() + main() + cmd_*() handlers, NullPool engine"
  - "Mock test pattern for begin() engine: _make_begin_engine(side_effects) for write operations, _make_connect_engine(rows) for read operations"

# Metrics
duration: 20min
completed: 2026-02-25
---

# Phase 46 Plan 03: Override Manager Summary

**OverrideManager CRUD with dual cmc_risk_overrides + cmc_risk_events audit trail, sticky/non-sticky lifecycle, argparse CLI with --sticky flag, and 21 mock-only unit tests covering full state machine.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-02-25T14:38:04Z
- **Completed:** 2026-02-25T14:58:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- OverrideManager class with create/apply/revert/get_active/get_pending_non_sticky/get_override; every write operation is atomic (both tables in one transaction)
- Non-sticky auto-revert support: get_pending_non_sticky_overrides() returns overrides where sticky=FALSE AND applied_at IS NOT NULL AND reverted_at IS NULL -- the executor calls this after each signal cycle to snap back non-sticky overrides
- override_cli.py with create (--sticky flag), revert, and list subcommands, tabular output for list; matches kill_switch_cli.py pattern exactly
- 21 unit tests in 7 test classes; all pass without database (unittest.mock only); full risk test suite 50/50 passing

## Task Commits

Both tasks were incorporated into HEAD commits as plan 46-02 ran concurrently:

1. **Task 1: Implement OverrideManager class** - `190b0b81` (feat -- override_manager.py) / `fcd25068` (__init__.py update with OverrideManager exports)
2. **Task 2: Create override CLI and unit tests** - `fcd25068` (feat -- override_cli.py + test_override_manager.py)

Note: Plan 46-02 ran concurrently and committed override_manager.py + override_cli.py + test_override_manager.py in its second commit (fcd25068). This is the expected parallel execution outcome documented in the plan's IMPORTANT note.

## Files Created/Modified
- `src/ta_lab2/risk/override_manager.py` - OverrideInfo dataclass + OverrideManager with 6 methods; dual audit trail; sticky/non-sticky support
- `src/ta_lab2/risk/__init__.py` - Added OverrideManager and OverrideInfo to package exports
- `src/ta_lab2/scripts/risk/override_cli.py` - argparse CLI with create/revert/list subcommands; --sticky flag; tabular list output
- `tests/risk/test_override_manager.py` - 21 unit tests in 7 classes covering all OverrideManager lifecycle states

## Decisions Made
- **try/except in __init__.py for parallel plan compatibility:** Initially added try/except ImportError to handle the case where 46-02 was still running. The ruff formatter subsequently removed it once 46-02's files were on disk. End state: direct imports work correctly.
- **No-op idempotency with rowcount check:** apply_override and revert_override check `result.rowcount == 0` and skip the event INSERT if already applied/reverted. This prevents duplicate audit events if the executor retries (no DB unique constraint on events).
- **Executor-facing non-sticky query:** get_pending_non_sticky_overrides() is the integration point for the signal execution loop -- executor calls this at end of each cycle, reverts each result with operator="system" and reason="Auto-revert after signal cycle".
- **Free-form override_action values:** No validation of override_action in Python code (matches the DDL decision from 46-01 to use free-text without a CHECK constraint). Application validation, if needed, belongs in the CLI or executor.

## Deviations from Plan

### Parallel Execution Coordination

**1. [Coordination] Plan 46-02 committed override_manager.py and override_cli.py concurrently**
- **Found during:** Task 1 commit
- **Issue:** Plan 46-02 ran in parallel and committed `override_manager.py`, `override_cli.py`, and `test_override_manager.py` in its final commit (`fcd25068`) before this plan could make its own commit.
- **Fix:** Verified that the committed files match the implementation specified in this plan's task descriptions. All verification checks pass. No duplicate work or conflicts.
- **Impact:** The files created in this plan are identical to what's committed. The per-task atomic commits from this plan are reflected in 46-02's commits rather than separate 46-03 commits.

---

**Total deviations:** 1 (coordination -- not a code issue, parallel execution as designed)
**Impact on plan:** No scope creep. All plan requirements met. Files committed, tests pass.

## Issues Encountered
- Pre-commit hooks (ruff, mixed-line-ending) modified files and conflicted with pre-commit's internal stash mechanism on Windows (a known Windows pre-commit limitation). The concurrent execution of plan 46-02 resolved this by picking up and committing the pre-commit-formatted versions of all files in its final commit.

## User Setup Required
None - no external service configuration required. override_cli.py uses the same db_config.env resolution as all other CLIs.

## Next Phase Readiness
- OverrideManager is fully operational; plan 46-04 (executor integration) can call:
  - `mgr.get_active_overrides(asset_id, strategy_id)` to check for active overrides before processing signals
  - `mgr.apply_override(override_id)` when acting on an override
  - `mgr.get_pending_non_sticky_overrides()` at end of signal cycle for auto-revert
  - `mgr.revert_override(id, reason="Auto-revert after signal cycle", operator="system")` for each pending non-sticky override
- CLI available for operator use: `python -m ta_lab2.scripts.risk.override_cli create/revert/list`
- No blockers for subsequent phases

---
*Phase: 46-risk-controls*
*Completed: 2026-02-25*
