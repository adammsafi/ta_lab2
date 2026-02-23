# Feature Landscape: v0.9.0 Research & Experimentation

**Domain:** Quantitative research platform — feature evaluation, advanced indicators, CV, backtesting statistics, visualization
**Researched:** 2026-02-23
**Scope:** 7 feature areas added to existing quant platform infrastructure

---

## Context: What Already Exists

This milestone adds research and experimentation capabilities to an existing platform.
The bar for "table stakes" is measured against what mature quant research platforms provide
for each feature area, adjusted for what this codebase already has.

| Area | Already Built | Gap for v0.9.0 |
|------|--------------|----------------|
| Adaptive MAs | EMA multi-TF (9/10/21/50/200), 6 alignment variants, _u sync, z-scores | KAMA, DEMA, TEMA, HMA — same full pipeline treatment |
| IC Evaluation | Pearson correlation, logistic regression weights, feature_target_correlations() | Spearman IC, IC decay, IC by regime, turnover/stability |
| PSR | Sigmoid stub: `1 / (1 + exp(-sharpe))` — not the real formula | Full Lopez de Prado formula with skewness/kurtosis/n; DSR for multiple testing |
| Purged CV | expanding_walk_forward() + fixed_date_splits() — no embargo, no purging | Embargo gap, purging overlapping labels, CPCV optional |
| Feature Experimentation | Design notes in feature_experimentation.md (not built) | Config-driven registry, lifecycle states, A/B comparison |
| Dashboard | None | Streamlit: research explorer + pipeline monitor (two modes) |
| Notebooks | None | End-to-end demos polished enough to share |

---

## Feature Area 1: Adaptive Moving Averages (KAMA, DEMA, TEMA, HMA)

### Table Stakes

Features users expect when adding adaptive MAs to an existing multi-TF platform.
Missing any of these means the new MAs are second-class citizens relative to existing EMAs.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Correct formula for each MA type | KAMA requires Efficiency Ratio; DEMA = 2*EMA - EMA(EMA); TEMA = 3*EMA - 3*EMA(EMA) + EMA(EMA(EMA)); HMA uses WMA(2*WMA(n/2) - WMA(n)) | Medium | DEMA/TEMA are compositional; KAMA needs price direction parameter |
| Multi-TF persistence (id, ts, tf, period) PK | Existing EMA tables use this PK; adaptive MAs must match | Medium | Same DDL pattern as cmc_ema_multi_tf; new tables needed |
| _u sync for each new MA family | Unified tables are how signals read data; if no _u, signal generators can't use them | Medium | Mirror sync_cmc_ema_multi_tf_u.py pattern for each new MA |
| Min-obs guard per TF | EMA guards: `period * min_obs_multiplier`; KAMA needs same (KAMA converges slowly — needs more warmup) | Low | KAMA is more sensitive to warmup than standard EMA |
| Derivative columns (d1, d2, d1_roll, d2_roll) | Existing EMA tables expose these; signal generators use crossovers between d1 values | Medium | Same ema_operations.py pattern applies |
| Z-scores on returns (_zscore_30, _zscore_90, _zscore_365) | Returns tables for EMAs have z-scores; new MA returns need same treatment | Medium | refresh_returns_zscore.py pattern already established |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Efficiency Ratio (ER) as standalone column in KAMA table | ER itself is a useful volatility/trending signal; exposing it separately enables IC analysis | Low | Store ER alongside KAMA value during computation |
| KAMA-specific parameters (fast/slow smoothing constants) | Allows tuning responsiveness; default is Perry Kaufman's 2/30 but alternatives exist | Low | Expose as config; don't hardcode |
| Signal generator support (KAMA crossover strategy) | KAMA-based crossover as 4th signal generator | High | Separate effort; do not block MA pipeline on this |
| Cross-MA comparison viz (EMA vs KAMA on same chart) | Research utility: shows where adaptive MA diverges from EMA | Medium | Useful in Streamlit explorer; not needed in DB |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| KAMA computed without warmup period | KAMA value is garbage for the first `period` bars; presenting it misleads IC analysis | Always enforce min_obs guard; write NULLs for warmup bars |
| All 4 MAs in a single table | Makes DDL and queries ambiguous; which MA type is this row? | Separate tables per MA type (cmc_kama_multi_tf, etc.) — same as existing EMA family pattern |
| Calendar alignment variants before core works | Adding 5 alignment variants (multi_tf, cal_us, cal_asia, etc.) before validating core MA computation | Build multi_tf first, validate IC, then add calendar variants if research shows value |
| HMA computed as pure EMA of EMA | HMA requires WMA, not EMA; the lag elimination property is lost if substituted | Implement proper WMA; numpy vectorized implementation exists and is not hard |

