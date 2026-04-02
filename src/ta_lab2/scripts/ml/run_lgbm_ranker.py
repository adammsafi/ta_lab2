"""
CLI for training and evaluating the cross-sectional LGBMRanker.

Loads CTF+AMA features from the database, trains a CrossSectionalRanker with
purged K-Fold cross-validation, logs metrics to ml_experiments, and optionally
pickles the full-data model to models/lgbm_ranker_latest.pkl.

Usage
-----
    # Dry-run: loads data and prints shape only
    python -m ta_lab2.scripts.ml.run_lgbm_ranker --dry-run

    # Full CV with default settings (1D TF, 5 folds)
    python -m ta_lab2.scripts.ml.run_lgbm_ranker --tf 1D

    # CV + save full-data model
    python -m ta_lab2.scripts.ml.run_lgbm_ranker --tf 1D --train-full

    # Custom settings
    python -m ta_lab2.scripts.ml.run_lgbm_ranker \\
        --tf 1D \\
        --venue-id 1 \\
        --n-splits 5 \\
        --embargo-frac 0.01 \\
        --train-full

Notes
-----
- Uses NullPool for SQLAlchemy engine (no connection pooling in CLI process).
- All timestamp columns loaded with pd.to_datetime(utc=True) per MEMORY.md.
- Any file I/O uses encoding='utf-8' (MEMORY.md Windows pitfall).
- Model pickled to models/lgbm_ranker_latest.pkl if --train-full is set.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_lgbm_ranker",
        description=(
            "Train LGBMRanker cross-sectional ranker on CTF+AMA features with "
            "purged K-Fold CV and log results to ml_experiments."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe string, e.g. '1D' or '4H' (default: '1D')",
    )
    parser.add_argument(
        "--venue-id",
        type=int,
        default=1,
        help="Venue ID filter (default: 1 = CMC_AGG)",
    )
    parser.add_argument(
        "--n-splits",
        type=int,
        default=5,
        help="Number of purged CV folds (default: 5)",
    )
    parser.add_argument(
        "--embargo-frac",
        type=float,
        default=0.01,
        help="Embargo fraction applied after each test fold (default: 0.01)",
    )
    parser.add_argument(
        "--train-full",
        action="store_true",
        help="After CV, train on full data and pickle to models/lgbm_ranker_latest.pkl",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load features and print shape/date-range only; do not train",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


# ---------------------------------------------------------------------------
# DB engine
# ---------------------------------------------------------------------------


def _build_engine() -> Any:
    """Build NullPool SQLAlchemy engine from ta_lab2 config."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from ta_lab2.config import TARGET_DB_URL

    if not TARGET_DB_URL:
        raise RuntimeError(
            "TARGET_DB_URL is not set. "
            "Configure db_config.env or set the TARGET_DB_URL environment variable."
        )
    return create_engine(TARGET_DB_URL, poolclass=NullPool)


# ---------------------------------------------------------------------------
# Model persistence
# ---------------------------------------------------------------------------


def _pickle_model(model: Any, output_path: Path) -> None:
    """Pickle the trained model to output_path."""
    import pickle

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pickle.dump(model, f)
    logger.info("Model pickled to %s", output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from ta_lab2.ml.ranker import CrossSectionalRanker

    engine = _build_engine()
    ranker = CrossSectionalRanker()

    # ------------------------------------------------------------------
    # Load features
    # ------------------------------------------------------------------
    logger.info("Loading features for tf=%s venue_id=%d ...", args.tf, args.venue_id)
    t0 = time.time()
    df = ranker.load_features(engine, tf=args.tf, venue_id=args.venue_id)
    elapsed_load = time.time() - t0

    if df.empty:
        logger.error("No features loaded — check database and Phase 98 CTF promotion.")
        return 1

    feature_cols = CrossSectionalRanker._get_feature_cols(df)
    n_features = len(feature_cols)
    n_assets = df["asset_id"].nunique()
    n_rows = len(df)
    date_min = df["ts"].min()
    date_max = df["ts"].max()

    print("\n--- Feature summary ---")
    print(f"  Rows:     {n_rows:,}")
    print(f"  Assets:   {n_assets}")
    print(f"  Features: {n_features}")
    print(f"  Date range: {date_min.date()} to {date_max.date()}")
    print(f"  Load time: {elapsed_load:.1f}s\n")

    if args.dry_run:
        logger.info("--dry-run: skipping training")
        return 0

    # ------------------------------------------------------------------
    # Cross-validation
    # ------------------------------------------------------------------
    logger.info(
        "Running purged %d-fold CV (embargo_frac=%.3f) ...",
        args.n_splits,
        args.embargo_frac,
    )
    t1 = time.time()
    cv_results = ranker.cross_validate(
        df,
        n_splits=args.n_splits,
        embargo_frac=args.embargo_frac,
    )
    elapsed_cv = time.time() - t1

    print("--- CV results ---")
    for fold_i, (ic, ndcg) in enumerate(
        zip(cv_results["fold_ics"], cv_results["fold_ndcgs"])
    ):
        print(f"  Fold {fold_i + 1}: IC={ic:.4f}  NDCG={ndcg:.4f}")
    print(f"  Mean IC:   {cv_results['mean_ic']:.4f}")
    print(f"  IC-IR:     {cv_results['ic_ir']:.4f}")
    print(f"  Mean NDCG: {cv_results['mean_ndcg']:.4f}")
    print(f"  CV time:   {elapsed_cv:.1f}s\n")

    # ------------------------------------------------------------------
    # Log to ml_experiments
    # ------------------------------------------------------------------

    asset_ids = sorted(df["asset_id"].unique().tolist())
    train_start = df["ts"].min()
    train_end = df["ts"].max()

    experiment_id = ranker.log_results(
        engine=engine,
        cv_results=cv_results,
        feature_names=cv_results["feature_names"],
        tf=args.tf,
        venue_id=args.venue_id,
        asset_ids=asset_ids,
        n_splits=args.n_splits,
        embargo_frac=args.embargo_frac,
        train_start=train_start,
        train_end=train_end,
    )
    print(f"Experiment logged: {experiment_id}\n")

    # ------------------------------------------------------------------
    # Optional: train on full data and pickle model
    # ------------------------------------------------------------------
    if args.train_full:
        logger.info("Training on full dataset ...")
        t2 = time.time()
        model = ranker.train_full(df)
        elapsed_full = time.time() - t2
        logger.info("train_full completed in %.1fs", elapsed_full)

        # Determine project root (4 parents up from this file:
        # scripts/ml -> scripts -> ta_lab2 -> src -> project_root)
        here = Path(__file__).resolve()
        project_root = here.parent.parent.parent.parent.parent
        output_path = project_root / "models" / "lgbm_ranker_latest.pkl"
        _pickle_model(model, output_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
