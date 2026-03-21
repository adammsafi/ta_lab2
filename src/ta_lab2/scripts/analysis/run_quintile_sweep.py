"""
CLI for quintile group returns analysis on features.

Loads all assets for a given timeframe, ranks them by a factor column into
5 cross-sectional quintiles at each timestamp, and produces a Plotly HTML
chart showing cumulative returns per quintile (Q1-Q5) plus the Q5-Q1
long-short spread.

Usage:
    python -m ta_lab2.scripts.analysis.run_quintile_sweep --factor rsi_14 --tf 1D
    python -m ta_lab2.scripts.analysis.run_quintile_sweep --factor ret_arith --tf 1D --horizon 5
    python -m ta_lab2.scripts.analysis.run_quintile_sweep --factor vol_30d --tf 1D --min-assets 10
    python -m ta_lab2.scripts.analysis.run_quintile_sweep \\
        --factor rsi_14 --tf 1D --horizon 3 \\
        --output reports/quintile/rsi_14_1D_h3.html

The factor column must exist in public.features (validated against
information_schema before building SQL to prevent injection).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import pandas as pd
from sqlalchemy import create_engine, pool, text

from ta_lab2.analysis.quintile import (
    build_quintile_returns_chart,
    compute_quintile_returns,
)
from ta_lab2.scripts.refresh_utils import resolve_db_url
from ta_lab2.scripts.sync_utils import get_columns

logger = logging.getLogger(__name__)

# Columns in features that are identifiers/metadata — never valid factors
_NON_FACTOR_COLS = frozenset(
    ["id", "ts", "tf", "open", "high", "low", "close", "volume", "ingested_at"]
)


def _validate_factor_col(engine, factor_col: str) -> list[str]:
    """
    Validate that factor_col exists in features.

    Returns the full list of available factor columns for error messaging.
    Raises ValueError if factor_col is not found.
    """
    available = get_columns(engine, "public.features")
    if factor_col not in available:
        valid_factors = sorted(c for c in available if c not in _NON_FACTOR_COLS)
        raise ValueError(
            f"Factor column '{factor_col}' not found in public.features.\n"
            f"Available factor columns ({len(valid_factors)}): {valid_factors[:20]}..."
        )
    return available


def _load_features(
    engine, tf: str, factor_col: str, close_col: str = "close"
) -> pd.DataFrame:
    """
    Load all assets from features for the given tf and factor column.

    SQL is constructed with a pre-validated column name (validated by
    _validate_factor_col before this function is called), preventing injection.

    Parameters
    ----------
    engine : SQLAlchemy engine
    tf : str
        Timeframe filter (e.g. '1D').
    factor_col : str
        Pre-validated feature column name.
    close_col : str
        Close price column. Default 'close'.

    Returns
    -------
    pd.DataFrame
        Columns: id, ts, factor_col, close (plus tf if present).
        ts is UTC-aware datetime.
    """
    sql = text(
        f"SELECT id, ts, {factor_col}, {close_col} "
        f"FROM public.features "
        f"WHERE tf = :tf AND {factor_col} IS NOT NULL "
        f"ORDER BY ts, id"
    )

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"tf": tf})

    if df.empty:
        logger.warning(
            "No rows returned from features for tf='%s', factor='%s'",
            tf,
            factor_col,
        )
        return df

    # Fix tz: CRITICAL — pd.read_sql on Windows may return object dtype or tz-naive
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    logger.info(
        "Loaded %d rows, %d unique assets, %d unique timestamps for tf='%s' factor='%s'",
        len(df),
        df["id"].nunique(),
        df["ts"].nunique(),
        tf,
        factor_col,
    )

    return df


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_quintile_sweep",
        description=(
            "Quintile group returns analysis for factor monotonicity testing.\n\n"
            "Ranks all assets by a factor column from features into 5 equal-weight "
            "quintiles at each timestamp. Tracks cumulative forward returns per quintile "
            "and produces a Plotly HTML chart with Q1-Q5 lines + Q5-Q1 long-short spread.\n\n"
            "This is the gold-standard test for factor predictive power: a factor has "
            "monotonic predictive power when Q1 < Q2 < Q3 < Q4 < Q5 in cumulative returns."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required: factor column
    parser.add_argument(
        "--factor",
        required=True,
        type=str,
        metavar="COL",
        help="Feature column name from features (e.g. rsi_14, ret_arith, vol_30d).",
    )

    # Optional: timeframe
    parser.add_argument(
        "--tf",
        default="1D",
        type=str,
        metavar="TF",
        help="Timeframe filter for features (default: 1D).",
    )

    # Optional: forward return horizon
    parser.add_argument(
        "--horizon",
        default=1,
        type=int,
        metavar="N",
        help="Forward return horizon in bars (default: 1).",
    )

    # Optional: minimum assets per timestamp
    parser.add_argument(
        "--min-assets",
        default=5,
        type=int,
        metavar="N",
        dest="min_assets",
        help="Minimum assets per timestamp required for quintile assignment (default: 5).",
    )

    # Optional: output path
    parser.add_argument(
        "--output",
        default=None,
        type=str,
        metavar="PATH",
        help=(
            "Output HTML file path. Default: reports/quintile/{factor}_{tf}_h{horizon}.html"
        ),
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

    # Resolve output path
    output_path = args.output
    if output_path is None:
        output_path = f"reports/quintile/{args.factor}_{args.tf}_h{args.horizon}.html"

    logger.info(
        "Quintile sweep: factor='%s' tf='%s' horizon=%d min_assets=%d",
        args.factor,
        args.tf,
        args.horizon,
        args.min_assets,
    )
    logger.info("Output: %s", output_path)

    # --- 1. Create engine (NullPool: no connection pooling for one-shot scripts) ---
    db_url = resolve_db_url()
    engine = create_engine(db_url, poolclass=pool.NullPool)

    # --- 2. Validate factor column against information_schema (injection guard) ---
    try:
        _validate_factor_col(engine, args.factor)
    except ValueError as exc:
        logger.error("Factor validation failed: %s", exc)
        return 1

    # --- 3. Load all assets from features ---
    try:
        df = _load_features(engine, args.tf, args.factor)
    except Exception as exc:
        logger.error("Failed to load features from features: %s", exc, exc_info=True)
        return 1

    if df.empty:
        logger.error(
            "No data found in features for tf='%s' factor='%s'. Exiting.",
            args.tf,
            args.factor,
        )
        return 1

    n_assets = df["id"].nunique()
    n_timestamps = df["ts"].nunique()

    logger.info(
        "Dataset: %d unique assets, %d unique timestamps", n_assets, n_timestamps
    )

    # --- 4. Compute quintile returns ---
    try:
        cumulative, long_short_spread = compute_quintile_returns(
            df,
            factor_col=args.factor,
            forward_horizon=args.horizon,
            close_col="close",
            min_assets_per_ts=args.min_assets,
        )
    except Exception as exc:
        logger.error("compute_quintile_returns failed: %s", exc, exc_info=True)
        return 1

    if cumulative.empty:
        logger.error(
            "Quintile computation produced empty results for factor='%s' tf='%s'. "
            "Check that enough assets have non-null factor values.",
            args.factor,
            args.tf,
        )
        return 1

    # --- 5. Build Plotly chart ---
    try:
        fig = build_quintile_returns_chart(
            cumulative,
            factor_col=args.factor,
            horizon=args.horizon,
            long_short_spread=long_short_spread,
        )
    except Exception as exc:
        logger.error("build_quintile_returns_chart failed: %s", exc, exc_info=True)
        return 1

    # --- 6. Save chart HTML ---
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    fig.write_html(output_path)
    logger.info("Chart saved to: %s", output_path)

    # --- 7. Print summary ---
    final_spread = (
        float(long_short_spread.iloc[-1])
        if not long_short_spread.empty
        else float("nan")
    )
    q1_final = (
        float(cumulative[1].iloc[-1]) if 1 in cumulative.columns else float("nan")
    )
    q5_final = (
        float(cumulative[5].iloc[-1]) if 5 in cumulative.columns else float("nan")
    )

    print("\n=== Quintile Sweep Summary ===")
    print(f"  Factor:          {args.factor}")
    print(f"  Timeframe:       {args.tf}")
    print(f"  Horizon:         {args.horizon} bar(s)")
    print(f"  Timestamps:      {len(cumulative)}")
    print(f"  Unique assets:   {n_assets}")
    print(f"  Q1 final return: {q1_final:.4f}x ({(q1_final - 1) * 100:.2f}%)")
    print(f"  Q5 final return: {q5_final:.4f}x ({(q5_final - 1) * 100:.2f}%)")
    print(f"  Q5-Q1 spread:    {final_spread:.4f}")
    print(f"  Output:          {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
