# Architecture Patterns: v1.3.0 Operational Activation & Research Expansion

**Domain:** Python quant trading platform integration and scaling
**Researched:** 2026-03-29
**Confidence:** HIGH (all findings from direct source code analysis)

---

## Executive Summary

v1.3.0 addresses six categories of work across a platform where the infrastructure
is built but components run in isolation. The central challenge is not new code --
it is wiring together existing pieces that were built in separate phases and never
connected end-to-end.

The `run_daily_refresh.py` pipeline already has all stage slots defined
(`signals`, `signal_validation_gate`, `calibrate_stops`, `portfolio`, `executor`).
The blocker for each is a single missing configuration or connection:

- Executor is silent because `dim_executor_config` has configs seeded but signals
  do not flow through `signals_ema_crossover` to the executor reliably
- Black-Litterman views are real (Phase 95 fixed uniform 1.0) but CTF features are
  absent from `feature_selection.yaml`
- Backtest infrastructure ran 78K aggregate bakeoff rows but zero Monte Carlo;
  `backtest_metrics.mc_sharpe_lo/hi/median` are all NULL
- FRED macro pipeline has 18 series defined in `SERIES_TO_LOAD` but equity indices
  (SP500, NASDAQ, DJIA, Russell 2000) are not wired

This document maps each category to specific integration points and build order.

---

## Component Map: Current State

```
                       VM SYNC
                      /      \
               FRED VM      HL VM
                  |              |
           fred.series_values  hyperliquid.*
                  |
                  v
    run_daily_refresh.py orchestrates via subprocess:

    sync_vms
      -> bars
         -> emas
            -> amas
               -> desc_stats
               -> macro_features (fred_reader -> feature_computer -> fred.fred_macro_features)
                  -> macro_regimes (regime_classifier -> macro_regime_labels)
                     -> macro_analytics (hmm_classifier, lead_lag_analyzer)
                        -> cross_asset_agg (cross_asset.py -> cross_asset_agg, funding_rate_agg)
                           -> macro_gates
                              -> macro_alerts
               -> regimes (refresh_regimes.py -> regimes table)
                  -> features (run_all_feature_refreshes.py -> features table)
                     -> garch (refresh_garch_forecasts.py -> garch_forecasts)
                        -> signals (run_all_signal_refreshes.py -> signals_ema_crossover,
                                    signals_rsi_mean_revert, signals_atr_breakout)
                           -> signal_validation_gate
                              -> ic_staleness_check
                                 -> calibrate_stops (calibrate_stops.py -> stop_calibrations)
                                    -> portfolio (refresh_portfolio_allocations.py
                                                  -> portfolio_allocations)
                                       -> executor (run_paper_executor.py
                                                    reads dim_executor_config WHERE is_active=TRUE
                                                    reads signals_ema_crossover WHERE executor_processed_at IS NULL
                                                    writes paper_orders, orders, fills, positions)
                                          -> drift_monitor
                                             -> pipeline_alerts
                                                -> stats
```

**Key observation:** The pipeline orchestrator exists and is complete. Every stage
is wired. The gaps are in the DATA flowing through existing stages.

---

## Integration Point Analysis: Each of the Six Categories

### 1. Operational Activation

The executor depends on two preconditions being met simultaneously:

**Precondition A: dim_executor_config must have active rows**

`PaperExecutor._load_active_configs()` queries:
```sql
SELECT * FROM public.dim_executor_config WHERE is_active = TRUE ORDER BY config_id
```

The seed script `scripts/executor/seed_executor_config.py` loads
`configs/executor_config_seed.yaml`, resolves `signal_name -> signal_id` from
`dim_signals`, and inserts via `ON CONFLICT (config_name) DO NOTHING`. The YAML
already contains two strategies: `ema_trend_17_77_paper_v1` and
`ema_trend_21_50_paper_v1`. The seed must have been run (or will need to be run)
for configs to appear with `is_active=TRUE`.

