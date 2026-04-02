"""
Refresh ema_multi_tf using BaseEMARefresher architecture.

REFACTORED VERSION - Uses new base class for:
- Standardized CLI parsing
- State management via EMAStateManager
- Parallel execution via EMAComputationOrchestrator
- Reduced code duplication

Migrated from: refresh_ema_multi_tf_from_bars.py (~500 LOC → ~150 LOC)

Fast-path (Phase 108-02):
- When watermark is recent (< 7 days), load only the last EMA value per
  (tf, period) and compute forward using the recursive formula:
      ema_new = close * alpha + ema_prev * (1 - alpha)
- Falls back to full recompute for stale watermarks or --no-fast-path.
- Typical speedup: ~59 min -> ~2-3 min for daily incremental runs.
"""

from __future__ import annotations

import argparse
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.features.m_tf.ema_multi_timeframe import write_multi_timeframe_ema_to_db
from ta_lab2.scripts.bars.common_snapshot_contract import resolve_db_url, get_engine
from ta_lab2.scripts.emas.base_ema_refresher import (
    BaseEMARefresher,
    EMARefresherConfig,
)
from ta_lab2.scripts.emas.ema_state_manager import EMAStateConfig, EMAStateManager
from ta_lab2.scripts.emas.ema_computation_orchestrator import WorkerTask
from ta_lab2.scripts.emas.logging_config import get_worker_logger
from ta_lab2.time.dim_timeframe import list_tfs


# Default EMA periods for multi-tf
DEFAULT_PERIODS = [6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365]

# Default fast-path threshold: watermarks older than this trigger full recompute
FAST_PATH_THRESHOLD_DAYS = 7


# =============================================================================
# Fast-Path Computation Helper
# =============================================================================


