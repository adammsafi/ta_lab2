from __future__ import annotations

r"""
refresh_ema_multi_tf_cal_anchor_stats.py

Calendar-aware EMA CAL_ANCHOR stats using public.dim_timeframe.

Targets (defaults):
- public.cmc_ema_multi_tf_cal_anchor_us
- public.cmc_ema_multi_tf_cal_anchor_iso

Incremental behavior:
- Uses public.ema_multi_tf_cal_anchor_stats_state as a per-table watermark store:
    last_ingested_at = MAX(ingested_at) processed last time for that EMA table.
- On each run (default incremental):
    * If no new rows (max_ingested_at <= last_ingested_at): skip stats work for that table.
    * If new rows exist: recompute stats ONLY for impacted (id, tf, period) keys
      that have rows with ingested_at > last_ingested_at.
    * TF-level tests run only for impacted TFs.
    * Updates watermark at end for each processed table.

Heartbeat behavior (state only):
- Regardless of whether any stats work is performed, if the EMA table is non-empty,
  we update state.updated_at to reflect "script ran for this table".
- This does NOT advance last_ingested_at unless we actually ran tests successfully.

Full refresh option:
- --full-refresh:
    * Truncates public.ema_multi_tf_cal_anchor_stats
    * Clears public.ema_multi_tf_cal_anchor_stats_state
    * Recomputes stats for all keys for each requested table
    * Resets watermarks

Assumptions:
- EMA tables have ingested_at column (timestamptz).
- EMA tables have roll (boolean), roll_bar (boolean), ts (timestamptz).

Spyder runfile():
runfile(
    r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\emas\stats\multi_tf_cal_anchor\refresh_ema_multi_tf_cal_anchor_stats.py",
    wdir=r"C:\Users\asafi\Downloads\ta_lab2",
    args="--tables public.cmc_ema_multi_tf_cal_anchor_us public.cmc_ema_multi_tf_cal_anchor_iso"
)
"""

import argparse
import logging
import sys
from typing import Iterable, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.config import TARGET_DB_URL

STATS_TABLE = "public.ema_multi_tf_cal_anchor_stats"
STATE_TABLE = "public.ema_multi_tf_cal_anchor_stats_state"


# ----------------------------
# Logging
# ----------------------------

def _setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("ema_cal_anchor_stats")
    if logger.handlers:
        return logger  # already configured (Spyder autoreload etc.)

    lvl = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(lvl)

    h = logging.StreamHandler(stream=sys.stdout)
    h.setLevel(lvl)
    fmt = logging.Formatter("[%(levelname)s] %(message)s")
    h.setFormatter(fmt)
    logger.addHandler(h)
    logger.propagate = False
    return logger


# ----------------------------
# Create tables if needed (no drops)
# ----------------------------

DDL_CREATE_STATS_IF_NEEDED = f"""
CREATE TABLE IF NOT EXISTS {STATS_TABLE} (
    stat_id          BIGSERIAL PRIMARY KEY,
    table_name       TEXT        NOT NULL,
    test_name        TEXT        NOT NULL,

    asset_id         INTEGER,
    tf               TEXT,
    period           INTEGER,

    alignment_type   TEXT,
    base_unit        TEXT,
    tf_qty           INTEGER,
    calendar_scheme  TEXT,
    calendar_anchor  BOOLEAN,

    status           TEXT        NOT NULL,
    actual           NUMERIC,
    expected         NUMERIC,
    extra            JSONB,
    checked_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

DDL_CREATE_STATE_IF_NEEDED = f"""
CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
    table_name        TEXT PRIMARY KEY,
    last_ingested_at  TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# ----------------------------
# dim_timeframe projection
# ----------------------------

DIM_TF_COLS = """
    dt.alignment_type,
    dt.base_unit,
    dt.tf_qty,
    dt.calendar_scheme,
    dt.calendar_anchor,
    dt.tf_days_nominal,
    dt.tf_days_min,
    dt.tf_days_max,
    dt.allow_partial_start,
    dt.allow_partial_end
"""


# ----------------------------
# Incremental temp tables
# ----------------------------

