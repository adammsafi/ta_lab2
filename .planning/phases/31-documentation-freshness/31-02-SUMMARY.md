---
phase: 31-documentation-freshness
plan: 02
subsystem: documentation
tags: [mermaid, diagrams, pipeline, data-flow, documentation]

# Dependency graph
requires:
  - phase: 29-stats-qa-orchestration
    provides: cmc_bar_stats, cmc_features_stats, audit_results tables wired into orchestrator
  - phase: 27-regime-integration
    provides: cmc_regimes/flips/stats/comovement tables and refresh pipeline
  - phase: 28-backtest-pipeline-fix
    provides: cmc_backtest_runs/trades/metrics tables and signal generators
provides:
  - docs/diagrams/data_flow.mmd — v0.8.0 main pipeline flow (8-stage TD flowchart)
  - docs/diagrams/table_variants.mmd — 4-family x 5-variant table structure diagram
affects:
  - 31-documentation-freshness (plans 03+): can reference diagrams as visual context
  - 32-runbooks: runbooks should link to these diagrams for pipeline orientation

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Split multi-diagram Mermaid files: separate .mmd files per diagram type for clean rendering"
    - "Mermaid subgraph blocks for pipeline stages with colour-coded style directives"

key-files:
  created:
    - docs/diagrams/table_variants.mmd
  modified:
    - docs/diagrams/data_flow.mmd

key-decisions:
  - "Split two diagrams into separate .mmd files (data_flow.mmd + table_variants.mmd) for cleaner rendering vs single combined file"
  - "Used flowchart TD for main pipeline (top-down stages), flowchart LR for variant detail (left-to-right consolidation pattern)"

patterns-established:
  - "Mermaid diagrams use short node IDs (PH7, BARS, EMAS) with full labels in node text"
  - "Stage subgraphs colour-coded by pipeline layer using Mermaid style directives"

# Metrics
duration: 2min
completed: 2026-02-23
---

# Phase 31 Plan 02: Pipeline Diagrams Summary

**Replaced obsolete v0.5.0 file-migration diagram with two accurate v0.8.0 Mermaid diagrams covering the full 8-stage data pipeline and 4-family x 5-variant table structure**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-23T01:31:52Z
- **Completed:** 2026-02-23T01:33:33Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Created `docs/diagrams/data_flow.mmd`: 8-stage top-down flowchart from `cmc_price_histories7` through bars, EMAs, features, regimes, signals, backtest, and stats/QA — all nodes use actual DB table names
- Created `docs/diagrams/table_variants.mmd`: left-right diagram showing all 4 table families (price bars, bar returns, EMA values, EMA returns), each with 5 alignment variants syncing into a unified `_u` table via INSERT ON CONFLICT DO NOTHING
- Completely removed v0.5.0 file-migration history content (ProjectTT, Data_Tools, fredtools2)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create main pipeline flow diagram and variant detail diagram** - `e79acc65` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `docs/diagrams/data_flow.mmd` — Main v0.8.0 pipeline flow, 104 lines, 8 stages, colour-coded subgraphs
- `docs/diagrams/table_variants.mmd` — Table variant structure detail, 4 families x 5 variants -> unified _u

## Decisions Made
- Split into two separate .mmd files rather than a single combined file: cleaner rendering and easier to reference independently. Mermaid renderers vary in multi-diagram support.
- Used `flowchart TD` (top-down) for the main pipeline: stages flow naturally from source to stats when read vertically.
- Used `flowchart LR` (left-right) for variant detail: the consolidation pattern (5 sources -> 1 unified) reads more naturally left-to-right.

## Deviations from Plan

None - plan executed exactly as written. The suggestion to split into two files if cleaner was explicitly provided in the plan action, and splitting was the correct choice for rendering clarity.

## Issues Encountered
- Pre-commit hook `mixed-line-ending` failed on first commit attempt for `table_variants.mmd` (LF vs CRLF on Windows). Hook auto-fixed the line endings; re-staged and committed successfully.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both diagrams are committed and accurate for v0.8.0 pipeline topology
- `data_flow.mmd` can be referenced in Plan 03 docs refresh and Plan 32 runbooks as the canonical pipeline overview
- No blockers for Plan 03 (version bump) or Plan 31-03 (architecture doc refresh)

---
*Phase: 31-documentation-freshness*
*Completed: 2026-02-23*
