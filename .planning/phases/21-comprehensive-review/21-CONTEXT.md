# Phase 21: Comprehensive Review - Context

**Gathered:** 2026-02-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Complete read-only analysis of all bar/EMA components before any code changes. This phase produces documentation that answers key questions, catalogs all scripts, maps data flows, compares variants, and identifies gaps with severity tiers.

</domain>

<decisions>
## Implementation Decisions

### Analysis Depth
- **Deep analysis required**: Every import traced, every SQL query documented, edge cases identified, code quality notes
- **Researched answers**: Trace through code to verify claims, find examples, document evidence
- **Individual script focus**: Analyze each script independently, no pattern analysis across scripts (that's Phase 24)
- **Investigate thoroughly**: For unclear/unused scripts, trace imports, check git history, search for callers

### Documentation Approach
- **Data flow diagram**: Mixed format (Mermaid visual + detailed narrative)
- **User note**: Review phases 1-10 - some questions were already answered there

### Variant Comparison
- **All dimensions matter**: Data sources, calendar/timeframe handling, refresh logic, code structure patterns
- **Equal weight on WHAT and WHY**: Document functionality AND justify why 6 variants exist
- **Flag questions only**: Raise questions about similarities (e.g., "Are variants X and Y intentionally different?"), no consolidation recommendations

### Gap Prioritization
- **CRITICAL severity**: Data quality risk OR system reliability threats
  - Could lead to incorrect calculations, silent errors, bad trading signals
  - Could cause crashes, data loss, or inability to run daily refresh
- **Severity framework**: Claude establishes clear HIGH/MEDIUM/LOW criteria based on project context

### Claude's Discretion
- Script inventory format (choose what serves downstream agents best)
- Document organization structure (single file vs split, logical grouping)
- Variant comparison format (table vs sections vs dimension-focused)
- Gap analysis phase assignments (how to map gaps to phases 22-24)
- Improvements handling (what qualifies as a "gap" vs out of scope)
- HIGH/MEDIUM/LOW severity criteria (establish clear thresholds)

</decisions>

<specifics>
## Specific Ideas

- User emphasized: "Review phases 1-10 - some of this was all answered in there"
- Phase 21 is read-only analysis ONLY - no code changes
- Outputs feed directly into Phase 22 (data quality fixes), Phase 23 (orchestration), Phase 24 (patterns)

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope

</deferred>

---

*Phase: 21-comprehensive-review*
*Context gathered: 2026-02-05*
