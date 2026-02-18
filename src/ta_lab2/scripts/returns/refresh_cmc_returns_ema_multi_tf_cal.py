from __future__ import annotations

r"""
refresh_cmc_returns_ema_multi_tf_cal.py

Unified incremental EMA-returns builder for calendar-aligned EMA tables (US/ISO),
covering BOTH series families:

  series='ema'     uses source columns: ema, roll
  series='ema_bar' uses source columns: ema_bar, roll

Source tables (by scheme):
  - US  : public.cmc_ema_multi_tf_cal_us
  - ISO : public.cmc_ema_multi_tf_cal_iso

Outputs (by scheme, unified):
  - US  : public.cmc_returns_ema_multi_tf_cal_us
  - ISO : public.cmc_returns_ema_multi_tf_cal_iso

State (by scheme, unified):
  - US  : public.cmc_returns_ema_multi_tf_cal_us_state
  - ISO : public.cmc_returns_ema_multi_tf_cal_iso_state

State key:
  (id, tf, period, series, roll) -> last_ts

Semantics:
  - Partition by (id, tf, period, series, roll), ordered by ts
  - Inserts only rows with a valid previous value (so coverage: n_ret == n_ema - 1)
  - Incremental by default:
      inserts rows where ts > last_ts
      but pulls ts >= last_ts to seed prev_ema for the first new row
  - --full-refresh deletes existing rows for selected keys and resets state

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_ema_multi_tf_cal.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--scheme both --series both --ids all --roll-mode both"
)
"""

import argparse
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine


# Sources
DEFAULT_EMA_CAL_US = "public.cmc_ema_multi_tf_cal_us"
DEFAULT_EMA_CAL_ISO = "public.cmc_ema_multi_tf_cal_iso"

# Unified outputs per scheme
DEFAULT_RET_US = "public.cmc_returns_ema_multi_tf_cal_us"
DEFAULT_RET_ISO = "public.cmc_returns_ema_multi_tf_cal_iso"

# Unified state per scheme
DEFAULT_STATE_US = "public.cmc_returns_ema_multi_tf_cal_us_state"
DEFAULT_STATE_ISO = "public.cmc_returns_ema_multi_tf_cal_iso_state"


@dataclass(frozen=True)
class RunnerConfig:
    db_url: str
    scheme: str  # us|iso|both
    series: str  # ema|ema_bar|both
    roll_mode: str  # canonical|roll|both
    start: str
    full_refresh: bool

    ema_us: str
    ema_iso: str
    ret_us: str
    ret_iso: str
    state_us: str
    state_iso: str


def _print(msg: str) -> None:
    print(f"[ret_ema_cal] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def _parse_ids(ids_arg: str) -> Optional[List[int]]:
    s = ids_arg.strip().lower()
    if s == "all":
        return None
    return [int(x.strip()) for x in ids_arg.split(",") if x.strip()]


def expand_scheme(s: str) -> List[str]:
    s = s.strip().lower()
    if s == "both":
        return ["us", "iso"]
    if s in ("us", "iso"):
        return [s]
    raise ValueError("scheme must be one of: us, iso, both")


def expand_series(s: str) -> List[str]:
    s = s.strip().lower()
    if s == "both":
        return ["ema", "ema_bar"]
    if s in ("ema", "ema_bar"):
        return [s]
    raise ValueError("series must be one of: ema, ema_bar, both")


def expand_roll_mode(mode: str) -> List[bool]:
    mode = mode.strip().lower()
    if mode == "both":
        return [False, True]
    if mode == "canonical":
        return [False]
    if mode == "roll":
        return [True]
    raise ValueError("roll-mode must be one of: both, canonical, roll")


def _ensure_tables(engine: Engine, ret_table: str, state_table: str) -> None:
    """Create returns and state tables if they don't exist."""
    out_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {ret_table} (
            id        bigint NOT NULL,
            ts        timestamptz NOT NULL,
            tf        text NOT NULL,
            period    integer NOT NULL,
            series    text NOT NULL CHECK (series IN ('ema','ema_bar')),
            roll      boolean NOT NULL,

            gap_days  integer,

            delta1        double precision,
            delta2        double precision,

            ret_arith     double precision,
            ret_log       double precision,

            delta_ret_arith double precision,
            delta_ret_log   double precision,

            ingested_at timestamptz NOT NULL DEFAULT now(),

            PRIMARY KEY (id, ts, tf, period, series, roll)
        );
        """
    )

    state_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {state_table} (
            id       bigint NOT NULL,
            tf       text NOT NULL,
            period   integer NOT NULL,
            series   text NOT NULL,
            roll     boolean NOT NULL,
            last_ts  timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, tf, period, series, roll)
        );
        """
    )

    with engine.begin() as cxn:
        cxn.execute(out_sql)
        cxn.execute(state_sql)


