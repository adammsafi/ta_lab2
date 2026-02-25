---
phase: 50-data-economics
plan: 02
subsystem: architecture
tags: [postgresql, tco-model, architecture-decision, timescaledb, data-lake, decision-triggers, adr]

# Dependency graph
requires:
  - phase: 50-data-economics
    plan: 01
    provides: cost-audit.md (46 GB measured DB) + vendor-comparison.md (CoinGecko/Alpaca recommendations)
provides:
  - reports/data-economics/tco-model.md — three-way architecture comparison at current/2x/5x scale with decision trigger matrix
  - docs/architecture/ADR-001-data-infrastructure.md — formal MADR 4.0 decision record (status: Accepted)
  - reports/data-economics/README.md — executive summary linking all four deliverables
affects:
  - any future infrastructure migration plans (ADR-001 is the canonical decision record)
  - vendor onboarding plans (trigger thresholds define when to upgrade data APIs)
  - 5x scale architecture planning

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MADR 4.0 architecture decision record format for infrastructure decisions"
    - "Weighted decision matrix pattern: score each option on dimensions x weights at each scale point"
    - "Trigger-based review pattern: any ONE quantitative threshold crossed justifies re-evaluation"

key-files:
  created:
    - reports/data-economics/tco-model.md
    - docs/architecture/ADR-001-data-infrastructure.md
    - reports/data-economics/README.md
  modified: []

key-decisions:
  - "Stay on local PostgreSQL through 2x scale: zero infrastructure cost, zero migration cost, PostgreSQL viable at 235M rows with partitioning"
  - "TimescaleDB Cloud is the preferred migration target if/when triggered: 1-2 weeks vs 4-8 weeks for DIY data lake, PostgreSQL-compatible"
  - "Decision trigger matrix defines 7 quantitative thresholds: any ONE crossed justifies re-evaluation"
  - "At 5x hourly scale, PostgreSQL approaches limits (~2.8B rows); Option B or C warranted"
  - "Dissenting view documented: migrate early for operational risk reduction and cloud backup"

patterns-established:
  - "TCO range pattern: present as Low/High at two scale points, per cost category, then monthly total"
  - "Weighted decision matrix: score per dimension, multiply by weight, sum for total — do separately at each scale"
  - "ADR dissenting view: always document the counter-argument with its own counter-counter-argument"

# Metrics
duration: 4min
completed: 2026-02-25
---

# Phase 50 Plan 02: TCO Model, ADR, and Executive Summary

**Local PostgreSQL confirmed as correct architecture through 2x scale (30 assets, daily bars); TimescaleDB Cloud designated as the migration target when 7 quantitative triggers are crossed; formal ADR-001 accepted with dissenting view documented**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-25T23:06:52Z
- **Completed:** 2026-02-25T23:10:42Z
- **Tasks:** 2
- **Files created:** 3 (tco-model.md + ADR-001 + README.md)

## Accomplishments

- Created `reports/data-economics/tco-model.md` (430 lines) — three-way architecture comparison (Option A: local PostgreSQL, Option B: DIY data lake, Option C: TimescaleDB Cloud) at current/2x/5x scale, PostgreSQL scaling analysis showing the path from 70.3M rows to ~2.8B rows at 5x hourly, quantitative decision trigger matrix with 7 thresholds, weighted scoring matrix scored separately at 2x and 5x scale, primary recommendation with dissenting view, and review schedule
- Created `docs/architecture/ADR-001-data-infrastructure.md` (102 lines) — formal MADR 4.0 architecture decision record with Status: Accepted, full decision rationale, consequences (Good/Bad/Neutral with mitigations), dissenting view with counter-counter-argument
- Created `reports/data-economics/README.md` (77 lines) — executive summary with key numbers table, report contents with DATA-01/02/03 traceability, decision summary table, and next actions
- DATA-02 SATISFIED: Three-way architecture comparison at current/2x/5x scale with monthly TCO ranges per category
- DATA-03 SATISFIED: Decision trigger matrix with 7 quantitative thresholds + weighted scoring matrix

