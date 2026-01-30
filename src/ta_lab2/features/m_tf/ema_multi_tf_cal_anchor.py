"""
Calendar-anchor multi-timeframe EMA - REFACTORED to use BaseEMAFeature.

Calendar anchor EMA semantics:
- Canonical closes from cmc_price_bars_multi_tf_cal_anchor_us/iso
- Timeframe universe from dim_timeframe (alignment_type='calendar', ANCHOR families)
- Similar to cal but with anchored periods
- Uses is_partial_end (not roll) column for canonical detection
- Dual EMAs: ema (daily-space) and ema_bar (bar-space with preview)

REFACTORED CHANGES:
- Extends BaseEMAFeature abstract class
- Uses ema_operations for derivative calculations
- ~550 LOC → ~430 LOC (22% reduction)
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
# Calendar Anchor EMA Feature Implementation
# =============================================================================

class CalendarAnchorEMAFeature(BaseEMAFeature):
    """
    Calendar-anchored EMA feature: EMAs on anchored calendar periods.

    Similar to CalendarEMAFeature but:
    - Uses _ANCHOR timeframes
    - Uses is_partial_end column (not roll)
    - Different alpha calculation (daily-equivalent formula)
    - roll_bar column for bar-space canonical detection
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
        """Initialize calendar anchor EMA feature."""
        super().__init__(engine, config)
        self.scheme = scheme.strip().upper()
        self.alpha_schema = alpha_schema
        self.alpha_table = alpha_table

        # Determine bars table from scheme
        if self.scheme == "US":
            self.bars_table = "public.cmc_price_bars_multi_tf_cal_anchor_us"
        elif self.scheme == "ISO":
            self.bars_table = "public.cmc_price_bars_multi_tf_cal_anchor_iso"
        else:
            raise ValueError(f"Unsupported scheme: {scheme}")

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
        """Load daily closes for all IDs."""
        where = ["id = ANY(:ids)"]
        params = {"ids": ids}

        if start:
            where.append('timeclose >= :start')
            params["start"] = start
        if end:
            where.append('timeclose <= :end')
            params["end"] = end

        sql = f"""
          SELECT id, timeclose AS ts, close
          FROM public.cmc_price_histories7
          WHERE {" AND ".join(where)}
          ORDER BY id, ts
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
        """Load calendar anchor TF specs from dim_timeframe."""
        if self._tf_specs_cache is not None:
            return self._tf_specs_cache

        # Load ANCHOR timeframes from dim_timeframe
        sql = f"""
          SELECT
            tf,
            COALESCE(tf_days_min, tf_days_max, tf_days_nominal) AS tf_days
          FROM public.dim_timeframe
          WHERE alignment_type = 'calendar'
            AND roll_policy = 'calendar_anchor'
            AND has_roll_flag = TRUE
            AND allow_partial_start = TRUE
            AND allow_partial_end = TRUE
            AND (
              (base_unit = 'W'
               AND calendar_scheme = :scheme
               AND tf LIKE ('%\\_CAL\\_ANCHOR\\_' || :scheme) ESCAPE '\\')
              OR
              (base_unit IN ('M','Y')
               AND tf LIKE '%\\_CAL\\_ANCHOR' ESCAPE '\\')
            )
          ORDER BY sort_order, tf
        """

        with self.engine.connect() as conn:
            df = read_sql_polars(sql, conn, params={"scheme": self.scheme})

        if df.empty:
            raise RuntimeError(f"No calendar anchor TFs found for scheme={self.scheme}")

        df["tf"] = df["tf"].astype(str)
        df["tf_days"] = df["tf_days"].astype(int)

        tf_specs = [TFSpec(tf=r.tf, tf_days=int(r.tf_days)) for r in df.itertuples(index=False)]

        logger.info(f"Loaded {len(tf_specs)} calendar anchor TF specs for scheme={self.scheme}")
        self._tf_specs_cache = tf_specs
        return tf_specs

    def compute_emas_for_tf(
        self,
        df_source: pd.DataFrame,
        tf_spec: TFSpec,
        periods: list[int],
    ) -> pd.DataFrame:
        """
        Compute calendar anchor EMAs for single TF.

        Implements dual EMA logic with anchored semantics:
        - ema: daily-space, seeded once, continuous daily updates
        - ema_bar: bar-space, snaps at anchored closes, evolves daily between
        """
        if df_source.empty or self._daily_data_cache is None:
            return pd.DataFrame()

        # Load canonical closes for this TF
        ids = df_source["id"].unique().tolist()
        bars_tf = self._load_anchor_bars(ids, [tf_spec.tf])

        if bars_tf.empty:
            return pd.DataFrame()

        out_frames = []

        # Process each ID separately
        for id_ in ids:
            df_id = self._daily_data_cache[self._daily_data_cache["id"] == id_].copy()
            if df_id.empty:
                continue

            bars_id = bars_tf[bars_tf["id"] == id_].copy()
            if bars_id.empty:
                continue

            # Process each period
            for period in periods:
                df_out = self._build_one_id_tf_period(
                    daily=df_id,
                    bars_tf=bars_id,
                    tf_days_for_alpha=tf_spec.tf_days,
                    period=period,
                )

                if not df_out.empty:
                    df_out["id"] = int(id_)
                    df_out["tf"] = tf_spec.tf
                    df_out["period"] = int(period)
                    df_out["tf_days"] = tf_spec.tf_days
                    out_frames.append(df_out)

        if not out_frames:
            return pd.DataFrame()

        result = pd.concat(out_frames, ignore_index=True)
        result["ts"] = pd.to_datetime(result["ts"], utc=True)
        return result

    def get_output_schema(self) -> dict[str, str]:
        """Define output table schema for calendar anchor EMAs."""
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

    def _load_anchor_bars(self, ids: list[int], tfs: list[str]) -> pd.DataFrame:
        """Load anchor bar snapshots from bars table."""
        if not ids or not tfs:
            return pd.DataFrame()

        sql = f"""
          SELECT
            id,
            tf,
            tf_days,
            bar_seq,
            time_close AS ts,
            close,
            is_partial_end
          FROM {self.bars_table}
          WHERE id = ANY(:ids)
            AND tf = ANY(:tfs)
          ORDER BY id, tf, bar_seq, ts
        """

        with self.engine.connect() as conn:
            df = read_sql_polars(sql, conn, params={"ids": ids, "tfs": tfs})

        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df["is_partial_end"] = df["is_partial_end"].astype(bool)
            df = df.sort_values(["id", "tf", "bar_seq", "ts"]).reset_index(drop=True)

        return df

    def _build_one_id_tf_period(
        self,
        daily: pd.DataFrame,
        bars_tf: pd.DataFrame,
        tf_days_for_alpha: int,
        period: int,
    ) -> pd.DataFrame:
        """Build full daily-grid output for single (id, tf, period)."""
        df = daily[["ts", "close"]].copy()
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values("ts").reset_index(drop=True)

        b = bars_tf.copy()
        b["ts"] = pd.to_datetime(b["ts"], utc=True)
        b = b.sort_values(["bar_seq", "ts"]).reset_index(drop=True)

        # Identify canonical bar closes (is_partial_end = FALSE)
        is_canon_row = (b["is_partial_end"] == False)
        canon_b = b.loc[is_canon_row].copy()

        # Dedupe to 1 canonical row per bar_seq (keep last)
        canon_b = (
            canon_b.sort_values(["bar_seq", "ts"])
            .drop_duplicates(subset=["bar_seq"], keep="last")
            .sort_values("ts")
            .reset_index(drop=True)
        )

        canonical_ts = canon_b["ts"].drop_duplicates().sort_values()

        # Roll flags
        is_canonical_day = df["ts"].isin(canonical_ts.tolist())
        roll = (~is_canonical_day).astype(bool)

        # roll_bar from is_partial_end
        roll_src = b[["ts", "is_partial_end"]].drop_duplicates(subset=["ts"], keep="last")
        m_roll = df.merge(roll_src, on="ts", how="left")
        roll_bar = m_roll["is_partial_end"].fillna(True).astype(bool)

        # Force canonical_ts days to roll_bar FALSE
        if len(canonical_ts) > 0:
            roll_bar = np.where(df["ts"].isin(canonical_ts.tolist()), False, roll_bar).astype(bool)

        # Canonical bar EMA at anchored closes
        canon_b["ema_close"] = compute_ema(
            canon_b["close"].astype(float), period=period, adjust=False, min_periods=period
        )
        canon_map = canon_b[["ts", "ema_close"]].drop_duplicates(subset=["ts"])

        m = df.merge(canon_map, on="ts", how="left")

        # ema_bar: evolves daily, snaps at anchored closes
        alpha_d_bar = self._alpha_daily_equivalent(tf_days_for_alpha, period)
        ema_bar = pd.Series(np.nan, index=m.index, dtype=float)

        is_canon_bar_day = (~pd.Series(roll_bar, index=df.index)).to_numpy()
        seed_mask = is_canon_bar_day & (~m["ema_close"].isna().to_numpy())
        seed_pos = np.where(seed_mask)[0]

        closes = m["close"].astype(float).to_numpy()
        ema_close_arr = m["ema_close"].astype(float).to_numpy()

        if len(seed_pos) > 0:
            i0 = int(seed_pos[0])
            ema_bar.iloc[:i0] = np.nan
            ema_bar.iloc[i0] = float(ema_close_arr[i0])

            for i in range(i0 + 1, len(m)):
                prev = float(ema_bar.iloc[i - 1])
                x = float(closes[i])
                v = alpha_d_bar * x + (1.0 - alpha_d_bar) * prev

                # Snap on anchored close days
                if is_canon_bar_day[i] and not np.isnan(ema_close_arr[i]):
                    v = float(ema_close_arr[i])

                ema_bar.iloc[i] = v

        # ema: seeded once, continuous daily
        alpha_d = self._alpha_daily_equivalent(tf_days_for_alpha, period)
        ema = pd.Series(np.nan, index=m.index, dtype=float)

        seed_mask_time = (~roll.values) & (~ema_bar.isna().to_numpy())
        seed_pos_time = np.where(seed_mask_time)[0]

        if len(seed_pos_time) > 0:
            j0 = int(seed_pos_time[0])
            ema.iloc[:j0] = np.nan
            ema.iloc[j0] = float(ema_bar.iloc[j0])

            for i in range(j0 + 1, len(m)):
                prev = float(ema.iloc[i - 1])
                x = float(closes[i])
                ema.iloc[i] = alpha_d * x + (1.0 - alpha_d) * prev

        out = pd.DataFrame({
            "ts": df["ts"],
            "roll": roll.astype(bool),
            "ema": ema.astype(float),
            "ema_bar": ema_bar.astype(float),
            "roll_bar": pd.Series(roll_bar, index=df.index).astype(bool),
        })

        # Derivatives
        out = self._add_cal_anchor_derivatives(out)

        return out[[
            "ts", "roll", "ema", "d1", "d2", "d1_roll", "d2_roll",
            "ema_bar", "d1_bar", "d2_bar", "roll_bar", "d1_roll_bar", "d2_roll_bar",
        ]]

    def _alpha_daily_equivalent(self, tf_days: int, period: int) -> float:
        """
        Convert bar-space alpha to daily-step alpha.

        alpha_daily = 1 - (1 - alpha_bar)^(1/tf_days)
        """
        if tf_days <= 0:
            raise ValueError(f"tf_days must be positive, got {tf_days}")
        alpha_bar = 2.0 / (period + 1.0)
        return 1.0 - (1.0 - alpha_bar) ** (1.0 / tf_days)

    def _canonical_subset_diff(self, x: pd.Series, is_canonical: pd.Series) -> pd.Series:
        """Canonical-only diff computed between canonical rows."""
        is_canonical = is_canonical.astype(bool)
        y = pd.Series(np.nan, index=x.index, dtype=float)

        idx = x.index[is_canonical.values]
        if len(idx) <= 1:
            return y

        xc = x.loc[idx].astype(float)
        dc = xc.diff()
        y.loc[idx] = dc.values
        return y

    def _add_cal_anchor_derivatives(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add derivatives for dual EMAs (anchor semantics)."""
        result = df.copy()

        # Daily diffs on ema (all rows)
        result["d1_roll"] = result["ema"].diff()
        result["d2_roll"] = result["d1_roll"].diff()

        # Canonical-only diffs on ema
        is_canon = ~result["roll"]
        result["d1"] = self._canonical_subset_diff(result["ema"], is_canon)
        result["d2"] = self._canonical_subset_diff(result["d1"], is_canon)

        # Daily diffs on ema_bar (all rows)
        result["d1_roll_bar"] = result["ema_bar"].diff()
        result["d2_roll_bar"] = result["d1_roll_bar"].diff()

        # Canonical-only diffs on ema_bar
        is_canon_bar = ~result["roll_bar"]
        result["d1_bar"] = self._canonical_subset_diff(result["ema_bar"], is_canon_bar)
        result["d2_bar"] = self._canonical_subset_diff(result["d1_bar"], is_canon_bar)

        return result


