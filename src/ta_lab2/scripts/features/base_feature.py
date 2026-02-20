"""
BaseFeature - Abstract base class for feature computation modules.

Following the BaseEMAFeature pattern, this provides a template for all
feature computation types:
- Returns features (simple, log returns)
- Volatility features (Parkinson, GK, RS, etc.)
- Technical indicators (RSI, MACD, etc.)

Design Pattern: Template Method
- Base class defines computation flow
- Subclasses implement specific data loading and feature computation
- Standardizes null handling, normalization, and DB operations
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.features.feature_utils import (
    apply_null_strategy,
    add_zscore as add_zscore_util,
    flag_outliers,
)


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class FeatureConfig:
    """
    Configuration for feature computation.

    Attributes:
        feature_type: Type of feature ('returns', 'vol', 'ta')
        tf: Timeframe code (e.g. '1D', '7D', '30D')
        output_schema: Schema for output table (default: 'public')
        output_table: Output table name (set by subclass)
        null_strategy: Null handling strategy ('skip', 'forward_fill', 'interpolate')
        add_zscore: Whether to add z-score normalization columns
        zscore_window: Rolling window for z-score (default 252 = 1 year)
    """

    feature_type: str  # 'returns', 'vol', 'ta'
    tf: str = "1D"
    output_schema: str = "public"
    output_table: str = ""  # Set by subclass
    null_strategy: str = "skip"
    add_zscore: bool = True
    zscore_window: int = 252


# =============================================================================
# Base Feature Class
# =============================================================================


class BaseFeature(ABC):
    """
    Abstract base class for feature computation modules.

    Template Method Pattern (same as BaseEMAFeature):
    - Defines computation flow (load -> compute -> normalize -> write)
    - Delegates specifics to subclasses
    - Standardizes null handling, normalization, DB operations

    Subclasses must implement:
    - load_source_data(ids, start, end): Load price/bar data
    - compute_features(df_source): Core feature computation
    - get_output_schema(): Define output table schema
    - get_feature_columns(): List of computed feature columns

    Common patterns extracted:
    - Null handling (skip, forward_fill, interpolate)
    - Z-score normalization
    - Outlier flagging (flag but keep)
    - Database writing with table creation
    """

    SOURCE_TABLE = "public.cmc_price_bars_multi_tf"
    TS_COLUMN = "time_close"

    def __init__(self, engine: Engine, config: FeatureConfig):
        """
        Initialize feature computation module.

        Args:
            engine: SQLAlchemy engine
            config: Feature configuration
        """
        self.engine = engine
        self.config = config

    def get_tf_days(self) -> int:
        """Return tf_days for current tf. Cached after first call."""
        if self.config.tf == "1D":
            return 1
        if not hasattr(self, "_tf_days_cache"):
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT tf_days_nominal FROM dim_timeframe WHERE tf = :tf"),
                    {"tf": self.config.tf},
                ).fetchone()
                self._tf_days_cache = row[0] if row else 1
        return self._tf_days_cache

    # =========================================================================
    # Abstract Methods (MUST override)
    # =========================================================================

    @abstractmethod
    def load_source_data(
        self,
        ids: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Load source price/bar data for computation.

        Args:
            ids: List of asset IDs (e.g., cryptocurrency IDs)
            start: Optional start date (inclusive, ISO format)
            end: Optional end date (inclusive, ISO format)

        Returns:
            DataFrame with at minimum: id, ts (or date), price columns
        """

    @abstractmethod
    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        """
        Compute features from source data.

        This is the core computation logic that varies by feature type.

        Args:
            df_source: Source data from load_source_data()
                       (already has null handling applied if configured)

        Returns:
            DataFrame with computed feature columns
            Must include: id, ts (or date), and feature columns from get_feature_columns()
        """

    @abstractmethod
    def get_output_schema(self) -> dict[str, str]:
        """
        Get output table schema definition.

        Returns:
            Dictionary mapping column names to SQL types

        Example:
            {
                "id": "INTEGER",
                "ts": "TIMESTAMPTZ",
                "return_1d": "DOUBLE PRECISION",
                "return_7d": "DOUBLE PRECISION",
                "return_1d_zscore": "DOUBLE PRECISION",
                ...
            }
        """

    @abstractmethod
    def get_feature_columns(self) -> list[str]:
        """
        Get list of computed feature columns.

        Used for applying normalization and outlier detection.

        Returns:
            List of feature column names (excluding id, ts, metadata columns)

        Example:
            ['return_1d', 'return_7d', 'return_30d']
        """

    # =========================================================================
    # Template Methods (Concrete - define flow)
    # =========================================================================

    def compute_for_ids(
        self,
        ids: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> int:
        """
        Compute features for given IDs (template method).

        Flow:
        1. Load source data
        2. Apply null handling (from config)
        3. Compute features
        4. Add z-score if configured
        5. Flag outliers
        6. Write to database

        Args:
            ids: List of asset IDs
            start: Optional start date
            end: Optional end date

        Returns:
            Number of rows written
        """
        # 1. Load source data
        df_source = self.load_source_data(ids, start, end)
        if df_source.empty:
            return 0

        # 2. Apply null handling (if not 'skip')
        if self.config.null_strategy != "skip":
            df_source = self.apply_null_handling(df_source)

        # 3. Compute features
        df_features = self.compute_features(df_source)
        if df_features.empty:
            return 0

        # 4. Add normalizations (z-score if configured)
        df_features = self.add_normalizations(df_features)

        # 5. Flag outliers
        df_features = self.add_outlier_flags(df_features)

        # 6. Write to database
        rows_written = self.write_to_db(df_features)
        return rows_written

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def apply_null_handling(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply null handling strategy to source data.

        Applies configured strategy to price columns (open, high, low, close).

        Args:
            df: Source DataFrame

        Returns:
            DataFrame with nulls handled
        """
        # Identify price columns to apply null handling
        price_cols = []
        for col in ["open", "high", "low", "close", "price"]:
            if col in df.columns:
                price_cols.append(col)

        # Apply strategy to each price column
        df_result = df.copy()
        for col in price_cols:
            df_result[col] = apply_null_strategy(
                df_result[col],
                self.config.null_strategy,
            )

        return df_result

    def add_normalizations(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add normalization columns (z-score if configured).

        Args:
            df: DataFrame with computed features

        Returns:
            DataFrame with added normalization columns
        """
        if not self.config.add_zscore:
            return df

        # Add z-score for each feature column
        feature_cols = self.get_feature_columns()
        for col in feature_cols:
            if col in df.columns:
                add_zscore_util(
                    df,
                    col,
                    window=self.config.zscore_window,
                    out_col=f"{col}_zscore",
                )

        return df

    def add_outlier_flags(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add outlier flag columns for feature columns.

        Per CONTEXT.md: Flag but keep - mark as outlier, preserve original value.

        Args:
            df: DataFrame with computed features

        Returns:
            DataFrame with added outlier flag columns
        """
        feature_cols = self.get_feature_columns()

        for col in feature_cols:
            if col in df.columns:
                # Flag outliers using z-score method (4 sigma threshold)
                outlier_flags = flag_outliers(df[col], n_sigma=4.0, method="zscore")
                df[f"{col}_is_outlier"] = outlier_flags

        return df

    def write_to_db(self, df: pd.DataFrame) -> int:
        """
        Write feature results to database using scoped DELETE + INSERT.

        Deletes existing rows for (ids, tf) batch, then inserts new data.
        Filters DataFrame columns to match the actual DB table columns
        to prevent column mismatch errors.
        Safe for re-runs — no duplicate risk.

        Args:
            df: DataFrame with feature results

        Returns:
            Number of rows written
        """
        if df.empty:
            return 0

        # Ensure output table exists
        self._ensure_output_table()

        fq_table = f"{self.config.output_schema}.{self.config.output_table}"

        # Get actual table columns to filter DataFrame
        table_cols = self._get_table_columns()
        if table_cols:
            # Only keep DataFrame columns that exist in the table
            keep_cols = [c for c in df.columns if c in table_cols]
            df = df[keep_cols]

        # Scoped delete: existing rows for these (ids, tf)
        ids = df["id"].unique().tolist()
        tf = self.config.tf

        with self.engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {fq_table} WHERE id = ANY(:ids) AND tf = :tf"),
                {"ids": ids, "tf": tf},
            )

        # Insert
        df.to_sql(
            self.config.output_table,
            self.engine,
            schema=self.config.output_schema,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=10000,
        )

        return len(df)

    def _get_table_columns(self) -> set[str]:
        """Get column names from the actual DB table. Returns empty set if table doesn't exist."""
        q = text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
        """
        )
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    q,
                    {
                        "schema": self.config.output_schema,
                        "table": self.config.output_table,
                    },
                )
                return {row[0] for row in result}
        except Exception:
            return set()

    def _ensure_output_table(self) -> None:
        """
        Ensure output table exists with correct schema.

        Creates table if it doesn't exist using get_output_schema().
        """
        schema_def = self.get_output_schema()

        columns_sql = ",\n    ".join(
            f"{col} {dtype}" for col, dtype in schema_def.items()
        )

        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.config.output_schema}.{self.config.output_table} (
            {columns_sql}
        )
        """

        with self.engine.begin() as conn:
            conn.execute(text(create_sql))

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"feature_type={self.config.feature_type}, "
            f"output_table={self.config.output_schema}.{self.config.output_table})"
        )
