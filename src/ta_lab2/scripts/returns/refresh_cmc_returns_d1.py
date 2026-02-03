from __future__ import annotations

r"""
refresh_cmc_returns_d1.py

Incremental daily returns builder from public.cmc_price_histories7.

Writes:
  public.cmc_returns_d1

State:
  public.cmc_returns_d1_state  (watermark per id: last_time_close)

Semantics:
  - Returns are computed on observed-to-observed daily closes from cmc_price_histories7
  - Computes both arithmetic and log returns
  - Adds gap_days between observations
  - Incremental by default:
      for each id, only inserts rows where time_close > last_time_close
      but pulls time_close >= last_time_close to seed prev_close for the first new row
  - History recomputed only with --full-refresh

IMPORTANT: Your cmc_price_histories7 uses:
  - id
  - timeclose  (timestamptz, populated in practice)
  - close
"""

import argparse
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_OUT_TABLE = "public.cmc_returns_d1"
DEFAULT_STATE_TABLE = "public.cmc_returns_d1_state"

# Source timestamp column (matches your schema)
SRC_TIME_COL = "timeclose"


@dataclass(frozen=True)
class RunnerConfig:
    db_url: str
    ids: Optional[List[int]]  # None means ALL
    start: str
    daily_table: str
    out_table: str
    state_table: str
    full_refresh: bool


