from __future__ import annotations

r"""
refresh_cmc_returns_ema_multi_tf_cal_anchor.py

Incremental returns builder for calendar-anchored EMA tables:

Source EMA tables:
  public.cmc_ema_multi_tf_cal_anchor_us
  public.cmc_ema_multi_tf_cal_anchor_iso

Writes returns tables:
  public.cmc_returns_ema_multi_tf_cal_anchor_us
  public.cmc_returns_ema_multi_tf_cal_anchor_iso

State tables:
  public.cmc_returns_ema_multi_tf_cal_anchor_us_state
  public.cmc_returns_ema_multi_tf_cal_anchor_iso_state

Series:
  - series='ema'     uses (ema, roll)
  - series='ema_bar' uses (ema_bar, roll_bar) but stored as (series='ema_bar', roll=<roll_bar>)

Incremental semantics (EMA-specific):
  - watermark last_ts per (id, tf, period, series, roll)
  - pull src rows where ts >= COALESCE(last_ts, start) to seed prev_ema
  - insert only rows where ts > last_ts (or last_ts IS NULL)
  - state last_ts updated to MAX(inserted ts) per key

Spyder run example:
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_ema_multi_tf_cal_anchor.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--scheme both --series both --ids all --roll-mode both"
)
"""

import argparse
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_EMA_US = "public.cmc_ema_multi_tf_cal_anchor_us"
DEFAULT_EMA_ISO = "public.cmc_ema_multi_tf_cal_anchor_iso"

DEFAULT_RET_US = "public.cmc_returns_ema_multi_tf_cal_anchor_us"
DEFAULT_RET_ISO = "public.cmc_returns_ema_multi_tf_cal_anchor_iso"

DEFAULT_STATE_US = "public.cmc_returns_ema_multi_tf_cal_anchor_us_state"
DEFAULT_STATE_ISO = "public.cmc_returns_ema_multi_tf_cal_anchor_iso_state"


Key = Tuple[int, str, int, str, bool]  # (id, tf, period, series, roll)


@dataclass(frozen=True)
class RunnerConfig:
    db_url: str
    scheme: str          # us | iso | both
    series_mode: str     # ema | ema_bar | both
    roll_mode: str       # canonical | roll | both
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


def expand_roll_mode(mode: str) -> List[bool]:
    m = (mode or "").strip().lower()
    if m == "canonical":
        return [False]
    if m == "roll":
        return [True]
    if m == "both":
        return [False, True]
    raise ValueError("--roll-mode must be one of: both, canonical, roll")


def expand_series_mode(mode: str) -> List[str]:
    m = (mode or "").strip().lower()
    if m == "ema":
        return ["ema"]
    if m == "ema_bar":
        return ["ema_bar"]
    if m == "both":
        return ["ema", "ema_bar"]
    raise ValueError("--series must be one of: ema, ema_bar, both")


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


def _load_keys_for_one_table(
    engine: Engine,
    ema_table: str,
    ids: Optional[List[int]],
    series_list: List[str],
    roll_mode: str,
) -> List[Key]:
    """
    Resolve (id, tf, period, series, roll) keys from EMA source table.

    For series='ema'     => uses roll column
    For series='ema_bar' => uses roll_bar column, but returned as "roll" in the key
    """
    rolls = expand_roll_mode(roll_mode)

    keys: List[Key] = []

    for series in series_list:
        if series == "ema":
            roll_col = "roll"
        elif series == "ema_bar":
            roll_col = "roll_bar"
        else:
            raise ValueError(series)

        if ids is None:
            sql = text(
                f"""
                SELECT DISTINCT id::bigint, tf::text, period::int, {roll_col}::boolean AS roll
                FROM {ema_table}
                WHERE {roll_col} IN :rolls
                ORDER BY id, tf, period, roll;
                """
            ).bindparams(bindparam("rolls", expanding=True))
            with engine.begin() as cxn:
                rows = cxn.execute(sql, {"rolls": rolls}).fetchall()
        else:
            sql = text(
                f"""
                SELECT DISTINCT id::bigint, tf::text, period::int, {roll_col}::boolean AS roll
                FROM {ema_table}
                WHERE id IN :ids
                  AND {roll_col} IN :rolls
                ORDER BY id, tf, period, roll;
                """
            ).bindparams(
                bindparam("ids", expanding=True),
                bindparam("rolls", expanding=True),
            )
            with engine.begin() as cxn:
                rows = cxn.execute(sql, {"ids": ids, "rolls": rolls}).fetchall()

        keys.extend([(int(r[0]), str(r[1]), int(r[2]), series, bool(r[3])) for r in rows])

    # stable ordering
    keys.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    return keys


