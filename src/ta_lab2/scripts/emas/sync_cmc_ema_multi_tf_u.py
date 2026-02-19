from __future__ import annotations

"""
sync_cmc_ema_multi_tf_u.py

Incrementally sync EMA records from 5 source EMA tables into:
  public.cmc_ema_multi_tf_u

Rules:
- alignment_source = suffix after 'cmc_ema_' in the source table name.
  e.g. public.cmc_ema_multi_tf -> multi_tf

- Watermark per source:
  - If source has ingested_at: use max(ingested_at) from _u for that alignment_source
  - Else: use max(ts) from _u for that alignment_source

- Insert uses ON CONFLICT DO NOTHING on PK:
  (id, ts, tf, period, alignment_source)

Run:
  python sync_cmc_ema_multi_tf_u.py

Spyder:
  runfile(
    r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\emas\\sync_cmc_ema_multi_tf_u.py",
    wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2"
  )
"""

import argparse
import os
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


U_TABLE = "public.cmc_ema_multi_tf_u"

SOURCES = [
    "public.cmc_ema_multi_tf",
    "public.cmc_ema_multi_tf_cal_us",
    "public.cmc_ema_multi_tf_cal_iso",
    "public.cmc_ema_multi_tf_cal_anchor_us",
    "public.cmc_ema_multi_tf_cal_anchor_iso",
]


def _log(msg: str) -> None:
    print(f"[ema_u_sync] {msg}")


def get_engine() -> Engine:
    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        raise RuntimeError("TARGET_DB_URL env var is required.")
    _log("Using DB URL from TARGET_DB_URL env.")
    return create_engine(db_url, future=True)


def split_schema_table(full_name: str) -> Tuple[str, str]:
    if "." in full_name:
        schema, table = full_name.split(".", 1)
        return schema, table
    return "public", full_name


def table_exists(engine: Engine, full_name: str) -> bool:
    schema, table = split_schema_table(full_name)
    q = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = :schema AND table_name = :table
        LIMIT 1
        """
    )
    df = pd.read_sql(q, engine, params={"schema": schema, "table": table})
    return not df.empty


def get_columns(engine: Engine, full_name: str) -> List[str]:
    schema, table = split_schema_table(full_name)
    q = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema AND table_name = :table
        ORDER BY ordinal_position
        """
    )
    df = pd.read_sql(q, engine, params={"schema": schema, "table": table})
    return df["column_name"].tolist()


def alignment_source_from_table(full_name: str) -> str:
    _, table = split_schema_table(full_name)
    # portion after cmc_ema_
    # e.g. cmc_ema_multi_tf_cal_us -> multi_tf_cal_us
    if table.startswith("cmc_ema_"):
        return table.replace("cmc_ema_", "", 1)
    return table


def get_watermark(
    engine: Engine, alignment_source: str, prefer_ingested_at: bool
) -> Optional[datetime]:
    """
    Returns max watermark in _u for this alignment_source.
    If prefer_ingested_at=True -> MAX(ingested_at), else MAX(ts).
    """
    if prefer_ingested_at:
        q = text(
            f"""
            SELECT MAX(ingested_at) AS wm
            FROM {U_TABLE}
            WHERE alignment_source = :a
            """
        )
    else:
        q = text(
            f"""
            SELECT MAX(ts) AS wm
            FROM {U_TABLE}
            WHERE alignment_source = :a
            """
        )
    df = pd.read_sql(q, engine, params={"a": alignment_source})
    wm = df.loc[0, "wm"]
    # pandas will give NaT if null
    if pd.isna(wm):
        return None
    # ensure python datetime
    if isinstance(wm, pd.Timestamp):
        wm = wm.to_pydatetime()
    return wm


def build_select_expr(
    cols: Sequence[str], alignment_source: str, use_ingested_filter: bool
) -> Tuple[str, str]:
    """
    Build (select_sql, where_sql) for INSERT ... SELECT.
    Ensures positional order matches _u insert columns.
    """
    colset = set(cols)

    # optional expressions (cast to target types)
    e_ingested_at = "ingested_at" if "ingested_at" in colset else "now()"
    e_tf_days = "tf_days::int" if "tf_days" in colset else "NULL::int"
    e_roll = "COALESCE(roll,false)::boolean" if "roll" in colset else "false::boolean"
    e_ema_bar = (
        "ema_bar::double precision" if "ema_bar" in colset else "NULL::double precision"
    )
    e_roll_bar = "roll_bar::boolean" if "roll_bar" in colset else "NULL::boolean"

    # required columns (must exist in source)
    required = {"id", "ts", "tf", "period", "ema"}
    missing = required - colset
    if missing:
        raise RuntimeError(f"Source missing required columns: {sorted(missing)}")

    # WHERE clause uses either ingested_at > :wm or ts > :wm
    if use_ingested_filter and "ingested_at" in colset:
        where_sql = "WHERE ingested_at > :wm"
    else:
        where_sql = "WHERE ts > :wm"

    select_sql = f"""
    SELECT
      id::int,
      ts,
      tf::text,
      period::int,
      ema::double precision,
      {e_ingested_at},
      {e_tf_days},
      {e_roll},
      :alignment_source::text,
      {e_ema_bar},
      {e_roll_bar}
    """
    return select_sql.strip(), where_sql


