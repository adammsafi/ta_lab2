from __future__ import annotations

r"""
refresh_cmc_returns_ema_multi_tf_v2.py

Incremental EMA-returns builder from public.cmc_ema_multi_tf_v2.

Writes:
  public.cmc_returns_ema_multi_tf_v2

State:
  public.cmc_returns_ema_multi_tf_v2_state  (watermark per key: (id, tf, period, roll) -> last_ts)

Semantics:
  - Computes arithmetic and log returns on EMA series
  - Partition: (id, tf, period, roll), ordered by time_close (ts)
  - gap_days computed from time_close (date difference between consecutive EMA points)
  - Incremental by default:
      inserts rows where time_close > last_ts per key
      but pulls time_close >= last_ts to seed prev_ema for the first new row
  - History recomputed only with --full-refresh

Spyder run examples:
Incremental:

runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_ema_multi_tf_v2.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--ids all --roll-mode both"
)

Full refresh:

runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_ema_multi_tf_v2.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--ids all --roll-mode both --full-refresh"
)

"""

import argparse
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_EMA_TABLE = "public.cmc_ema_multi_tf_v2"
DEFAULT_OUT_TABLE = "public.cmc_returns_ema_multi_tf_v2"
DEFAULT_STATE_TABLE = "public.cmc_returns_ema_multi_tf_v2_state"


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
    print(f"[ret_ema_v2] {msg}")


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
            prev_ema  double precision,
            gap_days  integer,

            ret_arith double precision,
            ret_log   double precision,

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


def _load_keys(
    engine: Engine,
    ema_table: str,
    ids: Optional[List[int]],
    roll_mode: str,
) -> List[Tuple[int, str, int, bool]]:
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
        sql = text(
            f"""
                SELECT DISTINCT id::bigint, tf::text, period::int, roll::bool
                FROM {ema_table}
                WHERE id IN :ids
                  AND roll = ANY(:rolls)
                ORDER BY id, tf, period, roll;
                """
        ).bindparams(bindparam("ids", expanding=True))
        with engine.begin() as cxn:
            rows = cxn.execute(sql, {"ids": ids, "rolls": rolls}).fetchall()

    return [(int(r[0]), str(r[1]), int(r[2]), bool(r[3])) for r in rows]


def _ensure_state_rows(
    engine: Engine, state_table: str, keys: List[Tuple[int, str, int, bool]]
) -> None:
    """
    Create state rows for all keys (idempotent). We still do this row-by-row because it's small
    (one row per key) and avoids any bulk-param typing issues.
    """
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
        for i, tf, period, roll in keys:
            cxn.execute(ins, {"id": i, "tf": tf, "period": period, "roll": roll})


def _read_state_for_keys(
    engine: Engine, state_table: str, ids: Optional[List[int]]
) -> List[Tuple[int, str, int, bool, Optional[str]]]:
    """
    Correct pattern to read state. (You may not need this for the per-key CTE approach,
    but keeping it here is useful for debugging and audits.)
    """
    if ids is None:
        sql = text(
            f"""
            SELECT id::bigint, tf::text, period::int, roll::bool, last_ts::timestamptz
            FROM {state_table};
            """
        )
        with engine.begin() as cxn:
            rows = cxn.execute(sql).fetchall()
    else:
        sql = text(
            f"""
                SELECT id::bigint, tf::text, period::int, roll::bool, last_ts::timestamptz
                FROM {state_table}
                WHERE id IN :ids;
                """
        ).bindparams(bindparam("ids", expanding=True))
        with engine.begin() as cxn:
            rows = cxn.execute(sql, {"ids": ids}).fetchall()

    # last_ts returned as Python datetime by SQLAlchemy/psycopg; keep as-is in practice.
    return [(int(r[0]), str(r[1]), int(r[2]), bool(r[3]), r[4]) for r in rows]


def _full_refresh(
    engine: Engine,
    out_table: str,
    state_table: str,
    keys: List[Tuple[int, str, int, bool]],
) -> None:
    if not keys:
        return

    _print(
        f"--full-refresh: deleting existing rows for {len(keys)} (id,tf,period,roll) keys and resetting state."
    )

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
        for i, tf, period, roll in keys:
            params = {"id": i, "tf": tf, "period": period, "roll": roll}
            cxn.execute(del_out, params)
            cxn.execute(del_state, params)

    _ensure_state_rows(engine, state_table, keys)


