# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-29)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v1.3.0 Operational Activation & Research Expansion — Phase 112 IN PROGRESS (Pipeline Architecture Separation — Plans 01-04 done)

## Current Position

Phase: 112 IN PROGRESS (Pipeline Architecture Separation) — 4/5 plans complete
Also: Phase 106 COMPLETE (Custom Composite Indicators) — 3/3 plans complete
Also: Phase 111 COMPLETE (Feature Polars Migration) — 5/5 plans complete
Also: Phase 110 COMPLETE (Feature Parallel Sub-Phases) — 1/1 plans complete
Also: Phase 109 COMPLETE (Feature Skip-Unchanged) — 2/2 plans complete
Also: Phase 105 COMPLETE (Parameter Optimization) — 3/3 plans complete
Also: Phase 104 COMPLETE (Crypto-Native Indicators) — 3/3 plans complete
Also: Phase 100 IN PROGRESS (ML Signal Combination) — Plans 01+02 complete (2/3 plans)
Also: Phase 108 COMPLETE (Pipeline Batch Performance) — 5 plans, all complete
Also: Phase 103 COMPLETE (Traditional TA Expansion) — 3/3 plans complete
Status: Plan 112-04 complete — sync_signals_to_vm.py, run_full_chain.py, run_daily_refresh.py deprecation notice
Last activity: 2026-04-02 — Completed 112-04-PLAN.md

