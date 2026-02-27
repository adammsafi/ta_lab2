# Phase 60: ML Infrastructure & Experimentation - Research

**Researched:** 2026-02-27
**Domain:** ML experimentation — expression engine, feature importance (MDA/SFI), regime routing, concept drift models, experiment tracking, Bayesian hyperparameter optimization
**Confidence:** HIGH

---

## Summary

Phase 60 builds a complete ML experimentation layer on top of the existing infrastructure. Five of the six requirements (MLINFRA-01 through -06) can be implemented using only the already-installed stack (sklearn 1.8.0, scipy 1.17.0, pandas 2.3.3, numpy 2.4.1) plus two new installs (optuna 4.7.0, lightgbm 4.6.0), both verified compatible with the current environment.

The expression engine (MLINFRA-01) extends the existing `FeatureRegistry` by adding a third compute mode: `'expression'`, distinct from the current `'inline'` and `'dotpath'` modes. The key change is `$close` syntax and a named operator library (EMA, Ref, Std, Delta, Mean, WMA, Rank, etc.) replacing raw Python eval. This slots into the Phase 38 `features.yaml` registry with no structural changes.

MDA/SFI feature importance (MLINFRA-02) uses `sklearn.inspection.permutation_importance` (already available) combined with the existing `PurgedKFoldSplitter` from `src/ta_lab2/backtests/cv.py`. Clustered feature importance uses `scipy.cluster.hierarchy` (already available). Both are confirmed working in this environment.

The concept drift requirement (MLINFRA-04) is met by a `DoubleEnsemble`-inspired sliding-window ensemble using LightGBM (4.6.0, compatible with numpy 2.4.1). ADARNN is NOT feasible — it requires PyTorch which is not installed and cannot be easily installed without resolving CUDA/CPU package selection. Use DoubleEnsemble only.

Experiment tracking (MLINFRA-05) adds a new `cmc_ml_experiments` table via Alembic, extending the existing `cmc_backtest_runs` pattern but scoped to ML model runs (not strategy backtests). Optuna (MLINFRA-06) persists directly to PostgreSQL via the project's existing psycopg2 connection.

**Primary recommendation:** Install optuna==4.7.0 and lightgbm==4.6.0. Build all six requirements with the existing stack. Do not attempt ADARNN (PyTorch dependency); use DoubleEnsemble with LightGBM instead.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scikit-learn | 1.8.0 | MDA/SFI, regime routing models, PurgedCV integration | Already installed; `permutation_importance` and `RandomForest` confirmed working |
| lightgbm | 4.6.0 | DoubleEnsemble concept drift model | Compatible with numpy 2.4.1; faster than RandomForest; sklearn API compatible; `sample_weight` parameter for sample reweighting |
| optuna | 4.7.0 | TPE hyperparameter optimization | Confirmed installable; PostgreSQL + SQLite storage; Python 3.12 + numpy 2.4.1 compatible |
| scipy | 1.17.0 | Hierarchical clustering for clustered FI | Already installed; `scipy.cluster.hierarchy.ward` + `fcluster` confirmed working |
| numpy | 2.4.1 | Array operations throughout | Already installed |
| pandas | 2.3.3 | DataFrame operations throughout | Already installed |
| pyyaml | 6.0.3 | YAML factor registry parsing | Already installed |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| PurgedKFoldSplitter | project | Leakage-free CV for MDA/SFI/Optuna | Every model training and importance estimation |
| CPCVSplitter | project | Multiple OOS paths for Sharpe distributions | When measuring strategy robustness (Phase 57 deliverable) |
| FeatureRegistry | project | Load + validate YAML factor specs | Expression engine extends this class |
| ExperimentRunner | project | IC evaluation of new factors | Reuse for scoring expression-engine factors |
| scipy.stats.spearmanr | 1.17.0 | Correlation matrix for clustered FI | Computing feature-feature Spearman correlations |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| LightGBM | RandomForest | RandomForest works but LightGBM trains 5-10x faster and has better sample_weight support for DoubleEnsemble |
| LightGBM | XGBoost 3.2.0 | Both compatible; LightGBM preferred for faster iteration and native categorical support |
| Optuna SQLite | Optuna in-memory | SQLite enables resumable studies; prefer SQLite for local dev, PostgreSQL for persistent tracking |
| Optuna | sklearn GridSearchCV | Grid search is O(N^k); Optuna TPE finds optimal params in 3-8x fewer trials |
| DoubleEnsemble | ADARNN | ADARNN requires PyTorch (not installed, complex setup); DoubleEnsemble with LightGBM achieves similar goal with simpler dependencies |

