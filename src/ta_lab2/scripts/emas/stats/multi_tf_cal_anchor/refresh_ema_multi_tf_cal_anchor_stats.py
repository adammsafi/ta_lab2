from __future__ import annotations

"""
Stats / sanity checks for cmc_ema_multi_tf_cal_anchor.

This is parallel to the ema_multi_tf_v2_stats style but for the
calendar-anchored multi-timeframe EMA table:

- Writes into ema_multi_tf_cal_anchor_stats
- Computes a suite of structural checks:

    * daily_row_span
        - min/max ts per (id, tf, period)
        - n_rows vs span_days (max_ts - min_ts + 1)
    * roll_false_spacing
        - average calendar gap (in days) between roll = FALSE rows
          vs tf_days (expected cadence)
    * roll_false_count_vs_span
        - consistency between number of canonical (roll = FALSE) rows
          and total span_days / tf_days
    * non_null_ema
        - count of NULL ema values per (id, tf, period)
    * non_decreasing_ts
        - detects time ordering violations within each (id, tf, period)
    * roll_boolean
        - sanity check on the roll column (true/false/null counts)

Run via:

    python -m ta_lab2.scripts.emas.stats.multi_tf_cal_anchor.refresh_ema_multi_tf_cal_anchor_stats --ids all

or from Spyder:

    runfile(
        '.../src/ta_lab2/scripts/emas/stats/multi_tf_cal_anchor/run_refresh_ema_multi_tf_cal_anchor_stats.py',
        wdir='.../ta_lab2',
        args='--ids all'
    )

This script is *id-scoped* and *append-only*:
- You pass a list of asset ids (or --ids all).
- It does NOT delete existing stats rows, so you can keep historical
  runs over time (distinguished by ingested_at).
"""

import os
from typing import Optional, Sequence, Iterable

import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATS_TABLE_NAME = "ema_multi_tf_cal_anchor_stats"
SOURCE_TABLE_NAME = "cmc_ema_multi_tf_cal_anchor"

