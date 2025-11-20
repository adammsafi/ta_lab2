# src/ta_lab2/scripts/refresh_ema_daily_stats.py
from __future__ import annotations

"""
Run data quality checks for cmc_ema_daily and store results in cmc_data_stats.

Assumptions
-----------
- cmc_ema_daily has (at least): id, ts, period, ema, roll.
- Daily timeframe => tf_days = 1.
- Canonical vs preview semantics (adjust if needed):
    * Canonical rows: roll = false
    * Preview rows : roll = true
    * Canonical anchors occur where:
          offset_days = (ts::date - min(ts)::date)
          offset_days % (1 * period) = 0

Tests implemented
-----------------

1) ema_daily_vs_price_row_count  (table_name = 'cmc_ema_daily')

   For each (id, period):
     - price_n  = rows in cmc_price_histories7 for that id.
     - ema_n    = rows in cmc_ema_daily for that (id, period), all rolls.
     - expected_n = max(price_n - period + 1, 0).
     - missing_from_expected = expected_n - ema_n.

   Status:
     - PASS if missing_from_expected = 0.
     - WARN if -5 <= missing_from_expected <= 5.
     - FAIL otherwise or if price_n is NULL.

2) ema_daily_max_ts_vs_price  (table_name = 'cmc_ema_daily')

   For each (id, period):
     - price_max_ts = max(timestamp) from cmc_price_histories7 for that id.
     - max_ema_ts   = max(ts) from cmc_ema_daily for that (id, period).
     - lag_days = (price_max_ts::date - max_ema_ts::date).

   Status:
     - PASS if 0 <= lag_days <= 2.
     - WARN if 3 <= lag_days <= 7.
     - FAIL otherwise or if timestamps are NULL.

3) ema_daily_roll_flag_consistency  (table_name = 'cmc_ema_daily')

   For each (id, period):
     - min_date = min(ts::date) within that group.
     - offset_days = (ts::date - min_date).
     - block_size_days = period * 1 (tf_days = 1).

   Expected pattern (based on assumption above):
     - If block_size_days <= 0 or period is NULL → pattern unknown, WARN.
     - If offset_days % block_size_days = 0 → row should be canonical → roll = false.
     - Else                                  → row should be preview   → roll = true.

   We count mismatches for each (id, period).

   Status:
     - PASS if n_mismatches = 0.
     - WARN if 1 <= n_mismatches <= 5.
     - FAIL if n_mismatches > 5 or block_size_days is NULL.

---------------------------------------------------------------------------
USAGE EXAMPLES
---------------------------------------------------------------------------

1) PowerShell (from repo root, using TARGET_DB_URL in ta_lab2.config):

    PS C:\\Users\\asafi\\Downloads\\ta_lab2> python -m ta_lab2.scripts.refresh_ema_daily_stats

   Or overriding DB URL:

    PS C:\\Users\\asafi\\Downloads\\ta_lab2> python -m ta_lab2.scripts.refresh_ema_daily_stats `
        --db-url "postgresql://user:pass@localhost:5432/ta_lab2"

2) Spyder (IPython console):

   Option A: run the script file directly

       %runfile C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/refresh_ema_daily_stats.py \
           --wdir C:/Users/asafi/Downloads/ta_lab2

   Option B: import and call main() manually

       from ta_lab2.scripts.refresh_ema_daily_stats import main

       # Use TARGET_DB_URL from ta_lab2.config
       main()

       # Or with an explicit DB URL:
       main(db_url="postgresql://user:pass@localhost:5432/ta_lab2")

After running, inspect recent non-PASS results:

    SELECT *
    FROM cmc_data_stats
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
CREATE TABLE IF NOT EXISTS cmc_data_stats (
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
INSERT INTO cmc_data_stats (
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
        e.ema_n,
        e.min_ema_ts,
        e.max_ema_ts,
        p.price_n,
        p.min_price_ts,
        p.max_price_ts,
        CASE
            WHEN p.price_n IS NULL THEN NULL
            ELSE GREATEST(p.price_n - e.period + 1, 0)
        END AS expected_n,
        CASE
            WHEN p.price_n IS NULL THEN NULL
            ELSE GREATEST(p.price_n - e.period + 1, 0) - e.ema_n
        END AS missing_from_expected
    FROM ema_counts e
    LEFT JOIN price_counts p
      ON p.asset_id = e.asset_id
) AS j;
"""


# ---------------------------------------------------------------------------
# Test 2: EMA daily max ts vs price max timestamp
# ---------------------------------------------------------------------------

SQL_TEST_EMA_DAILY_MAX_TS = """
INSERT INTO cmc_data_stats (
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
        e.max_ema_ts,
        p.price_max_ts,
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
#
# tf_days for daily = 1.
# block_size_days = period * tf_days = period.
#
SQL_TEST_EMA_DAILY_ROLL_FLAG = """
INSERT INTO cmc_data_stats (
    table_name, test_name, asset_id, period,
    status, actual, expected, extra
)
SELECT
    'cmc_ema_daily' AS table_name,
    'ema_daily_roll_flag_consistency' AS test_name,
    g.asset_id,
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
            id          AS asset_id,
            period,
            roll,
            ts::date    AS ts_date,
            MIN(ts::date) OVER (PARTITION BY id, period) AS min_date
        FROM cmc_ema_daily
    )
    SELECT
        asset_id,
        period,
        COUNT(*) AS n_rows,
        MAX(period) AS block_size_days,
        SUM(
            CASE
                WHEN period IS NULL OR period <= 0 THEN 0
                ELSE
                    CASE
                        -- offset_days multiple of block_size_days => canonical => roll should be false
                        WHEN ((ts_date - min_date) % period = 0 AND roll = false) THEN 0
                        -- non-multiple => preview => roll should be true
                        WHEN ((ts_date - min_date) % period <> 0 AND roll = true) THEN 0
                        ELSE 1
                    END
            END
        ) AS n_mismatches
    FROM base
    GROUP BY asset_id, period
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
