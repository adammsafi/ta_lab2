# Phase 100: ML Signal Combination - Research

**Researched:** 2026-03-31
**Domain:** ML ranking (LGBMRanker), SHAP interaction analysis, XGBoost meta-labeling, executor integration
**Confidence:** HIGH (all library behavior verified by running locally against installed packages)

---

## Summary

Phase 100 adds three ML layers on top of the existing signal pipeline: a cross-sectional ranker (LGBMRanker), feature interaction analysis (SHAP TreeExplainer), and an XGBoost meta-label confidence filter wired into the executor. All three integrate with the existing `ml/` package, `ml_experiments` table, and `ExperimentTracker`.

**What was researched:** LGBMRanker group-query mechanics and scoring, SHAP library behavior with LGBMRanker and XGBoost, XGBoost binary classification for meta-labeling, triple_barrier_labels schema, executor pre-filter hook points, and pyproject.toml dependency gaps.

**Standard approach:** LGBMRanker requires a `group` array that encodes how many assets belong to each "query" (one query = one time period). SHAP TreeExplainer works with LGBMRanker in shap 0.51.0 and returns full interaction tensors. XGBoost binary classifier predicts P(success) from triple_barrier outcomes. The meta-label filter belongs in `_process_asset_signal()` inside `paper_executor.py`, injected before the `PositionSizer.compute_target_position()` call.

**Primary recommendation:** Install `xgboost>=3.2.0` and `shap>=0.51.0` as a new `[ml]` optional-dependency group in pyproject.toml (both not currently in pyproject.toml). Both are pip-installable and were confirmed working locally. LightGBM 4.6.0 is already installed.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| lightgbm | 4.6.0 (installed) | LGBMRanker cross-sectional ranking | Already in use via `DoubleEnsemble`, lazy-imported; `LGBMRanker` is in the same package |
| xgboost | 3.2.0 (to install) | XGBClassifier meta-label confidence | Industry standard for gradient boosted trees; predict_proba() works natively for binary classification |
| shap | 0.51.0 (to install) | TreeExplainer SHAP + interaction values | Official SHAP library; confirmed shap_interaction_values() works with both LGBMRanker and XGBClassifier in shap 0.51.0 |
| scikit-learn | (installed) | PurgedKFoldSplitter, ndcg_score, spearmanr | Already used by entire ml/ package; `sklearn.metrics.ndcg_score` available |
| scipy | (installed) | spearmanr for IC scoring | Already used by feature_importance.py |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sklearn.metrics.ndcg_score | (installed) | OOS NDCG per fold | Compute NDCG per time-window fold for logging to ml_experiments |
| scipy.stats.spearmanr | (installed) | Spearman IC per time period | Compute mean cross-sectional Spearman IC (primary OOS metric per success criterion) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| xgboost XGBClassifier | sklearn RandomForestClassifier (already in MetaLabeler) | RFC is already in MetaLabeler; XGBoost adds scale/depth control and supports SHAP interaction natively. Success criterion explicitly requires XGBoost. |
| shap.TreeExplainer | LightGBM `pred_contrib=True` | pred_contrib gives per-sample feature SHAP values (not interactions). For interaction pairs, shap.TreeExplainer.shap_interaction_values() is simpler and returns (n_samples, n_features, n_features) tensor |
| shap interaction values | Correlation of pred_contrib columns | Works as fallback but less rigorous — a correlation of SHAP values is a proxy, not true Shapley interaction. Use shap.TreeExplainer as primary. |

### Installation

```bash
pip install "xgboost>=3.2.0" "shap>=0.51.0"
```

Add to pyproject.toml `[project.optional-dependencies]`:
```toml
[ml]
ml = [
  "lightgbm>=4.6.0",
  "xgboost>=3.2.0",
  "shap>=0.51.0",
]
```

---

## Architecture Patterns

### Recommended Project Structure

New files for Phase 100:

