"""
test_returns_ema_schema.py

Validation tests for the 6 cmc_returns_ema_* tables.
Tests schema, data integrity, and referential constraints.

Run:
    pytest tests/time/test_returns_ema_schema.py -v
"""

from __future__ import annotations

import os

import pandas as pd
import pytest
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Table configs: PK columns and value columns per returns table
# ---------------------------------------------------------------------------

RETURNS_TABLES = [
    "cmc_returns_ema_multi_tf",
    "cmc_returns_ema_multi_tf_cal_us",
    "cmc_returns_ema_multi_tf_cal_iso",
    "cmc_returns_ema_multi_tf_cal_anchor_us",
    "cmc_returns_ema_multi_tf_cal_anchor_iso",
    "cmc_returns_ema_multi_tf_u",
]

# PK columns per table (roll is NOT part of PK)
TABLE_PK_COLS: dict[str, list[str]] = {
    "cmc_returns_ema_multi_tf": ["id", "ts", "tf", "period"],
    "cmc_returns_ema_multi_tf_cal_us": ["id", "ts", "tf", "period"],
    "cmc_returns_ema_multi_tf_cal_iso": ["id", "ts", "tf", "period"],
    "cmc_returns_ema_multi_tf_cal_anchor_us": ["id", "ts", "tf", "period"],
    "cmc_returns_ema_multi_tf_cal_anchor_iso": ["id", "ts", "tf", "period"],
    "cmc_returns_ema_multi_tf_u": [
        "id",
        "ts",
        "tf",
        "period",
        "alignment_source",
    ],
}

# Value columns shared across all tables
# (unified timeline: _ema/_ema_bar for canonical, _roll for unified)
VALUE_COLS = [
    "roll",
    "gap_days",
    "gap_days_roll",
    # ema roll
    "delta1_ema_roll",
    "delta2_ema_roll",
    "ret_arith_ema_roll",
    "delta_ret_arith_ema_roll",
    "ret_log_ema_roll",
    "delta_ret_log_ema_roll",
    # ema canonical
    "delta1_ema",
    "delta2_ema",
    "ret_arith_ema",
    "delta_ret_arith_ema",
    "ret_log_ema",
    "delta_ret_log_ema",
    # ema_bar roll
    "delta1_ema_bar_roll",
    "delta2_ema_bar_roll",
    "ret_arith_ema_bar_roll",
    "delta_ret_arith_ema_bar_roll",
    "ret_log_ema_bar_roll",
    "delta_ret_log_ema_bar_roll",
    # ema_bar canonical
    "delta1_ema_bar",
    "delta2_ema_bar",
    "ret_arith_ema_bar",
    "delta_ret_arith_ema_bar",
    "ret_log_ema_bar",
    "delta_ret_log_ema_bar",
    "ingested_at",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_url():
    """Database URL from environment variable."""
    url = os.environ.get("TARGET_DB_URL")
    if not url:
        pytest.skip("TARGET_DB_URL not set - skipping database tests")
    return url


@pytest.fixture(scope="module")
def engine(db_url):
    """SQLAlchemy engine for database tests."""
    return create_engine(db_url, future=True)


@pytest.fixture(scope="module")
def existing_tables(engine):
    """Set of returns tables that actually exist in the database."""
    q = text(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(:tables)
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn, params={"tables": RETURNS_TABLES})
    return set(df["table_name"].tolist())


def _skip_if_missing(existing_tables, table):
    """Skip test if the table does not exist in the database."""
    if table not in existing_tables:
        pytest.skip(f"Table {table} does not exist - skipping")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", RETURNS_TABLES)
def test_returns_table_exists(engine, table):
    """Verify returns table exists in public schema."""
    q = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = :table_name
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn, params={"table_name": table})

    assert not df.empty, f"Table {table} does not exist in public schema"


@pytest.mark.parametrize("table", RETURNS_TABLES)
def test_returns_table_has_pk_columns(engine, table):
    """Verify all expected PK columns are present."""
    expected_pk = TABLE_PK_COLS[table]

    q = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :table_name
          AND column_name = ANY(:cols)
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn, params={"table_name": table, "cols": expected_pk})

    actual_cols = set(df["column_name"].tolist())
    missing = set(expected_pk) - actual_cols
    assert not missing, f"Table {table} missing PK columns: {sorted(missing)}"


@pytest.mark.parametrize("table", RETURNS_TABLES)
def test_returns_table_has_value_columns(engine, table):
    """Verify value columns are present."""
    q = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :table_name
          AND column_name = ANY(:cols)
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn, params={"table_name": table, "cols": VALUE_COLS})

    actual_cols = set(df["column_name"].tolist())
    missing = set(VALUE_COLS) - actual_cols
    assert not missing, f"Table {table} missing value columns: {sorted(missing)}"


