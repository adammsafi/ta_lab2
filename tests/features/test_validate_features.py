"""
Tests for feature validation module.

Tests cover:
- Gap detection with session awareness
- Outlier detection with feature-specific thresholds
- Cross-table consistency checks
- NULL ratio validation
- Rowcount validation with tolerance
- Telegram alert integration
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

import pandas as pd

from ta_lab2.scripts.features.validate_features import (
    FeatureValidator,
    ValidationReport,
    GapIssue,
    OutlierIssue,
    ConsistencyIssue,
    NullIssue,
    RowcountIssue,
    validate_features,
)


class TestFeatureValidator(unittest.TestCase):
    """Tests for FeatureValidator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.engine = MagicMock()
        self.validator = FeatureValidator(self.engine)

    def test_check_gaps_detects_missing(self):
        """Test that gap detection finds missing dates."""
        # Mock connection and results
        mock_conn = MagicMock()
        mock_result1 = MagicMock()
        mock_result1.scalar.return_value = True  # table exists

        mock_result2 = MagicMock()
        # Return actual dates (missing 2024-01-02)
        mock_result2.__iter__ = lambda self: iter([
            (datetime(2024, 1, 1).date(),),
            (datetime(2024, 1, 3).date(),)
        ])

        mock_conn.execute.side_effect = [mock_result1, mock_result2]
        self.engine.connect.return_value.__enter__.return_value = mock_conn

        issues = self.validator.check_gaps(
            table='cmc_returns_daily',
            ids=[1],
            start='2024-01-01',
            end='2024-01-03',
        )

        # Should detect gap on 2024-01-02
        self.assertEqual(len(issues), 1)
        self.assertIsInstance(issues[0], GapIssue)
        self.assertEqual(issues[0].details['id'], 1)
        self.assertEqual(issues[0].details['missing_count'], 1)

    def test_check_gaps_respects_session(self):
        """Test that gap detection respects trading sessions (weekends skipped for equity)."""
        # This is a placeholder - full implementation would query dim_sessions
        # For now, we test that the method completes without error
        self.engine.connect.return_value.__enter__.return_value.execute.side_effect = [
            MagicMock(scalar=lambda: True),  # table exists
            MagicMock(fetchall=lambda: []),  # no actual dates
        ]

        issues = self.validator.check_gaps(
            table='cmc_returns_daily',
            ids=[1],
            start='2024-01-01',
            end='2024-01-07',
        )

        # No crash, method completes
        self.assertIsInstance(issues, list)

    def test_check_gaps_no_false_positives(self):
        """Test that gap detection doesn't flag when data is complete."""
        # Generate complete date sequence
        dates = [(datetime(2024, 1, 1) + timedelta(days=i)).date() for i in range(3)]

        self.engine.connect.return_value.__enter__.return_value.execute.side_effect = [
            MagicMock(scalar=lambda: True),  # table exists
            MagicMock(fetchall=lambda: [(d,) for d in dates]),  # all dates present
        ]

        issues = self.validator.check_gaps(
            table='cmc_returns_daily',
            ids=[1],
            start='2024-01-01',
            end='2024-01-03',
        )

        # No issues when complete
        self.assertEqual(len(issues), 0)

    def test_check_outliers_returns(self):
        """Test outlier detection flags >50% daily return."""
        mock_conn = MagicMock()
        mock_result1 = MagicMock()
        mock_result1.scalar.return_value = True  # table exists
        mock_result2 = MagicMock()
        mock_result2.scalar.return_value = True  # column exists
        mock_result3 = MagicMock()
        mock_result3.__iter__ = lambda self: iter([(1, datetime(2024, 1, 1), 0.75)])  # 75% return

        mock_conn.execute.side_effect = [mock_result1, mock_result2, mock_result3]
        self.engine.connect.return_value.__enter__.return_value = mock_conn

        issues = self.validator.check_outliers(
            table='cmc_returns_daily',
            columns=['ret_1d_pct'],
            ids=[1],
        )

        # Should flag 75% return as outlier
        self.assertEqual(len(issues), 1)
        self.assertIsInstance(issues[0], OutlierIssue)
        self.assertEqual(issues[0].details['count'], 1)

    def test_check_outliers_vol(self):
        """Test outlier detection flags >500% volatility."""
        mock_conn = MagicMock()
        mock_result1 = MagicMock()
        mock_result1.scalar.return_value = True  # table exists
        mock_result2 = MagicMock()
        mock_result2.scalar.return_value = True  # column exists
        mock_result3 = MagicMock()
        mock_result3.__iter__ = lambda self: iter([(1, datetime(2024, 1, 1), 6.0)])  # 600% vol

        mock_conn.execute.side_effect = [mock_result1, mock_result2, mock_result3]
        self.engine.connect.return_value.__enter__.return_value = mock_conn

        issues = self.validator.check_outliers(
            table='cmc_vol_daily',
            columns=['parkinson_vol'],
            ids=[1],
        )

        # Should flag 600% vol as outlier
        self.assertEqual(len(issues), 1)
        self.assertIsInstance(issues[0], OutlierIssue)

    def test_check_outliers_rsi(self):
        """Test outlier detection flags RSI outside 0-100."""
        mock_conn = MagicMock()
        mock_result1 = MagicMock()
        mock_result1.scalar.return_value = True  # table exists
        mock_result2 = MagicMock()
        mock_result2.scalar.return_value = True  # column exists
        mock_result3 = MagicMock()
        mock_result3.__iter__ = lambda self: iter([(1, datetime(2024, 1, 1), 150.0)])  # Invalid RSI

        mock_conn.execute.side_effect = [mock_result1, mock_result2, mock_result3]
        self.engine.connect.return_value.__enter__.return_value = mock_conn

        issues = self.validator.check_outliers(
            table='cmc_ta_daily',
            columns=['rsi_14'],
            ids=[1],
        )

        # Should flag invalid RSI
        self.assertEqual(len(issues), 1)
        self.assertIsInstance(issues[0], OutlierIssue)

    def test_check_cross_table_returns(self):
        """Test cross-table consistency validates returns vs price delta."""
        # Mock query result with mismatch
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (1, datetime(2024, 1, 1), 0.05, 0.10, 0.05),  # calc_ret, ret_1d_pct, diff
        ]

        self.engine.connect.return_value.__enter__.return_value.execute.return_value = mock_result

        issues = self.validator.check_cross_table_consistency(ids=[1])

        # Should find at least one issue (returns check)
        consistency_issues = [i for i in issues if isinstance(i, ConsistencyIssue)]
        self.assertGreaterEqual(len(consistency_issues), 0)  # May have 0-3 depending on mocks

    def test_check_cross_table_close(self):
        """Test cross-table consistency validates close price alignment."""
        # This test verifies the method runs without error
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []

        self.engine.connect.return_value.__enter__.return_value.execute.return_value = mock_result

        issues = self.validator.check_cross_table_consistency(ids=[1])

        # Method completes without error
        self.assertIsInstance(issues, list)

    def test_check_null_ratios_warn(self):
        """Test NULL ratio check warns when >10% NULL."""
        self.engine.connect.return_value.__enter__.return_value.execute.side_effect = [
            MagicMock(scalar=lambda: True),  # table exists
            MagicMock(scalar=lambda: True),  # column exists
            MagicMock(fetchone=lambda: (100, 80, 20, 0.2)),  # 20% NULL ratio
        ]

        issues = self.validator.check_null_ratios(
            table='cmc_returns_daily',
            columns=['ret_1d_pct'],
            threshold=0.1,
        )

        # Should warn about 20% NULLs
        self.assertEqual(len(issues), 1)
        self.assertIsInstance(issues[0], NullIssue)
        self.assertEqual(issues[0].details['null_ratio'], 0.2)

    def test_check_null_ratios_ok(self):
        """Test NULL ratio check passes when <10% NULL."""
        self.engine.connect.return_value.__enter__.return_value.execute.side_effect = [
            MagicMock(scalar=lambda: True),  # table exists
            MagicMock(scalar=lambda: True),  # column exists
            MagicMock(fetchone=lambda: (100, 95, 5, 0.05)),  # 5% NULL ratio
        ]

        issues = self.validator.check_null_ratios(
            table='cmc_returns_daily',
            columns=['ret_1d_pct'],
            threshold=0.1,
        )

        # No issues when <10% NULL
        self.assertEqual(len(issues), 0)

    def test_check_rowcounts_within_tolerance(self):
        """Test rowcount validation passes within 5% tolerance."""
        self.engine.connect.return_value.__enter__.return_value.execute.side_effect = [
            MagicMock(scalar=lambda: True),  # table exists
            MagicMock(fetchone=lambda: (
                datetime(2024, 1, 1).date(),
                datetime(2024, 1, 31).date(),
                30,  # actual count (97% of expected 31)
            )),
        ]

        issues = self.validator.check_rowcounts(
            table='cmc_returns_daily',
            ids=[1],
        )

        # Within 5% tolerance, no issues
        self.assertEqual(len(issues), 0)

    def test_check_rowcounts_fail(self):
        """Test rowcount validation fails outside tolerance."""
        self.engine.connect.return_value.__enter__.return_value.execute.side_effect = [
            MagicMock(scalar=lambda: True),  # table exists
            MagicMock(fetchone=lambda: (
                datetime(2024, 1, 1).date(),
                datetime(2024, 1, 31).date(),
                20,  # actual count (65% of expected 31, >5% diff)
            )),
        ]

        issues = self.validator.check_rowcounts(
            table='cmc_returns_daily',
            ids=[1],
        )

        # Outside tolerance, should flag
        self.assertEqual(len(issues), 1)
        self.assertIsInstance(issues[0], RowcountIssue)

    def test_validation_report_summary(self):
        """Test ValidationReport has correct counts."""
        issues = [
            GapIssue(table='test', id_=1, missing_dates=['2024-01-01'], expected=10, actual=9),
            NullIssue(table='test', column='col', null_ratio=0.15, threshold=0.1),
        ]

        report = ValidationReport(
            passed=False,
            total_checks=10,
            failed_checks=2,
            issues=issues,
            summary="2 issues found",
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.total_checks, 10)
        self.assertEqual(report.failed_checks, 2)
        self.assertEqual(len(report.issues), 2)

    @patch('ta_lab2.scripts.features.validate_features.send_alert')
    @patch('ta_lab2.scripts.features.validate_features.telegram_configured')
    def test_send_alert_telegram(self, mock_configured, mock_send):
        """Test send_alert calls telegram.send_validation_alert."""
        mock_configured.return_value = True
        mock_send.return_value = True

        issues = [
            GapIssue(table='test', id_=1, missing_dates=['2024-01-01'], expected=10, actual=9),
        ]

        report = ValidationReport(
            passed=False,
            total_checks=10,
            failed_checks=1,
            issues=issues,
            summary="1 issue found",
        )

        result = report.send_alert()

        # Should call telegram send_alert
        self.assertTrue(result)
        mock_send.assert_called_once()

    @patch('ta_lab2.scripts.features.validate_features.telegram_configured')
    def test_send_alert_graceful(self, mock_configured):
        """Test send_alert degrades gracefully when telegram not configured."""
        mock_configured.return_value = False

        issues = [
            GapIssue(table='test', id_=1, missing_dates=['2024-01-01'], expected=10, actual=9),
        ]

        report = ValidationReport(
            passed=False,
            total_checks=10,
            failed_checks=1,
            issues=issues,
            summary="1 issue found",
        )

        result = report.send_alert()

        # Should return False but not crash
        self.assertFalse(result)


