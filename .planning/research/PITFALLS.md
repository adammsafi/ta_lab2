# Domain Pitfalls: v0.9.0 Research & Experimentation

**Domain:** Adding adaptive MAs, IC evaluation, purged K-fold CV, PSR, feature experimentation, and Streamlit dashboard to an existing quant research platform (ta_lab2)
**Researched:** 2026-02-23
**Scope:** Integration pitfalls specific to adding these six feature groups to an existing system with 50+ tables, 22M+ rows, vectorbt 0.28.1, numpy 2.4.1, pandas 2.3.3, numba 0.64.0, Streamlit 1.44.0, Windows development environment

---

## 1. Adaptive Moving Averages (KAMA, DEMA, TEMA, HMA)

### Critical: Adaptive MAs Cannot Share the `cmc_ema_multi_tf` PK Without a `ma_type` Discriminator

**What goes wrong:** The existing `cmc_ema_multi_tf` table uses PK `(id, ts, tf, period)`. KAMA and standard EMA both have a `period` (e.g., `period=10`). If KAMA values are inserted into the same table as standard EMA values — even into a new table with the same schema — the join logic in signal generators (`LEFT JOIN cmc_ema_multi_tf_u WHERE period = :p`) will return KAMA values when EMA values were expected or vice versa, because both share the same `period` namespace.

The downstream `_u` sync tables and all LEFT JOINs in signals will silently mix KAMA and EMA rows unless a `ma_type` discriminator is added to the PK.

**Why it happens:** The decision was made for this project to query `cmc_ema_multi_tf_u` directly via LEFT JOINs for EMA data (documented in MEMORY.md). Adding adaptive MAs to the same namespace without a discriminator propagates incorrect values into signal generators silently — no error is raised, backtest metrics simply shift.

**Consequences:** Signal generators produce wrong crossover signals. Backtest metrics differ from baseline without a visible error. The bug is very hard to detect post-hoc because the row counts in `cmc_ema_multi_tf` remain correct.

**Prevention:**
- Create a **separate table family** for adaptive MAs (e.g., `cmc_adaptive_ma_multi_tf`, `cmc_adaptive_ma_multi_tf_u`) with a `ma_type TEXT NOT NULL` column as part of the PK: `PRIMARY KEY (id, ts, tf, period, ma_type)`.
- Do NOT repurpose `cmc_ema_multi_tf_u` for adaptive MAs. The existing signal generators query it directly and cannot be changed without breaking v0.8.0 signals.
- Define `ma_type` values as controlled vocabulary: `'ema'`, `'kama'`, `'dema'`, `'tema'`, `'hma'`.
- Add a Alembic migration to create the new table before any adaptive MA data is written.
- Write a one-line CI smoke test that asserts `cmc_ema_multi_tf_u` row count is unchanged after the migration.

**Warning signs:**
- Any adaptive MA script that writes to `cmc_ema_multi_tf` or `cmc_ema_multi_tf_u`
- Signal generators that do not filter on `ma_type` after adaptive MAs are added
- Backtest metrics shift after adaptive MA data is first loaded, with no code change to signals

**Phase:** Adaptive MA table design. Define the `ma_type` discriminator in the DDL before writing any computation code.

---

### Critical: KAMA Warm-Up Produces Incorrect Values on Incremental Refresh

**What goes wrong:** KAMA requires a full history to produce a correct value at any given timestamp. The KAMA recurrence `KAMA_t = KAMA_{t-1} + SC_t * (close_t - KAMA_{t-1})` where the initial KAMA is a simple moving average of the first `period` bars. An incremental refresh that loads only the last N bars will start KAMA from a wrong seed, producing values that look plausible but are numerically incorrect for all rows in the incremental window.

The existing `BaseEMARefresher` pattern has this same issue for standard EMAs and handles it by loading full history for IDs being refreshed (confirmed by the `load_source_data` interface in `base_ema_feature.py`). But a developer building adaptive MA refreshers for the first time may assume a short lookback is sufficient.

DEMA, TEMA, and HMA compound this: DEMA requires computing two EMA layers and TEMA three layers, each requiring warm-up independently.

**Prevention:**
- Adaptive MA refreshers MUST load at minimum `max(period) * 10` bars of history before the first date being persisted. The StockCharts documentation recommends 10x the period.
- The `BaseEMARefresher` warm-up pattern is already established. New adaptive MA refreshers must follow the same `start - warmup_days` lookback extension.
- Add an explicit assertion after computation: `assert df_kama['kama'].notna().sum() >= expected_min_rows`.
- Write a regression test that computes KAMA over a full history, then recomputes over the last 90 days with warm-up, and asserts the overlapping rows match within floating-point tolerance.

**Warning signs:**
- Refresher loads only `WHERE ts >= :start` without a warm-up offset
- KAMA values for recent bars match the close price exactly (symptom of insufficient warm-up — KAMA collapses to close when seed is wrong)
- First N rows of KAMA output are NaN then suddenly non-NaN at `period` bars — correct behavior; values before that should be excluded from the persisted set

**Phase:** Adaptive MA computation phase. Write the warm-up logic before writing any DB insert code.

---

### Moderate: HMA Uses WMA, Not EWM — The Existing `_ema()` Helper Cannot Be Reused

