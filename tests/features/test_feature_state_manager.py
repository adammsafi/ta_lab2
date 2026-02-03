"""
Unit tests for FeatureStateManager class.

Tests configuration, schema, initialization, state loading, dirty window computation,
and null strategy retrieval without requiring database connection.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import pandas as pd

from ta_lab2.scripts.features.feature_state_manager import (
    FeatureStateConfig,
    FeatureStateManager,
    UNIFIED_STATE_SCHEMA,
)


class TestFeatureStateConfig(unittest.TestCase):
    """Test FeatureStateConfig configuration class."""

    def test_feature_state_config_defaults(self):
        """Verify FeatureStateConfig defaults."""
        config = FeatureStateConfig()

        assert config.state_schema == "public"
        assert config.state_table == "cmc_feature_state"
        assert config.feature_type == "returns"
        assert config.ts_column == "ts"
        assert config.id_column == "id"

    def test_feature_state_config_custom(self):
        """Create config with custom values and verify all fields set."""
        config = FeatureStateConfig(
            state_schema="custom_schema",
            state_table="custom_feature_state",
            feature_type="vol",
            ts_column="timestamp",
            id_column="asset_id",
        )

        assert config.state_schema == "custom_schema"
        assert config.state_table == "custom_feature_state"
        assert config.feature_type == "vol"
        assert config.ts_column == "timestamp"
        assert config.id_column == "asset_id"


class TestUnifiedStateSchema(unittest.TestCase):
    """Test UNIFIED_STATE_SCHEMA SQL definition."""

    def test_unified_state_schema_has_pk(self):
        """Verify UNIFIED_STATE_SCHEMA string contains PRIMARY KEY (id, feature_type, feature_name)."""
        assert "PRIMARY KEY (id, feature_type, feature_name)" in UNIFIED_STATE_SCHEMA
        assert "id" in UNIFIED_STATE_SCHEMA
        assert "feature_type" in UNIFIED_STATE_SCHEMA
        assert "feature_name" in UNIFIED_STATE_SCHEMA

    def test_unified_state_schema_has_timestamps(self):
        """Verify schema has daily_min_seen, daily_max_seen, last_ts columns."""
        assert "daily_min_seen" in UNIFIED_STATE_SCHEMA
        assert "daily_max_seen" in UNIFIED_STATE_SCHEMA
        assert "last_ts" in UNIFIED_STATE_SCHEMA
        assert "TIMESTAMPTZ" in UNIFIED_STATE_SCHEMA

    def test_unified_state_schema_has_row_count(self):
        """Verify schema has row_count column for tracking feature rows."""
        assert "row_count" in UNIFIED_STATE_SCHEMA
        assert "INTEGER" in UNIFIED_STATE_SCHEMA


class TestManagerInitialization(unittest.TestCase):
    """Test FeatureStateManager initialization."""

    def test_manager_init(self):
        """Create FeatureStateManager with mock engine and config, verify attributes set."""
        mock_engine = Mock()
        config = FeatureStateConfig(state_schema="test", state_table="test_table")

        manager = FeatureStateManager(mock_engine, config)

        assert manager.engine is mock_engine
        assert manager.config is config
        assert manager.config.state_schema == "test"
        assert manager.config.state_table == "test_table"

    def test_manager_repr(self):
        """Verify __repr__ returns readable string with table info."""
        mock_engine = Mock()
        config = FeatureStateConfig(
            state_schema="public", state_table="cmc_feature_state", feature_type="vol"
        )
        manager = FeatureStateManager(mock_engine, config)

        repr_str = repr(manager)

        assert "FeatureStateManager" in repr_str
        assert "public.cmc_feature_state" in repr_str
        assert "feature_type=vol" in repr_str


class TestEnsureStateTable(unittest.TestCase):
    """Test ensure_state_table method."""

    def test_ensure_state_table_creates_table(self):
        """Verify ensure_state_table executes CREATE TABLE SQL."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        manager.ensure_state_table()

        # Verify connection.execute was called
        assert mock_conn.execute.called

        # Verify SQL contains CREATE TABLE
        call_args = mock_conn.execute.call_args
        sql_text = str(call_args[0][0])
        assert "CREATE TABLE IF NOT EXISTS" in sql_text
        assert "cmc_feature_state" in sql_text


