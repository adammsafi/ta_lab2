---
phase: 33-alembic-migrations
plan: 01
subsystem: database
tags: [alembic, migrations, sqlalchemy, postgresql, pyproject]

# Dependency graph
requires:
  - phase: 30-code-quality-tooling
    provides: ruff configured in pyproject.toml (used in alembic post-write hook)
  - phase: 23-reliable-incremental-refresh
    provides: resolve_db_url() in refresh_utils.py (used in alembic env.py)
provides:
  - alembic>=1.18 in pyproject.toml core dependencies
  - alembic.ini with placeholder URL, ruff post-write hook, output_encoding=utf-8
  - alembic/env.py with resolve_db_url(), NullPool, encoding='utf-8', target_metadata=None
  - alembic/script.py.mako revision template
  - alembic/versions/ empty directory (ready for baseline revision in Plan 02)
affects:
  - 33-alembic-migrations Plan 02 (baseline revision depends on this framework)
  - Future schema changes (all go through alembic revision files)

# Tech tracking
tech-stack:
  added: [alembic>=1.18]
  patterns:
    - "Stamp-then-forward migration strategy: no autogenerate, all revisions by hand"
    - "resolve_db_url() integration in alembic env.py (same URL resolution as all other scripts)"
    - "NullPool in alembic online mode (matches project-wide pattern)"
    - "encoding='utf-8' in fileConfig (Windows cp1252 protection)"

key-files:
  created:
    - alembic.ini
    - alembic/env.py
    - alembic/script.py.mako
    - alembic/README
  modified:
    - pyproject.toml

key-decisions:
  - "Standard alembic init template (not pyproject): cleaner separation, alembic.ini handles all config"
  - "target_metadata=None: autogenerate disabled permanently -- without ORM models it would recreate all 50+ tables"
  - "Placeholder URL in alembic.ini: no credentials in git; real URL via resolve_db_url() in env.py"
  - "Ruff post-write hook: new revision files auto-linted on creation"

patterns-established:
  - "alembic/env.py imports resolve_db_url from src.ta_lab2.scripts.refresh_utils"
  - "sys.path.insert(0, _PROJECT_ROOT) before import ensures importability pre-install"
  - "fileConfig with encoding='utf-8' always (Windows safety)"

# Metrics
duration: 2min
completed: 2026-02-23
---

# Phase 33 Plan 01: Alembic Bootstrap Summary

**Alembic 1.18.4 migration framework bootstrapped: env.py wired to resolve_db_url()+NullPool, alembic.ini with placeholder URL + ruff post-write hook, `alembic history` exits 0**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-23T17:39:33Z
- **Completed:** 2026-02-23T17:41:57Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added `alembic>=1.18` to pyproject.toml core dependencies and `all` optional group; alembic 1.18.4 installed
- Bootstrapped `alembic/` directory with customized `env.py` that uses `resolve_db_url()`, `pool.NullPool`, `encoding='utf-8'` in fileConfig, and `target_metadata=None`
- Customized `alembic.ini` with placeholder URL (no credentials), `output_encoding=utf-8`, and ruff post-write hook for auto-linting new revision files

## Task Commits

Each task was committed atomically:

1. **Task 1: Add alembic dependency and install** - `338aae37` (chore)
2. **Task 2: Initialize Alembic and customize configuration** - `b0c402a3` (feat)

## Files Created/Modified

- `pyproject.toml` - Added `alembic>=1.18` to core `[project.dependencies]` and `all` optional group
- `alembic.ini` - Customized: placeholder URL, `output_encoding=utf-8`, ruff post-write hook, logging config
- `alembic/env.py` - Project-specific: `resolve_db_url()` import, `encoding='utf-8'` in fileConfig, `target_metadata=None`, `pool.NullPool` in online mode, both offline+online modes supported
- `alembic/script.py.mako` - Default revision file template from `alembic init`
- `alembic/README` - Default README from `alembic init`

## Decisions Made

- **Standard template over pyproject template:** `alembic init alembic` (standard) used rather than `alembic init --template pyproject alembic`. The pyproject template appends `[tool.alembic]` to `pyproject.toml` but still generates `alembic.ini` anyway — redundant. Standard template keeps all Alembic config in `alembic.ini` cleanly.
- **target_metadata = None enforced:** Without ORM models, `--autogenerate` would emit `op.create_table()` for all 50+ existing tables. Explicit `None` blocks this permanently; all revisions written by hand.
- **Ruff via exec runner:** `ruff.type = exec` (uses PATH binary) rather than `module` or `console_scripts` — consistent with how ruff is invoked elsewhere in the project (pre-commit hooks, Makefile).
- **Both offline and online modes in env.py:** Offline mode (`alembic upgrade head --sql`) costs nothing to support and enables producing SQL scripts for DBA review.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pre-commit hook failed on missing trailing newline in alembic/README**

- **Found during:** Task 2 (initial commit attempt)
- **Issue:** `alembic init` generated `alembic/README` without a trailing newline; the `end-of-file-fixer` pre-commit hook rejected it
- **Fix:** Pre-commit hook auto-fixed the file; re-staged and committed
- **Files modified:** alembic/README
- **Verification:** Second commit passed all hooks cleanly
- **Committed in:** b0c402a3 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking - pre-commit hook)
**Impact on plan:** Minor. Pre-commit hook auto-corrected the file; no scope change.

## Issues Encountered

None — all tasks executed as specified in the plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Alembic framework is fully bootstrapped; `alembic history` exits 0 cleanly
- Plan 02 can proceed immediately: create the no-op baseline revision with `alembic revision -m "baseline"`, then `alembic stamp head` on the live DB
- No blockers or concerns

---
*Phase: 33-alembic-migrations*
*Completed: 2026-02-23*
