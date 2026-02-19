# src/ta_lab2/scripts/refresh_ema_daily_stats.py
from __future__ import annotations

r"""
Run data quality checks for cmc_ema_daily and store results in ema_daily_stats.

Assumptions
-----------
- cmc_ema_daily has (at least): id, ts, period, ema, roll.
- Daily timeframe => tf_days = 1.

Tests
-----

We compute a small set of repeatable "stats" and persist them to ema_daily_stats
so that we can track them over time:

1) ema_daily_vs_price_row_count  (table_name = 'cmc_ema_daily')

   For each (id, period):
     - n_price_rows = COUNT(*) from cmc_price_histories7 for that id.
     - n_ema_rows   = COUNT(*) from cmc_ema_daily for that (id, period).
     - expected_n   = n_price_rows - warmup_days
       where warmup_days = period - 1 (min_periods = period).

   Status:
     - PASS if n_ema_rows = expected_n
     - WARN if |n_ema_rows - expected_n| between 1 and 5
     - FAIL otherwise

   extra JSON includes:
     - price_n
     - ema_n
     - expected_n
     - missing_from_expected (ema_n - expected_n)
     - max_ema_ts, min_ema_ts
     - max_price_ts, min_price_ts

2) ema_daily_max_ts_vs_price  (table_name = 'cmc_ema_daily')

   For each (id, period):
     - price_max_ts = MAX(timestamp) from cmc_price_histories7 for that id.
     - max_ema_ts   = MAX(ts)        from cmc_ema_daily for that (id, period).
     - lag_days     = DATE(price_max_ts) - DATE(max_ema_ts)

   Status:
     - PASS if 0 <= lag_days <= 2.
     - WARN if 3 <= lag_days <= 7.
     - FAIL otherwise or if timestamps are NULL.

3) ema_daily_roll_flag_consistency  (table_name = 'cmc_ema_daily')

   Current design for cmc_ema_daily:
     - roll is expected to always be FALSE (no preview/canonical semantics yet).
   This test simply verifies that there are no rows with roll = TRUE.

   For each (id, period):
     - n_rows  = total rows
     - n_true  = count of rows where roll = TRUE

   Status:
     - PASS if n_true = 0
     - FAIL if n_true > 0

   extra JSON includes:
     - n_rows
     - n_true

---------------------------------------------------------------------------
USAGE EXAMPLES
---------------------------------------------------------------------------

1) PowerShell (from repo root, using TARGET_DB_URL in ta_lab2.config):

    PS C:\Users\asafi\Downloads\ta_lab2> python -m ta_lab2.scripts.refresh_ema_daily_stats

2) Passing an explicit DB URL:

    PS C:\Users\asafi\Downloads\ta_lab2> python -m ta_lab2.scripts.refresh_ema_daily_stats --db-url "postgresql://user:pass@localhost:5432/ta_lab2"

After running, inspect recent non-PASS results:

    SELECT *
    FROM ema_daily_stats
    WHERE checked_at > now() - interval '1 hour'
      AND status <> 'PASS'
    ORDER BY checked_at DESC;
"""

import argparse
from typing import Optional

from sqlalchemy import text

from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
)


# ---------------------------------------------------------------------------
# DDL: shared stats table
# ---------------------------------------------------------------------------

