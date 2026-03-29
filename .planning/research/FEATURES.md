# Feature Landscape: v1.3.0 Operational Activation & Research Expansion

**Domain:** Operational activation + research scaling for an existing quant trading platform
**Researched:** 2026-03-29
**Confidence:** HIGH (primary source: codebase direct analysis; supported by web research)

## Scope

This document maps the feature landscape for v1.3.0 across five capability areas:

1. **Operational Activation** — Wiring signal generation, paper executor, and portfolio
   into a reliably automated daily loop
2. **Massive Backtest Scaling** — From 2 trade-level runs to 460K+, with Monte Carlo on every run
3. **ML Signal Combination** — LightGBM rank prediction, SHAP feature selection,
   XGBoost meta-label filtering
4. **CTF Graduation** — Promoting CTF research features into the live production pipeline
5. **FRED Equity Indices** — Adding SP500/NASDAQ/DJIA/R2K to the macro pipeline

**What is already built and NOT scope here:**
The paper executor, signal generators, BL portfolio construction, risk engine, GARCH
volatility, CTF infrastructure, and FRED macro pipeline all exist. This research
documents what features each capability NEEDS to work at scale, what makes it
production-grade, and what traps to avoid.

---

## Area 1: Operational Activation

### What "Paper Trading at Scale" Actually Means

The executor exists and is wired into `run_daily_refresh.py` (`--execute` stage). Signal
generators also exist (`refresh_signals_ema_crossover`, `refresh_signals_rsi_mean_revert`,
`refresh_signals_atr_breakout`). The gap: signals are generated but the executor is not
running on a schedule, and no one is watching the pipeline health.

Operational activation means the daily loop runs automatically, alerts when broken, and
has enough observability to know if signals stopped flowing before positions are taken.

---

### Table Stakes — Operational Activation

#### OA-TS-1: Automated Daily Schedule (Mandatory)

**Why Expected:** A signal-to-fill pipeline that requires manual invocation is not operational.
The executor reads signal freshness and raises `StaleSignalError` if signals exceed `cadence_hours`.
Without a scheduler, this fires on every manual run after a missed day.

**Complexity:** Low

**What It Looks Like:**
The existing `run_daily_refresh.py --all` covers the full pipeline in the correct STAGE_ORDER
(signals → signal_validation_gate → calibrate_stops → portfolio → executor). Schedule this
once daily via Windows Task Scheduler, cron, or systemd timer. Nothing new to build — the
scheduler is the missing piece.

**Critical constraint:** Executor runs AFTER signals stage. If signals stage fails, executor
must not run on stale data. The existing `ComponentResult.success` check in
`run_daily_refresh.py` handles this: if any stage returns `success=False`, downstream stages
stop unless `--continue-on-error` is passed.

**Dependencies:** None — this is a scheduler configuration task, not a code task.

---

#### OA-TS-2: Signal Freshness Guard Behavior at Scale (Mandatory)

**Why Expected:** `SignalReader.check_signal_freshness()` raises `StaleSignalError` when
`age_hours > cadence_hours` and `last_watermark_ts IS NOT NULL`. This is correct behavior,
but needs tuning for production: cadence_hours in `dim_executor_config` must match the actual
signal generation cadence (currently 24h for daily signals).

**Complexity:** Low

**What It Looks Like:** Each row in `dim_executor_config` has `cadence_hours`. For daily
signals, set `cadence_hours = 36` to allow a 12-hour buffer for late runs without triggering
false stale alerts. For weekly signals, `cadence_hours = 192` (8 days). Stale signals trigger
Telegram alert via `_try_telegram_alert()` — this path is already wired.

**Evidence from codebase:** `executor/paper_executor.py` lines 161-174 handle StaleSignalError
by sending Telegram alert and writing `status="stale_signal"` to `executor_run_log`. The
infrastructure is complete; only `cadence_hours` values need calibration.

---

#### OA-TS-3: Run Log Monitoring (Mandatory)

**Why Expected:** A production executor must produce an auditable trail. The
`executor_run_log` table exists and is written on every run. Monitoring means
querying this table and alerting when `status != 'success'`.

**Complexity:** Low

**What It Looks Like:**
```sql
-- Detect executor failures in the last 48h
SELECT config_ids, status, error_message, finished_at
FROM executor_run_log
WHERE finished_at > now() - interval '48 hours'
  AND status NOT IN ('success', 'no_signals')
ORDER BY finished_at DESC;
```
The existing `pipeline_alerts` stage in `run_daily_refresh.py` is the right hook for this.
The `pipeline_run_log` table from Phase 87 captures stage-level success/failure.

**Dependencies:** `pipeline_run_log` table (Phase 87, already built in v1.2.0).

---

#### OA-TS-4: dim_executor_config Populated for All Active Strategies (Mandatory)

**Why Expected:** The executor reads `dim_executor_config WHERE is_active = TRUE`. If
this table has zero active rows, the executor logs "no active executor configs found"
and returns `status = "no_configs"` — a silent no-op. The executor appears to run but
does nothing.

**Complexity:** Low

**What It Looks Like:** Each signal type (ema_crossover, rsi_mean_revert, atr_breakout)
needs at least one active row in `dim_executor_config` with `is_active = TRUE` and
correct `signal_type`, `signal_id`, and `cadence_hours`. The `seed_executor_config.py`
script handles this.

**Evidence from codebase:** `executor/paper_executor.py` line 121: early return on empty
configs. `scripts/executor/seed_executor_config.py` exists for seeding.

---

#### OA-TS-5: Position Isolation by strategy_id (Mandatory)

**Why Expected:** The executor supports multiple strategies simultaneously. Each strategy
must have isolated positions — EMA crossover should not see RSI mean revert's position
when computing delta. `OrderManager.process_fill()` takes `strategy_id` for this purpose.

**Complexity:** Low

