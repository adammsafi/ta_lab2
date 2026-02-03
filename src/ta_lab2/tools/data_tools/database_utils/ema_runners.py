"""
EMA database write utilities consolidated from Data_Tools.

Provides convenience runners for writing different types of EMAs to database tables.
All functions wrap existing ta_lab2 EMA infrastructure.

Tables written:
- cmc_ema_daily: Daily EMAs (1-day timeframe)
- cmc_ema_multi_tf: Multi-timeframe EMAs (1h, 4h, 1d, etc.)
- cmc_ema_multi_tf_cal: Calendar-aligned multi-timeframe EMAs
- Plus downstream views via refresh operations

Usage:
    # From Python
    from ta_lab2.tools.data_tools.database_utils.ema_runners import (
        write_daily_emas,
        write_multi_tf_emas,
        write_ema_multi_tf_cal,
        upsert_new_emas,
    )

    # Write daily EMAs for specific IDs
    rows = write_daily_emas(ids=[1, 1027, 5426], start="2010-01-01")

    # CLI
    python -m ta_lab2.tools.data_tools.database_utils.ema_runners daily --ids 1 1027 --start 2010-01-01
    python -m ta_lab2.tools.data_tools.database_utils.ema_runners multi-tf --ids 1 1027
    python -m ta_lab2.tools.data_tools.database_utils.ema_runners multi-tf-cal --ids 1 1027
    python -m ta_lab2.tools.data_tools.database_utils.ema_runners upsert

Note:
    These are convenience wrappers. For production use, prefer:
    - ta_lab2.features.ema.write_daily_ema_to_db
    - ta_lab2.features.m_tf.ema_multi_timeframe.write_multi_timeframe_ema_to_db
    - ta_lab2.features.m_tf.ema_multi_tf_cal.write_multi_timeframe_ema_cal_to_db
    - ta_lab2.scripts.emas.old.run_ema_refresh_examples.example_incremental_all_ids_all_targets
"""

from __future__ import annotations

import argparse
import logging
from typing import Iterable, Sequence

from ta_lab2.features.ema import write_daily_ema_to_db
from ta_lab2.features.m_tf.ema_multi_timeframe import write_multi_timeframe_ema_to_db
from ta_lab2.features.m_tf.ema_multi_tf_cal import write_multi_timeframe_ema_cal_to_db
from ta_lab2.scripts.emas.old.run_ema_refresh_examples import (
    example_incremental_all_ids_all_targets,
)

logger = logging.getLogger(__name__)


def write_daily_emas(
    ids: Iterable[int],
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (10, 21, 50, 100, 200),
) -> int:
    """
    Write daily EMAs to cmc_ema_daily table.

    Args:
        ids: CMC coin IDs to process
        start: Start date (YYYY-MM-DD format)
        end: Optional end date (defaults to today)
        ema_periods: EMA periods to calculate

    Returns:
        Number of rows written

    Example:
        >>> rows = write_daily_emas(
        ...     ids=[1, 1027, 5426, 52, 32196, 1975, 1839],
        ...     start="2010-01-01"
        ... )
        >>> print(f"Daily EMA rows written: {rows}")
    """
    logger.info(f"Writing daily EMAs for {len(list(ids))} IDs starting from {start}")
    rows = write_daily_ema_to_db(
        ids=ids,
        start=start,
        end=end,
        ema_periods=ema_periods,
    )
    logger.info(f"Daily EMA rows written: {rows}")
    return rows


def write_multi_tf_emas(
    ids: Sequence[int],
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Sequence[int] = (6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365),
    tf_subset: Sequence[str] | None = None,
) -> int:
    """
    Write multi-timeframe EMAs to cmc_ema_multi_tf table.

    Args:
        ids: CMC coin IDs to process
        start: Start date (YYYY-MM-DD format)
        end: Optional end date (defaults to today)
        ema_periods: EMA periods to calculate
        tf_subset: Optional timeframe subset (e.g., ["1h", "4h", "1d"])

    Returns:
        Total number of rows written

    Example:
        >>> total = write_multi_tf_emas(
        ...     ids=[1, 1027, 5426, 52, 32196, 1975, 1839],
        ...     start="2010-01-01"
        ... )
        >>> print(f"Multi-TF EMA rows written: {total}")
    """
    logger.info(f"Writing multi-timeframe EMAs for {len(ids)} IDs starting from {start}")
    total = write_multi_timeframe_ema_to_db(
        ids=ids,
        start=start,
        end=end,
        ema_periods=ema_periods,
        tf_subset=tf_subset,
    )
    logger.info(f"Multi-TF EMA rows written: {total}")
    return total


