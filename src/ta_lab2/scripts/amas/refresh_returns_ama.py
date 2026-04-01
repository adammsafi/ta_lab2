"""
refresh_returns_ama.py

Computes AMA return columns for all AMA value table variants and writes them
to returns_ama_multi_tf_u with alignment_source stamped on every row.

All 5 variants read from ama_multi_tf_u (scoped by alignment_source) and write
to returns_ama_multi_tf_u with alignment_source in PK, DELETE scope, and INSERT.

Source->returns mappings via TABLE_MAP:
    ama_multi_tf_u [multi_tf]            -> returns_ama_multi_tf_u
    ama_multi_tf_u [multi_tf_cal_us]     -> returns_ama_multi_tf_u
    ama_multi_tf_u [multi_tf_cal_iso]    -> returns_ama_multi_tf_u
    ama_multi_tf_u [multi_tf_cal_anchor_us]  -> returns_ama_multi_tf_u
    ama_multi_tf_u [multi_tf_cal_anchor_iso] -> returns_ama_multi_tf_u

Strategy (optimized v2 - batch per-ID with bulk watermark preload):
    - Bulk watermark preload: one query loads MAX(ts) for ALL IDs before dispatch
    - Source-advance skip: IDs where src_max_ts <= watermark_ts are skipped (no new data)
    - Batched workers: _BATCH_SIZE IDs per worker call to amortize engine creation
    - SET work_mem per transaction (not per connection probe)
    - Each worker creates ONE NullPool engine, processes N IDs sequentially, then disposes
    - ON CONFLICT DO NOTHING for idempotent upserts

Usage:
    python -m ta_lab2.scripts.amas.refresh_returns_ama --ids all --all-tfs --source all
    python -m ta_lab2.scripts.amas.refresh_returns_ama --ids 1 --tf 1D
    python -m ta_lab2.scripts.amas.refresh_returns_ama --ids all --all-tfs --source multi_tf -n 10
    python -m ta_lab2.scripts.amas.refresh_returns_ama --ids 1,52 --tf 1D --dry-run

Spyder run example:
runfile(
  r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\amas\\refresh_returns_ama.py",
  wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2",
  args="--ids 1 --tf 1D"
)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from multiprocessing import Pool
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table mapping: source_key -> (source_table, returns_table, state_table, alignment_source)
# All 5 variants now read from ama_multi_tf_u (scoped by alignment_source)
# and write to returns_ama_multi_tf_u with alignment_source in PK/CONFLICT/DELETE.
# ---------------------------------------------------------------------------

TABLE_MAP: dict[str, tuple[str, str, str, str]] = {
    "multi_tf": (
        "public.ama_multi_tf_u",
        "public.returns_ama_multi_tf_u",
        "public.returns_ama_multi_tf_state",
        "multi_tf",
    ),
    "cal_us": (
        "public.ama_multi_tf_u",
        "public.returns_ama_multi_tf_u",
        "public.returns_ama_multi_tf_cal_us_state",
        "multi_tf_cal_us",
    ),
    "cal_iso": (
        "public.ama_multi_tf_u",
        "public.returns_ama_multi_tf_u",
        "public.returns_ama_multi_tf_cal_iso_state",
        "multi_tf_cal_iso",
    ),
    "cal_anchor_us": (
        "public.ama_multi_tf_u",
        "public.returns_ama_multi_tf_u",
        "public.returns_ama_multi_tf_cal_anchor_us_state",
        "multi_tf_cal_anchor_us",
    ),
    "cal_anchor_iso": (
        "public.ama_multi_tf_u",
        "public.returns_ama_multi_tf_u",
        "public.returns_ama_multi_tf_cal_anchor_iso_state",
        "multi_tf_cal_anchor_iso",
    ),
}

_PRINT_PREFIX = "refresh_returns_ama"

# Number of IDs to process per worker call (amortizes engine creation overhead)
_BATCH_SIZE = 15


def _print(msg: str) -> None:
    print(f"[{_PRINT_PREFIX}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# SQL template: 2-pass CTE with window functions
# ---------------------------------------------------------------------------
# Parameters: {src}, {dst}, {where_clause}, {alignment_source}
# The where_clause scopes to a single id AND alignment_source (critical).

_INSERT_SQL = """
INSERT INTO {dst} (
    id, venue_id, ts, tf, tf_days, indicator, params_hash, roll,
    gap_days_roll, gap_days,
    delta1_ama_roll, delta2_ama_roll,
    ret_arith_ama_roll, delta_ret_arith_ama_roll,
    ret_log_ama_roll, delta_ret_log_ama_roll,
    delta1_ama, delta2_ama,
    ret_arith_ama, delta_ret_arith_ama,
    ret_log_ama, delta_ret_log_ama,
    alignment_source
)
WITH pass1 AS (
    SELECT
        id, venue_id, ts, tf, tf_days, indicator, params_hash, roll, ama,
        ama - LAG(ama, 1) OVER w AS delta1,
        ama / NULLIF(LAG(ama, 1) OVER w, 0) - 1.0 AS ret_arith,
        LN(NULLIF(GREATEST(ama / NULLIF(LAG(ama, 1) OVER w, 0), 0), 0)) AS ret_log,
        EXTRACT(EPOCH FROM (ts - LAG(ts, 1) OVER w))::double precision / 86400.0 AS gap_days_raw
    FROM {src}
    {where_clause}
    WINDOW w AS (PARTITION BY id, venue_id, tf, indicator, params_hash ORDER BY ts)
),
pass2 AS (
    SELECT
        id, venue_id, ts, tf, tf_days, indicator, params_hash, roll,
        gap_days_raw::integer AS gap_days_roll,
        CASE WHEN roll = FALSE THEN gap_days_raw::integer END AS gap_days,
        delta1 AS delta1_ama_roll,
        delta1 - LAG(delta1, 1) OVER w AS delta2_ama_roll,
        ret_arith AS ret_arith_ama_roll,
        ret_arith - LAG(ret_arith, 1) OVER w AS delta_ret_arith_ama_roll,
        ret_log AS ret_log_ama_roll,
        ret_log - LAG(ret_log, 1) OVER w AS delta_ret_log_ama_roll,
        CASE WHEN roll = FALSE THEN delta1 END AS delta1_ama,
        CASE WHEN roll = FALSE THEN delta1 - LAG(delta1, 1) OVER w END AS delta2_ama,
        CASE WHEN roll = FALSE THEN ret_arith END AS ret_arith_ama,
        CASE WHEN roll = FALSE THEN ret_arith - LAG(ret_arith, 1) OVER w END AS delta_ret_arith_ama,
        CASE WHEN roll = FALSE THEN ret_log END AS ret_log_ama,
        CASE WHEN roll = FALSE THEN ret_log - LAG(ret_log, 1) OVER w END AS delta_ret_log_ama
    FROM pass1
    WINDOW w AS (PARTITION BY id, venue_id, tf, indicator, params_hash ORDER BY ts)
)
SELECT *, '{alignment_source}'::text AS alignment_source FROM pass2
WHERE delta1_ama_roll IS NOT NULL
ON CONFLICT (id, venue_id, ts, tf, indicator, params_hash, alignment_source) DO NOTHING
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_db_url(cli_db_url: Optional[str]) -> str:
    from ta_lab2.scripts.refresh_utils import resolve_db_url

    return resolve_db_url(cli_db_url)


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True, poolclass=NullPool)


