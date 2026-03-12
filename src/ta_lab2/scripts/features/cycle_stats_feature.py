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

from ta_lab2.scripts.features.base_feature import BaseFeature, FeatureConfig
from ta_lab2.features.cycle import add_ath_cycle


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

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                id,
                {self.TS_COLUMN} AS ts,
                venue,
                venue_rank,
                close
            FROM {self.SOURCE_TABLE}
            WHERE {where_sql}
            ORDER BY id, venue, ts ASC
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params)

        return df

    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        """Compute ATH cycle metrics per asset."""
        if df_source.empty:
            return pd.DataFrame()

        results = []

        for (id_val, venue_val), df_id in df_source.groupby(["id", "venue"]):
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
            "alignment_source": "TEXT NOT NULL",
            "venue": "TEXT NOT NULL DEFAULT 'CMC_AGG'",
            "venue_rank": "INTEGER NOT NULL DEFAULT 50",
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
