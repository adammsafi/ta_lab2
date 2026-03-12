#!/usr/bin/env python
"""
refresh_cross_asset_corr.py

Computes pairwise rolling Pearson and Spearman correlation (with p-values) between
all asset pairs per timeframe, across 4 trailing windows (30, 60, 90, 252 bars).

Data source: returns_bars_multi_tf (ret_arith WHERE roll = FALSE)
Output table: cross_asset_corr (id_a, id_b, ts, tf, window, pearson_r, pearson_p,
              spearman_r, spearman_p, n_obs)
State table:  cross_asset_corr_state (watermark tracking per id_a, id_b, tf)
Materialized: corr_latest refreshed after all TF writes

Pair ordering: id_a < id_b always (matches CHECK constraint on cross_asset_corr).
NULL policy: pearson_r/p and spearman_r/p are NULL when intersection of non-null
             returns < window size. n_obs is always populated.

Usage:
    python -m ta_lab2.scripts.desc_stats.refresh_cross_asset_corr --ids all --tf 1D
    python -m ta_lab2.scripts.desc_stats.refresh_cross_asset_corr --ids 1,52 --tf 1D --dry-run
    python -m ta_lab2.scripts.desc_stats.refresh_cross_asset_corr --full-rebuild --workers 4

Spyder run example:
runfile(
  r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\desc_stats\\refresh_cross_asset_corr.py",
  wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2",
  args="--ids 1,52 --tf 1D"
)
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from multiprocessing import Pool
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.refresh_utils import parse_ids, resolve_db_url
from ta_lab2.time.dim_timeframe import list_tfs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WINDOWS: List[int] = [30, 60, 90, 252]
TABLE_NAME = "cross_asset_corr"
STATE_TABLE = "cross_asset_corr_state"
SOURCE_TABLE = "returns_bars_multi_tf"
MAT_VIEW = "public.corr_latest"

_PRINT_PREFIX = "cross_corr"


def _print(msg: str) -> None:
    print(f"[{_PRINT_PREFIX}] {msg}")


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_pairwise_rolling_corr(
    ret_a: pd.Series,
    ret_b: pd.Series,
    window: int,
    ts_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Compute rolling Pearson and Spearman correlation between two return series.

    Args:
        ret_a: Return series for asset A, aligned to ts_index
        ret_b: Return series for asset B, aligned to ts_index
        window: Rolling window size (bars)
        ts_index: Timestamp index for output DataFrame

    Returns:
        DataFrame indexed by ts_index with columns:
            pearson_r, pearson_p, spearman_r, spearman_p, n_obs
        NULL (None) when intersection of non-null values < window.
        n_obs is always populated (count of valid overlapping observations).
    """
    n = len(ts_index)
    pearson_r_arr: List[Optional[float]] = []
    pearson_p_arr: List[Optional[float]] = []
    spearman_r_arr: List[Optional[float]] = []
    spearman_p_arr: List[Optional[float]] = []
    n_obs_arr: List[Optional[int]] = []

    a_vals_full = ret_a.values
    b_vals_full = ret_b.values

    for i in range(n):
        if i < window - 1:
            # Insufficient history — no correlation possible yet
            pearson_r_arr.append(None)
            pearson_p_arr.append(None)
            spearman_r_arr.append(None)
            spearman_p_arr.append(None)
            n_obs_arr.append(None)
            continue

        start = i - window + 1
        a_slice = a_vals_full[start : i + 1]
        b_slice = b_vals_full[start : i + 1]

        # Compute intersection mask (both non-null/non-nan)
        mask = ~(pd.isna(a_slice) | pd.isna(b_slice))
        n_valid = int(mask.sum())
        n_obs_arr.append(n_valid)

        if n_valid < window:
            # Insufficient valid intersection
            pearson_r_arr.append(None)
            pearson_p_arr.append(None)
            spearman_r_arr.append(None)
            spearman_p_arr.append(None)
            continue

        a_clean = a_slice[mask].astype(float)
        b_clean = b_slice[mask].astype(float)

        # Pearson
        try:
            pr_result = pearsonr(a_clean, b_clean)
            pearson_r_arr.append(float(pr_result.statistic))
            pearson_p_arr.append(float(pr_result.pvalue))
        except Exception:
            pearson_r_arr.append(None)
            pearson_p_arr.append(None)

        # Spearman -- use named tuple attributes (.statistic, .pvalue)
        try:
            sr_result = spearmanr(a_clean, b_clean)
            spearman_r_arr.append(float(sr_result.statistic))
            spearman_p_arr.append(float(sr_result.pvalue))
        except Exception:
            spearman_r_arr.append(None)
            spearman_p_arr.append(None)

    return pd.DataFrame(
        {
            "pearson_r": pearson_r_arr,
            "pearson_p": pearson_p_arr,
            "spearman_r": spearman_r_arr,
            "spearman_p": spearman_p_arr,
            "n_obs": n_obs_arr,
        },
        index=ts_index,
    )


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _get_engine(db_url: str):
    """NullPool engine for single-process use."""
    return create_engine(db_url, future=True, poolclass=NullPool)


