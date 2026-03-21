"""
MultiTFAMAFeature - Concrete AMA feature subclass for multi-timeframe bars.

Computes KAMA, DEMA, TEMA, HMA for all 18 parameter sets across the
full timeframe universe from price_bars_multi_tf_u.

Data source:  price_bars_multi_tf_u  (canonical TF bars, alignment_source='multi_tf')
TF universe:  dim_timeframe             (all 109 TFs via tf_days_nominal)
Output table: ama_multi_tf          (id, ts, tf, indicator, params_hash PK)

Usage (scripted):
    python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids 1 --tf 1D

Usage (programmatic):
    from ta_lab2.features.ama.ama_multi_timeframe import MultiTFAMAFeature
    from ta_lab2.features.ama.base_ama_feature import AMAFeatureConfig
    from ta_lab2.features.ama.ama_params import ALL_AMA_PARAMS

    config = AMAFeatureConfig(
        param_sets=ALL_AMA_PARAMS,
        output_schema="public",
        output_table="ama_multi_tf",
    )
    feature = MultiTFAMAFeature(engine, config)
    df = feature.compute_for_asset_tf(engine, asset_id=1, tf="1D", tf_days=1, param_sets=ALL_AMA_PARAMS)
    feature.write_to_db(engine, df, schema="public", table="ama_multi_tf")

CRITICAL (Windows tz pitfall):
    Do NOT call .values on a tz-aware DatetimeIndex/Series — it strips timezone.
    Use .tolist() or pd.to_datetime(utc=True) for explicit UTC coercion.
"""

from __future__ import annotations

import json
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
# dim_ama_params Seeding
# =============================================================================


def populate_dim_ama_params(engine: Engine) -> int:
    """
    Seed dim_ama_params with all 18 canonical AMA parameter sets.

    Idempotent: uses ON CONFLICT (indicator, params_hash) DO NOTHING so
    multiple calls are safe. Call once at the start of each refresh run.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        Number of rows inserted (0 on subsequent calls if already seeded).
    """
    if not ALL_AMA_PARAMS:
        return 0

    rows_inserted = 0
    sql = text(
        """
        INSERT INTO public.dim_ama_params (indicator, params_hash, params_json, label)
        VALUES (:indicator, :params_hash, CAST(:params_json AS jsonb), :label)
        ON CONFLICT (indicator, params_hash) DO NOTHING
        """
    )

    try:
        with engine.begin() as conn:
            for ps in ALL_AMA_PARAMS:
                result = conn.execute(
                    sql,
                    {
                        "indicator": ps.indicator,
                        "params_hash": ps.params_hash,
                        "params_json": json.dumps(ps.params),
                        "label": ps.label,
                    },
                )
                rows_inserted += result.rowcount
    except Exception as exc:
        logger.warning(
            "populate_dim_ama_params: failed to seed dim_ama_params — %s. "
            "Continuing (table may not exist yet).",
            exc,
        )
        return 0

    if rows_inserted > 0:
        logger.info("Seeded %d rows into public.dim_ama_params", rows_inserted)
    else:
        logger.debug("dim_ama_params already seeded — no new rows inserted")

    return rows_inserted


# =============================================================================
# MultiTFAMAFeature
# =============================================================================


