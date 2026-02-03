"""
Validation tests for dim_sessions table and Python class.

Tests verify:
- Table exists in database
- Required columns are present
- Data is populated
- Python class can load from database
- Crypto sessions are 24-hour
- Timezone format is IANA standard (not numeric offsets)
"""

import pytest
from sqlalchemy import create_engine, text

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.time.dim_sessions import DimSessions, SessionKey

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


def test_dim_sessions_table_exists(engine):
    """Verify dim_sessions table exists in public schema."""
    query = text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = 'dim_sessions'
        )
    """
    )

    with engine.connect() as conn:
        result = conn.execute(query)
        exists = result.scalar()

    assert exists, "dim_sessions table does not exist in public schema"


def test_dim_sessions_has_required_columns(engine):
    """Verify all required columns exist in dim_sessions table."""
    required_columns = {
        "asset_class",
        "region",
        "venue",
        "asset_key_type",
        "asset_key",
        "session_type",
        "asset_id",
        "timezone",
        "session_open_local",
        "session_close_local",
        "is_24h",
    }

    query = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'dim_sessions'
    """
    )

    with engine.connect() as conn:
        result = conn.execute(query)
        actual_columns = {row[0] for row in result}

    missing_columns = required_columns - actual_columns
    assert not missing_columns, f"Missing required columns: {missing_columns}"


def test_dim_sessions_has_data(engine):
    """Verify dim_sessions has at least 1 row."""
    query = text("SELECT COUNT(*) FROM dim_sessions")

    with engine.connect() as conn:
        result = conn.execute(query)
        row_count = result.scalar()

    assert row_count >= 1, f"dim_sessions has {row_count} rows (expected at least 1)"


def test_dimsessions_from_db_loads(db_url):
    """Verify DimSessions.from_db loads successfully and has data."""
    dim_sessions = DimSessions.from_db(db_url)

    assert isinstance(
        dim_sessions, DimSessions
    ), "from_db did not return DimSessions instance"
    assert hasattr(dim_sessions, "_by_key"), "DimSessions missing _by_key attribute"
    assert len(dim_sessions._by_key) > 0, "DimSessions._by_key is empty"


def test_crypto_session_is_24h(engine):
    """Verify CRYPTO sessions have is_24h=True."""
    query = text(
        """
        SELECT is_24h
        FROM dim_sessions
        WHERE asset_class = 'CRYPTO'
        LIMIT 1
    """
    )

    with engine.connect() as conn:
        result = conn.execute(query)
        row = result.fetchone()

    if row is None:
        pytest.skip("No CRYPTO sessions found in dim_sessions")

    is_24h = row[0]
    assert is_24h is True, f"CRYPTO session has is_24h={is_24h} (expected True)"


def test_timezone_is_iana_format(engine):
    """Verify timezone column contains valid IANA timezone names (not numeric offsets)."""
    query = text(
        """
        SELECT DISTINCT timezone
        FROM dim_sessions
    """
    )

    with engine.connect() as conn:
        result = conn.execute(query)
        timezones = [row[0] for row in result]

    assert len(timezones) > 0, "No timezones found in dim_sessions"

    # IANA timezones are like 'UTC', 'America/New_York', 'Europe/London'
    # NOT like '+05:00' or '-08:00'
    invalid_timezones = []
    for tz in timezones:
        # Check for numeric offset patterns
        if tz.startswith("+") or tz.startswith("-"):
            invalid_timezones.append(tz)
        # IANA timezones should contain letters (not just numbers/symbols)
        elif not any(c.isalpha() for c in tz):
            invalid_timezones.append(tz)

    assert not invalid_timezones, (
        f"Found non-IANA timezone formats: {invalid_timezones}. "
        f"Expected IANA formats like 'UTC', 'America/New_York'"
    )


def test_dimsessions_get_session_by_key(db_url):
    """Verify DimSessions can retrieve session by SessionKey."""
    dim_sessions = DimSessions.from_db(db_url)

    # Try to get CRYPTO default session
    key = SessionKey(
        asset_class="CRYPTO",
        region="GLOBAL",
        venue="DEFAULT",
        asset_key_type="symbol",
        asset_key="*",
        session_type="RTH",
    )

    session = dim_sessions.get_session_by_key(key)

    if session is None:
        pytest.skip("CRYPTO default session not found")

    assert (
        session.timezone == "UTC"
    ), f"CRYPTO session timezone is {session.timezone} (expected UTC)"
    assert session.is_24h is True, "CRYPTO session should be 24-hour"


def test_equity_session_not_24h(engine):
    """Verify US EQUITY sessions have is_24h=False."""
    query = text(
        """
        SELECT is_24h
        FROM dim_sessions
        WHERE asset_class = 'EQUITY' AND region = 'US'
        LIMIT 1
    """
    )

    with engine.connect() as conn:
        result = conn.execute(query)
        row = result.fetchone()

    if row is None:
        pytest.skip("No US EQUITY sessions found in dim_sessions")

    is_24h = row[0]
    assert is_24h is False, f"US EQUITY session has is_24h={is_24h} (expected False)"
