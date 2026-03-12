#!/usr/bin/env python
"""
Meta-labeling pipeline: train a RandomForest secondary model over primary signals.

Connects primary signal directions to triple barrier label outcomes to build
binary training targets (y=1 when signal direction was correct), trains a
RandomForestClassifier with PurgedKFoldSplitter CV, then scores all signal entries
and persists trade probabilities to meta_label_results.

Reference: AFML Ch.10 -- Meta-Labeling (Lopez de Prado, 2018)

Usage:
    # EMA crossover on BTC
    python -m ta_lab2.scripts.labeling.run_meta_labeling --ids 1 --signal-type ema_crossover

    # RSI mean revert on BTC + ETH with custom barriers
    python -m ta_lab2.scripts.labeling.run_meta_labeling --ids 1,1027 \\
        --signal-type rsi_mean_revert --pt 1.5 --sl 1.5 --vertical-bars 10

    # Dry-run (logs metrics, does NOT write to DB)
    python -m ta_lab2.scripts.labeling.run_meta_labeling --ids 1 \\
        --signal-type ema_crossover --dry-run

    # All assets, ATR breakout, 5 CV folds
    python -m ta_lab2.scripts.labeling.run_meta_labeling --all \\
        --signal-type atr_breakout --n-folds 5

Pipeline per asset:
    1. Precondition check: triple barrier labels exist + signals exist for this asset
    2. Load triple barrier labels from triple_barrier_labels
    3. Load signal directions from signal table (position_state='open' entries)
    4. Align signals to labels by timestamp (inner join on t0/ts)
    5. Load features from features for aligned timestamps
    6. Construct meta-labels: y = (primary_side * barrier_bin > 0).astype(int)
    7. Build t1_series from barrier labels for PurgedKFoldSplitter
    8. CV evaluation with PurgedKFoldSplitter: log per-fold AUC
    9. Final model: train on all data, score all signal entries
    10. Persist to meta_label_results (unless --dry-run)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.backtests.cv import PurgedKFoldSplitter
from ta_lab2.config import TARGET_DB_URL
from ta_lab2.labeling.meta_labeler import MetaLabeler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal table configuration
# ---------------------------------------------------------------------------

# Maps signal_type -> (table_name, entry_ts_col, direction_col)
# Signal tables use 'ts' as the event timestamp (same column that's in features)
# and 'direction' as the long/short indicator.
SIGNAL_TABLE_MAP = {
    "ema_crossover": (
        "signals_ema_crossover",
        "ts",
        "direction",
    ),
    "rsi_mean_revert": (
        "signals_rsi_mean_revert",
        "ts",
        "direction",
    ),
    "atr_breakout": (
        "signals_atr_breakout",
        "ts",
        "direction",
    ),
}

# Feature columns to use in meta-labeling (numeric only, no outlier flags)
# Chosen to give broad coverage: returns, vol estimators, TA indicators
META_LABEL_FEATURE_COLS = [
    # Bar returns (canonical + z-scores)
    "ret_arith",
    "ret_log",
    "ret_arith_zscore_30",
    "ret_arith_zscore_90",
    "ret_log_zscore_30",
    "ret_log_zscore_90",
    # Volatility estimators
    "vol_parkinson_20",
    "vol_parkinson_63",
    "vol_gk_20",
    "vol_gk_63",
    "vol_log_roll_20",
    "vol_log_roll_63",
    "atr_14",
    # Vol z-scores
    "vol_parkinson_20_zscore",
    "vol_gk_20_zscore",
    # TA indicators
    "rsi_14",
    "rsi_14_zscore",
    "macd_12_26",
    "macd_hist_12_26_9",
    "stoch_k_14",
    "bb_width_20",
    "adx_14",
]

# Minimum aligned sample count to train a useful model
MIN_ALIGNED_SAMPLES = 20
# Minimum positive class count for meaningful AUC
MIN_POSITIVE_SAMPLES = 5


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Meta-labeling pipeline: train RF over primary signals using triple barrier labels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # BTC, EMA crossover signals
  python -m ta_lab2.scripts.labeling.run_meta_labeling --ids 1 --signal-type ema_crossover

  # BTC+ETH, RSI, custom barriers, 5 folds, dry-run
  python -m ta_lab2.scripts.labeling.run_meta_labeling --ids 1,1027 \\
      --signal-type rsi_mean_revert --pt 1.5 --sl 1.5 --n-folds 5 --dry-run

  # All assets, ATR breakout
  python -m ta_lab2.scripts.labeling.run_meta_labeling --all --signal-type atr_breakout

Preconditions:
  Triple barrier labels must exist in triple_barrier_labels.
  Signals must exist in the appropriate signal table.
  To generate labels: python -m ta_lab2.scripts.labeling.refresh_triple_barrier_labels --ids 1 --tf 1D
  To generate EMA signals: python -m ta_lab2.scripts.signals.refresh_signals_ema_crossover --ids 1
        """,
    )

    # Asset selection
    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument(
        "--ids",
        help="Comma-separated asset IDs (e.g. '1,52,1027')",
    )
    id_group.add_argument(
        "--all",
        action="store_true",
        help="Process all assets with triple barrier labels for the given tf",
    )

    # Timeframe
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe (default: '1D')",
    )

    # Signal type
    parser.add_argument(
        "--signal-type",
        choices=list(SIGNAL_TABLE_MAP.keys()),
        required=True,
        help="Signal type to use as primary model",
    )

    # Barrier parameters (to match which labels to load)
    parser.add_argument(
        "--pt", type=float, default=1.0, help="Profit-taking multiplier (default: 1.0)"
    )
    parser.add_argument(
        "--sl", type=float, default=1.0, help="Stop-loss multiplier (default: 1.0)"
    )
    parser.add_argument(
        "--vertical-bars",
        type=int,
        default=10,
        help="Vertical barrier bar count (default: 10)",
    )

    # Model parameters
    parser.add_argument(
        "--n-estimators", type=int, default=100, help="RF trees (default: 100)"
    )
    parser.add_argument(
        "--n-folds",
        type=int,
        default=5,
        help="CV folds for PurgedKFoldSplitter (default: 5)",
    )

    # Execution control
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and log meta-label results but do NOT write to DB",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--db-url",
        help="Database URL (defaults to TARGET_DB_URL env var)",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Asset resolution
