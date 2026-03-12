"""
IC decay visualization CLI.

Queries ic_results for all horizons of a given feature and generates an
HTML bar chart showing IC decay across forward horizons. Uses the existing
plot_ic_decay() function from ta_lab2.analysis.ic.

Usage:
    # IC decay for rsi_14 on 1D (all assets averaged)
    python -m ta_lab2.scripts.analysis.run_ic_decay --feature rsi_14

    # Specific asset
    python -m ta_lab2.scripts.analysis.run_ic_decay --feature rsi_14 --asset 1

    # Log returns, custom output path
    python -m ta_lab2.scripts.analysis.run_ic_decay --feature bb_pct_b --return-type log --output reports/ic_decay/bb_pct_b_log.html

    # 4H timeframe
    python -m ta_lab2.scripts.analysis.run_ic_decay --feature rsi_14 --tf 4H
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.ic import plot_ic_decay
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = Path("reports/ic_decay")


def _build_query(asset_id: int | None) -> str:
    """Build the aggregation SQL for ic_results."""
    asset_filter = "AND asset_id = :asset_id" if asset_id is not None else ""
    return f"""
        SELECT
            horizon,
            AVG(ic)          AS ic,
            AVG(ic_p_value)  AS ic_p_value,
            AVG(rank_ic)     AS rank_ic,
            AVG(ic_ir)       AS ic_ir,
            COUNT(*)         AS n_rows
        FROM public.ic_results
        WHERE feature     = :feature
          AND tf          = :tf
          AND return_type = :return_type
          AND regime_col  = 'all'
          AND regime_label = 'all'
          {asset_filter}
        GROUP BY horizon
        ORDER BY horizon
    """


def main(argv: list[str] | None = None) -> int:
    """Entry point for the IC decay CLI."""
    parser = argparse.ArgumentParser(
        prog="run_ic_decay",
        description="Generate an IC decay HTML chart for a given feature across all horizons.",
    )
    parser.add_argument(
        "--feature",
        required=True,
        help="Feature column name (e.g. rsi_14, bb_pct_b, vol_log_20).",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe filter (default: 1D).",
    )
    parser.add_argument(
        "--asset",
        type=int,
        default=None,
        help="Asset ID filter. If omitted, averages IC across all assets.",
    )
    parser.add_argument(
        "--return-type",
        dest="return_type",
        default="arith",
        choices=["arith", "log"],
        help="Return type filter (default: arith).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output HTML file path. "
            "Default: reports/ic_decay/{feature}_{tf}_{return_type}.html"
        ),
    )

    args = parser.parse_args(argv)

    # Resolve output path
    if args.output is None:
        asset_suffix = f"_asset{args.asset}" if args.asset is not None else ""
        filename = f"{args.feature}_{args.tf}_{args.return_type}{asset_suffix}.html"
        output_path = _DEFAULT_OUTPUT_DIR / filename
    else:
        output_path = Path(args.output)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Connect and query
    url = resolve_db_url()
    engine = create_engine(url, poolclass=NullPool)

    params: dict = {
        "feature": args.feature,
        "tf": args.tf,
        "return_type": args.return_type,
    }
    if args.asset is not None:
        params["asset_id"] = args.asset

    sql = text(_build_query(args.asset))

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if df.empty:
        logger.error(
            "No IC results found for feature=%s tf=%s return_type=%s%s. "
            "Run run_ic_sweep first to populate ic_results.",
            args.feature,
            args.tf,
            args.return_type,
            f" asset={args.asset}" if args.asset is not None else "",
        )
        return 1

    n_horizons = len(df)
    print(
        f"Found {n_horizons} horizons for feature={args.feature!r} tf={args.tf!r} "
        f"return_type={args.return_type!r}"
        + (f" asset={args.asset}" if args.asset is not None else " (all assets avg)")
    )

    # Build IC decay chart using the existing plot_ic_decay() helper
    fig = plot_ic_decay(df, feature=args.feature, return_type=args.return_type)

    # Add rank_ic trace as a secondary bar if available
    if "rank_ic" in df.columns and df["rank_ic"].notna().any():
        import plotly.graph_objects as go

        fig.add_trace(
            go.Bar(
                x=df["horizon"].tolist(),
                y=df["rank_ic"].tolist(),
                name="Rank IC",
                marker_color="orange",
                opacity=0.6,
                visible="legendonly",
            )
        )
        fig.update_layout(barmode="overlay")

    fig.write_html(str(output_path))
    print(f"IC decay chart saved to: {output_path}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
