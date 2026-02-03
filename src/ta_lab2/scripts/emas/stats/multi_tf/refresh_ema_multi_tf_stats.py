from __future__ import annotations

r"""
refresh_ema_multi_tf_stats.py

Stats runner for public.cmc_ema_multi_tf.

Incremental behavior:
- Uses public.ema_multi_tf_stats_state as watermark store
- Recomputes stats ONLY for impacted (id, tf, period) keys (impacted = any rows with ingested_at > last watermark)
- TF-level tests only for impacted TFs
- Heartbeat updates updated_at even when no new data

Design assumptions (public.cmc_ema_multi_tf) — SYNTHESIS:
- roll=false = canonical closes for TF cadence
- roll=true  = preview points on the daily grid between canonical closes, BUT the EMA builder
  may also emit preview points beyond the last canonical close (forward-filled ema_prev_bar).
  Therefore, preview validation MUST compare preview counts inside the canonical window only.

Expected preview count for a key is derived from price_histories7 daily bars:

    expected_preview = n_daily_in_[min_canon_date..max_canon_date] - n_canonical_in_[min_canon..max_canon]

SYNTHESIS RULES:
- Daily count uses DATE-bounded range for robustness to timestamp basis mismatches
  (midnight vs EOD vs microsecond offsets): p."timestamp"::date between [min_canon_d..max_canon_d]
- Preview count is bounded to the canonical TS window to avoid false failures when preview extends
  beyond last canonical close: e.ts between [min_canon_ts..max_canon_ts]

Spyder Runfile() examples:
runfile(
    r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\stats\multi_tf\refresh_ema_multi_tf_stats.py",
    wdir=r"C:\Users\asafi\Downloads\ta_lab2"
)

Full refresh:
runfile(
    r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\stats\multi_tf\refresh_ema_multi_tf_stats.py",
    wdir=r"C:\Users\asafi\Downloads\ta_lab2",
    args="--full-refresh"
)
"""

import argparse
import logging
import sys

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
)


EMA_TABLE = "public.cmc_ema_multi_tf"
STATS_TABLE = "public.ema_multi_tf_stats"
STATE_TABLE = "public.ema_multi_tf_stats_state"
PRICE_TABLE = "public.cmc_price_histories7"


# ----------------------------
# Logging
# ----------------------------


def _setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("ema_multi_tf_stats")
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
    'ema_multi_tf_key_uniqueness_id_tf_period_ts',
    CASE WHEN COALESCE(n_dupe_rows,0) = 0 THEN 'PASS' ELSE 'FAIL' END,
    COALESCE(n_dupe_rows,0),
    0,
    jsonb_build_object('n_dupe_groups', COALESCE(n_dupe_groups,0))
FROM d;
"""


# ----------------------------
# Tests (max gap)
# ----------------------------

SQL_TEST_MAX_GAP_ROLL_FALSE = f"""
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
    'ema_multi_tf_max_gap_vs_tf_days_roll_false',
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

SQL_TEST_MAX_GAP_ROLL_TRUE = f"""
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
    WHERE e.roll = true
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
    'ema_multi_tf_max_gap_vs_tf_days_roll_true',
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
        'tf_days_nominal', dt.tf_days_nominal,
        'note', 'roll=true bounded by tf_days_max; not daily'
    )
FROM gaps g
LEFT JOIN public.dim_timeframe dt ON dt.tf = g.tf;
"""


# ----------------------------
# Tests (rowcount vs span) — roll=false only
# ----------------------------

_SQL_EXPECTED_FROM_RANGE_TEMPLATE = r"""
WITH series AS (
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
    WHERE e.roll = {ROLL_FLAG}
    GROUP BY e.id, e.tf, e.period
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
    asset_id,
    tf,
    period,
    n_rows::numeric AS actual_rows,
    expected_rows,
    min_d,
    max_d,
    tf_days_nominal
FROM scored
"""

SQL_TEST_ROWCOUNT_VS_SPAN_ROLL_FALSE = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, period, status, actual, expected, extra
)
WITH base AS (
{_SQL_EXPECTED_FROM_RANGE_TEMPLATE.format(EMA_TABLE=EMA_TABLE, ROLL_FLAG='false')}
)
SELECT
    :table_name,
    'ema_multi_tf_row_count_vs_span_roll_false',
    asset_id,
    tf,
    period,
    CASE
        WHEN expected_rows IS NULL THEN 'WARN'
        WHEN expected_rows = 0 THEN 'WARN'
        WHEN abs(actual_rows - expected_rows) <= 2 THEN 'PASS'
        WHEN (abs(actual_rows - expected_rows) / expected_rows) <= 0.10 THEN 'WARN'
        ELSE 'FAIL'
    END,
    actual_rows,
    expected_rows,
    jsonb_build_object(
        'min_date', min_d,
        'max_date', max_d,
        'tf_days_nominal', tf_days_nominal,
        'abs_diff', CASE WHEN expected_rows IS NULL THEN NULL ELSE abs(actual_rows - expected_rows) END,
        'pct_diff', CASE WHEN expected_rows IS NULL OR expected_rows=0 THEN NULL ELSE (abs(actual_rows - expected_rows) / expected_rows) END
    )