# ---------------------------------------------------------------------------


def load_asset_ids(
    engine,
    ids_arg: Optional[str],
    all_ids: bool,
    tf: str,
    pt: float,
    sl: float,
    vertical_bars: int,
) -> list[int]:
    """Resolve the list of asset IDs to process."""
    if ids_arg:
        return [int(i.strip()) for i in ids_arg.split(",")]

    if all_ids:
        q = text(
            "SELECT DISTINCT asset_id FROM triple_barrier_labels "
            "WHERE tf = :tf "
            "  AND pt_multiplier = :pt "
            "  AND sl_multiplier = :sl "
            "  AND vertical_bars = :vb "
            "ORDER BY asset_id"
        )
        with engine.connect() as conn:
            rows = conn.execute(
                q, {"tf": tf, "pt": pt, "sl": sl, "vb": vertical_bars}
            ).fetchall()
        return [r[0] for r in rows]

    return []


# ---------------------------------------------------------------------------
# Precondition checks
# ---------------------------------------------------------------------------


def check_preconditions(
    engine,
    asset_id: int,
    tf: str,
    pt: float,
    sl: float,
    vertical_bars: int,
    signal_type: str,
) -> tuple[bool, str]:
    """
    Verify that triple barrier labels and signals exist for this asset.

    Returns (ok: bool, error_message: str).
    If ok=True, error_message is empty.
    """
    # Check triple barrier labels
    q_labels = text(
        "SELECT COUNT(*) FROM triple_barrier_labels "
        "WHERE asset_id = :asset_id "
        "  AND tf = :tf "
        "  AND pt_multiplier = :pt "
        "  AND sl_multiplier = :sl "
        "  AND vertical_bars = :vb"
    )
    with engine.connect() as conn:
        n_labels = conn.execute(
            q_labels,
            {"asset_id": asset_id, "tf": tf, "pt": pt, "sl": sl, "vb": vertical_bars},
        ).scalar()

    if not n_labels or n_labels == 0:
        return False, (
            f"No triple barrier labels for asset_id={asset_id}, tf={tf}, "
            f"pt={pt}, sl={sl}, vb={vertical_bars}. "
            f"Run first:\n"
            f"  python -m ta_lab2.scripts.labeling.refresh_triple_barrier_labels "
            f"--ids {asset_id} --tf {tf} --pt {pt} --sl {sl} --vertical-bars {vertical_bars}"
        )

    # Check signals exist
    signal_table, ts_col, direction_col = SIGNAL_TABLE_MAP[signal_type]
    q_signals = text(
        f"SELECT COUNT(*) FROM {signal_table} "
        f"WHERE id = :asset_id AND position_state = 'open'"
    )
    with engine.connect() as conn:
        n_signals = conn.execute(q_signals, {"asset_id": asset_id}).scalar()

    if not n_signals or n_signals == 0:
        script_map = {
            "ema_crossover": "refresh_signals_ema_crossover",
            "rsi_mean_revert": "refresh_signals_rsi_mean_revert",
            "atr_breakout": "refresh_signals_atr_breakout",
        }
        script = script_map[signal_type]
        return False, (
            f"No {signal_type} signals for asset_id={asset_id}. "
            f"Run first:\n"
            f"  python -m ta_lab2.scripts.signals.{script} --ids {asset_id}"
        )

    return True, ""


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_triple_barrier_labels(
    engine,
    asset_id: int,
    tf: str,
    pt: float,
    sl: float,
    vertical_bars: int,
) -> pd.DataFrame:
    """
    Load triple barrier labels for one asset from triple_barrier_labels.

    Returns DataFrame with columns: t0, t1, bin, barrier_type, daily_vol.
    Index: RangeIndex (t0 stored as column, not index).
    """
    q = text(
        "SELECT t0, t1, bin, barrier_type, daily_vol "
        "FROM triple_barrier_labels "
        "WHERE asset_id = :asset_id "
        "  AND tf = :tf "
        "  AND pt_multiplier = :pt "
        "  AND sl_multiplier = :sl "
        "  AND vertical_bars = :vb "
        "ORDER BY t0"
    )
    with engine.connect() as conn:
        df = pd.read_sql(
            q,
            conn,
            params={
                "asset_id": asset_id,
                "tf": tf,
                "pt": pt,
                "sl": sl,
                "vb": vertical_bars,
            },
        )

    if df.empty:
        return df

    df["t0"] = pd.to_datetime(df["t0"], utc=True)
    df["t1"] = pd.to_datetime(df["t1"], utc=True)
    return df


