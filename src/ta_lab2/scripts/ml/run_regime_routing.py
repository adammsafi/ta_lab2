"""
CLI for regime-routed backtest comparison vs single global model.

Loads ``features`` for the given asset IDs / timeframe / date range,
joins ``regimes`` L2 labels, trains a ``RegimeRouter`` (per-regime
sub-models) **and** a single global LGBMClassifier / RandomForest, evaluates
both using purged cross-validation, and prints a comparison table.

Usage
-----
    python -m ta_lab2.scripts.ml.run_regime_routing \\
        --asset-ids 1,2 \\
        --tf 1D \\
        --start 2023-01-01 \\
        --end 2025-12-31 \\
        --n-splits 5 \\
        --min-regime-samples 30 \\
        --log-experiment

Notes
-----
- Uses NullPool for SQLAlchemy engine (no connection pooling in CLI process).
- All timestamp columns loaded with pd.to_datetime(utc=True) per MEMORY.md.
- Always passes DataFrames (not numpy arrays) to model.fit/predict.
- LightGBM import error handled gracefully (falls back to RandomForest).
- Empty fold guard: skips CV folds with fewer than 2 training samples.
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
        # categorical/string columns from features (not numeric features)
        "asset_class",
        "venue",
    ]
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_regime_routing",
        description=(
            "Train per-regime sub-models (RegimeRouter) and compare to a single "
            "global model using purged cross-validation on features."
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
        "--n-splits",
        type=int,
        default=5,
        help="Number of purged CV folds (default: 5)",
    )
    parser.add_argument(
        "--min-regime-samples",
        type=int,
        default=30,
        help="Minimum samples for a regime to get its own sub-model (default: 30)",
    )
    parser.add_argument(
        "--model",
        choices=["rf", "lgbm"],
        default="lgbm",
        help="Base model: rf (RandomForest) or lgbm (LightGBM) (default: 'lgbm')",
    )
    parser.add_argument(
        "--log-experiment",
        action="store_true",
        help="Log results to ml_experiments via ExperimentTracker",
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
    """Load features for the given asset_ids, tf, and date range."""
    ids_literal = "{" + ",".join(str(i) for i in asset_ids) + "}"
    sql = text(
        """
        SELECT *
        FROM public.features
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


