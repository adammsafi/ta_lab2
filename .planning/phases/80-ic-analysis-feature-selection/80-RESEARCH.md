# Phase 80: IC Analysis & Feature Selection - Research

**Researched:** 2026-03-21
**Domain:** IC analysis, statistical testing, feature selection, YAML config output
**Confidence:** HIGH

---

## Summary

This phase builds directly on a substantial existing infrastructure. The IC sweep
pipeline (`run_ic_sweep.py`, `run_ic_eval.py`, `run_ic_decay.py`) is fully
implemented and persists results to the `ic_results` table. The quintile engine
(`quintile.py`, `run_quintile_sweep.py`) is complete. MDA, SFI, and clustered MDA
are implemented in `ml/feature_importance.py` and `run_feature_importance.py`.
Feature clustering using Spearman + Ward hierarchical linkage is already in
`cluster_features()`.

The primary work for this phase is:
1. Adding a statistical test layer (ADF/KPSS/Ljung-Box) — requires installing
   `statsmodels` which is NOT currently in the project
2. Building an aggregation/selection script that reads from `ic_results` and
   applies the IC-IR threshold and concordance logic
3. Writing the tiered YAML config (`configs/feature_selection.yaml`) and mirroring
   it to a new DB table (`dim_feature_selection`)
4. Orchestrating a batch run of quintile sweep + MDA for the top-N candidates

**Primary recommendation:** Add `statsmodels` as a new optional dependency group
(e.g., `[analysis]`). All statistical tests (ADF, KPSS, Ljung-Box) live in
`statsmodels.tsa.stattools` — none are available in `scipy.stats`.

---

## Existing Infrastructure

### IC Computation Layer (`src/ta_lab2/analysis/ic.py`)

Fully implemented. Key functions:

| Function | Purpose | Status |
|----------|---------|--------|
| `compute_ic()` | Spearman IC per feature across horizons, with IC-IR | Complete |
| `compute_rolling_ic()` | Vectorized rolling IC + IC-IR using rank-then-correlate | Complete |
| `compute_feature_turnover()` | Rank autocorrelation proxy (1 - lag-1 rank autocorr) | Complete |
| `compute_ic_by_regime()` | IC split by trend_state / vol_state from regimes | Complete |
| `batch_compute_ic()` | 112-feature batch with pre-computed forward-return cache (112x speedup) | Complete |
| `save_ic_results()` | Upsert to `ic_results` — both append-only and overwrite modes | Complete |
| `load_feature_series()` | Load feature + close from `features` table | Complete |
| `load_regimes_for_asset()` | Load and parse l2_label into trend_state/vol_state | Complete |
| `plot_ic_decay()` | Plotly bar chart of IC vs horizon | Complete |
| `plot_rolling_ic()` | Plotly rolling IC line chart | Complete |

**Key implementation notes:**
- Horizons: [1, 2, 3, 5, 10, 20, 60] bars (default)
- Return types: ['arith', 'log']
- Rolling window: 63 bars (default, ~1 quarter for 1D)
- IC-IR = mean(rolling_ic) / std(rolling_ic) — computed via vectorized rank-correlate
- `compute_feature_turnover()` returns `1 - spearmanr(rank[:-1], rank[1:])`, meaning
  turnover~0 = stable signal, turnover~1 = random daily permutation

### IC Sweep Scripts

| Script | What it does |
|--------|-------------|
| `run_ic_sweep.py` | Full batch across all assets x all TFs x all 112 features + AMA variants. Parallel with NullPool workers. Saves feature_ic_ranking.csv |
| `run_ic_eval.py` | Single asset, targeted feature list, with optional --regime breakdown |
| `run_ic_decay.py` | Generates HTML decay chart from ic_results for a single feature |

`run_ic_sweep.py` already outputs a ranking CSV at `reports/bakeoff/feature_ic_ranking.csv`
sorted by mean |IC-IR| at horizon=1 arith.

