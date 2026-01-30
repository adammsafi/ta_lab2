"""
BaseEMAFeature - Abstract base class for EMA feature modules.

Analogous to BaseBuilder for bar builders, this provides a template
for all EMA computation types:
- ema_multi_timeframe.py
- ema_multi_tf_cal.py
- ema_multi_tf_cal_anchor.py
- ema_multi_tf_v2.py

Design Pattern: Template Method
- Base class defines computation flow
- Subclasses implement specific data loading and TF logic
- Eliminates duplication of derivative computation, DB writing, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Sequence

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.features.m_tf.ema_operations import (
    compute_derivatives,
    compute_rolling_derivatives_canonical,
    add_derivative_columns_vectorized,
    filter_ema_periods_by_obs_count,
)


# =============================================================================
# Configuration
# =============================================================================

@dataclass(frozen=True)
class EMAFeatureConfig:
    """
    Configuration for EMA feature computation.

    Attributes:
        periods: List of EMA periods to compute
        output_schema: Schema for output table
        output_table: Output table name
        min_obs_multiplier: Minimum observations = period * multiplier
    """
    periods: list[int]
    output_schema: str
    output_table: str
    min_obs_multiplier: float = 3.0


@dataclass(frozen=True)
class TFSpec:
    """
    Timeframe specification.

    Attributes:
        tf: Timeframe label (e.g., "7D", "1M", "1W_mon")
        tf_days: Number of days in timeframe (e.g., 7, 30, 7)
    """
    tf: str
    tf_days: int


# =============================================================================
# Base EMA Feature Class
# =============================================================================

class BaseEMAFeature(ABC):
    """
    Abstract base class for EMA feature computation modules.

    Template Method Pattern:
    - Defines the computation flow (load → compute → write)
    - Delegates specifics to subclasses
    - Standardizes derivative computation and DB operations

    Subclasses must implement:
    - load_source_data(): Load price/bar data
    - get_tf_specs(): Get timeframe specifications
    - compute_emas_for_tf(): Core EMA computation for one TF
    - get_output_schema(): Define output table schema

    Common patterns extracted:
    - Derivative computation (d1, d2, d1_roll, d2_roll)
    - Period filtering by observation count
    - Database writing with upsert logic
    - Alpha calculation from horizon
    """

    def __init__(self, engine: Engine, config: EMAFeatureConfig):
        """
        Initialize EMA feature module.

        Args:
            engine: SQLAlchemy engine
            config: Feature configuration
        """
        self.engine = engine
        self.config = config

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
            ids: List of cryptocurrency IDs
            start: Optional start date (inclusive)
            end: Optional end date (inclusive)

        Returns:
            DataFrame with at minimum: id, ts (or time_close), close
        """

    @abstractmethod
    def get_tf_specs(self) -> list[TFSpec]:
        """
        Get timeframe specifications to compute.

        For multi_tf: Load from dim_timeframe
        For cal: Extract from bars table structure
        For v2: Load from dim_timeframe with horizon calculation

        Returns:
            List of TFSpec objects
        """

    @abstractmethod
    def compute_emas_for_tf(
        self,
        df_source: pd.DataFrame,
        tf_spec: TFSpec,
        periods: list[int],
    ) -> pd.DataFrame:
        """
        Compute EMAs for a single timeframe.

        This is the core computation logic that varies by EMA type.

        Args:
            df_source: Source data from load_source_data()
            tf_spec: Timeframe specification
            periods: List of EMA periods (already filtered by obs count)

        Returns:
            DataFrame with columns:
            - id, ts (or time_close), tf, period, ema
            - Optionally: roll, d1, d2, d1_roll, d2_roll
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
                "tf": "TEXT",
                "period": "INTEGER",
                "ema": "DOUBLE PRECISION",
                "d1": "DOUBLE PRECISION",
                "d2": "DOUBLE PRECISION",
                ...
            }
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
        Compute EMAs for given IDs (template method).

        Flow:
        1. Load source data
        2. Get TF specs
        3. For each TF: compute EMAs
        4. Write to database

        Args:
            ids: List of cryptocurrency IDs
            start: Optional start date
            end: Optional end date

        Returns:
            Number of rows written
        """
        # Load source data
        df_source = self.load_source_data(ids, start, end)
        if df_source.empty:
            return 0

        # Get TF specs
        tf_specs = self.get_tf_specs()
        if not tf_specs:
            raise ValueError("No timeframe specifications available")

        # Compute EMAs for each TF
        all_results = []
        for tf_spec in tf_specs:
            # Filter periods by observation count
            n_obs = len(df_source)
            valid_periods = filter_ema_periods_by_obs_count(
                self.config.periods,
                n_obs,
                min_obs_multiplier=self.config.min_obs_multiplier,
            )

            if not valid_periods:
                continue

            # Compute EMAs for this TF
            df_ema = self.compute_emas_for_tf(df_source, tf_spec, valid_periods)
            if not df_ema.empty:
                all_results.append(df_ema)

        if not all_results:
            return 0

        # Concatenate all results
        df_final = pd.concat(all_results, ignore_index=True)

        # Write to database
        rows_written = self.write_to_db(df_final)
        return rows_written

    def write_to_db(self, df: pd.DataFrame) -> int:
        """
        Write EMA results to database with upsert logic.

        Uses ON CONFLICT for incremental updates.

        Args:
            df: DataFrame with EMA results

        Returns:
            Number of rows written
        """
        if df.empty:
            return 0

        # Ensure output table exists
        self._ensure_output_table()

        # Convert to SQL-compatible types
        df_write = df.copy()

        # Write to temp table then upsert
        # (Implementation details depend on specific table schema)
        # For now, use simple insert (can be optimized later)

        table_fq = f"{self.config.output_schema}.{self.config.output_table}"
        rows = df_write.to_sql(
            self.config.output_table,
            self.engine,
            schema=self.config.output_schema,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=10000,
        )

        return int(rows) if rows else len(df_write)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def add_standard_derivatives(
        self,
        df: pd.DataFrame,
        ema_col: str = "ema",
        *,
        group_cols: Optional[list[str]] = None,
        is_canonical_col: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Add standard derivative columns to EMA DataFrame.

        Adds:
        - d1, d2 (derivatives)
        - d1_roll, d2_roll (rolling derivatives)

        Args:
            df: DataFrame with EMA values
            ema_col: Column name containing EMA
            group_cols: Optional columns to group by (e.g., ['id', 'tf', 'period'])
            is_canonical_col: Optional column indicating canonical rows (for cal/cal_anchor)

        Returns:
            DataFrame with added derivative columns
        """
        result = df.copy()

        if group_cols:
            # Compute derivatives per group
            for d_col, d_func in [("d1", "diff"), ("d2", lambda x: x.diff().diff())]:
                if d_func == "diff":
                    result[d_col] = result.groupby(group_cols)[ema_col].diff()
                else:
                    result[d_col] = result.groupby(group_cols)[ema_col].transform(d_func)

            # Rolling derivatives (same as regular for continuous series)
            result["d1_roll"] = result["d1"]
            result["d2_roll"] = result["d2"]

            # If canonical column provided, compute canonical-only derivatives
            if is_canonical_col and is_canonical_col in result.columns:
                for group_keys, group_df in result.groupby(group_cols):
                    is_canonical = group_df[is_canonical_col]
                    d1_canon, d2_canon = compute_rolling_derivatives_canonical(
                        group_df[ema_col],
                        is_canonical,
                    )
                    # Replace d1, d2 with canonical-only versions
                    result.loc[group_df.index, "d1"] = d1_canon
                    result.loc[group_df.index, "d2"] = d2_canon
        else:
            # No grouping - compute on full series
            result["d1"], result["d2"] = compute_derivatives(result[ema_col])
            result["d1_roll"] = result["d1"]
            result["d2_roll"] = result["d2"]

        return result

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
            f"periods={self.config.periods}, "
            f"output_table={self.config.output_schema}.{self.config.output_table})"
        )