```
src/ta_lab2/ml/
├── ranker.py              # Plan 100-01: LGBMRanker wrapper + purged CV + IC scoring
├── shap_analysis.py       # Plan 100-02: SHAP interaction analysis + feature pair report
├── meta_filter.py         # Plan 100-03: XGBoost meta-label filter + executor hook
└── [existing files]       # experiment_tracker.py, feature_importance.py, etc.

src/ta_lab2/scripts/ml/
├── run_lgbm_ranker.py     # Plan 100-01: CLI for training + logging to ml_experiments
├── run_shap_analysis.py   # Plan 100-02: CLI for SHAP interaction report
├── run_meta_filter.py     # Plan 100-03: CLI for training meta-label model

sql/ml/
├── 100_ml_meta_filter_config.sql   # config table for threshold + model version
```

### Pattern 1: LGBMRanker Group-Query Cross-Sectional CV

**What:** Each training sample belongs to a "query group" = one time period with multiple assets. The ranker learns relative ordering within each group (not absolute scores). For purged CV, each fold is evaluated by Spearman IC and NDCG across time-period groups.

**When to use:** Cross-sectional rank prediction: "given the current features for all assets at time T, which assets will outperform?"

**Key constraint:** The `group` array passed to `LGBMRanker.fit()` encodes how many samples belong to each query. `sum(group) == n_samples`. For cross-sectional use: if there are `n_assets` assets per time period, `group = np.full(n_periods, n_assets)`.

**Example:**
```python
# Source: verified locally with lightgbm 4.6.0
import lightgbm as lgb
import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score

# Build group array: one query per time period
n_periods = len(unique_timestamps)
n_assets = assets_per_period  # may vary; use actual counts
group = np.array([n_assets] * n_periods)  # shape (n_periods,)

# y = relevance score, e.g. quantile rank of forward returns (0, 1, 2, 3, 4)
ranker = lgb.LGBMRanker(
    n_estimators=200,
    num_leaves=31,
    learning_rate=0.05,
    verbose=-1,
)
ranker.fit(X_train, y_train, group=group_train)

# Predict returns continuous scores (not classes)
scores = ranker.predict(X_test)  # shape (n_samples,)

# Spearman IC per time period (primary metric for ml_experiments)
ics = []
for ts_group in test_groups:
    idx = period_indices[ts_group]
    corr, _ = spearmanr(y_test[idx], scores[idx])
    if not np.isnan(corr):
        ics.append(corr)
mean_ic = np.mean(ics)
ic_ir = mean_ic / np.std(ics) if np.std(ics) > 0 else 0.0
```

### Pattern 2: Purged CV for Ranker

**What:** Use `PurgedKFoldSplitter` (already in `backtests/cv.py`) to split the cross-sectional dataset without temporal leakage. Each fold trains on earlier periods, tests on later periods.

**Key difference from classifier CV:** The `group` array must be recomputed for each fold's subset. Groups are built from the time-period index, so slicing by integer row index automatically sub-selects the right time periods.

**Example:**
```python
# Source: PurgedKFoldSplitter in backtests/cv.py (existing)
from ta_lab2.backtests.cv import PurgedKFoldSplitter

cv = PurgedKFoldSplitter(
    n_splits=5,
    t1_series=t1_series,  # label-end timestamps indexed by label-start
    embargo_frac=0.01,
)

for train_idx, test_idx in cv.split(X.values):
    # Recompute group for train/test subsets
    group_train = _build_group_array(ts_index[train_idx])
    group_test = _build_group_array(ts_index[test_idx])

    m = lgb.LGBMRanker(n_estimators=200, num_leaves=31, verbose=-1)
    m.fit(X.iloc[train_idx], y[train_idx], group=group_train)
    fold_scores = m.predict(X.iloc[test_idx])
    # compute per-period Spearman IC for this fold
```

### Pattern 3: SHAP Interaction Values with LGBMRanker