**What It Looks Like:** `positions` table has `strategy_id` column. Each
`dim_executor_config` row gets a unique `config_id` which becomes `strategy_id` in fills.
The `_process_asset_signal()` method queries:
```sql
SELECT quantity FROM positions
WHERE asset_id = :asset_id AND exchange = :exchange AND strategy_id = :strategy_id
```
This is already implemented. Operational risk: seeding two configs with the same
`signal_id` would result in duplicate order generation for the same signal.

---

#### OA-TS-6: Parity Checker Runs After Burn-In (Mandatory)

**Why Expected:** The parity checker (`parity_checker.py`) correlates paper executor PnL
with backtest replay PnL. If correlation drops below threshold, it indicates the executor
is not following the strategy as backtested — a critical operational alarm.

**Complexity:** Low (already built; needs to be scheduled)

**What It Looks Like:** Run weekly or after significant drawdown:
```bash
python -m ta_lab2.scripts.executor.run_parity_check \
  --bakeoff-winners \
  --start 2025-01-01 --end 2025-12-31 \
  --pnl-correlation-threshold 0.90
```
Exit code 1 = correlation below threshold but script ran. Alert if exit code 1.

---

### Differentiators — Operational Activation

#### OA-D-1: Multi-Strategy Dashboard View (High Value)

**Value Proposition:** 17 Streamlit pages exist but no single view shows "all active
strategies, current positions, today's signals, last executor run status" in one glance.
An operator view that renders in under 5 seconds is the first thing needed when the daily
run completes.

**Complexity:** Medium

**What It Looks Like:**
```
| Strategy    | Signals Today | Orders | Fills | Status     | Last Run    |
|-------------|---------------|--------|-------|------------|-------------|
| ema_trend   | 12 assets     | 3      | 3     | SUCCESS     | 2026-03-29  |
| rsi_revert  | 8 assets      | 1      | 1     | SUCCESS     | 2026-03-29  |
| atr_break   | 0 assets      | 0      | 0     | NO_SIGNALS  | 2026-03-29  |
```
Sources: `executor_run_log` + `positions` + `signals_*` tables.

---

#### OA-D-2: Burn-In Progress Tracker (High Value)

**Value Proposition:** `daily_burn_in_report.py` from Phase 88 exists but is run manually.
An automated weekly burn-in report appended to the dashboard makes the "ON TRACK / WARNING /
STOP" verdict visible without manual invocation.

**Complexity:** Low

---

#### OA-D-3: Cadence-Aware Stale Signal Escalation (Medium Value)

**Value Proposition:** Currently, stale signals always fire `StaleSignalError` (hard stop).
For strategies with known data gaps (weekends, holidays), a grace-period escalation would
log WARNING for <48h staleness and only ERROR after that.

**Complexity:** Medium

---

### Anti-Features — Operational Activation

#### OA-AF-1: Live Exchange Order Placement

**Why Avoid:** The executor is deliberately a PAPER executor. Connecting it to a live
exchange order book (Coinbase/Kraken production API) before 4+ weeks of paper burn-in
data and parity correlation >= 0.90 is premature. Risk: a bad signal or bug causes real
financial loss.

**What to Do Instead:** Complete the burn-in protocol. Gate live trading on explicit
parity check passing.

---

#### OA-AF-2: Per-Minute Signal Cadence

**Why Avoid:** The bar pipeline is daily-batch. Running the executor more frequently than
the bar cadence just re-processes already-processed signals (watermark prevents duplicates)
but adds complexity and load.

**What to Do Instead:** Keep executor cadence matched to signal cadence (daily = 1x/day).

---

## Area 2: Massive Backtest Scaling

### What 460K Runs Actually Requires

Current state: 78K aggregate bakeoff rows (aggregate metrics, no trade-level detail),
2 trade-level runs in `backtest_runs`, zero Monte Carlo. Target: ~460K trade-level runs
with Monte Carlo confidence intervals on every run.

The challenge is not algorithmic — the infrastructure exists. The challenge is:
(a) resume-safe orchestration so partial runs can restart without duplicating work,
(b) storage that does not become unqueryable at 20-40M trade rows,
(c) pruning logic to skip hopeless parameter combos early.

---

### Table Stakes — Backtest Scaling

#### BS-TS-1: Resume-Safe State Table (Mandatory)

**Why Expected:** At 460K runs with ~30s each, the total compute is ~3,800 CPU-hours.
Multiprocessing reduces wall time but crashes are inevitable. Without resume safety,
a crash at run 300K means restarting from 0.

**Complexity:** Medium

**What It Looks Like:** A state table tracking completion:
```sql
CREATE TABLE backtest_run_state (
    params_hash TEXT NOT NULL,
    asset_id INT NOT NULL,
    strategy_name TEXT NOT NULL,
    tf TEXT NOT NULL,
    cost_scenario TEXT NOT NULL,
    status TEXT NOT NULL, -- 'pending', 'running', 'complete', 'failed'
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (params_hash, asset_id, strategy_name, tf, cost_scenario)
);
```
Orchestrator queries `WHERE status = 'pending'` to find work. On completion, `UPDATE status =
'complete'`. On restart, already-complete combos are skipped.

**Evidence from codebase:** `run_bakeoff.py` has `--overwrite` flag but no state table —
skip-if-exists logic checks `strategy_bakeoff_results` directly. For 460K runs, this
query becomes slow. A dedicated state table is faster and safer.

---

#### BS-TS-2: backtest_trades Table Partitioned by strategy_name (Mandatory)

**Why Expected:** At 20-40M trade rows, a single unpartitioned `backtest_trades` table
becomes slow for queries like "show all trades for strategy X" or "compute drawdown for
run Y." PostgreSQL's range/list partitioning keeps each strategy's data co-located.

**Complexity:** Medium

