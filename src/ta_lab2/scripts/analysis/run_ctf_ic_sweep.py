"""
Batch IC sweep for Cross-Timeframe (CTF) features across all assets x base TFs.

Loads CTF pivot features via load_ctf_features(), computes IC for all feature
columns using batch_compute_ic(), and persists results to ic_results.

Usage:
    python -m ta_lab2.scripts.analysis.run_ctf_ic_sweep --all
    python -m ta_lab2.scripts.analysis.run_ctf_ic_sweep --assets 1 1027 --base-tf 1D
    python -m ta_lab2.scripts.analysis.run_ctf_ic_sweep --dry-run --min-bars 500
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from multiprocessing import Pool

import pandas as pd
from sqlalchemy import create_engine, pool, text
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.ic import batch_compute_ic, save_ic_results
from ta_lab2.analysis.multiple_testing import log_trials_to_registry
from ta_lab2.features.cross_timeframe import load_ctf_features
from ta_lab2.scripts.refresh_utils import resolve_db_url
from ta_lab2.time.dim_timeframe import DimTimeframe

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Picklable worker task (frozen dataclass — MANDATORY for Windows spawn)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CTFICWorkerTask:
    """
    Task for a single CTF IC sweep worker process.

    Frozen dataclass with only picklable types (no engine/connection objects).
    Each worker creates its own NullPool engine from db_url.
    """

    asset_id: int
    base_tf: str
    n_rows: int
    db_url: str
    horizons: tuple  # tuple[int, ...] for pickling
    return_types: tuple  # tuple[str, ...]
    rolling_window: int
    tf_days_nominal: int
    overwrite: bool


# ---------------------------------------------------------------------------
# Timestamp utilities
# ---------------------------------------------------------------------------


def _to_utc_timestamp(val) -> pd.Timestamp:
    """
    Convert a DB-returned timestamp value to a tz-aware UTC pd.Timestamp.

    SQLAlchemy may return tz-aware or tz-naive datetimes depending on DB driver.
    - tz-aware: use tz_convert("UTC")
    - tz-naive: assume UTC and tz_localize("UTC")
    """
    ts = pd.Timestamp(val)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _discover_ctf_pairs(
    engine,
    min_bars: int,
    asset_ids_filter=None,
    base_tf_filter=None,
) -> list[tuple[int, str, int]]:
    """
    Discover qualifying (asset_id, base_tf) pairs from the ctf table.

    Returns list of (asset_id, base_tf, n_ts) tuples with n_ts >= min_bars.
    Filters by asset_ids_filter and base_tf_filter when provided.
    """
    with engine.connect() as conn:
        sql = text(
            """
            SELECT id AS asset_id, base_tf, COUNT(DISTINCT ts) AS n_ts
            FROM public.ctf
            WHERE alignment_source = 'multi_tf'
              AND venue_id = 1
            GROUP BY id, base_tf
            HAVING COUNT(DISTINCT ts) >= :min_bars
            ORDER BY id, base_tf
            """
        )
        df = pd.read_sql(sql, conn, params={"min_bars": min_bars})

    if df.empty:
        logger.info(
            "ctf: no qualifying (asset_id, base_tf) pairs with >= %d rows", min_bars
        )
        return []

    pairs = list(zip(df["asset_id"], df["base_tf"], df["n_ts"]))

    # Apply optional filters
    if asset_ids_filter is not None:
        asset_ids_set = set(asset_ids_filter)
        pairs = [(aid, btf, n) for aid, btf, n in pairs if aid in asset_ids_set]

    if base_tf_filter is not None:
        base_tf_set = set(base_tf_filter)
        pairs = [(aid, btf, n) for aid, btf, n in pairs if btf in base_tf_set]

    logger.info(
        "ctf: %d qualifying (asset_id, base_tf) pairs with >= %d rows (after filter)",
        len(pairs),
        min_bars,
    )
    return pairs


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_close_for_asset(conn, asset_id: int, base_tf: str) -> pd.Series:
    """
    Load close prices from features table for a given asset + base_tf.

    Filters by venue_id=1 (CMC_AGG) to avoid duplicate ts rows when multiple
    venues exist in the features table PK (id, venue_id, ts, tf).

    Returns pd.Series indexed by UTC timestamps.
    """
    sql = text(
        """
        SELECT ts, close
        FROM public.features
        WHERE id = :asset_id AND tf = :base_tf AND venue_id = 1
        ORDER BY ts
        """
    )
    df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "base_tf": base_tf})

    if df.empty:
        return pd.Series(dtype=float)

    # CRITICAL: fix mixed-tz-offset object dtype from pd.read_sql on Windows
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    return df["close"].copy()


def _get_train_window(
    conn, asset_id: int, base_tf: str
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Get the train window (min ts, max ts) for a given asset + base_tf in ctf.

    Returns (train_start, train_end) as UTC-aware pd.Timestamps.
    """
    sql = text(
        """
        SELECT MIN(ts) AS train_start, MAX(ts) AS train_end
        FROM public.ctf
        WHERE id = :asset_id
          AND base_tf = :base_tf
          AND alignment_source = 'multi_tf'
          AND venue_id = 1
        """
    )
    result = conn.execute(sql, {"asset_id": asset_id, "base_tf": base_tf})
    row = result.fetchone()

    if row is None or row[0] is None:
        raise ValueError(f"No CTF rows found for asset_id={asset_id} base_tf={base_tf}")

    return _to_utc_timestamp(row[0]), _to_utc_timestamp(row[1])


