# src/ta_lab2/scripts/run_ema_refresh_examples.py
from __future__ import annotations

"""
Helper script to refresh EMA tables for CMC price histories.

Typical usage from Spyder:

    %runfile C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/run_ema_refresh_examples.py --wdir

What this does:

  1. Reads all distinct ids from cmc_price_histories7
  2. Calls refresh_cmc_emas via its CLI entrypoint:

         python -m ta_lab2.scripts.refresh_cmc_emas --ids ...

     with flags to update:
        - cmc_ema_daily
        - cmc_ema_multi_tf
        - cmc_ema_multi_tf_cal
        - (and refresh EMA views, if wired in the CLI)

  3. Takes BEFORE and AFTER snapshots of:
        - cmc_ema_daily
        - cmc_ema_multi_tf
        - cmc_ema_multi_tf_cal

     and prints a summary per table of:
        - how many ids changed (row count or max ts)
        - how many remained unchanged
        - or that no rows exist / no changes detected.

The public function other helper scripts rely on is:

    example_incremental_all_ids_all_targets()

which is what upsert_new_emas_canUpdate.py imports and calls.
"""

from typing import Sequence, List, Dict, Tuple, Optional
import sys
import subprocess

from sqlalchemy import create_engine, text

from ta_lab2.config import TARGET_DB_URL


# ---------------------------------------------------------------------------
# Small helpers: DB engine and id discovery
# ---------------------------------------------------------------------------


def get_engine(db_url: str | None = None):
    """Create an SQLAlchemy engine using TARGET_DB_URL by default."""
    url = db_url or TARGET_DB_URL
    return create_engine(url)


def get_all_ids(db_url: str | None = None) -> List[int]:
    """Return all distinct ids from cmc_price_histories7, sorted ascending."""
    engine = get_engine(db_url)
    sql = text("SELECT DISTINCT id FROM cmc_price_histories7 ORDER BY id;")
    with engine.begin() as conn:
        rows = conn.execute(sql).fetchall()
    return [int(r[0]) for r in rows]


# ---------------------------------------------------------------------------
# Snapshots & summaries
# ---------------------------------------------------------------------------

Snapshot = Dict[int, Tuple[Optional[str], int]]
# maps id -> (max_ts_iso or None, n_rows)


def _get_table_snapshot(
    table_name: str,
    ids: Sequence[int],
    db_url: str | None = None,
) -> Snapshot:
    """
    For a given table and list of ids, return a simple snapshot:

        { id: (max_ts_iso_str_or_None, n_rows) }

    If the table is missing or has no ts column, this will raise / print
    in the caller – we don't swallow hard errors silently.
    """
    if not ids:
        return {}

    engine = get_engine(db_url)
    sql = text(
        f"""
        SELECT
            id,
            MAX(ts) AS max_ts,
            COUNT(*) AS n_rows
        FROM {table_name}
        WHERE id = ANY(:ids)
        GROUP BY id
        ORDER BY id;
        """
    )

    snapshot: Snapshot = {}
    try:
        with engine.begin() as conn:
            # rows are plain tuples: (id, max_ts, n_rows)
            rows = conn.execute(sql, {"ids": list(ids)}).fetchall()
    except Exception as exc:  # pragma: no cover - diagnostic path
        print(f"[summary] Skipping snapshot for {table_name}: {exc!r}")
        return {}

    for row in rows:
        # row is a tuple, not a mapping
        _id = int(row[0])
        max_ts = row[1]
        n_rows_val = row[2]
        n_rows = int(n_rows_val) if n_rows_val is not None else 0

        if max_ts is None:
            max_ts_iso: Optional[str] = None
        else:
            try:
                max_ts_iso = max_ts.isoformat()
            except AttributeError:
                max_ts_iso = str(max_ts)

        snapshot[_id] = (max_ts_iso, n_rows)

    return snapshot


def _summarize_table_changes(
    table_name: str,
    ids: Sequence[int],
    before: Snapshot,
    after: Snapshot,
) -> None:
    """
    Print a human-readable summary of what changed between two snapshots.
    """
    if not before and not after:
        print(f"[summary] {table_name}: no rows found for requested ids.")
        return

    changed = 0
    unchanged = 0
    missing_before = 0
    new_ids = 0

    for _id in ids:
        b = before.get(_id)
        a = after.get(_id)

        if b is None and a is None:
            # No rows for this id either way.
            continue
        if b is None and a is not None:
            new_ids += 1
            changed += 1
            continue
        if b is not None and a is None:
            # Rows disappeared (unlikely with upsert pattern, but track it)
            missing_before += 1
            changed += 1
            continue

        # Both exist; compare (max_ts, n_rows)
        if b == a:
            unchanged += 1
        else:
            changed += 1

    msg_parts = [f"[summary] {table_name}:"]
    msg_parts.append(f" changed_ids={changed}")
    msg_parts.append(f" unchanged_ids={unchanged}")
    if new_ids:
        msg_parts.append(f" new_ids={new_ids}")
    if missing_before:
        msg_parts.append(f" ids_lost={missing_before}")

    print(" ".join(msg_parts))

    if changed == 0:
        print(
            f"[summary] {table_name}: no changes detected "
            f"for the requested ids based on (max_ts, n_rows)."
        )