### Feature Dependencies

```
Existing EMA pipeline
  -> New MA tables (DDL: same (id, ts, tf, period) PK pattern)
  -> New MA feature classes (BaseEMAFeature subclasses)
  -> New MA refresher scripts
  -> _u sync scripts (one per MA family)
  -> Returns tables (cmc_kama_returns_multi_tf etc.)
  -> Z-score refresh coverage in refresh_returns_zscore.py

Signal pipeline (optional, defer)
  -> KAMA crossover signal generator
  -> Uses cmc_kama_multi_tf_u via LEFT JOIN (same as EMA signal pattern)
```

---

## Feature Area 2: Information Coefficient (IC) Evaluation

IC is the Spearman rank correlation between a feature's value and the forward return of the asset
over a given horizon. It is the standard tool for measuring predictive signal quality in quant research.
IC = 0 means no predictive power. IC > 0.05 sustained over time is meaningful. IC > 0.10 is strong.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Spearman (rank) IC, not Pearson | Pearson IC is sensitive to return outliers; Spearman is the industry standard for this metric | Low | `scipy.stats.spearmanr` or `pandas.Series.rank` + correlation; NOT the existing Pearson in feature_eval.py |
| IC computed per feature, per forward-return horizon | Standard horizons: 1D, 5D, 20D — measures decay rate. IC at 1D high but 20D near zero = short-lived signal | Medium | Vectorized across horizons; future_return() already exists |
| Rolling IC (time series of IC values) | Single-number IC is misleading; rolling shows stability, regime-dependence, and whether IC is degrading | Medium | Rolling window: typically 63 bars (1 quarter) |
| Mean IC and IC-IR (mean / std of IC) | IC-IR = Information Ratio for features; IC-IR > 0.5 is the benchmark for a signal worth keeping | Low | Compute from rolling IC series |
| IC decay table (IC vs horizon) | Shows how quickly the signal's predictive power decays — critical for setting holding period | Medium | Run IC for horizons [1, 2, 3, 5, 10, 20, 60] bars |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| IC by regime | Splits IC computation by regime label (trend_state, vol_state) — answers "does this signal work in all regimes or only trending markets?" | Medium | Existing regime labels in cmc_regimes available; group IC by regime |
| Feature turnover / rank autocorrelation | High IC but 100% daily rank turnover = not tradable; rank autocorrelation measures signal stability | Medium | `factor_rank_autocorrelation()` in alphalens pattern; period-over-period rank correlation |
| Feature redundancy detection | IC of feature A vs feature B: if both high IC but correlated, one is redundant | Low | Existing redundancy_report() covers this; extend to use rank correlation instead of Pearson |
| IC significance test (t-test on rolling IC) | `t = mean_IC * sqrt(T) / std_IC`; flags whether IC is statistically non-zero | Low | Standard formula; adds t-stat and p-value to IC summary output |
| Quantile returns analysis | Divide assets into quintiles by feature value; top quintile should outperform bottom — visualize spread | High | Requires cross-asset universe; current platform is single-asset-series-focused, not cross-sectional |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Using Pearson IC as primary metric | Pearson IC inflates for features correlated with return magnitude not direction; Spearman is the standard | Replace feature_eval.py's `corr()` with spearmanr for IC calculation |
| Computing IC without lag alignment | Feature at time t correlated with return at time t is look-ahead; must use future_return() shifting | Always use `close.shift(-horizon) / close - 1` (already in feature_eval.py); verify no leakage |
| Single IC value across entire history | Hides the fact that IC may be driven by a single regime or crash event | Always report rolling IC alongside mean IC |
| Quantile analysis cross-asset before platform supports it | Platform is time-series-per-asset, not cross-sectional; quantile analysis requires ranking across assets simultaneously | Defer quantile analysis; focus on IC time series per feature per asset |

