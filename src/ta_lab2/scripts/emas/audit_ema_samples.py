from __future__ import annotations
# -*- coding: utf-8 -*-

r"""
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
    print(f"[ema_sample] {msg}")


def pick_cols(colset: set[str]) -> List[str]:
    preferred = [
        "id",
        "tf",
        "period",
        "ts",
        "tf_days",
        "roll",
        "ema",
        "d1",
        "d2",
        "d1_roll",
        "d2_roll",
        "roll_bar",
        "ema_bar",
        "d1_bar",
        "d2_bar",
        "d1_roll_bar",
        "d2_roll_bar",
        "ingested_at",
    ]
    return [c for c in preferred if c in colset]


def get_group_keys(
    engine: Engine, table: str, ids: Sequence[int], max_groups_per_id: int | None
) -> pd.DataFrame:
    in_clause = ",".join(str(int(i)) for i in ids)
    q = f"""
        SELECT id, tf, period
        FROM (
          SELECT DISTINCT id, tf, period
          FROM {table}
          WHERE id IN ({in_clause})
        ) x
        ORDER BY id, tf, period
        """
    df = read_sql_polars(q, engine)
    if df.empty or not max_groups_per_id or max_groups_per_id <= 0:
        return df

    out = []
    for id_, sub in df.groupby("id", sort=True):
        out.append(sub.head(max_groups_per_id))
    return pd.concat(out, ignore_index=True)


def sample_group(
    engine: Engine,
    table: str,
    cols: List[str],
    id_: int,
    tf: str,
    period: int,
    per_group: int,
) -> pd.DataFrame:
    q = f"""
        SELECT {", ".join(cols)}
        FROM {table}
        WHERE id = :id AND tf = :tf AND period = :period
        ORDER BY ts DESC
        LIMIT :lim
        """
    df = read_sql_polars(
        q,
        engine,
        params={
            "id": int(id_),
            "tf": str(tf),
            "period": int(period),
            "lim": int(per_group),
        },
    )
    if df.empty:
        return df
    df.insert(0, "table_name", table)
    return df


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create a visual sample CSV from EMA tables (last N rows per id/tf/period)."
    )
    ap.add_argument(
        "--ids", required=True, help="all OR comma-separated list like 1,52"
    )
    ap.add_argument(
        "--daily-table",
        default=DEFAULT_DAILY_TABLE,
        help="Used only to resolve --ids all",
    )
    ap.add_argument(
        "--per-group", type=int, default=50, help="Rows per (table,id,tf,period) group"
    )
    ap.add_argument(
        "--max-groups-per-id",
        type=int,
        default=0,
        help="Cap groups per id (0 = no cap)",
    )
    ap.add_argument("--out", default="ema_samples.csv", help="Output CSV filename")
    args = ap.parse_args()

    db_url = resolve_db_url(None)
    eng = get_engine(db_url)

    ids_result = parse_ids(args.ids)
    if ids_result == "all":
        ids = load_all_ids(db_url, args.daily_table)
    else:
        ids = ids_result

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
            max_groups_per_id=(
                args.max_groups_per_id if args.max_groups_per_id > 0 else None
            ),
        )
        if keys.empty:
            _log(f"No groups found for {table} with requested ids.")
            continue

        _log(
            f"Sampling {table}: {len(keys)} groups * {args.per_group} rows each (max)."
        )

        for _, r in keys.iterrows():
            df_g = sample_group(
                eng,
                table,
                cols,
                int(r["id"]),
                str(r["tf"]),
                int(r["period"]),
                args.per_group,
            )
            if not df_g.empty:
                frames.append(df_g)

    if not frames:
        raise RuntimeError(
            "No samples produced. Check ids/table names and permissions."
        )

    out_df = pd.concat(frames, ignore_index=True)
    out_df["sample_generated_at"] = datetime.now(UTC).isoformat()

    out_df = out_df.sort_values(
        ["table_name", "id", "tf", "period", "ts"],
        ascending=[True, True, True, True, False],
    ).reset_index(drop=True)
    out_df.to_csv(args.out, index=False)
    _log(f"Wrote {len(out_df)} rows -> {args.out}")


if __name__ == "__main__":
    main()
