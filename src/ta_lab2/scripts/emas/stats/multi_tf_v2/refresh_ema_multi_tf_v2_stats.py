from __future__ import annotations

"""
Stats/ref-checks for cmc_ema_multi_tf_v2.

This mirrors ema_multi_tf_stats.py, but targets the pure-daily
EMA system in cmc_ema_multi_tf_v2.

We write into ema_multi_tf_v2_stats with rows like:

- test_name='daily_row_span'
    * For each (id, tf, period), we compute:
        - ts_min, ts_max
        - n_rows
        - span_days = (ts_max - ts_min) + 1
      and check whether n_rows ~= span_days.

- test_name='roll_false_spacing'
    * For each (id, tf, period), we look ONLY at rows with roll = FALSE
      and compute:
        - avg_gap_days between successive roll=FALSE dates
        - compare vs tf_days
"""

import argparse
import os
from typing import Iterable, Sequence

import sqlalchemy as sa

SOURCE_TABLE_NAME = "cmc_ema_multi_tf_v2"
STATS_TABLE_NAME = "ema_multi_tf_v2_stats"


# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------

def _resolve_db_url(cli_db_url: str | None) -> str:
    """
    Resolve DB URL from CLI arg or environment, mirroring other scripts.
    """
    env_url = os.getenv("TARGET_DB_URL")
    if cli_db_url:
        db_url = cli_db_url
        print(
            f"[{STATS_TABLE_NAME}] Using DB URL (resolved): {db_url}"
        )
    elif env_url:
        db_url = env_url
        print(
            f"[{STATS_TABLE_NAME}] Using DB URL from TARGET_DB_URL env: {db_url}"
        )
    else:
        raise RuntimeError(
            f"[{STATS_TABLE_NAME}] No DB URL provided and TARGET_DB_URL not set."
        )
    return db_url


def _get_engine(cli_db_url: str | None) -> sa.Engine:
    db_url = _resolve_db_url(cli_db_url)
    return sa.create_engine(db_url)


# ---------------------------------------------------------------------------
# ID loading / normalization
# ---------------------------------------------------------------------------

def _load_all_ids(engine: sa.Engine) -> list[int]:
    """
    Load all distinct asset ids from cmc_ema_multi_tf_v2.
    """
    sql = sa.text(
        f"""
        SELECT DISTINCT id
        FROM {SOURCE_TABLE_NAME}
        ORDER BY id
        """
    )
    with engine.begin() as conn:
        rows = conn.execute(sql).fetchall()
    return [int(r[0]) for r in rows]


def _normalize_ids_arg(engine: sa.Engine, ids_arg: Sequence[str]) -> list[int]:
    """
    Handle:
      --ids all
      --ids 1 2 3
      --ids 1,2,3
    """
    if len(ids_arg) == 1 and ids_arg[0].strip().lower() == "all":
        ids = _load_all_ids(engine)
        print(
            f"[{STATS_TABLE_NAME}] Loaded ALL ids from {SOURCE_TABLE_NAME}: {len(ids)}"
        )
        return ids

    raw_pieces: list[str] = []
    for token in ids_arg:
        raw_pieces.extend(token.split(","))

    ids: list[int] = []
    for piece in raw_pieces:
        piece = piece.strip()
        if not piece:
            continue
        ids.append(int(piece))

    ids = sorted(set(ids))
    print(f"[{STATS_TABLE_NAME}] Using explicit ids: {ids}")
    return ids


# ---------------------------------------------------------------------------
# Core stats helpers
# ---------------------------------------------------------------------------

def _delete_existing_for_ids(conn: sa.Connection, ids: Iterable[int]) -> None:
    ids_list = list(ids)
    if not ids_list:
        return

    sql = sa.text(
        f"""
        DELETE FROM {STATS_TABLE_NAME}
        WHERE table_name = :table_name
          AND asset_id = ANY(:ids)
        """
    )
    conn.execute(sql, {"table_name": SOURCE_TABLE_NAME, "ids": ids_list})


def _insert_daily_row_span(conn: sa.Connection, ids: Sequence[int]) -> None:
    """
    For each (id, tf, period):

        ts_min, ts_max, n_rows
        span_days = (ts_max - ts_min) + 1

    Check whether n_rows ~= span_days, since v2 is supposed to be
    a *daily* EMA series with no gaps in the middle (barring
    genuine missing price data).
    """
    ids_list = list(ids)
    if not ids_list:
        return

    sql = sa.text(
        f"""
        INSERT INTO {STATS_TABLE_NAME} (
            table_name,
            test_name,
            asset_id,
            tf,
            period,
            status,
            actual,
            expected,
            extra
        )
        WITH per_combo AS (
            SELECT
                id,
                tf,
                period,
                MIN(ts::date) AS ts_min,
                MAX(ts::date) AS ts_max,
                COUNT(*)      AS n_rows
            FROM {SOURCE_TABLE_NAME}
            WHERE id = ANY(:ids)
            GROUP BY id, tf, period
        ),
        span_calc AS (
            SELECT
                id,
                tf,
                period,
                ts_min,
                ts_max,
                n_rows,
                CASE
                    WHEN ts_min IS NOT NULL AND ts_max IS NOT NULL
                    THEN (ts_max - ts_min) + 1
                    ELSE NULL
                END AS span_days
            FROM per_combo
        )
        SELECT
            :table_name                      AS table_name,
            'daily_row_span'                 AS test_name,
            s.id                             AS asset_id,
            s.tf                             AS tf,
            s.period                         AS period,
            CASE
                WHEN span_days IS NULL THEN 'warn'
                WHEN abs(COALESCE(span_days, 0) - n_rows) <= 2
                    THEN 'ok'
                ELSE 'warn'
            END                              AS status,
            s.n_rows::DOUBLE PRECISION       AS actual,
            s.span_days::DOUBLE PRECISION    AS expected,
            jsonb_build_object(
                'ts_min', s.ts_min,
                'ts_max', s.ts_max,
                'n_rows', s.n_rows,
                'span_days', s.span_days,
                'missing_days_est',
                    CASE
                        WHEN span_days IS NULL THEN NULL
                        ELSE span_days - n_rows
                    END
            )                                AS extra
        FROM span_calc AS s
        ;
        """
    )

    conn.execute(sql, {"table_name": SOURCE_TABLE_NAME, "ids": ids_list})


