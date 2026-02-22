from __future__ import annotations

r"""
refresh_price_bars_stats.py

Stats runner for public.cmc_price_bars_multi_tf.

Incremental behavior:
- Uses public.price_bars_multi_tf_stats_state as watermark store
- Recomputes stats ONLY for impacted (id, tf) keys
  (impacted = any rows with ingested_at > last watermark)
- TF-level tests only for impacted TFs
- Heartbeat updates updated_at even when no new data

Stats tests:
  1. pk_uniqueness_id_tf_ts       — no duplicate (id, tf, timestamp)
  2. tf_membership_in_dim_timeframe — every tf exists in dim_timeframe
  3. ohlc_consistency             — high >= low, high >= open/close, low <= open/close
  4. max_gap_canonical            — max gap between canonical closes vs tf_days_max
  5. row_count_vs_span            — actual canonical rows vs expected from date range
  6. max_ts_lag_vs_price          — freshness: max(timestamp) lag vs price_histories7

CLI:
  python -m ta_lab2.scripts.bars.stats.refresh_price_bars_stats
  python -m ta_lab2.scripts.bars.stats.refresh_price_bars_stats --full-refresh

Spyder:
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\bars\stats\refresh_price_bars_stats.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--full-refresh"
)
"""

import argparse
import logging
import sys

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.common_snapshot_contract import get_engine, resolve_db_url


BAR_TABLE = "public.cmc_price_bars_multi_tf"
STATS_TABLE = "public.price_bars_multi_tf_stats"
STATE_TABLE = "public.price_bars_multi_tf_stats_state"
PRICE_TABLE = "public.cmc_price_histories7"


# ----------------------------
# Logging
# ----------------------------


def _setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("price_bars_stats")
    if logger.handlers:
        return logger
    lvl = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(lvl)
    h = logging.StreamHandler(stream=sys.stdout)
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(h)
    logger.propagate = False
    return logger


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
CREATE TEMP TABLE IF NOT EXISTS _impacted_bar_keys (
    asset_id BIGINT  NOT NULL,
    tf       TEXT    NOT NULL
) ON COMMIT DROP;

TRUNCATE TABLE _impacted_bar_keys;
"""

SQL_MAX_INGESTED_AT = f"SELECT MAX(ingested_at) FROM {BAR_TABLE};"

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
SELECT DISTINCT id AS asset_id, tf
FROM {BAR_TABLE}
WHERE is_partial_end = FALSE;
"""

SQL_IMPACTED_KEYS_SINCE = f"""
SELECT DISTINCT id AS asset_id, tf
FROM {BAR_TABLE}
WHERE ingested_at > :last_ingested_at;
"""


# ----------------------------
# Delete old stats (latest-only)
# ----------------------------

SQL_DELETE_KEYS = f"""
DELETE FROM {STATS_TABLE} s
USING _impacted_bar_keys k
WHERE s.table_name = :table_name
  AND s.asset_id = k.asset_id
  AND s.tf = k.tf;
"""

SQL_DELETE_TFS = f"""
DELETE FROM {STATS_TABLE}
WHERE table_name = :table_name
  AND tf IN (SELECT DISTINCT tf FROM _impacted_bar_keys)
  AND asset_id IS NULL;
"""

SQL_DELETE_GLOBAL = f"""
DELETE FROM {STATS_TABLE}
WHERE table_name = :table_name
  AND asset_id IS NULL
  AND tf IS NULL;
"""


# ----------------------------
# Tests (global uniqueness)
# ----------------------------

SQL_TEST_PK_UNIQUENESS = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, status, actual, expected, extra
)
WITH d AS (
    SELECT
        SUM(cnt - 1) AS n_dupe_rows,
        COUNT(*) FILTER (WHERE cnt > 1) AS n_dupe_groups
    FROM (
        SELECT COUNT(*) AS cnt
        FROM {BAR_TABLE} b
        WHERE EXISTS (
            SELECT 1
            FROM _impacted_bar_keys k
            WHERE k.asset_id = b.id AND k.tf = b.tf
        )
        GROUP BY b.id, b.tf, b."timestamp"
    ) x
)
SELECT
    :table_name,
    'pk_uniqueness_id_tf_ts',
    CASE WHEN COALESCE(n_dupe_rows,0) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COALESCE(n_dupe_rows,0),
    0,
    jsonb_build_object('n_dupe_groups', COALESCE(n_dupe_groups,0))