def _load_regimes_batch(
    engine: Any,
    asset_ids: list[int],
    tf: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Load regimes L2 labels for all asset_ids in a single query."""
    ids_literal = "{" + ",".join(str(i) for i in asset_ids) + "}"
    sql = text(
        """
        SELECT id, ts, l2_label
        FROM public.regimes
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
    df["l2_label"] = df["l2_label"].fillna("Unknown")
    return df


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------


def _build_model(model_name: str) -> Any:
    """Return a sklearn-compatible classifier. Falls back to RF if lgbm unavailable."""
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
# Cross-validation helpers
# ---------------------------------------------------------------------------


def _run_purged_cv_global(
    model: Any,
    X: pd.DataFrame,
    y: np.ndarray,
    t1_series: pd.Series,
    n_splits: int,
) -> dict[str, float]:
    """Evaluate a single global model via purged CV. Returns accuracy dict."""
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
        return {"oos_accuracy": float("nan"), "n_folds": 0}

    return {
        "oos_accuracy": float(np.mean(fold_scores)),
        "oos_accuracy_std": float(np.std(fold_scores)),
        "n_folds": len(fold_scores),
    }


def _run_purged_cv_regime_router(
    base_model: Any,
    X: pd.DataFrame,
    y: np.ndarray,
    regimes: pd.Series,
    t1_series: pd.Series,
    n_splits: int,
    min_regime_samples: int,
) -> dict[str, Any]:
    """Evaluate RegimeRouter via purged CV. Returns accuracy dict + per-regime breakdown."""
    from ta_lab2.backtests.cv import PurgedKFoldSplitter
    from ta_lab2.ml.regime_router import RegimeRouter

    cv = PurgedKFoldSplitter(n_splits=n_splits, t1_series=t1_series, embargo_frac=0.01)
    fold_scores: list[float] = []
    regime_fold_scores: dict[str, list[float]] = {}

    regimes_arr = np.asarray(regimes)

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
        reg_tr = pd.Series(regimes_arr[train_idx])
        reg_te = pd.Series(regimes_arr[test_idx])

        # Need at least 2 classes in training
        if len(np.unique(y_tr)) < 2:
            logger.debug("Skipping fold — single class in training set")
            continue

        router = RegimeRouter(base_model=base_model, min_samples=min_regime_samples)
        router.fit(X_tr, y_tr, reg_tr)
        preds = router.predict(X_te, reg_te)
        fold_scores.append(accuracy_score(y_te, preds))

        # Per-regime breakdown within this fold
        unique_test_regimes = np.unique(regimes_arr[test_idx])
        for regime in unique_test_regimes:
            r_mask = regimes_arr[test_idx] == regime
            if r_mask.sum() < 2:
                continue
            r_score = accuracy_score(y_te[r_mask], preds[r_mask])
            if regime not in regime_fold_scores:
                regime_fold_scores[str(regime)] = []
            regime_fold_scores[str(regime)].append(r_score)

    if not fold_scores:
        return {"oos_accuracy": float("nan"), "n_folds": 0, "per_regime": {}}

    per_regime_mean = {
        r: float(np.mean(scores)) for r, scores in regime_fold_scores.items()
    }

    return {
        "oos_accuracy": float(np.mean(fold_scores)),
        "oos_accuracy_std": float(np.std(fold_scores)),
        "n_folds": len(fold_scores),
        "per_regime": per_regime_mean,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_comparison(
    global_results: dict[str, Any],
    router_results: dict[str, Any],
) -> None:
    """Print side-by-side comparison table."""
    print("\n" + "=" * 65)
    print("Regime Routing vs Global Model — Purged CV Comparison")
    print("=" * 65)
    print(f"\n{'Metric':<35} {'Global':>12} {'RegimeRouter':>12}")
    print("-" * 65)

    g_acc = global_results.get("oos_accuracy", float("nan"))
    r_acc = router_results.get("oos_accuracy", float("nan"))
    g_std = global_results.get("oos_accuracy_std", float("nan"))
    r_std = router_results.get("oos_accuracy_std", float("nan"))
    g_folds = global_results.get("n_folds", 0)
    r_folds = router_results.get("n_folds", 0)

    print(f"{'OOS Accuracy (mean)':<35} {g_acc:>12.4f} {r_acc:>12.4f}")
    print(f"{'OOS Accuracy (std)':<35} {g_std:>12.4f} {r_std:>12.4f}")
    print(f"{'N valid folds':<35} {g_folds:>12d} {r_folds:>12d}")

    delta = r_acc - g_acc
    print(f"\n{'Delta (Router - Global)':<35} {delta:>+12.4f}")

    if abs(delta) < 0.001:
        verdict = "No material difference"
    elif delta > 0:
        verdict = "RegimeRouter BETTER"
    else:
        verdict = "Global model BETTER"
    print(f"{'Verdict':<35} {verdict:>24}")

    per_regime = router_results.get("per_regime", {})
    if per_regime:
        print("\nPer-Regime Accuracy (RegimeRouter):")
        print(f"  {'Regime':<25} {'OOS Accuracy':>12}")
        print("  " + "-" * 38)
        for regime, acc in sorted(per_regime.items()):
            print(f"  {regime:<25} {acc:>12.4f}")

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
        "run_regime_routing: asset_ids=%s tf=%s start=%s end=%s n_splits=%d min_regime_samples=%d",
        asset_ids,
        args.tf,
        args.start,
        args.end,
        args.n_splits,
        args.min_regime_samples,
    )

    t0 = time.time()
    engine = _build_engine()

    # --- Load features ---
    logger.info("Loading features...")
    df = _load_features(engine, asset_ids, args.tf, args.start, args.end)
    if df.empty:
        logger.error(
            "No data in features for asset_ids=%s tf=%s %s to %s. Exiting.",
            asset_ids,
            args.tf,
            args.start,
            args.end,
        )
        sys.exit(1)
    logger.info("Loaded %d rows x %d columns", len(df), len(df.columns))

    # --- Load regimes ---
    logger.info("Loading regimes...")
    reg_df = _load_regimes_batch(engine, asset_ids, args.tf, args.start, args.end)

    # --- Build feature matrix ---
    # Exclude non-numeric dtypes (features has string/datetime cols: asset_class, venue, updated_at)
    feature_cols = [
        c
        for c in df.columns
        if c not in _EXCLUDE_COLS
        and df[c].notna().any()
        and c != "ret_arith"
        and pd.api.types.is_numeric_dtype(df[c])
    ]

    if "ret_arith" not in df.columns:
        logger.error("ret_arith column not found in features. Cannot build labels.")
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

    # --- Join regime labels ---
    if not reg_df.empty:
        # Build a (id, ts) -> l2_label lookup
        reg_df = reg_df.set_index(["id", "ts"])["l2_label"]
        pairs = list(zip(df_valid["id"].values, df_valid["ts"].values))
        regimes_list = []
        for asset_id, ts in pairs:
            try:
                label = reg_df.loc[(asset_id, ts)]
            except KeyError:
                label = "Unknown"
            regimes_list.append(label)
        regimes = pd.Series(regimes_list)
    else:
        logger.warning("No regime data found — using 'Unknown' for all rows.")
        regimes = pd.Series(["Unknown"] * len(X))

    unique_regimes = regimes.unique()
    logger.info("Regime distribution: %s", dict(regimes.value_counts()))

    # --- Build model ---
    base_model = _build_model(args.model)

    # --- Run global CV ---
    logger.info("Running purged CV for global model (n_splits=%d)...", args.n_splits)
    global_results = _run_purged_cv_global(base_model, X, y, t1_series, args.n_splits)
    logger.info(
        "Global OOS accuracy: %.4f", global_results.get("oos_accuracy", float("nan"))
    )

    # --- Run regime-routed CV ---
    logger.info("Running purged CV for RegimeRouter (n_splits=%d)...", args.n_splits)
    router_results = _run_purged_cv_regime_router(
        base_model, X, y, regimes, t1_series, args.n_splits, args.min_regime_samples
    )
    logger.info(
        "Regime-routed OOS accuracy: %.4f",
        router_results.get("oos_accuracy", float("nan")),
    )

    duration = time.time() - t0
    logger.info("Regime routing comparison complete in %.1f seconds.", duration)

    # --- Print comparison ---
    _print_comparison(global_results, router_results)

    # --- Optional experiment logging ---
    if args.log_experiment:
        logger.info("Logging experiments to ml_experiments...")
        from ta_lab2.ml.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker(engine)
        tracker.ensure_table()

        # Log global model
        global_eid = tracker.log_run(
            run_name=f"global_{args.model}_{args.tf}",
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
            label_params={"threshold": 0.0},
            oos_accuracy=global_results.get("oos_accuracy"),
            n_oos_folds=global_results.get("n_folds"),
            regime_routing=False,
            duration_seconds=duration / 2,
            notes="global baseline for regime routing comparison",
        )
        logger.info("Global experiment logged: %s", global_eid)

        # Log regime router
        router_eid = tracker.log_run(
            run_name=f"regime_router_{args.model}_{args.tf}",
            model_type="regime_routed",
            model_params={
                "n_estimators": 100,
                "random_state": 42,
                "model_class": args.model,
                "min_regime_samples": args.min_regime_samples,
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
            oos_accuracy=router_results.get("oos_accuracy"),
            n_oos_folds=router_results.get("n_folds"),
            regime_routing=True,
            regime_performance=router_results.get("per_regime", {}),
            duration_seconds=duration / 2,
            notes=(
                f"regime_router; unique_regimes={list(unique_regimes)}; "
                f"min_regime_samples={args.min_regime_samples}"
            ),
        )
        logger.info("RegimeRouter experiment logged: %s", router_eid)
        print(f"Experiments logged: global={global_eid}  router={router_eid}")


if __name__ == "__main__":
    main()
