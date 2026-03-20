from __future__ import annotations

# ruff: noqa: E402, F841
"""
ISO calendar-ANCHORED price bars builder (append-only DAILY SNAPSHOTS):

    public.price_bars_multi_tf_cal_anchor_iso

from daily source:

    public.cmc_price_histories7

ISO ANCHOR SEMANTICS
--------------------
- ISO week start is Monday (Mon..Sun)
- Anchored windows are calendar-defined (NOT data-aligned)
- Partial bars allowed at BOTH ends for *_CAL_ANCHOR_* families
- tf_days is the underlying window width (calendar days), regardless of partial start
- Missing-days detection computed within [bar_start_effective .. snapshot_day]

REFACTORED (24-04): Now uses BaseBarBuilder template method pattern.
"""

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.base_bar_builder import BaseBarBuilder
from ta_lab2.scripts.bars.bar_builder_config import BarBuilderConfig
from ta_lab2.scripts.bars.common_snapshot_contract import (
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
    get_coverage_n_days,
)
from ta_lab2.scripts.bars.derive_multi_tf_from_1d import (
    derive_multi_tf_bars,
    BUILDER_ALIGNMENT_MAP,
)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_TZ = "America/New_York"
DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_BARS_TABLE = "public.price_bars_multi_tf_cal_anchor_iso"
DEFAULT_STATE_TABLE = "public.price_bars_multi_tf_cal_anchor_iso_state"

# Global reference for anchored N-week grouping (ISO Monday)
REF_MONDAY_ISO = date(1970, 1, 5)


# =============================================================================
# Timeframe Spec
# =============================================================================


@dataclass(frozen=True)
class TFSpec:
    tf: str
    n: int
    unit: str


# =============================================================================
# Anchored window logic (ISO)
# =============================================================================


def _week_num_since_ref_iso(d: date) -> int:
    """Number of full ISO weeks since REF_MONDAY_ISO."""
    delta = (d - REF_MONDAY_ISO).days
    return delta // 7


def _anchor_window_for_day_iso_week(d: date, n: int) -> tuple[date, date]:
    """Return (window_start, window_end) for ISO N-week anchored window containing d."""
    ref_week = _week_num_since_ref_iso(d)
    group = ref_week // n
    first_week_in_group = group * n
    window_start = REF_MONDAY_ISO + timedelta(weeks=first_week_in_group)
    window_end = window_start + timedelta(weeks=n) - timedelta(days=1)
    return (window_start, window_end)


def _anchor_window_for_day_month(d: date, n: int) -> tuple[date, date]:
    """Return (window_start, window_end) for N-month anchored window containing d."""
    year = d.year
    month = d.month
    group = (month - 1) // n
    first_month = group * n + 1
    window_start = date(year, first_month, 1)

    last_month = first_month + n - 1
    if last_month > 12:
        year += 1
        last_month -= 12

    next_month = last_month + 1
    next_year = year
    if next_month > 12:
        next_year += 1
        next_month = 1

    window_end = date(next_year, next_month, 1) - timedelta(days=1)
    return (window_start, window_end)


def _anchor_window_for_day_year(d: date, n: int) -> tuple[date, date]:
    """Return (window_start, window_end) for N-year anchored window containing d."""
    year = d.year
    group = year // n
    first_year = group * n
    window_start = date(first_year, 1, 1)
    window_end = date(first_year + n, 1, 1) - timedelta(days=1)
    return (window_start, window_end)


def _anchor_window_for_day(d: date, n: int, unit: str) -> tuple[date, date]:
    """Dispatch to appropriate window function."""
    if unit == "W":
        return _anchor_window_for_day_iso_week(d, n)
    elif unit == "M":
        return _anchor_window_for_day_month(d, n)
    elif unit == "Y":
        return _anchor_window_for_day_year(d, n)
    else:
        raise ValueError(f"Unknown unit: {unit}")


def _nominal_tf_days(spec: TFSpec) -> int:
    """Approximate minimum calendar days needed for one window of the given spec."""
    if spec.unit == "W":
        return spec.n * 7
    if spec.unit == "M":
        return spec.n * 28
    if spec.unit == "Y":
        return spec.n * 365
    return 1


# =============================================================================
# AnchorCalendarISOBarBuilder - Inherits from BaseBarBuilder
# =============================================================================


