from __future__ import annotations

r"""
refresh_ema_multi_tf_v2_stats.py

Stats runner for public.cmc_ema_multi_tf_v2.

Incremental behavior:
- Uses public.ema_multi_tf_v2_stats_state as watermark store
- Recomputes stats ONLY for impacted (id, tf, period) keys
- TF-level tests only for impacted TFs
- Heartbeat updates updated_at even when no new data


Spyder Runfile() examples:
runfile(
    r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\stats\multi_tf_v2\refresh_ema_multi_tf_v2_stats.py",
    wdir=r"C:\Users\asafi\Downloads\ta_lab2"
)

Full refresh:
runfile(
    r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\stats\multi_tf_v2\refresh_ema_multi_tf_v2_stats.py",
    wdir=r"C:\Users\asafi\Downloads\ta_lab2",
    args="--full-refresh"
)

"""

import argparse
import logging
import sys
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.config import TARGET_DB_URL


EMA_TABLE = "public.cmc_ema_multi_tf_v2"
STATS_TABLE = "public.ema_multi_tf_v2_stats"
STATE_TABLE = "public.ema_multi_tf_v2_stats_state"


# ----------------------------
# Logging
# ----------------------------

def _setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("ema_v2_stats")
    if logger.handlers:
        return logger
    lvl = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(lvl)
    h = logging.StreamHandler(stream=sys.stdout)
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(h)
    logger.propagate = False
    return logger


def get_engine(db_url: Optional[str] = None) -> Engine:
    return create_engine(db_url or TARGET_DB_URL)


# ----------------------------
# DDL
# ----------------------------

DDL_CREATE_STATS = f"""
CREATE TABLE IF NOT EXISTS {STATS_TABLE} (
    stat_id     BIGSERIAL PRIMARY KEY,
    table_name  TEXT NOT NULL,
    test_name   TEXT NOT NULL,

    asset_id    BIGINT,
    tf          TEXT,
    period      INTEGER,

    status      TEXT NOT NULL,        -- PASS/WARN/FAIL
    actual      NUMERIC,
    expected    NUMERIC,
    extra       JSONB,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

DDL_CREATE_STATE = f"""
CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
    table_name       TEXT PRIMARY KEY,
    last_ingested_at TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# ----------------------------
# Incremental helpers
# ----------------------------

DDL_TEMP_IMPACTED = """
CREATE TEMP TABLE IF NOT EXISTS _impacted_keys (
    asset_id BIGINT  NOT NULL,
    tf       TEXT    NOT NULL,
    period   INTEGER NOT NULL
) ON COMMIT DROP;

TRUNCATE TABLE _impacted_keys;
"""

SQL_MAX_INGESTED_AT = f"SELECT MAX(ingested_at) FROM {EMA_TABLE};"

SQL_GET_STATE = f"""
SELECT last_ingested_at
FROM {STATE_TABLE}
WHERE table_name = :table_name;
"""

SQL_TOUCH_STATE = f"""
INSERT INTO {STATE_TABLE}(table_name, last_ingested_at, updated_at)
VALUES (:table_name, NULL, now())
ON CONFLICT (table_name)
DO UPDATE SET updated_at = now();
"""

SQL_SET_WATERMARK = f"""
INSERT INTO {STATE_TABLE}(table_name, last_ingested_at, updated_at)
VALUES (:table_name, :last_ingested_at, now())
ON CONFLICT (table_name)
DO UPDATE SET last_ingested_at = EXCLUDED.last_ingested_at,
              updated_at = EXCLUDED.updated_at;
"""

SQL_ALL_KEYS = f"""
SELECT DISTINCT id AS asset_id, tf, period
FROM {EMA_TABLE}
WHERE roll = false;
"""

SQL_IMPACTED_KEYS_SINCE = f"""
SELECT DISTINCT id AS asset_id, tf, period
FROM {EMA_TABLE}
WHERE ingested_at > :last_ingested_at;
"""


# ----------------------------
# Delete old stats (latest-only)
# ----------------------------

SQL_DELETE_KEYS = f"""
DELETE FROM {STATS_TABLE} s
USING _impacted_keys k
WHERE s.table_name = :table_name
  AND s.asset_id = k.asset_id
  AND s.tf = k.tf
  AND s.period = k.period;
"""

SQL_DELETE_TFS = f"""
DELETE FROM {STATS_TABLE}
WHERE table_name = :table_name
  AND tf IN (SELECT DISTINCT tf FROM _impacted_keys)
  AND asset_id IS NULL;
"""

