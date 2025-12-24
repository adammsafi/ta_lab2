from __future__ import annotations

r"""
refresh_cmc_returns_ema_multi_tf.py

Incremental EMA-returns builder from public.cmc_ema_multi_tf.

Writes:
  public.cmc_returns_ema_multi_tf

State:
  public.cmc_returns_ema_multi_tf_state  (watermark per key: (id, tf, period, roll) -> last_ts)

Semantics:
  - Computes arithmetic and log returns on EMA series
  - Partition: (id, tf, period, roll), ordered by ts
  - gap_days computed from ts (date difference between consecutive EMA points)
  - Incremental by default:
      inserts rows where ts > last_ts per key
      but pulls ts >= last_ts to seed prev_ema for the first new row
  - Excludes the first row per key (requires prev_ema IS NOT NULL)
  - History recomputed only with --full-refresh

Spyder run example:
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_ema_multi_tf.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--ids all --roll-mode both"
)
"""

import argparse
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_EMA_TABLE = "public.cmc_ema_multi_tf"
DEFAULT_OUT_TABLE = "public.cmc_returns_ema_multi_tf"
DEFAULT_STATE_TABLE = "public.cmc_returns_ema_multi_tf_state"


@dataclass(frozen=True)
class RunnerConfig:
    db_url: str
    ema_table: str
    out_table: str
    state_table: str
    start: str
    full_refresh: bool
    roll_mode: str  # 'both' | 'canonical' | 'roll'


def _print(msg: str) -> None:
    print(f"[ret_ema_multi_tf] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def expand_roll_mode(mode: str) -> List[bool]:
    """
    Expand roll-mode to concrete roll booleans.
      - both      -> [False, True]
      - canonical -> [False]
      - roll      -> [True]
    """
    mode = mode.strip().lower()
    if mode == "both":
        return [False, True]
    if mode == "canonical":
        return [False]
    if mode == "roll":
        return [True]
    raise ValueError("roll-mode must be one of: both, canonical, roll")


def _ensure_tables(engine: Engine, out_table: str, state_table: str) -> None:
    out_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {out_table} (
            id        bigint NOT NULL,
            ts        timestamptz NOT NULL,
            tf        text NOT NULL,
            period    integer NOT NULL,
            roll      boolean NOT NULL,

            ema       double precision NOT NULL,
            prev_ema  double precision NOT NULL,
            gap_days  integer NOT NULL,

            ret_arith double precision NOT NULL,
            ret_log   double precision NOT NULL,

            ingested_at timestamptz NOT NULL DEFAULT now(),

            PRIMARY KEY (id, ts, tf, period, roll)
        );
        """
    )

    state_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {state_table} (
            id       bigint NOT NULL,
            tf       text NOT NULL,
            period   integer NOT NULL,
            roll     boolean NOT NULL,
            last_ts  timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, tf, period, roll)
        );
        """
    )

    with engine.begin() as cxn:
        cxn.execute(out_sql)
        cxn.execute(state_sql)


def _parse_ids(ids_arg: str) -> Optional[List[int]]:
    s = ids_arg.strip().lower()
    if s == "all":
        return None
    return [int(x.strip()) for x in ids_arg.split(",") if x.strip()]


def _load_keys(engine: Engine, ema_table: str, ids: Optional[List[int]], roll_mode: str) -> List[Tuple[int, str, int, bool]]:
    rolls = expand_roll_mode(roll_mode)

    if ids is None:
        sql = text(
            f"""
            SELECT DISTINCT id::bigint, tf::text, period::int, roll::bool
            FROM {ema_table}
            WHERE roll = ANY(:rolls)
            ORDER BY id, tf, period, roll;
            """
        )
        with engine.begin() as cxn:
            rows = cxn.execute(sql, {"rolls": rolls}).fetchall()
    else:
        sql = (
            text(
                f"""
                SELECT DISTINCT id::bigint, tf::text, period::int, roll::bool
                FROM {ema_table}
                WHERE id IN :ids
                  AND roll = ANY(:rolls)
                ORDER BY id, tf, period, roll;
                """
            )
            .bindparams(bindparam("ids", expanding=True))
        )
        with engine.begin() as cxn:
            rows = cxn.execute(sql, {"ids": ids, "rolls": rolls}).fetchall()

    return [(int(r[0]), str(r[1]), int(r[2]), bool(r[3])) for r in rows]


