# Phase 31: Documentation Freshness - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Update documentation to accurately describe v0.8.0 of the system. Version strings are consistent across all files, a pipeline diagram reflects the current architecture, stale/aspirational references are removed, and mkdocs builds without errors. This phase does NOT add new documentation pages or restructure the docs site — it makes existing docs accurate.

</domain>

<decisions>
## Implementation Decisions

### Version bump strategy
- Bump to 0.8.0 NOW in Phase 31, not after Phases 32-33 complete
- The version represents the tooling/docs milestone state
- Standalone commit for version bump (Claude's discretion on exact commit strategy)

### Version files and CI
- Claude decides which files get the version string (pyproject.toml + README.md at minimum, mkdocs.yml as needed)
- Claude decides whether to extend the CI version-check job to also verify mkdocs.yml consistency

### Pipeline diagram content
- Full pipeline diagram showing the complete flow: price_histories7 → 1D bars → multi-TF bars → EMAs → features → regimes → signals → backtest → stats/QA
- Include actual DB table names in nodes (cmc_price_bars_multi_tf, cmc_ema_multi_tf_u, etc.), not just conceptual stage names
- TWO diagrams: main flow diagram (primary pipeline) + secondary detail diagram expanding bar/EMA table variants (6 variants each)
- Location: `docs/diagrams/data_flow.mmd` — standalone Mermaid file referenced from README and mkdocs nav

### Stale reference cleanup scope
- Remove aspirational alembic references NOW — Phase 33 will re-add correct ones when alembic is actually set up
- Resolve ALL [TODO:] placeholders in ops docs — zero TODOs remaining after this phase
- Full sweep of all docs/ and root .md files for stale references (black, isort, old versions, dead links, aspirational features)
- Remove aspirational references to features that don't exist yet (e.g., visualization dashboard). Future features get documented when they ship.

### mkdocs build fix approach
- Fix to build cleanly — minimal changes, fix broken links, remove dead entries, ensure existing pages reachable. Do NOT restructure nav.
- Fix API doc references (update module paths to match current code structure) rather than disabling strict mode
- Add `mkdocs build --strict` as a CI blocking check (new 'docs' job, similar to the ruff lint job added in Phase 30)

### Claude's Discretion
- Whether to create stub pages or remove broken nav entries (evaluate per case)
- Exact commit strategy (standalone version bump vs bundled)
- Which files need version strings beyond pyproject.toml + README.md
- Whether CI version-check should include mkdocs.yml
- Diagram styling and Mermaid syntax choices

</decisions>

<specifics>
## Specific Ideas

- Research identified version drift: pyproject.toml shows 0.5.0, mkdocs.yml shows v0.4.0, README shows v0.5.0 — all need updating to 0.8.0
- The pipeline diagram should be operationally useful — an operator should be able to match diagram nodes to actual SQL table names
- Two-level diagram approach: overview for understanding the flow + detail view for the bar/EMA variant structure

</specifics>

<deferred>
## Deferred Ideas

- Full docs site restructure to match current system architecture — potential future phase if needed
- Adding new documentation pages for regime pipeline, backtest pipeline — covered by Phase 32 (Runbooks)
- Interactive API documentation — v0.9.0 scope

</deferred>

---

*Phase: 31-documentation-freshness*
*Context gathered: 2026-02-22*
