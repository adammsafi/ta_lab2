# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-29)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v1.3.0 Operational Activation & Research Expansion — Phase 97: FRED Macro Expansion

## Current Position

Phase: 97 of 101 COMPLETE (FRED Macro Expansion)
Plan: 2 of 2 complete in Phase 97
Status: Phase 97 fully complete; ready for Phase 98
Last activity: 2026-03-31 — Completed 97-02-PLAN.md (multi-window BTC-equity correlation)

Progress: [##########] 100% v1.2.0 | [████░░░░░░] 23% v1.3.0 (6/26 plans, 2/6 phases)

## Performance Metrics

**Velocity:**
- Total plans completed: 415
- Average duration: 7 min
- Total execution time: ~32.3 hours

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

Phase 96-02 decisions:
- Self-contained _compute_macd in macd_crossover.py (not imported from registry) to avoid circular import: registry.py try/except silently sets macd_crossover_signal=None if circular import detected
- AMASignalGenerator loads from ama_multi_tf_u with DISTINCT ON deduplication (alignment_source='multi_tf', roll=FALSE)
- BATCH_1_TYPES/BATCH_2_TYPES exposed at module level in run_all_signal_refreshes for external reference

Phase 96-03 decisions:
- All 8 executor configs use sizing_mode='bl_weight' with position_fraction=0.10 as fallback
- bl_weight returns Decimal('0') (flat/close) when BL de-selects asset -- executor closes open position
- seed_watermarks() sets last_processed_signal_ts=MAX(ts) for active configs with NULL watermark (prevents historical replay)
- 6 new signal configs (RSI, ATR, MACD, 3 AMA) will be skipped at seed time until their dim_signals entries exist

Phase 97-01 decisions:
- db_columns allowlist must NOT duplicate raw columns already in list(_RENAME_MAP.values()); only add derived columns explicitly to avoid duplicate DataFrame columns
- _EQUITY_INDEX_SERIES loop pattern: add new equity indices by extending the list, not copy-pasting feature blocks
- forward_fill.py FFILL_LIMITS already had SP500/NASDAQCOM/DJIA at limit=5 before this plan; SERIES_TO_LOAD was the gap

Phase 97-02 decisions:
- 'window' double-quoted in all SQL: PostgreSQL reserved word; _q() helper wraps it in INSERT/SELECT/ON CONFLICT clauses
- venue_id=1 filter on BTC returns: returns_bars_multi_tf_u has one row per (id, venue_id, date); without filter duplicates cause all-NaN rolling corr
- Backward-compat default window=60 in upsert: old XAGG-04 callers without window column get 60 injected automatically
- Sign-flip alerts filtered to window=60: 4 windows x 3 vars would 12x alert volume without this gate
- .values[i] with enumerate() instead of .get(dt): avoids Series-return from DatetimeIndex on union of daily/business-day calendars

Phase 96-04 decisions:
- AVG(sharpe_mean) cross-asset aggregate from strategy_bakeoff_results (not per-asset rows which are noisy)
- orders.signal_id (not strategy_id which does not exist) is the correct join key to filter fills per strategy
- regex re.sub(r'_paper_v\d+$', '', config_name) extracts strategy_name for bakeoff lookup
- BTC (asset_id=1) as benchmark for all current asset classes; extensible to SPX for Phase 97 equity class
- Minimum sample thresholds: fill Sharpe >= 2 round-trips; MTM Sharpe >= 5 days; below threshold returns NULL not zero

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

Last session: 2026-03-31
Stopped at: Phase 97 Plan 02 COMPLETE (97-02-SUMMARY.md written). Phase 97 fully done. Next: Phase 98 (CTF Graduation).
Resume file: None

---
*Created: 2025-01-22*
*Last updated: 2026-03-31 (Phase 97-02 complete — Phase 97 done)*