DDL_TEMP_IMPACTED_KEYS = """
CREATE TEMP TABLE IF NOT EXISTS _impacted_keys (
    asset_id integer NOT NULL,
    tf       text    NOT NULL,
    period   integer NOT NULL
) ON COMMIT DROP;

TRUNCATE TABLE _impacted_keys;
"""

SQL_IMPACTED_KEYS_SINCE = """
SELECT DISTINCT e.id AS asset_id, e.tf, e.period
FROM {table} e
WHERE e.ingested_at > :last_ingested_at;
"""

SQL_ALL_KEYS = """
SELECT DISTINCT e.id AS asset_id, e.tf, e.period
FROM {table} e
WHERE e.roll = false;
"""

SQL_MAX_INGESTED_AT = """
SELECT MAX(ingested_at) AS max_ingested_at
FROM {table};
"""

SQL_GET_STATE = f"""
SELECT last_ingested_at
FROM {STATE_TABLE}
WHERE table_name = :table_name;
"""

SQL_UPSERT_STATE = f"""
INSERT INTO {STATE_TABLE}(table_name, last_ingested_at)
VALUES (:table_name, :last_ingested_at)
ON CONFLICT (table_name)
DO UPDATE SET last_ingested_at = EXCLUDED.last_ingested_at,
              updated_at = now();
"""

# State-only heartbeat: bump updated_at without changing last_ingested_at.
# Uses UPSERT so it creates the state row if missing, and NEVER overwrites last_ingested_at on conflict.
SQL_TOUCH_STATE = f"""
INSERT INTO {STATE_TABLE}(table_name, last_ingested_at, updated_at)
VALUES (:table_name, NULL, now())
ON CONFLICT (table_name)
DO UPDATE SET updated_at = now();
"""

SQL_CLEAR_STATE = f"TRUNCATE TABLE {STATE_TABLE};"
SQL_TRUNCATE_STATS = f"TRUNCATE TABLE {STATS_TABLE};"


# ----------------------------
# Delete old stats for impacted scope (latest-only)
# ----------------------------

SQL_DELETE_STATS_FOR_KEYS = f"""
DELETE FROM {STATS_TABLE} s
USING _impacted_keys k
WHERE s.table_name = :table_name
  AND s.test_name = :test_name
  AND s.asset_id = k.asset_id
  AND s.tf = k.tf
  AND s.period = k.period;
"""

SQL_DELETE_STATS_FOR_TFS = f"""
DELETE FROM {STATS_TABLE} s
USING (SELECT DISTINCT tf FROM _impacted_keys) tfs
WHERE s.table_name = :table_name
  AND s.test_name = :test_name
  AND s.tf = tfs.tf;
"""


# ----------------------------
# Tests (incremental filtered by _impacted_keys)
# ----------------------------

SQL_TEST_TF_MEMBERSHIP = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name,
    tf,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
    status, actual, expected, extra
)
WITH tfs AS (
  SELECT DISTINCT tf FROM _impacted_keys
),
j AS (
  SELECT
    t.tf,
    dt.alignment_type,
    dt.base_unit,
    dt.tf_qty,
    dt.calendar_scheme,
    dt.calendar_anchor,
    (dt.tf IS NOT NULL) AS in_dim
  FROM tfs t
  LEFT JOIN public.dim_timeframe dt
    ON dt.tf = t.tf
)
SELECT
  :table_name AS table_name,
  'tf_membership_in_dim_timeframe' AS test_name,
  tf,
  alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
  CASE WHEN in_dim THEN 'PASS' ELSE 'FAIL' END AS status,
  CASE WHEN in_dim THEN 0 ELSE 1 END::numeric AS actual,
  0::numeric AS expected,
  jsonb_build_object('missing_in_dim_timeframe', (NOT in_dim)) AS extra
