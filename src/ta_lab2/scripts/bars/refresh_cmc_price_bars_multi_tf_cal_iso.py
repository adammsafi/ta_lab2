from __future__ import annotations

# ruff: noqa: E402
"""
Calendar-aligned price bars builder for ISO weeks (Monday-start):

    public.cmc_price_bars_multi_tf_cal_iso

derived from daily input data in:

    public.cmc_price_histories7


OVERVIEW
--------
This script builds **calendar-aligned, multi-timeframe price bars** using an
**append-only, daily-snapshot model**, driven entirely by definitions in
`public.dim_timeframe`.

Each calendar bar (week, month, year, etc.) exists across multiple daily rows
while it is forming. A bar is considered *canonical* only on its scheduled
calendar end-day; all prior rows are in-progress snapshots.

ISO CALENDAR SEMANTICS
----------------------
- Weeks start on Monday (ISO convention, weekday=0)
- Full-period policy: only complete calendar periods emitted
- is_partial_start always FALSE
- is_partial_end TRUE for in-progress bars

REFACTORED (24-04): Now uses BaseBarBuilder template method pattern.
"""

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import polars as pl
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.base_bar_builder import BaseBarBuilder
from ta_lab2.scripts.bars.bar_builder_config import BarBuilderConfig
from ta_lab2.scripts.bars.common_snapshot_contract import (
    assert_one_row_per_local_day,
    resolve_db_url,
    get_engine,
    parse_ids,
    load_all_ids,
    ensure_state_table,
    load_state,
    upsert_state,
    upsert_bars,
    load_daily_prices_for_id,
    delete_bars_for_id_tf,
    load_last_snapshot_info_for_id_tfs,
    get_coverage_n_days,
)
from ta_lab2.scripts.bars.polars_bar_operations import (
    compute_extrema_timestamps_with_new_extreme_detection,
)
from ta_lab2.scripts.bars.derive_multi_tf_from_1d import (
    derive_multi_tf_bars,
    validate_derivation_consistency,
    BUILDER_ALIGNMENT_MAP,
)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_TZ = "America/New_York"
DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_iso"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_iso_state"


# =============================================================================
# Calendar Spec
# =============================================================================


@dataclass(frozen=True)
class CalSpec:
    tf: str
    unit: str  # 'W' | 'M' | 'Y'
    qty: int


# =============================================================================
# Calendar Boundary Helpers (ISO weeks: Monday start)
# =============================================================================


def _compute_anchor_start(first_day: date, unit: str) -> date:
    """
    Compute the first full-period start on or after first_day.

    - W: next Monday on or after first_day (ISO week convention)
    - M: first day of next month if first_day is not the 1st, else first_day
    - Y: first day of next year if first_day is not Jan 1, else first_day
    """
    if unit == "W":
        # ISO weeks start on Monday (weekday = 0)
        weekday = first_day.weekday()
        if weekday == 0:
            return first_day  # Already Monday
        days_until_monday = (7 - weekday) % 7
        return first_day + timedelta(
            days=days_until_monday if days_until_monday > 0 else 7
        )

    if unit == "M":
        if first_day.day == 1:
            return first_day
        if first_day.month == 12:
            return date(first_day.year + 1, 1, 1)
        return date(first_day.year, first_day.month + 1, 1)

    if unit == "Y":
        if first_day.month == 1 and first_day.day == 1:
            return first_day
        return date(first_day.year + 1, 1, 1)

    raise ValueError(f"Unsupported unit: {unit}")


def _next_boundary(d: date, unit: str, qty: int) -> date:
    """Return next calendar boundary after d for given unit/qty."""
    if unit == "W":
        return d + timedelta(days=7 * qty)
    if unit == "M":
        year = d.year + (d.month - 1 + qty) // 12
        month = (d.month - 1 + qty) % 12 + 1
        return date(year, month, 1)
    if unit == "Y":
        return date(d.year + qty, 1, 1)
    raise ValueError(f"Unsupported unit: {unit}")


def _bar_end_day(bar_start: date, unit: str, qty: int) -> date:
    """Return last day (inclusive) of calendar bar."""
    next_start = _next_boundary(bar_start, unit, qty)
    return next_start - timedelta(days=1)