SQL_DELETE_GLOBAL = f"""
DELETE FROM {STATS_TABLE}
WHERE table_name = :table_name
  AND asset_id IS NULL
  AND tf IS NULL
  AND period IS NULL;
"""


# ----------------------------
# Tests (TF-level)
# ----------------------------

SQL_TEST_TF_MEMBERSHIP = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, tf, status, actual, expected, extra
)
SELECT
    :table_name,
    'tf_membership_in_dim_timeframe',
    t.tf,
    CASE WHEN dt.tf IS NOT NULL THEN 'PASS' ELSE 'FAIL' END,
    CASE WHEN dt.tf IS NOT NULL THEN 0 ELSE 1 END,
    0,
    jsonb_build_object('missing', dt.tf IS NULL)
FROM (SELECT DISTINCT tf FROM _impacted_keys) t
LEFT JOIN public.dim_timeframe dt ON dt.tf = t.tf;
"""

SQL_TEST_TF_DAYS_CONSTANT = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, tf, status, actual, expected, extra
)
SELECT
    :table_name,
    'tf_days_constant_within_tf',
    tf,
    CASE WHEN MIN(tf_days) = MAX(tf_days) THEN 'PASS' ELSE 'FAIL' END,
    (MAX(tf_days) - MIN(tf_days)),
    0,
    jsonb_build_object(
        'min_tf_days', MIN(tf_days),
        'max_tf_days', MAX(tf_days)
    )
FROM {EMA_TABLE}
WHERE tf IN (SELECT DISTINCT tf FROM _impacted_keys)
GROUP BY tf;
"""


# ----------------------------
# Tests (key-level, canonical spacing)
# ----------------------------

SQL_TEST_CANONICAL_MAX_GAP = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, period, status, actual, expected, extra
)
WITH ordered AS (
    SELECT
        e.id AS asset_id,
        e.tf,
        e.period,
        e.ts::date AS d,
        LAG(e.ts::date) OVER (PARTITION BY e.id, e.tf, e.period ORDER BY e.ts) AS prev_d
    FROM {EMA_TABLE} e
    JOIN _impacted_keys k
      ON k.asset_id = e.id AND k.tf = e.tf AND k.period = e.period
    WHERE e.roll = false
),
gaps AS (
    SELECT
        asset_id, tf, period,
        MAX(CASE WHEN prev_d IS NULL THEN 0 ELSE (d - prev_d) END) AS max_gap
    FROM ordered
    GROUP BY asset_id, tf, period
)
SELECT
    :table_name,
    'canonical_max_gap_vs_dim_timeframe',
    g.asset_id,
    g.tf,
    g.period,
    CASE
        WHEN dt.tf_days_max IS NULL THEN 'WARN'
        WHEN g.max_gap <= dt.tf_days_max THEN 'PASS'
        WHEN g.max_gap <= dt.tf_days_max + 2 THEN 'WARN'
        ELSE 'FAIL'
    END,
    g.max_gap,
    dt.tf_days_max,
    jsonb_build_object(
        'tf_days_max', dt.tf_days_max,
        'tf_days_nominal', dt.tf_days_nominal
    )
FROM gaps g
LEFT JOIN public.dim_timeframe dt ON dt.tf = g.tf;
"""


# ----------------------------
# Tests (global uniqueness)
# ----------------------------

SQL_TEST_KEY_UNIQUENESS_TS = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, status, actual, expected, extra
)
WITH d AS (
    SELECT
        SUM(cnt - 1) AS n_dupe_rows,
        COUNT(*) FILTER (WHERE cnt > 1) AS n_dupe_groups
    FROM (
        SELECT COUNT(*) AS cnt
        FROM {EMA_TABLE} e
        WHERE EXISTS (
            SELECT 1
            FROM _impacted_keys k
            WHERE k.asset_id = e.id AND k.tf = e.tf AND k.period = e.period
        )
        GROUP BY e.id, e.tf, e.period, e.ts
    ) x
)
SELECT
    :table_name,
    'key_uniqueness_id_tf_period_ts',
    CASE WHEN COALESCE(n_dupe_rows,0) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COALESCE(n_dupe_rows,0),
    0,
    jsonb_build_object('n_dupe_groups', COALESCE(n_dupe_groups,0))
FROM d;
"""

