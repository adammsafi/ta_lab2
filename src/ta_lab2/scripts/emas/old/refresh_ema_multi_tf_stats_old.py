# src/ta_lab2/scripts/refresh_ema_multi_tf_stats.py
from __future__ import annotations

"""
Run data quality checks for cmc_ema_multi_tf and store results in ema_multi_tf_stats.

Assumptions
-----------
- cmc_ema_multi_tf has (at least):
    id, ts, tf, tf_days, period, ema, roll
- Canonical vs preview semantics (adjust if needed):
    * Canonical rows: roll = false
    * Preview rows : roll = true
- Canonical anchors per (id, tf, period) occur where:
      offset_days = (ts::date - min(ts)::date)   -- in days
      block_size_days = tf_days * period
      offset_days % block_size_days = 0

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

   Same logic as above but WHERE roll = true and test_name suffix _roll_true.

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

   For each (id, tf, tf_days, period):
     - min_date = min(ts::date) for that group.
     - offset_days = (ts::date - min_date).
     - block_size_days = tf_days * period.

   Expected pattern (again, based on assumption above):
     - If block_size_days <= 0 or NULL → pattern unknown, WARN.
     - If offset_days % block_size_days = 0 → row canonical → roll = false.
     - Else                                  → row preview   → roll = true.

   We count mismatches per group.

   Status:
     - PASS if n_mismatches = 0.
     - WARN if 1 <= n_mismatches <= 5.
     - FAIL if n_mismatches > 5 or block_size_days is NULL.

---------------------------------------------------------------------------
USAGE EXAMPLES
---------------------------------------------------------------------------

1) PowerShell (from repo root, using TARGET_DB_URL):

    PS C:\\Users\\asafi\\Downloads\\ta_lab2> python -m ta_lab2.scripts.refresh_ema_multi_tf_stats

   Or overriding DB URL:

    PS C:\\Users\\asafi\\Downloads\\ta_lab2> python -m ta_lab2.scripts.refresh_ema_multi_tf_stats `
        --db-url "postgresql://user:pass@localhost:5432/ta_lab2"

2) Spyder (IPython console):

   Run the script file directly:

       %runfile C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/refresh_ema_multi_tf_stats.py \
           --wdir C:/Users/asafi/Downloads/ta_lab2

After running, inspect recent non-PASS results:

    SELECT *
    FROM ema_multi_tf_stats
    WHERE checked_at > now() - interval '1 hour'
      AND status <> 'PASS'
    ORDER BY checked_at DESC;
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
        WHERE roll = true
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
# Test 5: roll flag consistency based on tf_days * period
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
        WHEN g.block_size_days IS NULL OR g.block_size_days <= 0 THEN 'WARN'
        WHEN g.n_mismatches = 0 THEN 'PASS'
        WHEN g.n_mismatches BETWEEN 1 AND 5 THEN 'WARN'
        ELSE 'FAIL'
    END AS status,
    g.n_mismatches::NUMERIC  AS actual,    -- number of flag mismatches
    0::NUMERIC               AS expected,  -- ideally zero mismatches
    jsonb_build_object(
        'n_rows',          g.n_rows,
        'n_mismatches',    g.n_mismatches,
        'block_size_days', g.block_size_days
    ) AS extra
FROM (
    WITH base AS (
        SELECT
            id        AS asset_id,
            tf,
            tf_days,
            period,
            roll,
            ts::date AS ts_date,
            MIN(ts::date) OVER (
                PARTITION BY id, tf, period
            ) AS min_date
        FROM cmc_ema_multi_tf
    )
    SELECT
        asset_id,
        tf,
        period,
        COUNT(*) AS n_rows,
        MAX(
            CASE
                WHEN tf_days IS NULL OR period IS NULL THEN NULL
                ELSE tf_days * period
            END
        ) AS block_size_days,
        SUM(
            CASE
                WHEN tf_days IS NULL OR period IS NULL OR tf_days * period <= 0 THEN 0
                ELSE
                    CASE
                        -- offset multiple of block_size_days => canonical => roll should be false
                        WHEN ((ts_date - min_date)::int % (tf_days * period) = 0 AND roll = false) THEN 0
                        -- non-multiple => preview => roll should be true
                        WHEN ((ts_date - min_date)::int % (tf_days * period) <> 0 AND roll = true) THEN 0
                        ELSE 1
                    END
            END
        ) AS n_mismatches
    FROM base
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
