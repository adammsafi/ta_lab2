#!/usr/bin/env python
"""
Run backtests from stored signals in database.

This script loads signals from cmc_signals_* tables and executes backtests
using vectorbt via the SignalBacktester class.

Supports:
- Clean PnL mode (no fees/slippage)
- Realistic PnL mode (with configurable fees/slippage)
- Database result storage
- JSON output export

Example usage:
    # Clean mode (no costs)
    python run_backtest_signals.py \\
        --signal-type ema_crossover \\
        --signal-id 1 \\
        --asset-id 1 \\
        --start 2023-01-01 \\
        --end 2023-12-31 \\
        --clean-pnl

    # Realistic mode with custom fees
    python run_backtest_signals.py \\
        --signal-type rsi_mean_revert \\
        --signal-id 2 \\
        --asset-id 1 \\
        --start 2023-01-01 \\
        --end 2023-12-31 \\
        --fee-bps 10 \\
        --slippage-bps 5 \\
        --save-results

    # With JSON output
    python run_backtest_signals.py \\
        --signal-type atr_breakout \\
        --signal-id 3 \\
        --asset-id 1 \\
        --start 2023-01-01 \\
        --end 2023-12-31 \\
        --save-results \\
        --output-json results.json
"""

import argparse
import logging
import os
import sys
import json
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine

from ta_lab2.backtests.costs import CostModel
from ta_lab2.scripts.backtests import SignalBacktester


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging with optional verbose mode."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Run backtests from stored signals in database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Required arguments
    parser.add_argument(
        '--signal-type',
        required=True,
        choices=['ema_crossover', 'rsi_mean_revert', 'atr_breakout'],
        help='Signal type to backtest'
    )
    parser.add_argument(
        '--signal-id',
        type=int,
        required=True,
        help='Signal ID from dim_signals table'
    )
    parser.add_argument(
        '--asset-id',
        type=int,
        required=True,
        help='Asset ID to backtest'
    )
    parser.add_argument(
        '--start',
        type=str,
        required=True,
        help='Start date (YYYY-MM-DD format)'
    )
    parser.add_argument(
        '--end',
        type=str,
        required=True,
        help='End date (YYYY-MM-DD format)'
    )

    # Cost model options
    cost_group = parser.add_argument_group('Cost Model Options')
    cost_group.add_argument(
        '--clean-pnl',
        action='store_true',
        help='Ignore fees/slippage (clean mode for theoretical PnL)'
    )
    cost_group.add_argument(
        '--fee-bps',
        type=float,
        default=10.0,
        help='Commission in basis points (default: 10.0 = 0.10%%)'
    )
    cost_group.add_argument(
        '--slippage-bps',
        type=float,
        default=5.0,
        help='Slippage in basis points (default: 5.0 = 0.05%%)'
    )
    cost_group.add_argument(
        '--funding-bps',
        type=float,
        default=0.0,
        help='Daily funding cost in basis points (default: 0.0, for perps)'
    )

    # Output options
    output_group = parser.add_argument_group('Output Options')
    output_group.add_argument(
        '--save-results',
        action='store_true',
        help='Store results in database (cmc_backtest_* tables)'
    )
    output_group.add_argument(
        '--output-json',
        type=str,
        metavar='PATH',
        help='Write results to JSON file at specified path'
    )
    output_group.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging (DEBUG level)'
    )

    return parser.parse_args()


