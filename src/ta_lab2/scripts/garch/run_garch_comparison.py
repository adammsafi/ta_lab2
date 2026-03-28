"""
run_garch_comparison.py -- GARCH vs range-based estimator comparison report.

Generates a comprehensive comparison evaluating all four GARCH conditional volatility
model variants (GARCH(1,1), GJR-GARCH(1,1), EGARCH(1,1), FIGARCH(1,d,1)) against
three range-based volatility estimators (Parkinson 20-day, Garman-Klass 20-day,
ATR-14 normalised) using rolling out-of-sample evaluation.

Outputs:
- Markdown report  (garch_comparison_report.md)
- Aggregate CSV    (garch_comparison_aggregate.csv)
- Per-asset CSV    (garch_comparison_per_asset.csv)

All metrics evaluated against a 5-day rolling std realised volatility proxy:
- RMSE   (root mean squared error)
- QLIKE  (quasi-likelihood loss; Patton 2011)
- MZ R2  (Mincer-Zarnowitz calibration R-squared)
- Combined score (0.5 * RMSE + 0.5 * QLIKE)

Usage::

    python -m ta_lab2.scripts.garch.run_garch_comparison --ids all --verbose
    python -m ta_lab2.scripts.garch.run_garch_comparison --ids 1,52 --eval-window 63 --train-window 252
    python -m ta_lab2.scripts.garch.run_garch_comparison --ids 1 --output-dir /tmp/report --verbose
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.garch_evaluator import (
    combined_score,
    compute_realized_vol_proxy,
    evaluate_all_models,
    mincer_zarnowitz_r2,
    qlike_loss,
    rmse_loss,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Range-based estimator names used throughout the report
RANGE_ESTIMATORS = ["vol_parkinson_20", "vol_gk_20", "atr_14"]

#: Friendly display names for the report
DISPLAY_NAMES: dict[str, str] = {
    "garch_1_1": "GARCH(1,1)",
    "gjr_garch_1_1": "GJR-GARCH(1,1)",
    "egarch_1_1": "EGARCH(1,1)",
    "figarch_1_d_1": "FIGARCH(1,d,1)",
    "vol_parkinson_20": "Parkinson-20",
    "vol_gk_20": "Garman-Klass-20",
    "atr_14": "ATR-14 (norm)",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_returns(
    engine: Any,
    asset_id: int,
    venue_id: int,
    tf: str,
) -> pd.Series:
    """Load log returns for one asset from returns_bars_multi_tf."""
    query = text(
        """
        SELECT ts, ret_log
        FROM returns_bars_multi_tf
        WHERE id = :id AND venue_id = :venue_id AND tf = :tf
          AND roll = FALSE
        ORDER BY ts
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(
            query, {"id": asset_id, "venue_id": venue_id, "tf": tf}
        ).fetchall()

    if not rows:
        return pd.Series(dtype=float)

    ts_list = [r[0] for r in rows]
    val_list = [float(r[1]) if r[1] is not None else np.nan for r in rows]
    return pd.Series(
        val_list, index=pd.DatetimeIndex(ts_list, name="ts"), name="ret_log"
    )