**Precondition B: signals must have unprocessed rows**

`SignalReader` reads:
```sql
WHERE executor_processed_at IS NULL AND ts > :watermark
```

from the table mapped by `SIGNAL_TABLE_MAP[signal_type]`:
```python
SIGNAL_TABLE_MAP = {
    "ema_crossover": "signals_ema_crossover",
    "rsi_mean_revert": "signals_rsi_mean_revert",
    "atr_breakout": "signals_atr_breakout",
}
```

AMA signals (ama_momentum, ama_mean_reversion, ama_regime_conditional) are in
`signals/registry.py` but have NO entry in `SIGNAL_TABLE_MAP` and NO
corresponding DB table (`signals_ama_momentum` does not exist). They are
bakeoff-only: used inside `bakeoff_orchestrator.py` as in-memory signal functions,
never persisted to a signals table. This is the hard boundary between research
(bakeoff) and production (executor).

**Precondition C: dim_executor_config.signal_id must match a valid dim_signals row**

`seed_executor_config.py` resolves signal names at seed time. If `dim_signals`
does not have `ema_17_77_long` or `ema_21_50_long`, the seed skips them with
`skipped_no_signal` count. A pre-seed validation step is needed.

**New components needed for ops activation:**
- `configs/executor_config_seed.yaml` -- exists, needs verification
- A validation script to confirm `dim_signals` has the required rows before seeding
- `run_daily_refresh.py --execute` flag must not be suppressed by `--no-execute`
  (it is already not suppressed by default -- `--no-execute` is the override)

**What is already wired:**
- `run_daily_refresh.py` calls `run_paper_executor_stage()` which invokes
  `ta_lab2.scripts.executor.run_paper_executor --db-url $DB_URL`
- `PaperExecutor.run()` is complete: loads L4 macro regime, iterates active configs,
  calls `SignalReader.read_unprocessed()`, generates `CanonicalOrder`, logs to
  `paper_orders`, promotes to `orders`, simulates fill via `FillSimulator`,
  updates `positions`, marks signals as processed, writes to `executor_run_log`
- `RiskEngine` and `MacroGateEvaluator` are integrated into `PaperExecutor.__init__`

---

### 2. Backtest Scaling

**Current state (from todo 2026-03-29):**
- Bakeoff: 78,698 rows in `strategy_bakeoff_results` (aggregate metrics only)
- Trade-level: 2 rows in `backtest_runs`, corresponding `backtest_trades`
- Monte Carlo: `backtest_metrics.mc_sharpe_lo/hi/median` all NULL
- `monte_carlo_trades()` in `analysis/monte_carlo.py` is fully implemented

**How bakeoff persists results vs trade-level backtests:**

The bakeoff (BakeoffOrchestrator) stores aggregate OOS metrics in
`strategy_bakeoff_results` (sharpe_mean, sharpe_std, max_drawdown_mean, dsr, etc.).
It does NOT generate individual trade records.

Trade-level backtests go through `btpy_runner.py` / `vbt_runner.py` which use
vectorbt to run the full strategy, then persist:
- `backtest_runs` (one row per strategy/asset/param/cost combination)
- `backtest_trades` (one row per trade, FK to backtest_runs)
- `backtest_metrics` (one row per run, includes mc_sharpe columns)

Monte Carlo attaches to `backtest_metrics` rows by calling
`monte_carlo_trades(df_trades)` from `analysis/monte_carlo.py`. This function is
imported in `run_monte_carlo.py` but has never been called in batch for all rows.

**New components needed:**

1. `scripts/analysis/run_mass_backtest.py` -- parallel orchestrator that:
   - Partitions work as `(asset, strategy)` chunks
   - Uses `NullPool + maxtasksperchild=1` (Windows multiprocessing requirement)
   - Tracks completed combos in a DB state table (resume-safe)
   - Calls `bakeoff_orchestrator._bakeoff_asset_worker()` with trade-level output flag