### Feature Dependencies

```
cmc_features (112 columns, already exists)
  -> IC computation against future returns from cmc_returns_bars_multi_tf_u
  -> Requires forward-looking join (feature at t, return at t+horizon)
  -> WARNING: join must preserve look-ahead-free alignment

cmc_regimes (already exists)
  -> IC by regime: join features with regime labels on (id, ts)
  -> Group IC by regime label before computing Spearman correlation

Existing feature_eval.py
  -> Add spearman_ic(), rolling_ic(), ic_decay_table(), ic_by_regime()
  -> Keep existing Pearson corr functions for redundancy detection use case
```

---

## Feature Area 3: Probabilistic Sharpe Ratio (PSR) and Deflated Sharpe Ratio (DSR)

PSR answers: "Given the sample Sharpe I observed, what is the probability the true Sharpe exceeds
a benchmark?" This accounts for sample length, non-normality, skewness, and kurtosis — all of which
cause the sample Sharpe to be an optimistic estimate.

DSR extends PSR to the multiple-testing case: when many strategies are tested, the best observed
Sharpe is inflated by selection bias. DSR deflates by the expected maximum Sharpe under the null.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| PSR full formula (Bailey/Lopez de Prado 2012) | The placeholder `1/(1+exp(-SR))` is not PSR; it has no statistical meaning and will produce wrong rankings | Medium | Formula: `PSR = Φ[(SR - SR*) * sqrt(n-1) / sqrt(1 - skew*SR + (kurt-1)/4 * SR^2)]` |
| Inputs: n, skewness, kurtosis of returns | Current metrics.py only uses mean/std; must add `scipy.stats.skew()` and `scipy.stats.kurtosis()` | Low | Already have `sharpe()` function; extend summarize() |
| Benchmark SR (SR*) parameter | PSR is always relative to a benchmark; default SR* = 0 is valid but should be configurable | Low | Expose as parameter; typical values: 0, 0.5, 1.0 |
| PSR replaces psr_placeholder() in summarize() | The stub is called in backtest metrics and stored in cmc_backtest_metrics; replacing stub fixes stored values | Medium | Requires re-running backtests or updating stored records |
| Annualization frequency parameter | PSR depends on observation frequency (daily vs weekly); must match the return series frequency | Low | Already in sharpe(); thread through PSR |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| DSR (Deflated Sharpe Ratio) for parameter sweeps | When running 100 parameter combinations, best observed Sharpe is inflated; DSR corrects for how many trials were run | High | Requires: number of trials tested, correlation between trials (if independent, correlation=0) |
| Minimum Track Record Length (MinTRL) | Inverse of PSR: "how many observations do I need to be confident this Sharpe is real at 95%?" | Medium | Direct computation from PSR formula; useful for communicating result validity |
| PSR stored per backtest run | PSR in cmc_backtest_metrics table, replacing the sigmoid stub value | Medium | Schema already has psr column; fix the value, not the schema |
| Probability of Backtest Overfitting (PBO) via CPCV | Bailey/Lopez de Prado 2014; uses CPCV to estimate probability that selected strategy underperforms OOS | High | Requires CPCV infrastructure; high research value, high complexity |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Keeping the sigmoid stub as PSR | The stub maps SR → probability without accounting for sample size or return distribution; a 2-year daily backtest and a 20-year one get the same "PSR" for same SR | Replace entirely with formula; label transition period clearly |
| Computing PSR on very short return series (< 30 obs) | PSR degenerates when n is small; the formula's denominator involves sqrt(n-1) | Guard: return NaN or None for series with fewer than 30 observations |
| Annualizing PSR (PSR is already a probability, not a ratio) | PSR output is in [0,1] probability space; annualizing it is nonsensical | Keep PSR as probability; present alongside annualized Sharpe, not instead of it |
| DSR before CPCV/purged CV is implemented | DSR needs the distribution of tested strategies; without structured trial tracking, the number-of-trials input is guesswork | Implement PSR first; DSR only after parameter sweep infrastructure is organized |

