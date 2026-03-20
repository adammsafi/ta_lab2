from __future__ import annotations

r"""
refresh_features_stats.py

Stats runner for public.features.

Incremental behavior:
- Uses public.features_stats_state as watermark store
- Recomputes stats ONLY for impacted (id, tf) keys
  (impacted = any rows with updated_at > last watermark)
- TF-level tests only for impacted TFs
- Heartbeat updates updated_at even when no new data

Stats tests:
  1. pk_uniqueness_id_tf_ts        — no duplicate (id, tf, ts)
  2. tf_membership_in_dim_timeframe — every tf exists in dim_timeframe
  3. null_rate_key_columns         — NULL rates for critical columns per (id, tf)
  4. row_count_vs_bars             — feature rows should match bar rows per (id, tf)
  5. max_ts_lag_vs_bars            — freshness: max(ts) lag vs bars source

CLI:
  python -m ta_lab2.scripts.features.stats.refresh_features_stats
  python -m ta_lab2.scripts.features.stats.refresh_features_stats --full-refresh

Spyder:
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\features\stats\refresh_features_stats.py",
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


FEATURE_TABLE = "public.features"
STATS_TABLE = "public.features_stats"
STATE_TABLE = "public.features_stats_state"
BAR_TABLE = "public.price_bars_multi_tf"

# Key feature columns to check for NULLs.
# These are the most important downstream columns.
KEY_COLUMNS = [
    "close",
    "rsi_14",
    "atr_14",
    "macd_12_26",
    "bb_width_20",
    "adx_14",
    "vol_parkinson_20",
    "vol_gk_20",
    "ret_arith",
    "ret_log",
]


# ----------------------------
# Logging
# ----------------------------


def _setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("features_stats")
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
    last_updated_at  TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# ----------------------------
# Incremental helpers
# ----------------------------

DDL_TEMP_IMPACTED = """
CREATE TEMP TABLE IF NOT EXISTS _impacted_feat_keys (
    asset_id BIGINT  NOT NULL,
    tf       TEXT    NOT NULL
) ON COMMIT DROP;

TRUNCATE TABLE _impacted_feat_keys;
"""

SQL_MAX_UPDATED_AT = f"SELECT MAX(updated_at) FROM {FEATURE_TABLE};"

SQL_GET_STATE = f"""
SELECT last_updated_at
FROM {STATE_TABLE}
WHERE table_name = :table_name;
"""

SQL_TOUCH_STATE = f"""
INSERT INTO {STATE_TABLE}(table_name, last_updated_at, updated_at)
VALUES (:table_name, NULL, now())
ON CONFLICT (table_name)
DO UPDATE SET updated_at = now();
"""

SQL_SET_WATERMARK = f"""
INSERT INTO {STATE_TABLE}(table_name, last_updated_at, updated_at)
VALUES (:table_name, :last_updated_at, now())
ON CONFLICT (table_name)
DO UPDATE SET last_updated_at = EXCLUDED.last_updated_at,
              updated_at = EXCLUDED.updated_at;
"""

SQL_ALL_KEYS = f"""
SELECT DISTINCT id AS asset_id, tf
FROM {FEATURE_TABLE};
"""

SQL_IMPACTED_KEYS_SINCE = f"""
SELECT DISTINCT id AS asset_id, tf
FROM {FEATURE_TABLE}
WHERE updated_at > :last_updated_at;
"""


# ----------------------------
# Delete old stats
# ----------------------------

SQL_DELETE_KEYS = f"""
DELETE FROM {STATS_TABLE} s
USING _impacted_feat_keys k
WHERE s.table_name = :table_name
  AND s.asset_id = k.asset_id
  AND s.tf = k.tf;