2. Extension to `bakeoff_orchestrator.py`: optional `persist_trades=True` flag
   that routes through `vbt_runner.py` to populate `backtest_runs/trades`

3. MC fill script: after each trade-level run, call `monte_carlo_trades()` and
   upsert result into `backtest_metrics`

4. For CTF signals: new `signals/ctf_threshold.py` with generic threshold signal
   (long/short when feature z-score crosses configurable threshold), plus
   registration in `signals/registry.py`

**Storage concern:** 20-40M trade rows at ~200 bytes each = 4-8 GB. Need
partition strategy (by strategy_name or asset_id) before exceeding 10 GB.

---

### 3. ML Signal Combination

**Current state:**

`ml/double_ensemble.py` (DoubleEnsemble) and `ml/regime_router.py` are implemented.
`scripts/ml/run_double_ensemble.py` CLI exists. The ML scripts are research-only:
they load from `features` table, train models, evaluate via purged CV, print
comparison table -- but write nothing to a signals table.

`BLAllocationBuilder` in `portfolio/black_litterman.py` accepts `signal_scores` as
a `pd.DataFrame` (index=asset_id, columns=feature_names). Phase 95 wired this to
real AMA feature values from `ama_multi_tf_u.d1`. The current signal_scores are
AMA momentum scores, not ML model outputs.

**Gap:** No path from ML model predictions to:
- A `signals_*` table (for executor)
- `signal_scores` in the portfolio allocation (for BL views)

**New components needed:**

1. `signals/ml_composite.py`: signal generator that loads a trained model,
   generates daily long/short scores per asset, applies threshold logic, returns
   standard signal tuple `(entries, exits, size)` compatible with the registry

2. `signals_ml_composite` DB table with schema matching other signal tables
   (id, venue_id, ts, tf, signal_id, signal_value, executor_processed_at, etc.)

3. `SIGNAL_TABLE_MAP` update in `executor/signal_reader.py`:
   ```python
   "ml_composite": "signals_ml_composite",
   ```

4. `dim_executor_config` row for the ML strategy (add to
   `executor_config_seed.yaml`)

5. For BL integration: a function `_load_ml_signal_scores()` in
   `scripts/portfolio/refresh_portfolio_allocations.py` that queries
   `signals_ml_composite` for latest values and shapes them into the
   `(asset_id, feature_name)` DataFrame expected by BLAllocationBuilder

The DoubleEnsemble model itself needs to be serialized (pickle/joblib) and stored
somewhere accessible at daily refresh time -- this is the main new infrastructure
piece.

---

### 4. CTF Graduation

**Current state:**

`dim_ctf_feature_selection` has 131 active features (IC-IR up to 1.19, correlation
with AMA features is 0.19 -- non-redundant). The table has no downstream consumers.

The signal/portfolio/execution pipeline reads from two sources:
- `feature_selection.yaml` (20 AMA features, IC-IR >= 1.0)
- `dim_feature_selection` (same 20 features, the DB version)

CTF features live in the `ctf` table (73.9M rows) computed by `cross_timeframe.py`.
They are NOT in the `features` table.

**The integration chain to close:**

```
dim_ctf_feature_selection (131 active)
    -> filter top 10-20 by IC-IR + pass rate
    -> ctf table (feature values at daily resolution)
    -> write to features table as new columns
       OR create a joined view that merges features + ctf columns
    -> add promoted names to feature_selection.yaml
    -> ICStalenessMonitor picks them up (run_ic_staleness_check reads feature_selection.yaml)
    -> BLAllocationBuilder.run() uses them as signal_scores
    -> bakeoff picks them up via parse_active_features()
```

**Key integration point -- how feature_selection.yaml drives consumers:**

`parse_active_features()` in `bakeoff_orchestrator.py` reads the YAML and returns
the list of feature names with IC-IR weights. This function is used by:
- `run_bakeoff.py` -- loads AMA feature columns from `ama_multi_tf_u`
- `scripts/portfolio/refresh_portfolio_allocations.py` -- builds IC-IR weight matrix
- `scripts/analysis/run_ic_staleness_check.py` -- monitors feature freshness
- `scripts/ml/run_regime_routing.py` -- loads features for regime model