def load_signals(
    engine,
    asset_id: int,
    signal_type: str,
) -> pd.DataFrame:
    """
    Load open-position signal entries for one asset.

    Returns DataFrame with columns: ts (tz-aware UTC), direction (+1 or -1 as int).
    Only loads position_state='open' rows (entry events).
    """
    signal_table, ts_col, direction_col = SIGNAL_TABLE_MAP[signal_type]

    q = text(
        f"SELECT {ts_col} AS signal_ts, {direction_col} AS direction "
        f"FROM {signal_table} "
        f"WHERE id = :asset_id AND position_state = 'open' "
        f"ORDER BY {ts_col}"
    )
    with engine.connect() as conn:
        df = pd.read_sql(q, conn, params={"asset_id": asset_id})

    if df.empty:
        return df

    df["signal_ts"] = pd.to_datetime(df["signal_ts"], utc=True)

    # Map 'long' -> +1, 'short' -> -1
    direction_map = {"long": 1, "short": -1}
    if df["direction"].dtype == object:
        df["primary_side"] = df["direction"].str.lower().map(direction_map)
    else:
        # Numeric direction already
        df["primary_side"] = df["direction"].astype(int)

    unmapped = df["primary_side"].isna().sum()
    if unmapped > 0:
        logger.warning(
            f"  asset_id={asset_id}: {unmapped} signals have unmapped direction values "
            f"(not 'long'/'short'). These will be dropped."
        )
        df = df.dropna(subset=["primary_side"])

    df["primary_side"] = df["primary_side"].astype(int)
    return df[["signal_ts", "primary_side"]]


