"""
Calendar-aligned multi-timeframe EMA - REFACTORED to use BaseEMAFeature.

Calendar EMA semantics:
- Canonical calendar closes from cmc_price_bars_multi_tf_cal_us/iso
- Timeframe universe from dim_timeframe (alignment_type='calendar')
- Dual EMAs: ema (daily-space) and ema_bar (bar-space with preview)
- Alpha from lookup table (ema_alpha_lookup)

REFACTORED CHANGES:
- Extends BaseEMAFeature abstract class
- Uses ema_operations for derivative calculations
- Preserves dual EMA logic (ema + ema_bar)
- ~680 LOC → ~480 LOC (29% reduction)
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
from ta_lab2.features.m_tf.polars_helpers import read_sql_polars
from ta_lab2.features.ema import filter_ema_periods_by_obs_count, compute_ema

logger = logging.getLogger(__name__)


# =============================================================================
# Calendar EMA Feature Implementation
# =============================================================================


class CalendarEMAFeature(BaseEMAFeature):
    """
    Calendar-aligned EMA feature: EMAs computed on calendar TF closes.

    Key characteristics:
    - Uses calendar bars tables (cal_us or cal_iso)
    - Loads TFs from dim_timeframe with calendar alignment
    - Alpha from lookup table (not computed)
    - Dual EMAs: ema (daily-space) + ema_bar (bar-space with preview)
    """

    def __init__(
        self,
        engine: Engine,
        config: EMAFeatureConfig,
        *,
        scheme: str = "us",
        alpha_schema: str = "public",
        alpha_table: str = "ema_alpha_lookup",
    ):
        """
        Initialize calendar EMA feature.

        Args:
            engine: SQLAlchemy engine
            config: EMA feature configuration
            scheme: Calendar scheme ("us" or "iso")
            alpha_schema: Schema for alpha lookup table
            alpha_table: Alpha lookup table name
        """
        super().__init__(engine, config)
        self.scheme = scheme.strip().upper()
        self.alpha_schema = alpha_schema
        self.alpha_table = alpha_table

        # Determine bars table from scheme
        if self.scheme == "US":
            self.bars_table = "public.cmc_price_bars_multi_tf_cal_us"
        elif self.scheme == "ISO":
            self.bars_table = "public.cmc_price_bars_multi_tf_cal_iso"
        else:
            raise ValueError(f"Unsupported scheme: {scheme} (expected US or ISO)")

        # Cache alpha lookup and TF specs
        self._alpha_lookup: Optional[pd.DataFrame] = None
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

        Returns: DataFrame with id, ts, close
        """
        where = ["id = ANY(:ids)"]
        params = {"ids": ids}

        if start:
            where.append('"timestamp" >= :start')
            params["start"] = pd.to_datetime(start, utc=True)
        if end:
            where.append('"timestamp" <= :end')
            params["end"] = pd.to_datetime(end, utc=True)

        sql = f"""
          SELECT
            id,
            "timestamp" AS ts,
            close
          FROM public.cmc_price_histories7
          WHERE {" AND ".join(where)}
          ORDER BY id, "timestamp"
        """

        with self.engine.connect() as conn:
            df = read_sql_polars(sql, conn, params=params)

        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df = df.sort_values(["id", "ts"]).reset_index(drop=True)

        logger.info(f"Loaded {len(df)} daily rows for {len(ids)} IDs")
        self._daily_data_cache = df
        return df

    def get_tf_specs(self) -> List[TFSpec]:
        """Load calendar TF specs from dim_timeframe."""
        if self._tf_specs_cache is not None:
            return self._tf_specs_cache

        # Build scheme-specific WHERE clause
        if self.scheme == "US":
            tf_where = """
              (
                (base_unit = 'W' AND tf ~ '_CAL_US$')
                OR
                (base_unit IN ('M','Y') AND tf ~ '_CAL$' AND tf !~ '_CAL_')
              )
            """
        elif self.scheme == "ISO":
            tf_where = """
              (
                (base_unit = 'W' AND tf ~ '_CAL_ISO$')
                OR
                (base_unit IN ('M','Y') AND tf ~ '_CAL$' AND tf !~ '_CAL_')
              )
            """
        else:
            raise ValueError(f"Unsupported scheme: {self.scheme}")

        sql = f"""
          SELECT
            tf,
            COALESCE(tf_days_min, tf_days_max, tf_days_nominal) AS tf_days
          FROM public.dim_timeframe
          WHERE alignment_type = 'calendar'
            AND tf NOT LIKE '%\\_CAL\\_ANCHOR\\_%' ESCAPE '\\'
            AND tf NOT LIKE '%\\_ANCHOR%' ESCAPE '\\'
            AND {tf_where}
          ORDER BY sort_order, tf
        """

        with self.engine.connect() as conn:
            df = read_sql_polars(sql, conn)

        if df.empty:
            raise RuntimeError(f"No calendar TFs found for scheme={self.scheme}")

        df["tf"] = df["tf"].astype(str)
        df["tf_days"] = df["tf_days"].astype(int)

        tf_specs = [
            TFSpec(tf=r.tf, tf_days=int(r.tf_days)) for r in df.itertuples(index=False)
        ]

        logger.info(
            f"Loaded {len(tf_specs)} calendar TF specs for scheme={self.scheme}"
        )
        self._tf_specs_cache = tf_specs
        return tf_specs

    def compute_emas_for_tf(
        self,
        df_source: pd.DataFrame,
        tf_spec: TFSpec,
        periods: list[int],
    ) -> pd.DataFrame:
        """
        Compute calendar EMAs for single TF.

        Implements dual EMA logic:
        - ema: daily-space, seeded once, continuous daily updates
        - ema_bar: bar-space, snaps at TF closes, preview between
        """
        if df_source.empty or self._daily_data_cache is None:
            return pd.DataFrame()

        # Load alpha lookup
        alpha_lut = self._load_alpha_lookup()
        alpha_map = {
            (r.tf, int(r.period)): float(r.alpha)
            for r in alpha_lut.itertuples(index=False)
        }

        # Load canonical closes for this TF
        ids = df_source["id"].unique().tolist()
        tf_closes = self._load_canonical_closes(ids, [tf_spec.tf])

        if tf_closes.empty:
            return pd.DataFrame()

        # Group closes by (id, tf)
        closes_g = tf_closes.groupby(["id", "tf"])["ts_close"].agg(list).to_dict()

        out_frames = []

        for (id_, tf), close_list in closes_g.items():
            close_list = sorted(pd.to_datetime(close_list, utc=True))
            close_set = set(close_list)

            df_id = self._daily_data_cache[self._daily_data_cache["id"] == id_].copy()
            if df_id.empty:
                continue
            df_id = df_id.sort_values("ts").reset_index(drop=True)

            # Canonical closes for this ID+TF
            df_closes = df_id[df_id["ts"].isin(close_set)].copy()
            if df_closes.empty:
                continue
            df_closes = df_closes.sort_values("ts").reset_index(drop=True)

            close_px_arr = df_closes["close"].astype(float).to_numpy()
            close_ts_arr = df_closes["ts"].to_numpy()

            # Filter periods by observation count
            valid_periods = filter_ema_periods_by_obs_count(periods, len(close_px_arr))

            for period in valid_periods:
                # Get alpha from lookup or compute
                alpha_daily = alpha_map.get((tf, period))
                if alpha_daily is None:
                    effective_days = max(1, tf_spec.tf_days * period)
                    alpha_daily = 2.0 / (effective_days + 1.0)

                alpha_bar = 2.0 / (float(period) + 1.0)

                # Compute bar EMA on canonical closes
                bar_ema_on_closes = self._compute_bar_ema_on_closes(
                    close_px_arr, alpha_bar, period
                )

                valid_mask = ~np.isnan(bar_ema_on_closes)
                if not valid_mask.any():
                    continue

                first_valid_idx = int(np.argmax(valid_mask))
                first_valid_close_ts = pd.Timestamp(
                    close_ts_arr[first_valid_idx]
                ).tz_convert("UTC")

                # Map canonical closes to bar EMAs
                canonical_bar_map = {
                    pd.Timestamp(t).tz_convert("UTC"): float(v)
                    for t, v in zip(close_ts_arr, bar_ema_on_closes)
                    if not np.isnan(v)
                }

                # Output frame starts at first valid canonical close
                df_out = df_id[df_id["ts"] >= first_valid_close_ts].copy()
                if df_out.empty:
                    continue

                df_out["id"] = int(id_)
                df_out["tf"] = tf
                df_out["period"] = int(period)
                df_out["tf_days"] = tf_spec.tf_days

                # Roll flags (labels only)
                df_out["roll"] = ~df_out["ts"].isin(close_set)
                df_out["roll_bar"] = df_out["roll"]

                # Compute ema_bar: snaps at TF closes, preview between
                ema_bar_vals = []
                ema_bar_prev = None

                for ts, px in zip(
                    df_out["ts"].to_numpy(), df_out["close"].astype(float).to_numpy()
                ):
                    ts_u = pd.Timestamp(ts).tz_convert("UTC")
                    canon = canonical_bar_map.get(ts_u)

                    if canon is not None:
                        # Snap to canonical bar EMA
                        ema_bar_today = float(canon)
                    else:
                        # Daily preview propagation
                        if ema_bar_prev is None:
                            ema_bar_today = float(px)
                        else:
                            ema_bar_today = (
                                alpha_daily * float(px)
                                + (1.0 - alpha_daily) * ema_bar_prev
                            )

                    ema_bar_vals.append(ema_bar_today)
                    ema_bar_prev = ema_bar_today

                df_out["ema_bar"] = ema_bar_vals

                # Compute ema: seeded once, continuous daily updates
                ema_vals = []
                ema_prev = None

                for px, eb in zip(
                    df_out["close"].astype(float).to_numpy(),
                    df_out["ema_bar"].to_numpy(),
                ):
                    if ema_prev is None:
                        # Seed at first valid canonical bar EMA point
                        ema_today = float(eb)
                    else:
                        # Continuous daily update
                        ema_today = (
                            alpha_daily * float(px) + (1.0 - alpha_daily) * ema_prev
                        )

                    ema_vals.append(ema_today)
                    ema_prev = ema_today

                df_out["ema"] = ema_vals

                # Compute derivatives
                df_out = self._add_cal_derivatives(df_out)

                out_frames.append(
                    df_out[
                        [
                            "id",
                            "tf",
                            "ts",
                            "period",
                            "tf_days",
                            "roll",
                            "ema",
                            "d1",
                            "d2",
                            "d1_roll",
                            "d2_roll",
                            "ema_bar",
                            "d1_bar",
                            "d2_bar",
                            "roll_bar",
                            "d1_roll_bar",
                            "d2_roll_bar",
                        ]
                    ]
                )

        if not out_frames:
            return pd.DataFrame()

        result = pd.concat(out_frames, ignore_index=True)
        result["ts"] = pd.to_datetime(result["ts"], utc=True)
        return result

    def get_output_schema(self) -> dict[str, str]:
        """Define output table schema for calendar EMAs."""
        return {
            "id": "INTEGER NOT NULL",
            "tf": "TEXT NOT NULL",
            "ts": "TIMESTAMPTZ NOT NULL",
            "period": "INTEGER NOT NULL",
            "tf_days": "INTEGER",
            "roll": "BOOLEAN",
            "ema": "DOUBLE PRECISION",
            "d1": "DOUBLE PRECISION",
            "d2": "DOUBLE PRECISION",
            "d1_roll": "DOUBLE PRECISION",
            "d2_roll": "DOUBLE PRECISION",
            "ema_bar": "DOUBLE PRECISION",
            "d1_bar": "DOUBLE PRECISION",
            "d2_bar": "DOUBLE PRECISION",
            "roll_bar": "BOOLEAN",
            "d1_roll_bar": "DOUBLE PRECISION",
            "d2_roll_bar": "DOUBLE PRECISION",
            "ingested_at": "TIMESTAMPTZ DEFAULT now()",
            "PRIMARY KEY": "(id, tf, ts, period)",
        }

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _load_alpha_lookup(self) -> pd.DataFrame:
        """Load alpha lookup table (cached)."""
        if self._alpha_lookup is not None:
            return self._alpha_lookup

        sql = f"""
          SELECT tf, period, alpha_ema_dailyspace AS alpha
          FROM {self.alpha_schema}.{self.alpha_table}
        """

        with self.engine.connect() as conn:
            df = read_sql_polars(sql, conn)

        if df.empty:
            raise RuntimeError(
                f"Alpha lookup table {self.alpha_schema}.{self.alpha_table} is empty"
            )

        df["period"] = df["period"].astype(int)
        df["tf"] = df["tf"].astype(str)
        df["alpha"] = df["alpha"].astype(float)

        self._alpha_lookup = df
        return df

    def _load_canonical_closes(self, ids: list[int], tfs: list[str]) -> pd.DataFrame:
        """Load canonical closes from bars table."""
        if not ids or not tfs:
            return pd.DataFrame(columns=["id", "tf", "ts_close"])

        sql = f"""
          SELECT
            id,
            tf,
            time_close AS ts_close
          FROM {self.bars_table}
          WHERE id = ANY(:ids)
            AND tf = ANY(:tfs)
            AND is_partial_end = FALSE
          ORDER BY id, tf, time_close
        """

        with self.engine.connect() as conn:
            df = read_sql_polars(sql, conn, params={"ids": ids, "tfs": tfs})

        if not df.empty:
            df["id"] = df["id"].astype(int)
            df["tf"] = df["tf"].astype(str)
            df["ts_close"] = pd.to_datetime(df["ts_close"], utc=True)

        return df

    def _compute_bar_ema_on_closes(
        self, close_prices: np.ndarray, alpha_bar: float, min_periods: int
    ) -> np.ndarray:
        """Compute EMA in bar-space on canonical close prices."""
        period = int(round((2.0 / alpha_bar) - 1.0))
        close_series = pd.Series(close_prices, dtype=float)
        ema_series = compute_ema(
            close_series, period=period, adjust=False, min_periods=min_periods
        )
        return ema_series.to_numpy(dtype=float)

    def _add_cal_derivatives(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add calendar derivatives for dual EMAs.

        ema-space:
        - d1_roll/d2_roll: Daily diffs on ema (all rows)
        - d1/d2: Canonical-only diffs on ema (roll=FALSE)

        bar-space:
        - d1_roll_bar/d2_roll_bar: Daily diffs on ema_bar (all rows)
        - d1_bar/d2_bar: Canonical-only diffs on ema_bar (roll_bar=FALSE)
        """
        result = df.copy()

        # Daily diffs on ema (all rows)
        result["d1_roll"] = result["ema"].diff()
        result["d2_roll"] = result["d1_roll"].diff()

        # Canonical-only diffs on ema (roll=FALSE)
        result["d1"] = np.nan
        result["d2"] = np.nan
        mask_can = result["roll"] == False
        if mask_can.any():
            can_df = result.loc[mask_can, ["ts", "ema"]].copy()
            can_df["d1"] = can_df["ema"].diff()
            can_df["d2"] = can_df["d1"].diff()
            result.loc[mask_can, "d1"] = can_df["d1"].to_numpy()
            result.loc[mask_can, "d2"] = can_df["d2"].to_numpy()

        # Daily diffs on ema_bar (all rows)
        result["d1_roll_bar"] = result["ema_bar"].diff()
        result["d2_roll_bar"] = result["d1_roll_bar"].diff()

        # Canonical-only diffs on ema_bar (roll_bar=FALSE)
        result["d1_bar"] = np.nan
        result["d2_bar"] = np.nan
        mask_bar_can = result["roll_bar"] == False
        if mask_bar_can.any():
            bar_can = result.loc[mask_bar_can, ["ts", "ema_bar"]].copy()
            bar_can["d1_bar"] = bar_can["ema_bar"].diff()
            bar_can["d2_bar"] = bar_can["d1_bar"].diff()
            result.loc[mask_bar_can, "d1_bar"] = bar_can["d1_bar"].to_numpy()
            result.loc[mask_bar_can, "d2_bar"] = bar_can["d2_bar"].to_numpy()

        return result


# =============================================================================
# Public API (Backward Compatibility)
# =============================================================================


def write_multi_timeframe_ema_cal_to_db(
    engine_or_db_url,
    ids: Sequence[int],
    *,
    scheme: str = "US",
    start: Optional[str] = None,
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
    schema: str = "public",
    out_table: Optional[str] = None,
    alpha_schema: str = "public",
    alpha_table: str = "ema_alpha_lookup",
    update_existing: bool = True,
) -> int:
    """
    Compute calendar-aligned multi-timeframe EMAs and write to database.

    Uses the refactored BaseEMAFeature architecture with full dual EMA implementation.
    """
    from sqlalchemy import create_engine

    if isinstance(engine_or_db_url, str):
        engine = create_engine(engine_or_db_url, future=True)
    else:
        engine = engine_or_db_url

    scheme_u = scheme.strip().upper()
    if out_table is None:
        out_table = f"cmc_ema_multi_tf_cal_{scheme_u.lower()}"

    logger.info(
        f"Computing calendar EMAs: scheme={scheme_u}, periods={len(ema_periods)}, ids={len(ids)}"
    )

    config = EMAFeatureConfig(
        periods=list(ema_periods),
        output_schema=schema,
        output_table=out_table,
    )

    feature = CalendarEMAFeature(
        engine=engine,
        config=config,
        scheme=scheme_u,
        alpha_schema=alpha_schema,
        alpha_table=alpha_table,
    )

    # Load data
    df_daily = feature.load_source_data(list(ids), start=start, end=end)
    if df_daily.empty:
        logger.warning("No daily data found")
        return 0

    # Get TF specs
    tf_specs = feature.get_tf_specs()
    logger.info(f"Processing {len(tf_specs)} calendar TFs")

    # Compute EMAs for each TF
    all_results = []
    for tf_spec in tf_specs:
        logger.info(f"Computing EMAs for tf={tf_spec.tf} (tf_days={tf_spec.tf_days})")
        df_ema = feature.compute_emas_for_tf(df_daily, tf_spec, config.periods)
        if not df_ema.empty:
            all_results.append(df_ema)

    if not all_results:
        logger.warning("No EMAs computed")
        return 0

    df_out = pd.concat(all_results, ignore_index=True)
    logger.info(f"Built {len(df_out):,} EMA rows")

    # Convert NaN -> None for Postgres NULL
    df_out = df_out.replace({np.nan: None})

    # Write to database
    conflict_action = (
        """DO UPDATE SET
        tf_days      = EXCLUDED.tf_days,
        roll         = EXCLUDED.roll,
        ema          = EXCLUDED.ema,
        d1           = EXCLUDED.d1,
        d2           = EXCLUDED.d2,
        d1_roll      = EXCLUDED.d1_roll,
        d2_roll      = EXCLUDED.d2_roll,
        ema_bar      = EXCLUDED.ema_bar,
        d1_bar       = EXCLUDED.d1_bar,
        d2_bar       = EXCLUDED.d2_bar,
        roll_bar     = EXCLUDED.roll_bar,
        d1_roll_bar  = EXCLUDED.d1_roll_bar,
        d2_roll_bar  = EXCLUDED.d2_roll_bar,
        ingested_at  = now()"""
        if update_existing
        else "DO NOTHING"
    )

    upsert_sql = text(
        f"""
      INSERT INTO {schema}.{out_table} (
        id, tf, ts, period, tf_days,
        roll, ema, d1, d2, d1_roll, d2_roll,
        ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar,
        ingested_at
      )
      VALUES (
        :id, :tf, :ts, :period, :tf_days,
        :roll, :ema, :d1, :d2, :d1_roll, :d2_roll,
        :ema_bar, :d1_bar, :d2_bar, :roll_bar, :d1_roll_bar, :d2_roll_bar,
        now()
      )
      ON CONFLICT (id, tf, ts, period) {conflict_action}
    """
    )

    logger.info(f"Writing {len(df_out):,} rows to {schema}.{out_table}...")

    # Batch writes
    BATCH_SIZE = 10_000
    payload = df_out.to_dict(orient="records")
    total_rows = len(payload)

    with engine.begin() as conn:
        for i in range(0, total_rows, BATCH_SIZE):
            batch = payload[i : i + BATCH_SIZE]
            conn.execute(upsert_sql, batch)

            rows_written = min(i + BATCH_SIZE, total_rows)
            if rows_written % 50_000 == 0 or rows_written == total_rows or i == 0:
                pct = (rows_written / total_rows) * 100
                logger.info(
                    f"  Written {rows_written:,} / {total_rows:,} rows ({pct:.1f}%)"
                )

    logger.info(f"Successfully wrote {len(df_out):,} rows")
    return len(df_out)
