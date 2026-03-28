# -*- coding: utf-8 -*-
"""
Feature selection CLI orchestrator for Phase 80.

Runs the full feature selection pipeline:
  1. IC decay sweep across ALL horizons -- identify features with no signal
  2. Load IC ranking for the configured horizon
  3. Run ADF/KPSS stationarity tests on top-N features
  4. Run Ljung-Box on rolling IC series for top-N features
  5. Load regime-conditional IC for top-N features
  6. Compute quintile monotonicity scores for top-N features
  7. Classify all features into tiers (active/conditional/watch/archive)
  8. Write output to YAML + dim_feature_selection table

Usage:
    # Dry run -- print tier assignments without writing
    python -m ta_lab2.scripts.analysis.run_feature_selection --dry-run --top-n 5 --skip-quintile

    # Full run (top-40 features)
    python -m ta_lab2.scripts.analysis.run_feature_selection --top-n 40 --tf 1D

    # Custom cutoff
    python -m ta_lab2.scripts.analysis.run_feature_selection --top-n 40 --ic-ir-cutoff 0.35

    # Skip slow steps
    python -m ta_lab2.scripts.analysis.run_feature_selection --skip-quintile --skip-stationarity
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.feature_selection import (
    build_feature_selection_config,
    compute_monotonicity_score,
    load_ic_ranking,
    load_regime_ic,
    save_to_db,
    save_to_yaml,
    test_ljungbox_on_ic,
    test_stationarity,
)
from ta_lab2.analysis.ic import (
    compute_forward_returns,
    compute_rolling_ic,
    load_feature_series,
)
from ta_lab2.analysis.quintile import compute_quintile_returns
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timestamp utility
# ---------------------------------------------------------------------------


def _to_utc(val) -> pd.Timestamp:
    """Convert a DB-returned timestamp to tz-aware UTC pd.Timestamp."""
    ts = pd.Timestamp(val)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_all_assets_for_quintile(engine, tf: str, feature_col: str) -> pd.DataFrame:
    """
    Load ALL assets for a given TF and feature column for quintile analysis.

    Returns a DataFrame with columns: id, ts, {feature_col}, close.
    """
    sql = text(
        f"SELECT id, ts, {feature_col}, close "
        f"FROM public.features "
        f"WHERE tf = :tf AND {feature_col} IS NOT NULL "
        f"ORDER BY ts, id"
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"tf": tf})

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def _get_date_range(engine, tf: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Query MIN and MAX ts from features for the given TF.

    Returns (train_start, train_end) as tz-aware UTC Timestamps.
    """
    sql = text(
        "SELECT MIN(ts) AS min_ts, MAX(ts) AS max_ts "
        "FROM public.features WHERE tf = :tf"
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"tf": tf}).fetchone()

    if row is None or row[0] is None:
        logger.warning("No data found in features for tf=%s", tf)
        # Return a dummy range
        now = pd.Timestamp.utcnow()
        return now - pd.Timedelta(days=365), now

    return _to_utc(row[0]), _to_utc(row[1])


