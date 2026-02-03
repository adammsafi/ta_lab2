from __future__ import annotations

r"""
refresh_cmc_returns_bars_multi_tf_cal_anchor_us.py

Incremental bar-returns builder from:
  public.cmc_price_bars_multi_tf_cal_anchor_us

Writes:
  public.cmc_returns_bars_multi_tf_cal_anchor_us

State:
  public.cmc_returns_bars_multi_tf_cal_anchor_us_state
  (watermark per (id, tf): last_time_close)

Semantics:
  - Returns computed on observed-to-observed bar closes ordered by time_close (NOT bar_seq).
  - First bar per (id, tf) has no return (prev_close NULL) and is not inserted.
  - Incremental by default:
      for each (id, tf), only inserts rows where time_close > last_time_close
      but queries time_close >= last_time_close to seed prev_close for the first new row.
  - History recomputed only with --full-refresh
      (drops outputs + state for the selected table).

Notes:
  - Required for *_cal_anchor_* bar tables where bar_seq is not unique or stable.

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_bars_multi_tf_cal_anchor_us.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args=""
)

Examples:
  # Full rebuild of output + state tables
  args="--full-refresh"

  # Debug: process only first 5 (id,tf) groups
  args="--limit-keys 5"


Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_bars_multi_tf_cal_anchor_us.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--bars-table public.cmc_price_bars_multi_tf_cal_anchor_us "
       "--out-table public.cmc_returns_bars_multi_tf_cal_anchor_us "
       "--state-table public.cmc_returns_bars_multi_tf_cal_anchor_us_state"
)

"""

import argparse
import os
from dataclasses import dataclass
from typing import List

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_us"
DEFAULT_OUT_TABLE = "public.cmc_returns_bars_multi_tf_cal_anchor_us"
DEFAULT_STATE_TABLE = "public.cmc_returns_bars_multi_tf_cal_anchor_us_state"


def _print(msg: str) -> None:
    print(f"[ret_bars_cal_anchor_us] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


@dataclass(frozen=True)
class Key:
    id: int
    tf: str


def ensure_tables(engine: Engine, out_table: str, state_table: str) -> None:
    with engine.begin() as cxn:
        cxn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {out_table} (
                    id           integer NOT NULL,
                    tf           text    NOT NULL,
                    time_close   timestamptz NOT NULL,
                    close        double precision,
                    prev_close   double precision,
                    gap_days     double precision,
                    ret_arith    double precision,
                    ret_log      double precision,
                    ingested_at  timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (id, tf, time_close)
                );
                """
            )
        )
        cxn.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_{out_table.split('.')[-1]}_time_close ON {out_table} (id, tf, time_close);"
            )
        )
        cxn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {state_table} (
                    id              integer NOT NULL,
                    tf              text    NOT NULL,
                    last_time_close timestamptz,
                    updated_at      timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (id, tf)
                );
                """
            )
        )


def drop_tables(engine: Engine, out_table: str, state_table: str) -> None:
    with engine.begin() as cxn:
        cxn.execute(text(f"DROP TABLE IF EXISTS {out_table};"))
        cxn.execute(text(f"DROP TABLE IF EXISTS {state_table};"))


def load_keys(engine: Engine, bars_table: str) -> List[Key]:
    sql = text(f"SELECT DISTINCT id, tf FROM {bars_table} ORDER BY id, tf;")
    with engine.begin() as cxn:
        rows = cxn.execute(sql).fetchall()
    return [Key(int(r[0]), str(r[1])) for r in rows]


def get_last_time_close(engine: Engine, state_table: str, key: Key):
    sql = text(f"SELECT last_time_close FROM {state_table} WHERE id=:id AND tf=:tf;")
    with engine.begin() as cxn:
        row = cxn.execute(sql, {"id": key.id, "tf": key.tf}).fetchone()
    return None if not row else row[0]


def upsert_state(engine: Engine, state_table: str, key: Key, last_time_close) -> None:
    sql = text(
        f"""
        INSERT INTO {state_table} (id, tf, last_time_close, updated_at)
        VALUES (:id, :tf, :tc, now())
        ON CONFLICT (id, tf) DO UPDATE
          SET last_time_close = EXCLUDED.last_time_close,
              updated_at = now();
        """
    )
    with engine.begin() as cxn:
        cxn.execute(sql, {"id": key.id, "tf": key.tf, "tc": last_time_close})