FROM j;
"""

# TF-scoped audit: bounds must be internally consistent (min <= max).
# Missing dim row => WARN (membership test is the authoritative FAIL).
SQL_TEST_DIM_BOUNDS_MIN_LE_MAX = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name,
    tf,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
    status, actual, expected, extra
)
WITH tfs AS (
  SELECT DISTINCT tf FROM _impacted_keys
),
j AS (
  SELECT
    t.tf,
    {DIM_TF_COLS},
    (dt.tf IS NOT NULL) AS in_dim
  FROM tfs t
  LEFT JOIN public.dim_timeframe dt
    ON dt.tf = t.tf
),
chk AS (
  SELECT
    tf,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
    tf_days_min, tf_days_max, tf_days_nominal, in_dim,
    CASE
      WHEN NOT in_dim THEN 'WARN'
      WHEN tf_days_min IS NULL OR tf_days_max IS NULL THEN 'WARN'
      WHEN tf_days_min <= tf_days_max THEN 'PASS'
      ELSE 'FAIL'
    END AS status,
    CASE
      WHEN tf_days_min IS NULL OR tf_days_max IS NULL THEN NULL
      ELSE (tf_days_min - tf_days_max)::numeric
    END AS actual,
    0::numeric AS expected,
    jsonb_build_object(
      'in_dim_timeframe', in_dim,
      'tf_days_min', tf_days_min,
      'tf_days_max', tf_days_max,
      'tf_days_nominal', tf_days_nominal
    ) AS extra
  FROM j
)
SELECT
  :table_name AS table_name,
  'dim_timeframe_bounds_min_le_max' AS test_name,
  tf,
  alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
  status, actual, expected, extra
FROM chk;
"""

# TF-scoped audit: nominal should be "reasonable" under anchor convention:
# - Months: expected nominal = 30 * qty (30/360 convention), with small tolerance
# - Years: expected nominal = 365 * qty, with small tolerance
# - Weeks: expected nominal = 7 * qty (exact)
# - Days: expected nominal = qty (exact)
# Missing dim row => WARN (membership test is the authoritative FAIL).
SQL_TEST_DIM_NOMINAL_REASONABLE = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name,
    tf,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
    status, actual, expected, extra
)
WITH tfs AS (
  SELECT DISTINCT tf FROM _impacted_keys
),
j AS (
  SELECT
    t.tf,
    {DIM_TF_COLS},
    (dt.tf IS NOT NULL) AS in_dim
  FROM tfs t
  LEFT JOIN public.dim_timeframe dt
    ON dt.tf = t.tf
),
calc AS (
  SELECT
    *,
    CASE
      WHEN base_unit = 'D' AND tf_qty IS NOT NULL THEN tf_qty
      WHEN base_unit = 'W' AND tf_qty IS NOT NULL THEN 7 * tf_qty
      WHEN base_unit = 'M' AND tf_qty IS NOT NULL THEN 30 * tf_qty   -- 30/360 convention (business standard)
      WHEN base_unit = 'Y' AND tf_qty IS NOT NULL THEN 365 * tf_qty  -- business convention
      ELSE NULL
    END AS expected_nominal,
    CASE
      WHEN base_unit = 'D' THEN 0
      WHEN base_unit = 'W' THEN 0
      WHEN base_unit = 'M' THEN 2
      WHEN base_unit = 'Y' THEN 5
      ELSE 7
    END AS tol_days
  FROM j
)
SELECT
  :table_name AS table_name,
  'dim_timeframe_nominal_reasonable' AS test_name,
  tf,
  alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
  CASE
    WHEN NOT in_dim THEN 'WARN'
    WHEN tf_days_nominal IS NULL OR expected_nominal IS NULL THEN 'WARN'
    WHEN abs(tf_days_nominal - expected_nominal) <= tol_days THEN 'PASS'
    ELSE 'WARN'
  END AS status,
  tf_days_nominal::numeric AS actual,
  expected_nominal::numeric AS expected,
  jsonb_build_object(
    'in_dim_timeframe', in_dim,
    'tf_days_nominal', tf_days_nominal,
    'expected_nominal', expected_nominal,
    'tol_days', tol_days,
    'tf_days_min', tf_days_min,
    'tf_days_max', tf_days_max
  ) AS extra