**What goes wrong:** The project's existing `_ema()` helper in `features/indicators.py` uses `pd.Series.ewm()`. The Hull Moving Average is defined as `HMA = WMA(2*WMA(n/2) - WMA(n), sqrt(n))`, where WMA is a **weighted** (linearly-weighted) moving average, not an exponential moving average. A developer who extends the `_ema()` or `_sma()` helper pattern without checking the HMA formula will compute a wrong result that closely resembles HMA numerically (because EMA and WMA are both smoothing functions) but diverges especially during trend inflections.

**Prevention:**
- Implement a dedicated `_wma(s: pd.Series, window: int) -> pd.Series` helper using `pd.Series.rolling().apply(lambda x: np.dot(x, np.arange(1, window+1)) / np.arange(1, window+1).sum())`.
- For performance, use numpy convolution: `np.convolve(s.values, weights[::-1], mode='valid')` rather than a rolling apply lambda, which is O(n*window) in Python.
- Write a unit test that checks `hma(s, 16)` against a known reference value from a table computed by a trusted external source.

**Warning signs:**
- HMA implementation that calls `ewm()` anywhere
- HMA and EMA produce similar values (within 2%) for trend moves — should differ more

**Phase:** Adaptive MA computation. Implement `_wma()` as a standalone helper before implementing HMA.

---

### Moderate: `fillna(method='ffill')` in `feature_eval.py` and `performance.py` Raises FutureWarning in pandas 2.3 and Will Error in pandas 3.0

**What goes wrong:** The existing codebase already contains two instances of the deprecated `fillna(method='ffill')` pattern: `feature_eval.py` line 78 and `performance.py` line 81. In pandas 2.3.3 (the currently installed version), these produce a `FutureWarning`. In pandas 3.0 (which the `pyproject.toml` does not pin against), they will raise a `TypeError`.

Any new IC evaluation or feature experimentation code that copies the existing `feature_eval.py` pattern will inherit the deprecated call.

**Prevention:**
- Before writing any new IC or feature evaluation code, fix the two existing instances:
  - `df.fillna(method="ffill")` → `df.ffill()`
  - `equity.fillna(method="ffill")` → `equity.ffill()`
- Add `numpy<3.0` or `pandas<3.0` as a constraint in `pyproject.toml` if there is any dependency that has not been tested against pandas 3.0.
- Add a CI step: `python -W error::FutureWarning -m pytest tests/` to catch FutureWarnings as errors before they become TypeError.

**Warning signs:**
- `pytest` output contains `FutureWarning: Series.fillna with 'method' is deprecated`
- Any new file that copies from `feature_eval.py` without inspecting the `fillna` calls

**Phase:** Feature evaluation phase. Fix the existing deprecated calls before adding new IC evaluation code.

---

## 2. Information Coefficient (IC) Evaluation

### Critical: IC Computed Over Full History Leaks Future Information into Feature Selection

**What goes wrong:** IC is computed as `spearmanr(feature_t, return_{t+h})` for each bar `t`. If a developer computes IC over the full asset history and then uses the IC scores to select which features to include in a model or strategy, those features were selected using future return data (the forward returns at the end of the history are used in the IC calculation). Any strategy built on IC-ranked features inherits this look-ahead bias.

This is a subtle form of the "feature selection before cross-validation" error. The IC scores themselves appear to be computed on past data (feature at time t, return at time t+h), but the selection process uses IC scores that integrate information from the entire historical series including near-future periods.

**Why it happens:** IC looks backward: "how correlated was this feature with forward returns?" But feature selection based on those IC scores is a forward-looking use of backward-computed statistics. When applied to the full history, the IC scores incorporate signal from the most recent bars, which overlap with any test period.

**Consequences:** Features with spuriously high IC are promoted. Out-of-sample IC collapses. Backtest looks better than live would.

**Prevention:**
- Always compute IC scores **only on the training window** of each cross-validation fold, never on the full history.
- For exploratory analysis (not for selection), IC over the full history is acceptable if clearly labeled as exploratory.
- Store IC results with a `computed_on` date range field in the database so the computation window is always queryable.
- Add a guard in the IC function: if `end_date` is within the past 90 days, log a warning that recent IC scores may influence future selection decisions.

**Warning signs:**
- IC computed on `SELECT * FROM cmc_features` without a date cutoff
- Feature selection step that does not repeat IC computation inside each CV fold

**Phase:** IC evaluation phase. Write the IC function to accept explicit `train_start`, `train_end` bounds as required parameters, not optionals.

---

### Moderate: Pearson IC vs Spearman IC — Crypto Returns Have Fat Tails, Pearson IC Is Misleading

**What goes wrong:** The existing `feature_target_correlations` in `feature_eval.py` uses `pd.Series.corr()`, which computes **Pearson** correlation by default. Crypto return distributions have documented fat tails (kurtosis >> 3) and occasional extreme outliers (BTC -40% in a day during 2022). Pearson IC is dominated by a handful of extreme return observations, causing it to misrank features — a feature that correctly predicts direction 60% of the time but with moderate magnitude may score below a feature that happened to be nonzero on the three days with the largest return observations.

**Prevention:**
- Default IC computation to Spearman rank correlation: `pd.Series.corr(other, method='spearman')`.
- Report both Pearson and Spearman IC in the output, but make Spearman the primary sort key.
- Add a note in docstrings: "Pearson IC is provided for reference only. Use Spearman IC for feature ranking in crypto."

**Warning signs:**
- IC function that uses `corr()` without `method='spearman'`
- Top-ranked features by IC change significantly when outlier return days are removed from the dataset

**Phase:** IC evaluation phase. Default to Spearman from the start; retrofitting is painful once IC scores are in the database and reports reference them.

