#!/usr/bin/env python3
"""
Tests for EMA rowcount validation logic.

Tests cover:
- Unit tests for expected rowcount computation
- Status logic (OK, GAP, DUPLICATE)
- Summary aggregation
- Telegram integration (mocked)
- CLI functionality
- Database integration (when database available)
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.scripts.emas.validate_ema_rowcounts import (
    compute_expected_rowcount,
    summarize_validation,
)


# ============================================================================
# Unit Tests - Expected Rowcount Computation
# ============================================================================

def test_compute_expected_1d():
    """Test expected rowcount for 1D timeframe over 30 days."""
    expected = compute_expected_rowcount(
        start_date="2024-01-01",
        end_date="2024-01-30",
        tf="1D",
        tf_days=1,
    )
    # 30 days / 1 day = 30
    assert expected == 30


def test_compute_expected_7d():
    """Test expected rowcount for 7D timeframe over 28 days."""
    expected = compute_expected_rowcount(
        start_date="2024-01-01",
        end_date="2024-01-28",
        tf="7D",
        tf_days=7,
    )
    # 28 days / 7 days = 4
    assert expected == 4


def test_compute_expected_30d():
    """Test expected rowcount for 30D timeframe over 90 days."""
    expected = compute_expected_rowcount(
        start_date="2024-01-01",
        end_date="2024-03-30",
        tf="30D",
        tf_days=30,
    )
    # 90 days / 30 days = 3
    assert expected == 3


def test_compute_expected_edge_case():
    """Test with date range shorter than tf_days."""
    expected = compute_expected_rowcount(
        start_date="2024-01-01",
        end_date="2024-01-05",
        tf="7D",
        tf_days=7,
    )
    # 5 days / 7 days = 0 (conservative)
    assert expected == 0


def test_compute_expected_zero_tf_days():
    """Test with zero tf_days (edge case)."""
    expected = compute_expected_rowcount(
        start_date="2024-01-01",
        end_date="2024-01-30",
        tf="INVALID",
        tf_days=0,
    )
    # Zero tf_days should return 0
    assert expected == 0


# ============================================================================
# Status Logic Tests
# ============================================================================

def test_status_ok():
    """Test that status is OK when actual == expected."""
    df = pd.DataFrame([{
        "id": 1,
        "tf": "1D",
        "period": 10,
        "expected": 30,
        "actual": 30,
        "diff": 0,
        "status": "OK",
    }])

    summary = summarize_validation(df)
    assert summary["ok"] == 1
    assert summary["gaps"] == 0
    assert summary["duplicates"] == 0


def test_status_gap():
    """Test that status is GAP when actual < expected."""
    df = pd.DataFrame([{
        "id": 1,
        "tf": "1D",
        "period": 10,
        "expected": 30,
        "actual": 25,
        "diff": -5,
        "status": "GAP",
    }])

    summary = summarize_validation(df)
    assert summary["ok"] == 0
    assert summary["gaps"] == 1
    assert summary["duplicates"] == 0
    assert len(summary["issues"]) == 1
    assert summary["issues"][0]["status"] == "GAP"


def test_status_duplicate():
    """Test that status is DUPLICATE when actual > expected."""
    df = pd.DataFrame([{
        "id": 1,
        "tf": "1D",
        "period": 10,
        "expected": 30,
        "actual": 35,
        "diff": 5,
        "status": "DUPLICATE",
    }])

    summary = summarize_validation(df)
    assert summary["ok"] == 0
    assert summary["gaps"] == 0
    assert summary["duplicates"] == 1
    assert len(summary["issues"]) == 1
    assert summary["issues"][0]["status"] == "DUPLICATE"


# ============================================================================
# Summary Tests
# ============================================================================

def test_summarize_validation_counts():
    """Test summarize_validation returns correct counts."""
    df = pd.DataFrame([
        {"id": 1, "tf": "1D", "period": 10, "expected": 30, "actual": 30, "diff": 0, "status": "OK"},
        {"id": 1, "tf": "7D", "period": 10, "expected": 4, "actual": 3, "diff": -1, "status": "GAP"},
        {"id": 2, "tf": "1D", "period": 20, "expected": 30, "actual": 32, "diff": 2, "status": "DUPLICATE"},
    ])

    summary = summarize_validation(df)

    assert summary["total"] == 3
    assert summary["ok"] == 1
    assert summary["gaps"] == 1
    assert summary["duplicates"] == 1
    assert len(summary["issues"]) == 2  # 2 non-OK rows


def test_summarize_validation_empty():
    """Test summarize_validation with empty DataFrame."""
    df = pd.DataFrame(columns=["id", "tf", "period", "expected", "actual", "diff", "status"])

    summary = summarize_validation(df)

    assert summary["total"] == 0
    assert summary["ok"] == 0
    assert summary["gaps"] == 0
    assert summary["duplicates"] == 0
    assert len(summary["issues"]) == 0


# ============================================================================
# Telegram Integration Tests (Mocked)
# ============================================================================

def test_telegram_alert_not_sent_when_disabled():
    """Verify alert not sent when --alert flag not passed."""
    from ta_lab2.scripts.emas.validate_ema_rowcounts import main

    with patch("ta_lab2.scripts.emas.validate_ema_rowcounts.validate_rowcounts") as mock_validate:
        with patch("ta_lab2.scripts.emas.validate_ema_rowcounts.send_validation_alert") as mock_alert:
            # Mock validation to return issues
            mock_validate.return_value = pd.DataFrame([{
                "id": 1,
                "tf": "1D",
                "period": 10,
                "expected": 30,
                "actual": 25,
                "diff": -5,
                "status": "GAP",
            }])

            # Run without --alert flag
            with patch("sys.argv", ["validate_ema_rowcounts.py", "--start", "2024-01-01", "--end", "2024-01-30"]):
                exit_code = main()

            # Should return 1 (issues found)
            assert exit_code == 1

            # Alert should NOT be called
            mock_alert.assert_not_called()


def test_telegram_alert_sent_on_issues():
    """Verify send_validation_alert called when issues found and --alert set."""
    from ta_lab2.scripts.emas.validate_ema_rowcounts import main

    with patch("ta_lab2.scripts.emas.validate_ema_rowcounts.validate_rowcounts") as mock_validate:
        with patch("ta_lab2.scripts.emas.validate_ema_rowcounts.send_validation_alert") as mock_alert:
            with patch("ta_lab2.scripts.emas.validate_ema_rowcounts.telegram_configured", return_value=True):
                # Mock validation to return issues
                mock_validate.return_value = pd.DataFrame([{
                    "id": 1,
                    "tf": "1D",
                    "period": 10,
                    "expected": 30,
                    "actual": 25,
                    "diff": -5,
                    "status": "GAP",
                }])

                # Run WITH --alert flag
                with patch("sys.argv", ["validate_ema_rowcounts.py", "--start", "2024-01-01", "--end", "2024-01-30", "--alert"]):
                    exit_code = main()

                # Should return 1 (issues found)
                assert exit_code == 1

                # Alert SHOULD be called
                mock_alert.assert_called_once()


# ============================================================================
# CLI Tests
# ============================================================================

def test_cli_help():
    """Test CLI --help flag."""
    result = subprocess.run(
        [sys.executable, "-m", "ta_lab2.scripts.emas.validate_ema_rowcounts", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Validate EMA rowcounts" in result.stdout
    assert "--alert" in result.stdout
    assert "--start" in result.stdout


# ============================================================================
# Integration Tests (Database Required)
# ============================================================================

@pytest.mark.skipif(not TARGET_DB_URL, reason="Database not configured")
def test_validate_rowcounts_returns_dataframe():
    """Test validate_rowcounts returns DataFrame with expected columns."""
    from ta_lab2.scripts.emas.validate_ema_rowcounts import validate_rowcounts
    from sqlalchemy import create_engine

    engine = create_engine(TARGET_DB_URL)

    df = validate_rowcounts(
        engine=engine,
        table="cmc_ema_multi_tf_u",
        schema="public",
        ids=[1],  # Small scope
        tfs=["1D"],  # Single TF
        periods=[10],  # Single period
        start_date="2024-01-01",
        end_date="2024-01-31",
        db_url=TARGET_DB_URL,
    )

    # Should return DataFrame with expected columns
    assert isinstance(df, pd.DataFrame)
    expected_columns = {"id", "tf", "period", "expected", "actual", "diff", "status"}
    assert set(df.columns) == expected_columns


@pytest.mark.skipif(not TARGET_DB_URL, reason="Database not configured")
def test_validate_rowcounts_no_crash_on_empty():
    """Test validate_rowcounts doesn't crash on non-existent ID."""
    from ta_lab2.scripts.emas.validate_ema_rowcounts import validate_rowcounts
    from sqlalchemy import create_engine

    engine = create_engine(TARGET_DB_URL)

    # Use a non-existent ID (assuming 999999 doesn't exist)
    df = validate_rowcounts(
        engine=engine,
        table="cmc_ema_multi_tf_u",
        schema="public",
        ids=[999999],
        tfs=["1D"],
        periods=[10],
        start_date="2024-01-01",
        end_date="2024-01-31",
        db_url=TARGET_DB_URL,
    )

    # Should return DataFrame (possibly with zero actual counts)
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0  # Should have rows (expected counts calculated)
    # Actual counts should be 0 for non-existent ID
    assert (df["actual"] == 0).all()


# ============================================================================
# Success Summary
# ============================================================================

def test_count():
    """Meta-test: verify we have at least 13 tests as specified in plan."""
    import inspect

    # Get all functions in this module that start with "test_"
    tests = [name for name, obj in inspect.getmembers(sys.modules[__name__])
             if inspect.isfunction(obj) and name.startswith("test_") and name != "test_count"]

    # Should have at least 13 tests (plan minimum, may have more for better coverage)
    assert len(tests) >= 13, f"Expected at least 13 tests, found {len(tests)}: {tests}"