### Feature Dependencies

```
backtests/metrics.py
  -> Replace psr_placeholder() with psr() using full formula
  -> Add dsr() function (depends on number of trials)
  -> scipy.stats for skewness/kurtosis (already in dependencies)

cmc_backtest_metrics table
  -> psr column exists; values become valid after formula fix
  -> DSR would need new column (dsr, n_trials_tested)

Parameter sweep (analysis/parameter_sweep.py)
  -> DSR naturally fits here: sweep tracks n_trials, can compute DSR on best result
```

---

## Feature Area 4: Purged K-Fold Cross-Validation

Standard K-fold CV assumes IID observations. Financial time series are not IID: labels depend on
future price movements, which overlap between adjacent bars. Training on bar t and testing on bar t+1
causes label leakage when the label is a multi-bar forward return.

Purging removes training samples whose labels overlap with the test set time window.
Embargo adds a buffer gap after the test set to prevent serial correlation leakage.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Embargo gap parameter | Even after purging, serial correlation in features can cause leakage from the bars immediately before/after the test set | Medium | Embargo = skip N bars after test end; N typically 5% of total observations |
| Purging of overlapping labels | If forward return label at t spans [t, t+h], any training sample with label period overlapping [t, t+h] must be removed | High | Requires label start/end timestamps, not just bar timestamps |
| Time-ordered splits (no future leakage) | CV splits must always be train-before-test in time; no shuffling | Low | Existing splitters.py already does this; purging adds the label overlap check |
| Configurable k (number of folds) | More folds = more CV iterations = better estimate of generalization error; k=5 is standard | Low | Parameter on the CV class |
| Compatible with sklearn pipeline API | Should return (train_indices, test_indices) like sklearn's KFold; enables use with cross_val_score | Medium | Implement as class with split() method returning index arrays |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Combinatorial Purged CV (CPCV) | Instead of 1 test path, CPCV generates C(k,p) paths — provides distribution of OOS performance, not just point estimate | High | Lopez de Prado 2018; skfolio has reference implementation; high value for PBO computation |
| Label span tracking | Store label start/end with each training sample so purging can be precise | High | Requires refactoring how forward returns are attached to features; significant upfront work |
| Gap-free fold visualization | Show train/test splits as timeline chart in Streamlit — makes split logic auditable | Medium | Useful for dashboard; not required for correctness |
| Walk-forward + purged CV hybrid | Outer loop: walk-forward (train grows, test slides); inner loop: purged CV on train set for hyperparameter tuning | High | Mature production approach; complex to implement correctly |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Standard K-fold on time series | Without purging/embargo, CV estimates are optimistically biased — the entire reason for building purged CV | The existing `expanding_walk_forward()` is better than standard KFold even without purging; add purging incrementally |
| Purging without defining label spans | If you purge by "bar timestamp" instead of "label overlap period", you either over-purge (too few training samples) or under-purge (still leaking) | Define label span precisely: a 20D forward return at bar t has label span [t, t+20] |
| CPCV before basic purged KFold works | CPCV is a significant complexity jump; building it before validating purging logic creates untestable code | Ship purged KFold first, validate on simple test case, then add CPCV as extension |
| Purged CV on non-time-series features | Purging is only necessary for forward-looking labels; applying it to contemporaneous features (RSI at time t predicting RSI at time t) adds complexity with no benefit | Gate purging on label type; contemporaneous features use standard splits |

### Feature Dependencies

```
backtests/splitters.py
  -> Add PurgedKFold class alongside existing expanding_walk_forward()
  -> PurgedKFold.split() returns (train_idx, test_idx) arrays
  -> Requires label_start / label_end per sample (or derive from horizon)

cmc_features (existing)
  -> Features are at bar granularity (ts column)
  -> Label span for horizon=20D: [ts, ts + 20*tf_days]
  -> Purging needs to know tf_days from dim_timeframe

CPCV (optional extension)
  -> Builds on PurgedKFold split logic
  -> Generates C(k,p) train/test path combinations
  -> Required for DSR / PBO computation (connects to PSR feature area)
```

