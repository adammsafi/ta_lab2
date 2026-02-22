---
phase: 29-stats-qa-orchestration
plan: 02
subsystem: infra
tags: [stats, orchestration, pipeline, subprocess, telegram, data-quality]

# Dependency graph
requires:
  - phase: 29-01
    provides: Subprocess timeout pattern (TIMEOUT_STATS=3600, TimeoutExpired handling) -- pattern reused directly
  - phase: 27-regime-integration
    provides: run_daily_refresh.py --regimes flag -- pipeline chain to extend with --stats

provides:
  - run_all_stats_runners.py: stats orchestrator calling all 6 runners with DB aggregate query and Telegram alerting
  - --stats flag on run_daily_refresh.py: standalone stats-only mode
  - Stats as 4th/final stage in --all pipeline
  - Pipeline gate: FAIL status halts pipeline with return 1 (always terminal, ignores --continue-on-error)
  - TIMEOUT_STATS = 3600 module-level constant in run_daily_refresh.py

affects:
  - 29-03: stats runners are now wired; plan 03 can verify end-to-end stats pipeline with live DB
  - 30-code-quality-tooling: ruff will sweep new stats orchestrator code (run_all_stats_runners.py)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stats orchestrator pattern: run all N runners to completion, then query DB for aggregate PASS/WARN/FAIL"
    - "Pipeline gate pattern: stats FAIL always halts with return 1, ignores --continue-on-error"
    - "Telegram alerting in orchestrator: critical on FAIL, warning on WARN, silent on PASS"

key-files:
  created:
    - src/ta_lab2/scripts/stats/__init__.py
    - src/ta_lab2/scripts/stats/run_all_stats_runners.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "Stats exit code semantics: run_all_stats_runners.py exits 1 for FAIL (DB rows), 0 for PASS/WARN -- run_daily_refresh.py checks exit code for pipeline gate"
  - "DB query is authoritative for FAIL/WARN: stats runners exit 0 even when they write FAIL rows -- orchestrator must query DB after all runners complete"
  - "Pipeline gate is unconditional: stats FAIL always halts even with --continue-on-error because continuing past bad data is worse than stopping"
  - "Telegram alerting is internal to stats orchestrator: run_daily_refresh.py only checks exit code, not alert state"

patterns-established:
  - "All-complete-then-query: run all N subprocess runners to completion before querying DB for aggregate status"
  - "Exit code as pipeline signal: subprocess exits 1 = FAIL (gate), 0 = PASS or WARN (gate-free, Telegram sent)"

# Metrics
duration: 4min
completed: 2026-02-22
---

# Phase 29 Plan 02: Stats Runner Orchestrator Summary

**Stats wired as the 4th pipeline stage in run_daily_refresh.py -- run_all_stats_runners.py calls all 6 runners via subprocess, queries DB for aggregate PASS/WARN/FAIL, sends Telegram alerts, and exits 1 on FAIL to gate the pipeline**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-22T22:03:28Z
- **Completed:** 2026-02-22T22:07:26Z
- **Tasks:** 2/2
- **Files created/modified:** 3

## Accomplishments
- New `src/ta_lab2/scripts/stats/run_all_stats_runners.py` (550+ lines) with StatsScript dataclass, ALL_STATS_SCRIPTS list (6 runners), run_stats_script(), query_stats_status(), send_stats_alerts(), run_all_stats(), and main()
- Stats runners invoked via `-m module` pattern for clean subprocess isolation (same as signal generators)
- DB aggregate query checks all 6 stats tables for PASS/WARN/FAIL counts in last 2-hour window after all runners complete
- Telegram alerts: critical severity on FAIL, warning on WARN, silent on PASS
- `run_daily_refresh.py --stats` runs stats as standalone component
- `run_daily_refresh.py --all` now runs bars -> EMAs -> regimes -> stats (4 stages)
- Pipeline gate: non-zero exit from stats subprocess triggers `return 1` with [PIPELINE GATE] message -- unconditional halt

## Task Commits

Each task was committed atomically:

1. **Task 1: Create stats runner orchestrator** - `ea9e8cb9` (feat)
2. **Task 2: Wire --stats flag into run_daily_refresh.py with pipeline gating** - `7d884086` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/ta_lab2/scripts/stats/__init__.py` - Package marker
- `src/ta_lab2/scripts/stats/run_all_stats_runners.py` - Stats orchestrator (6 runners, DB query, Telegram alerts, exit code gating)
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added TIMEOUT_STATS=3600, run_stats_runners(), --stats flag, stats as 4th pipeline stage, pipeline gate block

## Decisions Made
- **Exit code semantics for DB status:** run_all_stats_runners.py exits 1 for FAIL (FAIL rows in DB or crashed runners), 0 for PASS or WARN -- clean binary for pipeline gate; WARN triggers Telegram but doesn't halt
- **DB query is authoritative:** Stats runners exit 0 even when they write FAIL rows to the DB (by design, they report via DB not exit code); orchestrator must explicitly query DB after all runners complete
- **Pipeline gate unconditional:** Stats FAIL always halts even with --continue-on-error; continuing past bad data is operationally worse than stopping; this differs from bars/EMAs which respect --continue-on-error
- **Telegram alerting internal to stats orchestrator:** run_daily_refresh.py only checks exit code; Telegram logic stays in run_all_stats_runners.py for cohesion

## Deviations from Plan

None - plan executed exactly as written. Pre-commit hook reformatted both files (ruff format), re-staged and committed on second attempt as expected.

## Issues Encountered
- ruff format pre-commit hook reformatted both Task 1 and Task 2 files on first commit attempt (long line wrapping). Re-staged after auto-format, committed successfully on second attempt. Expected behavior from established pre-commit setup.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- STAT-01 satisfied: `--stats` wired into standalone and `--all` pipeline
- STAT-03 satisfied: FAIL halts pipeline with alert, WARN continues with alert
- Plan 29-03 can now run live verification against the database to confirm stats runners execute correctly end-to-end
- No blockers for Phase 30 (ruff sweep of run_all_stats_runners.py will be included)

---
*Phase: 29-stats-qa-orchestration*
*Completed: 2026-02-22*
