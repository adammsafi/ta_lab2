"""
test_ema_unification.py

Validation tests for cmc_ema_multi_tf_u unified EMA table.
Tests schema, data integrity, and referential constraints.

Run:
    pytest tests/time/test_ema_unification.py -v
"""

from __future__ import annotations

import os

import pandas as pd
import pytest
from sqlalchemy import create_engine, text


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


def test_unified_table_exists(engine):
    """Verify cmc_ema_multi_tf_u table exists in public schema."""
    q = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'cmc_ema_multi_tf_u'
        """
    )
    df = pd.read_sql(q, engine)

    assert not df.empty, "Table cmc_ema_multi_tf_u does not exist in public schema"


def test_unified_table_has_pk_columns(engine):
    """Verify primary key columns exist: id, ts, tf, period, alignment_source."""
    required_pk_cols = ["id", "ts", "tf", "period", "alignment_source"]

    q = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cmc_ema_multi_tf_u'
          AND column_name = ANY(:cols)
        """
    )
    df = pd.read_sql(q, engine, params={"cols": required_pk_cols})

    actual_cols = set(df["column_name"].tolist())
    expected_cols = set(required_pk_cols)

    missing = expected_cols - actual_cols
    assert not missing, f"Missing PK columns: {sorted(missing)}"


def test_unified_table_has_value_columns(engine):
    """Verify value columns: ema, ingested_at, d1, d2, tf_days, roll, d1_roll, d2_roll."""
    required_value_cols = [
        "ema",
        "ingested_at",
        "d1",
        "d2",
        "tf_days",
        "roll",
        "d1_roll",
        "d2_roll",
    ]

    q = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cmc_ema_multi_tf_u'
          AND column_name = ANY(:cols)
        """
    )
    df = pd.read_sql(q, engine, params={"cols": required_value_cols})

    actual_cols = set(df["column_name"].tolist())
    expected_cols = set(required_value_cols)

    missing = expected_cols - actual_cols
    assert not missing, f"Missing value columns: {sorted(missing)}"


def test_unified_table_has_bar_columns(engine):
    """Verify bar-space columns for calendar variants."""
    bar_cols = [
        "ema_bar",
        "d1_bar",
        "d2_bar",
        "roll_bar",
        "d1_roll_bar",
        "d2_roll_bar",
    ]

    q = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cmc_ema_multi_tf_u'
          AND column_name = ANY(:cols)
        """
    )
    df = pd.read_sql(q, engine, params={"cols": bar_cols})

    actual_cols = set(df["column_name"].tolist())
    expected_cols = set(bar_cols)

    missing = expected_cols - actual_cols
    assert not missing, f"Missing bar columns: {sorted(missing)}"


def test_alignment_source_values(engine):
    """
    Verify alignment_source contains expected values.

    Expected alignment sources (those with source tables):
    - multi_tf
    - multi_tf_v2
    - multi_tf_cal_us
    - multi_tf_cal_iso
    - multi_tf_cal_anchor_us
    - multi_tf_cal_anchor_iso
    """
    q = text(
        """
        SELECT DISTINCT alignment_source
        FROM cmc_ema_multi_tf_u
        ORDER BY alignment_source
        """
    )
    df = pd.read_sql(q, engine)

    if df.empty:
        pytest.skip("Table cmc_ema_multi_tf_u is empty - cannot validate alignment_source values")

    actual_sources = set(df["alignment_source"].tolist())

    # Expected sources based on SOURCES list in sync_cmc_ema_multi_tf_u.py
    expected_sources = {
        "multi_tf",
        "multi_tf_v2",
        "multi_tf_cal_us",
        "multi_tf_cal_iso",
        "multi_tf_cal_anchor_us",
        "multi_tf_cal_anchor_iso",
    }

    # At least one expected source should be present
    overlap = actual_sources & expected_sources
    assert overlap, f"No expected alignment_source values found. Got: {sorted(actual_sources)}"

    # Warn about unexpected sources (not a failure, just informational)
    unexpected = actual_sources - expected_sources
    if unexpected:
        print(f"Warning: Unexpected alignment_source values: {sorted(unexpected)}")


def test_unified_table_has_data(engine):
    """Verify table has at least 1000 rows (reasonable minimum for production)."""
    q = text("SELECT COUNT(*)::bigint AS n_rows FROM cmc_ema_multi_tf_u")
    df = pd.read_sql(q, engine)

    n_rows = int(df.loc[0, "n_rows"])

    # Allow table to be empty in fresh environments, but warn
    if n_rows == 0:
        pytest.skip("Table cmc_ema_multi_tf_u is empty - run sync script to populate")

    assert n_rows >= 1000, f"Table has only {n_rows} rows, expected at least 1000"


def test_pk_uniqueness(engine):
    """Verify no duplicate primary keys (id, ts, tf, period, alignment_source)."""
    q = text(
        """
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT (id, ts, tf, period, alignment_source)) AS distinct_pk
        FROM cmc_ema_multi_tf_u
        """
    )
    df = pd.read_sql(q, engine)

    total = int(df.loc[0, "total_rows"])
    distinct = int(df.loc[0, "distinct_pk"])

    if total == 0:
        pytest.skip("Table cmc_ema_multi_tf_u is empty - cannot validate uniqueness")

    assert total == distinct, (
        f"Primary key not unique: {total} total rows but {distinct} distinct PKs. "
        f"Duplicate count: {total - distinct}"
    )


def test_tf_values_match_dim_timeframe(engine):
    """Verify all tf values exist in dim_timeframe table (referential integrity)."""
    # First check if dim_timeframe exists
    q_exists = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'dim_timeframe'
        """
    )
    df_exists = pd.read_sql(q_exists, engine)

    if df_exists.empty:
        pytest.skip("dim_timeframe table does not exist - cannot validate FK constraint")

    # Get distinct tf values from unified table
    q_tf_values = text("SELECT DISTINCT tf FROM cmc_ema_multi_tf_u ORDER BY tf")
    df_tf = pd.read_sql(q_tf_values, engine)

    if df_tf.empty:
        pytest.skip("cmc_ema_multi_tf_u is empty - cannot validate tf values")

    tf_values = df_tf["tf"].tolist()

    # Check each tf value exists in dim_timeframe
    q_validate = text(
        """
        SELECT tf
        FROM dim_timeframe
        WHERE tf = ANY(:tf_values)
        """
    )
    df_valid = pd.read_sql(q_validate, engine, params={"tf_values": tf_values})

    valid_tfs = set(df_valid["tf"].tolist())
    actual_tfs = set(tf_values)

    invalid_tfs = actual_tfs - valid_tfs

    assert not invalid_tfs, (
        f"TF values in cmc_ema_multi_tf_u not found in dim_timeframe: {sorted(invalid_tfs)}"
    )
