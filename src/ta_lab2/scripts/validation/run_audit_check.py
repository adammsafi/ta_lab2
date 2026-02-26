"""
run_audit_check.py
~~~~~~~~~~~~~~~~~~
V1 Validation Audit Gap Detection CLI.

Runs 6 automated gap detection checks against the database covering:
  1. Missing executor run days
  2. Error runs (failed/stale_signal status)
  3. Orphaned orders (stuck created/submitted > 2 days)
  4. Position/fill consistency
  5. Stale price data (1D bar > 28 hours old)
  6. Drift metric gaps (executor ran but no drift metrics)

Prints summary to stdout and writes full Markdown report to:
  ``reports/validation/audit/audit_YYYY-MM-DD.md``

Exit codes:
  0  -- all checks PASS (no anomalies)
  1  -- one or more anomalies detected (FAILs)
  2  -- execution error

Usage::

    python -m ta_lab2.scripts.validation.run_audit_check \\
        --start-date 2026-03-01 \\
        --end-date 2026-03-14

Design notes:
  - ALL file operations use encoding='utf-8' (Windows cp1252 safety per MEMORY.md).
  - Uses NullPool to avoid connection pooling issues (project convention).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_OUTPUT_DIR = str(_PROJECT_ROOT / "reports" / "validation" / "audit")


# ---------------------------------------------------------------------------
# DB engine helper (NullPool pattern -- project convention)
# ---------------------------------------------------------------------------


def _get_engine(db_url: str | None = None):
    """Create SQLAlchemy engine with NullPool."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from ta_lab2.db.config import resolve_db_url

    url = db_url or resolve_db_url()
    return create_engine(url, poolclass=NullPool)


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _print_summary(findings, summary) -> None:
    """Print audit summary table to stdout."""
    sep = "=" * 60
    print(sep)
    print("V1 VALIDATION AUDIT SUMMARY")
    print(sep)

    for finding in findings:
        tag = f"[{finding.status}]"
        print(f"  {tag:<8} {finding.check_name}")
        if finding.status == "FAIL":
            print(f"           --> {finding.count} anomaly(ies) detected")

    print(sep)
    print(f"Total anomalies: {summary.n_anomalies}")
    if summary.n_anomalies == 0:
        print("Result: PASS -- no gaps detected")
    else:
        print(
            f"Result: FAIL -- {summary.n_anomalies} anomaly(ies) require human review and sign-off"
        )
    print(sep)


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def run_audit(
    start_date: date,
    end_date: date,
    output_dir: str,
    db_url: str | None = None,
) -> int:
    """Run the audit gap detection and generate the report.

    Args:
        start_date: Inclusive start date for the audit period.
        end_date:   Inclusive end date for the audit period.
        output_dir: Directory to write the report file.
        db_url:     Optional database URL override.

    Returns:
        Exit code: 0 if PASS, 1 if anomalies detected, 2 on execution error.
    """
    from ta_lab2.validation.audit_checker import AuditChecker

    try:
        engine = _get_engine(db_url)
        checker = AuditChecker(engine)

        findings, summary = checker.run_audit(
            start_date=start_date,
            end_date=end_date,
        )

        _print_summary(findings, summary)

        report_path = checker.generate_report(
            findings=findings,
            summary=summary,
            start_date=start_date,
            end_date=end_date,
            output_dir=output_dir,
        )
        print(f"\nFull audit report written to: {report_path}")

        return 0 if summary.n_anomalies == 0 else 1

    except Exception as exc:
        logger.error("run_audit failed: %s", exc, exc_info=True)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "V1 Validation Audit Gap Detection. "
            "Runs 6 automated gap checks (missing run days, error runs, "
            "orphaned orders, position/fill consistency, stale data, drift gaps). "
            "Exit 0 = PASS (no anomalies). Exit 1 = anomalies detected. Exit 2 = error."
        )
    )
    parser.add_argument(
        "--start-date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Audit period start date (inclusive).",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Audit period end date (inclusive).",
    )
    parser.add_argument(
        "--output-dir",
        default=_DEFAULT_OUTPUT_DIR,
        metavar="PATH",
        help=f"Output directory for audit report (default: {_DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        metavar="URL",
        help="Database URL (default: resolve_db_url() from db_config.env).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    # Parse dates
    try:
        start_date = date.fromisoformat(args.start_date)
    except ValueError as exc:
        print(f"ERROR: Invalid --start-date: {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        end_date = date.fromisoformat(args.end_date)
    except ValueError as exc:
        print(f"ERROR: Invalid --end-date: {exc}", file=sys.stderr)
        sys.exit(2)

    if end_date < start_date:
        print("ERROR: --end-date must be >= --start-date", file=sys.stderr)
        sys.exit(2)

    sys.exit(
        run_audit(
            start_date=start_date,
            end_date=end_date,
            output_dir=args.output_dir,
            db_url=args.db_url,
        )
    )


if __name__ == "__main__":
    main()
