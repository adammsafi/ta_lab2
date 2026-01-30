#!/usr/bin/env python3
"""
Validate EMA rowcounts against dim_timeframe expectations.

This script compares actual EMA rowcounts in the database against expected counts
calculated from dim_timeframe metadata. It detects gaps (missing rows) and duplicates
(extra rows) for each (id, tf, period) combination.

Usage:
    python validate_ema_rowcounts.py --help
    python validate_ema_rowcounts.py --start 2024-01-01 --end 2024-12-31
    python validate_ema_rowcounts.py --alert --start 2024-01-01
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.time.dim_timeframe import get_tf_days, list_tfs
from ta_lab2.notifications.telegram import send_validation_alert, is_configured as telegram_configured

logger = logging.getLogger(__name__)


def resolve_db_url() -> str:
    """Resolve database URL from config."""
    if not TARGET_DB_URL:
        raise RuntimeError(
            "TARGET_DB_URL not set. Set DB_URL or TARGET_DB_URL environment variable."
        )
    return TARGET_DB_URL


def compute_expected_rowcount(
    start_date: str,
    end_date: str,
    tf: str,
    tf_days: int,
) -> int:
    """
    Compute expected number of canonical closes for a timeframe in a date range.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        tf: Timeframe string (e.g., '1D', '7D', '1M_CAL')
        tf_days: Nominal days for the timeframe

    Returns:
        Expected row count (approximate for calendar-aligned TFs)
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    total_days = (end - start).days + 1  # inclusive

    if tf_days <= 0:
        return 0

    # For tf_day alignment: simple division
    # For calendar alignment: this is approximate (actual may vary by calendar)
    expected = total_days // tf_days

    # Edge case: if range is shorter than tf_days, we might have 0 or 1
    if total_days < tf_days:
        return 0  # or 1, depending on alignment - 0 is conservative

    return expected