**What It Looks Like:**
```sql
-- List partitioning by strategy (13 strategies = 13 partitions)
CREATE TABLE backtest_trades (
    run_id UUID,
    strategy_name TEXT NOT NULL,
    asset_id INT NOT NULL,
    entry_ts TIMESTAMPTZ,
    exit_ts TIMESTAMPTZ,
    entry_price NUMERIC,
    exit_price NUMERIC,
    qty NUMERIC,
    pnl NUMERIC
) PARTITION BY LIST (strategy_name);

CREATE TABLE backtest_trades_ema_trend
    PARTITION OF backtest_trades FOR VALUES IN ('ema_trend');
-- ... repeat for each strategy
```
Queries filtered by `strategy_name` touch only one partition.

**Evidence from codebase planning:** The pending todo notes "At 20-40M trades,
backtest_trades will be ~10-20 GB. Partition by strategy_name or asset_id?"
Answer: strategy_name. Strategy is the most common query filter (leaderboard,
overfitting analysis). asset_id partitioning would produce 109 partitions
with uneven sizes (BTC has far more data than small caps).

---

#### BS-TS-3: Monte Carlo on Every Run (Mandatory)

**Why Expected:** `backtest_metrics` already has `mc_sharpe_lo`, `mc_sharpe_hi`,
`mc_sharpe_median` columns — all NULL. These are the primary outputs of a Monte Carlo
run. A backtest result without Monte Carlo confidence intervals is an incomplete result.

**Complexity:** Medium

**What It Looks Like:** After each backtest completes, call:
```python
mc_result = monte_carlo_trades(
    trades_df=trades,
    n_simulations=1000,
    metric='sharpe',
    seed=42
)
# Store percentiles: mc_sharpe_lo=5th, mc_sharpe_median=50th, mc_sharpe_hi=95th
```
`analysis/monte_carlo.py` already implements `monte_carlo_trades()` and
`monte_carlo_returns()`. The integration step is calling it inside
`bakeoff_orchestrator.py` and persisting the result.

**Evidence from codebase:** `backtests/metrics.py` defines the `backtest_metrics` schema
with these columns. `analysis/monte_carlo.py` exists. The wiring call is missing.

---

#### BS-TS-4: Multiprocessing Orchestrator with NullPool (Mandatory)

**Why Expected:** Single-process sequential execution of 460K runs at ~30s each =
~159 days wall time. Multiprocessing with 8 workers = ~20 days. With 16 workers on VM
= ~10 days. NullPool is required on Windows to avoid SQLAlchemy connection-pool
corruption across processes.

**Complexity:** Medium

**What It Looks Like:**
```python
# Existing pattern from MEMORY.md:
# Workers: NullPool for multiprocessing, maxtasksperchild=1 on Windows
with multiprocessing.Pool(
    processes=n_workers,
    maxtasksperchild=1  # critical on Windows
) as pool:
    pool.map(run_single_backtest, work_items)
```
Each worker creates its own engine with `NullPool`. The `params_hash` uniquely identifies
each work item so duplicates are impossible.

**Evidence from codebase:** `bakeoff_orchestrator.py` already uses multiprocessing:
`multiprocessing.Pool` with `maxtasksperchild=1` at line ~240. The new orchestrator
(`run_mass_backtest.py`) should follow this exact pattern.

---

#### BS-TS-5: Early Stopping / Pruning Logic (Mandatory at 460K Scale)

**Why Expected:** Running all 460K combos to completion before knowing which are
viable is wasteful. Standard practice in large-scale backtesting: compute fold-1
Sharpe, skip the combo if it is below a floor (e.g., < -0.5) before running all folds.

**Complexity:** Low

**What It Looks Like:**
```python
# After fold 1 completes
fold1_sharpe = compute_fold1_sharpe(trades_fold1)
if fold1_sharpe < PRUNE_FLOOR:
    log.info("Pruning combo %s: fold1_sharpe=%.2f", params_hash, fold1_sharpe)
    mark_state("pruned", params_hash=params_hash, ...)
    continue  # skip remaining folds
```
Typical floor: -0.5 Sharpe. At 460K combos, pruning 50% after fold-1 halves
compute time with negligible loss of good strategies.

---

#### BS-TS-6: Feature-to-Signal Lineage Tracking (Mandatory for CTF Signals)

**Why Expected:** When CTF features become signals, traceability requires knowing which
IC-scored feature produced which backtest result. Without lineage, you cannot answer
"did the feature that scored IC-IR=1.19 produce good backtests?"

**Complexity:** Low

**What It Looks Like:** Store `feature_name` and `feature_tier` (from
`dim_ctf_feature_selection`) in `strategy_bakeoff_results.experiment_name` or a
dedicated `feature_lineage` column. The `--experiment-name` flag in `run_bakeoff.py`
already supports this for human-readable tags; make it structured.

**Dependencies:** CTF graduation (Area 4) produces the feature list; backtest scaling
consumes it.

---

### Differentiators — Backtest Scaling

#### BS-D-1: Strategy Leaderboard Dashboard Page (High Value)

**Value Proposition:** At 460K runs, the question "which strategy is best" becomes
answerable with statistical confidence. A leaderboard ranked by MC-adjusted Sharpe
(50th percentile) with PBO scores makes the evidence visible.

**Complexity:** Medium

**What It Looks Like:**
```
| Strategy          | Median Sharpe | Sharpe P5 | Max DD | PBO  | n_runs |
|-------------------|---------------|-----------|--------|------|--------|
| ama_momentum      | 1.42          | 0.87      | 12%    | 0.23 | 34,800 |
| ema_trend         | 1.21          | 0.71      | 14%    | 0.31 | 34,800 |
| ctf_threshold_001 | 1.18          | 0.65      | 18%    | 0.28 | 18,000 |
```
Sources: `backtest_metrics` + `strategy_bakeoff_results`. The existing
`dashboard/pages/11_backtest_results.py` is the starting point.

---

#### BS-D-2: PBO Heatmap (Medium Value)

**Value Proposition:** Probability of Backtest Overfitting (from CPCV) is computed per
strategy but not visualized. A strategy-x-timeframe PBO heatmap quickly shows which
strategies are robust vs overfit across TFs.

**Complexity:** Medium

---

#### BS-D-3: VM Execution (High Value for Speed)