---

### Minor: IC Instability Across Asset Universes Is Not the Same as Feature Weakness

**What goes wrong:** IC computed on BTC alone may be 0.08. IC computed on the full 109-TF universe may be 0.02. A developer concludes the feature is weak. In fact, the IC is diluted by small-cap assets where the feature has less predictive power. The feature may be worth keeping for BTC-class assets and irrelevant for others.

**Prevention:**
- Always report IC stratified by asset tier (BTC, large-cap, mid-cap) as separate rows, not an aggregate.
- Report ICIR (IC / std(IC)) over rolling windows, not only point-in-time IC. A feature with IC=0.04 and ICIR=0.8 is more valuable than IC=0.06 with ICIR=0.2.

**Phase:** IC evaluation phase. Design the IC output schema to include `asset_id`, `tf`, `window_start`, `window_end` as dimensions from the start.

---

## 3. Purged K-Fold Cross-Validation with Embargo

### Critical: Label Overlap Is the Rule, Not the Exception, for Multi-Bar Features

**What goes wrong:** The existing returns tables compute `ret_arith` over multiple periods (e.g., `ret_30` spans 30 bars). If a 30-bar return is used as a feature (or a proxy for a label), a test fold that begins at bar T will have training samples from T-30 to T-1 whose labels (which span to T-1, T-2, ...) partially overlap with the feature construction window of the first test bar at T. Standard K-Fold does not remove these training samples, leading to data leakage.

This is exactly the problem that purging was designed to solve, but it only works if the `t1` (label end) timestamps are passed to the purge function. The existing `splitters.py` works on date ranges, not event (start, end) pairs. It has no concept of label duration.

**Consequences:** Cross-validation folds that look purged but are not. Reported CV accuracy is optimistic. Model trained on these folds will underperform out-of-sample, and the cause will not be obvious.

**Prevention:**
- For any feature that uses a return computed over N bars, the purge function must receive a `pd.Series` indexed by `t0` (feature observation time) with values `t1 = t0 + N * bar_duration`. This is the Lopez de Prado contract for `PurgedKFold`.
- The `splitters.py` `Split` dataclass works on calendar windows only. Do not extend it for purged CV. Build a separate `PurgedKFoldSplitter` class that accepts `t1_series`.
- For crypto 1D bars with a 30-bar return label: the embargo must be at least 30 bars long (not 5% of observations by default — compute it in bar count, not percentage).

**Warning signs:**
- `PurgedKFold` implementation that does not require a `t1_series` parameter
- Any purged CV test that uses a 5% embargo on a 30-bar label (5% of 252 bars = 12.6 bars, less than the 30-bar label duration — insufficient)
- CV using `splitters.py` `Split` objects with multi-bar labels

**Phase:** Purged CV phase. Write the `t1_series` construction logic first, before implementing the splitter.

---

### Critical: The mlfinlab PurgedKFold Has a Documented Bug Where Training Events Overlap Test Events

**What goes wrong:** If using the `mlfinlab` library's `PurgedKFold`, there is a documented GitHub issue (mlfinlab issue #295) where training events whose end timestamps fall within the test period are NOT purged. The root cause is that the test window is defined from the end time of the first test event to the end time of the last test event, rather than from the start time of the first test event. This means a training event that starts before the test fold and ends during it remains in the training set.

The consequence: even when using a dedicated purged CV library, data leakage may persist.

**Prevention:**
- If implementing PurgedKFold from scratch (recommended over library dependency), define the test exclusion window as `(t0_first_test_event, t1_last_test_event)` and purge all training events where `t1_train >= t0_first_test_event`.
- Add a post-construction validation: for each fold, assert that no training event's `t1` falls within `[t0_test_start, t1_test_end]`.
- Do not rely on mlfinlab PurgedKFold without patching this known bug first.

**Warning signs:**
- Using `from mlfinlab.cross_validation import PurgedKFold` without a local patch or version check
- Purged CV producing CV accuracy nearly identical to standard K-Fold (suggests purging is not actually happening)

**Phase:** Purged CV phase. If implementing from scratch, add the post-construction fold validation as a required assertion.

---

### Moderate: Embargo Size Must Be Computed in Bar Counts, Not Percentage of Observations

**What goes wrong:** The Lopez de Prado default embargo is often cited as `pct_embargo=0.01` (1% of observations). On a 1D crypto dataset with 2,000 bars, 1% = 20 bars. For a 30-bar label, 20-bar embargo is still insufficient — test-adjacent training samples within 10 bars of the test fold may still use partially overlapping features.

When operating across 109 timeframes (1D, 3D, 7D, 30D, etc.), the required embargo in bar count varies dramatically by timeframe. A 1-bar embargo on a 30D timeframe covers 30 calendar days, which may be appropriate; a 1-bar embargo on a 1D timeframe covers 1 day, which is almost certainly insufficient.

**Prevention:**
- Compute embargo as `ceil(label_bars / 2)` at minimum for any label that spans multiple bars.
- Parameterize embargo by `(label_duration_bars, tf_days)` rather than as a single `pct_embargo` float.
- For the 1D timeframe with a 30-bar return label: minimum embargo = 30 bars.

**Phase:** Purged CV phase. Document the embargo-by-timeframe formula before writing any CV loop.

---

## 4. Probabilistic Sharpe Ratio (Full Lopez de Prado Implementation)

### Critical: The Existing `psr_placeholder` in `metrics.py` Maps Sharpe to (0,1) via Logistic Sigmoid — This Is Mathematically Unrelated to PSR