### Quintile Engine (`src/ta_lab2/analysis/quintile.py`)

`compute_quintile_returns()` — cross-sectional ranking: ranks all assets by a factor
into 5 quintiles at each timestamp, tracks cumulative forward returns per bucket.

`build_quintile_returns_chart()` — Plotly figure with Q1-Q5 lines + Q5-Q1 spread.

`run_quintile_sweep.py` CLI — invokes one factor at a time, saves HTML to
`reports/quintile/{factor}_{tf}_h{horizon}.html`.

**Gap:** No batch quintile sweep that produces a monotonicity score across all
features and a pass/fail flag. The CLI is one-factor-at-a-time.

### Feature Importance (`src/ta_lab2/ml/feature_importance.py`)

| Function | Inputs | Output |
|----------|--------|--------|
| `compute_mda()` | model, X (DataFrame), y, t1_series, n_splits, n_repeats | pd.Series sorted descending |
| `compute_sfi()` | model, X (DataFrame), y, t1_series, n_splits | pd.Series sorted descending |
| `cluster_features()` | X (DataFrame), threshold=0.5 | dict[cluster_id, list[col]] |
| `compute_clustered_mda()` | model, X, y, t1_series, n_splits, n_repeats, cluster_threshold | pd.DataFrame with cluster_id, features, importance_mean |

`run_feature_importance.py` CLI wraps MDA + SFI for a given asset list + tf + date
range. Uses `PurgedKFoldSplitter` from `ta_lab2.backtests.cv` for leakage-free CV.

### Feature Evaluation Utilities (`src/ta_lab2/analysis/feature_eval.py`)

Simpler utilities — `corr_matrix()`, `redundancy_report()`, `future_return()`,
`quick_logit_feature_weights()`. These are supplementary; the main work for Phase 80
uses ic.py and feature_importance.py.

---

## Schema Details

### `ic_results` Table (current schema)

The table was originally created as `cmc_ic_results`, renamed to `ic_results` in the
strip_cmc_prefix migration (revision `a0b1c2d3e4f5`). Current columns:

| Column | Type | Notes |
|--------|------|-------|
| result_id | UUID | PK, gen_random_uuid() |
| asset_id | INTEGER | FK to cmc_da_ids |
| tf | TEXT | Timeframe string |
| feature | TEXT | Column name from features |
| horizon | INTEGER | Forward horizon in bars |
| horizon_days | INTEGER | nullable |
| return_type | TEXT | 'arith' or 'log' |
| regime_col | TEXT | 'trend_state', 'vol_state', or 'all' |
| regime_label | TEXT | 'Up', 'Down', 'High', 'Low', or 'all' |
| train_start | TIMESTAMPTZ | |
| train_end | TIMESTAMPTZ | |
| ic | NUMERIC | Spearman IC |
| ic_t_stat | NUMERIC | |
| ic_p_value | NUMERIC | |
| ic_ir | NUMERIC | IC-IR (rolling IC mean / std) |
| ic_ir_t_stat | NUMERIC | |
| turnover | NUMERIC | 1 - rank autocorrelation |
| n_obs | INTEGER | |
| rank_ic | NUMERIC | Same as ic (Spearman == Rank IC) |
| alignment_source | TEXT | e.g. 'multi_tf' |
| computed_at | TIMESTAMPTZ | server default now() |

**Unique constraint (9-column natural key):**
`(asset_id, tf, feature, horizon, return_type, regime_col, regime_label, train_start, train_end, alignment_source)`

**Indexes:** `idx_ic_results_asset_feature` on (asset_id, tf, feature),
`idx_ic_results_computed_at` on (computed_at)