**Value Proposition:** The Oracle Singapore VM (Hyperliquid sync VM) has available
compute. Running the mass backtest there enables 24/7 grinding without tying up local
resources.

**Complexity:** High (requires VM-side Python env, DB tunnel, result sync)

**When to Build:** After local multiprocessing is proven stable. Phase 4 of VM strategy.

---

### Anti-Features — Backtest Scaling

#### BS-AF-1: Real-Time Streaming Backtest

**Why Avoid:** The vectorbt-based pipeline is batch. Adding streaming (tick-by-tick
real-time) changes the entire execution model and is not needed for strategy selection.

---

#### BS-AF-2: Storing Full Trade-Level Data for All 460K Runs Indefinitely

**Why Avoid:** At 460M MC samples + 40M trades, unconstrained storage growth becomes
unmanageable. Set a retention policy: keep trade-level detail only for runs with
`mc_sharpe_50th >= 0.5` (viable strategies). Archive or drop others.

**What to Do Instead:** Retain aggregate metrics (`strategy_bakeoff_results`,
`backtest_metrics`) for all runs. Keep `backtest_trades` only for the top-N
strategies by Sharpe after each batch.

---

#### BS-AF-3: Expanding-Window Re-Optimization in First Pass

**Why Avoid:** `bakeoff_orchestrator.py` explicitly notes: "Expanding-window
re-optimization is DELIBERATELY DEFERRED." Fixed-parameter walk-forward is the
correct baseline. Adding re-optimization multiplies compute by N_folds and adds
a new hyperparameter (re-optimization window).

**What to Do Instead:** Run fixed-parameter first. Add re-optimization in a follow-on
phase if fixed-parameter results are inconclusive.

---

## Area 3: ML Signal Combination

### What ML Signal Combination Actually Requires

The existing ML stack: `double_ensemble.py` (LightGBM sliding-window), `regime_router.py`
(per-regime sub-models), `feature_importance.py` (MDA/SFI/clustered FI). What is missing
is the downstream connection: using these models to generate actual trading signals that the
executor processes, rather than just producing research outputs.

---

### Table Stakes — ML Signal Combination

#### ML-TS-1: Cross-Sectional Rank Target Construction (Mandatory)

**Why Expected:** LightGBM predicting forward returns directly is worse than predicting
cross-sectional ranks. Rank targets are more stationary, remove market-wide return bias,
and produce better IC when used as signals. This is standard practice in factor investing.

**Complexity:** Medium

**What It Looks Like:**
```python
# For each timestamp, rank assets by forward_return, normalize to [-1, 1]
y_rank = df.groupby('ts')['forward_ret_5d'].rank(pct=True)
y_rank = 2 * y_rank - 1  # scale to [-1, 1]
```
The `analysis/ic.py` module already computes `compute_forward_returns()`. Cross-sectional
ranking is a preprocessing step before model training.

**Dependencies:** Requires multiple assets to have feature data at the same timestamps.
The `features` table (112 columns) provides this.

---

#### ML-TS-2: SHAP Feature Selection Replacing MDA (Mandatory for Interpretability)

**Why Expected:** The existing `feature_importance.py` uses MDA (permutation importance),
which is correct but slow (requires N_repeats model fits). SHAP values from a single
fitted LightGBM model give comparable ranking with zero additional fits and per-prediction
explanations.

**Complexity:** Medium

**What It Looks Like:**
```python
import shap
explainer = shap.TreeExplainer(lgbm_model)
shap_values = explainer.shap_values(X_test)
feature_importance = pd.Series(
    np.abs(shap_values).mean(axis=0),
    index=X_test.columns
).sort_values(ascending=False)
```
SHAP feature importance is additive (satisfies efficiency axiom), game-theoretically
grounded, and works with LightGBM natively via `TreeExplainer` (no model re-fitting).

**Evidence from codebase:** `shap` is referenced as a known library in the codebase
(grep finds it in `features/microstructure.py` and `backtests/cv.py`). LightGBM is
already the model family in `double_ensemble.py`.

---

#### ML-TS-3: Signal Output Table for ML Predictions (Mandatory)

**Why Expected:** The executor reads from `signals_ema_crossover`, `signals_rsi_mean_revert`,
`signals_atr_breakout` via `SIGNAL_TABLE_MAP`. An ML-generated signal needs its own table
with the same schema for the executor to consume it. Without a registered table, the ML
model produces predictions that live nowhere.

**Complexity:** Medium

**What It Looks Like:**
```python
# New entry in executor/signal_reader.py:
SIGNAL_TABLE_MAP: dict[str, str] = {
    "ema_crossover": "signals_ema_crossover",
    "rsi_mean_revert": "signals_rsi_mean_revert",
    "atr_breakout": "signals_atr_breakout",
    "lgbm_rank": "signals_lgbm_rank",      # NEW
    "xgb_meta": "signals_xgb_meta_label",  # NEW
}
```
Schema must match: `id, ts, signal_id, direction, position_state, entry_price,
entry_ts, exit_price, exit_ts, feature_snapshot, params_hash, executor_processed_at`.

**Dependencies:** Requires Alembic migration to create new signal tables.

---

#### ML-TS-4: Purged Time-Series Cross-Validation (Mandatory — Already Exists)

**Why Expected:** Standard ML cross-validation causes lookahead bias in time series
because train/test splits can bleed information across the embargo gap. The existing
`PurgedKFoldSplitter` and `CPCVSplitter` in `backtests/cv.py` solve this — they must
be used for all ML training.

**Complexity:** Low (already implemented)

**What It Looks Like:**
```python
# Existing pattern — must not be bypassed for ML training:
splitter = PurgedKFoldSplitter(n_splits=5, embargo_gap=5)
for train_idx, test_idx in splitter.split(X, t1_series=t1):
    model.fit(X.iloc[train_idx], y.iloc[train_idx])
    preds[test_idx] = model.predict_proba(X.iloc[test_idx])[:, 1]
```

