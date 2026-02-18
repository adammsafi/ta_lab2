"""
Calendar-anchor multi-timeframe EMA - REFACTORED to use BaseEMAFeature.

Calendar anchor EMA semantics:
- Canonical closes from cmc_price_bars_multi_tf_cal_anchor_us/iso
- Timeframe universe from dim_timeframe (alignment_type='calendar', ANCHOR families)
- Similar to cal but with anchored periods
- Uses is_partial_end (not roll) column for canonical detection
- Dual EMAs: ema (daily-space) and ema_bar (bar-space with preview)
- Alpha from lookup table (ema_alpha_lookup), fallback to geometric formula

LEAN SCHEMA: EMA tables store only EMA values. All derivatives
(d1, d2, delta1, delta2, ret_arith, ret_log) live in returns tables.

REFACTORED CHANGES:
- Extends BaseEMAFeature abstract class
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
from ta_lab2.features.m_tf.polars_ema_operations import (
    compute_bar_ema_numpy,
    compute_dual_ema_numpy,
)

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
    - Alpha from ema_alpha_lookup table (fallback to geometric formula)
    - is_partial_end column for bar completeness tracking
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
        """Load daily closes for all IDs."""
        where = ["id = ANY(:ids)"]
        params = {"ids": ids}

        if start:
            where.append('"timestamp" >= :start')
            params["start"] = start
        if end:
            where.append('"timestamp" <= :end')
            params["end"] = end

        sql = f"""
          SELECT id, "timestamp" AS ts, close
          FROM public.cmc_price_bars_1d
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
        """Load calendar anchor TF specs from dim_timeframe."""
        if self._tf_specs_cache is not None:
            return self._tf_specs_cache

        # Load ANCHOR timeframes from dim_timeframe
        sql = """
          SELECT
            tf,
            COALESCE(tf_days_nominal, tf_days_max, tf_days_min) AS tf_days
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

        tf_specs = [
            TFSpec(tf=r.tf, tf_days=int(r.tf_days)) for r in df.itertuples(index=False)
        ]

        logger.info(
            f"Loaded {len(tf_specs)} calendar anchor TF specs for scheme={self.scheme}"
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
        Compute calendar anchor EMAs for single TF.

        Implements dual EMA logic with anchored semantics:
        - ema: daily-space, seeded once, continuous daily updates
        - ema_bar: bar-space, snaps at anchored closes, evolves daily between
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
                # Get alpha from lookup or fallback
                alpha_daily = alpha_map.get((tf_spec.tf, period))
                if alpha_daily is None:
                    alpha_daily = self._alpha_daily_equivalent(tf_spec.tf_days, period)
                    logger.debug(
                        f"Alpha not in lookup for ({tf_spec.tf}, {period}), "
                        f"using fallback: {alpha_daily:.8f}"
                    )

                df_out = self._build_one_id_tf_period(
                    daily=df_id,
                    bars_tf=bars_id,
                    period=period,
                    alpha_daily=alpha_daily,
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
        """Define output table schema for calendar anchor EMAs (lean - EMA only)."""
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
            "timestamp" AS ts,
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

    def _build_one_id_tf_period(
        self,
        daily: pd.DataFrame,
        bars_tf: pd.DataFrame,
        period: int,
        alpha_daily: float,
    ) -> pd.DataFrame:
        """
        Build full daily-grid output for single (id, tf, period).

        Vectorized with numpy: compute_bar_ema_numpy + compute_dual_ema_numpy
        replace pd.Series.iloc[i] loops (~100x faster for large series).
        """
        df = daily[["ts", "close"]].copy()
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values("ts").reset_index(drop=True)

        b = bars_tf.copy()
        b["ts"] = pd.to_datetime(b["ts"], utc=True)
        b = b.sort_values(["bar_seq", "ts"]).reset_index(drop=True)

        # Identify canonical bar closes (is_partial_end = FALSE)
        is_canon_row = b["is_partial_end"].eq(False)
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
        canonical_ts_set = set(canonical_ts.tolist())
        is_canonical_day = df["ts"].isin(canonical_ts_set)
        roll = (~is_canonical_day).to_numpy().astype(bool)
        canonical_mask = ~roll

        # Canonical bar EMA at anchored closes using numpy
        canon_close_arr = canon_b["close"].astype(float).to_numpy()
        canon_ema_arr = compute_bar_ema_numpy(
            canon_close_arr, period=period, min_periods=period
        )

        # Build canonical EMA map: ts -> ema_close
        canon_ts_arr = canon_b["ts"].values
        canon_ema_map = {}
        for i in range(len(canon_ts_arr)):
            if not np.isnan(canon_ema_arr[i]):
                canon_ema_map[canon_ts_arr[i]] = canon_ema_arr[i]

        # Build arrays for compute_dual_ema_numpy
        n = len(df)
        close_arr = df["close"].astype(float).to_numpy()
        ts_arr = df["ts"].values

        # Map canonical EMA values onto daily grid
        canonical_ema_values = np.full(n, np.nan, dtype=np.float64)
        for i in range(n):
            if canonical_mask[i] and ts_arr[i] in canon_ema_map:
                canonical_ema_values[i] = canon_ema_map[ts_arr[i]]

        # Compute dual EMA using numpy
        alpha_bar = 2.0 / (period + 1.0)
        ema_bar_arr, ema_arr = compute_dual_ema_numpy(
            close_arr,
            canonical_mask=canonical_mask,
            canonical_ema_values=canonical_ema_values,
            alpha_daily=alpha_daily,
            alpha_bar=alpha_bar,
        )

        # is_partial_end: True for rows after the last canonical close
        last_canon_ts = canonical_ts.max() if len(canonical_ts) > 0 else None
        if last_canon_ts is not None:
            is_partial = (df["ts"] > last_canon_ts).to_numpy()
        else:
            is_partial = np.ones(n, dtype=bool)

        out = pd.DataFrame(
            {
                "ts": df["ts"],
                "roll": roll.astype(bool),
                "ema": ema_arr,
                "ema_bar": ema_bar_arr,
                "is_partial_end": is_partial,
            }
        )

        # Filter pre-seed rows: only output from first valid ema_bar onward
        has_ema_bar = out["ema_bar"].notna()
        if not has_ema_bar.any():
            return pd.DataFrame()
        first_valid = has_ema_bar.idxmax()
        out = out.loc[first_valid:].reset_index(drop=True)

        return out[
            [
                "ts",
                "roll",
                "ema",
                "ema_bar",
                "is_partial_end",
            ]
        ]

    def _alpha_daily_equivalent(self, tf_days: int, period: int) -> float:
        """
        Convert bar-space alpha to daily-step alpha.

        alpha_daily = 1 - (1 - alpha_bar)^(1/tf_days)
        """
        if tf_days <= 0:
            raise ValueError(f"tf_days must be positive, got {tf_days}")
        alpha_bar = 2.0 / (period + 1.0)
        return 1.0 - (1.0 - alpha_bar) ** (1.0 / tf_days)


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

    logger.info(
        f"Computing calendar anchor EMAs: scheme={scheme_u}, periods={len(ema_periods)}, ids={len(ids)}"
    )

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

    # Pre-filter: only keep TFs that have bars for the requested IDs
    with engine.connect() as conn:
        bar_tfs = (
            conn.execute(
                text(
                    f"SELECT DISTINCT tf FROM {feature.bars_table} WHERE id = ANY(:ids)"
                ),
                {"ids": list(ids)},
            )
            .scalars()
            .all()
        )
    bar_tf_set = set(bar_tfs)
    skipped = [s.tf for s in tf_specs if s.tf not in bar_tf_set]
    tf_specs = [s for s in tf_specs if s.tf in bar_tf_set]
    if skipped:
        logger.info(f"Skipping {len(skipped)} TFs with no bars: {skipped}")
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
        tf_days          = EXCLUDED.tf_days,
        roll             = EXCLUDED.roll,
        ema              = EXCLUDED.ema,
        ema_bar          = EXCLUDED.ema_bar,
        is_partial_end   = EXCLUDED.is_partial_end,
        ingested_at      = now()"""
        if update_existing
        else "DO NOTHING"
    )

    upsert_sql = text(
        f"""
      INSERT INTO {schema}.{out_table} (
        id, tf, ts, period, tf_days,
        roll, ema, ema_bar, is_partial_end,
        ingested_at
      )
      VALUES (
        :id, :tf, :ts, :period, :tf_days,
        :roll, :ema, :ema_bar, :is_partial_end,
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