**What goes wrong:** The existing `psr_placeholder()` function in `backtests/metrics.py` line 50 returns `1 / (1 + exp(-sharpe))`, which is a logistic sigmoid. This is NOT the Probabilistic Sharpe Ratio. PSR is the probability that the true Sharpe ratio exceeds a benchmark SR*, computed using all four statistical moments (mean, standard deviation, skewness, kurtosis) and the `scipy.stats.norm.cdf()` CDF.

The placeholder is stored as `"psr"` in `cmc_backtest_metrics` table rows. When the real PSR is implemented in v0.9.0, the column will contain both placeholder and real values, making historical comparisons invalid.

**Consequences:** Any downstream report or dashboard that queries `psr` from `cmc_backtest_metrics` will mix placeholder values with real PSR values. A strategy that looked good under the placeholder (high Sharpe = high sigmoid = high "PSR") may look bad under real PSR (negative skewness reduces PSR significantly), or vice versa.

**Prevention:**
- Implement real PSR using scipy (already installed, version 1.17.0): `scipy.stats.norm.cdf(psr_statistic)` where:
  ```python
  from scipy import stats
  import numpy as np

  def psr(returns: pd.Series, sr_benchmark: float = 0.0, freq_per_year: int = 365) -> float:
      n = len(returns)
      if n < 30:
          return float('nan')  # insufficient data
      sr = sharpe(returns, freq_per_year=freq_per_year)
      sk = float(stats.skew(returns))
      ku = float(stats.kurtosis(returns, fisher=True))  # excess kurtosis
      se = np.sqrt((1 + 0.5 * sr**2 - sk * sr + (ku / 4) * sr**2) / (n - 1))
      return float(stats.norm.cdf((sr - sr_benchmark) / se))
  ```
- Before implementing, **add an Alembic migration** that renames `psr` to `psr_legacy` in `cmc_backtest_metrics` for all rows where `run_date < [migration date]`, so historical placeholder values are not mixed with real PSR values.
- Add a minimum sample guard: PSR is undefined (return `NaN`) when `n < 30`. Log a warning when PSR is computed on fewer than 90 observations.

**Warning signs:**
- Any code that imports `psr_placeholder` from `backtests.metrics` rather than renaming it to `psr_legacy` before release
- Dashboard that displays `psr` column without filtering on `run_date >= [migration date]`
- PSR values in `cmc_backtest_metrics` that are between 0.5 and 0.95 for strategies with Sharpe between 1 and 2 (these are the sigmoid range, not real PSR)

**Phase:** PSR implementation phase. The Alembic migration renaming the placeholder column must be the first step, before any PSR computation code is written.

---

### Moderate: Kurtosis Estimation Requires Long Return Histories — Crypto Has Insufficient Data for Short TFs

**What goes wrong:** PSR uses excess kurtosis `gamma_4 - 3`. Kurtosis estimation requires large samples; with fewer than 100 observations, kurtosis estimates have very high variance (standard error of ~`sqrt(24/n)` for kurtosis). For the 30D timeframe with a 1-year history, there are approximately 12 bars — kurtosis estimate is essentially noise.

**Consequences:** PSR values for short-history or high-TF strategies are numerically meaningless but appear precise (PSR=0.73 sounds authoritative even when computed on 12 observations).

**Prevention:**
- Return `NaN` for PSR when `n < 30`. Log a warning at `n < 100`.
- Report PSR with a confidence interval: `psr_lower = norm.cdf((sr - 2*se - sr_benchmark) / se_of_se)` is an approximation.
- In the dashboard, display PSR with a visual indicator of sample size reliability (green ≥ 252 bars, yellow 90-252, red < 90).

**Phase:** PSR implementation. Build the sample guard into the function signature, not as an afterthought.

---

### Minor: PSR Is Not Annualized — Comparing Strategies with Different Frequencies Requires a Benchmark SR Adjustment

**What goes wrong:** PSR is computed at the native frequency of the returns (daily, weekly, etc.). A 1D strategy with PSR=0.80 and a 7D strategy with PSR=0.80 are NOT equally strong. The benchmark SR* must be rescaled by sqrt(freq_ratio) before comparison.

**Prevention:**
- Store `sr_benchmark` and `freq_per_year` alongside every PSR value in the database.
- Document clearly: PSR is not directly comparable across timeframes without benchmark adjustment.

**Phase:** PSR implementation. Schema design must include `sr_benchmark` and `freq_per_year` as stored columns.

---

## 5. Feature Experimentation Framework

### Critical: Feature Registry Without Lifecycle Tracking Leads to "Zombie Features" in Production Compute

**What goes wrong:** A feature is added to the registry in `experimental` status and computed for 30 days. Research shows IC is poor. The feature is "abandoned" but not explicitly deprecated in the registry. The daily refresh continues to compute and store it, consuming compute and storage. Over 6 months, 5-10 zombie features accumulate. Storage and refresh time grow without anyone noticing because the registry has no `deprecated_at` or `retired_at` field.

**Prevention:**
- The feature registry schema must include `status` (experimental | active | deprecated | retired), `created_at`, `deprecated_at`, and `retire_after_date` fields from day one.
- The daily refresh pipeline must filter to only `status IN ('experimental', 'active')` features.
- Add a weekly automated check: any `experimental` feature with `created_at < NOW() - INTERVAL '60 days'` and IC not logged generates a Slack/Telegram alert.

