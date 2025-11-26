from __future__ import annotations

"""
Run data quality checks for cmc_ema_multi_tf and store results in ema_multi_tf_stats.

Assumptions
-----------
- cmc_ema_multi_tf has (at least):
    id, ts, tf, tf_days, period, ema, roll
- Canonical vs preview semantics:
    * Canonical rows: roll = false
    * Preview rows : roll = true

Tests implemented
-----------------

1) ema_multi_tf_row_count_vs_span_roll_false  (table_name = 'cmc_ema_multi_tf')

   For canonical rows: WHERE roll = false.

   For each (id, tf, tf_days, period):
     - min_date, max_date from ts::date.
     - n_rows = count(*).
     - expected_n =
          CASE
            WHEN tf_days IS NULL OR <= 0 THEN NULL
            ELSE ((max_date - min_date)::numeric / tf_days) + 1
          END
     - missing_from_expected = expected_n - n_rows.

   Status:
     - PASS if missing_from_expected = 0.
     - WARN if -2 <= missing_from_expected <= 2.
     - FAIL otherwise or if expected_n is NULL.

2) ema_multi_tf_row_count_vs_span_roll_true  (preview rows, roll = true)

   Preview rows are *non-canonical*. We don't expect one per tf bucket.
   Instead we compare preview density to canonical rows:

   For each (id, tf, tf_days, period):
     - n_preview   = count(*) WHERE roll = true
     - n_canonical = count(*) WHERE roll = false
     - preview_to_canonical_ratio = n_preview / n_canonical (if n_canonical > 0)

   Status:
     - WARN if n_canonical is NULL or 0 (can't judge density).
     - PASS if preview_to_canonical_ratio <= 50
     - WARN if 50 < ratio <= 200
     - FAIL if ratio > 200

3) ema_multi_tf_max_gap_vs_tf_days_roll_false

   For canonical rows: WHERE roll = false.

   For each (id, tf, tf_days, period):
     - Order ts::date ascending.
     - gap_days = ts_date - prev_date (0 for first row).
     - max_gap_days = max(gap_days).

   Status:
     - PASS if max_gap_days <= tf_days.
     - WARN if max_gap_days <= tf_days * 2.
     - FAIL otherwise or if tf_days is NULL.

4) ema_multi_tf_max_gap_vs_tf_days_roll_true

   Same logic but WHERE roll = true (preview rows).

5) ema_multi_tf_roll_flag_consistency

   For each (id, tf, period, ts_date):
     - n_canonical_at_ts = count where roll = false
     - n_preview_at_ts   = count where roll = true

   We only enforce:
     - At most one canonical row per (id, tf, period, ts_date).

   Per (id, tf, period) group we compute:
     - n_rows                 = total rows
     - n_problem_timestamps   = count of ts_date where n_canonical_at_ts > 1

   Status:
     - PASS if n_problem_timestamps = 0.
     - WARN if 1 <= n_problem_timestamps <= 5.
     - FAIL if n_problem_timestamps > 5.
"""

import argparse
from typing import Optional

from sqlalchemy import create_engine, text

from ta_lab2.config import TARGET_DB_URL


# ---------------------------------------------------------------------------
# DDL: shared stats table
# ---------------------------------------------------------------------------

