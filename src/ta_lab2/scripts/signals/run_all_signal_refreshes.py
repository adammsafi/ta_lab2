#!/usr/bin/env python
"""
Orchestrated signal generation pipeline.

Runs all signal types (EMA crossover, RSI mean revert, ATR breakout) in parallel,
then validates reproducibility of backtest results.

This script provides the complete signal refresh workflow:
1. Phase 1: Signal generation (parallel execution of all 3 types)
2. Phase 2: Reproducibility validation (verify backtest determinism)

Usage:
    python run_all_signal_refreshes.py
    python run_all_signal_refreshes.py --full-refresh
    python run_all_signal_refreshes.py --validate-only
    python run_all_signal_refreshes.py --skip-validation
    python run_all_signal_refreshes.py --fail-fast

The default behavior is to continue when one signal type fails (partial failure
handling). Use --fail-fast to exit immediately on first failure.
"""

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine, text

from ta_lab2.scripts.signals import SignalStateManager, SignalStateConfig, load_active_signals
from ta_lab2.scripts.signals.generate_signals_ema import EMASignalGenerator
from ta_lab2.scripts.signals.generate_signals_rsi import RSISignalGenerator
from ta_lab2.scripts.signals.generate_signals_atr import ATRSignalGenerator
from ta_lab2.scripts.signals.validate_reproducibility import validate_backtest_reproducibility
from ta_lab2.scripts.backtests import SignalBacktester
from ta_lab2.backtests.costs import CostModel

logger = logging.getLogger(__name__)


@dataclass
class RefreshResult:
    """
    Result from refreshing a single signal type.

    Tracks success/failure, signal count, and execution duration for reporting.
    """
    signal_type: str
    signals_generated: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None

    def __str__(self) -> str:
        """Human-readable result string."""
        status = "OK" if self.success else f"FAILED: {self.error}"
        return (
            f"{self.signal_type}: {self.signals_generated} signals "
            f"in {self.duration_seconds:.1f}s [{status}]"
        )


def refresh_signal_type(
    engine,
    signal_type: str,
    ids: list[int],
    full_refresh: bool,
) -> RefreshResult:
    """
    Refresh a single signal type.

    Catches exceptions to allow partial failure handling. When one signal type
    fails, the others can continue processing.

    Args:
        engine: SQLAlchemy engine for database operations
        signal_type: 'ema_crossover', 'rsi_mean_revert', or 'atr_breakout'
        ids: List of asset IDs to process
        full_refresh: If True, regenerate all signals. If False, incremental.

    Returns:
        RefreshResult with success status and metrics
    """
    start = datetime.now()

    try:
        logger.info(f"Starting refresh for {signal_type}...")

        # Initialize state manager
        config = SignalStateConfig(signal_type=signal_type)
        state_manager = SignalStateManager(engine, config)
        state_manager.ensure_state_table()

        # Select generator based on type
        generators = {
            'ema_crossover': EMASignalGenerator,
            'rsi_mean_revert': RSISignalGenerator,
            'atr_breakout': ATRSignalGenerator,
        }

        if signal_type not in generators:
            raise ValueError(f"Unknown signal type: {signal_type}")

        generator = generators[signal_type](engine, state_manager)
        configs = load_active_signals(engine, signal_type)

        logger.info(f"  Found {len(configs)} active signal configurations")

        # Generate signals for all active configs
        total_signals = 0
        for cfg in configs:
            logger.debug(f"  Processing config: {cfg['signal_name']}")
            n = generator.generate_for_ids(ids, cfg, full_refresh=full_refresh)
            total_signals += n
            logger.debug(f"    Generated {n} signals")

        duration = (datetime.now() - start).total_seconds()
        logger.info(f"✓ {signal_type} complete: {total_signals} signals in {duration:.1f}s")

        return RefreshResult(signal_type, total_signals, duration, True)

    except Exception as e:
        duration = (datetime.now() - start).total_seconds()
        logger.error(f"✗ {signal_type} FAILED after {duration:.1f}s: {e}", exc_info=True)
        return RefreshResult(signal_type, 0, duration, False, str(e))


