"""
CLI for Optuna TPE hyperparameter sweep on LightGBM with efficiency comparison.

Uses Optuna's Tree-structured Parzen Estimator (TPE) sampler to optimise
LightGBM hyperparameters (n_estimators, num_leaves, learning_rate,
min_child_samples) on ``cmc_features`` data.  Optionally compares the number
of TPE trials needed to reach near-optimal performance vs the equivalent full
grid search, demonstrating efficiency gains.

Usage
-----
    python -m ta_lab2.scripts.ml.run_optuna_sweep \\
        --asset-ids 1,2 \\
        --tf 1D \\
        --start 2023-01-01 \\
        --end 2025-12-31 \\
        --n-trials 50 \\
        --n-splits 5 \\
        --study-name lgbm_1d_sweep \\
        --grid-comparison \\
        --log-experiment

Notes
-----
- Uses NullPool for SQLAlchemy engine (no connection pooling in CLI process).
- All timestamp columns loaded with pd.to_datetime(utc=True) per MEMORY.md.
- Always passes DataFrames (not numpy arrays) to LightGBM.
- Empty fold guard: skips CV folds with fewer than 2 training samples.
- Optuna verbosity set to WARNING to suppress per-trial logs.
- Optuna imported lazily with a clear ImportError message if not installed.
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
    ]
)

# Hyperparameter search space definition (used for grid comparison sizing)
_SEARCH_SPACE: dict[str, list[Any]] = {
    "n_estimators": [50, 100, 200, 300],  # 4 choices
    "num_leaves": [15, 31, 63, 127],  # 4 choices
    "learning_rate": [0.01, 0.05, 0.1, 0.2],  # 4 choices
    "min_child_samples": [5, 10, 20, 50],  # 4 choices
}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_optuna_sweep",
        description=(
            "Optuna TPE hyperparameter sweep for LightGBM on cmc_features. "
            "Optionally compares efficiency vs full grid search."
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
        "--n-trials",
        type=int,
        default=50,
        help="Number of Optuna trials (default: 50)",
    )
    parser.add_argument(
        "--n-splits",
        type=int,
        default=5,
        help="Number of purged CV folds per trial (default: 5)",
    )
    parser.add_argument(
        "--study-name",
        default="lgbm_sweep",
        help="Optuna study name (default: 'lgbm_sweep')",
    )
    parser.add_argument(
        "--storage",
        default=None,
        help=(
            "Optuna storage URL (e.g. 'sqlite:///optuna.db'). "
            "If None, study is in-memory only (default: None)."
        ),
    )
    parser.add_argument(
        "--direction",
        default="maximize",
        choices=["maximize", "minimize"],
        help="Optimisation direction (default: 'maximize')",
    )
    parser.add_argument(
        "--grid-comparison",
        action="store_true",
        help=(
            "Print grid search efficiency comparison: grid size vs "
            "Optuna trials needed to reach near-optimal."
        ),
    )
    parser.add_argument(
        "--log-experiment",
        action="store_true",
        help="Log best trial results to cmc_ml_experiments via ExperimentTracker",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging (Optuna remains at WARNING level)",
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
# Objective function
# ---------------------------------------------------------------------------


def _make_objective(
    X: pd.DataFrame,
    y: np.ndarray,
    t1_series: pd.Series,
    n_splits: int,
) -> Any:
    """
    Return an Optuna objective function that evaluates a given trial's params.

    The objective trains a LGBMClassifier with the trial's suggested params
    and evaluates OOS accuracy via PurgedKFold.  Returns mean OOS accuracy
    (to maximise, or negate to minimise).
    """
    from ta_lab2.backtests.cv import PurgedKFoldSplitter

    def objective(trial: Any) -> float:
        try:
            from lightgbm import LGBMClassifier
        except ImportError as exc:
            raise ImportError(
                "LightGBM is required for run_optuna_sweep. "
                "Install with: pip install lightgbm==4.6.0"
            ) from exc

        # Suggest hyperparameters — matches _SEARCH_SPACE domain
        n_estimators = trial.suggest_int("n_estimators", 50, 300)
        num_leaves = trial.suggest_int("num_leaves", 15, 127)
        learning_rate = trial.suggest_float("learning_rate", 0.01, 0.2, log=True)
        min_child_samples = trial.suggest_int("min_child_samples", 5, 50)

        model = LGBMClassifier(
            n_estimators=n_estimators,
            num_leaves=num_leaves,
            learning_rate=learning_rate,
            min_child_samples=min_child_samples,
            random_state=42,
            verbose=-1,
        )

        cv = PurgedKFoldSplitter(
            n_splits=n_splits, t1_series=t1_series, embargo_frac=0.01
        )
        fold_scores: list[float] = []

        for train_idx, test_idx in cv.split(X):
            # Empty fold guard
            if len(train_idx) < 2 or len(test_idx) < 2:
                continue

            X_tr = X.iloc[train_idx]
            y_tr = y[train_idx]
            X_te = X.iloc[test_idx]
            y_te = y[test_idx]

            # Need at least 2 classes in training
            if len(np.unique(y_tr)) < 2:
                continue

            m = clone(model)
            m.fit(X_tr, y_tr)
            preds = m.predict(X_te)
            fold_scores.append(accuracy_score(y_te, preds))

        if not fold_scores:
            # Optuna requires a numeric return — return worst possible
            return 0.0

        return float(np.mean(fold_scores))

    return objective


# ---------------------------------------------------------------------------
# Grid comparison
# ---------------------------------------------------------------------------


def _compute_grid_comparison(
    study: Any,
    n_trials: int,
) -> None:
    """Print efficiency comparison: TPE vs full grid search."""
    # Compute grid size
    grid_size = 1
    for values in _SEARCH_SPACE.values():
        grid_size *= len(values)

    trials = study.trials
    if not trials:
        logger.warning("No completed trials — cannot compute grid comparison.")
        return

    # Find the best value seen so far in each trial (cumulative max)
    trial_values = [t.value for t in trials if t.value is not None]
    if not trial_values:
        return

    cummax = np.maximum.accumulate(trial_values)
    best_final = cummax[-1]

    # Near-optimal threshold: 99% of best
    threshold = 0.99 * best_final
    trials_to_near_optimal = next(
        (i + 1 for i, v in enumerate(cummax) if v >= threshold),
        n_trials,
    )

    efficiency_gain = grid_size / trials_to_near_optimal

    print("\n" + "=" * 65)
    print("Grid Search vs Optuna TPE — Efficiency Comparison")
    print("=" * 65)
    print("\nSearch space:")
    for param, values in _SEARCH_SPACE.items():
        print(f"  {param:<25}: {values}")
    print(f"\n{'Full grid size':<40}: {grid_size:>6} trials")
    print(f"{'Optuna trials run':<40}: {n_trials:>6} trials")
    print(f"{'Trials to reach 99% of best':<40}: {trials_to_near_optimal:>6} trials")
    print(f"{'Best OOS accuracy found':<40}: {best_final:>6.4f}")
    print(f"{'Efficiency gain (grid / near-optimal)':<40}: {efficiency_gain:>6.1f}x")
    print(
        f"\nConclusion: Optuna TPE found near-optimal params in "
        f"{trials_to_near_optimal}/{grid_size} trials "
        f"({100.0 * trials_to_near_optimal / grid_size:.1f}% of full grid), "
        f"a {efficiency_gain:.1f}x speed-up."
    )
    print()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_best_params(study: Any, direction: str) -> None:
    """Print the best trial's parameters and score."""
    best = study.best_trial
    print("\n" + "=" * 65)
    print("Optuna TPE Sweep — Best Trial")
    print("=" * 65)
    print(f"  Trial number : {best.number}")
    print(f"  OOS Accuracy : {best.value:.4f}")
    print(f"  Direction    : {direction}")
    print("\nBest hyperparameters:")
    for k, v in sorted(best.params.items()):
        print(f"  {k:<25}: {v}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint."""
    # Check optuna availability early — clear error message
    try:
        import optuna  # noqa: PLC0415
    except ImportError as exc:
        print(
            "ERROR: optuna is not installed. Install with: pip install optuna",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    parser = _build_parser()
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Keep Optuna's own logger quiet regardless of --verbose
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    asset_ids = [int(x.strip()) for x in args.asset_ids.split(",")]
    logger.info(
        "run_optuna_sweep: asset_ids=%s tf=%s start=%s end=%s n_trials=%d n_splits=%d",
        asset_ids,
        args.tf,
        args.start,
        args.end,
        args.n_trials,
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
    feature_cols = [
        c
        for c in df.columns
        if c not in _EXCLUDE_COLS and df[c].notna().any() and c != "ret_arith"
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
    ts_series = df_valid["ts"].reset_index(drop=True)
    t1_values = (ts_series + pd.Timedelta(days=1)).values
    t1_series = pd.Series(t1_values, index=ts_series.values)

    logger.info("Training set: %d samples, %d features", len(X), len(feature_cols))

    # --- Create Optuna study ---
    study_kwargs: dict[str, Any] = {
        "study_name": args.study_name,
        "direction": args.direction,
        "sampler": optuna.samplers.TPESampler(seed=42),
    }
    if args.storage:
        study_kwargs["storage"] = args.storage
        study_kwargs["load_if_exists"] = True

    logger.info(
        "Creating Optuna study '%s' (direction=%s, sampler=TPE, seed=42)...",
        args.study_name,
        args.direction,
    )
    study = optuna.create_study(**study_kwargs)

    # --- Define and run objective ---
    objective = _make_objective(X, y, t1_series, args.n_splits)

    logger.info("Running %d Optuna trials...", args.n_trials)
    study.optimize(objective, n_trials=args.n_trials, show_progress_bar=False)

    duration = time.time() - t0
    logger.info("Optuna sweep complete in %.1f seconds.", duration)

    # --- Print best params ---
    _print_best_params(study, args.direction)

    # --- Optional grid comparison ---
    if args.grid_comparison:
        _compute_grid_comparison(study, args.n_trials)

    # --- Optional experiment logging ---
    if args.log_experiment:
        logger.info("Logging best trial to cmc_ml_experiments...")
        from ta_lab2.ml.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker(engine)
        tracker.ensure_table()

        best_params = dict(study.best_trial.params)
        best_value = float(study.best_value)

        experiment_id = tracker.log_run(
            run_name=f"optuna_{args.study_name}_{args.tf}",
            model_type="lgbm",
            model_params={**best_params, "random_state": 42},
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
            oos_accuracy=best_value,
            regime_routing=False,
            optuna_study_name=args.study_name,
            optuna_n_trials=args.n_trials,
            optuna_best_params=best_params,
            duration_seconds=duration,
            notes=(
                f"Optuna TPE sweep; direction={args.direction}; "
                f"n_trials={args.n_trials}; best_value={best_value:.4f}"
            ),
        )
        logger.info("Experiment logged: %s", experiment_id)
        print(f"Experiment logged: {experiment_id}")


if __name__ == "__main__":
    main()