"""

SQL_DELETE_TFS = f"""
DELETE FROM {STATS_TABLE}
WHERE table_name = :table_name
  AND tf IN (SELECT DISTINCT tf FROM _impacted_feat_keys)
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
        FROM {FEATURE_TABLE} f
        WHERE EXISTS (
            SELECT 1
            FROM _impacted_feat_keys k
            WHERE k.asset_id = f.id AND k.tf = f.tf
        )
        GROUP BY f.id, f.tf, f.ts, f.venue_id
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
FROM (SELECT DISTINCT tf FROM _impacted_feat_keys) t
LEFT JOIN public.dim_timeframe dt ON dt.tf = t.tf;
"""


# ----------------------------
# Tests (NULL rate for key columns)
# ----------------------------


def _build_null_rate_sql() -> str:
    """Build SQL to check NULL rates for key feature columns."""
    null_counts = ", ".join(
        f"SUM(CASE WHEN f.{col} IS NULL THEN 1 ELSE 0 END) AS n_{col}_null"
        for col in KEY_COLUMNS
    )
    return f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, status, actual, expected, extra
)
WITH counts AS (
    SELECT
        f.id AS asset_id,
        f.tf,
        COUNT(*) AS n_rows,
        {null_counts}
    FROM {FEATURE_TABLE} f
    JOIN _impacted_feat_keys k
      ON k.asset_id = f.id AND k.tf = f.tf
    GROUP BY f.id, f.tf
)
SELECT
    :table_name,
    'null_rate_key_columns',
    asset_id,
    tf,
    CASE
        WHEN ({" + ".join(f"n_{col}_null" for col in KEY_COLUMNS)}) = 0 THEN 'PASS'
        WHEN ({" + ".join(f"n_{col}_null" for col in KEY_COLUMNS)})::numeric / (n_rows * {len(KEY_COLUMNS)}) <= 0.20 THEN 'WARN'
        ELSE 'FAIL'
    END,
    ({" + ".join(f"n_{col}_null" for col in KEY_COLUMNS)})::numeric,
    0,
    jsonb_build_object(
        'n_rows', n_rows,
        {", ".join(f"'n_{col}_null', n_{col}_null" for col in KEY_COLUMNS)}
    )
FROM counts;
"""


SQL_TEST_NULL_RATE = _build_null_rate_sql()


# ----------------------------
# Tests (row count vs bars source)
# ----------------------------

SQL_TEST_ROWCOUNT_VS_BARS = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, status, actual, expected, extra
)
WITH feat_counts AS (
    SELECT
        f.id AS asset_id,
        f.tf,
        COUNT(*) AS n_feat
    FROM {FEATURE_TABLE} f
    JOIN _impacted_feat_keys k
      ON k.asset_id = f.id AND k.tf = f.tf
    GROUP BY f.id, f.tf
),
bar_counts AS (
    SELECT
        b.id AS asset_id,
        b.tf,
        COUNT(*) AS n_bars
    FROM {BAR_TABLE} b
    GROUP BY b.id, b.tf
),
joined AS (
    SELECT
        fc.asset_id,
        fc.tf,
        fc.n_feat,
        COALESCE(bc.n_bars, 0) AS n_bars
    FROM feat_counts fc
    LEFT JOIN bar_counts bc
      ON bc.asset_id = fc.asset_id AND bc.tf = fc.tf
)
SELECT
    :table_name,
    'row_count_vs_bars_canonical',
    asset_id,
    tf,
    CASE
        WHEN n_bars = 0 THEN 'WARN'
        WHEN abs(n_feat - n_bars) <= 2 THEN 'PASS'
        WHEN abs(n_feat - n_bars)::numeric / GREATEST(n_bars,1) <= 0.05 THEN 'WARN'
        ELSE 'FAIL'
    END,
    n_feat::numeric,
    n_bars::numeric,
    jsonb_build_object(
        'abs_diff', abs(n_feat - n_bars),
        'pct_diff', CASE WHEN n_bars = 0 THEN NULL
                         ELSE abs(n_feat - n_bars)::numeric / n_bars END
    )
