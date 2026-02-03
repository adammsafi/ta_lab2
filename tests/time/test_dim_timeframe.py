"""
Validation tests for dim_timeframe table and Python class.

Tests verify:
- Table exists in database
- Required columns are present
- Data is populated
- Python class can load from database
- Convenience functions work correctly
"""

import pytest
from sqlalchemy import create_engine, text

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.time.dim_timeframe import DimTimeframe, get_tf_days, list_tfs

# Skip all tests if TARGET_DB_URL is not set
pytestmark = pytest.mark.skipif(
    not TARGET_DB_URL, reason="TARGET_DB_URL not set - database tests skipped"
)


@pytest.fixture(scope="module")
def db_url():
    """Database URL fixture."""
    if not TARGET_DB_URL:
        pytest.skip("TARGET_DB_URL not set")
    return TARGET_DB_URL


@pytest.fixture(scope="module")
def engine(db_url):
    """SQLAlchemy engine fixture."""
    return create_engine(db_url)


def test_dim_timeframe_table_exists(engine):
    """Verify dim_timeframe table exists in public schema."""
    query = text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = 'dim_timeframe'
        )
    """
    )

    with engine.connect() as conn:
        result = conn.execute(query)
        exists = result.scalar()

    assert exists, "dim_timeframe table does not exist in public schema"


def test_dim_timeframe_has_required_columns(engine):
    """Verify all required columns exist in dim_timeframe table."""
    required_columns = {
        "tf",
        "label",
        "base_unit",
        "tf_qty",
        "tf_days_nominal",
        "alignment_type",
        "calendar_anchor",
        "roll_policy",
        "has_roll_flag",
        "is_intraday",
        "sort_order",
        "is_canonical",
        "calendar_scheme",
        "allow_partial_start",
        "allow_partial_end",
        "tf_days_min",
        "tf_days_max",
    }

    query = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'dim_timeframe'
    """
    )

    with engine.connect() as conn:
        result = conn.execute(query)
        actual_columns = {row[0] for row in result}

    missing_columns = required_columns - actual_columns
    assert not missing_columns, f"Missing required columns: {missing_columns}"


def test_dim_timeframe_has_data(engine):
    """Verify dim_timeframe has at least 5 rows (minimum viable population)."""
    query = text("SELECT COUNT(*) FROM dim_timeframe")

    with engine.connect() as conn:
        result = conn.execute(query)
        row_count = result.scalar()

    assert (
        row_count >= 5
    ), f"dim_timeframe has only {row_count} rows (expected at least 5)"


def test_list_tfs_returns_canonical(db_url):
    """Verify list_tfs returns canonical timeframes including 1D."""
    tfs = list_tfs(db_url, canonical_only=True)

    assert len(tfs) > 0, "list_tfs returned empty list"
    assert "1D" in tfs, "1D not found in canonical timeframes"


def test_list_tfs_tf_day_alignment(db_url):
    """Verify list_tfs can filter by alignment_type='tf_day'."""
    tfs = list_tfs(db_url, alignment_type="tf_day", canonical_only=False)

    assert len(tfs) > 0, "No tf_day alignment timeframes found"

    # Verify at least some expected tf_day timeframes exist
    expected_tf_day = {"1D", "5D", "7D", "10D", "21D"}
    found = expected_tf_day & set(tfs)
    assert len(found) > 0, f"Expected some of {expected_tf_day} in tf_day timeframes"


def test_get_tf_days_1d(db_url):
    """Verify get_tf_days returns 1 for '1D' timeframe."""
    tf_days = get_tf_days("1D", db_url)

    assert tf_days == 1, f"Expected tf_days=1 for '1D', got {tf_days}"


def test_dimtimeframe_from_db_loads(db_url):
    """Verify DimTimeframe.from_db loads successfully and has data."""
    dim_tf = DimTimeframe.from_db(db_url)

    assert isinstance(
        dim_tf, DimTimeframe
    ), "from_db did not return DimTimeframe instance"
    assert hasattr(dim_tf, "_meta"), "DimTimeframe missing _meta attribute"
    assert len(dim_tf._meta) > 0, "DimTimeframe._meta is empty"
    assert "1D" in dim_tf._meta, "1D timeframe not found in DimTimeframe._meta"


def test_dimtimeframe_alignment_type(db_url):
    """Verify DimTimeframe can retrieve alignment_type for timeframes."""
    dim_tf = DimTimeframe.from_db(db_url)

    alignment = dim_tf.alignment("1D")
    assert alignment in [
        "tf_day",
        "calendar",
    ], f"Unexpected alignment type: {alignment}"


def test_dimtimeframe_list_tfs_canonical(db_url):
    """Verify DimTimeframe.list_tfs returns canonical timeframes."""
    dim_tf = DimTimeframe.from_db(db_url)

    canonical_tfs = list(dim_tf.list_tfs(canonical_only=True))

    assert len(canonical_tfs) > 0, "No canonical timeframes found"
    assert "1D" in canonical_tfs, "1D not in canonical timeframes"


def test_dimtimeframe_tf_days_bounds_or_nominal(db_url):
    """Verify tf_days_bounds_or_nominal returns valid bounds."""
    dim_tf = DimTimeframe.from_db(db_url)

    min_days, max_days = dim_tf.tf_days_bounds_or_nominal("1D")

    assert min_days == 1, f"Expected min_days=1 for '1D', got {min_days}"
    assert max_days == 1, f"Expected max_days=1 for '1D', got {max_days}"
    assert min_days <= max_days, f"min_days ({min_days}) > max_days ({max_days})"
