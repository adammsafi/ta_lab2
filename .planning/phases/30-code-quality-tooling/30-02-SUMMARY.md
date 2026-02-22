---
phase: 30-code-quality-tooling
plan: 02
subsystem: infra
tags: [ruff, mypy, ci, pre-commit, quality-gates, type-checking]

# Dependency graph
requires:
  - phase: 30-01
    provides: zero ruff violations and fully formatted codebase (precondition for removing || true escape hatch)
provides:
  - Hard CI lint gate via ruff check src/ --output-format=github (no || true)
  - Hard CI format gate via ruff format --check src/
  - Non-blocking mypy CI job scoped to features/ and regimes/ (continue-on-error: true)
  - Version-consistency CI job comparing pyproject.toml vs README.md
  - [tool.mypy] section in pyproject.toml with ignore_missing_imports and check_untyped_defs
  - Version pins aligned: ruff>=0.9.0, mypy>=1.14, pandas-stubs>=2.2, mkdocstrings>=0.24
  - Pre-commit ruff hook updated to v0.9.0 (was v0.1.14)
  - README and CONTRIBUTING doc stale black references eliminated
affects:
  - 31-documentation-freshness (README and version pins are now clean)
  - 32-runbooks (CI job structure is stable reference point)

# Tech tracking
tech-stack:
  added:
    - pandas-stubs>=2.2 (dev group only, for mypy type checking support)
  patterns:
    - "5-job parallel CI pattern: test + lint + format + mypy + version-check, all independent"
    - "Non-blocking mypy gate: continue-on-error: true for gradual adoption without CI breakage"
    - "Version consistency gate: shell script extracts versions from pyproject.toml and README.md"
    - "pandas-stubs dev-only: avoid numpy version conflicts with vectorbt 0.28.1 in all group"

key-files:
  created: []
  modified:
    - pyproject.toml
    - .pre-commit-config.yaml
    - README.md
    - CONTRIBUTING.md
    - .github/workflows/ci.yml

key-decisions:
  - "pandas-stubs in dev group only: vectorbt 0.28.1 pins numpy to older version; pandas-stubs in all group would conflict"
  - "mypy continue-on-error: true: 15 existing errors in features/regimes are documented baseline, not to be fixed in v0.8.0"
  - "version-check via shell grep not Python: no dependency installation needed, fast, portable"
  - "5 independent jobs (not sequential): parallel execution maximizes CI speed, any job can fail independently"

patterns-established:
  - "Hard gate removal protocol: fix all violations FIRST (Plan 30-01), THEN remove || true (Plan 30-02)"
  - "CI job independence: test/lint/format/mypy/version-check all run in parallel, no depends-on chains"
  - "Dev-only stubs: type stubs that conflict with production deps go in dev group, not all group"

# Metrics
duration: 3min
completed: 2026-02-22
---

# Phase 30 Plan 02: Code Quality Tooling (CI Gates + Version Pins) Summary

**5-job parallel CI with hard ruff lint/format gates, non-blocking mypy scoped to features/regimes, version-consistency check, and aligned version pins (ruff>=0.9.0, mypy>=1.14) across pyproject.toml, pre-commit, and CI**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-22T23:54:33Z
- **Completed:** 2026-02-22T23:57:13Z
- **Tasks:** 3/3
- **Files modified:** 5

## Accomplishments

- Removed the `|| true` escape hatch from CI lint job -- ruff violations now block merges
- Added [tool.mypy] section to pyproject.toml with ignore_missing_imports=true and check_untyped_defs=true
- Restructured ci.yml from 2 jobs to 5 independent parallel jobs (test, lint, format, mypy, version-check)
- Eliminated all stale black references from README.md and CONTRIBUTING.md
- Aligned ruff version to >=0.9.0 across pyproject.toml (dev+all groups), pre-commit hook, and CI installs

## Task Commits

Each task was committed atomically:

1. **Task 1: Update pyproject.toml -- [tool.mypy], version pins, pandas-stubs** - `cbee94c9` (chore)
2. **Task 2: Update pre-commit config, README, and CONTRIBUTING stale references** - `c411def1` (chore)
3. **Task 3: Restructure ci.yml -- lint/format/mypy/version-check as separate jobs** - `8d7c8a42` (ci)

## Files Created/Modified

- `.github/workflows/ci.yml` - Restructured from 2 jobs to 5 independent parallel jobs; removed `|| true`; added lint (--output-format=github), format (--check), mypy (continue-on-error: true), version-check jobs
- `pyproject.toml` - Added [tool.mypy] section; updated ruff>=0.9.0, mypy>=1.14; added pandas-stubs>=2.2 (dev only); updated mkdocstrings[python]>=0.24
- `.pre-commit-config.yaml` - Updated ruff rev from v0.1.14 to v0.9.0
- `README.md` - Replaced `black src/ tests/` code block with ruff check/format/mypy commands
- `CONTRIBUTING.md` - Replaced hypothetical "if we add linters" line with active ruff command

## Decisions Made

- **pandas-stubs dev-only**: Adding to `all` group risks numpy version conflict with vectorbt 0.28.1's numpy pin. Dev group is safe since vectorbt is not a dev dependency.
- **mypy continue-on-error: true**: There are 15 documented baseline errors in features/ and regimes/ (35% unannotated functions, vectorbt/psycopg2 missing stubs). Making it non-blocking enables visibility without blocking PRs during v0.8.0.
- **version-check via shell grep**: Extracts PYPROJECT_VER with grep -oP and README_VER from head -1. No Python or pip install needed -- runs in seconds.
- **5 independent CI jobs**: All run in parallel. Lint/format/version-check are fast (<30s). mypy is non-blocking. test is the slow one (matrix). No depends-on chains.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- QUAL-01 (ruff lint hard gate) and QUAL-02 (ruff format hard gate) are now satisfied
- QUAL-03 (mypy non-blocking CI) is satisfied
- QUAL-04 (version-check) is satisfied
- All 4 QUAL items from the v0.8.0 roadmap are complete
- Phase 31 (documentation-freshness) can proceed -- README is clean, version pins are fresh
- README.md version still shows v0.5.0; updating to v0.8.0 is a Phase 31 task (docs freshness)

---
*Phase: 30-code-quality-tooling*
*Completed: 2026-02-22*