Adding CTF features to `feature_selection.yaml` automatically propagates to all
four consumers. The only new wiring needed is ensuring the feature values are
accessible in a queryable form at daily refresh time.

**Two materialization options:**

Option A (simpler): Add CTF feature columns to the `features` table via a new
refresh step. The `features` table is written by
`scripts/features/run_all_feature_refreshes.py`. Adding CTF columns requires a
new refresh function that joins `ctf` by `(id, venue_id, ts, tf)`.

Option B (lighter): Create a view `features_extended` that LEFT JOINs `features`
with `ctf` on `(id, venue_id, ts, tf)`. Downstream consumers that query `features`
would need to be pointed at the view.

Option A is recommended: it fits the existing upsert pattern, does not introduce
a view dependency, and keeps all feature data co-located.

**New components needed:**

1. `scripts/analysis/promote_ctf_features.py`: reads `dim_ctf_feature_selection`,
   selects top N by IC-IR, writes promoted names + metadata to
   `feature_selection.yaml` (appends to active list)

2. `scripts/features/refresh_ctf_promoted.py`: reads promoted feature names,
   queries `ctf` table, upserts values into `features` table as new columns
   (follows same scoped DELETE + INSERT per batch pattern as other feature refreshers)

3. Alembic migration: add promoted CTF column names to `features` DDL (or use
   a flexible schema approach with dynamic column addition)

4. `run_all_feature_refreshes.py` update: add `refresh_ctf_promoted` as a step
   after the existing CTF step in the pipeline

5. `run_daily_refresh.py` has no changes needed -- `features` stage already runs
   `run_all_feature_refreshes.py --all --tf 1D`

---

### 5. FRED Macro Expansion

**Current state:**

`fred_reader.py` has `SERIES_TO_LOAD` with 18 series (Phases 65-66). The pipeline
is: `load_series_wide()` -> `forward_fill_with_limits()` ->
`compute_derived_features()` -> `compute_derived_features_66()` -> upsert into
`fred.fred_macro_features`.

`cross_asset.py` reads from `fred.fred_macro_features` for VIX, DXY, HY OAS,
net_liquidity when computing crypto-macro correlations.

**FRED equity indices (from todo 2026-03-28):**

Four new FRED series (SP500, NASDAQ Composite, DJIA, Russell 2000) need to be
added. The decision was Option B: macro layer only (not the full OHLCV bar
pipeline). The implementation is straightforward:

1. Add 4 series IDs to `SERIES_TO_LOAD` in `fred_reader.py`
2. Add 4 entries to `_RENAME_MAP` in `feature_computer.py`
3. Add derived features in `compute_derived_features_66()` or a new
   `compute_derived_features_67()` function: 1d/5d/20d returns, 20d realized vol,
   running drawdown, MA ratios (50d/200d)
4. Wire into `cross_asset.py`: rolling BTC-SPX, BTC-NASDAQ correlations
5. Alembic migration: new columns in `fred.fred_macro_features`

**Prerequisites:** The four FRED series must be synced from the GCP VM. Check
`fred.series_values` for their presence before adding to `SERIES_TO_LOAD`.

**No new scripts needed.** The existing `refresh_macro_features.py` already calls
`compute_macro_features(engine)` which calls the full chain. Adding series to
`SERIES_TO_LOAD` automatically includes them on next incremental refresh.

The 400-day `WARMUP_DAYS` in `refresh_macro_features.py` is sufficient for the
new MA ratio features (200-day MA requires 200 days, warmup covers it).

---

### 6. Tech Debt Cleanup

From the v1.2.0 milestone audit:

1. `blend_vol_simple()` in `garch_blend.py` is exported but has no external
   callers. The vol sizer uses inline blending. Remove or mark as internal.

