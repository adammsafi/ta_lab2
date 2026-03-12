#!/usr/bin/env python
"""
Refresh ATR breakout signals from features.

This script generates ATR breakout signals using Donchian channels with ATR confirmation.
Signals are stored in signals_atr_breakout with full feature snapshot for reproducibility.

Usage:
    # Generate signals for all assets and all active ATR breakout signals
    python refresh_signals_atr_breakout.py

    # Generate for specific assets
    python refresh_signals_atr_breakout.py --ids 1 52 825

    # Generate for specific signal_id from dim_signals
    python refresh_signals_atr_breakout.py --signal-id 6

    # Full refresh (regenerate all signals)
    python refresh_signals_atr_breakout.py --full-refresh

    # Dry run (don't write to database)
    python refresh_signals_atr_breakout.py --dry-run

    # Verbose logging
    python refresh_signals_atr_breakout.py --verbose

Environment:
    TARGET_DB_URL: Database connection string (required)

Signal Configuration:
    Loads active signal configurations from dim_signals where:
    - signal_type = 'atr_breakout'
    - is_active = TRUE

    Example dim_signals params:
    {
        "lookback": 20,
        "atr_col": "atr_14",
        "trail_atr_mult": 2.0,
        "confirm_close": true,
        "exit_on_channel_crossback": true,
        "use_trailing_atr_stop": true
    }
"""

import argparse
import logging
import os
import sys
from sqlalchemy import create_engine, text

from ta_lab2.scripts.signals import (
    SignalStateManager,
    SignalStateConfig,
    load_active_signals,
)
from ta_lab2.scripts.signals.generate_signals_atr import ATRSignalGenerator


def _get_all_asset_ids(engine) -> list[int]:
    """
    Query all active asset IDs from features.

    Returns:
        List of unique asset IDs with feature data
    """
    sql = text(
        """
        SELECT DISTINCT id
        FROM public.features
        WHERE tf = '1D'
        ORDER BY id
    """
    )

    with engine.connect() as conn:
        result = conn.execute(sql)
        return [row[0] for row in result.fetchall()]


