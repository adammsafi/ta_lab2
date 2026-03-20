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
1. vol (depends on price_bars_multi_tf)
2. ta (depends on price_bars_multi_tf)
3. features (depends on 1-2 + EMAs + bar returns)
4. features CS norms (depends on features having up-to-date ret_arith/rsi_14/vol columns)

Parallel execution where possible:
- vol, ta can run in parallel (same dependency)
- features runs after all complete
- CS norms run sequentially after features (window-function UPDATE, not insert)

Note: cmc_returns is deprecated; returns now come from returns_bars_multi_tf.
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

# CS norms import is optional — script may not exist in older deployments.
try:
    from ta_lab2.scripts.features.refresh_cs_norms import (
        refresh_cs_norms as _refresh_cs_norms,
    )

    _CS_NORMS_AVAILABLE = True
except ImportError:
    _CS_NORMS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning(
        "refresh_cs_norms not found; CS normalization step will be skipped. "
        "Run Plan 56-06 to create the module."
    )

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


def refresh_vol(
    engine,
    ids: list[int],
    start: Optional[str],
    end: Optional[str],
    tf: str = "1D",
    alignment_source: str = "multi_tf",
    venue_id: int | None = None,
) -> RefreshResult:
    """Refresh vol table for given tf + alignment_source."""
    from ta_lab2.scripts.features.vol_feature import VolatilityFeature, VolatilityConfig

    table = "vol"
    t0 = time.time()

    try:
        config = VolatilityConfig(
            tf=tf, alignment_source=alignment_source, venue_id=venue_id
        )
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
    engine,
    ids: list[int],
    start: Optional[str],
    end: Optional[str],
    tf: str = "1D",
    alignment_source: str = "multi_tf",
    venue_id: int | None = None,
) -> RefreshResult:
    """Refresh ta table for given tf + alignment_source."""
    from ta_lab2.scripts.features.ta_feature import TAFeature, TAConfig

    table = "ta"
    t0 = time.time()

    try:
        config = TAConfig(tf=tf, alignment_source=alignment_source, venue_id=venue_id)
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


