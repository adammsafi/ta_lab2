from __future__ import annotations

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
"""

import re
import time
from typing import Sequence

import numpy as np
import pandas as pd
import polars as pl
from sqlalchemy import create_engine, text

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
    load_daily_min_max,
    ensure_state_table,
    load_state,
    upsert_state,
    resolve_num_processes,
    # Shared write pipeline
    upsert_bars,
    enforce_ohlc_sanity,
    # Bar builder DB utilities (extracted)
    load_daily_prices_for_id,
    delete_bars_for_id_tf,
    load_last_snapshot_info_for_id_tfs,
    # CLI parsing utility (extracted)
    create_bar_builder_argument_parser,
    # Reject table utilities (GAP-C01)
    create_rejects_table_ddl,
    log_to_rejects,
    detect_ohlc_violations,
)
from ta_lab2.orchestration import (
    MultiprocessingOrchestrator,
    OrchestratorConfig,
    ProgressTracker,
)

# =============================================================================
# Defaults / constants
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


# =============================================================================
# Reject logging helper
# =============================================================================


def _log_ohlc_violations(out: pd.DataFrame) -> None:
    """
    Log OHLC violations from DataFrame to rejects table (if enabled).

    Called before enforce_ohlc_sanity to capture original invalid values.
    """
    if not _KEEP_REJECTS or not _REJECTS_TABLE or not _DB_URL:
        return

    rejects = []
    for _, row in out.iterrows():
        violations = detect_ohlc_violations(row.to_dict())
        for vtype, raction in violations:
            rejects.append(
                {
                    "id": row["id"],
                    "tf": row["tf"],
                    "bar_seq": row["bar_seq"],
                    "timestamp": row["timestamp"],
                    "violation_type": vtype,
                    "repair_action": raction,
                    "original_open": row["open"],
                    "original_high": row["high"],
                    "original_low": row["low"],
                    "original_close": row["close"],
                }
            )
    if rejects:
        engine = get_engine(_DB_URL)
        log_to_rejects(engine, _REJECTS_TABLE, rejects)


# =============================================================================
# TF selection (from dim_timeframe)
# =============================================================================

_TF_DAY_LABEL_RE = re.compile(r"^\d+D$")


def load_tf_list_from_dim_timeframe(
    *,
    db_url: str,
    include_non_canonical: bool = False,
) -> list[tuple[int, str]]:
    eng = get_engine(db_url)
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

    with eng.connect() as conn:
        rows = conn.execute(sql).mappings().all()

    out: list[tuple[int, str]] = []
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
        raise RuntimeError("No TFs selected from dim_timeframe for tf_day/multi_tf.")
    return out


# =============================================================================
# Bar building helpers (now imported from common_snapshot_contract)
# =============================================================================


def delete_state_for_id_tf(db_url: str, state_table: str, id_: int, tf: str) -> None:
    """Delete the state row for a single (id, tf). Good hygiene for full rebuild."""
    engine = create_engine(db_url, future=True)
    q = text(f"DELETE FROM {state_table} WHERE id = :id AND tf = :tf;")
    with engine.begin() as conn:
        conn.execute(q, {"id": int(id_), "tf": tf})


def _make_day_time_open(ts: pd.Series) -> pd.Series:
    day_open = ts.shift(1) + _ONE_MS
    if len(ts) > 0:
        day_open.iloc[0] = ts.iloc[0] - pd.Timedelta(days=1) + _ONE_MS
    return day_open


# =============================================================================
# Bar building (snapshots) - VECTORIZED FULL BUILD
# =============================================================================


def build_snapshots_for_id_polars(
    df_id: pd.DataFrame,
    *,
    tf_days: int,
    tf_label: str,
) -> pd.DataFrame:
    """
    FAST PATH: Full build using Polars vectorization (20-30% faster for large datasets).

    Emits ONE ROW PER DAY per bar_seq (append-only snapshots).

    CONTRACT:
    - Enforces 1 row per local day.
    - time_high/time_low: earliest-tie-break among equals, with fallback to ts.
    - Normalizes required contract schema columns.
    """
    if df_id.empty:
        return pd.DataFrame()

    # Hard invariant (shared contract)
    assert_one_row_per_local_day(df_id, ts_col="ts", tz=DEFAULT_TZ, id_col="id")

    df = df_id.sort_values("ts").reset_index(drop=True).copy()

    n = len(df)
    if n <= 0:
        return pd.DataFrame()

    # Vectorized bar assignment
    day_idx = np.arange(n, dtype=np.int64)
    df["bar_seq"] = (day_idx // tf_days) + 1
    df["pos_in_bar"] = (day_idx % tf_days) + 1

    id_val = int(df["id"].iloc[0])

    # --- contract normalization: ensure we have ts/timehigh/timelow as tz-naive UTC datetimes for Polars ops ---
    if "ts" not in df.columns:
        if "timestamp" in df.columns:
            df["ts"] = df["timestamp"]
        else:
            raise ValueError(
                "Daily table is missing required 'timestamp' column (needed to derive 'ts')."
            )

    if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
        raise TypeError(f"df['ts'] must be datetime64; got {df['ts'].dtype}")

    # Normalize timestamps using extracted utility
    from ta_lab2.scripts.bars.polars_bar_operations import (
        normalize_timestamps_for_polars,
        apply_standard_polars_pipeline,
        restore_utc_timezone,
        compact_output_types,
    )

    df = normalize_timestamps_for_polars(df)

    pl_df = pl.from_pandas(df).sort("ts")

    # Apply standard Polars pipeline (replaces 120+ lines of inline operations)
    pl_df = apply_standard_polars_pipeline(pl_df, include_missing_days=True)

    # Cumulative count within bar_seq (builder-specific)
    pl_df = pl_df.with_columns(
        [
            pl.col("bar_seq")
            .cum_count()
            .over("bar_seq")
            .cast(pl.Int64)
            .alias("count_days"),
        ]
    )

    # time_open, time_close, last_ts_half_open (builder-specific)
    one_ms = pl.duration(milliseconds=1)
    pl_df = pl_df.with_columns(
        [
            pl.col("day_time_open").first().over("bar_seq").alias("time_open"),
            pl.col("ts").alias("time_close"),
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
            pl.col("open_bar").cast(pl.Float64).alias("open"),
            pl.col("high_bar").cast(pl.Float64).alias("high"),
            pl.col("low_bar").cast(pl.Float64).alias("low"),
            pl.col("close_bar").cast(pl.Float64).alias("close"),
            pl.col("vol_bar").cast(pl.Float64).alias("volume"),
            pl.col("mc_bar").cast(pl.Float64).alias("market_cap"),
            pl.col("time_close").alias("timestamp"),
            pl.col("last_ts_half_open"),
            pl.col("pos_in_bar").cast(pl.Int64),
            pl.col("is_partial_start").cast(pl.Boolean),
            pl.col("is_partial_end").cast(pl.Boolean),
            pl.col("count_days_remaining").cast(pl.Int64),
            pl.col("is_missing_days").cast(pl.Boolean),
            pl.col("count_days").cast(pl.Int64),
            pl.col("count_missing_days").cast(pl.Int64),
            # builder-owned; left as NaT unless you choose to compute them later
            pl.lit(None).cast(pl.Datetime).alias("first_missing_day"),
            pl.lit(None).cast(pl.Datetime).alias("last_missing_day"),
        ]
    )

    # Convert back to pandas
    out = out_pl.to_pandas()

    # Restore UTC timezone using extracted utility
    out = restore_utc_timezone(out)

    # Compact types using extracted utility
    out = compact_output_types(out)

    out = normalize_output_schema(out)
    out = enforce_ohlc_sanity(out)
    return out


def build_snapshots_for_id(
    df_id: pd.DataFrame,
    *,
    tf_days: int,
    tf_label: str,
) -> pd.DataFrame:
    """
    PANDAS PATH: Full build for a single id + tf_days, emitting ONE ROW PER DAY per bar_seq.

    This is the fallback implementation. Use build_snapshots_for_id_polars() for better performance.
    Kept for compatibility and as reference implementation.

    CONTRACT:
    - Enforces 1 row per local day.
    - time_high/time_low: earliest-tie-break among equals, with fallback to ts.
    - Normalizes required contract schema columns.
    """
    if df_id.empty:
        return pd.DataFrame()

    # Hard invariant (shared contract)
    assert_one_row_per_local_day(df_id, ts_col="ts", tz=DEFAULT_TZ, id_col="id")

    df = df_id.sort_values("ts").reset_index(drop=True).copy()
    df["day_time_open"] = _make_day_time_open(df["ts"])

    n = len(df)
    if n <= 0:
        return pd.DataFrame()

    day_idx = np.arange(n, dtype=np.int64)
    df["bar_seq"] = (day_idx // tf_days) + 1
    df["pos_in_bar"] = (day_idx % tf_days) + 1

    id_val = int(df["id"].iloc[0])
    g = df.groupby("bar_seq", sort=True)

    df["time_open"] = g["day_time_open"].transform("first")
    df["time_close"] = df["ts"]

    df["open_bar"] = g["open"].transform("first")
    df["close_bar"] = df["close"]

    df["high_bar"] = g["high"].cummax()
    df["low_bar"] = g["low"].cummin()

    # volume: treat NaN as 0 then cumsum within bar
    df["vol_bar"] = df["volume"].fillna(0.0).groupby(df["bar_seq"], sort=False).cumsum()
    df["mc_bar"] = df["market_cap"]

    # Missing days diagnostics (simple)
    gaps = df.groupby("bar_seq", sort=False)["ts"].diff()
    missing_incr = gaps / pd.Timedelta(days=1)
    missing_incr = missing_incr.fillna(0).astype("int64") - 1
    missing_incr = missing_incr.clip(lower=0).astype("int64")

    df["missing_incr"] = missing_incr
    df["count_missing_days"] = (
        df.groupby("bar_seq", sort=False)["missing_incr"].cumsum().astype("int64")
    )
    df["is_missing_days"] = df["count_missing_days"] > 0

    # Contract-consistent extrema timestamps: fallback to ts when timehigh/timelow missing
    ts_arr = df["ts"].to_numpy(dtype="datetime64[ns]")
    timehigh_arr = df["timehigh"].to_numpy(dtype="datetime64[ns]")
    timelow_arr = df["timelow"].to_numpy(dtype="datetime64[ns]")

    t_high = np.where(np.isnat(timehigh_arr), ts_arr, timehigh_arr).astype(
        "datetime64[ns]"
    )
    t_low = np.where(np.isnat(timelow_arr), ts_arr, timelow_arr).astype(
        "datetime64[ns]"
    )

    high_vals = df["high"].to_numpy(dtype=float)
    low_vals = df["low"].to_numpy(dtype=float)

    df["time_high"] = _cum_extrema_time_by_bar(
        gkey=df["bar_seq"], val=high_vals, t=t_high, want="max"
    )
    df["time_low"] = _cum_extrema_time_by_bar(
        gkey=df["bar_seq"], val=low_vals, t=t_low, want="min"
    )

    df["is_partial_start"] = False
    df["is_partial_end"] = df["pos_in_bar"] < tf_days
    df["count_days_remaining"] = (tf_days - df["pos_in_bar"]).astype(int)

    # Contract bookkeeping
    df["timestamp"] = df["time_close"]
    df["last_ts_half_open"] = df["time_close"] + _ONE_MS

    out = pd.DataFrame(
        {
            "id": id_val,
            "tf": tf_label,
            "tf_days": int(tf_days),
            "bar_seq": df["bar_seq"].astype(int),
            "time_open": pd.to_datetime(df["time_open"], utc=True),
            "time_close": pd.to_datetime(df["time_close"], utc=True),
            "time_high": pd.to_datetime(df["time_high"], utc=True),
            "time_low": pd.to_datetime(df["time_low"], utc=True),
            "open": df["open_bar"].astype(float),
            "high": df["high_bar"].astype(float),
            "low": df["low_bar"].astype(float),
            "close": df["close_bar"].astype(float),
            "volume": df["vol_bar"].astype(float),
            "market_cap": df["mc_bar"].astype(float),
            "timestamp": pd.to_datetime(df["timestamp"], utc=True),
            "last_ts_half_open": pd.to_datetime(df["last_ts_half_open"], utc=True),
            "pos_in_bar": df["pos_in_bar"].astype(int),
            "is_partial_start": df["is_partial_start"].astype(bool),
            "is_partial_end": df["is_partial_end"].astype(bool),
            "count_days_remaining": df["count_days_remaining"].astype(int),
            "is_missing_days": df["is_missing_days"].astype(bool),
            "count_days": df["pos_in_bar"].astype(int),
            "count_missing_days": df["count_missing_days"].astype(int),
            # builder-owned; left as NaT unless you choose to compute them later
            "first_missing_day": pd.NaT,
            "last_missing_day": pd.NaT,
        }
    )

    out = normalize_output_schema(out)
    out = enforce_ohlc_sanity(out)
    return out


# =============================================================================
# Incremental append builder (with optional carry-forward)
# =============================================================================


def _append_incremental_rows_for_id_tf(
    *,
    db_url: str,
    daily_table: str,
    bars_table: str,
    id_: int,
    tf_days: int,
    tf_label: str,
    daily_max_ts: pd.Timestamp,
    last: dict,
) -> pd.DataFrame:
    """
    Append snapshot rows after last_time_close for one (id, tf).

    CONTRACT:
    - daily loader enforces 1 row per local day
    - carry-forward path uses strict gate + apply_carry_forward (no semantic rewrites)
    """
    last_time_close: pd.Timestamp = last["last_time_close"]
    last_bar_seq: int = int(last["last_bar_seq"])
    last_pos_in_bar: int = int(last["last_pos_in_bar"])

    if daily_max_ts <= last_time_close:
        return pd.DataFrame()

    ts_start = last_time_close + _ONE_MS
    df_new = load_daily_prices_for_id(
        db_url=db_url, daily_table=daily_table, id_=int(id_), ts_start=ts_start
    )
    if df_new.empty:
        return pd.DataFrame()

    cur_bar_seq = last_bar_seq
    cur_pos = last_pos_in_bar

    last_row = load_last_bar_snapshot_row(
        db_url, bars_table, id_=int(id_), tf=tf_label, bar_seq=cur_bar_seq
    )
    if last_row is None:
        return pd.DataFrame()

    prev_snapshot = normalize_output_schema(pd.DataFrame([last_row])).iloc[0].to_dict()
    prev_time_close = pd.to_datetime(prev_snapshot["time_close"], utc=True)
    prev_time_open = pd.to_datetime(prev_snapshot["time_open"], utc=True)

    # tracked local days for missing-days diagnostics
    cur_bar_local_days: list[pd.Timestamp] = []
    cur_bar_start_day_local = prev_time_close.tz_convert(DEFAULT_TZ).date()

    new_rows: list[dict] = []

    for _, d in df_new.iterrows():
        day_ts: pd.Timestamp = pd.to_datetime(d["ts"], utc=True)

        # start new bar if prior was complete
        if cur_pos >= tf_days:
            cur_bar_seq += 1
            cur_pos = 0

            prev_time_open = prev_time_close + _ONE_MS
            cur_bar_local_days = []
            cur_bar_start_day_local = day_ts.tz_convert(DEFAULT_TZ).date()

            # reset snapshot baseline (open/high/low should be carried from this first day)
            prev_snapshot = (
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
                                "market_cap": float(d["market_cap"])
                                if pd.notna(d["market_cap"])
                                else float("nan"),
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

        cur_pos += 1

        snapshot_day_local = day_ts.tz_convert(DEFAULT_TZ).date()
        cur_bar_local_days.append(snapshot_day_local)

        # strict tail continuity for carry-forward gate
        prev_snapshot_day_local = prev_time_close.tz_convert(DEFAULT_TZ).date()
        missing_days_tail_ok = (
            snapshot_day_local
            == (prev_snapshot_day_local + pd.Timedelta(days=1)).date()
        )

        inp = CarryForwardInputs(
            prev_snapshot_day_local=prev_snapshot_day_local,
            snapshot_day_local=snapshot_day_local,
            same_bar_identity=True,  # we only reach here if we did NOT advance bar_seq above
            missing_days_tail_ok=bool(missing_days_tail_ok),
        )

        is_partial_end = cur_pos < tf_days
        count_days_remaining = int(tf_days - cur_pos)

        # compute missing-days diagnostics for this snapshot (incremental only; OK to do per-row)
        miss_diag = compute_missing_days_diagnostics(
            bar_start_day_local=cur_bar_start_day_local,
            snapshot_day_local=snapshot_day_local,
            observed_local_days=cur_bar_local_days,
        )

        # Use shared O(1) updater only when the strict gate passes
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
            out_row["time_open"] = prev_time_open

            out_row["timestamp"] = day_ts
            out_row["last_ts_half_open"] = day_ts + _ONE_MS
            out_row["count_days_remaining"] = int(count_days_remaining)

            # Keep first/last missing day as NaT for now (builder-owned)
            out_row.setdefault("first_missing_day", pd.NaT)
            out_row.setdefault("last_missing_day", pd.NaT)

            out_row = normalize_output_schema(pd.DataFrame([out_row])).iloc[0].to_dict()
            new_rows.append(out_row)

            prev_snapshot = dict(out_row)
            prev_time_close = day_ts
            continue

        # Fallback path (explicit incremental math; contract-equivalent)
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

        day_high = float(d["high"]) if pd.notna(d["high"]) else float("nan")
        day_low = float(d["low"]) if pd.notna(d["low"]) else float("nan")

        # fallback-to-ts for tie timestamps (contract)
        day_th = (
            pd.to_datetime(d["timehigh"], utc=True)
            if pd.notna(d["timehigh"])
            else day_ts
        )
        day_tl = (
            pd.to_datetime(d["timelow"], utc=True) if pd.notna(d["timelow"]) else day_ts
        )

        new_high = prev_high
        new_time_high = prev_time_high
        if pd.isna(new_high) or (pd.notna(day_high) and day_high > new_high):
            new_high = day_high
            new_time_high = day_th
        elif pd.notna(day_high) and pd.notna(new_high) and day_high == new_high:
            if pd.notna(day_th) and (pd.isna(new_time_high) or day_th < new_time_high):
                new_time_high = day_th

        new_low = prev_low
        new_time_low = prev_time_low
        if pd.isna(new_low) or (pd.notna(day_low) and day_low < new_low):
            new_low = day_low
            new_time_low = day_tl
        elif pd.notna(day_low) and pd.notna(new_low) and day_low == new_low:
            if pd.notna(day_tl) and (pd.isna(new_time_low) or day_tl < new_time_low):
                new_time_low = day_tl

        prev_vol = (
            float(prev_snapshot.get("volume"))
            if pd.notna(prev_snapshot.get("volume"))
            else 0.0
        )
        add_vol = float(d["volume"]) if pd.notna(d["volume"]) else 0.0
        new_volume = prev_vol + add_vol

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

        row = {
            "id": int(id_),
            "tf": tf_label,
            "tf_days": int(tf_days),
            "bar_seq": int(cur_bar_seq),
            "time_open": prev_time_open,
            "time_close": day_ts,
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
        }
        row = normalize_output_schema(pd.DataFrame([row])).iloc[0].to_dict()
        new_rows.append(row)

        prev_snapshot = dict(row)
        prev_time_close = day_ts

    df_out = pd.DataFrame(new_rows)
    df_out = normalize_output_schema(df_out)
    df_out = enforce_ohlc_sanity(df_out)
    return df_out


# =============================================================================
# Incremental driver (serial)
# =============================================================================


def refresh_incremental(
    *,
    db_url: str,
    ids: list[int],
    tf_list: list[tuple[int, str]],
    daily_table: str,
    bars_table: str,
    state_table: str,
) -> None:
    start_time = time.time()
    total_combinations = len(ids) * len(tf_list)
    print(
        f"[bars_multi_tf] Incremental: {len(ids)} IDs × {len(tf_list)} TFs = {total_combinations:,} combinations"
    )

    ensure_state_table(db_url, state_table, with_tz=False)

    daily_mm = load_daily_min_max(db_url, daily_table, ids, ts_col='"timestamp"')
    if daily_mm.empty:
        print("[bars_multi_tf] No daily data found for requested ids.")
        return

    mm_map = {int(r["id"]): r for r in daily_mm.to_dict(orient="records")}

    state_df = load_state(db_url, state_table, ids, with_tz=False)
    state_map: dict[tuple[int, str], dict] = {}
    if not state_df.empty:
        for r in state_df.to_dict(orient="records"):
            state_map[(int(r["id"]), str(r["tf"]))] = r

    state_updates: list[dict] = []
    totals = {"upserted": 0, "rebuilds": 0, "appends": 0, "noops": 0, "errors": 0}

    for id_ in ids:
        mm = mm_map.get(int(id_))
        if mm is None:
            continue

        daily_min_ts: pd.Timestamp = mm["daily_min_ts"]
        daily_max_ts: pd.Timestamp = mm["daily_max_ts"]

        for tf_days, tf_label in tf_list:
            key = (int(id_), tf_label)
            st = state_map.get(key)
            last = load_last_snapshot_info(
                db_url, bars_table, id_=int(id_), tf=tf_label
            )

            if st is None and last is None:
                df_full = load_daily_prices_for_id(
                    db_url=db_url, daily_table=daily_table, id_=int(id_)
                )
                bars = build_snapshots_for_id_polars(
                    df_full, tf_days=int(tf_days), tf_label=tf_label
                )
                if not bars.empty:
                    upsert_bars(
                        bars,
                        db_url=db_url,
                        bars_table=bars_table,
                        keep_rejects=_KEEP_REJECTS,
                        rejects_table=_REJECTS_TABLE,
                    )
                    totals["upserted"] += len(bars)
                    totals["rebuilds"] += 1
                    last_bar_seq = int(bars["bar_seq"].max())
                    last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)
                else:
                    last_bar_seq = None
                    last_time_close = None

                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": daily_min_ts,
                        "daily_max_seen": daily_max_ts,
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            daily_min_seen = (
                pd.to_datetime(st["daily_min_seen"], utc=True)
                if st is not None and pd.notna(st.get("daily_min_seen"))
                else daily_min_ts
            )
            daily_max_seen = (
                pd.to_datetime(st["daily_max_seen"], utc=True)
                if st is not None and pd.notna(st.get("daily_max_seen"))
                else daily_max_ts
            )

            if last is None:
                df_full = load_daily_prices_for_id(
                    db_url=db_url, daily_table=daily_table, id_=int(id_)
                )
                bars = build_snapshots_for_id_polars(
                    df_full, tf_days=int(tf_days), tf_label=tf_label
                )
                if not bars.empty:
                    upsert_bars(
                        bars,
                        db_url=db_url,
                        bars_table=bars_table,
                        keep_rejects=_KEEP_REJECTS,
                        rejects_table=_REJECTS_TABLE,
                    )
                    totals["upserted"] += len(bars)
                    totals["rebuilds"] += 1
                    last_bar_seq = int(bars["bar_seq"].max())
                    last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)
                else:
                    last_bar_seq = None
                    last_time_close = None

                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": daily_min_ts,
                        "daily_max_seen": daily_max_ts,
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            if daily_min_ts < daily_min_seen:
                print(
                    f"[bars_multi_tf] Backfill detected: id={id_}, tf={tf_label}, "
                    f"daily_min moved earlier {daily_min_seen} -> {daily_min_ts}. Rebuilding."
                )
                delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=tf_label)
                df_full = load_daily_prices_for_id(
                    db_url=db_url, daily_table=daily_table, id_=int(id_)
                )
                bars = build_snapshots_for_id_polars(
                    df_full, tf_days=int(tf_days), tf_label=tf_label
                )
                if not bars.empty:
                    upsert_bars(
                        bars,
                        db_url=db_url,
                        bars_table=bars_table,
                        keep_rejects=_KEEP_REJECTS,
                        rejects_table=_REJECTS_TABLE,
                    )
                    totals["upserted"] += len(bars)
                    last_bar_seq = int(bars["bar_seq"].max())
                    last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)
                else:
                    last_bar_seq = None
                    last_time_close = None

                totals["rebuilds"] += 1
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": daily_min_ts,
                        "daily_max_seen": daily_max_ts,
                        "last_bar_seq": last_bar_seq,
                        "last_time_close": last_time_close,
                    }
                )
                continue

            if daily_max_ts <= last["last_time_close"]:
                totals["noops"] += 1
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": min(daily_min_seen, daily_min_ts),
                        "daily_max_seen": max(daily_max_seen, daily_max_ts),
                        "last_bar_seq": int(last["last_bar_seq"]),
                        "last_time_close": last["last_time_close"],
                    }
                )
                continue

            try:
                new_rows = _append_incremental_rows_for_id_tf(
                    db_url=db_url,
                    daily_table=daily_table,
                    bars_table=bars_table,
                    id_=int(id_),
                    tf_days=int(tf_days),
                    tf_label=tf_label,
                    daily_max_ts=daily_max_ts,
                    last=last,
                )

                if new_rows.empty:
                    totals["noops"] += 1
                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": tf_label,
                            "daily_min_seen": min(daily_min_seen, daily_min_ts),
                            "daily_max_seen": max(daily_max_seen, daily_max_ts),
                            "last_bar_seq": int(last["last_bar_seq"]),
                            "last_time_close": last["last_time_close"],
                        }
                    )
                    continue

                upsert_bars(
                new_rows,
                db_url=db_url,
                bars_table=bars_table,
                keep_rejects=_KEEP_REJECTS,
                rejects_table=_REJECTS_TABLE,
            )
                totals["upserted"] += len(new_rows)
                totals["appends"] += 1

                last_bar_seq2 = int(new_rows["bar_seq"].max())
                last_time_close2 = pd.to_datetime(
                    new_rows["time_close"].max(), utc=True
                )

                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": min(daily_min_seen, daily_min_ts),
                        "daily_max_seen": max(daily_max_seen, daily_max_ts),
                        "last_bar_seq": last_bar_seq2,
                        "last_time_close": last_time_close2,
                    }
                )
            except Exception as e:
                totals["errors"] += 1
                print(
                    f"[bars_multi_tf] ERROR id={id_} tf={tf_label}: {type(e).__name__}: {e}"
                )
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": min(daily_min_seen, daily_min_ts),
                        "daily_max_seen": max(daily_max_seen, daily_max_ts),
                        "last_bar_seq": int(last["last_bar_seq"]) if last else None,
                        "last_time_close": last["last_time_close"] if last else None,
                    }
                )

    upsert_state(db_url, state_table, state_updates, with_tz=False)

    total_time = time.time() - start_time
    minutes = int(total_time // 60)
    seconds = total_time % 60
    print(
        f"[bars_multi_tf] Incremental complete: upserted={totals['upserted']:,} "
        f"rebuilds={totals['rebuilds']} appends={totals['appends']} "
        f"noops={totals['noops']} errors={totals['errors']} [time: {minutes}m {seconds:.1f}s]"
    )


# =============================================================================
# Incremental driver (PARALLEL across IDs)
# =============================================================================


def _process_single_id_with_all_specs(args) -> tuple[list[dict], dict[str, int]]:
    (
        id_,
        db_url,
        daily_table,
        bars_table,
        state_table,
        tf_list,
        daily_min_ts,
        daily_max_ts,
        state_map,
    ) = args

    state_updates: list[dict] = []
    stats = {
        "id": int(id_),
        "upserted": 0,
        "rebuilds": 0,
        "appends": 0,
        "noops": 0,
        "errors": 0,
    }

    try:
        tfs = [tf_label for _, tf_label in tf_list]
        last_map = load_last_snapshot_info_for_id_tfs(
            db_url=db_url, bars_table=bars_table, id_=int(id_), tfs=tfs
        )

        for tf_days, tf_label in tf_list:
            try:
                key = (int(id_), tf_label)
                st = state_map.get(key)
                last = last_map.get(tf_label)

                daily_min_seen = (
                    pd.to_datetime(st["daily_min_seen"], utc=True)
                    if st is not None and pd.notna(st.get("daily_min_seen"))
                    else daily_min_ts
                )
                daily_max_seen = (
                    pd.to_datetime(st["daily_max_seen"], utc=True)
                    if st is not None and pd.notna(st.get("daily_max_seen"))
                    else daily_max_ts
                )

                if st is None and last is None:
                    df_full = load_daily_prices_for_id(
                        db_url=db_url, daily_table=daily_table, id_=int(id_)
                    )
                    bars = build_snapshots_for_id_polars(
                        df_full, tf_days=int(tf_days), tf_label=tf_label
                    )
                    if not bars.empty:
                        upsert_bars(
                        bars,
                        db_url=db_url,
                        bars_table=bars_table,
                        keep_rejects=_KEEP_REJECTS,
                        rejects_table=_REJECTS_TABLE,
                    )
                        stats["upserted"] += len(bars)
                        stats["rebuilds"] += 1
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(
                            bars["time_close"].max(), utc=True
                        )
                    else:
                        last_bar_seq = None
                        last_time_close = None

                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": tf_label,
                            "daily_min_seen": daily_min_ts,
                            "daily_max_seen": daily_max_ts,
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                if last is None:
                    df_full = load_daily_prices_for_id(
                        db_url=db_url, daily_table=daily_table, id_=int(id_)
                    )
                    bars = build_snapshots_for_id_polars(
                        df_full, tf_days=int(tf_days), tf_label=tf_label
                    )
                    if not bars.empty:
                        upsert_bars(
                        bars,
                        db_url=db_url,
                        bars_table=bars_table,
                        keep_rejects=_KEEP_REJECTS,
                        rejects_table=_REJECTS_TABLE,
                    )
                        stats["upserted"] += len(bars)
                        stats["rebuilds"] += 1
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(
                            bars["time_close"].max(), utc=True
                        )
                    else:
                        last_bar_seq = None
                        last_time_close = None

                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": tf_label,
                            "daily_min_seen": daily_min_ts,
                            "daily_max_seen": daily_max_ts,
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                if daily_min_ts < daily_min_seen:
                    print(
                        f"[bars_multi_tf] Backfill detected: id={id_}, tf={tf_label}, "
                        f"daily_min moved earlier {daily_min_seen} -> {daily_min_ts}. Rebuilding."
                    )
                    delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=tf_label)
                    df_full = load_daily_prices_for_id(
                        db_url=db_url, daily_table=daily_table, id_=int(id_)
                    )
                    bars = build_snapshots_for_id_polars(
                        df_full, tf_days=int(tf_days), tf_label=tf_label
                    )
                    if not bars.empty:
                        upsert_bars(
                        bars,
                        db_url=db_url,
                        bars_table=bars_table,
                        keep_rejects=_KEEP_REJECTS,
                        rejects_table=_REJECTS_TABLE,
                    )
                        stats["upserted"] += len(bars)
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(
                            bars["time_close"].max(), utc=True
                        )
                    else:
                        last_bar_seq = None
                        last_time_close = None

                    stats["rebuilds"] += 1
                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": tf_label,
                            "daily_min_seen": daily_min_ts,
                            "daily_max_seen": daily_max_ts,
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                if daily_max_ts <= last["last_time_close"]:
                    stats["noops"] += 1
                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": tf_label,
                            "daily_min_seen": min(daily_min_seen, daily_min_ts),
                            "daily_max_seen": max(daily_max_seen, daily_max_ts),
                            "last_bar_seq": int(last["last_bar_seq"]),
                            "last_time_close": last["last_time_close"],
                        }
                    )
                    continue

                new_rows = _append_incremental_rows_for_id_tf(
                    db_url=db_url,
                    daily_table=daily_table,
                    bars_table=bars_table,
                    id_=int(id_),
                    tf_days=int(tf_days),
                    tf_label=tf_label,
                    daily_max_ts=daily_max_ts,
                    last=last,
                )
                if new_rows.empty:
                    stats["noops"] += 1
                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": tf_label,
                            "daily_min_seen": min(daily_min_seen, daily_min_ts),
                            "daily_max_seen": max(daily_max_seen, daily_max_ts),
                            "last_bar_seq": int(last["last_bar_seq"]),
                            "last_time_close": last["last_time_close"],
                        }
                    )
                    continue

                upsert_bars(
                new_rows,
                db_url=db_url,
                bars_table=bars_table,
                keep_rejects=_KEEP_REJECTS,
                rejects_table=_REJECTS_TABLE,
            )
                stats["upserted"] += len(new_rows)
                stats["appends"] += 1

                last_bar_seq2 = int(new_rows["bar_seq"].max())
                last_time_close2 = pd.to_datetime(
                    new_rows["time_close"].max(), utc=True
                )
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": min(daily_min_seen, daily_min_ts),
                        "daily_max_seen": max(daily_max_seen, daily_max_ts),
                        "last_bar_seq": last_bar_seq2,
                        "last_time_close": last_time_close2,
                    }
                )

            except Exception as e:
                stats["errors"] += 1
                print(
                    f"[bars_multi_tf] ERROR id={id_} tf={tf_label}: {type(e).__name__}: {e}"
                )
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": tf_label,
                        "daily_min_seen": min(daily_min_seen, daily_min_ts),
                        "daily_max_seen": max(daily_max_seen, daily_max_ts),
                        "last_bar_seq": st.get("last_bar_seq")
                        if st is not None
                        else None,
                        "last_time_close": (
                            pd.to_datetime(st["last_time_close"], utc=True)
                            if st is not None and pd.notna(st.get("last_time_close"))
                            else None
                        ),
                    }
                )

    except Exception as e:
        stats["errors"] += 1
        print(f"[bars_multi_tf] FATAL ERROR id={id_}: {type(e).__name__}: {e}")

    return state_updates, stats


def refresh_incremental_parallel(
    *,
    db_url: str,
    ids: list[int],
    tf_list: list[tuple[int, str]],
    daily_table: str,
    bars_table: str,
    state_table: str,
    num_processes: int,
) -> None:
    start_time = time.time()
    total_combinations = len(ids) * len(tf_list)
    print(
        f"[bars_multi_tf] Incremental (parallel): {len(ids)} IDs × {len(tf_list)} TFs = {total_combinations:,} combinations"
    )

    ensure_state_table(db_url, state_table, with_tz=False)

    daily_mm = load_daily_min_max(db_url, daily_table, ids, ts_col='"timestamp"')
    if daily_mm.empty:
        print("[bars_multi_tf] No daily data found for requested ids.")
        return

    mm_map = {int(r["id"]): r for r in daily_mm.to_dict(orient="records")}

    state_df = load_state(db_url, state_table, ids, with_tz=False)
    state_map: dict[tuple[int, str], dict] = {}
    if not state_df.empty:
        for r in state_df.to_dict(orient="records"):
            state_map[(int(r["id"]), str(r["tf"]))] = r

    tasks = []
    for id_ in ids:
        mm = mm_map.get(int(id_))
        if mm is None:
            continue
        tasks.append(
            (
                int(id_),
                db_url,
                daily_table,
                bars_table,
                state_table,
                tf_list,
                mm["daily_min_ts"],
                mm["daily_max_ts"],
                state_map,
            )
        )

    print(
        f"[bars_multi_tf] Processing {len(tasks)} IDs with {num_processes} workers..."
    )

    # Use orchestrator for parallel execution with progress tracking
    config = OrchestratorConfig(num_processes=num_processes, maxtasksperchild=50)
    progress = ProgressTracker(
        total=len(tasks), log_interval=5, prefix="[bars_multi_tf]"
    )
    orchestrator = MultiprocessingOrchestrator(
        worker_fn=_process_single_id_with_all_specs,
        config=config,
        progress_callback=progress.update,
    )

    all_state_updates, totals = orchestrator.execute(
        tasks,
        stats_template={
            "upserted": 0,
            "rebuilds": 0,
            "appends": 0,
            "noops": 0,
            "errors": 0,
        },
    )

    upsert_state(db_url, state_table, all_state_updates, with_tz=False)

    total_time = time.time() - start_time
    minutes = int(total_time // 60)
    seconds = total_time % 60
    print(
        f"[bars_multi_tf] Incremental complete: upserted={totals['upserted']:,} "
        f"rebuilds={totals['rebuilds']} appends={totals['appends']} "
        f"noops={totals['noops']} errors={totals['errors']} [time: {minutes}m {seconds:.1f}s]"
    )


# =============================================================================
# Full rebuild (all snapshots)
# =============================================================================


def refresh_full_rebuild(
    *,
    db_url: str,
    ids: list[int],
    tf_list: list[tuple[int, str]],
    daily_table: str,
    bars_table: str,
    state_table: str,
) -> None:
    start_time = time.time()
    total_combinations = len(ids) * len(tf_list)
    running_total = 0
    combo_count = 0

    print(
        f"[bars_multi_tf] Full rebuild: {len(ids)} IDs × {len(tf_list)} TFs = {total_combinations:,} combinations"
    )
    ensure_state_table(db_url, state_table, with_tz=False)

    for id_ in ids:
        df_id = load_daily_prices_for_id(
            db_url=db_url, daily_table=daily_table, id_=int(id_)
        )
        if df_id.empty:
            combo_count += len(tf_list)
            continue
        for tf_days, tf_label in tf_list:
            combo_count += 1
            delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=tf_label)
            delete_state_for_id_tf(db_url, state_table, id_=int(id_), tf=tf_label)
            bars = build_snapshots_for_id_polars(
                df_id, tf_days=int(tf_days), tf_label=tf_label
            )
            if not bars.empty:
                num_rows = len(bars)
                running_total += num_rows
                upsert_bars(
                        bars,
                        db_url=db_url,
                        bars_table=bars_table,
                        keep_rejects=_KEEP_REJECTS,
                        rejects_table=_REJECTS_TABLE,
                    )
                last_bar_seq = int(bars["bar_seq"].max())
                last_time_close = pd.to_datetime(
                    bars["time_close"].max(), utc=True
                ).tz_convert(None)
                daily_min_seen = pd.to_datetime(df_id["ts"].min(), utc=True)
                daily_max_seen = pd.to_datetime(df_id["ts"].max(), utc=True)
                upsert_state(
                    db_url,
                    state_table,
                    [
                        {
                            "id": int(id_),
                            "tf": tf_label,
                            "daily_min_seen": daily_min_seen,
                            "daily_max_seen": daily_max_seen,
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    ],
                    with_tz=False,
                )

                period_start = bars["time_open"].min().strftime("%Y-%m-%d")
                period_end = bars["time_close"].max().strftime("%Y-%m-%d")
                elapsed = time.time() - start_time
                pct = (
                    (combo_count / total_combinations) * 100
                    if total_combinations > 0
                    else 0
                )

                print(
                    f"[bars_multi_tf] ID={id_}, TF={tf_label}, period={period_start} to {period_end}: "
                    f"upserted {num_rows:,} rows ({running_total:,} total, {pct:.1f}%) [elapsed: {elapsed:.1f}s]"
                )

    total_time = time.time() - start_time
    minutes = int(total_time // 60)
    seconds = total_time % 60
    print(
        f"[bars_multi_tf] Full rebuild complete: {running_total:,} total rows [time: {minutes}m {seconds:.1f}s]"
    )


# =============================================================================
# CLI
# =============================================================================


def main(argv: Sequence[str] | None = None) -> None:
    # Use shared CLI parser (saves ~15 lines of boilerplate)
    ap = create_bar_builder_argument_parser(
        description="Build tf_day (multi_tf) price bars (append-only snapshots).",
        default_daily_table=DEFAULT_DAILY_TABLE,
        default_bars_table=DEFAULT_BARS_TABLE,
        default_state_table=DEFAULT_STATE_TABLE,
        include_tz=False,  # multi_tf doesn't use timezone
        include_fail_on_gaps=False,
    )

    # Add builder-specific arguments
    ap.add_argument("--include-non-canonical", action="store_true")
    ap.add_argument(
        "--keep-rejects",
        action="store_true",
        help="Log OHLC violations to rejects table before repair",
    )
    ap.add_argument(
        "--rejects-table",
        default="cmc_price_bars_multi_tf_rejects",
        help="Table name for rejects (default: cmc_price_bars_multi_tf_rejects)",
    )

    args = ap.parse_args(list(argv) if argv is not None else None)

    db_url = resolve_db_url(args.db_url)
    ids = parse_ids(args.ids)
    if ids == "all":
        ids = load_all_ids(db_url, args.daily_table)

    tf_list = load_tf_list_from_dim_timeframe(
        db_url=db_url, include_non_canonical=args.include_non_canonical
    )
    print(f"[bars_multi_tf] TF list size={len(tf_list)}: {[t for _, t in tf_list]}")

    # Set module-level state for reject logging
    global _KEEP_REJECTS, _REJECTS_TABLE, _DB_URL
    _KEEP_REJECTS = args.keep_rejects
    _REJECTS_TABLE = args.rejects_table
    _DB_URL = db_url

    # Create rejects table if --keep-rejects flag is set
    if args.keep_rejects:
        ddl = create_rejects_table_ddl(args.rejects_table, schema="public")
        engine = get_engine(db_url)
        with engine.begin() as conn:
            conn.execute(text(ddl))
        print(f"[bars_multi_tf] Reject logging enabled: table={args.rejects_table}")

    if args.full_rebuild:
        refresh_full_rebuild(
            db_url=db_url,
            ids=ids,
            tf_list=tf_list,
            daily_table=args.daily_table,
            bars_table=args.bars_table,
            state_table=args.state_table,
        )
        return

    nproc = resolve_num_processes(args.num_processes)
    if nproc > 1:
        refresh_incremental_parallel(
            db_url=db_url,
            ids=ids,
            tf_list=tf_list,
            daily_table=args.daily_table,
            bars_table=args.bars_table,
            state_table=args.state_table,
            num_processes=nproc,
        )
    else:
        refresh_incremental(
            db_url=db_url,
            ids=ids,
            tf_list=tf_list,
            daily_table=args.daily_table,
            bars_table=args.bars_table,
            state_table=args.state_table,
        )


if __name__ == "__main__":
    main()
