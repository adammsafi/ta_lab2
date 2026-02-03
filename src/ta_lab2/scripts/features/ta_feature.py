"""
TAFeature - Technical indicators feature computation.

Computes RSI, MACD, Stochastic, Bollinger Bands, ATR, ADX with configurable
parameter sets loaded from dim_indicators metadata table.

Design:
- Extends BaseFeature with template method pattern
- Reuses indicators.py functions with inplace=True for efficiency
- Parameter sets dynamically loaded from dim_indicators (database-driven)
- Handles missing volume gracefully (skips volume-based indicators)

Usage:
    from ta_lab2.scripts.features.ta_feature import TAFeature, TAConfig

    config = TAConfig()
    feature = TAFeature(engine, config)
    rows = feature.compute_for_ids(ids=[1, 52], start="2023-01-01")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import json

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.scripts.features.base_feature import BaseFeature, FeatureConfig
from ta_lab2.features.indicators import (
    rsi,
    macd,
    stoch_kd,
    bollinger,
    atr,
    adx,
)


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class TAConfig(FeatureConfig):
    """
    Configuration for technical indicators computation.

    Attributes:
        feature_type: Type of feature (default: "ta")
        output_table: Output table name (default: "cmc_ta_daily")
        null_strategy: Null handling strategy (default: "interpolate")
        add_zscore: Whether to add z-score normalization (default: True)
        load_indicators_from_db: Load parameter sets from dim_indicators (default: True)
    """

    feature_type: str = "ta"
    output_table: str = "cmc_ta_daily"
    null_strategy: str = "interpolate"  # Per CONTEXT.md - indicators interpolate
    add_zscore: bool = True
    load_indicators_from_db: bool = True


# =============================================================================
# TAFeature Class
# =============================================================================


class TAFeature(BaseFeature):
    """
    Compute daily technical indicators.

    Uses existing indicators.py functions:
    - rsi(): RSI with configurable period
    - macd(): MACD with fast/slow/signal
    - stoch_kd(): Stochastic %K/%D
    - bollinger(): Bollinger Bands
    - atr(): Average True Range
    - adx(): ADX

    Parameter sets loaded from dim_indicators table for database-driven configuration.
    """

    def __init__(self, engine: Engine, config: TAConfig):
        """
        Initialize TAFeature.

        Args:
            engine: SQLAlchemy engine
            config: TA configuration
        """
        super().__init__(engine, config)
        self.config: TAConfig = config  # Type hint for IDE support
        self._indicator_params: Optional[list[dict]] = None

    # =========================================================================
    # Abstract Method Implementations
    # =========================================================================

    def load_source_data(
        self,
        ids: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Load OHLCV data from cmc_price_bars_1d.

        Args:
            ids: List of asset IDs
            start: Optional start date (inclusive, ISO format)
            end: Optional end date (inclusive, ISO format)

        Returns:
            DataFrame with columns: id, ts, open, high, low, close, volume
            Sorted by id, ts ASC
        """
        # Build WHERE clauses
        where_clauses = ["id = ANY(:ids)"]
        params = {"ids": ids}

        if start:
            where_clauses.append("ts >= :start")
            params["start"] = start

        if end:
            where_clauses.append("ts <= :end")
            params["end"] = end

        where_sql = " AND ".join(where_clauses)

        sql_text = f"""
            SELECT
                id,
                ts,
                open,
                high,
                low,
                close,
                volume
            FROM public.cmc_price_bars_1d
            WHERE {where_sql}
            ORDER BY id, ts ASC
        """

        sql = text(sql_text)

        with self.engine.connect() as conn:
            df = pd.read_sql(sql, conn, params=params)

        return df

    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all active technical indicators.

        For each ID:
        1. Apply null handling (interpolate per config)
        2. For each active indicator in dim_indicators:
           - Parse params from JSONB
           - Call corresponding indicators.py function
           - Add columns to result

        Args:
            df_source: Source data with OHLCV (null handling already applied)

        Returns:
            DataFrame with computed indicator columns
        """
        if df_source.empty:
            return pd.DataFrame()

        # Load active indicator parameters
        indicator_params = self.load_indicator_params()

        # Process each ID separately
        results = []

        for id_val in df_source["id"].unique():
            df_id = df_source[df_source["id"] == id_val].copy()

            # Compute each active indicator
            for ind in indicator_params:
                ind_type = ind["indicator_type"]
                ind_name = ind["indicator_name"]
                params = ind["params"]

                try:
                    if ind_type == "rsi":
                        self._compute_rsi(df_id, params)
                    elif ind_type == "macd":
                        self._compute_macd(df_id, params)
                    elif ind_type == "stoch":
                        self._compute_stoch(df_id, params)
                    elif ind_type == "bb":
                        self._compute_bollinger(df_id, params)
                    elif ind_type == "atr":
                        self._compute_atr(df_id, params)
                    elif ind_type == "adx":
                        self._compute_adx(df_id, params)
                except Exception as e:
                    # Log error but continue with other indicators
                    print(f"Warning: Failed to compute {ind_name} for id={id_val}: {e}")
                    continue

            results.append(df_id)

        if not results:
            return pd.DataFrame()

        # Combine all IDs
        df_result = pd.concat(results, ignore_index=True)

        # Select output columns
        output_cols = ["id", "ts", "close"] + [
            col
            for col in df_result.columns
            if col not in ["id", "ts", "close", "open", "high", "low", "volume"]
        ]

        return df_result[output_cols]

    def get_output_schema(self) -> dict[str, str]:
        """
        Get output table schema definition.

        Returns:
            Dictionary mapping column names to SQL types
        """
        # Base schema (static columns)
        schema = {
            "id": "INTEGER NOT NULL",
            "ts": "TIMESTAMPTZ NOT NULL",
            "close": "DOUBLE PRECISION",
        }

        # Add columns for all possible indicators
        # (Dynamic based on dim_indicators in production, static for table creation)
        schema.update(
            {
                # RSI variations
                "rsi_7": "DOUBLE PRECISION",
                "rsi_14": "DOUBLE PRECISION",
                "rsi_21": "DOUBLE PRECISION",
                # MACD variations
                "macd_12_26": "DOUBLE PRECISION",
                "macd_signal_9": "DOUBLE PRECISION",
                "macd_hist_12_26_9": "DOUBLE PRECISION",
                "macd_8_17": "DOUBLE PRECISION",
                "macd_signal_9_fast": "DOUBLE PRECISION",
                "macd_hist_8_17_9": "DOUBLE PRECISION",
                # Stochastic
                "stoch_k_14": "DOUBLE PRECISION",
                "stoch_d_3": "DOUBLE PRECISION",
                # Bollinger Bands
                "bb_ma_20": "DOUBLE PRECISION",
                "bb_up_20_2": "DOUBLE PRECISION",
                "bb_lo_20_2": "DOUBLE PRECISION",
                "bb_width_20": "DOUBLE PRECISION",
                # ATR and ADX
                "atr_14": "DOUBLE PRECISION",
                "adx_14": "DOUBLE PRECISION",
                # Normalized versions
                "rsi_14_zscore": "DOUBLE PRECISION",
                # Data quality
                "is_outlier": "BOOLEAN DEFAULT FALSE",
                # Metadata
                "updated_at": "TIMESTAMPTZ DEFAULT now()",
            }
        )

        return schema

    def get_feature_columns(self) -> list[str]:
        """
        Get list of computed feature columns.

        Returns:
            List of feature column names (excluding id, ts, metadata columns)
        """
        # Get active indicators from database
        indicator_params = self.load_indicator_params()

        feature_cols = []

        for ind in indicator_params:
            ind_type = ind["indicator_type"]
            ind_name = ind["indicator_name"]
            params = ind["params"]

            if ind_type == "rsi":
                period = params.get("period", 14)
                feature_cols.append(f"rsi_{period}")
            elif ind_type == "macd":
                fast = params.get("fast", 12)
                slow = params.get("slow", 26)
                signal = params.get("signal", 9)
                feature_cols.extend(
                    [
                        f"macd_{fast}_{slow}",
                        f"macd_signal_{signal}",
                        f"macd_hist_{fast}_{slow}_{signal}",
                    ]
                )
            elif ind_type == "stoch":
                k = params.get("k", 14)
                d = params.get("d", 3)
                feature_cols.extend([f"stoch_k_{k}", f"stoch_d_{d}"])
            elif ind_type == "bb":
                window = params.get("window", 20)
                n_sigma = params.get("n_sigma", 2.0)
                # Convert float to string without decimal if it's a whole number
                sigma_str = (
                    str(int(n_sigma)) if n_sigma == int(n_sigma) else str(n_sigma)
                )
                feature_cols.extend(
                    [
                        f"bb_ma_{window}",
                        f"bb_up_{window}_{sigma_str}",
                        f"bb_lo_{window}_{sigma_str}",
                        f"bb_width_{window}",
                    ]
                )
            elif ind_type == "atr":
                period = params.get("period", 14)
                feature_cols.append(f"atr_{period}")
            elif ind_type == "adx":
                period = params.get("period", 14)
                feature_cols.append(f"adx_{period}")

        return feature_cols

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def load_indicator_params(self) -> list[dict]:
        """
        Load active indicator parameters from dim_indicators.

        Returns:
            List of dicts with indicator_type, indicator_name, params

        Raises:
            sqlalchemy.exc.SQLAlchemyError: On database errors
        """
        if not self.config.load_indicators_from_db:
            # Return default indicators if not loading from DB
            return self._get_default_indicators()

        # Cache indicator params to avoid repeated DB queries
        if self._indicator_params is not None:
            return self._indicator_params

        sql = text(
            """
            SELECT
                indicator_type,
                indicator_name,
                params
            FROM public.dim_indicators
            WHERE is_active = TRUE
            ORDER BY indicator_id
        """
        )

        with self.engine.connect() as conn:
            result = conn.execute(sql)
            rows = result.fetchall()

        indicators = []
        for row in rows:
            indicators.append(
                {
                    "indicator_type": row[0],
                    "indicator_name": row[1],
                    "params": json.loads(row[2]) if isinstance(row[2], str) else row[2],
                }
            )

        self._indicator_params = indicators
        return indicators

    def _get_default_indicators(self) -> list[dict]:
        """Get default indicator parameters when not loading from DB."""
        return [
            {
                "indicator_type": "rsi",
                "indicator_name": "rsi_14",
                "params": {"period": 14},
            },
            {
                "indicator_type": "rsi",
                "indicator_name": "rsi_21",
                "params": {"period": 21},
            },
            {
                "indicator_type": "rsi",
                "indicator_name": "rsi_7",
                "params": {"period": 7},
            },
            {
                "indicator_type": "macd",
                "indicator_name": "macd_12_26_9",
                "params": {"fast": 12, "slow": 26, "signal": 9},
            },
            {
                "indicator_type": "macd",
                "indicator_name": "macd_8_17_9",
                "params": {"fast": 8, "slow": 17, "signal": 9},
            },
            {
                "indicator_type": "stoch",
                "indicator_name": "stoch_14_3",
                "params": {"k": 14, "d": 3},
            },
            {
                "indicator_type": "bb",
                "indicator_name": "bb_20_2",
                "params": {"window": 20, "n_sigma": 2.0},
            },
            {
                "indicator_type": "atr",
                "indicator_name": "atr_14",
                "params": {"period": 14},
            },
            {
                "indicator_type": "adx",
                "indicator_name": "adx_14",
                "params": {"period": 14},
            },
        ]

    def _compute_rsi(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute RSI indicator.

        Args:
            df: DataFrame with close column
            params: RSI parameters (period)

        Returns:
            DataFrame with RSI column added (inplace)
        """
        period = params.get("period", 14)
        out_col = f"rsi_{period}"
        rsi(df, period=period, out_col=out_col, inplace=True)
        return df

    def _compute_macd(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute MACD indicator.

        Args:
            df: DataFrame with close column
            params: MACD parameters (fast, slow, signal)

        Returns:
            DataFrame with MACD columns added (inplace)
        """
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        signal = params.get("signal", 9)

        # MACD returns separate columns, need custom out_cols
        out_cols = (
            f"macd_{fast}_{slow}",
            f"macd_signal_{signal}",
            f"macd_hist_{fast}_{slow}_{signal}",
        )
        macd(df, fast=fast, slow=slow, signal=signal, out_cols=out_cols, inplace=True)
        return df

    def _compute_stoch(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute Stochastic indicator.

        Args:
            df: DataFrame with high, low, close columns
            params: Stochastic parameters (k, d)

        Returns:
            DataFrame with Stoch K/D columns added (inplace)
        """
        k = params.get("k", 14)
        d = params.get("d", 3)

        out_cols = (f"stoch_k_{k}", f"stoch_d_{d}")
        stoch_kd(df, k=k, d=d, out_cols=out_cols, inplace=True)
        return df

    def _compute_bollinger(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute Bollinger Bands indicator.

        Args:
            df: DataFrame with close column
            params: Bollinger parameters (window, n_sigma)

        Returns:
            DataFrame with BB columns added (inplace)
        """
        window = params.get("window", 20)
        n_sigma = params.get("n_sigma", 2.0)

        # Convert float to string without decimal if it's a whole number
        sigma_str = str(int(n_sigma)) if n_sigma == int(n_sigma) else str(n_sigma)

        out_cols = (
            f"bb_ma_{window}",
            f"bb_up_{window}_{sigma_str}",
            f"bb_lo_{window}_{sigma_str}",
            f"bb_width_{window}",
        )
        bollinger(df, window=window, n_sigma=n_sigma, out_cols=out_cols, inplace=True)
        return df

    def _compute_atr(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute ATR indicator.

        Args:
            df: DataFrame with high, low, close columns
            params: ATR parameters (period)

        Returns:
            DataFrame with ATR column added (inplace)
        """
        period = params.get("period", 14)
        atr(df, period=period, inplace=True)
        return df

    def _compute_adx(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """
        Compute ADX indicator.

        Args:
            df: DataFrame with high, low, close columns
            params: ADX parameters (period)

        Returns:
            DataFrame with ADX column added (inplace)
        """
        period = params.get("period", 14)
        adx(df, period=period, inplace=True)
        return df
