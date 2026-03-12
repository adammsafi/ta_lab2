from __future__ import annotations

r"""
refresh_returns_zscore.py

Standalone post-processing script that adds rolling z-scores and is_outlier
flags to bar-returns, EMA-returns, and AMA-returns tables.

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

AMA returns z-scores (per window, 2 canonical + 2 roll = 4 columns):
    Canonical (roll=FALSE only): ret_arith_ama_zscore_{W}, ret_log_ama_zscore_{W}
    Roll (ALL rows):             ret_arith_ama_roll_zscore_{W}, ret_log_ama_roll_zscore_{W}
    NOTE: key_cols include indicator and params_hash for per-param-set z-score grouping.

is_outlier: TRUE if any |z-score| > 4 across ALL z-score columns for that row.

Usage:
    python -m ta_lab2.scripts.returns.refresh_returns_zscore --tables bars --workers 4
    python -m ta_lab2.scripts.returns.refresh_returns_zscore --tables emas --workers 4
    python -m ta_lab2.scripts.returns.refresh_returns_zscore --tables amas --workers 4
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
import subprocess
import time
from dataclasses import dataclass
from multiprocessing import Pool
from typing import Dict, List, Optional, Tuple

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
        table="public.returns_bars_multi_tf",
        ts_col='"timestamp"',
        pk_cols=["id", '"timestamp"', "tf"],
        key_cols=["id", "tf"],
        canonical_base_pairs=_BAR_CANONICAL_BASE,
        roll_base_pairs=_BAR_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_bars_multi_tf_cal_us",
        ts_col='"timestamp"',
        pk_cols=["id", '"timestamp"', "tf"],
        key_cols=["id", "tf"],
        canonical_base_pairs=_BAR_CANONICAL_BASE,
        roll_base_pairs=_BAR_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_bars_multi_tf_cal_iso",
        ts_col='"timestamp"',
        pk_cols=["id", '"timestamp"', "tf"],
        key_cols=["id", "tf"],
        canonical_base_pairs=_BAR_CANONICAL_BASE,
        roll_base_pairs=_BAR_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_bars_multi_tf_cal_anchor_us",
        ts_col='"timestamp"',
        pk_cols=["id", '"timestamp"', "tf"],
        key_cols=["id", "tf"],
        canonical_base_pairs=_BAR_CANONICAL_BASE,
        roll_base_pairs=_BAR_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_bars_multi_tf_cal_anchor_iso",
        ts_col='"timestamp"',
        pk_cols=["id", '"timestamp"', "tf"],
        key_cols=["id", "tf"],
        canonical_base_pairs=_BAR_CANONICAL_BASE,
        roll_base_pairs=_BAR_ROLL_BASE,
    ),
]

# -- EMA returns tables (5 source, _u synced separately) -------------------

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
        table="public.returns_ema_multi_tf",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period"],
        key_cols=["id", "tf", "period"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_ema_multi_tf_cal_us",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period"],
        key_cols=["id", "tf", "period"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_ema_multi_tf_cal_iso",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period"],
        key_cols=["id", "tf", "period"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_ema_multi_tf_cal_anchor_us",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period"],
        key_cols=["id", "tf", "period"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_ema_multi_tf_cal_anchor_iso",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "period"],
        key_cols=["id", "tf", "period"],
        canonical_base_pairs=_EMA_CANONICAL_BASE,
        roll_base_pairs=_EMA_ROLL_BASE,
    ),
]

# -- AMA returns tables (5 source, _u synced separately) -------------------
# AMA has no _ema_bar column family — only 4 z-score base pairs per window
# (2 canonical + 2 roll) vs EMA's 8 (4+4).
# CRITICAL: key_cols MUST include indicator and params_hash so that z-scores
# are computed per (id, tf, indicator, params_hash) group — prevents z-scores
# from aggregating across different AMA types and parameter sets.

_AMA_CANONICAL_BASE = [
    ("ret_arith_ama", "ret_arith_ama_zscore"),
    ("ret_log_ama", "ret_log_ama_zscore"),
]

_AMA_ROLL_BASE = [
    ("ret_arith_ama_roll", "ret_arith_ama_roll_zscore"),
    ("ret_log_ama_roll", "ret_log_ama_roll_zscore"),
]

_AMA_TABLES = [
    TableConfig(
        table="public.returns_ama_multi_tf",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "indicator", "params_hash"],
        key_cols=["id", "tf", "indicator", "params_hash"],
        canonical_base_pairs=_AMA_CANONICAL_BASE,
        roll_base_pairs=_AMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_ama_multi_tf_cal_us",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "indicator", "params_hash"],
        key_cols=["id", "tf", "indicator", "params_hash"],
        canonical_base_pairs=_AMA_CANONICAL_BASE,
        roll_base_pairs=_AMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_ama_multi_tf_cal_iso",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "indicator", "params_hash"],
        key_cols=["id", "tf", "indicator", "params_hash"],
        canonical_base_pairs=_AMA_CANONICAL_BASE,
        roll_base_pairs=_AMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_ama_multi_tf_cal_anchor_us",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "indicator", "params_hash"],
        key_cols=["id", "tf", "indicator", "params_hash"],
        canonical_base_pairs=_AMA_CANONICAL_BASE,
        roll_base_pairs=_AMA_ROLL_BASE,
    ),
    TableConfig(
        table="public.returns_ama_multi_tf_cal_anchor_iso",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "indicator", "params_hash"],
        key_cols=["id", "tf", "indicator", "params_hash"],
        canonical_base_pairs=_AMA_CANONICAL_BASE,
        roll_base_pairs=_AMA_ROLL_BASE,
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
# Core z-score computation (SQL window functions)
# ---------------------------------------------------------------------------


def _build_combined_zscore_update_sql(
    cfg: TableConfig,
    window_specs: List[Tuple[int, str]],
    mode: str,
) -> Optional[str]:
    """
    Build a single SQL UPDATE that computes z-scores for ALL eligible windows
    at once using multiple named WINDOW definitions.

    window_specs: [(window_bars, suffix), ...] — only windows with wb >= MIN_WINDOW
    mode='roll':      use roll_base_pairs, no roll filter (all rows)
    mode='canonical': use canonical_base_pairs, WHERE roll = FALSE

    This produces ONE UPDATE per mode instead of one per (window, mode),
    cutting table scans from 6 to 2 per work unit.
    """
    pairs = cfg.roll_base_pairs if mode == "roll" else cfg.canonical_base_pairs
    if not pairs or not window_specs:
        return None

    roll_filter = " AND roll = FALSE" if mode == "canonical" else ""

    # Build SET and SELECT parts for all (source_col, window) combinations
    set_parts = []
    select_parts = []
    window_defs = []
    seen_windows = set()

    for window_bars, suffix in window_specs:
        win_name = f"w{window_bars}"
        if win_name not in seen_windows:
            seen_windows.add(win_name)
            frame = window_bars - 1
            partition = ", ".join(cfg.key_cols)
            window_defs.append(
                f"{win_name} AS (PARTITION BY {partition} ORDER BY {cfg.ts_col} "
                f"ROWS BETWEEN {frame} PRECEDING AND CURRENT ROW)"
            )

        for src_col, base in pairs:
            z_col = f"{base}{suffix}"
            alias = f"_z_{src_col}{suffix}"
            set_parts.append(f'"{z_col}" = sub."{alias}"')
            select_parts.append(
                f'CASE WHEN COUNT("{src_col}") OVER {win_name} >= {window_bars} '
                f'AND STDDEV_SAMP("{src_col}") OVER {win_name} > 0 '
                f'THEN ("{src_col}" - AVG("{src_col}") OVER {win_name}) '
                f'/ STDDEV_SAMP("{src_col}") OVER {win_name} END AS "{alias}"'
            )

    # PK join for UPDATE
    pk_joins = []
    for c in cfg.pk_cols:
        c_clean = c.strip('"')
        if c_clean == "timestamp":
            pk_joins.append('t."timestamp" = sub."timestamp"')
        else:
            pk_joins.append(f't."{c_clean}" = sub."{c_clean}"')

    return f"""
    UPDATE {cfg.table} t
    SET {", ".join(set_parts)}
    FROM (
        SELECT {", ".join(f'"{c.strip(chr(34))}"' for c in cfg.pk_cols)},
            {", ".join(select_parts)}
        FROM {cfg.table}
        WHERE id = :id AND tf = :tf{roll_filter}
        WINDOW {", ".join(window_defs)}
    ) sub
    WHERE {" AND ".join(pk_joins)};
    """


def _build_is_outlier_sql(cfg: TableConfig) -> str:
    """Build SQL to set is_outlier based on all z-score columns."""
    zscore_cols = _all_zscore_cols(cfg)

    # is_outlier = TRUE if any |z-score| > threshold
    outlier_conditions = " OR ".join(
        f'ABS("{c}") > {OUTLIER_THRESHOLD}' for c in zscore_cols
    )
    # has_any_zscore = at least one z-score is not NULL
    any_not_null = " OR ".join(f'"{c}" IS NOT NULL' for c in zscore_cols)

    return f"""
    UPDATE {cfg.table}
    SET is_outlier = CASE
        WHEN ({any_not_null}) THEN ({outlier_conditions})
        ELSE NULL
    END
    WHERE id = :id AND tf = :tf;
    """


def _worker_sql_tf(args: tuple) -> dict:
    """
    Process z-scores for one (table, id, tf) using SQL window functions.

    Work unit = (table, id, tf) keeps each UPDATE to ~100K rows max.
    Runs ~6 UPDATE statements (roll + canonical per window) plus 1 is_outlier.
    """
    (
        cfg_table,
        cfg_ts_col,
        cfg_pk_cols,
        cfg_key_cols,
        cfg_canon_pairs,
        cfg_roll_pairs,
        id_val,
        tf_val,
        tf_days_val,
        db_url,
    ) = args

    cfg = TableConfig(
        table=cfg_table,
        ts_col=cfg_ts_col,
        pk_cols=cfg_pk_cols,
        key_cols=cfg_key_cols,
        canonical_base_pairs=cfg_canon_pairs,
        roll_base_pairs=cfg_roll_pairs,
    )

    t0 = time.time()
    try:
        engine = _get_worker_engine(db_url)
        total_updated = 0

        # Compute eligible (window_bars, suffix) for this TF
        window_specs = []
        for window_days, suffix in WINDOW_CONFIGS:
            window_bars = round(window_days / tf_days_val)
            if window_bars >= MIN_WINDOW:
                window_specs.append((window_bars, suffix))

        if not window_specs:
            # No eligible windows for this TF — skip entirely
            return {
                "table": cfg.table,
                "id": id_val,
                "tf": tf_val,
                "n_updated": 0,
                "elapsed": time.time() - t0,
                "error": None,
            }

        # Single connection, single transaction: 2 UPDATEs + 1 is_outlier
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL work_mem = '128MB'"))

            # Roll z-scores (all rows, all windows in one pass)
            sql = _build_combined_zscore_update_sql(cfg, window_specs, "roll")
            if sql:
                result = conn.execute(text(sql), {"id": id_val, "tf": tf_val})
                total_updated += result.rowcount

            # Canonical z-scores (roll=FALSE, all windows in one pass)
            sql = _build_combined_zscore_update_sql(cfg, window_specs, "canonical")
            if sql:
                result = conn.execute(text(sql), {"id": id_val, "tf": tf_val})
                total_updated += result.rowcount

            # is_outlier for this (id, tf)
            sql = _build_is_outlier_sql(cfg)
            conn.execute(text(sql), {"id": id_val, "tf": tf_val})

        elapsed = time.time() - t0
        return {
            "table": cfg.table,
            "id": id_val,
            "tf": tf_val,
            "n_updated": total_updated,
            "elapsed": elapsed,
            "error": None,
        }
    except Exception as exc:
        return {
            "table": cfg_table,
            "id": id_val,
            "tf": tf_val,
            "n_updated": 0,
            "elapsed": time.time() - t0,
            "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Table-level orchestrator (SQL bulk mode)
# ---------------------------------------------------------------------------


def _get_tf_days_map(engine: Engine, table: str, db_url: str) -> Dict[str, int]:
    """Get tf -> tf_days mapping for all TFs in a table."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT DISTINCT tf FROM {table} ORDER BY tf")
        ).fetchall()
    return {r[0]: get_tf_days(r[0], db_url) for r in rows}


