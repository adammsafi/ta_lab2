"""
Multi-timeframe EMA - REFACTORED to use BaseEMAFeature.

Multi-TF EMA semantics:
- Canonical closes from persisted bars (cmc_price_bars_multi_tf) OR synthetic from daily
- Timeframe universe from dim_timeframe (tf_day family)
- Preview EMAs: daily grid with EMAs between canonical closes
- Roll flag: FALSE for canonical, TRUE for preview

LEAN SCHEMA: EMA tables store only EMA values. All derivatives
(d1, d2, delta1, delta2, ret_arith, ret_log) live in returns tables.

REFACTORED CHANGES:
- Extends BaseEMAFeature abstract class
- Complexity remains due to dual data source + preview logic
"""

from __future__ import annotations

from typing import List, Optional, Sequence
import logging

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from ta_lab2.features.m_tf.base_ema_feature import (
    BaseEMAFeature,
    EMAFeatureConfig,
    TFSpec,
)
from ta_lab2.features.ema import filter_ema_periods_by_obs_count
from ta_lab2.features.m_tf.polars_ema_operations import (
    compute_bar_ema_numpy,
    compute_dual_ema_numpy,
)
from ta_lab2.time.dim_timeframe import list_tfs, get_tf_days
from ta_lab2.io import _get_marketdata_engine as _get_engine

logger = logging.getLogger(__name__)


# =============================================================================
# Multi-TF EMA Feature Implementation
# =============================================================================


