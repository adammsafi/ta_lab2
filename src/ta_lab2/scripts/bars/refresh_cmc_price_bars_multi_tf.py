"""
Build tf_days-count "bar-state snapshots" into public.cmc_price_bars_multi_tf from public.cmc_price_histories7.

UPDATED SEMANTICS (append-only snapshots):
- For each (id, tf, bar_seq), emit ONE ROW PER DAILY CLOSE as the bar forms.
- The same bar_seq will therefore appear multiple times with different time_close values.
- is_partial_end = TRUE for in-progress snapshots (bar not yet complete).
- The snapshot where the bar completes (pos == tf_days) is_partial_end = FALSE.

Bar definition:
- tf_day style, row-count anchored to the FIRST available daily row per id (data-start anchoring).
- bar_seq increments every tf_days daily rows.
- There is ALWAYS a trailing partial bar if the series ends mid-bar (and it will have is_partial_end=TRUE).

INCREMENTAL (default):
- Backfill detection: if daily_min decreases vs stored state, rebuild that (id, tf) from scratch.
- Otherwise, append new snapshot rows for new daily closes after the last snapshot time_close.

PERF UPGRADES:
- Full-build snapshots are vectorized with Polars (20-30% faster than pandas for large datasets).
- Optionally parallelize incremental refresh across IDs with --num-processes.
- Batch-load last snapshot info for (id, all tfs) in one query per id.

CONTRACT GUARANTEES (mechanics only; semantics remain in this file):
- Enforce 1 row per local day in base daily data.
- Deterministic time_high/time_low tie-breaks (earliest timestamp among ties), with fallback to ts when timehigh/timelow is missing.
- Optional O(1) carry-forward update in incremental path when strict gate passes.

DATA QUALITY FIX (parity with prior script behavior):
- If computed time_low is AFTER time_close for a snapshot:
    set low = min(open, close)
    set time_low = time_open if open<=close else time_close
- Enforce OHLC sanity:
    - high >= max(open, close) (and if high is NaN, set to that)
    - low  <= min(open, close) (and if low is NaN or forced down, set time_low to endpoint consistently)

NOTES ON CONTRACT FIELDS:
- 'roll' is NOT a stored field (preview is implicit via is_partial_end / count_days_remaining).
- Contract-required columns (timestamp, last_ts_half_open, pos_in_bar, first_missing_day, last_missing_day)
  are emitted here (first/last missing day are left as NaT unless you later choose to compute them).

REFACTORED (24-03): Now uses BaseBarBuilder template method pattern for 70% LOC reduction.
"""

from __future__ import annotations

import argparse
import re
from typing import Optional

import numpy as np
import pandas as pd
import polars as pl
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.base_bar_builder import BaseBarBuilder
from ta_lab2.scripts.bars.bar_builder_config import BarBuilderConfig
from ta_lab2.scripts.bars.polars_bar_operations import (
    normalize_timestamps_for_polars,
    apply_standard_polars_pipeline,
    restore_utc_timezone,
    compact_output_types,
)
from ta_lab2.scripts.bars.common_snapshot_contract import (
    # Contract/invariants + shared snapshot mechanics
    assert_one_row_per_local_day,
    CarryForwardInputs,
    can_carry_forward,
    apply_carry_forward,
    compute_missing_days_diagnostics,
    normalize_output_schema,
    # Shared DB + IO plumbing
    resolve_db_url,
    get_engine,
    parse_ids,
    load_all_ids,
    load_state,
    upsert_state,
    resolve_num_processes,
    # Shared write pipeline
    upsert_bars,
    enforce_ohlc_sanity,
    # Bar builder DB utilities
    load_daily_prices_for_id,
    delete_bars_for_id_tf,
    create_rejects_table_ddl,
    # Coverage table
    get_coverage_n_days,
)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_state"
DEFAULT_TZ = "America/New_York"
_ONE_MS = pd.Timedelta(milliseconds=1)

# Module-level state for reject logging (set by main())
_KEEP_REJECTS = False
_REJECTS_TABLE = None
_DB_URL = None

# TF selection regex
_TF_DAY_LABEL_RE = re.compile(r"^\d+D$")


# =============================================================================
# MultiTFBarBuilder - Inherits from BaseBarBuilder
# =============================================================================


