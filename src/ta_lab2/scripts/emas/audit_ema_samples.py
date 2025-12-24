from __future__ import annotations
# -*- coding: utf-8 -*-

"""
audit_ema_samples.py

Creates a small human-eyeball sample CSV to spot-check EMA tables.

Sampling strategy per (table, id, tf, period):
- take the most recent N rows ordered by ts DESC

Includes diagnostic columns if they exist:
- roll, roll_bar
- ema, ema_bar
- d1/d2 and roll variants
- tf_days, ingested_at

Run:
runfile(
    r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\audit_ema_samples.py",
    wdir=r"C:\Users\asafi\Downloads\ta_lab2",
    args="--ids all --per-group 50 --out ema_samples.csv"
)

"""

import argparse
import os
from datetime import UTC, datetime
from typing import List, Sequence

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


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
    print(f"[ema_sample] {msg}")


def get_engine() -> Engine:
    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        raise RuntimeError("TARGET_DB_URL env var is required.")
    _log("Using DB URL from TARGET_DB_URL env.")
    return create_engine(db_url, future=True)


def parse_ids(engine: Engine, ids_arg: str, daily_table: str) -> List[int]:
    if ids_arg.strip().lower() == "all":
        df = pd.read_sql(text(f"SELECT DISTINCT id FROM {daily_table} ORDER BY id"), engine)
        ids = [int(x) for x in df["id"].tolist()]
        _log(f"Loaded ALL ids from {daily_table}: {len(ids)}")
        return ids

    ids: List[int] = []
    for part in ids_arg.split(","):
        part = part.strip()
        if part:
            ids.append(int(part))
    if not ids:
        raise ValueError("No ids parsed.")
    return ids


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


def pick_cols(colset: set[str]) -> List[str]:
    preferred = [
        "id", "tf", "period", "ts", "tf_days",
        "roll", "ema", "d1", "d2", "d1_roll", "d2_roll",
        "roll_bar", "ema_bar", "d1_bar", "d2_bar", "d1_roll_bar", "d2_roll_bar",
        "ingested_at",
    ]
    return [c for c in preferred if c in colset]


def get_group_keys(engine: Engine, table: str, ids: Sequence[int], max_groups_per_id: int | None) -> pd.DataFrame:
    in_clause = ",".join(str(int(i)) for i in ids)
    q = text(
        f"""
        SELECT id, tf, period
        FROM (
          SELECT DISTINCT id, tf, period
          FROM {table}
          WHERE id IN ({in_clause})
        ) x
        ORDER BY id, tf, period
        """
    )
    df = pd.read_sql(q, engine)
    if df.empty or not max_groups_per_id or max_groups_per_id <= 0:
        return df

    out = []
    for id_, sub in df.groupby("id", sort=True):
        out.append(sub.head(max_groups_per_id))
    return pd.concat(out, ignore_index=True)


def sample_group(engine: Engine, table: str, cols: List[str], id_: int, tf: str, period: int, per_group: int) -> pd.DataFrame:
    q = text(
        f"""
        SELECT {", ".join(cols)}
        FROM {table}
        WHERE id = :id AND tf = :tf AND period = :period
        ORDER BY ts DESC
        LIMIT :lim
        """
    )
    df = pd.read_sql(q, engine, params={"id": int(id_), "tf": str(tf), "period": int(period), "lim": int(per_group)})
    if df.empty:
        return df
    df.insert(0, "table_name", table)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Create a visual sample CSV from EMA tables (last N rows per id/tf/period).")
    ap.add_argument("--ids", required=True, help="all OR comma-separated list like 1,52")
    ap.add_argument("--daily-table", default=DEFAULT_DAILY_TABLE, help="Used only to resolve --ids all")
    ap.add_argument("--per-group", type=int, default=50, help="Rows per (table,id,tf,period) group")
    ap.add_argument("--max-groups-per-id", type=int, default=0, help="Cap groups per id (0 = no cap)")
    ap.add_argument("--out", default="ema_samples.csv", help="Output CSV filename")
    args = ap.parse_args()

    eng = get_engine()
    ids = parse_ids(eng, args.ids, args.daily_table)

    frames: List[pd.DataFrame] = []
    for table in TABLES:
        if not table_exists(eng, table):
            _log(f"SKIP missing table: {table}")
            continue

        cols_all = get_columns(eng, table)
        colset = set(cols_all)
        required = {"id", "tf", "period", "ts"}
        if not required.issubset(colset):
            _log(f"SKIP {table}: missing {sorted(required - colset)}")
            continue

        cols = pick_cols(colset)
        keys = get_group_keys(
            eng,
            table,
            ids,
            max_groups_per_id=(args.max_groups_per_id if args.max_groups_per_id > 0 else None),
        )
        if keys.empty:
            _log(f"No groups found for {table} with requested ids.")
            continue

        _log(f"Sampling {table}: {len(keys)} groups * {args.per_group} rows each (max).")

        for _, r in keys.iterrows():
            df_g = sample_group(eng, table, cols, int(r["id"]), str(r["tf"]), int(r["period"]), args.per_group)
            if not df_g.empty:
                frames.append(df_g)

    if not frames:
        raise RuntimeError("No samples produced. Check ids/table names and permissions.")

    out_df = pd.concat(frames, ignore_index=True)
    out_df["sample_generated_at"] = datetime.now(UTC).isoformat()

    out_df = out_df.sort_values(["table_name", "id", "tf", "period", "ts"], ascending=[True, True, True, True, False]).reset_index(drop=True)
    out_df.to_csv(args.out, index=False)
    _log(f"Wrote {len(out_df)} rows -> {args.out}")


if __name__ == "__main__":
    main()
