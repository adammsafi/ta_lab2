"""
Incremental daily volatility refresh from cmc_price_bars_1d.

This script computes daily volatility measures (Parkinson, Garman-Klass,
Rogers-Satchell, ATR, rolling historical) from OHLC bars and writes them
to cmc_vol_daily table.

State tracking uses public.cmc_feature_state (feature_type='vol').

Usage:
    # Compute for specific IDs
    python -m ta_lab2.scripts.features.refresh_cmc_vol_daily --ids 1,52

    # Compute for all IDs
    python -m ta_lab2.scripts.features.refresh_cmc_vol_daily --all

    # Full refresh (recompute from start date)
    python -m ta_lab2.scripts.features.refresh_cmc_vol_daily --ids 1,52 --full-refresh

    # Dry run (no writes)
    python -m ta_lab2.scripts.features.refresh_cmc_vol_daily --ids 1,52 --dry-run

Features computed:
- Parkinson (1980): Range-based volatility (high/low)
- Garman-Klass (1980): OHLC-based volatility
- Rogers-Satchell (1991): Drift-independent volatility
- ATR (Wilder): Average True Range
- Rolling historical volatility from log returns

All volatility measures annualized using sqrt(252) for trading days.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from ta_lab2.io import get_engine
from ta_lab2.scripts.features.vol_feature import VolatilityFeature, VolatilityConfig
from ta_lab2.scripts.features.feature_state_manager import (
    FeatureStateManager,
    FeatureStateConfig,
)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Incremental daily volatility refresh from cmc_price_bars_1d",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compute for specific IDs
  python -m ta_lab2.scripts.features.refresh_cmc_vol_daily --ids 1,52

  # Compute for all IDs
  python -m ta_lab2.scripts.features.refresh_cmc_vol_daily --all

  # Full refresh from start date
  python -m ta_lab2.scripts.features.refresh_cmc_vol_daily --ids 1,52 --full-refresh

  # Dry run
  python -m ta_lab2.scripts.features.refresh_cmc_vol_daily --ids 1,52 --dry-run
        """,
    )

    # ID selection
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument(
        "--ids",
        type=str,
        help="Comma-separated list of asset IDs (e.g., '1,52,1027')",
    )
    id_group.add_argument(
        "--all",
        action="store_true",
        help="Compute for all IDs with price bars",
    )

    # Date range
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD). If omitted, uses incremental state or default",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD). If omitted, computes through latest bar",
    )

    # Refresh mode
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Ignore state and recompute from --start (or default start date)",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute features but don't write to database",
    )

    # Verbosity
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    return parser.parse_args(argv)


def get_all_ids(engine) -> list[int]:
    """
    Query all distinct IDs from cmc_price_bars_1d.

    Returns:
        List of asset IDs with daily bars
    """
    from sqlalchemy import text

    sql = text(
        """
        SELECT DISTINCT id
        FROM public.cmc_price_bars_1d
        ORDER BY id
    """
    )

    with engine.connect() as conn:
        result = conn.execute(sql)
        ids = [row[0] for row in result]

    return ids


def main(argv: Optional[list[str]] = None) -> int:
    """
    Main entry point for volatility refresh script.

    Returns:
        Exit code (0 = success, non-zero = error)
    """
    args = parse_args(argv)

    # Initialize engine
    engine = get_engine()

    # Initialize config and feature
    vol_config = VolatilityConfig()
    vol_feature = VolatilityFeature(engine, vol_config)

    # Initialize state manager
    state_config = FeatureStateConfig(
        state_schema="public",
        state_table="cmc_feature_state",
        feature_type="vol",
        ts_column="ts",
        id_column="id",
    )
    state_manager = FeatureStateManager(engine, state_config)

    # Ensure state table exists
    state_manager.ensure_state_table()

    # Determine IDs to process
    if args.all:
        ids = get_all_ids(engine)
        if args.verbose:
            print(f"Found {len(ids)} IDs with daily bars")
    else:
        ids = [int(x.strip()) for x in args.ids.split(",")]
        if args.verbose:
            print(f"Processing {len(ids)} IDs: {ids}")

    if not ids:
        print("No IDs to process")
        return 0

    # Determine start date
    start_date = args.start

    if not args.full_refresh and start_date is None:
        # Load state to determine dirty window
        if args.verbose:
            print("Loading state for incremental refresh...")

        dirty_starts = state_manager.compute_dirty_window_starts(
            ids=ids,
            feature_type="vol",
            default_start="2010-01-01",
        )

        # For simplicity, use earliest dirty start across all IDs
        # (More sophisticated: process each ID with its own dirty start)
        start_date = min(dirty_starts.values()).strftime("%Y-%m-%d")

        if args.verbose:
            print(f"Incremental refresh from: {start_date}")
    elif args.full_refresh:
        # Full refresh from explicit start or default
        start_date = start_date or "2010-01-01"
        if args.verbose:
            print(f"Full refresh from: {start_date}")

    # Compute features
    if args.verbose:
        print("Computing volatility features...")
        print(f"  IDs: {ids}")
        print(f"  Start: {start_date}")
        print(f"  End: {args.end or 'latest'}")

    rows_computed = vol_feature.compute_for_ids(
        ids=ids,
        start=start_date,
        end=args.end,
    )

    if args.verbose:
        print(f"Computed {rows_computed} rows")

    # Update state (unless dry-run)
    if not args.dry_run:
        if args.verbose:
            print("Updating state...")

        state_rows = state_manager.update_state_from_output(
            output_table=vol_config.output_table,
            output_schema=vol_config.output_schema,
            feature_name="vol_daily",  # Single feature name for all vol metrics
        )

        if args.verbose:
            print(f"Updated {state_rows} state rows")

        print(f"[OK] Computed {rows_computed} volatility rows for {len(ids)} IDs")
    else:
        print(
            f"[DRY RUN] Would compute {rows_computed} volatility rows for {len(ids)} IDs"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
