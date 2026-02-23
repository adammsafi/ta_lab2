---
phase: 31-documentation-freshness
plan: 01
subsystem: documentation
tags: [version-bump, docs, stale-references, alembic, ruff, changelog]

# Dependency graph
requires:
  - phase: 30-code-quality-tooling
    provides: ruff as canonical formatter (replaces black in docs)
provides:
  - All 6 version-bearing files updated to 0.8.0
  - Zero [TODO:] placeholders in docs/ops/
  - Zero aspirational alembic commands in README.md and docs/index.md
  - Zero black formatter references in docs/index.md (replaced with ruff)
affects:
  - 31-03 (mkdocs nav fixes touch same files)
  - 32-runbooks (inherits correct version context)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "pyproject.toml as version source of truth — all version strings derive from here"
    - "ruff format/check as canonical Code Quality section in developer docs"

key-files:
  created: []
  modified:
    - pyproject.toml
    - README.md
    - mkdocs.yml
    - docs/index.md
    - docs/DESIGN.md
    - docs/deployment.md
    - docs/ops/update_price_histories_and_emas.md

key-decisions:
  - "Historical changelog entries (v0.4.0 initial release, v0.5.0 reorganization) preserved untouched"
  - "Aspirational alembic section deleted entirely — no placeholder left — Phase 33 will add real migration docs"
  - "black -> ruff format in Code Quality section of docs/index.md (matches Phase 30 tooling)"
  - "TODO scaffolding meta-note removed alongside the [TODO:] placeholder it referred to"

patterns-established:
  - "Version bump pattern: update pyproject.toml + README heading/callout/changelog + mkdocs site_name + docs/index heading + DESIGN.md/deployment.md version headers and footers"

# Metrics
duration: 5min
completed: 2026-02-22
---

# Phase 31 Plan 01: Version Bump and Stale Reference Cleanup Summary

**Version strings bumped to 0.8.0 across 6 files; aspirational alembic commands removed; black replaced with ruff format; 4 [TODO:] placeholders in ops doc resolved with actual script paths**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-23T01:31:05Z
- **Completed:** 2026-02-23T01:36:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Bumped version to 0.8.0 in all 6 version-bearing files (pyproject.toml, README.md, mkdocs.yml, docs/index.md, docs/DESIGN.md, docs/deployment.md)
- Removed entire aspirational `### Database Migrations` section from both README.md and docs/index.md (3 alembic commands each)
- Replaced `black src/ tests/` with `ruff format src/` in docs/index.md Code Quality section
- Resolved all 4 `[TODO:]` placeholders in `docs/ops/update_price_histories_and_emas.md` with actual Python module paths

## Task Commits

Each task was committed atomically:

1. **Task 1: Version bump to 0.8.0 across all version-bearing files** - `beab8d9f` (docs)
2. **Task 2: Remove stale references and resolve TODO placeholders** - `e3c323bb` (docs)

## Files Created/Modified

- `pyproject.toml` - version bumped from 0.5.0 to 0.8.0
- `README.md` - heading, callout block, overview paragraph, changelog section updated to v0.8.0; alembic section removed
- `mkdocs.yml` - site_name updated to v0.8.0
- `docs/index.md` - heading, overview, changelog updated to v0.8.0; Code Quality updated (black -> ruff); alembic section removed
- `docs/DESIGN.md` - Version header and footer updated to 0.8.0; last updated date to 2026-02-22
- `docs/deployment.md` - Version header and footer updated to 0.8.0; last updated date to 2026-02-22
- `docs/ops/update_price_histories_and_emas.md` - 4 TODO placeholders resolved with actual script module paths

## Decisions Made

- Historical changelog entries (v0.4.0, v0.5.0 releases) preserved untouched in README.md and docs/index.md — these are accurate historical facts, not stale content
- Aspirational alembic section deleted entirely with no replacement placeholder — Phase 33 will add real migration documentation when Alembic is actually implemented
- TODO scaffolding meta-note (the `> **If you haven't finalized...** > [TODO:]` block) removed alongside the placeholder since the SQL path was already filled in on the preceding line

## Deviations from Plan

None - plan executed exactly as written. All 4 TODO placeholder replacements, both alembic section removals, and the black->ruff substitution performed as specified.

## Issues Encountered

Pre-commit `mixed-line-ending` hook triggered on each commit (Windows CRLF/LF normalization). Standard pattern on this repo — re-stage after hook fixes and commit again. No functional impact.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All version-bearing files now show 0.8.0 — Plan 03 (mkdocs nav fixes) can safely modify these files without version conflicts
- docs/index.md Code Quality section reflects actual tooling (ruff, not black)
- docs/ops/ has no TODO placeholders — ops documentation is operationally usable

---
*Phase: 31-documentation-freshness*
*Completed: 2026-02-22*
