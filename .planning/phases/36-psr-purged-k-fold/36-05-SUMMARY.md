---
phase: 36-psr-purged-k-fold
plan: 05
subsystem: infra
tags: [alembic, migrations, sqlalchemy, nullpool, daily-refresh]

# Dependency graph
requires:
  - phase: 36-01
    provides: Alembic migration files (psr_column_rename, psr_results_table) that this check validates

provides:
  - alembic_utils.py with is_alembic_head() and check_migration_status() functions
  - run_daily_refresh.py startup migration check (advisory, non-blocking)

affects: [all future phases that add Alembic migrations, run_daily_refresh users]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Advisory migration check: NullPool engine, try/except wrapper, warn-only (never auto-upgrade)"
    - "Startup gate pattern: check after resolve_db_url(), before refresh steps, skip in dry-run"

key-files:
  created:
    - src/ta_lab2/scripts/alembic_utils.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "Warn-only (never auto-upgrade) to avoid leaving DB in inconsistent state mid-migration"
  - "NullPool for DB connection in migration check (matches project pattern for one-shot connections)"
  - "Migration check skipped in --dry-run mode (no DB connection needed)"
  - "Full try/except wrapper: migration check failure never crashes the pipeline"
  - "ini_path defaults to project root/alembic.ini resolved relative to scripts/ directory"

patterns-established:
  - "alembic_utils pattern: advisory check module with graceful error handling"

# Metrics
duration: 7min
completed: 2026-02-24
---

# Phase 36 Plan 05: Alembic Migration Status Check Summary

**Advisory Alembic migration checker (alembic_utils.py) with NullPool engine, warn-only logic, and startup integration in run_daily_refresh.py**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-02-24T00:12:36Z
- **Completed:** 2026-02-24T00:19:00Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments

- Created `alembic_utils.py` with `is_alembic_head()` and `check_migration_status()` -- 164 lines
- `check_migration_status()` resolves alembic.ini from project root, uses NullPool, logs INFO when at head and WARNING with upgrade instructions when behind
- Wired `check_migration_status()` into `run_daily_refresh.py` startup -- after `resolve_db_url()`, before any refresh steps, skipped in `--dry-run` mode

## Task Commits

Each task was committed atomically:

1. **Task 1: Create alembic_utils.py migration checker** - `3f3d1243` (feat)
2. **Task 2: Wire migration check into run_daily_refresh.py** - `c1960220` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/alembic_utils.py` - New module: `is_alembic_head()` returns bool, `check_migration_status()` wraps with logging, both wrapped in try/except
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added import + startup migration check call (9 lines added)

## Decisions Made

- **Warn-only, not auto-upgrade**: RESEARCH pitfall 6 says auto-upgrade risks leaving DB in inconsistent state. Check is advisory -- logs warning with `alembic upgrade head` instructions.
- **NullPool**: Matches project pattern for one-shot connections in scripts (avoids connection pooling overhead).
- **Skip in dry-run**: Migration check connects to DB; dry-run mode should require no live DB.
- **Graceful error handling**: `try/except` wraps the entire function body so alembic.ini missing, DB unreachable, or import error never crashes the pipeline.
- **ini_path resolution**: `scripts/ -> ta_lab2/ -> src/ -> project_root/alembic.ini` traversal is explicit and testable.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hooks (`ruff-format` + `mixed-line-ending`) reformatted `alembic_utils.py` on first commit attempt. Re-staged and committed successfully on second attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Migration check is now integrated; any future Alembic migration added to Phase 36 will automatically trigger a warning on next `run_daily_refresh.py` run if the DB is behind head
- Plans 36-06 (and beyond) can proceed; no blockers

---
*Phase: 36-psr-purged-k-fold*
*Completed: 2026-02-24*