**Warning signs:**
- Feature registry schema without a `status` column
- Daily refresh that iterates over all features without a status filter
- Storage for `cmc_features` or adaptive MA tables grows faster than the bar count would explain

**Phase:** Feature experimentation framework phase. Design the lifecycle state machine before writing any registry code.

---

### Critical: IC-Based Feature Promotion Is a Form of Multiple Comparisons — Adjustment Required

**What goes wrong:** 50 experimental features are evaluated for IC. 5 pass the IC threshold of 0.05. Those 5 are promoted to `active`. But with 50 simultaneous tests, expecting 2-3 to clear a 0.05 threshold by chance alone (false discovery rate at p=0.05, 50 tests = 2.5 expected false positives). The promoted features may be pure noise.

**Why it matters:** This system uses promoted features in signal generators and backtests. A noise feature that passes IC promotion gets wired into a live strategy.

**Consequences:** Live strategies perform worse than backtested. Root cause is difficult to diagnose because IC evaluation looked rigorous.

**Prevention:**
- Apply Benjamini-Hochberg correction when evaluating multiple features simultaneously. `scipy.stats.false_discovery_control()` is available in scipy 1.17.0.
- Require features to pass IC evaluation on a held-out period (not the period used to compute IC) before promotion.
- Document the multiple-comparisons adjustment as a requirement in the feature registry design, not as an optional future enhancement.

**Warning signs:**
- IC evaluation that produces individual p-values without a family-wise correction
- All 50 experimental features evaluated simultaneously and ranked by raw IC

**Phase:** Feature experimentation framework. The promotion logic must include Benjamini-Hochberg correction before being used.

---

### Moderate: Feature Computation Must Be Time-Consistent — Using Different Lookback Windows in Different Runs Silently Corrupts the Registry

**What goes wrong:** A developer computes a 30-bar rolling volatility feature with `min_periods=1` to get values on early dates. Two weeks later, the refresher is re-run with `min_periods=30` to fix a data quality issue. The two sets of rows now disagree for the early dates. The upsert pattern (ON CONFLICT DO UPDATE) silently overwrites the early rows with `NaN` for dates that previously had values.

**Prevention:**
- Feature computation parameters (`lookback_bars`, `min_periods`, `normalization_window`) must be stored as part of the feature registry record and locked at promotion time.
- The refresher must validate that computation parameters match the registry record before writing. Raise an error if they differ.
- Add a data quality check: after each feature refresh, assert `null_count < expected_null_threshold`.

**Phase:** Feature experimentation framework. Lock parameters at first write, not at promotion.

---

## 6. Streamlit Dashboard

### Critical: `st.cache_resource` for SQLAlchemy Engine Is Thread-Safe but Connection Objects Are Not — The Existing `NullPool` Pattern Must Be Preserved

**What goes wrong:** The existing production code uses `NullPool` to avoid connection pooling issues in multiprocessing (documented in MEMORY.md). Streamlit's recommended pattern for database connections is `@st.cache_resource` on a `create_engine()` call. If the Streamlit engine uses the default pool (QueuePool), it will conflict with the multiprocessing workers that use `NullPool` if they share the same PostgreSQL session limit.

More specifically: `@st.cache_resource` caches the engine globally across all Streamlit user sessions. If two users trigger a heavy query simultaneously, they share the same engine and compete for connections. On a development machine with a low `max_connections` PostgreSQL setting, this causes `psycopg2.OperationalError: connection refused` errors.

**Prevention:**
- Use `NullPool` for the Streamlit engine, consistent with the existing codebase pattern:
  ```python
  @st.cache_resource
  def get_db_engine():
      return create_engine(db_url, poolclass=NullPool)
  ```
- Add the Streamlit `validate` parameter to detect stale connections: a NullPool creates and closes connections per query, so this is less critical but still good practice.
- Document in the dashboard's README: "This dashboard uses NullPool. Each widget interaction creates a new database connection. Avoid running the dashboard simultaneously with a full refresh job."

**Warning signs:**
- Dashboard engine using `create_engine()` with default QueuePool
- Dashboard queries hanging when run during a `run_daily_refresh --all` execution

**Phase:** Streamlit dashboard phase. Establish the NullPool engine pattern in the first PR.

---

### Critical: Streamlit Re-runs the Entire Script on Every Widget Interaction — Heavy Queries Must Be Wrapped in `st.cache_data`

**What goes wrong:** Streamlit's execution model re-runs the entire Python script every time a user interacts with a widget (changes a filter, moves a slider). A dashboard that runs `SELECT * FROM cmc_features WHERE tf='1D'` (potentially millions of rows) on every re-run will hammer the database and feel non-interactive.

The trap is that this works fine during development with small datasets but becomes unusable in production once `cmc_features` has 2M+ rows at tf='1D'.

**Prevention:**
- Wrap every database query in `@st.cache_data(ttl=300)` (5-minute TTL for research dashboards, longer for pipeline monitor pages).
- For the IC scores page, pre-aggregate IC by asset and timeframe in the database (a materialized view or an `ic_scores` table) so the dashboard never computes IC on raw features.
- For equity curve plots, store pre-computed equity curves in `cmc_backtest_runs` (already exists) and query that rather than recomputing from trades.
- Size validation: any query that might return >100K rows must be paginated or pre-aggregated before being passed to `st.cache_data`.

**Warning signs:**
- Dashboard page that calls `pd.read_sql()` without a limit clause
- Widget interaction that takes >3 seconds (user tolerance threshold)
- Database CPU spikes visible every time a filter is changed

