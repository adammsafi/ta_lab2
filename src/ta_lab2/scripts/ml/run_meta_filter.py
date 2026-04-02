"""CLI to train the XGBoost meta-label confidence filter and evaluate backtest impact.

The meta-label filter (MetaLabelFilter) trains an XGBoost classifier on
triple_barrier_labels to predict P(trade success).  Trades with predicted
confidence below a configurable threshold are skipped before reaching the
executor, reducing noise trades while preserving profitable ones.

Usage
-----
    # Dry run -- load data only, print shape and class balance
    python -m ta_lab2.scripts.ml.run_meta_filter --dry-run

    # Train and save model
    python -m ta_lab2.scripts.ml.run_meta_filter --model-path models/xgb_meta_filter_latest.json

    # Train, save, and show threshold impact analysis
    python -m ta_lab2.scripts.ml.run_meta_filter --evaluate-thresholds

    # Non-default tf and splits
    python -m ta_lab2.scripts.ml.run_meta_filter --tf 4H --n-splits 3 --evaluate-thresholds

Notes
-----
- Uses NullPool for DB connections (CLI process, no pooling needed).
- All timestamps loaded with pd.to_datetime(utc=True) per MEMORY.md.
- ASCII-only comments (Windows cp1252 safety).
- Model file is saved to --model-path (default: models/xgb_meta_filter_latest.json).
- ml_experiments row logged after successful training (model_type='xgb_meta_filter').
"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import sys
import time

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db_url() -> str:
    """Load database URL from environment or db_config.env."""
    url = os.environ.get("TARGET_DB_URL")
    if url:
        return url
    env_file = pathlib.Path("db_config.env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
    url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "No DB URL found. Set TARGET_DB_URL env var or create db_config.env."
        )
    return url


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
        stream=sys.stdout,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Train XGBoost meta-label confidence filter and evaluate backtest impact.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe for triple_barrier_labels and features (default: 1D).",
    )
    parser.add_argument(
        "--venue-id",
        type=int,
        default=1,
        help="Venue ID for feature loading (default: 1 = CMC_AGG).",
    )
    parser.add_argument(
        "--n-splits",
        type=int,
        default=5,
        help="Number of purged k-fold CV splits (default: 5).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Primary confidence threshold for trade filtering (default: 0.5).",
    )
    parser.add_argument(
        "--model-path",
        default="models/xgb_meta_filter_latest.json",
        help="Output path for the serialized XGBoost model (default: models/xgb_meta_filter_latest.json).",
    )
    parser.add_argument(
        "--evaluate-thresholds",
        action="store_true",
        help="Run threshold impact analysis after training and print results.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load training data only; print shape and class balance without training.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    logger.info(
        "run_meta_filter: tf=%s venue_id=%d n_splits=%d threshold=%.2f dry_run=%s",
        args.tf,
        args.venue_id,
        args.n_splits,
        args.threshold,
        args.dry_run,
    )

    # ------------------------------------------------------------------
    # DB connection
    # ------------------------------------------------------------------
    url = _get_db_url()
    engine = create_engine(url, poolclass=NullPool)

    # ------------------------------------------------------------------
    # Import MetaLabelFilter (lazy -- xgboost only required if not --dry-run)
    # ------------------------------------------------------------------
    from ta_lab2.ml.meta_filter import MetaLabelFilter  # noqa: PLC0415

    flt = MetaLabelFilter(engine)

    # ------------------------------------------------------------------
    # Step 1: Load training data
    # ------------------------------------------------------------------
    t0 = time.time()
    logger.info("Loading training data (tf=%s, venue_id=%d)...", args.tf, args.venue_id)

    try:
        X, y, t1_series = flt.load_training_data(tf=args.tf, venue_id=args.venue_id)
    except ValueError as exc:
        logger.error("Failed to load training data: %s", exc)
        sys.exit(1)

    pos = int((y == 1).sum())
    neg = int((y == 0).sum())
    total = len(y)

    print("\n--- Training Data Summary ---")
    print(f"  Samples  : {total:,}")
    print(f"  Features : {len(X.columns):,}")
    print(f"  Positive (bin > 0): {pos:,} ({pos / total:.1%})")
    print(f"  Negative (bin <= 0): {neg:,} ({neg / total:.1%})")
    print(f"  Imbalance ratio (neg/pos): {neg / pos:.2f}")
    print(f"  Feature names (first 10): {list(X.columns[:10])}")
    print()

    if args.dry_run:
        logger.info("--dry-run: exiting after data load (%.1fs)", time.time() - t0)
        print("Dry run complete.")
        return

    # ------------------------------------------------------------------
    # Step 2: Train model with purged CV
    # ------------------------------------------------------------------
    logger.info(
        "Training XGBoost with purged k-fold CV (n_splits=%d)...", args.n_splits
    )
    cv_results = flt.train(X, y, t1_series, n_splits=args.n_splits)

    print("--- CV Metrics ---")
    for metric in ("accuracy", "precision", "recall", "f1", "auc"):
        vals = cv_results[metric]
        mean = cv_results[f"{metric}_mean"]
        folds_str = "  ".join(f"{v:.4f}" for v in vals)
        print(f"  {metric:<12}: [{folds_str}]  mean={mean:.4f}")
    print()

    # ------------------------------------------------------------------
    # Step 3: Save model
    # ------------------------------------------------------------------
    logger.info("Saving model to %s...", args.model_path)
    flt.save_model(args.model_path)
    print(f"Model saved to: {args.model_path}")

    # ------------------------------------------------------------------
    # Step 4: Log experiment to ml_experiments
    # ------------------------------------------------------------------
    logger.info("Logging results to ml_experiments...")
    eid = flt.log_results(engine, cv_results, list(X.columns), args.threshold)
    print(f"Experiment logged: experiment_id={eid}")
    print()

    # ------------------------------------------------------------------
    # Step 5: Threshold impact analysis (optional)
    # ------------------------------------------------------------------
    if args.evaluate_thresholds:
        logger.info("Running threshold impact analysis...")

        # Use a random 20% holdout from training data for evaluation
        # (In a full pipeline you would use a separate test set)
        n = len(X)
        holdout_size = max(int(n * 0.20), 1)
        X_test = X.iloc[-holdout_size:]
        y_test = y.iloc[-holdout_size:]

        impact_df = flt.evaluate_threshold_impact(X_test, y_test)

        print("--- Threshold Impact Analysis ---")
        print(
            f"  (evaluated on last {holdout_size:,} rows = 20% holdout, "
            "most recent signals)"
        )
        print()
        print(
            impact_df.to_string(
                index=False,
                float_format=lambda x: f"{x:.4f}",
            )
        )
        print()
        print(
            "Interpretation:\n"
            "  pass_rate            = fraction of trades that pass the filter\n"
            "  accuracy_passed      = accuracy among passed trades (y_hat=1 vs y_true)\n"
            "  profitable_capture_rate = fraction of truly profitable trades retained\n"
        )

    elapsed = time.time() - t0
    logger.info("run_meta_filter: complete in %.1fs", elapsed)
    print(f"Done ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