DDL_STATS_TABLE = """
CREATE TABLE IF NOT EXISTS ema_multi_tf_stats (
    stat_id        BIGSERIAL PRIMARY KEY,
    table_name     TEXT        NOT NULL,
    test_name      TEXT        NOT NULL,
    asset_id       INTEGER,
    tf             TEXT,
    period         INTEGER,
    status         TEXT        NOT NULL,
    actual         NUMERIC,
    expected       NUMERIC,
    extra          JSONB,
    checked_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# ---------------------------------------------------------------------------
# Test 1 & 2: row count vs span for roll = false and roll = true
# ---------------------------------------------------------------------------

SQL_TEST_ROWCOUNT_ROLL_FALSE = """
INSERT INTO ema_multi_tf_stats (
    table_name, test_name, asset_id, tf, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_multi_tf' AS table_name,
    'ema_multi_tf_row_count_vs_span_roll_false' AS test_name,
    g.asset_id,
    g.tf,
    g.period,
    CASE
        WHEN g.expected_n IS NULL THEN 'WARN'
        WHEN g.missing_from_expected = 0 THEN 'PASS'
        WHEN g.missing_from_expected BETWEEN -2 AND 2 THEN 'WARN'
        ELSE 'FAIL'
    END AS status,
    g.n_rows::NUMERIC     AS actual,
    g.expected_n::NUMERIC AS expected,
    jsonb_build_object(
        'min_date',             g.min_date,
        'max_date',             g.max_date,
        'tf_days',              g.tf_days,
        'n_rows',               g.n_rows,
        'expected_n',           g.expected_n,
        'missing_from_expected',g.missing_from_expected
    ) AS extra
FROM (
    WITH groups AS (
        SELECT
            id AS asset_id,
            tf,
            tf_days,
            period,
            MIN(ts::date) AS min_date,
            MAX(ts::date) AS max_date,
            COUNT(*)      AS n_rows
        FROM cmc_ema_multi_tf
        WHERE roll = false
        GROUP BY id, tf, tf_days, period
    )
    SELECT
        asset_id,
        tf,
        tf_days,
        period,
        n_rows,
        min_date,
        max_date,
        CASE
            WHEN tf_days IS NULL OR tf_days <= 0 OR min_date IS NULL OR max_date IS NULL THEN NULL
            ELSE ((max_date - min_date)::numeric / tf_days) + 1
        END AS expected_n,
        CASE
            WHEN tf_days IS NULL OR tf_days <= 0 OR min_date IS NULL OR max_date IS NULL THEN NULL
            ELSE ((max_date - min_date)::numeric / tf_days) + 1 - n_rows
        END AS missing_from_expected
    FROM groups
) AS g;
"""

SQL_TEST_ROWCOUNT_ROLL_TRUE = """
INSERT INTO ema_multi_tf_stats (
    table_name, test_name, asset_id, tf, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_multi_tf' AS table_name,
    'ema_multi_tf_row_count_vs_span_roll_true' AS test_name,
    p.asset_id,
    p.tf,
    p.period,
    CASE
        WHEN p.n_preview IS NULL OR p.n_preview = 0 THEN 'WARN'
        WHEN p.n_canonical IS NULL OR p.n_canonical = 0 THEN 'WARN'
        WHEN p.tf_days IS NULL OR p.tf_days <= 0 THEN 'WARN'

        -- Per-tf thresholds based on tf_days
        WHEN p.preview_to_canonical_ratio <=
             CASE
                 WHEN p.tf_days <= 7   THEN 10     -- very short tf
                 WHEN p.tf_days <= 31  THEN 20     -- up to ~1M
                 WHEN p.tf_days <= 90  THEN 50     -- up to ~3M
                 ELSE 100                          -- 3M+ (9M, 12M, etc.)
             END
        THEN 'PASS'

        WHEN p.preview_to_canonical_ratio <=
             CASE
                 WHEN p.tf_days <= 7   THEN 50
                 WHEN p.tf_days <= 31  THEN 100
                 WHEN p.tf_days <= 90  THEN 200
                 ELSE 400
             END
        THEN 'WARN'

        ELSE 'FAIL'
    END AS status,
    p.n_preview::NUMERIC   AS actual,   -- number of preview rows
    p.n_canonical::NUMERIC AS expected, -- number of canonical rows (context)
    jsonb_build_object(
        'min_date',                    p.min_date,
        'max_date',                    p.max_date,
        'tf_days',                     p.tf_days,
        'n_preview',                   p.n_preview,
        'n_canonical',                 p.n_canonical,
        'preview_to_canonical_ratio',  p.preview_to_canonical_ratio
    ) AS extra
FROM (
    WITH previews AS (
        SELECT
            id AS asset_id,
            tf,
            tf_days,
            period,
            MIN(ts::date) AS min_date,
            MAX(ts::date) AS max_date,
            COUNT(*)      AS n_preview
        FROM cmc_ema_multi_tf
        WHERE roll = true
        GROUP BY id, tf, tf_days, period
    ),
    canonicals AS (
        SELECT
            id AS asset_id,
            tf,
            period,
            COUNT(*) AS n_canonical
        FROM cmc_ema_multi_tf
        WHERE roll = false
        GROUP BY id, tf, period
    )
    SELECT
        p.asset_id,
        p.tf,
        p.tf_days,
        p.period,
        p.min_date,
        p.max_date,
        p.n_preview,
        c.n_canonical,
        CASE
            WHEN c.n_canonical IS NULL OR c.n_canonical = 0 THEN NULL
            ELSE (p.n_preview::numeric / c.n_canonical::numeric)
        END AS preview_to_canonical_ratio
    FROM previews p
    LEFT JOIN canonicals c
      ON c.asset_id = p.asset_id
     AND c.tf       = p.tf
     AND c.period   = p.period
) AS p;
"""



# ---------------------------------------------------------------------------
# Test 3 & 4: max gap vs tf_days for roll = false and roll = true
# ---------------------------------------------------------------------------

SQL_TEST_GAP_ROLL_FALSE = """
INSERT INTO ema_multi_tf_stats (
    table_name, test_name, asset_id, tf, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_multi_tf' AS table_name,
    'ema_multi_tf_max_gap_vs_tf_days_roll_false' AS test_name,
    g.asset_id,
    g.tf,
    g.period,
    CASE
        WHEN g.tf_days IS NULL OR g.tf_days <= 0 THEN 'WARN'
        WHEN g.max_gap_days <= g.tf_days THEN 'PASS'
        WHEN g.max_gap_days <= g.tf_days * 2 THEN 'WARN'
        ELSE 'FAIL'
    END AS status,
    g.max_gap_days::NUMERIC AS actual,   -- observed worst-case gap
    g.tf_days::NUMERIC      AS expected, -- target gap
    jsonb_build_object(
        'tf_days',      g.tf_days,
        'max_gap_days', g.max_gap_days,
        'n_rows',       g.n_rows
    ) AS extra
FROM (
    WITH ordered AS (
        SELECT
            id AS asset_id,
            tf,
            tf_days,
            period,
            ts::date AS ts_date,
            LAG(ts::date) OVER (
                PARTITION BY id, tf, period
                ORDER BY ts
            ) AS prev_date
        FROM cmc_ema_multi_tf
        WHERE roll = false
    ),
    gaps AS (
        SELECT
            asset_id,
            tf,
            tf_days,
            period,
            COUNT(*) AS n_rows,
            MAX(
                CASE
                    WHEN prev_date IS NULL THEN 0
                    ELSE (ts_date - prev_date)
                END
            ) AS max_gap_days
        FROM ordered
        GROUP BY asset_id, tf, tf_days, period
    )
    SELECT * FROM gaps
) AS g;
"""

SQL_TEST_GAP_ROLL_TRUE = """
INSERT INTO ema_multi_tf_stats (
    table_name, test_name, asset_id, tf, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_multi_tf' AS table_name,
    'ema_multi_tf_max_gap_vs_tf_days_roll_true' AS test_name,
    g.asset_id,
    g.tf,
    g.period,
    CASE
        WHEN g.tf_days IS NULL OR g.tf_days <= 0 THEN 'WARN'
        WHEN g.max_gap_days <= g.tf_days THEN 'PASS'
        WHEN g.max_gap_days <= g.tf_days * 2 THEN 'WARN'
        ELSE 'FAIL'
    END AS status,
    g.max_gap_days::NUMERIC AS actual,
    g.tf_days::NUMERIC      AS expected,
    jsonb_build_object(
        'tf_days',      g.tf_days,
        'max_gap_days', g.max_gap_days,
        'n_rows',       g.n_rows
    ) AS extra
FROM (
    WITH ordered AS (
        SELECT
            id AS asset_id,
            tf,
            tf_days,
            period,
            ts::date AS ts_date,
            LAG(ts::date) OVER (
                PARTITION BY id, tf, period
                ORDER BY ts
            ) AS prev_date
        FROM cmc_ema_multi_tf
        WHERE roll = true
    ),
    gaps AS (
        SELECT
            asset_id,
            tf,
            tf_days,
            period,
            COUNT(*) AS n_rows,
            MAX(
                CASE
                    WHEN prev_date IS NULL THEN 0
                    ELSE (ts_date - prev_date)
                END
            ) AS max_gap_days
        FROM ordered
        GROUP BY asset_id, tf, tf_days, period
    )
    SELECT * FROM gaps
) AS g;
"""


# ---------------------------------------------------------------------------
# Test 5: roll flag consistency based on “one canonical per ts”
# ---------------------------------------------------------------------------

SQL_TEST_ROLL_FLAG_CONSISTENCY = """
INSERT INTO ema_multi_tf_stats (
    table_name, test_name, asset_id, tf, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_multi_tf' AS table_name,
    'ema_multi_tf_roll_flag_consistency' AS test_name,
    g.asset_id,
    g.tf,
    g.period,
    CASE
        WHEN g.n_problem_timestamps = 0 THEN 'PASS'
        WHEN g.n_problem_timestamps BETWEEN 1 AND 5 THEN 'WARN'
        ELSE 'FAIL'
    END AS status,
    g.n_problem_timestamps::NUMERIC AS actual,   -- number of timestamps with >1 canonical row
    0::NUMERIC                       AS expected,
    jsonb_build_object(
        'n_rows',               g.n_rows,
        'n_problem_timestamps', g.n_problem_timestamps,
        'n_canonical_rows',     g.n_canonical_rows,
        'n_preview_rows',       g.n_preview_rows
    ) AS extra
FROM (
    WITH per_ts AS (
        SELECT
            id        AS asset_id,
            tf,
            period,
            ts::date AS ts_date,
            SUM(CASE WHEN roll = false THEN 1 ELSE 0 END) AS n_canonical_at_ts,
            SUM(CASE WHEN roll = true  THEN 1 ELSE 0 END) AS n_preview_at_ts,
            COUNT(*) AS n_rows_at_ts
        FROM cmc_ema_multi_tf
        GROUP BY id, tf, period, ts::date
    )
    SELECT
        asset_id,
        tf,
        period,
        SUM(n_rows_at_ts) AS n_rows,
        SUM(CASE WHEN n_canonical_at_ts > 1 THEN 1 ELSE 0 END) AS n_problem_timestamps,
        SUM(n_canonical_at_ts) AS n_canonical_rows,
        SUM(n_preview_at_ts)   AS n_preview_rows
    FROM per_ts
    GROUP BY asset_id, tf, period
) AS g;
"""


# ---------------------------------------------------------------------------
# Helper: engine + runner
# ---------------------------------------------------------------------------

def get_engine(db_url: Optional[str] = None):
    """
    Return a SQLAlchemy engine.

    If db_url is None, use TARGET_DB_URL from ta_lab2.config.
    """
    return create_engine(db_url or TARGET_DB_URL)


def run_all_tests(engine) -> None:
    """
    Run all cmc_ema_multi_tf tests in a single transaction.
    """
    with engine.begin() as conn:
        conn.execute(text(DDL_STATS_TABLE))

        # Rowcount vs span tests
        conn.execute(text(SQL_TEST_ROWCOUNT_ROLL_FALSE))
        conn.execute(text(SQL_TEST_ROWCOUNT_ROLL_TRUE))

        # Gap vs tf_days tests
        conn.execute(text(SQL_TEST_GAP_ROLL_FALSE))
        conn.execute(text(SQL_TEST_GAP_ROLL_TRUE))

        # Roll-flag consistency
        conn.execute(text(SQL_TEST_ROLL_FLAG_CONSISTENCY))


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(db_url: Optional[str] = None) -> None:
    """
    Main entrypoint for both CLI and programmatic use.

    Parameters
    ----------
    db_url : str, optional
        If provided, overrides TARGET_DB_URL.
    """
    if db_url is None:
        parser = argparse.ArgumentParser(
            description="Run EMA multi-timeframe data quality stats for cmc_ema_multi_tf."
        )
        parser.add_argument(
            "--db-url",
            help="Override TARGET_DB_URL from ta_lab2.config",
        )
        args = parser.parse_args()
        db_url = args.db_url

    engine = get_engine(db_url)
    run_all_tests(engine)


if __name__ == "__main__":
    # Preferred from repo root:
    #   python -m ta_lab2.scripts.refresh_ema_multi_tf_stats
    main()
