"""
Calendar-anchor multi-timeframe AMA feature classes.

Covers two calendar anchor schemes:
- CalAnchorUSAMAFeature  : loads from price_bars_multi_tf_u (alignment_source='multi_tf_cal_anchor_us')
- CalAnchorISOAMAFeature : loads from price_bars_multi_tf_u (alignment_source='multi_tf_cal_anchor_iso')

Both extend BaseAMAFeature and write to their respective output tables:
  ama_multi_tf_cal_anchor_us
  ama_multi_tf_cal_anchor_iso

Design matches CalUSAMAFeature/CalISOAMAFeature except:
- Source bars tables are the anchor-aligned variants
- TF universe is loaded from dim_timeframe WHERE roll_policy = 'calendar_anchor'
  for the respective calendar_scheme
- tf_days from tf_days_nominal (CRITICAL: NOT tf_days — see MEMORY.md)

CRITICAL (Windows tz pitfall):
    Do NOT call .values on a tz-aware DatetimeIndex/Series — it strips timezone.
    Use .tolist() or pd.to_datetime(utc=True) for explicit UTC coercion.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.features.ama.base_ama_feature import (
    AMAFeatureConfig,
    BaseAMAFeature,
    TFSpec,
)
from ta_lab2.features.ama.ama_params import ALL_AMA_PARAMS

logger = logging.getLogger(__name__)


# =============================================================================
# CalAnchorUSAMAFeature
# =============================================================================


class CalAnchorUSAMAFeature(BaseAMAFeature):
    """
    AMA feature for US calendar-anchor bars.

    Loads close prices from price_bars_multi_tf_u (alignment_source='multi_tf_cal_anchor_us').
    TF universe: calendar anchor TFs with US scheme from dim_timeframe.
    Output table: ama_multi_tf_cal_anchor_us.
    """

    def __init__(
        self,
        engine: Engine,
        config: Optional[AMAFeatureConfig] = None,
        *,
        bars_schema: str = "public",
        bars_table: str = "price_bars_multi_tf_u",
    ) -> None:
        """
        Initialise calendar anchor US AMA feature.

        Args:
            engine: SQLAlchemy engine.
            config: AMA feature configuration. Defaults to AMAFeatureConfig with
                    ALL_AMA_PARAMS and output_table="ama_multi_tf_cal_anchor_us".
            bars_schema: Schema for bars source table.
            bars_table: Source bars table name.
        """
        if config is None:
            config = AMAFeatureConfig(
                param_sets=list(ALL_AMA_PARAMS),
                output_schema="public",
                output_table="ama_multi_tf_cal_anchor_us",
            )
        super().__init__(engine, config)
        self.bars_schema = bars_schema
        self.bars_table = bars_table
        self._tf_specs_cache: Optional[list[TFSpec]] = None

    # =========================================================================
    # Abstract Method Implementations
    # =========================================================================

    def preload_all_bars(
        self, engine: Engine, asset_id: int, venue_id: int = 1
    ) -> None:
        """Load bars for ALL TFs and venues in a single query and cache."""
        params: dict = {"id": asset_id}
        alignment_filter = ""
        if self.config.alignment_source:
            alignment_filter = "AND alignment_source = :alignment_source"
            params["alignment_source"] = self.config.alignment_source

        sql = text(
            f"""
            SELECT id, venue_id, "timestamp" AS ts, tf, tf_days, is_partial_end AS roll, close, is_partial_end
            FROM {self.bars_schema}.{self.bars_table}
            WHERE id = :id {alignment_filter}
            ORDER BY venue_id, tf, "timestamp"
            """
        )
        try:
            with engine.connect() as conn:
                df = pd.read_sql(sql, conn, params=params)
        except Exception as exc:
            logger.warning(
                "preload_all_bars: failed for asset_id=%s table=%s — %s",
                asset_id,
                self.bars_table,
                exc,
            )
            self._bars_cache = pd.DataFrame()
            return
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
        self._bars_cache = df

    def _load_bars(
        self,
        engine: Engine,
        asset_id: int,
        tf: str,
        tf_days: int,
        start_ts: Optional[pd.Timestamp],
        venue_id: int = 1,
    ) -> pd.DataFrame:
        """Load close prices for a single (asset_id, tf, venue_id) slice (uses cache if available)."""
        if self._bars_cache is not None:
            if self._bars_cache.empty:
                return pd.DataFrame()
            mask = (self._bars_cache["tf"] == tf) & (
                self._bars_cache["venue_id"] == venue_id
            )
            if start_ts is not None:
                mask = mask & (self._bars_cache["ts"] >= start_ts)
            df = self._bars_cache[mask].copy()
            return df.sort_values("ts").reset_index(drop=True)

        where_clauses = ["id = :id", "tf = :tf", "venue_id = :venue_id"]
        params: dict = {"id": asset_id, "tf": tf, "venue_id": venue_id}
        if start_ts is not None:
            where_clauses.append('"timestamp" >= :start_ts')
            params["start_ts"] = start_ts
        if self.config.alignment_source:
            where_clauses.append("alignment_source = :alignment_source")
            params["alignment_source"] = self.config.alignment_source
        where_sql = " AND ".join(where_clauses)
        sql = text(
            f"""
            SELECT id, venue_id, "timestamp" AS ts, tf, tf_days, is_partial_end AS roll, close, is_partial_end
            FROM {self.bars_schema}.{self.bars_table}
            WHERE {where_sql}
            ORDER BY "timestamp"
            """
        )
        try:
            with engine.connect() as conn:
                df = pd.read_sql(sql, conn, params=params)
        except Exception as exc:
            logger.warning(
                "_load_bars: failed for asset_id=%s tf=%s table=%s — %s",
                asset_id,
                tf,
                self.bars_table,
                exc,
            )
            return pd.DataFrame()
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values("ts").reset_index(drop=True)
        return df

    def _get_timeframes(self, engine: Engine) -> list[TFSpec]:
        """
        Load calendar anchor US TF specs from dim_timeframe.

        Queries for roll_policy='calendar_anchor' TFs with US scheme.
        tf_days from tf_days_nominal.

        CRITICAL: Column is `tf_days_nominal` NOT `tf_days` — see MEMORY.md.

        Args:
            engine: SQLAlchemy engine.

        Returns:
            List of TFSpec for US calendar anchor TFs, ordered by sort_order.

        Raises:
            RuntimeError: If no calendar anchor US TFs found.
        """
        if self._tf_specs_cache is not None:
            return self._tf_specs_cache

        sql = text(
            """
            SELECT tf, tf_days_nominal
            FROM public.dim_timeframe
            WHERE alignment_type = 'calendar'
              AND roll_policy = 'calendar_anchor'
              AND has_roll_flag = TRUE
              AND allow_partial_start = TRUE
              AND allow_partial_end = TRUE
              AND (
                (base_unit = 'W'
                 AND calendar_scheme = 'US'
                 AND tf LIKE ('%\\_CAL\\_ANCHOR\\_US') ESCAPE '\\')
                OR
                (base_unit IN ('M','Y')
                 AND tf LIKE '%\\_CAL\\_ANCHOR' ESCAPE '\\')
              )
            ORDER BY sort_order, tf
            """
        )

        with engine.connect() as conn:
            df = pd.read_sql(sql, conn)

        if df.empty:
            raise RuntimeError("No calendar anchor US TFs found in dim_timeframe.")

        specs = [
            TFSpec(tf=row.tf, tf_days=int(row.tf_days_nominal))
            for row in df.itertuples()
            if row.tf_days_nominal and row.tf_days_nominal > 0
        ]

        if not specs:
            raise RuntimeError(
                "dim_timeframe has no calendar anchor US TFs with positive tf_days_nominal."
            )

        logger.info(
            "Loaded %d calendar anchor US TF specs from dim_timeframe", len(specs)
        )
        self._tf_specs_cache = specs
        return specs

    def _get_source_table_info(self) -> dict:
        """Return metadata about the data source for this module."""
        return {
            "source_table": f"{self.bars_schema}.{self.bars_table}",
            "table": self.bars_table,
            "schema": self.bars_schema,
            "type": "cal_anchor_us",
        }

    # =========================================================================
    # Repr
    # =========================================================================

    def __repr__(self) -> str:
        n = len(self.config.param_sets)
        return (
            f"CalAnchorUSAMAFeature("
            f"param_sets={n}, "
            f"source={self.bars_schema}.{self.bars_table}, "
            f"output={self.config.output_schema}.{self.config.output_table})"
        )


# =============================================================================
# CalAnchorISOAMAFeature
# =============================================================================


class CalAnchorISOAMAFeature(BaseAMAFeature):
    """
    AMA feature for ISO calendar-anchor bars.

    Loads close prices from price_bars_multi_tf_u (alignment_source='multi_tf_cal_anchor_iso').
    TF universe: calendar anchor TFs with ISO scheme from dim_timeframe.
    Output table: ama_multi_tf_cal_anchor_iso.
    """

    def __init__(
        self,
        engine: Engine,
        config: Optional[AMAFeatureConfig] = None,
        *,
        bars_schema: str = "public",
        bars_table: str = "price_bars_multi_tf_u",
    ) -> None:
        """
        Initialise calendar anchor ISO AMA feature.

        Args:
            engine: SQLAlchemy engine.
            config: AMA feature configuration. Defaults to AMAFeatureConfig with
                    ALL_AMA_PARAMS and output_table="ama_multi_tf_cal_anchor_iso".
            bars_schema: Schema for bars source table.
            bars_table: Source bars table name.
        """
        if config is None:
            config = AMAFeatureConfig(
                param_sets=list(ALL_AMA_PARAMS),
                output_schema="public",
                output_table="ama_multi_tf_cal_anchor_iso",
            )
        super().__init__(engine, config)
        self.bars_schema = bars_schema
        self.bars_table = bars_table
        self._tf_specs_cache: Optional[list[TFSpec]] = None

    # =========================================================================
    # Abstract Method Implementations
    # =========================================================================

    def preload_all_bars(
        self, engine: Engine, asset_id: int, venue_id: int = 1
    ) -> None:
        """Load bars for ALL TFs and venues in a single query and cache."""
        params: dict = {"id": asset_id}
        alignment_filter = ""
        if self.config.alignment_source:
            alignment_filter = "AND alignment_source = :alignment_source"
            params["alignment_source"] = self.config.alignment_source

        sql = text(
            f"""
            SELECT id, venue_id, "timestamp" AS ts, tf, tf_days, is_partial_end AS roll, close, is_partial_end
            FROM {self.bars_schema}.{self.bars_table}
            WHERE id = :id {alignment_filter}
            ORDER BY venue_id, tf, "timestamp"
            """
        )
        try:
            with engine.connect() as conn:
                df = pd.read_sql(sql, conn, params=params)
        except Exception as exc:
            logger.warning(
                "preload_all_bars: failed for asset_id=%s table=%s — %s",
                asset_id,
                self.bars_table,
                exc,
            )
            self._bars_cache = pd.DataFrame()
            return
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
        self._bars_cache = df

    def _load_bars(
        self,
        engine: Engine,
        asset_id: int,
        tf: str,
        tf_days: int,
        start_ts: Optional[pd.Timestamp],
        venue_id: int = 1,
    ) -> pd.DataFrame:
        """Load close prices for a single (asset_id, tf, venue_id) slice (uses cache if available)."""
        if self._bars_cache is not None:
            if self._bars_cache.empty:
                return pd.DataFrame()
            mask = (self._bars_cache["tf"] == tf) & (
                self._bars_cache["venue_id"] == venue_id
            )
            if start_ts is not None:
                mask = mask & (self._bars_cache["ts"] >= start_ts)
            df = self._bars_cache[mask].copy()
            return df.sort_values("ts").reset_index(drop=True)

        where_clauses = ["id = :id", "tf = :tf", "venue_id = :venue_id"]
        params: dict = {"id": asset_id, "tf": tf, "venue_id": venue_id}
        if start_ts is not None:
            where_clauses.append('"timestamp" >= :start_ts')
            params["start_ts"] = start_ts
        if self.config.alignment_source:
            where_clauses.append("alignment_source = :alignment_source")
            params["alignment_source"] = self.config.alignment_source
        where_sql = " AND ".join(where_clauses)
        sql = text(
            f"""
            SELECT id, venue_id, "timestamp" AS ts, tf, tf_days, is_partial_end AS roll, close, is_partial_end
            FROM {self.bars_schema}.{self.bars_table}
            WHERE {where_sql}
            ORDER BY "timestamp"
            """
        )
        try:
            with engine.connect() as conn:
                df = pd.read_sql(sql, conn, params=params)
        except Exception as exc:
            logger.warning(
                "_load_bars: failed for asset_id=%s tf=%s table=%s — %s",
                asset_id,
                tf,
                self.bars_table,
                exc,
            )
            return pd.DataFrame()
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values("ts").reset_index(drop=True)
        return df

    def _get_timeframes(self, engine: Engine) -> list[TFSpec]:
        """
        Load calendar anchor ISO TF specs from dim_timeframe.

        Queries for roll_policy='calendar_anchor' TFs with ISO scheme.
        tf_days from tf_days_nominal.

        CRITICAL: Column is `tf_days_nominal` NOT `tf_days` — see MEMORY.md.

        Args:
            engine: SQLAlchemy engine.

        Returns:
            List of TFSpec for ISO calendar anchor TFs, ordered by sort_order.

        Raises:
            RuntimeError: If no calendar anchor ISO TFs found.
        """
        if self._tf_specs_cache is not None:
            return self._tf_specs_cache

        sql = text(
            """
            SELECT tf, tf_days_nominal
            FROM public.dim_timeframe
            WHERE alignment_type = 'calendar'
              AND roll_policy = 'calendar_anchor'
              AND has_roll_flag = TRUE
              AND allow_partial_start = TRUE
              AND allow_partial_end = TRUE
              AND (
                (base_unit = 'W'
                 AND calendar_scheme = 'ISO'
                 AND tf LIKE ('%\\_CAL\\_ANCHOR\\_ISO') ESCAPE '\\')
                OR
                (base_unit IN ('M','Y')
                 AND tf LIKE '%\\_CAL\\_ANCHOR' ESCAPE '\\')
              )
            ORDER BY sort_order, tf
            """
        )

        with engine.connect() as conn:
            df = pd.read_sql(sql, conn)

        if df.empty:
            raise RuntimeError("No calendar anchor ISO TFs found in dim_timeframe.")

        specs = [
            TFSpec(tf=row.tf, tf_days=int(row.tf_days_nominal))
            for row in df.itertuples()
            if row.tf_days_nominal and row.tf_days_nominal > 0
        ]

        if not specs:
            raise RuntimeError(
                "dim_timeframe has no calendar anchor ISO TFs with positive tf_days_nominal."
            )

        logger.info(
            "Loaded %d calendar anchor ISO TF specs from dim_timeframe", len(specs)
        )
        self._tf_specs_cache = specs
        return specs

    def _get_source_table_info(self) -> dict:
        """Return metadata about the data source for this module."""
        return {
            "source_table": f"{self.bars_schema}.{self.bars_table}",
            "table": self.bars_table,
            "schema": self.bars_schema,
            "type": "cal_anchor_iso",
        }

    # =========================================================================
    # Repr
    # =========================================================================

    def __repr__(self) -> str:
        n = len(self.config.param_sets)
        return (
            f"CalAnchorISOAMAFeature("
            f"param_sets={n}, "
            f"source={self.bars_schema}.{self.bars_table}, "
            f"output={self.config.output_schema}.{self.config.output_table})"
        )
