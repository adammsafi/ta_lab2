from __future__ import annotations

r"""
refresh_returns_ema_multi_tf_cal_anchor.py

Incremental returns builder for calendar-anchored EMA tables.

Source EMA table (both schemes):
  public.ema_multi_tf_u  (scoped by alignment_source)

Writes returns (both schemes write to same _u table, tagged by alignment_source):
  public.returns_ema_multi_tf_u  (alignment_source='multi_tf_cal_anchor_us' or 'multi_tf_cal_anchor_iso')

State tables (unchanged, remain per-variant):
  public.returns_ema_multi_tf_cal_anchor_us_state
  public.returns_ema_multi_tf_cal_anchor_iso_state

State key:
  (id, tf, period, venue_id) -> last_ts

Semantics:
  - Processes BOTH roll=True and roll=False EMA rows for each (id,tf,period)
    in a single unified timeline ordered by ts.
  - Non-roll value columns (_ema, _ema_bar): populated only on roll=False rows,
    computed via LAG within the roll=False partition (canonical->canonical).
  - Roll value columns (_ema_roll, _ema_bar_roll): populated on ALL rows,
    computed via LAG over the unified timeline (daily transitions, including
    the cross-roll transition at bar close timestamps).
  - PK: (id, venue_id, ts, tf, period); roll is a regular boolean column.
  - Incremental by default:
      inserts rows where ts > last_ts per key
      but pulls ts >= seed_ts to seed prev values for the first new row
  - History recomputed only with --full-refresh

Spyder run example:
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_returns_ema_multi_tf_cal_anchor.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--scheme both --ids all"
)
"""

import argparse
import os
from dataclasses import dataclass
from multiprocessing import Pool
from typing import List, Optional, Tuple

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool


# Source: both schemes read from the unified _u table (scoped by alignment_source)
DEFAULT_EMA_US = "public.ema_multi_tf_u"
DEFAULT_EMA_ISO = "public.ema_multi_tf_u"

# Output: both schemes write to the unified _u table (tagged by alignment_source)
DEFAULT_RET_US = "public.returns_ema_multi_tf_u"
DEFAULT_RET_ISO = "public.returns_ema_multi_tf_u"

# State (unchanged, remain per-variant)
DEFAULT_STATE_US = "public.returns_ema_multi_tf_cal_anchor_us_state"
DEFAULT_STATE_ISO = "public.returns_ema_multi_tf_cal_anchor_iso_state"

# Alignment sources per scheme
ALIGNMENT_SOURCE_US = "multi_tf_cal_anchor_us"
ALIGNMENT_SOURCE_ISO = "multi_tf_cal_anchor_iso"


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


def _tables_for_scheme(scheme: str) -> Tuple[str, str, str, str]:
    """Returns (ema_table, ret_table, state_table, alignment_source)."""
    s = scheme.lower()
    if s == "us":
        return (DEFAULT_EMA_US, DEFAULT_RET_US, DEFAULT_STATE_US, ALIGNMENT_SOURCE_US)
    if s == "iso":
        return (
            DEFAULT_EMA_ISO,
            DEFAULT_RET_ISO,
            DEFAULT_STATE_ISO,
            ALIGNMENT_SOURCE_ISO,
        )
    raise ValueError(f"unknown scheme={scheme}")


