from __future__ import annotations

r"""
refresh_returns_ema_stats.py

Parameterized incremental stats script for all 6 EMA-returns tables.

Targets (shared tables, discriminated by table_name):
  public.returns_ema_stats       — stat rows
  public.returns_ema_stats_state — per-table watermark

All 6 returns families share identical value columns and differ only in PK
structure, so one script handles them all (unlike EMA stats which need separate
scripts per family due to calendar/roll/preview logic).

Incremental behavior:
  - Watermark via last_ingested_at per table_name in state table.
  - On each run: if no new rows, skip.  Otherwise, recompute stats for
    impacted (id, tf, period) keys that have ingested_at > last_ingested_at.
  - TF-level tests run only for impacted TFs.
  - Heartbeat: always bumps state.updated_at for non-empty tables.

Full refresh:
  --full-refresh truncates stats + state, recomputes everything.

Stats tests:
  1. pk_uniqueness              — no duplicate PKs per impacted keys
  2. tf_membership_in_dim_timeframe — every tf exists in dim_timeframe
  3. coverage_vs_ema_source     — n_ret == n_ema - 1 per key group
  4. gap_days_min_ge_1          — gap_days >= 1, never NULL
  5. max_gap_vs_tf_days_nominal — max(gap_days) <= 1.5 * tf_days_nominal
  6. null_policy_ret            — ret_arith and ret_log never NULL
  7. alignment_to_ema_source    — every returns row has matching EMA source row

CLI:
  python refresh_returns_ema_stats.py --families multi_tf,cal_us
  python refresh_returns_ema_stats.py --families all
  python refresh_returns_ema_stats.py --families all --full-refresh

Spyder:
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\stats\refresh_returns_ema_stats.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--families all --full-refresh"
)
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError

from ta_lab2.scripts.bars.common_snapshot_contract import get_engine


# ---------------------------------------------------------------------------
# Table configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReturnsTableConfig:
    returns_table: str  # e.g. "public.cmc_returns_ema_multi_tf"
    ema_source_table: str  # e.g. "public.cmc_ema_multi_tf"
    label: str  # e.g. "multi_tf"
    pk_cols: tuple[str, ...]  # full PK including ts
    key_cols: tuple[str, ...]  # PK minus ts (grouping key)
    has_alignment_source: bool


ALL_CONFIGS: Dict[str, ReturnsTableConfig] = {
    "multi_tf": ReturnsTableConfig(
        returns_table="public.cmc_returns_ema_multi_tf",
        ema_source_table="public.cmc_ema_multi_tf",
        label="multi_tf",
        pk_cols=("id", "ts", "tf", "period"),
        key_cols=("id", "tf", "period"),
        has_alignment_source=False,
    ),
    "cal_us": ReturnsTableConfig(
        returns_table="public.cmc_returns_ema_multi_tf_cal_us",
        ema_source_table="public.cmc_ema_multi_tf_cal_us",
        label="cal_us",
        pk_cols=("id", "ts", "tf", "period"),
        key_cols=("id", "tf", "period"),
        has_alignment_source=False,
    ),
    "cal_iso": ReturnsTableConfig(
        returns_table="public.cmc_returns_ema_multi_tf_cal_iso",
        ema_source_table="public.cmc_ema_multi_tf_cal_iso",
        label="cal_iso",
        pk_cols=("id", "ts", "tf", "period"),
        key_cols=("id", "tf", "period"),
        has_alignment_source=False,
    ),
    "cal_anchor_us": ReturnsTableConfig(
        returns_table="public.cmc_returns_ema_multi_tf_cal_anchor_us",
        ema_source_table="public.cmc_ema_multi_tf_cal_anchor_us",
        label="cal_anchor_us",
        pk_cols=("id", "ts", "tf", "period"),
        key_cols=("id", "tf", "period"),
        has_alignment_source=False,
    ),
    "cal_anchor_iso": ReturnsTableConfig(
        returns_table="public.cmc_returns_ema_multi_tf_cal_anchor_iso",
        ema_source_table="public.cmc_ema_multi_tf_cal_anchor_iso",
        label="cal_anchor_iso",
        pk_cols=("id", "ts", "tf", "period"),
        key_cols=("id", "tf", "period"),
        has_alignment_source=False,
    ),
    "u": ReturnsTableConfig(
        returns_table="public.cmc_returns_ema_multi_tf_u",
        ema_source_table="public.cmc_ema_multi_tf_u",
        label="u",
        pk_cols=("id", "ts", "tf", "period", "alignment_source"),
        key_cols=("id", "tf", "period", "alignment_source"),
        has_alignment_source=True,
    ),
}


# ---------------------------------------------------------------------------
# Shared stats + state tables
# ---------------------------------------------------------------------------

STATS_TABLE = "public.returns_ema_stats"
STATE_TABLE = "public.returns_ema_stats_state"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("returns_ema_stats")
    if logger.handlers:
        return logger

    lvl = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(lvl)

    h = logging.StreamHandler(stream=sys.stdout)
    h.setLevel(lvl)
    fmt = logging.Formatter("[%(levelname)s] %(message)s")
    h.setFormatter(fmt)
    logger.addHandler(h)
    logger.propagate = False
    return logger


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

DDL_CREATE_STATS_IF_NEEDED = f"""
CREATE TABLE IF NOT EXISTS {STATS_TABLE} (
    stat_id       BIGSERIAL PRIMARY KEY,
    table_name    TEXT        NOT NULL,
    test_name     TEXT        NOT NULL,

    asset_id      INTEGER,
    tf            TEXT,
    period        INTEGER,

    status        TEXT        NOT NULL,
    actual        NUMERIC,
    expected      NUMERIC,
    extra         JSONB,
    checked_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

DDL_CREATE_STATE_IF_NEEDED = f"""
CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
    table_name        TEXT PRIMARY KEY,
    last_ingested_at  TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# ---------------------------------------------------------------------------
# Impacted-keys temp table
# ---------------------------------------------------------------------------

DDL_TEMP_IMPACTED_KEYS = """
CREATE TEMP TABLE IF NOT EXISTS _impacted_keys (
    asset_id integer NOT NULL,
    tf       text    NOT NULL,
    period   integer NOT NULL
) ON COMMIT DROP;

TRUNCATE TABLE _impacted_keys;
"""


# ---------------------------------------------------------------------------
# State / watermark SQL
# ---------------------------------------------------------------------------

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

SQL_TOUCH_STATE = f"""
INSERT INTO {STATE_TABLE}(table_name, last_ingested_at, updated_at)
VALUES (:table_name, NULL, now())
ON CONFLICT (table_name)
DO UPDATE SET updated_at = now();
"""

SQL_CLEAR_STATE = f"TRUNCATE TABLE {STATE_TABLE};"
SQL_TRUNCATE_STATS = f"TRUNCATE TABLE {STATS_TABLE};"


# ---------------------------------------------------------------------------
# Scope deletion SQL
# ---------------------------------------------------------------------------

SQL_DELETE_STATS_FOR_KEYS = f"""
DELETE FROM {STATS_TABLE} s
USING _impacted_keys k
WHERE s.table_name = :table_name
  AND s.test_name  = :test_name
  AND s.asset_id   = k.asset_id
  AND s.tf         = k.tf
  AND s.period     = k.period;
"""

SQL_DELETE_STATS_FOR_TFS = f"""
DELETE FROM {STATS_TABLE} s
USING (SELECT DISTINCT tf FROM _impacted_keys) tfs
WHERE s.table_name = :table_name
  AND s.test_name  = :test_name
  AND s.tf         = tfs.tf;
"""


# ---------------------------------------------------------------------------
# Impacted-key queries (parametrized by table/key_cols)
# ---------------------------------------------------------------------------


def _sql_impacted_keys_since(table: str) -> str:
    return f"""
    SELECT DISTINCT e.id AS asset_id, e.tf, e.period
    FROM {table} e
    WHERE e.ingested_at > :last_ingested_at;
    """


def _sql_all_keys(table: str) -> str:
    return f"""
    SELECT DISTINCT e.id AS asset_id, e.tf, e.period
    FROM {table} e;
    """


# ---------------------------------------------------------------------------
# Test 1: pk_uniqueness
# ---------------------------------------------------------------------------


def _sql_test_pk_uniqueness(cfg: ReturnsTableConfig) -> str:
    pk_tuple = ", ".join(f"r.{c}" for c in cfg.pk_cols)
    return f"""
    INSERT INTO {STATS_TABLE} (
        table_name, test_name,
        asset_id, tf, period,
        status, actual, expected, extra
    )
    WITH scoped AS (
        SELECT r.*
        FROM {cfg.returns_table} r
        JOIN _impacted_keys k
          ON k.asset_id = r.id AND k.tf = r.tf AND k.period = r.period
    ),
    agg AS (
        SELECT
            id AS asset_id, tf, period,
            COUNT(*) AS total_rows,
            COUNT(DISTINCT ({pk_tuple})) AS distinct_pk
        FROM scoped r
        GROUP BY id, tf, period
    )
    SELECT
        :table_name AS table_name,
        'pk_uniqueness' AS test_name,
        asset_id, tf, period,
        CASE WHEN total_rows = distinct_pk THEN 'PASS' ELSE 'FAIL' END AS status,
        (total_rows - distinct_pk)::numeric AS actual,
        0::numeric AS expected,
        jsonb_build_object(
            'total_rows', total_rows,
            'distinct_pk', distinct_pk
        ) AS extra
    FROM agg;
    """


# ---------------------------------------------------------------------------
# Test 2: tf_membership_in_dim_timeframe
# ---------------------------------------------------------------------------

SQL_TEST_TF_MEMBERSHIP = f"""
INSERT INTO {STATS_TABLE} (
    table_name, test_name,
    tf,
    status, actual, expected, extra
)
WITH tfs AS (
    SELECT DISTINCT tf FROM _impacted_keys
),
j AS (
    SELECT
        t.tf,
        (dt.tf IS NOT NULL) AS in_dim
    FROM tfs t
    LEFT JOIN public.dim_timeframe dt
      ON dt.tf = t.tf
)
SELECT
    :table_name AS table_name,
    'tf_membership_in_dim_timeframe' AS test_name,
    tf,
    CASE WHEN in_dim THEN 'PASS' ELSE 'FAIL' END AS status,
    CASE WHEN in_dim THEN 0 ELSE 1 END::numeric AS actual,
    0::numeric AS expected,
    jsonb_build_object('missing_in_dim_timeframe', (NOT in_dim)) AS extra
FROM j;
"""


# ---------------------------------------------------------------------------
# Test 3: coverage_vs_ema_source
# ---------------------------------------------------------------------------


def _sql_test_coverage_vs_ema(cfg: ReturnsTableConfig) -> str:
    """n_ret == n_ema - 1 per key group, aggregated to (id, tf, period) for output.

    Both EMA source and returns tables now share the same key structure
    (no series column), so the comparison is a direct COUNT(*) match.
    """
    key_group = list(cfg.key_cols)

    ema_alias = ", ".join(
        f"e.{c} AS asset_id" if c == "id" else f"e.{c}" for c in key_group
    )
    ema_group_sql = ", ".join(f"e.{c}" for c in key_group)

    ret_alias = ", ".join(
        f"r.{c} AS asset_id" if c == "id" else f"r.{c}" for c in key_group
    )
    ret_group_sql = ", ".join(f"r.{c}" for c in key_group)

    # Join on all key columns
    join_parts = []
    for c in key_group:
        alias = "asset_id" if c == "id" else c
        join_parts.append(f"e.{alias} = r.{alias}")
    join_on = " AND ".join(join_parts)

    return f"""
    INSERT INTO {STATS_TABLE} (
        table_name, test_name,
        asset_id, tf, period,
        status, actual, expected, extra
    )
    WITH ema_counts AS (
        SELECT {ema_alias}, COUNT(*) AS n_ema
        FROM {cfg.ema_source_table} e
        JOIN _impacted_keys k
          ON k.asset_id = e.id AND k.tf = e.tf AND k.period = e.period
        GROUP BY {ema_group_sql}
    ),
    ret_counts AS (
        SELECT {ret_alias}, COUNT(*) AS n_ret
        FROM {cfg.returns_table} r
        JOIN _impacted_keys k
          ON k.asset_id = r.id AND k.tf = r.tf AND k.period = r.period
        GROUP BY {ret_group_sql}
    ),
    checks AS (
        SELECT
            r.asset_id, r.tf, r.period,
            COALESCE(e.n_ema, 0) AS n_ema,
            r.n_ret,
            CASE
                WHEN e.n_ema IS NULL OR e.n_ema = 0 THEN 'WARN'
                WHEN r.n_ret = e.n_ema - 1 THEN 'PASS'
                WHEN abs(r.n_ret - (e.n_ema - 1)) <= 2 THEN 'WARN'
                ELSE 'FAIL'
            END AS key_status
        FROM ret_counts r
        LEFT JOIN ema_counts e
          ON {join_on}
    ),
    agg AS (
        SELECT
            asset_id, tf, period,
            CASE
                WHEN bool_or(key_status = 'FAIL') THEN 'FAIL'
                WHEN bool_or(key_status = 'WARN') THEN 'WARN'
                ELSE 'PASS'
            END AS status,
            SUM(n_ret)::numeric AS total_ret,
            SUM(n_ema - 1)::numeric AS total_expected,
            SUM(CASE WHEN key_status <> 'PASS' THEN 1 ELSE 0 END) AS n_bad_keys,
            COUNT(*) AS n_key_groups
        FROM checks
        GROUP BY asset_id, tf, period
    )
    SELECT
        :table_name AS table_name,
        'coverage_vs_ema_source' AS test_name,
        asset_id, tf, period,
        status,
        total_ret AS actual,
        total_expected AS expected,
        jsonb_build_object(
            'total_ret', total_ret,
            'total_expected', total_expected,
            'n_bad_keys', n_bad_keys,
            'n_key_groups', n_key_groups
        ) AS extra
    FROM agg;
    """


# ---------------------------------------------------------------------------
# Test 4: gap_days_min_ge_1
# ---------------------------------------------------------------------------


def _sql_test_gap_days_min(cfg: ReturnsTableConfig) -> str:
    return f"""
    INSERT INTO {STATS_TABLE} (
        table_name, test_name,
        asset_id, tf, period,
        status, actual, expected, extra
    )
    WITH agg AS (
        SELECT
            r.id AS asset_id, r.tf, r.period,
            MIN(r.gap_days_roll) AS min_gap,
            SUM(CASE WHEN r.gap_days_roll IS NULL THEN 1 ELSE 0 END) AS n_null_gap
        FROM {cfg.returns_table} r
        JOIN _impacted_keys k
          ON k.asset_id = r.id AND k.tf = r.tf AND k.period = r.period
        GROUP BY r.id, r.tf, r.period
    )
    SELECT
        :table_name AS table_name,
        'gap_days_min_ge_1' AS test_name,
        asset_id, tf, period,
        CASE
            WHEN n_null_gap > 0 THEN 'FAIL'
            WHEN min_gap >= 1 THEN 'PASS'
            ELSE 'FAIL'
        END AS status,
        COALESCE(min_gap, -1)::numeric AS actual,
        1::numeric AS expected,
        jsonb_build_object(
            'min_gap_days_roll', min_gap,
            'n_null_gap', n_null_gap
        ) AS extra
    FROM agg;
    """


# ---------------------------------------------------------------------------
# Test 5: max_gap_vs_tf_days_nominal
# ---------------------------------------------------------------------------


def _sql_test_max_gap(cfg: ReturnsTableConfig) -> str:
    return f"""
    INSERT INTO {STATS_TABLE} (
        table_name, test_name,
        asset_id, tf, period,
        status, actual, expected, extra
    )
    WITH agg AS (
        SELECT
            r.id AS asset_id, r.tf, r.period,
            MAX(r.gap_days_roll) AS max_gap,
            MAX(r.tf_days) AS tf_days
        FROM {cfg.returns_table} r
        JOIN _impacted_keys k
          ON k.asset_id = r.id AND k.tf = r.tf AND k.period = r.period
        GROUP BY r.id, r.tf, r.period
    )
    SELECT
        :table_name AS table_name,
        'max_gap_vs_tf_days_nominal' AS test_name,
        asset_id, tf, period,
        CASE
            WHEN tf_days IS NULL OR tf_days <= 0 THEN 'WARN'
            WHEN max_gap <= 1.5 * tf_days THEN 'PASS'
            WHEN max_gap <= 2.0 * tf_days THEN 'WARN'
            ELSE 'FAIL'
        END AS status,
        max_gap::numeric AS actual,
        (1.5 * tf_days)::numeric AS expected,
        jsonb_build_object(
            'max_gap_days', max_gap,
            'tf_days', tf_days,
            'threshold_1_5x', 1.5 * COALESCE(tf_days, 0)
        ) AS extra
    FROM agg;
    """


# ---------------------------------------------------------------------------
# Test 6: null_policy_ret
# ---------------------------------------------------------------------------


def _sql_test_null_policy_ret(cfg: ReturnsTableConfig) -> str:
    return f"""
    INSERT INTO {STATS_TABLE} (
        table_name, test_name,
        asset_id, tf, period,
        status, actual, expected, extra
    )
    WITH agg AS (
        SELECT
            r.id AS asset_id, r.tf, r.period,
            COUNT(*) AS n_rows,
            -- _roll columns should never be NULL (populated on all rows)
            SUM(CASE WHEN r.ret_arith_ema_roll IS NULL THEN 1 ELSE 0 END) AS n_null_arith_roll,
            SUM(CASE WHEN r.ret_arith_ema_bar_roll IS NULL THEN 1 ELSE 0 END) AS n_null_arith_bar_roll,
            SUM(CASE WHEN r.ret_log_ema_roll IS NULL THEN 1 ELSE 0 END)   AS n_null_log_roll,
            SUM(CASE WHEN r.ret_log_ema_bar_roll IS NULL THEN 1 ELSE 0 END) AS n_null_log_bar_roll,
            -- Non-roll columns should not be NULL on roll=FALSE rows
            SUM(CASE WHEN NOT r.roll AND r.ret_arith_ema IS NULL THEN 1 ELSE 0 END) AS n_null_arith_canon,
            SUM(CASE WHEN NOT r.roll AND r.ret_arith_ema_bar IS NULL THEN 1 ELSE 0 END) AS n_null_arith_bar_canon,
            SUM(CASE WHEN NOT r.roll AND r.ret_log_ema IS NULL THEN 1 ELSE 0 END)   AS n_null_log_canon,
            SUM(CASE WHEN NOT r.roll AND r.ret_log_ema_bar IS NULL THEN 1 ELSE 0 END) AS n_null_log_bar_canon
        FROM {cfg.returns_table} r
        JOIN _impacted_keys k
          ON k.asset_id = r.id AND k.tf = r.tf AND k.period = r.period
        GROUP BY r.id, r.tf, r.period
    )
    SELECT
        :table_name AS table_name,
        'null_policy_ret' AS test_name,
        asset_id, tf, period,
        CASE
            WHEN n_null_arith_roll = 0 AND n_null_arith_bar_roll = 0
             AND n_null_log_roll = 0 AND n_null_log_bar_roll = 0
             AND n_null_arith_canon = 0 AND n_null_arith_bar_canon = 0
             AND n_null_log_canon = 0 AND n_null_log_bar_canon = 0 THEN 'PASS'
            ELSE 'FAIL'
        END AS status,
        (n_null_arith_roll + n_null_arith_bar_roll + n_null_log_roll + n_null_log_bar_roll
         + n_null_arith_canon + n_null_arith_bar_canon + n_null_log_canon + n_null_log_bar_canon)::numeric AS actual,
        0::numeric AS expected,
        jsonb_build_object(
            'n_rows', n_rows,
            'n_null_arith_roll', n_null_arith_roll,
            'n_null_arith_bar_roll', n_null_arith_bar_roll,
            'n_null_log_roll', n_null_log_roll,
            'n_null_log_bar_roll', n_null_log_bar_roll,
            'n_null_arith_canon', n_null_arith_canon,
            'n_null_arith_bar_canon', n_null_arith_bar_canon,
            'n_null_log_canon', n_null_log_canon,
            'n_null_log_bar_canon', n_null_log_bar_canon
        ) AS extra
    FROM agg;
    """


# ---------------------------------------------------------------------------
# Test 7: alignment_to_ema_source
# ---------------------------------------------------------------------------


def _sql_test_alignment(cfg: ReturnsTableConfig) -> str:
    """Every returns row should have a matching EMA source row on (id, tf, period, ts)."""
    return f"""
    INSERT INTO {STATS_TABLE} (
        table_name, test_name,
        asset_id, tf, period,
        status, actual, expected, extra
    )
    WITH ret AS (
        SELECT r.id AS asset_id, r.tf, r.period, r.ts
        FROM {cfg.returns_table} r
        JOIN _impacted_keys k
          ON k.asset_id = r.id AND k.tf = r.tf AND k.period = r.period
    ),
    unmatched AS (
        SELECT ret.asset_id, ret.tf, ret.period, COUNT(*) AS n_unmatched
        FROM ret
        LEFT JOIN {cfg.ema_source_table} e
          ON e.id = ret.asset_id AND e.tf = ret.tf AND e.period = ret.period AND e.ts = ret.ts
        WHERE e.id IS NULL
        GROUP BY ret.asset_id, ret.tf, ret.period
    ),
    all_keys AS (
        SELECT DISTINCT asset_id, tf, period FROM _impacted_keys
    )
    SELECT
        :table_name AS table_name,
        'alignment_to_ema_source' AS test_name,
        ak.asset_id, ak.tf, ak.period,
        CASE
            WHEN COALESCE(u.n_unmatched, 0) = 0 THEN 'PASS'
            ELSE 'FAIL'
        END AS status,
        COALESCE(u.n_unmatched, 0)::numeric AS actual,
        0::numeric AS expected,
        jsonb_build_object(
            'n_unmatched_returns_rows', COALESCE(u.n_unmatched, 0)
        ) AS extra
    FROM all_keys ak
    LEFT JOIN unmatched u
      USING (asset_id, tf, period);
    """


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run(
    engine: Engine,
    families: Iterable[str],
    full_refresh: bool = False,
    log_level: str = "INFO",
) -> None:
    logger = _setup_logging(log_level)
    families_list = list(families)
    if not families_list:
        raise ValueError("No families provided.")

    configs: List[ReturnsTableConfig] = []
    for f in families_list:
        if f not in ALL_CONFIGS:
            raise ValueError(
                f"Unknown family '{f}'. Available: {sorted(ALL_CONFIGS.keys())}"
            )
        configs.append(ALL_CONFIGS[f])

    logger.info("Starting returns EMA stats run. full_refresh=%s", full_refresh)
    logger.info("Stats table: %s", STATS_TABLE)
    logger.info("State table: %s", STATE_TABLE)
    logger.info("Families: %s", ", ".join(c.label for c in configs))

    # Ensure stats/state tables exist
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_STATS_IF_NEEDED))
        conn.execute(text(DDL_CREATE_STATE_IF_NEEDED))

        if full_refresh:
            logger.warning("FULL REFRESH: truncating stats + clearing state.")
            conn.execute(text(SQL_TRUNCATE_STATS))
            conn.execute(text(SQL_CLEAR_STATE))

    for cfg in configs:
        table_name = cfg.returns_table

        with engine.begin() as conn:
            last_ing = conn.execute(
                text(SQL_GET_STATE), {"table_name": table_name}
            ).scalar()
            try:
                max_ing = conn.execute(
                    text(SQL_MAX_INGESTED_AT.format(table=table_name))
                ).scalar()
            except ProgrammingError:
                logger.warning("Table does not exist, skipping: %s", table_name)
                continue

            if max_ing is None:
                logger.warning("Table empty, skipping: %s", table_name)
                continue

            logger.info(
                "Table=%s max_ingested_at=%s state_last=%s",
                table_name,
                max_ing,
                last_ing,
            )

            # Heartbeat
            conn.execute(text(SQL_TOUCH_STATE), {"table_name": table_name})

            if (not full_refresh) and (last_ing is not None) and (max_ing <= last_ing):
                logger.info(
                    "No new ingested_at since last run. Skipping tests: %s", table_name
                )
                continue

            # Create temp table for impacted keys
            conn.execute(text(DDL_TEMP_IMPACTED_KEYS))

            if full_refresh or last_ing is None:
                logger.info("Building impacted keys: ALL keys for %s", table_name)
                impacted = conn.execute(text(_sql_all_keys(table_name))).fetchall()
            else:
                logger.info(
                    "Building impacted keys: ingested_at > %s for %s",
                    last_ing,
                    table_name,
                )
                impacted = conn.execute(
                    text(_sql_impacted_keys_since(table_name)),
                    {"last_ingested_at": last_ing},
                ).fetchall()

            if not impacted:
                logger.info(
                    "No impacted keys found for %s; leaving watermark unchanged.",
                    table_name,
                )
                continue

            conn.execute(
                text(
                    "INSERT INTO _impacted_keys(asset_id, tf, period) "
                    "VALUES (:asset_id, :tf, :period)"
                ),
                [dict(r._mapping) for r in impacted],
            )
            logger.info(
                "Impacted keys inserted: %s rows for %s", len(impacted), table_name
            )

            # --- Delete old stats for impacted scope ---

            tests_keyed = [
                "pk_uniqueness",
                "coverage_vs_ema_source",
                "gap_days_min_ge_1",
                "max_gap_vs_tf_days_nominal",
                "null_policy_ret",
                "alignment_to_ema_source",
            ]
            for tn in tests_keyed:
                conn.execute(
                    text(SQL_DELETE_STATS_FOR_KEYS),
                    {"table_name": table_name, "test_name": tn},
                )
            logger.info(
                "Cleared keyed test rows for impacted scope: %s",
                ", ".join(tests_keyed),
            )

            tests_tf = ["tf_membership_in_dim_timeframe"]
            for tn in tests_tf:
                conn.execute(
                    text(SQL_DELETE_STATS_FOR_TFS),
                    {"table_name": table_name, "test_name": tn},
                )
            logger.info(
                "Cleared TF-scoped test rows for impacted TFs: %s",
                ", ".join(tests_tf),
            )

            # --- Run tests ---
            logger.info("Running tests for %s ...", table_name)

            conn.execute(
                text(_sql_test_pk_uniqueness(cfg)),
                {"table_name": table_name},
            )
            conn.execute(
                text(SQL_TEST_TF_MEMBERSHIP),
                {"table_name": table_name},
            )
            conn.execute(
                text(_sql_test_coverage_vs_ema(cfg)),
                {"table_name": table_name},
            )
            conn.execute(
                text(_sql_test_gap_days_min(cfg)),
                {"table_name": table_name},
            )
            conn.execute(
                text(_sql_test_max_gap(cfg)),
                {"table_name": table_name},
            )
            conn.execute(
                text(_sql_test_null_policy_ret(cfg)),
                {"table_name": table_name},
            )
            conn.execute(
                text(_sql_test_alignment(cfg)),
                {"table_name": table_name},
            )

            # Advance watermark
            conn.execute(
                text(SQL_UPSERT_STATE),
                {"table_name": table_name, "last_ingested_at": max_ing},
            )
            logger.info("Updated watermark for %s to %s", table_name, max_ing)

    logger.info("Done.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(db_url: Optional[str] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Incremental stats for EMA-returns tables."
    )
    parser.add_argument("--db-url", help="Override TARGET_DB_URL from ta_lab2.config")
    parser.add_argument(
        "--families",
        default="all",
        help=(
            'Comma-separated family labels or "all". '
            f"Available: {', '.join(sorted(ALL_CONFIGS.keys()))}"
        ),
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Truncate stats + clear state, then recompute all keys.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR). Default INFO.",
    )
    args = parser.parse_args()

    families_str: str = args.families.strip()
    if families_str.lower() == "all":
        families_list = list(ALL_CONFIGS.keys())
    else:
        families_list = [f.strip() for f in families_str.split(",") if f.strip()]

    engine = get_engine(args.db_url or db_url)
    run(
        engine,
        families_list,
        full_refresh=args.full_refresh,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