FROM calc;
"""

SQL_TEST_CANONICAL_ROWCOUNT = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name,
    asset_id, tf, period,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
    status, actual, expected, extra
)
WITH groups AS (
    SELECT
        e.id AS asset_id,
        e.tf,
        e.period,
        MIN(e.ts::date) AS min_date,
        MAX(e.ts::date) AS max_date,
        COUNT(*)        AS n_rows
    FROM {{table}} e
    JOIN _impacted_keys k
      ON k.asset_id = e.id AND k.tf = e.tf AND k.period = e.period
    WHERE e.roll = false
    GROUP BY e.id, e.tf, e.period
),
joined AS (
    SELECT
        g.*,
        {DIM_TF_COLS},
        (g.max_date - g.min_date) AS span_days,

        CASE
            WHEN dt.base_unit IN ('D','W')
                 AND dt.tf_days_nominal IS NOT NULL
                 AND dt.tf_days_nominal > 0
                 AND g.min_date IS NOT NULL
                 AND g.max_date IS NOT NULL
            THEN ((g.max_date - g.min_date)::numeric / dt.tf_days_nominal::numeric) + 1
            ELSE NULL
        END AS expected_n_dw,

        CASE
            WHEN dt.base_unit = 'M'
                 AND dt.tf_qty IS NOT NULL
                 AND dt.tf_qty > 0
                 AND g.min_date IS NOT NULL
                 AND g.max_date IS NOT NULL
            THEN (
                SELECT COUNT(*)
                FROM (
                    SELECT date_trunc('month', dd)::date AS m
                    FROM generate_series(
                        date_trunc('month', g.min_date)::date,
                        date_trunc('month', g.max_date)::date,
                        interval '1 month'
                    ) AS dd
                ) months
                WHERE (
                    (EXTRACT(YEAR FROM months.m)::int * 12 + EXTRACT(MONTH FROM months.m)::int)
                    - (EXTRACT(YEAR FROM date_trunc('month', g.min_date)::date)::int * 12
                       + EXTRACT(MONTH FROM date_trunc('month', g.min_date)::date)::int)
                ) % dt.tf_qty = 0
            )
            ELSE NULL
        END AS expected_n_m,

        CASE
            WHEN dt.base_unit = 'Y'
                 AND dt.tf_qty IS NOT NULL
                 AND dt.tf_qty > 0
                 AND g.min_date IS NOT NULL
                 AND g.max_date IS NOT NULL
            THEN (
                SELECT COUNT(*)
                FROM (
                    SELECT date_trunc('year', dd)::date AS y
                    FROM generate_series(
                        date_trunc('year', g.min_date)::date,
                        date_trunc('year', g.max_date)::date,
                        interval '1 year'
                    ) AS dd
                ) years
                WHERE (EXTRACT(YEAR FROM years.y)::int - EXTRACT(YEAR FROM date_trunc('year', g.min_date)::date)::int) % dt.tf_qty = 0
            )
            ELSE NULL
        END AS expected_n_y
    FROM groups g
    LEFT JOIN public.dim_timeframe dt
      ON dt.tf = g.tf
),
final AS (
    SELECT
        *,
        COALESCE(expected_n_dw, expected_n_m, expected_n_y) AS expected_n,
        CASE
            WHEN COALESCE(expected_n_dw, expected_n_m, expected_n_y) IS NULL THEN NULL
            ELSE (COALESCE(expected_n_dw, expected_n_m, expected_n_y) - n_rows)
        END AS diff_expected_minus_actual
    FROM joined
)
SELECT
    :table_name AS table_name,
    'canonical_row_count_vs_expected_dim_timeframe' AS test_name,
    asset_id, tf, period,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,

    CASE
        WHEN expected_n IS NULL THEN 'WARN'
        WHEN diff_expected_minus_actual = 0 THEN 'PASS'
        WHEN calendar_anchor IS TRUE AND diff_expected_minus_actual BETWEEN -5 AND 5 THEN 'WARN'
        WHEN calendar_anchor IS NOT TRUE AND diff_expected_minus_actual BETWEEN -2 AND 2 THEN 'WARN'
        ELSE 'FAIL'
    END AS status,

    n_rows::numeric AS actual,
    expected_n::numeric AS expected,
    jsonb_build_object(
        'min_date', min_date,
        'max_date', max_date,
        'span_days', span_days,
        'tf_days_nominal', tf_days_nominal,
        'tf_days_min', tf_days_min,
        'tf_days_max', tf_days_max,
        'allow_partial_start', allow_partial_start,
        'allow_partial_end', allow_partial_end,
        'expected_n_dw', expected_n_dw,
        'expected_n_m', expected_n_m,
        'expected_n_y', expected_n_y,
        'expected_n', expected_n,
        'diff_expected_minus_actual', diff_expected_minus_actual
    ) AS extra
FROM final;
"""

