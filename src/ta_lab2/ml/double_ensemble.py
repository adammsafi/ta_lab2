"""
DoubleEnsemble concept drift model using sliding-window LightGBM sub-models.

Implements a DoubleEnsemble-inspired approach for handling concept drift in
financial time series.  The core idea: financial market regimes shift over
time, so a single model trained on all history may under-weight recent
distributional changes.  DoubleEnsemble addresses this by:

1. Sliding windows — sub-models are trained on overlapping time windows of
   fixed length.  Earlier windows capture long-term patterns; later windows
   capture recent regime.
2. Sample reweighting — within each window, a first-pass model identifies
   uncertain / difficult samples (those with predictions near 0.5 confidence).
   A second-pass model is then trained with those samples up-weighted, forcing
   the learner to focus on harder examples.
3. Recency weighting — during prediction, later windows receive higher weight
   so that the ensemble's output is biased toward recent market structure.

References
----------
Qlib DoubleEnsemble: https://github.com/microsoft/qlib/tree/main/examples/benchmarks/DoubleEnsemble
LightGBM sample_weight: https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMClassifier.html

Notes
-----
LightGBM is imported lazily inside ``fit()`` and ``predict_proba()`` so that
this module is importable even if LightGBM is not installed.  An informative
``ImportError`` is raised at call time rather than import time.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_LGBM_MIN_VERSION = "4.6.0"
_LGBM_INSTALL_MSG = (
    f"LightGBM >= {_LGBM_MIN_VERSION} is required for DoubleEnsemble. "
    "Install it with: pip install lightgbm==4.6.0"
)

# Default LightGBM hyperparameters — conservative settings suitable for
# short financial time-series windows (60–120 bars).
_DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 100,
    "num_leaves": 20,
    "learning_rate": 0.05,
    "verbose": -1,
}


class DoubleEnsemble:
    """
    Sliding-window LightGBM ensemble with sample reweighting and recency weighting.

    Each sub-model is trained on a fixed-length window of the training data.
    Within each window a two-round training procedure upweights uncertain
    samples.  During prediction, each sub-model's probability output is
    weighted by its window's recency (how close the window end is to the
    end of the full training period).

    Parameters
    ----------
    window_size : int, default 60
        Number of rows per sliding window.  Should be large enough for the
        LightGBM base learner to generalise (recommended >= 30 bars).
    stride : int, default 15
        Step size between windows.  Smaller stride = more sub-models =
        higher compute cost.
    base_params : dict or None, default None
        LightGBM hyperparameter dict passed to ``LGBMClassifier``.
        When None, uses the internal defaults (100 trees, 20 leaves, lr=0.05).

    Attributes
    ----------
    models : list[tuple[LGBMClassifier, float]]
        List of (fitted sub-model, recency_weight) pairs populated after
        ``fit()``.
    classes_ : np.ndarray or None
        Unique class labels seen during training.

    Examples
    --------
    >>> import pandas as pd, numpy as np
    >>> np.random.seed(0)
    >>> n = 200
    >>> X = pd.DataFrame({'f1': np.random.randn(n), 'f2': np.random.randn(n)})
    >>> y = (X['f1'] > 0).astype(int).values
    >>> de = DoubleEnsemble(window_size=60, stride=15)
    >>> de.fit(X, y)
    DoubleEnsemble(window_size=60, stride=15, n_sub_models=...)
    >>> proba = de.predict_proba(X)
    >>> proba.shape
    (200, 2)
    """

    def __init__(
        self,
        window_size: int = 60,
        stride: int = 15,
        base_params: dict[str, Any] | None = None,
    ) -> None:
        self.window_size = window_size
        self.stride = stride
        self.base_params: dict[str, Any] = (
            dict(base_params) if base_params is not None else dict(_DEFAULT_PARAMS)
        )
        self.models: list[tuple[Any, float]] = []
        self.classes_: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "DoubleEnsemble":
        """
        Train sliding-window sub-models with sample reweighting.

        For each window of size ``window_size``, two LGBMClassifier models
        are trained:

        * Round 1: baseline fit on the window
        * Round 2: fit with sample weights that upweight uncertain samples
          (those where the Round 1 model predicted close to 0.5)

        Only the Round 2 model is retained.  Windows with a single class are
        skipped because LightGBM requires at least two classes.

        Falls back to a single global model if no valid sliding window exists
        (i.e., the dataset is shorter than ``window_size``).

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix, shape (n_samples, n_features).  Must be a
            DataFrame — not a numpy array — so LightGBM retains feature names.
        y : np.ndarray
            Integer label array, shape (n_samples,).

        Returns
        -------
        DoubleEnsemble
            self, to allow method chaining.

        Raises
        ------
        TypeError
            If X is not a pandas DataFrame.
        ImportError
            If LightGBM is not installed.
        """
        try:
            import lightgbm as lgb  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(_LGBM_INSTALL_MSG) from exc

        if not isinstance(X, pd.DataFrame):
            raise TypeError(
                f"X must be a pandas DataFrame, got {type(X).__name__}. "
                "Pass DataFrames (not numpy arrays) to preserve feature names."
            )

        y = np.asarray(y)
        self.classes_ = np.unique(y)
        n = len(X)
        self.models = []

        # Generate window start indices
        window_starts = list(range(0, n - self.window_size + 1, self.stride))

        for start in window_starts:
            end = start + self.window_size
            X_win = X.iloc[start:end]
            y_win = y[start:end]

            # Skip windows with only one class — LightGBM cannot learn
            unique_classes = np.unique(y_win)
            if len(unique_classes) < 2:
                logger.debug(
                    "Window [%d:%d] skipped — single class %s",
                    start,
                    end,
                    unique_classes,
                )
                continue

            # Round 1: baseline model to identify uncertain samples
            clf1 = lgb.LGBMClassifier(random_state=42, **self.base_params)
            clf1.fit(X_win, y_win)

            # Compute sample weights: upweight uncertain / difficult samples
            sample_weights = self._compute_sample_weights(clf1, X_win, y_win)

            # Round 2: model trained with reweighted samples
            clf2 = lgb.LGBMClassifier(random_state=43, **self.base_params)
            clf2.fit(X_win, y_win, sample_weight=sample_weights)

            # Recency weight: later windows (higher `end`) get higher weight
            recency_weight = end / n
            self.models.append((clf2, recency_weight))

            logger.debug(
                "Window [%d:%d] trained. recency_weight=%.4f",
                start,
                end,
                recency_weight,
            )

        # Edge case: dataset shorter than window_size — train a single global model
        if not self.models:
            logger.warning(
                "No valid sliding windows found (n=%d < window_size=%d). "
                "Falling back to single global model.",
                n,
                self.window_size,
            )
            unique_classes = np.unique(y)
            if len(unique_classes) >= 2:
                clf_global = lgb.LGBMClassifier(random_state=42, **self.base_params)
                clf_global.fit(X, y)
                self.models.append((clf_global, 1.0))
            else:
                logger.warning(
                    "Global fallback skipped — only one class in full dataset."
                )

        logger.info(
            "DoubleEnsemble fit complete: %d sub-models from %d windows.",
            len(self.models),
            len(window_starts),
        )
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Compute recency-weighted average of sub-model class probabilities.

        Each sub-model's predicted probability matrix is weighted by its
        ``recency_weight``.  Weights are normalised so they sum to 1.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix, shape (n_samples, n_features).  Must be a
            DataFrame to avoid LightGBM feature-name warnings.

        Returns
        -------
        np.ndarray
            Probability matrix of shape (n_samples, n_classes).

        Raises
        ------
        RuntimeError
            If ``fit()`` has not been called yet.
        ImportError
            If LightGBM is not installed.
        """
        try:
            import lightgbm as lgb  # noqa: PLC0415, F401
        except ImportError as exc:
            raise ImportError(_LGBM_INSTALL_MSG) from exc

        if not self.models:
            raise RuntimeError(
                "DoubleEnsemble has no trained sub-models. Call fit() first."
            )

        if not isinstance(X, pd.DataFrame):
            raise TypeError(f"X must be a pandas DataFrame, got {type(X).__name__}.")

        # Normalise recency weights so they sum to 1
        raw_weights = np.array([w for _, w in self.models], dtype=float)
        weights = raw_weights / raw_weights.sum()

        # Determine number of classes from first sub-model
        n_classes = len(self.models[0][0].classes_)
        proba = np.zeros((len(X), n_classes), dtype=float)

        for (clf, _), w in zip(self.models, weights):
            proba += w * clf.predict_proba(X)

        return proba

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict class labels using recency-weighted ensemble probabilities.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix, shape (n_samples, n_features).

        Returns
        -------
        np.ndarray
            Predicted class labels, shape (n_samples,), using ``classes_``
            values (not necessarily 0/1 integers if the training labels were
            different).

        Raises
        ------
        RuntimeError
            If ``fit()`` has not been called yet.
        """
        if self.classes_ is None:
            raise RuntimeError("DoubleEnsemble has not been fitted. Call fit() first.")
        proba = self.predict_proba(X)
        class_indices = np.argmax(proba, axis=1)
        return self.classes_[class_indices]

    def get_model_info(self) -> dict[str, Any]:
        """
        Return a summary of the fitted ensemble.

        Returns
        -------
        dict
            Keys: ``n_sub_models``, ``window_size``, ``stride``,
            ``recency_weights``, ``classes``, ``base_params``.
        """
        recency_weights = [float(w) for _, w in self.models]
        return {
            "n_sub_models": len(self.models),
            "window_size": self.window_size,
            "stride": self.stride,
            "recency_weights": recency_weights,
            "classes": self.classes_.tolist() if self.classes_ is not None else None,
            "base_params": dict(self.base_params),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_sample_weights(
        self,
        clf: Any,
        X: pd.DataFrame,
        y: np.ndarray,
    ) -> np.ndarray:
        """
        Compute per-sample weights that upweight uncertain / difficult samples.

        Uncertainty is measured as 1 - |p - 0.5| where p is the model's
        predicted probability for class 1.  Samples with p near 0.5 (max
        uncertainty) receive the highest weight; samples with p near 0 or 1
        (high confidence) receive the lowest weight.

        Weights are normalised so that they sum to ``len(X)`` (equivalent to
        uniform weights of 1.0 per sample).  This preserves the effective
        sample size signal while re-distributing focus toward harder examples.

        Parameters
        ----------
        clf : fitted LGBMClassifier
            First-round model to assess per-sample confidence.
        X : pd.DataFrame
            Feature matrix (same window slice that trained ``clf``).
        y : np.ndarray
            Label array for the same window slice.

        Returns
        -------
        np.ndarray
            Weight array, shape (n_samples,).  All values > 0.
        """
        proba = clf.predict_proba(X)
        # Confidence: distance from 0.5 — 0 = maximally uncertain, 0.5 = certain
        confidence = np.abs(proba[:, 1] - 0.5)
        # Invert so uncertain samples get higher weight
        weights = 1.0 - confidence
        # Guard against all-zero edge case (shouldn't happen but defensive)
        total = weights.sum()
        if total <= 0:
            return np.ones(len(X), dtype=float)
        # Normalise: weights sum to n_samples (matches sklearn sample_weight convention)
        weights = weights / total * len(X)
        return weights

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"DoubleEnsemble("
            f"window_size={self.window_size}, "
            f"stride={self.stride}, "
            f"n_sub_models={len(self.models)})"
        )
