"""
refresh_cmc_returns_ama.py

Computes AMA return columns for all AMA value table variants and writes them
to the corresponding returns tables.

This script is invoked as part of the all-in-one --amas refresh stage.

Each source table maps to its own returns table:
    cmc_ama_multi_tf            -> cmc_returns_ama_multi_tf
    cmc_ama_multi_tf_cal_us     -> cmc_returns_ama_multi_tf_cal_us
    cmc_ama_multi_tf_cal_iso    -> cmc_returns_ama_multi_tf_cal_iso
    cmc_ama_multi_tf_cal_anchor_us  -> cmc_returns_ama_multi_tf_cal_anchor_us
    cmc_ama_multi_tf_cal_anchor_iso -> cmc_returns_ama_multi_tf_cal_anchor_iso

Usage:
    python -m ta_lab2.scripts.amas.refresh_cmc_returns_ama --ids 1 --tf 1D
    python -m ta_lab2.scripts.amas.refresh_cmc_returns_ama --ids all --all-tfs --source multi_tf
    python -m ta_lab2.scripts.amas.refresh_cmc_returns_ama --ids all --all-tfs --source all
    python -m ta_lab2.scripts.amas.refresh_cmc_returns_ama --ids 1,52 --tf 1D --dry-run

Spyder run example:
runfile(
  r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\amas\\refresh_cmc_returns_ama.py",
  wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2",
  args="--ids 1 --tf 1D"
)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table mapping: source -> (source_table, returns_table, state_table)
# ---------------------------------------------------------------------------

TABLE_MAP: dict[str, tuple[str, str, str]] = {
    "multi_tf": (
        "public.cmc_ama_multi_tf",
        "public.cmc_returns_ama_multi_tf",
        "public.cmc_returns_ama_multi_tf_state",
    ),
    "cal_us": (
        "public.cmc_ama_multi_tf_cal_us",
        "public.cmc_returns_ama_multi_tf_cal_us",
        "public.cmc_returns_ama_multi_tf_cal_us_state",
    ),
    "cal_iso": (
        "public.cmc_ama_multi_tf_cal_iso",
        "public.cmc_returns_ama_multi_tf_cal_iso",
        "public.cmc_returns_ama_multi_tf_cal_iso_state",
    ),
    "cal_anchor_us": (
        "public.cmc_ama_multi_tf_cal_anchor_us",
        "public.cmc_returns_ama_multi_tf_cal_anchor_us",
        "public.cmc_returns_ama_multi_tf_cal_anchor_us_state",
    ),
    "cal_anchor_iso": (
        "public.cmc_ama_multi_tf_cal_anchor_iso",
        "public.cmc_returns_ama_multi_tf_cal_anchor_iso",
        "public.cmc_returns_ama_multi_tf_cal_anchor_iso_state",
    ),
}

_PRINT_PREFIX = "refresh_cmc_returns_ama"


def _print(msg: str) -> None:
    print(f"[{_PRINT_PREFIX}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_db_url(cli_db_url: Optional[str]) -> str:
    """
    Resolve DB URL from CLI arg, config file, or environment.

    Priority:
    1. CLI --db-url argument
    2. db_config.env file (searched up to 5 dirs up)
    3. TARGET_DB_URL environment variable
    4. MARKETDATA_DB_URL environment variable
    """
    from ta_lab2.scripts.refresh_utils import resolve_db_url

    return resolve_db_url(cli_db_url)


def _get_engine(db_url: str) -> Engine:
    """Create a NullPool engine suitable for sequential (non-pooled) access."""
    return create_engine(db_url, future=True, poolclass=NullPool)


def _table_exists(engine: Engine, full_table: str) -> bool:
    """Return True if the given fully-qualified table exists in the DB."""
    if "." in full_table:
        schema, table = full_table.split(".", 1)
    else:
        schema, table = "public", full_table

    sql = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = :schema AND table_name = :table
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        result = conn.execute(sql, {"schema": schema, "table": table})
        return result.fetchone() is not None


def _resolve_ids(ids_arg: str, engine: Engine, source_table: str) -> list[int]:
    """
    Resolve --ids argument to a list of integers.

    'all' -> load all distinct IDs from the source table.
    '1,52,825' -> parse directly.
    """
    if ids_arg.strip().lower() == "all":
        sql = text(f"SELECT DISTINCT id FROM {source_table} ORDER BY id")
        with engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [int(r[0]) for r in rows]

    return [int(x.strip()) for x in ids_arg.split(",") if x.strip()]


def _resolve_tfs(
    tf_arg: Optional[str],
    all_tfs: bool,
    engine: Engine,
    source_table: str,
) -> list[str]:
    """
    Resolve timeframe list from CLI args.

    --tf 1D         -> ["1D"]
    --all-tfs       -> all distinct TFs in the source table
    neither         -> raise if both absent

    Args:
        tf_arg: Value of --tf argument or None.
        all_tfs: True if --all-tfs was passed.
        engine: SQLAlchemy engine.
        source_table: Source AMA table to query TFs from.

    Returns:
        List of TF label strings.
    """
    if tf_arg:
        return [tf_arg.strip()]

    if all_tfs:
        sql = text(f"SELECT DISTINCT tf FROM {source_table} ORDER BY tf")
        with engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [str(r[0]) for r in rows]

    raise ValueError("Provide --tf <TF> or --all-tfs to specify timeframes.")


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------


def _process_source(
    source_key: str,
    source_table: str,
    returns_table: str,
    state_table: str,
    *,
    ids_arg: str,
    tf_arg: Optional[str],
    all_tfs: bool,
    verbose: bool,
    dry_run: bool,
    db_url: str,
) -> dict:
    """
    Process one AMA source table -> returns table mapping.

    Returns a summary dict: {source, n_ids, n_tfs, n_rows, elapsed, skipped_reason}.
    """
    engine = _get_engine(db_url)

    # Check source table exists
    if not _table_exists(engine, source_table):
        _print(
            f"  [{source_key}] Source table {source_table} does not exist — skipping"
        )
        return {"source": source_key, "skipped_reason": "table_missing"}

    # Check source table has data
    with engine.connect() as conn:
        row_count = conn.execute(text(f"SELECT COUNT(*) FROM {source_table}")).scalar()

    if row_count == 0:
        _print(f"  [{source_key}] Source table {source_table} is empty — skipping")
        return {"source": source_key, "skipped_reason": "table_empty"}

    # Resolve IDs and TFs
    try:
        asset_ids = _resolve_ids(ids_arg, engine, source_table)
    except Exception as exc:
        _print(f"  [{source_key}] Could not resolve IDs: {exc} — skipping")
        return {"source": source_key, "skipped_reason": str(exc)}

    try:
        tfs = _resolve_tfs(tf_arg, all_tfs, engine, source_table)
    except Exception as exc:
        _print(f"  [{source_key}] Could not resolve TFs: {exc} — skipping")
        return {"source": source_key, "skipped_reason": str(exc)}

    if not asset_ids:
        _print(f"  [{source_key}] No IDs found — skipping")
        return {"source": source_key, "skipped_reason": "no_ids"}

    if not tfs:
        _print(f"  [{source_key}] No TFs found — skipping")
        return {"source": source_key, "skipped_reason": "no_tfs"}

    _print(
        f"  [{source_key}] {source_table} -> {returns_table}: "
        f"{len(asset_ids)} ids, {len(tfs)} tfs"
    )

    if dry_run:
        _print(
            f"  [{source_key}] DRY-RUN — would process {len(asset_ids) * len(tfs)} (id, tf) pairs"
        )
        return {
            "source": source_key,
            "n_ids": len(asset_ids),
            "n_tfs": len(tfs),
            "n_rows": 0,
            "elapsed": 0.0,
            "dry_run": True,
        }

    # Actual processing
    from ta_lab2.features.ama.ama_returns import AMAReturnsFeature

    feature = AMAReturnsFeature(
        source_table=source_table,
        returns_table=returns_table,
        state_table=state_table,
    )

    t0 = time.time()

    if verbose:
        _print(f"  [{source_key}] Starting refresh...")

    feature.refresh(engine, asset_ids=asset_ids, tfs=tfs)

    elapsed = time.time() - t0

    _print(
        f"  [{source_key}] Done in {elapsed:.1f}s "
        f"({len(asset_ids)} ids x {len(tfs)} tfs)"
    )

    return {
        "source": source_key,
        "n_ids": len(asset_ids),
        "n_tfs": len(tfs),
        "elapsed": elapsed,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute AMA return columns (delta1, delta2, ret_arith, ret_log + roll "
            "variants) for all AMA value table variants."
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

    args = parser.parse_args()

    # Validate TF args
    if args.tf and args.all_tfs:
        parser.error("--tf and --all-tfs are mutually exclusive.")
    if not args.tf and not args.all_tfs:
        # Default: use all TFs
        args.all_tfs = True

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Resolve DB URL
    try:
        db_url = _resolve_db_url(args.db_url)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        _print("DRY-RUN mode: no database writes will occur.")

    # Determine which sources to process
    if args.source == "all":
        sources_to_process = list(TABLE_MAP.keys())
    else:
        sources_to_process = [args.source]

    _print(
        f"Processing {len(sources_to_process)} source(s): {', '.join(sources_to_process)}"
    )
    _print(f"IDs: {args.ids}, TF: {args.tf or 'all'}, dry-run: {args.dry_run}")

    t_total = time.time()
    results = []

    for source_key in sources_to_process:
        source_table, returns_table, state_table = TABLE_MAP[source_key]
        result = _process_source(
            source_key=source_key,
            source_table=source_table,
            returns_table=returns_table,
            state_table=state_table,
            ids_arg=args.ids,
            tf_arg=args.tf,
            all_tfs=args.all_tfs,
            verbose=args.verbose,
            dry_run=args.dry_run,
            db_url=db_url,
        )
        results.append(result)

    # Summary
    total_elapsed = time.time() - t_total
    skipped = [r for r in results if "skipped_reason" in r]
    processed = [r for r in results if "skipped_reason" not in r]

    _print(
        f"--- Summary ---\n"
        f"  Sources processed: {len(processed)}/{len(results)}\n"
        f"  Sources skipped:   {len(skipped)}\n"
        f"  Total elapsed:     {total_elapsed:.1f}s"
    )

    if skipped:
        _print("  Skipped sources:")
        for r in skipped:
            _print(f"    {r['source']}: {r.get('skipped_reason', 'unknown')}")


if __name__ == "__main__":
    main()