class AnchorCalendarISOBarBuilder(BaseBarBuilder):
    """
    Anchor Calendar ISO bar builder - builds year-anchored calendar bars with ISO week convention.

    Anchor Semantics:
    - ISO weeks start on Monday
    - Year-anchored calendar alignment
    - Partial bars allowed at year boundaries
    - Windows are calendar-defined (not data-aligned)

    Inherits shared infrastructure from BaseBarBuilder.
    """

    STATE_TABLE = "public.price_bars_multi_tf_cal_anchor_iso_state"
    OUTPUT_TABLE = "public.price_bars_multi_tf_cal_anchor_iso"

    def __init__(
        self,
        config: BarBuilderConfig,
        engine: Engine,
        specs: list[TFSpec],
        from_1d: bool = False,
    ):
        """
        Initialize Anchor Calendar ISO bar builder.

        Args:
            config: Bar builder configuration
            engine: SQLAlchemy engine
            specs: List of TFSpec timeframe specifications
            from_1d: Derive from 1D bars instead of daily prices
        """
        super().__init__(config, engine)
        self.specs = specs
        self.from_1d = from_1d

        self.logger.info(f"Loaded {len(specs)} anchor specs: {[s.tf for s in specs]}")
        if from_1d:
            self.logger.info("Derivation mode: building from price_bars_1d")

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
        Build anchor calendar bars for one ID across all timeframe specs and venues.

        This is the variant-specific core logic that:
        1. Optionally derives from 1D bars (if from_1d=True)
        2. Loads daily prices (all venues)
        3. For each venue:
           a. For each anchor spec:
              - Full rebuild (anchor bars always rebuild)
              - Upsert bars and update state

        Args:
            id_: Cryptocurrency ID
            start_ts: Optional start timestamp (for incremental)

        Returns:
            Total number of rows inserted/updated across all specs and venues
        """
        total_rows = 0

        # Derivation mode (from 1D bars)
        if self.from_1d:
            alignment, anchor_mode = BUILDER_ALIGNMENT_MAP["cal_anchor_iso"]
            timeframes_list = [spec.tf for spec in self.specs]

            bars_all = derive_multi_tf_bars(
                engine=self.engine,
                id=int(id_),
                timeframes=timeframes_list,
                alignment=alignment,
                anchor_mode=anchor_mode,
            )

            # Delete existing bars for this ID then insert derived bars
            # (from_1d always does full history; avoids partial unique index conflicts)
            if not bars_all.is_empty():
                bars_pd = bars_all.to_pandas()
                eng = get_engine(self.config.db_url)
                with eng.begin() as conn:
                    conn.execute(
                        text(
                            f"DELETE FROM {self.get_output_table_name()} WHERE id = :id"
                        ),
                        {"id": int(id_)},
                    )
                upsert_bars(
                    bars_pd,
                    db_url=self.config.db_url,
                    bars_table=self.get_output_table_name(),
                    conflict_cols=("id", "tf", "bar_seq", "venue_id", "timestamp"),
                )
                total_rows += len(bars_pd)

                # Update state per (tf, venue_id)
                if "venue_id" in bars_pd.columns:
                    venue_groups = bars_pd.groupby("venue_id")
                else:
                    bars_pd = bars_pd.assign(venue_id=1, venue="CMC_AGG")
                    venue_groups = bars_pd.groupby("venue_id")
                for vid, venue_bars in venue_groups:
                    venue_name = (
                        venue_bars["venue"].iloc[0]
                        if "venue" in venue_bars.columns
                        else "CMC_AGG"
                    )
                    for spec in self.specs:
                        spec_bars = venue_bars[venue_bars["tf"] == spec.tf]
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
                                        "venue_id": int(vid),
                                        "venue": venue_name,
                                        "tz": self.config.tz,
                                        "daily_min_seen": daily_min_ts,
                                        "daily_max_seen": daily_max_ts,
                                        "last_bar_seq": last_bar_seq,
                                        "last_time_close": last_time_close,
                                    }
                                ],
                                with_tz=True,
                                with_venue=True,
                            )

            return total_rows

        # Direct mode (from daily prices)
        # Load existing state for all (tf, venue) combos BEFORE daily data load
        # so we can detect new TFs and override start_ts if needed.
        state_df = load_state(
            self.config.db_url,
            self.get_state_table_name(),
            [id_],
            with_tz=True,
            with_venue=True,
        )

        # State map keyed by (tf, venue)
        state_map: dict[tuple[str, str], dict] = {}
        if not state_df.empty:
            for _, row in state_df.iterrows():
                state_map[(row["tf"], row.get("venue", "CMC_AGG"))] = row

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
                f"ID={id_}: Skipping {skipped} anchor spec(s) "
                f"(nominal tf_days > {n_available} available days)"
            )

        # For anchor builders, always load full history since we do full rebuild
        # per TF (delete + rebuild). Using start_ts would only load recent data
        # after the first run, but we need all data to build correct cumulative snapshots.
        df_all = load_daily_prices_for_id(
            db_url=self.config.db_url,
            daily_table=self.config.daily_table,
            id_=id_,
            ts_start=None,
            tz=self.config.tz or DEFAULT_TZ,
        )

        if df_all.empty:
            self.logger.info(f"ID={id_}: No daily data found")
            return 0

        # Get unique venues
        venues = df_all["venue"].unique() if "venue" in df_all.columns else ["CMC_AGG"]

        for venue in venues:
            if "venue" in df_all.columns:
                df_daily = df_all[df_all["venue"] == venue].copy()
            else:
                df_daily = df_all.copy()

            if df_daily.empty:
                continue

            venue_rank = (
                int(df_daily["venue_rank"].iloc[0])
                if "venue_rank" in df_daily.columns
                else 50
            )
            daily_min_ts = pd.to_datetime(df_daily["ts"].min(), utc=True)
            daily_max_ts = pd.to_datetime(df_daily["ts"].max(), utc=True)

            # Process each spec for this venue
            for spec in applicable_specs:
                try:
                    rows = self._build_bars_for_id_tf(
                        id_=id_,
                        spec=spec,
                        df_daily=df_daily,
                        daily_min_ts=daily_min_ts,
                        daily_max_ts=daily_max_ts,
                        state=state_map.get((spec.tf, venue)),
                        venue=venue,
                        venue_rank=venue_rank,
                    )
                    total_rows += rows
                except Exception as e:
                    self.logger.error(
                        f"ID={id_}, TF={spec.tf}, venue={venue} failed: {e}",
                        exc_info=True,
                    )
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

    def _build_bars_for_id_tf(
        self,
        id_: int,
        spec: TFSpec,
        df_daily: pd.DataFrame,
        daily_min_ts: pd.Timestamp,
        daily_max_ts: pd.Timestamp,
        state: Optional[dict],
        venue: str = "CMC_AGG",
        venue_rank: int = 50,
    ) -> int:
        """
        Build bars for one (id, spec, venue) combination.

        Anchor bars always do a full rebuild (delete + rebuild) because
        anchor window logic requires the full history for correct cumulative snapshots.

        Returns:
            Number of rows inserted/updated
        """
        self.logger.info(
            f"ID={id_}, TF={spec.tf}, venue={venue}: Building anchor bars (full rebuild)"
        )
        self._delete_bars_and_state(id_, spec.tf, venue=venue)

        bars = self._build_anchor_bars_simplified(
            df_daily, spec=spec, id_=id_, tz=self.config.tz or DEFAULT_TZ
        )

        if bars.empty:
            return 0

        # Set venue columns on output bars
        bars["venue"] = venue
        bars["venue_rank"] = venue_rank

        upsert_bars(
            bars,
            db_url=self.config.db_url,
            bars_table=self.get_output_table_name(),
        )
        self._update_state(id_, spec.tf, bars, daily_min_ts, daily_max_ts, venue=venue)
        return len(bars)

    def _build_anchor_bars_simplified(
        self,
        df_daily: pd.DataFrame,
        spec: TFSpec,
        id_: int,
        tz: str,
    ) -> pd.DataFrame:
        """
        Build anchor bars with simplified logic.

        For anchor bars:
        - Use anchor window logic to determine bar boundaries
        - Allow partial bars at both ends
        - Emit one row per day (append-only snapshots)
        """
        if df_daily.empty:
            return pd.DataFrame()

        df = df_daily.sort_values("ts").reset_index(drop=True).copy()

        # Convert to local timezone for calendar math
        df["ts_local"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(tz)
        df["day_local"] = df["ts_local"].dt.date

        # Assign bar_seq based on anchor windows
        bar_seqs = []
        window_widths = []  # calendar window width in days
        bar_seq_map = {}  # (window_start, window_end) -> bar_seq
        window_width_map = {}  # bar_seq -> calendar window width
        window_end_map = {}  # bar_seq -> window_end date
        window_start_map = {}  # bar_seq -> window_start date
        current_bar_seq = 1

        for day_local in df["day_local"]:
            window_start, window_end = _anchor_window_for_day(
                day_local, spec.n, spec.unit
            )
            window_key = (window_start, window_end)

            if window_key not in bar_seq_map:
                bar_seq_map[window_key] = current_bar_seq
                window_width_map[current_bar_seq] = (window_end - window_start).days + 1
                window_end_map[current_bar_seq] = window_end
                window_start_map[current_bar_seq] = window_start
                current_bar_seq += 1

            bar_seqs.append(bar_seq_map[window_key])

        df["bar_seq"] = bar_seqs

        # Build bars by aggregating within bar_seq
        rows = []
        max_data_ts = df["ts"].max()  # Latest data date for partial start/end detection
        prev_ts = None  # Track previous row's ts for per-row time_open
        for bar_seq in sorted(df["bar_seq"].unique()):
            bar_df = df[df["bar_seq"] == bar_seq].copy()
            tf_days = window_width_map[bar_seq]
            anchor_offset = (window_start_map[bar_seq] - REF_MONDAY_ISO).days

            # Determine if bar window has ended (data exists beyond window_end)
            bar_end = window_end_map[bar_seq]
            time_close_ts = pd.Timestamp(bar_end, tz="UTC") + pd.Timedelta(
                hours=23, minutes=59, seconds=59, milliseconds=999
            )
            bar_window_ended = max_data_ts >= time_close_ts

            # Partial start: fewer data rows than window width, but window has ended
            is_partial_start_bar = (len(bar_df) < tf_days) and bar_window_ended

            # Expected total data rows for this bar
            expected_total = len(bar_df) if bar_window_ended else tf_days

            # For each day in this bar, create a snapshot row
            for idx, day_row in bar_df.iterrows():
                # Get all data up to and including this day
                snapshot_df = bar_df[bar_df.index <= idx]

                # Per-row time_open = previous row's ts + 1ms
                if prev_ts is not None:
                    row_time_open = prev_ts + pd.Timedelta(milliseconds=1)
                else:
                    # First row: ts - 1 day + 1ms
                    row_time_open = (
                        day_row["ts"]
                        - pd.Timedelta(days=1)
                        + pd.Timedelta(milliseconds=1)
                    )

                row = {
                    "id": int(id_),
                    "tf": spec.tf,
                    "tf_days": tf_days,
                    "bar_seq": int(bar_seq),
                    "bar_anchor_offset": int(anchor_offset),
                    "time_open": row_time_open,
                    "time_open_bar": pd.Timestamp(window_start_map[bar_seq], tz="UTC"),
                    "time_close": day_row["ts"],
                    "time_close_bar": time_close_ts,
                    "time_high": snapshot_df.loc[
                        snapshot_df["high"].idxmax(), "timehigh"
                    ]
                    if pd.notna(snapshot_df["high"].max())
                    else None,
                    "time_low": snapshot_df.loc[snapshot_df["low"].idxmin(), "timelow"]
                    if pd.notna(snapshot_df["low"].min())
                    else None,
                    "open": float(snapshot_df["open"].iloc[0]),
                    "high": float(snapshot_df["high"].max()),
                    "low": float(snapshot_df["low"].min()),
                    "close": float(day_row["close"]),
                    "volume": float(snapshot_df["volume"].sum()),
                    "market_cap": float(day_row["market_cap"])
                    if pd.notna(day_row["market_cap"])
                    else None,
                    "timestamp": day_row["ts"],
                    "last_ts_half_open": day_row["ts"] + pd.Timedelta(milliseconds=1),
                    "pos_in_bar": len(snapshot_df),
                    "is_partial_start": is_partial_start_bar,
                    "is_partial_end": len(snapshot_df) < expected_total,
                    "count_days_remaining": expected_total - len(snapshot_df),
                    "is_missing_days": False,  # Simplified
                    "count_days": len(snapshot_df),
                    "count_missing_days": 0,  # Simplified
                    "first_missing_day": None,
                    "last_missing_day": None,
                    "src_name": day_row.get("src_name"),
                    "src_load_ts": day_row.get("src_load_ts"),
                    "src_file": "price_bars_1d",
                }

                rows.append(row)
                prev_ts = day_row["ts"]

        if not rows:
            return pd.DataFrame()

        out = pd.DataFrame(rows)

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

    # =========================================================================
    # Helper methods (venue-aware)
    # =========================================================================

    def _load_last_snapshot_info(
        self, id_: int, tf: str, venue: str = "CMC_AGG"
    ) -> dict | None:
        """Load last snapshot info for (id, tf, venue)."""
        engine = get_engine(self.config.db_url)
        bars_table = self.get_output_table_name()

        with engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        f"""
                    WITH last AS (
                      SELECT id, tf, venue, MAX(bar_seq) AS last_bar_seq
                      FROM {bars_table}
                      WHERE id = :id AND tf = :tf AND venue = :venue
                      GROUP BY id, tf, venue
                    ),
                    last_row AS (
                      SELECT b.*
                      FROM {bars_table} b
                      JOIN last l
                        ON b.id = l.id AND b.tf = l.tf AND b.venue = l.venue
                           AND b.bar_seq = l.last_bar_seq
                      ORDER BY b.timestamp DESC
                      LIMIT 1
                    ),
                    pos AS (
                      SELECT COUNT(*)::int AS last_pos_in_bar
                      FROM {bars_table} b
                      JOIN last l
                        ON b.id = l.id AND b.tf = l.tf AND b.venue = l.venue
                           AND b.bar_seq = l.last_bar_seq
                    )
                    SELECT
                      (SELECT last_bar_seq FROM last) AS last_bar_seq,
                      (SELECT timestamp FROM last_row) AS last_time_close,
                      (SELECT last_pos_in_bar FROM pos) AS last_pos_in_bar;
                    """
                    ),
                    {"id": int(id_), "tf": tf, "venue": venue},
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        d = dict(row)
        # If no bars exist yet, all values are None - treat as no data
        if d.get("last_bar_seq") is None:
            return None
        return d

    def _delete_bars_and_state(
        self, id_: int, tf: str, venue: str | None = None
    ) -> None:
        """Delete bars and state for (id, tf, venue) before rebuild."""
        delete_bars_for_id_tf(
            self.config.db_url,
            self.get_output_table_name(),
            id_=id_,
            tf=tf,
            venue=venue,
        )

        # Delete state
        engine = create_engine(self.config.db_url, future=True)
        params: dict = {"id": int(id_), "tf": tf}
        where = "WHERE id = :id AND tf = :tf"
        if venue is not None:
            where += " AND venue = :venue"
            params["venue"] = venue
        q = text(f"DELETE FROM {self.get_state_table_name()} {where};")
        with engine.begin() as conn:
            conn.execute(q, params)

    def _update_state(
        self,
        id_: int,
        tf: str,
        bars: pd.DataFrame,
        daily_min_ts: pd.Timestamp,
        daily_max_ts: pd.Timestamp,
        venue: str = "CMC_AGG",
        venue_id: int | None = None,
    ) -> None:
        """Update state table for (id, tf, venue_id)."""
        if venue_id is None:
            venue_id = self._resolve_venue_id(venue)
        last_bar_seq = int(bars["bar_seq"].max())
        last_time_close = pd.to_datetime(bars["timestamp"].max(), utc=True)

        upsert_state(
            self.config.db_url,
            self.get_state_table_name(),
            [
                {
                    "id": int(id_),
                    "tf": tf,
                    "venue_id": int(venue_id),
                    "venue": venue,
                    "daily_min_seen": daily_min_ts,
                    "daily_max_seen": daily_max_ts,
                    "last_bar_seq": last_bar_seq,
                    "last_time_close": last_time_close,
                    "tz": self.config.tz,
                }
            ],
            with_tz=True,
            with_venue=True,
        )

    def _resolve_venue_id(self, venue: str) -> int:
        """Resolve venue text to venue_id from dim_venues."""
        engine = get_engine(self.config.db_url)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT venue_id FROM dim_venues WHERE venue = :v"),
                {"v": venue},
            ).fetchone()
        if row:
            return int(row[0])
        return 1  # default to CMC_AGG

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """
        Create argument parser with anchor calendar ISO specific arguments.

        Returns:
            ArgumentParser with all arguments configured
        """
        parser = cls.create_base_argument_parser(
            description="Build ISO calendar-anchored price bars into price_bars_multi_tf_cal_anchor_iso.",
            default_daily_table=DEFAULT_DAILY_TABLE,
            default_bars_table=DEFAULT_BARS_TABLE,
            default_state_table=DEFAULT_STATE_TABLE,
            include_tz=True,
            default_tz=DEFAULT_TZ,
        )

        # Anchor ISO specific arguments
        parser.add_argument(
            "--from-1d",
            action="store_true",
            help="Derive multi-TF bars from price_bars_1d instead of price_histories7",
        )

        return parser

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "AnchorCalendarISOBarBuilder":
        """
        Factory method: Create builder from CLI arguments.

        Args:
            args: Parsed CLI arguments

        Returns:
            AnchorCalendarISOBarBuilder instance
        """
        # Resolve database URL
        db_url = resolve_db_url(args.db_url)

        # When deriving from 1D bars, load IDs from price_bars_1d (all venues)
        from_1d = getattr(args, "from_1d", False)
        id_source_table = "public.price_bars_1d" if from_1d else args.daily_table

        # Resolve IDs
        ids = parse_ids(args.ids)
        if ids == "all":
            ids = load_all_ids(db_url, id_source_table)

        # Load anchor specs from dim_timeframe
        specs = cls._load_anchor_specs_from_dim(db_url)

        # Create engine
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
            num_processes=1,  # Anchor builders use single process for now
            log_level=getattr(args, "log_level", "INFO"),
        )

        return cls(
            config=config,
            engine=engine,
            specs=specs,
            from_1d=getattr(args, "from_1d", False),
        )

    @classmethod
    def _load_anchor_specs_from_dim(cls, db_url: str) -> list[TFSpec]:
        """Load anchored week/month/year specs from dim_timeframe."""
        sql = text(
            """
          SELECT tf, tf_qty AS n, base_unit AS unit
          FROM public.dim_timeframe
          WHERE alignment_type = 'calendar'
            AND roll_policy = 'calendar_anchor'
            AND allow_partial_start = TRUE
            AND allow_partial_end = TRUE
            AND base_unit IN ('W','M','Y')
            AND (
              (base_unit = 'W' AND calendar_scheme = 'ISO' AND tf LIKE '%_CAL_ANCHOR_ISO')
              OR (base_unit IN ('M','Y') AND tf LIKE '%_CAL_ANCHOR%')
            )
          ORDER BY
            CASE base_unit
              WHEN 'W' THEN 1
              WHEN 'M' THEN 2
              WHEN 'Y' THEN 3
            END,
            tf_qty;
        """
        )

        eng = get_engine(db_url)
        with eng.connect() as conn:
            rows = conn.execute(sql).fetchall()

        specs = []
        for r in rows:
            tf = str(r[0])
            n = int(r[1])
            unit = str(r[2])
            specs.append(TFSpec(tf=tf, n=n, unit=unit))

        if not specs:
            raise RuntimeError("No anchor specs found in dim_timeframe.")

        return specs


# =============================================================================
# CLI Entry Point
# =============================================================================


def main(argv=None) -> None:
    """
    CLI entry point for anchor calendar ISO bar builder.

    Usage:
        python refresh_price_bars_multi_tf_cal_anchor_iso.py --ids all
        python refresh_price_bars_multi_tf_cal_anchor_iso.py --ids 1 52 825 --full-rebuild
        python refresh_price_bars_multi_tf_cal_anchor_iso.py --ids all --from-1d
    """
    parser = AnchorCalendarISOBarBuilder.create_argument_parser()
    args = parser.parse_args(argv)
    builder = AnchorCalendarISOBarBuilder.from_cli_args(args)
    builder.run()


if __name__ == "__main__":
    main()