FROM base;
"""


# ----------------------------
# Tests (preview expected) — SYNTHESIS
# - Daily counts: DATE-bounded for robustness
# - Preview counts: bounded to canonical TS window (prevents false FAIL when preview extends beyond last canon)
# ----------------------------

SQL_TEST_PREVIEW_ROWCOUNT_VS_EXPECTED = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, period, status, actual, expected, extra
)
WITH canon_ranges AS (
    SELECT
        k.asset_id,
        k.tf,
        k.period,
        MIN(e.ts)       AS min_canon_ts,
        MAX(e.ts)       AS max_canon_ts,
        MIN(e.ts::date) AS min_canon_d,
        MAX(e.ts::date) AS max_canon_d,
        COUNT(*)        AS n_canon
    FROM _impacted_keys k
    JOIN {EMA_TABLE} e
      ON e.id = k.asset_id AND e.tf = k.tf AND e.period = k.period
    WHERE e.roll = false
    GROUP BY 1,2,3
),
daily_counts AS (
    SELECT
        r.asset_id, r.tf, r.period,
        COUNT(*) AS n_daily
    FROM canon_ranges r
    JOIN {PRICE_TABLE} p
      ON p.id = r.asset_id
     AND p."timestamp"::date >= r.min_canon_d
     AND p."timestamp"::date <= r.max_canon_d
    GROUP BY 1,2,3
),
preview_counts AS (
    SELECT
        r.asset_id, r.tf, r.period,
        COUNT(e.*) AS n_preview
    FROM canon_ranges r
    LEFT JOIN {EMA_TABLE} e
      ON e.id = r.asset_id
     AND e.tf = r.tf
     AND e.period = r.period
     AND e.roll = true
     AND e.ts >= r.min_canon_ts
     AND e.ts <= r.max_canon_ts
    GROUP BY 1,2,3
),
scored AS (
    SELECT
        r.asset_id,
        r.tf,
        r.period,
        COALESCE(p.n_preview,0)::numeric AS actual_preview,
        (d.n_daily - r.n_canon)::numeric AS expected_preview,
        r.n_canon,
        d.n_daily,
        r.min_canon_ts,
        r.max_canon_ts,
        r.min_canon_d,
        r.max_canon_d,
        abs(COALESCE(p.n_preview,0)::numeric - (d.n_daily - r.n_canon)::numeric) AS abs_diff,
        CASE
          WHEN (d.n_daily - r.n_canon) <= 0 THEN NULL
          ELSE abs(COALESCE(p.n_preview,0)::numeric - (d.n_daily - r.n_canon)::numeric)
               / (d.n_daily - r.n_canon)::numeric
        END AS pct_diff
    FROM canon_ranges r
    JOIN daily_counts d
      ON d.asset_id=r.asset_id AND d.tf=r.tf AND d.period=r.period
    LEFT JOIN preview_counts p
      ON p.asset_id=r.asset_id AND p.tf=r.tf AND p.period=r.period
)
SELECT
    :table_name,
    'ema_multi_tf_preview_rowcount_vs_expected',
    asset_id,
    tf,
    period,
    CASE
        WHEN expected_preview IS NULL THEN 'WARN'
        WHEN expected_preview = 0 AND actual_preview = 0 THEN 'PASS'
        WHEN expected_preview = 0 AND actual_preview <> 0 THEN 'FAIL'
        WHEN expected_preview < 0 THEN 'WARN'
        WHEN abs_diff <= 2 THEN 'PASS'
        WHEN pct_diff IS NOT NULL AND pct_diff <= 0.01 THEN 'WARN'
        ELSE 'FAIL'
    END,
    actual_preview,
    expected_preview,
    jsonb_build_object(
        'n_canon', n_canon,
        'n_daily', n_daily,
        'abs_diff', abs_diff,
        'pct_diff', pct_diff,
        'min_canon_ts', min_canon_ts,
        'max_canon_ts', max_canon_ts,
        'min_canon_date', min_canon_d,
        'max_canon_date', max_canon_d,
        'expected_model', 'expected_preview = n_daily_between(min_canon_date,max_canon_date) - n_canon; preview counted inside [min_canon_ts,max_canon_ts]'
    )
FROM scored;
"""

# NOTE: Your error happened because expected_preview/actual_preview were referenced in the OUTER SELECT
# but only existed in base(), and the outer SELECT was FROM scored which didn't carry them through.
# Fix: keep actual_preview and expected_preview columns in scored so they are in scope.