SQL_TEST_CANONICAL_MAX_GAP = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name,
    asset_id, tf, period,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
    status, actual, expected, extra
)
WITH ordered AS (
    SELECT
        e.id AS asset_id,
        e.tf,
        e.period,
        e.ts::date AS ts_date,
        LAG(e.ts::date) OVER (PARTITION BY e.id, e.tf, e.period ORDER BY e.ts) AS prev_date
    FROM {{table}} e
    JOIN _impacted_keys k
      ON k.asset_id = e.id AND k.tf = e.tf AND k.period = e.period
    WHERE e.roll = false
),
gaps AS (
    SELECT
        asset_id, tf, period,
        COUNT(*) AS n_rows,
        MAX(CASE WHEN prev_date IS NULL THEN 0 ELSE (ts_date - prev_date) END) AS max_gap_days
    FROM ordered
    GROUP BY asset_id, tf, period
),
joined AS (
    SELECT
        g.*,
        {DIM_TF_COLS}
    FROM gaps g
    LEFT JOIN public.dim_timeframe dt
      ON dt.tf = g.tf
),
final AS (
    SELECT
        *,
        CASE WHEN calendar_anchor IS TRUE THEN 7 ELSE 2 END AS tol_days
    FROM joined
)
SELECT
    :table_name AS table_name,
    'canonical_max_gap_vs_dim_timeframe_bounds' AS test_name,
    asset_id, tf, period,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
    CASE
        WHEN tf_days_max IS NULL OR tf_days_max <= 0 THEN 'WARN'
        WHEN max_gap_days <= tf_days_max THEN 'PASS'
        WHEN max_gap_days <= (tf_days_max + tol_days) THEN 'WARN'
        ELSE 'FAIL'
    END AS status,
    max_gap_days::numeric AS actual,
    tf_days_max::numeric AS expected,
    jsonb_build_object(
        'n_rows', n_rows,
        'max_gap_days', max_gap_days,
        'tf_days_min', tf_days_min,
        'tf_days_max', tf_days_max,
        'tf_days_nominal', tf_days_nominal,
        'tol_days', tol_days
    ) AS extra
FROM final;
"""

SQL_TEST_CANONICAL_TS_MATCH = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name,
    asset_id, tf, period,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
    status, actual, expected, extra
)
WITH a AS (
  SELECT e.id AS asset_id, e.tf, e.period, e.ts
  FROM {{table}} e
  JOIN _impacted_keys k
    ON k.asset_id = e.id AND k.tf = e.tf AND k.period = e.period
  WHERE e.roll = false
),
b AS (
  SELECT e.id AS asset_id, e.tf, e.period, e.ts
  FROM {{table}} e
  JOIN _impacted_keys k
    ON k.asset_id = e.id AND k.tf = e.tf AND k.period = e.period
  WHERE e.roll_bar = false
),
j AS (
  SELECT
    COALESCE(a.asset_id, b.asset_id) AS asset_id,
    COALESCE(a.tf, b.tf) AS tf,
    COALESCE(a.period, b.period) AS period,
    CASE WHEN a.ts IS NULL THEN 1 ELSE 0 END AS bar_not_roll,
    CASE WHEN b.ts IS NULL THEN 1 ELSE 0 END AS roll_not_bar
  FROM a
  FULL OUTER JOIN b USING (asset_id, tf, period, ts)
),
m AS (
  SELECT
    asset_id, tf, period,
    SUM(bar_not_roll) AS n_bar_not_roll,
    SUM(roll_not_bar) AS n_roll_not_bar
  FROM j
  GROUP BY 1,2,3
),
joined AS (
  SELECT
    m.*,
    {DIM_TF_COLS},
    (m.n_bar_not_roll + m.n_roll_not_bar) AS n_mismatch
  FROM m
  LEFT JOIN public.dim_timeframe dt
    ON dt.tf = m.tf
)
SELECT
  :table_name AS table_name,
  'canonical_ts_match_roll_false_vs_roll_bar_false' AS test_name,
  asset_id, tf, period,
  alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
  CASE
    WHEN n_mismatch = 0 THEN 'PASS'
    WHEN n_mismatch BETWEEN 1 AND 5 THEN 'WARN'
    ELSE 'FAIL'
  END AS status,
  n_mismatch::numeric AS actual,
  0::numeric AS expected,
  jsonb_build_object(
    'n_bar_not_roll', n_bar_not_roll,
    'n_roll_not_bar', n_roll_not_bar
  ) AS extra
FROM joined;
"""

