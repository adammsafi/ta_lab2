"""
Meta-labeling for financial machine learning.

Implements AFML Ch.10 meta-labeling pattern (Lopez de Prado, 2018).

Meta-labeling sits on top of a primary model (signal generator) and asks:
"Given that the primary model predicted direction X, should we take the trade?"

The secondary model (MetaLabeler) predicts trade probability in [0, 1]:
  - 1.0 means high confidence the primary signal direction was correct
  - 0.0 means low confidence (skip the trade)
  - Probability in (0, 1) can be used directly for position sizing

Training targets (meta-labels) are constructed as:
  y = 1 if primary_side * triple_barrier_bin > 0 else 0

That is, y=1 when the primary signal direction was correct (matched the
barrier outcome), y=0 when the primary direction was wrong.

Classes
-------
MetaLabeler
    Wraps RandomForestClassifier with StandardScaler + balanced_subsample
    class weights. Handles imbalanced label distributions (class_weight=
    "balanced_subsample" rebalances at each tree using bootstrap sample).

Functions
---------
None (all functionality in MetaLabeler class)

Notes
-----
- Use construct_meta_labels() static method to build y from signal data.
- Primary_side convention: +1 = long, -1 = short.
- Triple barrier bin convention: +1 = profit target hit, -1 = stop hit, 0 = timeout.
- Timeout events (bin=0) result in y=0 (meta-label = do not take the trade),
  because the trade did not reach its profit target.
- predict_proba() returns the P(class=1) column -- probability of trade success.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


class MetaLabeler:
    """
    Secondary model for meta-labeling over primary signal predictions.

    Wraps RandomForestClassifier with StandardScaler preprocessing.
    Uses balanced_subsample class weights to handle label imbalance
    (common in financial data where profitable trades are a minority).

    The primary signal provides direction (long/short). MetaLabeler predicts
    whether that direction was correct given the feature vector at signal time.

    Parameters
    ----------
    n_estimators : int, default 100
        Number of trees in the random forest.
    max_features : str or float, default "sqrt"
        Feature subset strategy per split. "sqrt" = sqrt(n_features).
    class_weight : str, default "balanced_subsample"
        Re-balances class weights per bootstrap sample, which improves
        recall for the minority class (positive trades) without biasing
        precision downward as much as "balanced".
    n_jobs : int, default -1
        Parallelism for fitting/predicting. -1 = use all cores.
    random_state : int, default 42
        Random seed for reproducibility.

    Attributes
    ----------
    clf_ : RandomForestClassifier
        Fitted classifier (None before fit()).
    scaler_ : StandardScaler
        Fitted scaler (None before fit()).
    feature_names_ : list of str
        Column names from training DataFrame (None before fit()).
    is_fitted_ : bool
        True after fit() has been called.

    Examples
    --------
    >>> import pandas as pd
    >>> import numpy as np
    >>> from ta_lab2.labeling.meta_labeler import MetaLabeler
    >>> from ta_lab2.labeling.triple_barrier import get_t1_series
    >>>
    >>> # Synthetic data
    >>> n = 200
    >>> rng = np.random.default_rng(42)
    >>> X = pd.DataFrame({"feat_a": rng.standard_normal(n),
    ...                   "feat_b": rng.standard_normal(n)})
    >>> y = pd.Series(rng.integers(0, 2, n))
    >>>
    >>> ml = MetaLabeler()
    >>> ml.fit(X, y)
    >>> proba = ml.predict_proba(X)
    >>> assert proba.between(0, 1).all()
    """

    def __init__(
        self,
        n_estimators: int = 100,
        max_features: str | float = "sqrt",
        class_weight: str | dict = "balanced_subsample",
        n_jobs: int = -1,
        random_state: int = 42,
    ) -> None:
        self.n_estimators = n_estimators
        self.max_features = max_features
        self.class_weight = class_weight
        self.n_jobs = n_jobs
        self.random_state = random_state

        self.clf_: Optional[RandomForestClassifier] = None
        self.scaler_: Optional[StandardScaler] = None
        self.feature_names_: Optional[list[str]] = None
        self.is_fitted_: bool = False

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "MetaLabeler":
        """
        Fit the meta-labeler on labeled training data.

        Parameters
        ----------
        X : pd.DataFrame, shape (n_samples, n_features)
            Feature matrix at signal entry timestamps.
            Rows with any NaN will be dropped automatically (logged).
        y : pd.Series, shape (n_samples,)
            Meta-labels: 1 = take trade (primary direction correct),
            0 = skip trade (primary direction was wrong).
            Index must align with X.

        Returns
        -------
        self
            Enables method chaining.

        Raises
        ------
        ValueError
            If fewer than 10 valid training samples remain after NaN removal.
        ValueError
            If y contains only one class (degenerate training set).
        """
        X_arr, y_arr = self._prepare(X, y, fit=True)

        n_classes = len(np.unique(y_arr))
        if n_classes < 2:
            raise ValueError(
                f"Training y has only {n_classes} class(es). "
                "Need at least 2 classes for classification. "
                "Check that triple barrier labels contain both +1 and -1/0 bins."
            )

        self.clf_ = RandomForestClassifier(
            n_estimators=self.n_estimators,
            max_features=self.max_features,
            class_weight=self.class_weight,
            n_jobs=self.n_jobs,
            random_state=self.random_state,
            oob_score=True,
        )
        self.clf_.fit(X_arr, y_arr)
        self.is_fitted_ = True

        oob = getattr(self.clf_, "oob_score_", None)
        oob_str = f"{oob:.4f}" if oob is not None else "N/A"
        logger.debug(
            f"MetaLabeler fitted | n_samples={len(y_arr)} | "
            f"n_features={X_arr.shape[1]} | "
            f"class_dist={dict(zip(*np.unique(y_arr, return_counts=True)))} | "
            f"oob_score={oob_str}"
        )
        return self

    def predict_proba(self, X: pd.DataFrame) -> pd.Series:
        """
        Predict trade probability (P(meta_label=1)) for each sample.

        Returns values in [0, 1] suitable for position sizing:
        - proba > 0.5  -> MetaLabeler recommends taking the trade
        - proba <= 0.5 -> MetaLabeler recommends skipping the trade

        Parameters
        ----------
        X : pd.DataFrame, shape (n_samples, n_features)
            Feature matrix at signal timestamps.
            Must have the same columns as training X.

        Returns
        -------
        pd.Series, shape (n_samples,)
            Trade probabilities in [0, 1].
            Index preserved from X.
            NaN for any row that was all-NaN in input features.

        Raises
        ------
        RuntimeError
            If fit() has not been called yet.
        """
        self._check_fitted()

        X_aligned = X.reindex(columns=self.feature_names_)

        # Rows with any NaN after reindex get NaN probability
        nan_mask = X_aligned.isnull().any(axis=1)
        result = pd.Series(np.nan, index=X.index, name="trade_probability", dtype=float)

        if (~nan_mask).sum() == 0:
            logger.warning(
                "All rows have NaN features; returning all-NaN probabilities."
            )
            return result

        X_valid = X_aligned.loc[~nan_mask].copy()
        X_scaled = self.scaler_.transform(X_valid.values)

        proba = self.clf_.predict_proba(X_scaled)
        # P(class=1) column: class order from clf_.classes_
        pos_class_idx = (
            list(self.clf_.classes_).index(1) if 1 in self.clf_.classes_ else -1
        )
        if pos_class_idx < 0:
            # Fallback: model only saw class 0 at some fold (degenerate)
            result.loc[~nan_mask] = 0.0
        else:
            result.loc[~nan_mask] = proba[:, pos_class_idx]

        return result

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> pd.Series:
        """
        Binary prediction at a configurable probability threshold.

        Parameters
        ----------
        X : pd.DataFrame, shape (n_samples, n_features)
            Feature matrix.
        threshold : float, default 0.5
            Probability cutoff. Samples with proba >= threshold get label 1.
            Lower threshold => more trades (higher recall, lower precision).

        Returns
        -------
        pd.Series of int {0, 1}
            Meta-label predictions.
            Index preserved from X.
        """
        proba = self.predict_proba(X)
        labels = (proba >= threshold).astype(int)
        labels.name = "meta_label"
        return labels

    def evaluate(self, X: pd.DataFrame, y: pd.Series) -> dict:
        """
        Evaluate meta-labeler on held-out data.

        Computes accuracy, precision, recall, F1 (all at threshold=0.5),
        and AUC-ROC (threshold-free).

        Parameters
        ----------
        X : pd.DataFrame, shape (n_samples, n_features)
        y : pd.Series, shape (n_samples,)
            True meta-labels (0 or 1).

        Returns
        -------
        dict with keys: accuracy, precision, recall, f1, auc, n_samples, n_pos
            All float values. n_samples and n_pos are ints.

        Notes
        -----
        AUC < 0.5 means the model is worse than random (negative information).
        AUC > 0.5 means the model extracts predictive signal.
        Target: AUC > 0.5 per fold (plan must_have).
        """
        self._check_fitted()

        X_aligned, y_arr = self._prepare(X, y, fit=False)
        proba_arr = self.clf_.predict_proba(X_aligned)
        pos_class_idx = (
            list(self.clf_.classes_).index(1) if 1 in self.clf_.classes_ else -1
        )
        if pos_class_idx < 0:
            proba_pos = np.zeros(len(y_arr))
        else:
            proba_pos = proba_arr[:, pos_class_idx]

        y_pred = (proba_pos >= 0.5).astype(int)

        n_samples = len(y_arr)
        n_pos = int(y_arr.sum())

        metrics = {
            "accuracy": float(accuracy_score(y_arr, y_pred)),
            "precision": float(precision_score(y_arr, y_pred, zero_division=0)),
            "recall": float(recall_score(y_arr, y_pred, zero_division=0)),
            "f1": float(f1_score(y_arr, y_pred, zero_division=0)),
            "n_samples": n_samples,
            "n_pos": n_pos,
        }

        # AUC requires both classes in y_true
        if len(np.unique(y_arr)) >= 2:
            metrics["auc"] = float(roc_auc_score(y_arr, proba_pos))
        else:
            metrics["auc"] = float("nan")
            logger.warning(
                f"evaluate(): y_true has only {len(np.unique(y_arr))} class. "
                "AUC undefined. This fold may be too small or one-sided."
            )

        return metrics

    def feature_importance(
        self, feature_names: Optional[list[str]] = None
    ) -> pd.Series:
        """
        Return feature importances sorted descending.

        Parameters
        ----------
        feature_names : list of str, optional
            Names to use. Defaults to self.feature_names_ (names from fit()).

        Returns
        -------
        pd.Series
            Feature importances (mean impurity decrease), sorted descending.
            Index = feature names.
        """
        self._check_fitted()

        names = feature_names or self.feature_names_
        importances = self.clf_.feature_importances_
        s = pd.Series(importances, index=names, name="importance")
        return s.sort_values(ascending=False)

    # ------------------------------------------------------------------
    # Static helper
    # ------------------------------------------------------------------

    @staticmethod
    def construct_meta_labels(
        primary_side: pd.Series,
        triple_barrier_bin: pd.Series,
    ) -> pd.Series:
        """
        Build binary meta-labels from primary signal direction and barrier outcomes.

        Meta-label y = 1 when primary_side * barrier_bin > 0, else 0.

        Interpretation:
        - side=+1, bin=+1 -> profit target hit when long -> y=1 (correct direction)
        - side=+1, bin=-1 -> stop loss hit when long -> y=0 (wrong direction)
        - side=+1, bin=0  -> timeout when long -> y=0 (no edge demonstrated)
        - side=-1, bin=-1 -> stop loss hit when short -> y=1 (correct: went down)
        - side=-1, bin=+1 -> profit target hit when short -> y=0 (wrong direction)
        - side=-1, bin=0  -> timeout when short -> y=0

        Parameters
        ----------
        primary_side : pd.Series of int {+1, -1}
            Primary signal direction. +1 = long, -1 = short.
        triple_barrier_bin : pd.Series of int {+1, -1, 0}
            Triple barrier outcome bin. +1 = profit target, -1 = stop, 0 = timeout.
            Must have an index compatible with primary_side (will be aligned).

        Returns
        -------
        pd.Series of int {0, 1}
            Meta-labels aligned to the inner join of primary_side and barrier_bin.
            Name = 'meta_label'.

        Notes
        -----
        Both series are aligned on their index before multiplication.
        Rows present in only one series are dropped (inner join semantics).
        """
        aligned_side, aligned_bin = primary_side.align(triple_barrier_bin, join="inner")
        product = aligned_side * aligned_bin
        meta = (product > 0).astype(int)
        meta.name = "meta_label"
        return meta

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _prepare(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series],
        fit: bool,
    ) -> tuple[np.ndarray, Optional[np.ndarray]]:
        """
        Align, drop NaN rows, scale, and optionally fit the scaler.

        Parameters
        ----------
        X : pd.DataFrame
        y : pd.Series or None
        fit : bool
            If True, fits the scaler on this data.

        Returns
        -------
        (X_scaled : np.ndarray, y_arr : np.ndarray or None)
        """
        if fit:
            self.feature_names_ = list(X.columns)

        X_aligned = X.reindex(columns=self.feature_names_)

        if y is not None:
            # Align X and y on index, then drop NaN rows in X
            X_aligned, y_aligned = X_aligned.align(y.rename("y"), axis=0, join="inner")
            y_aligned = y_aligned.to_frame()
            combined = pd.concat([X_aligned, y_aligned], axis=1).dropna()
            X_clean = combined[self.feature_names_]
            y_arr = combined["y"].values.astype(int)
        else:
            X_clean = X_aligned.dropna()
            y_arr = None

        n_before = len(X)
        n_after = len(X_clean)
        if n_before > n_after:
            logger.debug(
                f"MetaLabeler._prepare: dropped {n_before - n_after} NaN rows "
                f"({n_before} -> {n_after})"
            )

        if n_after < 10:
            raise ValueError(
                f"Too few valid samples after NaN removal: {n_after}. "
                "Need at least 10. Check data quality or reduce NaN-heavy feature columns."
            )

        X_arr = X_clean.values.astype(float)

        if fit:
            self.scaler_ = StandardScaler()
            X_scaled = self.scaler_.fit_transform(X_arr)
        else:
            X_scaled = self.scaler_.transform(X_arr)

        return X_scaled, y_arr

    def _check_fitted(self) -> None:
        """Raise RuntimeError if model has not been fitted yet."""
        if not self.is_fitted_:
            raise RuntimeError(
                "MetaLabeler is not fitted. Call fit(X, y) before predict_proba()."
            )