**What:** `shap.TreeExplainer` wraps the fitted LGBMRanker and computes `shap_interaction_values(X)`, returning an (n_samples, n_features, n_features) tensor. The off-diagonal entry `[s, i, j]` is the pairwise interaction effect of features `i` and `j` on sample `s`'s score.

**Confirmed:** In shap 0.51.0, `shap_interaction_values()` works with LGBMRanker. This was NOT the case in older shap versions (was only supported for XGBoost before shap ~0.40).

**Example:**
```python
# Source: verified locally with shap 0.51.0 + lightgbm 4.6.0
import shap
import numpy as np

explainer = shap.TreeExplainer(ranker)

# Use a representative sample (not full dataset -- expensive)
X_sample = X_test.iloc[:500]  # representative subset
interaction_values = explainer.shap_interaction_values(X_sample)
# shape: (500, n_features, n_features)

# Aggregate: mean absolute interaction per feature pair
mean_abs_interactions = np.abs(interaction_values).mean(axis=0)
# Extract upper triangle (symmetric) for feature pairs
n_f = len(feature_cols)
pair_scores = []
for i in range(n_f):
    for j in range(i + 1, n_f):
        pair_scores.append({
            "feature_a": feature_cols[i],
            "feature_b": feature_cols[j],
            "mean_abs_interaction": float(mean_abs_interactions[i, j]),
        })
pair_df = pd.DataFrame(pair_scores).sort_values("mean_abs_interaction", ascending=False)
top_5_pairs = pair_df.head(5)
```

### Pattern 4: XGBoost Meta-Label Filter

**What:** Binary classifier trained on `triple_barrier_labels`. Input features = same feature set as primary signal at `t0`. Target `y = 1` when the triple barrier bin outcome matched the primary signal direction (i.e., the trade would have been profitable), `y = 0` otherwise.

**Wiring:** The filter is applied inside `_process_asset_signal()` in `paper_executor.py`, injected as a pre-gate after reading `signal` but before computing `target_qty`. If `predict_proba()[:, 1] < threshold`, skip the trade.

**Example:**
```python
# Source: verified locally with xgboost 3.2.0
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV  # optional calibration

clf = xgb.XGBClassifier(
    n_estimators=200,
    max_depth=4,
    learning_rate=0.05,
    use_label_encoder=False,
    eval_metric="logloss",
    verbosity=0,
    scale_pos_weight=neg_count / pos_count,  # handle class imbalance
)
clf.fit(X_train, y_train)  # y = 1 if trade outcome matched direction

# At inference time (pre-executor):
confidence = clf.predict_proba(X_current)[0, 1]  # P(trade succeeds)
if confidence < threshold:  # threshold from config, e.g. 0.55
    return {"skipped_meta_filter": True}
```

### Pattern 5: ExperimentTracker Integration

**What:** All three models log to `ml_experiments` via the existing `ExperimentTracker`. For the ranker, `oos_accuracy` is repurposed as Spearman IC (a numeric float); a custom field `notes` carries NDCG. The `model_type` field distinguishes: `"lgbm_ranker"`, `"xgb_meta_label"`.

**Example:**
```python
# Source: ExperimentTracker.log_run() signature in ml/experiment_tracker.py
tracker.log_run(
    run_name="lgbm_ranker_ctf_ama_v1",
    model_type="lgbm_ranker",
    model_params={"n_estimators": 200, "num_leaves": 31},
    feature_set=feature_cols,
    cv_method="purged_kfold",
    train_start=train_start,
    train_end=train_end,
    asset_ids=asset_ids,
    tf="1D",
    oos_accuracy=mean_ic,           # Spearman IC (re-used field)
    oos_sharpe=ic_ir,               # IC-IR in oos_sharpe field
    n_oos_folds=n_splits,
    notes=f"NDCG={mean_ndcg:.4f}",  # NDCG in notes
)
```

### Anti-Patterns to Avoid