def _table_exists(engine: Engine, full_table: str) -> bool:
    if "." in full_table:
        schema, table = full_table.split(".", 1)
    else:
        schema, table = "public", full_table

    sql = text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = :schema AND table_name = :table LIMIT 1"
    )
    with engine.connect() as conn:
        return (
            conn.execute(sql, {"schema": schema, "table": table}).fetchone() is not None
        )


def _resolve_ids(
    ids_arg: str, engine: Engine, source_table: str, alignment_source: str
) -> list[int]:
    if ids_arg.strip().lower() == "all":
        sql = text(
            f"SELECT DISTINCT id FROM {source_table} "
            f"WHERE alignment_source = :as_ ORDER BY id"
        )
        with engine.connect() as conn:
            rows = conn.execute(sql, {"as_": alignment_source}).fetchall()
        return [int(r[0]) for r in rows]
    return [int(x.strip()) for x in ids_arg.split(",") if x.strip()]


def _resolve_tfs(
    tf_arg: Optional[str],
    all_tfs: bool,
    engine: Engine,
    source_table: str,
    alignment_source: str,
) -> list[str]:
    if tf_arg:
        return [tf_arg.strip()]
    if all_tfs:
        sql = text(
            f"SELECT DISTINCT tf FROM {source_table} "
            f"WHERE alignment_source = :as_ ORDER BY tf"
        )
        with engine.connect() as conn:
            rows = conn.execute(sql, {"as_": alignment_source}).fetchall()
        return [str(r[0]) for r in rows]
    raise ValueError("Provide --tf <TF> or --all-tfs to specify timeframes.")