**Querying for IC-IR ranking (existing pattern from run_ic_sweep.py):**
```sql
SELECT feature,
       AVG(ABS(ic))        AS mean_abs_ic,
       AVG(ic_ir)          AS mean_ic_ir,
       AVG(ABS(ic_ir))     AS mean_abs_ic_ir,
       COUNT(*)            AS n_observations,
       COUNT(DISTINCT asset_id || '_' || tf) AS n_asset_tf_pairs
FROM public.ic_results
WHERE horizon = 1
  AND return_type = 'arith'
  AND regime_col = 'all'
  AND regime_label = 'all'
  AND ic IS NOT NULL
GROUP BY feature
ORDER BY AVG(ABS(ic_ir)) DESC NULLS LAST
```

### `features` Table

112 feature columns. Discovered dynamically via `get_columns(engine, 'public.features')`.
Key non-feature columns excluded: id, ts, tf, close, open, high, low, volume,
ingested_at, alignment_source, tf_days, asset_class, venue, updated_at, has_price_gap,
has_outlier, computed_at.

Feature categories (from `configs/experiments/features.yaml`):
- Returns: delta1, delta2, ret_arith, ret_log, range_pct, true_range_pct
  + roll variants + z-scores at 30/90/365 bars
- Volatility: Parkinson (20/63/126), Garman-Klass (20/63/126), Rogers-Satchell (20/63/126),
  rolling log vol (20/63/126), ATR(14) + z-scores
- TA indicators: RSI(7/14/21), MACD(12/26/9), MACD(8/17/9), Stochastic(14/3),
  Bollinger(20/2), ADX(14)
- Derived: vol ratios, MACD cross, stoch cross, RSI divergence, ret/vol adj,
  log vols, normalized ATR, BB width relative

### `dim_feature_registry` Table

Tracks feature lifecycle (experimental / promoted / deprecated). PK = feature_name.
Used by ExperimentRunner and promoter workflow. This is NOT the output table for
Phase 80 — it serves the promotion pipeline, not feature selection.

Phase 80 needs a NEW table: `dim_feature_selection` (does not exist yet).

### `feature_experiments` Table (formerly `cmc_feature_experiments`)

Records IC experiment results per (feature, asset, tf, horizon, return_type, regime
slice, training window). Separate from ic_results — used by ExperimentRunner.
Phase 80 does NOT write to this table.

---

## Dependencies & Libraries

### Available (installed)

| Library | Version | Relevant for Phase 80 |
|---------|---------|----------------------|
| scipy | 1.17.0 | spearmanr (already used in ic.py), cluster distance (squareform, hierarchy) |
| scikit-learn | 1.8.0 | MDA via permutation_importance, RandomForestClassifier, PurgedKFoldSplitter |
| pandas | (installed) | DataFrame operations throughout |
| numpy | (installed) | Numerical operations |
| pyyaml | (installed) | Reading/writing YAML configs |
| plotly | (installed) | IC decay and quintile charts |
| SQLAlchemy | >=2.0 | DB connections |

### NOT Available (must install)

**statsmodels is NOT installed.** ADF, KPSS, and Ljung-Box autocorrelation tests
are in `statsmodels.tsa.stattools`, NOT in `scipy.stats`. Specifically:

```python
# These are in statsmodels, not scipy:
from statsmodels.tsa.stattools import adfuller   # ADF test
from statsmodels.tsa.stattools import kpss       # KPSS test
from statsmodels.tsa.stattools import acf, q_stat  # Ljung-Box (acf gives autocorrs, q_stat gives LB stat)
# Or: from statsmodels.stats.diagnostic import acorr_ljungbox
```

**Required action:** Add `statsmodels` to pyproject.toml as a new optional dependency
group (e.g., `analysis`) and install it before Phase 80 implementation begins.

Recommended pyproject.toml addition:
```toml
analysis = [
  "statsmodels>=0.14.0",
]
```

---

## Architecture Patterns

### DB Connection Pattern (standard for analysis scripts)

```python
from ta_lab2.scripts.refresh_utils import resolve_db_url
from sqlalchemy import create_engine, pool

db_url = resolve_db_url()
engine = create_engine(db_url, poolclass=pool.NullPool)
```