def run_parallel_refresh(
    engine,
    ids: list[int],
    full_refresh: bool,
    max_workers: int = 3,
) -> List[RefreshResult]:
    """
    Run all signal types in parallel.

    Partial failure handling: Each signal type runs independently in a separate
    thread. One failure does not stop the others. This is the default behavior.

    Use --fail-fast flag in CLI to change this behavior and exit immediately
    on first failure.

    Args:
        engine: SQLAlchemy engine for database operations
        ids: List of asset IDs to process
        full_refresh: If True, regenerate all signals
        max_workers: Maximum concurrent threads (default 3 = one per signal type)

    Returns:
        List of RefreshResult for each signal type
    """
    signal_types = ['ema_crossover', 'rsi_mean_revert', 'atr_breakout']
    results = []

    logger.info(f"Starting parallel refresh of {len(signal_types)} signal types...")
    logger.info(f"  Max workers: {max_workers}")
    logger.info(f"  Full refresh: {full_refresh}")
    logger.info(f"  Asset count: {len(ids)}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {
            executor.submit(refresh_signal_type, engine, st, ids, full_refresh): st
            for st in signal_types
        }

        # Collect results as they complete
        for future in as_completed(futures):
            signal_type = futures[future]
            try:
                result = future.result()
                results.append(result)
                logger.info(f"  Completed: {result}")
            except Exception as e:
                # Should not happen (refresh_signal_type catches exceptions)
                # but handle defensively
                logger.error(f"  Unexpected error for {signal_type}: {e}")
                results.append(RefreshResult(signal_type, 0, 0, False, str(e)))

    return results


def validate_pipeline_reproducibility(
    engine,
    sample_asset_id: int,
    sample_start: pd.Timestamp,
    sample_end: pd.Timestamp,
) -> bool:
    """
    Validate reproducibility for all signal types.

    Uses a sample asset and date range for validation. Runs backtest twice
    for each signal type and verifies identical results.

    Args:
        engine: SQLAlchemy engine for database operations
        sample_asset_id: Asset ID to use for validation
        sample_start: Start timestamp for validation backtest
        sample_end: End timestamp for validation backtest

    Returns:
        True if all signal types pass reproducibility validation, False otherwise
    """
    logger.info("Starting reproducibility validation...")
    logger.info(f"  Sample asset: {sample_asset_id}")
    logger.info(f"  Date range: {sample_start} to {sample_end}")

    cost_model = CostModel()  # Clean mode for validation (no costs)
    backtester = SignalBacktester(engine, cost_model)

    all_pass = True
    validation_count = 0

    for signal_type in ['ema_crossover', 'rsi_mean_revert', 'atr_breakout']:
        configs = load_active_signals(engine, signal_type)

        if not configs:
            logger.warning(f"  No active configs for {signal_type}, skipping")
            continue

        for cfg in configs:
            validation_count += 1
            signal_name = cfg['signal_name']
            signal_id = cfg['signal_id']

            logger.info(f"  Validating: {signal_type}/{signal_name}")

            try:
                report = validate_backtest_reproducibility(
                    backtester,
                    signal_type,
                    signal_id,
                    sample_asset_id,
                    sample_start,
                    sample_end,
                    strict=False,  # Warn mode for validation
                )

                if not report.is_reproducible:
                    logger.error(f"    ✗ FAILED: {signal_type}/{signal_name}")
                    for diff in report.differences:
                        logger.error(f"      - {diff}")
                    all_pass = False
                else:
                    logger.info(f"    ✓ OK: {signal_type}/{signal_name}")

            except Exception as e:
                logger.error(f"    ✗ ERROR: {signal_type}/{signal_name}: {e}")
                all_pass = False

    if validation_count == 0:
        logger.warning("No signals to validate (no active configs or no signals generated)")
        return True

    return all_pass


def _get_all_asset_ids(engine) -> list[int]:
    """
    Query all asset IDs from cmc_daily_features.

    Returns:
        Sorted list of unique asset IDs
    """
    sql = text("""
        SELECT DISTINCT id
        FROM public.cmc_daily_features
        ORDER BY id
    """)

    with engine.connect() as conn:
        result = conn.execute(sql)
        rows = result.fetchall()
        return [row[0] for row in rows]