DDL_STATS_TABLE = """
CREATE TABLE IF NOT EXISTS ema_daily_stats (
    stat_id        BIGSERIAL PRIMARY KEY,
    table_name     TEXT        NOT NULL,   -- e.g. 'cmc_ema_daily'
    test_name      TEXT        NOT NULL,   -- e.g. 'ema_daily_vs_price_row_count'
    asset_id       INTEGER,                -- cmc id; NULL for global tests
    tf             TEXT,                   -- timeframe label (unused for daily)
    period         INTEGER,                -- EMA period when relevant
    status         TEXT        NOT NULL,   -- 'PASS', 'WARN', 'FAIL'
    actual         NUMERIC,                -- numeric actual value (e.g. row count)
    expected       NUMERIC,                -- numeric expected value
    extra          JSONB,                  -- JSON payload with extra info
    checked_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# ---------------------------------------------------------------------------
# Test 1: EMA daily row counts vs price bar counts
# ---------------------------------------------------------------------------

SQL_TEST_EMA_DAILY_VS_PRICE = """
INSERT INTO ema_daily_stats (
    table_name, test_name, asset_id, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_daily' AS table_name,
    'ema_daily_vs_price_row_count' AS test_name,
    j.asset_id,
    j.period,
    CASE
        WHEN j.price_n IS NULL THEN 'FAIL'
        WHEN j.missing_from_expected = 0 THEN 'PASS'
        WHEN j.missing_from_expected BETWEEN -5 AND 5 THEN 'WARN'
        ELSE 'FAIL'
    END AS status,
    j.ema_n::NUMERIC          AS actual,
    j.expected_n::NUMERIC     AS expected,
    jsonb_build_object(
        'price_n',               j.price_n,
        'ema_n',                 j.ema_n,
        'expected_n',            j.expected_n,
        'missing_from_expected', j.missing_from_expected,
        'min_ema_ts',            j.min_ema_ts,
        'max_ema_ts',            j.max_ema_ts,
        'min_price_ts',          j.min_price_ts,
        'max_price_ts',          j.max_price_ts
    ) AS extra
FROM (
    WITH price_counts AS (
        SELECT
            id AS asset_id,
            COUNT(*)              AS price_n,
            MIN("timestamp")      AS min_price_ts,
            MAX("timestamp")      AS max_price_ts
        FROM cmc_price_histories7
        GROUP BY id
    ),
    ema_counts AS (
        SELECT
            id AS asset_id,
            period,
            COUNT(*)         AS ema_n,
            MIN(ts)          AS min_ema_ts,
            MAX(ts)          AS max_ema_ts
        FROM cmc_ema_daily
        GROUP BY id, period
    )
    SELECT
        e.asset_id,
        e.period,
        p.price_n,
        e.ema_n,
        GREATEST(p.price_n - (e.period - 1), 0) AS expected_n,
        e.ema_n - GREATEST(p.price_n - (e.period - 1), 0) AS missing_from_expected,
        e.min_ema_ts,
        e.max_ema_ts,
        p.min_price_ts,
        p.max_price_ts
    FROM ema_counts e
    LEFT JOIN price_counts p
      ON p.asset_id = e.asset_id
) AS j;
"""


# ---------------------------------------------------------------------------
# Test 2: EMA daily max ts vs price max ts
# ---------------------------------------------------------------------------

SQL_TEST_EMA_DAILY_MAX_TS = """
INSERT INTO ema_daily_stats (
    table_name, test_name, asset_id, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_daily' AS table_name,
    'ema_daily_max_ts_vs_price' AS test_name,
    j.asset_id,
    j.period,
    CASE
        WHEN j.price_max_ts IS NULL OR j.max_ema_ts IS NULL THEN 'FAIL'
        WHEN j.lag_days BETWEEN 0 AND 2 THEN 'PASS'
        WHEN j.lag_days BETWEEN 3 AND 7 THEN 'WARN'
        ELSE 'FAIL'
    END AS status,
    j.lag_days::NUMERIC   AS actual,   -- days EMA is behind price
    0::NUMERIC            AS expected, -- ideally lag_days = 0
    jsonb_build_object(
        'price_max_ts', j.price_max_ts,
        'max_ema_ts',   j.max_ema_ts,
        'lag_days',     j.lag_days
    ) AS extra
FROM (
    WITH price_max AS (
        SELECT
            id AS asset_id,
            MAX("timestamp") AS price_max_ts
        FROM cmc_price_histories7
        GROUP BY id
    ),
    ema_max AS (
        SELECT
            id AS asset_id,
            period,
            MAX(ts) AS max_ema_ts
        FROM cmc_ema_daily
        GROUP BY id, period
    )
    SELECT
        e.asset_id,
        e.period,
        p.price_max_ts,
        e.max_ema_ts,
        CASE
            WHEN p.price_max_ts IS NULL OR e.max_ema_ts IS NULL THEN NULL
            ELSE (p.price_max_ts::date - e.max_ema_ts::date)
        END AS lag_days
    FROM ema_max e
    LEFT JOIN price_max p
      ON p.asset_id = e.asset_id
) AS j;
"""


# ---------------------------------------------------------------------------
# Test 3: EMA daily roll flag consistency
# ---------------------------------------------------------------------------

# For cmc_ema_daily we expect roll to always be FALSE.
# This test simply checks that there are no TRUE roll flags.
SQL_TEST_EMA_DAILY_ROLL_FLAG = """
INSERT INTO ema_daily_stats (
    table_name, test_name, asset_id, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_daily' AS table_name,
    'ema_daily_roll_flag_consistency' AS test_name,
    g.asset_id,
    g.period,
    CASE
        WHEN g.n_true = 0 THEN 'PASS'
        ELSE 'FAIL'
    END AS status,
    g.n_true::NUMERIC AS actual,   -- number of rows with roll = TRUE
    0::NUMERIC        AS expected, -- we expect zero TRUE roll flags
    jsonb_build_object(
        'n_rows', g.n_rows,
        'n_true', g.n_true
    ) AS extra
FROM (
    SELECT
        id      AS asset_id,
        period,
        COUNT(*) AS n_rows,
        SUM(
            CASE
                WHEN roll = TRUE THEN 1
                ELSE 0
            END
        ) AS n_true
    FROM cmc_ema_daily
    GROUP BY id, period
) AS g;
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_all_tests(engine) -> None:
    """
    Run all cmc_ema_daily tests in a single transaction.
    """
    with engine.begin() as conn:
        conn.execute(text(DDL_STATS_TABLE))
        conn.execute(text(SQL_TEST_EMA_DAILY_VS_PRICE))
        conn.execute(text(SQL_TEST_EMA_DAILY_MAX_TS))
        conn.execute(text(SQL_TEST_EMA_DAILY_ROLL_FLAG))


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
            description="Run EMA daily data quality stats for cmc_ema_daily."
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
    #   python -m ta_lab2.scripts.refresh_ema_daily_stats
    main()
