from __future__ import annotations

r"""
refresh_cmc_returns_ema_multi_tf_cal_anchor.py

Incremental returns builder for calendar-anchored EMA tables.

Source EMA tables:
  public.cmc_ema_multi_tf_cal_anchor_us
  public.cmc_ema_multi_tf_cal_anchor_iso

Writes returns tables:
  public.cmc_returns_ema_multi_tf_cal_anchor_us
  public.cmc_returns_ema_multi_tf_cal_anchor_iso

State tables:
  public.cmc_returns_ema_multi_tf_cal_anchor_us_state
  public.cmc_returns_ema_multi_tf_cal_anchor_iso_state

State key:
  (id, tf, period) -> last_ts

Semantics:
  - Processes BOTH roll=True and roll=False EMA rows for each (id,tf,period)
    in a single unified timeline ordered by ts.
  - Non-roll value columns (_ema, _ema_bar): populated only on roll=False rows,
    computed via LAG within the roll=False partition (canonical->canonical).
  - Roll value columns (_ema_roll, _ema_bar_roll): populated on ALL rows,
    computed via LAG over the unified timeline (daily transitions, including
    the cross-roll transition at bar close timestamps).
  - PK: (id, ts, tf, period); roll is a regular boolean column.
  - Incremental by default:
      inserts rows where ts > last_ts per key
      but pulls ts >= seed_ts to seed prev values for the first new row
  - History recomputed only with --full-refresh

Spyder run example:
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_ema_multi_tf_cal_anchor.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--scheme both --ids all"
)
"""

import argparse
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_EMA_US = "public.cmc_ema_multi_tf_cal_anchor_us"
DEFAULT_EMA_ISO = "public.cmc_ema_multi_tf_cal_anchor_iso"

DEFAULT_RET_US = "public.cmc_returns_ema_multi_tf_cal_anchor_us"
DEFAULT_RET_ISO = "public.cmc_returns_ema_multi_tf_cal_anchor_iso"

DEFAULT_STATE_US = "public.cmc_returns_ema_multi_tf_cal_anchor_us_state"
DEFAULT_STATE_ISO = "public.cmc_returns_ema_multi_tf_cal_anchor_iso_state"


@dataclass(frozen=True)
class RunnerConfig:
    db_url: str
    scheme: str  # us | iso | both
    start: str
    full_refresh: bool