2. Phase 82 has no `VERIFICATION.md`. Six phase summaries exist but no
   consolidated verification file. Create it from existing summaries.

3. Phase 92 `VERIFICATION.md` is stale -- gaps were closed in Phase 93 but
   the verification file was not updated. Update to reflect closed state.

These are all documentation changes with no runtime impact.

---

## Data Flow Changes for v1.3.0

### Current Daily Pipeline (v1.2.0)

```
sync_vms -> bars -> emas -> amas -> desc_stats ->
macro_features -> macro_regimes -> macro_analytics ->
cross_asset_agg -> macro_gates -> macro_alerts ->
regimes -> features -> garch -> signals ->
signal_validation_gate -> ic_staleness_check ->
calibrate_stops -> portfolio -> executor ->
drift_monitor -> pipeline_alerts -> stats
```

All stages exist. `executor` runs but produces no fills because
`dim_executor_config` is unseeded or signals are missing.

### v1.3.0 Data Flow Additions

```
ADDED: features stage now includes refresh_ctf_promoted step
       (CTF graduation)

ADDED: After signals, signals_ml_composite table populated
       by new ML signal generator
       (ML signal combination)

MODIFIED: portfolio stage - signal_scores includes CTF features
           (CTF graduation affects BL views)

ADDED: macro_features now computes equity index features
       (FRED expansion -- no new stage, extends existing stage)

MAINTAINED: executor stage now actually processes signals
             (ops activation -- config seeding, not code changes)
```

---

## Component Boundaries

| Component | Status | Change for v1.3.0 |
|-----------|--------|-------------------|
| `run_daily_refresh.py` | Exists, complete | No changes needed |
| `executor/paper_executor.py` | Exists, complete | No changes needed |
| `executor/signal_reader.py` | Exists, needs update | Add `ml_composite` to SIGNAL_TABLE_MAP |
| `configs/executor_config_seed.yaml` | Exists, needs ML config | Add AMA + ML strategy entries |
| `signals/ama_composite.py` | Research only (bakeoff) | Wrap into DB-persisting generator |
| `signals/registry.py` | Exists | Add ctf_threshold, ml_composite entries |
| `backtests/bakeoff_orchestrator.py` | Exists | Add `persist_trades=True` path |
| `analysis/monte_carlo.py` | Exists, never batched | Wire into mass backtest orchestrator |
| `macro/fred_reader.py` | Exists, 18 series | Add 4 equity index series to SERIES_TO_LOAD |
| `macro/feature_computer.py` | Exists | Add equity index derived features |
| `macro/cross_asset.py` | Exists | Add BTC-SPX/BTC-NASDAQ rolling correlations |
| `features/cross_timeframe.py` | Exists | No changes needed |
| `configs/feature_selection.yaml` | 20 AMA features | Add top CTF features after promotion |
| `portfolio/black_litterman.py` | Exists, complete | No changes needed |

**New components:**

| Component | Purpose | Depends On |
|-----------|---------|------------|
| `scripts/analysis/run_mass_backtest.py` | Parallel backtest orchestrator, resume-safe | `bakeoff_orchestrator.py`, `NullPool+maxtasksperchild` |
| `signals/ctf_threshold.py` | Generic CTF feature threshold signal | `ctf` table, `signals/registry.py` |
| `signals/ml_composite.py` | ML model output as daily signal | trained model artifact, `features` table |
| `signals_ml_composite` DB table | Persisted ML signals | Alembic migration |
| `scripts/analysis/promote_ctf_features.py` | CTF feature -> feature_selection.yaml | `dim_ctf_feature_selection`, `feature_selection.yaml` |
| `scripts/features/refresh_ctf_promoted.py` | CTF feature values -> features table | `ctf` table, new columns in `features` DDL |

---

## Build Order (Dependency-Driven)

The ordering below is driven by dependencies: what must exist before what can be
built or validated.