def _bulk_load_watermarks(
    engine: Engine,
    dst: str,
    alignment_source: str,
    asset_ids: list[int],
    venue_id: Optional[int],
) -> dict[int, object]:
    """Load MAX(ts) from the returns table for all IDs in one query.

    Returns a dict mapping asset_id -> max_ts (or None if no rows for that ID).
    Eliminates per-ID watermark queries (~2,460 queries -> 1 per source).
    """
    venue_clause = f" AND venue_id = {int(venue_id)}" if venue_id is not None else ""
    id_list = ",".join(str(i) for i in asset_ids)
    sql = text(
        f"SELECT id, MAX(ts) AS last_ts"
        f" FROM {dst}"
        f" WHERE alignment_source = :as_{venue_clause}"
        f"   AND id IN ({id_list})"
        f" GROUP BY id"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"as_": alignment_source}).fetchall()
    return {int(r[0]): r[1] for r in rows}


def _bulk_load_source_max_ts(
    engine: Engine,
    src: str,
    alignment_source: str,
    asset_ids: list[int],
    venue_id: Optional[int],
) -> dict[int, object]:
    """Load MAX(ts) from the source AMA table for all IDs in one query.

    Returns a dict mapping asset_id -> src_max_ts.
    Used to skip IDs where src_max_ts <= watermark_ts (no new data).
    """
    venue_clause = f" AND venue_id = {int(venue_id)}" if venue_id is not None else ""
    id_list = ",".join(str(i) for i in asset_ids)
    sql = text(
        f"SELECT id, MAX(ts) AS src_max_ts"
        f" FROM {src}"
        f" WHERE alignment_source = :as_{venue_clause}"
        f"   AND id IN ({id_list})"
        f" GROUP BY id"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"as_": alignment_source}).fetchall()
    return {int(r[0]): r[1] for r in rows}


# ---------------------------------------------------------------------------
# Worker function for multiprocessing
# ---------------------------------------------------------------------------