def _load_all_asset_ids(engine, ids_filter: Optional[List[int]]) -> List[int]:
    """Load asset IDs with pipeline_tier = 1, or filter to provided list."""
    with engine.connect() as conn:
        if ids_filter is None:
            rows = conn.execute(
                text(
                    "SELECT id FROM public.dim_assets WHERE pipeline_tier = 1 ORDER BY id"
                )
            ).fetchall()
            return [r[0] for r in rows]
        else:
            return sorted(ids_filter)


def _load_tf_list(engine, tf_filter: Optional[str]) -> List[str]:
    """Return list of timeframes to process."""
    if tf_filter is not None:
        return [tf_filter]
    # Use list_tfs which defaults to canonical_only=True
    from ta_lab2.time.dim_timeframe import list_tfs as _list_tfs

    return _list_tfs(
        engine.url.render_as_string(hide_password=False), canonical_only=True
    )


def _load_returns_wide(
    engine,
    tf: str,
    ids: List[int],
    start_ts: Optional[pd.Timestamp],
) -> pd.DataFrame:
    """
    Load ret_arith (roll=FALSE) for all ids in one query, pivot to wide format.

    Returns DataFrame with ts as DatetimeIndex, columns = asset id (int).
    Note: returns_bars_multi_tf uses "timestamp" column (reserved word, must be quoted).
    """
    params: Dict = {"tf": tf, "ids": ids}
    where_parts = ["tf = :tf", "roll = FALSE", "id = ANY(:ids)"]

    if start_ts is not None:
        where_parts.append('"timestamp" >= :start_ts')
        params["start_ts"] = start_ts

    where_clause = " AND ".join(where_parts)
    sql = text(
        f'SELECT id, "timestamp", ret_arith FROM public.{SOURCE_TABLE} '
        f'WHERE {where_clause} ORDER BY "timestamp"'
    )

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if df.empty:
        return pd.DataFrame()

    # Fix tz-aware timestamp (pandas pitfall: use pd.to_datetime with utc=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["ret_arith"] = df["ret_arith"].astype(float)

    # Pivot: timestamp as index, id as columns
    wide = df.pivot(index="timestamp", columns="id", values="ret_arith")
    # Fix tz-aware timestamp: use tz_convert if already tz-aware, tz_localize if naive
    # (MEMORY.md: series.values on tz-aware returns tz-NAIVE numpy on Windows;
    # use tz_localize/tz_convert on DatetimeIndex instead)
    if wide.index.tz is None:
        wide.index = wide.index.tz_localize("UTC")
    else:
        wide.index = wide.index.tz_convert("UTC")
    wide.index.name = "ts"
    wide.sort_index(inplace=True)

    return wide


# ---------------------------------------------------------------------------
# State / watermark helpers
# ---------------------------------------------------------------------------


