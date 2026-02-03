# Phase 16: Repository Cleanup - Context

**Gathered:** 2026-02-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Clean root directory and consolidate duplicate files. Move temp files, *_refactored.py, *.original files to archive. Organize loose .md files into docs/ structure. Identify exact duplicates via SHA256 and flag similar functions for review. Memory updated with all file movements.

</domain>

<decisions>
## Implementation Decisions

### Root Directory Rules
- Best practices approach — minimal root (README, pyproject.toml, .gitignore, LICENSE, standard configs)
- Loose Python scripts: **Case-by-case review** — examine each and decide archive/move/keep
- Untracked temp directories (connectivity/, media/, memory/, skills/): **Review contents first** — examine value before archiving (nothing gets deleted)
- .planning/ stays in root (GSD working directory)
- .env.example, config files, SQL files, .claude/.gemini directories: Claude's discretion based on best practices

### Archive vs Delete Policy
- **Absolute no-deletion** — everything goes to .archive/, nothing gets rm'd
- *_refactored.py files: **Compare and decide** — diff against original; if better, replace; if not, archive
- *.original files: **Archive all** — git history tracks originals, .original files are redundant
- Archive organization: **Categorized** — .archive/refactored/, .archive/temp/, .archive/duplicates/ etc.

### Duplicate Handling
- Exact duplicates (SHA256 match): **Keep src/ copy** — if one is in src/ta_lab2/, that's canonical
- Similar functions: **Flag for manual review** — generate report, user decides later
- Three-tier similarity thresholds:
  - 95%+ (near-exact)
  - 85-95% (similar)
  - 70-85% (related)
- Similarity algorithm: Claude's discretion (difflib vs AST-based)

### Loose Docs Organization
- Scattered .md files: **docs/ by category** — docs/architecture/, docs/analysis/, docs/guides/ based on content
- Module-level READMEs: Claude's discretion (likely keep in place)
- docs/ structure: **Content-driven** — subdirs emerge from actual doc types
- docs/index.md: **Update incrementally** — add new entries to existing structure

### Claude's Discretion
- Config file locations (.env.example, openai_config_2.env, start_qdrant_server.bat)
- AI tool directories (.claude/, .gemini/) location
- SQL file organization (sql/ vs src/ta_lab2/sql/)
- Specific exceptions to root cleanup rules (defer to best practices)
- Module-level README handling
- Similarity comparison algorithm choice

</decisions>

<specifics>
## Specific Ideas

- User emphasized "nothing gets deleted" multiple times — absolute preservation requirement
- Case-by-case review for loose scripts means actual examination of each file's purpose
- Similarity report is for manual review, not auto-action — user wants control over consolidation decisions

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 16-repository-cleanup*
*Context gathered: 2026-02-03*
