"""
Regime-routed model dispatcher using regimes L2 labels.

Implements the Temporal Routing Adaptor (TRA) pattern from Qlib: a router
that selects per-regime expert sub-models at prediction time.  Each regime
(e.g., 'Up', 'Down', 'Sideways') gets its own cloned and fitted estimator;
a global fallback handles unseen or low-sample regimes.

Architecture
------------
- ``load_regimes``: SQL query on ``public.regimes`` → pd.Series of L2 labels
- ``RegimeRouter``: wraps any sklearn-compatible estimator; dispatches fit/
  predict/predict_proba calls per regime with a global ``__global__`` fallback

References
----------
Yang, H. et al. (2021). *Qlib: An AI-oriented Quantitative Investment Platform*.
    https://arxiv.org/abs/2009.11189  (Temporal Routing Adaptor, Section 3.3)

Notes
-----
CRITICAL: Always pass DataFrame slices (not numpy arrays) to model.fit/predict
to avoid LightGBM feature-name warnings.

CRITICAL: Use pd.to_datetime(utc=True) for ts column (MEMORY.md Windows pitfall).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------


def load_regimes(
    conn: Any,
    asset_id: int,
    tf: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.Series:
    """Load L2 regime labels from ``public.regimes``.

    Parameters
    ----------
    conn:
        SQLAlchemy connection (or engine-level connection object).
    asset_id:
        Integer CMC asset ID.
    tf:
        Timeframe string (e.g. ``'1D'``, ``'4H'``).
    start, end:
        Inclusive date range for the query (UTC-aware or date strings).

    Returns
    -------
    pd.Series
        Index = UTC-aware timestamps (ts), values = L2 label strings.
        Unknown / NULL labels are filled with ``'Unknown'``.
    """
    sql = """
        SELECT ts, l2_label
        FROM public.regimes
        WHERE id = :id
          AND tf = :tf
          AND ts BETWEEN :start AND :end
        ORDER BY ts
    """
    # Use pd.read_sql with named params (MEMORY.md: use utc=True)
    from sqlalchemy import text

    result = conn.execute(
        text(sql),
        {"id": asset_id, "tf": tf, "start": str(start), "end": str(end)},
    )
    rows = result.fetchall()

    if not rows:
        logger.warning(
            "load_regimes: no regime rows found for asset_id=%d, tf=%s, %s to %s",
            asset_id,
            tf,
            start,
            end,
        )
        return pd.Series(dtype=str, name="l2_label")

    df = pd.DataFrame(rows, columns=["ts", "l2_label"])
    # CRITICAL: UTC-aware timestamp (MEMORY.md Windows pitfall)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")

    series = df["l2_label"].fillna("Unknown")
    logger.info(
        "load_regimes: loaded %d rows for asset_id=%d tf=%s",
        len(series),
        asset_id,
        tf,
    )
    return series


# ---------------------------------------------------------------------------
# RegimeRouter
# ---------------------------------------------------------------------------


class RegimeRouter:
    """Route predictions to per-regime expert sub-models.

    Each unique regime value (from ``regimes`` Series) gets its own cloned
    and independently fitted copy of ``base_model``.  A ``'__global__'``
    fallback is always trained on all data and used for unseen regimes or
    regimes with fewer than ``min_samples`` training examples.

    Parameters
    ----------
    base_model:
        Any sklearn-compatible estimator (RandomForestClassifier, LGBMClassifier,
        etc.).  Cloned via ``sklearn.base.clone`` for each regime and for the
        global fallback — the original is never mutated.
    min_samples:
        Minimum training samples required before a regime gets its own sub-model.
        Regimes with fewer samples fall back to ``'__global__'``.
        Default: 30.
    regime_col:
        Name stored in ``get_regime_stats()`` output for documentation.
        Default: ``'l2_label'``.

    Attributes
    ----------
    models : dict[str, estimator]
        Fitted models keyed by regime string plus ``'__global__'``.
    regime_sample_counts : dict[str, int]
        Training sample count per regime (before any fallback decision).
    """

    def __init__(
        self,
        base_model: Any,
        min_samples: int = 30,
        regime_col: str = "l2_label",
    ) -> None:
        self.base_model = base_model
        self.min_samples = min_samples
        self.regime_col = regime_col

        # Populated by fit()
        self.models: dict[str, Any] = {}
        self.regime_sample_counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        regimes: pd.Series,
    ) -> "RegimeRouter":
        """Fit per-regime sub-models and the global fallback.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix.  Must be a DataFrame (not numpy array) so that
            column names are preserved for LightGBM compatibility.
        y : np.ndarray
            Label array, shape (n_samples,).
        regimes : pd.Series
            Regime label for each row in X (same index/length as X).
            Values are strings such as ``'Up'``, ``'Down'``, ``'Sideways'``.

        Returns
        -------
        self
        """
        if len(X) != len(regimes):
            raise ValueError(
                f"X ({len(X)} rows) and regimes ({len(regimes)} rows) must have "
                "the same length."
            )

        # Reset state
        self.models = {}
        self.regime_sample_counts = {}

        # Always train global fallback on ALL data first
        logger.info("RegimeRouter: fitting __global__ fallback on %d samples", len(X))
        global_model = clone(self.base_model)
        # CRITICAL: pass DataFrame slice, not numpy array
        global_model.fit(X, y)
        self.models["__global__"] = global_model

        # Align regimes to X index if both are index-aligned Series/DataFrame
        regimes_values = np.asarray(regimes)

        unique_regimes = np.unique(regimes_values)
        for regime in unique_regimes:
            mask = regimes_values == regime
            n = int(mask.sum())
            self.regime_sample_counts[str(regime)] = n

            if n < self.min_samples:
                logger.info(
                    "RegimeRouter: regime=%r has %d samples < min_samples=%d, "
                    "will use __global__ fallback",
                    regime,
                    n,
                    self.min_samples,
                )
                continue

            logger.info(
                "RegimeRouter: fitting sub-model for regime=%r (%d samples)",
                regime,
                n,
            )
            m = clone(self.base_model)
            # CRITICAL: always pass DataFrame slice
            m.fit(X.iloc[mask] if hasattr(X, "iloc") else X[mask], y[mask])
            self.models[str(regime)] = m

        trained_regimes = [k for k in self.models if k != "__global__"]
        logger.info(
            "RegimeRouter: fit complete. Trained sub-models: %s. "
            "Fallback (__global__) always available.",
            trained_regimes,
        )
        return self

    # ------------------------------------------------------------------
    # Prediction helpers
    # ------------------------------------------------------------------

    def _get_model_for_regime(self, regime: str) -> Any:
        """Return sub-model for regime, or __global__ fallback."""
        if regime in self.models:
            return self.models[regime]
        return self.models["__global__"]

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(
        self,
        X: pd.DataFrame,
        regimes: pd.Series,
    ) -> np.ndarray:
        """Predict labels routing each sample to its regime sub-model.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix (same columns used in fit).
        regimes : pd.Series
            Regime label per row (same order/length as X).

        Returns
        -------
        np.ndarray
            Predicted labels, shape (n_samples,).  Dtype matches ``y`` from fit.
        """
        if not self.models:
            raise RuntimeError("RegimeRouter.fit() must be called before predict().")

        regimes_values = np.asarray(regimes)
        result = np.empty(len(X), dtype=object)

        unique_regimes = np.unique(regimes_values)
        for regime in unique_regimes:
            mask = regimes_values == str(regime)
            model = self._get_model_for_regime(str(regime))
            X_regime = X.iloc[mask] if hasattr(X, "iloc") else X[mask]
            preds = model.predict(X_regime)
            result[mask] = preds

        # Try to cast to the natural dtype (int/float) if homogeneous
        try:
            result = result.astype(int)
        except (ValueError, TypeError):
            pass

        return result

    def predict_proba(
        self,
        X: pd.DataFrame,
        regimes: pd.Series,
    ) -> np.ndarray:
        """Predict class probabilities routing each sample to its regime sub-model.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix.
        regimes : pd.Series
            Regime label per row.

        Returns
        -------
        np.ndarray
            Probability matrix, shape (n_samples, n_classes).
            Class order follows the global model's ``classes_`` attribute.
        """
        if not self.models:
            raise RuntimeError(
                "RegimeRouter.fit() must be called before predict_proba()."
            )

        # Determine n_classes from the global model
        global_model = self.models["__global__"]
        if not hasattr(global_model, "predict_proba"):
            raise AttributeError(
                "base_model does not support predict_proba. "
                "Use a probabilistic classifier (e.g., RandomForestClassifier)."
            )
        n_classes = len(global_model.classes_)

        regimes_values = np.asarray(regimes)
        result = np.zeros((len(X), n_classes), dtype=float)

        unique_regimes = np.unique(regimes_values)
        for regime in unique_regimes:
            mask = regimes_values == str(regime)
            model = self._get_model_for_regime(str(regime))
            X_regime = X.iloc[mask] if hasattr(X, "iloc") else X[mask]
            proba = model.predict_proba(X_regime)
            result[mask] = proba

        return result

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_regime_stats(self) -> dict:
        """Return a summary dict of fitted models and sample counts.

        Returns
        -------
        dict
            Keys:
            - ``'fitted_regimes'``: list of regime names that have sub-models
            - ``'fallback_regimes'``: list of regimes that fall back to __global__
            - ``'sample_counts'``: dict of regime → n_training_samples
            - ``'min_samples'``: the configured threshold
            - ``'global_trained'``: bool, always True after fit()
        """
        trained = [k for k in self.models if k != "__global__"]
        fallback = [
            r for r, n in self.regime_sample_counts.items() if n < self.min_samples
        ]
        return {
            "fitted_regimes": trained,
            "fallback_regimes": fallback,
            "sample_counts": dict(self.regime_sample_counts),
            "min_samples": self.min_samples,
            "global_trained": "__global__" in self.models,
        }