def _load_keys(
    engine: Engine,
    ema_table: str,
    ids: Optional[List[int]],
    series: str,
    roll_mode: str,
) -> List[Tuple[int, str, int, str, bool]]:
    """
    Returns keys as: (id, tf, period, series, roll)
    - For both series, roll comes from source column 'roll'
    """
    rolls = expand_roll_mode(roll_mode)
    roll_col = "roll"

    if ids is None:
        sql = text(
            f"""
            SELECT DISTINCT id::bigint, tf::text, period::int, {roll_col}::bool AS roll
            FROM {ema_table}
            WHERE {roll_col} = ANY(:rolls)
            ORDER BY 1,2,3,4;
            """
        )
        with engine.begin() as cxn:
            rows = cxn.execute(sql, {"rolls": rolls}).fetchall()
    else:
        sql = text(
            f"""
                SELECT DISTINCT id::bigint, tf::text, period::int, {roll_col}::bool AS roll
                FROM {ema_table}
                WHERE id IN :ids
                  AND {roll_col} = ANY(:rolls)
                ORDER BY 1,2,3,4;
                """
        ).bindparams(bindparam("ids", expanding=True))
        with engine.begin() as cxn:
            rows = cxn.execute(sql, {"ids": ids, "rolls": rolls}).fetchall()

    return [(int(r[0]), str(r[1]), int(r[2]), series, bool(r[3])) for r in rows]


def _ensure_state_rows(
    engine: Engine,
    state_table: str,
    keys: List[Tuple[int, str, int, str, bool]],
) -> None:
    if not keys:
        return

    # per-key INSERT; (fast enough at 5k keys; avoids bulk param issues)
    ins = text(
        f"""
        INSERT INTO {state_table} (id, tf, period, series, roll, last_ts)
        VALUES (:id, :tf, :period, :series, :roll, NULL)
        ON CONFLICT (id, tf, period, series, roll) DO NOTHING;
        """
    )
    with engine.begin() as cxn:
        for i, tf, period, series, roll in keys:
            cxn.execute(
                ins,
                {"id": i, "tf": tf, "period": period, "series": series, "roll": roll},
            )


def _full_refresh(
    engine: Engine,
    ret_table: str,
    state_table: str,
    keys: List[Tuple[int, str, int, str, bool]],
) -> None:
    if not keys:
        return

    _print(
        f"--full-refresh: deleting existing rows for {len(keys)} keys and resetting state."
    )

    del_ret = text(
        f"""
        DELETE FROM {ret_table}
        WHERE id=:id AND tf=:tf AND period=:period AND series=:series AND roll=:roll;
        """
    )
    del_state = text(
        f"""
        DELETE FROM {state_table}
        WHERE id=:id AND tf=:tf AND period=:period AND series=:series AND roll=:roll;
        """
    )

    with engine.begin() as cxn:
        for i, tf, period, series, roll in keys:
            params = {
                "id": i,
                "tf": tf,
                "period": period,
                "series": series,
                "roll": roll,
            }
            cxn.execute(del_ret, params)
            cxn.execute(del_state, params)

    _ensure_state_rows(engine, state_table, keys)


