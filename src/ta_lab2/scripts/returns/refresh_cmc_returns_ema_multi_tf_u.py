from __future__ import annotations

r"""
refresh_cmc_returns_ema_multi_tf_u.py

Incremental EMA-returns builder from:
  public.cmc_ema_multi_tf_u

Writes:
  public.cmc_returns_ema_multi_tf_u

State:
  public.cmc_returns_ema_multi_tf_u_state
    watermark per (id, tf, period, alignment_source) -> last_ts

Semantics:
  - Processes BOTH roll=True and roll=False EMA rows for each
    (id, tf, period, alignment_source) in a single unified timeline ordered by ts.
  - Non-roll value columns (_ema, _ema_bar): populated only on roll=False rows,
    computed via LAG within the roll=False partition (canonical->canonical).
  - Roll value columns (_ema_roll, _ema_bar_roll): populated on ALL rows,
    computed via LAG over the unified timeline (daily transitions, including
    the cross-roll transition at bar close timestamps).
  - PK: (id, ts, tf, period, alignment_source); roll is a regular boolean column.
  - Incremental by default:
      inserts rows where ts > last_ts per key
      but pulls ts >= seed_ts to seed prev values for the first new row
  - History recomputed only with --full-refresh

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_ema_multi_tf_u.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--ids all"
)
"""

import argparse
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_EMA_U_TABLE = "public.cmc_ema_multi_tf_u"
DEFAULT_OUT_TABLE = "public.cmc_returns_ema_multi_tf_u"
DEFAULT_STATE_TABLE = "public.cmc_returns_ema_multi_tf_u_state"


Key = Tuple[int, str, int, str]  # (id, tf, period, alignment_source)


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


def _ensure_tables(engine: Engine, out_table: str, state_table: str) -> None:
    out_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {out_table} (
            id              bigint NOT NULL,
            ts              timestamptz NOT NULL,
            tf              text NOT NULL,
            tf_days         integer NOT NULL,
            period          integer NOT NULL,
            alignment_source text NOT NULL,
            roll            boolean NOT NULL,

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

            PRIMARY KEY (id, ts, tf, period, alignment_source)
        );
        """
    )

    state_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {state_table} (
            id              bigint NOT NULL,
            tf              text NOT NULL,
            period          integer NOT NULL,
            alignment_source text NOT NULL,
            last_ts         timestamptz,
            updated_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, tf, period, alignment_source)
        );
        """
    )

    with engine.begin() as cxn:
        cxn.execute(out_sql)
        cxn.execute(state_sql)


def _load_keys(
    engine: Engine,
    ema_u_table: str,
    ids: Sequence[int],
) -> List[Key]:
    """Returns distinct key surface from EMA_U: (id, tf, period, alignment_source)."""
    params: dict = {}
    where_ids = ""
    if ids:
        where_ids = "AND e.id = ANY(:ids)"
        params["ids"] = list(ids)

    sql = text(
        f"""
        SELECT DISTINCT
          e.id::int,
          e.tf::text,
          e.period::int,
          e.alignment_source::text
        FROM {ema_u_table} e
        WHERE TRUE
          {where_ids}
        ORDER BY 1,2,3,4;
        """
    )

    with engine.begin() as cxn:
        rows = cxn.execute(sql, params).fetchall()

    return [(int(r[0]), str(r[1]), int(r[2]), str(r[3])) for r in rows]


def _ensure_state_rows(engine: Engine, state_table: str, keys: List[Key]) -> None:
    if not keys:
        return
    sql = text(
        f"""
        INSERT INTO {state_table} (id, tf, period, alignment_source, last_ts, updated_at)
        VALUES (:id, :tf, :period, :alignment_source, NULL, now())
        ON CONFLICT (id, tf, period, alignment_source) DO NOTHING;
        """
    )
    payload = [
        {
            "id": k[0],
            "tf": k[1],
            "period": k[2],
            "alignment_source": k[3],
        }
        for k in keys
    ]
    with engine.begin() as cxn:
        cxn.execute(sql, payload)


# ---------------------------------------------------------------------------
# Column lists
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
    # z-scores: 30-day window (canonical)
    "ret_arith_ema_zscore_30",
    "ret_arith_ema_bar_zscore_30",
    "ret_log_ema_zscore_30",
    "ret_log_ema_bar_zscore_30",
    # z-scores: 30-day window (roll)
    "ret_arith_ema_roll_zscore_30",
    "ret_arith_ema_bar_roll_zscore_30",
    "ret_log_ema_roll_zscore_30",
    "ret_log_ema_bar_roll_zscore_30",
    # z-scores: 90-day window (canonical)
    "ret_arith_ema_zscore_90",
    "ret_arith_ema_bar_zscore_90",
    "ret_log_ema_zscore_90",
    "ret_log_ema_bar_zscore_90",
    # z-scores: 90-day window (roll)
    "ret_arith_ema_roll_zscore_90",
    "ret_arith_ema_bar_roll_zscore_90",
    "ret_log_ema_roll_zscore_90",
    "ret_log_ema_bar_roll_zscore_90",
    # z-scores: 365-day window (canonical)
    "ret_arith_ema_zscore_365",
    "ret_arith_ema_bar_zscore_365",
    "ret_log_ema_zscore_365",
    "ret_log_ema_bar_zscore_365",
    # z-scores: 365-day window (roll)
    "ret_arith_ema_roll_zscore_365",
    "ret_arith_ema_bar_roll_zscore_365",
    "ret_log_ema_roll_zscore_365",
    "ret_log_ema_bar_roll_zscore_365",
    # outlier flag
    "is_outlier",
]