### Step 1: Ops Activation (Days 1-3)

**Why first:** Validates the end-to-end pipeline immediately. Produces live paper
fills that downstream monitoring (drift, dashboard) can display. No new code
required -- only configuration.

1. Validate `dim_signals` has the two required signal names (`ema_17_77_long`,
   `ema_21_50_long`). If missing, identify why signal generation did not register
   them.
2. Run `python -m ta_lab2.scripts.executor.seed_executor_config` -- seeds
   `dim_executor_config` from `executor_config_seed.yaml` idempotently.
3. Run one daily refresh with `--all` and verify executor stage produces fills.
4. Confirm `executor_run_log` has a row with `status=success`.

### Step 2: FRED Macro Expansion (Days 3-5)

**Why second:** Self-contained. Only touches `fred_reader.py`,
`feature_computer.py`, `cross_asset.py`, and one Alembic migration. No dependency
on other v1.3.0 work. Delivers value immediately in next daily refresh.

1. Check whether SP500/NASDAQ/DJIA/Russell 2000 series are in
   `fred.series_values`. If not, add them to the GCP VM collection list and wait
   for next VM sync before proceeding.
2. Add series to `SERIES_TO_LOAD` and `_RENAME_MAP`.
3. Add derived feature functions in `feature_computer.py`.
4. Write Alembic migration for new columns in `fred.fred_macro_features`.
5. Run `refresh_macro_features.py --full` to backfill from 2000-01-01.
6. Add BTC-SPX/NASDAQ correlations in `cross_asset.py`.

### Step 3: CTF Graduation (Days 5-10)

**Why third:** Unlocks better BL views (CTF features in signal_scores) and feeds
CTF signals into the backtest scaling work. Requires one Alembic migration before
the bakeoff work can use CTF signals.

1. Run `promote_ctf_features.py` to select top 15 CTF features from
   `dim_ctf_feature_selection` (IC-IR >= 1.0, pass_rate >= 0.5) and append to
   `feature_selection.yaml`.
2. Write Alembic migration to add promoted CTF column names to `features` DDL.
3. Implement `refresh_ctf_promoted.py` (scoped DELETE + INSERT from `ctf` table).
4. Add `refresh_ctf_promoted` step to `run_all_feature_refreshes.py`.
5. Validate: run daily refresh, confirm `features` table has CTF columns, confirm
   ICStalenessMonitor tracks them, confirm BL `signal_scores` includes them.

### Step 4: Backtest Scaling Infrastructure (Days 5-10, parallel with Step 3)

**Why can start in parallel:** The mass backtest orchestrator and trade-level
backfill do not depend on CTF graduation. CTF signals are Phase 3 of the todo
and come after the orchestrator is built.

1. Implement resume-safe state table (tracks completed `(asset, strategy,
   params_hash)` combos) -- DB table, not file.
2. Implement `run_mass_backtest.py` with `NullPool + maxtasksperchild=1` and
   `(asset, strategy)` chunking.
3. Add `persist_trades=True` path in `bakeoff_orchestrator.py` that routes
   through `vbt_runner.py`.
4. Wire `monte_carlo_trades()` call after each trade-level run -- updates
   `backtest_metrics.mc_sharpe_lo/hi/median`.
5. Run initial backfill: 13 existing strategies x 109 assets.
6. After CTF graduation (Step 3): implement `signals/ctf_threshold.py` and run
   CTF signal backtest sweep.

### Step 5: ML Signal Combination (Days 10-15)

**Why last:** Depends on backtest scaling infrastructure (Step 4) to evaluate
ML signals, and optionally on CTF features (Step 3) as ML inputs.

1. Train DoubleEnsemble on `features` table data (optionally including CTF columns
   after Step 3).
2. Serialize trained model to disk or DB artifact store.
3. Implement `signals/ml_composite.py` as a daily signal generator that loads the
   model and writes predictions to `signals_ml_composite` table.
