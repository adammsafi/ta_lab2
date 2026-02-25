---
phase: 47-drift-guard
plan: 05
subsystem: drift
tags: [cli, argparse, subprocess, pipeline, drift-guard, nullpool, integration-tests]

# Dependency graph
requires:
  - phase: 47-03
    provides: DriftMonitor orchestrator
  - phase: 47-04
    provides: DriftAttributor + ReportGenerator
  - phase: 29-01
    provides: run_daily_refresh.py ComponentResult + subprocess stage pattern

provides:
  - run_drift_monitor.py CLI (daily drift check, --paper-start required, --dry-run/--verbose/--db-url)
  - run_drift_report.py CLI (weekly report, --week-start/--week-end/--output-dir/--with-attribution)
  - run_daily_refresh.py wired with --drift/--no-drift/--paper-start flags + run_drift_monitor_stage()
  - TIMEOUT_DRIFT = 600s constant
  - 10 new integration tests in tests/drift/test_cli_drift.py
  - 58 total drift tests passing (Phase 47 complete)

affects:
  - Phase 52 (operational dashboard -- drift stage is now in pipeline)
  - Phase 55 (evaluation pipeline builds on same --all orchestration)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CLI subprocess stage pattern: run_drift_monitor_stage mirrors run_paper_executor_stage exactly (NullPool, dry-run skip, TimeoutExpired handler)"
    - "Optional gate pattern: run_drift and paper_start both required; drift silently skipped when paper_start is None"
    - "Deferred import pattern: from ta_lab2.drift import X inside try block avoids heavy imports at CLI parse time"

key-files:
  created:
    - src/ta_lab2/scripts/drift/__init__.py
    - src/ta_lab2/scripts/drift/run_drift_monitor.py
    - src/ta_lab2/scripts/drift/run_drift_report.py
    - tests/drift/test_cli_drift.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py
    - src/ta_lab2/drift/__init__.py

key-decisions:
  - "Weekly report is NOT wired into --all: invoked manually or from cron; too compute-heavy for daily pipeline"
  - "--paper-start is optional in run_daily_refresh.py: allows --all to run without drift every day; drift stage silently skipped when absent"
  - "run_drift_report.py accepts --with-attribution: the only way attr_* columns get populated; compute-heavy (7 replays/config)"
  - "Drift stage position: after executor (needs fills), before stats (stats should see current state)"

patterns-established:
  - "Pipeline stage pattern: TIMEOUT_DRIFT + run_drift_monitor_stage + ComponentResult return; mirrors existing run_paper_executor_stage"
  - "Optional gate pattern: `if run_drift and paper_start:` guards stage; `elif run_drift and not paper_start: print skip message`"

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 47 Plan 05: CLI Entry Points + Pipeline Wiring Summary

**Drift monitoring made operational: run_drift_monitor.py CLI, run_drift_report.py CLI, and run_daily_refresh.py --drift/--paper-start pipeline wiring with 58 tests passing**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-25T19:45:23Z
- **Completed:** 2026-02-25T19:50:49Z
- **Tasks:** 3
- **Files modified:** 6 (4 created, 2 modified)

## Accomplishments

- Created `run_drift_monitor.py` CLI: daily drift check entry point with --paper-start (required), --dry-run, --verbose, --db-url; uses NullPool + deferred DriftMonitor import
- Created `run_drift_report.py` CLI: weekly report generator with --week-start/--week-end/--output-dir/--with-attribution; --with-attribution runs DriftAttributor per config and passes paper_trade_count
- Wired drift monitor into `run_daily_refresh.py` as a new pipeline stage: TIMEOUT_DRIFT=600, run_drift_monitor_stage(), --drift/--no-drift/--paper-start args, positioned after executor and before stats
- --paper-start is optional in the orchestrator: drift stage silently skipped when absent, enabling --all to run without drift monitoring every day
- 10 new integration tests (help smoke, import/callable, command-build, dry-run skip, timeout handling, skip-without-paper-start) + all 58 total drift tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CLI scripts for drift monitor and report** - `d4b72daa` (feat)
2. **Task 2: Wire drift monitor into run_daily_refresh.py + integration tests** - `3bffa76f` (feat)
3. **Task 3: Package exports and full test suite verification** - `f6fcbd0c` (feat)

## Files Created/Modified

- `src/ta_lab2/scripts/drift/__init__.py` - Package init for scripts/drift directory
- `src/ta_lab2/scripts/drift/run_drift_monitor.py` - Daily drift check CLI (130 lines)
- `src/ta_lab2/scripts/drift/run_drift_report.py` - Weekly report generator CLI (215 lines)
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added TIMEOUT_DRIFT, run_drift_monitor_stage(), --drift/--no-drift/--paper-start flags, stage wiring
- `src/ta_lab2/drift/__init__.py` - Updated docstring to Phase 47 package description
- `tests/drift/test_cli_drift.py` - 10 integration tests for CLIs and pipeline stage

## Decisions Made

- **Weekly report not in --all pipeline:** The weekly digest is too compute-heavy (7 replays per config per attribution run) for daily automation. Research decision "Weekly digest NOT in --all" honored. `run_drift_report.py` is manual/cron only.
- **--paper-start optional in orchestrator:** Allows `--all` to run normally without always requiring a paper-trading start date. Drift stage silently skipped when absent. Drift stage requires explicit `--drift --paper-start DATE` (or `--all --paper-start DATE`).
- **Drift stage position after executor, before stats:** Drift needs paper fills (written by executor), and stats should observe current state after all writes.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hooks (ruff format + mixed-line-ending) reformatted files on first commit attempt. Standard pattern for this repo on Windows -- re-staged after hook fixes and committed cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 47 (Drift Guard) is now COMPLETE: all 5 plans done, 58 tests passing, 0 ruff violations
- Drift monitoring is operational: `python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start DATE` for daily use
- Weekly reports: `python -m ta_lab2.scripts.drift.run_drift_report --output-dir reports/drift`
- Daily pipeline integration: `python -m ta_lab2.scripts.run_daily_refresh --all --paper-start DATE`
- No blockers for Phase 48 or subsequent phases

---
*Phase: 47-drift-guard*
*Completed: 2026-02-25*