SQL_TEST_KEY_UNIQUENESS_DATE = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, status, actual, expected, extra
)
WITH d AS (
    SELECT
        SUM(cnt - 1) AS n_dupe_rows,
        COUNT(*) FILTER (WHERE cnt > 1) AS n_dupe_groups
    FROM (
        SELECT COUNT(*) AS cnt
        FROM {EMA_TABLE} e
        WHERE EXISTS (
            SELECT 1
            FROM _impacted_keys k
            WHERE k.asset_id = e.id AND k.tf = e.tf AND k.period = e.period
        )
        GROUP BY e.id, e.tf, e.period, (e.ts::date)
    ) x
)
SELECT
    :table_name,
    'key_uniqueness_id_tf_period_ts_date',
    CASE WHEN COALESCE(n_dupe_rows,0) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COALESCE(n_dupe_rows,0),
    0,
    jsonb_build_object('n_dupe_groups', COALESCE(n_dupe_groups,0))
FROM d;
"""


# ----------------------------
# Tests (rowcount sanity)
# ----------------------------

SQL_TEST_CANONICAL_ROWCOUNT_NONZERO = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, period, status, actual, expected, extra
)
SELECT
    :table_name,
    'canonical_rowcount_nonzero',
    k.asset_id,
    k.tf,
    k.period,
    CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END,
    COUNT(*),
    1,
    NULL
FROM _impacted_keys k
LEFT JOIN {EMA_TABLE} e
  ON e.id = k.asset_id AND e.tf = k.tf AND e.period = k.period
 AND e.roll = false
GROUP BY k.asset_id, k.tf, k.period;
"""

SQL_TEST_CANONICAL_ROWCOUNT_VS_EXPECTED_FROM_RANGE = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, period, status, actual, expected, extra
)
WITH canon AS (
    SELECT
        e.id AS asset_id,
        e.tf,
        e.period,
        COUNT(*) AS n_rows,
        MIN(e.ts::date) AS min_d,
        MAX(e.ts::date) AS max_d
    FROM {EMA_TABLE} e
    JOIN _impacted_keys k
      ON k.asset_id = e.id AND k.tf = e.tf AND k.period = e.period
    WHERE e.roll = false
    GROUP BY e.id, e.tf, e.period
),
joined AS (
    SELECT
        c.*,
        dt.tf_days_nominal
    FROM canon c
    LEFT JOIN public.dim_timeframe dt ON dt.tf = c.tf
),
scored AS (
    SELECT
        asset_id, tf, period,
        n_rows,
        min_d, max_d,
        tf_days_nominal,
        CASE
            WHEN tf_days_nominal IS NULL OR tf_days_nominal <= 0 THEN NULL
            ELSE ( (max_d - min_d) / tf_days_nominal )::numeric + 1
        END AS expected_rows
    FROM joined
)
SELECT
    :table_name,
    'canonical_rowcount_vs_expected_from_range',
    asset_id,
    tf,
    period,
    CASE
        WHEN expected_rows IS NULL THEN 'WARN'
        WHEN expected_rows = 0 THEN 'WARN'
        WHEN abs(n_rows - expected_rows) <= 2 THEN 'PASS'
        WHEN (abs(n_rows - expected_rows) / expected_rows) <= 0.10 THEN 'WARN'
        ELSE 'FAIL'
    END,
    n_rows::numeric,
    expected_rows,
    jsonb_build_object(
        'min_date', min_d,
        'max_date', max_d,
        'tf_days_nominal', tf_days_nominal,
        'abs_diff', CASE WHEN expected_rows IS NULL THEN NULL ELSE abs(n_rows - expected_rows) END,
        'pct_diff', CASE WHEN expected_rows IS NULL OR expected_rows=0 THEN NULL ELSE (abs(n_rows - expected_rows) / expected_rows) END
    )
FROM scored;
"""


# ----------------------------
# Tests (roll distribution)
# ----------------------------

SQL_TEST_ROLL_DISTRIBUTION_OVERALL = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, status, actual, expected, extra
)
WITH x AS (
    SELECT
        COUNT(*) FILTER (WHERE roll = true)  AS n_roll_true,
        COUNT(*) FILTER (WHERE roll = false) AS n_roll_false,
        COUNT(*) AS n_total
    FROM {EMA_TABLE} e
    WHERE EXISTS (
        SELECT 1
        FROM _impacted_keys k
        WHERE k.asset_id = e.id AND k.tf = e.tf AND k.period = e.period
    )
)
SELECT
    :table_name,
    'roll_distribution_overall',
    CASE
        WHEN n_total = 0 THEN 'WARN'
        WHEN n_roll_false = 0 THEN 'WARN'
        ELSE 'PASS'
    END,
    n_total::numeric,
    NULL,
    jsonb_build_object(
        'n_total', n_total,
        'n_roll_true', n_roll_true,
        'n_roll_false', n_roll_false,
        'pct_roll_true', CASE WHEN n_total=0 THEN NULL ELSE (n_roll_true::numeric / n_total) END
    )
FROM x;
"""