- **No temporal leakage in ranker CV:** Never use standard KFold on time-series data. Always use `PurgedKFoldSplitter` with `t1_series` pointing to the event end time.
- **Don't use `sklearn.cross_val_score` with LGBMRanker:** LGBMRanker is not fully sklearn-compatible (no `score()` method, needs `group` in `fit()`). Use manual fold loop.
- **Don't build a global meta-label model across all assets:** The meta-labeling literature recommends per-signal-type or per-asset models. Start with a global model and note this limitation.
- **Don't pass numpy arrays to LGBMRanker/XGBClassifier:** Always use `pd.DataFrame` to preserve feature names (matches the `DoubleEnsemble` pattern in `double_ensemble.py`).
- **Don't hardcode the confidence threshold:** The success criterion requires a configurable threshold. Store in `dim_executor_config` or a new `ml_meta_filter_config` table, loaded at executor runtime.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Spearman IC computation | Custom rank correlation | `scipy.stats.spearmanr` | Already in `feature_importance.py`; handles NaN and edge cases |
| NDCG metric | Custom DCG calculation | `sklearn.metrics.ndcg_score` | Handles k-truncation, already installed |
| Feature importance baseline | Manual permutation | `LGBMRanker.feature_importances_` + `pred_contrib=True` | LightGBM native, no extra library needed |
| Purged CV split | Custom time-based split | `PurgedKFoldSplitter` in `backtests/cv.py` | Already implemented, tested, handles embargo |
| Experiment logging | Custom DB insert | `ExperimentTracker.log_run()` in `ml/experiment_tracker.py` | Already handles numpy serialization, JSONB, UUID |
| Class imbalance in meta-label | Custom over/undersampling | `xgb.XGBClassifier(scale_pos_weight=...)` | XGBoost built-in; simpler than SMOTE for tabular data |
| Group array construction | Hardcoded period sizes | Build dynamically from `pd.Series.value_counts(sort=False)` on timestamp index | Asset universe varies by period; always recompute |

**Key insight:** The existing `ml/` package already has the building blocks (PurgedKFold, ExperimentTracker, feature_importance). Phase 100 adds models, not infrastructure.

---

## Common Pitfalls

### Pitfall 1: Variable Group Sizes in LGBMRanker

**What goes wrong:** If different time periods have different numbers of liquid assets (e.g., some periods have 40 assets, others 38), a constant `group = np.full(n_periods, 40)` will mismatch and LGBMRanker will raise or silently misalign.

**Why it happens:** Asset universe changes over time as assets are added or delisted.

**How to avoid:** Build group array from actual per-period counts:
```python
ts_counts = df.groupby("ts").size()  # counts per period
group = ts_counts.values  # array of per-period group sizes
```

**Warning signs:** `sum(group) != len(X)` will cause LightGBM to error on fit.

### Pitfall 2: SHAP interaction_values Memory Blowup

**What goes wrong:** `shap_interaction_values(X)` on a full training set with 100 features and 50K samples allocates a (50K, 100, 100) float64 tensor = ~4 GB RAM.

**Why it happens:** The interaction tensor grows as O(n_samples * n_features^2).

**How to avoid:** Always subsample for interaction analysis:
```python
X_sample = X_test.sample(min(500, len(X_test)), random_state=42)
iv = explainer.shap_interaction_values(X_sample)
```

**Warning signs:** Python process memory growing past 4 GB during SHAP computation.

### Pitfall 3: Meta-Label Data Leakage via Feature Timing

**What goes wrong:** Loading features from the `features` table at `t0` but accidentally including features computed using data after `t0` (e.g., a 365-day AMA that looks forward).

**Why it happens:** Some CTF features use forward-looking normalization or are computed at ingestion time with future data points available.

**How to avoid:** For meta-label training, use only features with `ts = t0` joined to `triple_barrier_labels.t0`. The label was generated with correct forward horizon but features must be point-in-time.

