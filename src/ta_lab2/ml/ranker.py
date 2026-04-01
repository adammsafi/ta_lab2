"""
Cross-sectional asset ranker using LGBMRanker on CTF+AMA features.

Implements a learning-to-rank model that predicts relative asset performance
across the universe at each timestamp.  Purged K-Fold cross-validation ensures
no lookahead bias in evaluation.

Design
------
- LGBMRanker is imported lazily (same pattern as double_ensemble.py) so this
  module is importable even when LightGBM is not installed.  An informative
  ImportError is raised at call time, not import time.
- PurgedKFoldSplitter from backtests/cv.py provides leakage-free CV.
- ExperimentTracker.log_run() persists metrics to ml_experiments.
- numpy scalar safety: all values bound to SQL are passed through _to_python().

Feature loading
---------------
Loads active-tier features from dim_feature_selection (tier='active') plus
CTF-promoted features (source='ctf_ic_promoted') and AMA features (columns
matching *_ama pattern) from the features table.

The ranking target is a percentile rank of the forward 1-period return within
each timestamp cross-section, computed via groupby().rank(pct=True).

Group array
-----------
LGBMRanker requires group sizes (number of assets per query group).  Each
timestamp cross-section is one group.  _build_group_array converts a ts Series
to a sorted array of counts.

References
----------
LightGBM LGBMRanker: https://lightgbm.readthedocs.io/
Lopez de Prado (2018): Advances in Financial Machine Learning, Chapter 7.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score
from sqlalchemy import text

from ta_lab2.backtests.cv import PurgedKFoldSplitter
from ta_lab2.ml.experiment_tracker import ExperimentTracker, _to_python

logger = logging.getLogger(__name__)

_LGBM_MIN_VERSION = "4.6.0"
_LGBM_INSTALL_MSG = (
    f"LightGBM >= {_LGBM_MIN_VERSION} is required for CrossSectionalRanker. "
    "Install it with: pip install lightgbm>=4.6.0"
)

# Columns from features table that are never model inputs
_EXCLUDE_COLS = frozenset(
    [
        "id",
        "ts",
        "tf",
        "venue_id",
        "ingested_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "market_cap",
        "alignment_source",
        "asset_class",
        "venue",
    ]
)


def _import_lgbm() -> Any:
    """Lazy-import LightGBM; raise informative error if not installed."""
    try:
        import lightgbm as lgb  # noqa: PLC0415

        return lgb
    except ImportError as e:
        raise ImportError(_LGBM_INSTALL_MSG) from e


class CrossSectionalRanker:
    """
    Cross-sectional asset ranker using LGBMRanker with purged K-Fold CV.

    Parameters
    ----------
    None — configured via method arguments.

    Attributes
    ----------
    model_ : lgb.LGBMRanker or None
        Fitted model.  Set by train_full() or the last CV fold's model.
    feature_names_ : list[str] or None
        Feature column names used in the last training run.

    Methods
    -------
    load_features(engine, tf, venue_id)
        Load CTF+AMA features and forward returns from the database.
    cross_validate(df, n_splits, embargo_frac)
        Purged K-Fold cross-validation returning IC, IC-IR, and NDCG.
    train_full(df)
        Train on all data and store model as self.model_.
    log_results(engine, cv_results, feature_names)
        Persist CV metrics to ml_experiments via ExperimentTracker.
    """

    def __init__(self) -> None:
        self.model_: Any = None
        self.feature_names_: list[str] | None = None

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_features(
        self,
        engine: Any,
        tf: str = "1D",
        venue_id: int = 1,
    ) -> pd.DataFrame:
        """Load CTF+AMA features with forward 1-period return as target.

        Queries features table for all assets filtered to:
        1. Active-tier features from dim_feature_selection (tier='active')
        2. CTF-promoted features from dim_feature_selection
           (source='ctf_ic_promoted')
        3. AMA features: columns matching the *_ama pattern

        Joins with returns_bars_multi_tf to attach the forward return (shifted
        by -1 within each asset so the target is the next-bar return).

        Parameters
        ----------
        engine:
            SQLAlchemy engine connected to the ta_lab2 PostgreSQL database.
        tf:
            Timeframe filter (default '1D').
        venue_id:
            Venue filter (default 1 = CMC_AGG).

        Returns
        -------
        pd.DataFrame
            Columns: ts (UTC-aware), asset_id (int), <feature columns>,
            forward_return (float).  Rows with NaN forward_return are dropped.
        """
        # ------------------------------------------------------------------
        # Step 1: discover which feature columns to load
        # ------------------------------------------------------------------
        col_sql = text(
            """
            SELECT DISTINCT feature_name
            FROM public.dim_feature_selection
            WHERE tier = 'active'
               OR source = 'ctf_ic_promoted'
            ORDER BY feature_name
            """
        )
        with engine.connect() as conn:
            selected_rows = conn.execute(col_sql).fetchall()

        selected_features = [r[0] for r in selected_rows]

        # Also include AMA features: query information_schema for *_ama columns
        ama_col_sql = text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'features'
              AND column_name LIKE '%_ama'
            ORDER BY column_name
            """
        )
        with engine.connect() as conn:
            ama_rows = conn.execute(ama_col_sql).fetchall()

        ama_features = [r[0] for r in ama_rows]

        # Union: selected features + AMA features, deduped, sorted
        all_feature_cols = sorted(set(selected_features) | set(ama_features))

        if not all_feature_cols:
            logger.warning(
                "No features found in dim_feature_selection or AMA columns. "
                "Check that Phase 98 (CTF promotion) has been run."
            )
            # Fall back to loading all numeric feature columns
            all_feature_cols = []

        # ------------------------------------------------------------------
        # Step 2: load features table
        # ------------------------------------------------------------------
        if all_feature_cols:
            # Only select discovered columns that actually exist in the table
            existing_col_sql = text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'features'
                ORDER BY ordinal_position
                """
            )
            with engine.connect() as conn:
                existing_rows = conn.execute(existing_col_sql).fetchall()
            existing_cols = {r[0] for r in existing_rows}

            # Always include id (for join) and ts
            base_cols = ["id", "ts", "tf", "venue_id"]
            feat_cols = [c for c in all_feature_cols if c in existing_cols]
            select_cols = base_cols + feat_cols
            col_list = ", ".join(f'"{c}"' for c in select_cols)
            feat_query = text(
                f"""
                SELECT {col_list}
                FROM public.features
                WHERE tf = :tf
                  AND venue_id = :venue_id
                ORDER BY id, ts
                """
            )
        else:
            # No specific columns — load all
            feat_query = text(
                """
                SELECT *
                FROM public.features
                WHERE tf = :tf
                  AND venue_id = :venue_id
                ORDER BY id, ts
                """
            )

        with engine.connect() as conn:
            feat_df = pd.read_sql(
                feat_query,
                conn,
                params={"tf": tf, "venue_id": venue_id},
            )

        if feat_df.empty:
            logger.warning(
                "features table returned 0 rows for tf=%s venue_id=%s", tf, venue_id
            )
            return pd.DataFrame()

        # CRITICAL: UTC-aware timestamps (MEMORY.md pitfall)
        feat_df["ts"] = pd.to_datetime(feat_df["ts"], utc=True)
        feat_df = feat_df.rename(columns={"id": "asset_id"})

        # ------------------------------------------------------------------
        # Step 3: load forward returns (shift -1 within each asset)
        # ------------------------------------------------------------------
        returns_sql = text(
            """
            SELECT id AS asset_id, ts, ret_arith
            FROM public.returns_bars_multi_tf
            WHERE tf = :tf
              AND venue_id = :venue_id
            ORDER BY asset_id, ts
            """
        )
        with engine.connect() as conn:
            ret_df = pd.read_sql(
                returns_sql,
                conn,
                params={"tf": tf, "venue_id": venue_id},
            )

        if ret_df.empty:
            logger.warning("returns_bars_multi_tf returned 0 rows for tf=%s", tf)
            return pd.DataFrame()

        ret_df["ts"] = pd.to_datetime(ret_df["ts"], utc=True)

        # Forward return: for each asset, shift ret_arith by -1
        ret_df = ret_df.sort_values(["asset_id", "ts"])
        ret_df["forward_return"] = ret_df.groupby("asset_id")["ret_arith"].shift(-1)

        # Keep only ts + forward_return for join
        ret_df = ret_df[["asset_id", "ts", "forward_return"]]

        # ------------------------------------------------------------------
        # Step 4: merge features with forward returns
        # ------------------------------------------------------------------
        merged = feat_df.merge(ret_df, on=["asset_id", "ts"], how="inner")

        # Drop rows where forward_return is NaN (last bar per asset)
        n_before = len(merged)
        merged = merged.dropna(subset=["forward_return"])
        n_dropped = n_before - len(merged)
        if n_dropped:
            logger.info(
                "Dropped %d rows with NaN forward_return (last bars)", n_dropped
            )

        # Drop non-feature columns from the feature matrix
        keep_meta = {"asset_id", "ts", "forward_return"}
        drop_cols = [c for c in merged.columns if c in _EXCLUDE_COLS - keep_meta]
        merged = merged.drop(columns=drop_cols, errors="ignore")

        logger.info(
            "Loaded %d rows, %d assets, %d feature columns",
            len(merged),
            merged["asset_id"].nunique(),
            len(merged.columns) - 3,  # minus asset_id, ts, forward_return
        )
        return merged.reset_index(drop=True)

    # ------------------------------------------------------------------
    # Group / target helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_group_array(ts_series: pd.Series) -> np.ndarray:
        """Build LGBMRanker group sizes array from a timestamp Series.

        Each unique timestamp is one query group.  LGBMRanker requires group
        sizes in the same order as the rows.

        Parameters
        ----------
        ts_series:
            Series of timestamps (must be sorted by timestamp for valid groups).

        Returns
        -------
        np.ndarray of int
            Length = number of unique timestamps; each element is the count of
            assets in that cross-section.
        """
        counts = ts_series.value_counts(sort=False).sort_index()
        group_array = counts.values.astype(np.int32)
        assert group_array.sum() == len(ts_series), (
            f"Group sum {group_array.sum()} != total rows {len(ts_series)}"
        )
        return group_array

    @staticmethod
    def _build_rank_target(df: pd.DataFrame) -> pd.Series:
        """Build percentile rank target from forward_return within each timestamp.

        For each timestamp cross-section, ranks assets by forward_return using
        percentile rank in [0, 1].  Higher rank = better return.

        Parameters
        ----------
        df:
            DataFrame with 'ts' and 'forward_return' columns.

        Returns
        -------
        pd.Series
            Percentile ranks aligned to df.index.
        """
        return df.groupby("ts")["forward_return"].rank(pct=True)

    # ------------------------------------------------------------------
    # Feature column extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _get_feature_cols(df: pd.DataFrame) -> list[str]:
        """Return feature column names (exclude metadata columns)."""
        meta = {"asset_id", "ts", "forward_return"} | _EXCLUDE_COLS
        return [c for c in df.columns if c not in meta]

    # ------------------------------------------------------------------
    # Cross-validation
    # ------------------------------------------------------------------

    def cross_validate(
        self,
        df: pd.DataFrame,
        n_splits: int = 5,
        embargo_frac: float = 0.01,
    ) -> dict:
        """Purged K-Fold cross-validation returning IC, IC-IR, and NDCG.

        Uses PurgedKFoldSplitter to create leakage-free folds.  The data is
        treated as a panel (many assets per timestamp) sorted by timestamp.
        Groups (assets per period) are recomputed per fold from the training
        subset.

        Parameters
        ----------
        df:
            DataFrame returned by load_features().  Must contain 'ts',
            'asset_id', 'forward_return', and feature columns.
        n_splits:
            Number of CV folds (default 5).
        embargo_frac:
            Embargo fraction applied after each test fold (default 0.01).

        Returns
        -------
        dict with keys:
            fold_ics:    list[float] — per-fold mean Spearman IC
            mean_ic:     float — mean of fold_ics
            ic_ir:       float — mean_ic / std(fold_ics)
            fold_ndcgs:  list[float] — per-fold mean NDCG
            mean_ndcg:   float — mean of fold_ndcgs
            n_splits:    int
            feature_names: list[str]
        """
        lgb = _import_lgbm()

        # Sort by timestamp to ensure temporal order
        df = df.sort_values("ts").reset_index(drop=True)

        feature_cols = self._get_feature_cols(df)
        self.feature_names_ = feature_cols

        X = df[feature_cols].values
        y = self._build_rank_target(df).values

        # Build t1_series for purged CV:
        # Index = row-level timestamps (one per row, not unique per timestamp),
        # Values = same timestamps + 1 period (label ends at next bar start).
        # PurgedKFoldSplitter needs a monotonically increasing index.
        # We index by integer position but use the ts values for purging.
        ts_arr = df["ts"].values
        # Use unique timestamps to build the series (index = position in sorted order)
        # Actually PurgedKFoldSplitter works on the full panel rows —
        # use row timestamps as index (sorted), values = ts + 1 bar (approx 1 day)
        ts_series_idx = pd.to_datetime(ts_arr, utc=True)
        # Label end = next timestamp (approximate with 1D offset for safety)
        t1_values = ts_series_idx + pd.Timedelta(days=1)
        t1_series = pd.Series(t1_values, index=ts_series_idx)
        # Ensure monotonically increasing index (sort by ts)
        t1_series = t1_series.sort_index()

        splitter = PurgedKFoldSplitter(
            n_splits=n_splits,
            t1_series=t1_series,
            embargo_frac=embargo_frac,
        )

        fold_ics: list[float] = []
        fold_ndcgs: list[float] = []

        for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(X)):
            if len(train_idx) < 2 or len(test_idx) < 2:
                logger.warning("Fold %d: too few samples, skipping", fold_idx)
                continue

            X_train = X[train_idx]
            y_train = y[train_idx]
            X_test = X[test_idx]
            y_test = y[test_idx]

            ts_train = df["ts"].iloc[train_idx]
            ts_test = df["ts"].iloc[test_idx]

            # CRITICAL: recompute group sizes from this fold's training subset
            group_train = self._build_group_array(ts_train)

            # Fill NaN with column median (simple imputation)
            col_medians = np.nanmedian(X_train, axis=0)
            nan_mask_train = np.isnan(X_train)
            X_train = X_train.copy()
            inds = np.where(nan_mask_train)
            X_train[inds] = np.take(col_medians, inds[1])

            X_test = X_test.copy()
            nan_mask_test = np.isnan(X_test)
            inds_test = np.where(nan_mask_test)
            X_test[inds_test] = np.take(col_medians, inds_test[1])

            model = lgb.LGBMRanker(
                n_estimators=200,
                num_leaves=31,
                learning_rate=0.05,
                verbose=-1,
            )
            model.fit(X_train, y_train, group=group_train)

            y_pred = model.predict(X_test)

            # Per-period Spearman IC
            period_ics = []
            period_ndcgs = []
            for ts_val in ts_test.unique():
                mask = (ts_test == ts_val).values
                y_true_p = y_test[mask]
                y_pred_p = y_pred[mask]

                if len(y_true_p) < 2:
                    continue

                ic_val, _ = spearmanr(y_true_p, y_pred_p)
                if not np.isnan(ic_val):
                    period_ics.append(float(ic_val))

                # NDCG requires 2D arrays
                try:
                    ndcg_val = ndcg_score(
                        [y_true_p],
                        [y_pred_p],
                    )
                    period_ndcgs.append(float(ndcg_val))
                except Exception:  # noqa: BLE001
                    pass

            fold_ic = float(np.mean(period_ics)) if period_ics else 0.0
            fold_ndcg = float(np.mean(period_ndcgs)) if period_ndcgs else 0.0
            fold_ics.append(fold_ic)
            fold_ndcgs.append(fold_ndcg)

            logger.info(
                "Fold %d: IC=%.4f  NDCG=%.4f  (train=%d test=%d)",
                fold_idx,
                fold_ic,
                fold_ndcg,
                len(train_idx),
                len(test_idx),
            )

            # Keep last fold model for downstream SHAP (Plan 100-02)
            self.model_ = model

        if not fold_ics:
            raise RuntimeError("All CV folds skipped — not enough data.")

        mean_ic = float(np.mean(fold_ics))
        std_ic = float(np.std(fold_ics, ddof=1)) if len(fold_ics) > 1 else 0.0
        ic_ir = mean_ic / std_ic if std_ic > 1e-9 else 0.0
        mean_ndcg = float(np.mean(fold_ndcgs))

        return {
            "fold_ics": fold_ics,
            "mean_ic": mean_ic,
            "ic_ir": ic_ir,
            "fold_ndcgs": fold_ndcgs,
            "mean_ndcg": mean_ndcg,
            "n_splits": len(fold_ics),
            "feature_names": feature_cols,
        }

    # ------------------------------------------------------------------
    # Full training
    # ------------------------------------------------------------------

    def train_full(self, df: pd.DataFrame) -> Any:
        """Train LGBMRanker on the full dataset and store as self.model_.

        For production use and downstream SHAP analysis (Plan 100-02).

        Parameters
        ----------
        df:
            DataFrame returned by load_features().

        Returns
        -------
        lgb.LGBMRanker
            The fitted model (also stored as self.model_).
        """
        lgb = _import_lgbm()

        df = df.sort_values("ts").reset_index(drop=True)

        feature_cols = self._get_feature_cols(df)
        self.feature_names_ = feature_cols

        X = df[feature_cols].values
        y = self._build_rank_target(df).values
        group = self._build_group_array(df["ts"])

        # Fill NaN with column median
        col_medians = np.nanmedian(X, axis=0)
        nan_mask = np.isnan(X)
        X = X.copy()
        inds = np.where(nan_mask)
        X[inds] = np.take(col_medians, inds[1])

        model = lgb.LGBMRanker(
            n_estimators=200,
            num_leaves=31,
            learning_rate=0.05,
            verbose=-1,
        )
        model.fit(X, y, group=group)
        self.model_ = model
        logger.info(
            "train_full: fitted on %d rows, %d features", len(df), len(feature_cols)
        )
        return model

    # ------------------------------------------------------------------
    # Experiment logging
    # ------------------------------------------------------------------

    def log_results(
        self,
        engine: Any,
        cv_results: dict,
        feature_names: list[str],
        tf: str = "1D",
        venue_id: int = 1,
        asset_ids: list[int] | None = None,
        n_splits: int = 5,
        embargo_frac: float = 0.01,
        train_start: Any = None,
        train_end: Any = None,
    ) -> str:
        """Persist CV metrics to ml_experiments via ExperimentTracker.

        Parameters
        ----------
        engine:
            SQLAlchemy engine.
        cv_results:
            Dict returned by cross_validate().
        feature_names:
            List of feature column names used.
        tf:
            Timeframe string.
        venue_id:
            Venue id (for notes).
        asset_ids:
            Asset IDs included in training (may be None → empty list).
        n_splits:
            Number of CV folds used.
        embargo_frac:
            Embargo fraction used.
        train_start, train_end:
            Date range (optional, for logging).

        Returns
        -------
        str
            experiment_id UUID string.
        """
        tracker = ExperimentTracker(engine)
        tracker.ensure_table()

        mean_ic = cv_results["mean_ic"]
        ic_ir = cv_results["ic_ir"]
        mean_ndcg = cv_results["mean_ndcg"]
        actual_n_splits = cv_results["n_splits"]

        notes = (
            f"NDCG={_to_python(mean_ndcg):.4f}, "
            f"n_folds={actual_n_splits}, "
            f"n_features={len(feature_names)}, "
            f"venue_id={venue_id}"
        )

        if train_start is None:
            train_start = "2020-01-01"
        if train_end is None:
            train_end = "2026-01-01"
        if asset_ids is None:
            asset_ids = []

        experiment_id = tracker.log_run(
            run_name="lgbm_ranker_ctf_ama_v1",
            model_type="lgbm_ranker",
            model_params={
                "n_estimators": 200,
                "num_leaves": 31,
                "learning_rate": 0.05,
                "objective": "lambdarank",
            },
            feature_set=feature_names,
            cv_method="purged_kfold",
            train_start=train_start,
            train_end=train_end,
            asset_ids=asset_ids,
            tf=tf,
            cv_n_splits=n_splits,
            cv_embargo_frac=embargo_frac,
            oos_accuracy=_to_python(mean_ic),
            oos_sharpe=_to_python(ic_ir),
            n_oos_folds=actual_n_splits,
            notes=notes,
        )
        logger.info(
            "Logged to ml_experiments: experiment_id=%s  IC=%.4f  IC-IR=%.4f  NDCG=%.4f",
            experiment_id,
            _to_python(mean_ic),
            _to_python(ic_ir),
            _to_python(mean_ndcg),
        )
        return experiment_id