def _ensure_state_rows(engine: Engine, state_table: str, keys: List[Tuple[int, str, int, bool]]) -> None:
    if not keys:
        return

    ins = text(
        f"""
        INSERT INTO {state_table} (id, tf, period, roll, last_ts)
        VALUES (:id, :tf, :period, :roll, NULL)
        ON CONFLICT (id, tf, period, roll) DO NOTHING;
        """
    )

    with engine.begin() as cxn:
        for (i, tf, period, roll) in keys:
            cxn.execute(ins, {"id": i, "tf": tf, "period": period, "roll": roll})


def _full_refresh(engine: Engine, out_table: str, state_table: str, keys: List[Tuple[int, str, int, bool]]) -> None:
    if not keys:
        return

    _print(f"--full-refresh: deleting existing rows for {len(keys)} (id,tf,period,roll) keys and resetting state.")

    del_out = text(
        f"""
        DELETE FROM {out_table}
        WHERE id = :id AND tf = :tf AND period = :period AND roll = :roll;
        """
    )
    del_state = text(
        f"""
        DELETE FROM {state_table}
        WHERE id = :id AND tf = :tf AND period = :period AND roll = :roll;
        """
    )

    with engine.begin() as cxn:
        for (i, tf, period, roll) in keys:
            params = {"id": i, "tf": tf, "period": period, "roll": roll}
            cxn.execute(del_out, params)
            cxn.execute(del_state, params)

    _ensure_state_rows(engine, state_table, keys)


def _run_one_key(engine: Engine, cfg: RunnerConfig, key: Tuple[int, str, int, bool]) -> None:
    one_id, one_tf, one_period, one_roll = key

    sql = text(
        f"""
        WITH st AS (
            SELECT last_ts
            FROM {cfg.state_table}
            WHERE id = :id AND tf = :tf AND period = :period AND roll = :roll
        ),
        src AS (
            SELECT
                e.id,
                e.ts,
                e.tf,
                e.period,
                e.roll,
                e.ema
            FROM {cfg.ema_table} e
            CROSS JOIN st
            WHERE e.id = :id
              AND e.tf = :tf
              AND e.period = :period
              AND e.roll = :roll
              AND e.ts >= COALESCE(st.last_ts, CAST(:start AS timestamptz))
        ),
        lagged AS (
            SELECT
                s.id,
                s.ts,
                s.tf,
                s.period,
                s.roll,
                s.ema,
                LAG(s.ts)  OVER (PARTITION BY s.id, s.tf, s.period, s.roll ORDER BY s.ts)  AS prev_ts,
                LAG(s.ema) OVER (PARTITION BY s.id, s.tf, s.period, s.roll ORDER BY s.ts)  AS prev_ema
            FROM src s
        ),
        calc AS (
            SELECT
                id,
                ts,
                tf,
                period,
                roll,
                ema,
                prev_ema,
                prev_ts,
                CASE
                    WHEN prev_ts IS NULL THEN NULL
                    ELSE (ts::date - prev_ts::date)::int
                END AS gap_days,
                CASE
                    WHEN prev_ema IS NULL OR prev_ema = 0 THEN NULL
                    ELSE (ema / prev_ema) - 1
                END AS ret_arith,
                CASE
                    WHEN prev_ema IS NULL OR prev_ema <= 0 OR ema <= 0 THEN NULL
                    ELSE LN(ema / prev_ema)
                END AS ret_log
            FROM lagged
        ),
        to_insert AS (
            SELECT c.*
            FROM calc c
            CROSS JOIN st
            WHERE
              c.prev_ema IS NOT NULL
              AND c.gap_days IS NOT NULL
              AND c.ret_arith IS NOT NULL
              AND c.ret_log IS NOT NULL
              AND ((st.last_ts IS NULL) OR (c.ts > st.last_ts))
        ),
        ins AS (
            INSERT INTO {cfg.out_table} (
                id, ts, tf, period, roll,
                ema, prev_ema, gap_days, ret_arith, ret_log,
                ingested_at
            )
            SELECT
                id, ts, tf, period, roll,
                ema, prev_ema, gap_days, ret_arith, ret_log,
                now()
            FROM to_insert
            ON CONFLICT (id, ts, tf, period, roll) DO NOTHING
            RETURNING ts
        )
        UPDATE {cfg.state_table} s
        SET
            last_ts = COALESCE((SELECT MAX(ts) FROM ins), s.last_ts),
            updated_at = now()
        WHERE s.id = :id AND s.tf = :tf AND s.period = :period AND s.roll = :roll;
        """
    )

    with engine.begin() as cxn:
        cxn.execute(sql, {"id": one_id, "tf": one_tf, "period": one_period, "roll": one_roll, "start": cfg.start})


