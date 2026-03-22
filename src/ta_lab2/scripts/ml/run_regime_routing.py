"""
CLI for regime-routed backtest comparison vs single global model.

Loads ``features`` for the given asset IDs / timeframe / date range,
optionally joins AMA features from ``ama_multi_tf_u`` (via ``parse_active_features``),
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
        --use-ama \\
        --log-experiment

    # Skip AMA loading (original bar-level-only behavior):
    python -m ta_lab2.scripts.ml.run_regime_routing \\
        --asset-ids 1 --tf 1D --no-ama

    # Include conditional-tier features for per-regime sub-models:
    python -m ta_lab2.scripts.ml.run_regime_routing \\
        --asset-ids 1 --tf 1D --use-ama --include-conditional

Notes
-----
- Uses NullPool for SQLAlchemy engine (no connection pooling in CLI process).
- All timestamp columns loaded with pd.to_datetime(utc=True) per MEMORY.md.
- Always passes DataFrames (not numpy arrays) to model.fit/predict.
- LightGBM import error handled gracefully (falls back to RandomForest).
- Empty fold guard: skips CV folds with fewer than 2 training samples.
- AMA features joined per-feature (separate SQL each) to avoid column name collisions.
- NaN rows dropped AFTER AMA join (AMA has shorter history for some assets).
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
        "venue_id",
        # categorical/string columns from features (not numeric features)
        "asset_class",
        "venue",
        # label column (target, not a feature)
        "ret_arith",
        "updated_at",
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
    # AMA feature loading (default: enabled)
    parser.add_argument(
        "--use-ama",
        action="store_true",
        default=True,
        help="Load AMA features from ama_multi_tf_u (default: True)",
    )
    parser.add_argument(
        "--no-ama",
        action="store_false",
        dest="use_ama",
        help="Skip AMA feature loading (use only features table)",
    )
    # Conditional-tier features for per-regime sub-models (default: disabled)
    parser.add_argument(
        "--include-conditional",
        action="store_true",
        default=False,
        help="Include conditional-tier features for per-regime sub-models (default: False)",
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


def _load_ama_features_for_asset(
    engine: Any,
    asset_id: int,
    tf: str,
    start: str,
    end: str,
    ama_feature_list: list[dict],
) -> pd.DataFrame:
    """
    Load AMA features from ama_multi_tf_u for a single asset.

    Returns a DataFrame indexed by ts (UTC-aware) with one column per AMA feature.
    Separate SQL per feature to avoid column name collisions (plan 01 pattern).
    """
    result_df: pd.DataFrame | None = None

    for feat in ama_feature_list:
        feat_name = feat["name"]
        indicator = feat["indicator"]
        params_hash_prefix = feat["params_hash"][:8]

        sql = text(
            """
            SELECT ts, ama AS feature_val
            FROM public.ama_multi_tf_u
            WHERE id = :asset_id
              AND venue_id = 1
              AND tf = :tf
              AND indicator = :indicator
              AND LEFT(params_hash, 8) = :params_hash
              AND ts BETWEEN CAST(:start AS TIMESTAMPTZ) AND CAST(:end AS TIMESTAMPTZ)
            ORDER BY ts
            """
        )

        with engine.connect() as conn:
            feat_df = pd.read_sql(
                sql,
                conn,
                params={
                    "asset_id": asset_id,
                    "tf": tf,
                    "indicator": indicator,
                    "params_hash": params_hash_prefix,
                    "start": start,
                    "end": end,
                },
            )

        if feat_df.empty:
            logger.warning(
                "No AMA data for feature '%s' (asset_id=%d, tf=%s, indicator=%s, "
                "params_hash=%s)",
                feat_name,
                asset_id,
                tf,
                indicator,
                params_hash_prefix,
            )
            continue

        # CRITICAL: UTC-aware timestamps (MEMORY.md pitfall)
        feat_df["ts"] = pd.to_datetime(feat_df["ts"], utc=True)
        feat_series = feat_df.set_index("ts")["feature_val"].rename(feat_name)

        if result_df is None:
            result_df = feat_series.to_frame()
        else:
            result_df = result_df.join(feat_series, how="outer")

    if result_df is None:
        return pd.DataFrame()

    logger.debug(
        "_load_ama_features_for_asset: asset_id=%d tf=%s -> %d features, %d rows",
        asset_id,
        tf,
        len(result_df.columns),
        len(result_df),
    )
    return result_df


def _parse_conditional_features(
    yaml_path: str = "configs/feature_selection.yaml",
) -> list[dict]:
    """
    Parse conditional-tier features from feature_selection.yaml.

    Returns a list of dicts with keys: name, indicator, params_hash, source.
    Source is "ama_multi_tf_u" for AMA-derived features (_ama, _d1, _d1_roll suffixes),
    "features" for bar-level features.
    """
    import os

    import yaml

    if not os.path.isabs(yaml_path):
        candidate = yaml_path
        if not os.path.exists(candidate):
            cwd = os.getcwd()
            parts = cwd.replace("\\", "/").split("/")
            for i in range(len(parts), 0, -1):
                root = "/".join(parts[:i])
                candidate = os.path.join(root, yaml_path)
                if os.path.exists(candidate):
                    break
            else:
                candidate = yaml_path

    with open(candidate, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    conditional_entries = config.get("conditional", [])
    features = []

    for entry in conditional_entries:
        name = entry["name"]

        # AMA-derived features: name ends with _ama, _d1, _d1_roll, _d2, _d2_roll
        ama_suffixes = ("_ama", "_d1", "_d1_roll", "_d2", "_d2_roll")
        is_ama = any(name.endswith(sfx) for sfx in ama_suffixes)

        if is_ama:
            # Strip the suffix to find indicator+hash
            suffix_used = next(sfx for sfx in ama_suffixes if name.endswith(sfx))
            body = name[: -len(suffix_used)]  # everything before the suffix
            last_underscore = body.rfind("_")
            if last_underscore == -1:
                logger.warning(
                    "Cannot parse conditional AMA feature name: %s; skipping", name
                )
                continue
            indicator = body[:last_underscore]
            params_hash = body[last_underscore + 1 :]

            # Map suffix to ama_multi_tf_u column
            col_map = {
                "_ama": "ama",
                "_d1": "d1",
                "_d1_roll": "d1_roll",
                "_d2": "d2",
                "_d2_roll": "d2_roll",
            }
            ama_col = col_map[suffix_used]

            features.append(
                {
                    "name": name,
                    "indicator": indicator,
                    "params_hash": params_hash,
                    "ama_col": ama_col,
                    "source": "ama_multi_tf_u",
                }
            )
        else:
            # Bar-level feature (rsi_14, adx_14, bb_*, etc.) - lives in features table
            features.append(
                {
                    "name": name,
                    "indicator": name,
                    "params_hash": "",
                    "ama_col": None,
                    "source": "features",
                }
            )

    return features


def _load_conditional_ama_features_for_asset(
    engine: Any,
    asset_id: int,
    tf: str,
    start: str,
    end: str,
    conditional_ama: list[dict],
) -> pd.DataFrame:
    """
    Load conditional-tier AMA features (d1, d1_roll, d2, d2_roll, ama columns)
    from ama_multi_tf_u for a single asset.

    Returns a DataFrame indexed by ts (UTC-aware) with one column per feature.
    """
    result_df: pd.DataFrame | None = None

    for feat in conditional_ama:
        feat_name = feat["name"]
        indicator = feat["indicator"]
        params_hash_prefix = feat["params_hash"][:8]
        ama_col = feat["ama_col"]

        sql = text(
            f"""
            SELECT ts, {ama_col} AS feature_val
            FROM public.ama_multi_tf_u
            WHERE id = :asset_id
              AND venue_id = 1
              AND tf = :tf
              AND indicator = :indicator
              AND LEFT(params_hash, 8) = :params_hash
              AND ts BETWEEN CAST(:start AS TIMESTAMPTZ) AND CAST(:end AS TIMESTAMPTZ)
            ORDER BY ts
            """
        )

        with engine.connect() as conn:
            feat_df = pd.read_sql(
                sql,
                conn,
                params={
                    "asset_id": asset_id,
                    "tf": tf,
                    "indicator": indicator,
                    "params_hash": params_hash_prefix,
                    "start": start,
                    "end": end,
                },
            )

        if feat_df.empty:
            logger.warning(
                "No AMA data for conditional feature '%s' "
                "(asset_id=%d, tf=%s, indicator=%s, params_hash=%s, col=%s)",
                feat_name,
                asset_id,
                tf,
                indicator,
                params_hash_prefix,
                ama_col,
            )
            continue

        feat_df["ts"] = pd.to_datetime(feat_df["ts"], utc=True)
        feat_series = feat_df.set_index("ts")["feature_val"].rename(feat_name)

        if result_df is None:
            result_df = feat_series.to_frame()
        else:
            result_df = result_df.join(feat_series, how="outer")

    if result_df is None:
        return pd.DataFrame()

    return result_df


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
    # Track the final router for regime stats (last fold)
    final_router: RegimeRouter | None = None

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
        final_router = router

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
        return {
            "oos_accuracy": float("nan"),
            "n_folds": 0,
            "per_regime": {},
            "router_stats": None,
        }

    per_regime_mean = {
        r: float(np.mean(scores)) for r, scores in regime_fold_scores.items()
    }

    # Get regime stats from the final router (last fold)
    router_stats = final_router.get_regime_stats() if final_router is not None else None

    return {
        "oos_accuracy": float(np.mean(fold_scores)),
        "oos_accuracy_std": float(np.std(fold_scores)),
        "n_folds": len(fold_scores),
        "per_regime": per_regime_mean,
        "router_stats": router_stats,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_comparison(
    global_results: dict[str, Any],
    router_results: dict[str, Any],
    n_active: int = 0,
    n_conditional: int = 0,
    asset_ids: list[int] | None = None,
    tf: str = "",
    start: str = "",
    end: str = "",
    n_total_rows: int = 0,
) -> None:
    """Print side-by-side comparison table with AMA feature summary."""
    print("\n" + "=" * 65)
    print("Regime Routing vs Global Model — Purged CV Comparison")
    print("=" * 65)

    # Feature summary
    if n_active > 0 or n_conditional > 0:
        print(
            f"\nFeatures: {n_active} active"
            + (
                f" + {n_conditional} conditional = {n_active + n_conditional} total"
                if n_conditional > 0
                else ""
            )
        )
    if asset_ids:
        print(f"Asset IDs: {asset_ids}")
    if tf:
        print(f"Timeframe: {tf}  Period: {start} to {end}  (N={n_total_rows} rows)")

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

    # Sub-model operational status
    router_stats = router_results.get("router_stats")
    if router_stats is not None:
        fitted_regimes = router_stats.get("fitted_regimes", [])
        operational = len(fitted_regimes) >= 2
        status = "YES" if operational else "NO (< 2 regimes with sub-models)"
        print(f"\nPer-regime sub-models operational: {status}")
        if fitted_regimes:
            print(f"  Fitted sub-model regimes: {sorted(fitted_regimes)}")
        fallback = router_stats.get("fallback_regimes", [])
        if fallback:
            print(
                f"  Fallback to global (< {router_stats.get('min_samples')} samples): {sorted(fallback)}"
            )
        counts = router_stats.get("sample_counts", {})
        if counts:
            print("  Last-fold regime sample counts:")
            for r, n in sorted(counts.items()):
                print(f"    {r}: {n} samples")

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
        "run_regime_routing: asset_ids=%s tf=%s start=%s end=%s n_splits=%d "
        "min_regime_samples=%d use_ama=%s include_conditional=%s",
        asset_ids,
        args.tf,
        args.start,
        args.end,
        args.n_splits,
        args.min_regime_samples,
        args.use_ama,
        args.include_conditional,
    )

    t0 = time.time()
    engine = _build_engine()

    # --- Load base features from features table ---
    logger.info("Loading base features...")
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
    logger.info(
        "Loaded %d rows x %d columns from features table", len(df), len(df.columns)
    )

    # --- Optionally join AMA features from ama_multi_tf_u ---
    ama_feature_names: list[str] = []

    if args.use_ama:
        logger.info("Loading AMA features via parse_active_features()...")
        from ta_lab2.backtests.bakeoff_orchestrator import parse_active_features

        active_features = parse_active_features()
        ama_only = [f for f in active_features if f["source"] == "ama_multi_tf_u"]
        bar_level = [f for f in active_features if f["source"] == "features"]

        logger.info(
            "Active features: %d AMA + %d bar-level = %d total",
            len(ama_only),
            len(bar_level),
            len(active_features),
        )

        # Join AMA features per-asset, then concatenate
        ama_frames: list[pd.DataFrame] = []
        for asset_id in asset_ids:
            ama_df = _load_ama_features_for_asset(
                engine, asset_id, args.tf, args.start, args.end, ama_only
            )
            if ama_df.empty:
                logger.warning(
                    "No AMA features loaded for asset_id=%d tf=%s", asset_id, args.tf
                )
                continue
            # Add asset_id column for join
            ama_df = ama_df.reset_index()  # ts -> column
            ama_df["id"] = asset_id
            ama_frames.append(ama_df)

        if ama_frames:
            ama_all = pd.concat(ama_frames, ignore_index=True)
            # Merge onto base df by (id, ts)
            ama_all["ts"] = pd.to_datetime(ama_all["ts"], utc=True)
            n_before = len(df)
            df = df.merge(ama_all, on=["id", "ts"], how="left")
            ama_feature_names = [f["name"] for f in ama_only if f["name"] in df.columns]
            logger.info(
                "Merged AMA features: %d -> %d cols, %d rows (left-join preserves all bars)",
                n_before,
                len(df.columns),
                len(df),
            )
        else:
            logger.warning(
                "No AMA data loaded for any asset. Continuing with bar-level features only."
            )

    # --- Optionally load conditional-tier features ---
    conditional_ama_feature_names: list[str] = []
    conditional_bar_names: list[str] = []

    if args.include_conditional:
        logger.info("Loading conditional-tier features...")
        cond_features = _parse_conditional_features()
        cond_ama = [f for f in cond_features if f["source"] == "ama_multi_tf_u"]
        cond_bar = [f for f in cond_features if f["source"] == "features"]

        logger.info(
            "Conditional features: %d AMA-derived + %d bar-level = %d total",
            len(cond_ama),
            len(cond_bar),
            len(cond_features),
        )

        # Load AMA-derived conditional features
        if cond_ama:
            cond_ama_frames: list[pd.DataFrame] = []
            for asset_id in asset_ids:
                c_df = _load_conditional_ama_features_for_asset(
                    engine, asset_id, args.tf, args.start, args.end, cond_ama
                )
                if not c_df.empty:
                    c_df = c_df.reset_index()
                    c_df["id"] = asset_id
                    cond_ama_frames.append(c_df)

            if cond_ama_frames:
                cond_ama_all = pd.concat(cond_ama_frames, ignore_index=True)
                cond_ama_all["ts"] = pd.to_datetime(cond_ama_all["ts"], utc=True)
                df = df.merge(cond_ama_all, on=["id", "ts"], how="left")
                conditional_ama_feature_names = [
                    f["name"] for f in cond_ama if f["name"] in df.columns
                ]
                logger.info(
                    "Merged %d conditional AMA features",
                    len(conditional_ama_feature_names),
                )

        # Bar-level conditional features (may already be in features table)
        for feat in cond_bar:
            if feat["name"] in df.columns:
                conditional_bar_names.append(feat["name"])
            else:
                logger.debug(
                    "Conditional bar-level feature '%s' not found in features table; skipping",
                    feat["name"],
                )

        logger.info(
            "Conditional bar-level features available: %d / %d",
            len(conditional_bar_names),
            len(cond_bar),
        )

    # --- Load regimes ---
    logger.info("Loading regimes...")
    reg_df = _load_regimes_batch(engine, asset_ids, args.tf, args.start, args.end)

    # --- Build feature matrix ---
    # Determine active feature columns (for global model)
    # Exclude non-feature columns; include only numeric, non-excluded columns
    base_feature_cols = [
        c
        for c in df.columns
        if c not in _EXCLUDE_COLS
        and df[c].notna().any()
        and pd.api.types.is_numeric_dtype(df[c])
        # Exclude conditional features from global model feature set
        and c not in conditional_ama_feature_names
        and c not in conditional_bar_names
    ]

    if "ret_arith" not in df.columns:
        logger.error("ret_arith column not found in features. Cannot build labels.")
        sys.exit(1)

    # Build X for active features (global model)
    X = df[base_feature_cols].copy()
    X = X.ffill().dropna(axis=1, how="all")
    base_feature_cols = list(X.columns)

    # Count feature breakdown
    active_bar_cols = [c for c in base_feature_cols if c not in ama_feature_names]
    active_ama_cols = [c for c in base_feature_cols if c in ama_feature_names]

    # Drop rows where active features have NaN (after AMA join, early AMA rows may be NaN)
    valid_mask = X.notna().all(axis=1)
    n_dropped = (~valid_mask).sum()
    if n_dropped > 0:
        logger.info(
            "Dropping %d rows with NaN in active features (AMA warmup period)",
            n_dropped,
        )
    X = X[valid_mask].reset_index(drop=True)
    df_valid = df[valid_mask].reset_index(drop=True)

    # --- Sort by ts for PurgedKFold (multi-asset data must be time-sorted globally) ---
    sort_idx = df_valid["ts"].argsort()
    df_valid = df_valid.iloc[sort_idx].reset_index(drop=True)
    X = X.iloc[sort_idx].reset_index(drop=True)

    # Build conditional feature matrix (for per-regime sub-models)
    all_conditional_cols = conditional_ama_feature_names + conditional_bar_names
    X_with_conditional: pd.DataFrame | None = None
    if all_conditional_cols:
        cond_available = [c for c in all_conditional_cols if c in df_valid.columns]
        if cond_available:
            X_cond = df_valid[cond_available].copy()
            X_cond = X_cond.ffill().fillna(0.0)
            X_with_conditional = pd.concat([X, X_cond], axis=1)
            logger.info(
                "Feature matrix with conditional: %d active + %d conditional = %d total",
                len(base_feature_cols),
                len(cond_available),
                len(X_with_conditional.columns),
            )

    # Feature counts for summary display
    n_active_total = len(base_feature_cols)
    n_conditional_display = (
        len(X_with_conditional.columns) - n_active_total
        if X_with_conditional is not None
        else 0
    )

    logger.info(
        "Active features: %d total (%d AMA + %d bar-level)",
        n_active_total,
        len(active_ama_cols),
        len(active_bar_cols),
    )
    logger.info("Labels: computing from ret_arith > 0...")

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
        reg_lookup = reg_df.set_index(["id", "ts"])["l2_label"]
        pairs = list(zip(df_valid["id"].values, df_valid["ts"].values))
        regimes_list = []
        for asset_id, ts in pairs:
            try:
                label = reg_lookup.loc[(asset_id, ts)]
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

    # --- Run global CV (uses active features only) ---
    logger.info(
        "Running purged CV for global model (n_splits=%d, n_features=%d)...",
        args.n_splits,
        n_active_total,
    )
    global_results = _run_purged_cv_global(base_model, X, y, t1_series, args.n_splits)
    logger.info(
        "Global OOS accuracy: %.4f", global_results.get("oos_accuracy", float("nan"))
    )

    # --- Run regime-routed CV ---
    # Use conditional feature matrix if available, else active-only matrix
    X_for_router = X_with_conditional if X_with_conditional is not None else X
    logger.info(
        "Running purged CV for RegimeRouter (n_splits=%d, n_features=%d)...",
        args.n_splits,
        len(X_for_router.columns),
    )
    router_results = _run_purged_cv_regime_router(
        base_model,
        X_for_router,
        y,
        regimes,
        t1_series,
        args.n_splits,
        args.min_regime_samples,
    )
    logger.info(
        "Regime-routed OOS accuracy: %.4f",
        router_results.get("oos_accuracy", float("nan")),
    )

    duration = time.time() - t0
    logger.info("Regime routing comparison complete in %.1f seconds.", duration)

    # --- Print comparison ---
    _print_comparison(
        global_results,
        router_results,
        n_active=n_active_total,
        n_conditional=n_conditional_display,
        asset_ids=asset_ids,
        tf=args.tf,
        start=args.start,
        end=args.end,
        n_total_rows=len(X),
    )

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
            feature_set=base_feature_cols,
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
            notes=(
                f"global baseline; use_ama={args.use_ama}; "
                f"n_active={n_active_total}; n_conditional={n_conditional_display}"
            ),
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
            feature_set=list(X_for_router.columns),
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
                f"min_regime_samples={args.min_regime_samples}; "
                f"use_ama={args.use_ama}; include_conditional={args.include_conditional}"
            ),
        )
        logger.info("RegimeRouter experiment logged: %s", router_eid)
        print(f"Experiments logged: global={global_eid}  router={router_eid}")


if __name__ == "__main__":
    main()
