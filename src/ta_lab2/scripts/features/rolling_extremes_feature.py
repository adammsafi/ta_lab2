"""
RollingExtremesFeature - Rolling high/low over configurable lookback windows.

Computes rolling max/min of close over N-bar windows with range position.
Lookback dimension allows multiple periods per bar, stored in a
separate table with PK (id, ts, tf, alignment_source, lookback_bars).

Default target durations: 90d, 180d, 365d, 730d
Converted to bars per TF: round(target_days / tf_days_nominal)

Usage:
    from ta_lab2.scripts.features.rolling_extremes_feature import (
        RollingExtremesFeature, RollingExtremesConfig,
    )

    config = RollingExtremesConfig(tf="1D")
    feature = RollingExtremesFeature(engine, config)
    rows = feature.compute_for_ids(ids=[1, 52])
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.scripts.features.base_feature import BaseFeature, FeatureConfig
from ta_lab2.features.cycle import add_rolling_extremes


# Target durations in days -> converted to bars per TF
DEFAULT_TARGET_DAYS = (90, 180, 365, 730)
MIN_WINDOW_BARS = 5  # Skip if fewer than 5 bars


@dataclass(frozen=True)
class RollingExtremesConfig(FeatureConfig):
    """Configuration for rolling extremes computation."""

    feature_type: str = "rolling_extremes"
    output_table: str = "rolling_extremes"
    null_strategy: str = "skip"
    add_zscore: bool = False
    target_days: tuple[int, ...] = DEFAULT_TARGET_DAYS


class RollingExtremesFeature(BaseFeature):
    """
    Compute rolling high/low over N-bar windows.

    For each target duration, converts days to bars using tf_days_nominal.
    Produces one row per (id, ts, tf, alignment_source, lookback_bars).

    Template method flow:
    1. Load close + ts from price_bars_multi_tf_u
    2. For each window, compute rolling extremes per asset
    3. Stack all windows into a single DataFrame
    4. Write to rolling_extremes
    """

    def __init__(self, engine: Engine, config: Optional[RollingExtremesConfig] = None):
        if config is None:
            config = RollingExtremesConfig()
        super().__init__(engine, config)
        self.re_config: RollingExtremesConfig = config
        self._windows = self._compute_windows()

    def _compute_windows(self) -> list[int]:
        """Convert target days to bar counts, dedup and filter."""
        tf_days = self.get_tf_days()
        windows = set()
        for target in self.re_config.target_days:
            w = max(1, round(target / tf_days))
            if w >= MIN_WINDOW_BARS:
                windows.add(w)
        return sorted(windows)

    def load_source_data(
        self,
        ids: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load close prices. Needs enough history for largest window."""
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
        """Compute rolling extremes for each window, stacking results."""
        if df_source.empty or not self._windows:
            return pd.DataFrame()

        all_results = []

        for (id_val, venue_val), df_id in df_source.groupby(["id", "venue"]):
            df_id = df_id.copy()
            df_id = df_id.sort_values("ts").reset_index(drop=True)

            if len(df_id) < MIN_WINDOW_BARS:
                continue

            for win in self._windows:
                df_win = df_id[["id", "ts", "venue", "venue_rank", "close"]].copy()
                add_rolling_extremes(df_win, window=win, close_col="close", ts_col="ts")
                df_win["lookback_bars"] = win
                all_results.append(df_win)

        if not all_results:
            return pd.DataFrame()

        df_features = pd.concat(all_results, ignore_index=True)

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
            "lookback_bars": "INTEGER NOT NULL",
            "tf_days": "INTEGER NOT NULL",
            "close": "DOUBLE PRECISION",
            "rolling_high": "DOUBLE PRECISION",
            "rolling_high_ts": "TIMESTAMPTZ",
            "bars_since_rolling_high": "INTEGER",
            "days_since_rolling_high": "INTEGER",
            "rolling_low": "DOUBLE PRECISION",
            "rolling_low_ts": "TIMESTAMPTZ",
            "bars_since_rolling_low": "INTEGER",
            "days_since_rolling_low": "INTEGER",
            "range_position": "DOUBLE PRECISION",
            "dd_from_rolling_high": "DOUBLE PRECISION",
            "updated_at": "TIMESTAMPTZ DEFAULT now()",
        }

    def get_feature_columns(self) -> list[str]:
        return [
            "rolling_high",
            "rolling_low",
            "range_position",
            "dd_from_rolling_high",
        ]

    def add_normalizations(self, df: pd.DataFrame) -> pd.DataFrame:
        """No z-scores for rolling extremes."""
        return df

    def add_outlier_flags(self, df: pd.DataFrame) -> pd.DataFrame:
        """No outlier flags for rolling extremes."""
        return df

    def write_to_db(self, df: pd.DataFrame) -> int:
        """
        Override write_to_db to include lookback_bars in DELETE scope.

        The base class deletes by (ids, tf, alignment_source) which would
        be too broad — we need to scope per lookback_bars too.
        """
        if df.empty:
            return 0

        self._ensure_output_table()

        fq_table = f"{self.config.output_schema}.{self.config.output_table}"

        # Get actual table columns to filter DataFrame
        table_cols = self._get_table_columns()
        if table_cols:
            keep_cols = [c for c in df.columns if c in table_cols]
            df = df[keep_cols]

        ids = df["id"].unique().tolist()
        venues = df["venue"].unique().tolist() if "venue" in df.columns else ["CMC_AGG"]
        tf = self.config.tf
        alignment_source = self.get_alignment_source()
        windows = df["lookback_bars"].unique().tolist()

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"DELETE FROM {fq_table}"
                    " WHERE id = ANY(:ids) AND tf = :tf"
                    " AND alignment_source = :as_"
                    " AND venue = ANY(:venues)"
                    " AND lookback_bars = ANY(:windows)"
                ),
                {
                    "ids": ids,
                    "tf": tf,
                    "as_": alignment_source,
                    "venues": venues,
                    "windows": windows,
                },
            )

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