def refresh_cycle_stats(
    engine,
    ids: list[int],
    start: Optional[str],
    end: Optional[str],
    tf: str = "1D",
    alignment_source: str = "multi_tf",
    venue_id: int | None = None,
) -> RefreshResult:
    """Refresh cycle_stats table for given tf + alignment_source."""
    from ta_lab2.scripts.features.cycle_stats_feature import (
        CycleStatsFeature,
        CycleStatsConfig,
    )

    table = "cycle_stats"
    t0 = time.time()

    try:
        config = CycleStatsConfig(
            tf=tf, alignment_source=alignment_source, venue_id=venue_id
        )
        feature = CycleStatsFeature(engine, config)
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
        logger.error(f"Cycle stats refresh failed (tf={tf}): {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


def refresh_rolling_extremes(
    engine,
    ids: list[int],
    start: Optional[str],
    end: Optional[str],
    tf: str = "1D",
    alignment_source: str = "multi_tf",
    venue_id: int | None = None,
) -> RefreshResult:
    """Refresh rolling_extremes table for given tf + alignment_source."""
    from ta_lab2.scripts.features.rolling_extremes_feature import (
        RollingExtremesFeature,
        RollingExtremesConfig,
    )

    table = "rolling_extremes"
    t0 = time.time()

    try:
        config = RollingExtremesConfig(
            tf=tf, alignment_source=alignment_source, venue_id=venue_id
        )
        feature = RollingExtremesFeature(engine, config)
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
        logger.error(f"Rolling extremes refresh failed (tf={tf}): {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


def refresh_microstructure(
    engine,
    ids: list[int],
    start: Optional[str],
    end: Optional[str],
    tf: str = "1D",
    alignment_source: str = "multi_tf",
    venue_id: int | None = None,
) -> RefreshResult:
    """Refresh microstructure columns in features for given tf."""
    from ta_lab2.scripts.features.microstructure_feature import (
        MicrostructureFeature,
        MicrostructureConfig,
    )

    table = "features (microstructure)"
    t0 = time.time()

    try:
        config = MicrostructureConfig(
            tf=tf, alignment_source=alignment_source, venue_id=venue_id
        )
        feature = MicrostructureFeature(engine, config)
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
        logger.error(f"Microstructure refresh failed (tf={tf}): {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


def refresh_features_store(
    engine,
    ids: list[int],
    start: Optional[str],
    end: Optional[str],
    tf: str = "1D",
    alignment_source: str = "multi_tf",
    venue_id: int | None = None,
) -> RefreshResult:
    """Refresh features table for given tf + alignment_source."""
    from ta_lab2.scripts.features.daily_features_view import refresh_features

    table = "features"
    t0 = time.time()

    try:
        rows_written = refresh_features(
            engine,
            ids=ids,
            tf=tf,
            alignment_source=alignment_source,
            full_refresh=False,
            venue_id=venue_id,
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
        logger.error(f"Features store refresh failed (tf={tf}): {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=duration,
            success=False,
            error=str(e),
        )


def refresh_cs_norms_step(engine, tf: str = "1D") -> RefreshResult:
    """Refresh cross-sectional normalization columns in features.

    Runs after features refresh (depends on up-to-date ret_arith, rsi_14,
    vol_parkinson_20 values).  Returns a RefreshResult whose rows_inserted is
    the sum of cursor.rowcount from all 3 UPDATE statements (int, never None).
    """
    table = "features (CS norms)"
    t0 = time.time()

    if not _CS_NORMS_AVAILABLE:
        logger.warning("CS norms step skipped: refresh_cs_norms module not available")
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=time.time() - t0,
            success=False,
            error="refresh_cs_norms module not available",
        )

    try:
        rows = _refresh_cs_norms(engine, tf)  # returns int (sum of rowcounts)
        return RefreshResult(
            table=table,
            rows_inserted=rows,
            duration_seconds=time.time() - t0,
            success=True,
        )
    except Exception as e:
        logger.error(f"CS norms refresh failed (tf={tf}): {e}", exc_info=True)
        return RefreshResult(
            table=table,
            rows_inserted=0,
            duration_seconds=time.time() - t0,
            success=False,
            error=str(e),
        )


# =============================================================================
# Orchestration
# =============================================================================


def get_available_tf_alignments(engine) -> list[tuple[str, str]]:
    """Query distinct (tf, alignment_source) pairs from _u table.

    Uses DISTINCT ON (tf) to pick one alignment_source per tf
    (month/year calendar TFs appear with both _iso and _us but bars
    are identical).
    """
    query = text(
        """
        SELECT DISTINCT ON (tf) tf, alignment_source
        FROM public.price_bars_multi_tf_u
        ORDER BY tf, alignment_source
        """
    )
    with engine.connect() as conn:
        return [(row[0], row[1]) for row in conn.execute(query)]


def run_all_refreshes(
    engine,
    ids: list[int],
    tf: str = "1D",
    alignment_source: str = "multi_tf",
    full_refresh: bool = False,
    validate: bool = True,
    parallel: bool = True,
    codependence: bool = False,
    venue_id: int | None = None,
    skip_cs_norms: bool = False,
) -> dict[str, RefreshResult]:
    """Refresh all feature tables for a single (tf, alignment_source)."""
    results = {}
    start = None
    end = None

    logger.info(
        f"Starting feature refresh for {len(ids)} IDs,"
        f" tf={tf}, alignment_source={alignment_source}"
    )
    logger.info(f"Mode: {'full' if full_refresh else 'incremental'}")

    # Phase 1: Vol, TA, Cycle Stats, Rolling Extremes (can run in parallel)
    phase1_tasks = [
        ("vol", refresh_vol),
        ("ta", refresh_ta),
        ("cycle_stats", refresh_cycle_stats),
        ("rolling_extremes", refresh_rolling_extremes),
    ]

    if parallel:
        logger.info("Phase 1: Running vol/ta in parallel")

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_name = {}
            for name, refresh_fn in phase1_tasks:
                future = executor.submit(
                    refresh_fn,
                    engine,
                    ids,
                    start,
                    end,
                    tf,
                    alignment_source,
                    venue_id=venue_id,
                )
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
        logger.info("Phase 1: Running vol/ta sequentially")

        for name, refresh_fn in phase1_tasks:
            result = refresh_fn(
                engine, ids, start, end, tf, alignment_source, venue_id=venue_id
            )
            results[result.table] = result

            if result.success:
                logger.info(
                    f"  {result.table} (tf={tf}): {result.rows_inserted} rows in {result.duration_seconds:.1f}s"
                )
            else:
                logger.error(f"  {result.table} (tf={tf}): FAILED - {result.error}")

    # Phase 2: Features store (depends on phase 1)
    logger.info("Phase 2: Running features (unified view)")

    result = refresh_features_store(
        engine, ids, start, end, tf, alignment_source, venue_id=venue_id
    )
    results[result.table] = result

    if result.success:
        logger.info(
            f"  {result.table} (tf={tf}): {result.rows_inserted} rows in {result.duration_seconds:.1f}s"
        )
    else:
        logger.error(f"  {result.table} (tf={tf}): FAILED - {result.error}")

    # Phase 2b: Microstructure UPDATE (supplemental columns on features rows)
    # MUST run after Phase 2 — microstructure does UPDATE on existing rows,
    # so the base rows from features must exist first.
    logger.info("Phase 2b: Running microstructure feature UPDATE on features")

    micro_result = refresh_microstructure(
        engine, ids, start, end, tf, alignment_source, venue_id=venue_id
    )
    results[micro_result.table] = micro_result

    if micro_result.success:
        logger.info(
            f"  {micro_result.table} (tf={tf}): {micro_result.rows_inserted} rows"
            f" in {micro_result.duration_seconds:.1f}s"
        )
    else:
        logger.error(f"  {micro_result.table} (tf={tf}): FAILED - {micro_result.error}")

    # Phase 3: Cross-sectional normalization (depends on features)
    # MUST run sequentially after features — window functions read the
    # freshly-written ret_arith / rsi_14 / vol_parkinson_20 values.
    if skip_cs_norms:
        logger.info("Phase 3: Skipping CS norms (--no-cs-norms)")
        cs_result = RefreshResult(
            table="features (CS norms)",
            rows_inserted=0,
            duration_seconds=0.0,
            success=True,
            error="skipped",
        )
    else:
        logger.info("Phase 3: Refreshing cross-sectional normalizations (CS norms)")
        cs_result = refresh_cs_norms_step(engine, tf=tf)
    results[cs_result.table] = cs_result

    if cs_result.success:
        logger.info(
            f"  {cs_result.table} (tf={tf}): {cs_result.rows_inserted} rows"
            f" in {cs_result.duration_seconds:.1f}s"
        )
    else:
        logger.error(f"  {cs_result.table} (tf={tf}): FAILED - {cs_result.error}")

    # Phase 3b: Codependence (optional, pairwise metrics — ~3 min for all assets)
    if codependence:
        logger.info("Phase 3b: Running codependence refresh (pairwise metrics)")

        t0_co = time.time()
        try:
            from ta_lab2.scripts.features.codependence_feature import (
                refresh_codependence,
            )

            n_pairs = refresh_codependence(engine, ids=ids, tf=tf)
            duration_co = time.time() - t0_co

            co_result = RefreshResult(
                table="cmc_codependence",
                rows_inserted=n_pairs,
                duration_seconds=duration_co,
                success=True,
            )
        except Exception as e:
            duration_co = time.time() - t0_co
            logger.error(f"Codependence refresh failed (tf={tf}): {e}", exc_info=True)
            co_result = RefreshResult(
                table="cmc_codependence",
                rows_inserted=0,
                duration_seconds=duration_co,
                success=False,
                error=str(e),
            )

        results[co_result.table] = co_result

        if co_result.success:
            logger.info(
                f"  {co_result.table} (tf={tf}): {co_result.rows_inserted} pairs"
                f" in {co_result.duration_seconds:.1f}s"
            )
        else:
            logger.error(f"  {co_result.table} (tf={tf}): FAILED - {co_result.error}")

    # Phase 4: Validation (if requested)
    if validate:
        logger.info("Phase 4: Running validation")

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
# Parallel TF helpers
# =============================================================================


def _should_skip_tf(engine, tf: str, alignment_source: str) -> bool:
    """Check if source bars have changed since last features refresh.

    Returns True if features are up-to-date (skip), False if refresh needed.
    """
    sql_source = text("""
        SELECT MAX(ingested_at) AS latest_source
        FROM public.price_bars_multi_tf_u
        WHERE tf = :tf AND alignment_source = :as_
    """)
    sql_feature = text("""
        SELECT MAX(updated_at) AS latest_feature
        FROM public.feature_state
        WHERE feature_type = 'daily_features'
          AND feature_name = :tf
    """)
    with engine.connect() as conn:
        source_ts = conn.execute(
            sql_source, {"tf": tf, "as_": alignment_source}
        ).scalar()
    with engine.connect() as conn:
        feature_ts = conn.execute(sql_feature, {"tf": tf}).scalar()

    if source_ts is None:
        return True  # No source data, skip
    if feature_ts is None:
        return False  # Never computed, must run
    return feature_ts >= source_ts  # Skip if features are newer than source


def _run_single_tf(args_tuple):
    """Worker: process one (tf, alignment_source) in a child process.

    Creates its own NullPool engine (Windows multiprocessing safety).
    Returns (tf, alignment_source, results_dict).
    """
    (
        db_url,
        ids,
        tf,
        alignment_source,
        full_refresh,
        parallel,
        codependence,
        venue_id,
        skip_cs_norms,
    ) = args_tuple

    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    engine = create_engine(db_url, poolclass=NullPool, future=True)
    try:
        # In incremental mode, check if source data has changed
        if not full_refresh and _should_skip_tf(engine, tf, alignment_source):
            return (tf, alignment_source, {"skipped": True})

        results = run_all_refreshes(
            engine,
            ids=ids,
            tf=tf,
            alignment_source=alignment_source,
            full_refresh=full_refresh,
            validate=False,  # validate once at end, not per-worker
            parallel=parallel,
            codependence=codependence,
            venue_id=venue_id,
            skip_cs_norms=skip_cs_norms,
        )
        return (tf, alignment_source, results)
    except Exception as e:
        logging.getLogger(__name__).error(
            f"Worker failed for tf={tf}, as={alignment_source}: {e}",
            exc_info=True,
        )
        return (tf, alignment_source, {"error": str(e)})
    finally:
        engine.dispose()


# =============================================================================
# CLI
# =============================================================================


def load_ids(
    engine, ids_arg: Optional[str], all_ids: bool, venue_id: int | None = None
) -> list[int]:
    """Load asset IDs to process.

    Args:
        engine: SQLAlchemy engine.
        ids_arg: Comma-separated ID string from CLI.
        all_ids: If True, query all IDs from the database.
        venue_id: If specified with all_ids, filter to IDs present in
            price_bars_multi_tf for this venue_id (instead of _u table).
    """
    if ids_arg:
        return [int(i.strip()) for i in ids_arg.split(",")]

    if all_ids:
        if venue_id is not None:
            query = text(
                "SELECT DISTINCT id FROM public.price_bars_multi_tf "
                "WHERE venue_id = :venue_id ORDER BY id"
            )
            with engine.connect() as conn:
                result = conn.execute(query, {"venue_id": venue_id})
                return [row[0] for row in result]
        else:
            query = text(
                "SELECT DISTINCT id FROM public.price_bars_multi_tf_u ORDER BY id"
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
        help="Process all IDs from price_bars_multi_tf",
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
        help="Process all timeframes with data in price_bars_multi_tf",
    )

    # Codependence (optional batch step)
    parser.add_argument(
        "--codependence",
        action="store_true",
        help="Also refresh cmc_codependence (pairwise, ~3 min for all assets)",
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

    # Venue filter
    parser.add_argument(
        "--venue-id",
        type=int,
        default=None,
        help="Filter to IDs for this venue_id (e.g., 2 for HYPERLIQUID).",
    )

    # TF-level parallelism
    parser.add_argument(
        "--tf-workers",
        type=int,
        default=1,
        help="Number of parallel TF workers (default: 1 = sequential). Max ~4.",
    )

    # CS norms
    parser.add_argument(
        "--no-cs-norms",
        action="store_true",
        default=False,
        help="Skip cross-sectional normalization step (slow on large tables).",
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
        ids = load_ids(engine, args.ids, args.all, venue_id=args.venue_id)
    except Exception as e:
        logger.error(f"Failed to load IDs: {e}", exc_info=True)
        return 1

    if not ids:
        logger.error("No IDs to process")
        return 1

    logger.info(
        f"Processing {len(ids)} IDs: {ids[:10]}{'...' if len(ids) > 10 else ''}"
    )

    # Determine (tf, alignment_source) pairs
    if args.all_tfs:
        tf_alignments = get_available_tf_alignments(engine)
        logger.info(
            f"Processing all {len(tf_alignments)} (tf, alignment_source) pairs:"
            f" {tf_alignments}"
        )
    else:
        # Look up alignment_source for the specified tf
        query = text(
            """
            SELECT DISTINCT ON (tf) alignment_source
            FROM public.price_bars_multi_tf_u WHERE tf = :tf
            ORDER BY tf, alignment_source
            """
        )
        with engine.connect() as conn:
            row = conn.execute(query, {"tf": args.tf}).fetchone()
            alignment_source = row[0] if row else "multi_tf"
        tf_alignments = [(args.tf, alignment_source)]
        logger.info(
            f"Processing timeframe: {args.tf} (alignment_source={alignment_source})"
        )

    # Run refreshes for each (tf, alignment_source)
    all_results = {}
    db_url = str(TARGET_DB_URL)

    if args.tf_workers > 1 and len(tf_alignments) > 1:
        from concurrent.futures import ProcessPoolExecutor

        logger.info(
            f"Parallel mode: {args.tf_workers} TF workers for"
            f" {len(tf_alignments)} (tf, alignment_source) pairs"
        )

        work_items = [
            (
                db_url,
                ids,
                tf,
                as_,
                args.full_refresh,
                args.parallel,
                getattr(args, "codependence", False),
                args.venue_id,
                getattr(args, "no_cs_norms", False),
            )
            for tf, as_ in tf_alignments
        ]

        with ProcessPoolExecutor(
            max_workers=args.tf_workers,
            max_tasks_per_child=1,
        ) as pool:
            for tf, as_, results in pool.map(_run_single_tf, work_items):
                if isinstance(results, dict) and results.get("skipped"):
                    logger.info(f"Skipped tf={tf} as={as_} (up-to-date)")
                else:
                    all_results[(tf, as_)] = results
                    logger.info(f"Completed tf={tf} alignment_source={as_}")

        # Run validation once at the end if requested
        if args.validate and all_results:
            logger.info("Running final validation (post-parallel)")
            try:
                from ta_lab2.scripts.features.validate_features import (
                    validate_features,
                )

                report = validate_features(engine, ids=ids[:5], alert=True)
                if report.passed:
                    logger.info(f"  Validation PASSED: {report.total_checks} checks")
                else:
                    logger.warning(f"  Validation found issues: {report.summary}")
            except Exception as e:
                logger.error(f"  Validation failed with error: {e}", exc_info=True)

    else:
        for tf, alignment_source in tf_alignments:
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Processing tf={tf}, alignment_source={alignment_source}")
            logger.info(f"{'=' * 60}")

            # In incremental mode (no --full-refresh), check watermark
            if not args.full_refresh and _should_skip_tf(engine, tf, alignment_source):
                logger.info(f"Skipped tf={tf} as={alignment_source} (up-to-date)")
                continue

            try:
                results = run_all_refreshes(
                    engine,
                    ids=ids,
                    tf=tf,
                    alignment_source=alignment_source,
                    full_refresh=args.full_refresh,
                    validate=args.validate
                    and ((tf, alignment_source) == tf_alignments[-1]),
                    parallel=args.parallel,
                    codependence=getattr(args, "codependence", False),
                    venue_id=args.venue_id,
                    skip_cs_norms=getattr(args, "no_cs_norms", False),
                )
                all_results[(tf, alignment_source)] = results
            except Exception as e:
                logger.error(f"Refresh pipeline failed for tf={tf}: {e}", exc_info=True)
                all_results[(tf, alignment_source)] = {"error": str(e)}

    # Print summary
    print("\n" + "=" * 70)
    print("REFRESH SUMMARY")
    print("=" * 70)

    total_rows = 0
    total_duration = 0.0
    failures = []

    for key, results in all_results.items():
        # key is (tf, alignment_source) tuple
        tf_label = f"{key[0]}|{key[1]}" if isinstance(key, tuple) else str(key)

        if isinstance(results, dict) and "error" in results:
            print(f"\n[{tf_label}] PIPELINE ERROR: {results['error']}")
            failures.append(f"{tf_label}/*")
            continue

        print(f"\n[{tf_label}]")
        for table in [
            "vol",
            "ta",
            "cycle_stats",
            "rolling_extremes",
            "features (microstructure)",
            "features",
            "features (CS norms)",
            "cmc_codependence",
        ]:
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
                    failures.append(f"{tf_label}/{table}")

    print("\n" + "=" * 70)
    print(
        f"Total: {total_rows} rows in {total_duration:.1f}s"
        f" across {len(tf_alignments)} TFs"
    )

    if failures:
        print(f"Failures: {', '.join(failures)}")
        return 1

    print("All refreshes completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
