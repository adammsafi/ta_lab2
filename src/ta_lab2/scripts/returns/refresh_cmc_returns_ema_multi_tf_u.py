from __future__ import annotations

r"""
refresh_cmc_returns_ema_multi_tf_u.py

Incremental EMA-returns builder from:
  public.cmc_ema_multi_tf_u

Writes:
  public.cmc_returns_ema_multi_tf_u

State:
  public.cmc_returns_ema_multi_tf_u_state
    watermark per (id, tf, period, alignment_source, series, roll) -> last_ts

Key semantics:
  - Returns are computed per key:
      (id, tf, period, alignment_source, series, roll)
    ordered by ts
  - series='ema'     uses ema + roll
  - series='ema_bar' uses ema_bar + roll_bar (aliased to roll)
  - Incremental:
      for each key, only insert rows where ts > last_ts
      but pull ts >= last_ts to seed prev_ema (first row)
  - History recomputed only with --full-refresh

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_ema_multi_tf_u.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--ids all --series both --roll-mode both"
)
"""

import argparse
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_EMA_U_TABLE = "public.cmc_ema_multi_tf_u"
DEFAULT_OUT_TABLE = "public.cmc_returns_ema_multi_tf_u"
DEFAULT_STATE_TABLE = "public.cmc_returns_ema_multi_tf_u_state"


Key = Tuple[int, str, int, str, str, bool]  # (id, tf, period, alignment_source, series, roll)


