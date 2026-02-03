#!/usr/bin/env python
"""
Refresh RSI mean reversion signals from cmc_daily_features.

This script generates RSI mean reversion trading signals using database-driven
threshold configuration from dim_signals. Supports both incremental and full
refresh modes with optional adaptive threshold computation.

Usage:
    # Refresh all active RSI signals for all assets (incremental)
    python refresh_cmc_signals_rsi_mean_revert.py

    # Full refresh for specific assets
    python refresh_cmc_signals_rsi_mean_revert.py --ids 1 52 --full-refresh

    # Use adaptive rolling percentile thresholds
    python refresh_cmc_signals_rsi_mean_revert.py --adaptive

    # Specific signal only
    python refresh_cmc_signals_rsi_mean_revert.py --signal-id 4

    # Dry run (validation without database writes)
    python refresh_cmc_signals_rsi_mean_revert.py --dry-run --verbose

Configuration:
    - Thresholds loaded from dim_signals params (default: lower=30, upper=70)
    - Signal types: 'rsi_mean_revert' in dim_signals
    - Output table: cmc_signals_rsi_mean_revert
    - State tracking: cmc_signal_state (per id, signal_type, signal_id)

Environment:
    Requires TARGET_DB_URL environment variable with PostgreSQL connection string.

Examples:
    # Default incremental refresh
    export TARGET_DB_URL="postgresql://user:pass@localhost/db"
    python refresh_cmc_signals_rsi_mean_revert.py

    # Full refresh with adaptive thresholds for debugging
    python refresh_cmc_signals_rsi_mean_revert.py --full-refresh --adaptive -v
"""

import argparse
import logging
import os
import sys
from sqlalchemy import create_engine, text

from ta_lab2.scripts.signals.signal_state_manager import (
    SignalStateManager,
    SignalStateConfig,
)
from ta_lab2.scripts.signals.signal_utils import load_active_signals
from ta_lab2.scripts.signals.generate_signals_rsi import RSISignalGenerator


logger = logging.getLogger(__name__)


def _get_all_asset_ids(engine) -> list[int]:
    """
    Query all unique asset IDs from cmc_daily_features.

    Args:
        engine: SQLAlchemy engine

    Returns:
        List of asset IDs sorted ascending
    """
    sql = text("SELECT DISTINCT id FROM public.cmc_daily_features ORDER BY id")

    with engine.connect() as conn:
        result = conn.execute(sql)
        return [row[0] for row in result.fetchall()]


def main():
    """Main entry point for RSI signal refresh script."""
    parser = argparse.ArgumentParser(
        description="Refresh RSI mean reversion signals from cmc_daily_features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Refresh all RSI signals incrementally
  %(prog)s

  # Full refresh for specific assets
  %(prog)s --ids 1 52 --full-refresh

  # Use adaptive rolling thresholds
  %(prog)s --adaptive

  # Dry run validation
  %(prog)s --dry-run -v
        """,
    )

    parser.add_argument(
        "--ids",
        type=int,
        nargs="+",
        help="Asset IDs to process (default: all from cmc_daily_features)",
    )
    parser.add_argument(
        "--signal-id",
        type=int,
        help="Process specific signal_id only (default: all active rsi_mean_revert)",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Regenerate all signals from scratch (ignore state tracking)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate without writing to database"
    )
    parser.add_argument(
        "--adaptive",
        action="store_true",
        help="Use adaptive rolling percentile thresholds instead of static from dim_signals",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Validate environment
    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        logger.error("TARGET_DB_URL environment variable not set")
        sys.exit(1)

    try:
        engine = create_engine(db_url)
        logger.info(
            f"Connected to database: {db_url.split('@')[-1]}"
        )  # Hide credentials
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)

    # Initialize state manager
    config = SignalStateConfig(signal_type="rsi_mean_revert")
    state_manager = SignalStateManager(engine, config)

    try:
        state_manager.ensure_state_table()
        logger.info("State table ensured")
    except Exception as e:
        logger.error(f"Failed to ensure state table: {e}")
        sys.exit(1)

    # Load signal configurations
    try:
        if args.signal_id:
            configs = [
                c
                for c in load_active_signals(engine, "rsi_mean_revert")
                if c["signal_id"] == args.signal_id
            ]
            if not configs:
                logger.error(f"No active signal found with signal_id={args.signal_id}")
                sys.exit(1)
        else:
            configs = load_active_signals(engine, "rsi_mean_revert")

        if not configs:
            logger.warning("No active RSI mean revert signals found in dim_signals")
            sys.exit(0)

        logger.info(f"Loaded {len(configs)} active signal configurations")
    except Exception as e:
        logger.error(f"Failed to load signal configurations: {e}")
        sys.exit(1)

    # Determine asset IDs to process
    if args.ids:
        ids = args.ids
        logger.info(f"Processing {len(ids)} specified asset IDs")
    else:
        try:
            ids = _get_all_asset_ids(engine)
            logger.info(f"Processing {len(ids)} assets from cmc_daily_features")
        except Exception as e:
            logger.error(f"Failed to query asset IDs: {e}")
            sys.exit(1)

    if not ids:
        logger.warning("No asset IDs to process")
        sys.exit(0)

    # Generate signals
    generator = RSISignalGenerator(engine, state_manager)
    total_signals = 0

    for config in configs:
        signal_id = config["signal_id"]
        signal_name = config["signal_name"]

        logger.info(
            f"Processing signal: {signal_name} (id={signal_id}), "
            f"params={config['params']}"
        )

        try:
            count = generator.generate_for_ids(
                ids=ids,
                signal_config=config,
                full_refresh=args.full_refresh,
                dry_run=args.dry_run,
                use_adaptive=args.adaptive,
            )
            total_signals += count
            logger.info(f"Generated {count} signals for {signal_name}")
        except Exception as e:
            logger.error(f"Failed to generate signals for {signal_name}: {e}")
            if args.verbose:
                logger.exception("Full traceback:")
            continue

    # Summary
    mode = "DRY RUN" if args.dry_run else "COMMITTED"
    refresh_type = "FULL" if args.full_refresh else "INCREMENTAL"
    threshold_mode = "ADAPTIVE" if args.adaptive else "STATIC"

    logger.info("=" * 80)
    logger.info(f"SUMMARY ({mode})")
    logger.info(f"  Refresh type: {refresh_type}")
    logger.info(f"  Threshold mode: {threshold_mode}")
    logger.info(f"  Signals processed: {len(configs)}")
    logger.info(f"  Assets processed: {len(ids)}")
    logger.info(f"  Total signals generated: {total_signals}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
