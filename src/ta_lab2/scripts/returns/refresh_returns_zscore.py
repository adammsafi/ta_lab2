from __future__ import annotations

r"""
refresh_returns_zscore.py

Standalone post-processing script that adds rolling z-scores and is_outlier
flags to bar-returns and EMA-returns tables.

Runs AFTER the base returns refresh scripts have populated raw return columns.
Z-scores are computed per (key, tf) group with multiple adaptive rolling windows:
    window_bars = round(window_days / tf_days)
If window_bars < 30, that window's z-scores are left NULL (insufficient history).

Windows:
    30-day  (~1 month):  suffix _30
    90-day  (~3 months): suffix _90
    365-day (~1 year):   suffix _365

Bar returns z-scores (per window, 4 canonical + 4 roll = 8 columns):
    Canonical (roll=FALSE only): ret_arith_zscore_{W}, delta_ret_arith_zscore_{W},
                                 ret_log_zscore_{W}, delta_ret_log_zscore_{W}
    Roll (ALL rows):             ret_arith_roll_zscore_{W}, delta_ret_arith_roll_zscore_{W},
                                 ret_log_roll_zscore_{W}, delta_ret_log_roll_zscore_{W}

EMA returns z-scores (per window, 4 canonical + 4 roll = 8 columns):
    Canonical (roll=FALSE only): ret_arith_ema_zscore_{W}, ret_arith_ema_bar_zscore_{W},
                                 ret_log_ema_zscore_{W}, ret_log_ema_bar_zscore_{W}
    Roll (ALL rows):             ret_arith_ema_roll_zscore_{W}, ret_arith_ema_bar_roll_zscore_{W},
                                 ret_log_ema_roll_zscore_{W}, ret_log_ema_bar_roll_zscore_{W}

is_outlier: TRUE if any |z-score| > 4 across ALL 24 z-score columns for that row.

Usage:
    python -m ta_lab2.scripts.returns.refresh_returns_zscore --tables bars --workers 4
    python -m ta_lab2.scripts.returns.refresh_returns_zscore --tables emas --workers 4
    python -m ta_lab2.scripts.returns.refresh_returns_zscore --tables all  --full-recalc
    python -m ta_lab2.scripts.returns.refresh_returns_zscore --tables bars --ids 1 --tf 1D

Spyder run example:
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_returns_zscore.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--tables bars --ids 1 --tf 1D"
)
"""

import argparse
import os
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

from ta_lab2.time.dim_timeframe import get_tf_days

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTLIER_THRESHOLD = 4.0
MIN_WINDOW = 30

# (window_days, column_suffix)
WINDOW_CONFIGS: List[Tuple[int, str]] = [
    (30, "_30"),
    (90, "_90"),
    (365, "_365"),
]

_PRINT_PREFIX = "ret_zscore"


def _print(msg: str) -> None:
    print(f"[{_PRINT_PREFIX}] {msg}")


# ---------------------------------------------------------------------------
# Table configurations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableConfig:
    """Configuration for one returns table's z-score processing."""

    table: str
    ts_col: str  # column name for ordering (quoted if needed)
    pk_cols: List[str]  # columns forming the PK (for UPDATE join)
    key_cols: List[str]  # grouping columns to iterate over (e.g. [id, tf])
    # Base canonical pairs: (source_col, zscore_base_name) — suffix added per window
    canonical_base_pairs: List[Tuple[str, str]]
    # Base roll pairs: (source_col, zscore_base_name) — suffix added per window
    roll_base_pairs: List[Tuple[str, str]]


# -- Bar returns tables (5) -------------------------------------------------

_BAR_CANONICAL_BASE = [
    ("ret_arith", "ret_arith_zscore"),
    ("delta_ret_arith", "delta_ret_arith_zscore"),
    ("ret_log", "ret_log_zscore"),
    ("delta_ret_log", "delta_ret_log_zscore"),
]

_BAR_ROLL_BASE = [
    ("ret_arith_roll", "ret_arith_roll_zscore"),
    ("delta_ret_arith_roll", "delta_ret_arith_roll_zscore"),
    ("ret_log_roll", "ret_log_roll_zscore"),
    ("delta_ret_log_roll", "delta_ret_log_roll_zscore"),
]