def _print(msg: str) -> None:
    print(f"[ret_ema_u] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def _parse_ids_arg(ids_arg: str) -> Optional[List[int]]:
    s = (ids_arg or "").strip().lower()
    if s in ("", "all"):
        return None
    out: List[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


def _expand_series(series: str) -> List[str]:
    s = (series or "").strip().lower()
    if s in ("both", ""):
        return ["ema", "ema_bar"]
    if s in ("ema", "ema_bar"):
        return [s]
    raise SystemExit("ERROR: --series must be one of: ema, ema_bar, both")


def _expand_roll_mode(roll_mode: str) -> List[bool]:
    s = (roll_mode or "").strip().lower()
    if s in ("both", ""):
        return [False, True]
    if s in ("true", "t", "1"):
        return [True]
    if s in ("false", "f", "0"):
        return [False]
    raise SystemExit("ERROR: --roll-mode must be one of: true, false, both")


def _load_keys(
    engine: Engine,
    ema_u_table: str,
    ids: Sequence[int],
    series_list: Sequence[str],
    rolls: Sequence[bool],
) -> List[Key]:
    """
    Returns distinct key surface from EMA_U, properly mapping roll per series.
    """
    series_set = {s.strip().lower() for s in (series_list or [])}
    want_ema = ("ema" in series_set)
    want_bar = ("ema_bar" in series_set)

    params = {"rolls": list(rolls)}
    where_ids = ""
    if ids:
        where_ids = "AND e.id = ANY(:ids)"
        params["ids"] = list(ids)

    parts: List[str] = []

    if want_ema:
        parts.append(
            f"""
            SELECT DISTINCT
              e.id::int,
              e.tf::text,
              e.period::int,
              e.alignment_source::text,
              'ema'::text AS series,
              e.roll::boolean AS roll
            FROM {ema_u_table} e
            WHERE e.roll = ANY(:rolls)
              {where_ids}
            """
        )

    if want_bar:
        parts.append(
            f"""
            SELECT DISTINCT
              e.id::int,
              e.tf::text,
              e.period::int,
              e.alignment_source::text,
              'ema_bar'::text AS series,
              e.roll_bar::boolean AS roll
            FROM {ema_u_table} e
            WHERE e.ema_bar IS NOT NULL
              AND e.roll_bar IS NOT NULL
              AND e.roll_bar = ANY(:rolls)
              {where_ids}
            """
        )

    if not parts:
        return []

    sql = text(" UNION ALL ".join(parts) + " ORDER BY 1,2,3,4,5,6;")

    with engine.begin() as cxn:
        rows = cxn.execute(sql, params).fetchall()

    return [(int(r[0]), str(r[1]), int(r[2]), str(r[3]), str(r[4]), bool(r[5])) for r in rows]


def _ensure_state_rows(engine: Engine, state_table: str, keys: List[Key]) -> None:
    # Bulk insert via executemany VALUES (safe, no array typing weirdness)
    sql = text(
        f"""
        INSERT INTO {state_table} (id, tf, period, alignment_source, series, roll, last_ts, updated_at)
        VALUES (:id, :tf, :period, :alignment_source, :series, :roll, NULL, now())
        ON CONFLICT (id, tf, period, alignment_source, series, roll) DO NOTHING;
        """
    )
    payload = [
        {
            "id": k[0],
            "tf": k[1],
            "period": k[2],
            "alignment_source": k[3],
            "series": k[4],
            "roll": k[5],
        }
        for k in keys
    ]
    with engine.begin() as cxn:
        cxn.execute(sql, payload)


def _run_one_key(
    engine: Engine,
    ema_u_table: str,
    out_table: str,
    state_table: str,
    start: str,
    key: Key,
) -> None:
    one_id, one_tf, one_period, one_align, one_series, one_roll = key

    # For ema vs ema_bar, select the correct EMA column and correct roll column.
    # We already normalized key.roll to the right source roll, so we filter using:
    # - series='ema'     -> e.roll = :roll
    # - series='ema_bar' -> e.roll_bar = :roll
    ema_expr = "e.ema" if one_series == "ema" else "e.ema_bar"
    roll_filter = "e.roll = :roll" if one_series == "ema" else "e.roll_bar = :roll"

    sql = text(
        f"""
        WITH st AS (
            SELECT last_ts
            FROM {state_table}
            WHERE id = :id
              AND tf = :tf
              AND period = :period
              AND alignment_source = :alignment_source
              AND series = :series
              AND roll = :roll
        ),
        src AS (
            SELECT
                e.id::bigint AS id,
                e.ts,
                e.tf,
                e.period,
                e.alignment_source,
                {ema_expr} AS ema
            FROM {ema_u_table} e
            CROSS JOIN st
            WHERE e.id = :id
              AND e.tf = :tf
              AND e.period = :period
              AND e.alignment_source = :alignment_source
              AND {roll_filter}
              AND e.ts >= COALESCE(st.last_ts, CAST(:start AS timestamptz))
              AND {ema_expr} IS NOT NULL
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
                alignment_source,
                :series AS series,
                :roll AS roll,
                ema,
                prev_ema,
                (ts::date - prev_ts::date)::int AS gap_days,
                (ema / prev_ema) - 1 AS ret_arith,
                LN(ema / prev_ema) AS ret_log
            FROM lagged
            WHERE prev_ema IS NOT NULL
              AND prev_ema <> 0
              AND ema > 0
              AND prev_ema > 0
              AND prev_ts IS NOT NULL
        ),
        to_insert AS (
            SELECT c.*
            FROM calc c
            CROSS JOIN st
            WHERE (st.last_ts IS NULL) OR (c.ts > st.last_ts)
        ),
        ins AS (
            INSERT INTO {out_table} (
                id, ts, tf, period, alignment_source, series, roll,
                ema, prev_ema, gap_days, ret_arith, ret_log,
                ingested_at
            )
            SELECT
                id, ts, tf, period, alignment_source, series, roll,
                ema, prev_ema, gap_days, ret_arith, ret_log,
                now()
            FROM to_insert
            ON CONFLICT (id, ts, tf, period, alignment_source, series, roll) DO NOTHING
            RETURNING ts
        )
        UPDATE {state_table} s
        SET
            last_ts = COALESCE((SELECT MAX(ts) FROM ins), s.last_ts),
            updated_at = now()
        WHERE s.id = :id
          AND s.tf = :tf
          AND s.period = :period
          AND s.alignment_source = :alignment_source
          AND s.series = :series
          AND s.roll = :roll;
        """
    )

    with engine.begin() as cxn:
        cxn.execute(
            sql,
            {
                "id": one_id,
                "tf": one_tf,
                "period": one_period,
                "alignment_source": one_align,
                "series": one_series,
                "roll": one_roll,
                "start": start,
            },
        )


@dataclass(frozen=True)
class RunnerConfig:
    ema_u_table: str
    out_table: str
    state_table: str
    start: str
    full_refresh: bool
    ids_arg: str
    series: str
    roll_mode: str


def main() -> None:
    p = argparse.ArgumentParser(description="Build incremental EMA returns from cmc_ema_multi_tf_u.")
    p.add_argument("--db-url", default=os.getenv("TARGET_DB_URL", ""), help="DB URL (or set TARGET_DB_URL).")
    p.add_argument("--ema-u-table", default=DEFAULT_EMA_U_TABLE)
    p.add_argument("--out-table", default=DEFAULT_OUT_TABLE)
    p.add_argument("--state-table", default=DEFAULT_STATE_TABLE)
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--ids", default="all", help="Comma-separated ids or 'all'.")
    p.add_argument("--series", default="both", help="ema | ema_bar | both")
    p.add_argument("--roll-mode", default="both", help="true | false | both")
    args = p.parse_args()

    db_url = (args.db_url or "").strip()
    if not db_url:
        raise SystemExit("ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL.")

    cfg = RunnerConfig(
        ema_u_table=args.ema_u_table,
        out_table=args.out_table,
        state_table=args.state_table,
        start=args.start,
        full_refresh=bool(args.full_refresh),
        ids_arg=args.ids,
        series=args.series,
        roll_mode=args.roll_mode,
    )

    _print("Using DB URL from TARGET_DB_URL env." if args.db_url == os.getenv("TARGET_DB_URL", "") else "Using --db-url.")
    _print(
        f"Runner config: ids={cfg.ids_arg}, series={cfg.series}, roll_mode={cfg.roll_mode}, "
        f"start={cfg.start}, full_refresh={cfg.full_refresh}"
    )
    _print(f"ema_u={cfg.ema_u_table}")
    _print(f"out={cfg.out_table}")
    _print(f"state={cfg.state_table}")

    engine = _get_engine(db_url)

    ids = _parse_ids_arg(cfg.ids_arg)
    series_list = _expand_series(cfg.series)
    rolls = _expand_roll_mode(cfg.roll_mode)

    keys = _load_keys(engine, cfg.ema_u_table, ids, series_list, rolls)
    _print(f"Resolved keys from EMA_U: {len(keys)}")
    if not keys:
        _print("No keys found. Exiting.")
        return

    _ensure_state_rows(engine, cfg.state_table, keys)

    if cfg.full_refresh:
        # simple full refresh: clear only selected keys (safe) and reset state last_ts
        _print("Full refresh requested: deleting existing rows for selected keys and resetting state.")
        with engine.begin() as cxn:
            for k in keys:
                one_id, one_tf, one_period, one_align, one_series, one_roll = k
                cxn.execute(
                    text(
                        f"""
                        DELETE FROM {cfg.out_table}
                        WHERE id=:id AND tf=:tf AND period=:period
                          AND alignment_source=:alignment_source
                          AND series=:series AND roll=:roll;
                        """
                    ),
                    {
                        "id": one_id,
                        "tf": one_tf,
                        "period": one_period,
                        "alignment_source": one_align,
                        "series": one_series,
                        "roll": one_roll,
                    },
                )
                cxn.execute(
                    text(
                        f"""
                        UPDATE {cfg.state_table}
                        SET last_ts=NULL, updated_at=now()
                        WHERE id=:id AND tf=:tf AND period=:period
                          AND alignment_source=:alignment_source
                          AND series=:series AND roll=:roll;
                        """
                    ),
                    {
                        "id": one_id,
                        "tf": one_tf,
                        "period": one_period,
                        "alignment_source": one_align,
                        "series": one_series,
                        "roll": one_roll,
                    },
                )

    for i, k in enumerate(keys, start=1):
        one_id, one_tf, one_period, one_align, one_series, one_roll = k
        if i <= 3 or (i % 500 == 0) or (i == len(keys)):
            _print(f"Processing key=({one_id},{one_tf},{one_period},{one_align},{one_series},roll={one_roll}) ({i}/{len(keys)})")
        _run_one_key(engine, cfg.ema_u_table, cfg.out_table, cfg.state_table, cfg.start, k)

    _print("Done.")


if __name__ == "__main__":
    main()
