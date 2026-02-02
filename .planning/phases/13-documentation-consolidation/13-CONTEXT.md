# Phase 13: Documentation Consolidation - Context

**Gathered:** 2026-02-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Convert ProjectTT documentation files (.docx, Excel) to Markdown and integrate into ta_lab2's docs/ structure. Original files preserved in .archive/documentation/. This phase focuses on documentation migration - new documentation creation and maintenance workflows are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Documentation structure
- **Hybrid organization:** Main categories defined by content analysis, Claude organizes subtopics within each category
- **Target-aligned structure:** If mirroring codebase organization, reflect the **final state** after v0.5.0 reorganization (not current state)
- **Category determination:** Claude analyzes ProjectTT documentation content and creates appropriate main categories (Architecture, Features, Development, etc.)
- **Navigation priority:** Structure optimized for what makes docs most navigable, not strictly following code structure

### Conversion approach
- **Per-document strategy:** Claude evaluates each .docx file and chooses conversion approach (preserve formatting, standardize, or extract content) based on document characteristics
- **Metadata inclusion:** Add YAML front matter with metadata extracted from original documents (creation date, author, version)
- **Image handling:** Claude decides based on image type and conversion feasibility (extract to docs/assets/, convert diagrams to Mermaid when possible)
- **Complex formatting fallback:** Three-tier strategy:
  1. Best effort conversion (convert what's possible, note limitations in comment)
  2. Simplify to Markdown patterns if best effort insufficient
  3. Flag for manual review as last resort

### Index organization
- **Content:** Claude decides index structure (simple TOC, categorized sections, or rich landing page) based on document volume/complexity
- **Code cross-references:** Include links to key code files/directories in index (e.g., "EMA docs → src/features/ema.py")
- **Archived document handling:** Claude chooses presentation strategy (show with tags, separate section, or exclude) based on archive volume

### Memory relationships
- **Granularity:** Maximum practical granularity - likely section-level or topic-level tracking, Claude decides based on document complexity
- **Relationship types:** Claude creates memory relationships that add navigation value (moved_to, references, supersedes, etc.)
- **Doc-code linking:** Bidirectional relationships between documentation and code (doc → code + code → doc)
- **Phase snapshot tagging:** Follow Phase 11 tagging patterns for consistency (descriptive tags, structured metadata as established)

### Claude's Discretion
- Exact folder names and category boundaries
- Per-document conversion methodology selection
- Mermaid diagram creation vs image extraction decisions
- Index layout and Quick Links inclusion
- Memory snapshot metadata structure details
- Getting Started section inclusion and content

</decisions>

<specifics>
## Specific Ideas

- **Structure principle:** If docs mirror codebase, they should reflect the target reorganized structure, not the transitional state
- **Conversion priority:** Prefer automated conversion with quality over manual effort - use three-tier fallback strategy
- **Memory depth:** "As granular as possible while still being practical" - maximize navigability through detailed cross-references

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope

</deferred>

---

*Phase: 13-documentation-consolidation*
*Context gathered: 2026-02-02*
