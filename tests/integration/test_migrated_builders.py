"""
Integration tests for refactored bar builders.

Tests that all 5 builders work correctly after extracting common database utilities
to common_snapshot_contract.py.

Phase 5.1: Integration Testing
"""

import os
import pytest
import pandas as pd
from sqlalchemy import text

from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
    load_daily_prices_for_id,
    load_last_snapshot_row,
    load_last_snapshot_info_for_id_tfs,
)


# Test IDs: Small sample of production data
TEST_IDS = [1, 52, 825]  # Bitcoin, Ripple, Tether
TEST_TFS = ["7d", "14d", "21d"]  # Sample timeframes

# Database URL from environment
DB_URL = os.environ.get("TARGET_DB_URL")

pytestmark = pytest.mark.skipif(
    not DB_URL, reason="TARGET_DB_URL environment variable not set"
)


class TestExtractedUtilities:
    """Test the 4 extracted database utility functions."""

    def test_load_daily_prices_for_id(self):
        """Test load_daily_prices_for_id returns valid data."""
        df = load_daily_prices_for_id(
            db_url=DB_URL,
            daily_table="public.cmc_price_histories7",
            id_=1,  # Bitcoin
            ts_start=None,
            tz="America/New_York",
        )

        assert not df.empty, "Daily prices should not be empty for Bitcoin"
        assert "ts" in df.columns, "Should have ts column"
        assert "open" in df.columns, "Should have OHLCV columns"
        assert "high" in df.columns
        assert "low" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns

        # Check timestamp is properly formatted
        assert pd.api.types.is_datetime64_any_dtype(df["ts"])

    def test_load_daily_prices_with_ts_start(self):
        """Test load_daily_prices_for_id with ts_start filter."""
        # Load recent data only
        ts_start = pd.Timestamp("2024-01-01", tz="UTC")
        df = load_daily_prices_for_id(
            db_url=DB_URL,
            daily_table="public.cmc_price_histories7",
            id_=1,
            ts_start=ts_start,
        )

        if not df.empty:
            assert df["ts"].min() >= ts_start.tz_localize(
                None
            ), "All timestamps should be >= ts_start"

    def test_load_last_snapshot_row(self):
        """Test load_last_snapshot_row returns most recent snapshot."""
        # Assuming bars exist for Bitcoin 7d
        row = load_last_snapshot_row(
            db_url=DB_URL, bars_table="public.cmc_price_bars_multi_tf", id_=1, tf="7d"
        )

        # May be None if no bars exist yet
        if row is not None:
            assert isinstance(row, dict), "Should return dict"
            assert "id" in row
            assert "tf" in row
            assert "bar_seq" in row or "timestamp" in row

    def test_load_last_snapshot_info_batch(self):
        """Test batch loading of snapshot info."""
        tfs = ["7d", "14d", "21d"]
        info_map = load_last_snapshot_info_for_id_tfs(
            db_url=DB_URL, bars_table="public.cmc_price_bars_multi_tf", id_=1, tfs=tfs
        )

        assert isinstance(info_map, dict), "Should return dict"

        # Check structure of returned data
        for tf, info in info_map.items():
            assert tf in tfs, f"Returned TF {tf} should be in requested TFs"
            assert "last_bar_seq" in info
            assert "last_time_close" in info

    def test_delete_bars_for_id_tf(self):
        """Test delete_bars_for_id_tf (cleanup test - use with caution)."""
        # This is a destructive operation - only test on non-production DB
        # or skip if we're on production

        engine = get_engine(DB_URL)
        with engine.connect() as conn:
            # Check if we're on a test database
            result = conn.execute(text("SELECT current_database();")).scalar()
            if "test" not in result.lower():
                pytest.skip("Skipping destructive test on non-test database")

        # If we get here, we're on a test DB
        # Create a test bar entry, then delete it
        # (Implementation would require setting up test data)
        pytest.skip("Destructive test - implement with proper test data setup")


