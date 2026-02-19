# src/ta_lab2/scripts/etl/backfill_ema_diffs.py
from __future__ import annotations

import os

import pandas as pd
from sqlalchemy import create_engine, text

from ta_lab2.features.ema import add_ema_diffs_longform

# --- Config ---
# Point this at your Postgres URL, or override via env var.
DB_URL = os.environ.get(
    "TARGET_DB_URL",
    "postgresql+psycopg2://postgres:3400@localhost:5432/marketdata",
)

# Tables you want to backfill.
# time_col here is just a *preferred* name; we’ll fall back if it’s missing.
TABLES = [
    {"name": "cmc_ema_multi_tf", "time_col": "timeopen"},
]


def _resolve_group_cols(df: pd.DataFrame, table_name: str) -> list[str]:
    """Figure out which grouping columns to use for this table."""
    base_group_cols = ["id", "timeframe", "period"]
    group_cols = [c for c in base_group_cols if c in df.columns]

    required = {"id", "period"}
    if not required.issubset(group_cols):
        raise KeyError(
            f"{table_name}: expected at least 'id' and 'period' columns, "
            f"found group_cols={group_cols}"
        )
    return group_cols


def _resolve_time_col(df: pd.DataFrame, preferred: str | None, table_name: str) -> str:
    """Pick an actual time column to use for sorting / joins."""
    candidates = []
    if preferred is not None:
        candidates.append(preferred)
    # common fallbacks
    candidates.extend(["timeopen", "ts", "time", "timestamp", "date"])

    for c in candidates:
        if c in df.columns:
            return c

    raise KeyError(
        f"{table_name}: could not find a time column. "
        f"Tried: {candidates}. Columns are: {list(df.columns)}"
    )


def backfill_table(engine, table_name: str, preferred_time_col: str | None) -> None:
    print(f"\n=== Backfilling d1/d2 for {table_name} ===")

    with engine.begin() as conn:
        df = pd.read_sql(text(f"SELECT * FROM {table_name}"), conn)

    if df.empty:
        print(f"{table_name}: no rows, skipping.")
        return

    group_cols = _resolve_group_cols(df, table_name)
    time_col = _resolve_time_col(df, preferred_time_col, table_name)

    # Compute d1/d2 in-memory
    add_ema_diffs_longform(
        df,
        group_cols=group_cols,
        ema_col="ema",
        d1_col="d1",
        d2_col="d2",
        time_col=time_col,
        round_places=None,
    )

    # Prepare a temp table with just keys + d1/d2
    key_cols = group_cols + [time_col]
    tmp_table = f"{table_name}_d_tmp"

    payload = df[key_cols + ["d1", "d2"]].copy()

    with engine.begin() as conn:
        # Overwrite / create temp helper table
        payload.to_sql(tmp_table, conn, if_exists="replace", index=False)

        # Build dynamic join condition on all key columns
        join_conds = " AND ".join(f"t.{c} = tmp.{c}" for c in key_cols)

        # Set-based update to push d1/d2 back into the main table
        conn.execute(
            text(
                f"""
                UPDATE {table_name} AS t
                SET d1 = tmp.d1,
                    d2 = tmp.d2
                FROM {tmp_table} AS tmp
                WHERE {join_conds}
                """
            )
        )

        # Drop temp helper
        conn.execute(text(f"DROP TABLE {tmp_table}"))

    print(f"{table_name}: backfill complete.")


def main() -> None:
    engine = create_engine(DB_URL)

    for cfg in TABLES:
        backfill_table(engine, cfg["name"], cfg["time_col"])


if __name__ == "__main__":
    main()
