from __future__ import annotations

"""
Run data quality checks for cmc_price_histories7 and store results in price_histories7_stats.

Tables used
-----------
- cmc_price_histories7: source OHLCV data
- price_histories7_stats      : generic test results / stats table
- cmc_price_ranges    : per-asset "reasonable price" config

Tests implemented
-----------------

1) bar_count_full_span  (table_name = 'cmc_price_histories7')

   For each id AS asset_id:
     - min_ts  = MIN(timestamp)
     - max_ts  = MAX(timestamp)
     - min_date = min_ts::date
     - max_date = max_ts::date
     - expected_bars = (max_date - min_date) + 1
     - n_bars        = COUNT(*)
     - missing_bars  = expected_bars - n_bars

   Status:
     - PASS if missing_bars = 0
     - WARN if 1 <= missing_bars <= 3
     - FAIL if missing_bars > 3

2) price_range_low  (table_name = 'cmc_price_histories7')

   For each asset_id:
     - min_low = MIN(low)
     - Compare against cmc_price_ranges.low_min / low_max.

   Status:
     - WARN if no range configured (r.asset_id IS NULL)
     - FAIL if min_low < low_min OR min_low > low_max
     - PASS otherwise

3) price_range_high  (table_name = 'cmc_price_histories7')

   For each asset_id:
     - max_high = MAX(high)
     - Compare against cmc_price_ranges.high_min / high_max.

   Status:
     - WARN if no range configured
     - FAIL if max_high < high_min OR max_high > high_max
     - PASS otherwise

---------------------------------------------------------------------------
USAGE EXAMPLES
---------------------------------------------------------------------------

1) PowerShell (from repo root, using TARGET_DB_URL in ta_lab2.config):

    PS C:/Users/asafi/Downloads/ta_lab2> python -m ta_lab2.scripts.refresh_price_histories7_stats

   Or overriding DB URL explicitly:

    PS C:/Users/asafi/Downloads/ta_lab2> python -m ta_lab2.scripts.refresh_price_histories7_stats `
        --db-url "postgresql://user:pass@localhost:5432/ta_lab2"

2) Spyder (IPython console), via the small runner script:

    %runfile C:/Users/asafi/Downloads/cmc_price_histories/run_refresh_price_histories7_stats.py \
        --wdir C:/Users/asafi/Downloads/ta_lab2

After running, inspect recent non-PASS results:

    SELECT *
    FROM price_histories7_stats
    WHERE checked_at > now() - interval '1 hour'
      AND status <> 'PASS'
    ORDER BY checked_at DESC;
"""

import argparse
from typing import Optional

from sqlalchemy import create_engine, text

from ta_lab2.config import TARGET_DB_URL


# ---------------------------------------------------------------------------
# DDL: stats table + price range config
# ---------------------------------------------------------------------------

DDL_STATS_TABLE = """
CREATE TABLE IF NOT EXISTS price_histories7_stats (
    stat_id        BIGSERIAL PRIMARY KEY,
    table_name     TEXT        NOT NULL,   -- e.g. 'cmc_price_histories7'
    test_name      TEXT        NOT NULL,   -- e.g. 'bar_count_full_span'
    asset_id       INTEGER,                -- cmc id; NULL for global tests
    tf             TEXT,                   -- timeframe label for EMA tables
    period         INTEGER,                -- EMA period when relevant
    status         TEXT        NOT NULL,   -- 'PASS', 'WARN', 'FAIL'
    actual         NUMERIC,                -- numeric actual value (e.g. n_bars)
    expected       NUMERIC,                -- numeric expected value
    extra          JSONB,                  -- JSON payload with extra info
    checked_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

DDL_PRICE_RANGES = """
CREATE TABLE IF NOT EXISTS cmc_price_ranges (
    asset_id   INTEGER PRIMARY KEY,  -- cmc id
    low_min    NUMERIC,              -- lower bound of plausible lows
    low_max    NUMERIC,              -- upper bound of plausible lows
    high_min   NUMERIC,              -- lower bound of plausible highs
    high_max   NUMERIC,              -- upper bound of plausible highs
    note       TEXT
);
"""


# ---------------------------------------------------------------------------
# Test 1: bar_count_full_span on cmc_price_histories7
# ---------------------------------------------------------------------------

SQL_TEST_BAR_COUNT = """
INSERT INTO price_histories7_stats (
    table_name, test_name, asset_id,
    status, actual, expected, extra
)
SELECT
    'cmc_price_histories7' AS table_name,
    'bar_count_full_span'  AS test_name,
    asset_id,
    CASE
        WHEN missing_bars = 0 THEN 'PASS'
        WHEN missing_bars BETWEEN 1 AND 3 THEN 'WARN'
        ELSE 'FAIL'
    END AS status,
    n_bars::NUMERIC                  AS actual,
    expected_bars::NUMERIC           AS expected,
    jsonb_build_object(
        'min_ts',       min_ts,
        'max_ts',       max_ts,
        'min_date',     min_date,
        'max_date',     max_date,
        'missing_bars', missing_bars
    ) AS extra
