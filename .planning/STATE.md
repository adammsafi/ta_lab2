# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-29)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v1.3.0 Operational Activation & Research Expansion — Phase 109 in progress (feature skip-unchanged optimization)

## Current Position

Phase: 109 of 111 IN PROGRESS (Feature Skip-Unchanged) — 1/2 plans complete
Also: Phase 108 COMPLETE (Pipeline Batch Performance) — 5 plans, all complete
Also: Phase 103 COMPLETE (Traditional TA Expansion) — 3/3 plans complete
Status: Plan 109-01 complete — feature_refresh_state table + 4 watermark helpers ready
Last activity: 2026-04-01 — Completed 109-01-PLAN.md

Progress: [##########] 100% v1.2.0 | [█████████░] 80% v1.3.0 (21/26 plans, 6/6 phases)

## Performance Metrics

**Velocity:**
- Total plans completed: 424
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

Phase 107-01 decisions:
- DO $$ DECLARE in migration to look up CHECK constraint name dynamically: avoids hardcoding auto-generated name
- Kill switch exits code 2 (not 1): distinguishes intentional kill from stage failure; dashboard can show 'killed' status
- _maybe_kill deletes .pipeline_kill after acting: prevents stale file re-triggering on next run
- KILL_SWITCH_FILE at repo root (4 parent-hops from script): one path shared by orchestrator and future dashboard

Phase 108-04 decisions:
- Watermark VALUES CTE uses literal embedding (not bound params): PostgreSQL VALUES type inference fails with bound params causing 'record = integer' type mismatch
- _build_wm_cte rows must NOT have outer parens: VALUES (a,b,c),(d,e,f) not VALUES ((a,b,c),(d,e,f))
- Empty watermarks sentinel CTE (WHERE FALSE): LEFT JOIN produces all-NULL rows -> all rows pass watermark filter (correct for first run)
- _run_one_id_mp returns Tuple[int,int] = (id_, signal) so caller can log which ID completed not just ordinal

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

Phase 108-01 decisions:
- PARTITION BY (tf, period, venue_id) for unified LAG, PARTITION BY (tf, period, venue_id, roll) for canonical LAG — preserves exact per-key semantics when iterating all combos in one CTE
- Global min watermark as seed anchor: min() across all keys for the ID; NULL if any key lacks watermark (full history required)
- LEFT JOIN state table for per-key to_insert filter: cleaner than VALUES clause, single indexed lookup per (tf, period, venue_id) row
- Bulk state update: INSERT...SELECT GROUP BY with GREATEST(): one upsert per combo vs one UPDATE per key
- Pre-ruff-format before staging: prevents pre-commit stash/restore failure when unstaged changes exist in other files

Phase 108-02 decisions:
- Fast-path threshold = 7 days: watermarks older than 7 days trigger full recompute; configurable via --fast-path-threshold-days
- Virtual seed row pattern: when daily grid starts after seed_ts (common daily incremental case), prepend virtual row with seed_ema_bar, run compute_dual_ema_numpy, drop index 0 from output
- load_recent_bars() uses price_bars_1d (not cmc_price_histories7): matches MultiTFEMAFeature.load_source_data() actual source
- --full-refresh implicitly sets no_fast_path=True: full-recompute semantics honored
- state_table passed through extra_config to worker: worker creates own EMAStateManager using correct state table name

Phase 108-03 decisions:
- _BATCH_SIZE=15: amortizes NullPool engine creation across ~15 IDs per engine (was 1 engine per ID)
- Bulk preload done in _process_source (coordinator), not workers: watermarks passed as data args to keep workers stateless and picklable
- Source-advance skip: smax <= wm means no new data, skip entirely; on incremental runs most IDs will be skipped
- _worker returns list[dict] (not dict): caller iterates batch_results from pool.imap_unordered
- SET LOCAL work_mem per engine.begin() transaction preserved: correct scope; connection-level SET would not carry to begin() blocks

Phase 102-02 decisions:
- Block bootstrap pair indexing: apply bs.index to both feat_clean and ret_clean jointly (not returns-only); bootstrapping only returns destroys feature/return alignment and produces CIs near zero
- arch 8.0.0 optimal_block_length() column: "stationary" (not "b_sb" from older versions); documented in module docstring
- haircut_ic_ir conn=None guard: when conn is None, get_trial_count() returns 0 and n_trials=0 edge case returns no-penalty result; enables pure-computation use in notebooks
- Bonferroni HL method applies identically to IC-IR as to Sharpe (both are t-stat / sqrt(n) structures)

Phase 102-01 decisions:
- tf column in trial_registry uses VARCHAR(32) not VARCHAR(16): actual tf values reach 18 chars ('10W_CAL_ANCHOR_ISO') -- fixed Rule 1 bug during execution
- Backfill filters to horizon=1 AND return_type='arith' only: permutation scope reduction; 757K rows from 10.6M ic_results source
- ON CONFLICT preserves perm_p_value, fdr_p_adjusted, passes_fdr, bb_ci columns, haircut_ic_ir: expensive computations must survive IC re-sweeps
- Migration chains from t4u5v6w7x8y9 (actual head) not s3t4u5v6w7x8 as specified: Phase 107 added t4u5v6w7x8y9 after Phase 99
- multiple_testing.py functions appended not rewriting: file already contained haircut_sharpe, block_bootstrap_ic, get_trial_count from 102-02

Phase 102-03 decisions:
- log_trials_to_registry placed inside if all_ic_rows block: no-op when sweep produces no rows (save_ic_results not called, neither is log_trials_to_registry)
- try/except wraps all 4 log_trials_to_registry call sites: IC sweep integrity preserved if registry fails (warnings logged, sweep continues)
- perm_p_value gate applied after IC-IR classification as a downgrade-only override — existing IC-IR logic determines base tier, then perm gate can only lower it
- Early-return tier pattern refactored to tier-variable pattern to enable post-classification gate application cleanly
- perm_p_value < 0.05 passes the gate with no constraint — consistent with standard 5% significance threshold

Phase 103-02 decisions:
- chaikin_osc output column fixed to 'chaikin_osc' (not chaikin_osc_3_10): matches schema DDL and migration column name
- coppock output column fixed to 'coppock' (not coppock_10): matches schema DDL and migration column name
- ichimoku get_feature_columns uses hardcoded string list: output col names are param-independent (always ichimoku_tenkan/kijun/span_a/span_b/chikou)
- mass_index column name uses mass_idx_{sum_period} matching indicators_extended default out_col pattern

Phase 109-01 decisions:
- down_revision = w6x7y8z9a0b1 (actual head): plan specified t4u5v6w7x8y9 but phases 100, 102, 103 added migrations after 107; use actual head per established precedent
- No venue_id in feature_refresh_state PK: features use venue_id=1 only; can be added via follow-up migration if multi-venue support added
- compute_changed_ids returns 3-tuple (changed_ids, unchanged_ids, bar_watermarks): bar_watermarks passed through to avoid redundant query in _update_feature_refresh_state
- total_rows_written in _update_feature_refresh_state is batch total (not per-asset): sufficient for monitoring

Phase 103-03 decisions:
- Shell out to run_all_feature_refreshes (--ta --all-tfs) instead of importing TAFeature: reuses all existing batching/parallelism, avoids managing second engine
- Direct SQL to load features (SELECT ts, <cols>, close) scoped to Phase 103 columns: avoids loading all 112+ feature columns into memory
- FDR uses MIN(ic_p_value) per indicator: most lenient cross-asset aggregation gives highest statistical power for indicator discovery
- trial_registry.indicator_name stores feature column names (e.g. 'willr_14'): validate_coverage() checks by _PHASE103_FEATURE_COLS list not indicator names

## Session Continuity

Last session: 2026-04-01
Stopped at: Completed 109-01-PLAN.md
Resume file: None

---
*Created: 2025-01-22*
*Last updated: 2026-04-01 (Phase 109-01 complete: feature_refresh_state table + 4 watermark helpers; Plan 02 wires into run_all_refreshes)*