def _compute_fast_path_emas(
    id_: int,
    engine,
    last_emas_df,
    bars_schema: str,
    bars_table: str,
    out_schema: str,
    out_table: str,
    alignment_source: str,
    periods: list[int],
    venue_id: int,
    logger,
):
    """
    Compute EMA forward from last known values using only new daily bars.

    For each (tf, period) combo:
    1. Get the last canonical EMA values (ema, ema_bar) from last_emas_df.
    2. Load new daily closes since the last EMA timestamp (+ 1 row overlap).
    3. Compute ema_bar for new bar boundaries using:
           ema_bar_new = alpha_bar * close + (1 - alpha_bar) * ema_bar_prev
    4. Compute ema (continuous daily alpha) forward from the seed:
           ema_new = alpha_daily * close + (1 - alpha_daily) * ema_prev
    5. Build output rows with roll=FALSE for bar boundaries, roll=TRUE for previews.

    This avoids loading 15 years of history when only 1-4 new daily rows exist.

    Returns:
        DataFrame with columns: id, venue_id, tf, ts, period, tf_days,
        roll, ema, ema_bar, is_partial_end, alignment_source
    """
    import numpy as np
    import pandas as pd
    from sqlalchemy import text as _text

    from ta_lab2.features.m_tf.polars_ema_operations import compute_dual_ema_numpy
    from ta_lab2.time.dim_timeframe import get_tf_days

    if last_emas_df.empty:
        return pd.DataFrame()

    db_url = engine.url.render_as_string(hide_password=False)

    # Minimum last_ts across all (tf, period) combos — load bars from here
    last_emas_df["ts"] = pd.to_datetime(last_emas_df["ts"], utc=True)
    min_last_ts = last_emas_df["ts"].min()

    # Load new daily bars from price_bars_1d (same source as load_source_data)
    sql_bars = _text(
        """
        SELECT
            id,
            venue_id,
            timestamp AS ts,
            close
        FROM public.price_bars_1d
        WHERE id = :id
          AND venue_id = :venue_id
          AND timestamp >= :since_ts
        ORDER BY id, venue_id, timestamp
        """
    )
    with engine.connect() as conn:
        df_new_bars = pd.read_sql(
            sql_bars,
            conn,
            params={"id": id_, "venue_id": venue_id, "since_ts": min_last_ts},
        )

    if df_new_bars.empty:
        logger.info(f"fast-path: no new bars for id={id_} (venue_id={venue_id})")
        return pd.DataFrame()

    df_new_bars["ts"] = pd.to_datetime(df_new_bars["ts"], utc=True)
    df_new_bars = df_new_bars.sort_values("ts").reset_index(drop=True)

    # Load new bar closes from price_bars_multi_tf_u for bar-boundary detection
    # (is_partial_end = FALSE marks bar completions within the new window)
    sql_bar_closes = _text(
        f"""
        SELECT
            tf,
            bar_seq,
            "timestamp" AS time_close,
            close AS close_bar,
            venue_id
        FROM {bars_schema}.{bars_table}
        WHERE id = :id
          AND venue_id = :venue_id
          AND alignment_source = :alignment_source
          AND is_partial_end = FALSE
          AND "timestamp" >= :since_ts
        ORDER BY tf, bar_seq
        """
    )
    with engine.connect() as conn:
        df_bar_closes = pd.read_sql(
            sql_bar_closes,
            conn,
            params={
                "id": id_,
                "venue_id": venue_id,
                "alignment_source": alignment_source,
                "since_ts": min_last_ts,
            },
        )

    if not df_bar_closes.empty:
        df_bar_closes["time_close"] = pd.to_datetime(
            df_bar_closes["time_close"], utc=True
        )

    # Build output frames — one per (tf, period) combo
    frames = []

    # Group last_emas_df by tf for efficient lookup
    last_emas_by_tf_period = {
        (row["tf"], int(row["period"])): row for _, row in last_emas_df.iterrows()
    }

    tfs_in_emas = last_emas_df["tf"].unique().tolist()

    for tf in tfs_in_emas:
        # Get tf_days for this TF
        try:
            tf_days = int(get_tf_days(tf, db_url=db_url))
        except Exception:
            logger.warning(f"fast-path: could not get tf_days for tf={tf}, skipping")
            continue

        if tf_days <= 0:
            continue

        # New bar closes for this TF (bar boundaries in the new window)
        # Note on alpha: each per-period combo uses alpha = 2/(period+1) for ema_bar
        # and alpha_daily = 2/(tf_days*period+1) for the continuous ema.
        if not df_bar_closes.empty:
            bars_tf = df_bar_closes[df_bar_closes["tf"] == tf].copy()
            bars_tf = bars_tf.sort_values("bar_seq").reset_index(drop=True)
        else:
            bars_tf = pd.DataFrame()

        bar_ts_set: set = set()
        if not bars_tf.empty:
            bar_ts_set = set(bars_tf["time_close"].tolist())

        # Daily grid for this TF (only rows >= min_last_ts_for_tf)
        # Find the earliest last_ts for any period in this TF
        tf_rows = last_emas_df[last_emas_df["tf"] == tf]
        tf_min_last_ts = tf_rows["ts"].min()

        df_grid = df_new_bars[df_new_bars["ts"] >= tf_min_last_ts].copy()
        if df_grid.empty:
            continue

        grid_ts = df_grid["ts"].tolist()
        grid_close = df_grid["close"].astype(float).to_numpy()
        n_grid = len(grid_ts)

        # Determine canonical mask (True = bar boundary = new canonical close)
        # The first row may be the last-known EMA timestamp (included as seed row)
        canonical_mask = np.zeros(n_grid, dtype=bool)
        for i, ts_val in enumerate(grid_ts):
            if ts_val in bar_ts_set:
                canonical_mask[i] = True

        # is_partial_end: True for rows after the last canonical close
        last_canon_ts = max(bar_ts_set) if bar_ts_set else None
        is_partial_arr = np.array(
            [ts_val > last_canon_ts if last_canon_ts else True for ts_val in grid_ts]
        )

        # Process each period for this TF
        for p in periods:
            key = (tf, p)
            if key not in last_emas_by_tf_period:
                continue

            seed_row = last_emas_by_tf_period[key]
            seed_ts = pd.to_datetime(seed_row["ts"], utc=True)
            seed_ema_bar = (
                float(seed_row["ema_bar"])
                if seed_row["ema_bar"] is not None
                else float("nan")
            )
            seed_ema = (
                float(seed_row["ema"]) if seed_row["ema"] is not None else float("nan")
            )

            if np.isnan(seed_ema_bar) or np.isnan(seed_ema):
                # Bad seed — skip fast-path for this (tf, period), let full recompute handle it
                continue

            # Build canonical_ema_values for new bar closes using recursive formula:
            # ema_bar_new = alpha_bar * close + (1-alpha_bar) * ema_bar_prev
            # We compute this for new canonical bars only.
            period_alpha_bar = 2.0 / (p + 1.0)

            canonical_ema_values = np.full(n_grid, np.nan, dtype=np.float64)

            # Seed: inject last known ema_bar at the grid position matching seed_ts
            # (the first row in the grid if seed_ts == grid[0], or find it)
            seed_injected = False
            prev_ema_bar = seed_ema_bar

            for i, ts_val in enumerate(grid_ts):
                if ts_val == seed_ts:
                    # Inject seed at this position (it's the last known canonical row)
                    canonical_ema_values[i] = seed_ema_bar
                    canonical_mask[i] = True  # Force canonical at seed
                    seed_injected = True
                    prev_ema_bar = seed_ema_bar
                elif canonical_mask[i]:
                    # New bar boundary — compute ema_bar forward
                    close_val = grid_close[i]
                    new_ema_bar = (
                        period_alpha_bar * close_val
                        + (1.0 - period_alpha_bar) * prev_ema_bar
                    )
                    canonical_ema_values[i] = new_ema_bar
                    prev_ema_bar = new_ema_bar

            if not seed_injected:
                # Seed timestamp not in the new grid — inject at the start as a virtual row
                # by forcing the first row to have the seed ema_bar value
                # This happens when grid starts after seed_ts (normal incremental case)
                # We need to prepend a virtual seed row.
                virtual_close = np.array([grid_close[0]])
                virtual_mask = np.array([True])
                virtual_canonical_ema = np.array([seed_ema_bar])

                # Rebuild grid with the virtual seed at position 0
                grid_close_with_seed = np.concatenate([virtual_close, grid_close])
                canonical_mask_with_seed = np.concatenate(
                    [virtual_mask, canonical_mask]
                )
                canonical_ema_values_with_seed = np.concatenate(
                    [virtual_canonical_ema, canonical_ema_values]
                )

                # Recompute canonical_ema_values using recursive forward pass
                prev_ema_bar = seed_ema_bar
                for i in range(1, len(grid_close_with_seed)):
                    if canonical_mask_with_seed[i]:
                        close_val = grid_close_with_seed[i]
                        new_ema_bar = (
                            period_alpha_bar * close_val
                            + (1.0 - period_alpha_bar) * prev_ema_bar
                        )
                        canonical_ema_values_with_seed[i] = new_ema_bar
                        prev_ema_bar = new_ema_bar

                # Compute alpha_daily for continuous EMA
                alpha_daily = 2.0 / (tf_days * p + 1.0)

                ema_bar_out, ema_out = compute_dual_ema_numpy(
                    grid_close_with_seed,
                    canonical_mask_with_seed,
                    canonical_ema_values_with_seed,
                    alpha_daily,
                    period_alpha_bar,
                )

                # Seed the continuous EMA at virtual row using known seed value
                # Override ema at position 0 with seed_ema, then recompute forward
                ema_out[0] = seed_ema
                for i in range(1, len(grid_close_with_seed)):
                    ema_out[i] = (
                        alpha_daily * grid_close_with_seed[i]
                        + (1.0 - alpha_daily) * ema_out[i - 1]
                    )

                # Drop the virtual seed row (position 0)
                grid_ts_slice = grid_ts  # original grid timestamps
                roll_arr = ~np.array([t in bar_ts_set for t in grid_ts_slice])
                is_partial_slice = is_partial_arr

                tmp = pd.DataFrame(
                    {
                        "id": id_,
                        "tf": tf,
                        "ts": grid_ts_slice,
                        "period": p,
                        "tf_days": tf_days,
                        "venue_id": int(venue_id),
                        "roll": roll_arr,
                        "ema": ema_out[1:],
                        "ema_bar": ema_bar_out[1:],
                        "is_partial_end": is_partial_slice,
                    }
                )
                frames.append(tmp)
                continue

            # seed_injected = True path: seed_ts is in the grid
            alpha_daily = 2.0 / (tf_days * p + 1.0)

            ema_bar_out, ema_out = compute_dual_ema_numpy(
                grid_close,
                canonical_mask,
                canonical_ema_values,
                alpha_daily,
                period_alpha_bar,
            )

            # Override ema at seed position with known seed_ema, then recompute forward
            seed_idx = next(
                (i for i, ts_val in enumerate(grid_ts) if ts_val == seed_ts), None
            )
            if seed_idx is not None:
                ema_out[seed_idx] = seed_ema
                for i in range(seed_idx + 1, n_grid):
                    ema_out[i] = (
                        alpha_daily * grid_close[i]
                        + (1.0 - alpha_daily) * ema_out[i - 1]
                    )

            # Only emit rows *after* the seed (don't re-emit the seed row itself)
            emit_start = next(
                (i for i, ts_val in enumerate(grid_ts) if ts_val > seed_ts), None
            )
            if emit_start is None:
                # No new rows beyond seed
                continue

            grid_ts_slice = grid_ts[emit_start:]
            roll_arr = ~np.array([t in bar_ts_set for t in grid_ts_slice])
            is_partial_slice = is_partial_arr[emit_start:]

            tmp = pd.DataFrame(
                {
                    "id": id_,
                    "tf": tf,
                    "ts": grid_ts_slice,
                    "period": p,
                    "tf_days": tf_days,
                    "venue_id": int(venue_id),
                    "roll": roll_arr,
                    "ema": ema_out[emit_start:],
                    "ema_bar": ema_bar_out[emit_start:],
                    "is_partial_end": is_partial_slice,
                }
            )
            frames.append(tmp)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    result["ts"] = pd.to_datetime(result["ts"], utc=True)
    result = result.sort_values(["id", "venue_id", "tf", "period", "ts"])
    logger.info(
        f"fast-path: id={id_} computed {len(result)} new EMA rows "
        f"across {result['tf'].nunique()} TFs x {result['period'].nunique()} periods"
    )
    return result