def process_key(
    engine: Engine,
    bars_table: str,
    out_table: str,
    state_table: str,
    key: Key,
    start: str,
) -> int:
    last_tc = get_last_time_close(engine, state_table, key)

    # Seed window: include the last processed bar (>=) to get prev_close for the first new row.
    seed_tc = last_tc if last_tc is not None else start

    insert_sql = text(
        f"""
        WITH src AS (
          SELECT id, tf, time_close, close
          FROM {bars_table}
          WHERE id = :id AND tf = :tf
            AND time_close >= :seed_tc
          ORDER BY time_close
        ),
        calc AS (
          SELECT
            id,
            tf,
            time_close,
            close,
            LAG(close) OVER (ORDER BY time_close) AS prev_close,
            EXTRACT(EPOCH FROM (time_close - LAG(time_close) OVER (ORDER BY time_close))) / 86400.0 AS gap_days
          FROM src
        )
        INSERT INTO {out_table} (
          id, tf, time_close, close, prev_close, gap_days, ret_arith, ret_log, ingested_at
        )
        SELECT
          id,
          tf,
          time_close,
          close,
          prev_close,
          gap_days,
          CASE
            WHEN prev_close IS NULL OR prev_close = 0 THEN NULL
            ELSE (close / prev_close) - 1.0
          END AS ret_arith,
          CASE
            WHEN prev_close IS NULL OR prev_close <= 0 OR close <= 0 THEN NULL
            ELSE LN(close / prev_close)
          END AS ret_log,
          now() AS ingested_at
        FROM calc
        WHERE
          prev_close IS NOT NULL
          AND (:last_tc IS NULL OR time_close > :last_tc)
        ON CONFLICT (id, tf, time_close) DO NOTHING;
        """
    )

    with engine.begin() as cxn:
        res = cxn.execute(
            insert_sql,
            {"id": key.id, "tf": key.tf, "seed_tc": seed_tc, "last_tc": last_tc},
        )

    max_tc_sql = text(
        f"SELECT MAX(time_close) FROM {bars_table} WHERE id=:id AND tf=:tf;"
    )
    with engine.begin() as cxn:
        max_tc = cxn.execute(max_tc_sql, {"id": key.id, "tf": key.tf}).scalar()

    if max_tc is not None:
        upsert_state(engine, state_table, key, max_tc)

    return int(res.rowcount or 0)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Incremental bar returns builder (time_close keyed)."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--bars-table", default=DEFAULT_BARS_TABLE)
    p.add_argument("--out-table", default=DEFAULT_OUT_TABLE)
    p.add_argument("--state-table", default=DEFAULT_STATE_TABLE)
    p.add_argument(
        "--start",
        default="2010-01-01",
        help="Start time_close for initial build / full refresh.",
    )
    p.add_argument(
        "--full-refresh",
        action="store_true",
        help="Drop and rebuild outputs for this table.",
    )
    p.add_argument(
        "--limit-keys",
        type=int,
        default=0,
        help="Debug: process only first N (id,tf) groups.",
    )
    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    engine = _get_engine(db_url)

    if args.full_refresh:
        _print("FULL REFRESH requested: dropping output + state tables.")
        drop_tables(engine, args.out_table, args.state_table)

    ensure_tables(engine, args.out_table, args.state_table)

    keys = load_keys(engine, args.bars_table)
    if args.limit_keys and args.limit_keys > 0:
        keys = keys[: args.limit_keys]
        _print(f"limit_keys={args.limit_keys} => processing {len(keys)} groups")

    _print(f"bars={args.bars_table}")
    _print(f"out={args.out_table}")
    _print(f"state={args.state_table}")
    _print(f"start={args.start}")
    _print(f"keys={len(keys)}")

    total = 0
    for i, key in enumerate(keys, start=1):
        if i == 1 or i % 200 == 0:
            _print(f"Processing {key} ({i}/{len(keys)})")
        n = process_key(
            engine, args.bars_table, args.out_table, args.state_table, key, args.start
        )
        total += n

    _print(f"Inserted rows: {total}")
    _print("Done.")


if __name__ == "__main__":
    main()