def _worker(args: tuple) -> list[dict]:
    """
    Process a batch of asset IDs for one source.

    Each call creates ONE NullPool engine and processes all IDs in the batch
    sequentially, amortizing engine creation overhead (~_BATCH_SIZE IDs per engine).

    Watermarks are pre-loaded by _process_source (bulk query) and passed in via
    id_watermark_pairs, so no per-ID watermark queries are issued here.

    For each ID:
    - Incremental INSERT: reads from seed row before watermark, ON CONFLICT DO NOTHING
    - Full rebuild (DELETE + INSERT) when no watermark exists (first run)

    Returns a list of result dicts (one per ID) with source, id, n_rows, elapsed.
    """
    (
        source_key,
        src,
        dst,
        id_watermark_pairs,  # list of (asset_id, watermark_ts_or_None)
        tf_filter,
        db_url,
        venue_id,
        alignment_source,
    ) = args

    results: list[dict] = []
    engine = None

    try:
        engine = _get_engine(db_url)

        for asset_id, watermark in id_watermark_pairs:
            t0 = time.time()
            try:
                # Build base scope — always scoped by alignment_source to prevent
                # cross-source LAG contamination (all 5 variants read from same _u table)
                scope = (
                    f"id = {int(asset_id)} AND alignment_source = '{alignment_source}'"
                )
                if tf_filter:
                    scope += f" AND tf = '{tf_filter}'"
                if venue_id is not None:
                    scope += f" AND venue_id = {int(venue_id)}"

                if watermark is not None:
                    # Incremental: read from 1 seed row before watermark for LAG context.
                    # The seed row ensures LAG() computes delta1/ret correctly for the
                    # first new row. ON CONFLICT DO NOTHING skips rows already in dst.
                    # We use a subquery to find the seed ts: max(ts) < watermark per partition.
                    where_clause = (
                        f"WHERE {scope}"
                        f" AND ts >= ("
                        f"   SELECT COALESCE(max(s.ts), '1970-01-01'::timestamptz)"
                        f"   FROM {src} s"
                        f"   WHERE s.id = {int(asset_id)}"
                        f"     AND s.alignment_source = '{alignment_source}'"
                        f"     AND s.ts < '{watermark}'"
                        + (f"     AND s.tf = '{tf_filter}'" if tf_filter else "")
                        + (
                            f"     AND s.venue_id = {int(venue_id)}"
                            if venue_id is not None
                            else ""
                        )
                        + " )"
                    )
                else:
                    # No watermark: full build (first run for this id/source)
                    where_clause = f"WHERE {scope}"

                insert_sql = _INSERT_SQL.format(
                    src=src,
                    dst=dst,
                    where_clause=where_clause,
                    alignment_source=alignment_source,
                )

                with engine.begin() as conn:
                    conn.execute(text("SET LOCAL work_mem = '128MB'"))
                    if watermark is None:
                        # First run: delete any stale data, then full insert
                        conn.execute(text(f"DELETE FROM {dst} WHERE {scope}"))
                    result = conn.execute(text(insert_sql))
                    n_rows = result.rowcount

                elapsed = time.time() - t0
                results.append(
                    {
                        "source": source_key,
                        "id": asset_id,
                        "n_rows": n_rows,
                        "elapsed": elapsed,
                        "error": None,
                    }
                )

            except Exception as exc:
                elapsed = time.time() - t0
                results.append(
                    {
                        "source": source_key,
                        "id": asset_id,
                        "n_rows": 0,
                        "elapsed": elapsed,
                        "error": str(exc),
                    }
                )

    except Exception as outer_exc:
        # Engine creation failed — report all IDs in batch as errors
        for asset_id, _ in id_watermark_pairs:
            results.append(
                {
                    "source": source_key,
                    "id": asset_id,
                    "n_rows": 0,
                    "elapsed": 0.0,
                    "error": f"engine error: {outer_exc}",
                }
            )
    finally:
        if engine is not None:
            engine.dispose()

    return results


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------