DDL_STATS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {STATS_TABLE_NAME} (
    id          BIGSERIAL PRIMARY KEY,
    table_name  TEXT        NOT NULL,
    test_name   TEXT        NOT NULL,
    asset_id    BIGINT      NOT NULL,
    tf          TEXT        NOT NULL,
    period      INTEGER     NOT NULL,
    status      TEXT        NOT NULL,
    actual      DOUBLE PRECISION,
    expected    DOUBLE PRECISION,
    extra       JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ema_multi_tf_cal_anchor_stats_pk
    ON {STATS_TABLE_NAME} (
        table_name,
        test_name,
        asset_id,
        tf,
        period,
        ingested_at
    );
"""

# ---------------------------------------------------------------------------
# Engine helper (no dependency on ta_lab2.db)
# ---------------------------------------------------------------------------


def _mask_url(url: str) -> str:
    """Light masking for printing DB URLs."""
    if "@" not in url or "://" not in url:
        return url
    prefix, rest = url.split("://", 1)
    if "@" not in rest:
        return f"{prefix}://***"
    creds, host = rest.split("@", 1)
    return f"{prefix}://***@{host}"


def _get_engine(db_url: Optional[str] = None) -> sa.Engine:
    """
    Resolve DB URL and return a SQLAlchemy engine.

    Priority:
        1. Explicit db_url argument
        2. TARGET_DB_URL environment variable

    We avoid importing ta_lab2.db here so this script is self-contained.
    """
    effective = db_url or os.environ.get("TARGET_DB_URL")
    if not effective:
        raise RuntimeError(
            f"[{STATS_TABLE_NAME}] No DB URL provided and TARGET_DB_URL not set."
        )
    print(
        f"[{STATS_TABLE_NAME}] Using DB URL (resolved): {_mask_url(effective)}"
    )
    return sa.create_engine(effective, future=True)


# ---------------------------------------------------------------------------
# DDL / housekeeping
# ---------------------------------------------------------------------------


def _ensure_stats_table(engine: sa.Engine) -> None:
    """Create the stats table/index if they don't exist yet."""
    with engine.begin() as conn:
        conn.execute(sa.text(DDL_STATS_TABLE))


# ---------------------------------------------------------------------------
# Stats insert helpers
# ---------------------------------------------------------------------------


def _insert_daily_row_span(conn: sa.Connection, ids: Sequence[int]) -> None:
    """
    For each (id, tf, period) in the source table, compute:

        - min_ts, max_ts (DATE)
        - n_rows
        - span_days = (max_ts - min_ts) + 1

    And write a single row into the stats table with test_name='daily_row_span'.

    status:
        - 'ok'   if n_rows == span_days
        - 'warn' otherwise
    """
    if not ids:
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
        WITH per_group AS (
            SELECT
                id              AS asset_id,
                tf,
                period,
                MIN(ts::date)   AS min_ts,
                MAX(ts::date)   AS max_ts,
                COUNT(*)        AS n_rows
            FROM {SOURCE_TABLE_NAME}
            WHERE id = ANY(:ids)
            GROUP BY id, tf, period
        ),
        summary AS (
            SELECT
                asset_id,
                tf,
                period,
                min_ts,
                max_ts,
                (max_ts - min_ts + 1) AS span_days,
                n_rows
            FROM per_group
        )
        SELECT
            :table_name                     AS table_name,
            'daily_row_span'                AS test_name,
            s.asset_id                      AS asset_id,
            s.tf                            AS tf,
            s.period                        AS period,
            CASE
                WHEN s.n_rows = s.span_days
                    THEN 'ok'
                ELSE 'warn'
            END                             AS status,
            s.n_rows::DOUBLE PRECISION      AS actual,
            s.span_days::DOUBLE PRECISION   AS expected,
            jsonb_build_object(
                'min_ts',    s.min_ts,
                'max_ts',    s.max_ts,
                'span_days', s.span_days,
                'n_rows',    s.n_rows
            )                               AS extra
        FROM summary AS s
        ;
        """
    )
    conn.execute(
        sql,
        {"ids": list(ids), "table_name": SOURCE_TABLE_NAME},
    )


def _insert_roll_false_spacing(conn: sa.Connection, ids: Sequence[int]) -> None:
    """
    Check that roll = FALSE rows are spaced roughly tf_days apart
    in calendar days.

    For each (id, tf, period):
        - Look only at rows where roll = FALSE.
        - Compute ts_date and previous ts_date.
        - Compute avg_gap_days = AVG(ts_date - prev_ts) in days.
        - Compare avg_gap_days to tf_days.

    Status:
        - 'ok'   if |avg_gap_days - tf_days| <= 1
        - 'warn' otherwise
    """
    if not ids:
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
                MIN(tf_days)                                         AS tf_days,
                AVG(
                    (ts_date - prev_ts)::DOUBLE PRECISION
                )                                                    AS avg_gap_days,
                COUNT(*)                                             AS n_canonical
            FROM canonical
            WHERE prev_ts IS NOT NULL
            GROUP BY id, tf, period
        )
        SELECT
            :table_name                     AS table_name,
            'roll_false_spacing'            AS test_name,
            g.id                            AS asset_id,
            g.tf                            AS tf,
            g.period                        AS period,
            CASE
                WHEN abs(g.avg_gap_days - g.tf_days) <= 1
                    THEN 'ok'
                ELSE 'warn'
            END                             AS status,
            g.avg_gap_days                  AS actual,
            g.tf_days::DOUBLE PRECISION     AS expected,
            jsonb_build_object(
                'n_canonical', g.n_canonical,
                'avg_gap_days', g.avg_gap_days,
                'tf_days',      g.tf_days
            )                               AS extra
        FROM gaps AS g
        ;
        """
    )
    conn.execute(
        sql,
        {"ids": list(ids), "table_name": SOURCE_TABLE_NAME},
    )


