"""
Orchestrated refresh for all feature tables.

Usage:
    python -m ta_lab2.scripts.features.run_all_feature_refreshes --ids 1,52
    python -m ta_lab2.scripts.features.run_all_feature_refreshes --all
    python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --tf 1D
    python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --all-tfs
    python -m ta_lab2.scripts.features.run_all_feature_refreshes --validate
    python -m ta_lab2.scripts.features.run_all_feature_refreshes --sequential

Refresh order (respects dependencies):
1. cmc_returns (depends on cmc_price_bars_multi_tf)
2. cmc_vol (depends on cmc_price_bars_multi_tf)
3. cmc_ta (depends on cmc_price_bars_multi_tf)
4. cmc_features (depends on 1-3 + EMAs)

Parallel execution where possible:
- returns, vol, ta can run in parallel (same dependency)
- cmc_features runs after all complete
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
    """Result of a single table refresh."""

    table: str
    rows_inserted: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None


# =============================================================================
# Refresh Functions
# =============================================================================


def refresh_returns(
    engine, ids: list[int], start: Optional[str], end: Optional[str], tf: str = "1D"
) -> RefreshResult:
    """Refresh cmc_returns table for given tf."""
    from ta_lab2.scripts.features.returns_feature import ReturnsFeature, ReturnsConfig

    table = "cmc_returns"
    t0 = time.time()

    try:
        config = ReturnsConfig(tf=tf)
        feature = ReturnsFeature(engine, config)
        rows_written = feature.compute_for_ids(ids=ids, start=start, end=end)
        duration = time.time() - t0

        return RefreshResult(
            table=table,
            rows_inserted=rows_written,
            duration_seconds=duration,
            success=True,
        )

    except Exception as e:
        duration = time.time() - t0
        logger.error(f"Returns refresh failed (tf={tf}): {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


def refresh_vol(
    engine, ids: list[int], start: Optional[str], end: Optional[str], tf: str = "1D"
) -> RefreshResult:
    """Refresh cmc_vol table for given tf."""
    from ta_lab2.scripts.features.vol_feature import VolatilityFeature, VolatilityConfig

    table = "cmc_vol"
    t0 = time.time()

    try:
        config = VolatilityConfig(tf=tf)
        feature = VolatilityFeature(engine, config)
        rows_written = feature.compute_for_ids(ids=ids, start=start, end=end)
        duration = time.time() - t0

        return RefreshResult(
            table=table,
            rows_inserted=rows_written,
            duration_seconds=duration,
            success=True,
        )

    except Exception as e:
        duration = time.time() - t0
        logger.error(f"Vol refresh failed (tf={tf}): {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


def refresh_ta(
    engine, ids: list[int], start: Optional[str], end: Optional[str], tf: str = "1D"
) -> RefreshResult:
    """Refresh cmc_ta table for given tf."""
    from ta_lab2.scripts.features.ta_feature import TAFeature, TAConfig

    table = "cmc_ta"
    t0 = time.time()

    try:
        config = TAConfig(tf=tf)
        feature = TAFeature(engine, config)
        rows_written = feature.compute_for_ids(ids=ids, start=start, end=end)
        duration = time.time() - t0

        return RefreshResult(
            table=table,
            rows_inserted=rows_written,
            duration_seconds=duration,
            success=True,
        )

    except Exception as e:
        duration = time.time() - t0
        logger.error(f"TA refresh failed (tf={tf}): {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


def refresh_features_store(
    engine, ids: list[int], start: Optional[str], end: Optional[str], tf: str = "1D"
) -> RefreshResult:
    """Refresh cmc_features table for given tf."""
    from ta_lab2.scripts.features.daily_features_view import refresh_features

    table = "cmc_features"
    t0 = time.time()

    try:
        rows_written = refresh_features(engine, ids=ids, tf=tf, full_refresh=False)
        duration = time.time() - t0

        return RefreshResult(
            table=table,
            rows_inserted=rows_written,
            duration_seconds=duration,
            success=True,
        )

    except Exception as e:
        duration = time.time() - t0
        logger.error(f"Features store refresh failed (tf={tf}): {e}", exc_info=True)
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


def get_available_tfs(engine) -> list[str]:
    """Query distinct TFs from cmc_price_bars_multi_tf."""
    query = text("SELECT DISTINCT tf FROM public.cmc_price_bars_multi_tf ORDER BY tf")
    with engine.connect() as conn:
        result = conn.execute(query)
        return [row[0] for row in result]


def run_all_refreshes(
    engine,
    ids: list[int],
    tf: str = "1D",
    full_refresh: bool = False,
    validate: bool = True,
    parallel: bool = True,
) -> dict[str, RefreshResult]:
    """Refresh all feature tables for a single tf."""
    results = {}
    start = None
    end = None

    logger.info(f"Starting feature refresh for {len(ids)} IDs, tf={tf}")
    logger.info(f"Mode: {'full' if full_refresh else 'incremental'}")

    # Phase 1: Returns, Vol, TA (can run in parallel)
    phase1_tasks = [
        ("returns", refresh_returns),
        ("vol", refresh_vol),
        ("ta", refresh_ta),
    ]

    if parallel:
        logger.info("Phase 1: Running returns/vol/ta in parallel")

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_name = {}
            for name, refresh_fn in phase1_tasks:
                future = executor.submit(refresh_fn, engine, ids, start, end, tf)
                future_to_name[future] = name

            for future in as_completed(future_to_name):
                name = future_to_name[future]
                result = future.result()
                results[result.table] = result

                if result.success:
                    logger.info(
                        f"  {result.table} (tf={tf}): {result.rows_inserted} rows in {result.duration_seconds:.1f}s"
                    )
                else:
                    logger.error(f"  {result.table} (tf={tf}): FAILED - {result.error}")

    else:
        logger.info("Phase 1: Running returns/vol/ta sequentially")

        for name, refresh_fn in phase1_tasks:
            result = refresh_fn(engine, ids, start, end, tf)
            results[result.table] = result

            if result.success:
                logger.info(
                    f"  {result.table} (tf={tf}): {result.rows_inserted} rows in {result.duration_seconds:.1f}s"
                )
            else:
                logger.error(f"  {result.table} (tf={tf}): FAILED - {result.error}")

    # Phase 2: Features store (depends on phase 1)
    logger.info("Phase 2: Running cmc_features (unified view)")

    result = refresh_features_store(engine, ids, start, end, tf)
    results[result.table] = result

    if result.success:
        logger.info(
            f"  {result.table} (tf={tf}): {result.rows_inserted} rows in {result.duration_seconds:.1f}s"
        )
    else:
        logger.error(f"  {result.table} (tf={tf}): FAILED - {result.error}")

    # Phase 3: Validation (if requested)
    if validate:
        logger.info("Phase 3: Running validation")

        try:
            from ta_lab2.scripts.features.validate_features import validate_features

            report = validate_features(
                engine,
                ids=ids[:5],
                alert=True,
            )

            if report.passed:
                logger.info(f"  Validation PASSED: {report.total_checks} checks")
            else:
                logger.warning(f"  Validation found issues: {report.summary}")

        except Exception as e:
            logger.error(f"  Validation failed with error: {e}", exc_info=True)

    return results


# =============================================================================
# CLI
# =============================================================================


def load_ids(engine, ids_arg: Optional[str], all_ids: bool) -> list[int]:
    """Load asset IDs to process."""
    if ids_arg:
        return [int(i.strip()) for i in ids_arg.split(",")]

    if all_ids:
        query = text(
            "SELECT DISTINCT id FROM public.cmc_price_bars_multi_tf ORDER BY id"
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
        help="Process all IDs from cmc_price_bars_multi_tf",
    )

    # Timeframe selection
    tf_group = parser.add_mutually_exclusive_group()
    tf_group.add_argument(
        "--tf",
        default="1D",
        help="Single timeframe to process (default: 1D)",
    )
    tf_group.add_argument(
        "--all-tfs",
        action="store_true",
        help="Process all timeframes with data in cmc_price_bars_multi_tf",
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

    # Determine timeframes
    if args.all_tfs:
        tfs = get_available_tfs(engine)
        logger.info(f"Processing all {len(tfs)} timeframes: {tfs}")
    else:
        tfs = [args.tf]
        logger.info(f"Processing timeframe: {args.tf}")

    # Run refreshes for each tf
    all_results = {}

    for tf in tfs:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing tf={tf}")
        logger.info(f"{'='*60}")

        try:
            results = run_all_refreshes(
                engine,
                ids=ids,
                tf=tf,
                full_refresh=args.full_refresh,
                validate=args.validate and (tf == tfs[-1]),  # validate on last tf only
                parallel=args.parallel,
            )
            all_results[tf] = results
        except Exception as e:
            logger.error(f"Refresh pipeline failed for tf={tf}: {e}", exc_info=True)
            all_results[tf] = {"error": str(e)}

    # Print summary
    print("\n" + "=" * 70)
    print("REFRESH SUMMARY")
    print("=" * 70)

    total_rows = 0
    total_duration = 0.0
    failures = []

    for tf, results in all_results.items():
        if isinstance(results, dict) and "error" in results:
            print(f"\n[tf={tf}] PIPELINE ERROR: {results['error']}")
            failures.append(f"{tf}/*")
            continue

        print(f"\n[tf={tf}]")
        for table in ["cmc_returns", "cmc_vol", "cmc_ta", "cmc_features"]:
            if table in results:
                result = results[table]
                status = "OK" if result.success else "FAILED"
                print(
                    f"  {table:30s} {status:10s} {result.rows_inserted:8d} rows in {result.duration_seconds:6.1f}s"
                )

                if result.success:
                    total_rows += result.rows_inserted
                    total_duration += result.duration_seconds
                else:
                    failures.append(f"{tf}/{table}")

    print("\n" + "=" * 70)
    print(f"Total: {total_rows} rows in {total_duration:.1f}s across {len(tfs)} TFs")

    if failures:
        print(f"Failures: {', '.join(failures)}")
        return 1

    print("All refreshes completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