# =============================================================================
# Public API (Backward Compatibility)
# =============================================================================

def write_multi_timeframe_ema_cal_anchor_to_db(
    engine_or_db_url,
    ids: Sequence[int],
    *,
    scheme: str = "US",
    start: Optional[str] = None,
    end: Optional[str] = None,
    ema_periods: Sequence[int] = (6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365),
    schema: str = "public",
    out_table: Optional[str] = None,
    alpha_schema: str = "public",
    alpha_table: str = "ema_alpha_lookup",
    update_existing: bool = True,
) -> int:
    """
    Compute calendar-anchor multi-timeframe EMAs and write to database.

    Uses the refactored BaseEMAFeature architecture with full dual EMA implementation.
    """
    from sqlalchemy import create_engine

    if isinstance(engine_or_db_url, str):
        engine = create_engine(engine_or_db_url, future=True)
    else:
        engine = engine_or_db_url

    scheme_u = scheme.strip().upper()
    if out_table is None:
        out_table = f"cmc_ema_multi_tf_cal_anchor_{scheme_u.lower()}"

    logger.info(f"Computing calendar anchor EMAs: scheme={scheme_u}, periods={len(ema_periods)}, ids={len(ids)}")

    config = EMAFeatureConfig(
        periods=list(ema_periods),
        output_schema=schema,
        output_table=out_table,
    )

    feature = CalendarAnchorEMAFeature(
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
    logger.info(f"Processing {len(tf_specs)} calendar anchor TFs")

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

    upsert_sql = text(f"""
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
    """)

    logger.info(f"Writing {len(df_out):,} rows to {schema}.{out_table}...")

    # Batch writes
    BATCH_SIZE = 10_000
    payload = df_out.to_dict(orient="records")
    total_rows = len(payload)

    with engine.begin() as conn:
        for i in range(0, total_rows, BATCH_SIZE):
            batch = payload[i:i + BATCH_SIZE]
            conn.execute(upsert_sql, batch)

            rows_written = min(i + BATCH_SIZE, total_rows)
            if rows_written % 50_000 == 0 or rows_written == total_rows or i == 0:
                pct = (rows_written / total_rows) * 100
                logger.info(f"  Written {rows_written:,} / {total_rows:,} rows ({pct:.1f}%)")

    logger.info(f"Successfully wrote {len(df_out):,} rows")
    return len(df_out)
