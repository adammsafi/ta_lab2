# Phase 19: Memory Validation & Release - Context

**Gathered:** 2026-02-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate memory completeness (function-level memories, relationship types, duplicate detection), ensure memory graph integrity, verify query capabilities work, and release v0.5.0 milestone. This is the final phase of v0.5.0 Ecosystem Reorganization.

</domain>

<decisions>
## Implementation Decisions

### Function-level memory scope
- **Significance threshold:** Claude's discretion — determines what counts as "significant function" based on complexity, reuse patterns, and documentation value
- **Metadata depth:** Full signatures — include param names, types, return types, defaults for type-aware queries
- **Test coverage:** Yes, include tests — test function names indexed to enable "what tests cover X?" queries

### Duplicate detection thresholds
- **95%+ similarity (near-identical):** All three actions — flag for consolidation, add similar_to memory relationship, AND analyze which version is canonical with keep/remove suggestion
- **85-95% similarity (highly similar):** Claude's discretion — determine if variation is meaningful (different error handling, specialized use cases)
- **70-85% similarity (related):** Document with similar_to link in memory AND include in report appendix (informational, not actionable)
- **Algorithm:** Claude's discretion — choose appropriate algorithm (AST-based vs token-based) based on codebase characteristics

### Validation acceptance criteria
- **Required query types:** Claude determines minimum essential set based on common usage patterns
- **Orphan tolerance:** Claude determines reasonable threshold based on memory graph characteristics
- **Output format:** BOTH — full VALIDATION.md report with metrics, query test results, coverage statistics AND clear pass/fail status at top
- **Release blocking:** Validation must pass before v0.5.0 tag — strict quality gate

### Release process
- **Tag scope:** Same as v0.4.0 release — follow established patterns
- **Changelog format:** Keep a Changelog format (Added/Changed/Deprecated/Removed/Fixed sections) per v0.4.0 pattern
- **Announcement:** Claude's discretion based on milestone significance

### Claude's Discretion
- Function significance threshold for indexing
- Similarity algorithm selection (AST vs token-based)
- Meaningful variation assessment for 85-95% tier
- Minimum essential query types for validation
- Orphan tolerance threshold
- Release announcement scope

</decisions>

<specifics>
## Specific Ideas

- Follow v0.4.0 release patterns exactly (CHANGELOG.md format, tag structure)
- 95%+ duplicates get full treatment: document + recommend + suggest canonical version
- Tests indexed because "what tests cover function X?" is valuable query
- Validation is a release blocker — no partial releases with known issues

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 19-memory-validation-release*
*Context gathered: 2026-02-03*