**Critical risk:** Using `sklearn.model_selection.KFold` instead of `PurgedKFoldSplitter`
will produce artificially inflated IC/Sharpe for ML signals due to train/test leakage.

---

#### ML-TS-5: Meta-Label Filtering (Mandatory for XGBoost)

**Why Expected:** Meta-labeling (Lopez de Prado, 2018 Chapter 3) trains a secondary
classifier to predict whether a primary signal's trade will be profitable. The primary
signal (e.g., EMA crossover) generates trade entries; the meta-labeler filters to only
take high-confidence ones.

**Complexity:** High

**What It Looks Like:**
```python
# Phase 1: Primary signal generates trade entries
primary_signals = ema_crossover_signals(bars)

# Phase 2: Meta-labeler trained on primary signal outcomes
X_meta = features.loc[primary_signals.index]
y_meta = (primary_signal_returns > 0).astype(int)  # binary: was trade profitable?
xgb_meta = XGBClassifier(...)
xgb_meta.fit(X_meta_train, y_meta_train)

# Phase 3: At prediction time, only take signals where meta-labeler > threshold
meta_proba = xgb_meta.predict_proba(X_meta_live)[:, 1]
filtered = primary_signals[meta_proba > 0.6]  # confidence threshold
```
`scripts/labeling/run_meta_labeling.py` exists. `meta_label_results` table exists.
The missing piece: using the trained meta-labeler to filter live signals in the executor.

**Evidence from codebase:** `triple_barrier_labels` table populated, `ml_experiments`
table exists. The `run_meta_labeling.py` script runs offline — it is not wired to
executor-time filtering.

---

### Differentiators — ML Signal Combination

#### ML-D-1: Regime-Conditional ML Models (High Value)

**Value Proposition:** `regime_router.py` dispatches different sub-models per L2 regime
(Up/Down/Sideways). Training a LightGBM ranker separately for each regime and then
combining with the regime classifier could materially improve IC during trending vs mean-
reversion regimes.

**Complexity:** High

**Dependencies:** Requires stable regime labels (already built) + sufficient per-regime
training samples (at least 60 bars per regime instance).

---

#### ML-D-2: Optuna Hyperparameter Optimization for ML Signals (Medium Value)

**Value Proposition:** `run_optuna_sweep.py` exists but uses manually defined search
spaces. For LightGBM ranker, Optuna can optimize `num_leaves`, `learning_rate`,
`n_estimators`, `embargo_gap` jointly, with the Sharpe ratio of OOS predictions as
objective.

**Complexity:** Medium

---

### Anti-Features — ML Signal Combination

#### ML-AF-1: Deep Learning for Signal Generation

**Why Avoid:** LSTM/Transformer models require far more data than available (4.1M bars
across 109 assets sounds large, but per-asset 1D series are only ~1,500 bars).
LightGBM on engineered features is empirically superior for tabular financial data at
this scale.

**What to Do Instead:** Use LightGBM with SHAP-selected features. Add deep learning
only if and when per-asset data exceeds 5,000+ bars.

---

#### ML-AF-2: Online Learning / Model Drift Adaptation

**Why Avoid:** Updating model weights in real-time as new data arrives requires careful
handling of lookahead bias and concept drift. The double_ensemble sliding-window approach
already handles concept drift at batch time. Online learning adds complexity without
clear benefit at daily cadence.

**What to Do Instead:** Retrain double_ensemble weekly or on regime change.

---

#### ML-AF-3: Ensemble of 10+ Models

**Why Avoid:** Adding more models beyond {LightGBM ranker, XGBoost meta-labeler}
without first validating that each component adds independent alpha is cargo-culting.
Ensembles of correlated models add complexity without reducing variance.

**What to Do Instead:** Measure incremental IC contribution of each model independently
before combining.

---

## Area 4: CTF Graduation

### What "CTF Graduation" Actually Requires

Phase 92 confirmed: 131 active features in `dim_ctf_feature_selection`, IC-IR up to
1.19, rho=0.19 non-redundant vs AMA. The CTF table has 73.9M rows. The gap: the live
pipeline reads from `dim_feature_selection` (20 features from Phase 80) and
`feature_selection.yaml`. CTF features are not in either.

Graduation means promoting a curated subset of CTF features so they flow through
signal generation, IC staleness monitoring, and BL portfolio weights.

---

### Table Stakes — CTF Graduation

#### CTF-TS-1: Promote Top 10-20 CTF Features to dim_feature_selection (Mandatory)

**Why Expected:** The production pipeline reads `dim_feature_selection`. Features not in
this table are invisible to signal generators, IC staleness monitor, and portfolio
construction. Promotion is the registry update that makes CTF features first-class.

**Complexity:** Low

**What It Looks Like:**
```sql
-- Promote top CTF features by IC-IR to dim_feature_selection with tier='active'
INSERT INTO dim_feature_selection (feature_name, tier, ic_ir, source, promoted_at)
SELECT feature_name, 'active', ic_ir, 'ctf', now()
FROM dim_ctf_feature_selection
WHERE tier = 'active'
ORDER BY ic_ir DESC
LIMIT 20
ON CONFLICT (feature_name) DO UPDATE
  SET tier = EXCLUDED.tier, ic_ir = EXCLUDED.ic_ir, promoted_at = EXCLUDED.promoted_at;
```

**Constraint:** Do not promote all 131 CTF active features at once. Start with top 10-20
to avoid overwhelming the BL portfolio model with correlated inputs.

---

#### CTF-TS-2: CTF Features Materialized into features Table (Mandatory)

**Why Expected:** Signal generators (`generate_signals_ema.py`, etc.) read from the
`features` table (112 columns, bar-level). CTF features live in the `ctf` table with a
different schema (base_tf, ref_tf columns). Signal generators cannot JOIN `ctf` inline
without refactoring their SQL.

**Complexity:** Medium

**What It Looks Like:** Either:
- **Option A (Recommended):** Add promoted CTF feature columns to `features` table via
  Alembic migration + refresh script that populates them from `ctf` JOIN.