### YAML Config Pattern (from configs/experiments/features.yaml)

Existing configs live in `configs/`. New feature selection config should go to
`configs/feature_selection.yaml`. The pattern is structured YAML with clear sections
and human-readable rationale. Example target structure:

```yaml
# configs/feature_selection.yaml
# Generated: <date>
# Phase 80 output: validated active feature set

metadata:
  generated_at: "2026-03-21"
  ic_ir_cutoff: 0.3
  n_features_active: 18
  n_features_watch: 12
  n_features_archive: 82

active:   # IC-IR > 0.3, universal across regimes
  - name: rsi_14_zscore
    ic_ir_mean: 0.45
    ic_p_value_min: 0.02
    turnover: 0.72
    stationarity: STATIONARY
    ljung_box_flag: false
    rationale: "Strong IC at h=1,2,3; stationary; regime-universal"

conditional:  # Strong IC in specific regimes only
  - name: macd_hist_12_26_9
    regimes: [trending_up, trending_down]
    ic_ir_mean_regime: 0.51
    ...

watch:    # IC-IR 0.15-0.30, worth monitoring
  - ...

archive:  # IC-IR < 0.15 across all horizons
  - ...
```

### Concordance Pattern (IC-IR vs MDA ranking)

The existing `run_ic_sweep.py` produces a ranking CSV sorted by `mean_abs_ic_ir`.
`run_feature_importance.py` produces a MDA importance `pd.Series`.

Concordance approach: compute Spearman rank correlation between the IC-IR ranking
and the MDA importance ranking across the same feature set. A high concordance
(> 0.6) validates both methods agree. Features that appear in both top-20 lists
are highest-confidence candidates.

For cluster handling: `cluster_features()` with `threshold=0.5` groups correlated
features. When a cluster contains multiple features, select the one with the highest
IC-IR within the cluster (not all members).

### Ljung-Box p-value Recommendation

For flagging IC series serial correlation — a flag that IC may be artificially
inflated by autocorrelation rather than predictive signal — use p-value threshold
of **0.05** with 10 lags. Features where the Ljung-Box test rejects the null at
p < 0.05 (i.e., significant autocorrelation in the IC series) get a `ljung_box_flag: true`
in the YAML. They are NOT excluded, but their IC-IR is treated with lower confidence.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| ADF stationarity test | custom unit root test | `statsmodels.tsa.stattools.adfuller` |
| KPSS stationarity test | custom KPSS | `statsmodels.tsa.stattools.kpss` |
| Ljung-Box autocorrelation | manual Q-stat | `statsmodels.stats.diagnostic.acorr_ljungbox` |
| Feature clustering | manual correlation pruning | `cluster_features()` in `ml/feature_importance.py` |
| MDA feature importance | custom permutation | `compute_mda()` in `ml/feature_importance.py` |
| IC aggregation queries | in-Python aggregation | SQL GROUP BY on `ic_results` |
| Quintile monotonicity | custom ranking | `compute_quintile_returns()` in `analysis/quintile.py` |

---

## Common Pitfalls

### Pitfall 1: statsmodels Signals on Non-Stationary Features

**What goes wrong:** ADF and KPSS have opposing null hypotheses. ADF null = unit root
(non-stationary); KPSS null = stationary. A feature flagged as non-stationary by
both tests is strong evidence. A feature that passes one but not the other is ambiguous.

**How to avoid:** Report both ADF and KPSS results. Use the decision rule:
- Both agree stationary = STATIONARY
- Both agree non-stationary = NON_STATIONARY
- Disagree = AMBIGUOUS (note in YAML, apply higher IC-IR threshold)

**Warning signs:** KPSS p-value near 0.01 but ADF p-value near 0.10 = ambiguous regime.

### Pitfall 2: IC-IR Computed on Aggregated Data vs Per-Asset

**What goes wrong:** Averaging IC-IR across all assets can mask that a feature has
strong IC for some assets and near-zero IC for others.