def write_ema_multi_tf_cal(
    ids: Sequence[int],
    start: str | None = None,
    end: str | None = None,
    scheme: str = "US",
    ema_periods: Sequence[int] = (6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365),
    tf_subset: Sequence[str] | None = None,
) -> int:
    """
    Write calendar-aligned multi-timeframe EMAs to cmc_ema_multi_tf_cal table.

    Uses business day calendars to align timeframes with trading schedules.

    Args:
        ids: CMC coin IDs to process
        start: Optional start date (YYYY-MM-DD format)
        end: Optional end date (defaults to today)
        scheme: Calendar scheme (default "US")
        ema_periods: EMA periods to calculate
        tf_subset: Optional timeframe subset

    Returns:
        Total number of rows written

    Example:
        >>> total = write_ema_multi_tf_cal(
        ...     ids=[1, 1027, 5426, 52, 32196, 1975, 1839],
        ...     start="2010-01-01"
        ... )
        >>> print(f"Calendar-aligned EMA rows written: {total}")
    """
    from ta_lab2.config import TARGET_DB_URL

    logger.info(f"Writing calendar-aligned multi-TF EMAs for {len(ids)} IDs")
    total = write_multi_timeframe_ema_cal_to_db(
        engine_or_db_url=TARGET_DB_URL,
        ids=ids,
        scheme=scheme,
        start=start,
        end=end,
        ema_periods=ema_periods,
        tf_subset=tf_subset,
    )
    logger.info(f"Calendar-aligned EMA rows written to cmc_ema_multi_tf_cal: {total}")
    return total


def upsert_new_emas() -> None:
    """
    Incremental upsert of new EMAs after fresh price data is loaded.

    Updates all EMA tables for all IDs:
    - cmc_ema_daily
    - cmc_ema_multi_tf
    - cmc_ema_multi_tf_cal
    - all_emas (view)
    - cmc_price_with_emas (view)
    - cmc_price_with_emas_d1d2 (view)

    This is a wrapper around example_incremental_all_ids_all_targets() which
    handles incremental refresh logic, snapshots, and reporting.

    Example:
        >>> upsert_new_emas()
        # Processes all IDs, prints before/after comparison
    """
    logger.info("Running incremental EMA upsert for all IDs and all targets")
    example_incremental_all_ids_all_targets()
    logger.info("Incremental EMA upsert complete")


def main():
    """CLI entry point for EMA runners."""
    parser = argparse.ArgumentParser(
        description="EMA database write utilities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Write daily EMAs for specific IDs
  python -m ta_lab2.tools.data_tools.database_utils.ema_runners daily --ids 1 1027 5426 --start 2010-01-01

  # Write multi-timeframe EMAs
  python -m ta_lab2.tools.data_tools.database_utils.ema_runners multi-tf --ids 1 1027 --start 2010-01-01

  # Write calendar-aligned multi-TF EMAs
  python -m ta_lab2.tools.data_tools.database_utils.ema_runners multi-tf-cal --ids 1 1027 --start 2010-01-01

  # Incremental upsert for all IDs
  python -m ta_lab2.tools.data_tools.database_utils.ema_runners upsert
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Daily EMAs
    daily_parser = subparsers.add_parser("daily", help="Write daily EMAs")
    daily_parser.add_argument("--ids", type=int, nargs="+", required=True, help="CMC coin IDs")
    daily_parser.add_argument("--start", default="2010-01-01", help="Start date (YYYY-MM-DD)")
    daily_parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")

    # Multi-timeframe EMAs
    multi_tf_parser = subparsers.add_parser("multi-tf", help="Write multi-timeframe EMAs")
    multi_tf_parser.add_argument("--ids", type=int, nargs="+", required=True, help="CMC coin IDs")
    multi_tf_parser.add_argument("--start", default="2010-01-01", help="Start date (YYYY-MM-DD)")
    multi_tf_parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")

    # Calendar-aligned multi-TF EMAs
    cal_parser = subparsers.add_parser("multi-tf-cal", help="Write calendar-aligned multi-TF EMAs")
    cal_parser.add_argument("--ids", type=int, nargs="+", required=True, help="CMC coin IDs")
    cal_parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    cal_parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    cal_parser.add_argument("--scheme", default="US", help="Calendar scheme")

    # Upsert
    subparsers.add_parser("upsert", help="Incremental upsert for all IDs")

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    if args.command == "daily":
        rows = write_daily_emas(ids=args.ids, start=args.start, end=args.end)
        print(f"Daily EMA rows written: {rows}")

    elif args.command == "multi-tf":
        total = write_multi_tf_emas(ids=args.ids, start=args.start, end=args.end)
        print(f"Multi-TF EMA rows written: {total}")

    elif args.command == "multi-tf-cal":
        total = write_ema_multi_tf_cal(
            ids=args.ids,
            start=args.start,
            end=args.end,
            scheme=args.scheme
        )
        print(f"Calendar-aligned EMA rows written: {total}")

    elif args.command == "upsert":
        upsert_new_emas()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