_BAR_TABLES = [
    TableConfig(
        table="public.cmc_returns_bars_multi_tf",
        ts_col='"timestamp"',
        pk_cols=["id", '"timestamp"', "tf"],
        key_cols=["id", "tf"],
        canonical_base_pairs=_BAR_CANONICAL_BASE,
        roll_base_pairs=_BAR_ROLL_BASE,
    ),
    TableConfig(
        table="public.cmc_returns_bars_multi_tf_cal_us",
        ts_col='"timestamp"',
        pk_cols=["id", '"timestamp"', "tf"],
        key_cols=["id", "tf"],
        canonical_base_pairs=_BAR_CANONICAL_BASE,
        roll_base_pairs=_BAR_ROLL_BASE,
    ),
    TableConfig(
        table="public.cmc_returns_bars_multi_tf_cal_iso",
        ts_col='"timestamp"',
        pk_cols=["id", '"timestamp"', "tf"],
        key_cols=["id", "tf"],
        canonical_base_pairs=_BAR_CANONICAL_BASE,
        roll_base_pairs=_BAR_ROLL_BASE,
    ),
    TableConfig(
        table="public.cmc_returns_bars_multi_tf_cal_anchor_us",
        ts_col='"timestamp"',
        pk_cols=["id", '"timestamp"', "tf"],
        key_cols=["id", "tf"],
        canonical_base_pairs=_BAR_CANONICAL_BASE,
        roll_base_pairs=_BAR_ROLL_BASE,
    ),
    TableConfig(
        table="public.cmc_returns_bars_multi_tf_cal_anchor_iso",
        ts_col='"timestamp"',
        pk_cols=["id", '"timestamp"', "tf"],
        key_cols=["id", "tf"],
        canonical_base_pairs=_BAR_CANONICAL_BASE,
        roll_base_pairs=_BAR_ROLL_BASE,
    ),
]

# -- EMA returns tables (6) -------------------------------------------------

_EMA_CANONICAL_BASE = [
    ("ret_arith_ema", "ret_arith_ema_zscore"),
    ("ret_arith_ema_bar", "ret_arith_ema_bar_zscore"),
    ("ret_log_ema", "ret_log_ema_zscore"),
    ("ret_log_ema_bar", "ret_log_ema_bar_zscore"),
]

_EMA_ROLL_BASE = [
    ("ret_arith_ema_roll", "ret_arith_ema_roll_zscore"),
    ("ret_arith_ema_bar_roll", "ret_arith_ema_bar_roll_zscore"),
    ("ret_log_ema_roll", "ret_log_ema_roll_zscore"),
    ("ret_log_ema_bar_roll", "ret_log_ema_bar_roll_zscore"),
]