def load_features_for_timestamps(
    engine,
    asset_id: int,
    tf: str,
    timestamps: list,
    feature_cols: list[str],
) -> pd.DataFrame:
    """
    Load feature rows from features for specific timestamps.

    Returns DataFrame with ts as tz-aware UTC index and feature_cols as columns.
    Rows with all-NaN features are kept (MetaLabeler handles NaN internally).
    """
    if not timestamps:
        return pd.DataFrame(columns=feature_cols)

    ts_list = [
        ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts for ts in timestamps
    ]

    # Build safe column list restricted to what meta-labeler uses
    col_sql = ", ".join(f"f.{c}" for c in feature_cols)

    q = text(
        f"SELECT f.ts, {col_sql} "
        f"FROM public.features f "
        f"WHERE f.id = :asset_id "
        f"  AND f.tf = :tf "
        f"  AND f.ts = ANY(:ts_list) "
        f"ORDER BY f.ts"
    )

    with engine.connect() as conn:
        df = pd.read_sql(
            q, conn, params={"asset_id": asset_id, "tf": tf, "ts_list": ts_list}
        )

    if df.empty:
        return pd.DataFrame(columns=feature_cols)

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    return df[feature_cols]


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO meta_label_results
    (result_id, asset_id, tf, signal_type, t0, t1_from_barrier,
     primary_side, meta_label, trade_probability,
     model_version, n_estimators, feature_set, computed_at)
VALUES
    (:result_id, :asset_id, :tf, :signal_type, :t0, :t1_from_barrier,
     :primary_side, :meta_label, :trade_probability,
     :model_version, :n_estimators, :feature_set, :computed_at)
ON CONFLICT ON CONSTRAINT uq_meta_label_key
DO UPDATE SET
    t1_from_barrier  = EXCLUDED.t1_from_barrier,
    primary_side     = EXCLUDED.primary_side,
    meta_label       = EXCLUDED.meta_label,
    trade_probability = EXCLUDED.trade_probability,
    n_estimators     = EXCLUDED.n_estimators,
    feature_set      = EXCLUDED.feature_set,
    computed_at      = EXCLUDED.computed_at
