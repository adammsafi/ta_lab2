"""
CLI for running feature experiments and persisting results to cmc_feature_experiments.

Computes an experimental feature from the YAML registry, scores it with Spearman IC
against forward returns, applies BH correction across all hypotheses, and optionally
writes results to cmc_feature_experiments.

Usage
-----
# Run a single feature (dry-run, no DB write)
python -m ta_lab2.scripts.experiments.run_experiment \\
    --feature vol_ratio_30_7 \\
    --train-start 2024-01-01 \\
    --train-end 2025-12-31 \\
    --tf 1D \\
    --dry-run

# Run a single feature on specific assets and write without prompt
python -m ta_lab2.scripts.experiments.run_experiment \\
    --feature vol_ratio_30_7 \\
    --ids 1,2,3 \\
    --train-start 2024-01-01 \\
    --train-end 2025-12-31 \\
    --tf 1D \\
    --yes

# Run all experimental features
python -m ta_lab2.scripts.experiments.run_experiment \\
    --all-experimental \\
    --train-start 2024-01-01 \\
    --train-end 2025-12-31 \\
    --yes

# Compare against prior runs
python -m ta_lab2.scripts.experiments.run_experiment \\
    --feature vol_ratio_30_7 \\
    --train-start 2024-01-01 \\
    --train-end 2025-12-31 \\
    --compare
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, pool, text

from ta_lab2.experiments.registry import FeatureRegistry
from ta_lab2.experiments.runner import ExperimentRunner
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

_DEFAULT_HORIZONS: list[int] = [1, 2, 3, 5, 10, 20, 60]
_DEFAULT_REGISTRY_PATH = "configs/experiments/features.yaml"

# Columns to display in the summary table
_DISPLAY_COLS = [
    "feature_name",
    "asset_id",
    "tf",
    "horizon",
    "return_type",
    "ic",
    "ic_p_value",
    "ic_p_value_bh",
    "n_obs",
]


def _to_python(v: Any) -> Any:
    """
    Normalize a value for SQL binding.

    - numpy scalars -> Python float/int via .item()
    - pd.Timestamp -> Python datetime
    - NaN float -> None (SQL NULL)
    - Everything else: unchanged
    """
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def save_experiment_results(conn: Any, result_df: pd.DataFrame) -> int:
    """
    Persist IC experiment results to cmc_feature_experiments.

    Uses ON CONFLICT (uq_feature_experiments_key) DO UPDATE for overwrite semantics.
    experiment_id is generated server-side via gen_random_uuid().

    Parameters
    ----------
    conn : SQLAlchemy connection (within a transaction)
    result_df : pd.DataFrame
        Output of ExperimentRunner.run(). Must include all required columns.

    Returns
    -------
    int
        Number of rows written.
    """
    if result_df.empty:
        return 0

    sql = text(
        """
        INSERT INTO public.cmc_feature_experiments
            (feature_name, asset_id, tf, train_start, train_end,
             horizon, horizon_days, return_type,
             regime_col, regime_label,
             ic, ic_t_stat, ic_p_value, ic_p_value_bh,
             ic_ir, ic_ir_t_stat, n_obs,
             wall_clock_seconds, peak_memory_mb, n_rows_computed,
             yaml_digest)
        VALUES
            (:feature_name, :asset_id, :tf, :train_start, :train_end,
             :horizon, :horizon_days, :return_type,
             :regime_col, :regime_label,
             :ic, :ic_t_stat, :ic_p_value, :ic_p_value_bh,
             :ic_ir, :ic_ir_t_stat, :n_obs,
             :wall_clock_seconds, :peak_memory_mb, :n_rows_computed,
             :yaml_digest)
        ON CONFLICT (feature_name, asset_id, tf, horizon, return_type,
                     regime_col, regime_label, train_start, train_end)
        DO UPDATE SET
            ic                = EXCLUDED.ic,
            ic_t_stat         = EXCLUDED.ic_t_stat,
            ic_p_value        = EXCLUDED.ic_p_value,
            ic_p_value_bh     = EXCLUDED.ic_p_value_bh,
            ic_ir             = EXCLUDED.ic_ir,
            ic_ir_t_stat      = EXCLUDED.ic_ir_t_stat,
            n_obs             = EXCLUDED.n_obs,
            horizon_days      = EXCLUDED.horizon_days,
            wall_clock_seconds = EXCLUDED.wall_clock_seconds,
            peak_memory_mb    = EXCLUDED.peak_memory_mb,
            n_rows_computed   = EXCLUDED.n_rows_computed,
            yaml_digest       = EXCLUDED.yaml_digest,
            run_at            = now()
        """
    )

    n_written = 0
    for _, row in result_df.iterrows():
        # Compute horizon_days if we have tf_days_nominal context
        # Use horizon as-is for horizon_days (caller can pass tf_days_nominal)
        params = {
            "feature_name": _to_python(row.get("feature_name")),
            "asset_id": _to_python(row.get("asset_id")),
            "tf": _to_python(row.get("tf")),
            "train_start": _to_python(row.get("train_start")),
            "train_end": _to_python(row.get("train_end")),
            "horizon": _to_python(row.get("horizon")),
            "horizon_days": _to_python(row.get("horizon_days", None)),
            "return_type": _to_python(row.get("return_type")),
            "regime_col": _to_python(row.get("regime_col", "all")),
            "regime_label": _to_python(row.get("regime_label", "all")),
            "ic": _to_python(row.get("ic")),
            "ic_t_stat": _to_python(row.get("ic_t_stat")),
            "ic_p_value": _to_python(row.get("ic_p_value")),
            "ic_p_value_bh": _to_python(row.get("ic_p_value_bh")),
            "ic_ir": _to_python(row.get("ic_ir")),
            "ic_ir_t_stat": _to_python(row.get("ic_ir_t_stat")),
            "n_obs": _to_python(row.get("n_obs")),
            "wall_clock_seconds": _to_python(row.get("wall_clock_seconds")),
            "peak_memory_mb": _to_python(row.get("peak_memory_mb")),
            "n_rows_computed": _to_python(row.get("n_rows_computed")),
            "yaml_digest": _to_python(row.get("yaml_digest")),
        }
        result = conn.execute(sql, params)
        n_written += result.rowcount

    return n_written


def _load_prior_results(
    conn: Any,
    feature_name: str,
    tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
) -> pd.DataFrame:
    """Load prior experiment results for the same feature/tf/window."""
    sql = text(
        """
        SELECT feature_name, asset_id, tf, horizon, return_type,
               ic, ic_p_value, ic_p_value_bh, n_obs, run_at
        FROM public.cmc_feature_experiments
        WHERE feature_name = :feature_name
          AND tf = :tf
          AND train_start = :train_start
          AND train_end = :train_end
        ORDER BY asset_id, horizon, return_type
        """
    )
    df = pd.read_sql(
        sql,
        conn,
        params={
            "feature_name": feature_name,
            "tf": tf,
            "train_start": train_start,
            "train_end": train_end,
        },
    )
    return df


def _print_comparison(result_df: pd.DataFrame, prior_df: pd.DataFrame) -> None:
    """Print IC delta between new results and prior results."""
    if prior_df.empty:
        print("  [compare] No prior results found for this feature/tf/window.")
        return

    key_cols = ["asset_id", "horizon", "return_type"]
    merged = result_df[key_cols + ["ic"]].merge(
        prior_df[key_cols + ["ic"]].rename(columns={"ic": "ic_prior"}),
        on=key_cols,
        how="left",
    )
    merged["delta_ic"] = merged["ic"] - merged["ic_prior"]

    print("\n  IC comparison vs prior run:")
    print(
        merged[key_cols + ["ic", "ic_prior", "delta_ic"]]
        .round(4)
        .to_string(index=False)
    )


def main() -> int:
    """Entry point for run_experiment CLI."""
    parser = argparse.ArgumentParser(
        prog="run_experiment",
        description=(
            "Run feature experiments from the YAML registry.\n\n"
            "Computes experimental feature values, scores with Spearman IC against "
            "forward returns, applies BH correction across all hypotheses, and "
            "optionally writes results to cmc_feature_experiments.\n\n"
            "Use --dry-run to compute without writing. Use --yes to skip prompt."
        ),
    )

    # Feature selection: mutually exclusive
    feature_group = parser.add_mutually_exclusive_group(required=True)
    feature_group.add_argument(
        "--feature",
        type=str,
        metavar="NAME",
        help="Feature name from the YAML registry (exact expanded name).",
    )
    feature_group.add_argument(
        "--all-experimental",
        action="store_true",
        dest="all_experimental",
        help="Run all features with lifecycle=experimental from the registry.",
    )

    # Asset selection
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        metavar="ID1,ID2,...",
        help="Comma-separated asset IDs. Default: all assets from dim_assets.",
    )

    # Training window (required)
    parser.add_argument(
        "--train-start",
        required=True,
        type=str,
        metavar="DATE",
        dest="train_start",
        help="Train window start date (YYYY-MM-DD). Required.",
    )
    parser.add_argument(
        "--train-end",
        required=True,
        type=str,
        metavar="DATE",
        dest="train_end",
        help="Train window end date (YYYY-MM-DD). Required.",
    )

    # Timeframe
    parser.add_argument(
        "--tf",
        default="1D",
        type=str,
        metavar="TF",
        help="Timeframe string (default: 1D).",
    )

    # IC parameters
    parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=None,
        metavar="N",
        help="Space-separated forward horizon ints (default: 1 2 3 5 10 20 60).",
    )

    # Persistence flags
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        default=False,
        help="Skip confirmation prompt and write results immediately.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="Print results but do not write to cmc_feature_experiments or scratch table.",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        default=False,
        help="Compare results against prior runs in cmc_feature_experiments (show delta IC).",
    )

    # Registry path
    parser.add_argument(
        "--registry",
        type=str,
        default=_DEFAULT_REGISTRY_PATH,
        metavar="PATH",
        help=f"Path to features.yaml (default: {_DEFAULT_REGISTRY_PATH}).",
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

    # Parse train window
    train_start = pd.Timestamp(args.train_start, tz="UTC")
    train_end = pd.Timestamp(args.train_end, tz="UTC")

    # Create engine and load registry
    db_url = resolve_db_url()
    engine = create_engine(db_url, poolclass=pool.NullPool)

    logger.info("Loading feature registry from: %s", args.registry)
    try:
        registry = FeatureRegistry(args.registry)
        registry.load()
    except FileNotFoundError:
        logger.error("Registry file not found: %s", args.registry)
        return 1
    except Exception as exc:
        logger.error("Failed to load registry: %s", exc, exc_info=True)
        return 1

    # Resolve feature names to run
    if args.all_experimental:
        feature_names = registry.list_experimental()
        if not feature_names:
            logger.warning(
                "No experimental features found in registry: %s", args.registry
            )
            return 0
        logger.info(
            "--all-experimental: found %d experimental features: %s",
            len(feature_names),
            feature_names,
        )
    else:
        feature_names = [args.feature]

    # Resolve asset IDs
    if args.ids:
        try:
            asset_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        except ValueError as exc:
            logger.error("Invalid --ids value: %s", exc)
            return 1
    else:
        logger.info("--ids not provided, loading all assets from dim_assets...")
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT id FROM dim_assets ORDER BY id"))
                asset_ids = [row[0] for row in result]
        except Exception as exc:
            logger.error(
                "Failed to load asset IDs from dim_assets: %s", exc, exc_info=True
            )
            return 1

    logger.info(
        "Running experiment: features=%s assets=%d tf=%s window=%s..%s",
        feature_names,
        len(asset_ids),
        args.tf,
        train_start.date(),
        train_end.date(),
    )

    n_failed = 0
    total_rows_written = 0

    for feature_name in feature_names:
        print(f"\n{'=' * 60}")
        print(f"Feature: {feature_name}")
        print(f"{'=' * 60}")

        try:
            runner = ExperimentRunner(registry, engine)
            result_df = runner.run(
                feature_name,
                asset_ids,
                args.tf,
                train_start,
                train_end,
                horizons=args.horizons or _DEFAULT_HORIZONS,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            logger.error(
                "ExperimentRunner failed for feature=%s: %s",
                feature_name,
                exc,
                exc_info=True,
            )
            n_failed += 1
            continue

        if result_df.empty:
            print(f"  No results produced for feature={feature_name}.")
            continue

        # Print summary table
        display_cols = [c for c in _DISPLAY_COLS if c in result_df.columns]
        print("\nIC Results:")
        print(
            result_df[display_cols]
            .round({"ic": 4, "ic_p_value": 4, "ic_p_value_bh": 4})
            .to_string(index=False)
        )

        # Print cost summary
        if "wall_clock_seconds" in result_df.columns:
            wall = result_df["wall_clock_seconds"].iloc[0]
            mem = result_df.get("peak_memory_mb", pd.Series([None])).iloc[0]
            n_rows = result_df.get("n_rows_computed", pd.Series([None])).iloc[0]
            print(
                f"\nCost: {wall:.1f}s wall-clock | {mem:.1f} MB peak | {n_rows} rows computed"
            )

        # Compare against prior results if requested
        if args.compare and not args.dry_run:
            try:
                with engine.connect() as conn:
                    prior_df = _load_prior_results(
                        conn, feature_name, args.tf, train_start, train_end
                    )
                _print_comparison(result_df, prior_df)
            except Exception as exc:
                logger.warning("--compare failed: %s", exc)

        # Decide whether to write to DB
        if args.dry_run:
            print("\n  [dry-run] Skipping DB write.")
            continue

        should_write = args.yes
        if not should_write:
            try:
                answer = (
                    input("\nWrite to cmc_feature_experiments? [y/N]: ").strip().lower()
                )
                should_write = answer in ("y", "yes")
            except EOFError:
                # Non-interactive environment — default to No
                should_write = False
                print("  Non-interactive mode, skipping write (use --yes to override).")

        if should_write:
            try:
                with engine.begin() as conn:
                    n_written = save_experiment_results(conn, result_df)
                total_rows_written += n_written
                print(f"  Wrote {n_written} rows to cmc_feature_experiments.")
                logger.info(
                    "Wrote %d rows to cmc_feature_experiments for feature=%s",
                    n_written,
                    feature_name,
                )
            except Exception as exc:
                logger.error(
                    "Failed to write results for feature=%s: %s",
                    feature_name,
                    exc,
                    exc_info=True,
                )
                n_failed += 1
        else:
            print("  Skipped DB write.")

    # Final summary
    print(f"\n{'=' * 60}")
    print(f"Done. Features run: {len(feature_names)}")
    if total_rows_written > 0:
        print(f"Total rows written: {total_rows_written}")
    if n_failed > 0:
        print(f"Failures: {n_failed}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
