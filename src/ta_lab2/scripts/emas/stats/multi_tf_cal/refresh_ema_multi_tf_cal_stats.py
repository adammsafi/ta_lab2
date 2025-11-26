from __future__ import annotations

"""
Run data quality checks for cmc_ema_multi_tf_cal and store results in
ema_multi_tf_cal_stats.

Assumptions
-----------
- cmc_ema_multi_tf_cal has (at least):
    id, ts, tf, tf_days, period, ema, roll
- Canonical vs preview semantics:
    * Canonical rows: roll = false
    * Preview rows : roll = true

Tests implemented
-----------------

1) ema_multi_tf_cal_row_count_vs_span_roll_false
   For canonical rows (roll = false), check row count vs span/tf_days.

2) ema_multi_tf_cal_row_count_vs_span_roll_true
   For preview rows (roll = true), check preview density vs canonical,
   with tf-dependent thresholds (same scheme as ema_multi_tf).

3) ema_multi_tf_cal_max_gap_vs_tf_days_roll_false
   For canonical rows, check max gap vs tf_days.

4) ema_multi_tf_cal_max_gap_vs_tf_days_roll_true
   Same, but for preview rows.

5) ema_multi_tf_cal_roll_flag_consistency
   For each (asset_id, tf, period), enforce:
       - At most one canonical row (roll = false) per ts_date.
   This matches the ema_multi_tf roll-flag semantics.
"""

import argparse
from typing import Optional

from sqlalchemy import create_engine, text

from ta_lab2.config import TARGET_DB_URL


# ---------------------------------------------------------------------------
# DDL: stats table for cmc_ema_multi_tf_cal
# ---------------------------------------------------------------------------

DDL_STATS_TABLE_CAL = """
CREATE TABLE IF NOT EXISTS ema_multi_tf_cal_stats (
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

SQL_TEST_ROWCOUNT_ROLL_FALSE_CAL = """
INSERT INTO ema_multi_tf_cal_stats (
    table_name, test_name, asset_id, tf, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_multi_tf_cal' AS table_name,
    'ema_multi_tf_cal_row_count_vs_span_roll_false' AS test_name,
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
        FROM cmc_ema_multi_tf_cal
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

# NEW: density-based test for roll = true (preview rows) with tf-level thresholds
SQL_TEST_ROWCOUNT_ROLL_TRUE_CAL = """
INSERT INTO ema_multi_tf_cal_stats (
    table_name, test_name, asset_id, tf, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_multi_tf_cal' AS table_name,
    'ema_multi_tf_cal_row_count_vs_span_roll_true' AS test_name,
    p.asset_id,
    p.tf,
    p.period,
    CASE
        WHEN p.n_preview IS NULL OR p.n_preview = 0 THEN 'WARN'
        WHEN p.n_canonical IS NULL OR p.n_canonical = 0 THEN 'WARN'
        WHEN p.tf_days IS NULL OR p.tf_days <= 0 THEN 'WARN'

        -- Per-tf thresholds based on tf_days (same scheme as ema_multi_tf)
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
        FROM cmc_ema_multi_tf_cal
        WHERE roll = true
        GROUP BY id, tf, tf_days, period
    ),
    canonicals AS (
        SELECT
            id AS asset_id,
            tf,
            period,
            COUNT(*) AS n_canonical
        FROM cmc_ema_multi_tf_cal
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

SQL_TEST_GAP_ROLL_FALSE_CAL = """
INSERT INTO ema_multi_tf_cal_stats (
    table_name, test_name, asset_id, tf, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_multi_tf_cal' AS table_name,
    'ema_multi_tf_cal_max_gap_vs_tf_days_roll_false' AS test_name,
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
        FROM cmc_ema_multi_tf_cal
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

SQL_TEST_GAP_ROLL_TRUE_CAL = """
INSERT INTO ema_multi_tf_cal_stats (
    table_name, test_name, asset_id, tf, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_multi_tf_cal' AS table_name,
    'ema_multi_tf_cal_max_gap_vs_tf_days_roll_true' AS test_name,
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
        FROM cmc_ema_multi_tf_cal
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
# Test 5: roll flag consistency – at most one canonical per ts_date
# ---------------------------------------------------------------------------

SQL_TEST_ROLL_FLAG_CONSISTENCY_CAL = """
INSERT INTO ema_multi_tf_cal_stats (
    table_name, test_name, asset_id, tf, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_multi_tf_cal' AS table_name,
    'ema_multi_tf_cal_roll_flag_consistency' AS test_name,
    g.asset_id,
    g.tf,
    g.period,
    CASE
        WHEN g.n_problem_timestamps = 0 THEN 'PASS'
        WHEN g.n_problem_timestamps BETWEEN 1 AND 5 THEN 'WARN'
        ELSE 'FAIL'
    END AS status,
    g.n_problem_timestamps::NUMERIC AS actual,   -- timestamps with >1 canonical row
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
        FROM cmc_ema_multi_tf_cal
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
    Run all cmc_ema_multi_tf_cal tests in a single transaction.
    """
    with engine.begin() as conn:
        conn.execute(text(DDL_STATS_TABLE_CAL))

        # Rowcount vs span / density tests
        conn.execute(text(SQL_TEST_ROWCOUNT_ROLL_FALSE_CAL))
        conn.execute(text(SQL_TEST_ROWCOUNT_ROLL_TRUE_CAL))

        # Gap vs tf_days tests
        conn.execute(text(SQL_TEST_GAP_ROLL_FALSE_CAL))
        conn.execute(text(SQL_TEST_GAP_ROLL_TRUE_CAL))

        # Roll-flag consistency
        conn.execute(text(SQL_TEST_ROLL_FLAG_CONSISTENCY_CAL))


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
            description="Run EMA multi-timeframe CAL data quality stats for cmc_ema_multi_tf_cal."
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
    #   python -m ta_lab2.scripts.refresh_ema_multi_tf_cal_stats
    main()