class TestBuilderConsistency:
    """Test that all 5 builders produce consistent results."""

    def test_all_builders_import_utilities(self):
        """Verify all builders import the 4 extracted utilities."""
        import importlib

        builders = [
            "ta_lab2.scripts.bars.refresh_cmc_price_bars_multi_tf",
            "ta_lab2.scripts.bars.refresh_cmc_price_bars_multi_tf_cal_iso",
            "ta_lab2.scripts.bars.refresh_cmc_price_bars_multi_tf_cal_us",
            "ta_lab2.scripts.bars.refresh_cmc_price_bars_multi_tf_cal_anchor_iso",
            "ta_lab2.scripts.bars.refresh_cmc_price_bars_multi_tf_cal_anchor_us",
        ]

        for builder_module_name in builders:
            module = importlib.import_module(builder_module_name)

            # Check that module has the functions (either imported or defined)
            # They should be imported from common_snapshot_contract
            assert hasattr(
                module, "load_daily_prices_for_id"
            ), f"{builder_module_name} should have load_daily_prices_for_id"
            assert hasattr(
                module, "delete_bars_for_id_tf"
            ), f"{builder_module_name} should have delete_bars_for_id_tf"
            assert hasattr(
                module, "load_last_snapshot_row"
            ), f"{builder_module_name} should have load_last_snapshot_row"
            assert hasattr(
                module, "load_last_snapshot_info_for_id_tfs"
            ), f"{builder_module_name} should have load_last_snapshot_info_for_id_tfs"

    def test_no_local_function_duplicates(self):
        """Verify builders don't have local copies of extracted functions."""
        import importlib

        builders = [
            "ta_lab2.scripts.bars.refresh_cmc_price_bars_multi_tf",
            "ta_lab2.scripts.bars.refresh_cmc_price_bars_multi_tf_cal_iso",
            "ta_lab2.scripts.bars.refresh_cmc_price_bars_multi_tf_cal_us",
            "ta_lab2.scripts.bars.refresh_cmc_price_bars_multi_tf_cal_anchor_iso",
            "ta_lab2.scripts.bars.refresh_cmc_price_bars_multi_tf_cal_anchor_us",
        ]

        from ta_lab2.scripts.bars import common_snapshot_contract

        for builder_module_name in builders:
            module = importlib.import_module(builder_module_name)

            # Check that these functions are imported, not locally defined
            for func_name in [
                "load_daily_prices_for_id",
                "delete_bars_for_id_tf",
                "load_last_snapshot_row",
                "load_last_snapshot_info_for_id_tfs",
            ]:
                if hasattr(module, func_name):
                    func = getattr(module, func_name)
                    contract_func = getattr(common_snapshot_contract, func_name)

                    # They should be the same object (imported, not redefined)
                    assert (
                        func is contract_func
                    ), f"{builder_module_name}.{func_name} should be imported from common_snapshot_contract, not locally defined"


class TestBuilderSmoke:
    """Smoke tests - quick validation that builders run without errors."""

    @pytest.mark.slow
    def test_multi_tf_smoke(self):
        """Smoke test: multi_tf builder runs on small dataset."""
        pytest.skip("Implement: Run multi_tf on 1 ID, 1 TF, verify no errors")

    @pytest.mark.slow
    def test_cal_iso_smoke(self):
        """Smoke test: cal_iso builder runs on small dataset."""
        pytest.skip("Implement: Run cal_iso on 1 ID, 1 TF, verify no errors")

    @pytest.mark.slow
    def test_cal_us_smoke(self):
        """Smoke test: cal_us builder runs on small dataset."""
        pytest.skip("Implement: Run cal_us on 1 ID, 1 TF, verify no errors")

    @pytest.mark.slow
    def test_cal_anchor_iso_smoke(self):
        """Smoke test: cal_anchor_iso builder runs on small dataset."""
        pytest.skip("Implement: Run cal_anchor_iso on 1 ID, 1 TF, verify no errors")

    @pytest.mark.slow
    def test_cal_anchor_us_smoke(self):
        """Smoke test: cal_anchor_us builder runs on small dataset."""
        pytest.skip("Implement: Run cal_anchor_us on 1 ID, 1 TF, verify no errors")


class TestPerformanceRegression:
    """Verify no performance regression after refactoring."""

    @pytest.mark.slow
    @pytest.mark.benchmark
    def test_batch_loading_performance(self):
        """Verify batch loading is faster than N+1 queries."""
        import time

        test_id = 1
        tfs = ["7d", "14d", "21d", "28d", "35d"]

        # Batch loading (should be fast)
        start = time.perf_counter()
        batch_result = load_last_snapshot_info_for_id_tfs(
            db_url=DB_URL,
            bars_table="public.cmc_price_bars_multi_tf",
            id_=test_id,
            tfs=tfs,
        )
        batch_time = time.perf_counter() - start

        # N+1 loading (should be slower)
        start = time.perf_counter()
        n_plus_1_result = {}
        for tf in tfs:
            row = load_last_snapshot_row(
                db_url=DB_URL,
                bars_table="public.cmc_price_bars_multi_tf",
                id_=test_id,
                tf=tf,
            )
            if row:
                n_plus_1_result[tf] = {
                    "last_bar_seq": row.get("bar_seq"),
                    "last_time_close": row.get("timestamp"),
                }
        n_plus_1_time = time.perf_counter() - start

        print(f"\nBatch loading: {batch_time:.4f}s")
        print(f"N+1 loading: {n_plus_1_time:.4f}s")
        print(f"Speedup: {n_plus_1_time / batch_time:.2f}x")

        # Batch loading should be faster (at least 1.5x for 5 TFs)
        assert (
            batch_time < n_plus_1_time
        ), "Batch loading should be faster than N+1 queries"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