4. Write Alembic migration for `signals_ml_composite` table.
5. Add `ml_composite` to `SIGNAL_TABLE_MAP` in `executor/signal_reader.py`.
6. Add ML strategy config to `executor_config_seed.yaml` and re-run seed.
7. Backtest the ML signal through `run_mass_backtest.py` before live paper trading.

### Step 6: Tech Debt Cleanup (Day 15, final)

1. Remove or mark `blend_vol_simple()` as internal in `garch_blend.py`.
2. Create Phase 82 `VERIFICATION.md` from existing summaries.
3. Update Phase 92 `VERIFICATION.md` to reflect closed gaps.

---

## Critical Integration Points

These are the exact lines of code / config that are the connective tissue between
existing components:

### 1. dim_executor_config -> PaperExecutor

```python
# executor/paper_executor.py line 204-217
# Query: SELECT * FROM public.dim_executor_config WHERE is_active = TRUE
# If 0 rows -> PaperExecutor.run() returns {"status": "no_configs", ...}
# Seeded by: configs/executor_config_seed.yaml via seed_executor_config.py
```

### 2. feature_selection.yaml -> Four Consumers

```python
# bakeoff_orchestrator.py: parse_active_features()
# Reads configs/feature_selection.yaml -> returns list of {name, ic_ir_mean, ...}
# Used by:
#   run_bakeoff.py (AMA feature loading)
#   refresh_portfolio_allocations.py (IC-IR weight matrix)
#   run_ic_staleness_check.py (feature monitoring)
#   run_regime_routing.py (ML feature loading)
```

### 3. SIGNAL_TABLE_MAP -> Signal Routing

```python
# executor/signal_reader.py line 37-41
SIGNAL_TABLE_MAP = {
    "ema_crossover": "signals_ema_crossover",
    "rsi_mean_revert": "signals_rsi_mean_revert",
    "atr_breakout": "signals_atr_breakout",
    # AMA signals intentionally absent -- bakeoff only, no DB persistence
    # ML composite: add here when signals_ml_composite table exists
}
```

### 4. MC columns -> backtest_metrics

```python
# analysis/monte_carlo.py: monte_carlo_trades(df_trades)
# Returns: {"mc_sharpe_lo": float, "mc_sharpe_hi": float, "mc_sharpe_median": float, ...}
# Target: public.backtest_metrics.mc_sharpe_lo / mc_sharpe_hi / mc_sharpe_median
# Currently: all NULL (monte_carlo_trades never called in batch)
```

### 5. SERIES_TO_LOAD -> FRED pipeline

```python
# macro/fred_reader.py line 27-58
SERIES_TO_LOAD: list[str] = [...]  # 18 series
# Adding 4 equity index series here triggers automatic inclusion in:
#   load_series_wide()
#   forward_fill_with_limits()
#   compute_macro_features() if _RENAME_MAP updated
```

### 6. ctf table -> features table (missing link for CTF graduation)

```python
# ctf table: (id, venue_id, ts, tf, indicator_id, base_tf, ref_tf, ...composites...)
# features table: (id, venue_id, ts, tf, ...feature_columns...)
# Gap: no ETL from ctf to features
# Bridge needed: refresh_ctf_promoted.py
#   SELECT id, venue_id, ts, tf, composite_value AS promoted_feature_name
#   FROM ctf WHERE indicator_id IN (promoted_indicator_ids)
#   -> scoped DELETE + INSERT into features
```

---

## Architecture Anti-Patterns to Avoid

### Anti-Pattern 1: Creating a New Orchestrator

Do not build a separate scheduling system for v1.3.0 tasks. `run_daily_refresh.py`
already has all the stage slots and subprocess patterns. Add stages there, not as
a new parallel scheduling system.

### Anti-Pattern 2: Making AMA Signals a Persistent Table Prematurely