def _get_representative_asset(engine, tf: str) -> Optional[int]:
    """
    Find the asset with the most rows in features for the given TF.

    Returns asset_id (int) or None if no data.
    """
    sql = text(
        """
        SELECT id, COUNT(*) AS cnt
        FROM public.features
        WHERE tf = :tf
        GROUP BY id
        ORDER BY cnt DESC
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"tf": tf}).fetchone()

    if row is None:
        logger.warning("No assets found in features for tf=%s", tf)
        return None

    asset_id = int(row[0])
    count = int(row[1])
    logger.info("Representative asset for tf=%s: id=%d (%d rows)", tf, asset_id, count)
    return asset_id


# ---------------------------------------------------------------------------
# Step 0: IC decay sweep
# ---------------------------------------------------------------------------


def _run_ic_decay_sweep(engine) -> list[str]:
    """
    Identify features with no significant IC (|IC-IR| < 0.1) at ANY horizon.

    These features are pre-classified as archive regardless of other tests.
    Returns a list of feature names with no signal at any horizon.
    """
    logger.info("Step 0: Running IC decay sweep across all horizons...")
    t0 = time.time()

    sql = text(
        """
        SELECT feature,
               MAX(ABS(ic_ir)) AS best_ic_ir_any_horizon,
               ARRAY_AGG(DISTINCT horizon ORDER BY horizon) AS horizons_tested
        FROM public.ic_results
        WHERE regime_col = 'all' AND regime_label = 'all' AND ic IS NOT NULL
        GROUP BY feature
        HAVING MAX(ABS(ic_ir)) < 0.1 OR MAX(ABS(ic_ir)) IS NULL
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    no_signal_features = df["feature"].tolist() if not df.empty else []

    elapsed = time.time() - t0
    logger.info(
        "Step 0 complete (%.1fs): %d features have no significant IC at any horizon",
        elapsed,
        len(no_signal_features),
    )

    if no_signal_features:
        logger.info("No-signal features (archive): %s", no_signal_features[:20])

    return no_signal_features


# ---------------------------------------------------------------------------
# Step 2: Stationarity tests
# ---------------------------------------------------------------------------


def _run_stationarity_tests(
    engine,
    features_list: list[str],
    tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    representative_asset_id: int,
) -> dict[str, dict]:
    """
    Run ADF/KPSS stationarity tests on a single representative asset per feature.

    Returns a dict keyed by feature name with stationarity result dicts.
    """
    logger.info(
        "Step 2: Running stationarity tests for %d features (asset_id=%d, tf=%s)...",
        len(features_list),
        representative_asset_id,
        tf,
    )
    t0 = time.time()
    results: dict[str, dict] = {}

    with engine.connect() as conn:
        for i, feature in enumerate(features_list):
            try:
                feature_series, _ = load_feature_series(
                    conn,
                    asset_id=representative_asset_id,
                    tf=tf,
                    feature_col=feature,
                    train_start=train_start,
                    train_end=train_end,
                )
                stat_result = test_stationarity(feature_series)
                results[feature] = stat_result
                logger.debug(
                    "  [%d/%d] %s -> %s",
                    i + 1,
                    len(features_list),
                    feature,
                    stat_result["result"],
                )
            except Exception as exc:
                logger.warning(
                    "  Stationarity test failed for feature '%s': %s — marking INSUFFICIENT_DATA",
                    feature,
                    exc,
                )
                results[feature] = {
                    "adf_stat": float("nan"),
                    "adf_pvalue": float("nan"),
                    "kpss_stat": float("nan"),
                    "kpss_pvalue": float("nan"),
                    "result": "INSUFFICIENT_DATA",
                }

    elapsed = time.time() - t0
    result_counts: dict[str, int] = {}
    for r in results.values():
        k = r.get("result", "UNKNOWN")
        result_counts[k] = result_counts.get(k, 0) + 1

    logger.info(
        "Step 2 complete (%.1fs): stationarity results: %s",
        elapsed,
        result_counts,
    )
    return results


# ---------------------------------------------------------------------------
# Step 3: Ljung-Box on rolling IC series
# ---------------------------------------------------------------------------


def _run_ljungbox_tests(
    engine,
    features_list: list[str],
    tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    representative_asset_id: int,
    horizon: int,
    return_type: str,
) -> dict[str, dict]:
    """
    Run Ljung-Box autocorrelation test on rolling IC series for each feature.

    Uses the same representative asset as stationarity tests.
    Returns a dict keyed by feature name with Ljung-Box result dicts.
    """
    logger.info(
        "Step 3: Running Ljung-Box tests for %d features (asset_id=%d, tf=%s)...",
        len(features_list),
        representative_asset_id,
        tf,
    )
    t0 = time.time()
    results: dict[str, dict] = {}
    log_flag = return_type == "log"

    with engine.connect() as conn:
        for i, feature in enumerate(features_list):
            try:
                feature_series, close_series = load_feature_series(
                    conn,
                    asset_id=representative_asset_id,
                    tf=tf,
                    feature_col=feature,
                    train_start=train_start,
                    train_end=train_end,
                )

                # Compute forward returns on the full close series
                fwd_ret = compute_forward_returns(
                    close_series, horizon=horizon, log=log_flag
                )

                # Slice to train window and apply boundary masking
                feat_train = feature_series[
                    (feature_series.index >= train_start)
                    & (feature_series.index <= train_end)
                ]
                fwd_train = fwd_ret.reindex(feat_train.index).copy()
                # Null boundary bars (last 'horizon' bars have look-ahead)
                horizon_delta = pd.Timedelta(days=horizon)
                boundary_mask = (feat_train.index + horizon_delta) > train_end
                fwd_train.iloc[boundary_mask] = float("nan")

                # Compute rolling IC series (window=63 quarters)
                rolling_ic_series, _, _ = compute_rolling_ic(
                    feat_train, fwd_train, window=63
                )

                # Run Ljung-Box on the rolling IC series
                lb_result = test_ljungbox_on_ic(rolling_ic_series)
                results[feature] = lb_result

                logger.debug(
                    "  [%d/%d] %s -> flag=%s, min_pvalue=%s",
                    i + 1,
                    len(features_list),
                    feature,
                    lb_result.get("flag"),
                    lb_result.get("min_pvalue"),
                )
            except Exception as exc:
                logger.warning(
                    "  Ljung-Box test failed for feature '%s': %s — skipping",
                    feature,
                    exc,
                )
                results[feature] = {"flag": False, "min_pvalue": None, "n_obs": 0}

    elapsed = time.time() - t0
    flagged = sum(1 for r in results.values() if r.get("flag", False))
    logger.info(
        "Step 3 complete (%.1fs): %d/%d features flagged for serial correlation",
        elapsed,
        flagged,
        len(results),
    )
    return results


# ---------------------------------------------------------------------------
# Step 4: Regime-conditional IC
# ---------------------------------------------------------------------------


def _load_all_regime_ic(
    engine,
    features_list: list[str],
    horizon: int,
    return_type: str,
) -> dict[str, pd.DataFrame]:
    """
    Load regime-conditional IC for each feature in features_list.

    Returns a dict keyed by feature name with regime IC DataFrames.
    """
    logger.info("Step 4: Loading regime IC for %d features...", len(features_list))
    t0 = time.time()
    regime_ic_map: dict[str, pd.DataFrame] = {}

    for feature in features_list:
        try:
            regime_df = load_regime_ic(
                engine,
                feature=feature,
                horizon=horizon,
                return_type=return_type,
            )
            regime_ic_map[feature] = regime_df
        except Exception as exc:
            logger.warning("  Failed to load regime IC for '%s': %s", feature, exc)
            regime_ic_map[feature] = pd.DataFrame()

    elapsed = time.time() - t0
    with_regime = sum(1 for df in regime_ic_map.values() if len(df) > 0)
    logger.info(
        "Step 4 complete (%.1fs): %d/%d features have regime IC data",
        elapsed,
        with_regime,
        len(features_list),
    )
    return regime_ic_map


# ---------------------------------------------------------------------------
# Step 5: Quintile monotonicity
# ---------------------------------------------------------------------------


def _run_quintile_monotonicity(
    engine,
    features_list: list[str],
    tf: str,
    horizon: int,
) -> dict[str, float]:
    """
    Compute quintile monotonicity scores for each feature.

    Loads ALL assets for cross-sectional quintile analysis.
    Returns a dict keyed by feature name with monotonicity scores.
    """
    logger.info(
        "Step 5: Computing quintile monotonicity for %d features (tf=%s, horizon=%d)...",
        len(features_list),
        tf,
        horizon,
    )
    t0 = time.time()
    scores: dict[str, float] = {}

    for i, feature in enumerate(features_list):
        try:
            feat_start = time.time()
            df = _load_all_assets_for_quintile(engine, tf, feature)

            if df.empty or len(df["id"].unique()) < 5:
                logger.debug(
                    "  [%d/%d] %s: insufficient cross-sectional data — score=0.0",
                    i + 1,
                    len(features_list),
                    feature,
                )
                scores[feature] = 0.0
                continue

            cumulative, _ = compute_quintile_returns(
                df,
                factor_col=feature,
                forward_horizon=horizon,
                min_assets_per_ts=5,
            )

            score = compute_monotonicity_score(cumulative)
            scores[feature] = score

            feat_elapsed = time.time() - feat_start
            logger.info(
                "  [%d/%d] %s: monotonicity=%.4f (%.1fs)",
                i + 1,
                len(features_list),
                feature,
                score,
                feat_elapsed,
            )

        except Exception as exc:
            logger.warning(
                "  Quintile monotonicity failed for '%s': %s — score=0.0",
                feature,
                exc,
            )
            scores[feature] = 0.0

    elapsed = time.time() - t0
    logger.info(
        "Step 5 complete (%.1fs): monotonicity computed for %d features",
        elapsed,
        len(scores),
    )
    return scores


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _print_summary(config: dict, yaml_path: Optional[Path] = None) -> None:
    """Print a human-readable summary table of the feature selection results."""
    print()
    print("=" * 72)
    print("FEATURE SELECTION SUMMARY")
    print("=" * 72)

    tier_order = ["active", "conditional", "watch", "archive"]

    fmt_header = f"{'Tier':<12} {'Count':>6} {'Example features (top 3)'}"
    print(fmt_header)
    print("-" * 72)

    total = 0
    for tier in tier_order:
        entries = config.get(tier, [])
        count = len(entries)
        total += count
        examples = ", ".join(e["name"] for e in entries[:3])
        if len(entries) > 3:
            examples += f", ... (+{count - 3} more)"
        print(f"{tier:<12} {count:>6}  {examples}")

    print("-" * 72)

    meta = config.get("metadata", {})
    print(f"{'TOTAL':<12} {total:>6}")
    print()
    print(f"IC-IR cutoff: {meta.get('ic_ir_cutoff', 'N/A')}")
    print(f"Generated at: {meta.get('generated_at', 'N/A')}")

    no_signal = meta.get("no_signal_features", [])
    if no_signal:
        print(f"No-signal features (archive): {len(no_signal)}")

    if yaml_path:
        print(f"YAML output: {yaml_path}")

    print("=" * 72)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_feature_selection",
        description=(
            "Phase 80 feature selection pipeline.\n\n"
            "Reads IC rankings from ic_results, runs full statistical test battery "
            "(stationarity, Ljung-Box, quintile monotonicity, regime IC), classifies "
            "features into tiers (active/conditional/watch/archive), and writes output "
            "to YAML + dim_feature_selection table."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # IC ranking parameters
    parser.add_argument(
        "--horizon",
        type=int,
        default=1,
        metavar="N",
        help="IC horizon for ranking and stationarity/Ljung-Box tests (default: 1).",
    )
    parser.add_argument(
        "--return-type",
        type=str,
        default="arith",
        dest="return_type",
        choices=["arith", "log"],
        help="Return type for IC ranking (default: arith).",
    )
    parser.add_argument(
        "--ic-ir-cutoff",
        type=float,
        default=0.3,
        dest="ic_ir_cutoff",
        metavar="FLOAT",
        help="IC-IR threshold for active tier classification (default: 0.3).",
    )

    # Data parameters
    parser.add_argument(
        "--tf",
        type=str,
        default="1D",
        metavar="TF",
        help="Timeframe for stationarity tests and quintile analysis (default: 1D).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=50,
        dest="top_n",
        metavar="N",
        help=(
            "Only run stationarity + Ljung-Box + quintile on top-N features by IC-IR "
            "(default: 50). Use to limit slow steps to candidates only."
        ),
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        metavar="DATE",
        help=(
            "Training start date in ISO format (e.g. 2020-01-01). "
            "Defaults to earliest date in features table for representative asset."
        ),
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        metavar="DATE",
        help=(
            "Training end date in ISO format (e.g. 2024-12-31). "
            "Defaults to latest date in features table for representative asset."
        ),
    )

    # Output
    parser.add_argument(
        "--output",
        type=str,
        default="configs/feature_selection.yaml",
        metavar="PATH",
        help="YAML output path (default: configs/feature_selection.yaml).",
    )

    # Skip flags
    parser.add_argument(
        "--skip-stationarity",
        action="store_true",
        default=False,
        dest="skip_stationarity",
        help="Skip ADF/KPSS stationarity tests.",
    )
    parser.add_argument(
        "--skip-ljungbox",
        action="store_true",
        default=False,
        dest="skip_ljungbox",
        help="Skip Ljung-Box autocorrelation test on rolling IC series.",
    )
    parser.add_argument(
        "--skip-quintile",
        action="store_true",
        default=False,
        dest="skip_quintile",
        help="Skip quintile monotonicity computation (slowest step).",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="Print ranking and tier assignments without writing YAML or DB.",
    )

    # YAML version tag
    parser.add_argument(
        "--yaml-version",
        type=str,
        default="80-initial",
        dest="yaml_version",
        metavar="TAG",
        help="Version tag for dim_feature_selection.yaml_version column (default: 80-initial).",
    )

    # Verbosity
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    pipeline_start = time.time()

    # -----------------------------------------------------------------------
    # Connect to DB
    # -----------------------------------------------------------------------
    db_url = resolve_db_url()
    engine = create_engine(db_url, poolclass=NullPool)

    # -----------------------------------------------------------------------
    # Step 0: IC decay sweep -- identify features with no signal at any horizon
    # -----------------------------------------------------------------------
    no_signal_features = _run_ic_decay_sweep(engine)

    # -----------------------------------------------------------------------
    # Step 1: Load IC ranking
    # -----------------------------------------------------------------------
    logger.info(
        "Step 1: Loading IC ranking (horizon=%d, return_type=%s)...",
        args.horizon,
        args.return_type,
    )
    t1 = time.time()
    ranking_df = load_ic_ranking(
        engine, horizon=args.horizon, return_type=args.return_type
    )

    if ranking_df.empty:
        logger.warning(
            "ic_results is empty -- no data found for horizon=%d, return_type=%s. "
            "Run run_ic_sweep first.",
            args.horizon,
            args.return_type,
        )
        # Still produce a valid (empty) config
        config = {
            "metadata": {
                "generated_at": pd.Timestamp.utcnow().isoformat(),
                "ic_ir_cutoff": args.ic_ir_cutoff,
                "n_features_total": 0,
                "n_features_active": 0,
                "n_features_conditional": 0,
                "n_features_watch": 0,
                "n_features_archive": 0,
                "no_signal_features": no_signal_features,
                "warning": "ic_results is empty -- run run_ic_sweep first",
            },
            "active": [],
            "conditional": [],
            "watch": [],
            "archive": [],
        }
        _print_summary(config)
        if not args.dry_run:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            yaml_path = save_to_yaml(config, output_path)
            logger.info("Empty config written to %s", yaml_path)
        return 0

    n_total = len(ranking_df)
    logger.info(
        "Step 1 complete (%.1fs): %d features loaded. Top-10 by IC-IR:",
        time.time() - t1,
        n_total,
    )
    top10 = ranking_df.head(10)
    for _, row in top10.iterrows():
        logger.info(
            "  %-35s IC-IR=%.4f, IC=%.4f, n_pairs=%d",
            row["feature"],
            float(row.get("mean_abs_ic_ir") or 0.0),
            float(row.get("mean_abs_ic") or 0.0),
            int(row.get("n_asset_tf_pairs") or 0),
        )

    # -----------------------------------------------------------------------
    # Determine top-N features for expensive tests
    # -----------------------------------------------------------------------
    # Use top-N by IC-IR for stationarity/Ljung-Box/quintile
    top_n_features = ranking_df.head(args.top_n)["feature"].tolist()
    logger.info(
        "Will run detailed tests on top-%d features (of %d total)",
        len(top_n_features),
        n_total,
    )

    # -----------------------------------------------------------------------
    # Determine train window
    # -----------------------------------------------------------------------
    if args.start and args.end:
        train_start = pd.Timestamp(args.start, tz="UTC")
        train_end = pd.Timestamp(args.end, tz="UTC")
        logger.info(
            "Using provided date range: %s to %s", train_start.date(), train_end.date()
        )
    else:
        train_start, train_end = _get_date_range(engine, args.tf)
        if args.start:
            train_start = pd.Timestamp(args.start, tz="UTC")
        if args.end:
            train_end = pd.Timestamp(args.end, tz="UTC")
        logger.info(
            "Using date range from features table: %s to %s",
            train_start.date(),
            train_end.date(),
        )

    # -----------------------------------------------------------------------
    # Step 2 + 3: Determine representative asset ONCE
    # -----------------------------------------------------------------------
    representative_asset_id = _get_representative_asset(engine, args.tf)

    # -----------------------------------------------------------------------
    # Step 2: Stationarity tests
    # -----------------------------------------------------------------------
    if args.skip_stationarity or representative_asset_id is None:
        if args.skip_stationarity:
            logger.info("Step 2: Skipping stationarity tests (--skip-stationarity)")
        else:
            logger.warning(
                "Step 2: Skipping stationarity tests (no representative asset)"
            )
        stationarity_results: dict[str, dict] = {}
    else:
        stationarity_results = _run_stationarity_tests(
            engine=engine,
            features_list=top_n_features,
            tf=args.tf,
            train_start=train_start,
            train_end=train_end,
            representative_asset_id=representative_asset_id,
        )

    # -----------------------------------------------------------------------
    # Step 3: Ljung-Box on rolling IC series
    # -----------------------------------------------------------------------
    if args.skip_ljungbox or representative_asset_id is None:
        if args.skip_ljungbox:
            logger.info("Step 3: Skipping Ljung-Box tests (--skip-ljungbox)")
        else:
            logger.warning("Step 3: Skipping Ljung-Box tests (no representative asset)")
        ljungbox_results: dict[str, dict] = {}
    else:
        ljungbox_results = _run_ljungbox_tests(
            engine=engine,
            features_list=top_n_features,
            tf=args.tf,
            train_start=train_start,
            train_end=train_end,
            representative_asset_id=representative_asset_id,
            horizon=args.horizon,
            return_type=args.return_type,
        )

    # -----------------------------------------------------------------------
    # Step 4: Regime-conditional IC
    # -----------------------------------------------------------------------
    regime_ic_map = _load_all_regime_ic(
        engine=engine,
        features_list=top_n_features,
        horizon=args.horizon,
        return_type=args.return_type,
    )

    # -----------------------------------------------------------------------
    # Step 5: Quintile monotonicity
    # -----------------------------------------------------------------------
    if args.skip_quintile:
        logger.info("Step 5: Skipping quintile monotonicity (--skip-quintile)")
        monotonicity_scores: dict[str, float] = {}
    else:
        monotonicity_scores = _run_quintile_monotonicity(
            engine=engine,
            features_list=top_n_features,
            tf=args.tf,
            horizon=args.horizon,
        )

    # -----------------------------------------------------------------------
    # Step 6: Build config
    # -----------------------------------------------------------------------
    logger.info("Step 6: Building feature selection config...")
    t6 = time.time()

    config = build_feature_selection_config(
        ranking_df=ranking_df,
        stationarity_results=stationarity_results,
        ljungbox_results=ljungbox_results,
        monotonicity_scores=monotonicity_scores,
        regime_ic_map=regime_ic_map,
        ic_ir_cutoff=args.ic_ir_cutoff,
    )

    # Add no-signal features to metadata (SC-1 coverage)
    config["metadata"]["no_signal_features"] = no_signal_features

    logger.info(
        "Step 6 complete (%.1fs): %d active, %d conditional, %d watch, %d archive",
        time.time() - t6,
        config["metadata"]["n_features_active"],
        config["metadata"]["n_features_conditional"],
        config["metadata"]["n_features_watch"],
        config["metadata"]["n_features_archive"],
    )

    # -----------------------------------------------------------------------
    # Step 7: Write outputs
    # -----------------------------------------------------------------------
    yaml_path: Optional[Path] = None

    if args.dry_run:
        logger.info("Step 7: --dry-run mode -- skipping YAML + DB writes")
    else:
        logger.info("Step 7: Writing YAML to %s...", args.output)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path = save_to_yaml(config, output_path)
        logger.info("YAML written to %s", yaml_path)

        logger.info("Step 7: Mirroring to dim_feature_selection table...")
        n_rows = save_to_db(engine, config, yaml_version=args.yaml_version)
        logger.info("DB: %d rows inserted into dim_feature_selection", n_rows)

    # -----------------------------------------------------------------------
    # Step 8: Print summary
    # -----------------------------------------------------------------------
    _print_summary(config, yaml_path=yaml_path)

    pipeline_elapsed = time.time() - pipeline_start
    minutes = int(pipeline_elapsed // 60)
    seconds = int(pipeline_elapsed % 60)
    logger.info("Feature selection pipeline complete in %dm%ds", minutes, seconds)

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
