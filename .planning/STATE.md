# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-21)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v1.2.0 Analysis -> Live Signals (in progress)

## Current Position

Phase: 90-ctf-core-computation-module (v1.2.0, In progress)
Plan: 1 of 2 complete (01 done)
Status: In progress
Last activity: 2026-03-23 -- Completed 90-01-PLAN.md (CTFConfig + CTFFeature data loading/alignment foundation)

Progress: [##########] 100% v0.4.0 | [##########] 100% v0.5.0 | [##########] 100% v0.6.0 | [##########] 100% v0.7.0 | [##########] 100% v0.8.0 | [##########] 100% v0.9.0 | [##########] 100% v1.0.0 | [##########] 100% v1.0.1 | [##########] 100% v1.1.0 | [########--] 62% v1.2.0

## Performance Metrics

**Velocity:**
- Total plans completed: 379
- Average duration: 7 min
- Total execution time: ~30.3 hours

**Recent Trend:**
- v0.8.0: 6 phases, 16 plans, ~1.2 hours
- v0.9.0: 8 phases, 35 plans + 3 cleanup, ~4.0 hours
- v1.0.0: 22 phases, 104 plans, ~14.5 hours
- v1.0.1: 10 phases, 29 plans, ~2.0 hours
- v1.1.0: 6 phases, 21 plans, ~2.5 hours
- v1.2.0 (in progress): Phase 80 = 5 plans (~35 min), Phase 81 = 5 plans (~40 min), Phase 82 = 6 plans (~7h incl execution), Phase 83 = 5 plans (~25 min)
- Trend: Stable (~5-7 min/plan)

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.

v1.1.0 decisions archived to `.planning/milestones/v1.1.0-ROADMAP.md`.

**Phase 84 decisions (plan 03):**
- load_ama_params_catalogue ttl=3600 (dim data, 18 rows, rarely changes)
- load_ama_curves filters roll=false + alignment_source='multi_tf': avoids scanning 170M row ama_multi_tf_u table
- er column rendered only for KAMA (NULL for DEMA/HMA/TEMA by design -- not a missing-data issue)
- load_ema_for_comparison uses ema column (not aliased as ema_value): direct column access in AMA Inspector vs build_candlestick_chart compat alias in load_ema_overlays
- Cross-asset comparison: yaxis2 overlaying='y' side='right' for dual price-normalized chart
- ruff-format reformatted both files on first commit (multi-arg function calls): re-staged and committed clean (standard pattern)

**Phase 84 decisions (plan 02):**
- trend_state derived via split_part(l2_label, '-', 1) in SQL: regimes table has no trend_state column
- REGIME_BAR_COLORS from charts.py used to build _HEATMAP_COLORSCALE: consistent color constants across dashboard
- regime_comovement displayed as st.dataframe only (NOT network graph): only 21 rows (7 assets x 3 EMA pairs), infeasible as network
- Weekly binning for heatmap x-axis (mode per symbol/week): reduces noise vs daily while preserving trend visibility
- ruff-format reformatted page on first commit (long line): re-staged and committed clean (standard pattern)

**Phase 89 decisions (plan 01):**
- down_revision=440fdfb3e8e1 (not i3j4k5l6m7n8 as research stated -- research predates the 440fdfb3e8e1 migration)
- ctf returns YAML section uses nested indicators: key with source_table + roll_filter metadata; avoids YAML scalar/list ambiguity
- computed_at (not updated_at) in ctf table: derived fact table semantics vs incremental measurement
- ta/vol tables have venue_id as column-only (not in PK): Phase 90 CTF joins must use (id, ts, tf, alignment_source) only

**Phase 90 decisions (plan 01):**
- ta/vol/features ALL have venue_id in PK (confirmed via information_schema in 90-01; Phase 89 research "column-only" note was incorrect/stale)
- Only features table gets AND venue_id = :venue_id in WHERE; ta/vol filtering by alignment_source is sufficient
- numpy imported with noqa: F401 in cross_timeframe.py: reserved for plan 02 composite computations (slope, divergence)
- build_alignment_frame imported from ta_lab2.regimes.comovement -- not reimplemented in features module

**Phase 84 decisions (plan 01):**
- hl_open_interest (82K rows, Coinalyze) for OI time series; hl_oi_snapshots has only 3 timestamps (2026-03-11) -- not a time series
- interval='1d' only for hl_candles candle chart; interval='1h' covers only 3 days for most assets
- load_hl_perp_list ttl=3600 (dimension data); data query functions ttl=900
- make_subplots(shared_xaxes=True, rows=2) for candle+OI stacked layout; conditional has_oi check for 1-row vs 2-row
- perp_options dict passed as argument into @st.fragment to avoid re-loading inside auto-refresh cycle
- cross-schema SQL pattern: always prefix HL tables with hyperliquid.* -- hl_assets.asset_id != public.dim_assets.id

**Phase 84 decisions (plan 04):**
- Placeholder page pattern: st.info() banner + TODO(Phase-XX) comments + get_engine import (noqa: F401) reserved for future wiring
- strategy_colors dict removed (F841 ruff violation): stacked bar uses Plotly default colorwheel instead
- Risk tier thresholds: <60% used = green, 60-85% = yellow, >=85% = red (standard risk budget convention)
- noqa: F401 on get_engine import preserves Phase 86 DB integration hook without triggering unused import lint

**Phase 83 decisions (plan 04):**
- ema aliased as ema_value in load_ema_overlays: matches build_candlestick_chart expected column without modifying charts.py
- period=ANY(:periods) for psycopg2 Python list -> PostgreSQL array binding (no UNNEST needed)
- regimes_df = None when empty in Asset Hub: build_candlestick_chart skips vrect loop on None vs empty DataFrame
- Deep linking via st.query_params['asset'] + st.query_params['tf']: cross-page navigation pattern established

**Phase 83 decisions (plan 02):**
- numpy.random.default_rng(42) for reproducible MC bootstrap CI -- consistent seed prevents UI flicker on re-run
- MAE/MFE stored as decimal fractions; multiplied by 100 in display layer for % presentation with format="%.2f%%"
- cost_matrix pivot: cost_df.set_index('cost_scenario')[metric_cols].T puts scenarios as columns -- natural comparison
- Equity sparklines in Strategy-First load fold_metrics for top 3 assets only (3 DB queries per expander when opened)
- ruff-format pre-commit hook reformatted file on first commit; re-staged and committed clean (standard pattern)

**Phase 83 decisions (plan 05):**
- 4 sidebar groups (Overview, Analysis, Operations, Monitor): replaced 6 organic groups with logical structure
- Asset Hub listed first in Analysis group as primary entry point
- Verifier fix: added s.feature_snapshot and s.regime_key to _SIGNAL_COLUMNS and load_closed_signals_for_strategy queries

**Phase 83 decisions (plan 03):**
- compute_signal_strength: base=20 + EMA separation (0-30) + RSI extremity (0-30) + ATR magnitude (0-20); all .get() access
- Sidebar outside fragment, passed as arguments: prevents Streamlit widget-inside-fragment error
- go.Heatmap: encode direction to numeric (long=1, short=-1, none=0) with custom colorscale (red/dark-gray/green)
- Cards view capped at 30 signals with informational caption to avoid render overload

**Phase 83 decisions (plan 01):**
- ttl=3600 for bakeoff data (rarely regenerated), ttl=300 for signal data (updates during daily refresh)
- fold_metrics_json is JSONB -- psycopg2 auto-deserializes to Python list; do NOT json.loads() the result
- _SIGNAL_COLUMNS constant ensures all 3 UNION ALL sub-SELECTs have identical schemas
- AMA strategy names (ama_*) route to signals_ema_crossover (AMA bakeoff reuses EMA signal lifecycle tracking)
- make_interval(days => :days) for parameterized interval in signal history queries (prevents injection)
- build_signal_timeline_chart: horizontal bars via go.Bar orientation=h with base=[entry_ts]
- build_equity_sparkline: additive cumulative sum of fold total_return (not compound return) -- adequate for sparkline

**Phase 82 decisions (plan 01):**
- KRAKEN_COST_MATRIX moved to costs.py (proper home for cost constants); re-exported from orchestrator for zero breaking changes
- Hyperliquid slippage range 3/5/10 bps (vs Kraken 5/10/20): HL CLOB tighter spreads justify lower range
- Separate SQL per AMA feature in load_strategy_data_with_ama(): avoids column name collisions, each feature independently debuggable
- experiment_name VARCHAR(128) NULL default: backward-compatible; existing rows get NULL; Phase 82 runs tag with experiment names

**Phase 82 decisions (plan 04):**
- AMA features loaded per-asset then merged by (id, ts): consistent with Plan 01 pattern; avoids SQL column collisions
- Conditional features excluded from global model X, added only to X_for_router: regime specialists use broader feature set
- NaN rows dropped AFTER AMA join: AMA warmup shorter than features table history; left-join then dropna preserves all post-warmup bars
- load_per_asset_ic_weights() uses asset_id column (confirmed from dashboard/queries/research.py)
- Universal IC-IR as fallback in per-asset weights: missing per-asset data filled with yaml ic_ir_mean before normalization
- ROADMAP criterion 2 satisfied: RegimeRouter.fit() called per CV fold with 20 active features; per-regime sub-models operational

**Phase 82 decisions (plan 03):**
- Expression signal param grid = [{holding_bars: hb}]: holding period is the only free param; expression encodes the full signal formula
- AMA loader auto-detection: any ama_* strategy OR --experiments-yaml triggers load_strategy_data_with_ama() -- unified, no per-strategy branching
- exchange=all concatenates both matrices into one list: orchestrator runs all 18 scenarios in single sweep
- load_per_asset_ic_weights() in bakeoff_orchestrator.py (not run_bakeoff.py): available to Plan 05 per_asset_weight_fn without CLI changes
- load_strategy_data_with_ama not re-imported in run_bakeoff.py: CLI delegates data loading to orchestrator via ama_features parameter

**Phase 82 decisions (plan 02):**
- fillna(0.0) for missing AMA warmup values: neutral contribution; pandas 2.x rejects fillna(method=None)
- IC-IR weights stored as raw unnormalized values, normalized at call time: preserves interpretable API
- ADX computed locally (Wilder ewm) when filter_col absent from DataFrame: signal functions are self-contained
- Holding-bar exit uses Python counter loop, not vectorbt internals: keeps signal functions library-independent
- AMA signal functions read df[ama_col] only, never recompute: prevents fold-boundary lookback contamination

**Phase 81 decisions (plan 05):**
- ATR-14 normalised by close: price-unit ATR / close gives fractional vol comparable to Parkinson/GK scale
- GARCH stage after features, before signals: GARCH reads bar returns; signals may use GARCH vol for sizing
- GARCH failure non-fatal: --continue-on-error allows pipeline to proceed to signals if GARCH fails
- TIMEOUT_GARCH=1800s (30 min): conservative timeout for 99 assets x 4 models sequential fitting

**Phase 81 decisions (plan 04):**
- Student's t unit-variance scaling: raw quantile * sqrt((df-2)/df) so sigma_forecast maps to actual std dev
- GARCH-VaR uses mu=mean(returns) in compute_var_suite: consistent with parametric_var_normal convention
- var_to_daily_cap raises ValueError for garch method with no garch_var_value: fail-fast over silent fallback

**Phase 81 decisions (plan 03):**
- QLIKE clips sigma^2 and realized^2 to 1e-16 (not individual vols to 1e-8): prevents log(0) at variance level
- Iterative floor for blend weights: clip-then-renormalize single-pass is wrong; iterative redistribution is correct
- get_blended_vol uses equal weights as fallback: RMSE history needs Plan 05 infrastructure; equal-weight is safe default
- rolling_oos_evaluate step=21 (monthly): captures regime changes without excessive runtime

**Phase 81 decisions (plan 02):**
- carry-forward half-life=5 days: exponential decay on prior converged forecast when GARCH fails to converge
- GK fallback uses 21 bars: Garman-Klass 21-bar estimate when no prior converged forecast exists
- INSERT RETURNING run_id: diagnostics row returned run_id set as model_run_id in forecast rows (clean FK)
- Sequential per-asset processing: GARCH fitting is CPU-bound, arch uses internal threading, multiprocessing deferred

**Phase 81 decisions (plan 01):**
- FIGARCH_MIN_OBS=200 (research recommends 200-250; 200 maximises asset coverage while maintaining convergence)
- Student's t distribution for all GARCH variants (crypto heavy tails)
- Returns scaled by 100 before fitting, variances divided by 10000 after (decimal space output)
- arch 8.x API: maxiter/ftol passed inside options dict, not as top-level fit() kwargs
- EGARCH/FIGARCH use simulation-based multi-step forecasts (arch 8.x analytic not supported for these families)
- garch_engine.py is pure computation (no DB) -- DB writes handled by refresh script (plan 02)

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

Last session: 2026-03-23T20:02:37Z
Stopped at: Completed 90-01-PLAN.md (CTFConfig + CTFFeature data loading/alignment foundation)
Resume file: None

---
*Created: 2025-01-22*
*Last updated: 2026-03-23 (Phase 90, Plan 1 complete)*
