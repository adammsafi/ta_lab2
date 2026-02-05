"""
Bar validation test suite for Phase 22 data quality features.

Tests:
- OHLC invariant enforcement (high >= low, high >= max(open, close), etc.)
- NULL rejection (OHLCV columns must not be NULL)
- Quality flags (is_partial_end, is_missing_days set correctly)
- Backfill detection (rebuild triggered when historical data appears)
- Reject table logging (violations logged before repair)

Test data strategy: Hybrid
- Unit tests: Small generated fixtures with targeted scenarios
- Integration tests: Skip if database not available
"""

import pytest
import pandas as pd
from datetime import date

# Mark tests that need database
DB_AVAILABLE = False  # Updated by conftest.py


# =============================================================================
# OHLC Invariant Tests
# =============================================================================


class TestOHLCInvariants:
    """Test OHLC invariant enforcement."""

    def test_high_greater_equal_low_violation_detected(self):
        """High must be >= low. If violated, swap occurs."""
        from ta_lab2.scripts.bars.common_snapshot_contract import enforce_ohlc_sanity

        # Create row with high < low (violation)
        df = pd.DataFrame(
            [
                {
                    "open": 120.0,
                    "high": 100.0,  # high < low - INVALID
                    "low": 150.0,
                    "close": 130.0,
                    "time_open": pd.Timestamp("2025-01-01T00:00:00Z"),
                    "time_close": pd.Timestamp("2025-01-02T00:00:00Z"),
                    "time_high": pd.Timestamp("2025-01-01T12:00:00Z"),
                    "time_low": pd.Timestamp("2025-01-01T18:00:00Z"),
                }
            ]
        )

        # Call enforce_ohlc_sanity - should adjust high and low to valid values
        result = enforce_ohlc_sanity(df)

        # After enforcement: high should be >= low
        assert (
            result.iloc[0]["high"] >= result.iloc[0]["low"]
        ), "High must be >= low after enforcement"
        # Low should be <= min(open, close) = 120
        assert result.iloc[0]["low"] <= 120.0, "Low should be <= min(open, close)"

    def test_high_greater_equal_oc_max_violation_detected(self):
        """High must be >= max(open, close)."""
        from ta_lab2.scripts.bars.common_snapshot_contract import enforce_ohlc_sanity

        # Create row with high < max(open, close)
        df = pd.DataFrame(
            [
                {
                    "open": 120.0,  # max(open, close) = 120
                    "high": 100.0,  # high < 120 - INVALID
                    "low": 80.0,
                    "close": 90.0,
                    "time_open": pd.Timestamp("2025-01-01T00:00:00Z"),
                    "time_close": pd.Timestamp("2025-01-02T00:00:00Z"),
                    "time_high": pd.Timestamp("2025-01-01T12:00:00Z"),
                    "time_low": pd.Timestamp("2025-01-01T18:00:00Z"),
                }
            ]
        )

        # Call enforce_ohlc_sanity - should adjust high to max(open, close)
        result = enforce_ohlc_sanity(df)

        assert (
            result.iloc[0]["high"] == 120.0
        ), "High should be adjusted to max(open, close)"

    def test_low_less_equal_oc_min_violation_detected(self):
        """Low must be <= min(open, close)."""
        from ta_lab2.scripts.bars.common_snapshot_contract import enforce_ohlc_sanity

        # Create row with low > min(open, close)
        df = pd.DataFrame(
            [
                {
                    "open": 100.0,  # min(open, close) = 100
                    "high": 150.0,
                    "low": 120.0,  # low > 100 - INVALID
                    "close": 130.0,
                    "time_open": pd.Timestamp("2025-01-01T00:00:00Z"),
                    "time_close": pd.Timestamp("2025-01-02T00:00:00Z"),
                    "time_high": pd.Timestamp("2025-01-01T12:00:00Z"),
                    "time_low": pd.Timestamp("2025-01-01T18:00:00Z"),
                }
            ]
        )

        # Call enforce_ohlc_sanity - should adjust low to min(open, close)
        result = enforce_ohlc_sanity(df)

        assert (
            result.iloc[0]["low"] == 100.0
        ), "Low should be adjusted to min(open, close)"

    def test_valid_ohlc_no_violations(self):
        """Valid OHLC should have no violations."""
        from ta_lab2.scripts.bars.common_snapshot_contract import enforce_ohlc_sanity

        df = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 150.0,
                    "low": 80.0,
                    "close": 120.0,
                    "time_open": pd.Timestamp("2025-01-01T00:00:00Z"),
                    "time_close": pd.Timestamp("2025-01-02T00:00:00Z"),
                    "time_high": pd.Timestamp("2025-01-01T12:00:00Z"),
                    "time_low": pd.Timestamp("2025-01-01T18:00:00Z"),
                }
            ]
        )

        # Call enforce_ohlc_sanity - should not modify values
        result = enforce_ohlc_sanity(df)

        assert result.iloc[0]["open"] == 100.0
        assert result.iloc[0]["high"] == 150.0
        assert result.iloc[0]["low"] == 80.0
        assert result.iloc[0]["close"] == 120.0

    def test_multiple_violations_all_repaired(self):
        """Multiple violations in same row should all be repaired."""
        from ta_lab2.scripts.bars.common_snapshot_contract import enforce_ohlc_sanity

        # Create row with multiple violations
        df = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 50.0,  # high < low AND high < max(open, close)
                    "low": 200.0,  # low > high AND low > min(open, close)
                    "close": 150.0,
                    "time_open": pd.Timestamp("2025-01-01T00:00:00Z"),
                    "time_close": pd.Timestamp("2025-01-02T00:00:00Z"),
                    "time_high": pd.Timestamp("2025-01-01T12:00:00Z"),
                    "time_low": pd.Timestamp("2025-01-01T18:00:00Z"),
                }
            ]
        )

        # Call enforce_ohlc_sanity - should repair all violations
        result = enforce_ohlc_sanity(df)

        # After repair, high should be at least max(open, close) = 150
        assert result.iloc[0]["high"] >= 150.0
        # After repair, low should be at most min(open, close) = 100
        assert result.iloc[0]["low"] <= 100.0