- **Option B:** Create a materialized view `features_extended` that UNIONs `features` +
  pivoted `ctf` columns. Simpler but less performant for write operations.

Option A keeps the pipeline's single-table read pattern intact. Option B adds query
complexity everywhere `features_extended` is used instead of `features`.

**Evidence from codebase:** `features` table has 112 columns (established in Phase 80).
CTF table has (id, base_tf, ref_tf, ts, ...) schema. The JOIN requires pivoting
CTF feature columns by (base_tf, ref_tf) pair into named columns.

---

#### CTF-TS-3: feature_selection.yaml Updated with CTF Entries (Mandatory)

**Why Expected:** `bakeoff_orchestrator.py` uses `parse_active_features()` which reads
`feature_selection.yaml`. The IC staleness monitor (`run_ic_staleness_check.py`) reads
from this YAML too. Features absent from the YAML are not included in bakeoff or
staleness checks.

**Complexity:** Low

**What It Looks Like:**
```yaml
features:
  # ... existing 20 AMA/EMA features ...

  # CTF graduated features (Phase 93)
  - name: macd_hist_7d_slope
    source: ctf
    base_tf: 1D
    ref_tf: 7D
    tier: active
    ic_ir: 1.19
    promoted_at: "2026-03-29"
  - name: rsi_7d_divergence
    source: ctf
    base_tf: 1D
    ref_tf: 7D
    tier: active
    ic_ir: 1.05
    promoted_at: "2026-03-29"
```

---

#### CTF-TS-4: IC Staleness Monitor Covers CTF Features (Mandatory)

**Why Expected:** The IC staleness monitor from Phase 87 tracks the 20 Phase 80
features. Promoted CTF features must also be monitored — if a CTF feature's IC decays
(e.g., because the ref_tf data stops updating), signals relying on it become noise.

**Complexity:** Low (hook into existing monitor infrastructure)

---

#### CTF-TS-5: Asset-Specific CTF Feature Selection (Mandatory for Per-Asset Routing)

**Why Expected:** The pending todo documents this: features highly predictive for BTC
may fail cross-asset consensus. An `asset_specific` tier in `dim_feature_selection`
allows per-asset feature routing so signal generators can use BTC-specific features
for BTC without forcing them onto all assets.

**Complexity:** High

**What It Looks Like:** New column `asset_id` (nullable) in `dim_feature_selection`.
`asset_id IS NULL` = universal feature. `asset_id = 1` = BTC-only feature. Signal
generators query:
```sql
SELECT feature_name FROM dim_feature_selection
WHERE tier IN ('active', 'asset_specific')
  AND (asset_id IS NULL OR asset_id = :target_asset_id)
```

---

### Differentiators — CTF Graduation

#### CTF-D-1: Cross-Asset CTF Composite Features (High Value)

**Value Proposition:** Market-wide composites (average RSI slope across top-N assets)
and relative-value features (BTC/ETH CTF divergence) capture market sentiment and
leader-follower dynamics not available from single-asset features.

**Complexity:** High

**Dependencies:** 150 HL assets with CTF data (confirmed in pending todo).

---

#### CTF-D-2: Lead-Lag IC Matrix (Medium Value)

**Value Proposition:** BTC's CTF features often lead altcoin returns by 1-3 days. A
Granger causality matrix across CTF features would identify the strongest predictive
leads, enabling systematic cross-asset signal generation.

**Complexity:** High

---

### Anti-Features — CTF Graduation

#### CTF-AF-1: Graduating All 131 Active CTF Features at Once

**Why Avoid:** 131 CTF features are highly correlated with each other (they are all
cross-timeframe variants of the same base indicators). Adding all 131 to the BL portfolio
model would swamp the 20 existing features and produce a near-singular covariance matrix.

**What to Do Instead:** Promote top 10-20 features by IC-IR with a correlation cap
(max pairwise Spearman |r| < 0.6 among promoted features).

---

#### CTF-AF-2: Promoting CTF Features Before Materialization Into features Table

**Why Avoid:** Adding features to `dim_feature_selection` and `feature_selection.yaml`
before the data is physically available in the `features` table causes signal generators
to fail with "column not found" errors.

**Sequencing required:** (1) Alembic migration adds columns → (2) Refresh script populates
data → (3) Registry (dim_feature_selection + YAML) updated → (4) Signal generators tested.

---

## Area 5: FRED Equity Indices

### What Adding Equity Indices to FRED Pipeline Actually Requires

The macro pipeline already handles 39 FRED series. Adding SP500/NASDAQ/DJIA/R2K is a
data + feature extension, not an architectural change. The decision (documented in
`.planning/todos/pending/2026-03-28-fred-equity-indices-macro-pipeline.md`) is to keep
these in the macro layer (not the bar pipeline) because they are daily closes only.

---

### Table Stakes — FRED Equity Indices

#### FE-TS-1: Four FRED Series in SERIES_TO_LOAD (Mandatory)

**Why Expected:** `fred_reader.py` loads from `SERIES_TO_LOAD`. Adding the four series
IDs makes them flow through the existing `load_series_wide()` → `forward_fill.py` →
`feature_computer.py` pipeline automatically.

**Complexity:** Low

**What It Looks Like (FRED series IDs):**
| Index | FRED Series ID | Frequency |
|-------|----------------|-----------|
| S&P 500 | `SP500` | Daily |
| NASDAQ Composite | `NASDAQCOM` | Daily |
| Dow Jones Industrial Average | `DJIA` | Daily |
| Russell 2000 | `RUT` (via FRED) | Daily |

Note: FRED S&P 500 access requires St. Louis Fed agreement (available, 10 years history).
FRED has confirmed these are accessible via the standard API.

**Dependency check:** `fred.series_values` on GCP VM must have these series populated.
If not collected yet, VM collection script must be updated first.

---

#### FE-TS-2: Derived Features in feature_computer.py (Mandatory)

