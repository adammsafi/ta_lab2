from __future__ import annotations

r"""
refresh_cmc_asset_stats.py

Per-asset rolling descriptive statistics refresh script.

Computes for each (id, tf) pair across 4 trailing windows (30, 60, 90, 252 bars):
  - mean_ret_{W}        : rolling mean of arithmetic returns
  - std_ret_{W}         : rolling std dev of arithmetic returns (ddof=1)
  - sharpe_raw_{W}      : (mean_ret - rf) / std_ret
  - sharpe_ann_{W}      : sharpe_raw * sqrt(365.0 / tf_days)
  - skew_{W}            : rolling skewness
  - kurt_fisher_{W}     : rolling kurtosis, Fisher/excess convention (normal=0)
  - kurt_pearson_{W}    : kurt_fisher + 3.0, Pearson convention (normal=3)
  - max_dd_window_{W}   : rolling max drawdown within trailing W bars

Non-windowed columns:
  - max_dd_from_ath     : expanding drawdown from all-time-high (always <= 0)
  - rf_rate             : risk-free rate constant used in Sharpe computation

NULL policy: min_periods=window ensures NULLs appear for the first (window-1) bars.
No partial windows.

Source table: cmc_returns_bars_multi_tf (roll=FALSE, canonical bars only)
Target table: cmc_asset_stats (PK: id, ts, tf)
State table:  cmc_asset_stats_state (watermark per id/tf)

Usage:
    python -m ta_lab2.scripts.desc_stats.refresh_cmc_asset_stats --ids all --tf 1D
    python -m ta_lab2.scripts.desc_stats.refresh_cmc_asset_stats --ids 1,2 --tf 1D --full-rebuild
    python -m ta_lab2.scripts.desc_stats.refresh_cmc_asset_stats --ids all --workers 4

Spyder run example:
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\desc_stats\refresh_cmc_asset_stats.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--ids 1 --tf 1D"
)
"""

import argparse
import math
import time
from dataclasses import dataclass
from functools import partial
from multiprocessing import Pool
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.refresh_utils import parse_ids, resolve_db_url
from ta_lab2.time.dim_timeframe import DimTimeframe, get_tf_days

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WINDOWS: List[int] = [30, 60, 90, 252]
DEFAULT_RF: float = 0.0
TABLE_NAME = "cmc_asset_stats"
STATE_TABLE = "cmc_asset_stats_state"
SOURCE_TABLE = "cmc_returns_bars_multi_tf"

_PRINT_PREFIX = "asset_stats"


def _print(msg: str) -> None:
    print(f"[{_PRINT_PREFIX}] {msg}")


# ---------------------------------------------------------------------------
# Rolling drawdown helpers
# ---------------------------------------------------------------------------


def _mdd(arr: np.ndarray) -> float:
    """
    Compute max drawdown within a window of arithmetic returns.

    Returns a negative fraction (or 0.0 if no drawdown).
    """
    eq = np.cumprod(1.0 + arr)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return float(np.min(dd))


def _rolling_max_drawdown(ret_series: pd.Series, window: int) -> pd.Series:
    """
    Compute rolling max drawdown over a trailing window of bars.

    Uses min_periods=window so values are NULL until a full window is available.
    Returns a Series of negative fractions.
    """
    return ret_series.rolling(window=window, min_periods=window).apply(_mdd, raw=True)