def _ensure_state_rows(engine: Engine, state_table: str, keys: List[Key]) -> None:
    """
    Bulletproof / fast: INSERT ... SELECT FROM UNNEST ... ON CONFLICT DO NOTHING
    """
    if not keys:
        return

    ids = [k[0] for k in keys]
    tfs = [k[1] for k in keys]
    periods = [k[2] for k in keys]
    series = [k[3] for k in keys]
    rolls = [k[4] for k in keys]

    sql = text(
        f"""
        INSERT INTO {state_table} (id, tf, period, series, roll, last_ts)
        SELECT u.id, u.tf, u.period, u.series, u.roll, NULL::timestamptz
        FROM UNNEST(
            CAST(:ids     AS bigint[]),
            CAST(:tfs     AS text[]),
            CAST(:periods AS int[]),
            CAST(:series  AS text[]),
            CAST(:rolls   AS boolean[])
        ) AS u(id, tf, period, series, roll)
        ON CONFLICT (id, tf, period, series, roll) DO NOTHING;
        """
    )

    with engine.begin() as cxn:
        cxn.execute(
            sql,
            {"ids": ids, "tfs": tfs, "periods": periods, "series": series, "rolls": rolls},
        )


def _full_refresh(engine: Engine, ret_table: str, state_table: str, keys: List[Key]) -> None:
    if not keys:
        return

    _print(f"--full-refresh: deleting existing rows for {len(keys)} keys and resetting state.")

    del_ret = text(
        f"""
        DELETE FROM {ret_table}
        WHERE id = :id AND tf = :tf AND period = :period AND series = :series AND roll = :roll;
        """
    )
    del_state = text(
        f"""
        DELETE FROM {state_table}
        WHERE id = :id AND tf = :tf AND period = :period AND series = :series AND roll = :roll;
        """
    )

    with engine.begin() as cxn:
        for (i, tf, period, series, roll) in keys:
            params = {"id": i, "tf": tf, "period": period, "series": series, "roll": roll}
            cxn.execute(del_ret, params)
            cxn.execute(del_state, params)

    _ensure_state_rows(engine, state_table, keys)


