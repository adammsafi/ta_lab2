---
phase: 34-audit-cleanup
plan: 01
subsystem: docs
tags: [documentation, cli, argparse, changelog, python-version, daily-refresh]

# Dependency graph
requires:
  - phase: 32-runbooks
    provides: operational runbooks documented in docs/operations/
  - phase: 33-alembic-migrations
    provides: Alembic framework with baseline revision 25f2b3c90f65
  - phase: 29-stats-qa-orchestration
    provides: stats runners and weekly digest wired into run_daily_refresh.py
  - phase: 27-regime-integration
    provides: regime refresher and --regimes flag in run_daily_refresh.py
provides:
  - DAILY_REFRESH.md documents all current orchestrator flags and 4-stage execution order
  - CHANGELOG.md [0.8.0] section complete with Phase 32 and Phase 33 entries
  - run_daily_refresh.py --no-telegram flag properly declared in argparse
  - CONTRIBUTING.md recommends Python 3.12 matching CI and ruff target-version
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Argparse --no-telegram forwarding pattern: declare flag in orchestrator, forward via getattr to subprocess"

key-files:
  created: []
  modified:
    - docs/operations/DAILY_REFRESH.md
    - docs/CHANGELOG.md
    - src/ta_lab2/scripts/run_daily_refresh.py
    - CONTRIBUTING.md

key-decisions:
  - "No new code patterns -- all 4 changes are doc/CLI accuracy fixes against shipped v0.8.0 system"

patterns-established: []

# Metrics
duration: 2min
completed: 2026-02-23
---

# Phase 34 Plan 01: Audit Cleanup Summary

**v0.8.0 tech debt closure: DAILY_REFRESH.md updated for 4-stage pipeline, CHANGELOG v0.8.0 completed with Phase 32/33, --no-telegram argparse gap fixed, CONTRIBUTING.md aligned to Python 3.12**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-23T19:02:19Z
- **Completed:** 2026-02-23T19:04:30Z
- **Tasks:** 4
- **Files modified:** 4

## Accomplishments
- DAILY_REFRESH.md now documents the full 4-stage orchestrator (bars -> EMAs -> regimes -> stats) with all current flags including --regimes, --stats, --weekly-digest, and --no-regime-hysteresis
- CHANGELOG.md [0.8.0] section completed with Phase 32 (runbooks) and Phase 33 (Alembic) entries, making the release record accurate
- run_daily_refresh.py --no-telegram flag declared in argparse so it is no longer silently ignored when passed via CLI
- CONTRIBUTING.md Python version recommendation updated from 3.11 to 3.12, matching CI matrix and ruff target-version (py312)

## Task Commits

Each task was committed atomically:

1. **Task 1: Update DAILY_REFRESH.md to reflect current orchestrator** - `6245be18` (docs)
2. **Task 2: Add Phase 32 and Phase 33 entries to CHANGELOG.md** - `045ef435` (docs)
3. **Task 3: Add --no-telegram argparse declaration to run_daily_refresh.py** - `e3e38982` (feat)
4. **Task 4: Update CONTRIBUTING.md Python version recommendation to 3.12** - `f60f1582` (docs)

**Plan metadata:** (see final docs commit)

## Files Created/Modified
- `docs/operations/DAILY_REFRESH.md` - Added --regimes/--stats/--weekly-digest/--no-regime-hysteresis flags, Regimes and Stats execution order subsections, updated --all description, 4-component summary example, Telegram alerts note for stats and weekly digest
- `docs/CHANGELOG.md` - Added Phase 32 (runbooks) and Phase 33 (Alembic) bullet points to [0.8.0] ### Added section
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added `--no-telegram` argparse declaration after `--no-regime-hysteresis`
- `CONTRIBUTING.md` - Changed "3.11" to "3.12" in two locations (dev setup and code style sections)

## Decisions Made
None - followed plan as specified. All 4 changes are straightforward accuracy fixes with no design decisions required.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- v0.8.0 audit cleanup complete. All 4 tech debt items closed.
- No blockers for next phase.

---
*Phase: 34-audit-cleanup*
*Completed: 2026-02-23*