def _run_one_key(
    engine: Engine,
    ema_table: str,
    ret_table: str,
    state_table: str,
    start: str,
    key: Tuple[int, str, int, str, bool],
) -> None:
    one_id, one_tf, one_period, one_series, one_roll = key

    ema_expr = "e.ema" if one_series == "ema" else "e.ema_bar"
    roll_col = "roll"

    sql = text(
        f"""
        WITH st AS (
            SELECT last_ts
            FROM {state_table}
            WHERE id = :id AND tf = :tf AND period = :period AND series = :series AND roll = :roll
        ),
        seed AS (
            SELECT COALESCE(
                (SELECT e2.ts FROM {ema_table} e2
                 WHERE e2.id = :id AND e2.tf = :tf AND e2.period = :period
                   AND e2.{roll_col} = :roll
                   AND e2.ts < (SELECT last_ts FROM st)
                 ORDER BY e2.ts DESC LIMIT 1),
                (SELECT last_ts FROM st),
                CAST(:start AS timestamptz)
            ) AS seed_ts
        ),
        src AS (
            SELECT
                e.id::bigint AS id,
                e.ts,
                e.tf,
                e.period,
                {ema_expr} AS ema
            FROM {ema_table} e, seed
            WHERE e.id = :id
              AND e.tf = :tf
              AND e.period = :period
              AND e.{roll_col} = :roll
              AND e.ts >= seed.seed_ts
        ),
        lagged AS (
            SELECT
                s.*,
                LAG(s.ts)  OVER (ORDER BY s.ts) AS prev_ts,
                LAG(s.ema) OVER (ORDER BY s.ts) AS prev_ema
            FROM src s
        ),
        calc AS (
            SELECT
                id, ts, tf, period,
                CAST(:series AS text) AS series,
                CAST(:roll   AS boolean) AS roll,
                (ts::date - prev_ts::date)::int AS gap_days,
                ema - prev_ema AS delta1,
                CASE WHEN prev_ema = 0 THEN NULL
                     ELSE (ema / prev_ema) - 1 END AS ret_arith,
                CASE WHEN prev_ema <= 0 OR ema <= 0 THEN NULL
                     ELSE LN(ema / prev_ema) END AS ret_log
            FROM lagged
            WHERE prev_ema IS NOT NULL
              AND prev_ts IS NOT NULL
              AND ema IS NOT NULL
        ),
        calc2 AS (
            SELECT c.*,
                c.delta1 - LAG(c.delta1) OVER (ORDER BY c.ts) AS delta2,
                c.ret_arith - LAG(c.ret_arith) OVER (ORDER BY c.ts) AS delta_ret_arith,
                c.ret_log - LAG(c.ret_log) OVER (ORDER BY c.ts) AS delta_ret_log
            FROM calc c
        ),
        to_insert AS (
            SELECT c2.*
            FROM calc2 c2
            CROSS JOIN st
            WHERE (st.last_ts IS NULL) OR (c2.ts > st.last_ts)
        ),
        ins AS (
            INSERT INTO {ret_table} (
                id, ts, tf, period, series, roll,
                gap_days, delta1, delta2,
                ret_arith, ret_log,
                delta_ret_arith, delta_ret_log,
                ingested_at
            )
            SELECT
                id, ts, tf, period, series, roll,
                gap_days, delta1, delta2,
                ret_arith, ret_log,
                delta_ret_arith, delta_ret_log,
                now()
            FROM to_insert
            ON CONFLICT (id, ts, tf, period, series, roll) DO NOTHING
            RETURNING ts
        )
        UPDATE {state_table} s
        SET
            last_ts = COALESCE((SELECT MAX(ts) FROM ins), s.last_ts),
            updated_at = now()
        WHERE s.id = :id AND s.tf = :tf AND s.period = :period AND s.series = :series AND s.roll = :roll;
        """
    )

    with engine.begin() as cxn:
        cxn.execute(
            sql,
            {
                "id": one_id,
                "tf": one_tf,
                "period": one_period,
                "series": one_series,
                "roll": one_roll,
                "start": start,
            },
        )


