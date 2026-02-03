"""
Orchestrated refresh for all feature tables.

Usage:
    python -m ta_lab2.scripts.features.run_all_feature_refreshes --ids 1,52
    python -m ta_lab2.scripts.features.run_all_feature_refreshes --all
    python -m ta_lab2.scripts.features.run_all_feature_refreshes --validate
    python -m ta_lab2.scripts.features.run_all_feature_refreshes --sequential

Refresh order (respects dependencies):
1. cmc_returns_daily (depends on cmc_price_bars_1d)
2. cmc_vol_daily (depends on cmc_price_bars_1d)
3. cmc_ta_daily (depends on cmc_price_bars_1d)
4. cmc_daily_features (depends on 1-3 + EMAs)

Parallel execution where possible:
- returns, vol, ta can run in parallel (same dependency)
- daily_features runs after all complete
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.scripts.bars.common_snapshot_contract import get_engine

logger = logging.getLogger(__name__)


# =============================================================================
# Result Types
# =============================================================================


@dataclass
class RefreshResult:
    """
    Result of a single table refresh.

    Attributes:
        table: Table name that was refreshed
        rows_inserted: Number of rows inserted/updated
        duration_seconds: Time taken for refresh
        success: Whether refresh succeeded
        error: Error message if failed
    """

    table: str
    rows_inserted: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None


# =============================================================================
# Refresh Functions
# =============================================================================


def refresh_returns(
    engine, ids: list[int], start: Optional[str], end: Optional[str]
) -> RefreshResult:
    """
    Refresh cmc_returns_daily table.

    Args:
        engine: SQLAlchemy engine
        ids: List of asset IDs
        start: Start date (optional)
        end: End date (optional)

    Returns:
        RefreshResult
    """
    from ta_lab2.scripts.features.returns_feature import ReturnsFeature, ReturnsConfig

    table = "cmc_returns_daily"
    t0 = time.time()

    try:
        config = ReturnsConfig()
        feature = ReturnsFeature(engine, config)

        rows_written = feature.compute_for_ids(
            ids=ids,
            start=start,
            end=end,
        )

        duration = time.time() - t0

        return RefreshResult(
            table=table,
            rows_inserted=rows_written,
            duration_seconds=duration,
            success=True,
        )

    except Exception as e:
        duration = time.time() - t0
        logger.error(f"Returns refresh failed: {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


def refresh_vol(
    engine, ids: list[int], start: Optional[str], end: Optional[str]
) -> RefreshResult:
    """
    Refresh cmc_vol_daily table.

    Args:
        engine: SQLAlchemy engine
        ids: List of asset IDs
        start: Start date (optional)
        end: End date (optional)

    Returns:
        RefreshResult
    """
    from ta_lab2.scripts.features.vol_feature import VolFeature, VolConfig

    table = "cmc_vol_daily"
    t0 = time.time()

    try:
        config = VolConfig()
        feature = VolFeature(engine, config)

        rows_written = feature.compute_for_ids(
            ids=ids,
            start=start,
            end=end,
        )

        duration = time.time() - t0

        return RefreshResult(
            table=table,
            rows_inserted=rows_written,
            duration_seconds=duration,
            success=True,
        )

    except Exception as e:
        duration = time.time() - t0
        logger.error(f"Vol refresh failed: {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


def refresh_ta(
    engine, ids: list[int], start: Optional[str], end: Optional[str]
) -> RefreshResult:
    """
    Refresh cmc_ta_daily table.

    Args:
        engine: SQLAlchemy engine
        ids: List of asset IDs
        start: Start date (optional)
        end: End date (optional)

    Returns:
        RefreshResult
    """
    from ta_lab2.scripts.features.ta_feature import TAFeature, TAConfig

    table = "cmc_ta_daily"
    t0 = time.time()

    try:
        config = TAConfig()
        feature = TAFeature(engine, config)

        rows_written = feature.compute_for_ids(
            ids=ids,
            start=start,
            end=end,
        )

        duration = time.time() - t0

        return RefreshResult(
            table=table,
            rows_inserted=rows_written,
            duration_seconds=duration,
            success=True,
        )

    except Exception as e:
        duration = time.time() - t0
        logger.error(f"TA refresh failed: {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


def refresh_daily_features(
    engine, ids: list[int], start: Optional[str], end: Optional[str]
) -> RefreshResult:
    """
    Refresh cmc_daily_features table.

    Args:
        engine: SQLAlchemy engine
        ids: List of asset IDs
        start: Start date (optional)
        end: End date (optional)

    Returns:
        RefreshResult
    """
    from ta_lab2.scripts.features.daily_features_view import (
        refresh_daily_features as refresh_fn,
    )

    table = "cmc_daily_features"
    t0 = time.time()

    try:
        # refresh_daily_features doesn't take ids/dates directly
        # It computes dirty window from state
        rows_written = refresh_fn(engine, full_refresh=False)

        duration = time.time() - t0

        return RefreshResult(
            table=table,
            rows_inserted=rows_written,
            duration_seconds=duration,
            success=True,
        )

    except Exception as e:
        duration = time.time() - t0
        logger.error(f"Daily features refresh failed: {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


# =============================================================================
# Orchestration
# =============================================================================


def run_all_refreshes(
    engine,
    ids: list[int],
    full_refresh: bool = False,
    validate: bool = True,
    parallel: bool = True,
) -> dict[str, RefreshResult]:
    """
    Refresh all feature tables.

    Returns dict mapping table_name -> RefreshResult

    Args:
        engine: SQLAlchemy engine
        ids: List of asset IDs
        full_refresh: If True, recompute all rows (not just incremental)
        validate: If True, run validation after refresh
        parallel: If True, run returns/vol/ta in parallel

    Returns:
        Dict mapping table name to RefreshResult
    """
    results = {}

    # Determine date range (None for incremental)
    start = None
    end = None

    logger.info(f"Starting feature refresh for {len(ids)} IDs")
    logger.info(f"Mode: {'full' if full_refresh else 'incremental'}")
    logger.info(f"Parallel: {parallel}")

    # Phase 1: Returns, Vol, TA (can run in parallel)
    phase1_tasks = [
        ("returns", refresh_returns),
        ("vol", refresh_vol),
        ("ta", refresh_ta),
    ]

    if parallel:
        logger.info("Phase 1: Running returns/vol/ta in parallel")

        with ThreadPoolExecutor(max_workers=3) as executor:
            # Submit all tasks
            future_to_name = {}
            for name, refresh_fn in phase1_tasks:
                future = executor.submit(refresh_fn, engine, ids, start, end)
                future_to_name[future] = name

            # Collect results as they complete
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                result = future.result()
                results[result.table] = result

                if result.success:
                    logger.info(
                        f"  {result.table}: {result.rows_inserted} rows in {result.duration_seconds:.1f}s"
                    )
                else:
                    logger.error(f"  {result.table}: FAILED - {result.error}")

    else:
        logger.info("Phase 1: Running returns/vol/ta sequentially")

        for name, refresh_fn in phase1_tasks:
            result = refresh_fn(engine, ids, start, end)
            results[result.table] = result

            if result.success:
                logger.info(
                    f"  {result.table}: {result.rows_inserted} rows in {result.duration_seconds:.1f}s"
                )
            else:
                logger.error(f"  {result.table}: FAILED - {result.error}")

    # Check if any phase 1 failures
    phase1_failures = [name for name, result in results.items() if not result.success]
    if phase1_failures:
        logger.warning(f"Phase 1 had failures: {phase1_failures}")
        logger.warning(
            "Continuing to daily_features refresh anyway (graceful degradation)"
        )

    # Phase 2: Daily features (depends on phase 1)
    logger.info("Phase 2: Running daily_features (unified view)")

    result = refresh_daily_features(engine, ids, start, end)
    results[result.table] = result

    if result.success:
        logger.info(
            f"  {result.table}: {result.rows_inserted} rows in {result.duration_seconds:.1f}s"
        )
    else:
        logger.error(f"  {result.table}: FAILED - {result.error}")

    # Phase 3: Validation (if requested)
    if validate:
        logger.info("Phase 3: Running validation")

        from ta_lab2.scripts.features.validate_features import validate_features

        try:
            # Validate last 30 days
            report = validate_features(
                engine,
                ids=ids[:5],  # Sample for performance
                alert=True,
            )

            if report.passed:
                logger.info(f"  Validation PASSED: {report.total_checks} checks")
            else:
                logger.warning(f"  Validation found issues: {report.summary}")
                logger.warning(
                    f"  Critical issues: {sum(1 for i in report.issues if i.severity == 'critical')}"
                )
                logger.warning(
                    f"  Warnings: {sum(1 for i in report.issues if i.severity == 'warning')}"
                )

        except Exception as e:
            logger.error(f"  Validation failed with error: {e}", exc_info=True)

    return results


# =============================================================================
# CLI
# =============================================================================


def load_ids(engine, ids_arg: Optional[str], all_ids: bool) -> list[int]:
    """
    Load asset IDs to process.

    Args:
        engine: SQLAlchemy engine
        ids_arg: Comma-separated ID string
        all_ids: If True, load all IDs from bars table

    Returns:
        List of asset IDs
    """
    if ids_arg:
        return [int(i.strip()) for i in ids_arg.split(",")]

    if all_ids:
        query = text(
            """
            SELECT DISTINCT id
            FROM public.cmc_price_bars_1d
            ORDER BY id
        """
        )

        with engine.connect() as conn:
            result = conn.execute(query)
            return [row[0] for row in result]

    return []


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Orchestrated refresh for all feature tables",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ID selection
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument(
        "--ids",
        help="Comma-separated cryptocurrency IDs (e.g., '1,52,1027')",
    )
    id_group.add_argument(
        "--all",
        action="store_true",
        help="Process all IDs from cmc_price_bars_1d",
    )

    # Refresh mode
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Full refresh (recompute all rows)",
    )

    # Validation
    parser.add_argument(
        "--validate",
        action="store_true",
        default=True,
        help="Run validation after refresh (default: True)",
    )
    parser.add_argument(
        "--no-validate",
        action="store_false",
        dest="validate",
        help="Skip validation after refresh",
    )

    # Parallelism
    parser.add_argument(
        "--parallel",
        action="store_true",
        default=True,
        help="Run phase 1 tables in parallel (default: True)",
    )
    parser.add_argument(
        "--sequential",
        action="store_false",
        dest="parallel",
        help="Run all tables sequentially",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Starting feature refresh pipeline")

    # Resolve database URL
    if not TARGET_DB_URL:
        logger.error("TARGET_DB_URL not set")
        return 1

    engine = get_engine(TARGET_DB_URL)

    # Load IDs
    try:
        ids = load_ids(engine, args.ids, args.all)
    except Exception as e:
        logger.error(f"Failed to load IDs: {e}", exc_info=True)
        return 1

    if not ids:
        logger.error("No IDs to process")
        return 1

    logger.info(
        f"Processing {len(ids)} IDs: {ids[:10]}{'...' if len(ids) > 10 else ''}"
    )

    # Run refreshes
    try:
        results = run_all_refreshes(
            engine,
            ids=ids,
            full_refresh=args.full_refresh,
            validate=args.validate,
            parallel=args.parallel,
        )
    except Exception as e:
        logger.error(f"Refresh pipeline failed: {e}", exc_info=True)
        return 1

    # Print summary
    print("\n" + "=" * 60)
    print("REFRESH SUMMARY")
    print("=" * 60)

    total_rows = 0
    total_duration = 0.0
    failures = []

    for table in [
        "cmc_returns_daily",
        "cmc_vol_daily",
        "cmc_ta_daily",
        "cmc_daily_features",
    ]:
        if table in results:
            result = results[table]
            status = "OK" if result.success else "FAILED"
            print(
                f"{table:30s} {status:10s} {result.rows_inserted:8d} rows in {result.duration_seconds:6.1f}s"
            )

            if result.success:
                total_rows += result.rows_inserted
                total_duration += result.duration_seconds
            else:
                failures.append(table)

    print("=" * 60)
    print(f"Total: {total_rows} rows in {total_duration:.1f}s")

    if failures:
        print(f"Failures: {', '.join(failures)}")
        return 1

    print("All refreshes completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