AMA signals (ama_momentum, ama_mean_reversion, ama_regime_conditional) are
currently bakeoff-only. Their signal quality over the full asset universe and
across production cost scenarios has not been validated in the same way EMA signals
were. Before creating a `signals_ama_momentum` table and adding AMA signals to the
executor, run them through the mass backtest infrastructure (Step 4) to confirm
they pass the same gates the EMA strategies passed in Phase 42.

### Anti-Pattern 3: Altering the _u Table Schema for CTF

Do not add CTF columns to `ama_multi_tf_u` or `price_bars_multi_tf_u`. CTF features
belong in the `features` table (bar-level feature store). The _u tables are for
aligned price/indicator data, not derived features.

### Anti-Pattern 4: Using a File-Based State for Mass Backtest

The mass backtest orchestrator must use a DB table (not a CSV or JSON file) to
track completed combos. File-based state does not survive process kills and is
not queryable for progress monitoring.

### Anti-Pattern 5: Expanding ML Model Training in the Daily Pipeline

The DoubleEnsemble training loop is hours-long. It must run as a separate offline
job (scheduled weekly or on-demand), not in the daily pipeline. The daily pipeline
only runs inference (predict from serialized model -> write signals to DB).

---

## Scalability Considerations

| Concern | v1.2.0 State | v1.3.0 Change | Mitigation |
|---------|-------------|---------------|------------|
| backtest_trades volume | 2 rows | 20-40M rows target | Partition by strategy_name or asset_id |
| features table width | ~112 columns | +15 CTF columns | Alembic migration, monitor query plan |
| fred.fred_macro_features width | ~50 columns | +20 equity index columns | Alembic migration |
| signals_ml_composite volume | 0 rows | ~100 assets x daily = 36K/year | Small, no concern |
| Mass backtest runtime | N/A | 460K runs estimated | NullPool + maxtasksperchild=1, batch by asset |
| GARCH timeout | 1800s in pipeline | Unchanged | Already wired, acceptable |

---

## Sources

All findings from direct source code analysis:

- `src/ta_lab2/scripts/run_daily_refresh.py` -- STAGE_ORDER (line 120-143), all
  subprocess wrappers
- `src/ta_lab2/executor/paper_executor.py` -- `_load_active_configs()` query,
  execution flow
- `src/ta_lab2/executor/signal_reader.py` -- `SIGNAL_TABLE_MAP` (lines 37-41)
- `src/ta_lab2/scripts/executor/seed_executor_config.py` -- seed mechanics,
  signal_name resolution
- `configs/executor_config_seed.yaml` -- two EMA strategies, signal_name refs
- `src/ta_lab2/backtests/bakeoff_orchestrator.py` -- bakeoff vs trade-level
  distinction, `parse_active_features()`
- `src/ta_lab2/analysis/monte_carlo.py` -- `monte_carlo_trades()` return shape,
  mc_sharpe keys
- `src/ta_lab2/macro/fred_reader.py` -- `SERIES_TO_LOAD` (18 series)
- `src/ta_lab2/macro/feature_computer.py` -- `_RENAME_MAP`, `compute_derived_features_66()`
- `src/ta_lab2/macro/cross_asset.py` -- reads `fred.fred_macro_features`
- `src/ta_lab2/portfolio/black_litterman.py` -- `signal_scores` DataFrame interface
- `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py` -- uniform 1.0
  fallback (lines 822-830), `_load_signal_scores()` real path (line 814)
- `src/ta_lab2/signals/registry.py` -- `REGISTRY` entries, AMA signal imports
- `src/ta_lab2/signals/ama_composite.py` -- confirms bakeoff-only design
- `configs/feature_selection.yaml` -- 20 active AMA features
- `.planning/todos/pending/2026-03-28-ctf-production-integration.md`
- `.planning/todos/pending/2026-03-29-massive-backtest-monte-carlo-expansion.md`
- `.planning/todos/pending/2026-03-28-fred-equity-indices-macro-pipeline.md`
- `.planning/milestones/v1.2.0-MILESTONE-AUDIT.md` -- integration wiring map,
  tech debt items