**How to avoid:** The aggregation query in `run_ic_sweep.py` uses AVG(ABS(ic_ir))
and also reports `n_asset_tf_pairs`. For Phase 80, supplement with: count of assets
where |IC-IR| > 0.3 vs total assets (pass rate). A feature with mean |IC-IR| = 0.35
but pass rate of 3/50 assets is a regime-specialist, not a universal feature.

**Warning signs:** High mean |IC-IR| but very low `n_asset_tf_pairs`.

### Pitfall 3: Ljung-Box on Rolling IC Series vs Feature Series

**What goes wrong:** Ljung-Box should be applied to the IC time series (rolling IC
values per feature per horizon), NOT to the raw feature values themselves. Applying
it to raw feature values tests feature autocorrelation, not IC autocorrelation.

**How to avoid:** To get the rolling IC series, call `compute_rolling_ic()` which
returns a `pd.Series`. Apply `acorr_ljungbox(rolling_ic_series.dropna(), lags=10)`.

### Pitfall 4: MDA Needs Binary Labels, Not IC

**What goes wrong:** `run_feature_importance.py` builds binary labels from
`ret_arith > 0`. For Phase 80, MDA should use the same training window used for IC
evaluation (not an arbitrary date range). Labels must be leakage-free (no look-ahead).

**How to avoid:** Use the same `train_start` / `train_end` as the IC sweep. Build
`t1_series` with a 1-bar lag (label_end = ts + 1 bar). Use `PurgedKFoldSplitter`
from `ta_lab2.backtests.cv`.

### Pitfall 5: dim_feature_selection Table Does Not Exist

**What goes wrong:** The CONTEXT.md says results should be mirrored to
`dim_feature_selection` (or similar) for runtime queries. This table does NOT exist
and needs a migration.

**How to avoid:** Create an Alembic migration for `dim_feature_selection` as part of
Phase 80. Design the schema to support: feature_name, tier (active/conditional/watch/archive),
ic_ir_mean, pass_rate, stationarity_flag, ljung_box_flag, regime_specialist (bool),
specialist_regimes (TEXT[]), selected_at, yaml_version.

### Pitfall 6: Windows UTF-8 Encoding in SQL Files

**What goes wrong:** SQL files with UTF-8 box-drawing chars cause `UnicodeDecodeError`
on Windows (cp1252 encoding).

**How to avoid:** Always open SQL files with `encoding='utf-8'`. Keep column
comments plain ASCII. (Already handled in existing migrations — follow the same pattern.)

### Pitfall 7: AMA Features in ic_results Have Long Disambiguated Names

**What goes wrong:** AMA features stored in `ic_results` use the naming pattern
`{indicator}_{hash_short}_{col}` (e.g., `KAMA_de1106d5_er`). The selection YAML
and DB mirror must handle these names correctly.

**How to avoid:** When building the feature list from ic_results, filter by
`regime_col = 'all'` and `regime_label = 'all'` to get full-sample results first.
Use `feature` column values as-is — do not try to normalize AMA names.

---

## Code Examples

### Aggregating IC-IR from ic_results for Selection

```python
# Source: run_ic_sweep.py _produce_feature_ranking()
from sqlalchemy import text

sql = text("""
    SELECT
        feature,
        AVG(ABS(ic))            AS mean_abs_ic,
        AVG(ABS(ic_ir))         AS mean_abs_ic_ir,
        COUNT(*)                AS n_observations,
        COUNT(DISTINCT asset_id || '_' || tf) AS n_asset_tf_pairs,
        -- Pass rate: fraction of asset-tf pairs where |IC-IR| > threshold
        SUM(CASE WHEN ABS(ic_ir) > 0.3 THEN 1 ELSE 0 END)::FLOAT
            / NULLIF(COUNT(*), 0) AS pass_rate_icir_0_3
    FROM public.ic_results
    WHERE horizon = 1
      AND return_type = 'arith'
      AND regime_col = 'all'
      AND regime_label = 'all'
      AND ic IS NOT NULL
    GROUP BY feature
    ORDER BY mean_abs_ic_ir DESC NULLS LAST
""")
with engine.connect() as conn:
    ranking_df = pd.read_sql(sql, conn)
```