def _current_drawdown_from_ath(ret_series: pd.Series) -> pd.Series:
    """
    Compute expanding drawdown from all-time-high (ATH).

    eq / ATH - 1  (always <= 0 except on new ATHs where it's 0.0)
    """
    eq = (1.0 + ret_series.fillna(0.0)).cumprod()
    ath = eq.cummax()
    return eq / ath - 1.0


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_asset_stats(
    df: pd.DataFrame,
    tf_days: int,
    windows: List[int],
    rf: float,
) -> pd.DataFrame:
    """
    Compute rolling descriptive statistics for one (id, tf) time series.

    Parameters
    ----------
    df : DataFrame with at least 'ret_arith' column, sorted by ts ascending.
         Must also have 'id', 'ts', 'tf' columns for the output.
    tf_days : Nominal days per bar (from dim_timeframe.tf_days_nominal).
    windows : List of rolling window sizes in bars (e.g. [30, 60, 90, 252]).
    rf : Risk-free rate (decimal per bar).

    Returns
    -------
    DataFrame with all stat columns + metadata columns (id, ts, tf, rf_rate).
    NULL values appear for the first (window-1) bars of each windowed stat.
    """
    result = df[["id", "ts", "tf"]].copy()

    ret = df["ret_arith"]

    # Expanding ATH drawdown (non-windowed)
    result["max_dd_from_ath"] = _current_drawdown_from_ath(ret)

    # Risk-free rate constant
    result["rf_rate"] = rf

    # Per-window statistics
    for w in windows:
        roll = ret.rolling(window=w, min_periods=w)

        mean_col = roll.mean()
        std_col = roll.std(ddof=1)

        # Replace zero std with NaN to avoid divide-by-zero in Sharpe
        std_safe = std_col.replace(0.0, np.nan)

        sharpe_raw = (mean_col - rf) / std_safe
        ann_factor = math.sqrt(365.0 / tf_days)
        sharpe_ann = sharpe_raw * ann_factor

        result[f"mean_ret_{w}"] = mean_col
        result[f"std_ret_{w}"] = std_col
        result[f"sharpe_raw_{w}"] = sharpe_raw
        result[f"sharpe_ann_{w}"] = sharpe_ann
        result[f"skew_{w}"] = roll.skew()
        result[f"kurt_fisher_{w}"] = roll.kurt()  # pandas .kurt() = Fisher (normal=0)
        result[f"kurt_pearson_{w}"] = result[f"kurt_fisher_{w}"] + 3.0
        result[f"max_dd_window_{w}"] = _rolling_max_drawdown(ret, w)

    return result


# ---------------------------------------------------------------------------
# Worker (per id/tf)
# ---------------------------------------------------------------------------


@dataclass
class WorkerTask:
    """Describes one unit of work: one (id, tf) pair."""

    asset_id: int
    tf: str
    full_rebuild: bool
    windows: List[int]
    rf: float


def _worker(task: WorkerTask, db_url: str) -> Tuple[int, str, int, bool, str]:
    """
    Process one (id, tf) pair.

    Returns (asset_id, tf, n_rows_written, success, error_msg).
    """
    engine = create_engine(db_url, future=True, poolclass=NullPool)

    try:
        n_rows = _process_one(engine, db_url, task)
        return (task.asset_id, task.tf, n_rows, True, "")
    except Exception as exc:
        return (task.asset_id, task.tf, 0, False, str(exc))
    finally:
        engine.dispose()