def _process_source(
    source_key: str,
    source_table: str,
    returns_table: str,
    alignment_source: str,
    *,
    ids_arg: str,
    tf_arg: Optional[str],
    all_tfs: bool,
    dry_run: bool,
    db_url: str,
    num_processes: int,
    venue_id: Optional[int] = None,
) -> dict:
    """Process one AMA alignment_source -> returns_ama_multi_tf_u mapping."""
    engine = _get_engine(db_url)

    if not _table_exists(engine, source_table):
        _print(f"  [{source_key}] Source {source_table} does not exist -- skipping")
        return {"source": source_key, "skipped_reason": "table_missing"}

    with engine.connect() as conn:
        row_count = conn.execute(
            text(f"SELECT COUNT(*) FROM {source_table} WHERE alignment_source = :as_"),
            {"as_": alignment_source},
        ).scalar()

    if row_count == 0:
        _print(
            f"  [{source_key}] Source {source_table} [{alignment_source}] is empty -- skipping"
        )
        return {"source": source_key, "skipped_reason": "table_empty"}

    asset_ids = _resolve_ids(ids_arg, engine, source_table, alignment_source)
    if not asset_ids:
        _print(f"  [{source_key}] No IDs found -- skipping")
        return {"source": source_key, "skipped_reason": "no_ids"}

    # For single-TF mode, resolve TFs to verify they exist but pass the filter
    tf_filter = None
    if tf_arg:
        tf_filter = tf_arg.strip()
    elif not all_tfs:
        raise ValueError("Provide --tf <TF> or --all-tfs to specify timeframes.")

    _print(
        f"  [{source_key}] {source_table}[{alignment_source}] -> {returns_table}: "
        f"{len(asset_ids)} ids, tf={'all' if not tf_filter else tf_filter}, "
        f"~{row_count:,} source rows"
    )

    if dry_run:
        _print(f"  [{source_key}] DRY-RUN -- would process {len(asset_ids)} IDs")
        return {
            "source": source_key,
            "n_ids": len(asset_ids),
            "n_rows": 0,
            "elapsed": 0.0,
            "dry_run": True,
        }

    # ------------------------------------------------------------------
    # Bulk watermark preload: one query for all IDs (avoids per-ID queries)
    # ------------------------------------------------------------------
    _print(f"  [{source_key}] Loading watermarks for {len(asset_ids)} IDs...")
    watermarks = _bulk_load_watermarks(
        engine, returns_table, alignment_source, asset_ids, venue_id
    )
    _print(f"  [{source_key}] Watermarks loaded ({len(watermarks)} existing)")

    # ------------------------------------------------------------------
    # Source-advance check: skip IDs where no new source data exists
    # ------------------------------------------------------------------
    _print(f"  [{source_key}] Checking source max_ts for skip optimization...")
    src_max_ts = _bulk_load_source_max_ts(
        engine, source_table, alignment_source, asset_ids, venue_id
    )

    active_ids: list[int] = []
    skipped_ids: list[int] = []
    for aid in asset_ids:
        wm = watermarks.get(aid)
        smax = src_max_ts.get(aid)
        if wm is not None and smax is not None and smax <= wm:
            skipped_ids.append(aid)
        else:
            active_ids.append(aid)

    if skipped_ids:
        _print(
            f"  [{source_key}] Skipping {len(skipped_ids)} IDs (no new source data); "
            f"{len(active_ids)} IDs to process"
        )
    else:
        _print(f"  [{source_key}] All {len(active_ids)} IDs have new source data")

    if not active_ids:
        _print(f"  [{source_key}] Nothing to do -- all IDs up to date")
        return {
            "source": source_key,
            "n_ids": len(asset_ids),
            "n_skipped": len(skipped_ids),
            "n_rows": 0,
            "elapsed": 0.0,
        }

    # ------------------------------------------------------------------
    # Build batched work units: _BATCH_SIZE IDs per worker call to amortize
    # engine creation overhead (was: 1 engine per ID)
    # ------------------------------------------------------------------
    id_wm_pairs = [(aid, watermarks.get(aid)) for aid in active_ids]

    def _chunks(lst: list, n: int):
        for i in range(0, len(lst), n):
            yield lst[i : i + n]

    work_units = [
        (
            source_key,
            source_table,
            returns_table,
            batch,
            tf_filter,
            db_url,
            venue_id,
            alignment_source,
        )
        for batch in _chunks(id_wm_pairs, _BATCH_SIZE)
    ]

    _print(
        f"  [{source_key}] Dispatching {len(active_ids)} IDs in "
        f"{len(work_units)} batches (batch_size={_BATCH_SIZE}), "
        f"workers={min(num_processes, len(work_units))}"
    )

    t0 = time.time()
    total_rows = 0
    errors = []

    def _handle_result(result: dict) -> None:
        nonlocal total_rows
        total_rows += result["n_rows"]
        if result["error"]:
            errors.append(result)
            _print(f"  [{source_key}] id={result['id']} ERROR: {result['error']}")
        else:
            _print(
                f"  [{source_key}] id={result['id']}: "
                f"{result['n_rows']:,} rows in {result['elapsed']:.1f}s"
            )

    # Use multiprocessing for >1 worker, sequential for 1
    effective_workers = min(num_processes, len(work_units))
    if effective_workers > 1:
        with Pool(processes=effective_workers, maxtasksperchild=1) as pool:
            for batch_results in pool.imap_unordered(_worker, work_units):
                for result in batch_results:
                    _handle_result(result)
    else:
        for wu in work_units:
            for result in _worker(wu):
                _handle_result(result)

    elapsed = time.time() - t0
    _print(
        f"  [{source_key}] Done: {total_rows:,} rows, "
        f"{len(active_ids)} ids ({len(skipped_ids)} skipped), {elapsed:.1f}s"
        + (f", {len(errors)} errors" if errors else "")
    )

    return {
        "source": source_key,
        "n_ids": len(asset_ids),
        "n_active": len(active_ids),
        "n_skipped": len(skipped_ids),
        "n_rows": total_rows,
        "elapsed": elapsed,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute AMA return columns (delta1, delta2, ret_arith, ret_log + roll "
            "variants) for all AMA value table variants using SQL window functions. "
            "Writes to returns_ama_multi_tf_u with alignment_source stamped per row."
        )
    )
    parser.add_argument(
        "--ids",
        default="all",
        help="Comma-separated asset IDs or 'all' (default: all).",
    )
    parser.add_argument(
        "--tf",
        default=None,
        help="Specific timeframe label, e.g. '1D' (mutually exclusive with --all-tfs).",
    )
    parser.add_argument(
        "--all-tfs",
        action="store_true",
        help="Process all timeframes found in the source table.",
    )
    parser.add_argument(
        "--source",
        default="all",
        choices=list(TABLE_MAP.keys()) + ["all"],
        help=(
            "Which source to process: "
            + ", ".join(TABLE_MAP.keys())
            + ", or 'all' (default: all)."
        ),
    )
    parser.add_argument(
        "-n",
        "--num-processes",
        type=int,
        default=10,
        help="Number of parallel workers (default: 10).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Postgres DB URL. Falls back to db_config.env / TARGET_DB_URL env.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging output.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be processed without writing to DB.",
    )
    parser.add_argument(
        "--venue-id",
        type=int,
        default=None,
        help="Filter to a specific venue_id (e.g., 2 for HYPERLIQUID). Default: all venues.",
    )

    args = parser.parse_args()

    if args.tf and args.all_tfs:
        parser.error("--tf and --all-tfs are mutually exclusive.")
    if not args.tf and not args.all_tfs:
        args.all_tfs = True

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    try:
        db_url = _resolve_db_url(args.db_url)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        _print("DRY-RUN mode: no database writes will occur.")

    if args.source == "all":
        sources_to_process = list(TABLE_MAP.keys())
    else:
        sources_to_process = [args.source]

    _print(
        f"Processing {len(sources_to_process)} source(s): "
        f"{', '.join(sources_to_process)}"
    )
    _print(
        f"IDs: {args.ids}, TF: {args.tf or 'all'}, "
        f"workers: {args.num_processes}, dry-run: {args.dry_run}"
    )

    t_total = time.time()
    results = []

    for source_key in sources_to_process:
        src, dst, state_table, alignment_source = TABLE_MAP[source_key]
        result = _process_source(
            source_key=source_key,
            source_table=src,
            returns_table=dst,
            alignment_source=alignment_source,
            ids_arg=args.ids,
            tf_arg=args.tf,
            all_tfs=args.all_tfs,
            dry_run=args.dry_run,
            db_url=db_url,
            num_processes=args.num_processes,
            venue_id=args.venue_id,
        )
        results.append(result)

    total_elapsed = time.time() - t_total
    skipped = [r for r in results if "skipped_reason" in r]
    processed = [r for r in results if "skipped_reason" not in r]
    total_rows = sum(r.get("n_rows", 0) for r in processed)

    _print(
        f"--- Summary ---\n"
        f"  Sources processed: {len(processed)}/{len(results)}\n"
        f"  Sources skipped:   {len(skipped)}\n"
        f"  Total rows:        {total_rows:,}\n"
        f"  Total elapsed:     {total_elapsed:.1f}s"
    )

    if skipped:
        _print("  Skipped sources:")
        for r in skipped:
            _print(f"    {r['source']}: {r.get('skipped_reason', 'unknown')}")


if __name__ == "__main__":
    main()
