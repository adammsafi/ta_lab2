"""
Standalone CLI for CTF (Cross-Timeframe) feature refresh.

Computes cross-timeframe slope, divergence, agreement, and crossover features
from configured indicator pairs and writes results to public.ctf.

Usage examples:
    python -m ta_lab2.scripts.features.refresh_ctf --ids 1 --base-tf 1D
    python -m ta_lab2.scripts.features.refresh_ctf --ids 1 --base-tf 1D --log-level DEBUG
    python -m ta_lab2.scripts.features.refresh_ctf --ids 1 --base-tf 1D --dry-run
    python -m ta_lab2.scripts.features.refresh_ctf --ids 1 --base-tf 1D --full-refresh
    python -m ta_lab2.scripts.features.refresh_ctf --ids 1 --base-tf 1D --indicators rsi_14 macd_12_26
    python -m ta_lab2.scripts.features.refresh_ctf --ids 1 --base-tf 1D --ref-tfs 7D 30D
    python -m ta_lab2.scripts.features.refresh_ctf --ids 1,52 --base-tf 1D --workers 2
    python -m ta_lab2.scripts.features.refresh_ctf --all --base-tf 1D --workers 6
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import time
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from tqdm import tqdm

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.scripts.bars.common_snapshot_contract import get_engine

logger = logging.getLogger(__name__)


# =============================================================================
# Data structures
# =============================================================================


@dataclass(frozen=True)
class CTFWorkerTask:
    """Task spec passed to each multiprocessing worker."""

    asset_id: int
    db_url: str
    venue_id: int
    alignment_source: str
    yaml_path: Optional[str]
    base_tf_filter: Optional[list[str]]  # None = all from YAML
    ref_tf_filter: Optional[list[str]]  # None = all from YAML
    indicator_filter: Optional[list[str]]  # None = all active
    dry_run: bool


@dataclass
class CTFRefreshResult:
    """Result from a single asset worker."""

    asset_id: int
    rows_written: int
    duration_seconds: float
    error: Optional[str] = None
    skipped: bool = False


# Re-export RefreshResult for pipeline step compatibility
@dataclass
class RefreshResult:
    """Result of a single table refresh (compatible with run_all_feature_refreshes)."""

    table: str
    rows_inserted: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None


# =============================================================================
# State management
# =============================================================================


def _should_skip_asset(
    engine,
    asset_id: int,
    venue_id: int,
    alignment_source: str,
) -> bool:
    """Check if all ctf_state scopes for this asset are up-to-date.

    Simple per-asset watermark check: compares ctf.computed_at MAX for this
    asset against ctf_state.updated_at MIN.  If ctf_state is absent or stale,
    returns False (must recompute).  If all scopes are fresh, returns True.

    We use ctf_state.updated_at as the watermark and do a simple check:
    - No ctf_state rows for this asset → must compute (return False)
    - MIN(ctf_state.updated_at) >= MAX(ctf.computed_at) → all scopes fresh
    - Otherwise → at least one scope is stale, recompute all
    """
    sql_state = text(
        """
        SELECT MIN(updated_at) AS min_updated_at
        FROM public.ctf_state
        WHERE id = :id
          AND venue_id = :venue_id
          AND alignment_source = :as_
        """
    )
    sql_ctf = text(
        """
        SELECT MAX(computed_at) AS max_computed_at
        FROM public.ctf
        WHERE id = :id
          AND venue_id = :venue_id
          AND alignment_source = :as_
        """
    )
    try:
        with engine.connect() as conn:
            state_row = conn.execute(
                sql_state,
                {"id": asset_id, "venue_id": venue_id, "as_": alignment_source},
            ).fetchone()
            ctf_row = conn.execute(
                sql_ctf,
                {"id": asset_id, "venue_id": venue_id, "as_": alignment_source},
            ).fetchone()

        min_state_ts = state_row[0] if state_row else None
        max_ctf_ts = ctf_row[0] if ctf_row else None

        if min_state_ts is None:
            # Never computed or no state row — must compute
            return False

        if max_ctf_ts is None:
            # No CTF data at all — must compute
            return False

        # If state is newer than CTF data, assume all fresh
        skip = min_state_ts >= max_ctf_ts
        if skip:
            logger.debug(
                "_should_skip_asset: asset_id=%d is up-to-date (state=%s >= ctf=%s)",
                asset_id,
                min_state_ts,
                max_ctf_ts,
            )
        return skip

    except Exception as e:
        logger.warning(
            "_should_skip_asset: error checking state for asset_id=%d: %s",
            asset_id,
            e,
        )
        return False


def _update_ctf_state(
    engine,
    asset_id: int,
    venue_id: int,
    base_tf: str,
    ref_tf: str,
    indicator_id: int,
    alignment_source: str,
    last_ts,
    row_count: int,
) -> None:
    """Upsert a single ctf_state scope row after successful computation."""
    sql = text(
        """
        INSERT INTO public.ctf_state
            (id, venue_id, base_tf, ref_tf, indicator_id, alignment_source,
             last_ts, row_count, updated_at)
        VALUES
            (:id, :venue_id, :base_tf, :ref_tf, :indicator_id, :as_,
             :last_ts, :row_count, NOW() AT TIME ZONE 'UTC')
        ON CONFLICT (id, venue_id, base_tf, ref_tf, indicator_id, alignment_source)
        DO UPDATE SET
            last_ts    = EXCLUDED.last_ts,
            row_count  = EXCLUDED.row_count,
            updated_at = EXCLUDED.updated_at
        """
    )
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "id": asset_id,
                "venue_id": venue_id,
                "base_tf": base_tf,
                "ref_tf": ref_tf,
                "indicator_id": indicator_id,
                "as_": alignment_source,
                "last_ts": last_ts,
                "row_count": row_count,
            },
        )


def _reset_ctf_state(engine, ids: list[int], venue_id: int) -> None:
    """Delete ctf_state rows for the given IDs (used by --full-refresh)."""
    sql = text(
        """
        DELETE FROM public.ctf_state
        WHERE id = ANY(:ids) AND venue_id = :venue_id
        """
    )
    with engine.begin() as conn:
        result = conn.execute(sql, {"ids": ids, "venue_id": venue_id})
    logger.info(
        "_reset_ctf_state: deleted %d ctf_state rows for %d ids",
        result.rowcount,
        len(ids),
    )


def _delete_ctf_rows(engine, ids: list[int], venue_id: int) -> None:
    """Delete ctf fact rows for the given IDs (used by --full-refresh)."""
    sql = text(
        """
        DELETE FROM public.ctf
        WHERE id = ANY(:ids) AND venue_id = :venue_id
        """
    )
    with engine.begin() as conn:
        result = conn.execute(sql, {"ids": ids, "venue_id": venue_id})
    logger.info(
        "_delete_ctf_rows: deleted %d ctf rows for %d ids",
        result.rowcount,
        len(ids),
    )


# =============================================================================
# Module-level worker (must be at module level for pickling)
# =============================================================================


def _ctf_worker(task: CTFWorkerTask) -> dict:
    """Process CTF features for a single asset in a child process.

    MUST be a module-level function (not a method) for multiprocessing pickling.
    Creates its own NullPool engine and cleans up in finally block.

    Returns dict with keys: asset_id, rows, duration, error, skipped.
    """
    import logging as _logging
    import os

    # Re-configure logging in child process (inherited but sometimes silent)
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    _log = _logging.getLogger(__name__)

    from ta_lab2.features.cross_timeframe import CTFConfig, CTFFeature

    t0 = time.time()
    engine = None
    temp_yaml_path = None

    try:
        engine = create_engine(task.db_url, poolclass=NullPool, future=True)

        # Incremental skip check (skip entire asset if all scopes fresh)
        if not task.dry_run:
            if _should_skip_asset(
                engine, task.asset_id, task.venue_id, task.alignment_source
            ):
                _log.info(
                    "_ctf_worker: asset_id=%d is up-to-date, skipping",
                    task.asset_id,
                )
                return {
                    "asset_id": task.asset_id,
                    "rows": 0,
                    "duration": time.time() - t0,
                    "error": None,
                    "skipped": True,
                }

        # Determine effective YAML path (filter base_tf / ref_tf if requested)
        effective_yaml_path = task.yaml_path

        if task.base_tf_filter or task.ref_tf_filter:
            # Load YAML, filter timeframe_pairs in-memory, write filtered temp YAML
            try:
                import yaml as _yaml
            except ImportError:
                _yaml = None  # type: ignore[assignment]

            if _yaml is None:
                raise RuntimeError("PyYAML required for TF filtering")

            from ta_lab2.config import project_root as _project_root

            base_yaml_path = (
                Path(task.yaml_path)
                if task.yaml_path
                else _project_root() / "configs" / "ctf_config.yaml"
            )
            with base_yaml_path.open("r", encoding="utf-8") as f:
                cfg = _yaml.safe_load(f) or {}

            # Filter timeframe_pairs
            pairs = cfg.get("timeframe_pairs", [])
            filtered_pairs = []
            for pair in pairs:
                base_tf = pair.get("base_tf", "")
                if task.base_tf_filter and base_tf not in task.base_tf_filter:
                    continue
                ref_tfs = pair.get("ref_tfs", [])
                if task.ref_tf_filter:
                    ref_tfs = [r for r in ref_tfs if r in task.ref_tf_filter]
                if ref_tfs:
                    filtered_pairs.append({"base_tf": base_tf, "ref_tfs": ref_tfs})

            cfg["timeframe_pairs"] = filtered_pairs

            # Write to a temp file
            tmp_f = tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False, encoding="utf-8"
            )
            _yaml.dump(cfg, tmp_f)
            tmp_f.close()
            temp_yaml_path = tmp_f.name
            effective_yaml_path = temp_yaml_path

        config = CTFConfig(
            alignment_source=task.alignment_source,
            venue_id=task.venue_id,
            yaml_path=effective_yaml_path,
        )
        feature = CTFFeature(config=config, engine=engine)

        # Apply indicator filter by patching the cached dim_indicators list
        if task.indicator_filter:
            all_indicators = feature._load_dim_ctf_indicators()
            filter_set = set(task.indicator_filter)
            feature._dim_indicators = [
                ind for ind in all_indicators if ind["indicator_name"] in filter_set
            ]
            if not feature._dim_indicators:
                _log.warning(
                    "_ctf_worker: asset_id=%d -- no indicators match filter %s",
                    task.asset_id,
                    task.indicator_filter,
                )
                return {
                    "asset_id": task.asset_id,
                    "rows": 0,
                    "duration": time.time() - t0,
                    "error": None,
                    "skipped": False,
                }

        if task.dry_run:
            # Report what would be computed without writing
            yaml_cfg = feature._load_ctf_config()
            indicators = feature._load_dim_ctf_indicators()
            tf_pairs = yaml_cfg.get("timeframe_pairs", [])
            n_pairs = sum(len(p.get("ref_tfs", [])) for p in tf_pairs)
            n_indicators = len(indicators)
            _log.info(
                "[DRY RUN] asset_id=%d: would compute %d TF pairs x %d indicators = %d combos",
                task.asset_id,
                n_pairs,
                n_indicators,
                n_pairs * n_indicators,
            )
            return {
                "asset_id": task.asset_id,
                "rows": 0,
                "duration": time.time() - t0,
                "error": None,
                "skipped": False,
            }

        # Execute computation
        rows = feature.compute_for_ids(ids=[task.asset_id])

        # Update state watermarks for all computed scopes
        _post_update_ctf_state(
            engine, task.asset_id, task.venue_id, task.alignment_source
        )

        duration = time.time() - t0
        _log.info(
            "_ctf_worker: asset_id=%d complete rows=%d duration=%.1fs",
            task.asset_id,
            rows,
            duration,
        )
        return {
            "asset_id": task.asset_id,
            "rows": rows,
            "duration": duration,
            "error": None,
            "skipped": False,
        }

    except Exception as e:
        duration = time.time() - t0
        _log.error(
            "_ctf_worker: asset_id=%d FAILED: %s", task.asset_id, e, exc_info=True
        )
        return {
            "asset_id": task.asset_id,
            "rows": 0,
            "duration": duration,
            "error": str(e),
            "skipped": False,
        }

    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass
        if temp_yaml_path is not None:
            try:
                os.unlink(temp_yaml_path)
            except Exception:
                pass


def _post_update_ctf_state(
    engine,
    asset_id: int,
    venue_id: int,
    alignment_source: str,
) -> None:
    """Update ctf_state watermarks after a successful compute.

    Queries the ctf table for the distinct (base_tf, ref_tf, indicator_id)
    scopes for this asset and upserts ctf_state rows with MAX(ts) and COUNT(*).
    """
    sql = text(
        """
        SELECT
            base_tf,
            ref_tf,
            indicator_id,
            MAX(ts) AS last_ts,
            COUNT(*) AS row_count
        FROM public.ctf
        WHERE id = :id
          AND venue_id = :venue_id
          AND alignment_source = :as_
        GROUP BY base_tf, ref_tf, indicator_id
        """
    )
    upsert_sql = text(
        """
        INSERT INTO public.ctf_state
            (id, venue_id, base_tf, ref_tf, indicator_id, alignment_source,
             last_ts, row_count, updated_at)
        VALUES
            (:id, :venue_id, :base_tf, :ref_tf, :indicator_id, :as_,
             :last_ts, :row_count, NOW() AT TIME ZONE 'UTC')
        ON CONFLICT (id, venue_id, base_tf, ref_tf, indicator_id, alignment_source)
        DO UPDATE SET
            last_ts    = EXCLUDED.last_ts,
            row_count  = EXCLUDED.row_count,
            updated_at = EXCLUDED.updated_at
        """
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sql,
                {"id": asset_id, "venue_id": venue_id, "as_": alignment_source},
            ).fetchall()

        if not rows:
            return

        with engine.begin() as conn:
            for row in rows:
                conn.execute(
                    upsert_sql,
                    {
                        "id": asset_id,
                        "venue_id": venue_id,
                        "base_tf": row[0],
                        "ref_tf": row[1],
                        "indicator_id": row[2],
                        "as_": alignment_source,
                        "last_ts": row[3],
                        "row_count": row[4],
                    },
                )
        logger.debug(
            "_post_update_ctf_state: asset_id=%d updated %d scopes",
            asset_id,
            len(rows),
        )
    except Exception as e:
        logger.warning(
            "_post_update_ctf_state: asset_id=%d state update failed: %s",
            asset_id,
            e,
        )


# =============================================================================
# ID loading
# =============================================================================


def load_ids(
    engine,
    ids_arg: Optional[str],
    all_ids: bool,
    venue_id: int = 1,
) -> list[int]:
    """Load asset IDs to process.

    If --ids: parse comma-separated string.
    If --all: query distinct IDs from price_bars_multi_tf_u.
    """
    if ids_arg:
        return [int(i.strip()) for i in ids_arg.split(",")]

    if all_ids:
        query = text(
            "SELECT DISTINCT id FROM public.price_bars_multi_tf_u "
            "WHERE venue_id = :venue_id AND alignment_source = 'multi_tf' "
            "ORDER BY id"
        )
        with engine.connect() as conn:
            result = conn.execute(query, {"venue_id": venue_id})
            return [row[0] for row in result]

    return []


# =============================================================================
# CLI argument parsing
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for refresh_ctf."""
    parser = argparse.ArgumentParser(
        description="Standalone CTF feature refresh with multiprocessing and incremental state",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ID selection (mutually exclusive, required)
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument(
        "--ids",
        help="Comma-separated asset IDs to process (e.g. '1,52,1027')",
    )
    id_group.add_argument(
        "--all",
        action="store_true",
        help="Process all assets from price_bars_multi_tf_u",
    )

    # Timeframe filters
    parser.add_argument(
        "--base-tf",
        nargs="+",
        metavar="TF",
        default=None,
        help="Base timeframe(s) to process (e.g. --base-tf 1D 7D). Default: all from YAML.",
    )
    parser.add_argument(
        "--ref-tfs",
        nargs="+",
        metavar="TF",
        default=None,
        help="Reference timeframe(s) to filter (e.g. --ref-tfs 7D 30D). Default: all from YAML.",
    )

    # Indicator filter
    parser.add_argument(
        "--indicators",
        nargs="+",
        metavar="NAME",
        default=None,
        help="Indicator name(s) to compute (e.g. --indicators rsi_14 macd_12_26). Default: all active.",
    )

    # Refresh mode
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Delete existing CTF rows and reset state before recomputing.",
    )

    # Workers
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of multiprocessing workers. Default: min(6, cpu_count()).",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be computed without writing to the database.",
    )

    # Venue
    parser.add_argument(
        "--venue-id",
        type=int,
        default=1,
        help="Venue ID to process (default: 1 = CMC_AGG).",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )

    return parser.parse_args()


