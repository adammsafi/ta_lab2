"""
Batch IC sweep across all assets x all TFs x all features.

Evaluates TWO data sources:
  Source A: features (bar-level features, 112 columns)
  Source B: ama_multi_tf_u (AMA indicator columns: ama, d1, d2, d1_roll, d2_roll, er)

Results are persisted to ic_results using upsert semantics (overwrite=True by default).
After the sweep, a feature ranking CSV is written to reports/bakeoff/feature_ic_ranking.csv
and the top-20 features by IC-IR (horizon=1, arith) are printed to console.

Usage:
    # Full sweep (features + AMA)
    python -m ta_lab2.scripts.analysis.run_ic_sweep --all

    # Targeted sweep
    python -m ta_lab2.scripts.analysis.run_ic_sweep --assets 1 1027 --tf 1D

    # With regime breakdown for BTC/ETH 1D
    python -m ta_lab2.scripts.analysis.run_ic_sweep --assets 1 1027 --tf 1D --regime

    # Dry run (list qualifying pairs without computing)
    python -m ta_lab2.scripts.analysis.run_ic_sweep --dry-run --min-bars 500

    # Skip AMA sweep (faster iteration on features only)
    python -m ta_lab2.scripts.analysis.run_ic_sweep --all --skip-ama
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, pool, text
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.ic import (
    _NON_FEATURE_COLS,
    batch_compute_ic,
    compute_ic_by_regime,
    load_regimes_for_asset,
    save_ic_results,
)
from ta_lab2.scripts.refresh_utils import resolve_db_url
from ta_lab2.scripts.sync_utils import get_columns, table_exists
from ta_lab2.time.dim_timeframe import DimTimeframe

logger = logging.getLogger(__name__)

# Regime breakdown is run for BTC and ETH on 1D by default
_REGIME_ASSET_IDS = frozenset([1, 1027])
_REGIME_TF = "1D"

# Extra metadata columns in features to exclude from feature discovery.
# Includes text/categorical columns that cannot be converted to float for IC computation.
_EXTRA_NON_FEATURE_COLS = frozenset(
    [
        "alignment_source",
        "tf_days",
        "asset_class",
        "venue",
        "updated_at",
        "has_price_gap",
        "has_outlier",
        "computed_at",
    ]
)

# AMA evaluatable columns (er is KAMA-only; others are for all indicators)
_AMA_FEATURE_COLS = ["ama", "d1", "d2", "d1_roll", "d2_roll", "er"]


@dataclass(frozen=True)
class ICWorkerTask:
    """
    Task for a single IC sweep worker process.

    Frozen dataclass with only picklable types (no engine/connection objects).
    Each worker creates its own NullPool engine from db_url.
    """

    asset_id: int
    tf: str
    n_rows: int
    db_url: str
    feature_cols: tuple  # tuple[str, ...] for hashability
    horizons: tuple  # tuple[int, ...]
    return_types: tuple  # tuple[str, ...]
    rolling_window: int
    tf_days_nominal: int
    overwrite: bool
    regime: bool


# ---------------------------------------------------------------------------
# Timestamp utilities
# ---------------------------------------------------------------------------


def _to_utc_timestamp(val) -> pd.Timestamp:
    """
    Convert a DB-returned timestamp value to a tz-aware UTC pd.Timestamp.

    SQLAlchemy may return tz-aware or tz-naive datetimes depending on DB driver.
    - tz-aware: use tz_convert("UTC")
    - tz-naive: assume UTC and tz_localize("UTC")
    """
    ts = pd.Timestamp(val)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


# ---------------------------------------------------------------------------
# Asset-TF discovery helpers
# ---------------------------------------------------------------------------


def _discover_features_pairs(engine, min_bars: int) -> list[tuple[int, str, int]]:
    """
    Discover qualifying (asset_id, tf) pairs from asset_data_coverage.

    Returns list of (asset_id, tf, n_rows) tuples with n_rows >= min_bars.
    Falls back to querying features directly if asset_data_coverage is unavailable.
    """
    # Try asset_data_coverage first
    try:
        with engine.connect() as conn:
            sql = text(
                """
                SELECT id AS asset_id, granularity AS tf, n_rows
                FROM public.asset_data_coverage
                WHERE source_table = 'features'
                  AND n_rows >= :min_bars
                ORDER BY asset_id, tf
                """
            )
            df = pd.read_sql(sql, conn, params={"min_bars": min_bars})
        if not df.empty:
            logger.info(
                "asset_data_coverage: found %d qualifying (asset, tf) pairs with >= %d bars",
                len(df),
                min_bars,
            )
            return list(zip(df["asset_id"], df["tf"], df["n_rows"]))
    except Exception as exc:
        logger.warning(
            "asset_data_coverage query failed (%s) — falling back to direct features query",
            exc,
        )

    # Fallback: query features directly
    with engine.connect() as conn:
        sql = text(
            """
            SELECT id AS asset_id, tf, COUNT(*) AS n_rows
            FROM public.features
            GROUP BY id, tf
            HAVING COUNT(*) >= :min_bars
            ORDER BY id, tf
            """
        )
        df = pd.read_sql(sql, conn, params={"min_bars": min_bars})

    logger.info(
        "features direct: found %d qualifying (asset, tf) pairs with >= %d bars",
        len(df),
        min_bars,
    )
    return list(zip(df["asset_id"], df["tf"], df["n_rows"]))


def _discover_ama_combos(engine, min_bars: int) -> list[tuple[int, str, str, str, int]]:
    """
    Discover qualifying (asset_id, tf, indicator, params_hash) combos from ama_multi_tf_u.

    Returns list of (asset_id, tf, indicator, params_hash, n_rows) tuples.
    Returns empty list if the table does not exist.
    """
    if not table_exists(engine, "public.ama_multi_tf_u"):
        logger.info("ama_multi_tf_u table does not exist — skipping AMA sweep")
        return []

    try:
        with engine.connect() as conn:
            sql = text(
                """
                SELECT
                    id AS asset_id,
                    tf,
                    indicator,
                    params_hash,
                    COUNT(*) AS n_rows
                FROM public.ama_multi_tf_u
                WHERE alignment_source = 'multi_tf'
                  AND roll = FALSE
                GROUP BY id, tf, indicator, params_hash
                HAVING COUNT(*) >= :min_bars
                ORDER BY id, tf, indicator, params_hash
                """
            )
            df = pd.read_sql(sql, conn, params={"min_bars": min_bars})
    except Exception as exc:
        logger.warning("Failed to discover AMA combos: %s", exc)
        return []

    logger.info(
        "ama_multi_tf_u: found %d qualifying (asset, tf, indicator, params_hash) combos",
        len(df),
    )
    return list(
        zip(df["asset_id"], df["tf"], df["indicator"], df["params_hash"], df["n_rows"])
    )


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_features_and_close(
    conn, asset_id: int, tf: str, feature_cols: list[str]
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Load all feature columns + close from features for an asset-tf pair.

    Returns (features_df, close_series) both indexed by UTC timestamps.
    """
    col_list = ", ".join(f'"{c}"' for c in feature_cols)
    sql = text(
        f"""
        SELECT ts, {col_list}, close
        FROM public.features
        WHERE id = :asset_id AND tf = :tf
        ORDER BY ts
        """
    )
    df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "tf": tf})

    if df.empty:
        return pd.DataFrame(), pd.Series(dtype=float)

    # CRITICAL: fix mixed-tz-offset object dtype from pd.read_sql on Windows
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")

    close_series = df["close"].copy()
    features_df = df[[c for c in feature_cols if c in df.columns]].copy()

    return features_df, close_series


