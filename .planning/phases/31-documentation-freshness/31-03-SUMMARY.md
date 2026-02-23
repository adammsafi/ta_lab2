---
phase: 31-documentation-freshness
plan: 03
subsystem: docs
tags: [mkdocs, ci, github-actions, documentation, markdown]

# Dependency graph
requires:
  - phase: 31-01
    provides: version bump to 0.8.0 and stale reference cleanup in mkdocs.yml
provides:
  - mkdocs build --strict exits 0 with no warnings/errors
  - docs/CHANGELOG.md accessible from nav
  - CI docs job blocking on strict build
  - version-check CI job validates mkdocs.yml version consistency
affects:
  - 32-runbooks
  - 33-alembic-migrations

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "mkdocs nav uses clean paths only (no #anchors)"
    - "exclude_docs for Excel temp lock files (~$*)"
    - "docs/CHANGELOG.md is a content copy of root CHANGELOG.md (no symlinks — Windows compat)"

key-files:
  created:
    - docs/CHANGELOG.md
  modified:
    - mkdocs.yml
    - pyproject.toml
    - .github/workflows/ci.yml
    - docs/DESIGN.md
    - docs/index.md
    - docs/api/orchestrator.md
    - docs/architecture/timeframes.md
    - docs/features/bar-creation.md
    - docs/planning/sofarinmyownwords.md

key-decisions:
  - "Nav anchors removed — mkdocs strict treats id#anchor as a missing file; clean paths only"
  - "docs/CHANGELOG.md is a content copy not a symlink — mkdocs on Windows does not follow symlinks"
  - "mkdocs-material pinned to <9.7 in pyproject.toml (docs + all groups) — 9.7.x causes colorama crash on Windows"
  - "CONTRIBUTING.md/SECURITY.md root links removed from DESIGN.md — not part of mkdocs site, can't be linked"
  - "image1.emf placeholders replaced with text notes — .emf diagrams from DOCX conversion, originals not available"
  - "CI docs job is independent, runs in parallel with all other CI jobs"

patterns-established:
  - "mkdocs build --strict as CI gate: all docs link issues must be resolved before merge"
  - "version-check CI validates pyproject.toml == README.md == mkdocs.yml versions"

# Metrics
duration: 8min
completed: 2026-02-23
---

# Phase 31 Plan 03: Documentation Freshness — mkdocs Build CI Gate Summary

**mkdocs build --strict exits 0 after fixing nav anchors, broken ARCHITECTURE.md links, missing docs/CHANGELOG.md, and image1.emf placeholders; CI now gates on clean docs build with 6-job parallel workflow**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-23T01:41:00Z
- **Completed:** 2026-02-23T01:49:00Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- `mkdocs build --strict` exits 0 with no WARNING or ERROR lines — all broken links resolved
- Created `docs/CHANGELOG.md` as a full content copy of root CHANGELOG.md (updated through v0.8.0) so it is accessible from nav
- Fixed 6 categories of broken links: nav anchors, ARCHITECTURE.md refs, CHANGELOG.md refs, CONTRIBUTING/SECURITY refs, image1.emf refs
- Added `docs:` CI job that runs `mkdocs build --strict` as a blocking gate on every push/PR
- Extended `version-check` CI job to compare `mkdocs.yml` version against `pyproject.toml` and `README.md`
- Pinned `mkdocs-material>=9.0,<9.7` in `pyproject.toml` (docs + all groups) to avoid Windows colorama crash

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix mkdocs.yml nav, broken links, and create docs/CHANGELOG.md** - `8d2019a5` (fix)
2. **Task 2: Add CI docs job and extend version-check to include mkdocs.yml** - `72f78bda` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `docs/CHANGELOG.md` - New file: content copy of root CHANGELOG.md with v0.8.0 entry added
- `mkdocs.yml` - Nav anchors removed, ARCHITECTURE.md -> architecture/architecture.md, exclude_docs added
- `pyproject.toml` - mkdocs-material pinned to <9.7 in both docs and all groups
- `.github/workflows/ci.yml` - Added docs: job; extended version-check with MKDOCS_VER
- `docs/DESIGN.md` - ../ARCHITECTURE.md -> architecture/architecture.md; CONTRIBUTING/SECURITY links de-linked
- `docs/index.md` - ../CHANGELOG.md -> CHANGELOG.md (two occurrences)
- `docs/api/orchestrator.md` - ../ARCHITECTURE.md -> ../architecture/architecture.md
- `docs/architecture/timeframes.md` - image1.emf reference replaced with text note
- `docs/features/bar-creation.md` - image1.emf reference replaced with text note
- `docs/planning/sofarinmyownwords.md` - image1.emf reference replaced with text note

## Decisions Made

- **Nav anchors removed** — mkdocs --strict treats `page.md#anchor` as a missing file reference; clean `page.md` paths are correct
- **docs/CHANGELOG.md as content copy** — mkdocs on Windows does not follow symlinks; a real file copy is required; updated with v0.8.0 entry
- **mkdocs-material pinned <9.7** — v9.7.x introduced a colorama dependency that crashes on Windows environments
- **CONTRIBUTING.md/SECURITY.md de-linked in DESIGN.md** — these are root-level files not in docs/; mkdocs --strict flags them as broken; display text preserved, link wrapper removed
- **image1.emf replaced with text notes** — .emf diagrams were leftover artifacts from DOCX-to-Markdown conversion; original files never existed in the repo

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- Pre-commit hook (`mixed-line-ending`) modified `docs/CHANGELOG.md` and `docs/api/orchestrator.md` after initial staging — had to re-stage both files before committing. Standard pre-commit behavior, resolved by re-staging.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 31 (Documentation Freshness) is now complete: 31-01 (version bump), 31-02 (pipeline diagrams), 31-03 (mkdocs CI gate) all done
- DOCS-01 through DOCS-04 requirements satisfied
- Phase 32 (Runbooks) can begin — docs infrastructure is stable
- Phase 33 (Alembic Migrations) can begin — unrelated to docs

---
*Phase: 31-documentation-freshness*
*Completed: 2026-02-23*
