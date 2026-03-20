---
phase: 74-foundation-shared-infrastructure
plan: "01"
subsystem: database
tags: [psycopg, psycopg2, psycopg3, bar-builder, refactor, shared-module]

# Dependency graph
requires: []
provides:
  - "ta_lab2.db.psycopg_helpers: shared psycopg v3/v2 connection and query helpers"
  - "All 3 1D bar builders (CMC, TVC, HL) wired to shared module"
affects:
  - 74-02 (generalized bar builder will also use ta_lab2.db.psycopg_helpers)
  - Any future bar builder or raw-SQL script

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Raw psycopg helpers centralised in ta_lab2.db.psycopg_helpers (not per-script copies)"
    - "Dual-driver detection (PSYCOPG3/PSYCOPG2) done once at import time in shared module"

key-files:
  created:
    - src/ta_lab2/db/__init__.py
    - src/ta_lab2/db/psycopg_helpers.py
  modified:
    - src/ta_lab2/scripts/bars/refresh_price_bars_1d.py
    - src/ta_lab2/scripts/bars/refresh_tvc_price_bars_1d.py
    - src/ta_lab2/scripts/bars/refresh_hl_price_bars_1d.py

key-decisions:
  - "Public API names (no underscore prefix) since helpers are now a shared module, not file-private"
  - "CMC builder chosen as canonical source since it has the most complete psycopg3-aware implementation"
  - "fetchall not imported in CMC builder (unused there); each builder imports only what it needs"

patterns-established:
  - "from ta_lab2.db.psycopg_helpers import connect, execute, fetchone [, fetchall]"
  - "New bar builders and raw-SQL scripts should import from ta_lab2.db.psycopg_helpers, not copy helpers"

# Metrics
duration: 9min
completed: "2026-03-20"
---

# Phase 74 Plan 01: Foundation Shared Infrastructure Summary

**Shared `ta_lab2.db.psycopg_helpers` module extracts 5 psycopg helper functions from 3 bar builders, eliminating ~222 lines of duplicated driver-detection and cursor-management code**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-20T03:45:59Z
- **Completed:** 2026-03-20T03:55:09Z
- **Tasks:** 2
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments
- Created `src/ta_lab2/db/` package with `psycopg_helpers.py` exporting 5 functions and 2 driver flags
- Removed per-file psycopg helper copies from CMC, TVC, and HL 1D bar builders (~222 lines total)
- All 3 builders import from the shared module and pass ruff lint/format clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Create shared psycopg_helpers module** - `0b699b0c` (feat)
2. **Task 2: Rewire all 3 bar builders to use shared helpers** - `1747f9b5` (refactor)

**Plan metadata:** see below (docs commit)

## Files Created/Modified
- `src/ta_lab2/db/__init__.py` - Package marker for ta_lab2.db
- `src/ta_lab2/db/psycopg_helpers.py` - Shared module: PSYCOPG3, PSYCOPG2, normalize_db_url, connect, execute, fetchall, fetchone
- `src/ta_lab2/scripts/bars/refresh_price_bars_1d.py` - CMC builder: removed local helpers, imports from shared module (-95 lines)
- `src/ta_lab2/scripts/bars/refresh_tvc_price_bars_1d.py` - TVC builder: removed local helpers, imports from shared module (-59 lines)
- `src/ta_lab2/scripts/bars/refresh_hl_price_bars_1d.py` - HL builder: removed local helpers, imports from shared module (-68 lines)

## Decisions Made
- Public names (no leading underscore) since helpers are now a shared package API, not file-private utilities
- CMC builder used as canonical source for the shared module (most complete: handles both psycopg3 context manager and psycopg2 manual close)
- Each builder imports only what it uses (`fetchall` excluded from CMC import since CMC never calls it)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused imports after extraction**
- **Found during:** Task 2 (after sed replacement, ruff flagged F401)
- **Issue:** `Sequence`, `Tuple` (typing) and `PSYCOPG3`, `PSYCOPG2`, `normalize_db_url`, `fetchall` were imported but unused after deleting per-file helper bodies
- **Fix:** Trimmed each file's import list to only what the file body actually uses
- **Files modified:** All 3 bar builders
- **Verification:** `ruff check` passes clean on all 4 files
- **Committed in:** `1747f9b5` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - unused imports after extraction)
**Impact on plan:** Necessary housekeeping; no scope creep.

## Issues Encountered
None - extraction was straightforward. TVC and HL had simpler `_exec`/`_fetchone` implementations (no PSYCOPG3 branching) but the shared module's CMC-derived implementation is fully backward-compatible.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `ta_lab2.db.psycopg_helpers` is ready for use by the generalized bar builder in plan 74-02
- All 3 existing builders function identically to before (no behavioral change)
- No blockers

---
*Phase: 74-foundation-shared-infrastructure*
*Completed: 2026-03-20*
