---
phase: 16-repository-cleanup
plan: 02
subsystem: codebase-organization
tags: [archive, refactoring, git-history, cleanup]

# Dependency graph
requires:
  - phase: 12-archive-foundation
    provides: Archive infrastructure with manifest patterns
provides:
  - Resolved refactored/original file conflicts with documented comparison decisions
  - Archived redundant *_refactored.py files (duplicates and incomplete stubs)
  - Archived .original backup files (git history provides canonical versions)
  - Clean m_tf/ module with single canonical version of each EMA feature
affects: [17-verification-validation, future-refactoring-efforts]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Comparison-based archiving: diff files and decide keep/archive with manifest tracking"
    - "Git history as canonical source: .original backups redundant when git log --follow available"

key-files:
  created:
    - .archive/refactored/manifest.json
    - .archive/originals/manifest.json
  modified: []

key-decisions:
  - "Canonical files already refactored: ema_multi_timeframe.py, ema_multi_tf_cal.py, ema_multi_tf_cal_anchor.py are complete refactored versions"
  - "Archive duplicate refactored files: _refactored.py variants are redundant or incomplete stubs"
  - "Archive .original files: Git history tracks originals, .original backup files unnecessary"

patterns-established:
  - "File comparison manifest: Record comparison results (LOC, features, decision, reason) for transparency"
  - "SHA256 checksums for archived files: Enables verification files unchanged during archiving"
  - "Git mv for tracked files: Preserves history with --follow capability"

# Metrics
duration: 18min
completed: 2026-02-03
---

# Phase 16 Plan 02: Refactored/Original File Resolution Summary

**Resolved 11 redundant files: archived 3 duplicate/stub _refactored.py variants and 8 .original backups, leaving canonical refactored versions in place**

## Performance

- **Duration:** 18 min
- **Started:** 2026-02-03T16:21:25Z
- **Completed:** 2026-02-03T16:38:55Z
- **Tasks:** 3 (comparison, refactored archiving, originals archiving)
- **Files archived:** 11

## Accomplishments

- Compared 3 *_refactored.py files against canonical versions with documented decisions
- Archived 3 *_refactored.py files (1 duplicate, 2 incomplete stubs) with comparison manifests
- Archived 8 *.original backup files (git history provides canonical originals)
- Clean src/ta_lab2/features/m_tf/ with single canonical version of each EMA feature

## Task Commits

Tasks were executed in prior commits (16-01 and 16-03 sessions):

1. **Task 1: Compare *_refactored.py files** - Analysis completed, decisions documented in manifest
2. **Task 2: Archive refactored files** - `f183cbb` (chore: part of 16-01 cleanup)
3. **Task 3: Archive .original files** - `9c75d6a` (chore: part of 16-03 cleanup)

**Note:** This plan documents work already committed. The refactored and .original files were archived during concurrent cleanup efforts (16-01 root cleanup, 16-03 docs reorganization). This SUMMARY formalizes comparison decisions and manifest tracking.

## Files Archived

### Refactored files (.archive/refactored/2026-02-03/):
- `ema_multi_timeframe_refactored.py` - Duplicate of canonical (571 LOC identical)
- `ema_multi_tf_cal_refactored.py` - Incomplete stub (289 LOC vs canonical 607 LOC)
- `ema_multi_tf_cal_anchor_refactored.py` - Incomplete stub (198 LOC vs canonical 570 LOC)

### Original files (.archive/originals/2026-02-03/):
- `ema_multi_tf_cal.original`
- `ema_multi_tf_cal_anchor.original`
- `ema_multi_tf_v2.original`
- `ema_multi_timeframe.original`
- `refresh_cmc_ema_multi_tf_cal_anchor_from_bars.original`
- `refresh_cmc_ema_multi_tf_cal_from_bars.original`
- `refresh_cmc_ema_multi_tf_from_bars.original`
- `refresh_cmc_ema_multi_tf_v2.original`

## Comparison Results

### Pair 1: ema_multi_timeframe
- **Canonical:** ema_multi_timeframe.py (571 LOC) - Already refactored, fully implemented
- **Variant:** ema_multi_timeframe_refactored.py (571 LOC) - Identical duplicate
- **Decision:** Archive variant (redundant)
- **Reason:** Files are byte-identical; canonical is already the refactored version

### Pair 2: ema_multi_tf_cal
- **Canonical:** ema_multi_tf_cal.py (607 LOC) - Fully implemented dual EMA logic
- **Variant:** ema_multi_tf_cal_refactored.py (289 LOC) - Incomplete stub with placeholders
- **Decision:** Archive variant (inferior to canonical)
- **Reason:** Canonical has complete ema + ema_bar computation with preview logic; variant is stub returning empty DataFrame

### Pair 3: ema_multi_tf_cal_anchor
- **Canonical:** ema_multi_tf_cal_anchor.py (570 LOC) - Fully implemented anchor semantics
- **Variant:** ema_multi_tf_cal_anchor_refactored.py (198 LOC) - Incomplete stub
- **Decision:** Archive variant (inferior to canonical)
- **Reason:** Canonical has full dual EMA + anchor bar logic; variant is stub with warning messages

## Decisions Made

**Canonical files are already refactored:**
- All three canonical files (ema_multi_timeframe.py, ema_multi_tf_cal.py, ema_multi_tf_cal_anchor.py) extend BaseEMAFeature abstract class
- They include full implementations with complete logic, derivatives, and database writes
- File headers explicitly state "REFACTORED to use BaseEMAFeature"

**Archive criteria:**
- Refactored duplicate → Archive (canonical is sufficient)
- Refactored incomplete → Archive (canonical is superior)
- Original backups → Archive (git history provides canonical access)

**Git history preservation:**
- Used git mv for tracked .original files (preserves --follow capability)
- Untracked *_refactored.py files moved with filesystem operations (never committed, no history to preserve)
- Manifests track SHA256 checksums for verification

## Deviations from Plan

None - plan executed as specified. Comparison analysis determined all refactored variants should be archived.

## Issues Encountered

None - straightforward comparison and archiving. Refactored files were untracked (never committed), .original files were tracked and moved with git mv.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Clean m_tf/ module ready for future development
- Single canonical version eliminates confusion about which file to modify
- Archive manifests provide audit trail for all archiving decisions
- Git history accessible via `git log --follow` for all original versions

**Blocker check:** None - verification criteria all met:
- ✅ Zero *_refactored.py files in src/
- ✅ Zero *.original files in src/
- ✅ Canonical files importable (ema_multi_timeframe, ema_multi_tf_cal, ema_multi_tf_cal_anchor)
- ✅ Manifests valid JSON with checksums

---
*Phase: 16-repository-cleanup*
*Completed: 2026-02-03*
