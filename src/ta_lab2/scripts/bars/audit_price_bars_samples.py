from __future__ import annotations
# -*- coding: utf-8 -*-
"""
Created on Fri Dec 19 21:15:03 2025

@author: asafi
"""

# -*- coding: utf-8 -*-
"""
audit_price_bars_samples.py

Creates a small "human eyeball" sample CSV to visually confirm that each of the 5
price_bars tables is behaving correctly.

Output: one row per sampled bar-snapshot record, across:
  1) public.cmc_price_bars_multi_tf
  2) public.cmc_price_bars_multi_tf_cal_us
  3) public.cmc_price_bars_multi_tf_cal_iso
  4) public.cmc_price_bars_multi_tf_cal_anchor_us
  5) public.cmc_price_bars_multi_tf_cal_anchor_iso

Sampling strategy (per table, per id, per tf):
  - Take the most recent N rows ordered by (time_close desc, bar_seq desc) when present.
  - Include key diagnostic columns if they exist (is_partial_end, is_partial_start, tf_days,
    count_days, count_days_remaining, is_missing_days, etc.)
  - Also include OHLCV and time_high/time_low when present.

Run:
  python audit_price_bars_samples.py --ids all --per-group 25 --out price_bars_samples.csv

Spyder runfile:
  runfile(
    r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\bars\\audit_price_bars_samples.py",
    wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2",
    args="--ids all --per-group 25 --out price_bars_samples.csv"
  )
"""



import argparse
import os
from datetime import UTC, datetime
from typing import Dict, List, Sequence, Tuple

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
    resolve_db_url,
    parse_ids,
    load_all_ids,
)

TABLES = [
    "public.cmc_price_bars_multi_tf",
    "public.cmc_price_bars_multi_tf_cal_us",
    "public.cmc_price_bars_multi_tf_cal_iso",
    "public.cmc_price_bars_multi_tf_cal_anchor_us",
    "public.cmc_price_bars_multi_tf_cal_anchor_iso",
]

DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"


def _log(msg: str) -> None:
    print(f"[bars_sample] {msg}")


def table_exists(engine: Engine, full_name: str) -> bool:
    if "." in full_name:
        schema, table = full_name.split(".", 1)
    else:
        schema, table = "public", full_name
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
    if "." in full_name:
        schema, table = full_name.split(".", 1)
    else:
        schema, table = "public", full_name
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


def get_tf_list(engine: Engine, table: str, ids: Sequence[int], max_tfs: int | None) -> pd.DataFrame:
    """
    Returns distinct (id, tf) pairs to sample.
    Optionally caps TF count per id using alphabetical order (deterministic).
    """
    in_clause = ",".join(str(int(i)) for i in ids)
    q = text(
        f"""
        SELECT id, tf
        FROM (
          SELECT DISTINCT id, tf
          FROM {table}
          WHERE id IN ({in_clause})
        ) x
        ORDER BY id, tf
        """
    )
    df = pd.read_sql(q, engine)
    if df.empty:
        return df

    if max_tfs is None or max_tfs <= 0:
        return df

    # cap TFs per id
    out = []
    for id_, sub in df.groupby("id", sort=True):
        out.append(sub.head(max_tfs))
    return pd.concat(out, ignore_index=True)


def pick_cols(colset: set[str]) -> List[str]:
    """
    Choose a readable, cross-table column subset.
    """
    preferred_order = [
        "id",
        "tf",
        "bar_seq",
        "time_close",
        "ts",
        "timestamp",
        "time_open",
        "time_high",
        "time_low",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "market_cap",
        "tf_days",
        "count_days",
        "count_days_remaining",
        "is_partial_start",
        "is_partial_end",
        "is_missing_days",
        "count_missing_days",
        "count_missing_days_start",
        "count_missing_days_interior",
        "count_missing_days_end",
        "missing_days_where",
        "ingested_at",
    ]
    cols = [c for c in preferred_order if c in colset]

    # Ensure we always include a timestamp column if present
    if "time_close" not in cols and "ts" not in cols and "timestamp" not in cols:
        # none present; okay
        pass

    return cols


def best_ts_col(colset: set[str]) -> str | None:
    for cand in ["time_close", "ts", "timestamp"]:
        if cand in colset:
            return cand
    return None