---

## Feature Area 5: Feature Experimentation Framework

A config-driven system for registering features in lifecycle states (experimental → promoted → deprecated),
computing them on demand from existing base data, and comparing experimental vs promoted variants.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Lifecycle states per feature (experimental, promoted, deprecated) | Without this, all features are equal; promotes arbitrary inclusion; no path to retirement | Low | Simple enum/string field in config |
| Config file as contract (not code) | Feature definitions in YAML/TOML are readable, diffable, and don't require code changes to add a feature | Medium | Config schema: name, state, indicator_fn, params, description, added_version |
| Compute on demand from base data | Experimental features are computed from cmc_price_bars or cmc_features data at query time; not persisted until promoted | Medium | Reuse existing indicator functions from indicators.py; thin wrapper |
| IC evaluation on experimental feature | The entire point of the framework is to evaluate new features before persisting them; IC is the evaluation metric | Medium | Wires into Feature Area 2 (IC) |
| A/B comparison between experimental and promoted | "Is this KAMA-based feature better than the existing EMA-based equivalent?" — needs side-by-side IC/return analysis | Medium | Output: table of IC values, correlations between candidates |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Version history in config | Track when a feature was promoted or deprecated; enables auditing which features were live during which backtest period | Low | Add added_version, promoted_version, deprecated_version fields to config |
| Promotion path (experimental → promoted → DB persist) | Promotion triggers creation of persistent DB column in cmc_features; demotes to full pipeline citizen | High | Requires Alembic migration (already have Alembic from v0.8.0); automated migration generation |
| Feature dependency graph | If feature B depends on feature A (e.g., KAMA-returns depends on KAMA), the framework tracks this and computes in order | High | DAG required; overkill for most cases; defer to post-MVP |
| Cross-asset feature stability report | Does this feature have consistent IC across BTC, ETH, SOL? Stable features are more robust | Medium | Requires running IC per asset; output: IC heatmap by asset |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Building a GUI for feature registration | Heavy investment in UI when a YAML config file serves the same purpose for a 1-person research team | YAML config + code review is sufficient; Streamlit can read the config and display it |
| Persisting all experimental features to DB | DB becomes polluted with features that get retired; column management becomes unmanageable | Experimental features computed at query time; DB persistence only on promotion |
| Feature versioning with separate DB tables per version | 1 table per feature version creates 50+ tables quickly | Version in a single table via a `feature_version` column or separate config tracking |
| Recomputing promoted features via the framework | Promoted features are already in cmc_features and maintained by existing refresh scripts; double-computing wastes resources | Framework handles experimental only; promoted features flow through existing cmc_features pipeline |

### Feature Dependencies

```
Config file (new): .planning/features/feature_registry.yaml (or similar)
  -> Feature definitions: name, state, indicator_fn, params, horizons_for_IC

indicators.py (existing)
  -> Compute engine calls existing functions: rsi(), atr(), macd(), etc.
  -> New indicator functions added here as needed (KAMA etc. from Feature Area 1)

IC evaluation (Feature Area 2)
  -> Compute on-demand IC for experimental features
  -> Output IC summary with experimental vs promoted comparison

Alembic (v0.8.0, existing)
  -> Promotion path generates Alembic migration to add column to cmc_features
```

---

## Feature Area 6: Streamlit Dashboard (Two Modes)

### Mode A: Research Explorer

Used during active research sessions to evaluate signals, features, and regime behavior.

#### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Asset + timeframe selector | All queries must be parameterized; hardcoded asset/TF is unusable as a research tool | Low | Streamlit selectbox from dim_assets and dim_timeframe |
| IC score table for all features | Top-N features by IC with sortable columns; the central research artifact | Medium | Reads from cmc_features; runs IC on demand or from cached results |
| Equity curve chart per strategy | Basic performance visualization; without it, the dashboard has no connection to backtest output | Medium | Reads cmc_backtest_runs + metrics; Plotly line chart |
| Regime transition timeline | Visualize regime labels on price chart (color bands or overlay); connects regime to price behavior | Medium | Reads cmc_regimes; Plotly chart with colored regions by regime state |
| Feature comparison (A vs B) | Select two features, see IC side-by-side; the main differentiator for the experimentation framework | Medium | Multi-select + IC table filtered by selection |
| Date range filter | All charts must support zooming to subperiods; full history charts are often unreadable | Low | Streamlit date_input or slider |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| IC decay chart (IC vs forward horizon) | See how quickly a signal loses predictive power; informs holding period decisions | Medium | Line chart: horizon on x-axis, mean IC on y-axis |
| Rolling IC chart (IC over time) | See if the signal is degrading or was only good during a specific regime | Medium | Plotly line chart of rolling IC series |
| Feature correlation heatmap | Identify redundant features before adding them to a model | Medium | Seaborn or Plotly heatmap of correlation matrix |
| Regime-conditional IC table | For each regime state, show top features by IC — answers "which features work in which regime" | High | Join on regime labels; compute IC subsetted by regime |
| Experimental feature upload/compute | User selects an experimental feature from registry, computes IC live | High | Wires into Feature Area 5; complex Streamlit state management |

#### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Real-time data streaming | This is a research dashboard, not a live trading terminal; data refreshes on page reload is sufficient | Use `@st.cache_data(ttl=3600)` for DB queries |
| Every feature in one massive page | Research explorer becomes unusable with 112 features and 5 chart types on one page | Use st.tabs() for: Features / Signals / Regimes / Comparison |
| Matplotlib for all charts | Matplotlib is static; interactive zoom/hover requires Plotly or Altair for research use | Use Plotly Express throughout; `st.plotly_chart(fig, use_container_width=True)` |
| Streamlit replacing the DB layer | Doing heavy computation in Streamlit callbacks freezes the UI | Keep heavy IC computation in Python functions; cache results; Streamlit is display only |

---

### Mode B: Pipeline Monitor

Used during operations to check pipeline health, data freshness, and QA status.

#### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Run status table (last N runs) | Shows timestamp, duration, exit status for each refresh step | Low | Reads from run log (if exists) or a simple runs table |
| Data freshness per table | For each major table, show: last ingested timestamp, rows, staleness in hours | Low | Reads asset_data_coverage table (already exists); SELECT max(last_ts) per source_table |
| PASS/FAIL stat summary | Count of PASS/WARN/FAIL across all stats runners in last 24h | Medium | Reads existing stats tables (bars_stats, features_stats, etc.) |
| Telegram alert history | Last N alerts sent — helps diagnose what the pipeline noticed | Medium | Requires logging Telegram sends to DB or file |
| Per-table row counts vs expected | Flags tables that lost rows unexpectedly (data deletion, failed refresh) | Low | Compare current row count to 7-day rolling average |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Red/yellow/green status badges | Traffic-light UX for quick triage; FAIL = red, WARN = yellow, PASS = green | Low | Streamlit `st.metric()` with delta_color; or markdown with color |
| Staleness SLA threshold coloring | Highlight tables breaching the SLA defined in runbooks (bars < 48h, features < 72h) | Low | Compare staleness hours to configurable thresholds |
| Asset-level data gap detection | Some assets may have gaps while others are healthy; per-asset freshness table | Medium | Group by id in asset_data_coverage; flag outliers |
| Pipeline execution timeline (Gantt-like) | Shows which refresh steps ran, in what order, with duration — useful for perf debugging | High | Requires structured run log; complex to implement |

#### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Pipeline monitor as separate application | Two Streamlit apps are harder to maintain; both modes need the same DB connection | Single Streamlit app with mode toggle (selectbox: "Research / Monitor") |
| Auto-refresh on a timer | Streamlit auto-refresh experimental API is fragile; pipeline data doesn't change that fast | Manual refresh button + `@st.cache_data(ttl=300)` for 5-minute cache |
| Replacing Telegram alerts with dashboard | Dashboard is passive; Telegram is active (pushes on failure); both serve different purposes | Monitor reads the same stats that trigger Telegram; do not replace either |

---