def _insert_roll_false_count_vs_span(conn: sa.Connection, ids: Sequence[int]) -> None:
    """
    Check consistency between:
        - number of canonical rows (roll = FALSE)
        - total calendar span_days / tf_days

    For each (id, tf, period):
        - On roll = FALSE rows, find ts_min, ts_max, tf_days, n_rows.
        - Compute n_days  = (ts_max - ts_min + 1).
        - Compute expected_canonical = n_days / tf_days.
        - status:
            * 'ok'   if |n_rows - expected_canonical| <= 1
            * 'warn' otherwise
    """
    if not ids:
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
        WITH base AS (
            SELECT
                id,
                tf,
                period,
                MIN(ts::date)               AS ts_min,
                MAX(ts::date)               AS ts_max,
                MIN(tf_days)                AS tf_days,
                COUNT(*)                    AS n_rows
            FROM {SOURCE_TABLE_NAME}
            WHERE id = ANY(:ids)
              AND roll = FALSE
            GROUP BY id, tf, period
        ),
        span AS (
            SELECT
                id,
                tf,
                period,
                ts_min,
                ts_max,
                tf_days,
                n_rows,
                (ts_max - ts_min + 1)       AS n_days
            FROM base
        )
        SELECT
            :table_name                     AS table_name,
            'roll_false_count_vs_span'      AS test_name,
            s.id                            AS asset_id,
            s.tf                            AS tf,
            s.period                        AS period,
            CASE
                WHEN abs(
                    s.n_rows - (s.n_days::DOUBLE PRECISION / s.tf_days::DOUBLE PRECISION)
                ) <= 1.0
                    THEN 'ok'
                ELSE 'warn'
            END                             AS status,
            s.n_rows::DOUBLE PRECISION      AS actual,
            (s.n_days::DOUBLE PRECISION /
             s.tf_days::DOUBLE PRECISION)   AS expected,
            jsonb_build_object(
                'ts_min',  s.ts_min,
                'ts_max',  s.ts_max,
                'n_rows',  s.n_rows,
                'n_days',  s.n_days,
                'tf_days', s.tf_days
            )                               AS extra
        FROM span AS s
        ;
        """
    )
    conn.execute(
        sql,
        {"ids": list(ids), "table_name": SOURCE_TABLE_NAME},
    )


def _insert_non_null_ema(conn: sa.Connection, ids: Sequence[int]) -> None:
    """
    Check that ema is non-null for each (id, tf, period).

    Status per group:
        - 'ok'   if n_null = 0
        - 'warn' otherwise
    """
    if not ids:
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
        SELECT
            :table_name                                             AS table_name,
            'non_null_ema'                                         AS test_name,
            id                                                      AS asset_id,
            tf                                                      AS tf,
            period                                                  AS period,
            CASE
                WHEN SUM(CASE WHEN ema IS NULL THEN 1 ELSE 0 END) = 0
                    THEN 'ok'
                ELSE 'warn'
            END                                                     AS status,
            SUM(CASE WHEN ema IS NULL THEN 1 ELSE 0 END)
                ::DOUBLE PRECISION                                  AS actual,
            0.0                                                     AS expected,
            jsonb_build_object(
                'n_null', SUM(CASE WHEN ema IS NULL THEN 1 ELSE 0 END),
                'n_rows', COUNT(*)
            )                                                       AS extra
        FROM {SOURCE_TABLE_NAME}
        WHERE id = ANY(:ids)
        GROUP BY id, tf, period
        ;
        """
    )
    conn.execute(
        sql,
        {"ids": list(ids), "table_name": SOURCE_TABLE_NAME},
    )


