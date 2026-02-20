"""
FeaturesStore - Unified multi-TF feature store management.

This module manages cmc_features, a materialized table joining all features:
- cmc_price_bars_multi_tf (OHLCV, all timeframes)
- cmc_ema_multi_tf_u (EMAs)
- cmc_returns (returns)
- cmc_vol (volatility)
- cmc_ta (technical indicators)

Design:
- Incremental refresh based on source table watermarks
- Graceful degradation when source tables missing
- Single-table access for ML pipelines
- Multi-TF support via tf parameter

Usage:
    from ta_lab2.scripts.features.daily_features_view import FeaturesStore

    store = FeaturesStore(engine, state_manager)
    rows = store.refresh_for_ids(ids=[1, 52], tf='1D')
"""

from __future__ import annotations

from typing import Optional
import logging

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.scripts.features.feature_state_manager import FeatureStateManager

logger = logging.getLogger(__name__)


# =============================================================================
# FeaturesStore Class
# =============================================================================


class FeaturesStore:
    """
    Manages cmc_features materialized table.

    Refresh pattern:
    1. Check which source tables exist and have data
    2. Identify dirty window (MIN of all source table watermarks)
    3. Delete rows in dirty window
    4. Re-materialize from source tables with JOIN query
    5. Update state

    Source tables (dependency order):
    1. cmc_price_bars_multi_tf (base - required)
    2. cmc_ema_multi_tf_u (depends on bars - optional)
    3. cmc_returns (depends on bars - optional)
    4. cmc_vol (depends on bars - optional)
    5. cmc_ta (depends on bars - optional)
    """

    SOURCE_TABLES = {
        "price_bars": {
            "table": "cmc_price_bars_multi_tf",
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
            "table": "cmc_returns",
            "schema": "public",
            "required": False,
            "feature_type": "returns",
        },
        "vol": {
            "table": "cmc_vol",
            "schema": "public",
            "required": False,
            "feature_type": "vol",
        },
        "ta": {
            "table": "cmc_ta",
            "schema": "public",
            "required": False,
            "feature_type": "ta",
        },
    }

    def __init__(self, engine: Engine, state_manager: FeatureStateManager):
        self.engine = engine
        self.state_manager = state_manager

    def check_source_tables_exist(self) -> dict[str, bool]:
        """Check which source tables exist and have data."""
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
                        count_sql = text(
                            f"SELECT COUNT(*) FROM {schema_name}.{table_name} LIMIT 1"
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
        """Get last refresh timestamp for each source table."""
        watermarks = {}

        for source_key, source_info in self.SOURCE_TABLES.items():
            feature_type = source_info["feature_type"]

            try:
                state_df = self.state_manager.load_state(
                    ids=ids, feature_type=feature_type
                )

                if state_df.empty:
                    watermarks[source_key] = None
                    continue

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
        """Compute dirty window requiring refresh."""
        watermarks = self.get_source_watermarks(ids)
        valid_watermarks = [ts for ts in watermarks.values() if ts is not None]

        if not valid_watermarks:
            start = pd.to_datetime(default_start, utc=True)
        else:
            start = min(valid_watermarks)

        end = pd.Timestamp.now(tz="UTC")
        return start, end

    def refresh_for_ids(
        self,
        ids: list[int],
        tf: str = "1D",
        start: Optional[str] = None,
        full_refresh: bool = False,
    ) -> int:
        """
        Refresh cmc_features for given IDs and timeframe.

        Args:
            ids: List of asset IDs to refresh
            tf: Timeframe code (e.g. '1D', '7D', '30D')
            start: Optional start date (ISO format)
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

        if not sources_available.get("price_bars", False):
            logger.error(
                "Required table cmc_price_bars_multi_tf not available - cannot refresh"
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
        self._delete_dirty_rows(ids, tf, dirty_start if not full_refresh else None)

        # 4. Insert refreshed data
        join_query = self._build_join_query(
            ids, tf, dirty_start.isoformat(), dirty_end.isoformat(), sources_available
        )

        with self.engine.begin() as conn:
            result = conn.execute(text(join_query))
            rows_inserted = result.rowcount

        logger.info(f"Inserted {rows_inserted} rows into cmc_features (tf={tf})")

        # 5. Update state
        self._update_state(ids)

        return rows_inserted

    def _delete_dirty_rows(
        self, ids: list[int], tf: str, start: Optional[pd.Timestamp] = None
    ) -> int:
        """Delete existing rows in dirty window for given tf."""
        where_clause = "id = ANY(:ids) AND tf = :tf"
        params = {"ids": ids, "tf": tf}

        if start is not None:
            where_clause += " AND ts >= :start"
            params["start"] = start

        delete_sql = f"""
            DELETE FROM public.cmc_features
            WHERE {where_clause}
        """

        with self.engine.begin() as conn:
            result = conn.execute(text(delete_sql), params)
            rows_deleted = result.rowcount

        logger.info(f"Deleted {rows_deleted} rows from dirty window (tf={tf})")
        return rows_deleted

    def _build_join_query(
        self,
        ids: list[int],
        tf: str,
        start: str,
        end: str,
        sources_available: dict[str, bool],
    ) -> str:
        """
        Build the JOIN query to materialize features.

        Uses cmc_price_bars_multi_tf as base with time_close as ts.
        LEFT JOINs optional sources filtered by tf.
        """
        ids_list = ",".join(str(id_) for id_ in ids)

        # Build SELECT columns
        select_cols = [
            "p.id",
            "p.time_close as ts",
            f"'{tf}' as tf",
            "p.tf_days",
            "'CRYPTO'::text as asset_class",
            # OHLCV
            "p.open",
            "p.high",
            "p.low",
            "p.close",
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
                    "e9.d1 as ema_9_d1",
                    "e21.d1 as ema_21_d1",
                ]
            )
        else:
            select_cols.extend(
                [
                    "NULL::double precision as ema_9",
                    "NULL::double precision as ema_10",
                    "NULL::double precision as ema_21",
                    "NULL::double precision as ema_50",
                    "NULL::double precision as ema_200",
                    "NULL::double precision as ema_9_d1",
                    "NULL::double precision as ema_21_d1",
                ]
            )

        # Returns
        if sources_available.get("returns", False):
            select_cols.extend(
                [
                    "r.ret_1_pct",
                    "r.ret_1_log",
                    "r.ret_7_pct",
                    "r.ret_30_pct",
                    "r.ret_1_pct_zscore",
                    "r.gap_days",
                ]
            )
        else:
            select_cols.extend(
                [
                    "NULL::double precision as ret_1_pct",
                    "NULL::double precision as ret_1_log",
                    "NULL::double precision as ret_7_pct",
                    "NULL::double precision as ret_30_pct",
                    "NULL::double precision as ret_1_pct_zscore",
                    "NULL::integer as gap_days",
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
                    "NULL::double precision as vol_parkinson_20",
                    "NULL::double precision as vol_gk_20",
                    "NULL::double precision as vol_parkinson_20_zscore",
                    "NULL::double precision as atr_14",
                ]
            )

        # Technical indicators (added rsi_7, bb_up_20_2, bb_lo_20_2 for signals)
        if sources_available.get("ta", False):
            select_cols.extend(
                [
                    "t.rsi_7",
                    "t.rsi_14",
                    "t.rsi_21",
                    "t.macd_12_26",
                    "t.macd_signal_9",
                    "t.macd_hist_12_26_9",
                    "t.stoch_k_14",
                    "t.stoch_d_3",
                    "t.bb_ma_20",
                    "t.bb_up_20_2",
                    "t.bb_lo_20_2",
                    "t.bb_width_20",
                    "t.adx_14",
                ]
            )
        else:
            select_cols.extend(
                [
                    "NULL::double precision as rsi_7",
                    "NULL::double precision as rsi_14",
                    "NULL::double precision as rsi_21",
                    "NULL::double precision as macd_12_26",
                    "NULL::double precision as macd_signal_9",
                    "NULL::double precision as macd_hist_12_26_9",
                    "NULL::double precision as stoch_k_14",
                    "NULL::double precision as stoch_d_3",
                    "NULL::double precision as bb_ma_20",
                    "NULL::double precision as bb_up_20_2",
                    "NULL::double precision as bb_lo_20_2",
                    "NULL::double precision as bb_width_20",
                    "NULL::double precision as adx_14",
                ]
            )

        # Data quality flags
        select_cols.extend(
            [
                "CASE WHEN r.gap_days > 1 THEN TRUE ELSE FALSE END as has_price_gap",
                "CASE WHEN r.is_outlier OR v.vol_parkinson_20_is_outlier OR t.is_outlier THEN TRUE ELSE FALSE END as has_outlier",
                "now() as updated_at",
            ]
        )

        # Build JOINs
        joins = []

        # Base: price_bars_multi_tf
        joins.append(
            """
            FROM public.cmc_price_bars_multi_tf p
        """
        )

        # EMAs (need multiple joins for different periods, filtered to matching tf)
        if sources_available.get("emas", False):
            joins.append(
                f"""
                LEFT JOIN (SELECT id, ts, ema, d1 FROM public.cmc_ema_multi_tf_u WHERE period = 9 AND tf = '{tf}') e9
                  ON p.id = e9.id AND p.time_close = e9.ts
                LEFT JOIN (SELECT id, ts, ema, d1 FROM public.cmc_ema_multi_tf_u WHERE period = 10 AND tf = '{tf}') e10
                  ON p.id = e10.id AND p.time_close = e10.ts
                LEFT JOIN (SELECT id, ts, ema, d1 FROM public.cmc_ema_multi_tf_u WHERE period = 21 AND tf = '{tf}') e21
                  ON p.id = e21.id AND p.time_close = e21.ts
                LEFT JOIN (SELECT id, ts, ema, d1 FROM public.cmc_ema_multi_tf_u WHERE period = 50 AND tf = '{tf}') e50
                  ON p.id = e50.id AND p.time_close = e50.ts
                LEFT JOIN (SELECT id, ts, ema, d1 FROM public.cmc_ema_multi_tf_u WHERE period = 200 AND tf = '{tf}') e200
                  ON p.id = e200.id AND p.time_close = e200.ts
            """
            )

        # Returns
        if sources_available.get("returns", False):
            joins.append(
                f"""
                LEFT JOIN public.cmc_returns r
                  ON p.id = r.id AND p.time_close = r.ts AND r.tf = '{tf}'
            """
            )

        # Volatility
        if sources_available.get("vol", False):
            joins.append(
                f"""
                LEFT JOIN public.cmc_vol v
                  ON p.id = v.id AND p.time_close = v.ts AND v.tf = '{tf}'
            """
            )

        # TA
        if sources_available.get("ta", False):
            joins.append(
                f"""
                LEFT JOIN public.cmc_ta t
                  ON p.id = t.id AND p.time_close = t.ts AND t.tf = '{tf}'
            """
            )

        # WHERE clause
        where_clause = f"""
            WHERE p.id IN ({ids_list})
              AND p.tf = '{tf}'
              AND p.time_close >= '{start}'
              AND p.time_close <= '{end}'
        """

        # Extract column names for INSERT
        insert_cols = []
        for col in select_cols:
            if " as " in col:
                insert_cols.append(col.split(" as ")[-1].strip())
            else:
                insert_cols.append(col.split(".")[-1].strip().strip('"'))

        # Build complete query
        query = f"""
            INSERT INTO public.cmc_features (
                {", ".join(insert_cols)}
            )
            SELECT
                {", ".join(select_cols)}
            {"".join(joins)}
            {where_clause}
        """

        return query

    def _update_state(self, ids: list[int]) -> None:
        """Update state after successful refresh."""
        try:
            self.state_manager.update_state_from_output(
                output_table="cmc_features",
                output_schema="public",
                feature_name="unified",
            )
            logger.info("Updated state for features")
        except Exception as e:
            logger.warning(f"Failed to update state: {e}")


# Backwards-compatible alias
DailyFeaturesStore = FeaturesStore


# =============================================================================
# Convenience Function
# =============================================================================


def refresh_features(
    engine: Engine,
    ids: list[int],
    tf: str = "1D",
    start: Optional[str] = None,
    full_refresh: bool = False,
) -> int:
    """
    Convenience function for CLI usage.

    Args:
        engine: SQLAlchemy engine
        ids: List of asset IDs to refresh
        tf: Timeframe code (e.g. '1D', '7D')
        start: Optional start date (ISO format)
        full_refresh: If True, delete all rows for IDs before refresh

    Returns:
        Number of rows inserted
    """
    from ta_lab2.scripts.features.feature_state_manager import (
        FeatureStateManager,
        FeatureStateConfig,
    )

    config = FeatureStateConfig(
        feature_type="daily_features",
        state_schema="public",
        state_table="cmc_feature_state",
    )
    state_manager = FeatureStateManager(engine, config)
    state_manager.ensure_state_table()

    store = FeaturesStore(engine, state_manager)
    return store.refresh_for_ids(ids, tf=tf, start=start, full_refresh=full_refresh)


# Backwards-compatible alias
refresh_daily_features = refresh_features