# IMPORTANT: do NOT Python-format this SQL (it contains :expected_scheme bind param)
SQL_TEST_WEEK_SCHEME_ALIGNMENT = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name,
    tf,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
    status, actual, expected, extra
)
WITH tfs AS (
  SELECT DISTINCT tf FROM _impacted_keys
),
j AS (
  SELECT
    t.tf,
    {DIM_TF_COLS}
  FROM tfs t
  LEFT JOIN public.dim_timeframe dt
    ON dt.tf = t.tf
),
chk AS (
  SELECT
    tf,
    alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
    CASE
      WHEN base_unit <> 'W' THEN 'PASS'
      WHEN calendar_scheme IS NULL OR calendar_scheme = '' THEN 'WARN'
      WHEN :expected_scheme = 'US' AND calendar_scheme = 'US' THEN 'PASS'
      WHEN :expected_scheme = 'ISO' AND calendar_scheme = 'ISO' THEN 'PASS'
      ELSE 'FAIL'
    END AS status,
    CASE
      WHEN base_unit = 'W'
       AND calendar_scheme IS NOT NULL AND calendar_scheme <> ''
       AND calendar_scheme <> :expected_scheme
      THEN 1 ELSE 0
    END::numeric AS actual,
    0::numeric AS expected,
    jsonb_build_object('expected_scheme', :expected_scheme) AS extra
  FROM j
)
SELECT
  :table_name AS table_name,
  'week_calendar_scheme_matches_table_family' AS test_name,
  tf,
  alignment_type, base_unit, tf_qty, calendar_scheme, calendar_anchor,
  status, actual, expected, extra