def _print(msg: str) -> None:
    print(f"[returns_d1] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def _load_all_ids(engine: Engine, daily_table: str) -> List[int]:
    sql = text(f"SELECT DISTINCT id FROM {daily_table} ORDER BY id;")
    with engine.begin() as cxn:
        rows = cxn.execute(sql).fetchall()
    return [int(r[0]) for r in rows]


def _ensure_state_rows(engine: Engine, state_table: str, ids: Iterable[int]) -> None:
    """
    Ensure every id has a row in the state table, without overwriting last_time_close.

    Uses UNNEST(:ids) to avoid SQLAlchemy/psycopg2 VALUES parameterization issues.
    """
    ids = [int(i) for i in ids]
    if not ids:
        return

    sql = text(
        f"""
        INSERT INTO {state_table} (id, last_time_close)
        SELECT UNNEST(:ids)::int AS id, NULL::timestamptz
        ON CONFLICT (id) DO NOTHING;
        """
    )

    with engine.begin() as cxn:
        cxn.execute(sql, {"ids": ids})


def _full_refresh(
    engine: Engine, out_table: str, state_table: str, ids: Iterable[int]
) -> None:
    ids = list(ids)
    if not ids:
        return

    _print(
        f"--full-refresh: deleting existing rows for {len(ids)} ids in {out_table} and resetting state."
    )
    with engine.begin() as cxn:
        cxn.execute(
            text(f"DELETE FROM {out_table} WHERE id = ANY(:ids);"), {"ids": ids}
        )
        cxn.execute(
            text(f"DELETE FROM {state_table} WHERE id = ANY(:ids);"), {"ids": ids}
        )
        cxn.execute(
            text(
                f"""
                INSERT INTO {state_table} (id, last_time_close)
                SELECT UNNEST(:ids)::int, NULL::timestamptz
                ON CONFLICT (id) DO UPDATE
                SET last_time_close = NULL, updated_at = now();
                """
            ),
            {"ids": ids},
        )


def _run_one_id(engine: Engine, cfg: RunnerConfig, one_id: int) -> None:
    """
    Inserts new return rows for one id and advances the watermark.
    """

    sql = text(
        f"""
        WITH st AS (
            SELECT last_time_close
            FROM {cfg.state_table}
            WHERE id = :id
        ),
        src AS (
            SELECT
                p.id,
                p.{SRC_TIME_COL} AS time_close,
                p.close
            FROM {cfg.daily_table} p
            CROSS JOIN st
            WHERE p.id = :id
              AND p.{SRC_TIME_COL} >= COALESCE(st.last_time_close, :start)
        ),
        calc AS (
            SELECT
                id,
                time_close,
                close,
                LAG(close) OVER (PARTITION BY id ORDER BY time_close) AS prev_close,
                LAG(time_close) OVER (PARTITION BY id ORDER BY time_close) AS prev_time_close
            FROM src
        ),
        to_insert AS (
            SELECT
                c.id,
                c.time_close,
                c.close,
                c.prev_close,
                CASE
                    WHEN c.prev_time_close IS NULL THEN NULL
                    ELSE (c.time_close::date - c.prev_time_close::date)::int
                END AS gap_days,
                CASE
                    WHEN c.prev_close IS NULL OR c.close IS NULL OR c.prev_close = 0 THEN NULL
                    ELSE (c.close / c.prev_close) - 1
                END AS ret_arith,
                CASE
                    WHEN c.prev_close IS NULL OR c.close IS NULL OR c.prev_close <= 0 OR c.close <= 0 THEN NULL
                    ELSE LN(c.close / c.prev_close)
                END AS ret_log
            FROM calc c
            CROSS JOIN st
            WHERE
                ((st.last_time_close IS NULL) OR (c.time_close > st.last_time_close))
                AND c.prev_close IS NOT NULL
        ),
        ins AS (
            INSERT INTO {cfg.out_table} (
                id, time_close, close, prev_close, gap_days, ret_arith, ret_log, ingested_at
            )
            SELECT
                id, time_close, close, prev_close, gap_days, ret_arith, ret_log, now()
            FROM to_insert
            ON CONFLICT (id, time_close) DO NOTHING
            RETURNING time_close
        )
        UPDATE {cfg.state_table} s
        SET
            last_time_close = COALESCE((SELECT MAX(time_close) FROM ins), s.last_time_close),
            updated_at = now()
        WHERE s.id = :id;
        """
    )

    with engine.begin() as cxn:
        cxn.execute(sql, {"id": one_id, "start": cfg.start})


def main() -> None:
    p = argparse.ArgumentParser(
        description="Incremental daily returns builder (arith + log) from cmc_price_histories7."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="Postgres DB URL (or set TARGET_DB_URL).",
    )

    p.add_argument("--ids", default="all", help="Comma-separated ids, or 'all'.")
    p.add_argument(
        "--start",
        default="2010-01-01",
        help="Start date (timestamptz parseable) for full history runs.",
    )

    p.add_argument(
        "--daily-table", default=DEFAULT_DAILY_TABLE, help="Source daily table."
    )
    p.add_argument(
        "--out-table", default=DEFAULT_OUT_TABLE, help="Output returns table."
    )
    p.add_argument("--state-table", default=DEFAULT_STATE_TABLE, help="State table.")

    p.add_argument(
        "--full-refresh",
        action="store_true",
        help="Recompute history for selected ids from --start.",
    )
    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    cfg = RunnerConfig(
        db_url=db_url,
        ids=None,
        start=args.start,
        daily_table=args.daily_table,
        out_table=args.out_table,
        state_table=args.state_table,
        full_refresh=bool(args.full_refresh),
    )

    _print(
        "Using DB URL from TARGET_DB_URL env."
        if os.getenv("TARGET_DB_URL")
        else "Using DB URL from --db-url."
    )
    _print(
        f"Runner config: ids={args.ids}, start={cfg.start}, daily={cfg.daily_table}, out={cfg.out_table}, state={cfg.state_table}, full_refresh={cfg.full_refresh}"
    )

    engine = _get_engine(cfg.db_url)

    if args.ids.strip().lower() == "all":
        ids = _load_all_ids(engine, cfg.daily_table)
        _print(f"Loaded ALL ids from {cfg.daily_table}: {len(ids)}")
    else:
        ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        _print(f"Loaded ids from args: {ids}")

    if not ids:
        _print("No ids to process. Exiting.")
        return

    _ensure_state_rows(engine, cfg.state_table, ids)

    if cfg.full_refresh:
        _full_refresh(engine, cfg.out_table, cfg.state_table, ids)

    for i, one_id in enumerate(ids, start=1):
        _print(f"Processing id={one_id} ({i}/{len(ids)})")
        _run_one_id(engine, cfg, one_id)

    _print("Done.")


if __name__ == "__main__":
    main()