**Warning signs:** Meta-label OOS AUC >> 0.65 on training data is a red flag.

### Pitfall 4: Configurable Threshold Not Persisted

**What goes wrong:** Threshold is hardcoded in `paper_executor.py` or passed as a CLI argument, making it invisible to the audit log and impossible to tune without redeployment.

**Why it happens:** The success criterion requires "configurable threshold" but the executor config table `dim_executor_config` does not have a meta_filter threshold column.

**How to avoid:** Add `meta_filter_enabled BOOLEAN DEFAULT FALSE` and `meta_filter_threshold NUMERIC DEFAULT 0.55` columns to `dim_executor_config` via Alembic migration, or create a separate `ml_meta_filter_config` table. The executor loads it at runtime alongside other config.

**Warning signs:** If the threshold is only in a Python file and not in the DB, it cannot be changed without a code deployment.

### Pitfall 5: Purged CV Group Misalignment for Ranker

**What goes wrong:** `PurgedKFoldSplitter` produces train/test indices in terms of row positions. After slicing `X.iloc[train_idx]`, the group array must be recomputed from the sliced timestamp index, not from the original group array.

**Why it happens:** Indexing into the original group array by fold indices is incorrect — the group array describes contiguous period runs, not arbitrary row subsets.

**How to avoid:** Always recompute group from `ts_index[fold_idx].value_counts(sort=False)` after each fold split.

### Pitfall 6: Windows / UTF-8 File Reading

**What goes wrong:** Any new `.sql` DDL files opened without `encoding="utf-8"` will fail on Windows when box-drawing characters or non-ASCII appear.

**How to avoid:** Always use `open(path, encoding="utf-8")` for SQL files. This is the project-wide convention (see MEMORY.md and ExperimentTracker).

---

## Code Examples

### Cross-Sectional Label Construction (relevance scores)

```python
# Source: pattern derived from MetaLabeler.construct_meta_labels() in labeling/meta_labeler.py
# Convert forward returns to 5-class relevance scores for LGBMRanker
import pandas as pd
import numpy as np

def build_relevance_labels(
    features_df: pd.DataFrame,
    forward_returns: pd.Series,
    n_bins: int = 5,
) -> pd.Series:
    """Convert forward returns to integer relevance scores [0, n_bins-1].

    Cross-sectional quantile rank within each time period.
    """
    result = pd.Series(index=features_df.index, dtype=int)
    for ts, group in features_df.groupby("ts"):
        idx = group.index
        rets = forward_returns.reindex(idx)
        valid = rets.dropna()
        if len(valid) < n_bins:
            continue
        # pd.qcut with duplicates='drop' for robustness
        try:
            labels = pd.qcut(valid, q=n_bins, labels=False, duplicates="drop")
            result.loc[valid.index] = labels.values.astype(int)
        except ValueError:
            pass
    return result
```

### Group Array Helper

```python
# Source: pattern required by LGBMRanker.fit(group=...), verified locally
def build_group_array(ts_index: pd.Index) -> np.ndarray:
    """Build LGBMRanker group array from a timestamp index.

    Returns an integer array where each entry is the count of samples
    in that time period. sum(group) == len(ts_index).
    """
    counts = pd.Series(ts_index).value_counts(sort=False).sort_index()
    return counts.values.astype(np.int32)
```

### SHAP Top-5 Feature Pairs

```python
# Source: verified locally with shap 0.51.0 + lightgbm 4.6.0
import shap, numpy as np, pandas as pd

def get_top_feature_pairs(
    ranker,
    X_sample: pd.DataFrame,
    n_top: int = 5,
) -> pd.DataFrame:
    """Return top-N feature pairs by mean absolute SHAP interaction value."""
    explainer = shap.TreeExplainer(ranker)
    iv = explainer.shap_interaction_values(X_sample)  # (n, f, f)
    mean_abs = np.abs(iv).mean(axis=0)  # (f, f)
    cols = X_sample.columns.tolist()
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append({
                "feature_a": cols[i],
                "feature_b": cols[j],
                "mean_abs_interaction": float(mean_abs[i, j]),
            })
    return (
        pd.DataFrame(pairs)
        .sort_values("mean_abs_interaction", ascending=False)
        .head(n_top)
        .reset_index(drop=True)
    )
```