def get_actual_rowcount(
    engine: Engine,
    table: str,
    schema: str,
    id_: int,
    tf: str,
    period: int,
    start_date: str,
    end_date: str,
) -> int:
    """
    Get actual rowcount from EMA table for a specific (id, tf, period) in date range.

    Args:
        engine: SQLAlchemy engine
        table: Table name (e.g., 'cmc_ema_multi_tf_u')
        schema: Schema name (e.g., 'public')
        id_: Asset ID
        tf: Timeframe
        period: EMA period
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Actual row count (canonical rows only, roll=FALSE)
    """
    query = text(f"""
        SELECT COUNT(*) as cnt
        FROM {schema}.{table}
        WHERE id = :id_
          AND tf = :tf
          AND period = :period
          AND ts BETWEEN :start_date AND :end_date
          AND roll = FALSE
    """)

    with engine.connect() as conn:
        result = conn.execute(
            query,
            {
                "id_": id_,
                "tf": tf,
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        row = result.fetchone()
        return int(row[0]) if row else 0


def validate_rowcounts(
    engine: Engine,
    table: str,
    schema: str,
    ids: Optional[List[int]],
    tfs: Optional[List[str]],
    periods: Optional[List[int]],
    start_date: str,
    end_date: str,
    db_url: str,
) -> pd.DataFrame:
    """
    Validate rowcounts for all combinations of (id, tf, period).

    Args:
        engine: SQLAlchemy engine
        table: Table name
        schema: Schema name
        ids: List of asset IDs to check (None = all)
        tfs: List of TFs to check (None = all canonical)
        periods: List of periods to check (None = common periods)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        db_url: Database URL for dim_timeframe lookup

    Returns:
        DataFrame with columns: id, tf, period, expected, actual, diff, status
    """
    # Determine IDs to check
    if ids is None:
        query = text(f"SELECT DISTINCT id FROM {schema}.{table} ORDER BY id")
        with engine.connect() as conn:
            result = conn.execute(query)
            ids = [row[0] for row in result]

    # Determine TFs to check
    if tfs is None:
        tfs = list_tfs(db_url, canonical_only=True)

    # Determine periods to check
    if periods is None:
        periods = [9, 10, 20, 50]  # Common EMA periods

    results = []

    total_checks = len(ids) * len(tfs) * len(periods)
    logger.info(f"Validating {total_checks} combinations: {len(ids)} IDs x {len(tfs)} TFs x {len(periods)} periods")

    for id_ in ids:
        for tf in tfs:
            # Get tf_days for this timeframe
            try:
                tf_days = get_tf_days(tf, db_url)
            except KeyError:
                logger.warning(f"Skipping unknown TF: {tf}")
                continue

            for period in periods:
                # Compute expected count
                expected = compute_expected_rowcount(start_date, end_date, tf, tf_days)

                # Get actual count
                actual = get_actual_rowcount(
                    engine, table, schema, id_, tf, period, start_date, end_date
                )

                # Calculate diff and status
                diff = actual - expected
                if diff == 0:
                    status = "OK"
                elif diff < 0:
                    status = "GAP"
                else:
                    status = "DUPLICATE"

                results.append({
                    "id": id_,
                    "tf": tf,
                    "period": period,
                    "expected": expected,
                    "actual": actual,
                    "diff": diff,
                    "status": status,
                })

    df = pd.DataFrame(results)
    return df


def summarize_validation(df: pd.DataFrame) -> dict:
    """
    Summarize validation results.

    Args:
        df: Validation results DataFrame

    Returns:
        Dict with total, ok, gaps, duplicates counts and list of issues
    """
    total = len(df)
    ok = len(df[df["status"] == "OK"])
    gaps = len(df[df["status"] == "GAP"])
    duplicates = len(df[df["status"] == "DUPLICATE"])

    # Extract issues (non-OK rows)
    issues = []
    for _, row in df[df["status"] != "OK"].iterrows():
        issues.append({
            "id": row["id"],
            "tf": row["tf"],
            "period": row["period"],
            "expected": row["expected"],
            "actual": row["actual"],
            "diff": row["diff"],
            "status": row["status"],
        })

    return {
        "total": total,
        "ok": ok,
        "gaps": gaps,
        "duplicates": duplicates,
        "issues": issues,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(
        description="Validate EMA rowcounts against dim_timeframe expectations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument(
        "--table",
        default="cmc_ema_multi_tf_u",
        help="EMA table name (default: cmc_ema_multi_tf_u)",
    )
    p.add_argument(
        "--schema",
        default="public",
        help="Schema name (default: public)",
    )
    p.add_argument(
        "--ids",
        default=None,
        help="Comma-separated IDs to check (default: all)",
    )
    p.add_argument(
        "--tfs",
        default=None,
        help="Comma-separated TFs to check (default: all canonical)",
    )
    p.add_argument(
        "--periods",
        default="9,10,20,50",
        help="Comma-separated periods (default: 9,10,20,50)",
    )
    p.add_argument(
        "--start",
        required=True,
        help="Start date YYYY-MM-DD",
    )
    p.add_argument(
        "--end",
        required=True,
        help="End date YYYY-MM-DD",
    )
    p.add_argument(
        "--alert",
        action="store_true",
        help="Send Telegram alert on validation errors",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    return p.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Starting EMA rowcount validation")
    logger.info(f"Table: {args.schema}.{args.table}")
    logger.info(f"Date range: {args.start} to {args.end}")

    # Resolve database URL
    try:
        db_url = resolve_db_url()
    except RuntimeError as e:
        logger.error(f"Database configuration error: {e}")
        return 1

    # Create engine
    engine = create_engine(db_url)

    # Parse IDs, TFs, periods
    ids = [int(x.strip()) for x in args.ids.split(",")] if args.ids else None
    tfs = [x.strip() for x in args.tfs.split(",")] if args.tfs else None
    periods = [int(x.strip()) for x in args.periods.split(",")]

    # Run validation
    try:
        df = validate_rowcounts(
            engine=engine,
            table=args.table,
            schema=args.schema,
            ids=ids,
            tfs=tfs,
            periods=periods,
            start_date=args.start,
            end_date=args.end,
            db_url=db_url,
        )
    except Exception as e:
        logger.error(f"Validation failed: {e}", exc_info=True)
        return 1

    # Summarize results
    summary = summarize_validation(df)

    logger.info(f"Validation complete: {summary['total']} checks")
    logger.info(f"  OK: {summary['ok']}")
    logger.info(f"  GAPs: {summary['gaps']}")
    logger.info(f"  DUPLICATEs: {summary['duplicates']}")

    # Send Telegram alert if requested and issues found
    if args.alert and (summary["gaps"] > 0 or summary["duplicates"] > 0):
        if telegram_configured():
            logger.info("Sending Telegram alert...")
            success = send_validation_alert(summary)
            if success:
                logger.info("Telegram alert sent successfully")
            else:
                logger.warning("Failed to send Telegram alert")
        else:
            logger.warning("Telegram not configured - skipping alert")

    # Exit code: 0 if all OK, 1 if any issues
    if summary["gaps"] > 0 or summary["duplicates"] > 0:
        logger.warning(f"Validation found {summary['gaps']} gaps and {summary['duplicates']} duplicates")
        return 1

    logger.info("All validation checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