def _run_one_key(
    engine: Engine,
    ema_table: str,
    ret_table: str,
    state_table: str,
    start: str,
    key: Key,
) -> None:
    """
    Build returns for one (id, tf, period, series, roll).
    No ':param::type' casts; only bind params.
    """
    one_id, one_tf, one_period, one_series, one_roll = key

    # Map series -> which EMA column + which roll column to filter on.
    if one_series == "ema":
        ema_col = "ema"
        roll_col = "roll"
    elif one_series == "ema_bar":
        ema_col = "ema_bar"
        roll_col = "roll_bar"
    else:
        raise ValueError(one_series)

    sql = text(
        f"""
        WITH st AS (
            SELECT last_ts
            FROM {state_table}
            WHERE id = :id AND tf = :tf AND period = :period AND series = :series AND roll = :roll
        ),
        src AS (
            SELECT
                e.id::bigint AS id,
                e.ts,
                e.tf,
                e.period,
                e.{ema_col} AS ema
            FROM {ema_table} e
            CROSS JOIN st
            WHERE e.id = :id
              AND e.tf = :tf
              AND e.period = :period
              AND e.{roll_col} = :roll
              AND e.ts >= COALESCE(st.last_ts, CAST(:start AS timestamptz))
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
                id,
                ts,
                tf,
                period,
                CAST(:series AS text) AS series,
                CAST(:roll   AS boolean) AS roll,
                ema,
                prev_ema,
                (ts::date - prev_ts::date)::int AS gap_days,
                (ema / prev_ema) - 1 AS ret_arith,
                LN(ema / prev_ema) AS ret_log
            FROM lagged
            WHERE prev_ts IS NOT NULL
              AND prev_ema IS NOT NULL
              AND prev_ema <> 0
              AND ema IS NOT NULL
              AND ema > 0
              AND prev_ema > 0
        ),
        to_insert AS (
            SELECT c.*
            FROM calc c
            CROSS JOIN st
            WHERE (st.last_ts IS NULL) OR (c.ts > st.last_ts)
        ),
        ins AS (
            INSERT INTO {ret_table} (
                id, ts, tf, period, series, roll,
                ema, prev_ema, gap_days, ret_arith, ret_log,
                ingested_at
            )
            SELECT
                id, ts, tf, period, series, roll,
                ema, prev_ema, gap_days, ret_arith, ret_log,
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
    p = argparse.ArgumentParser(description="Incremental returns builder for calendar-anchored EMA (US/ISO).")
    p.add_argument("--db-url", default=os.getenv("TARGET_DB_URL", ""), help="Postgres DB URL (or set TARGET_DB_URL).")

    p.add_argument("--scheme", default="both", help="us | iso | both")
    p.add_argument("--series", default="both", help="ema | ema_bar | both")
    p.add_argument("--roll-mode", default="both", help="both | canonical | roll")

    p.add_argument("--ids", default="all", help="Comma-separated ids, or 'all'.")
    p.add_argument("--start", default="2010-01-01", help="Start timestamptz for backfills/full refresh.")
    p.add_argument("--full-refresh", action="store_true", help="Recompute history for selected keys from --start.")

    args = p.parse_args()

    db_url = (args.db_url or "").strip()
    if not db_url:
        raise SystemExit("ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL.")

    cfg = RunnerConfig(
        db_url=db_url,
        scheme=(args.scheme or "both").strip().lower(),
        series_mode=(args.series or "both").strip().lower(),
        roll_mode=(args.roll_mode or "both").strip().lower(),
        start=str(args.start),
        full_refresh=bool(args.full_refresh),
    )

    _print("Using DB URL from TARGET_DB_URL env." if os.getenv("TARGET_DB_URL") else "Using DB URL from --db-url.")
    _print(
        f"Runner config: scheme={cfg.scheme}, series={cfg.series_mode}, roll_mode={cfg.roll_mode}, "
        f"ids={args.ids}, start={cfg.start}, full_refresh={cfg.full_refresh}"
    )

    engine = _get_engine(cfg.db_url)
    ids = _parse_ids(args.ids)
    series_list = expand_series_mode(cfg.series_mode)

    for scheme in expand_scheme(cfg.scheme):
        ema_table, ret_table, state_table = _tables_for_scheme(scheme)

        _print(f"=== scheme={scheme.upper()} ===")
        _print(f"ema={ema_table}")
        _print(f"ret={ret_table}")
        _print(f"state={state_table}")

        keys = _load_keys_for_one_table(engine, ema_table, ids, series_list, cfg.roll_mode)
        _print(f"resolved keys={len(keys)}")
        if not keys:
            _print("No keys found. Skipping scheme.")
            continue

        _ensure_state_rows(engine, state_table, keys)

        if cfg.full_refresh:
            _full_refresh(engine, ret_table, state_table, keys)

        for i, key in enumerate(keys, start=1):
            one_id, one_tf, one_period, one_series, one_roll = key
            _print(f"Processing key=({one_id},{one_tf},{one_period},{one_series},roll={one_roll}) ({i}/{len(keys)})")
            _run_one_key(engine, ema_table, ret_table, state_table, cfg.start, key)

    _print("Done.")


if __name__ == "__main__":
    main()
