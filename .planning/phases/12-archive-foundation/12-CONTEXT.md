# Phase 12: Archive Foundation - Context

**Gathered:** 2026-02-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish the .archive/ directory structure, git history preservation patterns, manifest tracking system, and validation baseline before any files are actually moved in future phases (13-16). This is pure infrastructure - no actual archiving happens in this phase, only creating the foundation.

**What's in scope:**
- .archive/ directory structure with categories
- 00-README.md documenting archive organization
- Manifest system (types, functions, template)
- Git mv verification (prove history preservation works)
- Pre-reorganization baseline snapshot

**What's out of scope:**
- Actually archiving files (Phases 13-16)
- Moving/renaming files (Phases 13-16)
- Memory updates during moves (MEMO-13, MEMO-14 - later phases)

</domain>

<decisions>
## Implementation Decisions

### Archive Structure

**Directory organization:**
- Category-first structure: `.archive/{category}/YYYY-MM-DD/`
- Example: `.archive/deprecated/2026-02-15/`, `.archive/refactored/2026-02-15/`
- Rationale: User prefers browsing by category type over chronological history

**Categories:**
- Use the 4 research-suggested categories: `deprecated`, `refactored`, `migrated`, `documentation`
- Strict categorization: Each file goes in exactly one category (no duplicates)
- Category priority for edge cases: Claude's discretion based on context (choose most informative category per file)

**Date handling:**
- Single directory per day per category (all operations on same day share directory)
- Claude's discretion: Use actual archive date vs phase date (whichever provides better traceability)

**README content:**
- Structure documentation only (directory layout, category definitions)
- Do NOT include retrieval examples or search guidance

### Manifest System

**Manifest location:**
- One manifest.json per category at `.archive/{category}/manifest.json`
- Tracks all files in that category across all dates
- No date-level manifests

**Metadata per file:**
- Required fields: original_path, archive_path, action, timestamp, sha256_checksum
- Additional fields: file_size_bytes, commit_hash, phase_number, archive_reason
- Archive reason: Claude's discretion on required vs optional (make required if improves auditability)

**Checksum scope:**
- Claude's discretion: Balance thoroughness vs performance based on file counts
- Consider: All files vs Python-only vs size-based threshold

**Replacement tracking:**
- YES - track relationships between archived files and their replacements
- Manifest includes `replaced_by` field pointing to new file path (when applicable)
- Helps trace evolution of codebase during reorganization

### Validation Baseline

**Scope:**
- Include: src/, tests/, docs/, root level files (from ta_lab2 repo)
- Include: All 4 external directories (Data_Tools, ProjectTT, fredtools2, fedtools2)
- Complete baseline of everything being reorganized

**Detail level:**
- Claude's discretion: Choose appropriate detail for validation
- Options: aggregates only, full file listing, or files with checksums

**Storage location:**
- Claude's discretion: .planning/baseline/, baseline/ in root, or .archive/baseline/
- Put it wherever makes most sense organizationally

### Claude's Discretion

Areas where implementation flexibility is granted:
- Category priority rules for edge cases (choose most informative)
- Date to use for archive directories (actual vs phase date)
- Checksum scope (all files, Python-only, or size-based)
- Archive reason field requirement (required vs optional)
- Baseline detail level (aggregates vs full listing vs checksums)
- Baseline storage location (.planning/ vs root vs .archive/)

</decisions>

<specifics>
## Specific Ideas

- NO DELETION constraint must be explicit in all documentation
- Git history preservation is critical - verify `git log --follow` works
- Category-first organization chosen for easier browsing by type
- Single directory per day avoids timestamp/sequence complexity
- Manifest per category (not per date) for simpler tracking
- Replacement tracking (`replaced_by` field) enables codebase evolution tracing

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope.

</deferred>

---

*Phase: 12-archive-foundation*
*Context gathered: 2026-02-02*