# =============================================================================
# Worker Function (Module-level for pickling)
# =============================================================================


def _process_id_worker(task: WorkerTask) -> int:
    """
    Worker function for parallel processing of individual IDs.

    Creates own engine with NullPool to avoid connection pooling issues.
    Processes timeframes for the given ID. Supports tf_subset for TF-level parallelism.

    Fast-path: When watermark is recent (< 7 days) and --no-fast-path is not set,
    loads only the last EMA value per (tf, period) and computes forward using the
    recursive formula. Falls back to full recompute for stale watermarks.

    Args:
        task: WorkerTask containing id, db_url, periods, start, extra_config, tf_subset

    Returns:
        Number of rows inserted/updated
    """
    worker_id = str(task.id_)
    logger = get_worker_logger(
        name="ema_multi_tf",
        worker_id=worker_id,
        log_level="INFO",
        log_file=None,
    )

    try:
        tf_info = f" tfs={len(task.tf_subset)}" if task.tf_subset else ""
        logger.info(f"Starting EMA computation for id={task.id_}{tf_info}")

        # Create engine with NullPool for worker
        engine = create_engine(task.db_url, poolclass=NullPool, future=True)

        # Extract configuration
        bars_table = task.extra_config.get("bars_table", "price_bars_multi_tf_u")
        bars_schema = task.extra_config.get("bars_schema", "public")
        out_schema = task.extra_config.get("out_schema", "public")
        out_table = task.extra_config.get("out_table", "ema_multi_tf_u")
        alignment_source = task.extra_config.get("alignment_source", "multi_tf")
        no_fast_path = task.extra_config.get("no_fast_path", False)
        fast_path_threshold = task.extra_config.get(
            "fast_path_threshold_days", FAST_PATH_THRESHOLD_DAYS
        )

        from ta_lab2.features.m_tf.base_ema_feature import EMAFeatureConfig
        from ta_lab2.features.m_tf.ema_multi_timeframe import MultiTFEMAFeature
        import pandas as pd
        import numpy as np

        config = EMAFeatureConfig(
            periods=list(task.periods),
            output_schema=out_schema,
            output_table=out_table,
            alignment_source=alignment_source,
        )

        # ------------------------------------------------------------------
        # Fast-path dispatch: check watermark recency
        # ------------------------------------------------------------------
        if not no_fast_path:
            state_config = EMAStateConfig(
                state_schema=out_schema,
                state_table=task.extra_config.get("state_table", "ema_multi_tf_state"),
            )
            state_mgr = EMAStateManager(engine, state_config)

            if state_mgr.is_watermark_recent(
                task.id_, threshold_days=fast_path_threshold
            ):
                logger.info(
                    f"fast-path: watermark is recent for id={task.id_} "
                    f"(threshold={fast_path_threshold}d) — loading last EMAs + new bars"
                )

                last_emas_df = state_mgr.load_last_ema_values(
                    id_=task.id_,
                    periods=list(task.periods),
                    output_table=out_table,
                    output_schema=out_schema,
                )

                if not last_emas_df.empty:
                    df_fast = _compute_fast_path_emas(
                        id_=task.id_,
                        engine=engine,
                        last_emas_df=last_emas_df,
                        bars_schema=bars_schema,
                        bars_table=bars_table,
                        out_schema=out_schema,
                        out_table=out_table,
                        alignment_source=alignment_source,
                        periods=list(task.periods),
                        venue_id=1,
                        logger=logger,
                    )

                    if df_fast is not None and not df_fast.empty:
                        # Apply tf_subset filter if specified
                        if task.tf_subset:
                            tf_subset_set = set(task.tf_subset)
                            df_fast = df_fast[df_fast["tf"].isin(tf_subset_set)]

                        df_fast = df_fast.replace({np.nan: None})

                        # Use the same write_to_db path as full recompute
                        feature_write = MultiTFEMAFeature(
                            engine=engine,
                            config=config,
                            bars_schema=bars_schema,
                            bars_table=bars_table,
                        )
                        feature_write.write_to_db(df_fast)
                        total_rows = len(df_fast)
                        engine.dispose()
                        logger.info(
                            f"fast-path complete for id={task.id_}: "
                            f"{total_rows} rows written"
                        )
                        return total_rows
                    else:
                        logger.info(
                            f"fast-path: no new rows for id={task.id_}, "
                            "skipping write (already up to date)"
                        )
                        engine.dispose()
                        return 0
                else:
                    logger.info(
                        f"fast-path: no existing EMA values for id={task.id_} "
                        "— falling back to full recompute"
                    )
                    # Fall through to full recompute below
            else:
                logger.info(
                    f"full-recompute: watermark is stale for id={task.id_} "
                    f"(threshold={fast_path_threshold}d)"
                )
        else:
            logger.info(f"full-recompute: --no-fast-path for id={task.id_}")

        # ------------------------------------------------------------------
        # Full recompute path (original logic, unchanged)
        # ------------------------------------------------------------------
        feature = MultiTFEMAFeature(
            engine=engine,
            config=config,
            bars_schema=bars_schema,
            bars_table=bars_table,
            tf_subset=task.tf_subset,
        )
        df_daily = feature.load_source_data([task.id_], start=task.start, end=task.end)
        if df_daily.empty:
            engine.dispose()
            return 0

        tf_specs = feature.get_tf_specs()
        if task.tf_subset:
            tf_subset_set = set(task.tf_subset)
            tf_specs = [s for s in tf_specs if s.tf in tf_subset_set]

        # Preload bar closes for ALL TFs in 1 query (avoids 122 per-TF queries)
        ids = df_daily["id"].unique().tolist()
        feature.preload_bar_closes(ids, end=task.end)

        all_results = []
        for tf_spec in tf_specs:
            df_ema = feature.compute_emas_for_tf(df_daily, tf_spec, config.periods)
            if not df_ema.empty:
                all_results.append(df_ema)

        if all_results:
            df_out = pd.concat(all_results, ignore_index=True)
            df_out = df_out.replace({np.nan: None})
            feature.write_to_db(df_out)
            total_rows = len(df_out)
        else:
            total_rows = 0

        engine.dispose()
        logger.info(f"Completed EMA computation for id={task.id_}: {total_rows} rows")
        return total_rows

    except Exception as e:
        logger.error(f"Worker failed for id={task.id_}: {e}", exc_info=True)
        return 0


