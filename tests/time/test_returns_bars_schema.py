"""
test_returns_bars_schema.py

Validation tests for the 5 cmc_returns_bars_* tables (wide-column, dual-LAG).
Tests schema, data integrity, and referential constraints.

Run:
    pytest tests/time/test_returns_bars_schema.py -v
"""

from __future__ import annotations

import os

import pandas as pd
import pytest
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Table configs
# ---------------------------------------------------------------------------

RETURNS_TABLES = [
    "cmc_returns_bars_multi_tf",
    "cmc_returns_bars_multi_tf_cal_us",
    "cmc_returns_bars_multi_tf_cal_iso",
    "cmc_returns_bars_multi_tf_cal_anchor_us",
    "cmc_returns_bars_multi_tf_cal_anchor_iso",
]

TABLE_PK_COLS: dict[str, list[str]] = {
    t: ["id", "timestamp", "tf"] for t in RETURNS_TABLES
}

VALUE_COLS = [
    "tf_days",
    "bar_seq",
    "pos_in_bar",
    "count_days",
    "count_days_remaining",
    "roll",
    "time_close",
    "time_close_bar",
    "time_open_bar",
    "gap_bars",
    # roll columns
    "delta1_roll",
    "delta2_roll",
    "ret_arith_roll",
    "delta_ret_arith_roll",
    "ret_log_roll",
    "delta_ret_log_roll",
    "range_roll",
    "range_pct_roll",
    "true_range_roll",
    "true_range_pct_roll",
    # canonical columns
    "delta1",
    "delta2",
    "ret_arith",
    "delta_ret_arith",
    "ret_log",
    "delta_ret_log",
    "range",
    "range_pct",
    "true_range",
    "true_range_pct",
    "ingested_at",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_url():
    url = os.environ.get("TARGET_DB_URL")
    if not url:
        pytest.skip("TARGET_DB_URL not set - skipping database tests")
    return url


@pytest.fixture(scope="module")
def engine(db_url):
    return create_engine(db_url, future=True)


@pytest.fixture(scope="module")
def existing_tables(engine):
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
    if table not in existing_tables:
        pytest.skip(f"Table {table} does not exist - skipping")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", RETURNS_TABLES)
def test_returns_table_exists(engine, table):
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
    _skip_if_missing(existing_tables, table)
    pk_cols = TABLE_PK_COLS[table]
    pk_expr = ", ".join(f'"{c}"' for c in pk_cols)

    q = text(
        f"""
        SELECT
            COUNT(*)::bigint AS total_rows,
            COUNT(DISTINCT ({pk_expr}))::bigint AS distinct_pk
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
    _skip_if_missing(existing_tables, table)
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
            SUM(CASE WHEN ret_arith_roll IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_arith_roll,
            SUM(CASE WHEN ret_log_roll IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_log_roll,
            SUM(CASE WHEN range_roll IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_range_roll,
            SUM(CASE WHEN true_range_roll IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_true_range_roll,
            COUNT(*)::bigint AS n_rows
        FROM {table}
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn)

    n_rows = int(df.loc[0, "n_rows"])
    if n_rows == 0:
        pytest.skip(f"Table {table} is empty - cannot validate null policy")

    total_nulls = sum(
        int(df.loc[0, c])
        for c in [
            "n_null_arith_roll",
            "n_null_log_roll",
            "n_null_range_roll",
            "n_null_true_range_roll",
        ]
    )
    assert total_nulls == 0, (
        f"Table {table} has NULL _roll returns: "
        f"ret_arith_roll={int(df.loc[0, 'n_null_arith_roll'])}, "
        f"ret_log_roll={int(df.loc[0, 'n_null_log_roll'])}, "
        f"range_roll={int(df.loc[0, 'n_null_range_roll'])}, "
        f"true_range_roll={int(df.loc[0, 'n_null_true_range_roll'])} "
        f"out of {n_rows} rows"
    )


@pytest.mark.parametrize("table", RETURNS_TABLES)
def test_returns_no_null_canonical_returns(engine, existing_tables, table):
    """Verify canonical return columns are never NULL on roll=FALSE rows (excluding first per key)."""
    _skip_if_missing(existing_tables, table)
    # Exclude first canonical row per (id,tf) — gap_bars IS NULL means no previous canonical
    q = text(
        f"""
        SELECT
            SUM(CASE WHEN ret_arith IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_arith,
            SUM(CASE WHEN ret_log IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_log,
            SUM(CASE WHEN range IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_range,
            SUM(CASE WHEN true_range IS NULL THEN 1 ELSE 0 END)::bigint AS n_null_true_range,
            COUNT(*)::bigint AS n_rows
        FROM {table}
        WHERE roll = FALSE AND gap_bars IS NOT NULL
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn)

    n_rows = int(df.loc[0, "n_rows"])
    if n_rows == 0:
        pytest.skip(f"Table {table} has no roll=FALSE rows - cannot validate")

    total_nulls = sum(
        int(df.loc[0, c])
        for c in [
            "n_null_arith",
            "n_null_log",
            "n_null_range",
            "n_null_true_range",
        ]
    )
    assert total_nulls == 0, (
        f"Table {table} has NULL canonical returns on roll=FALSE rows: "
        f"ret_arith={int(df.loc[0, 'n_null_arith'])}, "
        f"ret_log={int(df.loc[0, 'n_null_log'])}, "
        f"range={int(df.loc[0, 'n_null_range'])}, "
        f"true_range={int(df.loc[0, 'n_null_true_range'])} "
        f"out of {n_rows} roll=FALSE rows"
    )
