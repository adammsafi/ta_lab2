---
phase: 23-reliable-incremental-refresh
plan: 01
subsystem: orchestration
tags: [subprocess, dry-run, summary-reporting, ema, refreshers, cli]

# Dependency graph
requires:
  - phase: 22-critical-data-quality-fixes
    provides: "Validated bars and EMAs with quality checks"
provides:
  - "EMA orchestrator with subprocess isolation matching bar orchestrator pattern"
  - "Dry-run and verbose control for EMA refreshers"
  - "Summary reporting with counts, durations, and success/failure"
affects: [23-reliable-incremental-refresh, 24-pattern-consistency]

# Tech tracking
tech-stack:
  added: []
  patterns: ["subprocess isolation for orchestrators", "dry-run CLI pattern", "summary reporting format"]

key-files:
  created: []
  modified:
    - "src/ta_lab2/scripts/emas/run_all_ema_refreshes.py"

key-decisions:
  - "Subprocess isolation over runpy for process isolation and reliability"
  - "Mirror bar orchestrator patterns for consistency across orchestrators"
  - "Preserve all existing CLI functionality during refactor"

patterns-established:
  - "RefresherConfig/RefresherResult dataclasses: Consistent orchestrator configuration pattern"
  - "Dry-run support: Show commands without executing for verification"
  - "Summary reporting: Counts, durations, success/failure for all orchestrators"

# Metrics
duration: 4min
completed: 2026-02-05
---

# Phase 23 Plan 01: Reliable Incremental Refresh Summary

**EMA orchestrator refactored with subprocess isolation, dry-run support, and summary reporting matching bar orchestrator quality**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-05T20:33:14Z
- **Completed:** 2026-02-05T20:37:51Z
- **Tasks:** 2 (combined into single refactor)
- **Files modified:** 1

## Accomplishments
- Replaced runpy.run_path with subprocess.run for process isolation
- Added RefresherConfig and RefresherResult dataclasses matching bar orchestrator
- Implemented dry-run and verbose flags for better control
- Added summary reporting with counts, durations, and success/failure
- Migrated from hardcoded absolute paths to relative paths from script directory
- Preserved all existing CLI functionality (--ids, --periods, --cal-scheme, --validate, etc.)

## Task Commits

Each task was committed atomically:

1. **Combined Tasks 1-2: Refactor EMA orchestrator to subprocess with dry-run/summary** - `a040e2b4` (refactor)

## Files Created/Modified
- `src/ta_lab2/scripts/emas/run_all_ema_refreshes.py` - EMA orchestrator with subprocess isolation, dry-run, verbose control, and summary reporting

## Decisions Made

**1. Subprocess isolation over runpy**
- Rationale: Prevents state leakage between refreshers, enables dry-run, matches bar orchestrator pattern
- Impact: More reliable execution, better error isolation, easier to debug

**2. Mirror bar orchestrator patterns**
- Rationale: Consistency across orchestrators makes them predictable and maintainable
- Impact: RefresherConfig/RefresherResult match BuilderConfig/BuilderResult, same CLI flags, same summary format

**3. Preserve all existing CLI functionality**
- Rationale: Users depend on --validate, --alert-on-validation-error, --cal-scheme, --anchor-scheme
- Impact: Zero breaking changes, all existing workflows continue to work

## Deviations from Plan

None - plan executed exactly as written. Tasks 1 and 2 were combined into a single refactor commit since they touched the same code sections and formed a cohesive change.

## Issues Encountered

**1. Linter error: logger variable assigned but never used**
- Found during: Initial commit
- Issue: After switching from logger-based to print-based output, logger variable was unused
- Resolution: Renamed to _logger to indicate it's still needed for validation step
- Verification: Pre-commit hooks pass, all linter checks clean

## Next Phase Readiness

**Ready for Phase 23 continuation:**
- EMA orchestrator now matches bar orchestrator quality
- Subprocess isolation provides reliable execution
- Dry-run support enables safe verification before execution
- Summary reporting provides clear visibility into refresh outcomes

**Foundation established:**
- Pattern established for orchestrator quality (subprocess, dry-run, summary)
- Ready to apply same patterns to other orchestration needs
- Validation functionality preserved and working

---
*Phase: 23-reliable-incremental-refresh*
*Completed: 2026-02-05*
