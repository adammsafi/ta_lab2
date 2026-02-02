# Phase 14: Tools Integration - Context

**Gathered:** 2026-02-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Migrate Data_Tools scripts from external directory into ta_lab2/tools/data_tools/ with working imports. Reorganize functionally and standardize to ta_lab2 patterns. Archive/exclude deprecated, experimental, duplicate, or one-off scripts.

Out of scope: New functionality, external tools beyond Data_Tools, testing scripts that don't migrate.

</domain>

<decisions>
## Implementation Decisions

### Migration Scope
- **Discovery and filtering:** Claude inspects Data_Tools to determine migration vs archive candidates
- **Exclusion criteria:** Archive scripts with experiment/prototype markers (test_, temp_, scratch_, experimental_), duplicates of existing ta_lab2 functionality, one-off/throwaway scripts for past tasks
- **Borderline default:** When in doubt, migrate (better to have it and clean up later than lose useful tools)
- **Reorganization:** Group by function (data fetching/ingestion, data processing/transformation, analysis/reporting, utilities/helpers), not preserve original Data_Tools structure

### Import Path Strategy
- **Import style:** Claude's discretion - choose absolute vs relative based on project patterns
- **Hardcoded paths:** Claude decides per script (project-relative, config file, or parameterization based on usage patterns)
- **External dependencies:** Add to pyproject.toml as project dependencies (not optional extras)
- **Standardization:** Fully align migrated scripts with ta_lab2 patterns (logging, error handling, etc.) - more work but more consistent

### File Organization
- **Functional groupings:**
  - Data fetching/ingestion (API calls, file readers, database queries)
  - Data processing/transformation (cleaning, aggregation, format conversion)
  - Analysis/reporting (analytics, report generation)
  - Utilities/helpers (shared functions, constants, config loaders)
- **Directory structure:** Claude decides based on script count (subdirectories if many scripts per category, flat with prefixes if few)
- **Module exports:** Claude's discretion (export all scripts, selected public API, or no central exports)
- **Documentation:** Claude decides where READMEs are helpful (category explanations, key script summaries)

### Testing & Validation
- **Test level:** Claude decides based on script complexity (smoke tests for simple scripts, functional tests for complex ones)
- **Test failures:** Create gap closure plan after phase complete (migrate everything possible, document broken scripts for post-phase fixing)
- **Hardcoded path validation:** Strict automated check that no absolute paths or hardcoded user-specific references remain
- **Memory tracking:** Claude decides timing (incremental during migration vs batch after, based on Phase 13 learnings)

### Claude's Discretion
- Import style (absolute vs relative imports)
- Hardcoded path refactoring approach per script
- Directory structure (subdirs vs flat based on counts)
- Module export strategy (__init__.py design)
- README placement and content
- Test depth per script
- Memory update timing (incremental vs batch)

</decisions>

<specifics>
## Specific Ideas

- Follow Phase 13 pattern for memory updates (batch with infer=False if that worked well)
- Use Phase 12 archive patterns for excluded scripts (manifest.json, SHA256 checksums)
- Align with ta_lab2 existing tools structure (follow docs/ and archive/ module patterns)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 14-tools-integration*
*Context gathered: 2026-02-02*
