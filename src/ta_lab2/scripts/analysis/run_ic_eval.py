"""
Standalone CLI for computing and persisting IC (Information Coefficient) results.

Computes Spearman IC of feature columns against forward returns across horizons,
optionally broken down by regime label (trend_state / vol_state from cmc_regimes).
Results are persisted to cmc_ic_results with append-only (default) or upsert semantics.

Usage:
    # Single asset + single feature
    python -m ta_lab2.scripts.analysis.run_ic_eval \\
        --asset-id 1 --tf 1D --feature ret_arith \\
        --train-start 2020-01-01 --train-end 2024-01-01

    # Multiple features for one asset
    python -m ta_lab2.scripts.analysis.run_ic_eval \\
        --asset-id 1 --tf 1D --feature ret_arith ret_log rsi_14 \\
        --train-start 2020-01-01 --train-end 2024-01-01

    # All numeric features in cmc_features for one asset
    python -m ta_lab2.scripts.analysis.run_ic_eval \\
        --asset-id 1 --tf 1D --all-features \\
        --train-start 2020-01-01 --train-end 2024-01-01

    # With regime breakdown (trend_state + vol_state from cmc_regimes)
    python -m ta_lab2.scripts.analysis.run_ic_eval \\
        --asset-id 1 --tf 1D --feature ret_arith \\
        --train-start 2020-01-01 --train-end 2024-01-01 \\
        --regime

    # Custom horizons
    python -m ta_lab2.scripts.analysis.run_ic_eval \\
        --asset-id 1 --tf 1D --feature ret_arith \\
        --train-start 2020-01-01 --train-end 2024-01-01 \\
        --horizons 1 5 20

    # Overwrite existing results (upsert)
    python -m ta_lab2.scripts.analysis.run_ic_eval \\
        --asset-id 1 --tf 1D --feature ret_arith \\
        --train-start 2020-01-01 --train-end 2024-01-01 \\
        --overwrite

    # Dry-run (compute but do not write to DB)
    python -m ta_lab2.scripts.analysis.run_ic_eval \\
        --asset-id 1 --tf 1D --feature ret_arith \\
        --train-start 2020-01-01 --train-end 2024-01-01 \\
        --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd
from sqlalchemy import create_engine, pool

from ta_lab2.analysis.ic import (
    compute_ic,
    compute_ic_by_regime,
    load_feature_series,
    load_regimes_for_asset,
    save_ic_results,
)
from ta_lab2.scripts.refresh_utils import resolve_db_url
from ta_lab2.scripts.sync_utils import get_columns
from ta_lab2.time.dim_timeframe import DimTimeframe

logger = logging.getLogger(__name__)

# Columns that are identifiers/metadata — excluded from --all-features discovery
_NON_FEATURE_COLS = frozenset(
    ["id", "ts", "tf", "close", "open", "high", "low", "volume", "ingested_at"]
)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_ic_eval",
        description=(
            "Compute Spearman IC for feature columns against forward returns.\n\n"
            "For each (feature, horizon, return_type) combination, computes IC + t-stat + "
            "p-value + IC-IR + turnover and persists results to cmc_ic_results.\n\n"
            "Supports optional regime breakdown: IC is computed separately for each "
            "regime label (trend_state, vol_state) parsed from cmc_regimes.l2_label.\n\n"
            "Default mode is append-only (ON CONFLICT DO NOTHING). Use --overwrite to "
            "update existing rows (ON CONFLICT DO UPDATE)."
        ),
    )

    # Required args
    parser.add_argument(
        "--asset-id",
        required=True,
        type=int,
        metavar="INT",
        dest="asset_id",
        help="Asset ID to evaluate (matches cmc_features.id).",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        type=str,
        metavar="TF",
        help="Timeframe to evaluate (default: 1D).",
    )
    parser.add_argument(
        "--train-start",
        required=True,
        type=str,
        metavar="DATE",
        dest="train_start",
        help="Training window start date (ISO format, e.g. 2020-01-01).",
    )
    parser.add_argument(
        "--train-end",
        required=True,
        type=str,
        metavar="DATE",
        dest="train_end",
        help="Training window end date (ISO format, e.g. 2024-01-01).",
    )

    # Feature selection: --feature and --all-features are mutually exclusive
    feature_group = parser.add_mutually_exclusive_group(required=True)
    feature_group.add_argument(
        "--feature",
        nargs="+",
        type=str,
        metavar="COL",
        help="One or more feature column names from cmc_features.",
    )
    feature_group.add_argument(
        "--all-features",
        action="store_true",
        dest="all_features",
        help=(
            "Score all numeric feature columns in cmc_features "
            "(excludes id/ts/tf/close/open/high/low/volume/ingested_at)."
        ),
    )

    # Optional tuning args
    parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=None,
        metavar="N",
        help="Forward return horizons in bars (default: 1 2 3 5 10 20 60).",
    )
    parser.add_argument(
        "--return-types",
        nargs="+",
        default=None,
        metavar="TYPE",
        dest="return_types",
        help="Return types to compute: arith and/or log (default: arith log).",
    )
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=63,
        metavar="N",
        dest="rolling_window",
        help="Rolling IC window size in bars (default: 63).",
    )

    # Regime breakdown
    parser.add_argument(
        "--regime",
        action="store_true",
        default=False,
        help=(
            "Enable regime breakdown: compute IC separately per trend_state and vol_state "
            "label, loaded from cmc_regimes (l2_label parsed via split_part SQL)."
        ),
    )

    # Persistence flags
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Upsert existing rows (ON CONFLICT DO UPDATE). Default is append-only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="Compute IC but do not write to cmc_ic_results.",
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

    # Parse train window to tz-aware UTC timestamps
    train_start = pd.Timestamp(args.train_start, tz="UTC")
    train_end = pd.Timestamp(args.train_end, tz="UTC")

    logger.info(
        "IC evaluation: asset_id=%d tf=%s train=%s..%s",
        args.asset_id,
        args.tf,
        train_start.date(),
        train_end.date(),
    )

    # Look up tf_days_nominal from dim_timeframe
    db_url = resolve_db_url()
    try:
        dim = DimTimeframe.from_db(db_url)
        tf_days_nominal = dim.tf_days(args.tf)
        logger.debug("tf_days_nominal for %s: %d", args.tf, tf_days_nominal)
    except Exception as exc:
        logger.warning(
            "Could not look up tf_days_nominal for tf=%s (%s) — defaulting to 1",
            args.tf,
            exc,
        )
        tf_days_nominal = 1

    # Create engine with NullPool (no connection pooling — safe for one-shot scripts)
    engine = create_engine(db_url, poolclass=pool.NullPool)

    n_failed = 0
    all_rows: list[dict] = []
    feature_list: list[str] = []

    with engine.begin() as conn:
        # Determine feature list
        if args.all_features:
            all_cols = get_columns(engine, "public.cmc_features")
            feature_list = [c for c in all_cols if c not in _NON_FEATURE_COLS]
            logger.info(
                "--all-features: discovered %d feature columns", len(feature_list)
            )
        else:
            feature_list = list(args.feature)

        logger.info(
            "Features to evaluate: %s",
            feature_list
            if len(feature_list) <= 10
            else f"{len(feature_list)} features",
        )

        # Load regimes once (shared across all features) if --regime requested
        regimes_df: pd.DataFrame | None = None
        if args.regime:
            logger.info("Loading regimes for asset_id=%d tf=%s", args.asset_id, args.tf)
            try:
                regimes_df = load_regimes_for_asset(
                    conn, args.asset_id, args.tf, train_start, train_end
                )
                if not regimes_df.empty:
                    logger.info(
                        "Loaded %d regime rows; trend_state labels=%s; vol_state labels=%s",
                        len(regimes_df),
                        sorted(regimes_df["trend_state"].dropna().unique().tolist()),
                        sorted(regimes_df["vol_state"].dropna().unique().tolist()),
                    )
                else:
                    logger.warning(
                        "No regime data found for asset_id=%d tf=%s — will use full-sample IC",
                        args.asset_id,
                        args.tf,
                    )
            except Exception as exc:
                logger.error("Failed to load regimes: %s", exc, exc_info=True)
                regimes_df = None

        # Evaluate each feature
        for feature_col in feature_list:
            logger.debug("Evaluating feature: %s", feature_col)
            try:
                # Load feature + close from cmc_features
                feature_series, close_series = load_feature_series(
                    conn,
                    args.asset_id,
                    args.tf,
                    feature_col,
                    train_start,
                    train_end,
                )

                if feature_series.empty or feature_series.dropna().empty:
                    logger.warning(
                        "Feature '%s': no data in range %s..%s — skipping",
                        feature_col,
                        train_start.date(),
                        train_end.date(),
                    )
                    continue

                logger.debug(
                    "Feature '%s': %d rows, %d non-null",
                    feature_col,
                    len(feature_series),
                    int(feature_series.notna().sum()),
                )

                if args.regime and regimes_df is not None:
                    # Regime breakdown: compute IC for trend_state + vol_state separately
                    regime_dfs: list[pd.DataFrame] = []

                    for regime_col_name in ["trend_state", "vol_state"]:
                        regime_ic_df = compute_ic_by_regime(
                            feature_series,
                            close_series,
                            regimes_df,
                            train_start,
                            train_end,
                            horizons=args.horizons,
                            return_types=args.return_types,
                            rolling_window=args.rolling_window,
                            tf_days_nominal=tf_days_nominal,
                            regime_col=regime_col_name,
                        )
                        regime_dfs.append(regime_ic_df)

                    result_df = (
                        pd.concat(regime_dfs, ignore_index=True)
                        if regime_dfs
                        else pd.DataFrame()
                    )
                else:
                    # Full-sample IC (no regime breakdown)
                    result_df = compute_ic(
                        feature_series,
                        close_series,
                        train_start,
                        train_end,
                        horizons=args.horizons,
                        return_types=args.return_types,
                        rolling_window=args.rolling_window,
                        tf_days_nominal=tf_days_nominal,
                    )
                    # Add regime sentinel columns for full-sample path
                    result_df["regime_col"] = "all"
                    result_df["regime_label"] = "all"

                if result_df.empty:
                    logger.warning(
                        "Feature '%s': empty IC result — skipping", feature_col
                    )
                    continue

                # Annotate with feature + asset/tf/train window
                result_df["feature"] = feature_col
                result_df["asset_id"] = args.asset_id
                result_df["tf"] = args.tf
                result_df["train_start"] = train_start
                result_df["train_end"] = train_end
                result_df["horizon_days"] = result_df["horizon"] * tf_days_nominal

                all_rows.extend(result_df.to_dict(orient="records"))

            except Exception as exc:
                logger.error(
                    "Feature '%s': failed — %s", feature_col, exc, exc_info=True
                )
                n_failed += 1

        # Log summary of results
        logger.info(
            "IC computation complete: %d result rows for %d features",
            len(all_rows),
            len(feature_list),
        )

        if all_rows:
            # Top-5 features by |IC| at horizon=1 arith for quick inspection
            summary_df = pd.DataFrame(all_rows)
            h1_mask = (summary_df["horizon"] == 1) & (
                summary_df["return_type"] == "arith"
            )
            # For regime runs, also filter to full-sample rows for the summary
            if "regime_col" in summary_df.columns:
                h1_mask = h1_mask & (summary_df["regime_col"] == "all")
            h1_arith = summary_df[h1_mask].copy()
            if not h1_arith.empty and "ic" in h1_arith.columns:
                h1_arith = h1_arith.copy()
                h1_arith["abs_ic"] = h1_arith["ic"].abs()
                top5 = h1_arith.nlargest(5, "abs_ic")[
                    ["feature", "ic", "ic_p_value", "n_obs"]
                ]
                logger.info(
                    "Top-5 features by |IC| at horizon=1 (arith):\n%s",
                    top5.to_string(index=False),
                )

        # Write to DB (unless dry-run)
        if args.dry_run:
            logger.info(
                "[dry-run] Computed %d IC rows — NOT writing to cmc_ic_results",
                len(all_rows),
            )
        elif all_rows:
            n_written = save_ic_results(conn, all_rows, overwrite=args.overwrite)
            logger.info(
                "Wrote %d rows to cmc_ic_results (overwrite=%s)",
                n_written,
                args.overwrite,
            )
        else:
            logger.warning("No IC rows to write")

    logger.info(
        "IC eval complete: features=%d, rows=%d, failed=%d",
        len(feature_list),
        len(all_rows),
        n_failed,
    )

    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