# =============================================================================
# Refresher Implementation
# =============================================================================


class MultiTFEMARefresher(BaseEMARefresher):
    """
    EMA refresher for multi-timeframe EMAs from tf_day bars.

    Uses:
    - dim_timeframe (alignment_type='tf_day', canonical_only=True) for TFs
    - price_bars_multi_tf_u for tf_day canonical bars (alignment_source=multi_tf)
    - price_bars_1d for 1D timeframe (validated bars)
    - Parallel execution at ID level

    Fast-path (Phase 108-02):
    - When watermark is recent (< fast_path_threshold_days), loads only the last
      EMA value per (tf, period) and computes forward.
    - Disable with --no-fast-path or --full-refresh.
    """

    DEFAULT_PERIODS = DEFAULT_PERIODS

    def __init__(
        self,
        config: EMARefresherConfig,
        state_config: EMAStateConfig,
        engine,
    ):
        super().__init__(config, state_config, engine)
        self.bars_table = config.extra_config.get("bars_table", "price_bars_multi_tf_u")
        self.bars_schema = config.extra_config.get("bars_schema", "public")

    # =========================================================================
    # Abstract Method Implementations
    # =========================================================================

    def get_timeframes(self) -> list[str]:
        """Load tf_day canonical timeframes from dim_timeframe."""
        tfs = list_tfs(
            db_url=self.config.db_url,
            alignment_type="tf_day",
            canonical_only=True,
        )
        return tfs

    def compute_emas_for_id(
        self,
        id_: int,
        periods: list[int],
        start: Optional[str] = None,
        end: Optional[str] = None,
        **extra_args,
    ) -> int:
        """
        Compute multi-tf EMAs for single ID (sequential across TFs).

        Note: This method is not used by the parallel execution flow,
        but is provided for testing and direct invocation.
        """
        tfs = extra_args.get("tfs", self.get_timeframes())

        total_rows = 0
        for tf in tfs:
            # Special handling for 1D
            actual_bars_table = "price_bars_1d" if tf == "1D" else self.bars_table

            n = write_multi_timeframe_ema_to_db(
                ids=[id_],
                start=start or "2010-01-01",
                end=end,
                ema_periods=periods,
                tf_subset=[tf],
                db_url=self.config.db_url,
                schema=self.config.output_schema,
                out_table=self.config.output_table,
                bars_schema=self.bars_schema,
                bars_table_tf_day=actual_bars_table,
            )
            total_rows += n

        return total_rows

    def get_source_table_info(self) -> dict[str, str]:
        """Return source bars table for ID resolution.

        Uses price_bars_1d (validated daily bars) for ID discovery,
        since IDs exist in 1D before they appear in multi-TF bars.
        """
        return {
            "bars_table": "price_bars_1d",
            "bars_schema": self.bars_schema,
        }

    @staticmethod
    def get_worker_function():
        """Return module-level worker function for multiprocessing."""
        return _process_id_worker

    # =========================================================================
    # CLI Integration
    # =========================================================================

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """Create argument parser with multi-tf specific arguments."""
        # Use base parser to get standardized arguments including validation
        p = cls.create_base_argument_parser(
            description="Refresh ema_multi_tf from tf_day bars (refactored).",
        )

        # Override defaults for this script
        p.set_defaults(
            out_table="ema_multi_tf_u",
            state_table="ema_multi_tf_state",
        )

        # Script-specific arguments
        p.add_argument("--bars-table", default="price_bars_multi_tf_u")
        p.add_argument("--bars-schema", default="public")
        p.add_argument("--tfs", default=None)

        # Fast-path control
        p.add_argument(
            "--no-fast-path",
            action="store_true",
            default=False,
            help=(
                "Disable fast-path optimization. Forces full recompute even when "
                "watermark is recent. Use for debugging or data recovery."
            ),
        )
        p.add_argument(
            "--fast-path-threshold-days",
            type=int,
            default=FAST_PATH_THRESHOLD_DAYS,
            dest="fast_path_threshold_days",
            help=(
                f"Maximum watermark age (days) to use fast-path (default: "
                f"{FAST_PATH_THRESHOLD_DAYS}). Watermarks older than this trigger "
                "full recompute."
            ),
        )

        return p

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "MultiTFEMARefresher":
        """Create refresher instance from CLI arguments."""
        # Resolve database URL
        db_url = resolve_db_url(args.db_url)

        # Create engine
        engine = get_engine(db_url)

        # Create temporary instance to use helper methods
        temp_config = EMARefresherConfig(
            db_url=db_url,
            ids=[],  # Will be set below
            periods=[],  # Will be set below
            output_schema=args.out_schema,
            output_table=args.out_table,
            state_table=args.state_table,
            num_processes=args.num_processes,
            full_refresh=args.full_refresh,
            log_level=args.log_level,
            log_file=args.log_file,
            quiet=args.quiet,
            debug=args.debug,
            validate_output=args.validate_output,
            ema_rejects_table=args.ema_rejects_table,
            extra_config={
                "bars_table": args.bars_table,
                "bars_schema": args.bars_schema,
                "tfs": args.tfs.split(",") if args.tfs else None,
            },
        )

        temp_state_config = EMAStateConfig(
            state_schema=args.out_schema,
            state_table=args.state_table,
            ts_column="ts",
            roll_filter="roll = FALSE",
            use_canonical_ts=True,
            bars_table=args.bars_table,
            bars_schema=args.bars_schema,
            bars_partial_filter="is_partial_end = FALSE",
            alignment_source="multi_tf",
        )

        temp_instance = cls(temp_config, temp_state_config, engine)

        # Load IDs and periods using helper methods
        ids = temp_instance.load_ids(args.ids, venue_id=args.venue_id)
        periods = temp_instance.load_periods(args.periods)

        # Extract fast-path args (with fallback for older argparse namespaces)
        no_fast_path = getattr(args, "no_fast_path", False)
        fast_path_threshold_days = getattr(
            args, "fast_path_threshold_days", FAST_PATH_THRESHOLD_DAYS
        )

        # --full-refresh implicitly disables fast-path
        if args.full_refresh:
            no_fast_path = True

        # Create final config with loaded IDs and periods
        final_config = EMARefresherConfig(
            db_url=db_url,
            ids=ids,
            periods=periods,
            output_schema=args.out_schema,
            output_table=args.out_table,
            state_table=args.state_table,
            num_processes=args.num_processes,
            full_refresh=args.full_refresh,
            log_level=args.log_level,
            log_file=args.log_file,
            quiet=args.quiet,
            debug=args.debug,
            validate_output=args.validate_output,
            ema_rejects_table=args.ema_rejects_table,
            extra_config={
                "bars_table": args.bars_table,
                "bars_schema": args.bars_schema,
                "out_schema": args.out_schema,
                "out_table": args.out_table,
                "tfs": args.tfs.split(",") if args.tfs else None,
                "alignment_source": "multi_tf",
                "state_table": args.state_table,
                "no_fast_path": no_fast_path,
                "fast_path_threshold_days": fast_path_threshold_days,
            },
        )

        state_config = EMAStateConfig(
            state_schema=args.out_schema,
            state_table=args.state_table,
            ts_column="ts",
            roll_filter="roll = FALSE",
            use_canonical_ts=True,
            bars_table=args.bars_table,
            bars_schema=args.bars_schema,
            bars_partial_filter="is_partial_end = FALSE",
            alignment_source="multi_tf",
        )

        return cls(final_config, state_config, engine)


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    MultiTFEMARefresher.main()