# =============================================================================
# Pipeline step (callable from run_all_feature_refreshes integration)
# =============================================================================


def refresh_ctf_step(
    engine,
    ids: list[int],
    tf: str = "1D",
    venue_id: int = 1,
    workers: Optional[int] = None,
    alignment_source: str = "multi_tf",
    dry_run: bool = False,
) -> RefreshResult:
    """Run CTF refresh as a pipeline step.

    Callable from run_all_feature_refreshes or any orchestrator.
    Takes engine and ids directly (no CLI parsing).

    Parameters
    ----------
    engine:
        SQLAlchemy engine for the main process (used for admin ops).
    ids:
        List of asset IDs to process.
    tf:
        Base timeframe filter (e.g. '1D'). Passed as base_tf_filter.
    venue_id:
        Venue ID filter.
    workers:
        Number of parallel workers. None = min(6, cpu_count()).
    alignment_source:
        Source alignment filter.
    dry_run:
        If True, report without writing.

    Returns
    -------
    RefreshResult with table='ctf', rows_inserted, duration_seconds, success, error.
    """
    t0 = time.time()
    db_url = str(TARGET_DB_URL)
    effective_workers = workers if workers is not None else min(6, cpu_count())

    tasks = [
        CTFWorkerTask(
            asset_id=asset_id,
            db_url=db_url,
            venue_id=venue_id,
            alignment_source=alignment_source,
            yaml_path=None,
            base_tf_filter=[tf] if tf else None,
            ref_tf_filter=None,
            indicator_filter=None,
            dry_run=dry_run,
        )
        for asset_id in ids
    ]

    total_rows, n_errors = _execute_tasks(tasks, effective_workers)
    duration = time.time() - t0

    if n_errors > 0:
        return RefreshResult(
            table="ctf",
            rows_inserted=total_rows,
            duration_seconds=duration,
            success=False,
            error=f"{n_errors} asset(s) failed",
        )
    return RefreshResult(
        table="ctf",
        rows_inserted=total_rows,
        duration_seconds=duration,
        success=True,
    )