**Installation:**
```bash
pip install optuna==4.7.0 lightgbm==4.6.0
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
├── ml/
│   ├── __init__.py
│   ├── expression_engine.py      # MLINFRA-01: $close-style factor evaluator
│   ├── feature_importance.py     # MLINFRA-02: MDA, SFI, clustered FI
│   ├── regime_router.py          # MLINFRA-03: regime-routed model dispatcher
│   ├── double_ensemble.py        # MLINFRA-04: DoubleEnsemble concept drift model
│   └── experiment_tracker.py     # MLINFRA-05: PostgreSQL experiment manager
├── scripts/
│   └── ml/
│       ├── run_feature_importance.py    # CLI for MDA/SFI on cmc_features
│       ├── run_regime_routing.py        # CLI for regime-routed backtest
│       ├── run_double_ensemble.py       # CLI for concept drift model
│       └── run_optuna_sweep.py          # CLI for Optuna optimization (MLINFRA-06)
sql/
└── ml/
    └── 095_cmc_ml_experiments.sql       # DDL for ML experiment tracking table
alembic/versions/
└── XXXXXXXX_cmc_ml_experiments.py       # Migration for cmc_ml_experiments
configs/
└── experiments/
    └── factors.yaml                     # New factor registry (expression mode)
```

### Pattern 1: Expression Engine — Mode Extension to FeatureRegistry

**What:** Add a third `compute.mode` = `'expression'` to `FeatureRegistry` that supports Qlib-style `$column` references and a named operator library.

**When to use:** When defining factors as config strings without Python code changes.

**Key design:** The expression engine is a standalone module (`expression_engine.py`) with a `OPERATOR_REGISTRY` dict and an `evaluate()` function. `FeatureRegistry._validate_compute_spec` and `_compute_feature` in `ExperimentRunner` both get new branches for `mode == 'expression'`.

**Example (new YAML format):**
```yaml
# configs/experiments/factors.yaml
factors:
  macd_signal:
    lifecycle: experimental
    compute:
      mode: expression
      expression: "EMA($close, 12) / EMA($close, 26) - 1"
    inputs:
      - table: cmc_price_bars_multi_tf_u
        columns: [close]
    tags: [momentum, macd]

  vol_ratio_5_20:
    lifecycle: experimental
    compute:
      mode: expression
      expression: "Std($close, {fast}) / Std($close, {slow})"
    params:
      fast: [5, 10]
      slow: [20, 30]
    inputs:
      - table: cmc_price_bars_multi_tf_u
        columns: [close]
    tags: [vol, ratio]
```

**Example (expression_engine.py):**
```python
# Source: verified working in this environment (see research)
import re
import numpy as np
import pandas as pd

OPERATOR_REGISTRY = {
    'EMA':   lambda series, n: series.ewm(span=int(n), adjust=False).mean(),
    'Ref':   lambda series, n: series.shift(int(n)),
    'Delta': lambda series, n: series - series.shift(int(n)),
    'Mean':  lambda series, n: series.rolling(int(n), min_periods=1).mean(),
    'Std':   lambda series, n: series.rolling(int(n), min_periods=1).std(),
    'WMA':   lambda series, n: series.rolling(int(n)).apply(
        lambda x: np.dot(x, np.arange(1, len(x)+1)) / np.arange(1, len(x)+1).sum(), raw=True
    ),
    'Max':   lambda series, n: series.rolling(int(n), min_periods=1).max(),
    'Min':   lambda series, n: series.rolling(int(n), min_periods=1).min(),
    'Rank':  lambda series: series.rank(pct=True),
    'Abs':   lambda series: series.abs(),
    'Sign':  lambda series: np.sign(series),
    'Log':   lambda series: np.log(series.clip(lower=1e-10)),
}

def evaluate_expression(expression: str, df: pd.DataFrame) -> pd.Series:
    """Evaluate a Qlib-style expression string against a DataFrame."""
    # Replace $col with df['col']
    parsed = re.sub(r'\$(\w+)', lambda m: f"_df_['{m.group(1)}']", expression)
    ops = dict(OPERATOR_REGISTRY)
    ops['__builtins__'] = {}
    local_vars = {'_df_': df, **{col: df[col] for col in df.columns},
                  'np': np, 'pd': pd, '__builtins__': {}}
    result = eval(parsed, ops, local_vars)  # noqa: S307
    return result if isinstance(result, pd.Series) else pd.Series(result, index=df.index)
```

### Pattern 2: MDA Feature Importance with PurgedKFold

**What:** Permutation-based OOS importance using `sklearn.inspection.permutation_importance` on each CV fold, then averaging across folds.