def _process_one(engine: Engine, db_url: str, task: WorkerTask) -> int:
    """
    Core incremental logic for one (id, tf).

    1. Read watermark from cmc_asset_stats_state.
    2. Load ret_arith from cmc_returns_bars_multi_tf.
    3. Compute stats.
    4. DELETE + INSERT into cmc_asset_stats.
    5. Update watermark.

    Returns number of rows written.
    """
    asset_id = task.asset_id
    tf = task.tf
    windows = task.windows
    rf = task.rf

    # Use the explicit db_url (not str(engine.url) which strips the password)
    tf_days = get_tf_days(tf, db_url)
    lookback = max(windows)  # bars before watermark needed for continuity

    # ------------------------------------------------------------------
    # Step 1: Read watermark
    # ------------------------------------------------------------------
    last_ts: Optional[pd.Timestamp] = None
    if not task.full_rebuild:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT last_timestamp FROM public.cmc_asset_stats_state "
                    "WHERE id = :id AND tf = :tf"
                ),
                {"id": asset_id, "tf": tf},
            ).fetchone()
            if row and row[0] is not None:
                # row[0] may be a tz-aware datetime; convert to UTC safely
                _raw_ts = pd.Timestamp(row[0])
                if _raw_ts.tzinfo is None:
                    last_ts = _raw_ts.tz_localize("UTC")
                else:
                    last_ts = _raw_ts.tz_convert("UTC")

    # ------------------------------------------------------------------
    # Step 2: Load returns
    # ------------------------------------------------------------------
    if last_ts is None:
        # First run or full rebuild: load all history
        sql = text(
            'SELECT id, "timestamp" AS ts, tf, ret_arith '
            "FROM public.cmc_returns_bars_multi_tf "
            "WHERE id = :id AND tf = :tf AND roll = FALSE "
            'ORDER BY "timestamp"'
        )
        params: Dict[str, Any] = {"id": asset_id, "tf": tf}
    else:
        # Incremental: load from (last_ts - lookback bars) to capture the full
        # rolling window context needed for continuity.
        # We compute a safe cutoff in calendar days: lookback * tf_days * 1.5
        # to account for weekends/gaps. The stats are recomputed for any row
        # at or after the old watermark.
        lookback_days = int(lookback * tf_days * 1.5)
        sql = text(
            'SELECT id, "timestamp" AS ts, tf, ret_arith '
            "FROM public.cmc_returns_bars_multi_tf "
            "WHERE id = :id AND tf = :tf AND roll = FALSE "
            "AND \"timestamp\" >= (:last_ts - CAST(:lookback_days || ' days' AS INTERVAL)) "
            'ORDER BY "timestamp"'
        )
        params = {
            "id": asset_id,
            "tf": tf,
            "last_ts": last_ts,
            "lookback_days": lookback_days,
        }

    with engine.connect() as conn:
        df_raw = pd.read_sql(sql, conn, params=params)

    if df_raw.empty:
        return 0

    # Fix Windows tz-aware timestamp pitfall
    df_raw["ts"] = pd.to_datetime(df_raw["ts"], utc=True)
    df_raw = df_raw.sort_values("ts").reset_index(drop=True)

    # ------------------------------------------------------------------
    # Step 3: Compute stats
    # ------------------------------------------------------------------
    stats_df = compute_asset_stats(df_raw, tf_days, windows, rf)

    # Determine the range we will write: rows >= last_ts (new rows only)
    if last_ts is not None:
        write_df = stats_df[stats_df["ts"] > last_ts].copy()
    else:
        write_df = stats_df.copy()

    if write_df.empty:
        return 0

    first_new_ts = write_df["ts"].min()
    new_last_ts = write_df["ts"].max()
    n_rows = len(write_df)

    # Convert to plain Python types for psycopg2
    write_df = write_df.copy()
    # Convert Timestamp -> native datetime for DB writes
    # Use .tolist() to get tz-aware Python datetime objects (avoids FutureWarning)
    write_df["ts"] = write_df["ts"].tolist()

    # ------------------------------------------------------------------
    # Step 4: DELETE + INSERT (scoped to new rows)
    # ------------------------------------------------------------------
    # Build column list from the DataFrame (matches DDL order)
    stat_cols = [c for c in write_df.columns if c not in ("id", "ts", "tf")]
    all_cols = ["id", "ts", "tf"] + stat_cols
    write_df = write_df[all_cols]

    # Replace numpy NaN with None for DB
    records = _df_to_records(write_df)

    with engine.begin() as conn:
        # Scoped delete: only rows >= first_new_ts for this (id, tf)
        conn.execute(
            text(
                "DELETE FROM public.cmc_asset_stats "
                "WHERE id = :id AND tf = :tf AND ts >= :first_ts"
            ),
            {"id": asset_id, "tf": tf, "first_ts": first_new_ts.to_pydatetime()},
        )

        # Insert new rows
        col_list = ", ".join(all_cols)
        placeholders = ", ".join(f":{c}" for c in all_cols)
        insert_sql = text(
            f"INSERT INTO public.cmc_asset_stats ({col_list}) VALUES ({placeholders})"
        )
        conn.execute(insert_sql, records)

        # ------------------------------------------------------------------
        # Step 5: Update watermark
        # ------------------------------------------------------------------
        conn.execute(
            text(
                "INSERT INTO public.cmc_asset_stats_state (id, tf, last_timestamp, updated_at) "
                "VALUES (:id, :tf, :last_ts, now()) "
                "ON CONFLICT (id, tf) DO UPDATE "
                "SET last_timestamp = EXCLUDED.last_timestamp, updated_at = now()"
            ),
            {"id": asset_id, "tf": tf, "last_ts": new_last_ts.to_pydatetime()},
        )

    return n_rows


def _df_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Convert DataFrame rows to list of dicts, replacing NaN/NaT with None."""
    records = []
    for row in df.itertuples(index=False):
        d: Dict[str, Any] = {}
        for col in df.columns:
            v = getattr(row, col)
            if isinstance(v, float) and math.isnan(v):
                d[col] = None
            elif hasattr(v, "item"):
                # numpy scalar -> python scalar
                d[col] = v.item()
            else:
                d[col] = v
        records.append(d)
    return records


# ---------------------------------------------------------------------------
# Asset / TF discovery
# ---------------------------------------------------------------------------


def _get_all_asset_ids(engine: Engine) -> List[int]:
    """Return all active asset IDs from dim_assets (is_active=TRUE)."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT id FROM public.dim_assets "
                    "WHERE is_active = TRUE ORDER BY id"
                )
            ).fetchall()
            ids = [r[0] for r in rows]
            if ids:
                return ids
    except Exception:
        pass

    # Fallback: distinct IDs in source table
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT id FROM public.cmc_returns_bars_multi_tf "
                "WHERE tf = '1D' ORDER BY id"
            )
        ).fetchall()
        return [r[0] for r in rows]


