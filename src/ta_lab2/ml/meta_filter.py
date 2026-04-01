"""XGBoost meta-label confidence filter for the paper executor.

Implements the ML-03 requirement: a secondary XGBoost classifier that
predicts P(trade success) using triple-barrier labels as the training target.
Trades with predicted confidence below a configurable threshold are skipped
before they reach the sizing and order-generation stages of the executor.

Architecture
------------
- Training target: binary classification where y=1 means the triple-barrier
  label ``bin > 0`` (profit target hit), y=0 otherwise (stop or timeout).
  No ``primary_side`` column is required -- the target is model-agnostic.
- Features: point-in-time feature values from the ``features`` table joined
  on (asset_id, tf, t0=ts). Only features in ``dim_feature_selection``
  (tier='active') are used so feature set matches the live executor inputs.
- Cross-validation: PurgedKFoldSplitter avoids look-ahead leakage from
  overlapping triple-barrier label windows.
- Class imbalance: scale_pos_weight = neg/pos passed to XGBClassifier.

Lazy imports
------------
``xgboost`` is imported lazily inside methods. If not installed, an
``ImportError`` with an informative message is raised at call time (not at
import time), so the rest of the ta_lab2 package is unaffected.

Usage
-----
    from ta_lab2.ml.meta_filter import MetaLabelFilter

    flt = MetaLabelFilter(engine)
    X, y, t1 = flt.load_training_data(tf="1D", venue_id=1)
    cv_results = flt.train(X, y, t1, n_splits=5)
    flt.save_model("models/xgb_meta_filter_latest.json")
    flt.log_results(engine, cv_results, list(X.columns), threshold=0.5)

    impact_df = flt.evaluate_threshold_impact(X_test, y_test)
    print(impact_df)

Notes
-----
- ASCII-only comments and docstrings (Windows cp1252 safety).
- All timestamp columns loaded with pd.to_datetime(utc=True) per MEMORY.md.
- dim_timeframe column is ``tf_days_nominal`` (NOT ``tf_days``).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sqlalchemy import text

from ta_lab2.backtests.cv import PurgedKFoldSplitter
from ta_lab2.ml.experiment_tracker import ExperimentTracker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MetaLabelFilter
# ---------------------------------------------------------------------------


class MetaLabelFilter:
    """XGBoost meta-label confidence filter.

    Predicts P(trade success) for each signal. The executor uses this
    probability to skip trades below a configurable threshold.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
        Database engine pointing at the marketdata PostgreSQL instance.
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self.model_: Any = None  # XGBClassifier, set after train() or load_model()
        self._feature_names: list[str] = []

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_training_data(
        self,
        tf: str = "1D",
        venue_id: int = 1,
    ) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
        """Load and join triple_barrier_labels with features for training.

        Queries ``triple_barrier_labels`` for all assets at the given
        timeframe, then joins with the ``features`` table on
        (asset_id, tf, t0=ts) to fetch point-in-time feature values.

        Only features listed in ``dim_feature_selection`` with tier='active'
        are included so the model uses the same feature set as live executor.

        Returns
        -------
        X : pd.DataFrame
            Feature matrix (rows = labeled events, cols = feature columns).
        y : pd.Series
            Binary target: 1 if bin > 0 (profit target hit), 0 otherwise.
        t1_series : pd.Series
            Label end timestamps for PurgedKFoldSplitter.
        """
        logger.info(
            "MetaLabelFilter: loading training data (tf=%s venue_id=%d)", tf, venue_id
        )

        # -- Step 1: load active feature names from dim_feature_selection --
        with self._engine.connect() as conn:
            feat_rows = conn.execute(
                text(
                    """
                    SELECT feature_name
                    FROM public.dim_feature_selection
                    WHERE tier = 'active'
                    ORDER BY feature_name
                    """
                )
            ).fetchall()

        active_features = [r.feature_name for r in feat_rows]
        if not active_features:
            logger.warning(
                "MetaLabelFilter: no active features in dim_feature_selection; "
                "falling back to all non-PK columns"
            )

        # -- Step 2: load triple_barrier_labels --
        with self._engine.connect() as conn:
            labels_df = pd.read_sql(
                text(
                    """
                    SELECT asset_id, tf, t0, t1, bin
                    FROM public.triple_barrier_labels
                    WHERE tf = :tf
                      AND bin IS NOT NULL
                    ORDER BY asset_id, t0
                    """
                ),
                conn,
                params={"tf": tf},
            )

        if labels_df.empty:
            raise ValueError(
                f"MetaLabelFilter: no triple_barrier_labels rows for tf={tf!r}. "
                "Run refresh_triple_barrier_labels first."
            )

        # Ensure UTC-aware timestamps (MEMORY.md: use pd.to_datetime(utc=True))
        labels_df["t0"] = pd.to_datetime(labels_df["t0"], utc=True)
        labels_df["t1"] = pd.to_datetime(labels_df["t1"], utc=True)

        logger.info("MetaLabelFilter: loaded %d label rows", len(labels_df))

        # -- Step 3: load features for the same (asset_id, tf, ts) tuples --
        with self._engine.connect() as conn:
            # Discover available feature columns in the features table
            col_rows = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'features'
                      AND table_schema = 'public'
                      AND column_name NOT IN (
                          'id', 'ts', 'tf', 'ingested_at', 'venue_id',
                          'open', 'high', 'low', 'close', 'volume'
                      )
                    ORDER BY column_name
                    """
                )
            ).fetchall()
        all_feat_cols = [r.column_name for r in col_rows]

        # Restrict to active features when available
        if active_features:
            use_cols = [c for c in active_features if c in all_feat_cols]
            if not use_cols:
                logger.warning(
                    "MetaLabelFilter: none of %d active features found in "
                    "features table columns; using all available feature cols",
                    len(active_features),
                )
                use_cols = all_feat_cols
        else:
            use_cols = all_feat_cols

        if not use_cols:
            raise ValueError(
                "MetaLabelFilter: features table has no usable feature columns."
            )

        # Build SELECT clause -- keep col list deterministic
        cols_sql = ", ".join(f'"{c}"' for c in use_cols)

        with self._engine.connect() as conn:
            feat_df = pd.read_sql(
                text(
                    f"""
                    SELECT id AS asset_id, ts, {cols_sql}
                    FROM public.features
                    WHERE tf = :tf
                    ORDER BY id, ts
                    """
                ),
                conn,
                params={"tf": tf},
            )

        feat_df["ts"] = pd.to_datetime(feat_df["ts"], utc=True)

        logger.info(
            "MetaLabelFilter: loaded %d feature rows (%d cols)",
            len(feat_df),
            len(use_cols),
        )

        # -- Step 4: join labels with features on (asset_id, t0=ts) --
        joined = labels_df.merge(
            feat_df,
            left_on=["asset_id", "t0"],
            right_on=["asset_id", "ts"],
            how="inner",
        )

        logger.info("MetaLabelFilter: joined %d rows (labels x features)", len(joined))

        if joined.empty:
            raise ValueError(
                "MetaLabelFilter: no rows after joining labels with features. "
                "Ensure features table has rows matching label t0 timestamps."
            )

        # -- Step 5: build X, y, t1_series --
        # Drop rows where t1 is NaT -- PurgedKFoldSplitter requires finite timestamps
        joined = joined.dropna(subset=["t1"]).copy()

        # Sort by t0 (label-start) so PurgedKFoldSplitter index is monotonically increasing
        joined = joined.sort_values("t0").reset_index(drop=True)

        # Binary target: y=1 if bin > 0 (profit target hit), y=0 otherwise
        y = (joined["bin"] > 0).astype(int)
        y.name = "meta_label"
        y.index = range(len(y))

        # t1_series index = t0 timestamps (label-start), values = t1 (label-end)
        # PurgedKFoldSplitter uses index as fold boundary timestamps.
        t1_series = joined["t1"].copy()
        t1_series.index = pd.DatetimeIndex(joined["t0"].values).tz_localize("UTC")

        X = joined[use_cols].copy()
        X.index = range(len(X))

        # Drop columns that are entirely NaN (no signal)
        X = X.dropna(axis=1, how="all")

        # Drop rows where any feature or target is NaN
        valid_mask = X.notna().all(axis=1) & y.notna()
        X = X.loc[valid_mask].reset_index(drop=True)
        y = y.loc[valid_mask].reset_index(drop=True)
        # Re-align t1_series to same integer positions after valid_mask filter
        t1_series = t1_series.iloc[valid_mask.values].reset_index(drop=True)
        # Set t0 timestamps as the index for PurgedKFoldSplitter (must be monotonic)
        t0_index = pd.DatetimeIndex(
            joined.loc[valid_mask.values, "t0"].values
        ).tz_localize("UTC")
        t1_series.index = t0_index

        self._feature_names = list(X.columns)

        pos = int((y == 1).sum())
        neg = int((y == 0).sum())
        logger.info(
            "MetaLabelFilter: final training set -- %d rows, %d features, "
            "pos=%d neg=%d (imbalance=%.2f)",
            len(X),
            len(X.columns),
            pos,
            neg,
            neg / pos if pos > 0 else float("inf"),
        )

        return X, y, t1_series

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        t1_series: pd.Series,
        n_splits: int = 5,
        embargo_frac: float = 0.01,
    ) -> dict:
        """Train XGBoost with purged k-fold cross-validation.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix.
        y : pd.Series
            Binary target (0/1).
        t1_series : pd.Series
            Label end timestamps for purging.
        n_splits : int
            Number of CV folds.
        embargo_frac : float
            Fraction of total samples used as embargo gap after each test fold.

        Returns
        -------
        dict
            Per-fold and mean metrics:
            accuracy, precision, recall, f1, auc -- each as list + _mean key.
        """
        try:
            import xgboost as xgb  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "xgboost is required for MetaLabelFilter. "
                "Install with: pip install xgboost"
            ) from exc

        # Class imbalance correction
        neg = int((y == 0).sum())
        pos = int((y == 1).sum())
        scale_pos_weight = float(neg) / float(pos) if pos > 0 else 1.0
        logger.info(
            "MetaLabelFilter.train: neg=%d pos=%d scale_pos_weight=%.4f",
            neg,
            pos,
            scale_pos_weight,
        )

        splitter = PurgedKFoldSplitter(
            n_splits=n_splits,
            t1_series=t1_series,
            embargo_frac=embargo_frac,
        )

        fold_metrics: dict[str, list[float]] = {
            "accuracy": [],
            "precision": [],
            "recall": [],
            "f1": [],
            "auc": [],
        }

        X_arr = X.values
        y_arr = y.values

        for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(X_arr, y_arr)):
            X_tr, X_te = X_arr[train_idx], X_arr[test_idx]
            y_tr, y_te = y_arr[train_idx], y_arr[test_idx]

            model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=4,
                scale_pos_weight=scale_pos_weight,
                eval_metric="logloss",
                verbosity=0,
                # NOTE: use_label_encoder removed in XGBoost 2.0+
            )
            model.fit(X_tr, y_tr)

            y_pred = model.predict(X_te)
            y_proba = model.predict_proba(X_te)[:, 1]

            fold_metrics["accuracy"].append(float(accuracy_score(y_te, y_pred)))
            fold_metrics["precision"].append(
                float(precision_score(y_te, y_pred, zero_division=0))
            )
            fold_metrics["recall"].append(
                float(recall_score(y_te, y_pred, zero_division=0))
            )
            fold_metrics["f1"].append(float(f1_score(y_te, y_pred, zero_division=0)))
            try:
                fold_metrics["auc"].append(float(roc_auc_score(y_te, y_proba)))
            except ValueError:
                fold_metrics["auc"].append(float("nan"))

            logger.info(
                "MetaLabelFilter.train: fold %d/%d -- acc=%.4f prec=%.4f rec=%.4f f1=%.4f auc=%.4f",
                fold_idx + 1,
                n_splits,
                fold_metrics["accuracy"][-1],
                fold_metrics["precision"][-1],
                fold_metrics["recall"][-1],
                fold_metrics["f1"][-1],
                fold_metrics["auc"][-1],
            )

        # Mean metrics (ignore NaN)
        cv_results = {}
        for k, vals in fold_metrics.items():
            cv_results[k] = vals
            valid = [v for v in vals if not np.isnan(v)]
            cv_results[f"{k}_mean"] = float(np.mean(valid)) if valid else float("nan")

        logger.info(
            "MetaLabelFilter.train: CV complete -- mean acc=%.4f auc=%.4f f1=%.4f",
            cv_results["accuracy_mean"],
            cv_results["auc_mean"],
            cv_results["f1_mean"],
        )

        # Train final model on all data
        logger.info("MetaLabelFilter.train: fitting final model on all %d rows", len(X))
        final_model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=4,
            scale_pos_weight=scale_pos_weight,
            eval_metric="logloss",
            verbosity=0,
        )
        final_model.fit(X_arr, y_arr)
        self.model_ = final_model
        self._feature_names = list(X.columns)

        return cv_results

    # ------------------------------------------------------------------
    # Model persistence
    # ------------------------------------------------------------------

    def save_model(self, path: str) -> None:
        """Save the trained XGBoost model to disk (native XGBoost format).

        Parameters
        ----------
        path : str
            Filesystem path for the model file (e.g. 'models/xgb_meta_filter_latest.json').
        """
        if self.model_ is None:
            raise RuntimeError("MetaLabelFilter.save_model: no model trained yet.")
        import pathlib  # noqa: PLC0415

        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.model_.save_model(path)
        logger.info("MetaLabelFilter.save_model: saved to %s", path)

    def load_model(self, path: str) -> None:
        """Load a previously saved XGBoost model from disk.

        Parameters
        ----------
        path : str
            Path to the serialized XGBoost model file.
        """
        try:
            import xgboost as xgb  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "xgboost is required for MetaLabelFilter. "
                "Install with: pip install xgboost"
            ) from exc

        clf = xgb.XGBClassifier()
        clf.load_model(path)
        self.model_ = clf
        logger.info("MetaLabelFilter.load_model: loaded from %s", path)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict_confidence(self, X: pd.DataFrame) -> np.ndarray:
        """Return P(class=1) = P(trade success) for each row.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray
            Feature matrix with the same columns used during training.

        Returns
        -------
        np.ndarray
            1-D array of float probabilities in [0, 1].
        """
        if self.model_ is None:
            raise RuntimeError(
                "MetaLabelFilter.predict_confidence: no model loaded. "
                "Call train() or load_model() first."
            )
        proba = self.model_.predict_proba(X)
        return proba[:, 1]

    # ------------------------------------------------------------------
    # Threshold impact analysis
    # ------------------------------------------------------------------

    def evaluate_threshold_impact(
        self,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        thresholds: list[float] | None = None,
    ) -> pd.DataFrame:
        """Measure trade filtering impact at multiple confidence thresholds.

        For each threshold computes:
        - n_trades_total: total number of trade signals evaluated
        - n_trades_passed: signals with P(success) >= threshold
        - pass_rate: fraction of trades that pass the filter
        - accuracy_passed: accuracy of the model on passed trades
        - profitable_capture_rate: fraction of truly profitable trades that pass

        Parameters
        ----------
        X_test : pd.DataFrame
            Feature matrix for evaluation.
        y_test : pd.Series
            True binary labels.
        thresholds : list of float, optional
            Confidence thresholds to evaluate. Default: [0.3, 0.4, 0.5, 0.6, 0.7].

        Returns
        -------
        pd.DataFrame
            Columns: threshold, n_trades_total, n_trades_passed, pass_rate,
            accuracy_passed, profitable_capture_rate.
        """
        if thresholds is None:
            thresholds = [0.3, 0.4, 0.5, 0.6, 0.7]

        confidence = self.predict_confidence(X_test)
        y_arr = np.array(y_test)
        n_total = len(y_arr)

        rows = []
        for thr in thresholds:
            passed_mask = confidence >= thr
            n_passed = int(passed_mask.sum())

            if n_passed == 0:
                acc_passed = float("nan")
            else:
                acc_passed = float(
                    accuracy_score(
                        y_arr[passed_mask], (confidence[passed_mask] >= 0.5).astype(int)
                    )
                )

            # Profitable capture rate: of all truly profitable trades (y=1),
            # what fraction passes the threshold?
            n_profitable = int((y_arr == 1).sum())
            if n_profitable == 0:
                profitable_capture = float("nan")
            else:
                profitable_capture = (
                    float((y_arr[passed_mask] == 1).sum()) / n_profitable
                )

            rows.append(
                {
                    "threshold": thr,
                    "n_trades_total": n_total,
                    "n_trades_passed": n_passed,
                    "pass_rate": round(n_passed / n_total, 4)
                    if n_total > 0
                    else float("nan"),
                    "accuracy_passed": round(acc_passed, 4),
                    "profitable_capture_rate": round(profitable_capture, 4),
                }
            )

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Experiment logging
    # ------------------------------------------------------------------

    def log_results(
        self,
        engine: Any,
        cv_results: dict,
        feature_names: list[str],
        threshold: float,
    ) -> str:
        """Log training results to ml_experiments via ExperimentTracker.

        Parameters
        ----------
        engine : sqlalchemy.engine.Engine
            DB engine for ml_experiments writes.
        cv_results : dict
            Output of train() containing per-fold and mean metrics.
        feature_names : list of str
            Feature column names used in training.
        threshold : float
            The primary threshold used for the filter.

        Returns
        -------
        str
            The experiment_id UUID.
        """
        tracker = ExperimentTracker(engine)
        tracker.ensure_table()

        mean_acc = cv_results.get("accuracy_mean", float("nan"))
        mean_auc = cv_results.get("auc_mean", float("nan"))
        mean_f1 = cv_results.get("f1_mean", float("nan"))
        mean_prec = cv_results.get("precision_mean", float("nan"))

        eid = tracker.log_run(
            run_name="xgb_meta_filter_v1",
            model_type="xgb_meta_filter",
            model_params={
                "n_estimators": 200,
                "max_depth": 4,
                "eval_metric": "logloss",
            },
            feature_set=feature_names,
            cv_method="purged_kfold",
            # train_start/train_end use sentinel timestamps (cross-asset training,
            # actual range spans all triple_barrier_labels rows)
            train_start="2000-01-01",
            train_end="2099-12-31",
            asset_ids=[],
            tf="1D",
            oos_accuracy=mean_acc,
            oos_sharpe=mean_auc,  # AUC-ROC used as quality metric proxy
            oos_precision=mean_prec,
            oos_recall=cv_results.get("recall_mean", float("nan")),
            oos_f1=mean_f1,
            notes=(
                f"threshold={threshold}, mean_f1={mean_f1:.4f}, "
                f"precision={mean_prec:.4f}"
            ),
        )
        logger.info("MetaLabelFilter.log_results: logged to ml_experiments id=%s", eid)
        return eid