def main():
    """Main entry point for ATR breakout signal refresh."""
    parser = argparse.ArgumentParser(
        description="Refresh ATR breakout signals from features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--ids",
        type=int,
        nargs="+",
        help="Asset IDs to generate signals for (default: all assets with features)",
    )

    parser.add_argument(
        "--signal-id",
        type=int,
        help="Specific signal_id from dim_signals to generate (default: all active)",
    )

    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Regenerate all signals (default: incremental based on state)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate generation without writing to database",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--no-regime",
        action="store_true",
        help="Disable regime context (A/B comparison mode: signals generated without regime sizing)",
    )
    parser.add_argument(
        "--cusum",
        action="store_true",
        help="Enable symmetric CUSUM pre-filter (AFML Ch.17). "
        "Reduces signal count by retaining only statistically significant event bars.",
    )
    parser.add_argument(
        "--cusum-multiplier",
        type=float,
        default=2.0,
        metavar="MULT",
        help="EWM-vol multiplier for CUSUM threshold calibration (default: 2.0). "
        "Higher = stricter filter = fewer events.",
    )
    parser.add_argument(
        "--stop-ladder",
        action="store_true",
        default=False,
        help="Enable stop-ladder exit signals (PORT-05). "
        "Checks multi-tier SL/TP levels from configs/portfolio.yaml "
        "for each open position during signal generation.",
    )
    parser.add_argument(
        "--no-stop-ladder",
        dest="stop_ladder",
        action="store_false",
        help="Disable stop-ladder exit signals (default).",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    # Check environment
    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        logger.error("TARGET_DB_URL environment variable not set")
        sys.exit(1)

    # Create database engine
    try:
        engine = create_engine(db_url)
        logger.info(f"Connected to database: {db_url.split('@')[-1]}")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)

    # Initialize state manager
    config = SignalStateConfig(signal_type="atr_breakout")
    state_manager = SignalStateManager(engine, config)

    try:
        state_manager.ensure_state_table()
        logger.debug("State table ensured")
    except Exception as e:
        logger.error(f"Failed to ensure state table: {e}")
        sys.exit(1)

    # Load signal configurations from dim_signals
    try:
        if args.signal_id:
            configs = [
                c
                for c in load_active_signals(engine, "atr_breakout")
                if c["signal_id"] == args.signal_id
            ]
            if not configs:
                logger.error(f"No active signal found with signal_id={args.signal_id}")
                sys.exit(1)
        else:
            configs = load_active_signals(engine, "atr_breakout")

        if not configs:
            logger.warning("No active ATR breakout signals found in dim_signals")
            sys.exit(0)

        logger.info(f"Loaded {len(configs)} active ATR breakout signal(s)")
        for cfg in configs:
            logger.debug(f"  - {cfg['signal_name']} (signal_id={cfg['signal_id']})")

    except Exception as e:
        logger.error(f"Failed to load signal configurations: {e}")
        sys.exit(1)

    # Get asset IDs
    try:
        if args.ids:
            ids = args.ids
            logger.info(f"Processing {len(ids)} specified asset(s)")
        else:
            ids = _get_all_asset_ids(engine)
            logger.info(f"Processing all {len(ids)} asset(s) with features")

    except Exception as e:
        logger.error(f"Failed to load asset IDs: {e}")
        sys.exit(1)

    # Regime context mode
    regime_enabled = not args.no_regime
    if not regime_enabled:
        logger.info(
            "Regime context DISABLED (--no-regime mode): signals use base sizing"
        )
    else:
        logger.info("Regime context ENABLED: signals will use regime-adjusted sizing")

    # CUSUM filter mode
    cusum_enabled = args.cusum
    cusum_multiplier = args.cusum_multiplier
    if cusum_enabled:
        logger.info(
            f"CUSUM pre-filter ENABLED (multiplier={cusum_multiplier}): "
            "only significant event bars will generate signals"
        )
    else:
        logger.info("CUSUM pre-filter DISABLED (default mode)")

    # Stop ladder mode
    stop_ladder_enabled = args.stop_ladder
    if stop_ladder_enabled:
        logger.info("Stop ladder ENABLED: multi-tier SL/TP exits from portfolio.yaml")
    else:
        logger.info("Stop ladder DISABLED (default mode)")

    # Generate signals
    generator = ATRSignalGenerator(engine, state_manager)
    total_signals = 0

    for signal_config in configs:
        signal_id = signal_config["signal_id"]
        signal_name = signal_config["signal_name"]

        logger.info(f"Processing signal: {signal_name} (id={signal_id})")
        logger.debug(f"  Parameters: {signal_config['params']}")

        try:
            n = generator.generate_for_ids(
                ids=ids,
                signal_config=signal_config,
                full_refresh=args.full_refresh,
                dry_run=args.dry_run,
                regime_enabled=regime_enabled,
                cusum_enabled=cusum_enabled,
                cusum_threshold_multiplier=cusum_multiplier,
                stop_ladder_enabled=stop_ladder_enabled,
            )

            total_signals += n
            logger.info(f"  Generated {n} signal record(s)")

        except Exception as e:
            logger.error(f"  Failed to generate signals for {signal_name}: {e}")
            if args.verbose:
                logger.exception("Exception details:")
            continue

    # Summary
    cusum_mode = f"CUSUM(mult={cusum_multiplier})" if cusum_enabled else "NO_CUSUM"
    sl_mode = "STOP_LADDER" if stop_ladder_enabled else "NO_STOP_LADDER"
    logger.info("=" * 60)
    logger.info(f"Total: {total_signals} ATR breakout signal(s) generated")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info(f"Refresh: {'FULL' if args.full_refresh else 'INCREMENTAL'}")
    logger.info(f"CUSUM: {cusum_mode}")
    logger.info(f"Stop ladder: {sl_mode}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
