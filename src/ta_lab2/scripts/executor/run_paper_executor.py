#!/usr/bin/env python
"""
Paper-trade executor CLI.

Reads signals for active strategies, generates paper orders, simulates fills,
and updates positions. Runs for all active configs in dim_executor_config.

Usage:
    # Standard run (process new signals for all active strategies)
    python -m ta_lab2.scripts.executor.run_paper_executor

    # Dry run (log decisions without writing to DB)
    python -m ta_lab2.scripts.executor.run_paper_executor --dry-run

    # Replay historical signals for backtest parity check
    python -m ta_lab2.scripts.executor.run_paper_executor --replay-historical --start 2024-01-01 --end 2025-01-01

    # Verbose output
    python -m ta_lab2.scripts.executor.run_paper_executor --verbose
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.refresh_utils import resolve_db_url


def _configure_logging(verbose: bool) -> None:
    """Configure logging based on verbosity flag."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _print_summary(summary: dict) -> None:
    """Print run summary to stdout."""
    print(f"\n{'=' * 60}")
    print("PAPER EXECUTOR SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Status              : {summary.get('status', 'unknown')}")
    print(f"  Strategies processed: {summary.get('strategies_processed', 0)}")
    print(f"  Total signals       : {summary.get('total_signals', 0)}")
    print(f"  Total orders        : {summary.get('total_orders', 0)}")
    print(f"  Total fills         : {summary.get('total_fills', 0)}")
    print(f"  Total skipped       : {summary.get('total_skipped', 0)}")

    errors = summary.get("errors", [])
    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for err in errors:
            print(f"    - {err.get('config', '?')}: {err.get('error', '?')}")

    print(f"{'=' * 60}")


def main(argv: list[str] | None = None) -> int:
    """Main entry point for paper executor CLI."""
    p = argparse.ArgumentParser(
        description=(
            "Run paper trade executor for all active strategies. "
            "Reads signals, generates paper orders, simulates fills, "
            "and updates positions."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard daily run
  python -m ta_lab2.scripts.executor.run_paper_executor

  # Dry run (log decisions, no DB writes)
  python -m ta_lab2.scripts.executor.run_paper_executor --dry-run

  # Replay historical signals
  python -m ta_lab2.scripts.executor.run_paper_executor --replay-historical --start 2024-01-01 --end 2025-01-01

  # Verbose output
  python -m ta_lab2.scripts.executor.run_paper_executor --verbose
        """,
    )

    p.add_argument(
        "--db-url",
        help="Database URL (default: from config/env via resolve_db_url)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log decisions without writing to DB (no orders, fills, or position updates)",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose/debug logging output",
    )
    p.add_argument(
        "--replay-historical",
        action="store_true",
        help=(
            "Replay mode: skip freshness check and process all unprocessed signals "
            "regardless of age. Useful for backtest parity checks."
        ),
    )
    p.add_argument(
        "--start",
        metavar="DATE",
        help=(
            "Start date for replay mode (ISO format, e.g. 2024-01-01). "
            "Required with --replay-historical when filtering by date range."
        ),
    )
    p.add_argument(
        "--end",
        metavar="DATE",
        help=(
            "End date for replay mode (ISO format, e.g. 2025-01-01). "
            "Required with --replay-historical when filtering by date range."
        ),
    )

    args = p.parse_args(argv)

    # Validate replay args
    if (args.start or args.end) and not args.replay_historical:
        p.error("--start/--end require --replay-historical")

    _configure_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Resolve DB URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("[DRY RUN] Paper executor: no DB writes will occur")

    # Create engine with NullPool (project convention for subprocess workers)
    engine = create_engine(db_url, poolclass=NullPool)

    try:
        # Import here to avoid heavy imports at CLI parse time
        from ta_lab2.executor.paper_executor import PaperExecutor  # noqa: PLC0415

        executor = PaperExecutor(engine)

        logger.info(
            "PaperExecutor CLI: starting run (dry_run=%s, replay_historical=%s)",
            args.dry_run,
            args.replay_historical,
        )

        summary = executor.run(
            dry_run=args.dry_run,
            replay_historical=args.replay_historical,
            replay_start=args.start,
            replay_end=args.end,
        )

        _print_summary(summary)

        status = summary.get("status", "failed")
        if status in ("success", "no_configs", "no_signals"):
            return 0
        elif status == "partial_failure":
            logger.warning(
                "PaperExecutor CLI: partial failure (some strategies failed)"
            )
            return 1
        else:
            logger.error("PaperExecutor CLI: run failed with status=%s", status)
            return 1

    except Exception as exc:  # noqa: BLE001
        logger.exception("PaperExecutor CLI: unexpected error: %s", exc)
        print(f"[ERROR] PaperExecutor failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