def _insert_roll_false_spacing(conn: sa.Connection, ids: Sequence[int]) -> None:
    """
    For each (id, tf, period):

        Look only at roll = FALSE rows (canonical sampling points).
        Compute average spacing in *days* between successive canonical dates,
        and compare vs tf_days.
    """
    ids_list = list(ids)
    if not ids_list:
        return

    sql = sa.text(
        f"""
        INSERT INTO {STATS_TABLE_NAME} (
            table_name,
            test_name,
            asset_id,
            tf,
            period,
            status,
            actual,
            expected,
            extra
        )
        WITH canonical AS (
            SELECT
                id,
                tf,
                period,
                tf_days,
                ts::date AS ts_date,
                LAG(ts::date) OVER (
                    PARTITION BY id, tf, period
                    ORDER BY ts
                ) AS prev_ts
            FROM {SOURCE_TABLE_NAME}
            WHERE id = ANY(:ids)
              AND roll = FALSE
        ),
        gaps AS (
            SELECT
                id,
                tf,
                period,
                MIN(tf_days) AS tf_days,
                AVG(
                    (ts_date - prev_ts)::DOUBLE PRECISION
                ) AS avg_gap_days,
                COUNT(*) AS n_canonical
            FROM canonical
            WHERE prev_ts IS NOT NULL
            GROUP BY id, tf, period
        )
        SELECT
            :table_name                      AS table_name,
            'roll_false_spacing'             AS test_name,
            g.id                             AS asset_id,
            g.tf                             AS tf,
            g.period                         AS period,
            CASE
                WHEN g.avg_gap_days IS NULL THEN 'warn'
                WHEN abs(g.avg_gap_days - g.tf_days) <= 1
                    THEN 'ok'
                ELSE 'warn'
            END                              AS status,
            g.avg_gap_days                   AS actual,
            g.tf_days::DOUBLE PRECISION      AS expected,
            jsonb_build_object(
                'n_canonical', g.n_canonical,
                'avg_gap_days', g.avg_gap_days,
                'tf_days', g.tf_days
            )                                AS extra
        FROM gaps AS g
        ;
        """
    )

    conn.execute(sql, {"table_name": SOURCE_TABLE_NAME, "ids": ids_list})


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def refresh(ids: Sequence[int], db_url: str | None = None) -> None:
    """
    Compute and upsert stats for the given ids.
    """
    engine = _get_engine(db_url)
    ids_list = sorted(set(int(i) for i in ids))
    if not ids_list:
        print(f"[{STATS_TABLE_NAME}] No ids provided, nothing to do.")
        return

    print(f"[{STATS_TABLE_NAME}] Using DB URL (resolved): {engine.url}")
    print(f"[{STATS_TABLE_NAME}] Refreshing stats for ids={ids_list}")

    with engine.begin() as conn:
        print(
            f"[{STATS_TABLE_NAME}] Deleting existing stats rows for "
            f"{SOURCE_TABLE_NAME} and ids={ids_list}"
        )
        _delete_existing_for_ids(conn, ids_list)

        print(f"[{STATS_TABLE_NAME}] Inserting daily_row_span stats...")
        _insert_daily_row_span(conn, ids_list)

        print(f"[{STATS_TABLE_NAME}] Inserting roll_false_spacing stats...")
        _insert_roll_false_spacing(conn, ids_list)

    print(f"[{STATS_TABLE_NAME}] Refresh complete for ids={ids_list}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh ema_multi_tf_v2_stats for cmc_ema_multi_tf_v2 "
            "(pure-daily EMA system)."
        )
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="Asset ids to update (space- or comma-separated), or 'all'.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Optional SQLAlchemy DB URL. "
             "If omitted, uses TARGET_DB_URL environment variable.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    # Resolve ids
    engine = _get_engine(args.db_url)
    ids = _normalize_ids_arg(engine, args.ids)

    refresh(ids=ids, db_url=args.db_url)


if __name__ == "__main__":
    main()
"""
runfile(
    'C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/stats/multi_tf_v2/run_refresh_ema_multi_tf_v2_stats.py',
    wdir='C:/Users/asafi/Downloads/ta_lab2',
    args='--ids all'
)
"""