class MultiTFBarBuilder(BaseBarBuilder):
    """
    Multi-TF Bar Builder - builds multi-timeframe snapshot bars.

    Supports tf_day family timeframes (2D, 3D, 5D, 7D, 14D, etc.)
    Uses Polars for 20-30% performance improvement.
    Supports carry-forward optimization for strict snapshot gates.
    Inherits shared infrastructure from BaseBarBuilder.

    Variant-specific behavior:
    - State table has (id, tf) PRIMARY KEY (not just id like 1D builder)
    - Loads multiple timeframes from dim_timeframe
    - Processes each (id, tf) combination independently
    - Supports backfill detection per (id, tf)
    """

    STATE_TABLE = "public.cmc_price_bars_multi_tf_state"
    OUTPUT_TABLE = "public.cmc_price_bars_multi_tf"

    def __init__(
        self,
        config: BarBuilderConfig,
        engine: Engine,
        timeframes: list[tuple[int, str]],
    ):
        """
        Initialize Multi-TF bar builder.

        Args:
            config: Bar builder configuration
            engine: SQLAlchemy engine
            timeframes: List of (tf_days, tf_label) tuples (e.g., [(7, "7D"), (14, "14D")])
        """
        super().__init__(config, engine)
        self.timeframes = timeframes
        self.logger.info(
            f"Loaded {len(timeframes)} timeframes: {[tf for _, tf in timeframes]}"
        )

    # =========================================================================
    # Abstract method implementations (required by BaseBarBuilder)
    # =========================================================================

    def get_state_table_name(self) -> str:
        """Return state table name (uses tf column)."""
        return self.STATE_TABLE

    def get_output_table_name(self) -> str:
        """Return output bars table name."""
        return self.OUTPUT_TABLE

    def get_source_query(
        self, id_: int, start_ts: Optional[str] = None, **kwargs
    ) -> str:
        """
        Return SQL query to load daily prices for one ID.

        This is the standard daily price query - timeframe logic is applied later
        in build_bars_for_id().

        Args:
            id_: Cryptocurrency ID
            start_ts: Optional start timestamp for incremental refresh
            **kwargs: Additional arguments (unused, for signature compatibility)

        Returns:
            SQL query string to load daily price data
        """
        # Use the standard daily price loader query structure
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
        Build bars for one ID across all timeframes.

        This is the variant-specific core logic that:
        1. Loads daily prices
        2. For each timeframe:
           - Check for backfill
           - Full rebuild or incremental append
           - Upsert bars and update state

        Args:
            id_: Cryptocurrency ID
            start_ts: Optional start timestamp (for incremental)

        Returns:
            Total number of rows inserted/updated across all timeframes
        """
        total_rows = 0

        # Load daily price data
        df_daily = load_daily_prices_for_id(
            db_url=self.config.db_url,
            daily_table=self.config.daily_table,
            id_=id_,
            ts_start=start_ts,
        )

        if df_daily.empty:
            self.logger.info(f"ID={id_}: No daily data found")
            return 0

        daily_min_ts = pd.to_datetime(df_daily["ts"].min(), utc=True)
        daily_max_ts = pd.to_datetime(df_daily["ts"].max(), utc=True)

        # Load existing state for all timeframes
        state_df = load_state(
            self.config.db_url,
            self.get_state_table_name(),
            [id_],
            with_tz=False,
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
            # No coverage record yet – fall back to COUNT query
            n_available = self._count_total_daily_rows(id_)
        applicable_tfs = [
            (d, label) for d, label in self.timeframes if d <= n_available
        ]
        skipped = len(self.timeframes) - len(applicable_tfs)
        if skipped:
            self.logger.info(
                f"ID={id_}: Skipping {skipped} timeframe(s) "
                f"(tf_days > {n_available} available days)"
            )

        # Process each timeframe
        for tf_days, tf_label in applicable_tfs:
            try:
                rows = self._build_bars_for_id_tf(
                    id_=id_,
                    tf_days=tf_days,
                    tf_label=tf_label,
                    df_daily=df_daily,
                    daily_min_ts=daily_min_ts,
                    daily_max_ts=daily_max_ts,
                    state=state_map.get(tf_label),
                )
                total_rows += rows
            except Exception as e:
                self.logger.error(f"ID={id_}, TF={tf_label} failed: {e}", exc_info=True)
                continue

        return total_rows

    def _build_bars_for_id_tf(
        self,
        id_: int,
        tf_days: int,
        tf_label: str,
        df_daily: pd.DataFrame,
        daily_min_ts: pd.Timestamp,
        daily_max_ts: pd.Timestamp,
        state: Optional[dict],
    ) -> int:
        """
        Build bars for one (id, tf) combination.

        Handles:
        - Backfill detection
        - Full rebuild vs incremental append
        - State updates

        Returns:
            Number of rows inserted/updated
        """
        # Load last snapshot info
        last = self._load_last_snapshot_info(id_, tf_label)

        # Determine if backfill is needed
        needs_rebuild = False
        if state is not None:
            daily_min_seen = pd.to_datetime(state.get("daily_min_seen"), utc=True)
            if pd.notna(daily_min_seen) and daily_min_ts < daily_min_seen:
                self.logger.info(
                    f"ID={id_}, TF={tf_label}: Backfill detected "
                    f"({daily_min_seen} -> {daily_min_ts}), rebuilding"
                )
                needs_rebuild = True

        # Full rebuild path
        if needs_rebuild or last is None or self.config.full_rebuild:
            if needs_rebuild or self.config.full_rebuild:
                self._delete_bars_and_state(id_, tf_label)

            bars = self._build_snapshots_polars(df_daily, tf_days, tf_label)
            if bars.empty:
                return 0

            self._upsert_bars(bars)
            self._update_state(id_, tf_label, bars, daily_min_ts, daily_max_ts)
            return len(bars)

        # Incremental append path
        if (
            last["last_time_close"] is not None
            and daily_max_ts <= last["last_time_close"]
        ):
            # No new data
            return 0

        new_rows = self._append_incremental_rows(
            id_=id_,
            tf_days=tf_days,
            tf_label=tf_label,
            daily_max_ts=daily_max_ts,
            last=last,
        )

        if new_rows.empty:
            return 0

        self._upsert_bars(new_rows)
        self._update_state(id_, tf_label, new_rows, daily_min_ts, daily_max_ts)
        return len(new_rows)

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """
        Create argument parser with multi-TF specific arguments.

        Returns:
            ArgumentParser with all arguments configured
        """
        parser = cls.create_base_argument_parser(
            description="Build tf_day (multi_tf) price bars (append-only snapshots).",
            default_daily_table=DEFAULT_DAILY_TABLE,
            default_bars_table=DEFAULT_BARS_TABLE,
            default_state_table=DEFAULT_STATE_TABLE,
            include_tz=False,
        )

        # Multi-TF specific arguments
        parser.add_argument(
            "--include-non-canonical",
            action="store_true",
            help="Include non-canonical timeframes from dim_timeframe",
        )
        parser.add_argument(
            "--keep-rejects",
            action="store_true",
            help="Log OHLC violations to rejects table before repair",
        )
        parser.add_argument(
            "--rejects-table",
            default="cmc_price_bars_multi_tf_rejects",
            help="Table name for rejects (default: cmc_price_bars_multi_tf_rejects)",
        )

        return parser

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "MultiTFBarBuilder":
        """
        Factory method: Create builder from CLI arguments.

        Args:
            args: Parsed CLI arguments

        Returns:
            MultiTFBarBuilder instance
        """
        # Resolve database URL
        db_url = resolve_db_url(args.db_url)

        # Resolve IDs
        ids = parse_ids(args.ids)
        if ids == "all":
            ids = load_all_ids(db_url, args.daily_table)

        # Load timeframes from dim_timeframe
        timeframes = cls._load_timeframes_from_dim(
            db_url=db_url,
            include_non_canonical=args.include_non_canonical,
        )

        # Create engine
        engine = create_engine(db_url, future=True)

        # Set module-level state for reject logging
        global _KEEP_REJECTS, _REJECTS_TABLE, _DB_URL
        _KEEP_REJECTS = args.keep_rejects
        _REJECTS_TABLE = args.rejects_table
        _DB_URL = db_url

        # Create rejects table if needed
        if args.keep_rejects:
            ddl = create_rejects_table_ddl(args.rejects_table, schema="public")
            with engine.begin() as conn:
                conn.execute(text(ddl))

        # Build configuration
        config = BarBuilderConfig(
            db_url=db_url,
            ids=ids,
            daily_table=args.daily_table,
            bars_table=args.bars_table,
            state_table=args.state_table,
            full_rebuild=args.full_rebuild,
            keep_rejects=args.keep_rejects,
            rejects_table=args.rejects_table if args.keep_rejects else None,
            num_processes=resolve_num_processes(args.num_processes),
            log_level=getattr(args, "log_level", "INFO"),
        )

        return cls(config=config, engine=engine, timeframes=timeframes)

    # =========================================================================
    # Timeframe loading
    # =========================================================================

    @classmethod
    def _load_timeframes_from_dim(
        cls,
        db_url: str,
        include_non_canonical: bool = False,
    ) -> list[tuple[int, str]]:
        """
        Load timeframes from dim_timeframe.

        Args:
            db_url: Database URL
            include_non_canonical: Include non-canonical timeframes

        Returns:
            List of (tf_days, tf_label) tuples
        """
        engine = get_engine(db_url)
        sql = text(
            """
            SELECT
                tf,
                tf_days_nominal,
                sort_order,
                is_canonical
            FROM public.dim_timeframe
            WHERE alignment_type = 'tf_day'
              AND roll_policy = 'multiple_of_tf'
              AND calendar_scheme IS NULL
              AND tf_qty >= 2
              AND tf_days_nominal IS NOT NULL
              AND is_intraday = FALSE
            ORDER BY sort_order, tf;
            """
        )

        with engine.connect() as conn:
            rows = conn.execute(sql).mappings().all()

        out = []
        for r in rows:
            tf = str(r["tf"])
            if not _TF_DAY_LABEL_RE.match(tf):
                continue

            if (not include_non_canonical) and (not bool(r["is_canonical"])):
                continue

            tf_days_nominal = r["tf_days_nominal"]
            if tf_days_nominal is None:
                raise RuntimeError(f"dim_timeframe.tf_days_nominal is NULL for tf={tf}")
            out.append((int(tf_days_nominal), tf))

        if not out:
            raise RuntimeError(
                "No TFs selected from dim_timeframe for tf_day/multi_tf."
            )
        return out

    # =========================================================================
    # Bar building implementation (Polars-optimized)
    # =========================================================================

    def _build_snapshots_polars(
        self,
        df_daily: pd.DataFrame,
        tf_days: int,
        tf_label: str,
    ) -> pd.DataFrame:
        """
        FAST PATH: Full build using Polars vectorization (20-30% faster).

        Emits ONE ROW PER DAY per bar_seq (append-only snapshots).
        """
        if df_daily.empty:
            return pd.DataFrame()

        # Hard invariant (shared contract)
        assert_one_row_per_local_day(df_daily, ts_col="ts", tz=DEFAULT_TZ, id_col="id")

        df = df_daily.sort_values("ts").reset_index(drop=True).copy()
        n = len(df)

        # Vectorized bar assignment
        day_idx = np.arange(n, dtype=np.int64)
        df["bar_seq"] = (day_idx // tf_days) + 1
        df["pos_in_bar"] = (day_idx % tf_days) + 1

        id_val = int(df["id"].iloc[0])

        # Normalize timestamps for Polars
        df = normalize_timestamps_for_polars(df)
        pl_df = pl.from_pandas(df).sort("ts")

        # Apply standard Polars pipeline
        pl_df = apply_standard_polars_pipeline(pl_df, include_missing_days=True)

        # Cumulative count within bar_seq
        pl_df = pl_df.with_columns(
            [
                pl.col("bar_seq")
                .cum_count()
                .over("bar_seq")
                .cast(pl.Int64)
                .alias("count_days"),
            ]
        )

        # time_open, time_close, time_open_bar, time_close_bar, last_ts_half_open
        # time_close = per-row snapshot date (this row's ts) -- REVERTED to old behavior
        # time_close_bar = bar's scheduled end date (time_open + tf_days days)
        # time_open_bar = bar-level opening time (= time_open)
        one_ms = pl.duration(milliseconds=1)
        pl_df = pl_df.with_columns(
            [
                pl.col("day_time_open").alias("time_open"),
                pl.col("day_time_open").first().over("bar_seq").alias("time_open_bar"),
                pl.col("ts").alias("time_close"),
                (
                    pl.col("day_time_open").first().over("bar_seq")
                    + pl.duration(days=tf_days)
                ).alias("time_close_bar"),
                (pl.col("ts") + one_ms).alias("last_ts_half_open"),
            ]
        )

        pl_df = pl_df.with_columns(
            [
                (pl.col("count_missing_days") > 0).alias("is_missing_days"),
                pl.lit(False).alias("is_partial_start"),
                (pl.col("pos_in_bar") < tf_days).alias("is_partial_end"),
                (tf_days - pl.col("pos_in_bar"))
                .cast(pl.Int64)
                .alias("count_days_remaining"),
            ]
        )

        # Select final columns
        out_pl = pl_df.select(
            [
                pl.lit(id_val).cast(pl.Int64).alias("id"),
                pl.lit(tf_label).alias("tf"),
                pl.lit(tf_days).cast(pl.Int64).alias("tf_days"),
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
                pl.col("vol_bar").cast(pl.Float64).alias("volume"),
                pl.col("mc_bar").cast(pl.Float64).alias("market_cap"),
                pl.col("ts").alias("timestamp"),
                pl.col("last_ts_half_open"),
                pl.col("pos_in_bar").cast(pl.Int64),
                pl.col("is_partial_start").cast(pl.Boolean),
                pl.col("is_partial_end").cast(pl.Boolean),
                pl.col("count_days_remaining").cast(pl.Int64),
                pl.col("is_missing_days").cast(pl.Boolean),
                pl.col("count_days").cast(pl.Int64),
                pl.col("count_missing_days").cast(pl.Int64),
                pl.lit(None).cast(pl.Datetime).alias("first_missing_day"),
                pl.lit(None).cast(pl.Datetime).alias("last_missing_day"),
                pl.col("src_name"),
                pl.col("src_load_ts"),
                pl.lit("cmc_price_bars_1d").alias("src_file"),
            ]
        )

        # Convert back to pandas
        out = out_pl.to_pandas()

        # Restore UTC timezone and compact types
        out = restore_utc_timezone(out)
        out = compact_output_types(out)
        out = normalize_output_schema(out)
        out = enforce_ohlc_sanity(out)

        return out

    def _append_incremental_rows(
        self,
        id_: int,
        tf_days: int,
        tf_label: str,
        daily_max_ts: pd.Timestamp,
        last: dict,
    ) -> pd.DataFrame:
        """
        Append snapshot rows after last_time_close for one (id, tf).

        Uses carry-forward optimization when strict gate passes.
        """
        last_time_close = last["last_time_close"]
        last_bar_seq = (
            int(last["last_bar_seq"]) if last["last_bar_seq"] is not None else 0
        )
        last_pos_in_bar = (
            int(last["last_pos_in_bar"])
            if last.get("last_pos_in_bar") is not None
            else 0
        )

        if last_time_close is not None and daily_max_ts <= last_time_close:
            return pd.DataFrame()

        ts_start = last_time_close + _ONE_MS if last_time_close is not None else None
        df_new = load_daily_prices_for_id(
            db_url=self.config.db_url,
            daily_table=self.config.daily_table,
            id_=id_,
            ts_start=ts_start,
        )

        if df_new.empty:
            return pd.DataFrame()

        cur_bar_seq = last_bar_seq
        cur_pos = last_pos_in_bar

        # Load last snapshot row for current bar
        last_row = self._load_last_bar_snapshot_row(id_, tf_label, cur_bar_seq)
        if last_row is None:
            return pd.DataFrame()

        prev_snapshot = (
            normalize_output_schema(pd.DataFrame([last_row])).iloc[0].to_dict()
        )
        prev_time_close = pd.to_datetime(prev_snapshot["time_close"], utc=True)
        prev_time_open = pd.to_datetime(prev_snapshot["time_open"], utc=True)

        # Track local days for missing-days diagnostics
        cur_bar_local_days = []
        cur_bar_start_day_local = prev_time_close.tz_convert(DEFAULT_TZ).date()

        new_rows = []

        for _, d in df_new.iterrows():
            day_ts = pd.to_datetime(d["ts"], utc=True)

            # Start new bar if prior was complete
            if cur_pos >= tf_days:
                cur_bar_seq += 1
                cur_pos = 0
                prev_time_open = prev_time_close + _ONE_MS
                cur_bar_local_days = []
                cur_bar_start_day_local = day_ts.tz_convert(DEFAULT_TZ).date()

                # Reset snapshot baseline
                prev_snapshot = self._create_new_bar_snapshot(
                    id_, tf_label, tf_days, cur_bar_seq, prev_time_open, d
                )

            cur_pos += 1
            snapshot_day_local = day_ts.tz_convert(DEFAULT_TZ).date()
            cur_bar_local_days.append(snapshot_day_local)

            # Strict tail continuity for carry-forward gate
            prev_snapshot_day_local = prev_time_close.tz_convert(DEFAULT_TZ).date()
            missing_days_tail_ok = (
                snapshot_day_local
                == (prev_snapshot_day_local + pd.Timedelta(days=1)).date()
            )

            inp = CarryForwardInputs(
                prev_snapshot_day_local=prev_snapshot_day_local,
                snapshot_day_local=snapshot_day_local,
                same_bar_identity=True,
                missing_days_tail_ok=bool(missing_days_tail_ok),
            )

            is_partial_end = cur_pos < tf_days
            count_days_remaining = int(tf_days - cur_pos)

            # Compute missing-days diagnostics
            miss_diag = compute_missing_days_diagnostics(
                bar_start_day_local=cur_bar_start_day_local,
                snapshot_day_local=snapshot_day_local,
                observed_local_days=cur_bar_local_days,
            )

            # Use carry-forward optimization when gate passes
            if can_carry_forward(inp):
                out_row = apply_carry_forward(
                    prev_snapshot=prev_snapshot,
                    today_daily_row=d.to_dict(),
                    today_ts_utc=day_ts,
                    today_timehigh_utc=(
                        pd.to_datetime(d["timehigh"], utc=True)
                        if pd.notna(d["timehigh"])
                        else None
                    ),
                    today_timelow_utc=(
                        pd.to_datetime(d["timelow"], utc=True)
                        if pd.notna(d["timelow"])
                        else None
                    ),
                    missing_diag=miss_diag,
                    pos_in_bar=int(cur_pos),
                    is_partial_end=bool(is_partial_end),
                )

                # Builder-owned fields
                out_row["id"] = int(id_)
                out_row["tf"] = tf_label
                out_row["tf_days"] = int(tf_days)
                out_row["bar_seq"] = int(cur_bar_seq)
                out_row["time_open"] = prev_time_close + _ONE_MS
                out_row["time_open_bar"] = prev_time_open
                out_row["time_close"] = day_ts
                out_row["time_close_bar"] = prev_time_open + pd.Timedelta(days=tf_days)
                out_row["timestamp"] = day_ts
                out_row["last_ts_half_open"] = day_ts + _ONE_MS
                out_row["count_days_remaining"] = int(count_days_remaining)
                out_row.setdefault("first_missing_day", pd.NaT)
                out_row.setdefault("last_missing_day", pd.NaT)
                out_row["src_name"] = d.get("src_name")
                out_row["src_load_ts"] = d.get("src_load_ts")
                out_row["src_file"] = "cmc_price_bars_1d"

                out_row = (
                    normalize_output_schema(pd.DataFrame([out_row])).iloc[0].to_dict()
                )
                new_rows.append(out_row)

                prev_snapshot = dict(out_row)
                prev_time_close = day_ts
                continue

            # Fallback path (explicit incremental math)
            out_row = self._compute_incremental_snapshot(
                prev_snapshot=prev_snapshot,
                d=d,
                day_ts=day_ts,
                id_=id_,
                tf_label=tf_label,
                tf_days=tf_days,
                cur_bar_seq=cur_bar_seq,
                prev_time_open=prev_time_open,
                cur_pos=cur_pos,
                is_partial_end=is_partial_end,
                count_days_remaining=count_days_remaining,
                miss_diag=miss_diag,
            )

            out_row = normalize_output_schema(pd.DataFrame([out_row])).iloc[0].to_dict()
            new_rows.append(out_row)

            prev_snapshot = dict(out_row)
            prev_time_close = day_ts

        df_out = pd.DataFrame(new_rows)
        df_out = normalize_output_schema(df_out)
        df_out = enforce_ohlc_sanity(df_out)
        return df_out

    def _create_new_bar_snapshot(
        self,
        id_: int,
        tf_label: str,
        tf_days: int,
        cur_bar_seq: int,
        prev_time_open: pd.Timestamp,
        d: pd.Series,
    ) -> dict:
        """Create initial snapshot for new bar."""
        return (
            normalize_output_schema(
                pd.DataFrame(
                    [
                        {
                            "id": int(id_),
                            "tf": tf_label,
                            "tf_days": int(tf_days),
                            "bar_seq": int(cur_bar_seq),
                            "time_open": prev_time_open,
                            "time_close": pd.NaT,
                            "time_high": pd.NaT,
                            "time_low": pd.NaT,
                            "open": float(d["open"])
                            if pd.notna(d["open"])
                            else float("nan"),
                            "high": float(d["high"])
                            if pd.notna(d["high"])
                            else float("nan"),
                            "low": float(d["low"])
                            if pd.notna(d["low"])
                            else float("nan"),
                            "close": float("nan"),
                            "volume": 0.0,
                            "market_cap": (
                                float(d["market_cap"])
                                if pd.notna(d["market_cap"])
                                else float("nan")
                            ),
                            "timestamp": pd.NaT,
                            "last_ts_half_open": pd.NaT,
                            "pos_in_bar": 0,
                            "is_partial_start": False,
                            "is_partial_end": True,
                            "count_days_remaining": int(tf_days),
                            "is_missing_days": False,
                            "count_days": 0,
                            "count_missing_days": 0,
                            "first_missing_day": pd.NaT,
                            "last_missing_day": pd.NaT,
                        }
                    ]
                )
            )
            .iloc[0]
            .to_dict()
        )

    def _compute_incremental_snapshot(
        self,
        prev_snapshot: dict,
        d: pd.Series,
        day_ts: pd.Timestamp,
        id_: int,
        tf_label: str,
        tf_days: int,
        cur_bar_seq: int,
        prev_time_open: pd.Timestamp,
        cur_pos: int,
        is_partial_end: bool,
        count_days_remaining: int,
        miss_diag,
    ) -> dict:
        """Compute snapshot using explicit incremental math (fallback path)."""
        # Extract previous values
        prev_high = (
            float(prev_snapshot.get("high"))
            if pd.notna(prev_snapshot.get("high"))
            else float("-inf")
        )
        prev_low = (
            float(prev_snapshot.get("low"))
            if pd.notna(prev_snapshot.get("low"))
            else float("inf")
        )
        prev_time_high = pd.to_datetime(
            prev_snapshot.get("time_high"), utc=True, errors="coerce"
        )
        prev_time_low = pd.to_datetime(
            prev_snapshot.get("time_low"), utc=True, errors="coerce"
        )

        # Today's values
        day_high = float(d["high"]) if pd.notna(d["high"]) else float("nan")
        day_low = float(d["low"]) if pd.notna(d["low"]) else float("nan")

        # Fallback-to-ts for tie timestamps
        day_th = (
            pd.to_datetime(d["timehigh"], utc=True)
            if pd.notna(d["timehigh"])
            else day_ts
        )
        day_tl = (
            pd.to_datetime(d["timelow"], utc=True) if pd.notna(d["timelow"]) else day_ts
        )

        # Update high
        new_high = prev_high
        new_time_high = prev_time_high
        if pd.isna(new_high) or (pd.notna(day_high) and day_high > new_high):
            new_high = day_high
            new_time_high = day_th
        elif pd.notna(day_high) and pd.notna(new_high) and day_high == new_high:
            if pd.notna(day_th) and (pd.isna(new_time_high) or day_th < new_time_high):
                new_time_high = day_th

        # Update low
        new_low = prev_low
        new_time_low = prev_time_low
        if pd.isna(new_low) or (pd.notna(day_low) and day_low < new_low):
            new_low = day_low
            new_time_low = day_tl
        elif pd.notna(day_low) and pd.notna(new_low) and day_low == new_low:
            if pd.notna(day_tl) and (pd.isna(new_time_low) or day_tl < new_time_low):
                new_time_low = day_tl

        # Update volume
        prev_vol = (
            float(prev_snapshot.get("volume"))
            if pd.notna(prev_snapshot.get("volume"))
            else 0.0
        )
        add_vol = float(d["volume"]) if pd.notna(d["volume"]) else 0.0
        new_volume = prev_vol + add_vol

        # Update other fields
        prev_open = (
            float(prev_snapshot.get("open"))
            if pd.notna(prev_snapshot.get("open"))
            else float("nan")
        )
        new_close = float(d["close"]) if pd.notna(d["close"]) else float("nan")
        new_market_cap = (
            float(d["market_cap"])
            if pd.notna(d["market_cap"])
            else float(prev_snapshot.get("market_cap", float("nan")))
        )

        return {
            "id": int(id_),
            "tf": tf_label,
            "tf_days": int(tf_days),
            "bar_seq": int(cur_bar_seq),
            "time_open": pd.to_datetime(prev_snapshot["time_close"], utc=True)
            + _ONE_MS,
            "time_open_bar": prev_time_open,
            "time_close": day_ts,
            "time_close_bar": prev_time_open + pd.Timedelta(days=tf_days),
            "time_high": new_time_high,
            "time_low": new_time_low,
            "open": prev_open,
            "high": float(new_high) if pd.notna(new_high) else float("nan"),
            "low": float(new_low) if pd.notna(new_low) else float("nan"),
            "close": new_close,
            "volume": float(new_volume),
            "market_cap": float(new_market_cap)
            if pd.notna(new_market_cap)
            else float("nan"),
            "timestamp": day_ts,
            "last_ts_half_open": day_ts + _ONE_MS,
            "pos_in_bar": int(cur_pos),
            "is_partial_start": False,
            "is_partial_end": bool(is_partial_end),
            "count_days_remaining": int(count_days_remaining),
            "is_missing_days": bool(miss_diag.is_missing_days),
            "count_days": int(miss_diag.count_days),
            "count_missing_days": int(miss_diag.count_missing_days),
            "first_missing_day": pd.NaT,
            "last_missing_day": pd.NaT,
            "src_name": d.get("src_name"),
            "src_load_ts": d.get("src_load_ts"),
            "src_file": "cmc_price_bars_1d",
        }

    # =========================================================================
    # Helper methods
    # =========================================================================

    def _count_total_daily_rows(self, id_: int) -> int:
        """Count total daily rows for an ID in the source table."""
        engine = get_engine(self.config.db_url)
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT COUNT(*) FROM {self.config.daily_table} WHERE id = :id"),
                {"id": int(id_)},
            ).scalar()
        return int(result or 0)

    def _load_last_snapshot_info(self, id_: int, tf: str) -> dict | None:
        """Load last snapshot info for (id, tf)."""
        engine = get_engine(self.config.db_url)
        bars_table = self.get_output_table_name()

        with engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        f"""
                    WITH last AS (
                      SELECT id, tf, MAX(bar_seq) AS last_bar_seq
                      FROM {bars_table}
                      WHERE id = :id AND tf = :tf
                      GROUP BY id, tf
                    ),
                    last_row AS (
                      SELECT b.*
                      FROM {bars_table} b
                      JOIN last l
                        ON b.id = l.id AND b.tf = l.tf AND b.bar_seq = l.last_bar_seq
                      ORDER BY b.timestamp DESC
                      LIMIT 1
                    ),
                    pos AS (
                      SELECT COUNT(*)::int AS last_pos_in_bar
                      FROM {bars_table} b
                      JOIN last l
                        ON b.id = l.id AND b.tf = l.tf AND b.bar_seq = l.last_bar_seq
                    )
                    SELECT
                      (SELECT last_bar_seq FROM last) AS last_bar_seq,
                      (SELECT timestamp FROM last_row) AS last_time_close,
                      (SELECT last_pos_in_bar FROM pos) AS last_pos_in_bar;
                    """
                    ),
                    {"id": int(id_), "tf": tf},
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

    def _load_last_bar_snapshot_row(
        self, id_: int, tf: str, bar_seq: int
    ) -> dict | None:
        """Load the latest snapshot row for a specific bar_seq."""
        engine = get_engine(self.config.db_url)
        bars_table = self.get_output_table_name()

        with engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        f"""
                    SELECT *
                    FROM {bars_table}
                    WHERE id = :id AND tf = :tf AND bar_seq = :bar_seq
                    ORDER BY timestamp DESC
                    LIMIT 1;
                    """
                    ),
                    {"id": int(id_), "tf": tf, "bar_seq": int(bar_seq)},
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def _delete_bars_and_state(self, id_: int, tf: str) -> None:
        """Delete bars and state for (id, tf) before rebuild."""
        delete_bars_for_id_tf(
            self.config.db_url, self.get_output_table_name(), id_=id_, tf=tf
        )

        # Delete state
        engine = create_engine(self.config.db_url, future=True)
        q = text(
            f"DELETE FROM {self.get_state_table_name()} WHERE id = :id AND tf = :tf;"
        )
        with engine.begin() as conn:
            conn.execute(q, {"id": int(id_), "tf": tf})

    def _upsert_bars(self, bars: pd.DataFrame) -> None:
        """Upsert bars to database."""
        upsert_bars(
            bars,
            db_url=self.config.db_url,
            bars_table=self.get_output_table_name(),
            keep_rejects=_KEEP_REJECTS,
            rejects_table=_REJECTS_TABLE,
        )

    def _update_state(
        self,
        id_: int,
        tf: str,
        bars: pd.DataFrame,
        daily_min_ts: pd.Timestamp,
        daily_max_ts: pd.Timestamp,
    ) -> None:
        """Update state table for (id, tf)."""
        last_bar_seq = int(bars["bar_seq"].max())
        last_time_close = pd.to_datetime(bars["timestamp"].max(), utc=True)

        upsert_state(
            self.config.db_url,
            self.get_state_table_name(),
            [
                {
                    "id": int(id_),
                    "tf": tf,
                    "daily_min_seen": daily_min_ts,
                    "daily_max_seen": daily_max_ts,
                    "last_bar_seq": last_bar_seq,
                    "last_time_close": last_time_close,
                }
            ],
            with_tz=False,
        )


# =============================================================================
# CLI Entry Point
# =============================================================================


def main(argv=None) -> None:
    """
    CLI entry point for multi-TF bar builder.

    Usage:
        python refresh_cmc_price_bars_multi_tf.py --ids all
        python refresh_cmc_price_bars_multi_tf.py --ids 1,52,825 --full-rebuild
    """
    parser = MultiTFBarBuilder.create_argument_parser()
    args = parser.parse_args(argv)
    builder = MultiTFBarBuilder.from_cli_args(args)
    builder.run()


if __name__ == "__main__":
    main()