def _process_table(
    db_url: str,
    cfg: TableConfig,
    ids: Optional[List[int]],
    tf_filter: Optional[str],
    full_recalc: bool,
    workers: int,
) -> None:
    """Process one table using SQL window functions with multiprocessing.

    Work unit = (table, id, tf) so each UPDATE touches ~100K rows max.
    """
    tbl_short = cfg.table.split(".")[-1]
    _print(f"--- Processing table: {tbl_short} ---")

    engine = _get_engine(db_url)

    # Resolve IDs
    if ids is not None:
        id_list = ids
    else:
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT DISTINCT id FROM {cfg.table} ORDER BY id")
            ).fetchall()
            id_list = [r[0] for r in rows]

    if not id_list:
        _print(f"  No IDs found in {tbl_short}.")
        return

    # Get tf -> tf_days mapping
    tf_days_map = _get_tf_days_map(engine, cfg.table, db_url)
    if tf_filter:
        tf_days_map = {k: v for k, v in tf_days_map.items() if k == tf_filter}

    _print(
        f"  {len(id_list)} ids x {len(tf_days_map)} TFs = "
        f"{len(id_list) * len(tf_days_map)} work units"
    )

    # Build work units: one per (table, id, tf)
    work_units = [
        (
            cfg.table,
            cfg.ts_col,
            cfg.pk_cols,
            cfg.key_cols,
            cfg.canonical_base_pairs,
            cfg.roll_base_pairs,
            id_val,
            tf_val,
            tf_days_val,
            db_url,
        )
        for id_val in id_list
        for tf_val, tf_days_val in tf_days_map.items()
    ]

    t0 = time.time()
    total_updated = 0
    errors = []
    done = 0

    effective_workers = min(workers, len(work_units))

    def _handle_result(result: dict) -> None:
        nonlocal total_updated, done
        total_updated += result["n_updated"]
        done += 1
        if result["error"]:
            errors.append(result)
            _print(
                f"  [{tbl_short}] id={result['id']} tf={result['tf']} "
                f"ERROR: {result['error']}"
            )
        elif done % 50 == 0 or done == len(work_units):
            elapsed_so_far = time.time() - t0
            _print(
                f"  [{tbl_short}] {done}/{len(work_units)} done, "
                f"{total_updated:,} rows updated, {elapsed_so_far:.0f}s elapsed"
            )

    if effective_workers > 1:
        with Pool(processes=effective_workers, maxtasksperchild=20) as pool:
            for result in pool.imap_unordered(_worker_sql_tf, work_units):
                _handle_result(result)
    else:
        for wu in work_units:
            result = _worker_sql_tf(wu)
            _handle_result(result)

    elapsed = time.time() - t0
    _print(
        f"  {tbl_short}: {total_updated:,} total rows updated in {elapsed:.1f}s"
        + (f", {len(errors)} errors" if errors else "")
    )