def _load_watermarks(engine, id_a: int, id_b: int, tf: str) -> Optional[pd.Timestamp]:
    """Return last_timestamp from state table for this pair+tf, or None."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"SELECT last_timestamp FROM public.{STATE_TABLE} "
                "WHERE id_a = :id_a AND id_b = :id_b AND tf = :tf"
            ),
            {"id_a": id_a, "id_b": id_b, "tf": tf},
        ).fetchone()
    if row is None or row[0] is None:
        return None
    ts = pd.Timestamp(row[0])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def _load_all_watermarks(
    engine, pairs: List[Tuple[int, int]], tf: str
) -> Dict[Tuple[int, int], Optional[pd.Timestamp]]:
    """Bulk-load watermarks for all pairs at once."""
    if not pairs:
        return {}

    id_a_list = [p[0] for p in pairs]
    id_b_list = [p[1] for p in pairs]

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT id_a, id_b, last_timestamp FROM public.{STATE_TABLE} "
                "WHERE id_a = ANY(:id_a_list) AND id_b = ANY(:id_b_list) AND tf = :tf"
            ),
            {"id_a_list": id_a_list, "id_b_list": id_b_list, "tf": tf},
        ).fetchall()

    wm_map: Dict[Tuple[int, int], Optional[pd.Timestamp]] = {p: None for p in pairs}
    for row in rows:
        key = (row[0], row[1])
        if key in wm_map and row[2] is not None:
            ts = pd.Timestamp(row[2])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            wm_map[key] = ts
    return wm_map


def _update_state(conn, id_a: int, id_b: int, tf: str, last_ts: pd.Timestamp) -> None:
    """Upsert the watermark in state table."""
    conn.execute(
        text(
            f"INSERT INTO public.{STATE_TABLE} (id_a, id_b, tf, last_timestamp, updated_at) "
            "VALUES (:id_a, :id_b, :tf, :last_ts, now()) "
            "ON CONFLICT (id_a, id_b, tf) DO UPDATE "
            "SET last_timestamp = EXCLUDED.last_timestamp, updated_at = now()"
        ),
        {"id_a": id_a, "id_b": id_b, "tf": tf, "last_ts": last_ts},
    )


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def _write_corr_rows(
    conn,
    rows_df: pd.DataFrame,
    id_a: int,
    id_b: int,
    tf: str,
    windows: List[int],
    start_ts: Optional[pd.Timestamp],
) -> int:
    """
    Write correlation rows for one pair using scoped DELETE + INSERT.

    rows_df has columns: ts, window, pearson_r, pearson_p, spearman_r, spearman_p, n_obs
    Deletes existing rows for this pair/tf with ts >= start_ts (or all if full rebuild).
    Returns number of rows inserted.
    """
    if rows_df.empty:
        return 0

    # Scoped DELETE
    if start_ts is not None:
        conn.execute(
            text(
                f"DELETE FROM public.{TABLE_NAME} "
                "WHERE id_a = :id_a AND id_b = :id_b AND tf = :tf AND ts >= :start_ts"
            ),
            {"id_a": id_a, "id_b": id_b, "tf": tf, "start_ts": start_ts},
        )
    else:
        conn.execute(
            text(
                f"DELETE FROM public.{TABLE_NAME} "
                "WHERE id_a = :id_a AND id_b = :id_b AND tf = :tf"
            ),
            {"id_a": id_a, "id_b": id_b, "tf": tf},
        )

    # Build insert records
    records = []
    for _, row in rows_df.iterrows():
        ts_val = row["ts"]
        if hasattr(ts_val, "to_pydatetime"):
            ts_val = ts_val.to_pydatetime()
        records.append(
            {
                "id_a": id_a,
                "id_b": id_b,
                "ts": ts_val,
                "tf": tf,
                "window": int(row["window"]),
                "pearson_r": _to_none(row.get("pearson_r")),
                "pearson_p": _to_none(row.get("pearson_p")),
                "spearman_r": _to_none(row.get("spearman_r")),
                "spearman_p": _to_none(row.get("spearman_p")),
                "n_obs": _to_none_int(row.get("n_obs")),
            }
        )

    if not records:
        return 0

    conn.execute(
        text(
            f"INSERT INTO public.{TABLE_NAME} "
            '(id_a, id_b, ts, tf, "window", pearson_r, pearson_p, '
            "spearman_r, spearman_p, n_obs) "
            "VALUES (:id_a, :id_b, :ts, :tf, :window, :pearson_r, :pearson_p, "
            ":spearman_r, :spearman_p, :n_obs)"
        ),
        records,
    )

    return len(records)


def _to_none(v) -> Optional[float]:
    """Convert NaN/None to None, otherwise float."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _to_none_int(v) -> Optional[int]:
    """Convert NaN/None to None, otherwise int."""
    if v is None:
        return None
    try:
        f = float(v)
        if np.isnan(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Worker: process one TF
# ---------------------------------------------------------------------------


@dataclass
class TFResult:
    tf: str
    n_pairs: int
    n_rows: int
    success: bool
    error_msg: Optional[str]


def _worker_tf(
    args: Tuple,
) -> TFResult:
    """
    Worker function for TF-level parallelism.
    Processes all pairs for one TF.
    """
    tf, ids, windows, db_url, full_rebuild, dry_run = args
    engine = _get_engine(db_url)

    try:
        result = _process_tf(engine, tf, ids, windows, full_rebuild, dry_run)
        return result
    except Exception as exc:
        return TFResult(tf=tf, n_pairs=0, n_rows=0, success=False, error_msg=str(exc))
    finally:
        engine.dispose()


def _process_tf(
    engine,
    tf: str,
    ids: List[int],
    windows: List[int],
    full_rebuild: bool,
    dry_run: bool,
) -> TFResult:
    """Process all pairs for one TF: load data, compute correlations, write."""
    _print(f"tf={tf}: starting (full_rebuild={full_rebuild}, dry_run={dry_run})")

    # Generate canonical pairs: id_a < id_b
    pairs: List[Tuple[int, int]] = [(a, b) for a in ids for b in ids if a < b]
    if not pairs:
        _print(f"tf={tf}: no pairs (need >= 2 assets)")
        return TFResult(tf=tf, n_pairs=0, n_rows=0, success=True, error_msg=None)

    _print(f"tf={tf}: {len(pairs)} pairs x {len(windows)} windows")

    # Load watermarks for all pairs
    if full_rebuild:
        wm_map: Dict[Tuple[int, int], Optional[pd.Timestamp]] = {p: None for p in pairs}
    else:
        wm_map = _load_all_watermarks(engine, pairs, tf)

    # Determine global start_ts for data loading (min watermark - max_window bars)
    max_window = max(windows)
    global_min_wm: Optional[pd.Timestamp] = None
    for wm in wm_map.values():
        if wm is not None:
            if global_min_wm is None or wm < global_min_wm:
                global_min_wm = wm

    # Load data: go back max_window bars before earliest watermark
    # For incremental: start from (min_watermark - max_window * estimated_bar_days)
    # For safety, load data from min_watermark minus a generous lookback
    if global_min_wm is not None:
        # Load from max_window bars before the earliest watermark to recompute overlap
        # We'll load all data and slice in Python; the WHERE ts >= start is a DB hint
        # to avoid loading all historical data every run
        # Conservative: go back 2 * max_window days before earliest watermark
        from ta_lab2.time.dim_timeframe import get_tf_days

        try:
            tf_days = get_tf_days(tf, engine.url.render_as_string(hide_password=False))
        except Exception:
            tf_days = 1
        lookback_days = max_window * tf_days * 2
        data_start_ts = global_min_wm - pd.Timedelta(days=lookback_days)
    else:
        data_start_ts = None  # Full load

    # Load returns wide
    wide_df = _load_returns_wide(engine, tf, ids, data_start_ts)

    if wide_df.empty:
        _print(f"tf={tf}: no returns data found, skipping")
        return TFResult(
            tf=tf, n_pairs=len(pairs), n_rows=0, success=True, error_msg=None
        )

    ts_index = wide_df.index
    total_rows = 0

    for id_a, id_b in pairs:
        # Get return series for each asset
        if id_a not in wide_df.columns or id_b not in wide_df.columns:
            continue

        ret_a = wide_df[id_a]
        ret_b = wide_df[id_b]

        wm = wm_map.get((id_a, id_b))

        # Determine the timestamp after which we need to compute
        # For incremental: compute from (watermark + 1 bar) onward
        # Use ts_index to find position
        if wm is not None and not full_rebuild:
            # Find ts_index entries > watermark
            new_ts_mask = ts_index > wm
            if not new_ts_mask.any():
                continue  # No new data for this pair
            compute_start_ts = ts_index[new_ts_mask][0]
        else:
            compute_start_ts = ts_index[0] if len(ts_index) > 0 else None

        if compute_start_ts is None:
            continue

        # Collect rows for all windows
        all_window_rows: List[pd.DataFrame] = []

        for window in windows:
            corr_df = compute_pairwise_rolling_corr(ret_a, ret_b, window, ts_index)
            # compute_pairwise_rolling_corr returns DataFrame indexed by ts_index
            # reset_index() converts the DatetimeIndex (named "ts") to a column
            corr_df = corr_df.reset_index()
            # The index column name comes from ts_index.name; ensure it's called "ts"
            if "ts" not in corr_df.columns:
                # Rename whatever the index column ended up as
                idx_cols = [
                    c
                    for c in corr_df.columns
                    if c
                    not in (
                        "pearson_r",
                        "pearson_p",
                        "spearman_r",
                        "spearman_p",
                        "n_obs",
                    )
                ]
                if idx_cols:
                    corr_df.rename(columns={idx_cols[0]: "ts"}, inplace=True)

            # Only keep rows from compute_start_ts onward
            corr_df = corr_df[corr_df["ts"] >= compute_start_ts].copy()
            corr_df["window"] = window
            all_window_rows.append(corr_df)

        if not all_window_rows:
            continue

        combined_df = pd.concat(all_window_rows, ignore_index=True)

        if combined_df.empty:
            continue

        if dry_run:
            _print(
                f"  [dry-run] ({id_a},{id_b}) tf={tf}: would write "
                f"{len(combined_df)} rows"
            )
            total_rows += len(combined_df)
            continue

        # Write with scoped DELETE + INSERT
        with engine.begin() as conn:
            n_written = _write_corr_rows(
                conn=conn,
                rows_df=combined_df,
                id_a=id_a,
                id_b=id_b,
                tf=tf,
                windows=windows,
                start_ts=compute_start_ts
                if (wm is not None and not full_rebuild)
                else None,
            )
            total_rows += n_written

            # Update watermark
            if n_written > 0 and len(ts_index) > 0:
                _update_state(conn, id_a, id_b, tf, ts_index[-1])

    _print(f"tf={tf}: done - {total_rows} rows written for {len(pairs)} pairs")
    return TFResult(
        tf=tf, n_pairs=len(pairs), n_rows=total_rows, success=True, error_msg=None
    )


# ---------------------------------------------------------------------------
# Materialized view refresh
# ---------------------------------------------------------------------------


def _refresh_materialized_view(db_url: str) -> None:
    """Refresh corr_latest materialized view (CONCURRENTLY if possible)."""
    engine = _get_engine(db_url)
    try:
        with engine.begin() as conn:
            _print(f"Refreshing materialized view {MAT_VIEW} CONCURRENTLY...")
            conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {MAT_VIEW}"))
            _print(f"Materialized view {MAT_VIEW} refreshed (CONCURRENTLY).")
    except Exception as exc:
        _print(
            f"CONCURRENTLY refresh failed ({exc}); "
            f"falling back to non-concurrent refresh..."
        )
        # Fall back: non-concurrent (works even on empty view)
        try:
            with engine.begin() as conn:
                conn.execute(text(f"REFRESH MATERIALIZED VIEW {MAT_VIEW}"))
                _print(f"Materialized view {MAT_VIEW} refreshed (non-concurrent).")
        except Exception as exc2:
            _print(f"WARNING: Materialized view refresh failed: {exc2}")
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute pairwise rolling Pearson+Spearman correlation for all asset pairs "
            "per timeframe and write to cross_asset_corr."
        )
    )
    parser.add_argument(
        "--ids",
        default="all",
        help="Comma-separated asset IDs or 'all' (default: all).",
    )
    parser.add_argument(
        "--tf",
        default=None,
        help="Single TF to process, e.g. '1D' (default: all canonical TFs).",
    )
    parser.add_argument(
        "--windows",
        default="30,60,90,252",
        help="Comma-separated window sizes in bars (default: 30,60,90,252).",
    )
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Ignore watermarks and recompute all history (default: incremental).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing to DB.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue processing other TFs if one fails (default: stop on error).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel TF workers (default: 4).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (or set TARGET_DB_URL env var).",
    )
    args = parser.parse_args()

    t_start = time.time()

    # Resolve DB URL
    db_url = resolve_db_url(args.db_url)

    # Parse windows
    try:
        windows: List[int] = [
            int(w.strip()) for w in args.windows.split(",") if w.strip()
        ]
    except ValueError as exc:
        raise SystemExit(f"ERROR: Invalid --windows format: {args.windows}") from exc

    if not windows:
        raise SystemExit("ERROR: --windows must not be empty.")

    _print(
        f"windows={windows}, full_rebuild={args.full_rebuild}, dry_run={args.dry_run}"
    )

    # Parse asset IDs
    engine = _get_engine(db_url)
    ids_raw = parse_ids(args.ids, db_url)
    ids: List[int] = _load_all_asset_ids(engine, ids_raw)
    engine.dispose()

    _print(f"Assets: {len(ids)} IDs")

    if len(ids) < 2:
        _print("Need at least 2 assets to compute pairwise correlation. Exiting.")
        return

    # Determine TF list
    engine2 = _get_engine(db_url)
    if args.tf is not None:
        tf_list = [args.tf]
    else:
        tf_list = list_tfs(db_url, canonical_only=True)
    engine2.dispose()

    _print(f"Timeframes: {tf_list}")

    # Canonical pairs count
    n_pairs = len(ids) * (len(ids) - 1) // 2
    _print(f"Pairs: {n_pairs} (N*(N-1)/2 for N={len(ids)})")

    # Build worker args
    worker_args = [
        (tf, ids, windows, db_url, args.full_rebuild, args.dry_run) for tf in tf_list
    ]

    # Run workers
    results: List[TFResult] = []

    if args.workers > 1 and len(tf_list) > 1:
        with Pool(processes=min(args.workers, len(tf_list))) as pool:
            for result in pool.imap_unordered(_worker_tf, worker_args):
                results.append(result)
                if not result.success:
                    _print(f"tf={result.tf}: ERROR - {result.error_msg}")
                    if not args.continue_on_error:
                        pool.terminate()
                        raise RuntimeError(f"TF {result.tf} failed: {result.error_msg}")
    else:
        for wa in worker_args:
            result = _worker_tf(wa)
            results.append(result)
            if not result.success:
                _print(f"tf={result.tf}: ERROR - {result.error_msg}")
                if not args.continue_on_error:
                    raise RuntimeError(f"TF {result.tf} failed: {result.error_msg}")

    # Summary
    total_rows = sum(r.n_rows for r in results)
    n_success = sum(1 for r in results if r.success)
    n_fail = sum(1 for r in results if not r.success)

    _print(
        f"Completed: {n_success}/{len(results)} TFs OK, "
        f"{n_fail} failed, {total_rows} total rows written"
    )

    # Refresh materialized view (unless dry-run)
    if not args.dry_run:
        _refresh_materialized_view(db_url)
    else:
        _print("[dry-run] Skipping materialized view refresh.")

    elapsed = time.time() - t_start
    _print(f"All done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