def main() -> None:
    p = argparse.ArgumentParser(description="Incremental EMA returns builder for public.cmc_ema_multi_tf.")
    p.add_argument("--db-url", default=os.getenv("TARGET_DB_URL", ""), help="Postgres DB URL (or set TARGET_DB_URL).")

    p.add_argument("--ids", default="all", help="Comma-separated ids, or 'all'.")
    p.add_argument("--start", default="2010-01-01", help="Start timestamptz for full history runs.")
    p.add_argument("--roll-mode", default="both", help="both | canonical | roll")

    p.add_argument("--ema-table", default=DEFAULT_EMA_TABLE, help="Source EMA table.")
    p.add_argument("--out-table", default=DEFAULT_OUT_TABLE, help="Output returns table.")
    p.add_argument("--state-table", default=DEFAULT_STATE_TABLE, help="State table.")
    p.add_argument("--full-refresh", action="store_true", help="Recompute history for selected keys from --start.")

    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit("ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL.")

    cfg = RunnerConfig(
        db_url=db_url,
        ema_table=args.ema_table,
        out_table=args.out_table,
        state_table=args.state_table,
        start=args.start,
        full_refresh=bool(args.full_refresh),
        roll_mode=args.roll_mode.strip().lower(),
    )

    _print("Using DB URL from TARGET_DB_URL env." if os.getenv("TARGET_DB_URL") else "Using DB URL from --db-url.")
    _print(
        f"Runner config: ids={args.ids}, roll_mode={cfg.roll_mode}, start={cfg.start}, "
        f"ema={cfg.ema_table}, out={cfg.out_table}, state={cfg.state_table}, full_refresh={cfg.full_refresh}"
    )

    engine = _get_engine(cfg.db_url)

    _ensure_tables(engine, cfg.out_table, cfg.state_table)

    ids = _parse_ids(args.ids)
    keys = _load_keys(engine, cfg.ema_table, ids, cfg.roll_mode)
    _print(f"Resolved (id,tf,period,roll) keys from EMA table: {len(keys)}")
    if not keys:
        _print("No keys found. Exiting.")
        return

    _ensure_state_rows(engine, cfg.state_table, keys)

    if cfg.full_refresh:
        _full_refresh(engine, cfg.out_table, cfg.state_table, keys)

    for i, key in enumerate(keys, start=1):
        one_id, one_tf, one_period, one_roll = key
        _print(f"Processing key=({one_id},{one_tf},{one_period},roll={one_roll}) ({i}/{len(keys)})")
        _run_one_key(engine, cfg, key)

    _print("Done.")


if __name__ == "__main__":
    main()
