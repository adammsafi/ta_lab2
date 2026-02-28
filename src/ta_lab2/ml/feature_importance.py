"""
Feature importance methods for financial ML — MDA, SFI, and clustered FI.

Implements three complementary approaches from Advances in Financial Machine
Learning (Lopez de Prado, 2018), Chapter 8:

Mean Decrease Accuracy (MDA)
    Permutation-based, out-of-sample, model-agnostic.  For each CV fold, the
    fitted model is evaluated on the held-out test set; then each feature is
    randomly permuted and the drop in score is recorded as that feature's
    importance.  Averaged across folds.  Uses ``sklearn.inspection.
    permutation_importance`` combined with ``PurgedKFoldSplitter`` for
    leakage-free estimates.

Single Feature Importance (SFI)
    A separate model is trained on each feature in isolation.  OOS accuracy
    is its importance score.  Eliminates the substitution effect entirely —
    each feature is measured independently of all others.  Reveals genuinely
    independent signal vs redundant features.

Clustered FI
    Groups highly correlated features via Spearman correlation + Ward
    hierarchical clustering.  MDA is then computed by permuting *all* features
    in a cluster simultaneously, which avoids the substitution effect for
    correlated feature groups (e.g., multiple EMA periods).

References
----------
Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Chapter 8: Feature Importance.
sklearn.inspection.permutation_importance
    https://scikit-learn.org/stable/modules/permutation_importance.html
scipy.cluster.hierarchy
    https://docs.scipy.org/doc/scipy/reference/cluster.hierarchy.html
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform
from scipy.stats import spearmanr
from sklearn.base import clone
from sklearn.inspection import permutation_importance
from sklearn.metrics import accuracy_score

from ta_lab2.backtests.cv import PurgedKFoldSplitter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MDA — Mean Decrease Accuracy
# ---------------------------------------------------------------------------


def compute_mda(
    model: Any,
    X: pd.DataFrame,
    y: np.ndarray,
    t1_series: pd.Series,
    n_splits: int = 5,
    n_repeats: int = 10,
    scoring: str = "accuracy",
) -> pd.Series:
    """
    Compute Mean Decrease Accuracy (MDA) feature importance.

    For each purged CV fold, fits a cloned model on the training set and calls
    ``sklearn.inspection.permutation_importance`` on the held-out test fold.
    Fold-level importance vectors are averaged to produce a final ranking.

    Parameters
    ----------
    model : sklearn estimator
        Any fitted or unfitted sklearn-compatible classifier/regressor.
        A fresh clone is created for each fold.
    X : pd.DataFrame
        Feature matrix, shape (n_samples, n_features).  Must be a DataFrame
        so that feature names are preserved through permutation_importance.
    y : np.ndarray
        Label array, shape (n_samples,).
    t1_series : pd.Series
        Label-end timestamps.  Index = label-start timestamps (monotonically
        increasing), values = label-end timestamps.  Passed to
        ``PurgedKFoldSplitter`` for leakage-free splits.
    n_splits : int, default 5
        Number of purged CV folds.
    n_repeats : int, default 10
        Number of permutation repeats per feature per fold.  Higher values
        reduce variance at the cost of runtime.
    scoring : str, default 'accuracy'
        Scoring metric for permutation_importance.  Any sklearn scorer string.

    Returns
    -------
    pd.Series
        Per-feature importance scores averaged across valid folds, sorted
        descending.  Index = X.columns.  Returns zeros if no valid folds
        were found (e.g., all training sets were purged away).
    """
    cv = PurgedKFoldSplitter(
        n_splits=n_splits,
        t1_series=t1_series,
        embargo_frac=0.01,
    )

    fold_importances: list[np.ndarray] = []
    n_valid_folds = 0

    for fold_num, (train_idx, test_idx) in enumerate(cv.split(X.values)):
        # CRITICAL: empty fold guard — purge can exhaust all training samples
        # on small datasets or when embargo_frac is large relative to fold size.
        if len(train_idx) == 0 or len(test_idx) == 0:
            logger.info(
                "MDA fold %d/%d skipped (train=%d, test=%d)",
                fold_num + 1,
                n_splits,
                len(train_idx),
                len(test_idx),
            )
            continue

        logger.info(
            "MDA fold %d/%d: train=%d, test=%d",
            fold_num + 1,
            n_splits,
            len(train_idx),
            len(test_idx),
        )

        # Always pass DataFrame slices to avoid feature-name warnings
        m = clone(model)
        m.fit(X.iloc[train_idx], y[train_idx])

        result = permutation_importance(
            m,
            X.iloc[test_idx],
            y[test_idx],
            n_repeats=n_repeats,
            random_state=42,
            scoring=scoring,
        )
        fold_importances.append(result.importances_mean)
        n_valid_folds += 1

    if not fold_importances:
        logger.warning(
            "MDA: no valid folds produced (all purged). Returning zero importance."
        )
        return pd.Series(0.0, index=X.columns)

    logger.info("MDA complete: %d valid folds used.", n_valid_folds)
    mean_importance = np.mean(fold_importances, axis=0)
    return pd.Series(mean_importance, index=X.columns).sort_values(ascending=False)


# ---------------------------------------------------------------------------
# SFI — Single Feature Importance
# ---------------------------------------------------------------------------


def compute_sfi(
    model: Any,
    X: pd.DataFrame,
    y: np.ndarray,
    t1_series: pd.Series,
    n_splits: int = 5,
    scoring: str = "accuracy",
) -> pd.Series:
    """
    Compute Single Feature Importance (SFI).

    Each feature is evaluated in isolation: a cloned model is trained on
    ``X[[col]]`` across purged CV folds, and OOS accuracy is averaged.
    Eliminates all substitution effects — each feature is scored independently.

    Parameters
    ----------
    model : sklearn estimator
        Any sklearn-compatible classifier/regressor.
    X : pd.DataFrame
        Feature matrix, shape (n_samples, n_features).
    y : np.ndarray
        Label array, shape (n_samples,).
    t1_series : pd.Series
        Label-end timestamps for PurgedKFoldSplitter.
    n_splits : int, default 5
        Number of purged CV folds.
    scoring : str, default 'accuracy'
        Scoring metric.  Currently uses accuracy_score internally;
        ``scoring`` parameter is kept for API symmetry with compute_mda.

    Returns
    -------
    pd.Series
        Per-feature OOS accuracy score, sorted descending.
        Index = X.columns.
    """
    cv = PurgedKFoldSplitter(
        n_splits=n_splits,
        t1_series=t1_series,
        embargo_frac=0.01,
    )

    sfi_scores: dict[str, float] = {}

    for col_num, col in enumerate(X.columns):
        logger.info(
            "SFI feature %d/%d: %s",
            col_num + 1,
            len(X.columns),
            col,
        )
        # Single-column DataFrame preserves feature-name contract for estimators
        X_single = X[[col]]
        fold_scores: list[float] = []

        for fold_num, (train_idx, test_idx) in enumerate(cv.split(X_single.values)):
            # CRITICAL: empty fold guard
            if len(train_idx) == 0 or len(test_idx) == 0:
                logger.debug(
                    "SFI [%s] fold %d/%d skipped (train=%d, test=%d)",
                    col,
                    fold_num + 1,
                    n_splits,
                    len(train_idx),
                    len(test_idx),
                )
                continue

            # Always pass DataFrame slices — not numpy arrays
            m = clone(model)
            m.fit(X_single.iloc[train_idx], y[train_idx])
            pred = m.predict(X_single.iloc[test_idx])
            fold_scores.append(float(accuracy_score(y[test_idx], pred)))

        sfi_scores[col] = float(np.mean(fold_scores)) if fold_scores else 0.0

    return pd.Series(sfi_scores).sort_values(ascending=False)


# ---------------------------------------------------------------------------
# Clustered feature grouping
# ---------------------------------------------------------------------------


def cluster_features(
    X: pd.DataFrame,
    threshold: float = 0.5,
) -> dict[str, list[str]]:
    """
    Group features by Spearman correlation using Ward hierarchical clustering.

    Addresses the substitution effect: correlated features (e.g., ``ema_9``
    and ``ema_21``) appear unimportant in standard MDA because permuting one
    leaves the other intact.  Grouping them and permuting the entire cluster
    simultaneously gives a correct importance estimate.

    Parameters
    ----------
    X : pd.DataFrame
        Feature matrix.  All columns are treated as features.
    threshold : float, default 0.5
        Distance threshold passed to ``scipy.cluster.hierarchy.fcluster``
        with ``criterion='distance'``.  Lower values produce more, smaller
        clusters; higher values produce fewer, larger clusters.

    Returns
    -------
    dict[str, list[str]]
        Mapping from ``cluster_{id}`` to the list of feature column names in
        that cluster.  Single-feature DataFrames return one cluster containing
        all columns.

    Notes
    -----
    The Spearman correlation matrix is symmetrized and the diagonal set to 1.0
    before computing the distance matrix ``1 - |corr|`` to ensure valid input
    to ``squareform``.
    """
    n_features = X.shape[1]

    # Edge case: single feature — return trivially
    if n_features == 1:
        return {"cluster_1": list(X.columns)}

    # Spearman rank correlation — robust to monotone non-linear relationships
    corr_result = spearmanr(X)
    corr = np.array(corr_result.statistic)

    # Ensure the result is 2-D (spearmanr returns a scalar for 2-column input)
    if corr.ndim == 0:
        corr = np.array([[1.0, float(corr)], [float(corr), 1.0]])

    # Symmetrize and enforce diagonal = 1 to guard against floating-point drift
    corr = (corr + corr.T) / 2.0
    np.fill_diagonal(corr, 1.0)

    # Distance matrix: 0 = identical, 1 = uncorrelated, 2 = anti-correlated
    distance_matrix = 1.0 - np.abs(corr)

    # Ward linkage on the condensed distance matrix
    dist_linkage = hierarchy.ward(squareform(distance_matrix))

    # Cut dendrogram at threshold to assign cluster IDs
    cluster_ids = hierarchy.fcluster(dist_linkage, t=threshold, criterion="distance")

    groups: dict[str, list[str]] = defaultdict(list)
    for col, cid in zip(X.columns, cluster_ids):
        groups[f"cluster_{cid}"].append(col)

    return dict(groups)


# ---------------------------------------------------------------------------
# Clustered MDA
# ---------------------------------------------------------------------------


def compute_clustered_mda(
    model: Any,
    X: pd.DataFrame,
    y: np.ndarray,
    t1_series: pd.Series,
    n_splits: int = 5,
    n_repeats: int = 10,
    scoring: str = "accuracy",
    cluster_threshold: float = 0.5,
) -> pd.DataFrame:
    """
    Compute MDA with cluster-level permutation to address substitution effects.

    Instead of permuting one feature at a time, all features in a cluster are
    permuted simultaneously.  This avoids the situation where a correlated
    feature "covers" for its permuted sibling, making both appear unimportant.

    Algorithm
    ---------
    1. Cluster features via ``cluster_features(X, threshold=cluster_threshold)``.
    2. For each cluster:
       a. Build a copy of ``X`` where *all* columns in the cluster are replaced
          by their permuted versions simultaneously.
       b. Measure the drop in model score vs baseline.
       c. Average drop across ``n_repeats`` permutations and ``n_splits`` folds.
    3. Return a DataFrame mapping each cluster to its importance.

    Parameters
    ----------
    model : sklearn estimator
    X : pd.DataFrame
    y : np.ndarray
    t1_series : pd.Series
    n_splits : int, default 5
    n_repeats : int, default 10
    scoring : str, default 'accuracy'
    cluster_threshold : float, default 0.5
        Passed to cluster_features as the Ward distance cut threshold.

    Returns
    -------
    pd.DataFrame
        Columns: ``cluster_id``, ``features``, ``importance_mean``.
        One row per cluster, sorted by importance_mean descending.
    """
    clusters = cluster_features(X, threshold=cluster_threshold)

    cv = PurgedKFoldSplitter(
        n_splits=n_splits,
        t1_series=t1_series,
        embargo_frac=0.01,
    )

    # Pre-fit models on each fold; record baseline OOS score
    fold_models: list[tuple[Any, np.ndarray, np.ndarray]] = []  # (model, train_idx, test_idx)

    for fold_num, (train_idx, test_idx) in enumerate(cv.split(X.values)):
        if len(train_idx) == 0 or len(test_idx) == 0:
            logger.info(
                "Clustered MDA fold %d/%d skipped (train=%d, test=%d)",
                fold_num + 1,
                n_splits,
                len(train_idx),
                len(test_idx),
            )
            continue

        m = clone(model)
        m.fit(X.iloc[train_idx], y[train_idx])
        fold_models.append((m, train_idx, test_idx))

    if not fold_models:
        logger.warning("Clustered MDA: no valid folds. Returning zero importance.")
        records = [
            {
                "cluster_id": cid,
                "features": feats,
                "importance_mean": 0.0,
            }
            for cid, feats in clusters.items()
        ]
        return pd.DataFrame(records).sort_values("importance_mean", ascending=False).reset_index(drop=True)

    records: list[dict] = []

    for cid, cluster_cols in clusters.items():
        logger.info("Clustered MDA: cluster=%s features=%s", cid, cluster_cols)

        cluster_drop_per_fold: list[float] = []

        for m, train_idx, test_idx in fold_models:
            X_test = X.iloc[test_idx]
            y_test = y[test_idx]

            # Baseline OOS accuracy (no permutation)
            baseline_score = float(
                accuracy_score(y_test, m.predict(X_test))
            )

            # Permute all cluster columns simultaneously, n_repeats times
            repeat_drops: list[float] = []
            for _ in range(n_repeats):
                X_permuted = X_test.copy()
                rng = np.random.default_rng(42)
                perm_order = rng.permutation(len(X_test))
                for col in cluster_cols:
                    X_permuted[col] = X_test[col].values[perm_order]

                permuted_score = float(
                    accuracy_score(y_test, m.predict(X_permuted))
                )
                repeat_drops.append(baseline_score - permuted_score)

            cluster_drop_per_fold.append(float(np.mean(repeat_drops)))

        importance_mean = float(np.mean(cluster_drop_per_fold)) if cluster_drop_per_fold else 0.0
        records.append(
            {
                "cluster_id": cid,
                "features": cluster_cols,
                "importance_mean": importance_mean,
            }
        )

    result_df = (
        pd.DataFrame(records)
        .sort_values("importance_mean", ascending=False)
        .reset_index(drop=True)
    )

    logger.info("Clustered MDA complete: %d clusters evaluated.", len(records))
    return result_df
