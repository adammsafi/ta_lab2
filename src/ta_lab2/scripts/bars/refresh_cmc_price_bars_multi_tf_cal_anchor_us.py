from __future__ import annotations

# ruff: noqa: E402, F841
"""
US calendar-ANCHORED price bars builder (append-only DAILY SNAPSHOTS):

    public.cmc_price_bars_multi_tf_cal_anchor_us

from daily source:

    public.cmc_price_histories7

US ANCHOR SEMANTICS
-------------------
- US week start is Sunday (Sun..Sat)
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
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.base_bar_builder import BaseBarBuilder
from ta_lab2.scripts.bars.bar_builder_config import BarBuilderConfig
from ta_lab2.scripts.bars.common_snapshot_contract import (
    resolve_db_url,
    get_engine,
    parse_ids,
    load_all_ids,
    ensure_state_table,
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
DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_us"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_us_state"

# Global reference for anchored N-week grouping (Sunday)
REF_SUNDAY = date(1970, 1, 4)


# =============================================================================
# Timeframe Spec
# =============================================================================


@dataclass(frozen=True)
class TFSpec:
    tf: str
    n: int
    unit: str


# =============================================================================
# Anchored window logic (US)
# =============================================================================


def _week_num_since_ref(d: date) -> int:
    """Number of full US weeks since REF_SUNDAY."""
    delta = (d - REF_SUNDAY).days
    return delta // 7


def _anchor_window_for_day_us_week(d: date, n: int) -> tuple[date, date]:
    """Return (window_start, window_end) for US N-week anchored window containing d."""
    ref_week = _week_num_since_ref(d)
    group = ref_week // n
    first_week_in_group = group * n
    window_start = REF_SUNDAY + timedelta(weeks=first_week_in_group)
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
        return _anchor_window_for_day_us_week(d, n)
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
# AnchorCalendarUSBarBuilder - Inherits from BaseBarBuilder
# =============================================================================


class AnchorCalendarUSBarBuilder(BaseBarBuilder):
    """
    Anchor Calendar US bar builder - builds year-anchored calendar bars with US week convention.

    Anchor Semantics:
    - US weeks start on Sunday
    - Year-anchored calendar alignment
    - Partial bars allowed at year boundaries
    - Windows are calendar-defined (not data-aligned)

    Inherits shared infrastructure from BaseBarBuilder.
    """

    STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_us_state"
    OUTPUT_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_us"

    def __init__(
        self,
        config: BarBuilderConfig,
        engine: Engine,
        specs: list[TFSpec],
        from_1d: bool = False,
    ):
        """
        Initialize Anchor Calendar US bar builder.

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
            self.logger.info("Derivation mode: building from cmc_price_bars_1d")

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
        Build anchor calendar bars for one ID across all timeframe specs.

        This is the variant-specific core logic that:
        1. Optionally derives from 1D bars (if from_1d=True)
        2. Loads daily prices
        3. For each anchor spec:
           - Check for backfill
           - Full rebuild (anchor bars are complex, simplified to always rebuild)
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
            alignment, anchor_mode = BUILDER_ALIGNMENT_MAP["cal_anchor_us"]
            timeframes_list = [spec.tf for spec in self.specs]

            bars_all = derive_multi_tf_bars(
                engine=self.engine,
                id=int(id_),
                timeframes=timeframes_list,
                alignment=alignment,
                anchor_mode=anchor_mode,
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
        # For anchor builders, always load full history since we do full rebuild
        # per TF (delete + rebuild). Using start_ts would only load recent data
        # after the first run, but we need all data to build correct cumulative snapshots.

        df_daily = load_daily_prices_for_id(
            db_url=self.config.db_url,
            daily_table=self.config.daily_table,
            id_=id_,
            ts_start=None,
            tz=self.config.tz or DEFAULT_TZ,
        )

        if df_daily.empty:
            self.logger.info(f"ID={id_}: No daily data found")
            return 0

        daily_min_ts = pd.to_datetime(df_daily["ts"].min(), utc=True)
        daily_max_ts = pd.to_datetime(df_daily["ts"].max(), utc=True)

        # Look up coverage from asset_data_coverage (populated by 1D builder)
        n_available = get_coverage_n_days(
            get_engine(self.config.db_url),
            id_,
            source_table=self.config.daily_table,
            granularity="1D",
        )
        if n_available is None:
            n_available = len(df_daily)
        applicable_specs = [s for s in self.specs if _nominal_tf_days(s) <= n_available]
        skipped = len(self.specs) - len(applicable_specs)
        if skipped:
            self.logger.info(
                f"ID={id_}: Skipping {skipped} anchor spec(s) "
                f"(nominal tf_days > {n_available} available days)"
            )

        # Process each spec
        for spec in applicable_specs:
            try:
                # Simplified: Always rebuild for anchor builders
                self.logger.info(
                    f"ID={id_}, TF={spec.tf}: Building anchor bars (full rebuild)"
                )
                delete_bars_for_id_tf(
                    self.config.db_url,
                    self.get_output_table_name(),
                    id_=id_,
                    tf=spec.tf,
                )

                bars = self._build_anchor_bars_simplified(
                    df_daily, spec=spec, id_=id_, tz=self.config.tz or DEFAULT_TZ
                )

                if bars.empty:
                    continue

                upsert_bars(
                    bars,
                    db_url=self.config.db_url,
                    bars_table=self.get_output_table_name(),
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

                total_rows += len(bars)
            except Exception as e:
                self.logger.error(f"ID={id_}, TF={spec.tf} failed: {e}", exc_info=True)
                continue

        return total_rows

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
            anchor_offset = (window_start_map[bar_seq] - REF_SUNDAY).days

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
                    "src_file": "cmc_price_bars_1d",
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

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """
        Create argument parser with anchor calendar US specific arguments.

        Returns:
            ArgumentParser with all arguments configured
        """
        parser = cls.create_base_argument_parser(
            description="Build US calendar-anchored price bars into cmc_price_bars_multi_tf_cal_anchor_us.",
            default_daily_table=DEFAULT_DAILY_TABLE,
            default_bars_table=DEFAULT_BARS_TABLE,
            default_state_table=DEFAULT_STATE_TABLE,
            include_tz=True,
            default_tz=DEFAULT_TZ,
        )

        # Anchor US specific arguments
        parser.add_argument(
            "--from-1d",
            action="store_true",
            help="Derive multi-TF bars from cmc_price_bars_1d instead of price_histories7",
        )

        return parser

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "AnchorCalendarUSBarBuilder":
        """
        Factory method: Create builder from CLI arguments.

        Args:
            args: Parsed CLI arguments

        Returns:
            AnchorCalendarUSBarBuilder instance
        """
        # Resolve database URL
        db_url = resolve_db_url(args.db_url)

        # Resolve IDs
        ids = parse_ids(args.ids)
        if ids == "all":
            ids = load_all_ids(db_url, args.daily_table)

        # Load anchor specs from dim_timeframe
        specs = cls._load_anchor_specs_from_dim(db_url)

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
              (base_unit = 'W' AND calendar_scheme = 'US' AND tf LIKE '%_CAL_ANCHOR_US')
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
    CLI entry point for anchor calendar US bar builder.

    Usage:
        python refresh_cmc_price_bars_multi_tf_cal_anchor_us.py --ids all
        python refresh_cmc_price_bars_multi_tf_cal_anchor_us.py --ids 1 52 825 --full-rebuild
        python refresh_cmc_price_bars_multi_tf_cal_anchor_us.py --ids all --from-1d
    """
    parser = AnchorCalendarUSBarBuilder.create_argument_parser()
    args = parser.parse_args(argv)
    builder = AnchorCalendarUSBarBuilder.from_cli_args(args)
    builder.run()


if __name__ == "__main__":
    main()
