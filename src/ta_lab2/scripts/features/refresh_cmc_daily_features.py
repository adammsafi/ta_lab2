"""
Refresh unified daily features store.

Usage:
    python -m ta_lab2.scripts.features.refresh_cmc_daily_features --ids 1,52
    python -m ta_lab2.scripts.features.refresh_cmc_daily_features --all
    python -m ta_lab2.scripts.features.refresh_cmc_daily_features --full-refresh

Materializes cmc_daily_features from:
- cmc_price_bars_1d
- cmc_ema_multi_tf_u
- cmc_returns_daily
- cmc_vol_daily
- cmc_ta_daily

State tracked in public.cmc_feature_state (feature_type='daily_features').
"""

import argparse
import logging
import sys
from typing import Optional

from sqlalchemy import create_engine, text

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.scripts.features.daily_features_view import refresh_daily_features

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Refresh unified daily features store (cmc_daily_features)"
    )

    # ID selection
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument(
        '--ids',
        type=str,
        help='Comma-separated list of asset IDs (e.g., "1,52,1027")'
    )
    id_group.add_argument(
        '--all',
        action='store_true',
        help='Refresh all assets (queries dim_sessions for active IDs)'
    )

    # Date range
    parser.add_argument(
        '--start',
        type=str,
        help='Start date (ISO format, e.g., "2024-01-01"). If not provided, computed from state.'
    )

    # Refresh mode
    parser.add_argument(
        '--full-refresh',
        action='store_true',
        help='Delete all existing rows for IDs before refresh (default: incremental)'
    )

    # Dry run
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be refreshed without executing'
    )

    return parser.parse_args()


def get_all_ids(engine) -> list[int]:
    """
    Query dim_sessions for all active asset IDs.

    Args:
        engine: SQLAlchemy engine

    Returns:
        List of active asset IDs
    """
    sql = text("""
        SELECT DISTINCT id
        FROM public.dim_sessions
        WHERE is_active = TRUE
        ORDER BY id
    """)

    with engine.connect() as conn:
        result = conn.execute(sql)
        ids = [row[0] for row in result.fetchall()]

    return ids


def main():
    """Main CLI entry point."""
    args = parse_args()

    if not TARGET_DB_URL:
        logger.error("TARGET_DB_URL not configured in config.py")
        sys.exit(1)

    # Create engine
    engine = create_engine(TARGET_DB_URL)

    # Determine IDs
    if args.all:
        ids = get_all_ids(engine)
        logger.info(f"Discovered {len(ids)} active asset IDs from dim_sessions")
    else:
        ids = [int(id_.strip()) for id_ in args.ids.split(',')]
        logger.info(f"Processing {len(ids)} asset IDs: {ids}")

    if not ids:
        logger.error("No IDs to process")
        sys.exit(1)

    # Dry run
    if args.dry_run:
        logger.info(f"DRY RUN: Would refresh {len(ids)} IDs")
        logger.info(f"  Start: {args.start or 'computed from state'}")
        logger.info(f"  Full refresh: {args.full_refresh}")
        sys.exit(0)

    # Execute refresh
    try:
        rows_inserted = refresh_daily_features(
            engine=engine,
            ids=ids,
            start=args.start,
            full_refresh=args.full_refresh,
        )

        logger.info(f"SUCCESS: Inserted {rows_inserted} rows into cmc_daily_features")

    except Exception as e:
        logger.error(f"FAILED: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
