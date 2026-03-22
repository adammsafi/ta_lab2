# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-21)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v1.2.0 Analysis -> Live Signals (in progress)

## Current Position

Phase: 80-ic-analysis-feature-selection COMPLETE (v1.2.0, 5/5 plans)
Plan: All 5 plans complete, awaiting verification
Status: Phase 80 execution complete, verification pending
Last activity: 2026-03-22 -- Phase 80 all plans complete, user approved feature selection

Progress: [##########] 100% v0.4.0 | [##########] 100% v0.5.0 | [##########] 100% v0.6.0 | [##########] 100% v0.7.0 | [##########] 100% v0.8.0 | [##########] 100% v0.9.0 | [##########] 100% v1.0.0 | [##########] 100% v1.0.1 | [##########] 100% v1.1.0 | [#---------] 11% v1.2.0

## Performance Metrics

**Velocity:**
- Total plans completed: 364
- Average duration: 7 min
- Total execution time: ~29.5 hours

**Recent Trend:**
- v0.8.0: 6 phases, 16 plans, ~1.2 hours
- v0.9.0: 8 phases, 35 plans + 3 cleanup, ~4.0 hours
- v1.0.0: 22 phases, 104 plans, ~14.5 hours
- v1.0.1: 10 phases, 29 plans, ~2.0 hours
- v1.1.0: 6 phases, 21 plans, ~2.5 hours
- v1.2.0 (in progress): Phase 80 = 5 plans, ~35 min
- Trend: Stable (~5-7 min/plan)

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.

v1.1.0 decisions archived to `.planning/milestones/v1.1.0-ROADMAP.md`.

**Phase 80 decisions (all plans):**
- `[analysis]` optional group added to pyproject.toml for statistical analysis libraries (statsmodels)
- `dim_feature_selection.quintile_monotonicity` column added (Spearman Q1-Q5 terminal returns)
- Stationarity enum uses uppercase strings (STATIONARY, NON_STATIONARY, AMBIGUOUS, INSUFFICIENT_DATA)
- NON_STATIONARY features use 1.5x IC-IR cutoff (0.45 vs 0.3) — soft gate, not exclusion
- Ljung-Box applied to IC series (not raw feature values) to detect inflated IC-IR
- IC-IR cutoff 1.0 (default 0.3 gave 107 active; 1.0 gives 20 active — within 15-25 goal)
- bb_ma_20 promoted from watch to active (IC-IR=1.22, NON_STATIONARY — soft gate override per user review)
- AMA features dominate active tier (18/20) — downstream must load from BOTH features + ama_multi_tf tables
- Feature selection is strategy-agnostic — ranks by IC-IR, not strategy-aligned. Strategy alignment is Phase 82/85.
- Per-asset IC-IR variation is significant — universal YAML is "core", per-asset customization at model level
- Concordance IC-IR vs MDA: rho=0.14 (low due to AMA absence from features table). IC-IR takes precedence.
- Phases 82 and 86 updated with Phase 80 learnings (AMA data loading, per-asset weighting, strategy alignment)

### Pending Todos

3 pending todos -- see .planning/todos/pending/:
- 2026-03-13: Prune null return rows (addressed by CLN-01/CLN-02 in Phase 79)
- 2026-03-15: Consolidate 1D bar builders (addressed by BAR-01 through BAR-08 in Phases 74-75)
- 2026-03-15: VWAP consolidation and daily pipeline (addressed by VWP-01/VWP-02 in Phase 79)

### Blockers/Concerns

None active.

## Session Continuity

Last session: 2026-03-22
Stopped at: Phase 80 complete, all 5 plans executed, user approved feature selection
Resume file: None

---
*Created: 2025-01-22*
*Last updated: 2026-03-22 (Phase 80 complete)*
