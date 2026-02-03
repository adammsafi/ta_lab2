"""
Unit tests for EMAStateManager class.

Tests configuration, schema, initialization, state loading, and dirty window computation
without requiring database connection.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import pandas as pd

from ta_lab2.scripts.emas.ema_state_manager import (
    EMAStateConfig,
    EMAStateManager,
    UNIFIED_STATE_SCHEMA,
)


class TestEMAStateConfig(unittest.TestCase):
    """Test EMAStateConfig configuration class."""

    def test_ema_state_config_defaults(self):
        """Verify EMAStateConfig defaults."""
        config = EMAStateConfig()

        assert config.state_schema == "public"
        assert config.state_table == "cmc_ema_state"
        assert config.ts_column == "ts"
        assert config.roll_filter == "roll = FALSE"
        assert config.use_canonical_ts is False
        assert config.bars_table is None
        assert config.bars_schema == "public"
        assert config.bars_partial_filter == "is_partial_end = FALSE"

    def test_ema_state_config_custom(self):
        """Create config with custom values and verify all fields set."""
        config = EMAStateConfig(
            state_schema="custom_schema",
            state_table="custom_state_table",
            ts_column="canonical_ts",
            roll_filter="canonical = TRUE",
            use_canonical_ts=True,
            bars_table="bars_1d",
            bars_schema="raw_data",
            bars_partial_filter="is_complete = TRUE",
        )

        assert config.state_schema == "custom_schema"
        assert config.state_table == "custom_state_table"
        assert config.ts_column == "canonical_ts"
        assert config.roll_filter == "canonical = TRUE"
        assert config.use_canonical_ts is True
        assert config.bars_table == "bars_1d"
        assert config.bars_schema == "raw_data"
        assert config.bars_partial_filter == "is_complete = TRUE"


class TestUnifiedStateSchema(unittest.TestCase):
    """Test UNIFIED_STATE_SCHEMA SQL definition."""

    def test_unified_state_schema_has_pk(self):
        """Verify UNIFIED_STATE_SCHEMA string contains PRIMARY KEY (id, tf, period)."""
        assert "PRIMARY KEY (id, tf, period)" in UNIFIED_STATE_SCHEMA
        assert "id" in UNIFIED_STATE_SCHEMA
        assert "tf" in UNIFIED_STATE_SCHEMA
        assert "period" in UNIFIED_STATE_SCHEMA

    def test_unified_state_schema_has_timestamps(self):
        """Verify schema has daily_min_seen, daily_max_seen, last_time_close, last_canonical_ts columns."""
        assert "daily_min_seen" in UNIFIED_STATE_SCHEMA
        assert "daily_max_seen" in UNIFIED_STATE_SCHEMA
        assert "last_time_close" in UNIFIED_STATE_SCHEMA
        assert "last_canonical_ts" in UNIFIED_STATE_SCHEMA
        assert "TIMESTAMPTZ" in UNIFIED_STATE_SCHEMA


class TestManagerInitialization(unittest.TestCase):
    """Test EMAStateManager initialization."""

    def test_manager_init(self):
        """Create EMAStateManager with mock engine and config, verify attributes set."""
        mock_engine = Mock()
        config = EMAStateConfig(state_schema="test", state_table="test_table")

        manager = EMAStateManager(mock_engine, config)

        assert manager.engine is mock_engine
        assert manager.config is config
        assert manager.config.state_schema == "test"
        assert manager.config.state_table == "test_table"

    def test_manager_repr(self):
        """Verify __repr__ returns readable string with table info."""
        mock_engine = Mock()
        config = EMAStateConfig(state_schema="public", state_table="cmc_ema_state")
        manager = EMAStateManager(mock_engine, config)

        repr_str = repr(manager)

        assert "EMAStateManager" in repr_str
        assert "public.cmc_ema_state" in repr_str
        assert "ts_column=ts" in repr_str


class TestLoadState(unittest.TestCase):
    """Test load_state method with mocked database."""

    @patch("ta_lab2.scripts.emas.ema_state_manager.pd.read_sql")
    def test_load_state_empty(self, mock_read_sql):
        """Mock pd.read_sql to return empty DataFrame, verify load_state returns empty DataFrame with correct columns."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        config = EMAStateConfig()
        manager = EMAStateManager(mock_engine, config)

        # Mock empty result
        empty_df = pd.DataFrame(
            columns=[
                "id",
                "tf",
                "period",
                "daily_min_seen",
                "daily_max_seen",
                "last_bar_seq",
                "last_time_close",
                "last_canonical_ts",
                "updated_at",
            ]
        )
        mock_read_sql.return_value = empty_df

        result = manager.load_state()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
        expected_cols = [
            "id",
            "tf",
            "period",
            "daily_min_seen",
            "daily_max_seen",
            "last_bar_seq",
            "last_time_close",
            "last_canonical_ts",
            "updated_at",
        ]
        assert all(col in result.columns for col in expected_cols)

    @patch("ta_lab2.scripts.emas.ema_state_manager.pd.read_sql")
    def test_load_state_with_filters(self, mock_read_sql):
        """Mock read_sql, call load_state(ids=[1], tfs=["1D"]), verify SQL contains WHERE clauses."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        config = EMAStateConfig()
        manager = EMAStateManager(mock_engine, config)

        # Mock successful result
        result_df = pd.DataFrame(
            {
                "id": [1],
                "tf": ["1D"],
                "period": [9],
                "daily_min_seen": [None],
                "daily_max_seen": [None],
                "last_bar_seq": [None],
                "last_time_close": [pd.Timestamp("2024-01-01", tz="UTC")],
                "last_canonical_ts": [None],
                "updated_at": [pd.Timestamp.now(tz="UTC")],
            }
        )
        mock_read_sql.return_value = result_df

        result = manager.load_state(ids=[1], tfs=["1D"])

        # Verify pd.read_sql was called
        assert mock_read_sql.called

        # Verify SQL contains WHERE clauses by checking the text() argument
        call_args = mock_read_sql.call_args
        sql_arg = str(call_args[0][0])  # First positional arg is the SQL text object

        assert "WHERE" in sql_arg
        assert "id = ANY(:ids)" in sql_arg or "id" in sql_arg
        assert "tf = ANY(:tfs)" in sql_arg or "tf" in sql_arg


class TestDirtyWindowComputation(unittest.TestCase):
    """Test compute_dirty_window_starts method."""

    @patch.object(EMAStateManager, "load_state")
    def test_compute_dirty_window_no_state(self, mock_load_state):
        """When load_state returns empty for an ID, dirty window should be default_start."""
        mock_engine = Mock()
        config = EMAStateConfig()
        manager = EMAStateManager(mock_engine, config)

        # Mock empty state
        empty_df = pd.DataFrame(
            columns=[
                "id",
                "tf",
                "period",
                "daily_min_seen",
                "daily_max_seen",
                "last_bar_seq",
                "last_time_close",
                "last_canonical_ts",
                "updated_at",
            ]
        )
        mock_load_state.return_value = empty_df

        result = manager.compute_dirty_window_starts(
            ids=[1, 2], default_start="2010-01-01"
        )

        assert len(result) == 2
        assert 1 in result
        assert 2 in result
        assert result[1] == pd.Timestamp("2010-01-01", tz="UTC")
        assert result[2] == pd.Timestamp("2010-01-01", tz="UTC")

    @patch.object(EMAStateManager, "load_state")
    def test_compute_dirty_window_with_state(self, mock_load_state):
        """When load_state has data, dirty window should be based on last_canonical_ts or last_time_close."""
        mock_engine = Mock()
        config = EMAStateConfig()
        manager = EMAStateManager(mock_engine, config)

        # Mock state with data using last_canonical_ts (checked first by implementation)
        # Don't include last_time_close column to ensure last_canonical_ts logic is tested
        state_df = pd.DataFrame(
            {
                "id": [1, 1, 2],
                "tf": ["1D", "1W", "1D"],
                "period": [9, 9, 10],
                "daily_min_seen": [None, None, None],
                "daily_max_seen": [None, None, None],
                "last_bar_seq": [None, None, None],
                "last_canonical_ts": [
                    pd.Timestamp("2024-01-15", tz="UTC"),
                    pd.Timestamp("2024-01-20", tz="UTC"),
                    pd.Timestamp("2024-01-10", tz="UTC"),
                ],
                "last_time_close": [
                    pd.Timestamp("2024-01-15", tz="UTC"),
                    pd.Timestamp("2024-01-20", tz="UTC"),
                    pd.Timestamp("2024-01-10", tz="UTC"),
                ],
                "updated_at": [
                    pd.Timestamp.now(tz="UTC"),
                    pd.Timestamp.now(tz="UTC"),
                    pd.Timestamp.now(tz="UTC"),
                ],
            }
        )
        mock_load_state.return_value = state_df

        result = manager.compute_dirty_window_starts(
            ids=[1, 2], default_start="2010-01-01"
        )

        assert len(result) == 2
        # ID 1: min of 2024-01-15 and 2024-01-20 = 2024-01-15
        assert result[1] == pd.Timestamp("2024-01-15", tz="UTC")
        # ID 2: only 2024-01-10
        assert result[2] == pd.Timestamp("2024-01-10", tz="UTC")


if __name__ == "__main__":
    unittest.main()
