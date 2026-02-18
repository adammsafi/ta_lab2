# -*- coding: utf-8 -*-
"""
Created on Fri Dec 19 20:59:42 2025

@author: asafi
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from typing import List

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
    resolve_db_url,
    parse_ids,
    load_all_ids,
)


# ----------------------------
# Tables to audit
# ----------------------------
TABLES = [
    "public.cmc_price_bars_multi_tf",
    "public.cmc_price_bars_multi_tf_cal_us",
    "public.cmc_price_bars_multi_tf_cal_iso",
    "public.cmc_price_bars_multi_tf_cal_anchor_us",
    "public.cmc_price_bars_multi_tf_cal_anchor_iso",
]

DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"


def _log(msg: str) -> None:
    print(f"[bars_audit] {msg}")


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


def audit_table(engine: Engine, table: str, ids: List[int]) -> pd.DataFrame:
    """
    Produces per-(table,id,tf) metrics. Uses whatever columns exist in the table.
    """
    if not table_exists(engine, table):
        _log(f"SKIP missing table: {table}")
        return pd.DataFrame()

    cols = get_columns(engine, table)
    colset = set(cols)

    required_core = {"id", "tf"}
    if not required_core.issubset(colset):
        _log(f"SKIP {table}: missing core columns {sorted(required_core - colset)}")
        return pd.DataFrame()

    # Identify timestamp column names commonly used
    ts_col = None
    for cand in ["timestamp", "time_close", "ts"]:
        if cand in colset:
            ts_col = cand
            break

    # Optional behavior columns
    has_bar_seq = "bar_seq" in colset
    has_tf_days = "tf_days" in colset
    has_is_partial_end = "is_partial_end" in colset
    has_is_partial_start = "is_partial_start" in colset
    has_is_missing_days = "is_missing_days" in colset
    has_count_days = "count_days" in colset
    has_count_days_remaining = "count_days_remaining" in colset

    _log(f"Auditing {table} (cols={len(cols)})")

    # IN clause for your small id set (7 ids)
    in_clause = ",".join(str(int(i)) for i in ids)

    select_parts = [
        f"'{table}'::text AS table_name",
        "id",
        "tf",
        "COUNT(*)::bigint AS n_rows",
    ]

    if ts_col:
        select_parts += [
            f"MIN({ts_col}) AS min_ts",
            f"MAX({ts_col}) AS max_ts",
        ]

    if has_bar_seq:
        select_parts += [
            "COUNT(DISTINCT bar_seq)::bigint AS n_bar_seq",
        ]

    if has_tf_days:
        select_parts += [
            "MIN(tf_days)::int AS tf_days_min",
            "MAX(tf_days)::int AS tf_days_max",
        ]

    if has_is_partial_end:
        select_parts += [
            "SUM(CASE WHEN is_partial_end THEN 1 ELSE 0 END)::bigint AS n_partial_end_true",
            "SUM(CASE WHEN NOT is_partial_end THEN 1 ELSE 0 END)::bigint AS n_partial_end_false",
        ]

    if has_is_partial_start:
        select_parts += [
            "SUM(CASE WHEN is_partial_start THEN 1 ELSE 0 END)::bigint AS n_partial_start_true",
            "SUM(CASE WHEN NOT is_partial_start THEN 1 ELSE 0 END)::bigint AS n_partial_start_false",
        ]

    if has_is_missing_days:
        select_parts += [
            "SUM(CASE WHEN is_missing_days THEN 1 ELSE 0 END)::bigint AS n_missing_days_true",
            "SUM(CASE WHEN NOT is_missing_days THEN 1 ELSE 0 END)::bigint AS n_missing_days_false",
        ]

    if has_count_days:
        select_parts += [
            "MIN(count_days)::int AS count_days_min",
            "MAX(count_days)::int AS count_days_max",
        ]

    if has_count_days_remaining:
        select_parts += [
            "MIN(count_days_remaining)::int AS count_days_remaining_min",
            "MAX(count_days_remaining)::int AS count_days_remaining_max",
        ]

    q = text(
        f"""
        SELECT
          {", ".join(select_parts)}
        FROM {table}
        WHERE id IN ({in_clause})
        GROUP BY id, tf
        ORDER BY id, tf
        """
    )

    df = pd.read_sql(q, engine)

    # Derived checks (portable, no extra DB calls)
    df["audit_generated_at"] = datetime.now(UTC).isoformat()

    # Snapshot behavior: if bar_seq exists, n_rows should usually exceed n_bar_seq for snapshot tables.
    if "n_bar_seq" in df.columns:
        df["rows_per_bar_seq"] = (df["n_rows"] / df["n_bar_seq"]).round(4)
        df["has_snapshot_multiplicity"] = df["n_rows"] > df["n_bar_seq"]

    # Canonical vs snapshot split: if is_partial_end exists, canonical rows are where is_partial_end = FALSE.
    if "n_partial_end_false" in df.columns:
        df["canonical_share"] = (df["n_partial_end_false"] / df["n_rows"]).round(6)

    # Missing days share
    if "n_missing_days_true" in df.columns:
        df["missing_days_share"] = (df["n_missing_days_true"] / df["n_rows"]).round(6)

    # tf_days stability: for TFs where tf_days should be constant, tf_days_min == tf_days_max
    if "tf_days_min" in df.columns and "tf_days_max" in df.columns:
        df["tf_days_constant"] = df["tf_days_min"] == df["tf_days_max"]
        df["tf_days_span"] = df["tf_days_max"] - df["tf_days_min"]

    # Policy hint: anchors often have partial-start; CAL tables generally should not.
    if "n_partial_start_true" in df.columns:
        df["partial_start_share"] = (df["n_partial_start_true"] / df["n_rows"]).round(6)

    return df


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit 5 price_bars tables and write a combined CSV."
    )
    ap.add_argument(
        "--ids", required=True, help="all OR comma-separated list like 1,52"
    )
    ap.add_argument(
        "--daily-table",
        default=DEFAULT_DAILY_TABLE,
        help="Daily source table used only to resolve --ids all",
    )
    ap.add_argument("--out", default="price_bars_audit.csv", help="Output CSV filename")
    ap.add_argument(
        "--print-fingerprint",
        action="store_true",
        help="Print __file__ and sha1 of the executing script (useful in Spyder).",
    )

    args = ap.parse_args()

    if args.print_fingerprint:
        try:
            _log(f"__file__ = {__file__}")
            with open(__file__, "rb") as f:
                _log(f"sha1 = {hashlib.sha1(f.read()).hexdigest()}")
        except Exception as e:
            _log(f"Could not fingerprint file: {e}")

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
        raise RuntimeError(
            "No tables produced results. Check table names/schema and permissions."
        )

    out_df = pd.concat(frames, ignore_index=True)

    # Helpful sorting
    sort_cols = [c for c in ["table_name", "id", "tf"] if c in out_df.columns]
    if sort_cols:
        out_df = out_df.sort_values(sort_cols).reset_index(drop=True)

    out_df.to_csv(args.out, index=False)
    _log(f"Wrote {len(out_df)} rows -> {args.out}")


if __name__ == "__main__":
    main()