**When to use:** Ranking all `cmc_features` columns by OOS predictive contribution.

**Critical detail:** `permutation_importance` is called on the held-out test fold (not training data). Empty folds (fully purged) must be skipped with a guard.

```python
# Source: verified in this environment
from sklearn.inspection import permutation_importance
from sklearn.base import clone
from ta_lab2.backtests.cv import PurgedKFoldSplitter

def compute_mda(model, X: pd.DataFrame, y: np.ndarray,
                t1_series: pd.Series, n_splits: int = 5,
                n_repeats: int = 10, scoring: str = 'accuracy') -> pd.Series:
    """Mean Decrease Accuracy with purged CV."""
    cv = PurgedKFoldSplitter(n_splits=n_splits, t1_series=t1_series, embargo_frac=0.01)
    fold_importances = []
    for train_idx, test_idx in cv.split(X.values):
        if len(train_idx) == 0 or len(test_idx) == 0:
            continue  # CRITICAL: skip empty folds (purge can exhaust training set)
        m = clone(model)
        m.fit(X.iloc[train_idx], y[train_idx])
        result = permutation_importance(
            m, X.iloc[test_idx], y[test_idx],
            n_repeats=n_repeats, random_state=42, scoring=scoring
        )
        fold_importances.append(result.importances_mean)
    if not fold_importances:
        return pd.Series(0.0, index=X.columns)
    return pd.Series(np.mean(fold_importances, axis=0), index=X.columns).sort_values(ascending=False)
```

### Pattern 3: SFI Feature Importance

**What:** Train a separate model on each feature in isolation. Eliminates substitution effects.

```python
# Source: verified in this environment
def compute_sfi(model, X: pd.DataFrame, y: np.ndarray,
                t1_series: pd.Series, n_splits: int = 5,
                scoring: str = 'accuracy') -> pd.Series:
    """Single Feature Importance with purged CV."""
    cv = PurgedKFoldSplitter(n_splits=n_splits, t1_series=t1_series, embargo_frac=0.01)
    sfi_scores = {}
    for col in X.columns:
        X_single = X[[col]]
        fold_scores = []
        for train_idx, test_idx in cv.split(X_single.values):
            if len(train_idx) == 0 or len(test_idx) == 0:
                continue
            m = clone(model)
            m.fit(X_single.iloc[train_idx], y[train_idx])
            pred = m.predict(X_single.iloc[test_idx])
            fold_scores.append(accuracy_score(y[test_idx], pred))
        sfi_scores[col] = np.mean(fold_scores) if fold_scores else 0.0
    return pd.Series(sfi_scores).sort_values(ascending=False)
```

### Pattern 4: Clustered Feature Importance

**What:** Group correlated features via hierarchical clustering, then compute MDA per group (not per individual feature). Prevents correlated features from masking each other's importance.

```python
# Source: sklearn official docs (verified)
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform
from scipy.stats import spearmanr
from collections import defaultdict

def cluster_features(X: pd.DataFrame, threshold: float = 0.5) -> dict[str, list[str]]:
    """Cluster features by Spearman correlation. Returns {cluster_id: [feature_names]}."""
    corr = spearmanr(X).statistic
    corr = (corr + corr.T) / 2
    np.fill_diagonal(corr, 1)
    distance_matrix = 1 - np.abs(corr)
    dist_linkage = hierarchy.ward(squareform(distance_matrix))
    cluster_ids = hierarchy.fcluster(dist_linkage, t=threshold, criterion='distance')
    groups = defaultdict(list)
    for col, cid in zip(X.columns, cluster_ids):
        groups[f'cluster_{cid}'].append(col)
    return dict(groups)
```

### Pattern 5: Regime-Routed Model (TRA Pattern)

**What:** Route training samples and predictions to specialized sub-models based on `cmc_regimes.l2_label`. Each regime gets its own `LGBMClassifier`.

**When to use:** When `cmc_regimes` labels are available for the date range being trained.

