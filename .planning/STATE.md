# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-29)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v1.3.0 Operational Activation & Research Expansion — Phase 96: Executor Activation

## Current Position

Phase: 96 of 101 (Executor Activation)
Plan: 1 of 4 complete
Status: In progress
Last activity: 2026-03-30 — Completed 96-01-PLAN.md (schema foundation)

Progress: [##########] 100% v1.2.0 | [█░░░░░░░░░] 4% v1.3.0 (1/26 plans)

## Performance Metrics

**Velocity:**
- Total plans completed: 412
- Average duration: 7 min
- Total execution time: ~31.8 hours

**Recent Trend:**
- v0.9.0: 8 phases, 35 plans, ~4.0 hours
- v1.0.0: 22 phases, 104 plans, ~14.5 hours
- v1.0.1: 10 phases, 29 plans, ~2.0 hours
- v1.1.0: 6 phases, 21 plans, ~2.5 hours
- v1.2.0: 16 phases, 52 plans, ~10.5 hours
- Trend: Stable (~5-7 min/plan)

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.

v1.1.0 decisions archived to `.planning/milestones/v1.1.0-ROADMAP.md`.
v1.2.0 decisions archived to `.planning/milestones/v1.2.0-ROADMAP.md`.

v1.3.0 key decisions:
- Phase 96 (Executor Activation) first — burn-in time is rate-limiting; every day it doesn't run is a day lost
- Phase 97 (FRED Macro) sequenced second — self-contained, no blockers, captures pending SP500/NASDAQ/DJIA todos
- Phase 98 (CTF Graduation) before Phase 99 (Backtest) — CTF-05 signals need promoted features in features table
- Phase 100 (ML) last of research — depends on CTF features (CTF-01) and backtest infra (BT-01/BT-02)
- Phase 101 (Tech Debt) final — documentation only, no runtime impact

Phase 96-01 decisions:
- Seed dim_signals IN the Alembic migration (not in seeder script): seed_executor_config.py resolves signal_name -> signal_id from dim_signals; missing rows cause silent config skips
- Single migration file for all Phase 96 changes: ensures all-or-nothing atomicity
- executor_processed_at must exist in all new signal tables before executor starts (replay guard)

### Pending Todos

7 pending todos resolved into v1.3.0 phases:
- 2026-03-28: CTF production integration → Phase 98 (CTF-01)
- 2026-03-28: Asset-specific CTF feature selection → Phase 98 (CTF-02)
- 2026-03-28: Cross-asset CTF composites → Phase 98 (CTF-03)
- 2026-03-28: CTF lead-lag IC matrix → Phase 98 (CTF-04)
- 2026-03-28: FRED equity indices macro pipeline → Phase 97 (MACRO-01, MACRO-02)
- 2026-03-29: Massive backtest & Monte Carlo expansion → Phase 99 (BT-01 through BT-07)
- 2026-03-29: v1.2.0 low tech debt cleanup → Phase 101 (DEBT-01 through DEBT-04)

### Blockers/Concerns

- Phase 96 pitfall: executor silent no-op if dim_executor_config empty — seed FIRST, verify fills exist before burn-in
- Phase 96 pitfall: signal replay risk if historical signals not marked processed before executor starts
- Phase 96-01 RESOLVED: dim_signals seeded in migration (4 new rows with JSONB params) — no silent skips for new signal types
- Phase 99 pitfall: DSR under-deflation at 460K runs (N so large it inflates PSR) — document known limitation
- Phase 99 pitfall: Windows Pool hang with multiprocessing — use NullPool + maxtasksperchild=1
- Phase 100 dependency: ML-01/ML-02/ML-03 require CTF features in features table (Phase 98 must complete first)

## Session Continuity

Last session: 2026-03-30
Stopped at: Completed 96-01-PLAN.md (schema foundation — migration applied, SIGNAL_TABLE_MAP updated)
Resume file: None

---
*Created: 2025-01-22*
*Last updated: 2026-03-30 (96-01 schema foundation complete)*