# ---------------------------------------------------------------------------
# Re-sync _u tables after z-scoring source tables
# ---------------------------------------------------------------------------

# Map table family -> sync module path
_RESYNC_MODULES = {
    "bars": "ta_lab2.scripts.returns.sync_returns_bars_multi_tf_u",
    "emas": "ta_lab2.scripts.returns.sync_returns_ema_multi_tf_u",
    "amas": "ta_lab2.scripts.amas.sync_returns_ama_multi_tf_u",
}

_RESYNC_U_TABLES = {
    "bars": "public.returns_bars_multi_tf_u",
    "emas": "public.returns_ema_multi_tf_u",
    "amas": "public.returns_ama_multi_tf_u",
}


def _resync_u_tables(db_url: str, table_family: str) -> None:
    """Truncate and re-sync _u tables so z-scores propagate from source tables."""
    families = list(_RESYNC_MODULES.keys()) if table_family == "all" else [table_family]

    engine = _get_engine(db_url)
    for family in families:
        u_table = _RESYNC_U_TABLES[family]
        module = _RESYNC_MODULES[family]

        _print(f"--- Re-syncing {u_table} ---")

        # Truncate _u table
        _print(f"  Truncating {u_table}...")
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {u_table}"))
        _print("  Truncated.")

        # Run sync script as subprocess (inherits TARGET_DB_URL from env)
        _print(f"  Running sync: python -m {module}")
        t0 = time.time()
        result = subprocess.run(
            ["python", "-m", module],
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout
        )
        elapsed = time.time() - t0

        # Print sync output
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                _print(f"  {line.strip()}")
        if result.returncode != 0:
            _print(f"  SYNC ERROR (exit {result.returncode}): {result.stderr[:500]}")
        else:
            _print(f"  Sync complete in {elapsed:.0f}s")


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
        choices=["bars", "emas", "amas", "all"],
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
    p.add_argument(
        "--skip-resync",
        action="store_true",
        help="Skip re-syncing _u tables after z-scoring source tables.",
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
    if args.tables in ("amas", "all"):
        configs.extend(_AMA_TABLES)

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

    # Re-sync _u tables: TRUNCATE + full re-sync from z-scored source tables
    if not args.skip_resync:
        _resync_u_tables(db_url, args.tables)

    _print(f"All done in {time.time() - t_total:.1f}s")


if __name__ == "__main__":
    main()