def insert_new_rows(
    engine: Engine,
    src_table: str,
    alignment_source: str,
    dry_run: bool,
    use_ingested_filter: bool,
) -> int:
    """
    Inserts new rows from src_table into _u using watermark logic.
    Returns number of inserted rows (best-effort accurate).
    """
    cols = get_columns(engine, src_table)

    prefer_ingested = use_ingested_filter and ("ingested_at" in set(cols))
    wm = get_watermark(engine, alignment_source, prefer_ingested_at=prefer_ingested)

    if wm is None:
        # No existing rows for this alignment_source in _u.
        # We'll do a full copy from source (still safe with ON CONFLICT DO NOTHING).
        _log(
            f"{alignment_source}: no watermark found in _u; full-load from {src_table}"
        )
        where_clause = ""
        params = {"alignment_source": alignment_source}
    else:
        _log(f"{alignment_source}: watermark = {wm.isoformat()}")
        select_sql, where_clause = build_select_expr(
            cols, alignment_source, use_ingested_filter=use_ingested_filter
        )
        params = {"alignment_source": alignment_source, "wm": wm}

    if wm is None:
        # build select without wm clause
        select_sql, _ = build_select_expr(
            cols, alignment_source, use_ingested_filter=False
        )
        where_clause = ""

    # Use a CTE so we can count inserted rows
    sql = f"""
    WITH ins AS (
      INSERT INTO {U_TABLE} (
        id, ts, tf, period,
        ema, ingested_at, tf_days, roll,
        alignment_source,
        ema_bar, roll_bar
      )
      {select_sql}
      FROM {src_table}
      {where_clause}
      ON CONFLICT (id, ts, tf, period, alignment_source) DO NOTHING
      RETURNING 1
    )
    SELECT COUNT(*)::bigint AS n_inserted FROM ins;
    """

    if dry_run:
        # Estimate count of candidate rows (not exact inserts)
        if wm is None:
            q = text(f"SELECT COUNT(*)::bigint AS n_candidates FROM {src_table}")
            df = pd.read_sql(q, engine)
        else:
            # match same filter we will use
            if prefer_ingested and "ingested_at" in set(cols):
                q = text(
                    f"SELECT COUNT(*)::bigint AS n_candidates FROM {src_table} WHERE ingested_at > :wm"
                )
            else:
                q = text(
                    f"SELECT COUNT(*)::bigint AS n_candidates FROM {src_table} WHERE ts > :wm"
                )
            df = pd.read_sql(q, engine, params={"wm": wm})
        n = int(df.loc[0, "n_candidates"])
        _log(f"{alignment_source}: DRY RUN candidates = {n}")
        return 0

    df_ins = pd.read_sql(text(sql), engine, params=params)
    n_inserted = int(df_ins.loc[0, "n_inserted"])
    _log(f"{alignment_source}: inserted {n_inserted} rows")
    return n_inserted


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sync EMA source tables into public.cmc_ema_multi_tf_u (incremental)."
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not insert; only report candidate counts.",
    )
    ap.add_argument(
        "--use-ingested-at",
        action="store_true",
        help="Prefer watermarking by ingested_at when the source has ingested_at; else falls back to ts.",
    )
    ap.add_argument(
        "--only",
        default="",
        help="Optional comma-separated list of alignment_source values to process (e.g. multi_tf,multi_tf_cal_us)",
    )
    args = ap.parse_args()

    engine = get_engine()

    only_set = (
        set([s.strip() for s in args.only.split(",") if s.strip()])
        if args.only
        else None
    )

    total_inserted = 0
    for src in SOURCES:
        if not table_exists(engine, src):
            _log(f"SKIP missing table: {src}")
            continue

        a = alignment_source_from_table(src)
        if only_set is not None and a not in only_set:
            continue

        total_inserted += insert_new_rows(
            engine=engine,
            src_table=src,
            alignment_source=a,
            dry_run=args.dry_run,
            use_ingested_filter=args.use_ingested_at,
        )

    if args.dry_run:
        _log("Dry run complete.")
    else:
        _log(f"Done. Total inserted across all sources: {total_inserted}")

        # Optional quick summary
        df = pd.read_sql(
            text(
                f"""
                SELECT alignment_source, COUNT(*)::bigint AS n_rows
                FROM {U_TABLE}
                GROUP BY alignment_source
                ORDER BY alignment_source
                """
            ),
            engine,
        )
        _log("Current _u row counts by alignment_source:")
        for _, r in df.iterrows():
            _log(f"  {r['alignment_source']}: {int(r['n_rows'])}")


if __name__ == "__main__":
    main()