def _snapshot_all_targets(
    ids: Sequence[int],
    db_url: str | None = None,
) -> dict:
    """
    Take snapshots for all EMA targets we care about.
    Returns a dict {table_name: snapshot_dict}.
    """
    tables = [
        "cmc_ema_daily",
        "cmc_ema_multi_tf",
        "cmc_ema_multi_tf_cal",
    ]
    out: dict = {}
    for tbl in tables:
        out[tpl] = _get_table_snapshot(tbl, ids, db_url=db_url) if (tpl := tbl) else None
    return out


def _summarize_all_targets(
    ids: Sequence[int],
    before: dict,
    after: dict,
) -> None:
    """
    Print summaries for all EMA targets based on BEFORE/AFTER snapshots.
    """
    print("[summary] ----------------------------------------------------------------")
    print("[summary] EMA refresh summary (based on (max_ts, n_rows) per id):")
    for tbl in ["cmc_ema_daily", "cmc_ema_multi_tf", "cmc_ema_multi_tf_cal"]:
        _summarize_table_changes(tbl, ids, before.get(tbl, {}), after.get(tbl, {}))
    print("[summary] ----------------------------------------------------------------")


# ---------------------------------------------------------------------------
# Core refresh wrapper (CLI call)
# ---------------------------------------------------------------------------


def _build_cli_args(ids: Sequence[int], db_url: str | None = None) -> list[str]:
    """
    Build the CLI argument list to invoke refresh_cmc_emas as a module.

    Example:
        ['python', '-m', 'ta_lab2.scripts.refresh_cmc_emas',
         '--ids', '1', '52', '1027', '--update-daily', '--update-multi-tf',
         '--refresh-all-emas-view', '--refresh-price-emas-view',
         '--refresh-price-emas-d1d2-view']
    """
    python_exe = sys.executable
    base = [
        python_exe,
        "-m",
        "ta_lab2.scripts.refresh_cmc_emas",
        "--ids",
    ]
    base.extend(str(i) for i in ids)

    # Flags: we want daily + multi-tf + views refreshed.
    base.extend(
        [
            "--update-daily",
            "--update-multi-tf",
            "--refresh-all-emas-view",
            "--refresh-price-emas-view",
            "--refresh-price-emas-d1d2-view",
        ]
    )

    if db_url:
        base.extend(["--db-url", db_url])

    return base


def _refresh_insert_only_all_targets(
    ids: Sequence[int],
    db_url: str | None = None,
) -> None:
    """
    Call refresh_cmc_emas via CLI for the given ids and then print
    BEFORE/AFTER summaries for the EMA tables.

    Note: Whether the underlying script does true incremental vs recompute
    is controlled in refresh_cmc_emas itself. Here we only reflect the net
    effect by comparing (max_ts, n_rows) per id.
    """
    ids = list(ids)
    if not ids:
        print("[run_examples] No ids supplied; nothing to do.")
        return

    # Take BEFORE snapshots
    before = _snapshot_all_targets(ids, db_url=db_url)

    # Build and run CLI
    args = _build_cli_args(ids, db_url=db_url)
    print("[run_examples] Calling refresh_cmc_emas via CLI:")
    print("  " + " ".join(args))

    result = subprocess.run(args, check=False)
    if result.returncode != 0:
        print(f"[run_examples] refresh_cmc_emas exited with code {result.returncode}")
        # Still attempt AFTER snapshot to see if anything partial happened
    else:
        print("[run_examples] refresh_cmc_emas completed with exit code 0.")

    # AFTER snapshots
    after = _snapshot_all_targets(ids, db_url=db_url)

    # Summaries
    _summarize_all_targets(ids, before, after)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def example_incremental_all_ids_all_targets(db_url: str | None = None) -> None:
    """
    Incremental insert-only (from the caller's perspective) for ALL ids
    into all EMA targets.

    This is the function that upsert_new_emas_canUpdate.py imports and calls.
    """
    ids = get_all_ids(db_url)
    print(f"[run_examples] Using ALL ids from cmc_price_histories7: {ids}")
    _refresh_insert_only_all_targets(ids, db_url=db_url)


# ---------------------------------------------------------------------------
# Script entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Default behavior when you press "Run" in Spyder:
    example_incremental_all_ids_all_targets()
