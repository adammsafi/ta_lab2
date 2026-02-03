"""
Tests for DailyFeaturesStore and refresh_daily_features.

Tests unified feature store refresh logic including:
- Source watermark tracking
- Dirty window computation
- JOIN query structure
- Graceful handling of missing source tables
- End-to-end refresh flow
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import pandas as pd

from ta_lab2.scripts.features.daily_features_view import (
    DailyFeaturesStore,
    refresh_daily_features,
)


class TestDailyFeaturesStore(unittest.TestCase):
    """Tests for DailyFeaturesStore class."""

    def setUp(self):
        """Set up test fixtures."""
        self.engine = Mock()
        self.state_manager = Mock()
        self.store = DailyFeaturesStore(self.engine, self.state_manager)

    def test_check_source_tables_exist_all_present(self):
        """Test check_source_tables_exist when all tables present."""
        # Mock connection that returns True for all table existence checks
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.__exit__.return_value = None

        # All tables exist and have data
        mock_conn.execute.side_effect = [
            MagicMock(scalar=lambda: True),  # price_bars exists
            MagicMock(scalar=lambda: 10),  # price_bars has data
            MagicMock(scalar=lambda: True),  # emas exists
            MagicMock(scalar=lambda: 10),  # emas has data
            MagicMock(scalar=lambda: True),  # returns exists
            MagicMock(scalar=lambda: 10),  # returns has data
            MagicMock(scalar=lambda: True),  # vol exists
            MagicMock(scalar=lambda: 10),  # vol has data
            MagicMock(scalar=lambda: True),  # ta exists
            MagicMock(scalar=lambda: 10),  # ta has data
        ]

        self.engine.connect.return_value = mock_conn

        result = self.store.check_source_tables_exist()

        self.assertEqual(len(result), 5)
        self.assertTrue(result["price_bars"])
        self.assertTrue(result["emas"])
        self.assertTrue(result["returns"])
        self.assertTrue(result["vol"])
        self.assertTrue(result["ta"])

    def test_check_source_tables_exist_some_missing(self):
        """Test check_source_tables_exist with some tables missing."""
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.__exit__.return_value = None

        # price_bars and returns exist, others don't
        mock_conn.execute.side_effect = [
            MagicMock(scalar=lambda: True),  # price_bars exists
            MagicMock(scalar=lambda: 10),  # price_bars has data
            MagicMock(scalar=lambda: False),  # emas missing
            MagicMock(scalar=lambda: True),  # returns exists
            MagicMock(scalar=lambda: 10),  # returns has data
            MagicMock(scalar=lambda: False),  # vol missing
            MagicMock(scalar=lambda: False),  # ta missing
        ]

        self.engine.connect.return_value = mock_conn

        result = self.store.check_source_tables_exist()

        self.assertTrue(result["price_bars"])
        self.assertFalse(result["emas"])
        self.assertTrue(result["returns"])
        self.assertFalse(result["vol"])
        self.assertFalse(result["ta"])

    def test_get_source_watermarks_all_populated(self):
        """Test get_source_watermarks when all sources have state."""

        # Mock state manager to return different timestamps per feature type
        def mock_load_state(ids, feature_type):
            if feature_type == "price_bars":
                return pd.DataFrame(
                    {
                        "id": [1, 52],
                        "last_ts": ["2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"],
                    }
                )
            elif feature_type == "ema_multi_tf":
                return pd.DataFrame(
                    {
                        "id": [1, 52],
                        "last_ts": ["2024-01-05T00:00:00Z", "2024-01-06T00:00:00Z"],
                    }
                )
            elif feature_type == "returns":
                return pd.DataFrame(
                    {
                        "id": [1, 52],
                        "last_ts": ["2024-01-03T00:00:00Z", "2024-01-04T00:00:00Z"],
                    }
                )
            else:
                return pd.DataFrame()

        self.state_manager.load_state.side_effect = mock_load_state

        watermarks = self.store.get_source_watermarks([1, 52])

        # Should return MIN timestamp for each source
        self.assertEqual(watermarks["price_bars"], pd.Timestamp("2024-01-01T00:00:00Z"))
        self.assertEqual(watermarks["emas"], pd.Timestamp("2024-01-05T00:00:00Z"))
        self.assertEqual(watermarks["returns"], pd.Timestamp("2024-01-03T00:00:00Z"))

    def test_get_source_watermarks_missing_source(self):
        """Test get_source_watermarks with some sources missing state."""

        def mock_load_state(ids, feature_type):
            if feature_type == "price_bars":
                return pd.DataFrame({"id": [1], "last_ts": ["2024-01-01T00:00:00Z"]})
            else:
                # No state for other sources
                return pd.DataFrame()

        self.state_manager.load_state.side_effect = mock_load_state

        watermarks = self.store.get_source_watermarks([1])

        self.assertEqual(watermarks["price_bars"], pd.Timestamp("2024-01-01T00:00:00Z"))
        self.assertIsNone(watermarks["emas"])
        self.assertIsNone(watermarks["returns"])

    def test_compute_dirty_window_all_populated(self):
        """Test compute_dirty_window when all sources populated."""
        # Mock watermarks
        with patch.object(self.store, "get_source_watermarks") as mock_get:
            mock_get.return_value = {
                "price_bars": pd.Timestamp("2024-01-10T00:00:00Z"),
                "emas": pd.Timestamp("2024-01-08T00:00:00Z"),
                "returns": pd.Timestamp("2024-01-09T00:00:00Z"),
                "vol": pd.Timestamp("2024-01-07T00:00:00Z"),
                "ta": pd.Timestamp("2024-01-11T00:00:00Z"),
            }

            start, end = self.store.compute_dirty_window([1, 52])

            # Should use MIN of watermarks
            self.assertEqual(start, pd.Timestamp("2024-01-07T00:00:00Z"))
            self.assertIsInstance(end, pd.Timestamp)

    def test_compute_dirty_window_missing_source(self):
        """Test compute_dirty_window with missing sources."""
        with patch.object(self.store, "get_source_watermarks") as mock_get:
            mock_get.return_value = {
                "price_bars": pd.Timestamp("2024-01-10T00:00:00Z"),
                "emas": None,
                "returns": None,
                "vol": None,
                "ta": None,
            }

            start, end = self.store.compute_dirty_window([1])

            # Should use earliest valid watermark
            self.assertEqual(start, pd.Timestamp("2024-01-10T00:00:00Z"))

    def test_compute_dirty_window_no_state(self):
        """Test compute_dirty_window with no state (full refresh)."""
        with patch.object(self.store, "get_source_watermarks") as mock_get:
            mock_get.return_value = {
                "price_bars": None,
                "emas": None,
                "returns": None,
                "vol": None,
                "ta": None,
            }

            start, end = self.store.compute_dirty_window(
                [1], default_start="2020-01-01"
            )

            # Should use default_start
            self.assertEqual(start, pd.Timestamp("2020-01-01", tz="UTC"))

    def test_build_join_query_structure(self):
        """Test _build_join_query has correct SQL structure."""
        sources_available = {
            "price_bars": True,
            "emas": True,
            "returns": True,
            "vol": True,
            "ta": True,
        }

        query = self.store._build_join_query(
            ids=[1, 52],
            start="2024-01-01",
            end="2024-12-31",
            sources_available=sources_available,
        )

        # Check structure
        self.assertIn("INSERT INTO public.cmc_daily_features", query)
        self.assertIn("FROM public.cmc_price_bars_1d p", query)
        self.assertIn("LEFT JOIN public.dim_sessions s", query)
        self.assertIn("LEFT JOIN", query)  # Should have multiple LEFT JOINs

    def test_build_join_query_columns(self):
        """Test _build_join_query includes all feature columns."""
        sources_available = {
            "price_bars": True,
            "emas": True,
            "returns": True,
            "vol": True,
            "ta": True,
        }

        query = self.store._build_join_query(
            ids=[1],
            start="2024-01-01",
            end="2024-12-31",
            sources_available=sources_available,
        )

        # Check key columns present
        self.assertIn("ema_9", query)
        self.assertIn("ret_1d_pct", query)
        self.assertIn("vol_parkinson_20", query)
        self.assertIn("rsi_14", query)
        self.assertIn("asset_class", query)

    def test_build_join_query_missing_source_nulls(self):
        """Test _build_join_query uses NULL for missing sources."""
        sources_available = {
            "price_bars": True,
            "emas": False,  # Missing
            "returns": False,  # Missing
            "vol": True,
            "ta": True,
        }

        query = self.store._build_join_query(
            ids=[1],
            start="2024-01-01",
            end="2024-12-31",
            sources_available=sources_available,
        )

        # Should have NULL columns for missing sources
        self.assertIn("NULL as ema_9", query)
        self.assertIn("NULL as ret_1d_pct", query)
        # Should still have actual columns for available sources
        self.assertIn("v.vol_parkinson_20", query)
        self.assertIn("t.rsi_14", query)

    def test_refresh_for_ids_incremental(self):
        """Test refresh_for_ids incremental mode."""
        # Mock all dependencies
        with patch.object(
            self.store, "check_source_tables_exist"
        ) as mock_check, patch.object(
            self.store, "compute_dirty_window"
        ) as mock_window, patch.object(
            self.store, "_delete_dirty_rows"
        ) as mock_delete, patch.object(
            self.store, "_build_join_query"
        ) as mock_query, patch.object(self.store, "_update_state") as mock_update:
            mock_check.return_value = {
                "price_bars": True,
                "emas": True,
                "returns": True,
                "vol": True,
                "ta": True,
            }
            mock_window.return_value = (
                pd.Timestamp("2024-01-01", tz="UTC"),
                pd.Timestamp("2024-12-31", tz="UTC"),
            )
            mock_query.return_value = "INSERT INTO ... SELECT ..."

            # Mock engine execution
            mock_conn = MagicMock()
            mock_conn.__enter__.return_value = mock_conn
            mock_conn.__exit__.return_value = None
            mock_result = MagicMock()
            mock_result.rowcount = 100
            mock_conn.execute.return_value = mock_result
            self.engine.begin.return_value = mock_conn

            rows = self.store.refresh_for_ids(ids=[1, 52])

            # Verify flow
            mock_check.assert_called_once()
            mock_window.assert_called_once_with([1, 52])
            mock_delete.assert_called_once()
            mock_query.assert_called_once()
            mock_update.assert_called_once_with([1, 52])
            self.assertEqual(rows, 100)

    def test_refresh_for_ids_full_refresh(self):
        """Test refresh_for_ids full refresh mode."""
        with patch.object(
            self.store, "check_source_tables_exist"
        ) as mock_check, patch.object(
            self.store, "compute_dirty_window"
        ) as mock_window, patch.object(
            self.store, "_delete_dirty_rows"
        ) as mock_delete, patch.object(
            self.store, "_build_join_query"
        ) as mock_query, patch.object(self.store, "_update_state") as mock_update:
            mock_check.return_value = {
                "price_bars": True,
                "emas": False,
                "returns": False,
                "vol": False,
                "ta": False,
            }
            mock_window.return_value = (
                pd.Timestamp("2020-01-01", tz="UTC"),
                pd.Timestamp("2024-12-31", tz="UTC"),
            )
            mock_query.return_value = "INSERT INTO ... SELECT ..."

            mock_conn = MagicMock()
            mock_conn.__enter__.return_value = mock_conn
            mock_conn.__exit__.return_value = None
            mock_result = MagicMock()
            mock_result.rowcount = 500
            mock_conn.execute.return_value = mock_result
            self.engine.begin.return_value = mock_conn

            rows = self.store.refresh_for_ids(ids=[1], full_refresh=True)

            # Verify delete called with None (full delete)
            mock_delete.assert_called_once()
            args = mock_delete.call_args[0]
            self.assertEqual(args[0], [1])
            self.assertIsNone(args[1])  # start=None for full refresh

            self.assertEqual(rows, 500)

    def test_data_quality_flags_union(self):
        """Test that data quality flags combine source flags."""
        sources_available = {
            "price_bars": True,
            "emas": True,
            "returns": True,
            "vol": True,
            "ta": True,
        }

        query = self.store._build_join_query(
            ids=[1],
            start="2024-01-01",
            end="2024-12-31",
            sources_available=sources_available,
        )

        # Check has_price_gap logic
        self.assertIn("has_price_gap", query)
        self.assertIn("gap_days", query)

        # Check has_outlier union logic
        self.assertIn("has_outlier", query)
        self.assertIn("is_outlier", query)

    def test_asset_class_populated(self):
        """Test that asset_class is populated from dim_sessions."""
        sources_available = {
            "price_bars": True,
            "emas": False,
            "returns": False,
            "vol": False,
            "ta": False,
        }

        query = self.store._build_join_query(
            ids=[1],
            start="2024-01-01",
            end="2024-12-31",
            sources_available=sources_available,
        )

        # Check dim_sessions join
        self.assertIn("dim_sessions", query)
        self.assertIn("asset_class", query)

    def test_graceful_missing_source_table(self):
        """Test refresh continues when source table missing."""
        with patch.object(
            self.store, "check_source_tables_exist"
        ) as mock_check, patch.object(
            self.store, "compute_dirty_window"
        ) as mock_window, patch.object(
            self.store, "_delete_dirty_rows"
        ) as mock_delete, patch.object(
            self.store, "_build_join_query"
        ) as mock_query, patch.object(self.store, "_update_state") as mock_update:
            # Only price_bars available
            mock_check.return_value = {
                "price_bars": True,
                "emas": False,
                "returns": False,
                "vol": False,
                "ta": False,
            }
            mock_window.return_value = (
                pd.Timestamp("2024-01-01", tz="UTC"),
                pd.Timestamp("2024-12-31", tz="UTC"),
            )
            mock_query.return_value = "INSERT INTO ... SELECT ..."

            mock_conn = MagicMock()
            mock_conn.__enter__.return_value = mock_conn
            mock_conn.__exit__.return_value = None
            mock_result = MagicMock()
            mock_result.rowcount = 50
            mock_conn.execute.return_value = mock_result
            self.engine.begin.return_value = mock_conn

            # Should not raise error
            rows = self.store.refresh_for_ids(ids=[1])

            # Should still call query with sources_available
            mock_query.assert_called_once()
            call_args = mock_query.call_args
            # Check positional args - sources_available is 4th positional arg
            sources_available = call_args[0][3]
            self.assertFalse(sources_available["emas"])
            self.assertEqual(rows, 50)

    def test_graceful_empty_source(self):
        """Test NULL columns when source table empty."""
        # This is tested via _build_join_query with missing sources
        sources_available = {
            "price_bars": True,
            "emas": False,  # Empty/missing
            "returns": False,
            "vol": False,
            "ta": False,
        }

        query = self.store._build_join_query(
            ids=[1],
            start="2024-01-01",
            end="2024-12-31",
            sources_available=sources_available,
        )

        # Should have NULL columns
        null_count = query.count("NULL as ")
        self.assertGreater(null_count, 10)  # Many columns should be NULL


class TestRefreshFunction(unittest.TestCase):
    """Tests for refresh_daily_features convenience function."""

    @patch("ta_lab2.scripts.features.feature_state_manager.FeatureStateManager")
    @patch("ta_lab2.scripts.features.daily_features_view.DailyFeaturesStore")
    def test_refresh_daily_features_creates_components(
        self, mock_store_cls, mock_manager_cls
    ):
        """Test refresh_daily_features creates state manager and store."""
        mock_engine = MagicMock()
        mock_manager = MagicMock()
        mock_store = MagicMock()
        mock_manager_cls.return_value = mock_manager
        mock_store_cls.return_value = mock_store
        mock_store.refresh_for_ids.return_value = 100

        rows = refresh_daily_features(mock_engine, ids=[1, 52])

        # Verify state manager created and table ensured
        mock_manager_cls.assert_called_once()
        mock_manager.ensure_state_table.assert_called_once()

        # Verify store created with engine and manager
        mock_store_cls.assert_called_once_with(mock_engine, mock_manager)

        # Verify refresh called
        mock_store.refresh_for_ids.assert_called_once_with([1, 52], None, False)
        self.assertEqual(rows, 100)

    @patch("ta_lab2.scripts.features.feature_state_manager.FeatureStateManager")
    @patch("ta_lab2.scripts.features.daily_features_view.DailyFeaturesStore")
    def test_refresh_daily_features_passes_parameters(
        self, mock_store_cls, mock_manager_cls
    ):
        """Test refresh_daily_features passes parameters correctly."""
        mock_engine = MagicMock()
        mock_manager = MagicMock()
        mock_store = MagicMock()
        mock_manager_cls.return_value = mock_manager
        mock_store_cls.return_value = mock_store
        mock_store.refresh_for_ids.return_value = 200

        rows = refresh_daily_features(
            mock_engine, ids=[1], start="2024-01-01", full_refresh=True
        )

        # Verify parameters passed through
        mock_store.refresh_for_ids.assert_called_once_with([1], "2024-01-01", True)
        self.assertEqual(rows, 200)


if __name__ == "__main__":
    unittest.main()