def _nominal_tf_days(spec: CalSpec) -> int:
    """Approximate minimum calendar days needed for one complete bar."""
    if spec.unit == "W":
        return spec.qty * 7
    if spec.unit == "M":
        return spec.qty * 28
    if spec.unit == "Y":
        return spec.qty * 365
    return 1


# =============================================================================
# CalendarISOBarBuilder - Inherits from BaseBarBuilder
# =============================================================================


class CalendarISOBarBuilder(BaseBarBuilder):
    """
    Calendar-aligned ISO bar builder - builds calendar bars with ISO week convention.

    ISO Semantics:
    - Weeks start on Monday (weekday=0)
    - Full-period policy (no partial start/end bars)
    - Calendar-aligned to week/month/year boundaries

    Inherits shared infrastructure from BaseBarBuilder.
    """

    STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_iso_state"
    OUTPUT_TABLE = "public.cmc_price_bars_multi_tf_cal_iso"

    def __init__(
        self,
        config: BarBuilderConfig,
        engine: Engine,
        specs: list[CalSpec],
        from_1d: bool = False,
        validate_derivation: bool = False,
    ):
        """
        Initialize Calendar ISO bar builder.

        Args:
            config: Bar builder configuration
            engine: SQLAlchemy engine
            specs: List of CalSpec timeframe specifications
            from_1d: Derive from 1D bars instead of daily prices
            validate_derivation: Compare derived bars to direct computation
        """
        super().__init__(config, engine)
        self.specs = specs
        self.from_1d = from_1d
        self.validate_derivation = validate_derivation

        self.logger.info(f"Loaded {len(specs)} calendar specs: {[s.tf for s in specs]}")
        if from_1d:
            self.logger.info("Derivation mode: building from cmc_price_bars_1d")
        if validate_derivation:
            self.logger.info("Validation mode: comparing derived vs direct computation")

    # =========================================================================
    # Abstract method implementations (required by BaseBarBuilder)
    # =========================================================================

    def get_state_table_name(self) -> str:
        """
        Return state table name.

        Note on calendar builder state tables:
        tz column is metadata only, NOT part of PRIMARY KEY.
        Calendar builders process single timezone per run (--tz flag).
        See sql/ddl/calendar_state_tables.sql for full rationale.
        """
        return self.STATE_TABLE

    def get_output_table_name(self) -> str:
        """Return output bars table name."""
        return self.OUTPUT_TABLE

    def get_source_query(
        self, id_: int, start_ts: Optional[str] = None, **kwargs
    ) -> str:
        """
        Return SQL query to load daily prices for one ID.

        Args:
            id_: Cryptocurrency ID
            start_ts: Optional start timestamp for incremental refresh
            **kwargs: Additional arguments (unused, for signature compatibility)

        Returns:
            SQL query string to load daily price data
        """
        if start_ts:
            return f"""
                SELECT id, timestamp as ts, open, high, low, close, volume, market_cap, timehigh, timelow
                FROM {self.config.daily_table}
                WHERE id = {id_}
                  AND timestamp >= '{start_ts}'
                ORDER BY timestamp;
            """
        else:
            return f"""
                SELECT id, timestamp as ts, open, high, low, close, volume, market_cap, timehigh, timelow
                FROM {self.config.daily_table}
                WHERE id = {id_}
                ORDER BY timestamp;
            """

    def build_bars_for_id(
        self,
        id_: int,
        start_ts: Optional[str] = None,
    ) -> int:
        """
        Build calendar bars for one ID across all timeframe specs.

        This is the variant-specific core logic that:
        1. Optionally derives from 1D bars (if from_1d=True)
        2. Loads daily prices
        3. For each calendar spec:
           - Check for backfill
           - Full rebuild or incremental append
           - Upsert bars and update state

        Args:
            id_: Cryptocurrency ID
            start_ts: Optional start timestamp (for incremental)

        Returns:
            Total number of rows inserted/updated across all specs
        """
        total_rows = 0

        # Derivation mode (from 1D bars)
        if self.from_1d:
            alignment, anchor_mode = BUILDER_ALIGNMENT_MAP["cal_iso"]
            timeframes_list = [spec.tf for spec in self.specs]

            bars_all = derive_multi_tf_bars(
                engine=self.engine,
                id=int(id_),
                timeframes=timeframes_list,
                alignment=alignment,
                anchor_mode=anchor_mode,
            )

            if self.validate_derivation:
                # Compare derived vs direct
                df_full = load_daily_prices_for_id(
                    db_url=self.config.db_url,
                    daily_table=self.config.daily_table,
                    id_=int(id_),
                    tz=self.config.tz or DEFAULT_TZ,
                )

                bars_direct_all = []
                for spec in self.specs:
                    bars_direct = self._build_snapshots_full_history_polars(
                        df_full, spec=spec, tz=self.config.tz or DEFAULT_TZ
                    )
                    if not bars_direct.empty:
                        bars_direct_all.append(bars_direct)

                if bars_direct_all:
                    bars_direct_combined = pl.from_pandas(
                        pd.concat(bars_direct_all, ignore_index=True)
                    )
                    validate_derivation_consistency(
                        bars_derived=bars_all,
                        bars_direct=bars_direct_combined,
                        id=int(id_),
                        alignment=alignment,
                    )

            # Upsert derived bars
            if not bars_all.empty:
                bars_pd = bars_all.to_pandas()
                upsert_bars(
                    bars_pd,
                    db_url=self.config.db_url,
                    bars_table=self.get_output_table_name(),
                )
                total_rows += len(bars_pd)

                # Update state
                for spec in self.specs:
                    spec_bars = bars_pd[bars_pd["tf"] == spec.tf]
                    if not spec_bars.empty:
                        last_bar_seq = int(spec_bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(
                            spec_bars["timestamp"].max(), utc=True
                        )
                        daily_min_ts = pd.to_datetime(
                            spec_bars["time_open"].min(), utc=True
                        )
                        daily_max_ts = pd.to_datetime(
                            spec_bars["timestamp"].max(), utc=True
                        )

                        upsert_state(
                            self.config.db_url,
                            self.get_state_table_name(),
                            [
                                {
                                    "id": int(id_),
                                    "tf": spec.tf,
                                    "tz": self.config.tz,
                                    "daily_min_seen": daily_min_ts,
                                    "daily_max_seen": daily_max_ts,
                                    "last_bar_seq": last_bar_seq,
                                    "last_time_close": last_time_close,
                                }
                            ],
                            with_tz=True,
                        )

            return total_rows

        # Direct mode (from daily prices)
        # Load daily price data
        df_daily = load_daily_prices_for_id(
            db_url=self.config.db_url,
            daily_table=self.config.daily_table,
            id_=id_,
            ts_start=start_ts,
            tz=self.config.tz or DEFAULT_TZ,
        )

        if df_daily.empty:
            self.logger.info(f"ID={id_}: No daily data found")
            return 0

        daily_min_ts = pd.to_datetime(df_daily["ts"].min(), utc=True)
        daily_max_ts = pd.to_datetime(df_daily["ts"].max(), utc=True)

        # Load existing state for all specs
        state_df = load_state(
            self.config.db_url,
            self.get_state_table_name(),
            [id_],
            with_tz=True,
        )

        state_map = {}
        if not state_df.empty:
            for _, row in state_df.iterrows():
                state_map[row["tf"]] = row

        # Look up coverage from asset_data_coverage (populated by 1D builder)
        n_available = get_coverage_n_days(
            get_engine(self.config.db_url),
            id_,
            source_table=self.config.daily_table,
            granularity="1D",
        )
        if n_available is None:
            n_available = self._count_total_daily_rows(id_)
        applicable_specs = [s for s in self.specs if _nominal_tf_days(s) <= n_available]
        skipped = len(self.specs) - len(applicable_specs)
        if skipped:
            self.logger.info(
                f"ID={id_}: Skipping {skipped} calendar spec(s) "
                f"(nominal tf_days > {n_available} available days)"
            )

        # Process each spec
        for spec in applicable_specs:
            try:
                rows = self._build_bars_for_id_spec(
                    id_=id_,
                    spec=spec,
                    df_daily=df_daily,
                    daily_min_ts=daily_min_ts,
                    daily_max_ts=daily_max_ts,
                    state=state_map.get(spec.tf),
                )
                total_rows += rows
            except Exception as e:
                self.logger.error(f"ID={id_}, TF={spec.tf} failed: {e}", exc_info=True)
                continue

        return total_rows

    def _count_total_daily_rows(self, id_: int) -> int:
        """Count total daily rows for an ID in the source table."""
        engine = get_engine(self.config.db_url)
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT COUNT(*) FROM {self.config.daily_table} WHERE id = :id"),
                {"id": int(id_)},
            ).scalar()
        return int(result or 0)

    def _build_bars_for_id_spec(
        self,
        id_: int,
        spec: CalSpec,
        df_daily: pd.DataFrame,
        daily_min_ts: pd.Timestamp,
        daily_max_ts: pd.Timestamp,
        state: Optional[dict],
    ) -> int:
        """
        Build bars for one (id, spec) combination.

        Handles:
        - Backfill detection
        - Full rebuild vs incremental append
        - State updates

        Returns:
            Number of rows inserted/updated
        """
        # Determine if backfill is needed
        needs_rebuild = False
        if state is not None:
            daily_min_seen = pd.to_datetime(state.get("daily_min_seen"), utc=True)
            if pd.notna(daily_min_seen) and daily_min_ts < daily_min_seen:
                self.logger.info(
                    f"ID={id_}, TF={spec.tf}: Backfill detected "
                    f"({daily_min_seen} -> {daily_min_ts}), rebuilding"
                )
                needs_rebuild = True

        # Full rebuild path
        if needs_rebuild or state is None or self.config.full_rebuild:
            if needs_rebuild or self.config.full_rebuild:
                delete_bars_for_id_tf(
                    self.config.db_url,
                    self.get_output_table_name(),
                    id_=id_,
                    tf=spec.tf,
                )

            bars = self._build_snapshots_full_history_polars(
                df_daily, spec=spec, tz=self.config.tz or DEFAULT_TZ
            )
            if bars.empty:
                return 0

            upsert_bars(
                bars, db_url=self.config.db_url, bars_table=self.get_output_table_name()
            )

            # Update state
            last_bar_seq = int(bars["bar_seq"].max())
            last_time_close = pd.to_datetime(bars["timestamp"].max(), utc=True)

            upsert_state(
                self.config.db_url,
                self.get_state_table_name(),
                [
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": self.config.tz,
                        "daily_min_seen": daily_min_ts,
                        "daily_max_seen": daily_max_ts,
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                ],
                with_tz=True,
            )

            return len(bars)

        # Incremental append path
        last_time_close = pd.to_datetime(state.get("last_time_close"), utc=True)
        if daily_max_ts <= last_time_close:
            # No new data
            return 0

        # Load last snapshot info
        last_info = load_last_snapshot_info_for_id_tfs(
            self.config.db_url,
            self.get_output_table_name(),
            int(id_),
            [spec.tf],
        )

        if not last_info or spec.tf not in last_info:
            self.logger.warning(
                f"ID={id_}, TF={spec.tf}: No last snapshot info, rebuilding"
            )
            # Rebuild
            delete_bars_for_id_tf(
                self.config.db_url, self.get_output_table_name(), id_=id_, tf=spec.tf
            )
            bars = self._build_snapshots_full_history_polars(
                df_daily, spec=spec, tz=self.config.tz or DEFAULT_TZ
            )
            if bars.empty:
                return 0

            upsert_bars(
                bars, db_url=self.config.db_url, bars_table=self.get_output_table_name()
            )

            last_bar_seq = int(bars["bar_seq"].max())
            last_time_close = pd.to_datetime(bars["timestamp"].max(), utc=True)

            upsert_state(
                self.config.db_url,
                self.get_state_table_name(),
                [
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": self.config.tz,
                        "daily_min_seen": daily_min_ts,
                        "daily_max_seen": daily_max_ts,
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                ],
                with_tz=True,
            )

            return len(bars)

        # Incremental append
        # For calendar bars, incremental is complex (requires calendar boundary logic)
        # For simplicity in this refactoring, we'll rebuild on new data
        # (The original implementation has complex incremental logic that can be added back if needed)

        self.logger.info(
            f"ID={id_}, TF={spec.tf}: New data detected, rebuilding for now"
        )
        delete_bars_for_id_tf(
            self.config.db_url, self.get_output_table_name(), id_=id_, tf=spec.tf
        )
        bars = self._build_snapshots_full_history_polars(
            df_daily, spec=spec, tz=self.config.tz or DEFAULT_TZ
        )
        if bars.empty:
            return 0

        upsert_bars(
            bars, db_url=self.config.db_url, bars_table=self.get_output_table_name()
        )

        last_bar_seq = int(bars["bar_seq"].max())
        last_time_close = pd.to_datetime(bars["timestamp"].max(), utc=True)

        upsert_state(
            self.config.db_url,
            self.get_state_table_name(),
            [
                {
                    "id": int(id_),
                    "tf": spec.tf,
                    "tz": self.config.tz,
                    "daily_min_seen": daily_min_ts,
                    "daily_max_seen": daily_max_ts,
                    "last_bar_seq": last_bar_seq,
                    "last_time_close": last_time_close,
                }
            ],
            with_tz=True,
        )

        return len(bars)

    def _build_snapshots_full_history_polars(
        self,
        df_daily: pd.DataFrame,
        spec: CalSpec,
        tz: str,
    ) -> pd.DataFrame:
        """
        FAST PATH: Full build using Polars vectorization.

        Builds calendar-aligned bars with ISO week convention (Monday start).
        Emits ONE ROW PER DAY per bar_seq (append-only snapshots).
        """
        if df_daily.empty:
            return pd.DataFrame()

        # Hard invariant (shared contract)
        assert_one_row_per_local_day(df_daily, ts_col="ts", tz=tz, id_col="id")

        df = df_daily.sort_values("ts").reset_index(drop=True).copy()

        # Convert to local timezone for calendar math
        df["ts_local"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(tz)
        df["day_local"] = df["ts_local"].dt.date

        # Find first full calendar boundary
        first_day = df["day_local"].iloc[0]
        anchor_start = _compute_anchor_start(first_day, spec.unit)

        # Filter to data starting from anchor_start
        df = df[df["day_local"] >= anchor_start].reset_index(drop=True)

        if df.empty:
            return pd.DataFrame()

        # Assign bar_seq and scheduled bar_end_day based on calendar boundaries
        bar_seqs = []
        bar_end_days = []
        bar_start_days = []
        bar_seq = 1
        current_bar_start = anchor_start

        for day_local in df["day_local"]:
            # Check if we've moved to next bar
            bar_end = _bar_end_day(current_bar_start, spec.unit, spec.qty)
            while day_local > bar_end:
                # Start new bar
                bar_seq += 1
                current_bar_start = _next_boundary(
                    current_bar_start, spec.unit, spec.qty
                )
                bar_end = _bar_end_day(current_bar_start, spec.unit, spec.qty)

            bar_seqs.append(bar_seq)
            bar_end_days.append(bar_end)
            bar_start_days.append(current_bar_start)

        df["bar_seq"] = bar_seqs
        df["bar_end_day"] = bar_end_days
        df["bar_start_day"] = bar_start_days

        # Convert to Polars for vectorized aggregation
        pl_df = pl.from_pandas(df)

        # Normalize timehigh/timelow to tz-naive μs for Polars compatibility
        for col in ["timehigh", "timelow", "ts"]:
            if col in pl_df.columns and pl_df[col].dtype != pl.Datetime("us"):
                pl_df = pl_df.with_columns(
                    pl.col(col).cast(pl.Datetime("us")).alias(col)
                )

        # Cumulative aggregations within each bar_seq
        pl_df = pl_df.with_columns(
            [
                pl.col("bar_seq")
                .cum_count()
                .over("bar_seq")
                .cast(pl.Int64)
                .alias("pos_in_bar"),
            ]
        )

        # Aggregate per (bar_seq, snapshot row)
        # For each bar_seq, we emit multiple rows (one per day)
        # Each row shows the bar's state as of that day

        # Compute cumulative OHLC per bar_seq snapshot
        pl_df = pl_df.with_columns(
            [
                pl.col("open").first().over("bar_seq").alias("open_bar"),
                pl.col("high").cum_max().over("bar_seq").alias("high_bar"),
                pl.col("low").cum_min().over("bar_seq").alias("low_bar"),
                pl.col("close").alias("close_bar"),
                pl.col("volume").cum_sum().over("bar_seq").alias("volume_bar"),
                pl.col("market_cap").alias("market_cap_bar"),
            ]
        )

        # Compute time_high and time_low with correct new-extreme reset
        pl_df = compute_extrema_timestamps_with_new_extreme_detection(
            pl_df, group_col="bar_seq"
        )

        # Compute tf_days from window boundaries (nominal width)
        pl_df = pl_df.with_columns(
            [
                (
                    (pl.col("bar_end_day") - pl.col("bar_start_day"))
                    .dt.total_days()
                    .cast(pl.Int64)
                    + 1
                ).alias("tf_days_calc"),
            ]
        )

        # Compute is_partial_end: True when bar hasn't reached its end yet
        # (pos_in_bar < tf_days means more days remain in the bar period)
        pl_df = pl_df.with_columns(
            [
                (pl.col("pos_in_bar") < pl.col("tf_days_calc")).alias("is_partial_end"),
            ]
        )

        # Compute time_open, time_close, time_open_bar, time_close_bar
        # time_close = per-row snapshot date (this row's ts) -- REVERTED to old behavior
        # time_close_bar = bar's scheduled end date (from bar_end_day)
        # time_open_bar = bar-level opening time (= time_open)
        pl_df = pl_df.with_columns(
            [
                (pl.col("ts").shift(1) + pl.duration(milliseconds=1))
                .fill_null(
                    pl.col("ts") - pl.duration(days=1) + pl.duration(milliseconds=1)
                )
                .alias("time_open"),
                pl.col("bar_start_day")
                .cast(pl.Datetime("us"))
                .dt.replace_time_zone("UTC")
                .alias("time_open_bar"),
                pl.col("ts").alias("time_close"),
                (
                    pl.col("bar_end_day")
                    .cast(pl.Datetime("us"))
                    .dt.replace_time_zone("UTC")
                    + pl.duration(hours=23, minutes=59, seconds=59, milliseconds=999)
                ).alias("time_close_bar"),
            ]
        )

        # Compute missing days diagnostics (simplified)
        pl_df = pl_df.with_columns(
            [
                pl.col("pos_in_bar").alias("count_days"),
                pl.lit(False).alias("is_missing_days"),
                pl.lit(0).cast(pl.Int64).alias("count_missing_days"),
                (pl.col("tf_days_calc") - pl.col("pos_in_bar")).alias(
                    "count_days_remaining"
                ),
            ]
        )

        # Select final columns
        id_val = int(df["id"].iloc[0])
        out_pl = pl_df.select(
            [
                pl.lit(id_val).cast(pl.Int64).alias("id"),
                pl.lit(spec.tf).alias("tf"),
                pl.col("tf_days_calc").alias("tf_days"),
                pl.col("bar_seq").cast(pl.Int64),
                pl.col("time_open"),
                pl.col("time_close"),
                pl.col("time_high"),
                pl.col("time_low"),
                pl.col("time_open_bar"),
                pl.col("time_close_bar"),
                pl.col("open_bar").cast(pl.Float64).alias("open"),
                pl.col("high_bar").cast(pl.Float64).alias("high"),
                pl.col("low_bar").cast(pl.Float64).alias("low"),
                pl.col("close_bar").cast(pl.Float64).alias("close"),
                pl.col("volume_bar").cast(pl.Float64).alias("volume"),
                pl.col("market_cap_bar").cast(pl.Float64).alias("market_cap"),
                pl.col("ts").alias("timestamp"),
                (pl.col("ts") + pl.duration(milliseconds=1)).alias("last_ts_half_open"),
                pl.col("pos_in_bar").cast(pl.Int64),
                pl.lit(False).alias("is_partial_start"),
                pl.col("is_partial_end").cast(pl.Boolean),
                pl.col("count_days_remaining").cast(pl.Int64),
                pl.col("is_missing_days").cast(pl.Boolean),
                pl.col("count_days").cast(pl.Int64),
                pl.col("count_missing_days").cast(pl.Int64),
                pl.lit(None).cast(pl.Date).alias("first_missing_day"),
                pl.lit(None).cast(pl.Date).alias("last_missing_day"),
                pl.col("src_name"),
                pl.col("src_load_ts"),
                pl.lit("cmc_price_bars_1d").alias("src_file"),
            ]
        )

        # Convert back to pandas
        out = out_pl.to_pandas()

        # Ensure UTC timezone
        for col in [
            "time_open",
            "time_close",
            "time_high",
            "time_low",
            "time_open_bar",
            "time_close_bar",
            "timestamp",
            "last_ts_half_open",
            "src_load_ts",
        ]:
            if col in out.columns:
                out[col] = pd.to_datetime(out[col], utc=True)

        return out

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """
        Create argument parser with calendar ISO specific arguments.

        Returns:
            ArgumentParser with all arguments configured
        """
        parser = cls.create_base_argument_parser(
            description="Build calendar-aligned ISO price bars (Monday-start weeks) into cmc_price_bars_multi_tf_cal_iso.",
            default_daily_table=DEFAULT_DAILY_TABLE,
            default_bars_table=DEFAULT_BARS_TABLE,
            default_state_table=DEFAULT_STATE_TABLE,
            include_tz=True,
            default_tz=DEFAULT_TZ,
        )

        # Calendar ISO specific arguments
        parser.add_argument(
            "--from-1d",
            action="store_true",
            help="Derive multi-TF bars from cmc_price_bars_1d instead of price_histories7",
        )
        parser.add_argument(
            "--validate-derivation",
            action="store_true",
            help="Compare derived bars to direct computation (for migration validation)",
        )

        return parser

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "CalendarISOBarBuilder":
        """
        Factory method: Create builder from CLI arguments.

        Args:
            args: Parsed CLI arguments

        Returns:
            CalendarISOBarBuilder instance
        """
        # Resolve database URL
        db_url = resolve_db_url(args.db_url)

        # Resolve IDs
        ids = parse_ids(args.ids)
        if ids == "all":
            ids = load_all_ids(db_url, args.daily_table)

        # Load calendar specs from dim_timeframe
        specs = cls._load_cal_specs_from_dim(db_url)

        # Create engine
        from sqlalchemy import create_engine

        engine = create_engine(db_url, future=True)

        # Ensure state table exists (calendar builders use tz column)
        ensure_state_table(db_url, args.state_table, with_tz=True)

        # Build configuration
        config = BarBuilderConfig(
            db_url=db_url,
            ids=ids,
            daily_table=args.daily_table,
            bars_table=args.bars_table,
            state_table=args.state_table,
            full_rebuild=args.full_rebuild,
            tz=args.tz if hasattr(args, "tz") else DEFAULT_TZ,
            num_processes=1,  # Calendar builders use single process for now
            log_level=getattr(args, "log_level", "INFO"),
        )

        return cls(
            config=config,
            engine=engine,
            specs=specs,
            from_1d=getattr(args, "from_1d", False),
            validate_derivation=getattr(args, "validate_derivation", False),
        )

    @classmethod
    def _load_cal_specs_from_dim(cls, db_url: str) -> list[CalSpec]:
        """
        Load calendar TF definitions from dim_timeframe.

        Filters for ISO calendar specs:
        - Weeks: tf LIKE '%_CAL_ISO' (ISO Monday-start weeks)
        - Months/Years: calendar_scheme = 'CAL'
        """
        sql = text(
            r"""
            SELECT
                tf,
                base_unit,
                tf_qty
            FROM public.dim_timeframe
            WHERE alignment_type = 'calendar'
              AND allow_partial_start = FALSE
              AND allow_partial_end = FALSE
              AND base_unit IN ('W', 'M', 'Y')
              AND is_intraday = FALSE
              AND calendar_anchor = FALSE
              AND tf NOT LIKE '%\_CAL\_ANCHOR\_%' ESCAPE '\'
              AND (
                    (base_unit = 'W' AND tf ~ '_CAL_ISO$')
                  OR (base_unit IN ('M','Y') AND tf ~ '_CAL$' AND tf !~ '_CAL_')
                )
            ORDER BY base_unit, tf_qty;
            """
        )

        eng = get_engine(db_url)
        with eng.connect() as conn:
            rows = conn.execute(sql).mappings().all()

        specs = []
        for r in rows:
            specs.append(
                CalSpec(
                    tf=str(r["tf"]),
                    unit=str(r["base_unit"]),
                    qty=int(r["tf_qty"]),
                )
            )

        if not specs:
            raise RuntimeError(
                "No calendar TFs found in dim_timeframe matching ISO filters."
            )

        return specs


# =============================================================================
# CLI Entry Point
# =============================================================================


def main(argv=None) -> None:
    """
    CLI entry point for calendar ISO bar builder.

    Usage:
        python refresh_cmc_price_bars_multi_tf_cal_iso.py --ids all
        python refresh_cmc_price_bars_multi_tf_cal_iso.py --ids 1 52 825 --full-rebuild
        python refresh_cmc_price_bars_multi_tf_cal_iso.py --ids all --from-1d
    """
    parser = CalendarISOBarBuilder.create_argument_parser()
    args = parser.parse_args(argv)
    builder = CalendarISOBarBuilder.from_cli_args(args)
    builder.run()


if __name__ == "__main__":
    main()