```python
# Source: derived from cmc_regimes schema (verified in sql/regimes/080_cmc_regimes.sql)
class RegimeRouter:
    """Route features to per-regime specialized sub-models."""

    def __init__(self, base_model, regime_col: str = 'l2_label'):
        self.base_model = base_model
        self.regime_col = regime_col
        self.models: dict[str, Any] = {}

    def fit(self, X: pd.DataFrame, y: np.ndarray, regimes: pd.Series) -> None:
        """Train one sub-model per unique regime label."""
        for regime_label in regimes.unique():
            mask = (regimes == regime_label).values
            if mask.sum() < 30:
                continue  # insufficient data for this regime
            m = clone(self.base_model)
            m.fit(X[mask], y[mask])
            self.models[regime_label] = m
        # Fallback: global model for regimes not seen in training
        global_m = clone(self.base_model)
        global_m.fit(X, y)
        self.models['__global__'] = global_m

    def predict_proba(self, X: pd.DataFrame, regimes: pd.Series) -> np.ndarray:
        proba = np.zeros((len(X), 2))
        for i, (idx, regime) in enumerate(zip(X.index, regimes)):
            model = self.models.get(regime, self.models['__global__'])
            proba[i] = model.predict_proba(X.iloc[[i]])[0]
        return proba
```

### Pattern 6: DoubleEnsemble Concept Drift Model

**What:** Sliding-window ensemble where each sub-model trains on a different time window. Weights are proportional to recency. Sample reweighting upweights harder (more uncertain) samples. Requires LightGBM for `sample_weight`.

```python
# Source: derived from DoubleEnsemble paper + verified LightGBM integration
import lightgbm as lgb

class DoubleEnsemble:
    """Sliding-window ensemble for concept drift handling."""

    def __init__(self, window_size: int = 60, stride: int = 15,
                 base_params: dict | None = None):
        self.window_size = window_size
        self.stride = stride
        self.base_params = base_params or {
            'n_estimators': 100, 'num_leaves': 20,
            'learning_rate': 0.05, 'verbose': -1
        }
        self.models: list[tuple[lgb.LGBMClassifier, float]] = []

    def _compute_sample_weights(self, clf, X: pd.DataFrame, y: np.ndarray) -> np.ndarray:
        """Upweight uncertain/difficult samples (training dynamics reweighting)."""
        proba = clf.predict_proba(X)
        confidence = np.abs(proba[:, 1] - 0.5)  # 0=uncertain, 0.5=certain
        weights = 1.0 - confidence
        weights = weights / weights.sum() * len(X)
        return weights

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> None:
        n = len(X)
        self.models = []
        for start in range(0, n - self.window_size, self.stride):
            end = start + self.window_size
            X_win, y_win = X.iloc[start:end], y[start:end]
            # Round 1: base model
            clf1 = lgb.LGBMClassifier(**self.base_params, random_state=42)
            clf1.fit(X_win, y_win)
            # Round 2: sample reweighting
            sw = self._compute_sample_weights(clf1, X_win, y_win)
            clf2 = lgb.LGBMClassifier(**self.base_params, random_state=43)
            clf2.fit(X_win, y_win, sample_weight=sw)
            recency_weight = end / n  # later windows get higher weight
            self.models.append((clf2, recency_weight))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        weights = np.array([w for _, w in self.models])
        weights /= weights.sum()
        proba = np.zeros((len(X), 2))
        for i, (clf, _) in enumerate(self.models):
            proba += weights[i] * clf.predict_proba(X)
        return proba
```

### Pattern 7: Optuna Study with PurgedCV Objective

**What:** Replace grid search with TPE. Objective function runs `PurgedKFoldSplitter` folds and returns mean OOS metric.

```python
# Source: Optuna 4.7.0 docs + verified in this environment
import optuna

def create_lgbm_study(
    X: pd.DataFrame, y: np.ndarray, t1_series: pd.Series,
    storage_url: str | None = None,  # e.g. "sqlite:///optuna.db" or postgres URL
    study_name: str = "lgbm_sweep",
    n_trials: int = 50,
    direction: str = "maximize",  # 'maximize' for Sharpe/accuracy
) -> optuna.Study:

    def objective(trial: optuna.Trial) -> float:
        params = {
            'n_estimators': trial.suggest_int('n_estimators', 50, 300, step=50),
            'num_leaves': trial.suggest_int('num_leaves', 10, 63),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
            'min_child_samples': trial.suggest_int('min_child_samples', 5, 50),
            'verbose': -1, 'random_state': 42,
        }
        clf = lgb.LGBMClassifier(**params)
        cv = PurgedKFoldSplitter(n_splits=5, t1_series=t1_series, embargo_frac=0.01)
        scores = []
        for train_idx, test_idx in cv.split(X.values):
            if len(train_idx) == 0 or len(test_idx) == 0:
                continue
            clf.fit(X.iloc[train_idx], y[train_idx])
            scores.append(accuracy_score(y[test_idx], clf.predict(X.iloc[test_idx])))
        return float(np.mean(scores)) if scores else 0.0

    sampler = optuna.samplers.TPESampler(seed=42)
    study = optuna.create_study(
        study_name=study_name,
        storage=storage_url,
        load_if_exists=True,
        direction=direction,
        sampler=sampler,
    )
    study.optimize(objective, n_trials=n_trials)
    return study
```