FROM d;
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
FROM (SELECT DISTINCT tf FROM _impacted_bar_keys) t
LEFT JOIN public.dim_timeframe dt ON dt.tf = t.tf;
"""


# ----------------------------
# Tests (OHLC consistency)
# ----------------------------

SQL_TEST_OHLC_CONSISTENCY = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, status, actual, expected, extra
)
WITH violations AS (
    SELECT
        b.id AS asset_id,
        b.tf,
        COUNT(*) AS n_rows,
        SUM(CASE WHEN b.high < b.low THEN 1 ELSE 0 END) AS n_high_lt_low,
        SUM(CASE WHEN b.high < b.open THEN 1 ELSE 0 END) AS n_high_lt_open,
        SUM(CASE WHEN b.high < b.close THEN 1 ELSE 0 END) AS n_high_lt_close,
        SUM(CASE WHEN b.low > b.open THEN 1 ELSE 0 END) AS n_low_gt_open,
        SUM(CASE WHEN b.low > b.close THEN 1 ELSE 0 END) AS n_low_gt_close
    FROM {BAR_TABLE} b
    JOIN _impacted_bar_keys k
      ON k.asset_id = b.id AND k.tf = b.tf
    GROUP BY b.id, b.tf
)
SELECT
    :table_name,
    'ohlc_consistency',
    asset_id,
    tf,
    CASE
        WHEN (n_high_lt_low + n_high_lt_open + n_high_lt_close
              + n_low_gt_open + n_low_gt_close) = 0 THEN 'PASS'
        ELSE 'FAIL'
    END,
    (n_high_lt_low + n_high_lt_open + n_high_lt_close
     + n_low_gt_open + n_low_gt_close)::numeric,
    0,
    jsonb_build_object(
        'n_rows', n_rows,
        'n_high_lt_low', n_high_lt_low,
        'n_high_lt_open', n_high_lt_open,
        'n_high_lt_close', n_high_lt_close,
        'n_low_gt_open', n_low_gt_open,
        'n_low_gt_close', n_low_gt_close
    )
FROM violations;
"""


# ----------------------------
# Tests (max gap — canonical closes)
# ----------------------------

SQL_TEST_MAX_GAP_CANONICAL = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, status, actual, expected, extra
)
WITH ordered AS (
    SELECT
        b.id AS asset_id,
        b.tf,
        b."timestamp"::date AS d,
        LAG(b."timestamp"::date) OVER (
            PARTITION BY b.id, b.tf ORDER BY b."timestamp"
        ) AS prev_d
    FROM {BAR_TABLE} b
    JOIN _impacted_bar_keys k
      ON k.asset_id = b.id AND k.tf = b.tf
    WHERE b.is_partial_end = FALSE
),
gaps AS (
    SELECT
        asset_id, tf,
        MAX(CASE WHEN prev_d IS NULL THEN 0 ELSE (d - prev_d) END) AS max_gap
    FROM ordered
    GROUP BY asset_id, tf
)
SELECT
    :table_name,
    'max_gap_canonical_vs_tf_days',
    g.asset_id,
    g.tf,
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
# Tests (row count vs span — canonical only)
# ----------------------------

SQL_TEST_ROWCOUNT_VS_SPAN = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, status, actual, expected, extra
)
WITH series AS (
    SELECT
        b.id AS asset_id,
        b.tf,
        COUNT(*) AS n_rows,
        MIN(b."timestamp"::date) AS min_d,
        MAX(b."timestamp"::date) AS max_d
    FROM {BAR_TABLE} b
    JOIN _impacted_bar_keys k
      ON k.asset_id = b.id AND k.tf = b.tf
    WHERE b.is_partial_end = FALSE
    GROUP BY b.id, b.tf
),
joined AS (
    SELECT
        s.*,
        dt.tf_days_nominal
    FROM series s
    LEFT JOIN public.dim_timeframe dt ON dt.tf = s.tf
),
scored AS (
    SELECT
        asset_id, tf,
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
    'row_count_vs_span_canonical',
    asset_id,
    tf,
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
        'abs_diff', CASE WHEN expected_rows IS NULL THEN NULL
                         ELSE abs(n_rows - expected_rows) END,
        'pct_diff', CASE WHEN expected_rows IS NULL OR expected_rows=0 THEN NULL
                         ELSE (abs(n_rows - expected_rows) / expected_rows) END
    )
