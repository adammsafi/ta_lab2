# Phase 18: Structure Documentation - Context

**Gathered:** 2026-02-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Document final structure and migration decisions for future reference. This phase produces documentation artifacts (REORGANIZATION.md, diagrams, manifests, migration guide) after all file moves are complete (Phases 11-17). Creates reference material explaining what happened during v0.5.0 reorganization.

</domain>

<decisions>
## Implementation Decisions

### REORGANIZATION.md structure
- Organize by **source directory** (ProjectTT, Data_Tools, fredtools2, fedtools2 sections)
- **Full file listing** - every file with its destination path (comprehensive)
- **Detailed rationale** - full explanation for major decisions, especially archives/extractions
- Git commit links: Claude's discretion based on practicality

### Before/after diagrams
- **Both formats**: ASCII text trees for full detail, Mermaid for high-level overview
- ASCII tree depth: **Full depth** - all the way down to files
- Before scope: **All 5 directories** - ta_lab2 + ProjectTT + Data_Tools + fredtools2 + fedtools2 as they were
- Mermaid diagrams: **Both** - one for data flow (external dirs → ta_lab2), one for package structure

### Decision manifest format
- **JSON with .md companion** - JSON for data, separate Markdown for detailed rationale
- **Rich fields**: id, type, source, destination, phase, timestamp, category, action, rationale_id, related_decisions, requirements
- **$schema versioning** - follow Phase 12 pattern with schema URL and JSON Schema validation
- Queryability (CLI tool): Claude's discretion

### Migration guide depth
- **Both use cases equally**: import fixing ("what do I use now?") and file finding ("where did Y.py go?")
- Import mappings: **Both** - table for quick lookup, code blocks for complex cases
- Archived files: **Yes with alternatives** - if you used X and it's archived, here's what to use instead
- Migration scanning tool: Claude's discretion

### Claude's Discretion
- Whether to include git commit links in REORGANIZATION.md
- Whether to build a CLI query tool for the decision manifest
- Whether to build a migration scanning tool that finds old imports

</decisions>

<specifics>
## Specific Ideas

- Follow Phase 12 manifest patterns ($schema versioning, rich metadata)
- Full file listings mean this will be a comprehensive reference document
- Detailed rationale helps future developers understand WHY decisions were made
- Both ASCII and Mermaid diagrams serve different audiences (diff-friendly vs visual)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 18-structure-documentation*
*Context gathered: 2026-02-03*