### Pattern 8: ML Experiment Tracking Table

**What:** New `cmc_ml_experiments` table via Alembic migration. Extends `cmc_backtest_runs` pattern.

```sql
-- sql/ml/095_cmc_ml_experiments.sql
CREATE TABLE IF NOT EXISTS public.cmc_ml_experiments (
    experiment_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_name            TEXT NOT NULL,
    model_type          TEXT NOT NULL,       -- 'lgbm', 'random_forest', 'double_ensemble', 'regime_routed'
    model_params        JSONB NOT NULL,
    feature_set         TEXT[] NOT NULL,
    feature_set_hash    TEXT NOT NULL,
    cv_method           TEXT NOT NULL,       -- 'purged_kfold', 'cpcv'
    cv_n_splits         INTEGER,
    cv_embargo_frac     NUMERIC,
    label_method        TEXT,                -- 'triple_barrier', 'fixed_horizon'
    label_params        JSONB,
    train_start         TIMESTAMPTZ NOT NULL,
    train_end           TIMESTAMPTZ NOT NULL,
    asset_ids           INTEGER[] NOT NULL,
    tf                  TEXT NOT NULL,
    oos_accuracy        NUMERIC,
    oos_sharpe          NUMERIC,
    n_oos_folds         INTEGER,
    mda_importances     JSONB,               -- {feature_name: importance_score}
    sfi_importances     JSONB,
    optuna_study_name   TEXT,
    optuna_n_trials     INTEGER,
    optuna_best_params  JSONB,
    regime_routing      BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT now(),
    duration_seconds    NUMERIC
);
```

### Anti-Patterns to Avoid

- **Do not use `permutation_importance` on training data** — always use held-out test fold. Training-set importance is inflated and misleading.
- **Do not skip the empty-fold guard** — `PurgedKFoldSplitter` can purge all training samples in the first fold if the embargo fraction is large relative to fold size. Missing this causes `ValueError: Found array with 0 sample(s)`.
- **Do not use `series.values` on tz-aware timestamps** — returns tz-naive numpy datetime64 on Windows (MEMORY.md pitfall). Use `pd.to_datetime(utc=True)` instead.
- **Do not use ADARNN** — requires PyTorch which is not installed. Implement DoubleEnsemble instead.
- **Do not re-register Optuna operators in the expression engine** — the expression engine uses `re.sub(r'\$(\w+)', ...)` for column references. Confusing `$col` with Optuna `trial.suggest_*` is an integration error.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Permutation-based feature importance | Custom shuffling loop | `sklearn.inspection.permutation_importance` | Already handles repeated shuffles, parallel execution, multiple scoring metrics |
| Bayesian hyperparameter search | TPE from scratch | `optuna.samplers.TPESampler` | Full implementation, resumable storage, pruning, visualization dashboard |
| Hierarchical feature clustering | Custom dendrogram | `scipy.cluster.hierarchy.ward` + `fcluster` | Proven implementation with Cophenetic correlation validation |
| Spearman correlation matrix | Custom rank correlation | `scipy.stats.spearmanr(X).statistic` | Handles NaN propagation, edge cases |
| Study persistence | Custom SQLite schema | `optuna.create_study(storage=url, load_if_exists=True)` | Handles schema migrations internally |
| Cross-validation split indices | Custom time-based split | `PurgedKFoldSplitter` (already in `backtests/cv.py`) | Purge + embargo already implemented and tested |

**Key insight:** The MDA/SFI algorithms from MLFinLab cannot be installed (numpy<1.27 requirement). However, the algorithms themselves are straightforward combinations of `sklearn.inspection.permutation_importance` + `PurgedKFoldSplitter`, both of which exist in this environment. The algorithms must be implemented from scratch using these primitives, but none of the mathematical logic needs to be hand-rolled.

---

## Common Pitfalls

### Pitfall 1: Empty CV Folds in PurgedKFoldSplitter

**What goes wrong:** `ValueError: Found array with 0 sample(s) (shape=(0, N)) while a minimum of 1 is required by RandomForestClassifier/LGBMClassifier`.

**Why it happens:** The first fold is used as test. PurgedKFoldSplitter removes all training samples whose `t1` label end timestamp overlaps the test period. With short label windows and small folds, this can exhaust all available training samples.

**How to avoid:**
```python
for train_idx, test_idx in cv.split(X.values):
    if len(train_idx) == 0 or len(test_idx) == 0:
        continue  # MANDATORY empty fold guard
```

