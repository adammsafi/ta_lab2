#!/usr/bin/env python
"""
CPCV Sharpe Distribution Runner.

Runs Combinatorial Purged Cross-Validation (CPCV) to produce a distribution of
out-of-sample Sharpe ratios for any signal strategy.

CPCV(6,2) -> C(6,2) = 15 splits -> 15 OOS Sharpe values -> distribution statistics.

Each OOS Sharpe is computed by:
  1. Slicing the test fold from the pre-joined features DataFrame
  2. Calling make_signals() to generate fresh entries/exits on that fold
  3. Deriving a position series and computing strategy returns with transaction costs

Purging uses t1_series from cmc_triple_barrier_labels to prevent lookahead leakage.
EMA columns (ema_9, ema_21, ema_50) are pre-joined from cmc_ema_multi_tf_u BEFORE
the CPCV loop to ensure every test fold slice contains the required signal columns.

Usage:
    python -m ta_lab2.scripts.labeling.run_cpcv_backtest --ids 1 --tf 1D --signal-type ema_crossover
    python -m ta_lab2.scripts.labeling.run_cpcv_backtest --ids 1 --tf 1D --signal-type rsi_mean_revert
    python -m ta_lab2.scripts.labeling.run_cpcv_backtest --ids 1 --tf 1D --signal-type atr_breakout --n-splits 6 --n-test-splits 2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.backtests.cv import CPCVSplitter
from ta_lab2.config import TARGET_DB_URL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Run CPCV Sharpe distribution: CPCV(n_splits, n_test_splits) "
            "produces C(n_splits, n_test_splits) OOS Sharpe ratios."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Asset selection
    parser.add_argument(
        "--ids",
        required=True,
        help="Comma-separated asset IDs (e.g., '1,52')",
    )

    # Timeframe
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe string (default: '1D')",
    )

    # Signal type
    parser.add_argument(
        "--signal-type",
        required=True,
        choices=["ema_crossover", "rsi_mean_revert", "atr_breakout"],
        help="Signal strategy to evaluate",
    )

    # Triple barrier label parameters (used for pre-condition check + t1_series loading)
    parser.add_argument(
        "--pt",
        type=float,
        default=1.0,
        help="Profit-taking multiplier for triple barrier labels (default: 1.0)",
    )
    parser.add_argument(
        "--sl",
        type=float,
        default=1.0,
        help="Stop-loss multiplier for triple barrier labels (default: 1.0)",
    )
    parser.add_argument(
        "--vertical-bars",
        type=int,
        default=10,
        help="Vertical barrier bar count for labels (default: 10)",
    )

    # CPCV parameters
    parser.add_argument(
        "--n-splits",
        type=int,
        default=6,
        help="Number of fold groups for CPCV (default: 6)",
    )
    parser.add_argument(
        "--n-test-splits",
        type=int,
        default=2,
        help="Number of test fold groups per combination (default: 2, gives C(6,2)=15)",
    )
    parser.add_argument(
        "--embargo-frac",
        type=float,
        default=0.01,
        help="Embargo fraction after each test fold (default: 0.01)",
    )

    # Transaction costs
    parser.add_argument(
        "--fee-bps",
        type=float,
        default=10.0,
        help="Fee in basis points per trade (default: 10)",
    )
    parser.add_argument(
        "--slippage-bps",
        type=float,
        default=5.0,
        help="Slippage in basis points per trade (default: 5)",
    )

    # Output
    parser.add_argument(
        "--output-dir",
        default=".planning/phases/57-advanced-labeling-cv",
        help="Directory to write JSON results (default: .planning/phases/57-advanced-labeling-cv)",
    )

    # Logging
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    # DB override
    parser.add_argument(
        "--db-url",
        help="Database URL (defaults to TARGET_DB_URL env var)",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Pre-condition checks
# ---------------------------------------------------------------------------


def _check_preconditions(
    engine,
    asset_id: int,
    tf: str,
    pt: float,
    sl: float,
    vb: int,
) -> bool:
    """
    Verify triple barrier labels exist for the specified params.

    Returns True if labels exist and we can proceed, False otherwise.
    Logs a clear actionable error message if labels are missing.
    """
    with engine.connect() as conn:
        label_count = conn.execute(
            text(
                "SELECT count(*) FROM cmc_triple_barrier_labels "
                "WHERE asset_id = :id AND tf = :tf AND pt_multiplier = :pt "
                "AND sl_multiplier = :sl AND vertical_bars = :vb"
            ),
            {"id": asset_id, "tf": tf, "pt": pt, "sl": sl, "vb": vb},
        ).scalar()

    if label_count == 0:
        logger.error(
            f"No triple barrier labels found for asset_id={asset_id} tf={tf} "
            f"pt={pt} sl={sl} vb={vb}. "
            f"Run first:\n"
            f"  python -m ta_lab2.scripts.labeling.refresh_triple_barrier_labels "
            f"--ids {asset_id} --tf {tf} --pt {pt} --sl {sl} --vertical-bars {vb}"
        )
        return False

    logger.info(
        f"Pre-check passed: {label_count} triple barrier labels found "
        f"for asset_id={asset_id} tf={tf} pt={pt} sl={sl} vb={vb}"
    )
    return True


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _build_features_with_ema(engine, asset_id: int, tf: str) -> pd.DataFrame:
    """
    Load cmc_features and pre-join pivoted EMA columns from cmc_ema_multi_tf_u.

    cmc_ema_multi_tf_u has columns: id, ts, tf, period, ema, d1, d2, ...
    The 'period' column contains values like 9, 21, 50, 200.
    The 'ema' column contains the EMA value for that period.

    We pivot on 'period' to produce wide-format columns: ema_9, ema_21, ema_50, etc.
    Then merge into features_df on (ts).

    This MUST happen BEFORE the CPCV loop so that each test fold slice
    (features_df.iloc[test_idx]) already contains the EMA columns needed by
    make_signals() for ema_crossover.

    Returns:
        features_df: DataFrame indexed by tz-aware UTC ts with all cmc_features columns
                     plus ema_9, ema_21, ema_50 from cmc_ema_multi_tf_u.
    """
    # 1. Load all features for this asset/tf
    logger.info(f"Loading cmc_features for asset_id={asset_id} tf={tf} ...")
    with engine.connect() as conn:
        features_df = pd.read_sql(
            text("SELECT * FROM cmc_features WHERE id = :id AND tf = :tf ORDER BY ts"),
            conn,
            params={"id": asset_id, "tf": tf},
        )

    if features_df.empty:
        raise ValueError(
            f"No features found in cmc_features for asset_id={asset_id} tf={tf}. "
            f"Run feature refresh first."
        )

    # Normalize ts to tz-aware UTC and set as index
    features_df["ts"] = pd.to_datetime(features_df["ts"], utc=True)
    features_df = features_df.set_index("ts").sort_index()

    logger.info(f"  cmc_features: {len(features_df)} rows")

    # 2. Load EMA data for required periods
    ema_periods = [9, 21, 50]
    logger.info(
        f"Loading cmc_ema_multi_tf_u for asset_id={asset_id} tf={tf} "
        f"periods={ema_periods} ..."
    )
    with engine.connect() as conn:
        ema_df = pd.read_sql(
            text(
                "SELECT ts, period, ema FROM cmc_ema_multi_tf_u "
                "WHERE id = :id AND tf = :tf AND period = ANY(:periods) ORDER BY ts"
            ),
            conn,
            params={"id": asset_id, "tf": tf, "periods": ema_periods},
        )

    if ema_df.empty:
        logger.warning(
            f"No EMA data found in cmc_ema_multi_tf_u for asset_id={asset_id} tf={tf}. "
            f"EMA columns will be missing (ema_crossover signal will fail)."
        )
    else:
        # Normalize ts to tz-aware UTC
        ema_df["ts"] = pd.to_datetime(ema_df["ts"], utc=True)

        # 3. Pivot: rows=(ts), columns=(period), values=(ema)
        #    Result: columns named 9, 21, 50 with EMA values
        ema_wide = ema_df.pivot(index="ts", columns="period", values="ema")
        # Rename columns: 9 -> "ema_9", 21 -> "ema_21", 50 -> "ema_50"
        ema_wide.columns = [f"ema_{int(p)}" for p in ema_wide.columns]
        ema_wide = ema_wide.sort_index()

        logger.info(
            f"  EMA wide: {len(ema_wide)} rows, columns={list(ema_wide.columns)}"
        )

        # 4. Left-join EMA columns into features_df on ts index
        features_df = features_df.join(ema_wide, how="left")

    ema_cols = [c for c in features_df.columns if c.startswith("ema_")]
    logger.info(
        f"Built features_df: {len(features_df)} rows, EMA columns present: {ema_cols}"
    )

    return features_df


def _load_t1_series(
    engine,
    asset_id: int,
    tf: str,
    pt: float,
    sl: float,
    vb: int,
) -> pd.Series:
    """
    Load triple barrier label t1 timestamps for the specified params.

    Returns a pd.Series with:
        index = t0 (label-start timestamps, tz-aware UTC)
        values = t1 (label-end timestamps, tz-aware UTC)

    Used by CPCVSplitter for purging: training observations whose label-end
    timestamp (t1) bleeds into the test fold window are purged from training.
    """
    with engine.connect() as conn:
        labels_df = pd.read_sql(
            text(
                "SELECT t0, t1 FROM cmc_triple_barrier_labels "
                "WHERE asset_id = :id AND tf = :tf "
                "AND pt_multiplier = :pt AND sl_multiplier = :sl AND vertical_bars = :vb "
                "ORDER BY t0"
            ),
            conn,
            params={"id": asset_id, "tf": tf, "pt": pt, "sl": sl, "vb": vb},
        )

    if labels_df.empty:
        raise ValueError(
            f"No triple barrier labels found for asset_id={asset_id} tf={tf} "
            f"pt={pt} sl={sl} vb={vb}."
        )

    # Normalize to tz-aware UTC
    labels_df["t0"] = pd.to_datetime(labels_df["t0"], utc=True)
    labels_df["t1"] = pd.to_datetime(labels_df["t1"], utc=True)

    # Drop rows where t1 is NaT (vertical barrier with no resolution) --
    # CPCVSplitter requires non-null t1 values for purge comparisons
    labels_df = labels_df.dropna(subset=["t1"])

    # CRITICAL: Use .tolist() (NOT .values) to preserve tz-aware timestamps.
    # On this platform, Series.values on a tz-aware Series returns tz-NAIVE
    # numpy.datetime64, which would cause intersection() with features_df.index
    # (tz-aware UTC) to return empty. .tolist() returns tz-aware Timestamp objects.
    t1_series = pd.Series(
        labels_df["t1"].tolist(),
        index=pd.DatetimeIndex(labels_df["t0"].tolist()),
        name="t1",
    )
    t1_series = t1_series.sort_index()

    logger.info(
        f"Loaded t1_series: {len(t1_series)} label events "
        f"from {t1_series.index[0]} to {t1_series.index[-1]}"
    )

    return t1_series


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------


def _call_make_signals(
    signal_type: str,
    features_df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """
    Dispatch to the correct make_signals() function based on signal_type.

    Returns (entries, exits, size) where entries/exits are boolean Series.
    """
    if signal_type == "ema_crossover":
        from ta_lab2.signals.ema_trend import make_signals

        return make_signals(features_df)

    elif signal_type == "rsi_mean_revert":
        from ta_lab2.signals.rsi_mean_revert import make_signals

        return make_signals(features_df)

    elif signal_type == "atr_breakout":
        from ta_lab2.signals.breakout_atr import make_signals

        return make_signals(features_df)

    else:
        raise ValueError(
            f"Unknown signal_type: {signal_type!r}. "
            f"Must be one of: ema_crossover, rsi_mean_revert, atr_breakout"
        )


# ---------------------------------------------------------------------------
# Position series and return computation
# ---------------------------------------------------------------------------


def _derive_position(
    entries: pd.Series,
    exits: pd.Series,
    index: pd.Index,
) -> pd.Series:
    """
    Derive a continuous position series (0.0 or 1.0) from entry/exit signals.

    Uses a vectorized cumsum approach:
      - entry increments the cumsum; exit decrements it
      - clamp to [0, 1] to handle edge cases (double-entry, etc.)

    Position is 1.0 when in-trade, 0.0 when flat.
    """
    position = (
        (entries.astype(int) - exits.astype(int)).cumsum().clip(0, 1).astype(float)
    )
    return position.reindex(index, fill_value=0.0)


def _compute_oos_sharpe(
    test_close: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    fee_bps: float,
    slippage_bps: float,
) -> tuple[float, int]:
    """
    Compute the OOS Sharpe ratio for a test fold.

    Strategy returns:
        strategy_ret[t] = position[t-1] * price_ret[t] - trade_cost[t]

    Transaction costs:
        cost_per_trade = (fee_bps + slippage_bps) / 10_000
        Applied at every bar with an entry or exit signal.

    Returns:
        (sharpe, n_trades) where sharpe is annualized (sqrt(252) convention).
    """
    # Price returns (log or arithmetic -- use arithmetic for simplicity)
    price_returns = test_close.pct_change().fillna(0.0)

    # Position (lagged by 1 bar for next-bar execution)
    position = _derive_position(entries, exits, test_close.index)
    position_lagged = position.shift(1).fillna(0.0)

    # Transaction costs
    cost_per_trade = (fee_bps + slippage_bps) / 1e4
    # Cost incurred whenever there is a change in position (entry or exit)
    trade_events = (entries.astype(int) + exits.astype(int)).reindex(
        test_close.index, fill_value=0
    )
    trade_costs = trade_events * cost_per_trade

    # Strategy returns
    strategy_returns = position_lagged * price_returns - trade_costs

    # Count trades (number of entry events)
    n_trades = int(entries.sum())

    # Annualized Sharpe (252 trading days convention for daily)
    ret_std = strategy_returns.std()
    if ret_std > 1e-10:
        sharpe = float(strategy_returns.mean() / ret_std * np.sqrt(252))
    else:
        sharpe = 0.0

    return sharpe, n_trades


# ---------------------------------------------------------------------------
# Per-asset CPCV pipeline
# ---------------------------------------------------------------------------


def run_cpcv_for_asset(
    engine,
    asset_id: int,
    tf: str,
    signal_type: str,
    pt: float,
    sl: float,
    vb: int,
    n_splits: int,
    n_test_splits: int,
    embargo_frac: float,
    fee_bps: float,
    slippage_bps: float,
) -> Optional[dict]:
    """
    Run the full CPCV pipeline for one asset.

    Returns a results dict with distribution statistics, or None on failure.
    """
    # 1. Pre-condition check
    if not _check_preconditions(engine, asset_id, tf, pt, sl, vb):
        return None

    # 2. Build pre-joined features_df (EMA columns included)
    try:
        features_df = _build_features_with_ema(engine, asset_id, tf)
    except ValueError as e:
        logger.error(f"asset_id={asset_id}: {e}")
        return None

    # 3. Load t1_series for purging
    try:
        t1_series_full = _load_t1_series(engine, asset_id, tf, pt, sl, vb)
    except ValueError as e:
        logger.error(f"asset_id={asset_id}: {e}")
        return None

    # 4. Align features_df to rows that have labels (t1_series defines the event universe)
    #    Intersect features_df timestamps with t1_series index
    common_ts = features_df.index.intersection(t1_series_full.index)
    if len(common_ts) == 0:
        logger.error(
            f"asset_id={asset_id}: No overlap between features_df timestamps "
            f"and t1_series label timestamps. Check that feature refresh and "
            f"label refresh used the same tf={tf}."
        )
        return None

    features_aligned = features_df.loc[common_ts].copy()
    t1_series = t1_series_full.loc[common_ts]

    logger.info(
        f"asset_id={asset_id}: Aligned {len(features_aligned)} rows "
        f"(features x labels intersection)"
    )

    # 5. Validate minimum data requirement
    min_required = n_splits * 10
    if len(features_aligned) < min_required:
        logger.error(
            f"asset_id={asset_id}: Only {len(features_aligned)} aligned timestamps, "
            f"need at least {min_required} (n_splits={n_splits} * 10). "
            f"Not enough data for CPCV."
        )
        return None

    # 6. Create CPCVSplitter
    splitter = CPCVSplitter(
        n_splits=n_splits,
        n_test_splits=n_test_splits,
        t1_series=t1_series,
        embargo_frac=embargo_frac,
    )
    n_combinations = splitter.get_n_splits()
    logger.info(
        f"asset_id={asset_id}: CPCVSplitter ready: "
        f"C({n_splits},{n_test_splits}) = {n_combinations} splits"
    )

    # 7. Run CPCV loop
    oos_sharpes: list[float] = []
    X_dummy = np.arange(len(features_aligned))  # CPCVSplitter only uses len(X)

    for split_idx, (train_idx, test_idx) in enumerate(splitter.split(X_dummy), start=1):
        if len(test_idx) == 0:
            logger.warning(f"  Split {split_idx}: empty test fold, skipping")
            oos_sharpes.append(0.0)
            continue

        # 7a. Slice test fold from pre-joined features_df
        test_features_df = features_aligned.iloc[test_idx]
        test_close = test_features_df["close"].astype(float)

        if test_close.isna().all():
            logger.warning(f"  Split {split_idx}: all NaN close prices, Sharpe=0.0")
            oos_sharpes.append(0.0)
            continue

        # 7b. Generate signals on the test fold
        try:
            entries, exits, _size = _call_make_signals(signal_type, test_features_df)
        except KeyError as e:
            logger.warning(
                f"  Split {split_idx}: make_signals() failed with KeyError: {e}. "
                f"Required column missing from test fold. Recording Sharpe=0.0."
            )
            oos_sharpes.append(0.0)
            continue

        n_entry_signals = int(entries.sum())

        if n_entry_signals == 0:
            logger.warning(
                f"  Split {split_idx}: no entry signals generated on test fold "
                f"({len(test_idx)} bars). Recording Sharpe=0.0."
            )
            oos_sharpes.append(0.0)
            continue

        # 7c. Compute OOS Sharpe with transaction costs
        sharpe, n_trades = _compute_oos_sharpe(
            test_close=test_close,
            entries=entries,
            exits=exits,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )

        oos_sharpes.append(sharpe)
        logger.info(
            f"  Split {split_idx:>2}/{n_combinations}: "
            f"n_test_bars={len(test_idx):>4} | "
            f"n_trades={n_trades:>3} | "
            f"Sharpe={sharpe:>7.4f}"
        )

    if not oos_sharpes:
        logger.error(f"asset_id={asset_id}: No OOS Sharpe values computed.")
        return None

    # 8. Aggregate distribution statistics
    sharpe_arr = np.array(oos_sharpes)
    n_positive = int(np.sum(sharpe_arr > 0))
    result = {
        "asset_id": asset_id,
        "tf": tf,
        "signal_type": signal_type,
        "n_splits": n_combinations,
        "n_splits_config": f"CPCV({n_splits},{n_test_splits})",
        "pt_multiplier": pt,
        "sl_multiplier": sl,
        "vertical_bars": vb,
        "embargo_frac": embargo_frac,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "n_aligned_bars": len(features_aligned),
        "sharpe_distribution": [float(s) for s in oos_sharpes],
        "mean_sharpe": float(np.mean(sharpe_arr)),
        "median_sharpe": float(np.median(sharpe_arr)),
        "sharpe_p10": float(np.percentile(sharpe_arr, 10)),
        "sharpe_p25": float(np.percentile(sharpe_arr, 25)),
        "sharpe_p75": float(np.percentile(sharpe_arr, 75)),
        "sharpe_p90": float(np.percentile(sharpe_arr, 90)),
        "sharpe_std": float(np.std(sharpe_arr)),
        "pct_positive_sharpe": float(n_positive / len(oos_sharpes)),
        "n_positive_sharpe": n_positive,
        "n_negative_sharpe": len(oos_sharpes) - n_positive,
    }

    return result


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _print_distribution_table(result: dict) -> None:
    """Print a formatted table of CPCV results to stdout."""
    asset_id = result["asset_id"]
    signal_type = result["signal_type"]
    config = result["n_splits_config"]
    n_splits = result["n_splits"]

    print(f"\n{'=' * 65}")
    print("CPCV Sharpe Distribution")
    print(f"{'=' * 65}")
    print(f"  Asset ID  : {asset_id}")
    print(f"  TF        : {result['tf']}")
    print(f"  Signal    : {signal_type}")
    print(f"  Config    : {config} -> {n_splits} OOS splits")
    print(
        f"  Barriers  : pt={result['pt_multiplier']} sl={result['sl_multiplier']} vb={result['vertical_bars']}"
    )
    print(
        f"  Costs     : fee={result['fee_bps']}bps + slip={result['slippage_bps']}bps"
    )
    print(f"  Bars (aligned) : {result['n_aligned_bars']}")
    print(f"{'=' * 65}")
    print("  Distribution Statistics:")
    print(f"    Mean Sharpe   : {result['mean_sharpe']:>8.4f}")
    print(f"    Median Sharpe : {result['median_sharpe']:>8.4f}")
    print(f"    P10 Sharpe    : {result['sharpe_p10']:>8.4f}  (conservative estimate)")
    print(f"    P25 Sharpe    : {result['sharpe_p25']:>8.4f}")
    print(f"    P75 Sharpe    : {result['sharpe_p75']:>8.4f}")
    print(f"    P90 Sharpe    : {result['sharpe_p90']:>8.4f}")
    print(f"    Std Dev       : {result['sharpe_std']:>8.4f}")
    print(
        f"    % Positive    : {result['pct_positive_sharpe']:>8.1%}  ({result['n_positive_sharpe']}/{n_splits} splits)"
    )
    print(f"{'=' * 65}")
    print("  Per-split Sharpe values:")
    dist = result["sharpe_distribution"]
    for i, s in enumerate(dist, start=1):
        bar = "#" * max(0, int((s + 3) * 4))  # simple ASCII bar centered at 0
        sign = "+" if s >= 0 else ""
        print(f"    Split {i:>2}: {sign}{s:>7.4f}  {bar}")
    print(f"{'=' * 65}\n")


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def _write_json_output(result: dict, output_dir: str) -> str:
    """Write results dict to a JSON file. Returns the file path."""
    os.makedirs(output_dir, exist_ok=True)
    asset_id = result["asset_id"]
    signal_type = result["signal_type"]
    filename = f"cpcv_results_{asset_id}_{signal_type}.json"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info(f"JSON results written to: {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point."""
    args = parse_args(argv)

    # Logging setup
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    t_start = time.time()

    # DB URL
    db_url = args.db_url or TARGET_DB_URL
    if not db_url:
        logger.error("No database URL. Set TARGET_DB_URL or use --db-url.")
        return 1

    # Engine (NullPool for one-shot scripts)
    try:
        engine = create_engine(db_url, poolclass=NullPool)
    except Exception as exc:
        logger.error(f"Failed to create engine: {exc}")
        return 1

    # Parse asset IDs
    asset_ids = [int(i.strip()) for i in args.ids.split(",")]

    logger.info(
        f"CPCV backtest | signal={args.signal_type} | tf={args.tf} | "
        f"CPCV({args.n_splits},{args.n_test_splits}) = {_n_combinations(args.n_splits, args.n_test_splits)} splits | "
        f"assets={asset_ids}"
    )

    all_results = []
    exit_code = 0

    for asset_id in asset_ids:
        logger.info(f"\nProcessing asset_id={asset_id} ...")
        try:
            result = run_cpcv_for_asset(
                engine=engine,
                asset_id=asset_id,
                tf=args.tf,
                signal_type=args.signal_type,
                pt=args.pt,
                sl=args.sl,
                vb=args.vertical_bars,
                n_splits=args.n_splits,
                n_test_splits=args.n_test_splits,
                embargo_frac=args.embargo_frac,
                fee_bps=args.fee_bps,
                slippage_bps=args.slippage_bps,
            )

            if result is None:
                logger.error(f"asset_id={asset_id}: CPCV pipeline failed. Skipping.")
                exit_code = 1
                continue

            # Print distribution table
            _print_distribution_table(result)

            # Write JSON output
            json_path = _write_json_output(result, args.output_dir)
            print(f"JSON output: {json_path}")

            all_results.append(result)

        except Exception as exc:
            logger.error(f"asset_id={asset_id}: Unexpected error: {exc}", exc_info=True)
            exit_code = 1

    elapsed = time.time() - t_start
    logger.info(
        f"\n--- Summary ---\n"
        f"  assets processed : {len(all_results)}/{len(asset_ids)}\n"
        f"  elapsed          : {elapsed:.1f}s"
    )

    return exit_code


def _n_combinations(n: int, k: int) -> int:
    """Compute C(n, k) without importing math (for logger message)."""
    import math

    return math.comb(n, k)


if __name__ == "__main__":
    sys.exit(main())
