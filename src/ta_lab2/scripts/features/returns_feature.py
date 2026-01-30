"""
ReturnsFeature - Daily returns feature computation module.

Computes returns over multiple lookback windows (1D, 3D, 5D, 7D, 14D, 21D, 30D, etc.)
derived from dim_timeframe tf_days values.

Features:
- Bar-to-bar returns (1D percent and log) using existing returns.py functions
- Multi-day percent returns via pct_change(periods=n)
- Z-score normalization for key windows (1D, 7D, 30D)
- Gap tracking for data quality
- Outlier detection and flagging

Source: cmc_price_bars_1d (daily validated bars)
Output: cmc_returns_daily table
State: cmc_feature_state (feature_type='returns')
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.features.returns import b2t_pct_delta, b2t_log_delta
from ta_lab2.scripts.features.base_feature import BaseFeature, FeatureConfig


# =============================================================================
# Configuration
# =============================================================================

@dataclass(frozen=True)
class ReturnsConfig(FeatureConfig):
    """
    Configuration for returns feature computation.

    Attributes:
        feature_type: Set to 'returns'
        output_table: Output table name (cmc_returns_daily)
        null_strategy: 'skip' - preserves gaps in return calculations
        add_zscore: Whether to add z-score normalization (default True)
        zscore_window: Rolling window for z-score (default 252 days)
        lookback_windows: Return windows to compute (from dim_timeframe)
    """
    feature_type: str = "returns"
    output_table: str = "cmc_returns_daily"
    null_strategy: str = "skip"  # Per CONTEXT.md - returns skip NULLs
    add_zscore: bool = True
    zscore_window: int = 252

    # Return windows to compute (from dim_timeframe tf_days)
    lookback_windows: tuple[int, ...] = (1, 3, 5, 7, 14, 21, 30, 63, 126, 252)


# =============================================================================
# ReturnsFeature Implementation
# =============================================================================

class ReturnsFeature(BaseFeature):
    """
    Compute daily returns with multiple lookback windows.

    Uses existing returns.py functions (b2t_pct_delta, b2t_log_delta)
    for bar-to-bar returns, then computes multi-day returns via
    pct_change(periods=n).

    Lookback windows derived from dim_timeframe tf_days values.

    Workflow:
    1. Load daily close prices from cmc_price_bars_1d
    2. Compute bar-to-bar returns (1D pct and log)
    3. Compute multi-day returns for each lookback window
    4. Add gap_days for data quality tracking
    5. Apply z-score normalization (if configured)
    6. Flag outliers
    7. Write to cmc_returns_daily
    """

    def __init__(self, engine: Engine, config: Optional[ReturnsConfig] = None):
        """
        Initialize returns feature module.

        Args:
            engine: SQLAlchemy engine
            config: Returns configuration (uses default if not provided)
        """
        if config is None:
            config = ReturnsConfig()
        super().__init__(engine, config)

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
        Load daily close prices from cmc_price_bars_1d.

        Args:
            ids: List of asset IDs (e.g., cryptocurrency IDs)
            start: Optional start date (inclusive, ISO format)
            end: Optional end date (inclusive, ISO format)

        Returns:
            DataFrame with columns: id, ts, close
            Sorted by id, ts ASC for chronological processing
        """
        # Build WHERE clause for IDs
        if not ids:
            return pd.DataFrame()

        ids_str = ",".join(str(i) for i in ids)

        # Build date filters
        date_filters = []
        if start:
            date_filters.append(f"time_close >= '{start}'::timestamptz")
        if end:
            date_filters.append(f"time_close <= '{end}'::timestamptz")

        where_clause = f"id IN ({ids_str})"
        if date_filters:
            where_clause += " AND " + " AND ".join(date_filters)

        # Query for close prices
        query = f"""
        SELECT
            id,
            time_close AS ts,
            close
        FROM public.cmc_price_bars_1d
        WHERE {where_clause}
        ORDER BY id, ts ASC
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn)

        return df

    def get_lookback_windows(self) -> list[int]:
        """
        Get lookback windows from dim_timeframe.

        Queries dim_timeframe for distinct tf_days values,
        then intersects with configured lookback_windows.

        Returns:
            List of valid lookback windows (in days)
        """
        # Query dim_timeframe for available tf_days
        query = """
        SELECT DISTINCT tf_days
        FROM public.dim_timeframe
        WHERE tf_days IS NOT NULL
          AND tf_days > 0
        ORDER BY tf_days
        """

        with self.engine.connect() as conn:
            result = conn.execute(text(query))
            available_windows = [row[0] for row in result]

        # Intersect with configured windows
        config_windows = self.config.lookback_windows
        valid_windows = [w for w in config_windows if w in available_windows]

        return valid_windows

    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        """
        Compute returns for all windows.

        For each asset (id):
        1. Sort by ts ascending
        2. Compute bar-to-bar returns using b2t_pct_delta and b2t_log_delta
        3. Compute multi-day percent returns via pct_change(periods=n)
        4. Add gap_days = (ts - ts.shift(1)).dt.days

        Args:
            df_source: Source data from load_source_data()
                       Contains: id, ts, close

        Returns:
            DataFrame with computed return columns
            Includes: id, ts, close, ret_1d_pct, ret_1d_log, ret_Nd_pct, gap_days
        """
        if df_source.empty:
            return pd.DataFrame()

        # Ensure ts is datetime
        df_source['ts'] = pd.to_datetime(df_source['ts'], utc=True)

        # Get valid lookback windows
        lookback_windows = self.get_lookback_windows()

        # Process each ID separately (returns require chronological order per asset)
        results = []

        for asset_id, df_asset in df_source.groupby('id'):
            # Sort by timestamp ascending
            df_asset = df_asset.sort_values('ts').copy()

            # Compute bar-to-bar returns using existing functions
            # b2t_pct_delta and b2t_log_delta modify df in-place
            b2t_pct_delta(df_asset, cols=['close'], direction='oldest_top')
            b2t_log_delta(df_asset, cols=['close'], direction='oldest_top')

            # Rename to match schema
            df_asset['ret_1d_pct'] = df_asset['close_b2t_pct']
            df_asset['ret_1d_log'] = df_asset['close_b2t_log']

            # Drop intermediate columns
            df_asset = df_asset.drop(columns=['close_b2t_pct', 'close_b2t_log'])

            # Compute multi-day percent returns
            for window in lookback_windows:
                if window == 1:
                    # Already computed as ret_1d_pct
                    continue

                # pct_change(periods=n) computes (close[t] - close[t-n]) / close[t-n]
                col_name = f"ret_{window}d_pct"
                df_asset[col_name] = df_asset['close'].pct_change(periods=window)

            # Compute gap_days (days since previous observation)
            df_asset['gap_days'] = (df_asset['ts'] - df_asset['ts'].shift(1)).dt.days
            # First row has no previous, set to NULL
            df_asset.loc[df_asset.index[0], 'gap_days'] = None

            results.append(df_asset)

        # Combine all assets
        df_features = pd.concat(results, ignore_index=True)

        return df_features

    def get_output_schema(self) -> dict[str, str]:
        """
        Get output table schema definition.

        Returns:
            Dictionary mapping column names to SQL types
        """
        schema = {
            "id": "INTEGER",
            "ts": "TIMESTAMPTZ",
            "close": "DOUBLE PRECISION",
            "ret_1d_pct": "DOUBLE PRECISION",
            "ret_1d_log": "DOUBLE PRECISION",
        }

        # Add multi-day return columns
        for window in self.config.lookback_windows:
            if window == 1:
                continue  # Already included as ret_1d_pct
            schema[f"ret_{window}d_pct"] = "DOUBLE PRECISION"

        # Add z-score columns (will be added if config.add_zscore is True)
        if self.config.add_zscore:
            schema["ret_1d_pct_zscore"] = "DOUBLE PRECISION"
            schema["ret_7d_pct_zscore"] = "DOUBLE PRECISION"
            schema["ret_30d_pct_zscore"] = "DOUBLE PRECISION"

        # Add data quality columns
        schema["gap_days"] = "INTEGER"
        schema["is_outlier"] = "BOOLEAN DEFAULT FALSE"
        schema["updated_at"] = "TIMESTAMPTZ DEFAULT now()"

        return schema

    def get_feature_columns(self) -> list[str]:
        """
        Get list of computed feature columns.

        Used for applying normalization and outlier detection.

        Returns:
            List of return column names (excluding id, ts, metadata)
        """
        columns = ["ret_1d_pct", "ret_1d_log"]

        # Add multi-day return columns
        for window in self.config.lookback_windows:
            if window == 1:
                continue  # Already included
            columns.append(f"ret_{window}d_pct")

        return columns

    # =========================================================================
    # Override Helper Methods for Returns-Specific Logic
    # =========================================================================

    def add_normalizations(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add normalization columns (z-score for key windows only).

        Override to add z-score only for key return windows (1D, 7D, 30D)
        instead of all feature columns.

        Args:
            df: DataFrame with computed features

        Returns:
            DataFrame with added normalization columns
        """
        if not self.config.add_zscore:
            return df

        # Import here to avoid circular dependency
        from ta_lab2.features.feature_utils import add_zscore as add_zscore_util

        # Add z-score for key windows only (1D, 7D, 30D)
        key_windows = ['ret_1d_pct', 'ret_7d_pct', 'ret_30d_pct']

        for col in key_windows:
            if col in df.columns:
                # Process each asset separately for rolling calculations
                results = []
                for asset_id, df_asset in df.groupby('id'):
                    df_asset = df_asset.copy()
                    add_zscore_util(
                        df_asset,
                        col,
                        window=self.config.zscore_window,
                        out_col=f"{col}_zscore",
                    )
                    results.append(df_asset)

                df = pd.concat(results, ignore_index=True)

        return df

    def add_outlier_flags(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add outlier flag for returns (single is_outlier column).

        Override to create a single is_outlier column that flags
        extreme returns in any of the key windows (1D, 7D, 30D).

        Args:
            df: DataFrame with computed features

        Returns:
            DataFrame with added is_outlier column
        """
        from ta_lab2.features.feature_utils import flag_outliers

        # Start with all False
        df['is_outlier'] = False

        # Flag outliers in key windows
        key_windows = ['ret_1d_pct', 'ret_7d_pct', 'ret_30d_pct']

        for col in key_windows:
            if col in df.columns:
                # Flag using z-score method (4 sigma threshold)
                outlier_flags = flag_outliers(df[col], n_sigma=4.0, method='zscore')
                # Mark as outlier if ANY window is flagged
                df['is_outlier'] = df['is_outlier'] | outlier_flags

        return df

    def __repr__(self) -> str:
        return (
            f"ReturnsFeature("
            f"output_table={self.config.output_schema}.{self.config.output_table}, "
            f"windows={self.config.lookback_windows})"
        )
