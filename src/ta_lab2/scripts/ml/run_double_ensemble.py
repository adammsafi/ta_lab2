"""
CLI for DoubleEnsemble concept drift evaluation vs static LightGBM baseline.

Loads ``cmc_features`` for the given asset IDs / timeframe / date range,
trains a ``DoubleEnsemble`` (sliding-window LightGBM with sample reweighting)
and a static ``LGBMClassifier`` baseline, evaluates both via purged
cross-validation, and prints a side-by-side comparison table.

Usage
-----
    python -m ta_lab2.scripts.ml.run_double_ensemble \\
        --asset-ids 1,2 \\
        --tf 1D \\
        --start 2023-01-01 \\
        --end 2025-12-31 \\
        --window-size 60 \\
        --stride 15 \\
        --n-splits 5 \\
        --log-experiment

Notes
-----
- Uses NullPool for SQLAlchemy engine (no connection pooling in CLI process).
- All timestamp columns loaded with pd.to_datetime(utc=True) per MEMORY.md.
- Always passes DataFrames (not numpy arrays) to model.fit/predict.
- Empty fold guard: skips CV folds with fewer than 2 training samples.
- LightGBM import error handled gracefully (static baseline falls back to RF).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import accuracy_score
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# Columns never used as features
_EXCLUDE_COLS = frozenset(
    [
        "id",
        "ts",
        "tf",
        "ingested_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "market_cap",
        "alignment_source",
        # categorical/string columns from cmc_features (not numeric features)
        "asset_class",
        "venue",
    ]
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_double_ensemble",
        description=(
            "Train DoubleEnsemble and a static LGBMClassifier baseline on cmc_features, "
            "evaluate both with purged CV, and print a comparison table."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--asset-ids",
        default="1,2",
        help="Comma-separated asset IDs (default: '1,2')",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe string, e.g. '1D' or '4H' (default: '1D')",
    )
    parser.add_argument(
        "--start",
        default="2023-01-01",
        help="Training start date YYYY-MM-DD (default: '2023-01-01')",
    )
    parser.add_argument(
        "--end",
        default="2025-12-31",
        help="Training end date YYYY-MM-DD (default: '2025-12-31')",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=60,
        help="Sliding window size for DoubleEnsemble sub-models (default: 60)",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=15,
        help="Stride between windows for DoubleEnsemble (default: 15)",
    )
    parser.add_argument(
        "--n-splits",
        type=int,
        default=5,
        help="Number of purged CV folds (default: 5)",
    )
    parser.add_argument(
        "--log-experiment",
        action="store_true",
        help="Log results to cmc_ml_experiments via ExperimentTracker",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _build_engine() -> Any:
    """Build NullPool SQLAlchemy engine from ta_lab2 config."""
    from ta_lab2.config import TARGET_DB_URL

    if not TARGET_DB_URL:
        raise RuntimeError(
            "TARGET_DB_URL is not set. "
            "Configure db_config.env or set the TARGET_DB_URL environment variable."
        )
    return create_engine(TARGET_DB_URL, poolclass=NullPool)


def _load_features(
    engine: Any,
    asset_ids: list[int],
    tf: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Load cmc_features for the given asset_ids, tf, and date range."""
    ids_literal = "{" + ",".join(str(i) for i in asset_ids) + "}"
    sql = text(
        """
        SELECT *
        FROM public.cmc_features
        WHERE id = ANY(CAST(:ids AS INTEGER[]))
          AND tf = :tf
          AND ts BETWEEN CAST(:start AS TIMESTAMPTZ) AND CAST(:end AS TIMESTAMPTZ)
        ORDER BY id, ts
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(
            sql, conn, params={"ids": ids_literal, "tf": tf, "start": start, "end": end}
        )

    if df.empty:
        return df

    # CRITICAL: UTC-aware timestamps (MEMORY.md pitfall)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------


def _build_static_baseline() -> Any:
    """Return a static LGBMClassifier (or RF fallback) for comparison."""
    try:
        from lightgbm import LGBMClassifier

        logger.info("Static baseline: LGBMClassifier")
        return LGBMClassifier(
            n_estimators=100, num_leaves=31, random_state=42, verbose=-1
        )
    except ImportError:
        logger.warning(
            "lightgbm not installed — static baseline uses RandomForestClassifier"
        )
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier(n_estimators=100, n_jobs=-1, random_state=42)


# ---------------------------------------------------------------------------
# Cross-validation helpers
# ---------------------------------------------------------------------------


def _run_purged_cv_static(
    model: Any,
    X: pd.DataFrame,
    y: np.ndarray,
    t1_series: pd.Series,
    n_splits: int,
) -> dict[str, Any]:
    """Evaluate a static model with purged CV."""
    from ta_lab2.backtests.cv import PurgedKFoldSplitter

    cv = PurgedKFoldSplitter(n_splits=n_splits, t1_series=t1_series, embargo_frac=0.01)
    fold_scores: list[float] = []

    for train_idx, test_idx in cv.split(X):
        # Empty fold guard
        if len(train_idx) < 2 or len(test_idx) < 2:
            logger.debug(
                "Skipping empty/tiny fold (train=%d, test=%d)",
                len(train_idx),
                len(test_idx),
            )
            continue

        X_tr = X.iloc[train_idx]
        y_tr = y[train_idx]
        X_te = X.iloc[test_idx]
        y_te = y[test_idx]

        # Need at least 2 classes in training
        if len(np.unique(y_tr)) < 2:
            logger.debug("Skipping fold — single class in training set")
            continue

        m = clone(model)
        m.fit(X_tr, y_tr)
        preds = m.predict(X_te)
        fold_scores.append(accuracy_score(y_te, preds))

    if not fold_scores:
        return {
            "oos_accuracy": float("nan"),
            "oos_accuracy_std": float("nan"),
            "n_folds": 0,
        }

    return {
        "oos_accuracy": float(np.mean(fold_scores)),
        "oos_accuracy_std": float(np.std(fold_scores)),
        "n_folds": len(fold_scores),
    }


def _run_purged_cv_double_ensemble(
    window_size: int,
    stride: int,
    X: pd.DataFrame,
    y: np.ndarray,
    t1_series: pd.Series,
    n_splits: int,
) -> dict[str, Any]:
    """Evaluate DoubleEnsemble with purged CV (re-fit per fold)."""
    from ta_lab2.backtests.cv import PurgedKFoldSplitter
    from ta_lab2.ml.double_ensemble import DoubleEnsemble

    cv = PurgedKFoldSplitter(n_splits=n_splits, t1_series=t1_series, embargo_frac=0.01)
    fold_scores: list[float] = []

    for fold_num, (train_idx, test_idx) in enumerate(cv.split(X), start=1):
        # Empty fold guard
        if len(train_idx) < 2 or len(test_idx) < 2:
            logger.debug(
                "Skipping empty/tiny fold %d (train=%d, test=%d)",
                fold_num,
                len(train_idx),
                len(test_idx),
            )
            continue

        X_tr = X.iloc[train_idx]
        y_tr = y[train_idx]
        X_te = X.iloc[test_idx]
        y_te = y[test_idx]

        # Need at least 2 classes in training
        if len(np.unique(y_tr)) < 2:
            logger.debug("Skipping fold %d — single class in training set", fold_num)
            continue

        # Adapt window_size if training fold is very short
        eff_window = min(window_size, max(len(X_tr) // 2, 10))
        eff_stride = min(stride, max(eff_window // 4, 1))

        de = DoubleEnsemble(window_size=eff_window, stride=eff_stride)
        de.fit(X_tr, y_tr)

        if not de.models:
            logger.debug(
                "Fold %d: DoubleEnsemble produced no sub-models — skipping", fold_num
            )
            continue

        preds = de.predict(X_te)
        fold_scores.append(accuracy_score(y_te, preds))
        logger.debug(
            "Fold %d: accuracy=%.4f, n_sub_models=%d",
            fold_num,
            fold_scores[-1],
            len(de.models),
        )

    if not fold_scores:
        return {
            "oos_accuracy": float("nan"),
            "oos_accuracy_std": float("nan"),
            "n_folds": 0,
        }

    return {
        "oos_accuracy": float(np.mean(fold_scores)),
        "oos_accuracy_std": float(np.std(fold_scores)),
        "n_folds": len(fold_scores),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_comparison(
    static_results: dict[str, Any],
    de_results: dict[str, Any],
    window_size: int,
    stride: int,
) -> None:
    """Print side-by-side comparison table."""
    print("\n" + "=" * 65)
    print("DoubleEnsemble vs Static Baseline — Purged CV Comparison")
    print("=" * 65)
    print(f"  DoubleEnsemble: window_size={window_size}, stride={stride}")
    print(f"\n{'Metric':<35} {'Static':>12} {'DoubleEnsemble':>14}")
    print("-" * 65)

    s_acc = static_results.get("oos_accuracy", float("nan"))
    d_acc = de_results.get("oos_accuracy", float("nan"))
    s_std = static_results.get("oos_accuracy_std", float("nan"))
    d_std = de_results.get("oos_accuracy_std", float("nan"))
    s_folds = static_results.get("n_folds", 0)
    d_folds = de_results.get("n_folds", 0)

    print(f"{'OOS Accuracy (mean)':<35} {s_acc:>12.4f} {d_acc:>14.4f}")
    print(f"{'OOS Accuracy (std)':<35} {s_std:>12.4f} {d_std:>14.4f}")
    print(f"{'N valid folds':<35} {s_folds:>12d} {d_folds:>14d}")

    delta = d_acc - s_acc
    print(f"\n{'Delta (DoubleEnsemble - Static)':<35} {delta:>+14.4f}")

    if abs(delta) < 0.001:
        verdict = "No material difference"
    elif delta > 0:
        verdict = "DoubleEnsemble BETTER"
    else:
        verdict = "Static baseline BETTER"
    print(f"{'Verdict':<35} {verdict:>26}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    asset_ids = [int(x.strip()) for x in args.asset_ids.split(",")]
    logger.info(
        "run_double_ensemble: asset_ids=%s tf=%s start=%s end=%s "
        "window_size=%d stride=%d n_splits=%d",
        asset_ids,
        args.tf,
        args.start,
        args.end,
        args.window_size,
        args.stride,
        args.n_splits,
    )

    t0 = time.time()
    engine = _build_engine()

    # --- Load features ---
    logger.info("Loading cmc_features...")
    df = _load_features(engine, asset_ids, args.tf, args.start, args.end)
    if df.empty:
        logger.error(
            "No data in cmc_features for asset_ids=%s tf=%s %s to %s. Exiting.",
            asset_ids,
            args.tf,
            args.start,
            args.end,
        )
        sys.exit(1)
    logger.info("Loaded %d rows x %d columns", len(df), len(df.columns))

    # --- Build feature matrix ---
    # Exclude non-numeric dtypes (cmc_features has string/datetime cols: asset_class, venue, updated_at)
    feature_cols = [
        c
        for c in df.columns
        if c not in _EXCLUDE_COLS
        and df[c].notna().any()
        and c != "ret_arith"
        and pd.api.types.is_numeric_dtype(df[c])
    ]

    if "ret_arith" not in df.columns:
        logger.error("ret_arith column not found in cmc_features. Cannot build labels.")
        sys.exit(1)

    X = df[feature_cols].copy()
    X = X.ffill().dropna(axis=1, how="all")
    feature_cols = list(X.columns)

    valid_mask = X.notna().all(axis=1)
    X = X[valid_mask].reset_index(drop=True)
    df_valid = df[valid_mask].reset_index(drop=True)

    # --- Sort by ts for PurgedKFold (multi-asset data must be time-sorted globally) ---
    sort_idx = df_valid["ts"].argsort()
    df_valid = df_valid.iloc[sort_idx].reset_index(drop=True)
    X = X.iloc[sort_idx].reset_index(drop=True)

    # --- Binary labels ---
    y = (df_valid["ret_arith"] > 0).astype(int).values
    logger.info(
        "Labels: %d positive (%.1f%%), %d negative (%.1f%%)",
        y.sum(),
        100.0 * y.sum() / len(y),
        (y == 0).sum(),
        100.0 * (y == 0).sum() / len(y),
    )

    # --- Build t1_series for PurgedKFold ---
    # CRITICAL (MEMORY.md): .values on tz-aware Series returns tz-naive numpy.datetime64.
    # Use .tolist() to preserve tz-aware Timestamp objects for correct cv.py comparisons.
    ts_series = df_valid["ts"].reset_index(drop=True)
    t1_series = ts_series + pd.Timedelta(days=1)
    t1_series.index = ts_series.tolist()  # index = label start, value = label end

    logger.info("Training set: %d samples, %d features", len(X), len(feature_cols))

    # --- Build static baseline ---
    static_model = _build_static_baseline()

    # --- Run static baseline CV ---
    logger.info("Running purged CV for static baseline (n_splits=%d)...", args.n_splits)
    static_results = _run_purged_cv_static(static_model, X, y, t1_series, args.n_splits)
    logger.info(
        "Static OOS accuracy: %.4f", static_results.get("oos_accuracy", float("nan"))
    )

    # --- Run DoubleEnsemble CV ---
    logger.info(
        "Running purged CV for DoubleEnsemble (window_size=%d stride=%d n_splits=%d)...",
        args.window_size,
        args.stride,
        args.n_splits,
    )
    de_results = _run_purged_cv_double_ensemble(
        args.window_size, args.stride, X, y, t1_series, args.n_splits
    )
    logger.info(
        "DoubleEnsemble OOS accuracy: %.4f",
        de_results.get("oos_accuracy", float("nan")),
    )

    duration = time.time() - t0
    logger.info("DoubleEnsemble comparison complete in %.1f seconds.", duration)

    # --- Print comparison ---
    _print_comparison(static_results, de_results, args.window_size, args.stride)

    # --- Optional experiment logging ---
    if args.log_experiment:
        logger.info("Logging experiments to cmc_ml_experiments...")
        from ta_lab2.ml.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker(engine)
        tracker.ensure_table()

        lgbm_params = {"n_estimators": 100, "num_leaves": 31, "random_state": 42}

        # Log static baseline
        static_eid = tracker.log_run(
            run_name=f"static_lgbm_{args.tf}",
            model_type="lgbm",
            model_params=lgbm_params,
            feature_set=feature_cols,
            cv_method="purged_kfold",
            train_start=args.start,
            train_end=args.end,
            asset_ids=asset_ids,
            tf=args.tf,
            cv_n_splits=args.n_splits,
            cv_embargo_frac=0.01,
            label_method="binary_ret_arith",
            label_params={"threshold": 0.0},
            oos_accuracy=static_results.get("oos_accuracy"),
            n_oos_folds=static_results.get("n_folds"),
            regime_routing=False,
            duration_seconds=duration / 2,
            notes="static baseline for DoubleEnsemble comparison",
        )
        logger.info("Static baseline experiment logged: %s", static_eid)

        # Log DoubleEnsemble
        de_eid = tracker.log_run(
            run_name=f"double_ensemble_{args.tf}_w{args.window_size}_s{args.stride}",
            model_type="double_ensemble",
            model_params={
                **lgbm_params,
                "window_size": args.window_size,
                "stride": args.stride,
            },
            feature_set=feature_cols,
            cv_method="purged_kfold",
            train_start=args.start,
            train_end=args.end,
            asset_ids=asset_ids,
            tf=args.tf,
            cv_n_splits=args.n_splits,
            cv_embargo_frac=0.01,
            label_method="binary_ret_arith",
            label_params={"threshold": 0.0},
            oos_accuracy=de_results.get("oos_accuracy"),
            n_oos_folds=de_results.get("n_folds"),
            regime_routing=False,
            duration_seconds=duration / 2,
            notes=(
                f"DoubleEnsemble; window_size={args.window_size}; stride={args.stride}; "
                f"delta_vs_static={de_results.get('oos_accuracy', float('nan')) - static_results.get('oos_accuracy', float('nan')):.4f}"
            ),
        )
        logger.info("DoubleEnsemble experiment logged: %s", de_eid)
        print(f"Experiments logged: static={static_eid}  double_ensemble={de_eid}")


if __name__ == "__main__":
    main()
