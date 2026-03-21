#!/usr/bin/env python
"""Daily drift monitor -- run parallel backtest replay and compute drift metrics.

Compares paper executor P&L against backtest replays for all active strategies.
Writes drift metrics to drift_metrics and activates drift pause when
threshold breaches are detected.

Usage:
    python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start 2025-01-01
    python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start 2025-01-01 --dry-run --verbose
    python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start 2025-01-01 --db-url postgresql://...
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


def _print_summary(metrics_list: list, dry_run: bool) -> None:
    """Print drift monitor run summary."""
    print(f"\n{'=' * 60}")
    print("DRIFT MONITOR SUMMARY")
    print(f"{'=' * 60}")

    if dry_run:
        print("  Mode                : DRY RUN (no DB writes)")

    n_configs = len(metrics_list)
    n_breaches = sum(
        1
        for m in metrics_list
        if getattr(m, "te_breach", False) or getattr(m, "drift_paused", False)
    )
    n_paused = sum(1 for m in metrics_list if getattr(m, "drift_paused", False))

    print(f"  Configs checked     : {n_configs}")
    print(f"  Threshold breaches  : {n_breaches}")
    print(f"  Drift paused        : {n_paused}")

    if n_paused > 0:
        print("\n  [WARNING] Drift pause is ACTIVE for some strategies")
        print("  Review cmc_drift_pause table and v_drift_summary view")

    print(f"{'=' * 60}")


def main(argv: list[str] | None = None) -> int:
    """Main entry point for drift monitor CLI."""
    p = argparse.ArgumentParser(
        description=(
            "Daily drift monitor: runs parallel backtest replay and computes drift metrics "
            "for all active paper trading strategies. Activates drift pause when thresholds "
            "are breached."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard daily run
  python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start 2025-01-01

  # Dry run (no DB writes)
  python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start 2025-01-01 --dry-run

  # Verbose output
  python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start 2025-01-01 --verbose

  # Override DB URL
  python -m ta_lab2.scripts.drift.run_drift_monitor --paper-start 2025-01-01 --db-url postgresql://user:pass@host/db
        """,
    )

    p.add_argument(
        "--paper-start",
        required=True,
        metavar="DATE",
        help=(
            "ISO date string for paper trading start date (e.g. 2025-01-01). "
            "Used as the boundary for replay backtests and paper fill queries."
        ),
    )
    p.add_argument(
        "--db-url",
        help="Database URL (default: from config/env via resolve_db_url)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip DB writes and view refreshes; log what would happen",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose/debug logging output",
    )

    args = p.parse_args(argv)

    _configure_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Resolve DB URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("[DRY RUN] Drift monitor: no DB writes will occur")

    # Create engine with NullPool (project convention for subprocess workers)
    engine = create_engine(db_url, poolclass=NullPool)

    try:
        # Deferred import to avoid heavy imports at CLI parse time
        from ta_lab2.drift.drift_monitor import DriftMonitor  # noqa: PLC0415

        monitor = DriftMonitor(engine)

        logger.info(
            "DriftMonitor CLI: starting run (paper_start=%s, dry_run=%s)",
            args.paper_start,
            args.dry_run,
        )

        metrics_list = monitor.run(
            paper_start_date=args.paper_start,
            dry_run=args.dry_run,
        )

        _print_summary(metrics_list, args.dry_run)

        # Return 1 if any strategy had a hard failure (empty metrics list on error)
        # A non-empty list means we processed at least something (even with breaches)
        if metrics_list is None:
            logger.error("DriftMonitor CLI: run returned None (unexpected failure)")
            return 1

        return 0

    except Exception as exc:  # noqa: BLE001
        logger.exception("DriftMonitor CLI: unexpected error: %s", exc)
        print(f"[ERROR] Drift monitor failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
