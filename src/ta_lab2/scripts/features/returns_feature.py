"""
ReturnsFeature - Multi-TF returns feature computation module.

Computes returns over multiple lookback windows (1, 3, 5, 7, 14, 21, 30, etc.)
derived from dim_timeframe tf_days values.

Features:
- Bar-to-bar returns (1-bar percent and log) using existing returns.py functions
- Multi-bar percent returns via pct_change(periods=n)
- Z-score normalization for key windows (1, 7, 30 bars)
- Gap tracking for data quality
- Outlier detection and flagging

Source: cmc_price_bars_multi_tf (all timeframes)
Output: cmc_returns table with (id, ts, tf) PK
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
        output_table: Output table name (cmc_returns)
        null_strategy: 'skip' - preserves gaps in return calculations
        add_zscore: Whether to add z-score normalization (default True)
        zscore_window: Rolling window for z-score (default 252 bars)
        lookback_windows: Return windows to compute (in bars, not days)
    """

    feature_type: str = "returns"
    output_table: str = "cmc_returns"
    null_strategy: str = "skip"  # Per CONTEXT.md - returns skip NULLs
    add_zscore: bool = True
    zscore_window: int = 252

    # Return windows to compute (in bars, from dim_timeframe tf_days)
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
        Load close prices from cmc_price_bars_multi_tf for configured tf.

        Args:
            ids: List of asset IDs (e.g., cryptocurrency IDs)
            start: Optional start date (inclusive, ISO format)
            end: Optional end date (inclusive, ISO format)

        Returns:
            DataFrame with columns: id, ts, close
            Sorted by id, ts ASC for chronological processing
        """
        if not ids:
            return pd.DataFrame()

        where_clauses = ["id = ANY(:ids)", "tf = :tf"]
        params = {"ids": ids, "tf": self.config.tf}

        if start:
            where_clauses.append(f"{self.TS_COLUMN} >= :start")
            params["start"] = start
        if end:
            where_clauses.append(f"{self.TS_COLUMN} <= :end")
            params["end"] = end

        where_sql = " AND ".join(where_clauses)

        query = f"""
        SELECT
            id,
            {self.TS_COLUMN} AS ts,
            close
        FROM {self.SOURCE_TABLE}
        WHERE {where_sql}
        ORDER BY id, ts ASC
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params)

        return df

    def get_lookback_windows(self) -> list[int]:
        """
        Get lookback windows for multi-bar returns.

        Returns configured lookback windows directly — these represent
        N-bar periods for pct_change, not calendar day counts.

        Returns:
            List of lookback windows (in bars)
        """
        return list(self.config.lookback_windows)

    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        """
        Compute returns for all windows.

        For each asset (id):
        1. Sort by ts ascending
        2. Compute bar-to-bar returns using b2t_pct_delta and b2t_log_delta
        3. Compute multi-bar percent returns via pct_change(periods=n)
        4. Add gap_days = (ts - ts.shift(1)).dt.days

        Args:
            df_source: Source data from load_source_data()
                       Contains: id, ts, close

        Returns:
            DataFrame with computed return columns
            Includes: id, ts, tf, tf_days, close, ret_1_pct, ret_1_log, ret_N_pct, gap_days
        """
        if df_source.empty:
            return pd.DataFrame()

        # Ensure ts is datetime
        df_source["ts"] = pd.to_datetime(df_source["ts"], utc=True)

        # Get valid lookback windows
        lookback_windows = self.get_lookback_windows()

        # Process each ID separately (returns require chronological order per asset)
        results = []

        for asset_id, df_asset in df_source.groupby("id"):
            # Sort by timestamp ascending
            df_asset = df_asset.sort_values("ts").copy()

            # Compute bar-to-bar returns using existing functions
            b2t_pct_delta(df_asset, cols=["close"], direction="oldest_top")
            b2t_log_delta(df_asset, cols=["close"], direction="oldest_top")

            # Rename to match schema (ret_1_pct = 1-bar return)
            df_asset["ret_1_pct"] = df_asset["close_b2t_pct"]
            df_asset["ret_1_log"] = df_asset["close_b2t_log"]

            # Drop intermediate columns
            df_asset = df_asset.drop(columns=["close_b2t_pct", "close_b2t_log"])

            # Compute multi-bar percent returns
            for window in lookback_windows:
                if window == 1:
                    continue

                col_name = f"ret_{window}_pct"
                df_asset[col_name] = df_asset["close"].pct_change(periods=window)

            # Compute gap_days (days since previous observation)
            df_asset["gap_days"] = (df_asset["ts"] - df_asset["ts"].shift(1)).dt.days
            df_asset.loc[df_asset.index[0], "gap_days"] = None

            results.append(df_asset)

        # Combine all assets
        df_features = pd.concat(results, ignore_index=True)

        # Add tf and tf_days columns
        df_features["tf"] = self.config.tf
        df_features["tf_days"] = self.get_tf_days()

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
            "tf": "TEXT NOT NULL",
            "tf_days": "INTEGER NOT NULL",
            "close": "DOUBLE PRECISION",
            "ret_1_pct": "DOUBLE PRECISION",
            "ret_1_log": "DOUBLE PRECISION",
        }

        # Add multi-bar return columns
        for window in self.config.lookback_windows:
            if window == 1:
                continue
            schema[f"ret_{window}_pct"] = "DOUBLE PRECISION"

        # Add z-score columns
        if self.config.add_zscore:
            schema["ret_1_pct_zscore"] = "DOUBLE PRECISION"
            schema["ret_7_pct_zscore"] = "DOUBLE PRECISION"
            schema["ret_30_pct_zscore"] = "DOUBLE PRECISION"

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
        columns = ["ret_1_pct", "ret_1_log"]

        # Add multi-bar return columns
        for window in self.config.lookback_windows:
            if window == 1:
                continue
            columns.append(f"ret_{window}_pct")

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

        # Add z-score for key windows only (1-bar, 7-bar, 30-bar)
        key_windows = ["ret_1_pct", "ret_7_pct", "ret_30_pct"]

        for col in key_windows:
            if col in df.columns:
                # Process each asset separately for rolling calculations
                results = []
                for asset_id, df_asset in df.groupby("id"):
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
        df["is_outlier"] = False

        # Flag outliers in key windows
        key_windows = ["ret_1_pct", "ret_7_pct", "ret_30_pct"]

        for col in key_windows:
            if col in df.columns:
                # Flag using z-score method (4 sigma threshold)
                outlier_flags = flag_outliers(df[col], n_sigma=4.0, method="zscore")
                # Mark as outlier if ANY window is flagged
                df["is_outlier"] = df["is_outlier"] | outlier_flags

        return df

    def __repr__(self) -> str:
        return (
            f"ReturnsFeature("
            f"output_table={self.config.output_schema}.{self.config.output_table}, "
            f"windows={self.config.lookback_windows})"
        )
