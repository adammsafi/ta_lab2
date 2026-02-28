"""
CLI for running MDA/SFI feature importance on cmc_features.

Loads feature data from the ``cmc_features`` table for the given asset IDs,
timeframe, and date range; builds binary directional labels from ``ret_arith``;
runs Mean Decrease Accuracy (MDA) and/or Single Feature Importance (SFI) via
purged cross-validation; prints a ranked table; optionally writes CSV and logs
results to ``cmc_ml_experiments`` via ExperimentTracker.

Usage
-----
    python -m ta_lab2.scripts.ml.run_feature_importance \\
        --asset-ids 1,2 \\
        --tf 1D \\
        --start 2023-01-01 \\
        --end 2025-12-31 \\
        --n-splits 5 \\
        --mode both \\
        --model rf \\
        --output-csv /tmp/fi_results.csv \\
        --log-experiment

Notes
-----
- Uses NullPool for SQLAlchemy engine (no connection pooling in CLI process).
- All timestamp columns loaded with pd.to_datetime(utc=True) per MEMORY.md.
- Always passes DataFrames (not numpy arrays) to model.fit/predict per MEMORY.md.
- LightGBM import error is handled gracefully (falls back to RandomForest).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PK and excluded columns
# ---------------------------------------------------------------------------

# These columns are never used as features
_EXCLUDE_COLS = frozenset(
    [
        "id",
        "ts",
        "tf",
        "ingested_at",
        # raw OHLCV (not derived features)
        "open",
        "high",
        "low",
        "close",
        "volume",
        "market_cap",
        # alignment metadata
        "alignment_source",
    ]
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_feature_importance",
        description="Run MDA/SFI feature importance on cmc_features and log results.",
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
        "--n-splits",
        type=int,
        default=5,
        help="Number of purged CV folds (default: 5)",
    )
    parser.add_argument(
        "--scoring",
        default="accuracy",
        help="sklearn scoring metric for MDA (default: 'accuracy')",
    )
    parser.add_argument(
        "--mode",
        choices=["mda", "sfi", "both"],
        default="both",
        help="Feature importance mode: mda, sfi, or both (default: 'both')",
    )
    parser.add_argument(
        "--model",
        choices=["rf", "lgbm"],
        default="rf",
        help="Base model: rf (RandomForest) or lgbm (LightGBM) (default: 'rf')",
    )
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Optional: path to write ranked importance CSV",
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
    """Load cmc_features for the given asset_ids, tf, and date range.

    Returns a DataFrame with ts as a UTC-aware DatetimeIndex.
    """
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


def _build_model(model_name: str) -> Any:
    """Return a sklearn-compatible model.  Falls back to RF if lgbm unavailable."""
    if model_name == "lgbm":
        try:
            from lightgbm import LGBMClassifier

            logger.info("Using LGBMClassifier")
            return LGBMClassifier(
                n_estimators=100, num_leaves=31, random_state=42, verbose=-1
            )
        except ImportError:
            logger.warning(
                "lightgbm not installed — falling back to RandomForestClassifier"
            )

    from sklearn.ensemble import RandomForestClassifier

    logger.info("Using RandomForestClassifier")
    return RandomForestClassifier(n_estimators=100, n_jobs=-1, random_state=42)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_importance_table(
    name: str,
    importance: pd.Series,
    top_n: int = 20,
    bottom_n: int = 10,
) -> None:
    """Print top and bottom features from importance Series."""
    print(f"\n{'=' * 60}")
    print(f"{name} Feature Importance")
    print(f"{'=' * 60}")

    top = importance.head(top_n)
    bottom = importance.tail(bottom_n)

    print(f"\nTop {top_n} features:")
    print(f"{'Rank':<6} {'Feature':<40} {'Importance':>12}")
    print("-" * 60)
    for rank, (feat, imp) in enumerate(top.items(), start=1):
        print(f"{rank:<6} {feat:<40} {imp:>12.6f}")

    print(f"\nBottom {bottom_n} features:")
    print(f"{'Rank':<6} {'Feature':<40} {'Importance':>12}")
    print("-" * 60)
    n_total = len(importance)
    for rank, (feat, imp) in enumerate(bottom.items(), start=n_total - bottom_n + 1):
        print(f"{rank:<6} {feat:<40} {imp:>12.6f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Logging setup
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Parse asset IDs
    asset_ids = [int(x.strip()) for x in args.asset_ids.split(",")]
    logger.info(
        "run_feature_importance: asset_ids=%s tf=%s start=%s end=%s mode=%s model=%s",
        asset_ids,
        args.tf,
        args.start,
        args.end,
        args.mode,
        args.model,
    )

    t0 = time.time()

    # --- Connect ---
    engine = _build_engine()

    # --- Load features ---
    logger.info("Loading cmc_features from DB...")
    df = _load_features(engine, asset_ids, args.tf, args.start, args.end)

    if df.empty:
        logger.error(
            "No data found in cmc_features for asset_ids=%s tf=%s %s to %s. Exiting.",
            asset_ids,
            args.tf,
            args.start,
            args.end,
        )
        sys.exit(1)

    logger.info("Loaded %d rows x %d columns", len(df), len(df.columns))

    # --- Build feature matrix ---
    # Exclude PK columns, raw OHLCV, all-NaN columns
    feature_cols = [
        c for c in df.columns if c not in _EXCLUDE_COLS and df[c].notna().any()
    ]

    # ret_arith must be present for labels; if it's in features remove it to avoid target leakage
    if "ret_arith" not in df.columns:
        logger.error("ret_arith column not found in cmc_features. Cannot build labels.")
        sys.exit(1)

    # Remove ret_arith from features (it IS the label source)
    feature_cols = [c for c in feature_cols if c != "ret_arith"]

    logger.info("Feature columns selected: %d", len(feature_cols))

    X = df[feature_cols].copy()

    # --- Forward-fill and drop any remaining all-NaN rows ---
    X = X.ffill().dropna(axis=1, how="all")
    feature_cols = list(X.columns)

    # Drop rows with any NaN in X (after ffill)
    valid_mask = X.notna().all(axis=1)
    X = X[valid_mask]
    df_valid = df[valid_mask].copy()

    # --- Build binary labels from ret_arith ---
    # 1 = positive return (up), 0 = negative/zero (down)
    y = (df_valid["ret_arith"] > 0).astype(int).values
    logger.info(
        "Labels: %d positive (%.1f%%), %d negative (%.1f%%)",
        y.sum(),
        100.0 * y.sum() / len(y),
        (y == 0).sum(),
        100.0 * (y == 0).sum() / len(y),
    )

    # --- Build t1_series for PurgedKFold ---
    # t1 = label end = ts + 1 bar (1 day for 1D)
    ts_series = df_valid["ts"].reset_index(drop=True)
    t1_series = ts_series + pd.Timedelta(days=1)
    t1_series.index = ts_series.values  # index = label start, value = label end
    X = X.reset_index(drop=True)

    logger.info("Training set: %d samples, %d features", len(X), len(feature_cols))

    # --- Build model ---
    model = _build_model(args.model)

    # --- Run importance ---
    from ta_lab2.ml.feature_importance import compute_mda, compute_sfi

    mda_result: pd.Series | None = None
    sfi_result: pd.Series | None = None

    if args.mode in ("mda", "both"):
        logger.info(
            "Running MDA (n_splits=%d, scoring=%s)...", args.n_splits, args.scoring
        )
        mda_result = compute_mda(
            model=model,
            X=X,
            y=y,
            t1_series=t1_series,
            n_splits=args.n_splits,
            scoring=args.scoring,
        )
        _print_importance_table("MDA", mda_result)

    if args.mode in ("sfi", "both"):
        logger.info("Running SFI (n_splits=%d)...", args.n_splits)
        sfi_result = compute_sfi(
            model=model,
            X=X,
            y=y,
            t1_series=t1_series,
            n_splits=args.n_splits,
            scoring=args.scoring,
        )
        _print_importance_table("SFI", sfi_result)

    duration = time.time() - t0
    logger.info("Feature importance complete in %.1f seconds.", duration)

    # --- Optional CSV output ---
    if args.output_csv:
        frames = {}
        if mda_result is not None:
            frames["mda_importance"] = mda_result
        if sfi_result is not None:
            frames["sfi_importance"] = sfi_result
        if frames:
            out_df = pd.DataFrame(frames)
            out_df.to_csv(args.output_csv)
            logger.info("Wrote importance CSV to %s", args.output_csv)

    # --- Optional experiment logging ---
    if args.log_experiment:
        logger.info("Logging experiment to cmc_ml_experiments...")
        from ta_lab2.ml.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker(engine)
        tracker.ensure_table()

        mda_dict = mda_result.to_dict() if mda_result is not None else None
        sfi_dict = sfi_result.to_dict() if sfi_result is not None else None

        # OOS accuracy: use top MDA feature as proxy (mean of positive importances)
        oos_accuracy: float | None = None
        if mda_result is not None:
            pos = mda_result[mda_result > 0]
            oos_accuracy = float(pos.mean()) if not pos.empty else 0.0

        run_name = f"fi_{args.mode}_{args.model}_{args.tf}"
        experiment_id = tracker.log_run(
            run_name=run_name,
            model_type=args.model,
            model_params={
                "n_estimators": 100,
                "random_state": 42,
                "model_class": args.model,
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
            label_params={"threshold": 0.0, "direction": "up"},
            oos_accuracy=oos_accuracy,
            mda_importances=mda_dict,
            sfi_importances=sfi_dict,
            duration_seconds=duration,
            notes=f"mode={args.mode}",
        )
        logger.info("Experiment logged: experiment_id=%s", experiment_id)
        print(f"\nExperiment logged: {experiment_id}")


if __name__ == "__main__":
    main()