"""


def write_meta_labels(
    engine,
    asset_id: int,
    tf: str,
    signal_type: str,
    aligned_df: pd.DataFrame,
    proba: pd.Series,
    predictions: pd.Series,
    n_estimators: int,
    feature_set: str,
    model_version: str,
) -> int:
    """
    Upsert meta-label results into meta_label_results.

    Parameters
    ----------
    aligned_df : pd.DataFrame
        Contains columns: t0, t1, primary_side, bin (from barrier join).
        Index: RangeIndex.
    proba : pd.Series
        Trade probabilities in [0, 1], indexed by aligned_df.t0 timestamps.
    predictions : pd.Series
        Binary predictions {0, 1}, indexed by aligned_df.t0 timestamps.

    Returns number of rows written.
    """
    computed_at = datetime.now(timezone.utc)
    rows = []

    for _, row in aligned_df.iterrows():
        t0 = row["t0"]
        prob_val = proba.get(t0, np.nan)
        pred_val = predictions.get(t0, np.nan)

        # Coerce numpy scalars to plain Python types for psycopg2
        prob_python = float(prob_val) if pd.notna(prob_val) else None
        pred_python = int(pred_val) if pd.notna(pred_val) else None
        t1_val = row["t1"].to_pydatetime() if pd.notna(row.get("t1")) else None

        rows.append(
            {
                "result_id": str(uuid.uuid4()),
                "asset_id": int(asset_id),
                "tf": tf,
                "signal_type": signal_type,
                "t0": t0.to_pydatetime(),
                "t1_from_barrier": t1_val,
                "primary_side": int(row["primary_side"]),
                "meta_label": pred_python,
                "trade_probability": prob_python,
                "model_version": model_version,
                "n_estimators": int(n_estimators),
                "feature_set": feature_set,
                "computed_at": computed_at,
            }
        )

    with engine.begin() as conn:
        for row in rows:
            conn.execute(text(_UPSERT_SQL), row)

    return len(rows)


# ---------------------------------------------------------------------------
# Per-asset pipeline
# ---------------------------------------------------------------------------


def process_asset(
    engine,
    asset_id: int,
    tf: str,
    signal_type: str,
    pt: float,
    sl: float,
    vertical_bars: int,
    n_estimators: int,
    n_folds: int,
    feature_cols: list[str],
    dry_run: bool,
) -> dict:
    """
    Run the meta-labeling pipeline for one asset.

    Returns summary dict with keys:
      asset_id, n_aligned, cv_auc_folds, mean_auc, feature_importance_top5,
      trade_filter_rate, n_written, error
    """
    result: dict = {
        "asset_id": asset_id,
        "n_aligned": 0,
        "cv_auc_folds": [],
        "mean_auc": float("nan"),
        "feature_importance_top5": [],
        "trade_filter_rate": float("nan"),
        "n_written": 0,
        "error": None,
    }

    # ------------------------------------------------------------------
    # 1. Precondition checks
    # ------------------------------------------------------------------
    ok, msg = check_preconditions(
        engine, asset_id, tf, pt, sl, vertical_bars, signal_type
    )
    if not ok:
        logger.warning(f"  asset_id={asset_id}: precondition failed -- {msg}")
        result["error"] = msg
        return result

    # ------------------------------------------------------------------
    # 2. Load triple barrier labels
    # ------------------------------------------------------------------
    labels_df = load_triple_barrier_labels(engine, asset_id, tf, pt, sl, vertical_bars)
    if labels_df.empty:
        logger.warning(
            f"  asset_id={asset_id}: no triple barrier labels loaded. Skipping."
        )
        result["error"] = "No triple barrier labels"
        return result

    logger.debug(
        f"  asset_id={asset_id}: loaded {len(labels_df)} triple barrier labels"
    )

    # ------------------------------------------------------------------
    # 3. Load signal directions
    # ------------------------------------------------------------------
    signals_df = load_signals(engine, asset_id, signal_type)
    if signals_df.empty:
        logger.warning(
            f"  asset_id={asset_id}: no {signal_type} signals loaded. Skipping."
        )
        result["error"] = f"No {signal_type} signals"
        return result

    logger.debug(
        f"  asset_id={asset_id}: loaded {len(signals_df)} {signal_type} signal entries"
    )

    # ------------------------------------------------------------------
    # 4. Align: inner join signals to labels on timestamp (t0 = signal_ts)
    # ------------------------------------------------------------------
    # Merge: inner join on label t0 == signal signal_ts (exact timestamp match)
    # Use pd.merge on key columns (not index join) to avoid name-mismatch producing 0 rows
    aligned = pd.merge(
        labels_df.rename(columns={}),  # columns: t0, t1, bin, barrier_type, daily_vol
        signals_df.rename(columns={"signal_ts": "t0"}),  # rename to t0 for merge key
        on="t0",
        how="inner",
    )

    n_aligned = len(aligned)
    result["n_aligned"] = n_aligned

    if n_aligned < MIN_ALIGNED_SAMPLES:
        logger.warning(
            f"  asset_id={asset_id}: only {n_aligned} aligned samples "
            f"(need >= {MIN_ALIGNED_SAMPLES}). Skipping."
        )
        result["error"] = f"Too few aligned samples: {n_aligned}"
        return result

    logger.info(f"  asset_id={asset_id}: {n_aligned} aligned (signal, label) pairs")

    # ------------------------------------------------------------------
    # 5. Load features for aligned timestamps
    # ------------------------------------------------------------------
    aligned_timestamps = aligned["t0"].tolist()
    features_df = load_features_for_timestamps(
        engine, asset_id, tf, aligned_timestamps, feature_cols
    )

    # Re-align features to aligned_df order using t0 as index
    aligned_indexed = aligned.set_index("t0")
    features_aligned = features_df.reindex(aligned_indexed.index)

    if features_aligned.empty or features_aligned.isnull().all(axis=None):
        logger.warning(
            f"  asset_id={asset_id}: no features loaded for aligned timestamps. "
            "Ensure features is populated for this asset/tf."
        )
        result["error"] = "No features for aligned timestamps"
        return result

    n_feat_rows = features_aligned.notna().any(axis=1).sum()
    logger.debug(
        f"  asset_id={asset_id}: {n_feat_rows}/{n_aligned} feature rows have data"
    )

    # ------------------------------------------------------------------
    # 6. Construct meta-labels
    # ------------------------------------------------------------------
    primary_side = aligned_indexed["primary_side"]
    barrier_bin = aligned_indexed["bin"]
    y = MetaLabeler.construct_meta_labels(primary_side, barrier_bin)

    n_pos = int(y.sum())
    n_neg = int((y == 0).sum())
    logger.info(f"  asset_id={asset_id}: meta-labels y=1: {n_pos}, y=0: {n_neg}")

    if n_pos < MIN_POSITIVE_SAMPLES:
        logger.warning(
            f"  asset_id={asset_id}: only {n_pos} positive meta-labels "
            f"(need >= {MIN_POSITIVE_SAMPLES}). AUC will be unreliable."
        )

    # ------------------------------------------------------------------
    # 7. Build t1_series from barrier labels (for PurgedKFoldSplitter)
    # ------------------------------------------------------------------
    # t1_series: index=t0, values=t1 (barrier end time)
    t1_raw = aligned_indexed["t1"]
    t1_series = pd.Series(
        pd.DatetimeIndex(t1_raw.tolist()).tolist(),
        index=aligned_indexed.index,
        dtype="datetime64[ns, UTC]",
    )

    # Sort by t0 (required by PurgedKFoldSplitter)
    sort_order = t1_series.index.argsort()
    t1_series = t1_series.iloc[sort_order]
    features_sorted = features_aligned.iloc[sort_order]
    y_sorted = y.iloc[sort_order]

    # ------------------------------------------------------------------
    # 8. CV evaluation with PurgedKFoldSplitter
    # ------------------------------------------------------------------
    actual_folds = min(n_folds, n_aligned // 10)  # ensure enough samples per fold
    if actual_folds < 2:
        actual_folds = 2

    cv_metrics: list[dict] = []
    meta_labeler_cv = MetaLabeler(n_estimators=n_estimators)

    try:
        splitter = PurgedKFoldSplitter(
            n_splits=actual_folds,
            t1_series=t1_series,
            embargo_frac=0.01,
        )

        for fold_idx, (train_idx, test_idx) in enumerate(
            splitter.split(features_sorted.values)
        ):
            if len(train_idx) < 10 or len(test_idx) < 5:
                logger.debug(
                    f"  asset_id={asset_id}: fold {fold_idx + 1}: "
                    f"too few train({len(train_idx)}) or test({len(test_idx)}) samples. Skipping fold."
                )
                continue

            X_train = features_sorted.iloc[train_idx]
            y_train = y_sorted.iloc[train_idx]
            X_test = features_sorted.iloc[test_idx]
            y_test = y_sorted.iloc[test_idx]

            # Skip folds with only one class in train or test
            if y_train.nunique() < 2 or y_test.nunique() < 2:
                logger.debug(
                    f"  asset_id={asset_id}: fold {fold_idx + 1}: "
                    "single-class train or test, skipping fold."
                )
                continue

            try:
                fold_model = MetaLabeler(n_estimators=n_estimators)
                fold_model.fit(X_train, y_train)
                fold_metrics = fold_model.evaluate(X_test, y_test)
                fold_metrics["fold"] = fold_idx + 1

                cv_metrics.append(fold_metrics)
                logger.info(
                    f"  asset_id={asset_id}: fold {fold_idx + 1}/{actual_folds} "
                    f"| AUC={fold_metrics['auc']:.4f} "
                    f"| precision={fold_metrics['precision']:.4f} "
                    f"| recall={fold_metrics['recall']:.4f} "
                    f"| F1={fold_metrics['f1']:.4f} "
                    f"| n_test={fold_metrics['n_samples']}"
                )
            except Exception as exc:
                logger.warning(
                    f"  asset_id={asset_id}: fold {fold_idx + 1} failed: {exc}"
                )
                continue

    except Exception as exc:
        logger.warning(f"  asset_id={asset_id}: PurgedKFoldSplitter failed: {exc}")

    # Aggregate CV AUC
    valid_aucs = [
        m["auc"] for m in cv_metrics if not np.isnan(m.get("auc", float("nan")))
    ]
    result["cv_auc_folds"] = valid_aucs
    mean_auc = float(np.mean(valid_aucs)) if valid_aucs else float("nan")
    result["mean_auc"] = mean_auc

    if valid_aucs:
        below_random = [a for a in valid_aucs if a < 0.5]
        if below_random:
            logger.warning(
                f"  asset_id={asset_id}: {len(below_random)}/{len(valid_aucs)} CV folds "
                f"have AUC < 0.5 ({below_random}). Model may not extract signal."
            )
        logger.info(
            f"  asset_id={asset_id}: CV AUC (mean={mean_auc:.4f}) "
            f"folds={[f'{a:.4f}' for a in valid_aucs]}"
        )
    else:
        logger.warning(f"  asset_id={asset_id}: no valid CV folds completed.")

    # ------------------------------------------------------------------
    # 9. Final model: train on all data, score all signal entries
    # ------------------------------------------------------------------
    try:
        meta_labeler_cv.fit(features_sorted, y_sorted)
    except Exception as exc:
        logger.error(f"  asset_id={asset_id}: final model fit failed: {exc}")
        result["error"] = f"Final model fit failed: {exc}"
        return result

    # Feature importance (top 5)
    fi = meta_labeler_cv.feature_importance()
    top5 = list(fi.head(5).to_dict().items())
    result["feature_importance_top5"] = top5
    logger.info(
        f"  asset_id={asset_id}: top-5 features: "
        + ", ".join(f"{k}={v:.4f}" for k, v in top5)
    )

    # Score ALL signal entries (not just the aligned subset), using available features
    all_signal_ts = signals_df["signal_ts"].tolist()
    all_features_df = load_features_for_timestamps(
        engine, asset_id, tf, all_signal_ts, feature_cols
    )

    if all_features_df.empty:
        logger.warning(f"  asset_id={asset_id}: no features for scoring all signals.")
        proba_all = pd.Series(dtype=float)
        pred_all = pd.Series(dtype=int)
    else:
        proba_all = meta_labeler_cv.predict_proba(all_features_df)
        pred_all = meta_labeler_cv.predict(all_features_df)

    # Trade filter rate: fraction of signals that meta-labeler recommends skipping
    n_signals_total = len(proba_all.dropna())
    n_skip = int((pred_all == 0).sum())
    trade_filter_rate = (
        n_skip / n_signals_total if n_signals_total > 0 else float("nan")
    )
    result["trade_filter_rate"] = trade_filter_rate

    logger.info(
        f"  asset_id={asset_id}: trade filter rate={trade_filter_rate:.1%} "
        f"({n_skip}/{n_signals_total} signals filtered out)"
    )

    if dry_run:
        logger.info(f"  asset_id={asset_id}: [DRY RUN] -- skipping DB write")
        return result

    # ------------------------------------------------------------------
    # 10. Persist to meta_label_results
    # ------------------------------------------------------------------
    # Write results for the aligned subset (has t1_from_barrier info)
    model_version = f"rf_v1_{signal_type}"
    feature_set = ",".join(feature_cols)

    # Rebuild aligned_df with all needed columns for write
    aligned_df_write = aligned.copy()

    try:
        n_written = write_meta_labels(
            engine=engine,
            asset_id=asset_id,
            tf=tf,
            signal_type=signal_type,
            aligned_df=aligned_df_write,
            proba=proba_all,
            predictions=pred_all,
            n_estimators=n_estimators,
            feature_set=feature_set,
            model_version=model_version,
        )
        result["n_written"] = n_written
        logger.info(
            f"  asset_id={asset_id}: {n_written} rows written to meta_label_results"
        )
    except Exception as exc:
        logger.error(f"  asset_id={asset_id}: DB write failed: {exc}", exc_info=True)
        result["error"] = f"DB write failed: {exc}"

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point."""
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    t_start = time.time()

    db_url = args.db_url or TARGET_DB_URL
    if not db_url:
        logger.error("No database URL. Set TARGET_DB_URL or use --db-url.")
        return 1

    try:
        engine = create_engine(db_url, poolclass=NullPool)
    except Exception as exc:
        logger.error(f"Failed to create engine: {exc}")
        return 1

    # Resolve assets
    try:
        asset_ids = load_asset_ids(
            engine,
            args.ids,
            args.all,
            args.tf,
            args.pt,
            args.sl,
            args.vertical_bars,
        )
    except Exception as exc:
        logger.error(f"Failed to resolve asset IDs: {exc}")
        return 1

    if not asset_ids:
        logger.error(
            "No asset IDs resolved. Provide --ids or --all.\n"
            "If using --all, ensure triple_barrier_labels has rows for "
            f"tf={args.tf}, pt={args.pt}, sl={args.sl}, vb={args.vertical_bars}."
        )
        return 1

    logger.info(
        f"Meta-labeling pipeline | signal_type={args.signal_type} | tf={args.tf} | "
        f"pt={args.pt} | sl={args.sl} | vb={args.vertical_bars} | "
        f"n_estimators={args.n_estimators} | n_folds={args.n_folds} | "
        f"dry_run={args.dry_run} | n_assets={len(asset_ids)}"
    )

    if args.dry_run:
        logger.info("[DRY RUN MODE] -- no data will be written to the database")

    # Process each asset
    results = []
    for asset_id in asset_ids:
        logger.info(f"Processing asset_id={asset_id} ...")
        try:
            r = process_asset(
                engine=engine,
                asset_id=asset_id,
                tf=args.tf,
                signal_type=args.signal_type,
                pt=args.pt,
                sl=args.sl,
                vertical_bars=args.vertical_bars,
                n_estimators=args.n_estimators,
                n_folds=args.n_folds,
                feature_cols=META_LABEL_FEATURE_COLS,
                dry_run=args.dry_run,
            )
            results.append(r)
        except Exception as exc:
            logger.error(f"  asset_id={asset_id}: FAILED -- {exc}", exc_info=True)
            results.append(
                {
                    "asset_id": asset_id,
                    "n_aligned": 0,
                    "cv_auc_folds": [],
                    "mean_auc": float("nan"),
                    "feature_importance_top5": [],
                    "trade_filter_rate": float("nan"),
                    "n_written": 0,
                    "error": str(exc),
                }
            )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    elapsed = time.time() - t_start
    n_success = sum(1 for r in results if not r.get("error"))
    total_aligned = sum(r["n_aligned"] for r in results)
    total_written = sum(r["n_written"] for r in results)

    valid_aucs = [
        r["mean_auc"] for r in results if not np.isnan(r.get("mean_auc", float("nan")))
    ]
    auc_summary = (
        f"{np.mean(valid_aucs):.4f} (min={min(valid_aucs):.4f})"
        if valid_aucs
        else "N/A"
    )

    logger.info(
        f"\n--- Meta-Labeling Summary ---\n"
        f"  signal_type      : {args.signal_type}\n"
        f"  assets processed : {len(results)} ({n_success} success, {len(results) - n_success} skipped)\n"
        f"  total aligned    : {total_aligned}\n"
        f"  rows written     : {total_written}\n"
        f"  mean CV AUC      : {auc_summary}\n"
        f"  elapsed          : {elapsed:.1f}s"
    )

    # Log per-asset top-5 features if verbose
    if args.verbose:
        for r in results:
            if r["feature_importance_top5"]:
                logger.debug(
                    f"  asset_id={r['asset_id']} top features: "
                    + ", ".join(f"{k}={v:.4f}" for k, v in r["feature_importance_top5"])
                )

    return 0


if __name__ == "__main__":
    sys.exit(main())