class MultiTFAMAFeature(BaseAMAFeature):
    """
    Concrete AMA feature for multi-timeframe bars.

    Loads canonical TF closes from price_bars_multi_tf_u and computes
    all 18 AMA parameter sets (KAMA x3, DEMA x5, TEMA x5, HMA x5) for
    each (asset_id, tf) combination.

    Timeframe universe: loaded from dim_timeframe ordered by tf_days_nominal.
    Incremental refresh: supported via start_ts argument to compute_for_asset_tf.
    """

    # =========================================================================
    # Constructor
    # =========================================================================

    def __init__(
        self,
        engine: Engine,
        config: Optional[AMAFeatureConfig] = None,
        *,
        bars_schema: str = "public",
        bars_table: str = "price_bars_multi_tf_u",
    ) -> None:
        """
        Initialise multi-TF AMA feature.

        Args:
            engine: SQLAlchemy engine.
            config: AMA feature configuration. Defaults to AMAFeatureConfig with
                    ALL_AMA_PARAMS and output_table="ama_multi_tf".
            bars_schema: Schema for bars source table.
            bars_table: Source bars table name.
        """
        if config is None:
            config = AMAFeatureConfig(
                param_sets=list(ALL_AMA_PARAMS),
                output_schema="public",
                output_table="ama_multi_tf",
            )
        super().__init__(engine, config)
        self.bars_schema = bars_schema
        self.bars_table = bars_table

        # Cache TF specs after first load to avoid repeated DB queries
        self._tf_specs_cache: Optional[list[TFSpec]] = None

    # =========================================================================
    # Abstract Method Implementations
    # =========================================================================

    def preload_all_bars(
        self,
        engine: Engine,
        asset_id: int,
        venue_id: int = 1,
    ) -> None:
        """
        Load bars for ALL TFs in a single query and cache.

        Call before the TF loop to avoid per-TF DB queries.
        """
        params: dict = {"id": asset_id, "venue_id": venue_id}
        alignment_filter = ""
        if self.config.alignment_source:
            alignment_filter = "AND alignment_source = :alignment_source"
            params["alignment_source"] = self.config.alignment_source

        sql = text(
            f"""
            SELECT id, venue_id, "timestamp" AS ts, tf, tf_days, is_partial_end AS roll, close, is_partial_end
            FROM {self.bars_schema}.{self.bars_table}
            WHERE id = :id AND venue_id = :venue_id {alignment_filter}
            ORDER BY tf, "timestamp"
            """
        )

        try:
            with engine.connect() as conn:
                df = pd.read_sql(sql, conn, params=params)
        except Exception as exc:
            logger.warning(
                "preload_all_bars: failed for asset_id=%s — %s", asset_id, exc
            )
            self._bars_cache = pd.DataFrame()
            return

        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)

        self._bars_cache = df
        logger.debug(
            "Preloaded bars for asset_id=%s: %d rows across %d TFs",
            asset_id,
            len(df),
            df["tf"].nunique() if not df.empty else 0,
        )

    def _load_bars(
        self,
        engine: Engine,
        asset_id: int,
        tf: str,
        tf_days: int,
        start_ts: Optional[pd.Timestamp],
        venue_id: int = 1,
    ) -> pd.DataFrame:
        """
        Load close prices for a single (asset_id, tf, venue_id) slice (uses cache if available).
        """
        # Use preloaded cache if available
        if self._bars_cache is not None:
            if self._bars_cache.empty:
                return pd.DataFrame()
            mask = self._bars_cache["tf"] == tf
            if start_ts is not None:
                mask = mask & (self._bars_cache["ts"] >= start_ts)
            df = self._bars_cache[mask].copy()
            return df.sort_values("ts").reset_index(drop=True)

        # Fallback: per-TF query
        where_clauses = ["id = :id", "tf = :tf", "venue_id = :venue_id"]
        params: dict = {"id": asset_id, "tf": tf, "venue_id": venue_id}

        if start_ts is not None:
            where_clauses.append('"timestamp" >= :start_ts')
            params["start_ts"] = start_ts

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
                "_load_bars: failed for asset_id=%s tf=%s — %s", asset_id, tf, exc
            )
            return pd.DataFrame()

        if df.empty:
            return df

        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values("ts").reset_index(drop=True)

        return df

    def _get_timeframes(self, engine: Engine) -> list[TFSpec]:
        """
        Load all timeframes from dim_timeframe ordered by tf_days_nominal.

        CRITICAL: Column is `tf_days_nominal` NOT `tf_days` — see MEMORY.md.

        Args:
            engine: SQLAlchemy engine.

        Returns:
            List of TFSpec ordered by tf_days_nominal ascending.

        Raises:
            RuntimeError: If dim_timeframe returns no rows.
        """
        if self._tf_specs_cache is not None:
            return self._tf_specs_cache

        sql = text(
            """
            SELECT tf, tf_days_nominal
            FROM public.dim_timeframe
            ORDER BY tf_days_nominal
            """
        )

        with engine.connect() as conn:
            df = pd.read_sql(sql, conn)

        if df.empty:
            raise RuntimeError(
                "dim_timeframe returned no rows — cannot determine timeframe universe."
            )

        specs = [
            TFSpec(tf=row.tf, tf_days=int(row.tf_days_nominal))
            for row in df.itertuples()
            if row.tf_days_nominal and row.tf_days_nominal > 0
        ]

        if not specs:
            raise RuntimeError(
                "dim_timeframe has no rows with positive tf_days_nominal."
            )

        logger.info("Loaded %d TF specs from dim_timeframe", len(specs))
        self._tf_specs_cache = specs
        return specs

    def _get_source_table_info(self) -> dict:
        """
        Return metadata about the data source for this module.

        Returns:
            Dict with source_table and type keys.
        """
        return {
            "source_table": f"{self.bars_schema}.{self.bars_table}",
            "table": self.bars_table,
            "schema": self.bars_schema,
            "type": "multi_tf",
        }

    # =========================================================================
    # Repr
    # =========================================================================

    def __repr__(self) -> str:
        n = len(self.config.param_sets)
        return (
            f"MultiTFAMAFeature("
            f"param_sets={n}, "
            f"source={self.bars_schema}.{self.bars_table}, "
            f"output={self.config.output_schema}.{self.config.output_table})"
        )