def _load_ama_data_with_close(
    conn, asset_id: int, tf: str, indicator: str, params_hash: str
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Load AMA columns + close price for a specific (asset, tf, indicator, params_hash) combo.

    Uses ama_multi_tf_u (alignment_source='multi_tf') for AMA values
    and features for close price (joined on id, ts, tf).

    Returns (ama_features_df, close_series) both indexed by UTC timestamps.
    """
    sql = text(
        """
        SELECT
            a.ts,
            a.ama,
            a.d1,
            a.d2,
            a.d1_roll,
            a.d2_roll,
            a.er,
            f.close
        FROM public.ama_multi_tf_u a
        INNER JOIN public.features f
            ON f.id = a.id AND f.ts = a.ts AND f.tf = a.tf
        WHERE a.id = :asset_id
          AND a.tf = :tf
          AND a.indicator = :indicator
          AND a.params_hash = :params_hash
          AND a.alignment_source = 'multi_tf'
          AND a.roll = FALSE
        ORDER BY a.ts
        """
    )
    df = pd.read_sql(
        sql,
        conn,
        params={
            "asset_id": asset_id,
            "tf": tf,
            "indicator": indicator,
            "params_hash": params_hash,
        },
    )

    if df.empty:
        return pd.DataFrame(), pd.Series(dtype=float)

    # CRITICAL: fix mixed-tz-offset object dtype on Windows
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")

    close_series = df["close"].copy()

    # Build disambiguated column names: {indicator}_{params_hash_short}_{col}
    # Use first 8 chars of params_hash to keep names manageable
    hash_short = params_hash[:8]
    prefix = f"{indicator}_{hash_short}"

    ama_cols = {}
    for col in _AMA_FEATURE_COLS:
        if col in df.columns:
            col_data = df[col]
            # Skip all-NULL columns (e.g. er for non-KAMA indicators)
            if col_data.notna().any():
                ama_cols[f"{prefix}_{col}"] = col_data

    if not ama_cols:
        return pd.DataFrame(), close_series

    ama_features_df = pd.DataFrame(ama_cols)
    return ama_features_df, close_series


# ---------------------------------------------------------------------------
# IC computation helpers
# ---------------------------------------------------------------------------


def _rows_from_ic_df(
    ic_df: pd.DataFrame,
    asset_id: int,
    tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    tf_days_nominal: int,
) -> list[dict]:
    """
    Convert an IC result DataFrame into a list of dicts for save_ic_results().

    Handles both full-sample IC (regime_col/regime_label sentinel columns present)
    and regime-conditional IC (regime_col/regime_label contain actual values).
    """
    rows = []
    for _, row in ic_df.iterrows():
        r_col = row.get("regime_col", "all")
        r_label = row.get("regime_label", "all")

        rows.append(
            {
                "asset_id": asset_id,
                "tf": tf,
                "feature": row["feature"],
                "horizon": int(row["horizon"]),
                "horizon_days": int(row["horizon"]) * tf_days_nominal,
                "return_type": row["return_type"],
                "regime_col": r_col if pd.notna(r_col) else "all",
                "regime_label": r_label if pd.notna(r_label) else "all",
                "train_start": train_start,
                "train_end": train_end,
                "ic": row.get("ic"),
                "ic_t_stat": row.get("ic_t_stat"),
                "ic_p_value": row.get("ic_p_value"),
                "ic_ir": row.get("ic_ir"),
                "ic_ir_t_stat": row.get("ic_ir_t_stat"),
                "turnover": row.get("turnover"),
                "n_obs": row.get("n_obs"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Module-level worker function (must be picklable for Windows `spawn`)
# ---------------------------------------------------------------------------


def _ic_worker(task: ICWorkerTask) -> dict:
    """
    Worker function for parallel IC sweep.

    Called by multiprocessing.Pool.imap_unordered(). Must be module-level
    for pickling to work on Windows (spawn start method).

    Creates its own engine with NullPool to prevent connection pooling
    issues across processes.

    Returns dict with {asset_id, tf, n_written, elapsed, error}.
    """
    _logger = logging.getLogger(f"ic_worker.{task.asset_id}.{task.tf}")
    pair_start = time.time()
    engine = None
    try:
        engine = create_engine(task.db_url, poolclass=NullPool)
        feature_cols = list(task.feature_cols)
        horizons = list(task.horizons)
        return_types = list(task.return_types)

        with engine.begin() as conn:
            # Load all features + close
            features_df, close_series = _load_features_and_close(
                conn, task.asset_id, task.tf, feature_cols
            )

            if features_df.empty or close_series.empty:
                _logger.warning(
                    "No data for asset_id=%d tf=%s — skipping", task.asset_id, task.tf
                )
                return {
                    "asset_id": task.asset_id,
                    "tf": task.tf,
                    "n_written": 0,
                    "elapsed": time.time() - pair_start,
                    "error": None,
                }

            train_start = features_df.index.min()
            train_end = features_df.index.max()

            valid_feature_cols = [
                c for c in features_df.columns if features_df[c].notna().any()
            ]
            if not valid_feature_cols:
                return {
                    "asset_id": task.asset_id,
                    "tf": task.tf,
                    "n_written": 0,
                    "elapsed": time.time() - pair_start,
                    "error": None,
                }

            # Regime breakdown
            run_regime = (
                task.regime
                and task.asset_id in _REGIME_ASSET_IDS
                and task.tf == _REGIME_TF
            )
            regimes_df = None
            if run_regime:
                try:
                    regimes_df = load_regimes_for_asset(
                        conn, task.asset_id, task.tf, train_start, train_end
                    )
                except Exception as exc:
                    _logger.warning(
                        "Failed to load regimes for asset_id=%d tf=%s (%s)",
                        task.asset_id,
                        task.tf,
                        exc,
                    )
                    regimes_df = None
                    run_regime = False

            # Batch IC
            ic_df = batch_compute_ic(
                features_df,
                close_series,
                train_start,
                train_end,
                feature_cols=valid_feature_cols,
                horizons=horizons,
                return_types=return_types,
                rolling_window=task.rolling_window,
                tf_days_nominal=task.tf_days_nominal,
            )

            all_ic_rows: list[dict] = []
            if not ic_df.empty:
                if "regime_col" not in ic_df.columns:
                    ic_df["regime_col"] = "all"
                if "regime_label" not in ic_df.columns:
                    ic_df["regime_label"] = "all"
                all_ic_rows.extend(
                    _rows_from_ic_df(
                        ic_df,
                        task.asset_id,
                        task.tf,
                        train_start,
                        train_end,
                        task.tf_days_nominal,
                    )
                )

            # Regime breakdown
            if run_regime and regimes_df is not None and not regimes_df.empty:
                for regime_col_name in ["trend_state", "vol_state"]:
                    for feat_col in valid_feature_cols:
                        try:
                            regime_ic_df = compute_ic_by_regime(
                                features_df[feat_col],
                                close_series,
                                regimes_df,
                                train_start,
                                train_end,
                                horizons=horizons,
                                return_types=return_types,
                                rolling_window=task.rolling_window,
                                tf_days_nominal=task.tf_days_nominal,
                                regime_col=regime_col_name,
                            )
                            if not regime_ic_df.empty:
                                regime_ic_df["feature"] = feat_col
                                all_ic_rows.extend(
                                    _rows_from_ic_df(
                                        regime_ic_df,
                                        task.asset_id,
                                        task.tf,
                                        train_start,
                                        train_end,
                                        task.tf_days_nominal,
                                    )
                                )
                        except Exception as exc:
                            _logger.warning(
                                "Regime IC failed for asset_id=%d tf=%s feat=%s regime=%s: %s",
                                task.asset_id,
                                task.tf,
                                feat_col,
                                regime_col_name,
                                exc,
                            )

            # Persist
            n_written = 0
            if all_ic_rows:
                n_written = save_ic_results(conn, all_ic_rows, overwrite=task.overwrite)

            elapsed = time.time() - pair_start
            _logger.info(
                "asset_id=%d tf=%s: %d IC rows in %.1fs",
                task.asset_id,
                task.tf,
                n_written,
                elapsed,
            )
            return {
                "asset_id": task.asset_id,
                "tf": task.tf,
                "n_written": n_written,
                "elapsed": elapsed,
                "error": None,
            }

    except Exception as exc:
        elapsed = time.time() - pair_start
        _logger.error(
            "Failed asset_id=%d tf=%s: %s", task.asset_id, task.tf, exc, exc_info=True
        )
        return {
            "asset_id": task.asset_id,
            "tf": task.tf,
            "n_written": 0,
            "elapsed": elapsed,
            "error": str(exc),
        }
    finally:
        if engine is not None:
            engine.dispose()


# ---------------------------------------------------------------------------
# Main sweep functions
# ---------------------------------------------------------------------------


def _run_features_sweep(
    engine,
    pairs: list[tuple[int, str, int]],
    feature_cols: list[str],
    dim,
    horizons: list[int],
    return_types: list[str],
    rolling_window: int,
    overwrite: bool,
    regime: bool,
    asset_ids_filter: Optional[list[int]] = None,
    tf_filter: Optional[str] = None,
    workers: int = 1,
    db_url: Optional[str] = None,
) -> int:
    """
    Run IC sweep for features columns across all qualifying (asset, tf) pairs.

    When workers > 1, dispatches work via multiprocessing.Pool.imap_unordered.
    When workers == 1, runs the existing sequential path.

    Returns total IC rows written to DB.
    """
    # Pre-filter pairs to only those matching the scope filters
    filtered_pairs = [
        (aid, tf, n)
        for aid, tf, n in pairs
        if (asset_ids_filter is None or aid in asset_ids_filter)
        and (tf_filter is None or tf == tf_filter)
    ]

    if not filtered_pairs:
        logger.info("features sweep: no pairs after filtering")
        return 0

    # --- Parallel path ---
    if workers > 1 and len(filtered_pairs) > 1:
        if db_url is None:
            raise ValueError("db_url is required for parallel dispatch (workers > 1)")

        # Build tasks — resolve tf_days_nominal in main process
        tasks: list[ICWorkerTask] = []
        for asset_id, tf, n_rows in filtered_pairs:
            try:
                tf_days_nominal = dim.tf_days(tf)
            except (KeyError, AttributeError):
                tf_days_nominal = 1

            tasks.append(
                ICWorkerTask(
                    asset_id=asset_id,
                    tf=tf,
                    n_rows=n_rows,
                    db_url=db_url,
                    feature_cols=tuple(feature_cols),
                    horizons=tuple(horizons),
                    return_types=tuple(return_types),
                    rolling_window=rolling_window,
                    tf_days_nominal=tf_days_nominal,
                    overwrite=overwrite,
                    regime=regime,
                )
            )

        n_workers = min(workers, len(tasks))
        logger.info(
            "Parallel dispatch: %d tasks across %d workers",
            len(tasks),
            n_workers,
        )

        total_written = 0
        n_done = 0
        n_errors = 0

        with Pool(processes=n_workers) as p:
            for result in p.imap_unordered(_ic_worker, tasks):
                n_done += 1
                total_written += result["n_written"]
                if result["error"]:
                    n_errors += 1

                if n_done % 10 == 0 or n_done == len(tasks):
                    logger.info(
                        "[features] progress: %d/%d done, %d rows written, %d errors",
                        n_done,
                        len(tasks),
                        total_written,
                        n_errors,
                    )

        logger.info(
            "features sweep done (parallel): %d rows written, %d errors",
            total_written,
            n_errors,
        )
        return total_written

    # --- Sequential path (workers == 1) ---
    total_written = 0
    total_pairs = len(filtered_pairs)
    skipped_sparse = 0

    for idx, (asset_id, tf, n_rows) in enumerate(filtered_pairs):
        pair_start = time.time()
        logger.info(
            "[features %d/%d] asset_id=%d tf=%s n_rows=%d",
            idx + 1,
            total_pairs,
            asset_id,
            tf,
            n_rows,
        )

        # Get tf_days_nominal
        try:
            tf_days_nominal = dim.tf_days(tf)
        except (KeyError, AttributeError):
            logger.warning(
                "tf=%s not found in dim_timeframe — defaulting tf_days_nominal=1", tf
            )
            tf_days_nominal = 1

        # Each pair uses its own transaction for isolation
        try:
            with engine.begin() as conn:
                # Load all features + close in one query
                features_df, close_series = _load_features_and_close(
                    conn, asset_id, tf, feature_cols
                )

                if features_df.empty or close_series.empty:
                    logger.warning(
                        "No data returned for asset_id=%d tf=%s — skipping",
                        asset_id,
                        tf,
                    )
                    skipped_sparse += 1
                    continue

                # Derive train window from loaded data
                train_start = features_df.index.min()
                train_end = features_df.index.max()

                # Filter to columns that actually have non-null data
                valid_feature_cols = [
                    c for c in features_df.columns if features_df[c].notna().any()
                ]
                if not valid_feature_cols:
                    logger.warning(
                        "All feature columns are null for asset_id=%d tf=%s — skipping",
                        asset_id,
                        tf,
                    )
                    skipped_sparse += 1
                    continue

                # Determine if regime breakdown should be run
                run_regime = (
                    regime and asset_id in _REGIME_ASSET_IDS and tf == _REGIME_TF
                )

                all_ic_rows: list[dict] = []

                # Load regime data if needed
                regimes_df = None
                if run_regime:
                    try:
                        regimes_df = load_regimes_for_asset(
                            conn, asset_id, tf, train_start, train_end
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to load regimes for asset_id=%d tf=%s (%s) — using full-sample IC",
                            asset_id,
                            tf,
                            exc,
                        )
                        regimes_df = None
                        run_regime = False

                # Run batch IC for all features at once
                ic_df = batch_compute_ic(
                    features_df,
                    close_series,
                    train_start,
                    train_end,
                    feature_cols=valid_feature_cols,
                    horizons=horizons,
                    return_types=return_types,
                    rolling_window=rolling_window,
                    tf_days_nominal=tf_days_nominal,
                )

                if not ic_df.empty:
                    # Add regime sentinel for full-sample path
                    if "regime_col" not in ic_df.columns:
                        ic_df["regime_col"] = "all"
                    if "regime_label" not in ic_df.columns:
                        ic_df["regime_label"] = "all"

                    all_ic_rows.extend(
                        _rows_from_ic_df(
                            ic_df, asset_id, tf, train_start, train_end, tf_days_nominal
                        )
                    )

                # Regime breakdown for BTC/ETH 1D
                if run_regime and regimes_df is not None and not regimes_df.empty:
                    for regime_col_name in ["trend_state", "vol_state"]:
                        for feat_col in valid_feature_cols:
                            try:
                                regime_ic_df = compute_ic_by_regime(
                                    features_df[feat_col],
                                    close_series,
                                    regimes_df,
                                    train_start,
                                    train_end,
                                    horizons=horizons,
                                    return_types=return_types,
                                    rolling_window=rolling_window,
                                    tf_days_nominal=tf_days_nominal,
                                    regime_col=regime_col_name,
                                )
                                if not regime_ic_df.empty:
                                    regime_ic_df["feature"] = feat_col
                                    all_ic_rows.extend(
                                        _rows_from_ic_df(
                                            regime_ic_df,
                                            asset_id,
                                            tf,
                                            train_start,
                                            train_end,
                                            tf_days_nominal,
                                        )
                                    )
                            except Exception as exc:
                                logger.warning(
                                    "Regime IC failed for asset_id=%d tf=%s feat=%s regime_col=%s: %s",
                                    asset_id,
                                    tf,
                                    feat_col,
                                    regime_col_name,
                                    exc,
                                )

                # Persist results
                n_written = 0
                if all_ic_rows:
                    n_written = save_ic_results(conn, all_ic_rows, overwrite=overwrite)
                    total_written += n_written

                elapsed = time.time() - pair_start
                logger.info(
                    "[features] asset_id=%d tf=%s: %d IC rows written in %.1fs",
                    asset_id,
                    tf,
                    n_written,
                    elapsed,
                )

        except Exception as exc:
            logger.error(
                "Failed processing asset_id=%d tf=%s: %s",
                asset_id,
                tf,
                exc,
                exc_info=True,
            )
            skipped_sparse += 1

    logger.info(
        "features sweep done: %d rows written, %d pairs skipped/errored",
        total_written,
        skipped_sparse,
    )
    return total_written


def _run_ama_sweep(
    engine,
    combos: list[tuple[int, str, str, str, int]],
    dim,
    horizons: list[int],
    return_types: list[str],
    rolling_window: int,
    overwrite: bool,
    asset_ids_filter: Optional[list[int]] = None,
    tf_filter: Optional[str] = None,
) -> int:
    """
    Run IC sweep for AMA indicator columns from ama_multi_tf_u.

    Returns total IC rows written to DB.
    """
    total_written = 0
    total_combos = len(combos)
    skipped = 0

    for idx, (asset_id, tf, indicator, params_hash, n_rows) in enumerate(combos):
        # Apply optional filters
        if asset_ids_filter is not None and asset_id not in set(asset_ids_filter):
            continue
        if tf_filter is not None and tf != tf_filter:
            continue

        combo_start = time.time()
        logger.info(
            "[AMA %d/%d] asset_id=%d tf=%s indicator=%s params_hash=%s n_rows=%d",
            idx + 1,
            total_combos,
            asset_id,
            tf,
            indicator,
            params_hash[:8],
            n_rows,
        )

        try:
            tf_days_nominal = dim.tf_days(tf)
        except (KeyError, AttributeError):
            logger.warning(
                "tf=%s not found in dim_timeframe — defaulting tf_days_nominal=1", tf
            )
            tf_days_nominal = 1

        try:
            with engine.begin() as conn:
                ama_df, close_series = _load_ama_data_with_close(
                    conn, asset_id, tf, indicator, params_hash
                )

                if ama_df.empty or close_series.empty:
                    logger.warning(
                        "No AMA data for asset_id=%d tf=%s %s/%s — skipping",
                        asset_id,
                        tf,
                        indicator,
                        params_hash[:8],
                    )
                    skipped += 1
                    continue

                # Use the AMA data's time range as train window
                train_start = ama_df.index.min()
                train_end = ama_df.index.max()

                valid_feature_cols = [
                    c for c in ama_df.columns if ama_df[c].notna().any()
                ]
                if not valid_feature_cols:
                    logger.warning(
                        "All AMA columns null for asset_id=%d tf=%s %s/%s — skipping",
                        asset_id,
                        tf,
                        indicator,
                        params_hash[:8],
                    )
                    skipped += 1
                    continue

                ic_df = batch_compute_ic(
                    ama_df,
                    close_series,
                    train_start,
                    train_end,
                    feature_cols=valid_feature_cols,
                    horizons=horizons,
                    return_types=return_types,
                    rolling_window=rolling_window,
                    tf_days_nominal=tf_days_nominal,
                )

                if ic_df.empty:
                    skipped += 1
                    continue

                # Add regime sentinel (AMA doesn't get regime breakdown in discovery phase)
                if "regime_col" not in ic_df.columns:
                    ic_df["regime_col"] = "all"
                if "regime_label" not in ic_df.columns:
                    ic_df["regime_label"] = "all"

                all_ic_rows = _rows_from_ic_df(
                    ic_df, asset_id, tf, train_start, train_end, tf_days_nominal
                )

                n_written = 0
                if all_ic_rows:
                    n_written = save_ic_results(conn, all_ic_rows, overwrite=overwrite)
                    total_written += n_written

                elapsed = time.time() - combo_start
                logger.info(
                    "[AMA] asset_id=%d tf=%s %s/%s: %d IC rows written in %.1fs",
                    asset_id,
                    tf,
                    indicator,
                    params_hash[:8],
                    n_written,
                    elapsed,
                )

        except Exception as exc:
            logger.error(
                "Failed processing AMA asset_id=%d tf=%s %s/%s: %s",
                asset_id,
                tf,
                indicator,
                params_hash[:8],
                exc,
                exc_info=True,
            )
            skipped += 1

    logger.info(
        "AMA sweep done: %d rows written, %d combos skipped",
        total_written,
        skipped,
    )
    return total_written


# ---------------------------------------------------------------------------
# Feature ranking output
# ---------------------------------------------------------------------------


def _produce_feature_ranking(
    engine, output_path: Path, top_n: int = 20
) -> pd.DataFrame:
    """
    Query ic_results and produce a feature ranking by mean |IC-IR| at horizon=1 arith.

    Saves CSV to output_path and returns the full ranking DataFrame.
    """
    sql = text(
        """
        SELECT
            feature,
            AVG(ABS(ic))            AS mean_abs_ic,
            AVG(ic_ir)              AS mean_ic_ir,
            AVG(ABS(ic_ir))         AS mean_abs_ic_ir,
            COUNT(*)                AS n_observations,
            COUNT(DISTINCT asset_id || '_' || tf) AS n_asset_tf_pairs
        FROM public.ic_results
        WHERE horizon = 1
          AND return_type = 'arith'
          AND regime_col = 'all'
          AND regime_label = 'all'
          AND ic IS NOT NULL
        GROUP BY feature
        ORDER BY AVG(ABS(ic_ir)) DESC NULLS LAST
        """
    )

    with engine.connect() as conn:
        ranking_df = pd.read_sql(sql, conn)

    if ranking_df.empty:
        logger.warning("No IC results found for feature ranking")
        return ranking_df

    # Save full ranking to CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ranking_df.to_csv(output_path, index=False)
    logger.info(
        "Feature ranking CSV saved to %s (%d features)", output_path, len(ranking_df)
    )

    # Print top-N to console
    top_df = ranking_df.head(top_n)
    print("\n" + "=" * 70)
    print(f"TOP-{top_n} FEATURES BY MEAN |IC-IR| (horizon=1, arith, full-sample)")
    print("=" * 70)
    print(
        top_df[
            ["feature", "mean_abs_ic", "mean_abs_ic_ir", "n_asset_tf_pairs"]
        ].to_string(
            index=False,
            float_format=lambda x: f"{x:.4f}",
        )
    )
    print("=" * 70 + "\n")

    # Call out AMA features if any appear in top-N
    ama_indicators = ["KAMA", "DEMA", "TEMA", "HMA"]
    ama_in_top = top_df[top_df["feature"].str.startswith(tuple(ama_indicators))]
    if not ama_in_top.empty:
        print(f"AMA-derived features in top-{top_n}:")
        print(
            ama_in_top[["feature", "mean_abs_ic", "mean_abs_ic_ir"]].to_string(
                index=False
            )
        )
        print()

    return ranking_df


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_ic_sweep",
        description=(
            "Batch IC sweep across all assets x all TFs x all features.\n\n"
            "Evaluates features columns AND AMA indicator columns from ama_multi_tf_u.\n"
            "Results are persisted to ic_results and a ranking CSV is saved to "
            "reports/bakeoff/feature_ic_ranking.csv."
        ),
    )

    # Scope selection
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_assets",
        help="Full sweep: all qualifying asset-TF pairs (features + AMA).",
    )
    parser.add_argument(
        "--assets",
        nargs="+",
        type=int,
        metavar="ID",
        dest="asset_ids",
        default=None,
        help="Specific asset IDs to evaluate (e.g. --assets 1 1027).",
    )
    parser.add_argument(
        "--tf",
        type=str,
        metavar="TF",
        default=None,
        dest="tf_filter",
        help="Specific timeframe to evaluate (e.g. --tf 1D). Default: all qualifying TFs.",
    )

    # Filtering
    parser.add_argument(
        "--min-bars",
        type=int,
        default=500,
        metavar="N",
        dest="min_bars",
        help="Minimum bars for an asset-TF pair to qualify (default: 500).",
    )

    # Horizon / return type
    parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=[1, 2, 3, 5, 10, 20, 60],
        metavar="N",
        help="Forward return horizons in bars (default: 1 2 3 5 10 20 60).",
    )
    parser.add_argument(
        "--return-types",
        nargs="+",
        default=["arith", "log"],
        metavar="TYPE",
        dest="return_types",
        help="Return types: arith and/or log (default: arith log).",
    )
    parser.add_argument(
        "--rolling-window",
        type=int,
        default=63,
        metavar="N",
        dest="rolling_window",
        help="Rolling IC window size in bars (default: 63).",
    )

    # Regime breakdown
    parser.add_argument(
        "--regime",
        action="store_true",
        default=False,
        help=(
            "Enable regime-conditional IC for BTC/ETH 1D "
            "(uses regimes.l2_label -> trend_state / vol_state)."
        ),
    )

    # Source flags
    parser.add_argument(
        "--skip-ama",
        action="store_true",
        default=False,
        dest="skip_ama",
        help="Skip AMA table sweep (evaluates features only).",
    )

    # Persistence
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=True,
        help="Upsert existing IC rows (ON CONFLICT DO UPDATE). Default True for bake-off.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_false",
        dest="overwrite",
        help="Use append-only semantics (ON CONFLICT DO NOTHING).",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="List qualifying asset-TF pairs and AMA combos without computing IC.",
    )

    # Output
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        metavar="DIR",
        dest="output_dir",
        help="Output directory for feature ranking CSV. Default: reports/bakeoff/.",
    )

    # Parallelism
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        dest="workers",
        help=(
            "Number of parallel worker processes for features sweep. "
            "Default: 1 (sequential). Recommended: 4-8 for full sweep."
        ),
    )

    # Verbosity
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Resolve output directory
    if args.output_dir:
        ranking_csv_path = Path(args.output_dir) / "feature_ic_ranking.csv"
    else:
        # Find project root (look for pyproject.toml)
        cwd = Path.cwd()
        project_root = cwd
        for _ in range(5):
            if (project_root / "pyproject.toml").exists():
                break
            parent = project_root.parent
            if parent == project_root:
                break
            project_root = parent
        ranking_csv_path = (
            project_root / "reports" / "bakeoff" / "feature_ic_ranking.csv"
        )

    sweep_start = time.time()

    # Connect to DB
    db_url = resolve_db_url()
    engine = create_engine(db_url, poolclass=pool.NullPool)

    # Load DimTimeframe
    try:
        dim = DimTimeframe.from_db(db_url)
        logger.info("DimTimeframe loaded: %d timeframes", len(list(dim.list_tfs())))
    except Exception as exc:
        logger.warning(
            "Failed to load DimTimeframe (%s) — tf_days_nominal will default to 1", exc
        )

        class _FallbackDim:
            def tf_days(self, tf: str) -> int:
                return 1

        dim = _FallbackDim()

    total_written = 0

    # --- Discover qualifying pairs (separate connections, each in own transaction) ---
    logger.info(
        "Discovering qualifying features asset-TF pairs (min_bars=%d)...",
        args.min_bars,
    )
    cmc_pairs = _discover_features_pairs(engine, args.min_bars)

    # Apply scope filters for display / dry-run output
    asset_ids_set = set(args.asset_ids) if args.asset_ids else None

    cmc_pairs_display = [
        (aid, tf, n)
        for aid, tf, n in cmc_pairs
        if (asset_ids_set is None or aid in asset_ids_set)
        and (args.tf_filter is None or tf == args.tf_filter)
    ]

    logger.info("features: %d pairs qualify after scope filter", len(cmc_pairs_display))

    # --- Discover feature columns ---
    try:
        all_cols = get_columns(engine, "public.features")
        feature_cols = [
            c
            for c in all_cols
            if c not in _NON_FEATURE_COLS and c not in _EXTRA_NON_FEATURE_COLS
        ]
        logger.info(
            "features: %d feature columns discovered (of %d total cols)",
            len(feature_cols),
            len(all_cols),
        )
    except Exception as exc:
        logger.error("Failed to discover features columns: %s", exc)
        return 1

    # --- AMA combos ---
    ama_combos: list[tuple[int, str, str, str, int]] = []
    ama_combos_display: list[tuple[int, str, str, str, int]] = []

    if not args.skip_ama:
        logger.info("Discovering qualifying AMA combos (min_bars=%d)...", args.min_bars)
        ama_combos = _discover_ama_combos(engine, args.min_bars)
        ama_combos_display = [
            (aid, tf, ind, ph, n)
            for aid, tf, ind, ph, n in ama_combos
            if (asset_ids_set is None or aid in asset_ids_set)
            and (args.tf_filter is None or tf == args.tf_filter)
        ]
        logger.info(
            "AMA: %d combos qualify after scope filter", len(ama_combos_display)
        )
    else:
        logger.info("--skip-ama: skipping AMA discovery")

    # --- Dry run output ---
    if args.dry_run:
        print(f"\n[DRY RUN] features qualifying pairs ({len(cmc_pairs_display)}):")
        for asset_id, tf, n_rows in cmc_pairs_display:
            print(f"  asset_id={asset_id} tf={tf} n_rows={n_rows}")

        if not args.skip_ama:
            print(f"\n[DRY RUN] AMA qualifying combos ({len(ama_combos_display)}):")
            for asset_id, tf, indicator, params_hash, n_rows in ama_combos_display:
                print(
                    f"  asset_id={asset_id} tf={tf} indicator={indicator} "
                    f"params_hash={params_hash[:8]} n_rows={n_rows}"
                )

        sweep_elapsed = time.time() - sweep_start
        print(
            f"\n[DRY RUN complete] "
            f"{len(cmc_pairs_display)} features pairs, "
            f"{len(ama_combos_display) if not args.skip_ama else 'skipped'} AMA combos "
            f"({sweep_elapsed:.1f}s)"
        )
        return 0

    # --- Source A: features sweep ---
    logger.info(
        "Starting features IC sweep (%d pairs, %d feature cols)...",
        len(cmc_pairs_display),
        len(feature_cols),
    )
    n_written = _run_features_sweep(
        engine=engine,
        pairs=cmc_pairs,
        feature_cols=feature_cols,
        dim=dim,
        horizons=args.horizons,
        return_types=args.return_types,
        rolling_window=args.rolling_window,
        overwrite=args.overwrite,
        regime=args.regime,
        asset_ids_filter=args.asset_ids,
        tf_filter=args.tf_filter,
        workers=args.workers,
        db_url=db_url,
    )
    total_written += n_written
    logger.info("features sweep complete: %d IC rows written", n_written)

    # --- Source B: AMA sweep ---
    if not args.skip_ama and ama_combos:
        logger.info("Starting AMA IC sweep (%d combos)...", len(ama_combos_display))
        n_written = _run_ama_sweep(
            engine=engine,
            combos=ama_combos,
            dim=dim,
            horizons=args.horizons,
            return_types=args.return_types,
            rolling_window=args.rolling_window,
            overwrite=args.overwrite,
            asset_ids_filter=args.asset_ids,
            tf_filter=args.tf_filter,
        )
        total_written += n_written
        logger.info("AMA sweep complete: %d IC rows written", n_written)
    elif args.skip_ama:
        logger.info("--skip-ama: AMA sweep skipped")
    else:
        logger.info("No AMA combos found — skipping AMA sweep")

    # --- Feature ranking ---
    logger.info("Producing feature ranking...")
    try:
        _produce_feature_ranking(engine, ranking_csv_path, top_n=20)
    except Exception as exc:
        logger.error("Failed to produce feature ranking: %s", exc, exc_info=True)

    sweep_elapsed = time.time() - sweep_start
    minutes = int(sweep_elapsed // 60)
    seconds = int(sweep_elapsed % 60)

    logger.info(
        "IC sweep complete: %d total IC rows written in %dm%ds",
        total_written,
        minutes,
        seconds,
    )

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