class MultiTFEMAFeature(BaseEMAFeature):
    """
    Multi-timeframe EMA feature: EMAs with preview values on daily grid.

    Key characteristics:
    - Uses persisted bars from cmc_price_bars_multi_tf OR synthetic from daily
    - Loads TFs from dim_timeframe (tf_day family)
    - Preview EMAs between canonical closes
    - Roll flag: FALSE for canonical, TRUE for preview
    """

    def __init__(
        self,
        engine: Engine,
        config: EMAFeatureConfig,
        *,
        bars_schema: str = "public",
        bars_table: str = "cmc_price_bars_multi_tf",
        tf_subset: Optional[Sequence[str]] = None,
    ):
        """
        Initialize multi-TF EMA feature.

        Args:
            engine: SQLAlchemy engine
            config: EMA feature configuration
            bars_schema: Schema for bars table
            bars_table: Bars table name (persisted TF bars)
            tf_subset: Optional subset of TFs to compute (day-label format like "7D", "14D")
        """
        super().__init__(engine, config)
        self.bars_schema = bars_schema
        self.bars_table = bars_table
        self.tf_subset = list(tf_subset) if tf_subset else None

        self._tf_specs_cache: Optional[List[TFSpec]] = None
        self._daily_data_cache: Optional[pd.DataFrame] = None

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
        Load daily closes for all IDs.

        Returns: DataFrame with id, ts, close (normalized)
        """
        # Load directly from price_histories to avoid config-file dependency
        # (load_cmc_ohlcv_daily requires configs/default.yaml for table resolution)
        where = ["id = ANY(:ids)", "timestamp >= :start"]
        params: dict = {"ids": list(ids), "start": "2010-01-01"}
        if end is not None:
            where.append("timestamp < :end")
            params["end"] = end

        sql = text(
            f"SELECT id, timestamp AS ts, open, high, low, close, volume "
            f"FROM public.cmc_price_bars_1d "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY id, timestamp"
        )

        with self.engine.connect() as conn:
            daily = pd.read_sql(sql, conn, params=params)

        daily = self._normalize_daily(daily)
        self._daily_data_cache = daily
        return daily

    def get_tf_specs(self) -> List[TFSpec]:
        """Load TF specs from dim_timeframe (tf_day family)."""
        if self._tf_specs_cache is not None:
            return self._tf_specs_cache

        # Extract db_url from engine for list_tfs
        db_url = self.engine.url.render_as_string(hide_password=False)

        all_tf_day = list_tfs(
            db_url=db_url, alignment_type="tf_day", canonical_only=True
        )
        if not all_tf_day:
            raise RuntimeError("dim_timeframe returned no canonical tf_day timeframes")

        # Filter to day-label format (e.g., "7D", "14D")
        def is_day_label(tf: str) -> bool:
            tf = (tf or "").strip()
            return tf.endswith("D") and tf[:-1].isdigit()

        all_tf_day_d = [tf for tf in all_tf_day if is_day_label(tf)]
        if not all_tf_day_d:
            raise RuntimeError(
                "No day-label TFs found in dim_timeframe (e.g., '7D', '14D')"
            )

        # Apply subset filter if provided
        if self.tf_subset is None:
            chosen = all_tf_day_d
        else:
            # Filter subset to day-label format
            kept_d = [t for t in self.tf_subset if is_day_label(t)]
            if not kept_d:
                logger.warning("tf_subset contained no valid day-label TFs, using all")
                chosen = all_tf_day_d
            else:
                # Keep only those in dim_timeframe
                chosen = [t for t in kept_d if t in set(all_tf_day_d)]
                if not chosen:
                    logger.warning("No tf_subset TFs found in dim_timeframe, using all")
                    chosen = all_tf_day_d

        # Build TFSpec list
        tf_specs = []
        for tf in chosen:
            tf_days = int(get_tf_days(tf, db_url=db_url))
            if tf_days <= 0:
                logger.warning(f"Invalid tf_days={tf_days} for tf='{tf}', skipping")
                continue
            tf_specs.append(TFSpec(tf=tf, tf_days=tf_days))

        if not tf_specs:
            raise RuntimeError("No valid TF specs after filtering")

        logger.info(f"Loaded {len(tf_specs)} multi-TF specs (tf_day family)")
        self._tf_specs_cache = tf_specs
        return tf_specs

    def compute_emas_for_tf(
        self,
        df_source: pd.DataFrame,
        tf_spec: TFSpec,
        periods: list[int],
    ) -> pd.DataFrame:
        """
        Compute multi-TF EMAs for single TF.

        Vectorized: uses compute_bar_ema_numpy for bar EMA, numpy for preview.

        Logic:
        1. Load/generate canonical bar closes (persisted or synthetic)
        2. For each ID: compute bar EMAs + preview EMAs on daily grid
        3. Add derivatives (d1_roll/d2_roll for all, d1/d2 for canonical only)
        """
        if df_source.empty:
            return pd.DataFrame()

        # Use cached daily data
        daily = (
            self._daily_data_cache if self._daily_data_cache is not None else df_source
        )

        # Load persisted bars for this TF (all IDs)
        ids = daily["id"].unique().tolist()
        bars_all = self._load_bar_closes(
            ids=ids,
            tf=tf_spec.tf,
            end=None,  # Load all available
        )

        frames = []

        for asset_id in ids:
            df_id = daily[daily["id"] == asset_id].copy()
            if df_id.empty:
                continue

            # Get bars for this ID (persisted or synthetic)
            if not bars_all.empty:
                bars_id = bars_all[bars_all["id"] == asset_id].copy()
            else:
                bars_id = pd.DataFrame()

            if bars_id.empty:
                # Fallback to synthetic bars
                bars_id = self._synthetic_tf_day_bars_from_daily(
                    df_id_daily=df_id,
                    tf=tf_spec.tf,
                    tf_days=tf_spec.tf_days,
                )

            if bars_id.empty:
                continue

            # Prepare daily data
            df_id = df_id.sort_values("ts").reset_index(drop=True)
            # Canonical closes
            closes = bars_id[["time_close", "close_bar", "bar_seq"]].copy()
            closes = closes.rename(columns={"time_close": "ts"})
            closes["ts"] = pd.to_datetime(closes["ts"], utc=True)

            # Daily grid with canonical markers
            grid = df_id[["ts", "close"]].merge(
                closes[["ts", "close_bar", "bar_seq"]],
                on="ts",
                how="left",
            )

            # Bar-close series in bar order
            df_closes = (
                closes[["ts", "close_bar", "bar_seq"]]
                .sort_values("bar_seq")
                .reset_index(drop=True)
            )

            # Filter periods by observation count
            valid_periods = filter_ema_periods_by_obs_count(periods, len(df_closes))

            # Pre-extract numpy arrays for the grid
            grid_close_arr = grid["close"].astype(float).to_numpy()
            n_grid = len(grid)

            for p in valid_periods:
                # Compute bar-space EMA on canonical closes
                bar_close_arr = df_closes["close_bar"].astype(float).to_numpy()
                bar_ema_arr = compute_bar_ema_numpy(
                    bar_close_arr, period=p, min_periods=p
                )

                valid_mask = ~np.isnan(bar_ema_arr)
                if not valid_mask.any():
                    continue

                bar_ts = df_closes["ts"].values
                valid_idx = np.where(valid_mask)[0]
                bar_ts_valid = bar_ts[valid_idx]
                bar_ema_valid = bar_ema_arr[valid_idx]

                # Build canonical mask and EMA values on daily grid
                bar_ts_set = set(pd.DatetimeIndex(bar_ts_valid).tz_localize("UTC"))
                canon_ts_to_ema = {}
                for i, ts_key in enumerate(
                    pd.DatetimeIndex(bar_ts_valid).tz_localize("UTC")
                ):
                    canon_ts_to_ema[ts_key] = bar_ema_valid[i]

                canonical_mask = np.zeros(n_grid, dtype=bool)
                canonical_ema_values = np.full(n_grid, np.nan, dtype=np.float64)
                grid_ts_list = grid["ts"].tolist()
                for i in range(n_grid):
                    ts_val = grid_ts_list[i]
                    if ts_val in canon_ts_to_ema:
                        canonical_mask[i] = True
                        canonical_ema_values[i] = canon_ts_to_ema[ts_val]

                # Compute dual EMA: ema_bar (bar alpha + reanchoring) + ema (daily alpha)
                alpha_bar = 2.0 / (p + 1.0)
                alpha_daily = 2.0 / (tf_spec.tf_days * p + 1.0)

                ema_bar_out, ema_out = compute_dual_ema_numpy(
                    grid_close_arr,
                    canonical_mask,
                    canonical_ema_values,
                    alpha_daily,
                    alpha_bar,
                )

                # Drop rows before first valid ema_bar
                valid_ema = ~np.isnan(ema_bar_out)
                if not valid_ema.any():
                    continue

                first_valid = int(np.argmax(valid_ema))
                sl = slice(first_valid, None)

                grid_ts_slice = grid["ts"].iloc[first_valid:].tolist()
                roll_arr = ~np.array([t in bar_ts_set for t in grid_ts_slice])

                # is_partial_end: True for rows after the last canonical close
                last_canon_ts = max(bar_ts_set) if bar_ts_set else None
                is_partial_arr = np.array(
                    [
                        t > last_canon_ts if last_canon_ts else True
                        for t in grid_ts_slice
                    ]
                )

                tmp = pd.DataFrame(
                    {
                        "id": asset_id,
                        "tf": tf_spec.tf,
                        "ts": grid_ts_slice,
                        "period": p,
                        "tf_days": tf_spec.tf_days,
                        "roll": roll_arr,
                        "ema": ema_out[sl],
                        "ema_bar": ema_bar_out[sl],
                        "is_partial_end": is_partial_arr,
                    }
                )

                frames.append(tmp)

        if not frames:
            return pd.DataFrame()

        result = pd.concat(frames, ignore_index=True)
        result["ts"] = pd.to_datetime(result["ts"], utc=True)
        result = result.sort_values(["id", "tf", "period", "ts"])

        return result

    def get_output_schema(self) -> dict[str, str]:
        """Define output table schema for multi-TF EMAs (dual EMA)."""
        return {
            "id": "INTEGER NOT NULL",
            "tf": "TEXT NOT NULL",
            "ts": "TIMESTAMPTZ NOT NULL",
            "period": "INTEGER NOT NULL",
            "tf_days": "INTEGER",
            "roll": "BOOLEAN",
            "ema": "DOUBLE PRECISION",
            "ema_bar": "DOUBLE PRECISION",
            "is_partial_end": "BOOLEAN",
            "ingested_at": "TIMESTAMPTZ DEFAULT now()",
            "PRIMARY KEY": "(id, tf, ts, period)",
        }

    # =========================================================================
    # Helper Methods (Module-specific)
    # =========================================================================

    def _normalize_daily(self, daily: pd.DataFrame) -> pd.DataFrame:
        """Normalize daily OHLCV to standard format (id, ts, close)."""
        df = daily.copy()

        # Handle multi-index
        if isinstance(df.index, pd.MultiIndex):
            df = df.reset_index()

        # Find timestamp column
        cols_lower = {c.lower(): c for c in df.columns}
        if "ts" not in df.columns:
            if "timeclose" in cols_lower:
                df = df.rename(columns={cols_lower["timeclose"]: "ts"})
            elif "timestamp" in cols_lower:
                df = df.rename(columns={cols_lower["timestamp"]: "ts"})
            elif "date" in cols_lower:
                df = df.rename(columns={cols_lower["date"]: "ts"})
            else:
                raise ValueError("Could not find timestamp column in daily data")

        # Check required columns
        required = {"id", "ts", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Daily OHLCV missing required columns: {missing}")

        # Fill missing OHLCV columns
        if "open" not in df.columns:
            df["open"] = df["close"]
        if "high" not in df.columns:
            df["high"] = df["close"]
        if "low" not in df.columns:
            df["low"] = df["close"]
        if "volume" not in df.columns:
            df["volume"] = 0.0

        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values(["id", "ts"]).reset_index(drop=True)
        return df

    def _load_bar_closes(
        self,
        ids: list[int],
        tf: str,
        end: Optional[str],
    ) -> pd.DataFrame:
        """Load canonical TF closes from persisted bars table."""
        end_ts = pd.to_datetime(end, utc=True) if end is not None else None

        sql = f"""
        SELECT
          id,
          tf,
          bar_seq,
          "timestamp" AS time_close,
          close AS close_bar
        FROM {self.bars_schema}.{self.bars_table}
        WHERE tf = :tf
          AND id = ANY(:ids)
          AND is_partial_end = FALSE
          {"" if end_ts is None else 'AND "timestamp" <= :end_ts'}
        ORDER BY id, bar_seq
        """

        params = {"tf": tf, "ids": ids}
        if end_ts is not None:
            params["end_ts"] = end_ts

        with self.engine.begin() as conn:
            df = pd.read_sql_query(text(sql), conn, params=params)

        if df.empty:
            return df

        df["time_close"] = pd.to_datetime(df["time_close"], utc=True)
        return df.sort_values(["id", "bar_seq"]).reset_index(drop=True)

    def _synthetic_tf_day_bars_from_daily(
        self,
        df_id_daily: pd.DataFrame,
        tf: str,
        tf_days: int,
    ) -> pd.DataFrame:
        """Generate synthetic TF bars from daily closes (fallback)."""
        if df_id_daily.empty:
            return pd.DataFrame(
                columns=["id", "tf", "bar_seq", "time_close", "close_bar"]
            )

        d = df_id_daily.sort_values("ts").reset_index(drop=True)
        n = len(d)
        if tf_days <= 0 or n < tf_days:
            return pd.DataFrame(
                columns=["id", "tf", "bar_seq", "time_close", "close_bar"]
            )

        # Canonical indices: (tf_days-1), (2*tf_days-1), ...
        idx = np.arange(tf_days - 1, n, tf_days, dtype=int)
        if idx.size == 0:
            return pd.DataFrame(
                columns=["id", "tf", "bar_seq", "time_close", "close_bar"]
            )

        bars = pd.DataFrame(
            {
                "id": int(d.loc[0, "id"]),
                "tf": tf,
                "bar_seq": np.arange(1, idx.size + 1, dtype=int),
                "time_close": d.loc[idx, "ts"].to_numpy(),
                "close_bar": d.loc[idx, "close"].astype(float).to_numpy(),
            }
        )

        return bars.reset_index(drop=True)


# =============================================================================
# Public API (Backward Compatibility)
# =============================================================================


def write_multi_timeframe_ema_to_db(
    ids: Sequence[int],
    start: str = "2010-01-01",
    end: Optional[str] = None,
    ema_periods: Sequence[int] = (
        6,
        9,
        10,
        12,
        14,
        17,
        20,
        21,
        26,
        30,
        50,
        52,
        77,
        100,
        200,
        252,
        365,
    ),
    tf_subset: Optional[Sequence[str]] = None,
    *,
    db_url: Optional[str] = None,
    schema: str = "public",
    out_table: str = "cmc_ema_multi_tf",
    update_existing: bool = True,
    bars_schema: str = "public",
    bars_table_tf_day: str = "cmc_price_bars_multi_tf",
) -> int:
    """
    Compute multi-TF EMAs and write to database (backward compatibility wrapper).

    This uses the refactored BaseEMAFeature architecture with full implementation.
    """
    engine = _get_engine(db_url)

    config = EMAFeatureConfig(
        periods=list(ema_periods),
        output_schema=schema,
        output_table=out_table,
    )

    feature = MultiTFEMAFeature(
        engine=engine,
        config=config,
        bars_schema=bars_schema,
        bars_table=bars_table_tf_day,
        tf_subset=tf_subset,
    )

    # Compute for IDs
    df = feature.load_source_data(list(ids), start=start, end=end)
    if df.empty:
        return 0

    tf_specs = feature.get_tf_specs()
    all_results = []

    for tf_spec in tf_specs:
        logger.info(f"Computing EMAs for tf={tf_spec.tf} (tf_days={tf_spec.tf_days})")
        df_ema = feature.compute_emas_for_tf(df, tf_spec, config.periods)
        if not df_ema.empty:
            all_results.append(df_ema)

    if not all_results:
        return 0

    df_final = pd.concat(all_results, ignore_index=True)

    # Apply date filters
    if start is not None:
        start_ts = pd.to_datetime(start, utc=True)
        df_final = df_final[df_final["ts"] >= start_ts]
    if end is not None:
        end_ts = pd.to_datetime(end, utc=True)
        df_final = df_final[df_final["ts"] <= end_ts]

    # Convert NaN -> None for Postgres NULL
    df_final = df_final.replace({np.nan: None})

    # Write to database with upsert
    tmp_table = f"{out_table}_tmp"

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{tmp_table};"))

        conn.execute(
            text(
                f"""
                CREATE TEMP TABLE {tmp_table} AS
                SELECT
                    id, tf, ts, period, tf_days, roll, ema, ema_bar, is_partial_end
                FROM {schema}.{out_table}
                LIMIT 0;
                """
            )
        )

        df_final.to_sql(
            tmp_table, conn, if_exists="append", index=False, method="multi"
        )

        conflict_sql = (
            """
            DO UPDATE SET
                tf_days         = EXCLUDED.tf_days,
                roll            = EXCLUDED.roll,
                ema             = EXCLUDED.ema,
                ema_bar         = EXCLUDED.ema_bar,
                is_partial_end  = EXCLUDED.is_partial_end
            """
            if update_existing
            else "DO NOTHING"
        )

        sql = f"""
        INSERT INTO {schema}.{out_table} AS t
            (id, tf, ts, period, tf_days, roll, ema, ema_bar, is_partial_end)
        SELECT
            id, tf, ts, period, tf_days, roll, ema, ema_bar, is_partial_end
        FROM {tmp_table}
        ON CONFLICT (id, tf, ts, period)
        {conflict_sql};
        """

        res = conn.execute(text(sql))
        return int(res.rowcount or 0)