_EMA_TABLES = [
    TableConfig(
        table="public.cmc_returns_ema_multi_tf",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period"],
        key_cols=["id", "tf", "period"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.cmc_returns_ema_multi_tf_u",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period", "alignment_source"],
        key_cols=["id", "tf", "period", "alignment_source"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.cmc_returns_ema_multi_tf_cal_us",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period"],
        key_cols=["id", "tf", "period"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.cmc_returns_ema_multi_tf_cal_iso",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period"],
        key_cols=["id", "tf", "period"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.cmc_returns_ema_multi_tf_cal_anchor_us",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period"],
        key_cols=["id", "tf", "period"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.cmc_returns_ema_multi_tf_cal_anchor_iso",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period"],
        key_cols=["id", "tf", "period"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def _get_worker_engine(db_url: str) -> Engine:
    """Engine for worker processes — uses NullPool to avoid connection leaks."""
    return create_engine(db_url, future=True, poolclass=NullPool)


def _all_zscore_cols(cfg: TableConfig) -> List[str]:
    """All z-score output column names across all windows."""
    cols: List[str] = []
    for _, suffix in WINDOW_CONFIGS:
        for _, base in cfg.canonical_base_pairs:
            cols.append(f"{base}{suffix}")
        for _, base in cfg.roll_base_pairs:
            cols.append(f"{base}{suffix}")
    return cols


def _all_source_cols(cfg: TableConfig) -> List[str]:
    """All source columns (canonical + roll) that z-scores are derived from."""
    return [p[0] for p in cfg.canonical_base_pairs] + [
        p[0] for p in cfg.roll_base_pairs
    ]


def _max_window_bars(tf_days: int) -> int:
    """Largest window in bars across all WINDOW_CONFIGS for this TF."""
    return max(round(w / tf_days) for w, _ in WINDOW_CONFIGS)


# ---------------------------------------------------------------------------
# Key discovery
# ---------------------------------------------------------------------------


def _discover_keys(
    engine: Engine,
    cfg: TableConfig,
    ids: Optional[List[int]],
    tf_filter: Optional[str],
    full_recalc: bool,
) -> List[Tuple]:
    """
    Discover (key_col...) tuples that need z-score computation.

    Incremental mode (default): find keys that have source data but have NEVER
    been z-scored (COUNT(is_outlier) = 0 for the key group, since COUNT ignores
    NULLs). Warm-up rows always have NULL z-scores, so checking individual rows
    would always re-discover processed keys.

    Full recalc: return all distinct keys.
    """
    key_select = ", ".join(cfg.key_cols)
    params: Dict[str, Any] = {}

    where_parts: List[str] = []
    if ids is not None:
        where_parts.append("id = ANY(:ids)")
        params["ids"] = ids
    if tf_filter is not None:
        where_parts.append("tf = :tf")
        params["tf"] = tf_filter

    where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    if not full_recalc:
        # Group by key, keep only keys with source data but zero is_outlier set
        src_cols = _all_source_cols(cfg)
        any_source_count = " + ".join(f"COUNT({c})" for c in src_cols)
        sql = text(
            f"SELECT {key_select} FROM {cfg.table}{where_clause} "
            f"GROUP BY {key_select} "
            f"HAVING ({any_source_count}) > 0 AND COUNT(is_outlier) = 0 "
            f"ORDER BY {key_select};"
        )
    else:
        sql = text(
            f"SELECT DISTINCT {key_select} FROM {cfg.table}{where_clause} "
            f"ORDER BY {key_select};"
        )

    with engine.begin() as cxn:
        rows = cxn.execute(sql, params).fetchall()

    return [tuple(r) for r in rows]


# ---------------------------------------------------------------------------
# Core z-score computation per key
# ---------------------------------------------------------------------------


def _process_key(
    db_url: str,
    cfg: TableConfig,
    tf_days: int,
    key: Tuple,
) -> Tuple[Tuple, int]:
    """
    Compute z-scores for one key (e.g. one (id, tf) or (id, tf, period)).
    Processes all applicable windows (30, 90, 365) in one pass.

    Returns (key, n_rows_updated).
    """
    engine = _get_worker_engine(db_url)

    # Build WHERE for this key
    key_where = " AND ".join(f"{col} = :k{i}" for i, col in enumerate(cfg.key_cols))
    key_params = {f"k{i}": v for i, v in enumerate(key)}

    # Load all rows for this key, ordered by timestamp
    source_cols = list(
        set(
            [p[0] for p in cfg.canonical_base_pairs]
            + [p[0] for p in cfg.roll_base_pairs]
        )
    )
    select_cols = cfg.pk_cols + ["roll"] + source_cols
    select_str = ", ".join(select_cols)

    sql = text(
        f"SELECT {select_str} FROM {cfg.table} "
        f"WHERE {key_where} ORDER BY {cfg.ts_col};"
    )

    with engine.begin() as cxn:
        df = pd.read_sql(sql, cxn, params=key_params)

    if df.empty:
        return key, 0

    # Initialize all z-score columns as NaN
    zscore_cols = _all_zscore_cols(cfg)
    for col in zscore_cols:
        df[col] = np.nan

    # Pre-compute canonical mask
    canon_mask = df["roll"] == False  # noqa: E712
    has_canonical = canon_mask.any()
    if has_canonical:
        canon_idx = df.index[canon_mask]

    # --- Process each window ---
    for window_days, suffix in WINDOW_CONFIGS:
        window_bars = round(window_days / tf_days)
        if window_bars < MIN_WINDOW:
            continue

        # Roll z-scores (computed on ALL rows)
        for src_col, base in cfg.roll_base_pairs:
            if src_col in df.columns:
                z_col = f"{base}{suffix}"
                rolling_mean = (
                    df[src_col]
                    .rolling(window=window_bars, min_periods=window_bars)
                    .mean()
                )
                rolling_std = (
                    df[src_col]
                    .rolling(window=window_bars, min_periods=window_bars)
                    .std()
                )
                df[z_col] = np.where(
                    rolling_std > 0,
                    (df[src_col] - rolling_mean) / rolling_std,
                    np.nan,
                )

        # Canonical z-scores (computed on roll=FALSE rows only)
        if has_canonical:
            canon_df = df.loc[canon_idx].copy()

            for src_col, base in cfg.canonical_base_pairs:
                if src_col in canon_df.columns:
                    z_col = f"{base}{suffix}"
                    rolling_mean = (
                        canon_df[src_col]
                        .rolling(window=window_bars, min_periods=window_bars)
                        .mean()
                    )
                    rolling_std = (
                        canon_df[src_col]
                        .rolling(window=window_bars, min_periods=window_bars)
                        .std()
                    )
                    canon_df[z_col] = np.where(
                        rolling_std > 0,
                        (canon_df[src_col] - rolling_mean) / rolling_std,
                        np.nan,
                    )

            # Merge canonical z-scores back
            for _, base in cfg.canonical_base_pairs:
                z_col = f"{base}{suffix}"
                df.loc[canon_idx, z_col] = canon_df[z_col].values

    # --- is_outlier: TRUE if any |z-score| > 4 across ALL windows ---
    z_abs = df[zscore_cols].abs()
    # Use object dtype to allow True/False/None (nullable)
    df["is_outlier"] = (z_abs > OUTLIER_THRESHOLD).any(axis=1).astype(object)
    # Rows where ALL z-scores are NaN → is_outlier should be NULL
    all_nan = df[zscore_cols].isna().all(axis=1)
    df.loc[all_nan, "is_outlier"] = None

    # --- Write back via temp table + UPDATE JOIN ---
    update_cols = zscore_cols + ["is_outlier"]
    pk_col_names = [c.strip('"') for c in cfg.pk_cols]

    # Prepare the subset to write
    write_df = df[pk_col_names + update_cols].copy()

    # Only write rows where at least one z-score is not NaN
    has_data = write_df[zscore_cols].notna().any(axis=1)
    write_df = write_df[has_data]

    if write_df.empty:
        return key, 0

    n_rows = len(write_df)

    with engine.begin() as cxn:
        # Create temp table
        tmp_cols_ddl = []
        for c in pk_col_names:
            if c == "id":
                tmp_cols_ddl.append(f"{c} bigint")
            elif c in ("timestamp", "ts"):
                tmp_cols_ddl.append(
                    f'"{c}" timestamptz' if c == "timestamp" else f"{c} timestamptz"
                )
            elif c == "period":
                tmp_cols_ddl.append(f"{c} integer")
            elif c == "alignment_source":
                tmp_cols_ddl.append(f"{c} text")
            else:
                tmp_cols_ddl.append(f"{c} text")  # tf
        for c in zscore_cols:
            tmp_cols_ddl.append(f"{c} double precision")
        tmp_cols_ddl.append("is_outlier boolean")

        tmp_name = f"tmp_zscore_{cfg.table.split('.')[-1][:40]}"
        cxn.execute(text(f"DROP TABLE IF EXISTS {tmp_name};"))
        cxn.execute(
            text(
                f"CREATE TEMP TABLE {tmp_name} "
                f"({', '.join(tmp_cols_ddl)}) ON COMMIT DROP;"
            )
        )

        # Insert into temp table
        insert_cols = pk_col_names + update_cols
        placeholders = ", ".join(f":{c}" for c in insert_cols)
        insert_sql = text(
            f"INSERT INTO {tmp_name} ({', '.join(insert_cols)}) "
            f"VALUES ({placeholders});"
        )

        # Convert DataFrame to list of dicts, handling NaN → None
        # Note: pandas float columns silently convert None back to NaN,
        # so we must do NaN→None conversion on the dict records instead.
        records = [
            {
                k: (None if isinstance(v, float) and np.isnan(v) else v)
                for k, v in d.items()
            }
            for d in write_df.to_dict("records")
        ]
        # Batch insert
        cxn.execute(insert_sql, records)

        # UPDATE via JOIN
        # Build the ON clause from PK columns
        on_parts = []
        for c in pk_col_names:
            if c == "timestamp":
                on_parts.append('t."timestamp" = s."timestamp"')
            else:
                on_parts.append(f"t.{c} = s.{c}")

        set_parts = ", ".join(f"{c} = s.{c}" for c in update_cols)
        on_clause = " AND ".join(on_parts)

        update_sql = text(
            f"UPDATE {cfg.table} t SET {set_parts} "
            f"FROM {tmp_name} s WHERE {on_clause};"
        )
        cxn.execute(update_sql)

    return key, n_rows


# ---------------------------------------------------------------------------
# Table-level orchestrator
# ---------------------------------------------------------------------------


def _process_table(
    db_url: str,
    cfg: TableConfig,
    ids: Optional[List[int]],
    tf_filter: Optional[str],
    full_recalc: bool,
    workers: int,
) -> None:
    """Process one table: discover keys, group by tf, compute z-scores."""
    tbl_short = cfg.table.split(".")[-1]
    _print(f"--- Processing table: {tbl_short} ---")

    engine = _get_engine(db_url)

    keys = _discover_keys(engine, cfg, ids, tf_filter, full_recalc)
    _print(f"  Found {len(keys)} keys to process")

    if not keys:
        _print(f"  No keys need z-score computation for {tbl_short}.")
        return

    # Group keys by tf (index depends on position in key_cols)
    tf_idx = cfg.key_cols.index("tf")
    keys_by_tf: Dict[str, List[Tuple]] = {}
    for k in keys:
        tf_val = k[tf_idx]
        keys_by_tf.setdefault(tf_val, []).append(k)

    total_updated = 0
    t0 = time.time()

    for tf_val, tf_keys in sorted(keys_by_tf.items()):
        tf_days = get_tf_days(tf_val, db_url)

        # Skip TF if even the largest window is too small
        max_wb = _max_window_bars(tf_days)
        if max_wb < MIN_WINDOW:
            _print(
                f"  tf={tf_val}: max_window_bars={max_wb} < {MIN_WINDOW}, "
                f"skipping {len(tf_keys)} keys (all z-scores left NULL)"
            )
            continue

        # Report which windows are active for this TF
        active_windows = []
        for wd, sfx in WINDOW_CONFIGS:
            wb = round(wd / tf_days)
            active_windows.append(
                f"{sfx[1:]}={'ok' if wb >= MIN_WINDOW else 'skip'}({wb})"
            )
        _print(
            f"  tf={tf_val}: tf_days={tf_days}, "
            f"windows=[{', '.join(active_windows)}], keys={len(tf_keys)}"
        )

        worker_fn = partial(_process_key, db_url, cfg, tf_days)

        if workers > 1 and len(tf_keys) > 1:
            with Pool(processes=min(workers, len(tf_keys))) as pool:
                for key, n_rows in pool.imap_unordered(worker_fn, tf_keys):
                    total_updated += n_rows
                    if n_rows > 0:
                        _print(f"    key={key} -> {n_rows} rows updated")
        else:
            for i, k in enumerate(tf_keys, 1):
                key, n_rows = worker_fn(k)
                total_updated += n_rows
                if n_rows > 0:
                    _print(f"    key={key} -> {n_rows} rows ({i}/{len(tf_keys)})")

    elapsed = time.time() - t0
    _print(f"  {tbl_short}: {total_updated} total rows updated in {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_ids(ids_arg: str) -> Optional[List[int]]:
    s = (ids_arg or "").strip().lower()
    if s in ("", "all"):
        return None
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def main() -> None:
    p = argparse.ArgumentParser(
        description="Post-processing z-score computation for bar and EMA returns tables."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="Postgres DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument(
        "--tables",
        choices=["bars", "emas", "all"],
        default="all",
        help="Which table family to process (default: all).",
    )
    p.add_argument(
        "--ids",
        default="all",
        help="Comma-separated asset ids, or 'all' (default: all).",
    )
    p.add_argument(
        "--tf",
        default=None,
        help="Filter to a specific timeframe, e.g. '1D' (default: all TFs).",
    )
    p.add_argument(
        "--full-recalc",
        action="store_true",
        help="Recompute z-scores for all keys (default: incremental, only NULL z-scores).",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers per table (default: 1).",
    )
    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    _print(
        "Using DB URL from TARGET_DB_URL env."
        if os.getenv("TARGET_DB_URL")
        else "Using DB URL from --db-url."
    )

    ids = _parse_ids(args.ids)

    # Select table configs
    configs: List[TableConfig] = []
    if args.tables in ("bars", "all"):
        configs.extend(_BAR_TABLES)
    if args.tables in ("emas", "all"):
        configs.extend(_EMA_TABLES)

    _print(
        f"Processing {len(configs)} tables, "
        f"ids={'all' if ids is None else ids}, "
        f"tf={args.tf or 'all'}, "
        f"full_recalc={args.full_recalc}, "
        f"workers={args.workers}, "
        f"windows={[w for w, _ in WINDOW_CONFIGS]}"
    )

    t_total = time.time()

    for cfg in configs:
        _process_table(
            db_url=db_url,
            cfg=cfg,
            ids=ids,
            tf_filter=args.tf,
            full_recalc=args.full_recalc,
            workers=args.workers,
        )

    _print(f"All done in {time.time() - t_total:.1f}s")


if __name__ == "__main__":
    main()