FROM (
    WITH per_asset AS (
        SELECT
            id AS asset_id,
            MIN("timestamp")          AS min_ts,
            MAX("timestamp")          AS max_ts,
            MIN("timestamp")::date    AS min_date,
            MAX("timestamp")::date    AS max_date,
            COUNT(*)                  AS n_bars
        FROM cmc_price_histories7
        GROUP BY id
    )
    SELECT
        asset_id,
        min_ts,
        max_ts,
        min_date,
        max_date,
        n_bars,
        ((max_date - min_date) + 1)           AS expected_bars,
        ((max_date - min_date) + 1) - n_bars AS missing_bars
    FROM per_asset
) t;
"""


# ---------------------------------------------------------------------------
# Test 2: price_range_low on cmc_price_histories7
# ---------------------------------------------------------------------------

SQL_TEST_PRICE_LOW = """
INSERT INTO price_histories7_stats (
    table_name, test_name, asset_id,
    status, actual, expected, extra
)
SELECT
    'cmc_price_histories7' AS table_name,
    'price_range_low'      AS test_name,
    e.asset_id,
    CASE
        WHEN r.asset_id IS NULL THEN 'WARN'
        WHEN e.min_low < r.low_min OR e.min_low > r.low_max THEN 'FAIL'
        ELSE 'PASS'
    END AS status,
    e.min_low::NUMERIC                      AS actual,
    r.low_min::NUMERIC                      AS expected,
    jsonb_build_object(
        'min_low',  e.min_low,
        'low_min',  r.low_min,
        'low_max',  r.low_max
    ) AS extra
FROM (
    SELECT
        id AS asset_id,
        MIN(low) AS min_low
    FROM cmc_price_histories7
    GROUP BY id
) e
LEFT JOIN cmc_price_ranges r
    ON r.asset_id = e.asset_id;
"""


# ---------------------------------------------------------------------------
# Test 3: price_range_high on cmc_price_histories7
# ---------------------------------------------------------------------------

SQL_TEST_PRICE_HIGH = """
INSERT INTO price_histories7_stats (
    table_name, test_name, asset_id,
    status, actual, expected, extra
)
SELECT
    'cmc_price_histories7' AS table_name,
    'price_range_high'     AS test_name,
    e.asset_id,
    CASE
        WHEN r.asset_id IS NULL THEN 'WARN'
        WHEN e.max_high < r.high_min OR e.max_high > r.high_max THEN 'FAIL'
        ELSE 'PASS'
    END AS status,
    e.max_high::NUMERIC                     AS actual,
    r.high_min::NUMERIC                     AS expected,
    jsonb_build_object(
        'max_high', e.max_high,
        'high_min', r.high_min,
        'high_max', r.high_max
    ) AS extra
FROM (
    SELECT
        id AS asset_id,
        MAX(high) AS max_high
    FROM cmc_price_histories7
    GROUP BY id
) e
LEFT JOIN cmc_price_ranges r
    ON r.asset_id = e.asset_id;
"""


# ---------------------------------------------------------------------------
# Helpers: engine + runner
# ---------------------------------------------------------------------------

def get_engine(db_url: Optional[str] = None):
    """
    Return a SQLAlchemy engine.

    If db_url is None, use TARGET_DB_URL from ta_lab2.config.
    """
    return create_engine(db_url or TARGET_DB_URL)


def run_all_tests(engine) -> None:
    """
    Run all cmc_price_histories7 tests in a single transaction.
    """
    with engine.begin() as conn:
        # Ensure helper tables exist
        conn.execute(text(DDL_STATS_TABLE))
        conn.execute(text(DDL_PRICE_RANGES))

        # Run tests
        conn.execute(text(SQL_TEST_BAR_COUNT))
        conn.execute(text(SQL_TEST_PRICE_LOW))
        conn.execute(text(SQL_TEST_PRICE_HIGH))


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(db_url: Optional[str] = None) -> None:
    """
    Main entrypoint for both CLI and programmatic use.

    Parameters
    ----------
    db_url : str, optional
        If provided, overrides TARGET_DB_URL from ta_lab2.config.
    """
    if db_url is None:
        parser = argparse.ArgumentParser(
            description="Run data quality stats for cmc_price_histories7."
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
    #   python -m ta_lab2.scripts.refresh_price_histories7_stats
    main()
