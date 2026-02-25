---
phase: 45-paper-trade-executor
plan: 05
subsystem: executor
tags: [paper-trading, executor, argparse, yaml, subprocess, pipeline, signals]

# Dependency graph
requires:
  - phase: 45-04
    provides: PaperExecutor.run() orchestrator with full signal-to-fill pipeline
  - phase: 45-01
    provides: dim_executor_config DDL and executor DB tables
provides:
  - CLI entry point run_paper_executor.py for standalone executor invocation
  - CLI entry point seed_executor_config.py for seeding dim_executor_config from YAML
  - run_daily_refresh.py --signals flag and run_signal_refreshes() function
  - run_daily_refresh.py --execute and --no-execute flags and run_paper_executor_stage()
  - Complete pipeline: bars -> EMAs -> AMAs -> desc_stats -> regimes -> signals -> executor -> stats
affects: [46-circuit-breakers, daily-automation, cron-scheduling]

# Tech tracking
tech-stack:
  added: [yaml (PyYAML for seed loading)]
  patterns: [ComponentResult subprocess pattern extended to signals and executor stages]

key-files:
  created:
    - src/ta_lab2/scripts/executor/__init__.py
    - src/ta_lab2/scripts/executor/run_paper_executor.py
    - src/ta_lab2/scripts/executor/seed_executor_config.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "run_paper_executor_stage() (not run_paper_executor()) to avoid name collision with the module"
  - "Signal refresher has no --dry-run flag; in dry_run mode we skip but still log the command"
  - "Parent path for default seed file: parents[4] from executor script = project root (ta_lab2/)"
  - "--no-execute skips executor but signals still run in --all mode"
  - "Regime stop-gate added: regimes block was missing continue_on_error guard before signals"

patterns-established:
  - "CLI scripts in scripts/executor/ follow same NullPool + resolve_db_url pattern as other CLIs"
  - "Pipeline stages added to run_daily_refresh.py as ComponentResult subprocess functions"
  - "Default config path computed relative to __file__ using parents[N] indexing"

# Metrics
duration: 7min
completed: 2026-02-25
---

# Phase 45 Plan 05: CLI Entry Points and Pipeline Wiring Summary

**argparse CLIs for standalone executor (--dry-run/--replay-historical) and YAML config seeder (ON CONFLICT DO NOTHING), plus run_daily_refresh.py --signals/--execute/--no-execute flags completing the bars->signals->executor->stats pipeline**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-25T05:32:13Z
- **Completed:** 2026-02-25T05:38:49Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created `run_paper_executor.py`: standalone CLI with `--dry-run`, `--verbose`, `--replay-historical`, `--start`, `--end`; NullPool engine; calls `PaperExecutor.run()`; exits 0/1
- Created `seed_executor_config.py`: loads `configs/executor_config_seed.yaml`, resolves `signal_name`->`signal_id` via `dim_signals`, inserts with `ON CONFLICT DO NOTHING`; warns-and-skips on missing signals
- Wired `run_signal_refreshes()` and `run_paper_executor_stage()` into `run_daily_refresh.py` following established ComponentResult subprocess pattern with `TIMEOUT_SIGNALS=1800` and `TIMEOUT_EXECUTOR=300`
- Added `--signals`, `--execute`, `--no-execute` flags; pipeline order: bars -> EMAs -> AMAs -> desc_stats -> regimes -> signals -> executor -> stats

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CLI scripts for executor and config seeder** - `88388169` (feat)
2. **Task 2: Wire signals and executor into run_daily_refresh.py pipeline** - `2a54e41b` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/ta_lab2/scripts/executor/__init__.py` - Package init for scripts/executor/
- `src/ta_lab2/scripts/executor/run_paper_executor.py` - Standalone CLI for PaperExecutor with argparse, NullPool engine, dry-run/replay-historical modes
- `src/ta_lab2/scripts/executor/seed_executor_config.py` - YAML seed loader for dim_executor_config; resolves signal_name->signal_id; ON CONFLICT DO NOTHING idempotency
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added TIMEOUT_SIGNALS/TIMEOUT_EXECUTOR, run_signal_refreshes(), run_paper_executor_stage(), --signals/--execute/--no-execute flags, updated pipeline wiring and docs

## Decisions Made
- Named the function `run_paper_executor_stage()` (not `run_paper_executor()`) to avoid collision with the module name `ta_lab2.scripts.executor.run_paper_executor`
- In dry_run mode, `run_signal_refreshes()` returns early (signal refresher has no --dry-run support) rather than skipping the print block
- Default seed file path uses `parents[4]` from `__file__` (0=executor/, 1=scripts/, 2=ta_lab2/, 3=src/, 4=project_root/)
- `--no-execute` skips executor but signals still run in `--all` mode (signals are always generated; executor consumption is optional)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added continue_on_error stop-gate for regimes block**
- **Found during:** Task 2 (run_daily_refresh.py wiring)
- **Issue:** The existing regimes block in `main()` was missing its `if not regime_result.success and not args.continue_on_error: return 1` guard. Adding signals and executor after it required this guard to be in place so pipeline stops on regime failure (unless --continue-on-error).
- **Fix:** Added the stop-gate check after `results.append(("regimes", regime_result))`, consistent with all other pipeline stages
- **Files modified:** src/ta_lab2/scripts/run_daily_refresh.py
- **Verification:** `--all --dry-run` runs all stages correctly; stop logic follows established pattern
- **Committed in:** `2a54e41b` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical stop-gate)
**Impact on plan:** Fix necessary for pipeline correctness - regimes stage now properly participates in stop-on-error flow like all other stages.

## Issues Encountered
- Default seed file path used `parents[5]` initially (wrong level) - caught during help text verification; corrected to `parents[4]`

## User Setup Required
None - no external service configuration required. Executor runs against existing DB.

## Next Phase Readiness
- Phase 45 is now complete (5/5 plans done)
- `run_paper_executor --dry-run` works standalone
- `run_daily_refresh --all` runs full pipeline including signals and executor
- Phase 46 (circuit breakers) can hook into executor by reading cmc_executor_run_log and cmc_positions

---
*Phase: 45-paper-trade-executor*
*Completed: 2026-02-25*