_INSERT_COLS = (
    "id, ts, tf, tf_days, period, alignment_source, roll,\n"
    + ",\n".join(_VALUE_COLS)
    + ",\ningested_at"
)
_UPSERT_SET = ",\n".join(f"{c} = EXCLUDED.{c}" for c in _VALUE_COLS + ["ingested_at"])


def _run_one_key(
    engine: Engine,
    ema_u_table: str,
    out_table: str,
    state_table: str,
    start: str,
    key: Key,
) -> None:
    one_id, one_tf, one_period, one_align = key

    sql = text(
        f"""
        WITH st AS (
            SELECT last_ts
            FROM {state_table}
            WHERE id = :id
              AND tf = :tf
              AND period = :period
              AND alignment_source = :alignment_source
        ),
        seed AS (
            SELECT COALESCE(
                (SELECT MIN(sub.ts) FROM (
                    SELECT ts FROM {ema_u_table}
                    WHERE id = :id AND tf = :tf AND period = :period
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
        src AS (
            SELECT
                e.id::bigint AS id,
                e.ts,
                e.tf,
                e.tf_days,
                e.period,
                e.alignment_source,
                e.roll,
                e.ema,
                e.ema_bar
            FROM {ema_u_table} e, seed
            WHERE e.id = :id
              AND e.tf = :tf
              AND e.period = :period
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
                id, ts, tf, tf_days, period, alignment_source, roll,

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
            INSERT INTO {out_table} (
                {_INSERT_COLS}
            )
            SELECT
                {_INSERT_COLS.replace('ingested_at', 'now()')}
            FROM to_insert
            ON CONFLICT (id, ts, tf, period, alignment_source) DO UPDATE SET
                roll = EXCLUDED.roll,
                {_UPSERT_SET}
            RETURNING ts
        )
        UPDATE {state_table} s
        SET
            last_ts = COALESCE((SELECT MAX(ts) FROM ins), s.last_ts),
            updated_at = now()
        WHERE s.id = :id
          AND s.tf = :tf
          AND s.period = :period
          AND s.alignment_source = :alignment_source;
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


def main() -> None:
    p = argparse.ArgumentParser(
        description="Build incremental EMA returns from cmc_ema_multi_tf_u (unified timeline with _roll columns)."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--ema-u-table", default=DEFAULT_EMA_U_TABLE)
    p.add_argument("--out-table", default=DEFAULT_OUT_TABLE)
    p.add_argument("--state-table", default=DEFAULT_STATE_TABLE)
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--ids", default="all", help="Comma-separated ids or 'all'.")
    args = p.parse_args()

    db_url = (args.db_url or "").strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    cfg = RunnerConfig(
        ema_u_table=args.ema_u_table,
        out_table=args.out_table,
        state_table=args.state_table,
        start=args.start,
        full_refresh=bool(args.full_refresh),
        ids_arg=args.ids,
    )

    _print(
        "Using DB URL from TARGET_DB_URL env."
        if args.db_url == os.getenv("TARGET_DB_URL", "")
        else "Using --db-url."
    )
    _print(
        f"Runner config: ids={cfg.ids_arg}, "
        f"start={cfg.start}, full_refresh={cfg.full_refresh}"
    )
    _print(f"ema_u={cfg.ema_u_table}")
    _print(f"out={cfg.out_table}")
    _print(f"state={cfg.state_table}")

    engine = _get_engine(db_url)

    _ensure_tables(engine, cfg.out_table, cfg.state_table)

    ids = _parse_ids_arg(cfg.ids_arg)

    keys = _load_keys(engine, cfg.ema_u_table, ids)
    _print(f"Resolved keys from EMA_U: {len(keys)}")
    if not keys:
        _print("No keys found. Exiting.")
        return

    _ensure_state_rows(engine, cfg.state_table, keys)

    if cfg.full_refresh:
        _print(
            "Full refresh requested: deleting existing rows for selected keys and resetting state."
        )
        with engine.begin() as cxn:
            for k in keys:
                one_id, one_tf, one_period, one_align = k
                cxn.execute(
                    text(
                        f"""
                        DELETE FROM {cfg.out_table}
                        WHERE id=:id AND tf=:tf AND period=:period
                          AND alignment_source=:alignment_source;
                        """
                    ),
                    {
                        "id": one_id,
                        "tf": one_tf,
                        "period": one_period,
                        "alignment_source": one_align,
                    },
                )
                cxn.execute(
                    text(
                        f"""
                        UPDATE {cfg.state_table}
                        SET last_ts=NULL, updated_at=now()
                        WHERE id=:id AND tf=:tf AND period=:period
                          AND alignment_source=:alignment_source;
                        """
                    ),
                    {
                        "id": one_id,
                        "tf": one_tf,
                        "period": one_period,
                        "alignment_source": one_align,
                    },
                )

    for i, k in enumerate(keys, start=1):
        one_id, one_tf, one_period, one_align = k
        if i <= 3 or (i % 500 == 0) or (i == len(keys)):
            _print(
                f"Processing key=({one_id},{one_tf},{one_period},{one_align}) ({i}/{len(keys)})"
            )
        _run_one_key(
            engine, cfg.ema_u_table, cfg.out_table, cfg.state_table, cfg.start, k
        )

    _print("Done.")


if __name__ == "__main__":
    main()
