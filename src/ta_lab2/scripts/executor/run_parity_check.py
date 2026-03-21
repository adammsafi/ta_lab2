#!/usr/bin/env python
"""
Backtest parity verification report.

Compares paper executor replay fills against stored backtest results.
Prerequisite: Run executor in replay mode first:
    python -m ta_lab2.scripts.executor.run_paper_executor --replay-historical \\
        --start 2024-01-01 --end 2025-01-01

Usage:
    python -m ta_lab2.scripts.executor.run_parity_check \\
        --signal-id 1 --start 2024-01-01 --end 2025-01-01

    python -m ta_lab2.scripts.executor.run_parity_check \\
        --signal-id 1 --start 2024-01-01 --end 2025-01-01 --verbose

Exit codes:
    0  Parity check PASSED
    1  Parity check FAILED (or error)
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.executor.parity_checker import ParityChecker

logger = logging.getLogger(__name__)


def _resolve_db_url(db_url: str | None) -> str:
    """Resolve database URL from argument or environment."""
    if db_url:
        return db_url

    import os

    url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url

    # Try reading from db_config.env
    config_path = "db_config.env"
    if os.path.exists(config_path):
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("TARGET_DB_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    raise ValueError(
        "Database URL not found. Provide --db-url or set TARGET_DB_URL env var."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_parity_check",
        description=(
            "Backtest parity verification: compare executor replay fills "
            "against stored backtest trades."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--signal-id",
        type=int,
        required=True,
        help="Signal ID to compare (must match backtest_runs.signal_id).",
    )
    parser.add_argument(
        "--config-id",
        type=int,
        default=None,
        help="Executor config ID (optional; used for labelling only).",
    )
    parser.add_argument(
        "--start",
        required=True,
        metavar="DATE",
        help="Start date inclusive (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end",
        required=True,
        metavar="DATE",
        help="End date inclusive (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--slippage-mode",
        default="zero",
        choices=["zero", "fixed", "lognormal"],
        help=(
            "Expected slippage mode. 'zero' requires exact fill price match "
            "(<1 bps); 'fixed'/'lognormal' requires P&L correlation >= 0.99. "
            "Default: zero."
        ),
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (overrides TARGET_DB_URL env var).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-trade price comparison detail.",
    )
    return parser


def _print_verbose_comparison(
    bt_trades: list[dict],
    exec_fills: list[dict],
) -> None:
    """Print per-trade price comparison table."""
    if not bt_trades or not exec_fills:
        print("\n[verbose] No trade data to compare.")
        return

    print("\n[verbose] Per-trade price comparison:")
    header = f"{'#':>4}  {'BT Entry Price':>16}  {'Exec Fill Price':>16}  {'Divergence (bps)':>18}"
    print(header)
    print("-" * len(header))

    for i, (bt, ex) in enumerate(zip(bt_trades, exec_fills), start=1):
        bt_price = float(bt.get("entry_price") or 0)
        ex_price = float(ex.get("fill_price") or 0)
        if bt_price > 0:
            bps = abs(ex_price - bt_price) / bt_price * 10_000
        else:
            bps = float("nan")
        print(f"{i:>4}  {bt_price:>16.4f}  {ex_price:>16.4f}  {bps:>18.4f}")


def main() -> int:
    """Run parity check. Returns 0 on PASS, 1 on FAIL."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args()

    try:
        db_url = _resolve_db_url(args.db_url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    engine = create_engine(db_url, poolclass=NullPool)

    checker = ParityChecker(engine)

    try:
        report = checker.check(
            config_id=args.config_id,
            signal_id=args.signal_id,
            start_date=args.start,
            end_date=args.end,
            slippage_mode=args.slippage_mode,
        )
    except Exception as exc:
        logger.exception("Parity check failed with error")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Print formatted report
    print(checker.format_report(report))

    # Verbose: per-trade comparison
    if args.verbose:
        try:
            bt_trades = checker._load_backtest_trades(
                args.signal_id, args.start, args.end
            )
            exec_fills = checker._load_executor_fills(
                args.signal_id, args.start, args.end
            )
            _print_verbose_comparison(bt_trades, exec_fills)
        except Exception as exc:
            logger.warning("Could not load per-trade data for verbose output: %s", exc)

    return 0 if report.get("parity_pass") else 1


if __name__ == "__main__":
    sys.exit(main())