def _insert_non_decreasing_ts(conn: sa.Connection, ids: Sequence[int]) -> None:
    """
    Check that ts is non-decreasing within each (id, tf, period).

    We count the number of times ts < prev_ts per group.

    Status:
        - 'ok'   if n_violations = 0
        - 'warn' otherwise
    """
    if not ids:
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
        WITH ordered AS (
            SELECT
                id,
                tf,
                period,
                ts,
                LAG(ts) OVER (
                    PARTITION BY id, tf, period
                    ORDER BY ts
                ) AS prev_ts
            FROM {SOURCE_TABLE_NAME}
            WHERE id = ANY(:ids)
        ),
        violations AS (
            SELECT
                id,
                tf,
                period,
                COUNT(*) AS n_violations
            FROM ordered
            WHERE prev_ts IS NOT NULL
              AND ts < prev_ts
            GROUP BY id, tf, period
        ),
        groups AS (
            SELECT DISTINCT id, tf, period
            FROM {SOURCE_TABLE_NAME}
            WHERE id = ANY(:ids)
        )
        SELECT
            :table_name                           AS table_name,
            'non_decreasing_ts'                   AS test_name,
            g.id                                  AS asset_id,
            g.tf                                  AS tf,
            g.period                              AS period,
            CASE
                WHEN COALESCE(v.n_violations, 0) = 0
                    THEN 'ok'
                ELSE 'warn'
            END                                   AS status,
            COALESCE(v.n_violations, 0)::DOUBLE PRECISION
                                                  AS actual,
            0.0                                   AS expected,
            jsonb_build_object(
                'n_violations', COALESCE(v.n_violations, 0)
            )                                     AS extra
        FROM groups AS g
        LEFT JOIN violations AS v
          ON v.id     = g.id
         AND v.tf     = g.tf
         AND v.period = g.period
        ;
        """
    )
    conn.execute(
        sql,
        {"ids": list(ids), "table_name": SOURCE_TABLE_NAME},
    )


def _insert_roll_boolean(conn: sa.Connection, ids: Sequence[int]) -> None:
    """
    Sanity check for the roll column: counts true/false/null per group.

    Status:
        - 'ok'   if n_null = 0 and n_true + n_false = n_rows
        - 'warn' otherwise
    """
    if not ids:
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
        WITH base AS (
            SELECT
                id,
                tf,
                period,
                COUNT(*) AS n_rows,
                SUM(CASE WHEN roll IS TRUE  THEN 1 ELSE 0 END) AS n_true,
                SUM(CASE WHEN roll IS FALSE THEN 1 ELSE 0 END) AS n_false,
                SUM(CASE WHEN roll IS NULL THEN 1 ELSE 0 END)  AS n_null
            FROM {SOURCE_TABLE_NAME}
            WHERE id = ANY(:ids)
            GROUP BY id, tf, period
        )
        SELECT
            :table_name                     AS table_name,
            'roll_boolean'                  AS test_name,
            b.id                            AS asset_id,
            b.tf                            AS tf,
            b.period                        AS period,
            CASE
                WHEN b.n_null = 0
                 AND (b.n_true + b.n_false) = b.n_rows
                    THEN 'ok'
                ELSE 'warn'
            END                             AS status,
            b.n_null::DOUBLE PRECISION      AS actual,
            0.0                             AS expected,
            jsonb_build_object(
                'n_rows',  b.n_rows,
                'n_true',  b.n_true,
                'n_false', b.n_false,
                'n_null',  b.n_null
            )                               AS extra
        FROM base AS b
        ;
        """
    )
    conn.execute(
        sql,
        {"ids": list(ids), "table_name": SOURCE_TABLE_NAME},
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def refresh(ids: Iterable[int], db_url: Optional[str] = None) -> None:
    """
    Refresh stats for the given asset ids from cmc_ema_multi_tf_cal_anchor.

    This function is append-only: it does not delete any existing rows
    in the stats table. Each run for the same ids will add additional
    stats records (distinguished by ingested_at).
    """
    ids_list = list(ids)
    if not ids_list:
        print(f"[{STATS_TABLE_NAME}] No ids provided, nothing to do.")
        return

    engine = _get_engine(db_url)
    _ensure_stats_table(engine)

    print(
        f"[{STATS_TABLE_NAME}] Refreshing stats for ids={ids_list}"
    )

    with engine.begin() as conn:
        print(f"[{STATS_TABLE_NAME}] Inserting daily_row_span stats...")
        _insert_daily_row_span(conn, ids_list)

        print(f"[{STATS_TABLE_NAME}] Inserting roll_false_spacing stats...")
        _insert_roll_false_spacing(conn, ids_list)

        print(f"[{STATS_TABLE_NAME}] Inserting roll_false_count_vs_span stats...")
        _insert_roll_false_count_vs_span(conn, ids_list)

        print(f"[{STATS_TABLE_NAME}] Inserting non_null_ema stats...")
        _insert_non_null_ema(conn, ids_list)

        print(f"[{STATS_TABLE_NAME}] Inserting non_decreasing_ts stats...")
        _insert_non_decreasing_ts(conn, ids_list)

        print(f"[{STATS_TABLE_NAME}] Inserting roll_boolean stats...")
        _insert_roll_boolean(conn, ids_list)

    print(
        f"[{STATS_TABLE_NAME}] Refresh complete for ids={ids_list}"
    )


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def _normalize_ids_arg(engine: sa.Engine, ids_arg: Sequence[str]) -> list[int]:
    """
    Support:
        --ids all
        --ids 1 2 3
        --ids 1,2,3
    """
    if len(ids_arg) == 1 and ids_arg[0].strip().lower() == "all":
        sql = sa.text(
            f"SELECT DISTINCT id FROM {SOURCE_TABLE_NAME} ORDER BY id"
        )
        with engine.begin() as conn:
            rows = conn.execute(sql).fetchall()
        ids = [r[0] for r in rows]
        print(
            f"[{STATS_TABLE_NAME}] Loaded ALL ids from {SOURCE_TABLE_NAME}: {len(ids)}"
        )
        return ids

    raw = ",".join(ids_arg)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    ids = [int(p) for p in parts]
    return ids


def main(argv: Sequence[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=f"Refresh stats for {SOURCE_TABLE_NAME} into {STATS_TABLE_NAME}."
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="Asset ids to update, or 'all'.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Optional DB URL (otherwise TARGET_DB_URL env is used).",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    # We need an engine early to resolve --ids all
    engine = _get_engine(args.db_url)
    ids = _normalize_ids_arg(engine, args.ids)

    # Now run the real refresh with the same db_url
    refresh(ids=ids, db_url=args.db_url)


if __name__ == "__main__":
    main()