**Phase:** Streamlit dashboard phase. Design the database-side aggregation tables before writing the dashboard UI.

---

### Moderate: Streamlit on Windows with Watchdog May Produce Spurious File-Watch Errors That Restart the App

**What goes wrong:** Streamlit 1.44.0 uses `watchdog` for file-change detection to enable hot-reload. On Windows, `watchdog` uses `ReadDirectoryChangesW`. In environments with large project directories (this project has 408+ source files plus cache directories), the watcher can exceed the Windows kernel object handle limit, producing spurious restarts and occasional `WinError` exceptions in the Streamlit log.

More practically: Streamlit's file watcher monitors the entire Python path. With the existing `src/ta_lab2` package layout plus `__pycache__` directories, the watcher may trigger on compiled `.pyc` files after any import, causing the dashboard to reload unexpectedly.

**Prevention:**
- Add a `.streamlit/config.toml` to the repository root:
  ```toml
  [server]
  fileWatcherType = "poll"

  [client]
  showErrorDetails = true
  ```
  The `"poll"` watcher does not use `ReadDirectoryChangesW` and avoids the kernel handle limit issue, at the cost of 2-second delay between file change and reload.
- Alternatively, for a research-only dashboard that does not need hot-reload: `streamlit run dashboard.py --server.fileWatcherType none`.
- Add `__pycache__` and `*.pyc` patterns to `.streamlit/config.toml`'s `folderWatchBlacklist`.

**Warning signs:**
- Streamlit console shows repeated `Watchdog` warnings on startup
- Dashboard reloads without any user interaction
- `streamlit run` command produces file-watcher errors before the first widget is rendered

**Phase:** Streamlit dashboard phase. Create the `.streamlit/config.toml` in the first commit.

---

### Moderate: Dashboard and Jupyter Notebooks Will Import from `ta_lab2` But Are Not in the `src/` Layout — Import Path Must Be Configured Explicitly

**What goes wrong:** The project uses a `src/` layout (`pyproject.toml`: `where = ["src"]`). When Jupyter or Streamlit is run from the project root, `import ta_lab2` will fail with `ModuleNotFoundError` unless the package is installed (`pip install -e .`) or `PYTHONPATH=src` is set.

