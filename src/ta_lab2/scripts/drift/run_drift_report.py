#!/usr/bin/env python
"""Weekly drift report generator -- produces Markdown + Plotly charts.

Generates a weekly drift guard report with equity curve overlays, tracking error
time series, and optional attribution waterfall charts.

Usage:
    python -m ta_lab2.scripts.drift.run_drift_report
    python -m ta_lab2.scripts.drift.run_drift_report --week-start 2025-01-01 --week-end 2025-01-07
    python -m ta_lab2.scripts.drift.run_drift_report --output-dir reports/drift --verbose
    python -m ta_lab2.scripts.drift.run_drift_report --with-attribution

Note:
    The weekly report is NOT wired into --all pipeline. Invoke manually or from cron.
    Attribution (--with-attribution) is compute-heavy; skip unless specifically needed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

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


def _parse_date(date_str: str) -> date:
    """Parse ISO date string to date object."""
    try:
        return date.fromisoformat(date_str)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date format '{date_str}'. Expected YYYY-MM-DD."
        ) from exc


def main(argv: list[str] | None = None) -> int:
    """Main entry point for drift report CLI."""
    p = argparse.ArgumentParser(
        description=(
            "Weekly drift report generator: produces Markdown report with Plotly HTML charts "
            "covering equity curve overlays, tracking error time series, and optional "
            "attribution waterfall. Invoked manually or from cron (not in --all pipeline)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default: report for last 7 days
  python -m ta_lab2.scripts.drift.run_drift_report

  # Specific date range
  python -m ta_lab2.scripts.drift.run_drift_report --week-start 2025-01-01 --week-end 2025-01-07

  # Custom output directory
  python -m ta_lab2.scripts.drift.run_drift_report --output-dir /reports/weekly

  # Include attribution decomposition (compute-heavy)
  python -m ta_lab2.scripts.drift.run_drift_report --with-attribution

  # Verbose output
  python -m ta_lab2.scripts.drift.run_drift_report --verbose
        """,
    )

    p.add_argument(
        "--week-start",
        metavar="DATE",
        help=(
            "ISO date for report window start (e.g. 2025-01-01). "
            "Default: 7 days before --week-end."
        ),
    )
    p.add_argument(
        "--week-end",
        metavar="DATE",
        help=("ISO date for report window end (e.g. 2025-01-07). Default: today."),
    )
    p.add_argument(
        "--output-dir",
        default="reports/drift",
        metavar="DIR",
        help="Report output directory (default: reports/drift). Created if absent.",
    )
    p.add_argument(
        "--db-url",
        help="Database URL (default: from config/env via resolve_db_url)",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose/debug logging output",
    )
    p.add_argument(
        "--with-attribution",
        action="store_true",
        help=(
            "Run full 6-source OAT attribution decomposition for the report period. "
            "Compute-heavy: each config runs 7 backtest replays. "
            "This is the only way attr_* columns in cmc_drift_metrics get populated."
        ),
    )

    args = p.parse_args(argv)

    _configure_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Resolve date range
    week_end = _parse_date(args.week_end) if args.week_end else date.today()
    week_start = (
        _parse_date(args.week_start)
        if args.week_start
        else week_end - timedelta(days=7)
    )

    if week_start >= week_end:
        print(
            f"[ERROR] --week-start ({week_start}) must be before --week-end ({week_end})",
            file=sys.stderr,
        )
        return 1

    # Resolve DB URL
    try:
        db_url = resolve_db_url(args.db_url)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Create engine with NullPool (project convention for subprocess workers)
    engine = create_engine(db_url, poolclass=NullPool)

    try:
        # Run attribution if requested (compute-heavy -- loads 7 backtests per config)
        if args.with_attribution:
            print(
                f"\n[INFO] Running attribution decomposition for {week_start} to {week_end}"
            )
            print(
                "[INFO] This may take several minutes (7 backtest replays per config)"
            )

            from ta_lab2.drift.attribution import DriftAttributor  # noqa: PLC0415
            from sqlalchemy import text  # noqa: PLC0415

            attributor = DriftAttributor(engine)

            # Load configs with metrics for the period
            # JOIN dim_executor_config to get signal_id (not in cmc_drift_metrics)
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT DISTINCT dm.config_id, dec.signal_id, dm.signal_type,
                               dm.asset_id, dm.paper_trade_count,
                               dm.paper_cumulative_pnl
                        FROM cmc_drift_metrics dm
                        JOIN dim_executor_config dec ON dec.config_id = dm.config_id
                        WHERE dm.metric_date BETWEEN :start AND :end
                          AND dm.paper_trade_count >= 10
                        """
                    ),
                    {"start": week_start.isoformat(), "end": week_end.isoformat()},
                ).fetchall()

            if not rows:
                logger.warning(
                    "No drift metrics rows found for attribution (period %s to %s)",
                    week_start,
                    week_end,
                )
            else:
                logger.info(
                    "Running attribution for %d (config, asset) pairs", len(rows)
                )
                for row in rows:
                    try:
                        result = attributor.run_attribution(
                            config_id=row.config_id,
                            signal_id=row.signal_id,
                            signal_type=row.signal_type,
                            asset_id=row.asset_id,
                            paper_start=week_start.isoformat(),
                            paper_end=week_end.isoformat(),
                            paper_pnl=float(row.paper_cumulative_pnl),
                            paper_trade_count=int(row.paper_trade_count),
                        )
                        logger.debug(
                            "Attribution done: config_id=%d asset_id=%d residual=%.4f",
                            row.config_id,
                            row.asset_id,
                            result.unexplained_residual,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Attribution failed for config_id=%d asset_id=%d: %s",
                            row.config_id,
                            row.asset_id,
                            exc,
                        )

        # Generate the report
        from ta_lab2.drift.drift_report import ReportGenerator  # noqa: PLC0415

        reporter = ReportGenerator(engine)

        logger.info(
            "ReportGenerator CLI: generating report for %s to %s -> %s",
            week_start,
            week_end,
            args.output_dir,
        )

        report_path = reporter.generate_weekly_report(
            week_start=week_start,
            week_end=week_end,
            output_dir=args.output_dir,
        )

        print(f"\n[OK] Drift report written to: {report_path}")
        return 0

    except Exception as exc:  # noqa: BLE001
        logger.exception("ReportGenerator CLI: unexpected error: %s", exc)
        print(f"[ERROR] Drift report failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