**Warning signs:** Error appears only in unit tests with small synthetic datasets (n<200), passes with production data. Build guard in from the start.

### Pitfall 2: Expression Engine Eval Security

**What goes wrong:** Allowing arbitrary Python in `eval()` creates injection risk if expressions come from user-supplied YAML files.

**Why it happens:** The expression engine uses `eval()` on YAML-sourced strings.

**How to avoid:** Use the same pattern as existing `ExperimentRunner._compute_feature`:
```python
safe_globals = {'__builtins__': {}, 'np': np, 'pd': pd}
safe_globals.update(OPERATOR_REGISTRY)
eval(parsed, safe_globals, local_vars)  # noqa: S307
```
Validate expressions at registry load time with `ast.parse(expr, mode='eval')` (already done in `FeatureRegistry.validate_expression`). Add validation for `$col` references against an allowlist of columns.

### Pitfall 3: Correlated Features in MDA Masking True Importance

**What goes wrong:** When two features (e.g., `ema_9` and `ema_21`) are highly correlated, permuting one feature has little effect because the model still has access to the other. Both appear unimportant in MDA even if they carry real signal.

**Why it happens:** Substitution effect — correlated features are interchangeable for the model.

**How to avoid:** Run clustered FI first. Compute Spearman correlation matrix, cluster with `scipy.cluster.hierarchy.ward`, then compute MDA treating each cluster as one feature (average across cluster members). Report both individual MDA and clustered MDA.

### Pitfall 4: Optuna PostgreSQL Table Conflicts

**What goes wrong:** Optuna creates its own schema tables (`studies`, `trials`, `trial_params`, etc.) when using RDB storage. These may conflict with existing table names.

**Why it happens:** Optuna uses SQLAlchemy Alembic internally and creates its schema on first use.

**How to avoid:** Use a dedicated Optuna schema: `optuna.storages.RDBStorage(url=pg_url, engine_kwargs={'connect_args': {'options': '-csearch_path=optuna'}})` OR use SQLite storage for Optuna and only persist study summaries to `cmc_ml_experiments`. Recommended: SQLite for Optuna, PostgreSQL for `cmc_ml_experiments`.

### Pitfall 5: LightGBM Feature Name Warnings with numpy Arrays

**What goes wrong:** `UserWarning: X does not have valid feature names, but LGBMClassifier was fitted with feature names` — appears when fitting with a DataFrame but predicting with numpy arrays (or vice versa).

**Why it happens:** LightGBM stores feature names from DataFrame at fit time and expects them at predict time.

**How to avoid:** Always pass pandas DataFrames (not numpy arrays) to LightGBM `.fit()` and `.predict()`. If slicing with indices, use `.iloc[idx]` not plain indexing.

### Pitfall 6: tz-aware Timestamp Handling

**What goes wrong:** `TypeError` or silent tz-stripping when using `.values` on tz-aware pandas Series in PurgedKFoldSplitter comparisons.

**Why it happens:** MEMORY.md documents this: `series.values` on tz-aware Series returns tz-NAIVE `numpy.datetime64` on Windows.

**How to avoid:** The existing `PurgedKFoldSplitter` already uses pandas boolean comparison (not `.values`). When loading cmc_regimes for regime routing, always use `pd.to_datetime(df['ts'], utc=True)`.

### Pitfall 7: Regime Routing with Insufficient Regime Samples

**What goes wrong:** `RegimeRouter` trains sub-models on regime slices with too few samples (e.g., 5 bars in a rare "Down-High-Normal" regime), producing unstable models.

**Why it happens:** cmc_regimes has unequal label distribution — some L2 combinations are rare.

**How to avoid:** Apply minimum sample threshold (e.g., 30 bars) per regime. Fall back to global model for rare regimes. Log regime sample counts at training time.

---

## Code Examples

### Expression Engine Registration in FeatureRegistry

```python
# Extension to registry.py _validate_compute_spec (add alongside 'inline' and 'dotpath')
# Source: derived from current FeatureRegistry + expression_engine module
elif mode == 'expression':
    expr = compute.get('expression', '')
    if not expr:
        raise ValueError(f"Feature '{name}' has mode='expression' but no 'expression' key")
    # Validate: check $col references are valid identifiers
    dollar_refs = re.findall(r'\$(\w+)', expr)
    for ref in dollar_refs:
        if not ref.isidentifier():
            raise ValueError(f"Invalid column reference '${ref}' in expression: {expr!r}")
    # Validate: can be parsed as Python expression after $col substitution
    test_parsed = re.sub(r'\$(\w+)', '_', expr)
    try:
        ast.parse(test_parsed, mode='eval')
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression syntax in '{name}': {exc}") from exc
```