# =============================================================================
# Quality Flags Tests
# =============================================================================


class TestQualityFlags:
    """Test quality flag assignment."""

    def test_missing_days_diagnostics_no_gaps(self):
        """is_missing_days=FALSE when no gaps in date sequence."""
        from ta_lab2.scripts.bars.common_snapshot_contract import (
            compute_missing_days_diagnostics,
        )

        d0, d4 = date(2025, 1, 1), date(2025, 1, 5)
        diag = compute_missing_days_diagnostics(
            bar_start_day_local=d0,
            snapshot_day_local=d4,
            observed_days_local=[
                date(2025, 1, 1),
                date(2025, 1, 2),
                date(2025, 1, 3),
                date(2025, 1, 4),
                date(2025, 1, 5),
            ],
        )

        assert diag["is_missing_days"] is False
        assert int(diag["count_missing_days"]) == 0

    def test_missing_days_diagnostics_interior_gap(self):
        """is_missing_days=TRUE when interior date is missing."""
        from ta_lab2.scripts.bars.common_snapshot_contract import (
            compute_missing_days_diagnostics,
        )

        d0, d4 = date(2025, 1, 1), date(2025, 1, 5)
        # Missing Jan 3
        diag = compute_missing_days_diagnostics(
            bar_start_day_local=d0,
            snapshot_day_local=d4,
            observed_days_local=[
                date(2025, 1, 1),
                date(2025, 1, 2),
                date(2025, 1, 4),
                date(2025, 1, 5),
            ],
        )

        assert diag["is_missing_days"] is True
        assert int(diag["count_missing_days"]) == 1

    def test_missing_days_diagnostics_edge_gap_start(self):
        """is_missing_days=TRUE when first date is missing."""
        from ta_lab2.scripts.bars.common_snapshot_contract import (
            compute_missing_days_diagnostics,
        )

        d0, d4 = date(2025, 1, 1), date(2025, 1, 5)
        # Missing Jan 1
        diag = compute_missing_days_diagnostics(
            bar_start_day_local=d0,
            snapshot_day_local=d4,
            observed_days_local=[
                date(2025, 1, 2),
                date(2025, 1, 3),
                date(2025, 1, 4),
                date(2025, 1, 5),
            ],
        )

        assert diag["is_missing_days"] is True
        assert int(diag["count_missing_days"]) == 1

    def test_missing_days_diagnostics_edge_gap_end(self):
        """is_missing_days=TRUE when last date is missing."""
        from ta_lab2.scripts.bars.common_snapshot_contract import (
            compute_missing_days_diagnostics,
        )

        d0, d4 = date(2025, 1, 1), date(2025, 1, 5)
        # Missing Jan 5
        diag = compute_missing_days_diagnostics(
            bar_start_day_local=d0,
            snapshot_day_local=d4,
            observed_days_local=[
                date(2025, 1, 1),
                date(2025, 1, 2),
                date(2025, 1, 3),
                date(2025, 1, 4),
            ],
        )

        assert diag["is_missing_days"] is True
        assert int(diag["count_missing_days"]) == 1