class TestLoadState(unittest.TestCase):
    """Test load_state method with mocked database."""

    @patch("ta_lab2.scripts.features.feature_state_manager.pd.read_sql")
    def test_load_state_empty(self, mock_read_sql):
        """Mock pd.read_sql to return empty DataFrame, verify load_state returns empty DataFrame with correct columns."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        # Mock empty result
        empty_df = pd.DataFrame(
            columns=[
                "id",
                "feature_type",
                "feature_name",
                "daily_min_seen",
                "daily_max_seen",
                "last_ts",
                "row_count",
                "updated_at",
            ]
        )
        mock_read_sql.return_value = empty_df

        result = manager.load_state()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
        expected_cols = [
            "id",
            "feature_type",
            "feature_name",
            "daily_min_seen",
            "daily_max_seen",
            "last_ts",
            "row_count",
            "updated_at",
        ]
        assert all(col in result.columns for col in expected_cols)

    @patch("ta_lab2.scripts.features.feature_state_manager.pd.read_sql")
    def test_load_state_with_ids_filter(self, mock_read_sql):
        """Mock read_sql, call load_state(ids=[1]), verify SQL contains WHERE clause."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        # Mock successful result
        result_df = pd.DataFrame(
            {
                "id": [1],
                "feature_type": ["returns"],
                "feature_name": ["b2t_pct"],
                "daily_min_seen": [None],
                "daily_max_seen": [None],
                "last_ts": [pd.Timestamp("2024-01-01", tz="UTC")],
                "row_count": [100],
                "updated_at": [pd.Timestamp.now(tz="UTC")],
            }
        )
        mock_read_sql.return_value = result_df

        result = manager.load_state(ids=[1])

        # Verify pd.read_sql was called
        assert mock_read_sql.called

        # Verify SQL contains WHERE clause
        call_args = mock_read_sql.call_args
        sql_arg = str(call_args[0][0])

        assert "WHERE" in sql_arg
        assert "id = ANY(:ids)" in sql_arg or "id" in sql_arg

    @patch("ta_lab2.scripts.features.feature_state_manager.pd.read_sql")
    def test_load_state_with_feature_type_filter(self, mock_read_sql):
        """Mock read_sql, call load_state(feature_type='vol'), verify SQL contains feature_type filter."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        # Mock successful result
        result_df = pd.DataFrame(
            {
                "id": [1],
                "feature_type": ["vol"],
                "feature_name": ["parkinson_20"],
                "daily_min_seen": [None],
                "daily_max_seen": [None],
                "last_ts": [pd.Timestamp("2024-01-01", tz="UTC")],
                "row_count": [100],
                "updated_at": [pd.Timestamp.now(tz="UTC")],
            }
        )
        mock_read_sql.return_value = result_df

        result = manager.load_state(feature_type="vol")

        # Verify pd.read_sql was called
        assert mock_read_sql.called

        # Verify SQL contains feature_type filter
        call_args = mock_read_sql.call_args
        sql_arg = str(call_args[0][0])

        assert "WHERE" in sql_arg
        assert "feature_type = :feature_type" in sql_arg or "feature_type" in sql_arg

    @patch("ta_lab2.scripts.features.feature_state_manager.pd.read_sql")
    def test_load_state_with_feature_names_filter(self, mock_read_sql):
        """Mock read_sql, call load_state(feature_names=['rsi_14']), verify SQL contains feature_name filter."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        # Mock successful result
        result_df = pd.DataFrame(
            {
                "id": [1],
                "feature_type": ["ta"],
                "feature_name": ["rsi_14"],
                "daily_min_seen": [None],
                "daily_max_seen": [None],
                "last_ts": [pd.Timestamp("2024-01-01", tz="UTC")],
                "row_count": [100],
                "updated_at": [pd.Timestamp.now(tz="UTC")],
            }
        )
        mock_read_sql.return_value = result_df

        result = manager.load_state(feature_names=["rsi_14"])

        # Verify pd.read_sql was called
        assert mock_read_sql.called

        # Verify SQL contains feature_name filter
        call_args = mock_read_sql.call_args
        sql_arg = str(call_args[0][0])

        assert "WHERE" in sql_arg
        assert (
            "feature_name = ANY(:feature_names)" in sql_arg or "feature_name" in sql_arg
        )

    @patch("ta_lab2.scripts.features.feature_state_manager.pd.read_sql")
    def test_load_state_returns_empty_on_exception(self, mock_read_sql):
        """When pd.read_sql raises exception (table doesn't exist), load_state returns empty DataFrame."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        # Mock exception (table doesn't exist)
        mock_read_sql.side_effect = Exception("Table does not exist")

        result = manager.load_state()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
        expected_cols = [
            "id",
            "feature_type",
            "feature_name",
            "daily_min_seen",
            "daily_max_seen",
            "last_ts",
            "row_count",
            "updated_at",
        ]
        assert all(col in result.columns for col in expected_cols)


class TestUpdateStateFromOutput(unittest.TestCase):
    """Test update_state_from_output method."""

    def test_update_state_from_output_upserts(self):
        """Verify update_state_from_output executes UPSERT SQL."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_conn.execute.return_value = mock_result
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        config = FeatureStateConfig(feature_type="returns")
        manager = FeatureStateManager(mock_engine, config)

        rowcount = manager.update_state_from_output(
            output_table="cmc_returns_daily",
            output_schema="public",
            feature_name="b2t_pct",
        )

        # Verify connection.execute was called
        assert mock_conn.execute.called
        assert rowcount == 5

        # Verify SQL contains INSERT...ON CONFLICT
        call_args = mock_conn.execute.call_args
        sql_text = str(call_args[0][0])
        assert "INSERT INTO" in sql_text
        assert "ON CONFLICT" in sql_text
        assert "DO UPDATE SET" in sql_text
        assert "cmc_returns_daily" in sql_text