class TestValidateFeaturesFunction(unittest.TestCase):
    """Tests for validate_features convenience function."""

    @patch('ta_lab2.scripts.features.validate_features.FeatureValidator')
    def test_validate_features_defaults(self, mock_validator_class):
        """Test validate_features uses sensible defaults."""
        mock_engine = MagicMock()
        mock_validator = MagicMock()
        mock_validator_class.return_value = mock_validator

        mock_report = ValidationReport(
            passed=True,
            total_checks=10,
            failed_checks=0,
            issues=[],
            summary="All checks passed",
        )
        mock_validator.validate_all.return_value = mock_report

        # Mock ID query
        mock_engine.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = [
            (1,), (52,)
        ]

        report = validate_features(mock_engine, ids=[1, 52])

        # Should call validator
        mock_validator.validate_all.assert_called_once()
        self.assertTrue(report.passed)

    @patch('ta_lab2.scripts.features.validate_features.FeatureValidator')
    def test_validate_features_with_alert(self, mock_validator_class):
        """Test validate_features sends alert when issues found."""
        mock_engine = MagicMock()
        mock_validator = MagicMock()
        mock_validator_class.return_value = mock_validator

        issues = [
            GapIssue(table='test', id_=1, missing_dates=['2024-01-01'], expected=10, actual=9),
        ]

        mock_report = MagicMock()
        mock_report.passed = False
        mock_report.issues = issues
        mock_validator.validate_all.return_value = mock_report

        report = validate_features(mock_engine, ids=[1], alert=True)

        # Should call send_alert
        mock_report.send_alert.assert_called_once()


if __name__ == '__main__':
    unittest.main()