**Why Expected:** Raw index levels are not predictive. Standard derived features are:
returns (1d, 5d, 20d), realized volatility (20d rolling), drawdown from running max,
and MA ratios (price vs 50d/200d). These are the same features computed for FRED rate
and dollar series — the pattern is established.

**Complexity:** Low

**What It Looks Like:** Follow the exact pattern of existing FRED features:
```python
# In feature_computer.py, after loading sp500 series:
df['sp500_ret_1d'] = df['SP500'].pct_change(1)
df['sp500_ret_5d'] = df['SP500'].pct_change(5)
df['sp500_ret_20d'] = df['SP500'].pct_change(20)
df['sp500_vol_20d'] = df['sp500_ret_1d'].rolling(20).std() * np.sqrt(252)
df['sp500_drawdown'] = df['SP500'] / df['SP500'].rolling(252).max() - 1
df['sp500_ma50_ratio'] = df['SP500'] / df['SP500'].rolling(50).mean() - 1
df['sp500_ma200_ratio'] = df['SP500'] / df['SP500'].rolling(200).mean() - 1
```

---

#### FE-TS-3: Rolling Crypto-Equity Correlations in cross_asset.py (Mandatory)

**Why Expected:** The primary value of equity indices in a crypto platform is the
correlation signal. BTC-SPX rolling 30d correlation is a recognized risk-on/risk-off
indicator. VIX spikes above 25 precede crypto sell-offs with high reliability.

**Complexity:** Low (cross_asset.py already has correlation infrastructure)

**What It Looks Like:**
```python
# Rolling BTC-SPX 30d correlation
df['btc_spx_corr_30d'] = df['btc_ret_1d'].rolling(30).corr(df['sp500_ret_1d'])
df['btc_nasdaq_corr_30d'] = df['btc_ret_1d'].rolling(30).corr(df['nasdaq_ret_1d'])

# Risk-on/risk-off divergence signal
# Positive divergence (crypto up, equity down) = crypto-specific risk
df['crypto_equity_divergence'] = df['btc_ret_5d'] - df['sp500_ret_5d']
```

---

#### FE-TS-4: Alembic Migration for New Columns in fred_macro_features (Mandatory)

**Why Expected:** `fred.fred_macro_features` is a schema-enforced table. Adding 20+
new columns (7 per index * 4 indexes = ~28 columns) without a migration will crash the
feature_computer's INSERT.

**Complexity:** Low

---

#### FE-TS-5: Forward-Fill Limits for Equity Index Data (Mandatory)

**Why Expected:** Equity indices do not trade on weekends or US holidays. `forward_fill.py`
has configurable `ffill_limits` per series — these must be set to avoid forward-filling
equity data across more than 3 business days (holiday maximum). Without this limit,
a 3-day weekend propagates Friday's close into Tuesday without warning.

**Complexity:** Low

**Evidence from codebase:** `.planning/todos/pending/2026-03-28-fred-equity-indices-macro-pipeline.md`
notes: "forward_fill.py ffill limits already added." This is a reminder to verify
limit is set appropriately (suggest ffill_limit=5 calendar days = ~3 trading days).

---

### Differentiators — FRED Equity Indices

#### FE-D-1: Equity Drawdown as Macro Regime Dimension (High Value)

**Value Proposition:** The 4-dimension macro regime classifier uses monetary policy,
liquidity, risk appetite, and carry. Adding an equity drawdown dimension (SPX < -10%
= bear market) would make the L4 regime label more sensitive to equity stress events
that precede crypto volatility.

**Complexity:** Medium

---

#### FE-D-2: Golden/Death Cross Detection as Event Gate (Medium Value)

**Value Proposition:** SPX 50d/200d MA crossover (golden cross = bullish, death cross =
bearish) is a widely-tracked institutional signal. Adding it as a macro gate condition
(reduce sizing when SPX death cross active) integrates standard equity technical analysis
into the crypto risk framework.

**Complexity:** Low

---

### Anti-Features — FRED Equity Indices

#### FE-AF-1: Treating Equity Indices as Tradeable Assets

**Why Avoid:** Equity indices are macro context signals only. They are not cryptos,
have no venue_id in dim_venues, no OHLCV, and no valid risk/executor paths. Adding
them to the bar pipeline or position sizing would corrupt the trading pipeline.

**What to Do Instead:** Keep in `fred.fred_macro_features` table. No entry in
dim_assets, no bar tables, no executor config.

---

#### FE-AF-2: Real-Time Equity Index Feeds

**Why Avoid:** The macro pipeline is daily-batch (FRED data is end-of-day). Adding
intraday equity index feeds would require a different data source (not FRED), new
infrastructure, and handling gaps during trading hours. Complexity far exceeds the
marginal value over daily closes.

**What to Do Instead:** Keep daily resolution. Monitor `sp500_ret_1d` and
`sp500_vol_20d` from FRED's end-of-day data.

---

## Feature Dependencies

```
Operational Activation
  OA-TS-1 (Scheduler)
    |
    +---> signals stage runs before executor stage (existing STAGE_ORDER)
    |
    +---> OA-TS-2 (cadence_hours tuning)
    |
    +---> OA-TS-3 (run log monitoring)
    |
    +---> OA-TS-4 (dim_executor_config populated)

CTF Graduation (prerequisite for Backtest Scaling)
  CTF-TS-1 (Promote to dim_feature_selection)
    |
    +---> CTF-TS-2 (Materialize into features table)  [must precede TS-1]
    |
    +---> CTF-TS-3 (Update feature_selection.yaml)    [must precede TS-1]
    |
    +---> CTF-TS-4 (IC staleness coverage)
    |
    +---> BS-TS-6 (Feature-to-signal lineage)

Backtest Scaling
  BS-TS-5 (Multiprocessing orchestrator)  [Phase 5 in todo — build first]
    |
    +---> BS-TS-1 (Resume-safe state table)
    |
    +---> BS-TS-2 (backtest_trades partitioning)
    |
    +---> BS-TS-3 (Monte Carlo on every run)
    |
    +---> BS-TS-4 (Early stopping)

ML Signal Combination
  ML-TS-1 (Cross-sectional rank target)
    |
    +---> ML-TS-4 (PurgedKFold — already built)
    |
    +---> ML-TS-2 (SHAP feature selection)
    |
    +---> ML-TS-3 (Signal output table)  [Alembic migration]
    |
    +---> ML-TS-5 (Meta-label filtering)  [depends on ML-TS-3]

FRED Equity Indices
  FE-TS-1 (VM series collection check)
    |
    +---> FE-TS-4 (Alembic migration)
    |
    +---> FE-TS-2 (Derived features in feature_computer)
    |
    +---> FE-TS-3 (Rolling correlations in cross_asset)
    |
    +---> FE-TS-5 (ffill limits)
```