A developer who gets it working with `pip install -e .` locally will assume it always works. A new environment (staging, another developer's machine) that clones the repo and runs `jupyter notebook` without installing will get a confusing import error.

**Prevention:**
- Add a check to the notebook preamble:
  ```python
  import sys
  if 'src' not in sys.path:
      sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
  import ta_lab2  # verify import works
  ```
- Or enforce `pip install -e .[dev]` in the project setup guide.
- Add a `notebooks/` directory with an `__init__.py` that performs the `sys.path` check, so all notebooks auto-correct the import path.
- For Streamlit: ensure the `Makefile` or run instructions include `pip install -e .` before `streamlit run`.

**Warning signs:**
- A notebook that has `sys.path.append('../src')` (relative path will break depending on where Jupyter is launched from)
- A notebook that imports `ta_lab2` without any `sys.path` adjustment and assumes global install

**Phase:** Streamlit and notebook phase. Establish the import pattern in the first notebook template.

---

## 7. Jupyter Notebooks

### Critical: Hidden Cell State Makes Notebooks Non-Reproducible — "Restart and Run All" Failures Discovered Late

**What goes wrong:** A Jupyter notebook for an IC analysis workflow is developed interactively. Cells are run in non-sequential order. Variables from earlier exploratory runs persist in kernel memory. The notebook "works" when the developer runs it cell by cell but fails with a `NameError` or produces different results when run fresh with "Restart and Run All."

In a research platform, a notebook that cannot be run reproducibly is a liability: results cannot be validated by another team member or a future AI session.

**Prevention:**
- Establish a project rule: every notebook committed to the repository must pass "Restart and Run All" without error before being committed.
- Add a CI job that runs notebooks using `nbconvert --execute` on a subset of example notebooks:
  ```yaml
  - name: Execute notebooks
    run: jupyter nbconvert --to notebook --execute notebooks/examples/*.ipynb --ExecutePreprocessor.timeout=300
  ```
- Use `# %%` cell markers (percent scripts) instead of `.ipynb` format for any notebook that grows beyond 200 lines — this makes cell ordering explicit and the file is diff-able.

**Warning signs:**
- A notebook committed that has output cells from a non-sequential execution order (visible from cell execution count indicators: `[3]`, `[1]`, `[5]` is a red flag)
- No CI job that executes notebooks
- Any notebook that uses `del df` or re-defines variables mid-way through (indicator of out-of-order execution during development)

**Phase:** Notebook phase. The "Restart and Run All" rule must be stated in `CONTRIBUTING.md` before any notebook is committed.

---

### Moderate: Notebooks and Source Code Will Diverge If Notebooks Import Functions That Are Then Refactored

**What goes wrong:** A notebook is written that calls `from ta_lab2.analysis.feature_eval import feature_target_correlations`. Later, `feature_target_correlations` is refactored to accept a different signature (e.g., `train_start`, `train_end` are added as required parameters to fix the IC leakage pitfall above). The notebook silently passes no `train_start`/`train_end`, using the old defaults. The notebook continues to "work" but produces leaked IC values.

**Prevention:**
- Treat notebooks as integration tests for the public API. When a function signature changes, run all notebooks in CI to catch broken calls.
- Pin the notebook to a stable public API surface. Do not call private functions (prefixed `_`) from notebooks.
- Add a `notebooks/` section to the module changelog.

**Phase:** Notebook phase. The CI notebook execution job catches this automatically if implemented.

---

## 8. Cross-Cutting Integration Pitfalls

### Critical: `pandas 2.3.3` + `numba 0.64.0` + `numpy 2.4.1` Environment Is Fragile — Any Dependency Upgrade Can Break vectorbt 0.28.1

**What goes wrong:** The current environment has a precarious version stack:
- `numpy 2.4.1` (2.x series)
- `numba 0.64.0` (this is a very recent numba version — earlier 0.6x versions required numpy ≤ 2.2)
- `vectorbt 0.28.1` (released before numpy 2.x existed)

The fact that `import vectorbt` succeeds today does not guarantee it continues to work after any package upgrade. `pip install --upgrade streamlit` or `pip install scipy --upgrade` may trigger numpy version resolution that breaks numba or vectorbt. This environment has zero pinning on `numpy`, `numba`, or `pandas` in `pyproject.toml` (all are unpinned).

**Adding new packages for v0.9.0** (sklearn extensions, mlfinlab, or any library that declares a numpy requirement) will trigger pip re-resolution and may upgrade numpy past a version numba 0.64.0 supports.

**Prevention:**
- Before adding any new package, capture the exact current working environment:
  ```bash
  pip freeze > requirements-lock-v0.9.0-baseline.txt
  ```
- Add explicit pins in `pyproject.toml` for the fragile stack:
  ```toml
  dependencies = [
      "numpy>=2.4,<2.5",   # locked to current working version
      "numba>=0.64,<0.65",  # locked to current working version
  ]
  ```
- After any `pip install` for new v0.9.0 dependencies, immediately run:
  ```bash
  python -c "import vectorbt; import numba; print('ok')"
  ```
- If a new package forces numpy above 2.4.x, test vectorbt backtests against the baseline metrics before proceeding.

**Warning signs:**
- `pip install [new-package]` output shows `numpy` being upgraded
- `import vectorbt` produces a `numba` or `numpy` compatibility error after any package installation
- CI passes but local backtest metrics differ from baseline (numpy numerical change)

**Phase:** Any phase that adds a new Python dependency. Run the compatibility check as the first step.

---

### Moderate: Windows Development + Linux CI Will Surface Path and Encoding Issues in Any New Script That Reads Files

**What goes wrong:** The existing codebase already has two documented Windows-specific issues (MEMORY.md):
1. `cp1252` encoding breaks when reading UTF-8 SQL files with box-drawing characters
2. `series.values` on tz-aware DatetimeSeries returns tz-naive numpy.datetime64

New v0.9.0 scripts that read SQL DDL files, config files, or CSV data will encounter these issues if they copy patterns from the pre-fix codebase without checking the MEMORY.md warnings.

Streamlit's hot-reload on Windows is an additional surface (see Pitfall 6.2 above).

**Prevention:**
- Any `open()` call in new scripts: always use `encoding='utf-8'`.
- Any `series.values` on a datetime column: always use `.tolist()` or `.tz_localize('UTC')` on DatetimeIndex, as documented.
- Add a CI job that explicitly runs on the Linux runner (already exists) and fails fast on any UnicodeDecodeError.
- New scripts must include the encoding pattern in their file-read boilerplate, not as an afterthought.

**Warning signs:**
- A new script that opens a `.sql` or `.md` file without `encoding='utf-8'`
- `UnicodeDecodeError: 'cp1252' codec can't decode byte` in CI on a script that worked locally on Windows

**Phase:** Every phase. This is a recurring risk. Review any new `open()` call before merging.

---

### Moderate: The `analysis/` Package Is Not in the importlinter Layer Contract — New IC/PSR Code Added There May Violate the Layer Hierarchy

**What goes wrong:** `pyproject.toml` defines the layer contract as `scripts > pipelines/backtests > signals/regimes/analysis > features/tools`. The `analysis/` package is at the same layer as `signals` and `regimes`. If IC evaluation code in `analysis/` imports from `signals/` (e.g., to pull signal returns for IC computation), it violates the contract because `signals` is at the same layer, not a lower layer.

More critically: if feature experimentation code in `analysis/` imports from `scripts/features/` to call the refresher directly, this crosses the layer boundary (scripts is above analysis).

**Consequences:** `import-linter` CI job fails. More importantly, circular import risks increase significantly as new cross-layer code is added.

**Prevention:**
- Before writing any IC/PSR/CV code in `analysis/`, draw the import graph:
  - IC needs: feature data (from DB, not from features layer), returns data (from DB)
  - PSR needs: backtest returns (from DB, not from backtests layer)
  - Both should query the DB directly via SQLAlchemy, not import from sibling layers
- Add any new module that bridges layers to `analysis/` with explicit `# importlinter: allow` comments, and justify the exception in the PR.
- Run `lint-imports` locally before any PR that adds imports across layer boundaries.

**Warning signs:**
- `from ta_lab2.signals import ...` inside any file in `ta_lab2.analysis`
- `from ta_lab2.scripts import ...` inside any file in `ta_lab2.analysis`
- `lint-imports` CI job failure on any v0.9.0 PR

**Phase:** All phases. Run `lint-imports` before every PR in v0.9.0.

---

## Phase-Specific Warnings Summary

| Phase Topic | Likely Pitfall | Mitigation |
|---|---|---|
| Adaptive MA table design | Sharing `cmc_ema_multi_tf` PK namespace causes silent signal corruption | Create separate `cmc_adaptive_ma_*` table family with `ma_type` discriminator |
| KAMA/DEMA/TEMA computation | Incremental refresh without warm-up produces wrong values | Load `max(period) * 10` bars before first persisted date |
| HMA implementation | HMA uses WMA, not EWM — `_ema()` helper cannot be reused | Implement `_wma()` separately; unit test against reference values |
| IC evaluation | IC over full history leaks future information into feature selection | IC must be recomputed inside each CV fold; use explicit `train_start`, `train_end` |
| IC metric choice | Pearson IC misleads on fat-tailed crypto returns | Default to Spearman rank correlation |
| Purged K-fold design | Multi-bar labels require `t1_series`, not date ranges | Build `PurgedKFoldSplitter` with `t1_series` input; never reuse `splitters.py` Split |
| Purged K-fold library | mlfinlab PurgedKFold has documented overlap bug (issue #295) | Implement from scratch with post-construction fold validation assertion |
| Embargo sizing | Percentage embargo insufficient for multi-bar labels | Compute embargo in bar counts: `ceil(label_bars / 2)` minimum |
| PSR implementation | Existing `psr_placeholder` is a sigmoid, not PSR — mixed in same DB column | Rename to `psr_legacy` via Alembic migration before implementing real PSR |
| PSR on short histories | Kurtosis estimation requires 100+ samples; short TFs have 12-20 bars | Return `NaN` when `n < 30`; warn when `n < 100` |
| Feature registry | Features without lifecycle tracking accumulate as zombie compute | Registry schema must include `status`, `deprecated_at` from day one |
| Feature promotion | IC-based promotion without multiple comparisons correction promotes noise | Require Benjamini-Hochberg correction for multi-feature evaluation |
| Streamlit DB connections | Default QueuePool conflicts with existing NullPool pattern | Use `NullPool` for Streamlit engine consistently |
| Streamlit re-runs | Every widget interaction re-runs full script, hammering DB | Wrap all DB queries in `@st.cache_data(ttl=300)` |
| Streamlit on Windows | Watchdog file watcher produces spurious restarts | Add `.streamlit/config.toml` with `fileWatcherType = "poll"` |
| Notebook reproducibility | Hidden cell state makes notebooks non-reproducible | CI must run `nbconvert --execute` on committed notebooks |
| Dependency upgrades | numpy/numba/vectorbt triangle breaks silently on new package install | Pin `numpy>=2.4,<2.5`, `numba>=0.64,<0.65`; test vectorbt after any install |
| Deprecated fillna | `fillna(method='ffill')` in `feature_eval.py` and `performance.py` will error in pandas 3.0 | Fix before adding any new IC/feature eval code |
| Import layer violation | IC/PSR/CV code that imports from sibling layers breaks importlinter | Query DB directly; run `lint-imports` before every PR |
| Windows encoding | Any new script reading `.sql` or config files without `encoding='utf-8'` | Enforce `encoding='utf-8'` in all `open()` calls |

---

## Sources

- [StockCharts: Kaufman's Adaptive Moving Average (KAMA) — warm-up requirements](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average-kama) — MEDIUM confidence (official reference documentation)
- [Lopez de Prado: Advances in Financial Machine Learning — purged CV, embargo, PSR](https://philpapers.org/rec/LPEAIF) — HIGH confidence (primary source)
- [mlfinlab issue #295: PurgedKFold training events overlap test events](https://github.com/hudson-and-thames/mlfinlab/issues/295) — HIGH confidence (bug report with reproduction case)
- [Quantdare: Probabilistic Sharpe Ratio — four-moment formula](https://quantdare.com/probabilistic-sharpe-ratio/) — HIGH confidence (formula verified against Lopez de Prado paper)
- [Streamlit docs: st.cache_resource — thread safety warnings](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_resource) — HIGH confidence (official docs)
- [Streamlit docs: Connecting to data — SQLAlchemy integration](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data) — HIGH confidence (official docs)
- [Aalto Scientific Computing: Jupyter notebook pitfalls](https://scicomp.aalto.fi/scicomp/jupyter-pitfalls/) — MEDIUM confidence (academic computing guide)
- [pandas 2.2 changelog: fillna method deprecation](https://pandas.pydata.org/docs/whatsnew/v2.2.0.html) — HIGH confidence (official changelog)
- [numba GitHub issue #10105: NumPy 2.3 support](https://github.com/numba/numba/issues/10105) — HIGH confidence (numba issue tracker)
- [PyQuant News: Information coefficient common mistakes](https://www.pyquantnews.com/the-pyquant-newsletter/information-coefficient-measure-your-alpha) — MEDIUM confidence (practitioner source)
- [ScienceDirect: Backtest overfitting comparison of out-of-sample testing methods](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110) — HIGH confidence (peer-reviewed 2024 paper)
- [dotdata: Preventing data leakage in feature engineering](https://dotdata.com/blog/preventing-data-leakage-in-feature-engineering-strategies-and-solutions/) — MEDIUM confidence (engineering blog, consistent with academic sources)
- Codebase direct inspection: `backtests/metrics.py` (psr_placeholder), `analysis/feature_eval.py` (Pearson IC, deprecated fillna), `backtests/splitters.py` (no t1_series), `pyproject.toml` (unpinned numpy/numba), `features/indicators.py` (ewm-based EMA only), MEMORY.md (NullPool, tz-aware pitfalls, Windows encoding) — HIGH confidence (observed directly)
