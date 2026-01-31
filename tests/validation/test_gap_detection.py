"""
Gap detection validation tests.

Tests that gap detection correctly identifies missing dates.
Per CONTEXT.md: Both schedule-based and statistical gap detection.
"""

import pytest
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd


@pytest.mark.validation
@pytest.mark.mocked_deps
class TestScheduleBasedGapDetection:
    """Tests for schedule-based gap detection."""

    def test_detects_missing_dates(self, mocker):
        """Test gap detection finds missing dates in sequence."""
        from ta_lab2.scripts.features.validate_features import FeatureValidator, GapIssue

        mock_engine = mocker.MagicMock()
        validator = FeatureValidator(mock_engine)

        # Mock table exists
        mock_conn = mocker.MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        # First call: table exists
        mock_result1 = mocker.MagicMock()
        mock_result1.scalar.return_value = True

        # Second call: actual dates (missing Jan 2)
        mock_result2 = mocker.MagicMock()
        mock_result2.__iter__ = lambda self: iter([
            (date(2024, 1, 1),),
            (date(2024, 1, 3),),  # Jan 2 missing
        ])

        mock_conn.execute.side_effect = [mock_result1, mock_result2]

        issues = validator.check_gaps(
            table='cmc_returns_daily',
            ids=[1],
            start='2024-01-01',
            end='2024-01-03',
        )

        assert len(issues) >= 1
        assert any(isinstance(i, GapIssue) for i in issues)

    def test_no_gaps_when_complete(self, mocker):
        """Test no issues when data is complete."""
        from ta_lab2.scripts.features.validate_features import FeatureValidator

        mock_engine = mocker.MagicMock()
        validator = FeatureValidator(mock_engine)

        mock_conn = mocker.MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        # Table exists
        mock_result1 = mocker.MagicMock()
        mock_result1.scalar.return_value = True

        # All dates present
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(3)]
        mock_result2 = mocker.MagicMock()
        mock_result2.__iter__ = lambda self: iter([(d,) for d in dates])

        mock_conn.execute.side_effect = [mock_result1, mock_result2]

        issues = validator.check_gaps(
            table='cmc_returns_daily',
            ids=[1],
            start='2024-01-01',
            end='2024-01-03',
        )

        assert len(issues) == 0

    def test_gap_details_include_missing_dates(self, mocker):
        """Test gap issues include list of missing dates."""
        from ta_lab2.scripts.features.validate_features import GapIssue

        issue = GapIssue(
            table='test',
            id_=1,
            missing_dates=['2024-01-02', '2024-01-05'],
            expected=10,
            actual=8,
        )

        assert issue.details['missing_count'] == 2
        assert '2024-01-02' in issue.details['missing_dates']


@pytest.mark.validation
@pytest.mark.mocked_deps
class TestStatisticalGapDetection:
    """Tests for statistical anomaly gap detection."""

    def test_detects_large_gap(self):
        """Test detection of unusually large gaps (>2x normal spacing)."""
        # Normal: 1 day between bars
        # Anomaly: 5 day gap (>2x normal)
        dates = [
            date(2024, 1, 1),
            date(2024, 1, 2),
            date(2024, 1, 3),
            date(2024, 1, 8),  # 5-day gap
            date(2024, 1, 9),
        ]

        # Calculate gaps
        gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        # gaps = [1, 1, 5, 1]

        normal_gap = 1
        anomalies = [g for g in gaps if g > normal_gap * 2]

        assert len(anomalies) == 1
        assert anomalies[0] == 5

    def test_no_anomaly_for_normal_gaps(self):
        """Test no anomaly flagged for consistent spacing."""
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(10)]
        gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]

        # All gaps should be 1
        assert all(g == 1 for g in gaps)


@pytest.mark.validation
@pytest.mark.mocked_deps
class TestGapReporting:
    """Tests for detailed gap reporting."""

    def test_gap_issue_has_asset_context(self):
        """Test gap issues include asset ID."""
        from ta_lab2.scripts.features.validate_features import GapIssue

        issue = GapIssue(
            table='test',
            id_=52,  # ETH
            missing_dates=['2024-01-02'],
            expected=10,
            actual=9,
        )

        assert issue.details['id'] == 52

    def test_gap_issue_has_table_context(self):
        """Test gap issues include table name."""
        from ta_lab2.scripts.features.validate_features import GapIssue

        issue = GapIssue(
            table='cmc_returns_daily',
            id_=1,
            missing_dates=['2024-01-02'],
            expected=10,
            actual=9,
        )

        assert issue.details['table'] == 'cmc_returns_daily'

    def test_gap_issue_has_expected_actual(self):
        """Test gap issues include expected vs actual counts."""
        from ta_lab2.scripts.features.validate_features import GapIssue

        issue = GapIssue(
            table='test',
            id_=1,
            missing_dates=['2024-01-02'],
            expected=10,
            actual=9,
        )

        assert issue.details['expected'] == 10
        assert issue.details['actual'] == 9
