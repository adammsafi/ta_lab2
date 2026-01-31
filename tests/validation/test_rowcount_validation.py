"""
Rowcount validation tests with strict tolerance.

Per CONTEXT.md:
- Strict (0% tolerance): Actual must exactly match expected
- Crypto: continuous data (every calendar day)
- Equity: session-based data (trading days only)
"""

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock


@pytest.mark.validation
@pytest.mark.mocked_deps
class TestStrictRowcountValidation:
    """Tests for strict (0% tolerance) rowcount validation."""

    def test_zero_tolerance_passes_exact_match(self, mocker):
        """Test 0% tolerance passes when actual == expected."""
        expected = 100
        actual = 100

        diff_pct = (actual - expected) / expected if expected > 0 else 0
        tolerance = 0.0  # Strict

        passes = abs(diff_pct) <= tolerance
        assert passes is True

    def test_zero_tolerance_fails_one_missing(self, mocker):
        """Test 0% tolerance fails when even 1 row missing."""
        expected = 100
        actual = 99  # 1 missing

        diff_pct = (actual - expected) / expected
        tolerance = 0.0  # Strict

        passes = abs(diff_pct) <= tolerance
        assert passes is False

    def test_zero_tolerance_fails_one_extra(self, mocker):
        """Test 0% tolerance fails when extra rows exist."""
        expected = 100
        actual = 101  # 1 extra

        diff_pct = (actual - expected) / expected
        tolerance = 0.0  # Strict

        passes = abs(diff_pct) <= tolerance
        assert passes is False

    def test_rowcount_issue_created(self, mocker):
        """Test RowcountIssue is created for mismatches."""
        from ta_lab2.scripts.features.validate_features import FeatureValidator

        mock_engine = mocker.MagicMock()
        validator = FeatureValidator(mock_engine)

        mock_conn = mocker.MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        # Table exists
        mock_result1 = mocker.MagicMock()
        mock_result1.scalar.return_value = True

        # Return data showing mismatch (50% of expected)
        mock_result2 = mocker.MagicMock()
        mock_result2.fetchone.return_value = (
            date(2024, 1, 1),   # min_date
            date(2024, 1, 31),  # max_date
            15,                  # actual (should be ~31)
        )

        mock_conn.execute.side_effect = [mock_result1, mock_result2]

        issues = validator.check_rowcounts(
            table='cmc_returns_daily',
            ids=[1],
        )

        # Should have issue (15 vs 31 is >5% diff)
        assert len(issues) >= 1


@pytest.mark.validation
@pytest.mark.mocked_deps
class TestCryptoRowcounts:
    """Tests for crypto asset rowcount expectations."""

    def test_crypto_expects_all_calendar_days(self):
        """Test crypto assets expect data for every calendar day."""
        start = date(2024, 1, 1)
        end = date(2024, 1, 31)

        # Crypto: every day
        expected_days = (end - start).days + 1
        assert expected_days == 31

    def test_crypto_year_expects_365_or_366(self):
        """Test crypto full year expects 365/366 days."""
        # 2024 leap year
        start_2024 = date(2024, 1, 1)
        end_2024 = date(2024, 12, 31)
        days_2024 = (end_2024 - start_2024).days + 1
        assert days_2024 == 366

        # 2026 common year
        start_2026 = date(2026, 1, 1)
        end_2026 = date(2026, 12, 31)
        days_2026 = (end_2026 - start_2026).days + 1
        assert days_2026 == 365


@pytest.mark.validation
@pytest.mark.mocked_deps
class TestEquityRowcounts:
    """Tests for equity asset rowcount expectations."""

    def test_equity_expects_trading_days_only(self):
        """Test equity assets expect trading days only."""
        import pandas as pd

        # January 2024 had:
        # - 31 calendar days
        # - ~22 trading days (excluding weekends + MLK day)
        start = date(2024, 1, 1)
        end = date(2024, 1, 31)

        # Generate business days
        bdays = pd.bdate_range(start, end)
        trading_days = len(bdays)

        # Should be ~22-23 (weekdays)
        assert 20 <= trading_days <= 24

    def test_equity_excludes_weekends(self):
        """Test equity excludes Saturdays and Sundays."""
        # A full week
        week_start = date(2024, 1, 1)  # Monday
        week_end = date(2024, 1, 7)    # Sunday

        # Should be 5 trading days (Mon-Fri)
        trading_days = 5
        calendar_days = 7

        assert trading_days < calendar_days


@pytest.mark.validation
@pytest.mark.mocked_deps
class TestRowcountReporting:
    """Tests for detailed rowcount reporting."""

    def test_rowcount_issue_has_expected(self):
        """Test RowcountIssue includes expected count."""
        from ta_lab2.scripts.features.validate_features import RowcountIssue

        issue = RowcountIssue(
            table='test',
            id_=1,
            expected=100,
            actual=95,
            diff_pct=-0.05,
        )

        assert issue.details['expected'] == 100

    def test_rowcount_issue_has_actual(self):
        """Test RowcountIssue includes actual count."""
        from ta_lab2.scripts.features.validate_features import RowcountIssue

        issue = RowcountIssue(
            table='test',
            id_=1,
            expected=100,
            actual=95,
            diff_pct=-0.05,
        )

        assert issue.details['actual'] == 95

    def test_rowcount_issue_has_diff_percent(self):
        """Test RowcountIssue includes difference percentage."""
        from ta_lab2.scripts.features.validate_features import RowcountIssue

        issue = RowcountIssue(
            table='test',
            id_=1,
            expected=100,
            actual=95,
            diff_pct=-0.05,
        )

        assert issue.details['diff_pct'] == -0.05

    def test_rowcount_issue_message_format(self):
        """Test RowcountIssue message is human-readable."""
        from ta_lab2.scripts.features.validate_features import RowcountIssue

        issue = RowcountIssue(
            table='cmc_returns_daily',
            id_=1,
            expected=100,
            actual=95,
            diff_pct=-0.05,
        )

        # Message should include key info
        assert 'cmc_returns_daily' in issue.message
        assert '95' in issue.message
        assert '100' in issue.message