---

## MVP Recommendation Per Area

### Operational Activation MVP (Minimal effort, immediate value)

1. **OA-TS-1**: Configure daily scheduler (Windows Task Scheduler or cron)
2. **OA-TS-2**: Calibrate `cadence_hours` in `dim_executor_config` to 36h
3. **OA-TS-4**: Verify/seed `dim_executor_config` for all 3 signal types
4. **OA-TS-3**: Weekly SQL query on `executor_run_log` (manual initially)

Defer: OA-D-1 (multi-strategy dashboard), OA-D-2 (burn-in tracker), OA-D-3 (grace period)

### Backtest Scaling MVP (Most value from Phase 5 first)

1. **BS-TS-1**: Build `backtest_run_state` table + orchestrator that reads it
2. **BS-TS-4**: Multiprocessing with NullPool (follow existing bakeoff_orchestrator pattern)
3. **BS-TS-3**: Wire `monte_carlo_trades()` into backtest run — 3 new columns per run
4. **BS-TS-5**: Early stopping at fold-1 Sharpe < -0.5
5. **BS-TS-2**: Partition `backtest_trades` by `strategy_name` (do before data volume grows)

Defer: BS-D-1 (leaderboard), BS-D-2 (PBO heatmap), BS-D-3 (VM execution)

### ML Signal Combination MVP (Start with LightGBM rank, then meta-label)

1. **ML-TS-1**: Cross-sectional rank target construction
2. **ML-TS-4**: Use existing PurgedKFoldSplitter (non-negotiable)
3. **ML-TS-2**: SHAP feature importance to select top 15 features for model
4. **ML-TS-3**: Create `signals_lgbm_rank` table + register in SIGNAL_TABLE_MAP

Defer: ML-TS-5 (meta-label filtering), ML-D-1 (regime-conditional), ML-D-2 (Optuna)

### CTF Graduation MVP (Materialize first, promote second)

1. **CTF-TS-2**: Materialize top 20 CTF features into `features` table columns
2. **CTF-TS-1**: Promote to `dim_feature_selection`
3. **CTF-TS-3**: Add to `feature_selection.yaml`
4. **CTF-TS-4**: Extend IC staleness monitor to cover CTF features

Defer: CTF-TS-5 (asset-specific tier), CTF-D-1 (cross-asset composites), CTF-D-2 (lead-lag matrix)

### FRED Equity Indices MVP (Entirely additive, low risk)

1. **FE-TS-1**: Verify GCP VM has SP500/NASDAQCOM/DJIA series; add if missing
2. **FE-TS-4**: Alembic migration for new columns
3. **FE-TS-2**: Add derived features in `feature_computer.py`
4. **FE-TS-3**: Add rolling correlations in `cross_asset.py`
5. **FE-TS-5**: Set ffill_limit=5 for equity series

Defer: FE-D-1 (equity drawdown regime dimension), FE-D-2 (golden/death cross gate)

---

## Sources

**Codebase analysis (HIGH confidence):**
- `src/ta_lab2/executor/paper_executor.py` — full signal-to-fill pipeline
- `src/ta_lab2/executor/signal_reader.py` — watermark, stale guard, SIGNAL_TABLE_MAP
- `src/ta_lab2/scripts/run_daily_refresh.py` — STAGE_ORDER, timeout tiers
- `src/ta_lab2/backtests/bakeoff_orchestrator.py` — fixed-parameter WF, multiprocessing
- `src/ta_lab2/ml/double_ensemble.py` — LightGBM sliding-window
- `src/ta_lab2/ml/feature_importance.py` — MDA/SFI/clustered FI
- `src/ta_lab2/macro/fred_reader.py` — SERIES_TO_LOAD, existing 39 series
- `src/ta_lab2/features/cross_timeframe.py` — CTF feature schema
- `src/ta_lab2/scripts/analysis/run_ctf_feature_selection.py` — tier classification
- `.planning/todos/pending/2026-03-29-massive-backtest-monte-carlo-expansion.md`
- `.planning/todos/pending/2026-03-28-ctf-production-integration.md`
- `.planning/todos/pending/2026-03-28-fred-equity-indices-macro-pipeline.md`
- `.planning/milestones/v1.2.0-REQUIREMENTS.md`
- `.planning/MILESTONES.md`

**Web research (MEDIUM confidence — verified against codebase patterns):**
- Monte Carlo bootstrap: 1,000 samples is standard; 5th/95th percentile confidence bands
  are the convention. Consistent with `backtest_metrics.mc_sharpe_lo/hi` schema.
- SHAP + LightGBM: `TreeExplainer` is the correct approach for gradient boosting models.
  Consistent with LightGBM 4.6.0 usage in `double_ensemble.py`.
- Cross-sectional rank targets: Standard practice in factor investing, confirmed by
  industry literature. IC computation in `analysis/ic.py` aligns with this pattern.
- Crypto-equity correlation: BTC-SPX positive correlation since 2020 confirmed by
  multiple sources; VIX > 25 as crypto sell-off predictor is consistent with existing
  macro event gate framework.
- PostgreSQL partitioning: List partitioning by strategy_name for trade tables is a
  standard pattern for high-volume query workloads.