def _run_one_key(
    engine: Engine, cfg: RunnerConfig, key: Tuple[int, str, int, bool]
) -> None:
    """
    Correct incremental watermark logic (EMA-specific):
      - pull ts >= last_ts to seed prev_ema
      - insert only ts > last_ts
    Also ensures we avoid :param::type casts inside text().
    """
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
              -- Seed window: ts >= last_ts (or >= start if last_ts is NULL)
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
            -- Minimal set: arith return, log return, gap_days (optional but recommended)
            SELECT
                id,
                ts,
                tf,
                period,
                roll,
                ema,
                prev_ema,
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
        cxn.execute(
            sql,
            {
                "id": one_id,
                "tf": one_tf,
                "period": one_period,
                "roll": one_roll,
                "start": cfg.start,
            },
        )


def _upsert_state_bulk_unnest(
    engine: Engine,
    state_table: str,
    rows: List[Tuple[int, str, int, bool, Optional[object]]],
) -> None:
    """
    Option 2 (bulletproof): INSERT ... SELECT FROM UNNEST to upsert state in bulk.

    rows: list of (id, tf, period, roll, last_ts)
    """
    if not rows:
        return

    ids = [int(r[0]) for r in rows]
    tfs = [str(r[1]) for r in rows]
    periods = [int(r[2]) for r in rows]
    rolls = [bool(r[3]) for r in rows]
    last_ts = [r[4] for r in rows]  # tz-aware datetimes (or None)

    upsert_sql = text(
        f"""
        INSERT INTO {state_table} (id, tf, period, roll, last_ts)
        SELECT
            x.id,
            x.tf,
            x.period,
            x.roll,
            x.last_ts
        FROM UNNEST(
            :ids,
            :tfs,
            :periods,
            :rolls,
            :last_ts
        ) AS x(id, tf, period, roll, last_ts)
        ON CONFLICT (id, tf, period, roll)
        DO UPDATE SET
            last_ts = EXCLUDED.last_ts,
            updated_at = now();
        """
    )

    with engine.begin() as cxn:
        cxn.execute(
            upsert_sql,
            {
                "ids": ids,
                "tfs": tfs,
                "periods": periods,
                "rolls": rolls,
                "last_ts": last_ts,
            },
        )


def main() -> None:
    p = argparse.ArgumentParser(
        description="Incremental EMA returns builder for cmc_ema_multi_tf_v2 (arith + log)."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="Postgres DB URL (or set TARGET_DB_URL).",
    )

    p.add_argument("--ids", default="all", help="Comma-separated ids, or 'all'.")
    p.add_argument(
        "--start", default="2010-01-01", help="Start timestamptz for full history runs."
    )
    p.add_argument("--roll-mode", default="both", help="both | canonical | roll")

    p.add_argument("--ema-table", default=DEFAULT_EMA_TABLE, help="Source EMA table.")
    p.add_argument(
        "--out-table", default=DEFAULT_OUT_TABLE, help="Output returns table."
    )
    p.add_argument("--state-table", default=DEFAULT_STATE_TABLE, help="State table.")
    p.add_argument(
        "--full-refresh",
        action="store_true",
        help="Recompute history for selected keys from --start.",
    )

    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    cfg = RunnerConfig(
        db_url=db_url,
        ema_table=args.ema_table,
        out_table=args.out_table,
        state_table=args.state_table,
        start=args.start,
        full_refresh=bool(args.full_refresh),
        roll_mode=args.roll_mode.strip().lower(),
    )

    _print(
        "Using DB URL from TARGET_DB_URL env."
        if os.getenv("TARGET_DB_URL")
        else "Using DB URL from --db-url."
    )
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
        _print(
            f"Processing key=({one_id},{one_tf},{one_period},roll={one_roll}) ({i}/{len(keys)})"
        )
        _run_one_key(engine, cfg, key)

    _print("Done.")


if __name__ == "__main__":
    main()