def _get_all_tfs(engine: Engine) -> List[str]:
    """Return all canonical TFs from dim_timeframe, sorted by sort_order."""
    dim = DimTimeframe.from_db(str(engine.url))
    return list(dim.list_tfs(canonical_only=True))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(
        description="Compute per-asset rolling descriptive statistics into cmc_asset_stats."
    )
    p.add_argument(
        "--ids",
        default="all",
        help="Comma-separated asset IDs or 'all' (default: all).",
    )
    p.add_argument(
        "--tf",
        default=None,
        help="Single TF filter, e.g. '1D'. Omit to run all canonical TFs.",
    )
    p.add_argument(
        "--windows",
        default="30,60,90,252",
        help="Comma-separated window sizes in bars (default: 30,60,90,252).",
    )
    p.add_argument(
        "--rf",
        type=float,
        default=DEFAULT_RF,
        help=f"Risk-free rate per bar (default: {DEFAULT_RF}).",
    )
    p.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Ignore watermarks and recompute all rows from scratch.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run without executing.",
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue processing remaining tasks if one fails.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel worker processes (default: 4).",
    )
    p.add_argument(
        "--db-url",
        default=None,
        help="Override database URL.",
    )
    args = p.parse_args()

    db_url = resolve_db_url(args.db_url)

    # Parse windows
    try:
        windows = [int(w.strip()) for w in args.windows.split(",") if w.strip()]
    except ValueError as exc:
        raise SystemExit(f"ERROR: Invalid --windows format: {args.windows}") from exc

    # Parse IDs
    ids_filter = parse_ids(args.ids, db_url)

    engine = create_engine(db_url, future=True)

    # Resolve asset IDs
    if ids_filter is None:
        asset_ids = _get_all_asset_ids(engine)
    else:
        asset_ids = sorted(ids_filter)

    # Resolve TFs
    if args.tf:
        tfs = [args.tf]
    else:
        tfs = _get_all_tfs(engine)

    engine.dispose()

    _print(
        f"ids={len(asset_ids)}, tfs={tfs}, windows={windows}, "
        f"rf={args.rf}, full_rebuild={args.full_rebuild}, workers={args.workers}"
    )

    # Build task list
    tasks: List[WorkerTask] = [
        WorkerTask(
            asset_id=asset_id,
            tf=tf,
            full_rebuild=args.full_rebuild,
            windows=windows,
            rf=args.rf,
        )
        for asset_id in asset_ids
        for tf in tfs
    ]

    _print(f"Total tasks: {len(tasks)}")

    if args.dry_run:
        _print("DRY RUN — tasks that would execute:")
        for t in tasks:
            _print(f"  id={t.asset_id} tf={t.tf}")
        return

    t0 = time.time()
    total_rows = 0
    errors: List[str] = []

    worker_fn = partial(_worker, db_url=db_url)

    if args.workers > 1 and len(tasks) > 1:
        with Pool(processes=min(args.workers, len(tasks))) as pool:
            for asset_id, tf, n_rows, success, err_msg in pool.imap_unordered(
                worker_fn, tasks
            ):
                if success:
                    total_rows += n_rows
                    if n_rows > 0:
                        _print(f"  id={asset_id} tf={tf} -> {n_rows} rows written")
                else:
                    err = f"id={asset_id} tf={tf}: {err_msg}"
                    errors.append(err)
                    _print(f"  ERROR {err}")
                    if not args.continue_on_error:
                        raise RuntimeError(f"Task failed: {err}")
    else:
        for i, task in enumerate(tasks, 1):
            asset_id, tf, n_rows, success, err_msg = worker_fn(task)
            if success:
                total_rows += n_rows
                if n_rows > 0:
                    _print(
                        f"  [{i}/{len(tasks)}] id={asset_id} tf={tf} -> {n_rows} rows written"
                    )
                else:
                    _print(
                        f"  [{i}/{len(tasks)}] id={asset_id} tf={tf} -> 0 rows (up to date)"
                    )
            else:
                err = f"id={asset_id} tf={tf}: {err_msg}"
                errors.append(err)
                _print(f"  [{i}/{len(tasks)}] ERROR {err}")
                if not args.continue_on_error:
                    raise RuntimeError(f"Task failed: {err}")

    elapsed = time.time() - t0
    _print(f"Done in {elapsed:.1f}s — {total_rows} rows written, {len(errors)} errors")
    if errors:
        _print("Errors:")
        for e in errors:
            _print(f"  {e}")


if __name__ == "__main__":
    main()