@pytest.mark.parametrize("table", RETURNS_TABLES)
def test_returns_pk_uniqueness(engine, existing_tables, table):
    """Verify no duplicate primary keys."""
    _skip_if_missing(existing_tables, table)
    pk_cols = TABLE_PK_COLS[table]
    pk_tuple = ", ".join(pk_cols)

    q = text(
        f"""
        SELECT
            COUNT(*)::bigint AS total_rows,
            COUNT(DISTINCT ({pk_tuple}))::bigint AS distinct_pk
        FROM {table}
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn)

    total = int(df.loc[0, "total_rows"])
    distinct = int(df.loc[0, "distinct_pk"])

    if total == 0:
        pytest.skip(f"Table {table} is empty - cannot validate uniqueness")

    assert total == distinct, (
        f"PK not unique in {table}: {total} total rows but {distinct} distinct PKs. "
        f"Duplicate count: {total - distinct}"
    )


@pytest.mark.parametrize("table", RETURNS_TABLES)
def test_returns_table_has_data(engine, existing_tables, table):
    """Verify table has at least 100 rows."""
    _skip_if_missing(existing_tables, table)
    q = text(f"SELECT COUNT(*)::bigint AS n_rows FROM {table}")
    with engine.connect() as conn:
        df = pd.read_sql(q, conn)

    n_rows = int(df.loc[0, "n_rows"])

    if n_rows == 0:
        pytest.skip(f"Table {table} is empty - run refresh script to populate")

    assert n_rows >= 100, f"Table {table} has only {n_rows} rows, expected at least 100"


@pytest.mark.parametrize("table", RETURNS_TABLES)
def test_returns_tf_in_dim_timeframe(engine, existing_tables, table):
    """Verify all tf values exist in dim_timeframe."""
    _skip_if_missing(existing_tables, table)
    # Check dim_timeframe exists
    q_exists = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'dim_timeframe'
        """
    )
    with engine.connect() as conn:
        df_exists = pd.read_sql(q_exists, conn)

    if df_exists.empty:
        pytest.skip("dim_timeframe table does not exist")

    q_tf = text(f"SELECT DISTINCT tf FROM {table} ORDER BY tf")
    with engine.connect() as conn:
        df_tf = pd.read_sql(q_tf, conn)

    if df_tf.empty:
        pytest.skip(f"Table {table} is empty - cannot validate tf values")

    tf_values = df_tf["tf"].tolist()

    q_valid = text(
        """
        SELECT tf
        FROM dim_timeframe
        WHERE tf = ANY(:tf_values)
        """
    )
    with engine.connect() as conn:
        df_valid = pd.read_sql(q_valid, conn, params={"tf_values": tf_values})

    valid_tfs = set(df_valid["tf"].tolist())
    actual_tfs = set(tf_values)
    invalid_tfs = actual_tfs - valid_tfs

    assert (
        not invalid_tfs
    ), f"TF values in {table} not found in dim_timeframe: {sorted(invalid_tfs)}"


@pytest.mark.parametrize("table", RETURNS_TABLES)
def test_returns_no_null_roll_returns(engine, existing_tables, table):
    """Verify _roll return columns are never NULL (populated on all rows)."""
    _skip_if_missing(existing_tables, table)
    q = text(
        f"""
        SELECT
            SUM(CASE WHEN ret_arith_ema_roll IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_arith_roll,
            SUM(CASE WHEN ret_arith_ema_bar_roll IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_arith_bar_roll,
            SUM(CASE WHEN ret_log_ema_roll IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_log_roll,
            SUM(CASE WHEN ret_log_ema_bar_roll IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_log_bar_roll,
            COUNT(*)::bigint AS n_rows
        FROM {table}
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn)

    n_rows = int(df.loc[0, "n_rows"])
    if n_rows == 0:
        pytest.skip(f"Table {table} is empty - cannot validate null policy")

    n_null_arith_roll = int(df.loc[0, "n_null_arith_roll"])
    n_null_arith_bar_roll = int(df.loc[0, "n_null_arith_bar_roll"])
    n_null_log_roll = int(df.loc[0, "n_null_log_roll"])
    n_null_log_bar_roll = int(df.loc[0, "n_null_log_bar_roll"])

    total_nulls = (
        n_null_arith_roll
        + n_null_arith_bar_roll
        + n_null_log_roll
        + n_null_log_bar_roll
    )
    assert total_nulls == 0, (
        f"Table {table} has NULL _roll returns: "
        f"ret_arith_ema_roll={n_null_arith_roll}, ret_arith_ema_bar_roll={n_null_arith_bar_roll}, "
        f"ret_log_ema_roll={n_null_log_roll}, ret_log_ema_bar_roll={n_null_log_bar_roll} "
        f"out of {n_rows} rows"
    )


@pytest.mark.parametrize("table", RETURNS_TABLES)
def test_returns_no_null_canonical_returns(engine, existing_tables, table):
    """Verify non-roll return columns are never NULL on roll=FALSE rows."""
    _skip_if_missing(existing_tables, table)
    q = text(
        f"""
        SELECT
            SUM(CASE WHEN ret_arith_ema IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_arith_ema,
            SUM(CASE WHEN ret_arith_ema_bar IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_arith_ema_bar,
            SUM(CASE WHEN ret_log_ema IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_log_ema,
            SUM(CASE WHEN ret_log_ema_bar IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_log_ema_bar,
            COUNT(*)::bigint AS n_rows
        FROM {table}
        WHERE roll = FALSE
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn)

    n_rows = int(df.loc[0, "n_rows"])
    if n_rows == 0:
        pytest.skip(f"Table {table} has no roll=FALSE rows - cannot validate")

    n_null_arith_ema = int(df.loc[0, "n_null_arith_ema"])
    n_null_arith_ema_bar = int(df.loc[0, "n_null_arith_ema_bar"])
    n_null_log_ema = int(df.loc[0, "n_null_log_ema"])
    n_null_log_ema_bar = int(df.loc[0, "n_null_log_ema_bar"])

    total_nulls = (
        n_null_arith_ema + n_null_arith_ema_bar + n_null_log_ema + n_null_log_ema_bar
    )
    assert total_nulls == 0, (
        f"Table {table} has NULL canonical returns on roll=FALSE rows: "
        f"ret_arith_ema={n_null_arith_ema}, ret_arith_ema_bar={n_null_arith_ema_bar}, "
        f"ret_log_ema={n_null_log_ema}, ret_log_ema_bar={n_null_log_ema_bar} "
        f"out of {n_rows} roll=FALSE rows"
    )
