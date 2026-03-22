# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-21)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v1.2.0 Analysis -> Live Signals (in progress)

## Current Position

Phase: 80-ic-analysis-feature-selection (v1.2.0, plan 3 of 5 complete)
Plan: 80-03 complete, 80-04 next
Status: In progress
Last activity: 2026-03-22 -- Completed 80-03-PLAN.md (run_feature_selection.py CLI + configs/feature_selection.yaml)

Progress: [##########] 100% v0.4.0 | [##########] 100% v0.5.0 | [##########] 100% v0.6.0 | [##########] 100% v0.7.0 | [##########] 100% v0.8.0 | [##########] 100% v0.9.0 | [##########] 100% v1.0.0 | [##########] 100% v1.0.1 | [##########] 100% v1.1.0 | [###-------] 50% v1.2.0

## Performance Metrics

**Velocity:**
- Total plans completed: 360
- Average duration: 7 min
- Total execution time: ~28.9 hours

**Recent Trend:**
- v0.8.0: 6 phases, 16 plans, ~1.2 hours
- v0.9.0: 8 phases, 35 plans + 3 cleanup, ~4.0 hours
- v1.0.0: 22 phases, 104 plans, ~14.5 hours
- v1.0.1: 10 phases, 29 plans, ~2.0 hours
- v1.1.0: 6 phases, 21 plans, ~2.5 hours
- Trend: Stable (~5-7 min/plan)

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.

v1.1.0 decisions archived to `.planning/milestones/v1.1.0-ROADMAP.md`.

**Phase 80-01 decisions:**
- `[analysis]` optional group added to pyproject.toml for statistical analysis libraries (statsmodels)
- `dim_feature_selection.quintile_monotonicity` column added (Spearman Q1-Q5 terminal returns) beyond RESEARCH.md schema
- Stationarity enum uses uppercase strings (STATIONARY, NON_STATIONARY, AMBIGUOUS, INSUFFICIENT_DATA)

**Phase 80-02 decisions:**
- NON_STATIONARY features use 1.5x IC-IR cutoff (0.45 vs 0.3) — soft gate, not exclusion, per CONTEXT.md
- Ljung-Box applied to IC series (not raw feature values) to detect inflated IC-IR from serial correlation
- `compute_monotonicity_score` accepts 1-row DataFrames (terminal row has 5 quintile values for spearmanr)
- `save_to_db` uses TRUNCATE + INSERT (snapshot table, full replace each run)
- KPSS InterpolationWarning suppressed via `warnings.catch_warnings()` context

**Phase 80-03 decisions:**
- IC-IR cutoff 1.0 used for feature_selection.yaml (default 0.3 gave 107 active; 1.0 gives 19 — within 15-25 goal)
- AMA features get INSUFFICIENT_DATA for stationarity (correct: they live in ama_multi_tf_u, not features table)
- 0 archive-tier features at cutoff 1.0 — all 205 features have IC signal (watch or better)
- No-signal features list (SC-1) is empty — all 205 features have |IC-IR| > 0.1 at some horizon

### Pending Todos

3 pending todos -- see .planning/todos/pending/:
- 2026-03-13: Prune null return rows (addressed by CLN-01/CLN-02 in Phase 79)
- 2026-03-15: Consolidate 1D bar builders (addressed by BAR-01 through BAR-08 in Phases 74-75)
- 2026-03-15: VWAP consolidation and daily pipeline (addressed by VWP-01/VWP-02 in Phase 79)

### Blockers/Concerns

None active.

## Session Continuity

Last session: 2026-03-22
Stopped at: Completed 80-03-PLAN.md (run_feature_selection.py CLI + configs/feature_selection.yaml)
Resume file: None

---
*Created: 2025-01-22*
*Last updated: 2026-03-22 (80-03 complete)*
