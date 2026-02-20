from __future__ import annotations

"""
sync_utils.py

Generic incremental sync from N source tables into a single unified (_u) table.
Columns are matched dynamically via information_schema so the same logic works
for price_bars, returns_bars, and returns_ema families.
"""

import argparse
from datetime import datetime
from typing import List, Optional, Set, Tuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


# ── helpers ────────────────────────────────────────────────────────


def split_schema_table(full_name: str) -> Tuple[str, str]:
    if "." in full_name:
        schema, table = full_name.split(".", 1)
        return schema, table
    return "public", full_name


def table_exists(engine: Engine, full_name: str) -> bool:
    schema, table = split_schema_table(full_name)
    q = text(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = :schema AND table_name = :table
        LIMIT 1
    """
    )
    with engine.connect() as conn:
        row = conn.execute(q, {"schema": schema, "table": table}).fetchone()
    return row is not None


def get_columns(engine: Engine, full_name: str) -> List[str]:
    """Return column names in ordinal order."""
    schema, table = split_schema_table(full_name)
    q = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema AND table_name = :table
        ORDER BY ordinal_position
    """
    )
    with engine.connect() as conn:
        rows = conn.execute(q, {"schema": schema, "table": table}).fetchall()
    return [r[0] for r in rows]


def _q(col: str) -> str:
    """Double-quote a column name (safe for reserved words like timestamp, range)."""
    return f'"{col}"'


# ── core sync ──────────────────────────────────────────────────────


def alignment_source_from_table(full_name: str, prefix: str) -> str:
    """
    Derive alignment_source label by stripping prefix from table name.
    e.g.  prefix='cmc_price_bars_', table='cmc_price_bars_multi_tf_cal_us'
          -> 'multi_tf_cal_us'
    """
    _, table = split_schema_table(full_name)
    if table.startswith(prefix):
        return table[len(prefix) :]
    return table


def _get_watermark(
    engine: Engine, u_table: str, alignment_source: str
) -> Optional[datetime]:
    q = text(
        f"""
        SELECT MAX("ingested_at") AS wm
        FROM {u_table}
        WHERE "alignment_source" = :a
    """
    )
    with engine.connect() as conn:
        row = conn.execute(q, {"a": alignment_source}).fetchone()
    if row is None or row[0] is None:
        return None
    wm = row[0]
    if isinstance(wm, pd.Timestamp):
        wm = wm.to_pydatetime()
    return wm


def _sync_one_source(
    engine: Engine,
    u_table: str,
    src_table: str,
    pk_cols: List[str],
    alignment_source: str,
    log_fn,
    dry_run: bool = False,
) -> int:
    """Sync rows from one source table into the unified table. Returns rows inserted."""
    u_cols = get_columns(engine, u_table)
    src_cols_set = set(get_columns(engine, src_table))

    # Build SELECT and INSERT column lists
    select_parts: List[str] = []
    insert_cols: List[str] = []
    for col in u_cols:
        if col == "alignment_source":
            select_parts.append("CAST(:alignment_source AS text)")
            insert_cols.append(_q(col))
        elif col in src_cols_set:
            select_parts.append(_q(col))
            insert_cols.append(_q(col))
        else:
            # Column in _u but not in source — fill NULL
            select_parts.append("NULL")
            insert_cols.append(_q(col))

    pk_sql = ", ".join(_q(c) for c in pk_cols)
    insert_csv = ", ".join(insert_cols)
    select_csv = ", ".join(select_parts)

    # Watermark
    wm = _get_watermark(engine, u_table, alignment_source)
    if wm is None:
        log_fn(f"{alignment_source}: no watermark — full load from {src_table}")
        where_clause = ""
        params = {"alignment_source": alignment_source}
    else:
        log_fn(f"{alignment_source}: watermark = {wm.isoformat()}")
        where_clause = 'WHERE "ingested_at" > :wm'
        params = {"alignment_source": alignment_source, "wm": wm}

    if dry_run:
        count_sql = f"SELECT COUNT(*)::bigint AS n FROM {src_table} {where_clause}"
        with engine.connect() as conn:
            row = conn.execute(text(count_sql), params).fetchone()
        n = int(row[0]) if row else 0
        log_fn(f"{alignment_source}: DRY RUN — {n:,} candidate rows")
        return 0

    sql = f"""
    WITH ins AS (
        INSERT INTO {u_table} ({insert_csv})
        SELECT {select_csv}
        FROM {src_table}
        {where_clause}
        ON CONFLICT ({pk_sql}) DO NOTHING
        RETURNING 1
    )
    SELECT COUNT(*)::bigint AS n_inserted FROM ins;
    """

    with engine.begin() as conn:
        row = conn.execute(text(sql), params).fetchone()
        n_inserted = int(row[0]) if row else 0
    log_fn(f"{alignment_source}: inserted {n_inserted:,} rows")
    return n_inserted


def sync_sources_to_unified(
    engine: Engine,
    u_table: str,
    sources: List[str],
    pk_cols: List[str],
    source_prefix: str,
    log_prefix: str = "sync",
    dry_run: bool = False,
    only: Optional[Set[str]] = None,
) -> int:
    """
    Incrementally sync rows from multiple source tables into a single
    unified (_u) table. Returns total rows inserted.

    Parameters
    ----------
    engine : SQLAlchemy Engine
    u_table : fully-qualified target table (e.g. "public.cmc_price_bars_multi_tf_u")
    sources : list of fully-qualified source tables
    pk_cols : PK column names of the _u table (for ON CONFLICT)
    source_prefix : prefix stripped from source table name to derive alignment_source
    log_prefix : tag for log messages
    dry_run : if True, only report candidate counts
    only : optional set of alignment_source values to process
    """

    def _log(msg: str):
        print(f"[{log_prefix}] {msg}")

    if not table_exists(engine, u_table):
        _log(f"ERROR: target table {u_table} does not exist — run DDL first")
        return 0

    total = 0
    for src in sources:
        if not table_exists(engine, src):
            _log(f"SKIP missing source: {src}")
            continue

        a = alignment_source_from_table(src, source_prefix)
        if only is not None and a not in only:
            continue

        total += _sync_one_source(
            engine=engine,
            u_table=u_table,
            src_table=src,
            pk_cols=pk_cols,
            alignment_source=a,
            log_fn=_log,
            dry_run=dry_run,
        )

    if dry_run:
        _log("Dry run complete.")
    else:
        _log(f"Done. Total inserted: {total:,}")
        # Summary
        with engine.connect() as conn:
            df = pd.read_sql(
                text(
                    f"""
                    SELECT "alignment_source", COUNT(*)::bigint AS n_rows
                    FROM {u_table}
                    GROUP BY "alignment_source"
                    ORDER BY "alignment_source"
                """
                ),
                conn,
            )
        _log("Row counts by alignment_source:")
        for _, r in df.iterrows():
            _log(f"  {r['alignment_source']}: {int(r['n_rows']):,}")

    return total


def add_sync_cli_args(parser: argparse.ArgumentParser) -> None:
    """Add standard CLI arguments for sync scripts."""
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report candidate counts without inserting.",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated alignment_source values to process.",
    )