class TestDirtyWindowComputation(unittest.TestCase):
    """Test compute_dirty_window_starts method."""

    @patch.object(FeatureStateManager, "load_state")
    def test_compute_dirty_window_no_state(self, mock_load_state):
        """When load_state returns empty for an ID, dirty window should be default_start."""
        mock_engine = Mock()
        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        # Mock empty state
        empty_df = pd.DataFrame(
            columns=[
                "id",
                "feature_type",
                "feature_name",
                "daily_min_seen",
                "daily_max_seen",
                "last_ts",
                "row_count",
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

    @patch.object(FeatureStateManager, "load_state")
    def test_compute_dirty_window_with_state(self, mock_load_state):
        """When load_state has data, dirty window should be based on last_ts."""
        mock_engine = Mock()
        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        # Mock state with data
        state_df = pd.DataFrame(
            {
                "id": [1, 1, 2],
                "feature_type": ["returns", "returns", "returns"],
                "feature_name": ["b2t_pct", "log_return", "b2t_pct"],
                "daily_min_seen": [None, None, None],
                "daily_max_seen": [None, None, None],
                "last_ts": [
                    pd.Timestamp("2024-01-15", tz="UTC"),
                    pd.Timestamp("2024-01-20", tz="UTC"),
                    pd.Timestamp("2024-01-10", tz="UTC"),
                ],
                "row_count": [100, 100, 50],
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

    @patch.object(FeatureStateManager, "load_state")
    def test_compute_dirty_window_with_feature_type_filter(self, mock_load_state):
        """When feature_type is specified, compute_dirty_window_starts passes filter to load_state."""
        mock_engine = Mock()
        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        # Mock state with data
        state_df = pd.DataFrame(
            {
                "id": [1],
                "feature_type": ["vol"],
                "feature_name": ["parkinson_20"],
                "daily_min_seen": [None],
                "daily_max_seen": [None],
                "last_ts": [pd.Timestamp("2024-01-15", tz="UTC")],
                "row_count": [100],
                "updated_at": [pd.Timestamp.now(tz="UTC")],
            }
        )
        mock_load_state.return_value = state_df

        result = manager.compute_dirty_window_starts(
            ids=[1], feature_type="vol", default_start="2010-01-01"
        )

        # Verify load_state was called with feature_type filter
        mock_load_state.assert_called_once_with(ids=[1], feature_type="vol")

        assert len(result) == 1
        assert result[1] == pd.Timestamp("2024-01-15", tz="UTC")


class TestGetNullStrategy(unittest.TestCase):
    """Test get_null_strategy method."""

    def test_get_null_strategy_found(self):
        """When feature exists in dim_features, return its null_strategy."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("forward_fill",)
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        strategy = manager.get_null_strategy("vol_parkinson")

        assert strategy == "forward_fill"
        # Verify SQL was executed
        assert mock_conn.execute.called

    def test_get_null_strategy_not_found_returns_default(self):
        """When feature doesn't exist in dim_features, return default 'skip'."""
        # Create mock engine with proper context manager support
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None  # Not found
        mock_conn.execute.return_value = mock_result
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        config = FeatureStateConfig()
        manager = FeatureStateManager(mock_engine, config)

        strategy = manager.get_null_strategy("unknown_feature")

        assert strategy == "skip"


if __name__ == "__main__":
    unittest.main()