def _load_range_estimators(
    engine: Any,
    asset_id: int,
    venue_id: int,
    tf: str,
) -> pd.DataFrame:
    """Load range-based vol estimators from features table.

    Returns a DataFrame indexed by ts with columns:
    vol_parkinson_20, vol_gk_20, atr_14 (normalised by close).
    """
    # atr_14 is in price units; normalise by close to get fractional vol
    query = text(
        """
        SELECT f.ts, f.vol_parkinson_20, f.vol_gk_20, f.atr_14,
               b.close
        FROM features f
        JOIN price_bars_multi_tf b
          ON b.id = f.id AND b.venue_id = f.venue_id AND b.ts = f.ts AND b.tf = f.tf
        WHERE f.id = :id AND f.venue_id = :venue_id AND f.tf = :tf
        ORDER BY f.ts
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(
            query, {"id": asset_id, "venue_id": venue_id, "tf": tf}
        ).fetchall()

    if not rows:
        return pd.DataFrame(columns=["vol_parkinson_20", "vol_gk_20", "atr_14"])

    records = []
    for r in rows:
        ts_val, park, gk, atr, close = r[0], r[1], r[2], r[3], r[4]
        # Normalise ATR by close to get fractional vol (comparable to Parkinson/GK)
        atr_norm = (
            (float(atr) / float(close))
            if (atr is not None and close and float(close) > 0)
            else np.nan
        )
        records.append(
            {
                "ts": ts_val,
                "vol_parkinson_20": float(park) if park is not None else np.nan,
                "vol_gk_20": float(gk) if gk is not None else np.nan,
                "atr_14": atr_norm,
            }
        )

    df = pd.DataFrame(records)
    df.index = pd.DatetimeIndex(df["ts"], name="ts")
    df.drop(columns="ts", inplace=True)
    return df


def _get_asset_ids(engine: Any, ids_arg: str, venue_id: int) -> list[int]:
    """Resolve asset IDs from CLI argument."""
    if ids_arg.strip().lower() == "all":
        query = text(
            """
            SELECT DISTINCT id FROM returns_bars_multi_tf
            WHERE venue_id = :venue_id AND tf = '1d'
            ORDER BY id
            """
        )
        with engine.connect() as conn:
            rows = conn.execute(query, {"venue_id": venue_id}).fetchall()
        return [int(r[0]) for r in rows]
    else:
        return [int(x.strip()) for x in ids_arg.split(",") if x.strip()]


# ---------------------------------------------------------------------------
# Evaluate range-based estimators against realised vol proxy
# ---------------------------------------------------------------------------


def _evaluate_range_estimators(
    returns: pd.Series,
    range_df: pd.DataFrame,
    eval_window: int,
    train_window: int,
) -> dict[str, dict[str, Any]]:
    """Compute RMSE, QLIKE, MZ R2 for range-based estimators.

    Aligns range estimators to the same OOS period as GARCH evaluation:
    only uses dates after the initial train_window.
    """
    realized = compute_realized_vol_proxy(returns, window=5)

    # OOS period: starts at bar train_window (same as GARCH rolling OOS)
    if len(returns) <= train_window:
        return {}

    oos_start_idx = train_window
    oos_dates = returns.index[oos_start_idx:]

    results: dict[str, dict[str, Any]] = {}

    for col in RANGE_ESTIMATORS:
        if col not in range_df.columns:
            results[col] = {
                "rmse": float("nan"),
                "qlike": float("nan"),
                "mz_r2": float("nan"),
                "combined": float("nan"),
                "n_forecasts": 0,
            }
            continue

        # Align range estimator to OOS dates
        range_aligned = range_df[col].reindex(oos_dates)
        real_aligned = realized.reindex(oos_dates)

        # Drop NaN pairs
        mask = ~(range_aligned.isna() | real_aligned.isna())
        if mask.sum() < 5:
            results[col] = {
                "rmse": float("nan"),
                "qlike": float("nan"),
                "mz_r2": float("nan"),
                "combined": float("nan"),
                "n_forecasts": int(mask.sum()),
            }
            continue

        f = range_aligned[mask].values
        r = real_aligned[mask].values

        rmse = rmse_loss(f, r)
        qlike = qlike_loss(f, r)
        mz = mincer_zarnowitz_r2(f, r)

        results[col] = {
            "rmse": rmse,
            "qlike": qlike,
            "mz_r2": mz,
            "combined": combined_score(rmse, qlike),
            "n_forecasts": int(mask.sum()),
        }

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _generate_markdown_report(
    aggregate_df: pd.DataFrame,
    per_asset_df: pd.DataFrame,
    report_date: str,
    n_assets: int,
    train_window: int,
    eval_window: int,
    output_path: Path,
) -> None:
    """Write the markdown comparison report."""
    lines: list[str] = []

    lines.append("# GARCH vs Range-Based Volatility Estimator Comparison Report\n")
    lines.append(f"**Date:** {report_date}")
    lines.append(f"**Assets evaluated:** {n_assets}")
    lines.append(f"**Training window:** {train_window} bars")
    lines.append(f"**OOS evaluation window:** {eval_window} bars")
    lines.append("**Realised vol proxy:** 5-day rolling std of log returns\n")
    lines.append("---\n")

    # Aggregate results table
    lines.append("## Aggregate Results (sorted by Combined Score)\n")
    if aggregate_df.empty:
        lines.append("*No estimators had enough data for evaluation.*\n")
    else:
        agg = aggregate_df.sort_values("combined_mean")
        lines.append(
            "| Rank | Estimator | RMSE (mean) | RMSE (median) | QLIKE (mean) | QLIKE (median) "
            "| MZ R2 (mean) | Combined (mean) | #1 Rank Count |"
        )
        lines.append(
            "|------|-----------|-------------|---------------|--------------|----------------"
            "|--------------|-----------------|---------------|"
        )
        for rank, (_, row) in enumerate(agg.iterrows(), 1):
            name = DISPLAY_NAMES.get(row["estimator"], row["estimator"])
            lines.append(
                f"| {rank} | {name} "
                f"| {row['rmse_mean']:.6f} | {row['rmse_median']:.6f} "
                f"| {row['qlike_mean']:.4f} | {row['qlike_median']:.4f} "
                f"| {row['mz_r2_mean']:.4f} | {row['combined_mean']:.6f} "
                f"| {int(row['rank1_count'])} |"
            )
        lines.append("")

    # Per-asset: identify best GARCH vs best range per asset
    if not per_asset_df.empty:
        garch_models = {"garch_1_1", "gjr_garch_1_1", "egarch_1_1", "figarch_1_d_1"}
        range_models = set(RANGE_ESTIMATORS)

        asset_summary_rows = []
        for asset_id, grp in per_asset_df.groupby("asset_id"):
            garch_rows = grp[grp["estimator"].isin(garch_models)]
            range_rows = grp[grp["estimator"].isin(range_models)]

            if garch_rows.empty or range_rows.empty:
                continue

            best_garch = garch_rows.loc[garch_rows["rmse"].idxmin()]
            best_range = range_rows.loc[range_rows["rmse"].idxmin()]

            garch_rmse = best_garch["rmse"]
            range_rmse = best_range["rmse"]

            if np.isfinite(garch_rmse) and np.isfinite(range_rmse) and range_rmse > 0:
                improvement_pct = (range_rmse - garch_rmse) / range_rmse * 100.0
            else:
                improvement_pct = float("nan")

            asset_summary_rows.append(
                {
                    "asset_id": int(asset_id),
                    "best_garch": best_garch["estimator"],
                    "best_garch_rmse": garch_rmse,
                    "best_range": best_range["estimator"],
                    "best_range_rmse": range_rmse,
                    "improvement_pct": improvement_pct,
                }
            )

        if asset_summary_rows:
            summary_df = pd.DataFrame(asset_summary_rows).sort_values(
                "improvement_pct", ascending=False
            )
            valid_improvements = summary_df["improvement_pct"].dropna()

            # Improvement distribution summary
            lines.append("## GARCH Improvement Distribution\n")
            if not valid_improvements.empty:
                n_better = int((valid_improvements > 0).sum())
                n_worse = int((valid_improvements <= 0).sum())
                n_strong = int((valid_improvements > 10).sum())
                n_degraded = int((valid_improvements < -10).sum())

                lines.append(
                    f"- **{n_better}** of {len(valid_improvements)} assets show GARCH improvement (RMSE reduction > 0%)"
                )
                lines.append(
                    f"- **{n_strong}** assets show strong improvement (>10% RMSE reduction)"
                )
                lines.append(
                    f"- **{n_worse}** assets show no GARCH benefit (range-based is equal or better)"
                )
                lines.append(
                    f"- **{n_degraded}** assets show notable degradation (>10% RMSE increase)"
                )
                lines.append(
                    f"- Median improvement: {valid_improvements.median():.1f}%"
                )
                lines.append(f"- Mean improvement: {valid_improvements.mean():.1f}%\n")
            else:
                lines.append("*No valid comparisons available.*\n")

            # Top-3 assets (GARCH wins most)
            top3 = summary_df.head(3)
            lines.append("## Per-Asset Top 3 (GARCH most beneficial)\n")
            lines.append(
                "| Asset ID | Best GARCH | GARCH RMSE | Best Range | Range RMSE | Improvement % |"
            )
            lines.append(
                "|----------|------------|------------|------------|------------|---------------|"
            )
            for _, row in top3.iterrows():
                gn = DISPLAY_NAMES.get(row["best_garch"], row["best_garch"])
                rn = DISPLAY_NAMES.get(row["best_range"], row["best_range"])
                lines.append(
                    f"| {int(row['asset_id'])} | {gn} | {row['best_garch_rmse']:.6f} "
                    f"| {rn} | {row['best_range_rmse']:.6f} "
                    f"| {row['improvement_pct']:+.1f}% |"
                )
            lines.append("")

            # Bottom-3 assets (range wins most)
            bottom3 = summary_df.tail(3).iloc[::-1]
            lines.append("## Per-Asset Bottom 3 (range-based better)\n")
            lines.append(
                "| Asset ID | Best GARCH | GARCH RMSE | Best Range | Range RMSE | Improvement % |"
            )
            lines.append(
                "|----------|------------|------------|------------|------------|---------------|"
            )
            for _, row in bottom3.iterrows():
                gn = DISPLAY_NAMES.get(row["best_garch"], row["best_garch"])
                rn = DISPLAY_NAMES.get(row["best_range"], row["best_range"])
                lines.append(
                    f"| {int(row['asset_id'])} | {gn} | {row['best_garch_rmse']:.6f} "
                    f"| {rn} | {row['best_range_rmse']:.6f} "
                    f"| {row['improvement_pct']:+.1f}% |"
                )
            lines.append("")

            # Conclusion
            lines.append("## Conclusion\n")
            if not valid_improvements.empty:
                median_imp = valid_improvements.median()
                if median_imp > 5:
                    verdict = (
                        "GARCH adds meaningful value over range-based estimators for the "
                        "majority of assets. The median RMSE improvement is substantial."
                    )
                elif median_imp > 0:
                    verdict = (
                        "GARCH provides modest improvement over range-based estimators on "
                        "average. Per-asset variation is significant; selective use of GARCH "
                        "for assets where it outperforms is recommended."
                    )
                else:
                    verdict = (
                        "Range-based estimators perform comparably to GARCH models on "
                        "average. GARCH provides benefit for a subset of assets but the "
                        "aggregate improvement is minimal. Consider using blend weights "
                        "to combine both approaches."
                    )
                lines.append(verdict)
                lines.append(
                    f"\n*Median RMSE improvement: {median_imp:.1f}% across {len(valid_improvements)} assets.*"
                )
            else:
                lines.append("*Insufficient data for a conclusion.*")

    lines.append("\n---")
    lines.append(
        "*Generated by run_garch_comparison.py (Phase 81, GARCH conditional volatility)*"
    )

    output_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for GARCH comparison report."""
    parser = argparse.ArgumentParser(
        description="Generate GARCH vs range-based volatility estimator comparison report"
    )
    parser.add_argument(
        "--ids",
        default="all",
        help='Comma-separated asset IDs or "all" (default: all)',
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe (default: 1D)",
    )
    parser.add_argument(
        "--venue-id",
        type=int,
        default=1,
        help="Venue ID (default: 1 = CMC_AGG)",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL override (default: from db_config.env / TARGET_DB_URL)",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory for report output files (default: current directory)",
    )
    parser.add_argument(
        "--eval-window",
        type=int,
        default=63,
        help="OOS evaluation window in days (default: 63)",
    )
    parser.add_argument(
        "--train-window",
        type=int,
        default=252,
        help="Training window in days (default: 252)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Resolve DB URL
    db_url = args.db_url
    if db_url is None:
        db_url = os.environ.get("TARGET_DB_URL")
    if db_url is None:
        try:
            from ta_lab2.scripts.refresh_utils import resolve_db_url  # noqa: PLC0415

            db_url = resolve_db_url(None)
        except Exception as exc:
            print(f"[ERROR] Cannot resolve database URL: {exc}", file=sys.stderr)
            return 1

    engine = create_engine(db_url, poolclass=NullPool)

    # Resolve asset IDs
    asset_ids = _get_asset_ids(engine, args.ids, args.venue_id)
    if not asset_ids:
        print("[ERROR] No asset IDs found")
        return 1

    tf = args.tf.lower()
    venue_id = args.venue_id
    train_window = args.train_window
    eval_window = args.eval_window
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(f"\n{'=' * 70}")
    print("GARCH COMPARISON REPORT GENERATOR")
    print(f"{'=' * 70}")
    print(f"  Assets:         {len(asset_ids)}")
    print(f"  Timeframe:      {tf}")
    print(f"  Venue ID:       {venue_id}")
    print(f"  Train window:   {train_window} bars")
    print(f"  Eval window:    {eval_window} bars")
    print(f"  Output dir:     {output_dir}")

    # Per-asset evaluation
    all_per_asset_rows: list[dict[str, Any]] = []
    n_evaluated = 0
    n_skipped = 0

    start_time = time.perf_counter()

    for idx, asset_id in enumerate(asset_ids, 1):
        logger.info("Processing asset %d/%d (id=%d)", idx, len(asset_ids), asset_id)
        if args.verbose:
            print(f"\n  [{idx}/{len(asset_ids)}] Asset {asset_id}...")

        # Load returns
        returns = _load_returns(engine, asset_id, venue_id, tf)
        min_required = train_window + eval_window

        if len(returns) < min_required:
            if args.verbose:
                print(f"    Skipped: only {len(returns)} bars (need {min_required})")
            n_skipped += 1
            continue

        # Drop NaN returns
        returns = returns.dropna()
        if len(returns) < min_required:
            if args.verbose:
                print(
                    f"    Skipped: only {len(returns)} non-NaN bars (need {min_required})"
                )
            n_skipped += 1
            continue

        # Evaluate GARCH models (rolling OOS)
        garch_results = evaluate_all_models(
            returns,
            train_window=train_window,
            eval_window=eval_window,
        )

        # Load and evaluate range-based estimators
        range_df = _load_range_estimators(engine, asset_id, venue_id, tf)
        range_results = _evaluate_range_estimators(
            returns, range_df, eval_window, train_window
        )

        # Combine results for this asset
        for est_name, metrics in garch_results.items():
            all_per_asset_rows.append(
                {
                    "asset_id": asset_id,
                    "estimator": est_name,
                    "rmse": metrics["rmse"],
                    "qlike": metrics["qlike"],
                    "mz_r2": metrics["mz_r2"],
                    "combined": metrics["combined"],
                    "n_forecasts": metrics["n_forecasts"],
                }
            )

        for est_name, metrics in range_results.items():
            all_per_asset_rows.append(
                {
                    "asset_id": asset_id,
                    "estimator": est_name,
                    "rmse": metrics["rmse"],
                    "qlike": metrics["qlike"],
                    "mz_r2": metrics["mz_r2"],
                    "combined": metrics["combined"],
                    "n_forecasts": metrics["n_forecasts"],
                }
            )

        n_evaluated += 1

        if args.verbose:
            # Print per-asset summary
            best_name = None
            best_rmse = float("inf")
            for est_name in list(garch_results.keys()) + list(range_results.keys()):
                r_dict = garch_results.get(est_name) or range_results.get(est_name)
                if (
                    r_dict
                    and np.isfinite(r_dict["rmse"])
                    and r_dict["rmse"] < best_rmse
                ):
                    best_rmse = r_dict["rmse"]
                    best_name = est_name
            if best_name:
                print(
                    f"    Best: {DISPLAY_NAMES.get(best_name, best_name)} "
                    f"(RMSE={best_rmse:.6f})"
                )

    elapsed = time.perf_counter() - start_time

    print(f"\n  Evaluated: {n_evaluated} assets")
    print(f"  Skipped:   {n_skipped} assets (insufficient history)")
    print(f"  Duration:  {elapsed:.1f}s")

    if not all_per_asset_rows:
        print("\n[WARN] No assets had sufficient data for evaluation")
        return 0

    # Build per-asset DataFrame
    per_asset_df = pd.DataFrame(all_per_asset_rows)

    # Build aggregate DataFrame
    aggregate_rows = []
    for estimator, grp in per_asset_df.groupby("estimator"):
        valid = grp[grp["n_forecasts"] > 0]
        if valid.empty:
            continue

        # Count rank-1 appearances: how many assets does this estimator rank #1 by combined score?
        rank1_count = 0
        for _, asset_grp in per_asset_df.groupby("asset_id"):
            valid_asset = asset_grp[
                (asset_grp["n_forecasts"] > 0) & np.isfinite(asset_grp["combined"])
            ]
            if valid_asset.empty:
                continue
            best_idx = valid_asset["combined"].idxmin()
            if valid_asset.loc[best_idx, "estimator"] == estimator:
                rank1_count += 1

        aggregate_rows.append(
            {
                "estimator": str(estimator),
                "rmse_mean": valid["rmse"].mean(),
                "rmse_median": valid["rmse"].median(),
                "qlike_mean": valid["qlike"].mean(),
                "qlike_median": valid["qlike"].median(),
                "mz_r2_mean": valid["mz_r2"].mean(),
                "combined_mean": valid["combined"].mean(),
                "rank1_count": rank1_count,
                "n_assets": len(valid),
            }
        )

    aggregate_df = pd.DataFrame(aggregate_rows)

    # Write CSV files
    agg_csv_path = output_dir / "garch_comparison_aggregate.csv"
    per_asset_csv_path = output_dir / "garch_comparison_per_asset.csv"
    report_md_path = output_dir / "garch_comparison_report.md"

    aggregate_df.to_csv(agg_csv_path, index=False)
    per_asset_df.to_csv(per_asset_csv_path, index=False)

    # Generate markdown report
    _generate_markdown_report(
        aggregate_df=aggregate_df,
        per_asset_df=per_asset_df,
        report_date=report_date,
        n_assets=n_evaluated,
        train_window=train_window,
        eval_window=eval_window,
        output_path=report_md_path,
    )

    # Print summary to stdout
    print(f"\n{'=' * 70}")
    print("COMPARISON REPORT COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Markdown: {report_md_path}")
    print(f"  Aggregate CSV: {agg_csv_path}")
    print(f"  Per-asset CSV: {per_asset_csv_path}")

    if not aggregate_df.empty:
        print("\n  Aggregate ranking (by combined score):")
        agg_sorted = aggregate_df.sort_values("combined_mean")
        for rank, (_, row) in enumerate(agg_sorted.iterrows(), 1):
            name = DISPLAY_NAMES.get(row["estimator"], row["estimator"])
            print(
                f"    {rank}. {name:<20s} RMSE={row['rmse_mean']:.6f}  "
                f"QLIKE={row['qlike_mean']:.4f}  "
                f"MZ-R2={row['mz_r2_mean']:.4f}  "
                f"Combined={row['combined_mean']:.6f}  "
                f"(#1 in {int(row['rank1_count'])} assets)"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
