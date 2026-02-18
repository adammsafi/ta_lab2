"""
Multi-timeframe V2 EMA feature - REFACTORED to use BaseEMAFeature.

V2 semantics:
- One row per DAILY bar from cmc_price_bars_1d (validated bars).
- For each (tf, period):
    * Compute a single, continuous DAILY EMA.
    * Alpha is based on a DAYS horizon: horizon_days = tf_days * period.
    * roll = FALSE on every tf_days-th day (per id, per tf), TRUE otherwise.

LEAN SCHEMA: EMA tables store only EMA values. All derivatives
(d1, d2, delta1, delta2, ret_arith, ret_log) live in returns tables.

REFACTORED CHANGES:
- Extends BaseEMAFeature abstract class
- Uses ema_operations utilities for alpha/derivative calculations
- Eliminates duplication with other EMA modules
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.features.m_tf.base_ema_feature import (
    BaseEMAFeature,
    EMAFeatureConfig,
    TFSpec,
)
from ta_lab2.features.m_tf.ema_operations import (
    filter_ema_periods_by_obs_count,
)
from ta_lab2.features.m_tf.polars_ema_operations import compute_bar_ema_numpy
from ta_lab2.time.dim_timeframe import get_tf_days, list_tfs

logger = logging.getLogger(__name__)


# =============================================================================
# V2 EMA Feature Implementation
# =============================================================================


class MultiTFV2EMAFeature(BaseEMAFeature):
    """
    V2 EMA feature: Daily-space EMAs with dynamic timeframe universe.

    Key differences from other EMA features:
    - Uses cmc_price_bars_1d (validated bars) exclusively
    - Computes all TFs from daily data (no multi-tf bars needed)
    - Horizon-based alpha: alpha = 2 / (tf_days * period + 1)
    - Roll flag: FALSE every tf_days-th day
    """

    def __init__(
        self,
        engine: Engine,
        config: EMAFeatureConfig,
        *,
        alignment_type: str = "tf_day",
        canonical_only: bool = True,
        price_schema: str = "public",
        price_table: str = "cmc_price_bars_1d",
    ):
        """
        Initialize V2 EMA feature.

        Args:
            engine: SQLAlchemy engine
            config: EMA feature configuration
            alignment_type: dim_timeframe alignment type filter
            canonical_only: Only include canonical TFs from dim_timeframe
            price_schema: Schema for price bars table
            price_table: Price bars table name (default: cmc_price_bars_1d)
        """
        super().__init__(engine, config)
        self.alignment_type = alignment_type
        self.canonical_only = canonical_only
        self.price_schema = price_schema
        self.price_table = price_table

        # Cache TF universe (expensive to resolve)
        self._tf_specs_cache: Optional[list[TFSpec]] = None

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
        Load daily price data from cmc_price_bars_1d.

        Returns DataFrame with columns: id, ts, close
        """
        where_clauses = ["is_partial_end = FALSE"]

        if ids:
            ids_str = ",".join(map(str, ids))
            where_clauses.append(f"id IN ({ids_str})")

        if start:
            where_clauses.append(f"\"timestamp\" >= '{start}'")

        if end:
            where_clauses.append(f"\"timestamp\" <= '{end}'")

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                id,
                "timestamp" AS ts,
                close
            FROM {self.price_schema}.{self.price_table}
            WHERE {where_sql}
            ORDER BY id, "timestamp"
        """

        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn)

        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)

        logger.info(
            f"Loaded {len(df)} daily bars for {len(ids)} IDs from {self.price_schema}.{self.price_table}"
        )
        return df

    def get_tf_specs(self) -> list[TFSpec]:
        """
        Load timeframe specs from dim_timeframe.

        Returns TF specs for alignment_type (e.g., "tf_day") filtered by canonical_only.
        Caches result since TF universe is static for a given config.
        """
        if self._tf_specs_cache is not None:
            return self._tf_specs_cache

        # Extract db_url from engine for list_tfs
        db_url = self.engine.url.render_as_string(hide_password=False)

        # Get TF labels from dim_timeframe
        tf_labels = list_tfs(
            db_url=db_url,
            alignment_type=self.alignment_type,
            canonical_only=self.canonical_only,
        )

        # Filter to only numeric+D format (e.g., "7D", "365D")
        valid_tfs = []
        dropped = []

        for tf in tf_labels:
            tf_str = str(tf)
            if tf_str.endswith("D") and tf_str[:-1].isdigit():
                valid_tfs.append(tf_str)
            else:
                dropped.append(tf_str)

        if dropped:
            logger.info(f"Dropping {len(dropped)} non-day TF labels: {dropped[:10]}")

        if not valid_tfs:
            raise RuntimeError(
                f"No valid day-based TFs found for alignment_type='{self.alignment_type}'. "
                f"Check dim_timeframe."
            )

        # Get tf_days for each TF
        tf_specs = []
        missing_days = []

        for tf in valid_tfs:
            try:
                # Note: get_tf_days signature is (tf, db_url) not (db_url, tf)
                tf_days = get_tf_days(tf, db_url)
                if tf_days and tf_days > 0:
                    tf_specs.append(TFSpec(tf=tf, tf_days=int(tf_days)))
                else:
                    missing_days.append(tf)
            except (KeyError, Exception):
                missing_days.append(tf)

        if missing_days:
            logger.warning(
                f"Skipping {len(missing_days)} TFs with missing tf_days: {missing_days[:10]}"
            )

        if not tf_specs:
            raise RuntimeError(
                f"No TFs with valid tf_days found for alignment_type='{self.alignment_type}'"
            )

        logger.info(
            f"Resolved {len(tf_specs)} TF specs for alignment_type='{self.alignment_type}'"
        )

        # Cache result
        self._tf_specs_cache = tf_specs
        return tf_specs

    def compute_emas_for_tf(
        self,
        df_source: pd.DataFrame,
        tf_spec: TFSpec,
        periods: list[int],
    ) -> pd.DataFrame:
        """
        Compute V2 EMAs for a single timeframe.

        Vectorized with numpy: compute_bar_ema_numpy replaces pandas compute_ema,
        numpy array ops replace pandas .diff() and .loc[] operations.

        Returns DataFrame with columns:
        id, ts, tf, period, tf_days, roll, ema
        """
        out_cols = [
            "id",
            "ts",
            "tf",
            "period",
            "tf_days",
            "roll",
            "ema",
            "is_partial_end",
        ]

        if df_source.empty:
            return pd.DataFrame(columns=out_cols)

        out_frames: List[pd.DataFrame] = []

        for id_val, df_id in df_source.groupby("id"):
            df_id = df_id.sort_values("ts").reset_index(drop=True)
            n_obs = len(df_id)

            # Filter periods based on effective observations for this TF
            effective_n_obs = n_obs // tf_spec.tf_days if tf_spec.tf_days > 0 else 0
            valid_periods = filter_ema_periods_by_obs_count(
                periods,
                effective_n_obs,
                min_obs_multiplier=self.config.min_obs_multiplier,
            )

            if not valid_periods:
                continue

            # Pre-extract numpy arrays (shared across periods)
            id_arr = df_id["id"].values
            ts_arr = df_id["ts"].values
            close_arr = df_id["close"].to_numpy(dtype=np.float64)

            # Roll mask: FALSE every tf_days-th day (shared across periods)
            day_index = np.arange(n_obs, dtype=np.int64)
            roll_arr = ((day_index + 1) % tf_spec.tf_days) != 0  # True=roll

            for period in valid_periods:
                period_int = int(period)
                horizon_days = tf_spec.tf_days * period_int

                # Compute daily EMA with numpy (replaces pandas compute_ema)
                ema_arr = compute_bar_ema_numpy(
                    close_arr, period=horizon_days, min_periods=horizon_days
                )

                # Seeding rule: skip rows before horizon_days
                if horizon_days > 1 and n_obs >= horizon_days:
                    start_idx = horizon_days - 1
                else:
                    continue

                # Slice all arrays from start_idx
                ema_sl = ema_arr[start_idx:]
                ts_sl = ts_arr[start_idx:]
                id_sl = id_arr[start_idx:]
                roll_sl = roll_arr[start_idx:]

                # is_partial_end: True for rows after last canonical close
                roll_sl_bool = roll_sl.astype(bool)
                canon_positions = np.where(~roll_sl_bool)[0]
                if len(canon_positions) > 0:
                    last_canon_idx = canon_positions[-1]
                    is_partial_sl = np.arange(len(roll_sl)) > last_canon_idx
                else:
                    is_partial_sl = np.ones(len(roll_sl), dtype=bool)

                df_tf = pd.DataFrame(
                    {
                        "id": id_sl,
                        "ts": ts_sl,
                        "tf": tf_spec.tf,
                        "period": period_int,
                        "tf_days": tf_spec.tf_days,
                        "roll": roll_sl,
                        "ema": ema_sl,
                        "is_partial_end": is_partial_sl,
                    }
                )

                out_frames.append(df_tf[out_cols])

        if not out_frames:
            return pd.DataFrame(columns=out_cols)

        return pd.concat(out_frames, ignore_index=True)

    def get_output_schema(self) -> dict[str, str]:
        """Define output table schema for V2 EMAs (lean - EMA only)."""
        return {
            "id": "INTEGER NOT NULL",
            "ts": "TIMESTAMPTZ NOT NULL",
            "tf": "TEXT NOT NULL",
            "period": "INTEGER NOT NULL",
            "tf_days": "INTEGER",
            "roll": "BOOLEAN",
            "ema": "DOUBLE PRECISION",
            "is_partial_end": "BOOLEAN",
            "ingested_at": "TIMESTAMPTZ DEFAULT now()",
            "PRIMARY KEY": "(id, ts, tf, period)",
        }


# =============================================================================
# Public API (Backward Compatibility)
# =============================================================================


def refresh_cmc_ema_multi_tf_v2_incremental(
    engine: Engine,
    *,
    periods: Sequence[int],
    ids: Sequence[int],
    alignment_type: str = "tf_day",
    canonical_only: bool = True,
    price_schema: str = "public",
    price_table: str = "cmc_price_bars_1d",
    out_schema: str = "public",
    out_table: str = "cmc_ema_multi_tf_v2",
) -> None:
    """
    Incremental refresh for cmc_ema_multi_tf_v2 (backward compatibility wrapper).

    REFACTORED: Now uses MultiTFV2EMAFeature class internally.

    Args:
        engine: SQLAlchemy engine
        periods: EMA periods to compute
        ids: Cryptocurrency IDs
        alignment_type: dim_timeframe alignment_type filter
        canonical_only: Only canonical TFs
        price_schema: Schema for price bars
        price_table: Price bars table name
        out_schema: Output schema
        out_table: Output table name
    """
    config = EMAFeatureConfig(
        periods=list(periods),
        output_schema=out_schema,
        output_table=out_table,
        min_obs_multiplier=1.0,
    )

    feature = MultiTFV2EMAFeature(
        engine=engine,
        config=config,
        alignment_type=alignment_type,
        canonical_only=canonical_only,
        price_schema=price_schema,
        price_table=price_table,
    )

    # Compute and write
    rows = feature.compute_for_ids(list(ids))

    if rows == 0:
        logger.info("No new EMA rows to insert for any id.")
    else:
        logger.info(f"Inserted/updated {rows} EMA rows.")