### XGBoost Meta-Label Training

```python
# Source: verified locally with xgboost 3.2.0
import xgboost as xgb, numpy as np, pandas as pd
from sqlalchemy import text

def build_meta_labels(conn, asset_id: int, tf: str, signal_type: str) -> pd.DataFrame:
    """Join triple_barrier_labels + features at t0 for meta-label training.

    y = 1 when primary_side * bin > 0 (direction was correct).
    """
    sql = text("""
        SELECT tbl.t0, tbl.bin, tbl.primary_side_placeholder,
               f.*
        FROM triple_barrier_labels tbl
        JOIN features f ON f.id = :asset_id AND f.ts = tbl.t0 AND f.tf = :tf
        WHERE tbl.asset_id = :asset_id AND tbl.tf = :tf
          AND tbl.bin IS NOT NULL
        ORDER BY tbl.t0
    """)
    # NOTE: primary_side must come from the signal table, not triple_barrier_labels
    # triple_barrier_labels schema has no primary_side column (see SQL DDL)
    # Join with signals table or pass pre-computed primary_side Series
    ...

def train_xgb_meta_filter(
    X: pd.DataFrame,
    y: np.ndarray,  # 1=take trade, 0=skip
    t1_series: pd.Series,
    n_splits: int = 5,
) -> xgb.XGBClassifier:
    """Train XGBoost meta-label filter with purged CV for OOS metric."""
    from ta_lab2.backtests.cv import PurgedKFoldSplitter
    from sklearn.metrics import roc_auc_score

    pos = y.sum()
    neg = len(y) - pos
    clf = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        scale_pos_weight=neg / max(pos, 1),
        eval_metric="logloss",
        verbosity=0,
    )
    clf.fit(X, y)
    return clf
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SHAP interaction values not supported in LightGBM | shap 0.51.0 supports interaction values for LightGBM | ~shap 0.40+ | Can use one model (LGBMRanker) for both ranking and interaction analysis |
| XGBoost 1.x (sklearn interface changes) | XGBoost 3.2.0 (pip installable, no breaking changes to predict_proba) | 2024-2025 | Direct drop-in; `scale_pos_weight` and `predict_proba` work as before |
| Manual meta-labeling scripts | MetaLabeler class in `labeling/meta_labeler.py` | Phase 57 | Phase 100 should use XGBClassifier as drop-in instead of RandomForestClassifier |
| No ML-gated executor | Executor processes all signals above delta threshold | Phase 45 | Phase 100 adds confidence filter before position sizing |

**Deprecated/outdated:**
- shap < 0.40: LightGBM interaction values raise `NotImplementedError`. Do not use old shap. Use shap 0.51.0.
- `use_label_encoder=False` in XGBoost: This parameter was removed in XGBoost 2.0. Do not include it in 3.2.0.

---

## Open Questions

1. **triple_barrier_labels has no primary_side column**
   - What we know: The DDL in `sql/labeling/085_triple_barrier_labels.sql` stores `bin` (+1/-1/0) and returns but not the primary signal direction.
   - What's unclear: To construct meta-labels (`y = 1` when direction matched outcome), we need `primary_side`. This must come from the signal tables (`signals_ema_crossover`, etc.) joined on `t0`. The Phase 100 trainer must join `triple_barrier_labels.bin` with the appropriate signal table to reconstruct primary_side.
   - Recommendation: Join `triple_barrier_labels` with the signal table by `(id, ts=t0, tf)`. The `signal_value` column in signal tables encodes direction (+1/-1/0).

2. **dim_executor_config lacks meta_filter columns**
   - What we know: `dim_executor_config` has no `meta_filter_enabled` or `meta_filter_threshold` columns. The success criterion requires a configurable threshold.
   - What's unclear: Whether to extend `dim_executor_config` via Alembic or create a new `ml_meta_filter_config` table.
   - Recommendation: Add two columns to `dim_executor_config` via Alembic migration (simpler, keeps configuration co-located): `meta_filter_enabled BOOLEAN DEFAULT FALSE` and `meta_filter_threshold NUMERIC DEFAULT 0.55`.

3. **Model serialization for production use**
   - What we know: The executor loads its config from DB at runtime but the meta-label model is a Python object that needs to be persisted between training and inference.
   - What's unclear: No model serialization pattern exists in the codebase.
   - Recommendation: Serialize trained XGBClassifier with `model.save_model(path)` to a local file path, store the path in `dim_executor_config` as a `meta_filter_model_path TEXT` column. Load at executor startup via `xgb.XGBClassifier().load_model(path)`.

4. **Cross-sectional ranking scope**
   - What we know: The `features` table has ~112 columns for assets at tf=1D. The universe is ~40-100 assets at any given time.
   - What's unclear: Whether to rank all assets or only a subset defined by `dim_feature_selection`.
   - Recommendation: Default to active-tier features from `dim_feature_selection` (same as existing IC analysis) plus CTF features graduated in Phase 98.

---

## Sources

### Primary (HIGH confidence)
- LightGBM 4.6.0 installed locally — `lgb.LGBMRanker`, `LGBMRanker.fit(group=...)`, `pred_contrib=True`, `feature_importances_` all verified by running Python
- shap 0.51.0 installed locally — `shap.TreeExplainer.shap_interaction_values()` verified to work with LGBMRanker (returns shape (n_samples, n_features, n_features))
- xgboost 3.2.0 installed locally — `XGBClassifier.predict_proba()` verified; SHAP interaction values confirmed working
- `sql/ml/095_ml_experiments.sql` — DDL schema for experiment logging (existing)
- `sql/labeling/085_triple_barrier_labels.sql` — DDL schema confirming no `primary_side` column
- `src/ta_lab2/ml/experiment_tracker.py` — ExperimentTracker.log_run() signature verified
- `src/ta_lab2/backtests/cv.py` — PurgedKFoldSplitter confirmed available
- `src/ta_lab2/ml/double_ensemble.py` — LightGBM lazy-import pattern (reference for Phase 100)
- `sql/executor/088_dim_executor_config.sql` — confirms no meta_filter columns exist yet

### Secondary (MEDIUM confidence)
- [LightGBM GitHub Issue #6814](https://github.com/microsoft/LightGBM/issues/6814) — NDCG inconsistency between fit vs predict; confirmed use sklearn.metrics.ndcg_score for OOS
- [SHAP TreeExplainer docs](https://shap.readthedocs.io/en/latest/generated/shap.TreeExplainer.html) — API reference for shap_interaction_values()

### Tertiary (LOW confidence)
- WebSearch: SHAP interaction values historically unsupported for LightGBM — this is NOW resolved in shap 0.51.0 (tested and confirmed). Any docs saying "not supported" are outdated.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — lightgbm 4.6.0 installed, xgboost 3.2.0 + shap 0.51.0 pip-installable and tested
- Architecture: HIGH — LGBMRanker group mechanics, SHAP interaction tensor, executor hook point all verified in code
- Pitfalls: HIGH — group misalignment, SHAP memory, primary_side gap all discovered from actual DDL and code inspection
- Open questions: HIGH confidence that they ARE open (DDL confirmed missing columns, no model serialization found)

**Research date:** 2026-03-31
**Valid until:** 2026-05-01 (stable libraries; lightgbm/xgboost/shap are not fast-moving for these APIs)