def _execute_tasks(
    tasks: list[CTFWorkerTask], effective_workers: int
) -> tuple[int, int]:
    """Execute a list of CTFWorkerTasks with progress bar.

    Returns (total_rows, n_errors).
    """
    total_rows = 0
    n_errors = 0
    n_skipped = 0
    n_done = 0

    if effective_workers == 1 or len(tasks) == 1:
        # Sequential mode: wrap task list with tqdm
        for task in tqdm(tasks, desc="CTF refresh", unit="asset"):
            result = _ctf_worker(task)
            n_done += 1
            if result.get("skipped"):
                n_skipped += 1
            elif result.get("error"):
                n_errors += 1
                logger.warning(
                    "Asset %d failed: %s", result["asset_id"], result["error"]
                )
            else:
                total_rows += result.get("rows", 0)

            if n_done % 10 == 0:
                logger.info(
                    "Progress: %d/%d assets done, %d rows, %d skipped, %d errors",
                    n_done,
                    len(tasks),
                    total_rows,
                    n_skipped,
                    n_errors,
                )
    else:
        # Parallel mode: pool.imap_unordered + tqdm
        with Pool(processes=effective_workers, maxtasksperchild=1) as pool:
            results_iter = pool.imap_unordered(_ctf_worker, tasks)
            for result in tqdm(
                results_iter,
                total=len(tasks),
                desc="CTF refresh",
                unit="asset",
            ):
                n_done += 1
                if result.get("skipped"):
                    n_skipped += 1
                elif result.get("error"):
                    n_errors += 1
                    logger.warning(
                        "Asset %d failed: %s", result["asset_id"], result["error"]
                    )
                else:
                    total_rows += result.get("rows", 0)

                if n_done % 10 == 0:
                    logger.info(
                        "Progress: %d/%d assets done, %d rows, %d skipped, %d errors",
                        n_done,
                        len(tasks),
                        total_rows,
                        n_skipped,
                        n_errors,
                    )

    return total_rows, n_errors


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    """Main entry point for CTF refresh CLI."""
    args = parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Starting CTF feature refresh")

    if not TARGET_DB_URL:
        logger.error("TARGET_DB_URL not set. Configure db_config.env.")
        return 1

    engine = get_engine(str(TARGET_DB_URL))

    # Load IDs
    try:
        ids = load_ids(engine, args.ids, args.all, venue_id=args.venue_id)
    except Exception as e:
        logger.error("Failed to load IDs: %s", e, exc_info=True)
        return 1

    if not ids:
        logger.error("No IDs to process. Check --ids or --all.")
        return 1

    logger.info(
        "Processing %d IDs: %s%s",
        len(ids),
        ids[:10],
        "..." if len(ids) > 10 else "",
    )

    # Full refresh: delete existing rows and reset state first
    if args.full_refresh and not args.dry_run:
        logger.info(
            "--full-refresh: deleting CTF rows and resetting state for %d IDs", len(ids)
        )
        _delete_ctf_rows(engine, ids, args.venue_id)
        _reset_ctf_state(engine, ids, args.venue_id)

    # Determine effective workers
    effective_workers = (
        args.workers if args.workers is not None else min(6, cpu_count())
    )
    logger.info("Workers: %d (cpu_count=%d)", effective_workers, cpu_count())

    # Build task list (one task per asset)
    db_url = str(TARGET_DB_URL)
    tasks = [
        CTFWorkerTask(
            asset_id=asset_id,
            db_url=db_url,
            venue_id=args.venue_id,
            alignment_source="multi_tf",
            yaml_path=None,
            base_tf_filter=args.base_tf,
            ref_tf_filter=args.ref_tfs,
            indicator_filter=args.indicators,
            dry_run=args.dry_run,
        )
        for asset_id in ids
    ]

    t0 = time.time()
    total_rows, n_errors = _execute_tasks(tasks, effective_workers)
    duration = time.time() - t0

    # Print summary
    print("\n" + "=" * 70)
    print("CTF REFRESH SUMMARY")
    print("=" * 70)
    print(f"Assets processed : {len(ids)}")
    print(f"Total rows written: {total_rows}")
    print(f"Errors           : {n_errors}")
    print(f"Duration         : {duration:.1f}s")
    if args.dry_run:
        print("Mode             : DRY RUN (no data written)")
    print("=" * 70)

    if n_errors > 0:
        logger.warning("%d asset(s) failed during CTF refresh", n_errors)
        return 1

    logger.info("CTF refresh complete. rows=%d duration=%.1fs", total_rows, duration)
    return 0


if __name__ == "__main__":
    sys.exit(main())