FROM chk;
"""


def get_engine(db_url: Optional[str] = None) -> Engine:
    return create_engine(db_url or TARGET_DB_URL)


def infer_expected_scheme(table: str) -> Optional[str]:
    t = table.lower()
    if t.endswith("_us"):
        return "US"
    if t.endswith("_iso"):
        return "ISO"
    return None


def run(engine: Engine, tables: Iterable[str], full_refresh: bool = False, log_level: str = "INFO") -> None:
    logger = _setup_logging(log_level)
    tables = list(tables)
    if not tables:
        raise ValueError("No tables provided.")

    logger.info("Starting CAL_ANCHOR stats run. full_refresh=%s", full_refresh)
    logger.info("Stats table: %s", STATS_TABLE)
    logger.info("State table: %s", STATE_TABLE)
    logger.info("Tables: %s", ", ".join(tables))

    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_STATS_IF_NEEDED))
        conn.execute(text(DDL_CREATE_STATE_IF_NEEDED))

        if full_refresh:
            logger.warning("FULL REFRESH: truncating stats + clearing state.")
            conn.execute(text(SQL_TRUNCATE_STATS))
            conn.execute(text(SQL_CLEAR_STATE))

    for table in tables:
        table_name = table  # schema-qualified input

        with engine.begin() as conn:
            last_ing = conn.execute(text(SQL_GET_STATE), {"table_name": table_name}).scalar()
            max_ing = conn.execute(text(SQL_MAX_INGESTED_AT.format(table=table_name))).scalar()

            if max_ing is None:
                logger.warning("Table empty, skipping: %s", table_name)
                continue

            logger.info("Table=%s max_ingested_at=%s state_last=%s", table_name, max_ing, last_ing)

            # Always bump state.updated_at for non-empty tables to show "script ran"
            conn.execute(text(SQL_TOUCH_STATE), {"table_name": table_name})

            # If no new ingested_at, do nothing else (do NOT advance watermark, do NOT touch stats)
            if (not full_refresh) and (last_ing is not None) and (max_ing <= last_ing):
                logger.info("No new ingested_at since last run. Skipping tests: %s", table_name)
                continue

            conn.execute(text(DDL_TEMP_IMPACTED_KEYS))

            if full_refresh or last_ing is None:
                logger.info("Building impacted keys: ALL canonical keys (roll=false) for %s", table_name)
                impacted = conn.execute(text(SQL_ALL_KEYS.format(table=table_name))).fetchall()
            else:
                logger.info("Building impacted keys: ingested_at > %s for %s", last_ing, table_name)
                impacted = conn.execute(
                    text(SQL_IMPACTED_KEYS_SINCE.format(table=table_name)),
                    {"last_ingested_at": last_ing},
                ).fetchall()

            if not impacted:
                logger.info("No impacted keys found for %s; leaving watermark unchanged.", table_name)
                continue

            conn.execute(
                text("INSERT INTO _impacted_keys(asset_id, tf, period) VALUES (:asset_id, :tf, :period)"),
                [dict(r._mapping) for r in impacted],
            )
            logger.info("Impacted keys inserted: %s rows for %s", len(impacted), table_name)

            # Delete + recompute latest-only for impacted scope
            tests_keyed = [
                "canonical_row_count_vs_expected_dim_timeframe",
                "canonical_max_gap_vs_dim_timeframe_bounds",
                "canonical_ts_match_roll_false_vs_roll_bar_false",
            ]
            for tn in tests_keyed:
                conn.execute(text(SQL_DELETE_STATS_FOR_KEYS), {"table_name": table_name, "test_name": tn})
            logger.info("Cleared keyed test rows for impacted scope: %s", ", ".join(tests_keyed))

            tests_tf = [
                "tf_membership_in_dim_timeframe",
                "week_calendar_scheme_matches_table_family",
                "dim_timeframe_bounds_min_le_max",
                "dim_timeframe_nominal_reasonable",
            ]
            for tn in tests_tf:
                conn.execute(text(SQL_DELETE_STATS_FOR_TFS), {"table_name": table_name, "test_name": tn})
            logger.info("Cleared TF-scoped test rows for impacted TFs: %s", ", ".join(tests_tf))

            # Run tests
            logger.info("Running tests for %s ...", table_name)
            conn.execute(text(SQL_TEST_TF_MEMBERSHIP), {"table_name": table_name})
            conn.execute(text(SQL_TEST_DIM_BOUNDS_MIN_LE_MAX), {"table_name": table_name})
            conn.execute(text(SQL_TEST_DIM_NOMINAL_REASONABLE), {"table_name": table_name})
            conn.execute(text(SQL_TEST_CANONICAL_ROWCOUNT.format(table=table_name)), {"table_name": table_name})
            conn.execute(text(SQL_TEST_CANONICAL_MAX_GAP.format(table=table_name)), {"table_name": table_name})
            conn.execute(text(SQL_TEST_CANONICAL_TS_MATCH.format(table=table_name)), {"table_name": table_name})

            exp = infer_expected_scheme(table_name)
            if exp is not None:
                conn.execute(
                    text(SQL_TEST_WEEK_SCHEME_ALIGNMENT),
                    {"table_name": table_name, "expected_scheme": exp},
                )

            # Advance watermark ONLY after tests succeed
            conn.execute(text(SQL_UPSERT_STATE), {"table_name": table_name, "last_ingested_at": max_ing})
            logger.info("Updated watermark for %s to %s", table_name, max_ing)

    logger.info("Done.")


def main(db_url: Optional[str] = None, tables: Optional[Iterable[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Calendar-aware EMA CAL_ANCHOR stats (incremental via stats_state).")
    parser.add_argument("--db-url", help="Override TARGET_DB_URL from ta_lab2.config")
    parser.add_argument(
        "--tables",
        nargs="+",
        default=["public.cmc_ema_multi_tf_cal_anchor_us", "public.cmc_ema_multi_tf_cal_anchor_iso"],
        help="Schema-qualified EMA tables to audit.",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Truncate stats + clear state, then recompute all keys for each table.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR). Default INFO.",
    )
    args = parser.parse_args()

    engine = get_engine(args.db_url or db_url)
    run(engine, args.tables if tables is None else list(tables), full_refresh=args.full_refresh, log_level=args.log_level)


if __name__ == "__main__":
    main()