def _ensure_tables(engine: Engine, ret_table: str, state_table: str) -> None:
    out_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {ret_table} (
            id        bigint NOT NULL,
            venue_id  smallint NOT NULL DEFAULT 1,
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

            ret_arith_ema_zscore_30           double precision,
            ret_arith_ema_bar_zscore_30       double precision,
            ret_log_ema_zscore_30             double precision,
            ret_log_ema_bar_zscore_30         double precision,
            ret_arith_ema_roll_zscore_30      double precision,
            ret_arith_ema_bar_roll_zscore_30  double precision,
            ret_log_ema_roll_zscore_30        double precision,
            ret_log_ema_bar_roll_zscore_30    double precision,
            ret_arith_ema_zscore_90           double precision,
            ret_arith_ema_bar_zscore_90       double precision,
            ret_log_ema_zscore_90             double precision,
            ret_log_ema_bar_zscore_90         double precision,
            ret_arith_ema_roll_zscore_90      double precision,
            ret_arith_ema_bar_roll_zscore_90  double precision,
            ret_log_ema_roll_zscore_90        double precision,
            ret_log_ema_bar_roll_zscore_90    double precision,
            ret_arith_ema_zscore_365          double precision,
            ret_arith_ema_bar_zscore_365      double precision,
            ret_log_ema_zscore_365            double precision,
            ret_log_ema_bar_zscore_365        double precision,
            ret_arith_ema_roll_zscore_365     double precision,
            ret_arith_ema_bar_roll_zscore_365 double precision,
            ret_log_ema_roll_zscore_365       double precision,
            ret_log_ema_bar_roll_zscore_365   double precision,
            is_outlier                    boolean,

            ingested_at timestamptz NOT NULL DEFAULT now(),

            PRIMARY KEY (id, venue_id, ts, tf, period)
        );
        """
    )

    state_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {state_table} (
            id       bigint NOT NULL,
            venue_id smallint NOT NULL DEFAULT 1,
            tf       text NOT NULL,
            period   integer NOT NULL,
            last_ts  timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, venue_id, tf, period)
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
    alignment_source: str = ALIGNMENT_SOURCE_US,
) -> List[Tuple[int, str, int, int]]:
    """Returns keys as: (id, tf, period, venue_id).
    Scoped by alignment_source so that when reading from ema_multi_tf_u we
    only enumerate keys belonging to this builder's variant.
    """
    if ids is None:
        sql = text(
            f"""
            SELECT DISTINCT id::bigint, tf::text, period::int,
                   venue_id
            FROM {ema_table}
            WHERE alignment_source = :alignment_source
            ORDER BY 1,2,3,4;
            """
        )
        with engine.begin() as cxn:
            rows = cxn.execute(sql, {"alignment_source": alignment_source}).fetchall()
    else:
        sql = text(
            f"""
            SELECT DISTINCT id::bigint, tf::text, period::int,
                   venue_id
            FROM {ema_table}
            WHERE id IN :ids AND alignment_source = :alignment_source
            ORDER BY 1,2,3,4;
            """
        ).bindparams(bindparam("ids", expanding=True))
        with engine.begin() as cxn:
            rows = cxn.execute(
                sql, {"ids": ids, "alignment_source": alignment_source}
            ).fetchall()

    return [(int(r[0]), str(r[1]), int(r[2]), int(r[3])) for r in rows]


def _ensure_state_rows(
    engine: Engine, state_table: str, keys: List[Tuple[int, str, int, int]]
) -> None:
    if not keys:
        return

    ins = text(
        f"""
        INSERT INTO {state_table} (id, venue_id, tf, period, last_ts)
        VALUES (:id, :venue_id, :tf, :period, NULL)
        ON CONFLICT (id, venue_id, tf, period) DO NOTHING;
        """
    )

    with engine.begin() as cxn:
        for i, tf, period, venue_id in keys:
            cxn.execute(
                ins, {"id": i, "venue_id": venue_id, "tf": tf, "period": period}
            )


def _full_refresh(
    engine: Engine,
    ret_table: str,
    state_table: str,
    keys: List[Tuple[int, str, int, int]],
    alignment_source: str = ALIGNMENT_SOURCE_US,
) -> None:
    if not keys:
        return

    _print(
        f"--full-refresh: deleting existing rows for {len(keys)} keys and resetting state."
    )

    del_ret = text(
        f"""
        DELETE FROM {ret_table}
        WHERE id = :id AND tf = :tf AND period = :period AND venue_id = :venue_id
          AND alignment_source = :alignment_source;
        """
    )
    del_state = text(
        f"""
        DELETE FROM {state_table}
        WHERE id = :id AND tf = :tf AND period = :period AND venue_id = :venue_id;
        """
    )

    with engine.begin() as cxn:
        for i, tf, period, venue_id in keys:
            del_out_params = {
                "id": i,
                "tf": tf,
                "period": period,
                "venue_id": venue_id,
                "alignment_source": alignment_source,
            }
            del_state_params = {
                "id": i,
                "tf": tf,
                "period": period,
                "venue_id": venue_id,
            }
            cxn.execute(del_ret, del_out_params)
            cxn.execute(del_state, del_state_params)

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
    # NOTE: z-score columns and is_outlier are populated by refresh_returns_zscore.py
]

_INSERT_COLS = (
    "id, venue_id, ts, tf, tf_days, period, roll,\n"
    + ",\n".join(_VALUE_COLS)
    + ",\ningested_at, alignment_source"
)
_UPSERT_SET = ",\n".join(
    f"{c} = EXCLUDED.{c}" for c in ["roll"] + _VALUE_COLS + ["ingested_at"]
)


def _run_one_key(
    engine: Engine,
    ema_table: str,
    ret_table: str,
    state_table: str,
    start: str,
    key: Tuple[int, str, int, int],
    alignment_source: str = ALIGNMENT_SOURCE_US,
) -> None:
    one_id, one_tf, one_period, one_venue_id = key

    sql = text(
        f"""
        WITH st AS (
            SELECT last_ts
            FROM {state_table}
            WHERE id = :id AND tf = :tf AND period = :period AND venue_id = :venue_id
        ),
        seed AS (
            SELECT COALESCE(
                (SELECT MIN(sub.ts) FROM (
                    SELECT ts FROM {ema_table}
                    WHERE id = :id AND tf = :tf AND period = :period
                      AND venue_id = :venue_id
                      AND alignment_source = :alignment_source
                      AND roll = FALSE
                      AND ts < COALESCE((SELECT last_ts FROM st), CAST(:start AS timestamptz))
                    ORDER BY ts DESC
                    LIMIT 2
                ) sub),
                (SELECT last_ts FROM st),
                CAST(:start AS timestamptz)
            ) AS seed_ts
        ),
        -- CRITICAL: scope by alignment_source to avoid cross-source LAG contamination
        src AS (
            SELECT
                e.id::bigint AS id,
                e.venue_id,
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
              AND e.venue_id = :venue_id
              AND e.alignment_source = :alignment_source
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
                id, venue_id, ts, tf, tf_days, period, roll,

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
                {_INSERT_COLS.replace("ingested_at", "now()").replace("alignment_source", "CAST(:alignment_source AS text)")}
            FROM to_insert
            ON CONFLICT (id, venue_id, ts, tf, period, alignment_source) DO UPDATE SET
                {_UPSERT_SET}
            RETURNING ts
        )
        UPDATE {state_table} s
        SET
            last_ts = COALESCE((SELECT MAX(ts) FROM ins), s.last_ts),
            updated_at = now()
        WHERE s.id = :id AND s.tf = :tf AND s.period = :period AND s.venue_id = :venue_id;
        """
    )

    with engine.begin() as cxn:
        cxn.execute(
            sql,
            {
                "id": one_id,
                "tf": one_tf,
                "period": one_period,
                "venue_id": one_venue_id,
                "start": start,
                "alignment_source": alignment_source,
            },
        )


def _run_one_key_mp(args: tuple) -> Tuple[int, str, int, int, bool]:
    """Multiprocessing-safe wrapper. Creates own engine with NullPool."""
    db_url, ema_table, ret_table, state_table, start, key, alignment_source = args
    one_id, one_tf, one_period, one_venue_id = key
    try:
        engine = create_engine(db_url, poolclass=NullPool, future=True)
        _run_one_key(
            engine, ema_table, ret_table, state_table, start, key, alignment_source
        )
        engine.dispose()
        return (one_id, one_tf, one_period, one_venue_id, True)
    except Exception as exc:
        _print(f"FAILED key=({one_id},{one_tf},{one_period},v{one_venue_id}): {exc}")
        return (one_id, one_tf, one_period, one_venue_id, False)


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
    p.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers (default 1 = sequential).",
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
        ema_table, ret_table, state_table, alignment_source = _tables_for_scheme(scheme)

        _print(f"=== scheme={scheme.upper()} ===")
        _print(f"ema={ema_table} (alignment_source={alignment_source})")
        _print(f"ret={ret_table}")
        _print(f"state={state_table}")

        _ensure_tables(engine, ret_table, state_table)

        keys = _load_keys(engine, ema_table, ids, alignment_source=alignment_source)
        _print(f"Resolved keys={len(keys)}")
        if not keys:
            _print("No keys found. Skipping scheme.")
            continue

        _ensure_state_rows(engine, state_table, keys)

        if cfg.full_refresh:
            _full_refresh(
                engine, ret_table, state_table, keys, alignment_source=alignment_source
            )

        workers = args.workers
        if workers > 1:
            _print(f"Running {len(keys)} keys with {workers} workers.")
            mp_args = [
                (
                    cfg.db_url,
                    ema_table,
                    ret_table,
                    state_table,
                    cfg.start,
                    key,
                    alignment_source,
                )
                for key in keys
            ]
            done = 0
            failed = 0
            with Pool(processes=workers, maxtasksperchild=50) as pool:
                for one_id, one_tf, one_period, one_venue_id, ok in pool.imap_unordered(
                    _run_one_key_mp, mp_args
                ):
                    done += 1
                    if not ok:
                        failed += 1
                    if done % 200 == 0 or done == len(keys):
                        _print(f"  progress: {done}/{len(keys)} ({failed} failed)")
            _print(f"Scheme {scheme.upper()} done: {done} keys, {failed} failed.")
        else:
            for i, key in enumerate(keys, start=1):
                one_id, one_tf, one_period, one_venue_id = key
                _print(
                    f"Processing key=({one_id},{one_tf},{one_period},v{one_venue_id}) ({i}/{len(keys)})"
                )
                _run_one_key(
                    engine,
                    ema_table,
                    ret_table,
                    state_table,
                    cfg.start,
                    key,
                    alignment_source=alignment_source,
                )

    _print("Done.")


if __name__ == "__main__":
    main()