FROM joined;
"""


# ----------------------------
# Tests (freshness — max_ts lag vs bars)
# ----------------------------

SQL_TEST_MAX_TS_LAG_VS_BARS = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, status, actual, expected, extra
)
WITH bar_max AS (
    SELECT
        id AS asset_id,
        tf,
        MAX("timestamp") AS max_bar_ts
    FROM {BAR_TABLE}
    GROUP BY id, tf
),
feat_max AS (
    SELECT
        k.asset_id,
        k.tf,
        MAX(f.ts) AS max_feat_ts
    FROM _impacted_feat_keys k
    JOIN {FEATURE_TABLE} f
      ON f.id = k.asset_id AND f.tf = k.tf
    GROUP BY k.asset_id, k.tf
),
joined AS (
    SELECT
        fm.asset_id,
        fm.tf,
        bm.max_bar_ts,
        fm.max_feat_ts,
        CASE
            WHEN bm.max_bar_ts IS NULL OR fm.max_feat_ts IS NULL THEN NULL
            ELSE (bm.max_bar_ts::date - fm.max_feat_ts::date)
        END AS lag_days
    FROM feat_max fm
    LEFT JOIN bar_max bm ON bm.asset_id = fm.asset_id AND bm.tf = fm.tf
)
SELECT
    :table_name,
    'max_ts_lag_vs_bars',
    asset_id,
    tf,
    CASE
        WHEN max_bar_ts IS NULL OR max_feat_ts IS NULL THEN 'FAIL'
        WHEN lag_days <= 1 THEN 'PASS'
        WHEN lag_days <= 3 THEN 'WARN'
        ELSE 'FAIL'
    END,
    lag_days::numeric,
    0,
    jsonb_build_object(
        'max_bar_ts', max_bar_ts,
        'max_feat_ts', max_feat_ts,
        'lag_days', lag_days
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
        max_upd = conn.execute(text(SQL_MAX_UPDATED_AT)).scalar()
        last_upd = conn.execute(
            text(SQL_GET_STATE), {"table_name": FEATURE_TABLE}
        ).scalar()

        if max_upd is None:
            logger.warning("Features table empty, nothing to do.")
            return

        # Heartbeat
        conn.execute(text(SQL_TOUCH_STATE), {"table_name": FEATURE_TABLE})

        # Incremental no-op
        if not full_refresh and last_upd is not None and max_upd <= last_upd:
            logger.info("No new updated data, skipping.")
            logger.info("features stats run complete.")
            return

        # Build impacted keys
        conn.execute(text(DDL_TEMP_IMPACTED))

        if full_refresh or last_upd is None:
            impacted = conn.execute(text(SQL_ALL_KEYS)).fetchall()
        else:
            impacted = conn.execute(
                text(SQL_IMPACTED_KEYS_SINCE),
                {"last_updated_at": last_upd},
            ).fetchall()

        if not impacted:
            logger.info("No impacted keys.")
            logger.info("features stats run complete.")
            return

        conn.execute(
            text(
                "INSERT INTO _impacted_feat_keys(asset_id, tf) VALUES (:asset_id, :tf)"
            ),
            [dict(r._mapping) for r in impacted],
        )

        logger.info("Impacted keys: %d", len(impacted))

        # Delete prior stats
        conn.execute(text(SQL_DELETE_KEYS), {"table_name": FEATURE_TABLE})
        conn.execute(text(SQL_DELETE_TFS), {"table_name": FEATURE_TABLE})
        conn.execute(text(SQL_DELETE_GLOBAL), {"table_name": FEATURE_TABLE})

        # Run tests
        logger.info("Running pk_uniqueness...")
        conn.execute(text(SQL_TEST_PK_UNIQUENESS), {"table_name": FEATURE_TABLE})

        logger.info("Running tf_membership...")
        conn.execute(text(SQL_TEST_TF_MEMBERSHIP), {"table_name": FEATURE_TABLE})

        logger.info("Running null_rate_key_columns...")
        conn.execute(text(SQL_TEST_NULL_RATE), {"table_name": FEATURE_TABLE})

        logger.info("Running row_count_vs_bars...")
        conn.execute(text(SQL_TEST_ROWCOUNT_VS_BARS), {"table_name": FEATURE_TABLE})

        logger.info("Running max_ts_lag_vs_bars...")
        conn.execute(text(SQL_TEST_MAX_TS_LAG_VS_BARS), {"table_name": FEATURE_TABLE})

        # Advance watermark
        conn.execute(
            text(SQL_SET_WATERMARK),
            {"table_name": FEATURE_TABLE, "last_updated_at": max_upd},
        )

    logger.info("features stats run complete.")


def main() -> None:
    p = argparse.ArgumentParser(description="Stats runner for features")
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--db-url")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    engine = get_engine(resolve_db_url(args.db_url))
    run(engine, args.full_refresh, args.log_level)


if __name__ == "__main__":
    main()