def _print(msg: str) -> None:
    print(f"[ret_ema_cal_anchor] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def _parse_ids(ids_arg: str) -> Optional[List[int]]:
    s = (ids_arg or "").strip().lower()
    if s == "all" or s == "":
        return None
    return [int(x.strip()) for x in ids_arg.split(",") if x.strip()]


def expand_scheme(scheme: str) -> List[str]:
    s = (scheme or "").strip().lower()
    if s == "us":
        return ["us"]
    if s == "iso":
        return ["iso"]
    if s == "both":
        return ["us", "iso"]
    raise ValueError("--scheme must be one of: us, iso, both")


def _tables_for_scheme(scheme: str) -> Tuple[str, str, str]:
    s = scheme.lower()
    if s == "us":
        return (DEFAULT_EMA_US, DEFAULT_RET_US, DEFAULT_STATE_US)
    if s == "iso":
        return (DEFAULT_EMA_ISO, DEFAULT_RET_ISO, DEFAULT_STATE_ISO)
    raise ValueError(f"unknown scheme={scheme}")


def _ensure_tables(engine: Engine, ret_table: str, state_table: str) -> None:
    out_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {ret_table} (
            id        bigint NOT NULL,
            ts        timestamptz NOT NULL,
            tf        text NOT NULL,
            tf_days   integer NOT NULL,
            period    integer NOT NULL,
            roll      boolean NOT NULL,

            gap_days       integer,
            gap_days_roll  integer,

            delta1_ema            double precision,
            delta1_ema_bar        double precision,
            delta1_ema_roll       double precision,
            delta1_ema_bar_roll   double precision,

            delta2_ema            double precision,
            delta2_ema_bar        double precision,
            delta2_ema_roll       double precision,
            delta2_ema_bar_roll   double precision,

            ret_arith_ema         double precision,
            ret_arith_ema_bar     double precision,
            ret_arith_ema_roll    double precision,
            ret_arith_ema_bar_roll double precision,

            ret_log_ema           double precision,
            ret_log_ema_bar       double precision,
            ret_log_ema_roll      double precision,
            ret_log_ema_bar_roll  double precision,

            delta_ret_arith_ema       double precision,
            delta_ret_arith_ema_bar   double precision,
            delta_ret_arith_ema_roll  double precision,
            delta_ret_arith_ema_bar_roll double precision,

            delta_ret_log_ema         double precision,
            delta_ret_log_ema_bar     double precision,
            delta_ret_log_ema_roll    double precision,
            delta_ret_log_ema_bar_roll double precision,

            ingested_at timestamptz NOT NULL DEFAULT now(),

            PRIMARY KEY (id, ts, tf, period)
        );
        """
    )

    state_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {state_table} (
            id       bigint NOT NULL,
            tf       text NOT NULL,
            period   integer NOT NULL,
            last_ts  timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, tf, period)
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
) -> List[Tuple[int, str, int]]:
    """Returns keys as: (id, tf, period)."""
    if ids is None:
        sql = text(
            f"""
            SELECT DISTINCT id::bigint, tf::text, period::int
            FROM {ema_table}
            ORDER BY 1,2,3;
            """
        )
        with engine.begin() as cxn:
            rows = cxn.execute(sql).fetchall()
    else:
        sql = text(
            f"""
            SELECT DISTINCT id::bigint, tf::text, period::int
            FROM {ema_table}
            WHERE id IN :ids
            ORDER BY 1,2,3;
            """
        ).bindparams(bindparam("ids", expanding=True))
        with engine.begin() as cxn:
            rows = cxn.execute(sql, {"ids": ids}).fetchall()

    return [(int(r[0]), str(r[1]), int(r[2])) for r in rows]


def _ensure_state_rows(
    engine: Engine, state_table: str, keys: List[Tuple[int, str, int]]
) -> None:
    if not keys:
        return

    ins = text(
        f"""
        INSERT INTO {state_table} (id, tf, period, last_ts)
        VALUES (:id, :tf, :period, NULL)
        ON CONFLICT (id, tf, period) DO NOTHING;
        """
    )

    with engine.begin() as cxn:
        for i, tf, period in keys:
            cxn.execute(ins, {"id": i, "tf": tf, "period": period})


def _full_refresh(
    engine: Engine, ret_table: str, state_table: str, keys: List[Tuple[int, str, int]]
) -> None:
    if not keys:
        return

    _print(
        f"--full-refresh: deleting existing rows for {len(keys)} keys and resetting state."
    )

    del_ret = text(
        f"""
        DELETE FROM {ret_table}
        WHERE id = :id AND tf = :tf AND period = :period;
        """
    )
    del_state = text(
        f"""
        DELETE FROM {state_table}
        WHERE id = :id AND tf = :tf AND period = :period;
        """
    )

    with engine.begin() as cxn:
        for i, tf, period in keys:
            params = {"id": i, "tf": tf, "period": period}
            cxn.execute(del_ret, params)
            cxn.execute(del_state, params)

    _ensure_state_rows(engine, state_table, keys)


# ---------------------------------------------------------------------------
# Column lists (used in INSERT and ON CONFLICT DO UPDATE)
# ---------------------------------------------------------------------------

_VALUE_COLS = [
    "gap_days",
    "gap_days_roll",
    # ema roll
    "delta1_ema_roll",
    "delta2_ema_roll",
    "ret_arith_ema_roll",
    "delta_ret_arith_ema_roll",
    "ret_log_ema_roll",
    "delta_ret_log_ema_roll",
    # ema canonical
    "delta1_ema",
    "delta2_ema",
    "ret_arith_ema",
    "delta_ret_arith_ema",
    "ret_log_ema",
    "delta_ret_log_ema",
    # ema_bar roll
    "delta1_ema_bar_roll",
    "delta2_ema_bar_roll",
    "ret_arith_ema_bar_roll",
    "delta_ret_arith_ema_bar_roll",
    "ret_log_ema_bar_roll",
    "delta_ret_log_ema_bar_roll",
    # ema_bar canonical
    "delta1_ema_bar",
    "delta2_ema_bar",
    "ret_arith_ema_bar",
    "delta_ret_arith_ema_bar",
    "ret_log_ema_bar",
    "delta_ret_log_ema_bar",
]

_INSERT_COLS = (
    "id, ts, tf, tf_days, period, roll,\n" + ",\n".join(_VALUE_COLS) + ",\ningested_at"
)
_UPSERT_SET = ",\n".join(f"{c} = EXCLUDED.{c}" for c in _VALUE_COLS + ["ingested_at"])


def _run_one_key(
    engine: Engine,
    ema_table: str,
    ret_table: str,
    state_table: str,
    start: str,
    key: Tuple[int, str, int],
) -> None:
    one_id, one_tf, one_period = key

    sql = text(
        f"""
        WITH st AS (
            SELECT last_ts
            FROM {state_table}
            WHERE id = :id AND tf = :tf AND period = :period
        ),
        seed AS (
            SELECT COALESCE(
                (SELECT MIN(sub.ts) FROM (
                    SELECT ts FROM {ema_table}
                    WHERE id = :id AND tf = :tf AND period = :period
                      AND roll = FALSE
                      AND ts < COALESCE((SELECT last_ts FROM st), CAST(:start AS timestamptz))
                    ORDER BY ts DESC
                    LIMIT 2
                ) sub),
                (SELECT last_ts FROM st),
                CAST(:start AS timestamptz)
            ) AS seed_ts
        ),
        src AS (
            SELECT
                e.id::bigint AS id,
                e.ts,
                e.tf,
                e.tf_days,
                e.period,
                e.roll,
                e.ema,
                e.ema_bar
            FROM {ema_table} e, seed
            WHERE e.id = :id
              AND e.tf = :tf
              AND e.period = :period
              AND e.ts >= seed.seed_ts
        ),
        lagged AS (
            SELECT
                s.*,
                LAG(s.ts)      OVER (ORDER BY s.ts) AS prev_ts_u,
                LAG(s.ema)     OVER (ORDER BY s.ts) AS prev_ema_u,
                LAG(s.ema_bar) OVER (ORDER BY s.ts) AS prev_ema_bar_u,
                LAG(s.ts)      OVER (PARTITION BY s.roll ORDER BY s.ts) AS prev_ts_c,
                LAG(s.ema)     OVER (PARTITION BY s.roll ORDER BY s.ts) AS prev_ema_c,
                LAG(s.ema_bar) OVER (PARTITION BY s.roll ORDER BY s.ts) AS prev_ema_bar_c
            FROM src s
        ),
        calc AS (
            SELECT
                id, ts, tf, tf_days, period, roll,

                CASE WHEN NOT roll AND prev_ts_c IS NOT NULL
                     THEN (ts::date - prev_ts_c::date)::int END AS gap_days,
                CASE WHEN prev_ts_u IS NOT NULL
                     THEN (ts::date - prev_ts_u::date)::int END AS gap_days_roll,

                CASE WHEN NOT roll AND prev_ema_c IS NOT NULL
                     THEN ema - prev_ema_c END AS delta1_ema,
                CASE WHEN NOT roll AND prev_ema_bar_c IS NOT NULL
                     THEN ema_bar - prev_ema_bar_c END AS delta1_ema_bar,
                CASE WHEN prev_ema_u IS NOT NULL
                     THEN ema - prev_ema_u END AS delta1_ema_roll,
                CASE WHEN prev_ema_bar_u IS NOT NULL
                     THEN ema_bar - prev_ema_bar_u END AS delta1_ema_bar_roll,

                CASE WHEN NOT roll AND prev_ema_c IS NOT NULL AND prev_ema_c != 0
                     THEN (ema / prev_ema_c) - 1 END AS ret_arith_ema,
                CASE WHEN NOT roll AND prev_ema_bar_c IS NOT NULL AND prev_ema_bar_c != 0
                     THEN (ema_bar / prev_ema_bar_c) - 1 END AS ret_arith_ema_bar,
                CASE WHEN prev_ema_u IS NOT NULL AND prev_ema_u != 0
                     THEN (ema / prev_ema_u) - 1 END AS ret_arith_ema_roll,
                CASE WHEN prev_ema_bar_u IS NOT NULL AND prev_ema_bar_u != 0
                     THEN (ema_bar / prev_ema_bar_u) - 1 END AS ret_arith_ema_bar_roll,

                CASE WHEN NOT roll AND prev_ema_c IS NOT NULL AND prev_ema_c > 0 AND ema > 0
                     THEN LN(ema / prev_ema_c) END AS ret_log_ema,
                CASE WHEN NOT roll AND prev_ema_bar_c IS NOT NULL AND prev_ema_bar_c > 0 AND ema_bar > 0
                     THEN LN(ema_bar / prev_ema_bar_c) END AS ret_log_ema_bar,
                CASE WHEN prev_ema_u IS NOT NULL AND prev_ema_u > 0 AND ema > 0
                     THEN LN(ema / prev_ema_u) END AS ret_log_ema_roll,
                CASE WHEN prev_ema_bar_u IS NOT NULL AND prev_ema_bar_u > 0 AND ema_bar > 0
                     THEN LN(ema_bar / prev_ema_bar_u) END AS ret_log_ema_bar_roll

            FROM lagged
            WHERE prev_ts_u IS NOT NULL
        ),
        calc2 AS (
            SELECT c.*,
                CASE WHEN NOT c.roll
                     THEN c.delta1_ema - LAG(c.delta1_ema) OVER (PARTITION BY c.roll ORDER BY c.ts)
                END AS delta2_ema,
                CASE WHEN NOT c.roll
                     THEN c.delta1_ema_bar - LAG(c.delta1_ema_bar) OVER (PARTITION BY c.roll ORDER BY c.ts)
                END AS delta2_ema_bar,
                c.delta1_ema_roll - LAG(c.delta1_ema_roll) OVER (ORDER BY c.ts) AS delta2_ema_roll,
                c.delta1_ema_bar_roll - LAG(c.delta1_ema_bar_roll) OVER (ORDER BY c.ts) AS delta2_ema_bar_roll,

                CASE WHEN NOT c.roll
                     THEN c.ret_arith_ema - LAG(c.ret_arith_ema) OVER (PARTITION BY c.roll ORDER BY c.ts)
                END AS delta_ret_arith_ema,
                CASE WHEN NOT c.roll
                     THEN c.ret_arith_ema_bar - LAG(c.ret_arith_ema_bar) OVER (PARTITION BY c.roll ORDER BY c.ts)
                END AS delta_ret_arith_ema_bar,
                c.ret_arith_ema_roll - LAG(c.ret_arith_ema_roll) OVER (ORDER BY c.ts) AS delta_ret_arith_ema_roll,
                c.ret_arith_ema_bar_roll - LAG(c.ret_arith_ema_bar_roll) OVER (ORDER BY c.ts) AS delta_ret_arith_ema_bar_roll,

                CASE WHEN NOT c.roll
                     THEN c.ret_log_ema - LAG(c.ret_log_ema) OVER (PARTITION BY c.roll ORDER BY c.ts)
                END AS delta_ret_log_ema,
                CASE WHEN NOT c.roll
                     THEN c.ret_log_ema_bar - LAG(c.ret_log_ema_bar) OVER (PARTITION BY c.roll ORDER BY c.ts)
                END AS delta_ret_log_ema_bar,
                c.ret_log_ema_roll - LAG(c.ret_log_ema_roll) OVER (ORDER BY c.ts) AS delta_ret_log_ema_roll,
                c.ret_log_ema_bar_roll - LAG(c.ret_log_ema_bar_roll) OVER (ORDER BY c.ts) AS delta_ret_log_ema_bar_roll

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
                {_INSERT_COLS}
            )
            SELECT
                {_INSERT_COLS.replace('ingested_at', 'now()')}
            FROM to_insert
            ON CONFLICT (id, ts, tf, period) DO UPDATE SET
                roll = EXCLUDED.roll,
                {_UPSERT_SET}
            RETURNING ts
        )
        UPDATE {state_table} s
        SET
            last_ts = COALESCE((SELECT MAX(ts) FROM ins), s.last_ts),
            updated_at = now()
        WHERE s.id = :id AND s.tf = :tf AND s.period = :period;
        """
    )

    with engine.begin() as cxn:
        cxn.execute(
            sql,
            {
                "id": one_id,
                "tf": one_tf,
                "period": one_period,
                "start": start,
            },
        )


def main() -> None:
    p = argparse.ArgumentParser(
        description="Incremental returns builder for calendar-anchored EMA (unified timeline with _roll columns)."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="Postgres DB URL (or set TARGET_DB_URL).",
    )

    p.add_argument("--scheme", default="both", help="us | iso | both")
    p.add_argument("--ids", default="all", help="Comma-separated ids, or 'all'.")
    p.add_argument(
        "--start",
        default="2010-01-01",
        help="Start timestamptz for backfills/full refresh.",
    )
    p.add_argument(
        "--full-refresh",
        action="store_true",
        help="Recompute history for selected keys from --start.",
    )

    args = p.parse_args()

    db_url = (args.db_url or "").strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    cfg = RunnerConfig(
        db_url=db_url,
        scheme=(args.scheme or "both").strip().lower(),
        start=str(args.start),
        full_refresh=bool(args.full_refresh),
    )

    _print(
        "Using DB URL from TARGET_DB_URL env."
        if os.getenv("TARGET_DB_URL")
        else "Using DB URL from --db-url."
    )
    _print(
        f"Runner config: scheme={cfg.scheme}, "
        f"ids={args.ids}, start={cfg.start}, full_refresh={cfg.full_refresh}"
    )

    engine = _get_engine(cfg.db_url)
    ids = _parse_ids(args.ids)

    for scheme in expand_scheme(cfg.scheme):
        ema_table, ret_table, state_table = _tables_for_scheme(scheme)

        _print(f"=== scheme={scheme.upper()} ===")
        _print(f"ema={ema_table}")
        _print(f"ret={ret_table}")
        _print(f"state={state_table}")

        _ensure_tables(engine, ret_table, state_table)

        keys = _load_keys(engine, ema_table, ids)
        _print(f"Resolved keys={len(keys)}")
        if not keys:
            _print("No keys found. Skipping scheme.")
            continue

        _ensure_state_rows(engine, state_table, keys)

        if cfg.full_refresh:
            _full_refresh(engine, ret_table, state_table, keys)

        for i, key in enumerate(keys, start=1):
            one_id, one_tf, one_period = key
            _print(f"Processing key=({one_id},{one_tf},{one_period}) ({i}/{len(keys)})")
            _run_one_key(engine, ema_table, ret_table, state_table, cfg.start, key)

    _print("Done.")


if __name__ == "__main__":
    main()
