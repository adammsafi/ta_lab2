"""
DailyFeaturesStore - Unified daily feature store management.

This module manages cmc_daily_features, a materialized table joining all daily features:
- cmc_price_bars_1d (OHLCV)
- cmc_ema_multi_tf_u (EMAs for 1D timeframe)
- cmc_returns_daily (returns)
- cmc_vol_daily (volatility)
- cmc_ta_daily (technical indicators)

Design:
- Incremental refresh based on source table watermarks
- Graceful degradation when source tables missing
- Single-table access for ML pipelines

Usage:
    from ta_lab2.scripts.features.daily_features_view import DailyFeaturesStore

    store = DailyFeaturesStore(engine, state_manager)
    rows = store.refresh_for_ids(ids=[1, 52])
"""

from __future__ import annotations

from typing import Optional
import logging

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.scripts.features.feature_state_manager import FeatureStateManager

logger = logging.getLogger(__name__)


# =============================================================================
# DailyFeaturesStore Class
# =============================================================================


class DailyFeaturesStore:
    """
    Manages cmc_daily_features materialized table.

    Refresh pattern:
    1. Check which source tables exist and have data
    2. Identify dirty window (MIN of all source table watermarks)
    3. Delete rows in dirty window
    4. Re-materialize from source tables with JOIN query
    5. Update state

    Source tables (dependency order):
    1. cmc_price_bars_1d (base - required)
    2. cmc_ema_multi_tf_u (depends on bars - optional)
    3. cmc_returns_daily (depends on bars - optional)
    4. cmc_vol_daily (depends on bars - optional)
    5. cmc_ta_daily (depends on bars - optional)

    Graceful failure handling:
    - If source table missing: log warning, skip that source, continue with available
    - If source table empty for IDs: populate NULLs for those columns
    - Never fail entire refresh due to single source issue
    """

    # Source table definitions
    SOURCE_TABLES = {
        "price_bars": {
            "table": "cmc_price_bars_1d",
            "schema": "public",
            "required": True,
            "feature_type": "price_bars",
        },
        "emas": {
            "table": "cmc_ema_multi_tf_u",
            "schema": "public",
            "required": False,
            "feature_type": "ema_multi_tf",
        },
        "returns": {
            "table": "cmc_returns_daily",
            "schema": "public",
            "required": False,
            "feature_type": "returns",
        },
        "vol": {
            "table": "cmc_vol_daily",
            "schema": "public",
            "required": False,
            "feature_type": "vol",
        },
        "ta": {
            "table": "cmc_ta_daily",
            "schema": "public",
            "required": False,
            "feature_type": "ta",
        },
    }

    def __init__(self, engine: Engine, state_manager: FeatureStateManager):
        """
        Initialize DailyFeaturesStore.

        Args:
            engine: SQLAlchemy engine
            state_manager: FeatureStateManager for tracking refresh state
        """
        self.engine = engine
        self.state_manager = state_manager

    def check_source_tables_exist(self) -> dict[str, bool]:
        """
        Check which source tables exist and have data.

        Returns:
            Dictionary mapping source_key -> exists_with_data.
            Used for graceful degradation when source tables missing.
        """
        result = {}

        for source_key, source_info in self.SOURCE_TABLES.items():
            table_name = source_info["table"]
            schema_name = source_info["schema"]

            try:
                sql = text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = :schema
                          AND table_name = :table
                    )
                """
                )

                with self.engine.connect() as conn:
                    exists = conn.execute(
                        sql, {"schema": schema_name, "table": table_name}
                    ).scalar()

                    if exists:
                        # Check if has data
                        count_sql = text(
                            f"""
                            SELECT COUNT(*) FROM {schema_name}.{table_name} LIMIT 1
                        """
                        )
                        has_data = conn.execute(count_sql).scalar() > 0
                        result[source_key] = has_data
                    else:
                        result[source_key] = False

            except Exception as e:
                logger.warning(f"Error checking source table {table_name}: {e}")
                result[source_key] = False

        return result

    def get_source_watermarks(self, ids: list[int]) -> dict[str, pd.Timestamp]:
        """
        Get last refresh timestamp for each source table.

        Queries state manager for each feature_type to determine last_ts.

        Args:
            ids: List of asset IDs

        Returns:
            Dictionary mapping source_key -> min_timestamp across all IDs
        """
        watermarks = {}

        for source_key, source_info in self.SOURCE_TABLES.items():
            feature_type = source_info["feature_type"]

            try:
                # Load state for this feature type
                state_df = self.state_manager.load_state(
                    ids=ids, feature_type=feature_type
                )

                if state_df.empty:
                    watermarks[source_key] = None
                    continue

                # Get MIN of last_ts across all IDs (conservative)
                ts_series = pd.to_datetime(state_df["last_ts"], errors="coerce")
                ts_series = ts_series.dropna()

                if ts_series.empty:
                    watermarks[source_key] = None
                else:
                    watermarks[source_key] = ts_series.min()

            except Exception as e:
                logger.warning(f"Error getting watermark for {source_key}: {e}")
                watermarks[source_key] = None

        return watermarks

    def compute_dirty_window(
        self, ids: list[int], default_start: str = "2010-01-01"
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        """
        Compute dirty window requiring refresh.

        Start = MIN of source watermarks (most conservative)
        End = now()

        If any source has no state, use default_start.

        Args:
            ids: List of asset IDs
            default_start: Default start if no state found

        Returns:
            Tuple of (start_timestamp, end_timestamp)
        """
        watermarks = self.get_source_watermarks(ids)

        # Find minimum watermark across all sources
        valid_watermarks = [ts for ts in watermarks.values() if ts is not None]

        if not valid_watermarks:
            # No state found - full refresh from default
            start = pd.to_datetime(default_start, utc=True)
        else:
            # Start from earliest watermark
            start = min(valid_watermarks)

        # End = now
        end = pd.Timestamp.now(tz="UTC")

        return start, end

    def refresh_for_ids(
        self,
        ids: list[int],
        start: Optional[str] = None,
        full_refresh: bool = False,
    ) -> int:
        """
        Refresh cmc_daily_features for given IDs.

        Steps:
        1. Check source tables exist (graceful handling if missing)
        2. Compute dirty window if start not provided
        3. If full_refresh: DELETE WHERE id IN ids
           Else: DELETE WHERE id IN ids AND ts >= dirty_start
        4. INSERT from JOIN query (with LEFT JOINs for optional sources)
        5. Update state

        Args:
            ids: List of asset IDs to refresh
            start: Optional start date (ISO format). If None, computed from state.
            full_refresh: If True, delete all rows for IDs before refresh

        Returns:
            Number of rows inserted
        """
        if not ids:
            logger.warning("No IDs provided for refresh")
            return 0

        # 1. Check which source tables exist
        sources_available = self.check_source_tables_exist()
        logger.info(f"Source tables available: {sources_available}")

        # Require price_bars at minimum
        if not sources_available.get("price_bars", False):
            logger.error(
                "Required table cmc_price_bars_1d not available - cannot refresh"
            )
            return 0

        # 2. Compute dirty window
        if start is None:
            dirty_start, dirty_end = self.compute_dirty_window(ids)
        else:
            dirty_start = pd.to_datetime(start, utc=True)
            dirty_end = pd.Timestamp.now(tz="UTC")

        logger.info(f"Dirty window: {dirty_start} to {dirty_end}")

        # 3. Delete existing rows in dirty window
        self._delete_dirty_rows(ids, dirty_start if not full_refresh else None)

        # 4. Insert refreshed data
        join_query = self._build_join_query(
            ids, dirty_start.isoformat(), dirty_end.isoformat(), sources_available
        )

        with self.engine.begin() as conn:
            result = conn.execute(text(join_query))
            rows_inserted = result.rowcount

        logger.info(f"Inserted {rows_inserted} rows into cmc_daily_features")

        # 5. Update state
        self._update_state(ids)

        return rows_inserted

    def _delete_dirty_rows(
        self, ids: list[int], start: Optional[pd.Timestamp] = None
    ) -> int:
        """
        Delete existing rows in dirty window.

        Args:
            ids: List of asset IDs
            start: Optional start timestamp. If None, delete all for IDs.

        Returns:
            Number of rows deleted
        """
        where_clause = "id = ANY(:ids)"
        params = {"ids": ids}

        if start is not None:
            where_clause += " AND ts >= :start"
            params["start"] = start

        delete_sql = f"""
            DELETE FROM public.cmc_daily_features
            WHERE {where_clause}
        """

        with self.engine.begin() as conn:
            result = conn.execute(text(delete_sql), params)
            rows_deleted = result.rowcount

        logger.info(f"Deleted {rows_deleted} rows from dirty window")
        return rows_deleted

    def _build_join_query(
        self, ids: list[int], start: str, end: str, sources_available: dict[str, bool]
    ) -> str:
        """
        Build the JOIN query to materialize features.

        Strategy:
        - Start from cmc_price_bars_1d (required)
        - LEFT JOIN each optional source (EMAs, returns, vol, TA)
        - Use LEFT JOINs so missing sources result in NULL columns

        Args:
            ids: List of asset IDs
            start: Start date (ISO format)
            end: End date (ISO format)
            sources_available: Dict of which sources are available

        Returns:
            SQL INSERT query string
        """
        ids_list = ",".join(str(id_) for id_ in ids)

        # Build SELECT columns
        select_cols = [
            "p.id",
            'p."timestamp" as ts',
            "s.asset_class",
            # OHLCV from price_bars
            "p.open_price as open",
            "p.high_price as high",
            "p.low_price as low",
            "p.close_price as close",
            "p.volume",
        ]

        # EMAs (pivoted from long format)
        if sources_available.get("emas", False):
            select_cols.extend(
                [
                    "e9.ema as ema_9",
                    "e10.ema as ema_10",
                    "e21.ema as ema_21",
                    "e50.ema as ema_50",
                    "e200.ema as ema_200",
                    "e9.ema_d1 as ema_9_d1",
                    "e21.ema_d1 as ema_21_d1",
                ]
            )
        else:
            select_cols.extend(
                [
                    "NULL as ema_9",
                    "NULL as ema_10",
                    "NULL as ema_21",
                    "NULL as ema_50",
                    "NULL as ema_200",
                    "NULL as ema_9_d1",
                    "NULL as ema_21_d1",
                ]
            )

        # Returns
        if sources_available.get("returns", False):
            select_cols.extend(
                [
                    "r.ret_1d_pct",
                    "r.ret_1d_log",
                    "r.ret_7d_pct",
                    "r.ret_30d_pct",
                    "r.ret_1d_pct_zscore",
                    "r.gap_days",
                ]
            )
        else:
            select_cols.extend(
                [
                    "NULL as ret_1d_pct",
                    "NULL as ret_1d_log",
                    "NULL as ret_7d_pct",
                    "NULL as ret_30d_pct",
                    "NULL as ret_1d_pct_zscore",
                    "NULL as gap_days",
                ]
            )

        # Volatility
        if sources_available.get("vol", False):
            select_cols.extend(
                [
                    "v.vol_parkinson_20",
                    "v.vol_gk_20",
                    "v.vol_parkinson_20_zscore",
                    "v.atr_14",
                ]
            )
        else:
            select_cols.extend(
                [
                    "NULL as vol_parkinson_20",
                    "NULL as vol_gk_20",
                    "NULL as vol_parkinson_20_zscore",
                    "NULL as atr_14",
                ]
            )

        # Technical indicators
        if sources_available.get("ta", False):
            select_cols.extend(
                [
                    "t.rsi_14",
                    "t.rsi_21",
                    "t.macd_12_26",
                    "t.macd_signal_9",
                    "t.macd_hist_12_26_9",
                    "t.stoch_k_14",
                    "t.stoch_d_3",
                    "t.bb_ma_20",
                    "t.bb_width_20",
                    "t.adx_14",
                ]
            )
        else:
            select_cols.extend(
                [
                    "NULL as rsi_14",
                    "NULL as rsi_21",
                    "NULL as macd_12_26",
                    "NULL as macd_signal_9",
                    "NULL as macd_hist_12_26_9",
                    "NULL as stoch_k_14",
                    "NULL as stoch_d_3",
                    "NULL as bb_ma_20",
                    "NULL as bb_width_20",
                    "NULL as adx_14",
                ]
            )

        # Data quality flags
        # For now, simple heuristics - can be enhanced
        select_cols.extend(
            [
                "CASE WHEN r.gap_days > 1 THEN TRUE ELSE FALSE END as has_price_gap",
                "CASE WHEN r.is_outlier OR v.vol_parkinson_20_is_outlier OR t.is_outlier THEN TRUE ELSE FALSE END as has_outlier",
                "now() as updated_at",
            ]
        )

        # Build JOINs
        joins = []

        # Base: price_bars + dim_sessions for asset_class
        joins.append(
            """
            FROM public.cmc_price_bars_1d p
            LEFT JOIN public.dim_sessions s ON p.id = s.id
        """
        )

        # EMAs (need multiple joins for different periods, filtered to 1D tf)
        if sources_available.get("emas", False):
            joins.append(
                """
                LEFT JOIN (SELECT id, ts, ema, ema_d1 FROM public.cmc_ema_multi_tf_u WHERE period = 9 AND tf = '1D') e9
                  ON p.id = e9.id AND p."timestamp" = e9.ts
                LEFT JOIN (SELECT id, ts, ema, ema_d1 FROM public.cmc_ema_multi_tf_u WHERE period = 10 AND tf = '1D') e10
                  ON p.id = e10.id AND p."timestamp" = e10.ts
                LEFT JOIN (SELECT id, ts, ema, ema_d1 FROM public.cmc_ema_multi_tf_u WHERE period = 21 AND tf = '1D') e21
                  ON p.id = e21.id AND p."timestamp" = e21.ts
                LEFT JOIN (SELECT id, ts, ema, ema_d1 FROM public.cmc_ema_multi_tf_u WHERE period = 50 AND tf = '1D') e50
                  ON p.id = e50.id AND p."timestamp" = e50.ts
                LEFT JOIN (SELECT id, ts, ema, ema_d1 FROM public.cmc_ema_multi_tf_u WHERE period = 200 AND tf = '1D') e200
                  ON p.id = e200.id AND p."timestamp" = e200.ts
            """
            )

        # Returns
        if sources_available.get("returns", False):
            joins.append(
                """
                LEFT JOIN public.cmc_returns_daily r ON p.id = r.id AND p."timestamp" = r.ts
            """
            )

        # Volatility
        if sources_available.get("vol", False):
            joins.append(
                """
                LEFT JOIN public.cmc_vol_daily v ON p.id = v.id AND p."timestamp" = v.ts
            """
            )

        # TA
        if sources_available.get("ta", False):
            joins.append(
                """
                LEFT JOIN public.cmc_ta_daily t ON p.id = t.id AND p."timestamp" = t.ts
            """
            )

        # WHERE clause
        where_clause = f"""
            WHERE p.id IN ({ids_list})
              AND p."timestamp" >= '{start}'
              AND p."timestamp" <= '{end}'
        """

        # Build complete query
        query = f"""
            INSERT INTO public.cmc_daily_features (
                {", ".join([col.split(" as ")[-1] if " as " in col else col.split(".")[-1] for col in select_cols])}
            )
            SELECT
                {", ".join(select_cols)}
            {"".join(joins)}
            {where_clause}
        """

        return query

    def _update_state(self, ids: list[int]) -> None:
        """
        Update state after successful refresh.

        Args:
            ids: List of asset IDs that were refreshed
        """
        try:
            # Update state using feature_type='daily_features'
            self.state_manager.update_state_from_output(
                output_table="cmc_daily_features",
                output_schema="public",
                feature_name="unified",
            )
            logger.info("Updated state for daily_features")
        except Exception as e:
            logger.warning(f"Failed to update state: {e}")


# =============================================================================
# Convenience Function
# =============================================================================


def refresh_daily_features(
    engine: Engine,
    ids: list[int],
    start: Optional[str] = None,
    full_refresh: bool = False,
) -> int:
    """
    Convenience function for CLI usage.

    Args:
        engine: SQLAlchemy engine
        ids: List of asset IDs to refresh
        start: Optional start date (ISO format)
        full_refresh: If True, delete all rows for IDs before refresh

    Returns:
        Number of rows inserted
    """
    from ta_lab2.scripts.features.feature_state_manager import (
        FeatureStateManager,
        FeatureStateConfig,
    )

    # Create state manager for daily_features
    config = FeatureStateConfig(
        feature_type="daily_features",
        state_schema="public",
        state_table="cmc_feature_state",
    )
    state_manager = FeatureStateManager(engine, config)
    state_manager.ensure_state_table()

    # Create store and refresh
    store = DailyFeaturesStore(engine, state_manager)
    return store.refresh_for_ids(ids, start, full_refresh)
