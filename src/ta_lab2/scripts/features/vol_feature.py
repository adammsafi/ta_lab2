"""
Volatility Feature Module - Daily volatility measures from OHLC bars.

This module computes multiple volatility estimators:
- Parkinson (1980): Range-based volatility (high/low)
- Garman-Klass (1980): OHLC-based volatility
- Rogers-Satchell (1991): Drift-independent volatility
- ATR (Wilder): Average True Range
- Rolling historical volatility: Log return standard deviation

All volatility measures are annualized using sqrt(252) for trading days.

Uses existing vol.py functions for all calculations - no duplication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.scripts.features.base_feature import BaseFeature, FeatureConfig
from ta_lab2.features.vol import (
    add_parkinson_vol,
    add_garman_klass_vol,
    add_rogers_satchell_vol,
    add_atr,
    add_rolling_vol_from_returns_batch,
)


# =============================================================================
# Configuration
# =============================================================================

@dataclass(frozen=True)
class VolatilityConfig(FeatureConfig):
    """
    Configuration for volatility feature computation.

    Attributes:
        feature_type: 'vol' (volatility features)
        output_table: 'cmc_vol_daily' (output table name)
        null_strategy: 'forward_fill' (per CONTEXT.md - vol forward fills)
        add_zscore: True (add z-score normalization)
        zscore_window: 252 (1 trading year for rolling z-score)
        vol_windows: (20, 63, 126) - volatility estimation windows
        estimators: ('parkinson', 'gk', 'rs') - which estimators to compute
        periods_per_year: 252 (annualization factor)
        atr_period: 14 (ATR period)
    """
    feature_type: str = "vol"
    output_table: str = "cmc_vol_daily"
    null_strategy: str = "forward_fill"  # Per CONTEXT.md - vol forward fills
    add_zscore: bool = True
    zscore_window: int = 252

    # Volatility windows (days)
    vol_windows: tuple[int, ...] = (20, 63, 126)

    # Estimators to compute
    estimators: tuple[str, ...] = ("parkinson", "gk", "rs")

    # Annualization factor (252 trading days)
    periods_per_year: int = 252

    # ATR period
    atr_period: int = 14


# =============================================================================
# Volatility Feature Class
# =============================================================================

class VolatilityFeature(BaseFeature):
    """
    Compute daily volatility measures from OHLC bars.

    This class uses existing vol.py functions for all volatility calculations:
    - add_parkinson_vol(): Range-based (high/low)
    - add_garman_klass_vol(): OHLC-based
    - add_rogers_satchell_vol(): Drift-independent
    - add_atr(): Average True Range
    - add_rolling_vol_from_returns_batch(): Historical from log returns

    All volatility measures are annualized using sqrt(252) for trading days.

    Template method flow:
    1. Load OHLC data from cmc_price_bars_1d
    2. Apply forward_fill null handling (config)
    3. Compute all volatility estimators
    4. Add z-score normalization
    5. Flag outliers
    6. Write to cmc_vol_daily
    """

    def __init__(self, engine: Engine, config: Optional[VolatilityConfig] = None):
        """
        Initialize volatility feature module.

        Args:
            engine: SQLAlchemy engine
            config: Volatility configuration (defaults to VolatilityConfig())
        """
        if config is None:
            config = VolatilityConfig()
        super().__init__(engine, config)
        self.vol_config = config  # Type-safe reference

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
        Load OHLC data from cmc_price_bars_1d for volatility computation.

        Args:
            ids: List of asset IDs
            start: Optional start date (inclusive, ISO format)
            end: Optional end date (inclusive, ISO format)

        Returns:
            DataFrame with columns: id, ts, open, high, low, close
            Sorted by id ASC, ts ASC
        """
        # Build WHERE clauses
        where_clauses = ["id = ANY(:ids)"]
        params = {"ids": ids}

        if start:
            where_clauses.append("time_close >= :start")
            params["start"] = start

        if end:
            where_clauses.append("time_close <= :end")
            params["end"] = end

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                id,
                time_close as ts,
                open,
                high,
                low,
                close
            FROM public.cmc_price_bars_1d
            WHERE {where_sql}
            ORDER BY id ASC, ts ASC
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params)

        return df

    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all volatility measures from OHLC data.

        Uses existing vol.py functions for all calculations:
        1. Parkinson volatility (range-based)
        2. Garman-Klass volatility (OHLC-based)
        3. Rogers-Satchell volatility (drift-independent)
        4. ATR (Average True Range)
        5. Rolling historical volatility (log return std)

        Args:
            df_source: Source OHLC data (with nulls handled)

        Returns:
            DataFrame with computed volatility columns
        """
        if df_source.empty:
            return pd.DataFrame()

        # Make a copy to avoid modifying source
        df = df_source.copy()

        # Process each ID separately (volatility requires ordering)
        results = []

        for id_val in df['id'].unique():
            df_id = df[df['id'] == id_val].copy()

            # Sort by timestamp (required for rolling calculations)
            df_id = df_id.sort_values('ts')

            # 1. Parkinson volatility (range-based)
            if 'parkinson' in self.vol_config.estimators:
                add_parkinson_vol(
                    df_id,
                    high_col='high',
                    low_col='low',
                    windows=self.vol_config.vol_windows,
                    annualize=True,
                    periods_per_year=self.vol_config.periods_per_year,
                )

            # 2. Garman-Klass volatility (OHLC-based)
            if 'gk' in self.vol_config.estimators:
                add_garman_klass_vol(
                    df_id,
                    open_col='open',
                    high_col='high',
                    low_col='low',
                    close_col='close',
                    windows=self.vol_config.vol_windows,
                    annualize=True,
                    periods_per_year=self.vol_config.periods_per_year,
                )

            # 3. Rogers-Satchell volatility (drift-independent)
            if 'rs' in self.vol_config.estimators:
                add_rogers_satchell_vol(
                    df_id,
                    open_col='open',
                    high_col='high',
                    low_col='low',
                    close_col='close',
                    windows=self.vol_config.vol_windows,
                    annualize=True,
                    periods_per_year=self.vol_config.periods_per_year,
                )

            # 4. ATR (Average True Range)
            add_atr(
                df_id,
                period=self.vol_config.atr_period,
                open_col='open',
                high_col='high',
                low_col='low',
                close_col='close',
            )

            # 5. Rolling historical volatility from log returns
            add_rolling_vol_from_returns_batch(
                df_id,
                close_col='close',
                windows=self.vol_config.vol_windows,
                types='log',
                annualize=True,
                periods_per_year=self.vol_config.periods_per_year,
                ddof=0,
                prefix='vol',
            )

            results.append(df_id)

        # Combine all IDs
        df_features = pd.concat(results, ignore_index=True)

        return df_features

    def get_output_schema(self) -> dict[str, str]:
        """
        Get output table schema definition.

        Returns:
            Dictionary mapping column names to SQL types
        """
        schema = {
            "id": "INTEGER NOT NULL",
            "ts": "TIMESTAMPTZ NOT NULL",
            # OHLC context
            "open": "DOUBLE PRECISION",
            "high": "DOUBLE PRECISION",
            "low": "DOUBLE PRECISION",
            "close": "DOUBLE PRECISION",
        }

        # Add volatility columns for each window
        for window in self.vol_config.vol_windows:
            schema[f"vol_parkinson_{window}"] = "DOUBLE PRECISION"
            schema[f"vol_gk_{window}"] = "DOUBLE PRECISION"
            schema[f"vol_rs_{window}"] = "DOUBLE PRECISION"
            schema[f"vol_log_roll_{window}"] = "DOUBLE PRECISION"

        # ATR
        schema[f"atr_{self.vol_config.atr_period}"] = "DOUBLE PRECISION"

        # Z-scores (if enabled)
        if self.config.add_zscore:
            for window in self.vol_config.vol_windows:
                schema[f"vol_parkinson_{window}_zscore"] = "DOUBLE PRECISION"
                schema[f"vol_gk_{window}_zscore"] = "DOUBLE PRECISION"
                schema[f"vol_rs_{window}_zscore"] = "DOUBLE PRECISION"

        # Outlier flags
        for window in self.vol_config.vol_windows:
            schema[f"vol_parkinson_{window}_is_outlier"] = "BOOLEAN DEFAULT FALSE"
            schema[f"vol_gk_{window}_is_outlier"] = "BOOLEAN DEFAULT FALSE"
            schema[f"vol_rs_{window}_is_outlier"] = "BOOLEAN DEFAULT FALSE"
            schema[f"vol_log_roll_{window}_is_outlier"] = "BOOLEAN DEFAULT FALSE"

        schema[f"atr_{self.vol_config.atr_period}_is_outlier"] = "BOOLEAN DEFAULT FALSE"

        # Metadata
        schema["updated_at"] = "TIMESTAMPTZ DEFAULT now()"

        return schema

    def get_feature_columns(self) -> list[str]:
        """
        Get list of computed feature columns.

        Used for applying normalization and outlier detection.

        Returns:
            List of feature column names
        """
        cols = []

        # Volatility columns for each window
        for window in self.vol_config.vol_windows:
            cols.append(f"vol_parkinson_{window}")
            cols.append(f"vol_gk_{window}")
            cols.append(f"vol_rs_{window}")
            cols.append(f"vol_log_roll_{window}")

        # ATR
        cols.append(f"atr_{self.vol_config.atr_period}")

        return cols

    def __repr__(self) -> str:
        return (
            f"VolatilityFeature("
            f"output_table={self.config.output_schema}.{self.config.output_table}, "
            f"windows={self.vol_config.vol_windows}, "
            f"estimators={self.vol_config.estimators})"
        )