def sample_group(
    engine: Engine,
    table: str,
    cols: List[str],
    id_: int,
    tf: str,
    per_group: int,
) -> pd.DataFrame:
    """
    Return last N rows for a given (id, tf) group.
    """
    colset = set(cols)
    ts_col = best_ts_col(colset)
    has_bar_seq = "bar_seq" in colset

    # Ordering: latest snapshot first. If bar_seq exists, include it for stable ordering.
    if ts_col and has_bar_seq:
        order_by = f"{ts_col} DESC, bar_seq DESC"
    elif ts_col:
        order_by = f"{ts_col} DESC"
    elif has_bar_seq:
        order_by = "bar_seq DESC"
    else:
        # fallback
        order_by = "id DESC"

    q = text(
        f"""
        SELECT {", ".join(cols)}
        FROM {table}
        WHERE id = :id AND tf = :tf
        ORDER BY {order_by}
        LIMIT :lim
        """
    )
    df = pd.read_sql(q, engine, params={"id": id_, "tf": tf, "lim": per_group})
    if df.empty:
        return df

    df.insert(0, "table_name", table)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create a visual sample CSV from the 5 price_bars tables (last N rows per id/tf)."
    )
    ap.add_argument("--ids", required=True, help="all OR comma-separated list like 1,52")
    ap.add_argument("--daily-table", default=DEFAULT_DAILY_TABLE, help="Used only to resolve --ids all")
    ap.add_argument("--per-group", type=int, default=25, help="Rows per (table,id,tf) group")
    ap.add_argument(
        "--max-tfs-per-id",
        type=int,
        default=0,
        help="Optional cap on TFs per id (0 means no cap). Useful if your TF list is huge.",
    )
    ap.add_argument("--out", default="price_bars_samples.csv", help="Output CSV filename")

    args = ap.parse_args()

    db_url = resolve_db_url(None)
    engine = get_engine(db_url)

    ids_result = parse_ids(args.ids)
    if ids_result == "all":
        ids = load_all_ids(db_url, args.daily_table)
    else:
        ids = ids_result

    frames: List[pd.DataFrame] = []

    for table in TABLES:
        if not table_exists(engine, table):
            _log(f"SKIP missing table: {table}")
            continue

        cols_all = get_columns(engine, table)
        colset = set(cols_all)

        # Need at least id/tf
        if "id" not in colset or "tf" not in colset:
            _log(f"SKIP {table}: missing id/tf")
            continue

        cols = pick_cols(colset)

        # Ensure id/tf are present and first-ish for readability
        if "id" not in cols:
            cols = ["id"] + cols
        if "tf" not in cols:
            cols = ["tf"] + cols

        # Distinct (id, tf) pairs to sample
        tf_pairs = get_tf_list(
            engine,
            table,
            ids,
            max_tfs=(args.max_tfs_per_id if args.max_tfs_per_id > 0 else None),
        )
        if tf_pairs.empty:
            _log(f"No rows for {table} with requested ids.")
            continue

        _log(f"Sampling {table}: {len(tf_pairs)} (id,tf) groups * {args.per_group} rows each (max).")

        for _, r in tf_pairs.iterrows():
            id_ = int(r["id"])
            tf = str(r["tf"])
            df_g = sample_group(engine, table, cols, id_, tf, args.per_group)
            if not df_g.empty:
                frames.append(df_g)

    if not frames:
        raise RuntimeError("No samples produced. Check ids/table names and permissions.")

    out_df = pd.concat(frames, ignore_index=True)

    # Add audit timestamp
    out_df["sample_generated_at"] = datetime.now(UTC).isoformat()

    # Sort for readability: table, id, tf, then (time_close/ts/timestamp desc if present)
    sort_cols = [c for c in ["table_name", "id", "tf"] if c in out_df.columns]
    ts_sort = None
    for cand in ["time_close", "ts", "timestamp"]:
        if cand in out_df.columns:
            ts_sort = cand
            break

    if ts_sort:
        out_df = out_df.sort_values(sort_cols + [ts_sort], ascending=[True, True, True, False]).reset_index(drop=True)
    else:
        out_df = out_df.sort_values(sort_cols).reset_index(drop=True)

    out_df.to_csv(args.out, index=False)
    _log(f"Wrote {len(out_df)} rows -> {args.out}")


if __name__ == "__main__":
    main()