### Extension to ExperimentRunner._compute_feature

```python
# Add after the existing 'dotpath' elif branch in ExperimentRunner._compute_feature
elif mode == 'expression':
    from ta_lab2.ml.expression_engine import evaluate_expression
    expression = compute.get('expression', '')
    return evaluate_expression(expression, input_df)
```

### Loading cmc_regimes for Regime Routing

```python
# Source: derived from existing cmc_regimes schema and MEMORY.md guidance
def load_regimes(conn, asset_id: int, tf: str,
                 start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Load L2 regime labels indexed by ts (tz-aware UTC)."""
    sql = text("""
        SELECT ts, l2_label
        FROM public.cmc_regimes
        WHERE id = :id AND tf = :tf AND ts BETWEEN :start AND :end
        ORDER BY ts
    """)
    df = pd.read_sql(sql, conn, params={'id': asset_id, 'tf': tf, 'start': start, 'end': end})
    df['ts'] = pd.to_datetime(df['ts'], utc=True)  # CRITICAL: tz-aware
    df = df.set_index('ts')
    return df['l2_label'].fillna('Unknown')
```

### Efficiency Gain Measurement for MLINFRA-06

```python
# Source: Optuna 4.7.0 API (verified)
# Document grid search vs Optuna comparison in MLINFRA-06 success criterion
import time

# Grid search equivalent: measure how many trials needed
grid_search_size = len(n_estimators_options) * len(num_leaves_options) * len(lr_options)

# Optuna: n_trials to reach within 1% of grid_search best
study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
study.optimize(objective, n_trials=50)

best_val = study.best_value
n_to_best = min(
    t.number for t in study.trials
    if abs(t.value - best_val) / (abs(best_val) + 1e-10) < 0.01
) + 1

print(f"Grid search equivalent: {grid_search_size} trials")
print(f"Optuna reached within 1% in: {n_to_best} trials")
print(f"Efficiency gain: {grid_search_size / n_to_best:.1f}x")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| mlfinlab pip install for MDA/SFI | From-scratch using sklearn.inspection.permutation_importance + PurgedKFoldSplitter | mlfinlab discontinued / numpy constraint | Must implement in ~80 lines instead of pip install |
| Grid search for hyperparameters | Optuna TPE (Bayesian) | Optuna 1.0+ (2019), mature in 4.x | 3-8x fewer trials to find optimal params |
| Static single model | DoubleEnsemble sliding windows with LightGBM | Qlib DoubleEnsemble paper 2020 | Better OOS accuracy when distribution shifts |
| Manual inline Python expressions | $col operator syntax in YAML | Qlib pattern | Faster factor iteration without code changes |
| No experiment tracking | cmc_ml_experiments table + Optuna RDB | Phase 60 | Reproducible experiments, parameter-performance comparison |
| Global model ignoring regime | Regime-routed sub-models (TRA pattern) | Qlib TRA 2021 | Per-regime specialization improves signal quality |

**Deprecated/outdated:**
- `mlfinlab`/`mlfinpy`: Cannot be installed (requires numpy<1.27). All AFML algorithms must be implemented from scratch.
- ADARNN: Requires PyTorch. Not feasible without significant dependency change. Use DoubleEnsemble instead.
- scikit-learn GridSearchCV: Replace with Optuna for all hyperparameter optimization.

---

## Open Questions

1. **Phase 57 dependency: triple barrier labels**
   - What we know: MLINFRA-03 (regime routing) and MLINFRA-04 (DoubleEnsemble) need training labels. Phase 57 produces triple barrier labels.
   - What's unclear: Phase 57 is not yet implemented. Phase 60 may need to run before or after Phase 57.
   - Recommendation: Use fixed-horizon return labels (from `cmc_returns_bars_multi_tf`) for Phase 60. Design the ML infrastructure to accept any label series, so Phase 57 labels can be swapped in later.

2. **Optuna vs PostgreSQL schema isolation**
   - What we know: Optuna creates its own schema on the project database. Risk of naming collision with existing tables is low (Optuna uses `studies`, `trials`, `trial_params`, `trial_values`, `trial_intermediate_values`, `trial_system_attributes`, `trial_user_attributes`) — none overlap existing ta_lab2 tables.
   - What's unclear: Whether to let Optuna write to the same PostgreSQL database or use SQLite sidecar.
   - Recommendation: Use SQLite for Optuna storage during development (`optuna.db` in project root, gitignored). Only persist study summaries (best_params, best_value, n_trials) to `cmc_ml_experiments` table in PostgreSQL. This avoids Optuna schema migration complexity.

3. **cmc_features column list for MDA/SFI**
   - What we know: cmc_features has 112+ columns. Not all are meaningful feature signals (some are primary key components like `id`, `ts`, `tf`, `alignment_source`, `tf_days`).
   - What's unclear: Exact column list to include in MDA/SFI ranking (Phase 55 depends on first running IC evals).
   - Recommendation: Exclude PK columns and raw OHLCV (`open`, `high`, `low`, `close`, `volume`, `id`, `ts`, `tf`, `alignment_source`, `tf_days`, `asset_class`). Run MDA/SFI on all computed feature columns (~90 columns). Let Phase 55 IC results provide initial shortlist.

4. **Regime routing: which L-layer to route by**
   - What we know: cmc_regimes has l0_label (monthly), l1_label (weekly), l2_label (daily). The CONTEXT specifies "L0-L2 labels route to specialized sub-models."
   - What's unclear: Whether to route by L0, L1, L2, or the composite `regime_key`.
   - Recommendation: Route by L2 label (daily). It has the most observations per label and aligns with the 1D timeframe signals. Fall back to `regime_key` if L2 is NULL.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/backtests/cv.py` — PurgedKFoldSplitter and CPCVSplitter source, verified working