def main() -> None:
    p = argparse.ArgumentParser(
        description="Unified EMA returns builder for CAL US/ISO (ema + ema_bar)."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="Postgres DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--scheme", default="both", help="us | iso | both")
    p.add_argument("--series", default="both", help="ema | ema_bar | both")
    p.add_argument("--roll-mode", default="both", help="both | canonical | roll")
    p.add_argument("--ids", default="all", help="Comma-separated ids, or 'all'.")
    p.add_argument(
        "--start", default="2010-01-01", help="Start timestamptz for full history runs."
    )
    p.add_argument(
        "--full-refresh",
        action="store_true",
        help="Recompute history for selected keys from --start.",
    )

    p.add_argument("--ema-us", default=DEFAULT_EMA_CAL_US)
    p.add_argument("--ema-iso", default=DEFAULT_EMA_CAL_ISO)
    p.add_argument("--ret-us", default=DEFAULT_RET_US)
    p.add_argument("--ret-iso", default=DEFAULT_RET_ISO)
    p.add_argument("--state-us", default=DEFAULT_STATE_US)
    p.add_argument("--state-iso", default=DEFAULT_STATE_ISO)

    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    cfg = RunnerConfig(
        db_url=db_url,
        scheme=args.scheme.strip().lower(),
        series=args.series.strip().lower(),
        roll_mode=args.roll_mode.strip().lower(),
        start=args.start,
        full_refresh=bool(args.full_refresh),
        ema_us=args.ema_us,
        ema_iso=args.ema_iso,
        ret_us=args.ret_us,
        ret_iso=args.ret_iso,
        state_us=args.state_us,
        state_iso=args.state_iso,
    )

    _print(
        "Using DB URL from TARGET_DB_URL env."
        if os.getenv("TARGET_DB_URL")
        else "Using DB URL from --db-url."
    )
    _print(
        f"Runner config: scheme={cfg.scheme}, series={cfg.series}, roll_mode={cfg.roll_mode}, "
        f"ids={args.ids}, start={cfg.start}, full_refresh={cfg.full_refresh}"
    )

    engine = _get_engine(cfg.db_url)
    ids = _parse_ids(args.ids)

    schemes = expand_scheme(cfg.scheme)
    series_list = expand_series(cfg.series)

    for sch in schemes:
        ema_table = cfg.ema_us if sch == "us" else cfg.ema_iso
        ret_table = cfg.ret_us if sch == "us" else cfg.ret_iso
        state_table = cfg.state_us if sch == "us" else cfg.state_iso

        _print(f"=== scheme={sch.upper()} ===")
        _print(f"ema={ema_table}")
        _print(f"ret={ret_table}")
        _print(f"state={state_table}")

        _ensure_tables(engine, ret_table, state_table)

        for ser in series_list:
            keys = _load_keys(engine, ema_table, ids, ser, cfg.roll_mode)
            _print(f"series={ser}: resolved keys={len(keys)}")

            if not keys:
                continue

            _ensure_state_rows(engine, state_table, keys)

            if cfg.full_refresh:
                _full_refresh(engine, ret_table, state_table, keys)

            for i, key in enumerate(keys, start=1):
                one_id, one_tf, one_period, one_series, one_roll = key
                _print(
                    f"Processing key=({one_id},{one_tf},{one_period},{one_series},roll={one_roll}) ({i}/{len(keys)})"
                )
                _run_one_key(engine, ema_table, ret_table, state_table, cfg.start, key)

    _print("Done.")


if __name__ == "__main__":
    main()