## Feature Area 7: Jupyter Notebooks

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| End-to-end demo notebook (one per major topic) | Notebooks are the standard medium for sharing quant research; without them, findings live only in scripts | Medium | One notebook per: (1) feature IC analysis, (2) backtest walk-through, (3) regime analysis |
| Data loading cells are clean and documented | If cell 1 fails to connect to DB, the notebook is unusable by anyone else | Low | Use environment variable for DB connection; document in first cell |
| Clear separation of: load / compute / visualize | Notebooks that intermix computation with visualization are hard to debug and iterate on | Low | Naming convention: ## Load Data, ## Compute IC, ## Visualize |
| Outputs cleared before commit | Notebooks with cached outputs are large binary blobs that pollute git history | Low | Add `nbstripout` pre-commit hook or document "always clear before commit" |
| Results reproducible from DB (not hardcoded DataFrames) | Notebooks that use hardcoded data snapshots become stale immediately | Medium | All data from DB queries; parameterize asset, TF, date range at top |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Narrative markdown cells explaining quant concepts | Makes notebooks shareable with non-quant readers; explains WHY before showing code | Low | Add 2-3 sentences before each compute section explaining the metric |
| Parameter cell at top (asset, TF, date range) | Single cell to change to run for different asset/timeframe — essential for reusability | Low | `ASSET_ID = 1`, `TF = "1D"`, `START_DATE = "2022-01-01"` as named constants at top |
| IC heatmap across all features as final cell | Summary artifact showing the full feature ranking — the "deliverable" of the research notebook | Medium | Plotly heatmap; columns = features, rows = horizons, values = IC |
| Walk-forward PnL notebook showing purged CV result | Demonstrates the CV methodology on a real strategy — builds confidence in backtest validity | High | Requires purged CV from Feature Area 4 |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Notebooks that duplicate production code | If IC computation is also in feature_eval.py, the notebook should call that function — not reimplement | `from ta_lab2.analysis.feature_eval import spearman_ic` in notebook |
| One 500-line mega-notebook | Unnavigable; sections mix concerns; hard to share selectively | 3-5 focused notebooks, each with a single research question |
| Notebooks that require local CSV files | Creates file path dependency; breaks when anyone else runs the notebook | Always load from DB; if DB query is slow, cache with `@lru_cache` or write to temp Parquet in /tmp |
| nbconvert to PDF as deliverable | PDF removes interactivity; if the recipient can't run the notebook, send HTML export | Use `jupyter nbconvert --to html` for read-only sharing |

---

## Cross-Feature Dependencies

```
Adaptive MAs (Area 1)
  -> Provides new features for IC evaluation (Area 2)
  -> KAMA Efficiency Ratio as standalone IC candidate

IC Evaluation (Area 2)
  -> Required by Feature Experimentation framework (Area 5)
  -> Feeds Streamlit research explorer (Area 6, Mode A)
  -> Drives notebook analysis (Area 7)

PSR/DSR (Area 3)
  -> Replaces stub in backtests/metrics.py (prerequisite: none, standalone)
  -> DSR requires purged CV trial counts (Area 4 dependency)

Purged CV (Area 4)
  -> Enables valid hyperparameter tuning in backtests
  -> Required for CPCV (which enables DSR/PBO)
  -> Feeds walk-forward PnL notebook (Area 7)

Feature Experimentation (Area 5)
  -> Depends on IC evaluation (Area 2) for feature scoring
  -> Feeds Streamlit research explorer (Area 6)
  -> Alembic (v0.8.0) handles promotion migrations

Streamlit Dashboard (Area 6)
  -> Depends on IC evaluation results (Area 2)
  -> Reads cmc_backtest_metrics including fixed PSR (Area 3)
  -> Displays regime data from cmc_regimes (existing)
  -> Reads feature registry config (Area 5)

Notebooks (Area 7)
  -> Imports from ta_lab2 package (all areas above)
  -> Demonstration artifacts, not production code
```

---

## MVP Recommendation

For v0.9.0 MVP, prioritize by value delivered vs complexity:

### Must Have (core research capability)