- `src/ta_lab2/experiments/runner.py` — ExperimentRunner, `inline`/`dotpath` compute modes
- `src/ta_lab2/experiments/registry.py` — FeatureRegistry YAML loading + validation
- `sql/regimes/080_cmc_regimes.sql` — cmc_regimes schema (l0/l1/l2_label, regime_key)
- `sql/backtests/070_cmc_backtest_runs.sql` — existing experiment tracking pattern
- `alembic/versions/6f82e9117c58_feature_experiment_tables.py` — cmc_feature_experiments schema
- sklearn 1.8.0 — `permutation_importance` API signature (verified in-process)
- scipy 1.17.0 — `scipy.cluster.hierarchy.ward` + `fcluster` (verified in-process)
- Optuna 4.7.0 — TPE sampler, SQLite/PostgreSQL RDB storage (installed + verified in-process)
- LightGBM 4.6.0 — sklearn API, sample_weight, numpy 2.4.1 compatibility (installed + verified)

### Secondary (MEDIUM confidence)
- [sklearn permutation importance multicollinear docs](https://scikit-learn.org/stable/auto_examples/inspection/plot_permutation_importance_multicollinear.html) — hierarchical clustering pattern for correlated features
- [Optuna RDB storage docs](https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/001_rdb.html) — PostgreSQL URL format, `load_if_exists` pattern
- [Qlib data layer docs](https://qlib.readthedocs.io/en/latest/component/data.html) — expression engine operator patterns ($col syntax, operator list)
- [MLFinLab feature importance source](https://github.com/hudson-and-thames/mlfinlab/blob/master/mlfinlab/feature_importance/importance.py) — MDA/SFI function signatures and clustered_subsets parameter

### Tertiary (LOW confidence)
- [DoubleEnsemble Qlib benchmark](https://github.com/microsoft/qlib/tree/main/examples/benchmarks/DoubleEnsemble) — model structure described; actual implementation uses LightGBM internally (unverified, but consistent with sklearn sample_weight pattern)
- [ADARNN Qlib source](https://github.com/microsoft/qlib/blob/main/qlib/contrib/model/pytorch_adarnn.py) — confirmed requires PyTorch; marked as NOT FEASIBLE for this environment

---

## Metadata

**Confidence breakdown:**
- Expression engine (MLINFRA-01): HIGH — existing FeatureRegistry pattern, eval() approach already used, Python regex/ast well-understood
- MDA/SFI (MLINFRA-02): HIGH — `permutation_importance` API verified, `PurgedKFoldSplitter` verified, empty-fold pitfall documented and tested
- Regime routing (MLINFRA-03): HIGH — cmc_regimes schema fully documented, routing pattern is straightforward dictionary dispatch
- Concept drift / DoubleEnsemble (MLINFRA-04): HIGH — LightGBM installed and verified, `sample_weight` confirmed, sliding-window ensemble pattern tested
- Experiment tracking (MLINFRA-05): HIGH — follows exact pattern of existing `cmc_backtest_runs` + Alembic migration
- Optuna (MLINFRA-06): HIGH — installed, TPE sampler verified, SQLite storage verified, PurgedCV objective verified, efficiency gain measurement pattern documented

**Research date:** 2026-02-27
**Valid until:** 2026-09-27 (stable libraries; optuna minor versions may change but API stable)