def main():
    """
    Main entry point for orchestrated signal pipeline.

    Parses CLI arguments, runs signal generation (Phase 1), and optionally
    validates reproducibility (Phase 2).

    Returns:
        Exit code: 0 on success, 1 on failure
    """
    parser = argparse.ArgumentParser(
        description='Orchestrated signal generation pipeline with reproducibility validation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default: incremental refresh + validation
  python run_all_signal_refreshes.py

  # Full refresh (regenerate all signals)
  python run_all_signal_refreshes.py --full-refresh

  # Only validate (skip signal generation)
  python run_all_signal_refreshes.py --validate-only

  # Skip validation (only generate signals)
  python run_all_signal_refreshes.py --skip-validation

  # Exit on first failure (default: continue with partial results)
  python run_all_signal_refreshes.py --fail-fast

  # Specific assets with verbose logging
  python run_all_signal_refreshes.py --ids 1 2 3 --verbose
        """
    )

    parser.add_argument(
        '--ids',
        type=int,
        nargs='+',
        help='Asset IDs to process (default: all assets from cmc_daily_features)'
    )
    parser.add_argument(
        '--full-refresh',
        action='store_true',
        help='Regenerate all signals (default: incremental refresh)'
    )
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Skip signal generation, only run reproducibility validation'
    )
    parser.add_argument(
        '--skip-validation',
        action='store_true',
        help='Skip reproducibility validation after signal generation'
    )
    parser.add_argument(
        '--fail-fast',
        action='store_true',
        help='Exit immediately on first signal type failure (default: continue with partial results)'
    )
    parser.add_argument(
        '--parallel',
        type=int,
        default=3,
        help='Max parallel workers (default: 3)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose (DEBUG-level) logging'
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger.info("=" * 70)
    logger.info("Orchestrated Signal Pipeline")
    logger.info("=" * 70)

    # Check for database URL
    db_url = os.environ.get('TARGET_DB_URL')
    if not db_url:
        logger.error("TARGET_DB_URL environment variable not set")
        return 1

    engine = create_engine(db_url)

    # Get asset IDs
    if args.ids:
        ids = args.ids
        logger.info(f"Processing {len(ids)} specified assets")
    else:
        ids = _get_all_asset_ids(engine)
        logger.info(f"Processing all {len(ids)} assets from database")

    if not ids:
        logger.error("No asset IDs to process")
        return 1

    # Phase 1: Signal generation (unless validate-only)
    if not args.validate_only:
        logger.info("")
        logger.info("PHASE 1: Signal Generation")
        logger.info("-" * 70)

        results = run_parallel_refresh(engine, ids, args.full_refresh, args.parallel)

        logger.info("")
        logger.info("Phase 1 Results:")
        for r in results:
            status_symbol = "✓" if r.success else "✗"
            logger.info(f"  {status_symbol} {r}")

        # Check for failures
        failed = [r for r in results if not r.success]
        succeeded = [r for r in results if r.success]

        if failed:
            logger.warning("")
            logger.warning(f"{len(failed)} signal type(s) FAILED, {len(succeeded)} succeeded")
            for r in failed:
                logger.error(f"  FAILED: {r.signal_type} - {r.error}")

            if args.fail_fast:
                logger.error("")
                logger.error("--fail-fast enabled, exiting")
                return 1
            else:
                logger.info("")
                logger.info("Continuing with partial results (default behavior)")
                logger.info("Use --fail-fast to exit on first failure")

    # Phase 2: Reproducibility validation (unless skipped)
    if not args.skip_validation:
        logger.info("")
        logger.info("PHASE 2: Reproducibility Validation")
        logger.info("-" * 70)

        # Select sample asset (first ID)
        sample_asset = ids[0]

        # Use recent date range for validation (1 year)
        sample_end = pd.Timestamp.now(tz='UTC').normalize()
        sample_start = sample_end - pd.Timedelta(days=365)

        logger.info(f"Using sample asset {sample_asset} for validation")

        validation_passed = validate_pipeline_reproducibility(
            engine, sample_asset, sample_start, sample_end
        )

        logger.info("")
        if validation_passed:
            logger.info("✓ Reproducibility validation PASSED")
        else:
            logger.error("✗ Reproducibility validation FAILED")
            logger.error("Some backtests produced different results on reruns")
            return 1

    # Success
    logger.info("")
    logger.info("=" * 70)
    logger.info("Signal pipeline complete")
    logger.info("=" * 70)

    return 0


if __name__ == '__main__':
    sys.exit(main())
