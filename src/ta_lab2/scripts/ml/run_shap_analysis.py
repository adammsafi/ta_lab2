"""
CLI for SHAP TreeExplainer interaction analysis on LGBMRanker.

Loads CTF+AMA features, trains a CrossSectionalRanker via train_full() (or
loads a previously pickled model if one exists), runs SHAP TreeExplainer to
compute main-effect SHAP values and pairwise interaction values, prints the
top interaction pairs to stdout, writes a markdown report, and optionally
updates feature_selection.yaml with an ``interactions`` key.

Findings are also logged to ml_experiments via ExperimentTracker.

Usage
-----
    # Basic: run analysis and print results
    python -m ta_lab2.scripts.ml.run_shap_analysis --tf 1D

    # With report to non-default path
    python -m ta_lab2.scripts.ml.run_shap_analysis \\
        --tf 1D --report-path /path/to/report.md

    # Write findings back to feature_selection.yaml
    python -m ta_lab2.scripts.ml.run_shap_analysis \\
        --tf 1D --update-yaml

    # Use existing pickled model (skip train_full if pkl exists)
    python -m ta_lab2.scripts.ml.run_shap_analysis \\
        --tf 1D --model-path models/lgbm_ranker_latest.pkl

Notes
-----
- Uses NullPool (no connection pooling) for CLI process.
- All file I/O uses encoding='utf-8' per MEMORY.md Windows pitfall.
- SHAP interaction computation is memory-intensive; max_samples=500
  (default) keeps peak memory < 2 GB for typical feature counts.
- The default report path is reports/ml/shap_interaction_report.md
  (relative to project root, not cwd).
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
# Helpers
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_shap_analysis",
        description=(
            "SHAP TreeExplainer interaction analysis on LGBMRanker. "
            "Identifies top feature interaction pairs from the cross-sectional ranker."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe string (default: '1D')",
    )
    parser.add_argument(
        "--venue-id",
        type=int,
        default=1,
        help="Venue ID filter (default: 1 = CMC_AGG)",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=500,
        help="Max samples for SHAP computation (default: 500; memory safety)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of top interaction pairs to report (default: 5)",
    )
    parser.add_argument(
        "--top-k-features",
        type=int,
        default=20,
        help="Number of top SHAP features to report (default: 20)",
    )
    parser.add_argument(
        "--update-yaml",
        action="store_true",
        help="Write top interaction findings to configs/feature_selection.yaml",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help=(
            "Output path for markdown report "
            "(default: reports/ml/shap_interaction_report.md)"
        ),
    )
    parser.add_argument(
        "--model-path",
        default=None,
        help=(
            "Path to pickled LGBMRanker model. "
            "If provided and the file exists, skip train_full(). "
            "(default: models/lgbm_ranker_latest.pkl)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load features and print shape only; do not run SHAP",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


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


def _project_root() -> Path:
    """Return project root (4 parents up from this file: scripts/ml -> scripts -> ta_lab2 -> src -> root)."""
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def _load_or_train_model(
    ranker: Any,
    df: Any,
    model_path: Path,
) -> Any:
    """Load pickled model if it exists; otherwise call train_full()."""
    import pickle

    if model_path.exists():
        logger.info("Loading pickled model from %s ...", model_path)
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        # Sync feature_names_ from df (pickle may not have it)
        from ta_lab2.ml.ranker import CrossSectionalRanker

        feature_cols = CrossSectionalRanker._get_feature_cols(df)
        ranker.feature_names_ = feature_cols
        ranker.model_ = model
        logger.info("Model loaded from pickle")
        return model

    logger.info("No pickled model found at %s — calling train_full() ...", model_path)
    t0 = time.time()
    model = ranker.train_full(df)
    elapsed = time.time() - t0
    logger.info("train_full() completed in %.1fs", elapsed)

    # Persist for future runs
    model_path.parent.mkdir(parents=True, exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    logger.info("Model pickled to %s", model_path)

    return model


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    root = _project_root()

    # Resolve paths
    model_path = (
        Path(args.model_path)
        if args.model_path
        else root / "models" / "lgbm_ranker_latest.pkl"
    )
    report_path = (
        Path(args.report_path)
        if args.report_path
        else root / "reports" / "ml" / "shap_interaction_report.md"
    )
    yaml_path = root / "configs" / "feature_selection.yaml"

    from ta_lab2.ml.ranker import CrossSectionalRanker
    from ta_lab2.ml.shap_analysis import RankerShapAnalyzer

    engine = _build_engine()
    ranker = CrossSectionalRanker()

    # ------------------------------------------------------------------
    # Load features
    # ------------------------------------------------------------------
    logger.info("Loading features: tf=%s venue_id=%d ...", args.tf, args.venue_id)
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
        logger.info("--dry-run: skipping SHAP analysis")
        return 0

    # ------------------------------------------------------------------
    # Load or train model
    # ------------------------------------------------------------------
    model = _load_or_train_model(ranker, df, model_path)

    # ------------------------------------------------------------------
    # Build feature matrix for SHAP
    # ------------------------------------------------------------------
    import numpy as np

    feature_cols = ranker.feature_names_ or CrossSectionalRanker._get_feature_cols(df)
    X_full = df[feature_cols].astype(float).values

    # Fill NaN with column medians (same imputation as train_full)
    col_medians = np.nanmedian(X_full, axis=0)
    nan_mask = np.isnan(X_full)
    X_full = X_full.copy()
    inds = np.where(nan_mask)
    X_full[inds] = np.take(col_medians, inds[1])

    # ------------------------------------------------------------------
    # SHAP analysis
    # ------------------------------------------------------------------
    analyzer = RankerShapAnalyzer(model=model, feature_names=feature_cols)

    logger.info("Computing SHAP values (max_samples=%d) ...", args.max_samples)
    t_shap = time.time()
    analyzer.compute_shap_values(X_full, max_samples=args.max_samples)
    elapsed_shap = time.time() - t_shap
    logger.info("SHAP values done in %.1fs", elapsed_shap)

    logger.info(
        "Computing SHAP interaction values (max_samples=%d) ...", args.max_samples
    )
    t_interact = time.time()
    analyzer.compute_interaction_values(X_full, max_samples=args.max_samples)
    elapsed_interact = time.time() - t_interact
    logger.info("Interaction values done in %.1fs", elapsed_interact)

    # ------------------------------------------------------------------
    # Print results
    # ------------------------------------------------------------------
    top_pairs = analyzer.top_interaction_pairs(k=args.top_k)
    top_features = analyzer.top_shap_features(k=args.top_k_features)

    print(f"\n--- Top {args.top_k} SHAP Interaction Pairs ---")
    print(f"  {'Rank':<5} {'Feature A':<40} {'Feature B':<40} {'Strength':>12}")
    print(f"  {'-' * 5} {'-' * 40} {'-' * 40} {'-' * 12}")
    for rank, pair in enumerate(top_pairs, start=1):
        print(
            f"  {rank:<5} {pair['feature_a']:<40} {pair['feature_b']:<40} "
            f"{pair['mean_abs_interaction']:>12.6f}"
        )

    print(f"\n--- Top {args.top_k_features} SHAP Features ---")
    print(f"  {'Rank':<5} {'Feature':<50} {'Mean|SHAP|':>12}")
    print(f"  {'-' * 5} {'-' * 50} {'-' * 12}")
    for rank, feat in enumerate(top_features, start=1):
        print(f"  {rank:<5} {feat['feature']:<50} {feat['mean_abs_shap']:>12.6f}")
    print()

    # ------------------------------------------------------------------
    # Generate and write markdown report
    # ------------------------------------------------------------------
    report_md = analyzer.generate_report(
        top_k_interactions=args.top_k,
        top_k_features=args.top_k_features,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    logger.info("Report written to %s", report_path)

    # ------------------------------------------------------------------
    # Update feature_selection.yaml
    # ------------------------------------------------------------------
    if args.update_yaml:
        analyzer.update_feature_selection(
            yaml_path=str(yaml_path),
            engine=engine,
            top_k_interactions=args.top_k,
        )
        logger.info("feature_selection.yaml updated with interactions key")

    # ------------------------------------------------------------------
    # Log to ml_experiments
    # ------------------------------------------------------------------
    try:
        from ta_lab2.ml.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker(engine)
        tracker.ensure_table()

        top_pairs_note = ", ".join(
            f"{p['feature_a']}+{p['feature_b']}({p['mean_abs_interaction']:.4f})"
            for p in top_pairs
        )

        experiment_id = tracker.log_run(
            run_name="shap_interaction_analysis_v1",
            model_type="shap_analysis",
            model_params={
                "max_samples": args.max_samples,
                "top_k_interactions": args.top_k,
                "top_k_features": args.top_k_features,
            },
            feature_set=list(feature_cols),
            cv_method="none",
            train_start="2000-01-01",
            train_end="2099-12-31",
            asset_ids=[],
            tf=args.tf,
            cv_n_splits=0,
            cv_embargo_frac=0.0,
            oos_accuracy=float(top_pairs[0]["mean_abs_interaction"])
            if top_pairs
            else 0.0,
            oos_sharpe=0.0,
            n_oos_folds=0,
            notes=f"SHAP interaction analysis | top_pairs: {top_pairs_note}",
        )
        logger.info("Logged to ml_experiments: experiment_id=%s", experiment_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to log to ml_experiments: %s", exc)

    print(f"\nReport: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