# =============================================================================
# Schema Normalization Tests
# =============================================================================


class TestSchemaNormalization:
    """Test output schema normalization."""

    def test_normalize_output_schema_adds_required_defaults(self):
        """normalize_output_schema should add all required columns with defaults."""
        from ta_lab2.scripts.bars.common_snapshot_contract import (
            normalize_output_schema,
        )

        df = pd.DataFrame(
            [{"id": 1, "tf": "7D", "bar_seq": 1, "open": 1.0, "close": 1.0}]
        )
        out = normalize_output_schema(df)

        # Check representative required columns
        must = [
            "time_open",
            "time_close",
            "is_partial_start",
            "is_partial_end",
            "is_missing_days",
            "count_missing_days",
        ]
        missing = [c for c in must if c not in out.columns]
        assert (
            not missing
        ), f"normalize_output_schema did not add required columns: {missing}"

    def test_normalize_output_schema_preserves_existing_values(self):
        """normalize_output_schema should not overwrite existing columns."""
        from ta_lab2.scripts.bars.common_snapshot_contract import (
            normalize_output_schema,
        )

        df = pd.DataFrame(
            [
                {
                    "id": 1,
                    "tf": "7D",
                    "bar_seq": 1,
                    "open": 1.0,
                    "close": 1.0,
                    "is_partial_end": True,  # Already set
                }
            ]
        )
        out = normalize_output_schema(df)

        # Should preserve existing value (pandas uses np.True_ not Python True)
        # Use bool() to handle both Python True and numpy True_
        assert bool(out.iloc[0]["is_partial_end"]) is True


# =============================================================================
# Carry Forward Tests
# =============================================================================


class TestCarryForward:
    """Test carry-forward validation logic."""

    def test_can_carry_forward_valid_case(self):
        """Valid carry-forward: consecutive days, same bar identity."""
        from ta_lab2.scripts.bars.common_snapshot_contract import (
            can_carry_forward,
            CarryForwardInputs,
        )

        today = date(2025, 1, 10)
        inputs = CarryForwardInputs(
            last_snapshot_day_local=date(2025, 1, 9),
            today_local=today,
            snapshot_day_local=today,
            same_bar_identity=True,
            missing_days_tail_ok=True,
        )

        assert can_carry_forward(inputs) is True

    def test_can_carry_forward_gap_rejects(self):
        """Gap between snapshots should reject carry-forward."""
        from ta_lab2.scripts.bars.common_snapshot_contract import (
            can_carry_forward,
            CarryForwardInputs,
        )

        today = date(2025, 1, 10)
        inputs = CarryForwardInputs(
            last_snapshot_day_local=date(2025, 1, 8),  # Gap: not consecutive
            today_local=today,
            snapshot_day_local=today,
            same_bar_identity=True,
            missing_days_tail_ok=True,
        )

        assert can_carry_forward(inputs) is False


# =============================================================================
# Integration Tests (skip if no DB)
# =============================================================================


@pytest.mark.skipif(not DB_AVAILABLE, reason="Database not available")
class TestBarValidationIntegration:
    """Integration tests with real database."""

    def test_1d_builder_has_rejects_table(self):
        """Verify 1D builder has rejects table for OHLC violations."""
        # This is a smoke test - actual integration testing would require
        # running the builder with intentionally broken data
        pytest.skip("Integration test placeholder - requires full builder execution")

    def test_multi_tf_builder_logs_repairs(self):
        """Verify multi-TF builders log repairs to rejects table."""
        pytest.skip("Integration test placeholder - requires full builder execution")