def format_results_for_console(result) -> str:
    """Format backtest results for console output."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"Backtest Results: {result.signal_type}/{result.signal_id}")
    lines.append("=" * 70)
    lines.append(f"Asset ID:        {result.asset_id}")
    lines.append(f"Date Range:      {result.start_ts.date()} to {result.end_ts.date()}")
    lines.append(f"Run ID:          {result.run_id}")
    lines.append("")
    lines.append("Performance Metrics:")
    lines.append("-" * 70)
    lines.append(f"  Total Return:  {result.total_return:>10.2%}")
    lines.append(f"  CAGR:          {result.metrics.get('cagr', 0):>10.2%}")
    lines.append(f"  Sharpe Ratio:  {result.sharpe_ratio:>10.2f}")
    lines.append(f"  Sortino Ratio: {result.metrics.get('sortino_ratio', 0) or 0:>10.2f}")
    lines.append(f"  Calmar Ratio:  {result.metrics.get('calmar_ratio', 0):>10.2f}")
    lines.append(f"  Max Drawdown:  {result.max_drawdown:>10.2%}")
    lines.append("")
    lines.append("Trade Statistics:")
    lines.append("-" * 70)
    lines.append(f"  Trade Count:   {result.trade_count:>10}")
    lines.append(f"  Win Rate:      {result.metrics.get('win_rate', 0) or 0:>10.1f}%")
    lines.append(f"  Profit Factor: {result.metrics.get('profit_factor', 0) or 0:>10.2f}")
    lines.append(f"  Avg Win:       {result.metrics.get('avg_win', 0) or 0:>10.2f}%")
    lines.append(f"  Avg Loss:      {result.metrics.get('avg_loss', 0) or 0:>10.2f}%")
    lines.append(f"  Avg Hold (d):  {result.metrics.get('avg_holding_period_days', 0) or 0:>10.1f}")
    lines.append("")
    lines.append("Risk Metrics:")
    lines.append("-" * 70)
    lines.append(f"  VaR 95%:       {result.metrics.get('var_95', 0) or 0:>10.4f}")
    lines.append(f"  CVaR:          {result.metrics.get('expected_shortfall', 0) or 0:>10.4f}")
    lines.append("")
    lines.append("Cost Model:")
    lines.append("-" * 70)
    lines.append(f"  Fee (bps):     {result.cost_model['fee_bps']:>10.2f}")
    lines.append(f"  Slippage (bps):{result.cost_model['slippage_bps']:>10.2f}")
    lines.append(f"  Funding (bps): {result.cost_model['funding_bps_day']:>10.2f}")
    lines.append("=" * 70)

    return "\n".join(lines)


def convert_result_to_json_serializable(result) -> dict:
    """Convert BacktestResult to JSON-serializable dictionary."""
    return {
        'run_id': result.run_id,
        'signal_type': result.signal_type,
        'signal_id': result.signal_id,
        'asset_id': result.asset_id,
        'start_ts': result.start_ts.isoformat(),
        'end_ts': result.end_ts.isoformat(),
        'total_return': float(result.total_return),
        'sharpe_ratio': float(result.sharpe_ratio),
        'max_drawdown': float(result.max_drawdown),
        'trade_count': int(result.trade_count),
        'cost_model': result.cost_model,
        'signal_params_hash': result.signal_params_hash,
        'feature_hash': result.feature_hash,
        'signal_version': result.signal_version,
        'vbt_version': result.vbt_version,
        'metrics': {
            k: float(v) if v is not None and not isinstance(v, int) else v
            for k, v in result.metrics.items()
        },
        'trades': result.trades_df.to_dict(orient='records') if not result.trades_df.empty else [],
    }


def main():
    """Main entry point for backtest CLI."""
    args = parse_args()
    logger = setup_logging(args.verbose)

    # Check database URL
    db_url = os.environ.get('TARGET_DB_URL')
    if not db_url:
        logger.error("TARGET_DB_URL environment variable not set")
        sys.exit(1)

    # Create database engine
    try:
        engine = create_engine(db_url)
        logger.debug(f"Connected to database: {db_url.split('@')[-1]}")  # Hide credentials
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)

    # Parse dates
    try:
        start_ts = pd.Timestamp(args.start, tz='UTC')
        end_ts = pd.Timestamp(args.end, tz='UTC')
    except Exception as e:
        logger.error(f"Invalid date format: {e}")
        logger.error("Dates must be in YYYY-MM-DD format")
        sys.exit(1)

    # Create cost model
    cost_model = CostModel(
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        funding_bps_day=args.funding_bps,
    )

    if args.clean_pnl:
        logger.info("Running in CLEAN mode (no fees/slippage)")
    else:
        logger.info(f"Running in REALISTIC mode: {cost_model.describe()}")

    # Create backtester
    backtester = SignalBacktester(engine, cost_model)

    # Run backtest
    try:
        result = backtester.run_backtest(
            signal_type=args.signal_type,
            signal_id=args.signal_id,
            asset_id=args.asset_id,
            start_ts=start_ts,
            end_ts=end_ts,
            clean_mode=args.clean_pnl,
        )
    except Exception as e:
        logger.error(f"Backtest execution failed: {e}")
        if args.verbose:
            logger.exception("Full traceback:")
        sys.exit(1)

    # Print results to console
    print(format_results_for_console(result))

    # Save to database if requested
    if args.save_results:
        try:
            run_id = backtester.save_backtest_results(result)
            logger.info(f"Results saved to database with run_id: {run_id}")
        except Exception as e:
            logger.error(f"Failed to save results to database: {e}")
            if args.verbose:
                logger.exception("Full traceback:")
            sys.exit(1)

    # Export to JSON if requested
    if args.output_json:
        try:
            json_data = convert_result_to_json_serializable(result)
            with open(args.output_json, 'w') as f:
                json.dump(json_data, f, indent=2)
            logger.info(f"Results exported to JSON: {args.output_json}")
        except Exception as e:
            logger.error(f"Failed to export JSON: {e}")
            if args.verbose:
                logger.exception("Full traceback:")
            sys.exit(1)

    logger.info("Backtest complete")
    sys.exit(0)


if __name__ == '__main__':
    main()