SQL_TEST_PREVIEW_DENSITY_VS_EXPECTED = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, period, status, actual, expected, extra
)
WITH base AS (
    SELECT
        s.asset_id,
        s.tf,
        s.period,
        s.actual::numeric   AS actual_preview,
        s.expected::numeric AS expected_preview
    FROM {STATS_TABLE} s
    WHERE s.table_name = :table_name
      AND s.test_name = 'ema_multi_tf_preview_rowcount_vs_expected'
      AND s.asset_id IS NOT NULL
),
scored AS (
    SELECT
        asset_id,
        tf,
        period,
        actual_preview,
        expected_preview,
        CASE
            WHEN expected_preview <= 0 THEN NULL
            ELSE actual_preview / expected_preview
        END AS ratio
    FROM base
)
SELECT
    :table_name,
    'preview_density_vs_expected',
    asset_id,
    tf,
    period,
    CASE
        WHEN expected_preview = 0 AND actual_preview = 0 THEN 'PASS'
        WHEN expected_preview = 0 AND actual_preview <> 0 THEN 'FAIL'
        WHEN ratio IS NULL THEN 'WARN'
        WHEN abs(ratio - 1) <= 0.01 THEN 'PASS'
        WHEN abs(ratio - 1) <= 0.05 THEN 'WARN'
        ELSE 'FAIL'
    END,
    ratio,
    1,
    jsonb_build_object(
        'expected_ratio', 1,
        'note', 'ratio = actual_preview / expected_preview (preview bounded to canonical TS window)'
    )
FROM scored;
"""


# ----------------------------
# Tests (roll flag consistency)
# ----------------------------

SQL_TEST_ROLL_FLAG_CONSISTENCY = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name, asset_id, tf, period, status, actual, expected, extra
)
WITH counts AS (
    SELECT
        k.asset_id,
        k.tf,
        k.period,
        COUNT(*) FILTER (WHERE e.roll = false) AS n_roll_false,
        COUNT(*) FILTER (WHERE e.roll = true)  AS n_roll_true,
        COUNT(*) AS n_total
    FROM _impacted_keys k
    LEFT JOIN {EMA_TABLE} e
      ON e.id = k.asset_id AND e.tf = k.tf AND e.period = k.period
    GROUP BY k.asset_id, k.tf, k.period
)
SELECT
    :table_name,
    'ema_multi_tf_roll_flag_consistency',
    asset_id,
    tf,
    period,
    CASE
        WHEN n_roll_false = 0 THEN 'FAIL'
        WHEN n_roll_true = 0 THEN 'WARN'
        ELSE 'PASS'
    END,
    n_roll_true::numeric,
    1,
    jsonb_build_object(
        'n_roll_false', n_roll_false,
        'n_roll_true', n_roll_true,
        'n_total', n_total
    )
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
            logger.info("multi_tf stats run complete.")
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
            logger.info("multi_tf stats run complete.")
            return

        conn.execute(
            text(
                "INSERT INTO _impacted_keys(asset_id, tf, period) VALUES (:asset_id, :tf, :period)"
            ),
            [dict(r._mapping) for r in impacted],
        )

        # Delete prior stats for these keys/TFs + global rows
        conn.execute(text(SQL_DELETE_KEYS), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_DELETE_TFS), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_DELETE_GLOBAL), {"table_name": EMA_TABLE})

        # Run tests
        conn.execute(text(SQL_TEST_KEY_UNIQUENESS_TS), {"table_name": EMA_TABLE})

        conn.execute(text(SQL_TEST_TF_MEMBERSHIP), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_TEST_TF_DAYS_CONSTANT), {"table_name": EMA_TABLE})

        conn.execute(text(SQL_TEST_MAX_GAP_ROLL_FALSE), {"table_name": EMA_TABLE})
        conn.execute(text(SQL_TEST_MAX_GAP_ROLL_TRUE), {"table_name": EMA_TABLE})

        conn.execute(
            text(SQL_TEST_ROWCOUNT_VS_SPAN_ROLL_FALSE), {"table_name": EMA_TABLE}
        )

        # Preview expected (SYNTHESIS)
        conn.execute(
            text(SQL_TEST_PREVIEW_ROWCOUNT_VS_EXPECTED), {"table_name": EMA_TABLE}
        )
        conn.execute(
            text(SQL_TEST_PREVIEW_DENSITY_VS_EXPECTED), {"table_name": EMA_TABLE}
        )

        conn.execute(text(SQL_TEST_ROLL_FLAG_CONSISTENCY), {"table_name": EMA_TABLE})

        # Advance watermark only after successful test writes
        conn.execute(
            text(SQL_SET_WATERMARK),
            {"table_name": EMA_TABLE, "last_ingested_at": max_ing},
        )

    logger.info("multi_tf stats run complete.")


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
