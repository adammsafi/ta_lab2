"""
run_daily_validation_log.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
V1 Validation Daily Log CLI.

Generates a daily Markdown validation report from DB data, covering
pipeline status, signals, orders/fills, positions, P&L, drift metrics,
and risk state.

Output: ``reports/validation/daily/validation_YYYY-MM-DD.md``

Exit codes:
  0  -- report generated successfully
  1  -- error

Usage::

    python -m ta_lab2.scripts.validation.run_daily_validation_log \\
        --validation-start 2026-03-01

    python -m ta_lab2.scripts.validation.run_daily_validation_log \\
        --validation-start 2026-03-01 \\
        --date 2026-03-05 \\
        --output-dir /tmp/reports

Design notes:
  - --date defaults to today when omitted.
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
_DEFAULT_OUTPUT_DIR = str(_PROJECT_ROOT / "reports" / "validation" / "daily")


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
# Main logic
# ---------------------------------------------------------------------------


def run_daily_log(
    log_date: date,
    validation_start: date,
    output_dir: str,
    db_url: str | None = None,
) -> int:
    """Run the daily validation log generator.

    Args:
        log_date:         Date for which to generate the log.
        validation_start: First day of the 14-day validation window.
        output_dir:       Directory to write the report file.
        db_url:           Optional database URL override.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    from ta_lab2.validation.daily_log import DailyValidationLog

    try:
        engine = _get_engine(db_url)
        log_gen = DailyValidationLog(engine)
        report_path = log_gen.generate(
            log_date=log_date,
            validation_start=validation_start,
            output_dir=output_dir,
        )
        print(f"Daily validation log written to: {report_path}")
        return 0
    except Exception as exc:
        logger.error("run_daily_log failed: %s", exc, exc_info=True)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "V1 Validation Daily Log Generator. "
            "Queries DB and writes a structured Markdown validation report. "
            "Output: reports/validation/daily/validation_YYYY-MM-DD.md"
        )
    )
    parser.add_argument(
        "--validation-start",
        required=True,
        metavar="YYYY-MM-DD",
        help="Validation period start date (first day of the 14-day clock).",
    )
    parser.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Log date (default: today).",
    )
    parser.add_argument(
        "--output-dir",
        default=_DEFAULT_OUTPUT_DIR,
        metavar="PATH",
        help=f"Output directory for report files (default: {_DEFAULT_OUTPUT_DIR}).",
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
        validation_start = date.fromisoformat(args.validation_start)
    except ValueError as exc:
        print(f"ERROR: Invalid --validation-start date: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.date:
        try:
            log_date = date.fromisoformat(args.date)
        except ValueError as exc:
            print(f"ERROR: Invalid --date: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        log_date = date.today()

    sys.exit(
        run_daily_log(
            log_date=log_date,
            validation_start=validation_start,
            output_dir=args.output_dir,
            db_url=args.db_url,
        )
    )


if __name__ == "__main__":
    main()