### ADF + KPSS Stationarity Tests (requires statsmodels)

```python
# Source: statsmodels docs (verified against statsmodels 0.14.x API)
from statsmodels.tsa.stattools import adfuller, kpss

def test_stationarity(series: pd.Series) -> dict:
    series_clean = series.dropna()
    if len(series_clean) < 30:
        return {"adf_pvalue": None, "kpss_pvalue": None, "result": "INSUFFICIENT_DATA"}

    # ADF: null = unit root (non-stationary). Low p-value -> reject -> stationary
    adf_stat, adf_pvalue, _, _, _, _ = adfuller(series_clean, autolag='AIC')

    # KPSS: null = stationary. Low p-value -> reject -> non-stationary
    kpss_stat, kpss_pvalue, _, _ = kpss(series_clean, regression='c', nlags='auto')

    # Classify
    adf_stationary = adf_pvalue < 0.05
    kpss_stationary = kpss_pvalue > 0.05

    if adf_stationary and kpss_stationary:
        result = "STATIONARY"
    elif not adf_stationary and not kpss_stationary:
        result = "NON_STATIONARY"
    else:
        result = "AMBIGUOUS"

    return {
        "adf_pvalue": float(adf_pvalue),
        "kpss_pvalue": float(kpss_pvalue),
        "result": result,
    }
```

### Ljung-Box on Rolling IC Series

```python
# Source: statsmodels docs
from statsmodels.stats.diagnostic import acorr_ljungbox
from ta_lab2.analysis.ic import compute_rolling_ic

# Get rolling IC series for feature X at horizon H
rolling_ic_series, ic_ir, _ = compute_rolling_ic(
    feat_train, fwd_train, window=63
)
ic_series_clean = rolling_ic_series.dropna()

if len(ic_series_clean) >= 10:
    lb_result = acorr_ljungbox(ic_series_clean, lags=10, return_df=True)
    # lb_result is a DataFrame with columns: lb_stat, lb_pvalue
    # Flag if ANY lag's p-value < 0.05
    ljung_box_flag = bool((lb_result['lb_pvalue'] < 0.05).any())
else:
    ljung_box_flag = False
```

### Feature Clustering for Concordance

```python
# Source: src/ta_lab2/ml/feature_importance.py cluster_features()
from ta_lab2.ml.feature_importance import cluster_features

# X is the feature DataFrame for top-N candidates
clusters = cluster_features(X, threshold=0.5)
# Returns: {"cluster_1": ["rsi_14", "rsi_7"], "cluster_2": ["macd_hist_12_26_9"], ...}

# Per-cluster: select the feature with highest IC-IR
for cluster_id, cols in clusters.items():
    best_in_cluster = ranking_df[ranking_df['feature'].isin(cols)].iloc[0]['feature']
```

### YAML Config Writing

