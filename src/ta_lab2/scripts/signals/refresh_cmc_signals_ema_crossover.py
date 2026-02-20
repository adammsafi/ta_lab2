#!/usr/bin/env python
"""
Refresh EMA crossover signals from cmc_features.

Generates EMA crossover trading signals using database-driven configuration
from dim_signals. Supports incremental and full refresh modes with state
management via SignalStateManager.

Usage:
    python -m ta_lab2.scripts.signals.refresh_cmc_signals_ema_crossover --ids 1,52
    python -m ta_lab2.scripts.signals.refresh_cmc_signals_ema_crossover --all
    python -m ta_lab2.scripts.signals.refresh_cmc_signals_ema_crossover --signal-id 1
    python -m ta_lab2.scripts.signals.refresh_cmc_signals_ema_crossover --full-refresh
    python -m ta_lab2.scripts.signals.refresh_cmc_signals_ema_crossover --dry-run

Signal configurations loaded from dim_signals table (signal_type='ema_crossover').
State tracked in public.cmc_signal_state.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

from sqlalchemy import text, create_engine

from ta_lab2.scripts.signals import (
    SignalStateManager,
    SignalStateConfig,
    load_active_signals,
)
from ta_lab2.scripts.signals.generate_signals_ema import EMASignalGenerator


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        argv: Optional argument list (for testing)

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Refresh EMA crossover signals from cmc_features",
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
        help="Process all IDs from cmc_features",
    )

    # Signal selection
    parser.add_argument(
        "--signal-id",
        type=int,
        help="Specific signal_id from dim_signals (default: all active EMA crossover signals)",
    )

    # Refresh mode
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Recompute all signals from scratch (ignore state)",
    )

    # Execution control
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without writing to database",
    )

    # Logging
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
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


def get_all_asset_ids(engine) -> list[int]:
    """
    Query all distinct asset IDs from cmc_features.

    Args:
        engine: SQLAlchemy engine

    Returns:
        List of asset IDs sorted ascending
    """
    query = """
        SELECT DISTINCT id
        FROM public.cmc_features
        WHERE tf = '1D'
        ORDER BY id
    """
    with engine.connect() as conn:
        result = conn.execute(text(query))
        return [row[0] for row in result]


def load_ids(engine, ids_arg: Optional[str] = None, all_ids: bool = False) -> list[int]:
    """
    Load cryptocurrency IDs to process.

    Args:
        engine: SQLAlchemy engine
        ids_arg: Comma-separated ID string
        all_ids: If True, load all IDs from cmc_features

    Returns:
        List of cryptocurrency IDs
    """
    if ids_arg:
        return [int(i.strip()) for i in ids_arg.split(",")]

    if all_ids:
        return get_all_asset_ids(engine)

    return []


def main(argv: Optional[list[str]] = None) -> int:
    """
    Main entry point for EMA crossover signal refresh.

    Args:
        argv: Optional argument list (for testing)

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    args = parse_args(argv)

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

    # Resolve database URL
    db_url = args.db_url or os.environ.get("TARGET_DB_URL")
    if not db_url:
        logger.error("Database URL not provided and TARGET_DB_URL not set")
        return 1

    logger.debug(f"Connecting to database: {db_url[:20]}...")

    # Create engine
    try:
        engine = create_engine(db_url, future=True)
    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
        return 1

    # Load IDs
    try:
        ids = load_ids(engine, args.ids, args.all)
    except Exception as e:
        logger.error(f"Error loading IDs: {e}")
        return 1

    if not ids:
        logger.error("No IDs to process")
        return 1

    logger.info(f"Processing {len(ids)} cryptocurrency IDs")

    # Setup state manager
    config = SignalStateConfig(signal_type="ema_crossover")
    state_manager = SignalStateManager(engine, config)

    try:
        state_manager.ensure_state_table()
        logger.debug("State table verified/created")
    except Exception as e:
        logger.error(f"Failed to ensure state table: {e}")
        return 1

    # Load signal configurations from dim_signals
    try:
        if args.signal_id:
            configs = [
                c
                for c in load_active_signals(engine, "ema_crossover")
                if c["signal_id"] == args.signal_id
            ]
            if not configs:
                logger.error(f"Signal ID {args.signal_id} not found or not active")
                return 1
        else:
            configs = load_active_signals(engine, "ema_crossover")

        if not configs:
            logger.error("No active EMA crossover signals found in dim_signals")
            return 1

        logger.info(f"Loaded {len(configs)} signal configuration(s)")
        for cfg in configs:
            logger.debug(f"  - {cfg['signal_name']} (signal_id={cfg['signal_id']})")

    except Exception as e:
        logger.error(f"Error loading signal configurations: {e}")
        return 1

    # Dry run mode
    if args.dry_run:
        logger.info("\n[DRY RUN MODE]")
        logger.info(f"Would process IDs: {ids[:10]}{'...' if len(ids) > 10 else ''}")
        logger.info(f"Signal configurations: {[c['signal_name'] for c in configs]}")
        logger.info(f"Full refresh: {args.full_refresh}")
        logger.info("Output table: public.cmc_signals_ema_crossover")
        return 0

    # Generate signals
    generator = EMASignalGenerator(engine, state_manager)
    total_signals = 0

    try:
        for config in configs:
            logger.info(f"\nProcessing signal: {config['signal_name']}")
            logger.debug(f"  Params: {config['params']}")

            n = generator.generate_for_ids(
                ids=ids,
                signal_config=config,
                full_refresh=args.full_refresh,
                dry_run=False,  # Already handled dry_run above
            )

            total_signals += n
            logger.info(f"  Generated {n} signal records")

            # Update state (unless dry_run, but we handled that already)
            if not args.dry_run:
                rows_updated = state_manager.update_state_after_generation(
                    signal_table="cmc_signals_ema_crossover",
                    signal_id=config["signal_id"],
                )
                logger.debug(f"  Updated {rows_updated} state rows")

        logger.info(f"\nTotal: {total_signals} signal records generated")
        return 0

    except Exception as e:
        logger.error(f"Error generating signals: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