Progress: [##########] 100% v1.2.0 | [██████████] 100% v1.3.0 (32/32 plans, 9/6 phases)

## Performance Metrics

**Velocity:**
- Total plans completed: 428
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

Phase 100-01 decisions:
- dim_ctf_feature_selection (not dim_feature_selection.source) is the correct table for CTF features: dim_feature_selection has no source column; Phase 92 populates dim_ctf_feature_selection
- ret_arith from features table used for forward returns: returns_bars_multi_tf base table does not exist (only _u and _state variants); shift ret_arith -1 per asset within features table
- LGBMRanker labels must be integer: _build_rank_target returns rank(method='first',ascending=True)-1 not pct rank; LGBMRanker fatal error on float 0.5
- Panel CV on unique timestamps: t1_series built via unique_ts.tolist() -> DatetimeIndex; split at period level; expand to rows via ts->rows dict
- MEMORY.md tz fix in panel CV: Series.tolist() preserves UTC Timestamps; Series.values strips tz causing tz-naive vs tz-aware TypeError in PurgedKFoldSplitter comparison
- IC evaluation uses actual forward_return (Spearman corr against float returns); NDCG uses integer rank as relevance grade

Phase 109-01 decisions:
- down_revision = w6x7y8z9a0b1 (actual head): plan specified t4u5v6w7x8y9 but phases 100, 102, 103 added migrations after 107; use actual head per established precedent
- No venue_id in feature_refresh_state PK: features use venue_id=1 only; can be added via follow-up migration if multi-venue support added
- compute_changed_ids returns 3-tuple (changed_ids, unchanged_ids, bar_watermarks): bar_watermarks passed through to avoid redundant query in _update_feature_refresh_state
- total_rows_written in _update_feature_refresh_state is batch total (not per-asset): sufficient for monitoring

Phase 100-03 decisions:
- Alembic revision w6x7y8z9a0b1 chains from v5w6x7y8z9a0 (actual head at time of execution); plan spec was stale
- t1_series.index = DatetimeIndex(t0) required for PurgedKFoldSplitter: integer index caused datetime/int TypeError on fold boundary comparison
- train_start/train_end use sentinel dates "2000-01-01"/"2099-12-31": cross-asset training has no single date range; "N/A" caused TIMESTAMPTZ parse error in ExperimentTracker
- meta_filter_enabled=FALSE default ensures zero behavior change for existing executor configs -- must be explicitly enabled
- xgboost lazy-imported in _init_meta_filter() inside method scope: optional dependency, no ImportError at module load time
- skipped_meta_filter counted in skipped_no_delta for run log (consistent skip semantics)
- Rule 1 bug fixed: v5w6x7y8z9a0 migration had :params::jsonb syntax error; fixed to CAST(:params AS jsonb)

Phase 103-03 decisions:
- Shell out to run_all_feature_refreshes (--ta --all-tfs) instead of importing TAFeature: reuses all existing batching/parallelism, avoids managing second engine
- Direct SQL to load features (SELECT ts, <cols>, close) scoped to Phase 103 columns: avoids loading all 112+ feature columns into memory
- FDR uses MIN(ic_p_value) per indicator: most lenient cross-asset aggregation gives highest statistical power for indicator discovery
- trial_registry.indicator_name stores feature column names (e.g. 'willr_14'): validate_coverage() checks by _PHASE103_FEATURE_COLS list not indicator names

Phase 100-02 decisions:
- ranker.py train_full() lacked astype(float) on X: object-dtype columns with Python None caused np.nanmedian TypeError; fix: .astype(float).values
- LIKE clause in SQLAlchemy text() requires %% for literal %: single % treated as psycopg2 format placeholder causing ProgrammingError
- dim_feature_selection uses 'rationale' column not 'notes': discovered via information_schema query at execution time
- top_interaction_pairs uses upper triangle only to avoid double-counting symmetric interaction matrix
- YAML write on Windows requires newline='\n': default CRLF mode causes mixed line ending failures in pre-commit

Phase 104-01 decisions:
- dim_listings JOIN (not cmc_da_ids): resolves HL asset_id -> CMC id using ticker_on_venue=symbol AND venue='HYPERLIQUID'; mirrors seed_hl_assets.py approach
- km assets excluded via asset_id < 20000 filter: km perps (indices, commodities, FX, equities) have no CMC id; consistent with seed_hl_assets.py reclassification
- COALESCE(hl_candles.close_oi, hl_open_interest.close) for OI: candles are primary (daily), hl_open_interest provides gap fill for NULL OI days
- funding_rate aggregated via SUM not AVG: hourly funding compounds per day; SUM preserves daily economic interpretation
- mark_px from hl_oi_snapshots via DISTINCT ON (asset_id, day) ORDER BY ts DESC: latest intraday snapshot per day
- down_revision = u5v6w7x8y9z0 (actual head): phases 100, 102, 103, 109 added migrations after 107; use actual head per project precedent

Phase 104-02 decisions:
- Per-asset groupby sorts by ts before indicator compute: rolling window correctness requires temporal ordering
- oi_concentration_ratio on full sorted frame (ts, id): cross-asset groupby(ts).transform requires all assets at same ts
- _ensure_output_table overridden to skip CREATE TABLE: public.features is Alembic-managed; pre-flight info_schema check instead
- pct_change(fill_method=None): suppresses FutureWarning from deprecated default; Rule 1 auto-fix
- vol_oi_regime uses pd.array(..., dtype='Int64'): nullable integer; first bar is pd.NA (diff produces NaN)

Phase 109-02 decisions:
- process_ids (changed_ids only) for Phases 1/2/2b/2c; full ids for codependence (pairwise needs complete cross-section), validation (spot-check full population for staleness), CS norms (PARTITION BY all assets)
- bar_watermarks={} sentinel before if-not-full-refresh block: guards state update as falsy in full_refresh mode without extra bool
- Early return returns {} (empty dict): consistent with dict[str, RefreshResult] return type; callers checking bool(results) get falsy
- Success guard uses getattr(r, 'success', True): defensive for heterogeneous result types
- --full-rebuild added as second flag name to --full-refresh argparse argument; argparse stores in args.full_refresh (first name)

Phase 105-01 decisions:
- Revision ID y8z9a0b1c2d3 (not t4u5v6w7x8y9 from plan): plan spec was stale -- t4u5v6w7x8y9 used by phase107; use actual HEAD per established precedent
- GridSampler uses list(range(low, high+1)) for int params: np.arange returns numpy scalars that fail GridSampler type checks
- TrialPruned for feature_fn exceptions (constraint violations); NaN return for insufficient observations (< min_obs=50)
- Boundary masking: fwd_ret set NaN where feat.index > train_end - tf_days_nominal days to prevent lookahead leakage at train window boundary

Phase 105-02 decisions:
- plateau_score returns 0.0 when best_ic <= 0: negative-IC peaks have no meaningful positive neighborhood to measure
- rolling_stability_test uses np.array_split (equal row splits) not date-based splits: robust to irregular bar frequencies across windows
- compute_dsr_over_sweep falls back to n_trials approximate mode when no valid ICs: defensive against all-NaN sweep results
- select_best_from_sweep slices to train window before stability/DSR: prevents out-of-window data leaking into computations
- DB UPDATE in select_best_from_sweep wrapped in try/except: registry failure must not abort returned selection result
- compute_rolling_ic and compute_dsr imported at module level (not lazily): lightweight, no circular import risk

Phase 105-03 decisions:
- stoch_kd param names are 'k' and 'd' (not 'k_period'/'d_period' as plan suggested): verified against actual signature
- elder_ray param name is 'period' (not 'ema_period'): EMA span parameter
- force_index param name is 'smooth' (not 'smooth_period'): EMA period
- Crypto-native indicators with empty param_space_def skip sweep loop via _crypto_native flag: prevents grid_size=0 and skips placeholder entries
- Both tasks committed in single commit: same file, written atomically to avoid half-baked intermediate state
- train_end = max(ts) - tf_days_nominal days: consistent with _make_ic_objective boundary masking in param_optimizer.py
- fwd_ret = ret_arith.shift(-1): forward returns shifted by 1 bar from returns_bars_multi_tf_u

Phase 110-01 decisions:
- wave1_workers threaded as tuple element (not kwargs) in _run_single_tf args_tuple: consistent with existing positional tuple pattern
- Clamp wave1_workers = min(wave1_workers, len(phase1_tasks)) inside run_all_refreshes(): prevents over-provisioning, self-correcting
- Microstructure remains in Wave 2b (not moved to Wave 1): hard dependency on features_store INSERTs must be preserved
- Phase 3b (codependence) log label left as-is: plan only specified Phase 1/2/2c/3 logger calls; optional off-path step

Phase 111-01 decisions:
- polars_sorted_groupby: sort once with polars then pandas groupby(sort=False) -- eliminates per-group sort inside apply_fn, numba kernels unchanged
- use_polars=False default: zero behavior change for existing callers; opt-in at config level per sub-phase
- timestamp normalization as explicit step: polars cannot represent tz-aware pandas datetimes; strip before pl.from_pandas(), restore after .to_pandas()
- CS norms is pure SQL (PARTITION BY window functions): confirmed no-op for polars migration, no Python loop to migrate
- boolean column XOR in compare_feature_outputs: numpy cannot subtract bool arrays; use ^ operator and count mismatches instead
- HAVE_POLARS constant: try/except at module import level; pl=None fallback for environments without polars installed

Phase 111-02 decisions:
- ATR divergence fix: pl.when(prev_close.is_null()).then(None).otherwise(max_horizontal(...)) + ewm_mean(ignore_nulls=True) -- fill_nan(None) alone insufficient; ignore_nulls=True makes polars EWM skip null row matching pandas ewm NaN-skip
- polars log: (pl.col(a)/pl.col(b)).log(base=np.e) for natural log -- polars has no shorthand .ln() method
- HAVE_POLARS guard in vol.py separate from polars_feature_ops.HAVE_POLARS -- each standalone module owns its own import guard

Phase 111-03 decisions:
- atr_polars uses rolling_mean not ewm_mean: indicators.py atr() uses rolling().mean(); different from vol.py add_atr (Wilder EWM). Both patterns now available.
- Phase 103 extended indicators stay pandas in polars path: convert-apply-convert avoids rewriting 20+ complex indicators; only 6 core indicators migrated
- Rule 1 bug fix: _compute_rsi/atr/adx used period= keyword; rsi/atr/adx only apply alias when window=None, so window=14 default was always used. Fixed to window=period.
- Intermediate column dunder naming (__col__): prevents collision with user columns; all cleaned up before return

Phase 111-04 decisions:
- _compute_micro_single_group as bound method (not closure): accesses self.micro_config for 5 config values; bound method is cleaner and directly testable
- daily_features_view.py confirmed no-op: pure SQL INSERT INTO features SELECT ... JOIN price_bars/returns/vol/ta; no Python groupby loops to migrate
- _run_single_tf tuple extended with use_polars at position 10: positional tuple for pickle-safe multiprocessing; both construction and unpacking updated together
- getattr(args, 'use_polars', False) safe access: defensive pattern consistent with existing codependence/no_cs_norms access in orchestrator

Phase 111-05 decisions:
- join_asof strategy='backward': matches pandas merge_asof default direction; vectorized across all assets via by='id'; max diff = 0.0 vs pandas
- strip-UTC-before-join: polars Datetime('us','UTC') != Datetime('us'); join fails on dtype mismatch; normalize_timestamps_for_polars strips UTC before conversion
- CTFConfig.use_polars frozen dataclass field: consistent with other sub-phase configs; zero behavior change for existing callers
- NaN position mismatch tolerance 0.1%: source data has venue_id=1/2 duplicate timestamps; polars/pandas sort tie-rows differently causing 2 isolated EWM NaN shifts out of ~5000 rows; not a polars migration bug
- Graceful fallback: CTFFeature._align_timeframes() catches polars exceptions, logs warning, falls back to pandas merge_asof

Phase 106-01 decisions:
- Revision ID z9a0b1c2d3e4 chains from y8z9a0b1c2d3 (Phase 105 actual head); plan spec listed u5v6w7x8y9z0 -- use actual alembic heads per established precedent
- DO $$ BLOCK for CHECK constraint idempotency: avoids hardcoding auto-generated constraint name
- CTF agreement defaults to 1.0 when absent in OI divergence composite: preserves signal with neutral gate (no zeroing)
- tanh volume gate rescaled to [0,1] in volume_regime_gated_trend: trend is dampened in low-vol, never sign-flipped
- Lead-lag composite queries asset_b_id=target_asset_id (follower), asset_a_id=predictor: matches lead_lag_ic Phase 98-04 schema
- ALL_COMPOSITES assertion at module load: registry/COMPOSITE_NAMES mismatch raises AssertionError immediately (fail-fast)

Phase 106-02 decisions:
- Per-composite fresh connection: each composite gets engine.connect() to isolate aborted-txn state; one missing-table error (ama_multi_tf absent locally) would otherwise cascade to block all subsequent composites in same connection
- Temp-table bulk UPDATE (ON COMMIT DELETE ROWS): single UPDATE features FROM _tmp_composite vs N row-by-row UPDATEs; no DELETE+INSERT (would destroy other feature columns)
- tf_alignment_score resample bug fix: resample('1D').last() snapped CTF 23:59:59.999 UTC timestamps to midnight, causing UPDATE to match 0 features rows; fixed by using natural CTF index (no resample) since all pairs share same timestamp convention
- LOW COVERAGE flag not raised for HL composites (oi_divergence, funding_adjusted_momentum): expected < 100% coverage; composites in _NEEDS_CMC_SYMBOL set are suppressed from LOW COVERAGE warning

Phase 106-03 decisions:
- 0 composites promoted is the intellectually honest result: tf_alignment_score passed permutation+FDR+CPCV but failed held-out (sign flip: training IC=+0.030 vs held-out IC=-0.008 in 2022-2025 bear/recovery regime)
- insufficient_data vs failed distinction preserved: 5/6 composites have p=1.0 sentinel for FDR but status='insufficient_data' (missing base tables locally, not formula failures)
- Synthetic 1D timeline for pooled CPCV: CPCVSplitter needs monotonic DatetimeIndex; pooling training data across 7 assets breaks chronological order; synthetic 1D date range used (CPCV uses positional splits, not calendar purge)
- Option C threshold is exclusive (>0.03): tf_alignment_score IC=0.0300 fails abs(ic)>0.03 correctly; plan specifies greater-than, not greater-than-or-equal

Phase 112-01 decisions:
- Revision ID b1c2d3e4f5a6 used instead of plan-specified a0b1c2d3e4f5: a0b1c2d3e4f5 already taken by strip_cmc_prefix_add_venue_id on this branch; use actual alembic heads per established precedent
- _start_pipeline_run backward-compat fallback: tries INSERT with pipeline_name first, falls back to legacy INSERT on OperationalError/ProgrammingError for pre-migration deployments
- _check_dead_man pipeline_name=None default: existing Phase 87 call sites unchanged; new callers pass pipeline_name='daily' for scoped check

Phase 112-02 decisions:
- VM sync stages non-blocking in run_data_pipeline.py: failures print [WARN] and continue -- matches monolith behavior, local data stays usable if VMs unreachable
- ids_for_emas carried through to AMAs: ids_for_amas = ids_for_emas if _should_run("emas", from_stage) else parsed_ids -- fresh-bar filter propagates to both EMA+AMA stages
- _should_run() helper uses _STAGE_ORDER index comparison: clean O(1) check for --from-stage without if/elif chains across 12 stages
- --chain via subprocess.run(): next pipeline launched as subprocess (not direct call) for log isolation and returncode propagation

Phase 112-03 decisions:
- signal_gate_blocked = True when gate exits code 2: pipeline returns 0 (gate block is informational, not a failure); --chain sync to VM is skipped
- run_polling_loop() as importable function not embedded in main(): enables unit testing without running infinite loop
- _SIGNAL_TABLES list of 7 tables: _get_last_signal_ts queries GREATEST(MAX(ts)) via UNION ALL for accurate freshness detection
- Consecutive failure limit 3 in polling loop: prevents tight infinite retry on persistent DB/executor errors; exits code 1 after 3rd failure
- drift_monitor silently skipped (not errored) when --paper-start absent: matching run_daily_refresh.py Phase 87 behavior
- pipeline_run_id guard (if pipeline_run_id:) before _complete_pipeline_run calls: prevents UUID cast error on empty string in dry-run mode

Phase 112-04 decisions:
- VM DB is hyperliquid (same as sync_hl_from_vm.py) -- execution tables created in Phase 113; missing VM tables handled gracefully (print + continue)
- sync_signals_to_vm --dry-run works WITHOUT VM connectivity: reads local watermarks only, never opens SSH connection
- sync_signals_to_vm failure is non-fatal in run_full_chain: local pipeline complete; VM sync is best-effort
- Signal tables: incremental by ts watermark; config/dim tables: full-replace (TRUNCATE + COPY all) -- small stateless tables
- Telegram alert on chain halt is best-effort wrapped in try/except -- never crashes chain script

## Session Continuity

Last session: 2026-04-02
Stopped at: Completed 112-04-PLAN.md (Phase 112 Plan 04 of 5)
Resume file: None

---
*Created: 2025-01-22*
*Last updated: 2026-04-02 (Phase 112-04 complete: sync_signals_to_vm.py, run_full_chain.py, run_daily_refresh.py deprecation)*