# ---------------------------------------------------------------------------
# IC row conversion helper
# ---------------------------------------------------------------------------


def _to_python(v):
    """
    Normalize a value for SQL binding.

    - numpy scalars -> Python float/int via .item()
    - pd.Timestamp -> Python datetime
    - NaN float -> None (SQL NULL)
    - Everything else: unchanged
    """
    if hasattr(v, "item"):
        # numpy scalar (float32, float64, int32, int64, etc.)
        v = v.item()
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    try:
        import math

        if math.isnan(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _rows_from_ic_df(
    ic_df: pd.DataFrame,
    asset_id: int,
    base_tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    tf_days_nominal: int,
) -> list[dict]:
    """
    Convert an IC result DataFrame into a list of dicts for save_ic_results().

    Each row dict contains: asset_id, tf (=base_tf), feature, horizon, horizon_days,
    return_type, regime_col, regime_label, ic, ic_t_stat, ic_p_value, ic_ir,
    ic_ir_t_stat, turnover, n_obs, train_start, train_end.
    """
    rows = []
    for _, row in ic_df.iterrows():
        r_col = row.get("regime_col", "all")
        r_label = row.get("regime_label", "all")

        rows.append(
            {
                "asset_id": asset_id,
                "tf": base_tf,
                "feature": row["feature"],
                "horizon": int(row["horizon"]),
                "horizon_days": int(row["horizon"]) * tf_days_nominal,
                "return_type": row["return_type"],
                "regime_col": r_col if pd.notna(r_col) else "all",
                "regime_label": r_label if pd.notna(r_label) else "all",
                "train_start": train_start,
                "train_end": train_end,
                "ic": row.get("ic"),
                "ic_t_stat": row.get("ic_t_stat"),
                "ic_p_value": row.get("ic_p_value"),
                "ic_ir": row.get("ic_ir"),
                "ic_ir_t_stat": row.get("ic_ir_t_stat"),
                "turnover": row.get("turnover"),
                "n_obs": row.get("n_obs"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Module-level worker function (must be picklable for Windows `spawn`)
# ---------------------------------------------------------------------------


def _ctf_ic_worker(task: CTFICWorkerTask) -> dict:
    """
    Worker function for parallel CTF IC sweep.

    Called by multiprocessing.Pool.imap_unordered(). Must be module-level
    for pickling to work on Windows (spawn start method).

    Creates its own engine with NullPool to prevent connection pooling
    issues across processes.

    Returns dict with {asset_id, base_tf, n_features, n_ic_rows, elapsed_s, error}.
    """
    _logger = logging.getLogger(f"ctf_ic_worker.{task.asset_id}.{task.base_tf}")
    pair_start = time.time()
    engine = None
    try:
        engine = create_engine(task.db_url, poolclass=NullPool)
        horizons = list(task.horizons)
        return_types = list(task.return_types)

        with engine.begin() as conn:
            # Get train window from ctf table
            train_start, train_end = _get_train_window(
                conn, task.asset_id, task.base_tf
            )

            # Load CTF pivot features
            ctf_df = load_ctf_features(
                conn,
                task.asset_id,
                task.base_tf,
                train_start,
                train_end,
            )

            if ctf_df.empty:
                _logger.warning(
                    "No CTF pivot features for asset_id=%d base_tf=%s — skipping",
                    task.asset_id,
                    task.base_tf,
                )
                return {
                    "asset_id": task.asset_id,
                    "base_tf": task.base_tf,
                    "n_features": 0,
                    "n_ic_rows": 0,
                    "elapsed_s": time.time() - pair_start,
                    "error": None,
                }

            # Load close prices for this asset + base_tf
            close = _load_close_for_asset(conn, task.asset_id, task.base_tf)

            if close.empty:
                _logger.warning(
                    "No close prices for asset_id=%d base_tf=%s — skipping",
                    task.asset_id,
                    task.base_tf,
                )
                return {
                    "asset_id": task.asset_id,
                    "base_tf": task.base_tf,
                    "n_features": 0,
                    "n_ic_rows": 0,
                    "elapsed_s": time.time() - pair_start,
                    "error": None,
                }

            # Pre-filter: drop columns where notna count < 50
            valid_cols = [c for c in ctf_df.columns if ctf_df[c].notna().sum() >= 50]
            if not valid_cols:
                _logger.warning(
                    "All CTF columns sparse for asset_id=%d base_tf=%s — skipping",
                    task.asset_id,
                    task.base_tf,
                )
                return {
                    "asset_id": task.asset_id,
                    "base_tf": task.base_tf,
                    "n_features": 0,
                    "n_ic_rows": 0,
                    "elapsed_s": time.time() - pair_start,
                    "error": None,
                }

            ctf_df = ctf_df[valid_cols]
            n_features = len(valid_cols)

            # Compute IC for all CTF pivot features
            ic_df = batch_compute_ic(
                ctf_df,
                close,
                train_start,
                train_end,
                feature_cols=valid_cols,
                horizons=horizons,
                return_types=return_types,
                rolling_window=task.rolling_window,
                tf_days_nominal=task.tf_days_nominal,
            )

            if ic_df.empty:
                _logger.info(
                    "No IC results for asset_id=%d base_tf=%s",
                    task.asset_id,
                    task.base_tf,
                )
                return {
                    "asset_id": task.asset_id,
                    "base_tf": task.base_tf,
                    "n_features": n_features,
                    "n_ic_rows": 0,
                    "elapsed_s": time.time() - pair_start,
                    "error": None,
                }

            # Add regime sentinels (CTF sweep does not compute regime-conditional IC)
            if "regime_col" not in ic_df.columns:
                ic_df["regime_col"] = "all"
            if "regime_label" not in ic_df.columns:
                ic_df["regime_label"] = "all"

            # Convert IC DataFrame to rows
            ic_rows = _rows_from_ic_df(
                ic_df,
                task.asset_id,
                task.base_tf,
                train_start,
                train_end,
                task.tf_days_nominal,
            )

            # Persist to ic_results
            n_written = 0
            if ic_rows:
                n_written = save_ic_results(conn, ic_rows, overwrite=task.overwrite)
                try:
                    n_logged = log_trials_to_registry(
                        conn, ic_rows, source_table="ic_results"
                    )
                    _logger.debug("Logged %d trials to trial_registry", n_logged)
                except Exception:
                    _logger.warning(
                        "Failed to log trials to trial_registry", exc_info=True
                    )

            elapsed = time.time() - pair_start
            _logger.info(
                "asset_id=%d base_tf=%s: %d features, %d IC rows in %.1fs",
                task.asset_id,
                task.base_tf,
                n_features,
                n_written,
                elapsed,
            )
            return {
                "asset_id": task.asset_id,
                "base_tf": task.base_tf,
                "n_features": n_features,
                "n_ic_rows": n_written,
                "elapsed_s": elapsed,
                "error": None,
            }

    except Exception as exc:
        elapsed = time.time() - pair_start
        _logger.error(
            "Failed asset_id=%d base_tf=%s: %s",
            task.asset_id,
            task.base_tf,
            exc,
            exc_info=True,
        )
        return {
            "asset_id": task.asset_id,
            "base_tf": task.base_tf,
            "n_features": 0,
            "n_ic_rows": 0,
            "elapsed_s": elapsed,
            "error": str(exc),
        }
    finally:
        if engine is not None:
            engine.dispose()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_ctf_ic_sweep",
        description=(
            "Batch IC sweep for Cross-Timeframe (CTF) features across all assets x base TFs.\n\n"
            "Loads CTF pivot features via load_ctf_features(), computes IC for all feature\n"
            "columns using batch_compute_ic(), and persists results to ic_results."
        ),
    )

    # Scope selection
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_assets",
        help="Full sweep: all qualifying (asset_id, base_tf) pairs.",
    )
    parser.add_argument(
        "--assets",
        nargs="+",
        type=int,
        metavar="ID",
        dest="asset_ids",
        default=None,
        help="Specific asset IDs to evaluate (e.g. --assets 1 1027).",
    )
    parser.add_argument(
        "--base-tf",
        nargs="+",
        type=str,
        metavar="TF",
        dest="base_tf_filter",
        default=None,
        help="Specific base timeframes to evaluate (e.g. --base-tf 1D 7D).",
    )

    # Filtering
    parser.add_argument(
        "--min-bars",
        type=int,
        default=500,
        metavar="N",
        dest="min_bars",
        help="Minimum distinct ts rows in ctf for a pair to qualify (default: 500).",
    )

    # Horizon / return type
    parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=[1, 5, 10, 21],
        metavar="N",
        help="Forward return horizons in bars (default: 1 5 10 21).",
    )
    parser.add_argument(
        "--return-types",
        nargs="+",
        default=["arith", "log"],
        metavar="TYPE",
        dest="return_types",
        help="Return types: arith and/or log (default: arith log).",
    )
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=63,
        metavar="N",
        dest="rolling_window",
        help="Rolling IC window size in bars (default: 63).",
    )

    # Persistence
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=True,
        help="Upsert existing IC rows (ON CONFLICT DO UPDATE). Default True.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_false",
        dest="overwrite",
        help="Use append-only semantics (ON CONFLICT DO NOTHING).",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="List qualifying (asset_id, base_tf) pairs without computing IC.",
    )

    # Parallelism
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        dest="workers",
        help=(
            "Number of parallel worker processes. "
            "Default: 4. Uses maxtasksperchild=1 on Windows."
        ),
    )

    # Verbosity
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    sweep_start = time.time()

    # Connect to DB
    db_url = resolve_db_url()
    engine = create_engine(db_url, poolclass=pool.NullPool)

    # Load DimTimeframe
    try:
        dim_tf = DimTimeframe.from_db(db_url)
        logger.info("DimTimeframe loaded: %d timeframes", len(list(dim_tf.list_tfs())))
    except Exception as exc:
        logger.warning(
            "Failed to load DimTimeframe (%s) — tf_days_nominal will default to 1", exc
        )

        class _FallbackDim:
            def tf_days(self, tf: str) -> int:
                return 1

        dim_tf = _FallbackDim()

    # Discover qualifying CTF pairs
    logger.info(
        "Discovering qualifying (asset_id, base_tf) pairs from ctf (min_bars=%d)...",
        args.min_bars,
    )
    pairs = _discover_ctf_pairs(
        engine,
        args.min_bars,
        asset_ids_filter=args.asset_ids,
        base_tf_filter=args.base_tf_filter,
    )

    if not pairs:
        logger.warning("No qualifying CTF pairs found — nothing to sweep.")
        return 0

    # --- Dry run output ---
    if args.dry_run:
        print(f"\n[DRY RUN] CTF qualifying pairs ({len(pairs)}):")
        for asset_id, base_tf, n_ts in pairs:
            print(f"  asset_id={asset_id} base_tf={base_tf} n_ts={n_ts}")
        sweep_elapsed = time.time() - sweep_start
        print(f"\n[DRY RUN complete] {len(pairs)} pairs found ({sweep_elapsed:.1f}s)")
        return 0

    # --- Validate scope flags ---
    if not args.all_assets and args.asset_ids is None and args.base_tf_filter is None:
        logger.error(
            "Must specify --all, --assets, or --base-tf to run a sweep. "
            "Use --dry-run to inspect qualifying pairs."
        )
        return 1

    # Build tasks
    tasks: list[CTFICWorkerTask] = []
    for asset_id, base_tf, n_rows in pairs:
        try:
            tf_days_nominal = dim_tf.tf_days(base_tf)
        except (KeyError, AttributeError):
            logger.warning(
                "base_tf=%s not found in dim_timeframe — defaulting tf_days_nominal=1",
                base_tf,
            )
            tf_days_nominal = 1

        tasks.append(
            CTFICWorkerTask(
                asset_id=asset_id,
                base_tf=base_tf,
                n_rows=n_rows,
                db_url=db_url,
                horizons=tuple(args.horizons),
                return_types=tuple(args.return_types),
                rolling_window=args.rolling_window,
                tf_days_nominal=tf_days_nominal,
                overwrite=args.overwrite,
            )
        )

    logger.info(
        "Starting CTF IC sweep: %d tasks, %d workers, horizons=%s",
        len(tasks),
        args.workers,
        args.horizons,
    )

    total_ic_rows = 0
    total_features = 0
    n_errors = 0
    n_done = 0

    if args.workers > 1 and len(tasks) > 1:
        # Parallel path with maxtasksperchild=1 (MANDATORY on Windows)
        n_workers = min(args.workers, len(tasks))
        with Pool(processes=n_workers, maxtasksperchild=1) as p:
            for result in p.imap_unordered(_ctf_ic_worker, tasks):
                n_done += 1
                total_ic_rows += result["n_ic_rows"]
                total_features += result["n_features"]
                if result["error"]:
                    n_errors += 1
                    logger.warning(
                        "Worker error: asset_id=%d base_tf=%s error=%s",
                        result["asset_id"],
                        result["base_tf"],
                        result["error"],
                    )

                if n_done % 10 == 0 or n_done == len(tasks):
                    logger.info(
                        "[CTF] progress: %d/%d done, %d IC rows, %d errors",
                        n_done,
                        len(tasks),
                        total_ic_rows,
                        n_errors,
                    )
    else:
        # Sequential path (workers == 1 or single task)
        for task in tasks:
            result = _ctf_ic_worker(task)
            n_done += 1
            total_ic_rows += result["n_ic_rows"]
            total_features += result["n_features"]
            if result["error"]:
                n_errors += 1
                logger.warning(
                    "Worker error: asset_id=%d base_tf=%s error=%s",
                    result["asset_id"],
                    result["base_tf"],
                    result["error"],
                )

    sweep_elapsed = time.time() - sweep_start
    minutes = int(sweep_elapsed // 60)
    seconds = int(sweep_elapsed % 60)

    print(
        f"\n{'=' * 70}\n"
        f"CTF IC SWEEP COMPLETE\n"
        f"{'=' * 70}\n"
        f"  Pairs processed: {n_done}/{len(tasks)}\n"
        f"  Successful:      {n_done - n_errors}\n"
        f"  Failed:          {n_errors}\n"
        f"  Total IC rows:   {total_ic_rows:,}\n"
        f"  Elapsed:         {minutes}m{seconds:02d}s\n"
        f"{'=' * 70}\n"
    )

    logger.info(
        "CTF IC sweep done: %d pairs, %d IC rows, %d errors in %dm%ds",
        n_done,
        total_ic_rows,
        n_errors,
        minutes,
        seconds,
    )

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
