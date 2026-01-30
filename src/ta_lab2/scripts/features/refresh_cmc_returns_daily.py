"""
Incremental daily returns refresh from cmc_price_bars_1d.

Computes daily returns with multiple lookback windows (1D, 3D, 5D, 7D, etc.)
using ReturnsFeature module.

Usage:
    python -m ta_lab2.scripts.features.refresh_cmc_returns_daily --ids 1,52
    python -m ta_lab2.scripts.features.refresh_cmc_returns_daily --all
    python -m ta_lab2.scripts.features.refresh_cmc_returns_daily --full-refresh
    python -m ta_lab2.scripts.features.refresh_cmc_returns_daily --dry-run

State tracked in public.cmc_feature_state (feature_type='returns').
For now, runs full computation (incremental state management to be added).
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from ta_lab2.scripts.bars.common_snapshot_contract import resolve_db_url, get_engine
from ta_lab2.scripts.features.returns_feature import ReturnsFeature, ReturnsConfig


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        argv: Optional argument list (for testing)

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Refresh cmc_returns_daily from cmc_price_bars_1d",
    )

    # ID selection
    id_group = parser.add_mutually_exclusive_group()
    id_group.add_argument(
        "--ids",
        help="Comma-separated cryptocurrency IDs (e.g., '1,52,1027')",
    )
    id_group.add_argument(
        "--all",
        action="store_true",
        help="Process all IDs from cmc_price_bars_1d",
    )

    # Date range
    parser.add_argument(
        "--start",
        help="Start date (YYYY-MM-DD, inclusive)",
    )
    parser.add_argument(
        "--end",
        help="End date (YYYY-MM-DD, inclusive)",
    )

    # Refresh mode
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Full refresh (recompute all rows)",
    )

    # Execution control
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing",
    )

    # Database connection
    parser.add_argument(
        "--db-url",
        help="Database URL (defaults to TARGET_DB_URL env var)",
    )

    args = parser.parse_args(argv)

    # Validate ID selection
    if not args.ids and not args.all:
        parser.error("Must specify --ids or --all")

    return args


def load_ids(engine, ids_arg: Optional[str] = None, all_ids: bool = False) -> list[int]:
    """
    Load cryptocurrency IDs to process.

    Args:
        engine: SQLAlchemy engine
        ids_arg: Comma-separated ID string
        all_ids: If True, load all IDs from bars table

    Returns:
        List of cryptocurrency IDs
    """
    if ids_arg:
        return [int(i.strip()) for i in ids_arg.split(",")]

    if all_ids:
        from sqlalchemy import text
        query = """
        SELECT DISTINCT id
        FROM public.cmc_price_bars_1d
        ORDER BY id
        """
        with engine.connect() as conn:
            result = conn.execute(text(query))
            return [row[0] for row in result]

    return []


def main(argv: Optional[list[str]] = None) -> int:
    """
    Main entry point for returns refresh script.

    Args:
        argv: Optional argument list (for testing)

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    args = parse_args(argv)

    # Resolve database URL
    try:
        db_url = resolve_db_url(args.db_url)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Create engine
    engine = get_engine(db_url)

    # Load IDs
    try:
        ids = load_ids(engine, args.ids, args.all)
    except Exception as e:
        print(f"Error loading IDs: {e}", file=sys.stderr)
        return 1

    if not ids:
        print("No IDs to process", file=sys.stderr)
        return 1

    print(f"Processing {len(ids)} cryptocurrency IDs")

    # Create feature instance
    config = ReturnsConfig()
    feature = ReturnsFeature(engine, config)

    # Dry run mode
    if args.dry_run:
        print("\n[DRY RUN MODE]")
        print(f"Would process IDs: {ids[:10]}{'...' if len(ids) > 10 else ''}")
        print(f"Start date: {args.start or 'all available'}")
        print(f"End date: {args.end or 'all available'}")
        print(f"Output table: {config.output_schema}.{config.output_table}")
        print(f"Lookback windows: {config.lookback_windows}")
        return 0

    # Compute features
    try:
        rows_written = feature.compute_for_ids(
            ids=ids,
            start=args.start,
            end=args.end,
        )
        print(f"Success: {rows_written} rows written to {config.output_table}")
        return 0

    except Exception as e:
        print(f"Error computing features: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
