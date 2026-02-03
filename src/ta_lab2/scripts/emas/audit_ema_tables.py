from __future__ import annotations
# -*- coding: utf-8 -*-

"""
audit_ema_tables.py

High-level audit metrics for EMA output tables after refresh.

Produces per-(table,id,tf,period) metrics:
- n_rows, min_ts, max_ts
- duplicate key detection for (id,tf,ts,period)
- roll/canonical shares when roll columns exist
- null shares for ema/ema_bar and derivative columns when present

Run:
  python audit_ema_tables.py --ids all --out ema_audit.csv

Spyder runfile:
  runfile(
    r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\emas\\audit_ema_tables.py",
    wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2",
    args="--ids all --out ema_audit.csv"
  )
"""

import argparse
from datetime import UTC, datetime
from typing import List, Sequence

import pandas as pd
from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
    resolve_db_url,
    parse_ids,
    load_all_ids,
    table_exists,
    get_columns,
)
from ta_lab2.features.m_tf.polars_helpers import read_sql_polars


TABLES = [
    "public.cmc_ema_multi_tf",
    "public.cmc_ema_multi_tf_v2",
    "public.cmc_ema_multi_tf_cal_us",
    "public.cmc_ema_multi_tf_cal_iso",
    "public.cmc_ema_multi_tf_cal_anchor_us",
    "public.cmc_ema_multi_tf_cal_anchor_iso",
]

DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"


def _log(msg: str) -> None:
    print(f"[ema_audit] {msg}")


def audit_table(engine: Engine, table: str, ids: Sequence[int]) -> pd.DataFrame:
    if not table_exists(engine, table):
        _log(f"SKIP missing table: {table}")
        return pd.DataFrame()

    cols = get_columns(engine, table)
    colset = set(cols)

    required = {"id", "tf", "ts", "period"}
    if not required.issubset(colset):
        _log(f"SKIP {table}: missing {sorted(required - colset)}")
        return pd.DataFrame()

    has_roll = "roll" in colset
    has_roll_bar = "roll_bar" in colset

    # Common numeric columns (only if present)
    maybe_cols = [
        "ema",
        "d1",
        "d2",
        "d1_roll",
        "d2_roll",
        "ema_bar",
        "d1_bar",
        "d2_bar",
        "d1_roll_bar",
        "d2_roll_bar",
        "tf_days",
    ]
    present_cols = [c for c in maybe_cols if c in colset]

    in_clause = ",".join(str(int(i)) for i in ids)

    # Duplicate key detection: count rows vs count distinct keys
    # Group metrics per (id,tf,period)
    select_parts = [
        f"'{table}'::text AS table_name",
        "id",
        "tf",
        "period",
        "COUNT(*)::bigint AS n_rows",
        "MIN(ts) AS min_ts",
        "MAX(ts) AS max_ts",
        "COUNT(DISTINCT (id, tf, ts, period))::bigint AS n_distinct_keys",
        "COUNT(*)::bigint - COUNT(DISTINCT (id, tf, ts, period))::bigint AS n_dup_keys",
    ]

    if has_roll:
        select_parts += [
            "SUM(CASE WHEN roll THEN 1 ELSE 0 END)::bigint AS n_roll_true",
            "SUM(CASE WHEN NOT roll THEN 1 ELSE 0 END)::bigint AS n_roll_false",
        ]
    if has_roll_bar:
        select_parts += [
            "SUM(CASE WHEN roll_bar THEN 1 ELSE 0 END)::bigint AS n_roll_bar_true",
            "SUM(CASE WHEN NOT roll_bar THEN 1 ELSE 0 END)::bigint AS n_roll_bar_false",
        ]

    # Null shares for numeric columns
    for c in present_cols:
        select_parts.append(
            f"SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END)::bigint AS n_{c}_null"
        )

    q = f"""
        SELECT
          {", ".join(select_parts)}
        FROM {table}
        WHERE id IN ({in_clause})
        GROUP BY id, tf, period
        ORDER BY id, tf, period
        """
    df = read_sql_polars(q, engine)
    if df.empty:
        return df

    df["audit_generated_at"] = datetime.now(UTC).isoformat()

    # Derived shares
    df["dup_key_share"] = (df["n_dup_keys"] / df["n_rows"]).round(8)

    if has_roll:
        df["roll_share"] = (df["n_roll_true"] / df["n_rows"]).round(8)
        df["canonical_share"] = (df["n_roll_false"] / df["n_rows"]).round(8)

    if has_roll_bar:
        df["roll_bar_share"] = (df["n_roll_bar_true"] / df["n_rows"]).round(8)
        df["canonical_bar_share"] = (df["n_roll_bar_false"] / df["n_rows"]).round(8)

    for c in present_cols:
        df[f"{c}_null_share"] = (df[f"n_{c}_null"] / df["n_rows"]).round(8)

    return df


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit EMA output tables (coverage, duplicates, NULL shares)."
    )
    ap.add_argument(
        "--ids", required=True, help="all OR comma-separated list like 1,52"
    )
    ap.add_argument(
        "--daily-table",
        default=DEFAULT_DAILY_TABLE,
        help="Used only to resolve --ids all",
    )
    ap.add_argument("--out", default="ema_audit.csv", help="Output CSV filename")
    args = ap.parse_args()

    db_url = resolve_db_url(None)
    engine = get_engine(db_url)

    ids_result = parse_ids(args.ids)
    if ids_result == "all":
        ids = load_all_ids(db_url, args.daily_table)
    else:
        ids = ids_result

    frames: List[pd.DataFrame] = []
    for t in TABLES:
        df_t = audit_table(engine, t, ids)
        if not df_t.empty:
            frames.append(df_t)

    if not frames:
        raise RuntimeError("No results. Check table names/schema and permissions.")

    out_df = pd.concat(frames, ignore_index=True)
    out_df = out_df.sort_values(["table_name", "id", "tf", "period"]).reset_index(
        drop=True
    )

    out_df.to_csv(args.out, index=False)
    _log(f"Wrote {len(out_df)} rows -> {args.out}")


if __name__ == "__main__":
    main()