1. **Spearman IC + IC decay** (Area 2, table stakes) — Replaces Pearson correlation in feature_eval.py; delivers the primary research metric. No new infrastructure needed.

2. **PSR formula** (Area 3, table stakes) — Replaces one function in metrics.py; fixes stored backtest values. Self-contained.

3. **Purged KFold basic implementation** (Area 4, table stakes) — New class in splitters.py; embargo + purging without CPCV. Validates backtest methodology.

4. **KAMA + HMA implementations** (Area 1, table stakes) — KAMA is the most research-valuable adaptive MA (ER column is itself an IC candidate). HMA is the simplest to implement correctly. DEMA/TEMA can follow.

5. **Feature registry config** (Area 5, table stakes) — YAML config + compute-on-demand; no DB persistence for experimental features.

6. **Streamlit Pipeline Monitor** (Area 6, Mode B) — Reads existing DB tables; no new infrastructure; immediate operational value.

### Defer to Post-MVP

- **Streamlit Research Explorer**: Higher complexity; depends on IC infrastructure being solid first. Build Mode B first.
- **CPCV and DSR**: High complexity; wait until purged KFold is validated and parameter sweep is organized.
- **Feature promotion path (Alembic migration)**: Experimental features have value before promotion path; build registry first.
- **Quantile returns analysis**: Requires cross-sectional universe view; current architecture is per-asset time series.
- **Feature dependency DAG**: Overkill for first iteration of experimentation framework.
- **Notebooks**: Build after IC evaluation and PSR are working; notebooks showcase those capabilities.

---

## Sources

- Information Coefficient standard: [PyQuant News — IC with Alphalens](https://www.pyquantnews.com/free-python-resources/real-factor-alpha-how-to-measure-it-with-information-coefficient-and-alphalens-in-python)
- Alphalens IC analysis outputs: [Alphalens documentation](https://quantopian.github.io/alphalens/alphalens.html)
- IC decay and turnover: [Quantopian IC tutorial](https://www.quantrocket.com/codeload/quant-finance-lectures/quant_finance_lectures/Lecture38-Factor-Analysis-with-Alphalens.ipynb.html)
- PSR formula: [Quantdare — Probabilistic Sharpe Ratio](https://quantdare.com/probabilistic-sharpe-ratio/)
- PSR paper: [QuantConnect PSR implementation](https://www.quantconnect.com/research/17112/probabilistic-sharpe-ratio/)
- DSR paper: [Bailey/Lopez de Prado — Deflated Sharpe Ratio (PDF)](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
- Purged KFold: [Wikipedia — Purged cross-validation](https://en.wikipedia.org/wiki/Purged_cross-validation)
- CPCV: [skfolio CombinatorialPurgedCV](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html)
- mlfinlab purged CV: [Hudson and Thames mlfinlab](https://github.com/hudson-and-thames/mlfinlab)
- KAMA: [StockCharts — Kaufman Adaptive MA](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average-kama)
- IC by regime: [Two Sigma — ML approach to regime modeling](https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/)
- IC thresholds: [IC article with thresholds](https://thetradinganalyst.com/information-coefficient/)

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| IC / Spearman standard practice | HIGH | Multiple authoritative sources (Alphalens docs, Quantopian lectures, AQR papers) agree; well-established |
| PSR formula | HIGH | Original Bailey/Lopez de Prado paper; QuantConnect implementation; formula is published and unambiguous |
| DSR formula | MEDIUM | Paper is authoritative; Python implementation details verified via GitHub; multiple testing correction approach is sound |
| Purged KFold mechanics | HIGH | Wikipedia + mlfinlab + quantinsti sources agree on purging/embargo mechanics |
| CPCV complexity | MEDIUM | skfolio has reference implementation; complexity estimate based on reading source; project-specific integration is unverified |
| Adaptive MA formulas | HIGH | KAMA formula from Kaufman's original source; DEMA/TEMA/HMA formulas are textbook-standard |
| Streamlit feasibility | HIGH | Direct experience in codebase; Streamlit is well-documented |
| Feature registry design | MEDIUM | Lifecycle concepts from tidyverse + OpenTelemetry; quant-specific registry is custom design — no authoritative reference |