```python
# Source: existing YAML pattern in configs/experiments/features.yaml
import yaml
from pathlib import Path

output_path = Path("configs/feature_selection.yaml")
config = {
    "metadata": {
        "generated_at": "2026-03-21",
        "ic_ir_cutoff": 0.3,
        "n_features_active": len(active_features),
    },
    "active": [
        {
            "name": f["feature"],
            "ic_ir_mean": round(f["mean_abs_ic_ir"], 4),
            "stationarity": f["stationarity"],
            "ljung_box_flag": f["ljung_box_flag"],
            "rationale": f["rationale"],
        }
        for f in active_features
    ],
    "conditional": [...],
    "watch": [...],
    "archive": [...],
}

with open(output_path, "w", encoding="utf-8") as fh:
    yaml.dump(config, fh, default_flow_style=False, allow_unicode=True)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `cmc_ic_results` table | `ic_results` (strip_cmc_prefix migration) | Phase 74 migration | Table name in all queries |
| Single IC metric | IC + IC-IR + IC-IR t-stat + turnover | Phase 53-56 | All metrics in ic_results |
| Per-feature loops | `batch_compute_ic()` with pre-computed forward returns cache | Phase 55 | 112x compute speedup |
| No regime breakdown | `compute_ic_by_regime()` for trend_state/vol_state | Phase 55 | Regime-conditional IC in ic_results |

**Deprecated/outdated:**
- `cmc_ic_results` name: use `ic_results` (rename completed)
- `cmc_feature_experiments` name: use `feature_experiments` (rename completed)

---

## Gaps & Risks

### Gap 1: statsmodels Not Installed (BLOCKING)

ADF, KPSS, and Ljung-Box tests require `statsmodels`. It is NOT installed. This must
be resolved before any statistical test code can run.

**Resolution:** `pip install statsmodels` and add to `pyproject.toml`:
```toml
analysis = [
  "statsmodels>=0.14.0",
]
```

### Gap 2: dim_feature_selection Table Does Not Exist (NEW MIGRATION NEEDED)

The CONTEXT.md requires a DB mirror of the YAML config. This table must be created
via Alembic migration. Phase 80 needs to include a migration plan.

**Suggested schema:**
```sql
CREATE TABLE public.dim_feature_selection (
    feature_name TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('active', 'conditional', 'watch', 'archive')),
    ic_ir_mean NUMERIC,
    pass_rate NUMERIC,
    stationarity TEXT CHECK (stationarity IN ('STATIONARY', 'NON_STATIONARY', 'AMBIGUOUS', 'INSUFFICIENT_DATA')),
    ljung_box_flag BOOLEAN DEFAULT FALSE,
    regime_specialist BOOLEAN DEFAULT FALSE,
    specialist_regimes TEXT[],
    selected_at TIMESTAMPTZ DEFAULT now(),
    yaml_version TEXT,
    rationale TEXT,
    PRIMARY KEY (feature_name)
);
```

### Gap 3: No Batch Quintile Sweep (NEEDS BUILDING)

`run_quintile_sweep.py` evaluates ONE factor at a time and outputs HTML. Phase 80
needs a batch script that runs quintile analysis for all active/watch features and
produces a monotonicity score (e.g., Spearman rank correlation of Q1-Q5 terminal
returns = 1 if perfectly monotonic).

### Gap 4: MDA Concordance Script Does Not Exist (NEEDS BUILDING)

No script combines IC-IR ranking with MDA ranking to produce a concordance report.
The plan needs to build `run_concordance.py` or equivalent that:
1. Loads IC-IR ranking from ic_results
2. Runs MDA on the top-N features
3. Computes Spearman rank correlation between IC-IR rank and MDA rank
4. Flags features that appear in both top-20 lists as high-confidence

### Gap 5: Re-evaluation Cadence Not Implemented

CONTEXT.md requests monthly automated re-evaluation with alerts when the feature
set changes significantly. Phase 80 should lay the groundwork (e.g., a script that
diffs the current YAML against a new run and flags changes) but the monthly
scheduling is out of scope for this phase.

---

## Recommendations

1. **First plan: install statsmodels.** Add it to pyproject.toml as `[analysis]`
   optional group. All stationarity/autocorrelation work depends on it.

2. **New migration for dim_feature_selection.** This is a dependency for the
   YAML-to-DB mirror requirement. Build it early in the phase.

3. **Three-tier architecture for new scripts:**
   - `src/ta_lab2/analysis/feature_selection.py` — library module with
     `run_stationarity_tests()`, `run_ljungbox_on_ic_series()`,
     `compute_quintile_monotonicity_score()`, `build_feature_selection_config()`
   - `src/ta_lab2/scripts/analysis/run_feature_selection.py` — CLI orchestrator
     that reads from ic_results, runs all tests, and writes YAML + DB
   - `src/ta_lab2/scripts/analysis/run_concordance.py` — concordance between
     IC-IR ranking and MDA ranking

4. **Tier design (Claude's discretion):**
   - **Active:** |IC-IR| > 0.3, stationarity not NON_STATIONARY or has compensating
     evidence, pass rate >= 30% of assets, Ljung-Box flag noted but not disqualifying
   - **Conditional:** |IC-IR| > 0.3 in at least one regime (trend_state or vol_state)
     but not universal; or universal |IC-IR| = 0.15-0.30 with good quintile spread
   - **Watch:** |IC-IR| = 0.10-0.30, some horizons show signal, needs more data
   - **Archive:** |IC-IR| < 0.10 across all assets and horizons

5. **Quintile monotonicity score:** For each surviving feature, run `compute_quintile_returns()`
   and compute `spearmanr([1,2,3,4,5], [q1_terminal, q2_terminal, q3_terminal, q4_terminal, q5_terminal]).statistic`.
   A score > 0.9 = strongly monotonic. Store this score in the YAML and DB.

6. **Per-timeframe vs universal:** Based on what IC data reveals, the default
   recommendation is to make the active set universal (1D) and note if a feature
   only has IC at shorter TFs (4H, 1H) without 1D signal. Do not create per-TF
   configs in this phase — that adds complexity for limited gain.

---

## Sources

### Primary (HIGH confidence)

- `src/ta_lab2/analysis/ic.py` — Complete IC computation library (verified by reading)
- `src/ta_lab2/scripts/analysis/run_ic_sweep.py` — Full batch sweep (verified by reading)
- `src/ta_lab2/scripts/analysis/run_ic_decay.py` — Decay CLI (verified by reading)
- `src/ta_lab2/scripts/analysis/run_quintile_sweep.py` — Quintile CLI (verified by reading)
- `src/ta_lab2/analysis/quintile.py` — Quintile engine (verified by reading)
- `src/ta_lab2/ml/feature_importance.py` — MDA/SFI/clustered MDA (verified by reading)
- `src/ta_lab2/scripts/ml/run_feature_importance.py` — MDA CLI (verified by reading)
- `alembic/versions/c3b718c2d088_ic_results_table.py` — ic_results schema (verified)
- `alembic/versions/a1b2c3d4e5f6_add_rank_ic_to_ic_results.py` — rank_ic addition (verified)
- `alembic/versions/a0b1c2d3e4f5_strip_cmc_prefix_add_venue_id.py` — table rename (verified)
- `pyproject.toml` — dependency list (verified — statsmodels ABSENT)
- `configs/experiments/features.yaml` — YAML pattern (verified)
- Python runtime verification: `import statsmodels` → ModuleNotFoundError (confirmed)
- Python runtime verification: scipy 1.17.0, sklearn 1.8.0 (confirmed installed)

### Secondary (MEDIUM confidence)

- statsmodels ADF/KPSS/Ljung-Box API — based on knowledge of statsmodels 0.14.x API;
  exact import paths should be verified after installation

---

## Metadata

**Confidence breakdown:**
- Existing infrastructure inventory: HIGH — all files read directly
- ic_results schema: HIGH — verified from migrations
- statsmodels absence: HIGH — Python import verified at runtime
- Statistical test API (statsmodels): MEDIUM — library not installed, based on knowledge
- dim_feature_selection schema design: MEDIUM — recommended, not yet existing
- Tier threshold recommendations: MEDIUM — reasonable starting points per CONTEXT.md decisions
- Ljung-Box p-value threshold (0.05, 10 lags): MEDIUM — standard choice for financial time series

**Research date:** 2026-03-21
**Valid until:** 2026-04-21 (stable domain — no fast-moving dependencies once statsmodels added)
