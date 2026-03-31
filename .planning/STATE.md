# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-29)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v1.3.0 Operational Activation & Research Expansion — Phase 99: Backtest Scaling

## Current Position

Phase: 99 of 106 IN PROGRESS (Backtest Scaling) — Plans 01-04 complete
Next: Phase 99 Plan 05 (data quality validation) or next queued plan
Status: Plan 99-03 complete — BakeoffOrchestrator extended with data_loader_fn; run_mass_backtest.py + backfill_mc_bands.py created
Last activity: 2026-03-31 — Completed 99-03-PLAN.md (orchestrator extensions + mass backtest scripts)

Progress: [##########] 100% v1.2.0 | [████████░░] 46% v1.3.0 (12/26 plans, 3/6 phases)

## Performance Metrics

**Velocity:**
- Total plans completed: 421
- Average duration: 7 min
- Total execution time: ~32.6 hours

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

Phase 98-01 decisions:
- 401 CTF features promoted via IC > 0.02 cross-asset median (PERCENTILE_CONT(0.5)) -- no artificial cap
- UPDATE pattern (not DELETE+INSERT) preserves other features columns -- same as microstructure_feature.py
- Dynamic IC query in Alembic migration: columns discovered at runtime from ic_results, idempotency guard via information_schema
- dim_feature_selection_asset separate from dim_feature_selection to avoid TRUNCATE hazard
- Pre-flight check (information_schema.columns) raises RuntimeError if migration not applied before write
- base_tf in YAML is placeholder '1D' -- promoted feature set same for all base_tfs (IC computed cross-asset)

Phase 98-02 decisions:
- Per-asset IC uses ABS(ic) > threshold (single asset value, not PERCENTILE_CONT) -- correct for single-asset evaluation
- Asset-specific additions = per_asset_passing - global_features; only write additions not already in global tier
- Write only asset-specific rows to dim_feature_selection_asset; superset is logical construct at query time
- All 98 assets have CTF IC data; all 98 have asset-specific additions (53-164 per asset, 10,716 total rows)
- dim_feature_selection verified unchanged at 205 rows before and after run (no TRUNCATE damage)

Phase 98-03 decisions:
- Vectorized pivots over row iteration: pivot.mean(axis=1), pivot.notna().sum(axis=1) replaces row-level Python loops
- Chunked 50K-row persistence: avoids large single transactions; 1.43M rows = 29 chunks @ 20s; 6.41M rows = 129 chunks
- Relative value uses per-asset composite_name (relative_value_{feat}_{asset_id}) to preserve unique PK in ctf_composites
- PCA sign correction: dominant_sign = np.sign(loadings[abs(loadings).argmax()]) ensures consistent direction across re-runs
- Materialization to features skipped: cross-asset aggregates don't map to per-asset rows (single feature column per ts, not per asset)
- Leader-follower uses full-history window leader score at last_ts; not rolling per-timestamp (would require O(n^2) rolling corr)

Phase 98-04 decisions:
- Pre-load-then-iterate: all CTF DataFrames and forward returns cached in memory dicts before inner loop -- 15 min vs hours
- Single global BH correction: collect all p-values then multipletests once (correct global FDR control, not per-pair)
- reports/ is gitignored: CSV report is local artifact; lead_lag_ic table is authoritative
- Sequential default (--workers=1): tractable for 7 assets in 15 min; --workers N for larger universes
- Valid p-value filter before BH: rows with n_obs < 30 have NaN p-value, excluded from correction array but written to DB

Phase 99-01 decisions:
- FK deliberately dropped on partitioned backtest_trades: PostgreSQL partitioned tables do not support row-level FK; join via run_id at query time
- Default partition created for 'unknown' and future strategy names not in initial 8-partition list
- mc_sharpe_* go on strategy_bakeoff_results (not backtest_metrics): bakeoff pipeline is the writer; c3d4e5f6a1b2 backtest_metrics columns untouched
- run_claude.py added to .gitignore: pre-existing root file triggered always_run no-root-py-files hook; moved temporarily during commit

Phase 99-02 decisions:
- ctf_threshold uses **params dict extraction (not keyword-only args) to match registry YAML-driven call convention
- holding_bars=0 disables time-based exit in ctf_threshold (consistent with ama_composite pattern)
- YAML grid structure: strategy_name.params list of flat dicts -- compatible with simple yaml.safe_load() + iteration
- macd_crossover baseline for 3x comparison is registry.py grid_for() return of 3 (not _BAKEOFF_PARAM_GRIDS which lacks it)

Phase 99-03 decisions:
- data_loader_fn used in sequential mode (workers=1); data_loader_type/kwargs used in parallel mode to avoid pickle failures with partial()
- BakeoffAssetTask.data_loader_type='ctf' reconstructs load_strategy_data_with_ctf() inside worker; avoids cross-process partial() pickle issues
- mass_backtest_state tracks at (strategy, asset, params_hash) level; cost_bps=0.0 sentinel for 'all costs for this params combo'
- Pre-flight check in backfill_mc_bands.py raises RuntimeError with migration guidance if mc_sharpe_lo/hi/median columns absent
- load_strategy_data_with_ctf() validates columns via information_schema.columns before SELECT to avoid KeyError on absent CTF cols

Phase 99-04 decisions:
- ci_source column computed in load_leaderboard_with_mc() at query level (not display level): all callers get the correct source indicator
- IC join in load_ctf_lineage() wrapped in try/except: missing ic_results data before CTF runs complete should not crash the lineage tab
- PBO heatmap always uses cv_method='cpcv' regardless of sidebar selection: PBO is only meaningful from CPCV runs
- load_pbo_heatmap_data() uses groupby().mean() before unstack(): collapses multiple param combos per (strategy, asset) to a single representative PBO value

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
- Phase 98-01 NOTE: refresh_ctf_promoted.py 1D refresh takes ~13 minutes (row-by-row UPDATE with 401 cols). Acceptable for periodic refresh; full all-base_tfs run ~60 min.

## Session Continuity

Last session: 2026-03-31
Stopped at: Completed 99-03-PLAN.md (BakeoffOrchestrator extension + run_mass_backtest.py + backfill_mc_bands.py). Next: 99-04 or 99-05.
Resume file: None

---
*Created: 2025-01-22*
*Last updated: 2026-03-31 (Phase 99-03 complete: mass backtest orchestrator + MC bands backfill)*
