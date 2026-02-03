"""
DST handling validation tests for dim_sessions.

Tests DST transitions, session windows, and timezone validation.
Covers SUCCESS CRITERION #5 - DST handling validation tests.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo
import pytest

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.time.dim_sessions import DimSessions


def local_to_utc(d: date, t: time, tz: str) -> datetime:
    """Convert local date/time to UTC (helper function from existing test)."""
    z = ZoneInfo(tz)
    local = datetime.combine(d, t).replace(tzinfo=z)
    return local.astimezone(ZoneInfo("UTC"))


# ============================================================================
# Basic DST Tests (extend existing test_sessions_dst.py pattern)
# ============================================================================


def test_ny_winter_offset():
    """NY 9:30 local in January = 14:30 UTC (EST = UTC-5)."""
    tz = "America/New_York"
    open_t = time(9, 30)

    winter = local_to_utc(date(2025, 1, 15), open_t, tz)

    assert (
        winter.hour == 14 and winter.minute == 30
    ), f"Expected 9:30 EST to be 14:30 UTC, got {winter.hour}:{winter.minute} UTC"


def test_ny_summer_offset():
    """NY 9:30 local in July = 13:30 UTC (EDT = UTC-4)."""
    tz = "America/New_York"
    open_t = time(9, 30)

    summer = local_to_utc(date(2025, 7, 15), open_t, tz)

    assert (
        summer.hour == 13 and summer.minute == 30
    ), f"Expected 9:30 EDT to be 13:30 UTC, got {summer.hour}:{summer.minute} UTC"


def test_spring_forward_transition():
    """Test March DST transition day (US spring forward)."""
    tz = "America/New_York"
    open_t = time(9, 30)

    # Day before spring forward (2025-03-08)
    day_before = local_to_utc(date(2025, 3, 8), open_t, tz)
    # Day of spring forward (2025-03-09) - clocks jump from 2am to 3am
    day_of = local_to_utc(date(2025, 3, 9), open_t, tz)
    # Day after spring forward (2025-03-10)
    day_after = local_to_utc(date(2025, 3, 10), open_t, tz)

    # Before: EST (UTC-5) = 14:30 UTC
    assert (
        day_before.hour == 14
    ), f"Expected 14:30 UTC before DST, got {day_before.hour}:{day_before.minute}"

    # After: EDT (UTC-4) = 13:30 UTC
    assert (
        day_of.hour == 13
    ), f"Expected 13:30 UTC on DST transition, got {day_of.hour}:{day_of.minute}"
    assert (
        day_after.hour == 13
    ), f"Expected 13:30 UTC after DST, got {day_after.hour}:{day_after.minute}"


def test_fall_back_transition():
    """Test November DST transition day (US fall back)."""
    tz = "America/New_York"
    open_t = time(9, 30)

    # Day before fall back (2025-11-01)
    day_before = local_to_utc(date(2025, 11, 1), open_t, tz)
    # Day of fall back (2025-11-02) - clocks jump back from 2am to 1am
    day_of = local_to_utc(date(2025, 11, 2), open_t, tz)
    # Day after fall back (2025-11-03)
    day_after = local_to_utc(date(2025, 11, 3), open_t, tz)

    # Before: EDT (UTC-4) = 13:30 UTC
    assert (
        day_before.hour == 13
    ), f"Expected 13:30 UTC before fall back, got {day_before.hour}:{day_before.minute}"

    # After: EST (UTC-5) = 14:30 UTC
    assert (
        day_of.hour == 14
    ), f"Expected 14:30 UTC on fall back, got {day_of.hour}:{day_of.minute}"
    assert (
        day_after.hour == 14
    ), f"Expected 14:30 UTC after fall back, got {day_after.hour}:{day_after.minute}"


# ============================================================================
# Database Session Window Tests (requires TARGET_DB_URL)
# ============================================================================


@pytest.mark.skipif(not TARGET_DB_URL, reason="TARGET_DB_URL not configured")
def test_session_windows_span_dst():
    """Call session_windows_utc_by_key spanning March 8-12, verify no duplicate or missing dates."""
    ds = DimSessions.from_db()

    # Use actual CRYPTO session key from database (CMC venue with specific crypto)
    # Get first available crypto key
    crypto_keys = [k for k in ds._by_key.keys() if k.asset_class == "CRYPTO"]
    if not crypto_keys:
        pytest.skip("No CRYPTO sessions in database")

    key = crypto_keys[0]

    # Span DST transition (March 8-12, 2025)
    windows = ds.session_windows_utc_by_key(
        key=key,
        start_date=date(2025, 3, 8),
        end_date=date(2025, 3, 12),
        db_url=TARGET_DB_URL,
    )

    # Should have exactly 5 dates (no duplicates, no missing)
    assert len(windows) == 5, f"Expected 5 session windows, got {len(windows)}"

    # Check all dates are present
    expected_dates = [
        date(2025, 3, 8),
        date(2025, 3, 9),
        date(2025, 3, 10),
        date(2025, 3, 11),
        date(2025, 3, 12),
    ]

    actual_dates = [
        row.session_date if hasattr(row, "session_date") else row["session_date"]
        for _, row in windows.iterrows()
    ]

    for expected in expected_dates:
        assert expected in actual_dates, f"Missing date {expected} in session windows"


@pytest.mark.skipif(not TARGET_DB_URL, reason="TARGET_DB_URL not configured")
def test_session_windows_december_january():
    """Call across year boundary, verify correct handling."""
    ds = DimSessions.from_db()

    # Use actual CRYPTO session key from database
    crypto_keys = [k for k in ds._by_key.keys() if k.asset_class == "CRYPTO"]
    if not crypto_keys:
        pytest.skip("No CRYPTO sessions in database")

    key = crypto_keys[0]

    # Span year boundary (Dec 30, 2024 - Jan 3, 2025)
    windows = ds.session_windows_utc_by_key(
        key=key,
        start_date=date(2024, 12, 30),
        end_date=date(2025, 1, 3),
        db_url=TARGET_DB_URL,
    )

    # Should have exactly 5 dates
    assert (
        len(windows) == 5
    ), f"Expected 5 session windows across year boundary, got {len(windows)}"

    # Verify year transitions correctly
    actual_dates = [
        row.session_date if hasattr(row, "session_date") else row["session_date"]
        for _, row in windows.iterrows()
    ]

    assert date(2024, 12, 30) in actual_dates, "Missing Dec 30, 2024"
    assert date(2025, 1, 3) in actual_dates, "Missing Jan 3, 2025"


@pytest.mark.skipif(not TARGET_DB_URL, reason="TARGET_DB_URL not configured")
def test_crypto_session_no_dst():
    """Crypto 24h sessions should have consistent UTC times (no DST shift)."""
    ds = DimSessions.from_db()

    # Use actual CRYPTO session key from database
    crypto_keys = [k for k in ds._by_key.keys() if k.asset_class == "CRYPTO"]
    if not crypto_keys:
        pytest.skip("No CRYPTO sessions in database")

    key = crypto_keys[0]
    meta = ds.get_session_by_key(key)

    # Get windows spanning DST transition
    windows = ds.session_windows_utc_by_key(
        key=key,
        start_date=date(2025, 3, 8),
        end_date=date(2025, 3, 12),
        db_url=TARGET_DB_URL,
    )

    # Should have data
    assert len(windows) > 0, "Expected session windows for crypto"

    # Verify crypto session is marked as 24h and uses UTC timezone
    assert (
        meta.is_24h is True
    ), f"Expected crypto session to be 24h, got is_24h={meta.is_24h}"
    assert (
        meta.timezone == "UTC"
    ), f"Expected crypto session to use UTC timezone, got {meta.timezone}"

    # Verify all dates present (no duplicates or missing dates)
    expected_dates = [
        date(2025, 3, 8),
        date(2025, 3, 9),
        date(2025, 3, 10),
        date(2025, 3, 11),
        date(2025, 3, 12),
    ]
    actual_dates = [
        row.session_date if hasattr(row, "session_date") else row["session_date"]
        for _, row in windows.iterrows()
    ]

    for expected in expected_dates:
        assert (
            expected in actual_dates
        ), f"Missing date {expected} in crypto session windows"


# ============================================================================
# Timezone Validation
# ============================================================================


@pytest.mark.skipif(not TARGET_DB_URL, reason="TARGET_DB_URL not configured")
def test_iana_timezone_parsing():
    """Verify ZoneInfo parses all timezones in dim_sessions (no ValueError)."""
    ds = DimSessions.from_db()

    # Get all unique timezones from dim_sessions
    timezones = set()
    for meta in ds._by_key.values():
        timezones.add(meta.timezone)

    # Verify each timezone is valid IANA timezone
    for tz_name in timezones:
        try:
            ZoneInfo(tz_name)
        except Exception as e:
            pytest.fail(f"Invalid timezone '{tz_name}' in dim_sessions: {e}")


@pytest.mark.skipif(not TARGET_DB_URL, reason="TARGET_DB_URL not configured")
def test_no_numeric_offsets():
    """Query dim_sessions and verify no timezone values match pattern r'^[+-]\\d+' (no numeric offsets)."""
    import re

    ds = DimSessions.from_db()

    # Get all unique timezones
    timezones = set()
    for meta in ds._by_key.values():
        timezones.add(meta.timezone)

    # Check for numeric offset patterns like "+0500", "-0800", etc.
    numeric_offset_pattern = re.compile(r"^[+-]\d+")

    violations = []
    for tz_name in timezones:
        if numeric_offset_pattern.match(tz_name):
            violations.append(tz_name)

    assert (
        len(violations) == 0
    ), f"Found numeric timezone offsets (should use IANA names): {violations}"


# ============================================================================
# Edge Cases
# ============================================================================


@pytest.mark.skipif(not TARGET_DB_URL, reason="TARGET_DB_URL not configured")
def test_leap_year_feb29():
    """Verify session window for 2024-02-29 (leap year) works correctly."""
    ds = DimSessions.from_db()

    # Use actual CRYPTO session key from database
    crypto_keys = [k for k in ds._by_key.keys() if k.asset_class == "CRYPTO"]
    if not crypto_keys:
        pytest.skip("No CRYPTO sessions in database")

    key = crypto_keys[0]

    # Get window for Feb 29, 2024 (leap year)
    windows = ds.session_windows_utc_by_key(
        key=key,
        start_date=date(2024, 2, 29),
        end_date=date(2024, 2, 29),
        db_url=TARGET_DB_URL,
    )

    # Should have exactly 1 session window
    assert (
        len(windows) == 1
    ), f"Expected 1 session window for leap day, got {len(windows)}"

    # Verify date is correct
    actual_date = (
        windows.iloc[0].session_date
        if hasattr(windows.iloc[0], "session_date")
        else windows.iloc[0]["session_date"]
    )
    assert actual_date == date(2024, 2, 29), f"Expected Feb 29, 2024, got {actual_date}"