## Task Commits

Each task was committed atomically:

1. **Task 1: Write tco-model.md** — reports/ is gitignored (files written to disk, not committed). Files on disk at `reports/data-economics/tco-model.md`.
2. **Task 2: Write ADR-001 + README.md** — ADR committed as `feat(50-02)` (8468bce3). README is gitignored (reports/). ADR is in docs/architecture/ which is tracked.

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 2 | Write ADR-001-data-infrastructure.md | 8468bce3 | docs/architecture/ADR-001-data-infrastructure.md |

## Files Created/Modified

- `reports/data-economics/tco-model.md` — 430-line TCO analysis with Option A/B/C architecture descriptions, PostgreSQL scaling analysis, TCO comparison at 3 scale points, migration LOE table, quantitative trigger matrix (7 thresholds), weighted decision matrix at 2x and 5x scale, recommendation + dissenting view, review schedule
- `docs/architecture/ADR-001-data-infrastructure.md` — MADR 4.0 ADR: Status Accepted, decision (stay on PostgreSQL through 2x), rationale (5 numbered reasons), consequences (Good/Bad/Neutral with mitigations), dissenting view (5 arguments + counter), links to full analysis
- `reports/data-economics/README.md` — Executive summary: key numbers, report contents table with DATA-01/02/03 traceability, ADR link, decision summary, next actions (5 specific items), next review date

## Decisions Made

- **Stay on local PostgreSQL through 2x scale:** Weighted decision matrix scores Option A at 45/60 at 2x scale vs Option C at 53/60. The gap (45 vs 53) is not large enough to justify migration when triggers have not been crossed. Migration optionality is preserved — switching to TimescaleDB Cloud costs $400-800 one-time when needed.

- **TimescaleDB Cloud over DIY Data Lake at 5x:** At 5x scale, Option B (DIY Lake) scores 47/60 vs Option C (TimescaleDB) at 44/60 — B wins on TCO but only by 3 points. Option C wins on migration effort (1-2 weeks vs 4-8 weeks) and operational simplicity. Recommendation: Option C is the pragmatic migration target.

- **Decision trigger matrix (DATA-03):** Seven quantitative thresholds defined. Any ONE being met justifies re-evaluation. Key thresholds: >500M rows, >20 assets, >$300/mo API cost, hourly bars, >2hr daily refresh time. Current values are all comfortably below thresholds.

- **Dissenting view preserved in ADR:** The case for migrating early (operational risk, CMC fragility, low switching cost) is documented in the ADR with a counter-argument. This prevents the decision from being treated as absolute and ensures future readers understand the trade-off was considered.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written. All three documents produced with content matching specifications.

**Note on gitignore:** As established in Plan 50-01, `reports/` is gitignored by project convention. This is expected behavior. Only `docs/architecture/ADR-001-data-infrastructure.md` and planning artifacts are committed.

## Issues Encountered

- Pre-commit hook flagged mixed line endings (CRLF vs LF) in ADR-001. Hook auto-fixed the file; re-stage and recommit resolved the issue. One extra commit cycle required.

## User Setup Required

None — no external service configuration required. All documents are analysis artifacts, not runnable code.

## Next Phase Readiness

- Phase 50 is **complete** — DATA-01, DATA-02, DATA-03 all satisfied
- ADR-001 is the canonical decision record for infrastructure choice; future plans should reference it
- Decision triggers are defined; monitoring can begin immediately with the two SQL queries in tco-model.md
- Next data-related work: Phase 55 (Feature & Signal Evaluation) — running IC evaluations and scoring AMAs with real data (open problem identified in analysis)
- **No blockers** for subsequent phases

---
*Phase: 50-data-economics*
*Completed: 2026-02-25*
