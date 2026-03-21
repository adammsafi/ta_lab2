"""
CycleStatsFeature - ATH tracking and drawdown cycle analysis.

Computes cumulative all-time high, drawdown from ATH, cycle low,
and related metrics per (id, tf) from price bar data.

Usage:
    from ta_lab2.scripts.features.cycle_stats_feature import (
        CycleStatsFeature, CycleStatsConfig,
    )

    config = CycleStatsConfig(tf="1D")
    feature = CycleStatsFeature(engine, config)
    rows = feature.compute_for_ids(ids=[1, 52])
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from sqlalchemy import Engine, text

import logging

from ta_lab2.scripts.features.base_feature import BaseFeature, FeatureConfig
from ta_lab2.features.cycle import add_ath_cycle

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CycleStatsConfig(FeatureConfig):
    """Configuration for cycle stats computation."""

    feature_type: str = "cycle_stats"
    output_table: str = "cycle_stats"
    null_strategy: str = "skip"
    add_zscore: bool = False  # No z-scores on cycle metrics


class CycleStatsFeature(BaseFeature):
    """
    Compute ATH tracking and drawdown cycle metrics.

    Uses add_ath_cycle() from ta_lab2.features.cycle for core computation.

    Template method flow:
    1. Load close + ts from price_bars_multi_tf_u
    2. Compute ATH, drawdown, cycle low per asset
    3. No z-scores or outlier flags (cumulative state, not windowed)
    4. Write to cycle_stats
    """

    def __init__(self, engine: Engine, config: Optional[CycleStatsConfig] = None):
        if config is None:
            config = CycleStatsConfig()
        super().__init__(engine, config)

    # -- Asset chunking to limit peak memory ---------------------------------
    CHUNK_SIZE = 20

    def compute_for_ids(
        self,
        ids: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> int:
        """Process in chunks of CHUNK_SIZE assets to limit peak memory."""
        total = 0
        for i in range(0, len(ids), self.CHUNK_SIZE):
            chunk_ids = ids[i : i + self.CHUNK_SIZE]
            logger.debug(
                f"CycleStats chunk {i // self.CHUNK_SIZE + 1}: "
                f"ids {chunk_ids[0]}..{chunk_ids[-1]} ({len(chunk_ids)} assets)"
            )
            total += super().compute_for_ids(chunk_ids, start, end)
        return total

    def load_source_data(
        self,
        ids: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load close prices from price bars. Must load full history for ATH."""
        # ATH requires full history — ignore start/end for the query
        # (cummax needs all prior data to be correct)
        where_clauses = [
            "id = ANY(:ids)",
            "tf = :tf",
            "alignment_source = :as_",
        ]
        params = {
            "ids": ids,
            "tf": self.config.tf,
            "as_": self.get_alignment_source(),
        }

        if self.config.venue_id is not None:
            where_clauses.append("venue_id = :venue_id")
            params["venue_id"] = self.config.venue_id

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                id,
                {self.TS_COLUMN} AS ts,
                venue_id,
                close
            FROM {self.SOURCE_TABLE}
            WHERE {where_sql}
            ORDER BY id, venue_id, ts ASC
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params)

        return df

    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        """Compute ATH cycle metrics per asset."""
        if df_source.empty:
            return pd.DataFrame()

        results = []

        for (id_val, venue_id_val), df_id in df_source.groupby(["id", "venue_id"]):
            df_id = df_id.copy()
            df_id = df_id.sort_values("ts").reset_index(drop=True)

            if len(df_id) < 1:
                continue

            add_ath_cycle(df_id, close_col="close", ts_col="ts")
            results.append(df_id)

        if not results:
            return pd.DataFrame()

        df_features = pd.concat(results, ignore_index=True)

        # Add tf metadata
        df_features["tf"] = self.config.tf
        df_features["alignment_source"] = self.get_alignment_source()
        df_features["tf_days"] = self.get_tf_days()

        return df_features

    def get_output_schema(self) -> dict[str, str]:
        return {
            "id": "INTEGER NOT NULL",
            "ts": "TIMESTAMPTZ NOT NULL",
            "tf": "TEXT NOT NULL",
            "venue_id": "SMALLINT NOT NULL DEFAULT 1",
            "alignment_source": "TEXT NOT NULL",
            "tf_days": "INTEGER NOT NULL",
            "close": "DOUBLE PRECISION",
            "ath": "DOUBLE PRECISION",
            "ath_ts": "TIMESTAMPTZ",
            "dd_from_ath": "DOUBLE PRECISION",
            "bars_since_ath": "INTEGER",
            "days_since_ath": "INTEGER",
            "cycle_low": "DOUBLE PRECISION",
            "cycle_low_ts": "TIMESTAMPTZ",
            "dd_ath_to_low": "DOUBLE PRECISION",
            "bars_ath_to_low": "INTEGER",
            "days_ath_to_low": "INTEGER",
            "is_at_ath": "BOOLEAN DEFAULT FALSE",
            "cycle_number": "INTEGER",
            "updated_at": "TIMESTAMPTZ DEFAULT now()",
        }

    def get_feature_columns(self) -> list[str]:
        return [
            "ath",
            "dd_from_ath",
            "bars_since_ath",
            "days_since_ath",
            "cycle_low",
            "dd_ath_to_low",
            "bars_ath_to_low",
            "days_ath_to_low",
        ]

    def add_normalizations(self, df: pd.DataFrame) -> pd.DataFrame:
        """No z-scores for cycle metrics."""
        return df

    def add_outlier_flags(self, df: pd.DataFrame) -> pd.DataFrame:
        """No outlier flags for cycle metrics."""
        return df
