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
    e.g.  prefix='cmc_price_bars_', table='price_bars_multi_tf_cal_us'
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


def _build_column_mapping(
    engine: Engine, u_table: str, src_table: str
) -> Tuple[str, str, str]:
    """Build INSERT/SELECT column lists. Returns (insert_csv, select_csv, pk_sql)."""
    u_cols = get_columns(engine, u_table)
    src_cols_set = set(get_columns(engine, src_table))

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
            select_parts.append("NULL")
            insert_cols.append(_q(col))

    return ", ".join(insert_cols), ", ".join(select_parts)


def _sync_one_source(
    engine: Engine,
    u_table: str,
    src_table: str,
    pk_cols: List[str],
    alignment_source: str,
    log_fn,
    dry_run: bool = False,
    batch_col: Optional[str] = None,
) -> int:
    """Sync rows from one source table into the unified table. Returns rows inserted.

    When batch_col is set (e.g. "id"), rows are batched by distinct values of
    that column — each batch is a separate committed transaction. This prevents
    multi-hour single-transaction bulk inserts for large tables.
    """
    insert_csv, select_csv = _build_column_mapping(engine, u_table, src_table)
    pk_sql = ", ".join(_q(c) for c in pk_cols)

    # Watermark
    wm = _get_watermark(engine, u_table, alignment_source)
    if wm is None:
        log_fn(f"{alignment_source}: no watermark — full load from {src_table}")
        wm_clause = ""
        base_params = {"alignment_source": alignment_source}
    else:
        log_fn(f"{alignment_source}: watermark = {wm.isoformat()}")
        wm_clause = 'AND "ingested_at" > :wm'
        base_params = {"alignment_source": alignment_source, "wm": wm}

    if dry_run:
        where = f"WHERE 1=1 {wm_clause}" if wm_clause else ""
        count_sql = f"SELECT COUNT(*)::bigint AS n FROM {src_table} {where}"
        with engine.connect() as conn:
            row = conn.execute(text(count_sql), base_params).fetchone()
        n = int(row[0]) if row else 0
        log_fn(f"{alignment_source}: DRY RUN — {n:,} candidate rows")
        return 0

    # Decide whether to batch
    if batch_col:
        batch_where = f"WHERE 1=1 {wm_clause}" if wm_clause else ""
        ids_sql = (
            f"SELECT DISTINCT {_q(batch_col)} FROM {src_table} {batch_where} ORDER BY 1"
        )
        with engine.connect() as conn:
            batch_vals = [
                r[0] for r in conn.execute(text(ids_sql), base_params).fetchall()
            ]
        log_fn(
            f"{alignment_source}: batching by {batch_col}, {len(batch_vals)} batches"
        )
    else:
        batch_vals = [None]  # single batch, no extra WHERE

    total = 0
    for bv in batch_vals:
        if bv is not None:
            where_clause = f"WHERE {_q(batch_col)} = :batch_val {wm_clause}"
            params = {**base_params, "batch_val": bv}
        elif wm_clause:
            where_clause = f"WHERE 1=1 {wm_clause}"
            params = base_params
        else:
            where_clause = ""
            params = base_params

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
            n = int(row[0]) if row else 0
        total += n
        if bv is not None:
            log_fn(f"{alignment_source}: {batch_col}={bv} -> {n:,} rows")

    log_fn(f"{alignment_source}: inserted {total:,} rows total")
    return total


def sync_sources_to_unified(
    engine: Engine,
    u_table: str,
    sources: List[str],
    pk_cols: List[str],
    source_prefix: str,
    log_prefix: str = "sync",
    dry_run: bool = False,
    only: Optional[Set[str]] = None,
    batch_col: Optional[str] = None,
) -> int:
    """
    Incrementally sync rows from multiple source tables into a single
    unified (_u) table. Returns total rows inserted.

    Parameters
    ----------
    engine : SQLAlchemy Engine
    u_table : fully-qualified target table (e.g. "public.price_bars_multi_tf_u")
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
            batch_col=batch_col,
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