SQL_TEST_ROLL_FALSE_PRESENCE_PER_KEY = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, period, status, actual, expected, extra
)
WITH counts AS (
    SELECT
        k.asset_id, k.tf, k.period,
        COUNT(*) FILTER (WHERE e.roll = false) AS n_roll_false,
        COUNT(*) AS n_total
    FROM _impacted_keys k
    LEFT JOIN {EMA_TABLE} e
      ON e.id = k.asset_id AND e.tf = k.tf AND e.period = k.period
    GROUP BY k.asset_id, k.tf, k.period
)
SELECT
    :table_name,
    'roll_false_presence_per_key',
    asset_id,
    tf,
    period,
    CASE WHEN n_roll_false > 0 THEN 'PASS' ELSE 'FAIL' END,
    n_roll_false::numeric,
    1,
    jsonb_build_object('n_total', n_total)
FROM counts;
"""


# ----------------------------
# Runner
# ----------------------------

def run(engine: Engine, full_refresh: bool, log_level: str) -> None:
    logger = _setup_logging(log_level)

    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_STATS))
        conn.execute(text(DDL_CREATE_STATE))

    with engine.begin() as conn:
        max_ing = conn.execute(text(SQL_MAX_INGESTED_AT)).scalar()
        last_ing = conn.execute(text(SQL_GET_STATE), {"table_name": EMA_TABLE}).scalar()

        if max_ing is None:
            logger.warning("EMA table empty, nothing to do.")
            return

        # Heartbeat
        conn.execute(text(SQL_TOUCH_STATE), {"table_name": EMA_TABLE})

        # Incremental no-op
        if not full_refresh and last_ing is not None and max_ing <= last_ing:
            logger.info("No new ingested data, skipping.")
            logger.info("v2 stats run complete.")
            return

        # Build impacted keys
        conn.execute(text(DDL_TEMP_IMPACTED))

        if full_refresh or last_ing is None:
            impacted = conn.execute(text(SQL_ALL_KEYS)).fetchall()
        else:
            impacted = conn.execute(
                text(SQL_IMPACTED_KEYS_SINCE),
                {"last_ingested_at": last_ing},
            ).fetchall()

        if not impacted:
            logger.info("No impacted keys.")
            logger.info("v2 stats run complete.")
            return

        conn.execute(
            text("INSERT INTO _impacted_keys(asset_id, tf, period) VALUES (:asset_id, :tf, :period)"),
            [dict(r._mapping) for r in impacted],
        )

        # Delete prior stats for these keys/TFs + global rows
        conn.execute(text(SQL_DELETE_KEYS), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_DELETE_TFS), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_DELETE_GLOBAL), {"table_name": EMA_TABLE})

        # Run tests (order: global, TF-level, key-level)
        conn.execute(text(SQL_TEST_KEY_UNIQUENESS_TS), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_TEST_KEY_UNIQUENESS_DATE), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_TEST_ROLL_DISTRIBUTION_OVERALL), {"table_name": EMA_TABLE})

        conn.execute(text(SQL_TEST_TF_MEMBERSHIP), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_TEST_TF_DAYS_CONSTANT), {"table_name": EMA_TABLE})

        conn.execute(text(SQL_TEST_ROLL_FALSE_PRESENCE_PER_KEY), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_TEST_CANONICAL_ROWCOUNT_NONZERO), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_TEST_CANONICAL_ROWCOUNT_VS_EXPECTED_FROM_RANGE), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_TEST_CANONICAL_MAX_GAP), {"table_name": EMA_TABLE})

        # Advance watermark only after successful test writes
        conn.execute(
            text(SQL_SET_WATERMARK),
            {"table_name": EMA_TABLE, "last_ingested_at": max_ing},
        )

    logger.info("v2 stats run complete.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--db-url")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    engine = get_engine(args.db_url)
    run(engine, args.full_refresh, args.log_level)


if __name__ == "__main__":
    main()