FROM scored;
"""


# ----------------------------
# Tests (freshness — max_ts lag vs price source)
# ----------------------------

SQL_TEST_MAX_TS_LAG_VS_PRICE = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, status, actual, expected, extra
)
WITH price_max AS (
    SELECT
        id AS asset_id,
        MAX("timestamp") AS price_max_ts
    FROM {PRICE_TABLE}
    GROUP BY id
),
bar_max AS (
    SELECT
        k.asset_id,
        k.tf,
        MAX(b."timestamp") AS max_bar_ts
    FROM _impacted_bar_keys k
    JOIN {BAR_TABLE} b
      ON b.id = k.asset_id AND b.tf = k.tf
    WHERE b.is_partial_end = FALSE
    GROUP BY k.asset_id, k.tf
),
joined AS (
    SELECT
        bm.asset_id,
        bm.tf,
        p.price_max_ts,
        bm.max_bar_ts,
        dt.tf_days_nominal,
        CASE
            WHEN p.price_max_ts IS NULL OR bm.max_bar_ts IS NULL THEN NULL
            ELSE (p.price_max_ts::date - bm.max_bar_ts::date)
        END AS lag_days
    FROM bar_max bm
    LEFT JOIN price_max p ON p.asset_id = bm.asset_id
    LEFT JOIN public.dim_timeframe dt ON dt.tf = bm.tf
)
SELECT
    :table_name,
    'max_ts_lag_vs_price',
    asset_id,
    tf,
    CASE
        WHEN price_max_ts IS NULL OR max_bar_ts IS NULL THEN 'FAIL'
        WHEN lag_days <= COALESCE(tf_days_nominal, 1) + 1 THEN 'PASS'
        WHEN lag_days <= COALESCE(tf_days_nominal, 1) * 3  THEN 'WARN'
        ELSE 'FAIL'
    END,
    lag_days::numeric,
    0,
    jsonb_build_object(
        'price_max_ts', price_max_ts,
        'max_bar_ts',   max_bar_ts,
        'lag_days',     lag_days,
        'tf_days_nominal', tf_days_nominal
    )
FROM joined;
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
        last_ing = conn.execute(text(SQL_GET_STATE), {"table_name": BAR_TABLE}).scalar()

        if max_ing is None:
            logger.warning("Bar table empty, nothing to do.")
            return

        # Heartbeat
        conn.execute(text(SQL_TOUCH_STATE), {"table_name": BAR_TABLE})

        # Incremental no-op
        if not full_refresh and last_ing is not None and max_ing <= last_ing:
            logger.info("No new ingested data, skipping.")
            logger.info("price_bars stats run complete.")
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
            logger.info("price_bars stats run complete.")
            return

        conn.execute(
            text(
                "INSERT INTO _impacted_bar_keys(asset_id, tf) "
                "VALUES (:asset_id, :tf)"
            ),
            [dict(r._mapping) for r in impacted],
        )

        logger.info("Impacted keys: %d", len(impacted))

        # Delete prior stats for these keys/TFs + global rows
        conn.execute(text(SQL_DELETE_KEYS), {"table_name": BAR_TABLE})
        conn.execute(text(SQL_DELETE_TFS), {"table_name": BAR_TABLE})
        conn.execute(text(SQL_DELETE_GLOBAL), {"table_name": BAR_TABLE})

        # Run tests
        logger.info("Running pk_uniqueness...")
        conn.execute(text(SQL_TEST_PK_UNIQUENESS), {"table_name": BAR_TABLE})

        logger.info("Running tf_membership...")
        conn.execute(text(SQL_TEST_TF_MEMBERSHIP), {"table_name": BAR_TABLE})

        logger.info("Running ohlc_consistency...")
        conn.execute(text(SQL_TEST_OHLC_CONSISTENCY), {"table_name": BAR_TABLE})

        logger.info("Running max_gap_canonical...")
        conn.execute(text(SQL_TEST_MAX_GAP_CANONICAL), {"table_name": BAR_TABLE})

        logger.info("Running row_count_vs_span...")
        conn.execute(text(SQL_TEST_ROWCOUNT_VS_SPAN), {"table_name": BAR_TABLE})

        logger.info("Running max_ts_lag_vs_price...")
        conn.execute(text(SQL_TEST_MAX_TS_LAG_VS_PRICE), {"table_name": BAR_TABLE})

        # Advance watermark
        conn.execute(
            text(SQL_SET_WATERMARK),
            {"table_name": BAR_TABLE, "last_ingested_at": max_ing},
        )

    logger.info("price_bars stats run complete.")


def main() -> None:
    p = argparse.ArgumentParser(description="Stats runner for cmc_price_bars_multi_tf")
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--db-url")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    engine = get_engine(resolve_db_url(args.db_url))
    run(engine, args.full_refresh, args.log_level)


if __name__ == "__main__":
    main()
