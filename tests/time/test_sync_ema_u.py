"""
test_sync_ema_u.py

Validation tests for sync_cmc_ema_multi_tf_u.py sync script.
Tests helper functions and sync script behavior.

Run:
    pytest tests/time/test_sync_ema_u.py -v
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine

from ta_lab2.scripts.emas.sync_cmc_ema_multi_tf_u import (
    SOURCES,
    alignment_source_from_table,
    build_select_expr,
    get_watermark,
    table_exists,
)


def test_sources_list():
    """Verify SOURCES contains 6 expected table names."""
    expected_sources = [
        "public.cmc_ema_multi_tf",
        "public.cmc_ema_multi_tf_v2",
        "public.cmc_ema_multi_tf_cal_us",
        "public.cmc_ema_multi_tf_cal_iso",
        "public.cmc_ema_multi_tf_cal_anchor_us",
        "public.cmc_ema_multi_tf_cal_anchor_iso",
    ]

    assert len(SOURCES) == 6, f"Expected 6 sources, got {len(SOURCES)}"

    for expected in expected_sources:
        assert expected in SOURCES, f"Expected source {expected} not found in SOURCES"


def test_alignment_source_extraction():
    """Test alignment_source_from_table extracts correct suffix."""
    test_cases = [
        ("public.cmc_ema_multi_tf", "multi_tf"),
        ("public.cmc_ema_multi_tf_v2", "multi_tf_v2"),
        ("public.cmc_ema_multi_tf_cal_us", "multi_tf_cal_us"),
        ("public.cmc_ema_multi_tf_cal_iso", "multi_tf_cal_iso"),
        ("public.cmc_ema_multi_tf_cal_anchor_us", "multi_tf_cal_anchor_us"),
        ("public.cmc_ema_multi_tf_cal_anchor_iso", "multi_tf_cal_anchor_iso"),
    ]

    for table_name, expected_source in test_cases:
        actual = alignment_source_from_table(table_name)
        assert actual == expected_source, (
            f"alignment_source_from_table('{table_name}') returned '{actual}', "
            f"expected '{expected_source}'"
        )


@pytest.fixture
def mock_engine():
    """Mock SQLAlchemy engine for testing."""
    return MagicMock()


def test_get_watermark_returns_none_for_empty(mock_engine):
    """Test get_watermark with empty result returns None (not crash)."""
    # Mock pd.read_sql to return DataFrame with NaT
    mock_df = pd.DataFrame({"wm": [pd.NaT]})

    with patch("ta_lab2.scripts.emas.sync_cmc_ema_multi_tf_u.pd.read_sql", return_value=mock_df):
        result = get_watermark(mock_engine, "multi_tf", prefer_ingested_at=False)

    assert result is None, "get_watermark should return None for empty/NaT result"


def test_build_select_expr_required_columns():
    """Test build_select_expr raises RuntimeError when required columns missing."""
    # Missing 'ema' column
    cols_missing_ema = ["id", "ts", "tf", "period"]

    with pytest.raises(RuntimeError) as exc_info:
        build_select_expr(cols_missing_ema, "multi_tf", use_ingested_filter=False)

    assert "missing required columns" in str(exc_info.value).lower()
    assert "ema" in str(exc_info.value).lower()

    # Missing 'id' column
    cols_missing_id = ["ts", "tf", "period", "ema"]

    with pytest.raises(RuntimeError) as exc_info:
        build_select_expr(cols_missing_id, "multi_tf", use_ingested_filter=False)

    assert "missing required columns" in str(exc_info.value).lower()
    assert "id" in str(exc_info.value).lower()


def test_build_select_expr_success():
    """Test build_select_expr with all required columns returns valid SQL."""
    # All required columns present
    cols_complete = [
        "id",
        "ts",
        "tf",
        "period",
        "ema",
        "ingested_at",
        "d1",
        "d2",
        "tf_days",
        "roll",
        "d1_roll",
        "d2_roll",
    ]

    select_sql, where_sql = build_select_expr(
        cols_complete,
        "multi_tf_v2",
        use_ingested_filter=True
    )

    # Verify SELECT clause contains expected elements
    assert "SELECT" in select_sql
    assert "id::int" in select_sql
    assert "ts" in select_sql
    assert "tf::text" in select_sql
    assert "period::int" in select_sql
    assert "ema::double precision" in select_sql
    assert ":alignment_source" in select_sql

    # Verify WHERE clause
    assert "WHERE" in where_sql
    assert "ingested_at > :wm" in where_sql

    # Test with use_ingested_filter=False
    select_sql2, where_sql2 = build_select_expr(
        cols_complete,
        "multi_tf_v2",
        use_ingested_filter=False
    )

    assert "WHERE" in where_sql2
    assert "ts > :wm" in where_sql2


def test_table_exists_helper():
    """Test table_exists correctly identifies existing vs non-existing tables."""
    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        pytest.skip("TARGET_DB_URL not set - skipping database test")

    engine = create_engine(db_url, future=True)

    # Test with table that should exist (unified table)
    exists_result = table_exists(engine, "public.cmc_ema_multi_tf_u")
    assert isinstance(exists_result, bool), "table_exists should return bool"

    # Test with table that definitely doesn't exist
    not_exists_result = table_exists(engine, "public.nonexistent_table_xyz_999")
    assert not_exists_result is False, "table_exists should return False for nonexistent table"
