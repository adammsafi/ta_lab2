# -*- coding: utf-8 -*-
"""
CLI for TAIL-01 vol-sizing comparison: 3 variants x strategies x assets x vol metrics.

Compares:
- Variant A: Fixed position size (30% allocation) + hard stop-loss
- Variant B: Vol-sized position (ATR or realized vol) + no stops
- Variant C: Vol-sized position (ATR or realized vol) + hard stop-loss

Outputs:
- SIZING_COMPARISON.md  -- full metrics table + winner recommendation per strategy/asset
- charts/sizing_sharpe_heatmap.html  -- Sharpe by variant and strategy (Plotly)
- charts/sizing_maxdd_comparison.html  -- MaxDD grouped bar chart (Plotly)

Usage
-----
    # Default: 4 strategies, BTC+ETH, 3 risk budgets, atr+realized vol
    python -m ta_lab2.scripts.analysis.run_tail_risk_comparison

    # Specific strategy / asset:
    python -m ta_lab2.scripts.analysis.run_tail_risk_comparison \\
        --strategies ema_trend_17_77 --asset-ids 1

    # Risk budget sweep:
    python -m ta_lab2.scripts.analysis.run_tail_risk_comparison \\
        --risk-budgets 0.005 0.01 0.02

    # Dry-run (print config and exit):
    python -m ta_lab2.scripts.analysis.run_tail_risk_comparison --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.vol_sizer import (
    compute_comparison_metrics,
    run_vol_sized_backtest,
)
from ta_lab2.config import TARGET_DB_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project layout
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "reports" / "tail_risk"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_STRATEGIES = [
    "ema_trend_17_77",
    "ema_trend_21_50",
    "rsi_mean_revert",
    "breakout_atr",
]
_DEFAULT_ASSET_IDS = [1, 1027]  # BTC, ETH
_DEFAULT_RISK_BUDGETS = [0.005, 0.01, 0.02]
_DEFAULT_VOL_METRICS = ["atr", "realized"]
_DEFAULT_STOP_PCT = 0.07
_DEFAULT_FEE_BPS = 16

# Signal table mapping
SIGNAL_TABLE_MAP = {
    "ema_trend_17_77": "signals_ema_crossover",
    "ema_trend_21_50": "signals_ema_crossover",
    "rsi_mean_revert": "signals_rsi_mean_revert",
    "breakout_atr": "signals_atr_breakout",
}

# Strategy params for on-the-fly signal generation
STRATEGY_PARAMS = {
    "ema_trend_17_77": {"signal_type": "ema_crossover", "fast_ema": 17, "slow_ema": 77},
    "ema_trend_21_50": {"signal_type": "ema_crossover", "fast_ema": 21, "slow_ema": 50},
    "rsi_mean_revert": {
        "signal_type": "rsi_mean_revert",
        "period": 14,
        "oversold": 30,
        "overbought": 70,
    },
    "breakout_atr": {
        "signal_type": "atr_breakout",
        "period": 14,
        "multiplier": 2.0,
    },
}

# Asset name lookup for display
_ASSET_NAME = {1: "BTC", 1027: "ETH"}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_pct(v: float, decimals: int = 2) -> str:
    if pd.isna(v) or v is None:
        return "N/A"
    return f"{v * 100:.{decimals}f}%"


def _fmt_float(v: float, decimals: int = 3) -> str:
    if pd.isna(v) or v is None:
        return "N/A"
    return f"{v:.{decimals}f}"


def _fmt_int(v) -> str:
    if pd.isna(v) or v is None:
        return "N/A"
    return str(int(v))


# ---------------------------------------------------------------------------
# Data loading functions
# ---------------------------------------------------------------------------


def _load_price_data(engine, asset_id: int, tf: str = "1D") -> pd.Series:
    """
    Load daily close prices from price_bars_multi_tf_u.

    NOTE: This table uses "timestamp" (a quoted PostgreSQL reserved word), NOT ts.
    Returns pd.Series with DatetimeIndex (UTC), index name = "timestamp".
    """
    sql = text(
        """
        SELECT "timestamp", close
        FROM public.price_bars_multi_tf_u
        WHERE id = :asset_id AND tf = :tf
        ORDER BY "timestamp"
        """
    )
    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "tf": tf})
    except Exception as exc:
        logger.error("Failed to load price data for asset_id=%d: %s", asset_id, exc)
        return pd.Series(dtype=float, name="close")

    if df.empty:
        logger.warning("No price data for asset_id=%d tf=%s", asset_id, tf)
        return pd.Series(dtype=float, name="close")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    series = pd.Series(
        df["close"].values,
        index=pd.DatetimeIndex(df["timestamp"], name="timestamp"),
        name="close",
    )
    logger.info("Loaded %d price bars for asset_id=%d", len(series), asset_id)
    return series


def _load_atr_data(engine, asset_id: int, tf: str = "1D") -> pd.Series:
    """
    Load ATR-14 values from features.

    NOTE: features uses 'ts' (not 'timestamp').
    Returns pd.Series with DatetimeIndex (UTC).
    """
    sql = text(
        """
        SELECT ts, atr_14
        FROM public.features
        WHERE id = :asset_id AND tf = :tf AND atr_14 IS NOT NULL
        ORDER BY ts
        """
    )
    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "tf": tf})
    except Exception as exc:
        logger.error("Failed to load ATR data for asset_id=%d: %s", asset_id, exc)
        return pd.Series(dtype=float, name="atr_14")

    if df.empty:
        logger.warning("No ATR data for asset_id=%d tf=%s", asset_id, tf)
        return pd.Series(dtype=float, name="atr_14")

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    series = pd.Series(
        df["atr_14"].values,
        index=pd.DatetimeIndex(df["ts"]),
        name="atr_14",
    )
    return series


def _load_realized_vol(
    engine, asset_id: int, tf: str = "1D", window: int = 20
) -> pd.Series:
    """
    Load arithmetic returns from returns_bars_multi_tf_u and compute
    rolling(window).std() as realized volatility.

    NOTE: returns_bars_multi_tf_u uses "timestamp" (quoted reserved word), NOT ts.
    Returns pd.Series with DatetimeIndex (UTC).
    """
    sql = text(
        """
        SELECT "timestamp", ret_arith
        FROM public.returns_bars_multi_tf_u
        WHERE id = :asset_id AND tf = :tf
        ORDER BY "timestamp"
        """
    )
    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "tf": tf})
    except Exception as exc:
        logger.error(
            "Failed to load returns for realized vol asset_id=%d: %s", asset_id, exc
        )
        return pd.Series(dtype=float, name="realized_vol")

    if df.empty:
        logger.warning("No returns data for asset_id=%d tf=%s", asset_id, tf)
        return pd.Series(dtype=float, name="realized_vol")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    ret_series = pd.Series(
        df["ret_arith"].values,
        index=pd.DatetimeIndex(df["timestamp"]),
        name="ret_arith",
    )

    # Rolling std as realized volatility
    realized_vol = ret_series.rolling(window=window, min_periods=window).std()
    realized_vol.name = "realized_vol"
    return realized_vol


def _generate_ema_crossover_signals(
    engine, asset_id: int, fast_ema: int, slow_ema: int, price_index: pd.DatetimeIndex
) -> tuple[pd.Series, pd.Series]:
    """Generate EMA crossover signals on-the-fly from ema_multi_tf_u."""
    sql = text(
        """
        SELECT ts, period, ema
        FROM public.ema_multi_tf_u
        WHERE id = :asset_id AND tf = '1D' AND period IN :periods
        ORDER BY ts, period
        """
    )
    try:
        with engine.connect() as conn:
            df = pd.read_sql(
                sql,
                conn,
                params={"asset_id": asset_id, "periods": (fast_ema, slow_ema)},
            )
    except Exception as exc:
        logger.warning(
            "Could not load EMAs for on-the-fly signals asset_id=%d: %s", asset_id, exc
        )
        return _synthetic_signals(price_index)

    if df.empty:
        logger.warning(
            "No EMA data for on-the-fly signals asset_id=%d fast=%d slow=%d",
            asset_id,
            fast_ema,
            slow_ema,
        )
        return _synthetic_signals(price_index)

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    pivot = df.pivot(index="ts", columns="period", values="ema")

    if fast_ema not in pivot.columns or slow_ema not in pivot.columns:
        logger.warning(
            "Missing EMA periods %d or %d for asset_id=%d", fast_ema, slow_ema, asset_id
        )
        return _synthetic_signals(price_index)

    fast = pivot[fast_ema].reindex(price_index)
    slow = pivot[slow_ema].reindex(price_index)

    # Crossover: fast crosses above slow (entry), crosses below (exit)
    fast_above = fast > slow
    entries = fast_above & ~fast_above.shift(1).fillna(False)
    exits = (~fast_above) & fast_above.shift(1).fillna(True)

    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)

    logger.info(
        "On-the-fly EMA(%d/%d) signals for asset_id=%d: %d entries, %d exits",
        fast_ema,
        slow_ema,
        asset_id,
        int(entries.sum()),
        int(exits.sum()),
    )
    return entries, exits


def _generate_rsi_signals(
    engine,
    asset_id: int,
    period: int,
    oversold: int,
    overbought: int,
    price_index: pd.DatetimeIndex,
) -> tuple[pd.Series, pd.Series]:
    """Generate RSI mean-revert signals on-the-fly from features."""
    sql = text(
        """
        SELECT ts, rsi_14
        FROM public.features
        WHERE id = :asset_id AND tf = '1D' AND rsi_14 IS NOT NULL
        ORDER BY ts
        """
    )
    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"asset_id": asset_id})
    except Exception as exc:
        logger.warning(
            "Could not load RSI for on-the-fly signals asset_id=%d: %s", asset_id, exc
        )
        return _synthetic_signals(price_index)

    if df.empty:
        return _synthetic_signals(price_index)

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    rsi = pd.Series(
        df["rsi_14"].values,
        index=pd.DatetimeIndex(df["ts"]),
        name="rsi_14",
    ).reindex(price_index)

    # RSI mean revert: entry when rsi < oversold, exit when rsi > overbought
    entries = (rsi < oversold).fillna(False).astype(bool)
    exits = (rsi > overbought).fillna(False).astype(bool)

    logger.info(
        "On-the-fly RSI signals for asset_id=%d: %d entries, %d exits",
        asset_id,
        int(entries.sum()),
        int(exits.sum()),
    )
    return entries, exits


def _generate_atr_breakout_signals(
    engine,
    asset_id: int,
    period: int,
    multiplier: float,
    price_index: pd.DatetimeIndex,
    price_series: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Generate ATR breakout signals on-the-fly from features."""
    sql = text(
        """
        SELECT ts, atr_14
        FROM public.features
        WHERE id = :asset_id AND tf = '1D' AND atr_14 IS NOT NULL
        ORDER BY ts
        """
    )
    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"asset_id": asset_id})
    except Exception as exc:
        logger.warning(
            "Could not load ATR for breakout signals asset_id=%d: %s", asset_id, exc
        )
        return _synthetic_signals(price_index)

    if df.empty:
        return _synthetic_signals(price_index)

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    atr = pd.Series(
        df["atr_14"].values,
        index=pd.DatetimeIndex(df["ts"]),
        name="atr_14",
    ).reindex(price_index)

    close = price_series.reindex(price_index)
    rolling_high = close.rolling(window=20, min_periods=5).max()
    rolling_low = close.rolling(window=20, min_periods=5).min()

    # ATR breakout: entry when close > rolling_high + multiplier * atr
    entries = (close > rolling_high + multiplier * atr).fillna(False).astype(bool)
    # Exit when close < rolling_low
    exits = (close < rolling_low).fillna(False).astype(bool)

    logger.info(
        "On-the-fly ATR breakout signals for asset_id=%d: %d entries, %d exits",
        asset_id,
        int(entries.sum()),
        int(exits.sum()),
    )
    return entries, exits


def _synthetic_signals(price_index: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    """
    Fallback synthetic signals: entry every 30 bars, exit at +20.
    """
    n = len(price_index)
    entries = pd.Series(False, index=price_index, dtype=bool)
    exits = pd.Series(False, index=price_index, dtype=bool)
    for i in range(0, n, 30):
        entries.iloc[i] = True
        exit_i = min(i + 20, n - 1)
        exits.iloc[exit_i] = True
    logger.warning(
        "Using synthetic signals (entry every 30 bars, exit at +20): %d entries.",
        int(entries.sum()),
    )
    return entries, exits


def _load_signals(
    engine,
    strategy: str,
    asset_id: int,
    price_index: pd.DatetimeIndex,
    price_series: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """
    Load or generate (entry, exit) boolean signals aligned to price_index.

    Strategy: try loading from the signal table first. If empty (common for ETH),
    generate on-the-fly using the strategy parameters and ema_multi_tf_u /
    features.

    Returns (entries: bool Series, exits: bool Series) aligned to price_index.
    """
    signal_table = SIGNAL_TABLE_MAP.get(strategy)
    if signal_table is None:
        logger.warning("Unknown strategy '%s', using on-the-fly generation.", strategy)
    else:
        # Validate signal table name to prevent SQL injection
        _VALID_TABLES = frozenset(SIGNAL_TABLE_MAP.values())
        if signal_table not in _VALID_TABLES:
            raise ValueError(f"Invalid signal table: {signal_table!r}")

        sql = text(
            f"""
            SELECT entry_ts, exit_ts
            FROM public.{signal_table}
            WHERE id = :asset_id AND direction = 'long'
            ORDER BY entry_ts
            """  # noqa: S608
        )
        try:
            with engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={"asset_id": asset_id})
        except Exception as exc:
            logger.warning(
                "Could not query %s for asset_id=%d: %s. Generating on-the-fly.",
                signal_table,
                asset_id,
                exc,
            )
            df = pd.DataFrame()

        if not df.empty:
            # Build boolean Series aligned to price index
            entries = pd.Series(False, index=price_index, dtype=bool)
            exits = pd.Series(False, index=price_index, dtype=bool)

            entry_ts = pd.to_datetime(df["entry_ts"], utc=True)
            for ts in entry_ts:
                idx = price_index.searchsorted(ts)
                if idx < len(price_index):
                    entries.iloc[idx] = True

            exit_ts_raw = df["exit_ts"].dropna()
            if not exit_ts_raw.empty:
                exit_ts = pd.to_datetime(exit_ts_raw, utc=True)
                for ts in exit_ts:
                    idx = price_index.searchsorted(ts)
                    if idx < len(price_index):
                        exits.iloc[idx] = True

            n_entries = int(entries.sum())
            if n_entries > 0:
                logger.info(
                    "Loaded %d signals from %s for strategy=%s asset_id=%d",
                    n_entries,
                    signal_table,
                    strategy,
                    asset_id,
                )
                return entries, exits

        logger.info(
            "No signals in DB for strategy=%s asset_id=%d -- generating on-the-fly.",
            strategy,
            asset_id,
        )

    # On-the-fly generation based on strategy type
    params = STRATEGY_PARAMS.get(strategy, {})
    signal_type = params.get("signal_type", "")

    if signal_type == "ema_crossover":
        return _generate_ema_crossover_signals(
            engine,
            asset_id,
            fast_ema=params["fast_ema"],
            slow_ema=params["slow_ema"],
            price_index=price_index,
        )
    elif signal_type == "rsi_mean_revert":
        return _generate_rsi_signals(
            engine,
            asset_id,
            period=params.get("period", 14),
            oversold=params.get("oversold", 30),
            overbought=params.get("overbought", 70),
            price_index=price_index,
        )
    elif signal_type == "atr_breakout":
        return _generate_atr_breakout_signals(
            engine,
            asset_id,
            period=params.get("period", 14),
            multiplier=params.get("multiplier", 2.0),
            price_index=price_index,
            price_series=price_series,
        )
    else:
        logger.warning(
            "Unknown signal_type '%s' for strategy '%s', using synthetic signals.",
            signal_type,
            strategy,
        )
        return _synthetic_signals(price_index)


# ---------------------------------------------------------------------------
# Variant A: Fixed sizing + hard stop
# ---------------------------------------------------------------------------


def _run_variant_a(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    stop_pct: float,
    fee_bps: float,
    init_cash: float = 1000.0,
) -> dict:
    """
    Variant A: Fixed 30% allocation + hard stop.

    Uses vectorbt directly (no vol-sizing). Size = 0.30 * init_cash / close.
    """
    try:
        import vectorbt as vbt  # type: ignore[import]
    except ImportError:
        raise ImportError("vectorbt required for Variant A backtest")

    # Strip tz for vectorbt
    price_no_tz = price.copy()
    if hasattr(price.index, "tz") and price.index.tz is not None:
        price_no_tz.index = price.index.tz_localize(None)

    # Fixed size: 30% of init_cash / price at each entry bar
    fixed_pct = 0.30
    size_array = np.where(
        entries.values.astype(bool),
        fixed_pct * init_cash / price.values,
        np.nan,
    )

    pf = vbt.Portfolio.from_signals(
        price_no_tz,
        entries=entries.to_numpy().astype(bool),
        exits=exits.to_numpy().astype(bool),
        size=size_array,
        sl_stop=stop_pct,
        direction="longonly",
        freq="D",
        init_cash=init_cash,
        fees=fee_bps / 1e4,
    )
    metrics = compute_comparison_metrics(pf)
    metrics["variant"] = "A: Fixed+Stops"
    metrics["vol_metric"] = "-"
    metrics["risk_budget"] = "-"
    return metrics


# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------


def _composite_score(metrics: dict, baseline_worst_5: float) -> float:
    """
    Composite score: 0.4*Sharpe + 0.3*Sortino + 0.2*(1+Calmar) + 0.1*(1-|worst_5/baseline|)

    baseline_worst_5: worst_5_day_mean from Variant A (the reference tail metric).
    """
    sharpe_val = metrics.get("sharpe", 0) or 0
    sortino_val = metrics.get("sortino", 0) or 0
    calmar_val = metrics.get("calmar", 0) or 0
    worst_5 = metrics.get("worst_5_day_mean", baseline_worst_5)
    if worst_5 is None or np.isnan(worst_5):
        worst_5 = baseline_worst_5

    denom = (
        baseline_worst_5
        if (baseline_worst_5 and not np.isnan(baseline_worst_5))
        else -0.01
    )
    tail_component = 1.0 - abs(worst_5 / denom)
    return (
        0.4 * sharpe_val
        + 0.3 * sortino_val
        + 0.2 * (1 + calmar_val)
        + 0.1 * max(tail_component, 0)
    )


# ---------------------------------------------------------------------------
# Main comparison runner
# ---------------------------------------------------------------------------


def run_comparison(
    engine,
    strategies: list[str],
    asset_ids: list[int],
    risk_budgets: list[float],
    vol_metrics: list[str],
    stop_pct: float = _DEFAULT_STOP_PCT,
    fee_bps: float = _DEFAULT_FEE_BPS,
    init_cash: float = 1000.0,
) -> list[dict]:
    """
    Run the full comparison matrix and return a list of result dicts.

    Each dict represents one (strategy, asset, vol_metric, risk_budget, variant) combo.
    """
    results = []

    for strategy in strategies:
        for asset_id in asset_ids:
            asset_name = _ASSET_NAME.get(asset_id, str(asset_id))
            logger.info(
                "Processing strategy=%s asset=%s (id=%d)",
                strategy,
                asset_name,
                asset_id,
            )

            # Load price data
            price = _load_price_data(engine, asset_id)
            if price.empty:
                logger.warning(
                    "Skipping strategy=%s asset_id=%d: no price data",
                    strategy,
                    asset_id,
                )
                continue

            # Load vol data
            atr_series = _load_atr_data(engine, asset_id)
            realized_vol = _load_realized_vol(engine, asset_id)

            # Load signals
            entries, exits = _load_signals(
                engine, strategy, asset_id, price.index, price
            )

            if not entries.any():
                logger.warning(
                    "No entry signals for strategy=%s asset_id=%d -- skipping.",
                    strategy,
                    asset_id,
                )
                continue

            # Determine common date range across all series
            valid_start = price.index.min()
            valid_end = price.index.max()

            # Trim to common range
            price_aligned = price.loc[valid_start:valid_end]
            entries_aligned = (
                entries.reindex(price_aligned.index).fillna(False).astype(bool)
            )
            exits_aligned = (
                exits.reindex(price_aligned.index).fillna(False).astype(bool)
            )

            # --- Variant A: Fixed + Stops ---
            try:
                metrics_a = _run_variant_a(
                    price_aligned,
                    entries_aligned,
                    exits_aligned,
                    stop_pct=stop_pct,
                    fee_bps=fee_bps,
                    init_cash=init_cash,
                )
                metrics_a.update(
                    {
                        "strategy": strategy,
                        "asset_id": asset_id,
                        "asset_name": asset_name,
                    }
                )
                baseline_worst_5 = metrics_a.get("worst_5_day_mean", -0.05)
                metrics_a["composite"] = _composite_score(metrics_a, baseline_worst_5)
                results.append(metrics_a)
            except Exception as exc:
                logger.error(
                    "Variant A failed for %s/%s: %s", strategy, asset_name, exc
                )
                baseline_worst_5 = -0.05

            # --- Variants B and C ---
            for vol_metric in vol_metrics:
                # Select vol series
                if vol_metric == "atr":
                    vol_series = atr_series.reindex(price_aligned.index)
                elif vol_metric == "realized":
                    vol_series = realized_vol.reindex(price_aligned.index)
                else:
                    logger.warning("Unknown vol_metric '%s', skipping.", vol_metric)
                    continue

                # Fill forward for small gaps, then drop remaining NaN
                vol_series = vol_series.ffill().bfill()

                if vol_series.isna().all():
                    logger.warning(
                        "All-NaN vol series for %s/%s/%s -- skipping.",
                        strategy,
                        asset_name,
                        vol_metric,
                    )
                    continue

                for risk_budget in risk_budgets:
                    for variant_label, sl_stop in [
                        ("B: Vol-Sized", None),
                        ("C: Vol-Sized+Stops", stop_pct),
                    ]:
                        try:
                            pf = run_vol_sized_backtest(
                                price=price_aligned,
                                entries=entries_aligned,
                                exits=exits_aligned,
                                vol_series=vol_series,
                                vol_type=vol_metric,
                                risk_budget=risk_budget,
                                init_cash=init_cash,
                                fee_bps=fee_bps,
                                sl_stop=sl_stop,
                            )
                            metrics = compute_comparison_metrics(pf)
                            metrics["variant"] = variant_label
                            metrics["vol_metric"] = vol_metric
                            metrics["risk_budget"] = risk_budget
                            metrics["strategy"] = strategy
                            metrics["asset_id"] = asset_id
                            metrics["asset_name"] = asset_name
                            metrics["composite"] = _composite_score(
                                metrics, baseline_worst_5
                            )
                            results.append(metrics)
                        except Exception as exc:
                            logger.error(
                                "%s failed for %s/%s/%s rb=%.3f: %s",
                                variant_label,
                                strategy,
                                asset_name,
                                vol_metric,
                                risk_budget,
                                exc,
                            )

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _df_to_markdown_table(df: pd.DataFrame) -> str:
    """Build a markdown table from DataFrame (no tabulate dependency)."""
    headers = list(df.columns)
    header_row = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"
    rows = []
    for _, row in df.iterrows():
        cells = []
        for h in headers:
            v = row[h]
            if isinstance(v, float) and np.isnan(v):
                cells.append("N/A")
            else:
                cells.append(str(v))
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([header_row, separator] + rows)


def _build_display_row(m: dict, baseline_worst_5: float) -> dict:
    """Build a display-formatted row for the markdown report."""
    variant = m.get("variant", "?")
    vol_metric = m.get("vol_metric", "-")
    rb = m.get("risk_budget", "-")
    rb_str = f"{rb * 100:.1f}%" if isinstance(rb, float) else str(rb)

    return {
        "Variant": variant,
        "Vol Metric": vol_metric,
        "Risk Budget": rb_str,
        "Sharpe": _fmt_float(m.get("sharpe")),
        "Sortino": _fmt_float(m.get("sortino")),
        "Calmar": _fmt_float(m.get("calmar")),
        "MaxDD": _fmt_pct(m.get("max_dd")),
        "Total Ret": _fmt_pct(m.get("total_return")),
        "Trades": _fmt_int(m.get("n_trades")),
        "Win Rate": _fmt_pct(m.get("win_rate")),
        "Worst-5-Day": _fmt_pct(m.get("worst_5_day_mean"), decimals=3),
        "Recovery Bars": _fmt_int(m.get("recovery_bars")),
        "Composite": _fmt_float(m.get("composite"), 4),
    }


def _generate_report(
    results: list[dict],
    strategies: list[str],
    asset_ids: list[int],
    risk_budgets: list[float],
    vol_metrics: list[str],
    stop_pct: float,
    output_dir: Path,
) -> str:
    """Generate SIZING_COMPARISON.md and return its path."""
    ts_now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    asset_names = [_ASSET_NAME.get(a, str(a)) for a in asset_ids]
    rb_pct_list = [f"{r * 100:.1f}%" for r in risk_budgets]

    lines = [
        "# Tail-Risk Sizing Comparison Report",
        "",
        f"Generated: {ts_now}",
        f"Strategies: {', '.join(strategies)}",
        f"Assets: {', '.join(asset_names)} (ids={asset_ids})",
        f"Risk budgets: {', '.join(rb_pct_list)}",
        f"Vol metrics: {', '.join(vol_metrics)}",
        f"Stop-loss (Variant A & C): {stop_pct * 100:.0f}%",
        "",
        "---",
        "",
        "## Results by Strategy",
        "",
    ]

    summary_rows = []

    for strategy in strategies:
        for asset_id in asset_ids:
            asset_name = _ASSET_NAME.get(asset_id, str(asset_id))

            # Filter results for this (strategy, asset)
            combo_results = [
                r
                for r in results
                if r.get("strategy") == strategy and r.get("asset_id") == asset_id
            ]
            if not combo_results:
                continue

            lines.append(f"### {strategy} on {asset_name}")
            lines.append("")

            # Variant A baseline worst-5 for composite scoring
            variant_a = [
                r for r in combo_results if r.get("variant", "").startswith("A:")
            ]
            baseline_worst_5 = (
                variant_a[0].get("worst_5_day_mean", -0.05) if variant_a else -0.05
            )

            # Build display rows
            display_rows = [
                _build_display_row(m, baseline_worst_5) for m in combo_results
            ]
            display_df = pd.DataFrame(display_rows)

            lines.append(_df_to_markdown_table(display_df))
            lines.append("")

            # Winner: highest composite score (exclude Variant A from vol comparison,
            # but include all in winner determination)
            best_result = max(
                combo_results, key=lambda m: m.get("composite", float("-inf"))
            )
            best_variant = best_result.get("variant", "?")
            best_vol = best_result.get("vol_metric", "-")
            best_rb = best_result.get("risk_budget", "-")
            best_rb_str = (
                f"{best_rb * 100:.1f}% risk budget"
                if isinstance(best_rb, float)
                else ""
            )
            best_composite = best_result.get("composite", float("nan"))

            winner_note = f"**Winner:** {best_variant}"
            if best_vol != "-":
                winner_note += f" with {best_vol} vol"
            if best_rb_str:
                winner_note += f" at {best_rb_str}"
            winner_note += f" (composite score: {_fmt_float(best_composite, 4)})"
            lines.append(winner_note)

            # Flag if any vol variant has worse MaxDD than Variant A
            if variant_a:
                a_max_dd = variant_a[0].get("max_dd", 0)
                vol_variants = [
                    r
                    for r in combo_results
                    if not r.get("variant", "").startswith("A:")
                ]
                worse_dd = [r for r in vol_variants if r.get("max_dd", 0) < a_max_dd]
                if worse_dd:
                    n_worse = len(worse_dd)
                    lines.append(
                        f"> **Note:** {n_worse} vol-sized variant(s) show worse MaxDD than "
                        f"Variant A (Fixed+Stops MaxDD={_fmt_pct(a_max_dd)})."
                    )

            lines.append("")

            # Add to summary
            summary_rows.append(
                {
                    "Strategy": strategy,
                    "Asset": asset_name,
                    "Recommended Variant": best_variant,
                    "Vol Metric": best_vol,
                    "Risk Budget": best_rb_str,
                    "Composite Score": _fmt_float(best_composite, 4),
                    "Sharpe": _fmt_float(best_result.get("sharpe")),
                    "MaxDD": _fmt_pct(best_result.get("max_dd")),
                }
            )

    # Summary recommendations
    lines.append("---")
    lines.append("")
    lines.append("## Summary Recommendations")
    lines.append("")
    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        lines.append(_df_to_markdown_table(summary_df))
    else:
        lines.append("_No results generated._")
    lines.append("")

    # Key findings
    lines.append("---")
    lines.append("")
    lines.append("## Key Findings")
    lines.append("")

    if results:
        # Finding 1: Vol-sizing vs fixed MaxDD comparison
        a_results = [r for r in results if r.get("variant", "").startswith("A:")]
        b_results = [r for r in results if r.get("variant", "").startswith("B:")]
        c_results = [r for r in results if r.get("variant", "").startswith("C:")]

        if a_results and b_results:
            avg_dd_a = np.mean(
                [r.get("max_dd", 0) for r in a_results if r.get("max_dd") is not None]
            )
            avg_dd_b = np.mean(
                [r.get("max_dd", 0) for r in b_results if r.get("max_dd") is not None]
            )
            dd_improvement = (
                (avg_dd_b - avg_dd_a) / abs(avg_dd_a) * 100 if avg_dd_a != 0 else 0
            )
            sign = "reduces" if dd_improvement < 0 else "increases"
            lines.append(
                f"- Vol-sizing (B) {sign} average MaxDD by {abs(dd_improvement):.1f}% "
                f"vs Fixed+Stops (A) across all strategy/asset combinations."
            )

        # Finding 2: ATR vs realized vol
        atr_results = [r for r in results if r.get("vol_metric") == "atr"]
        real_results = [r for r in results if r.get("vol_metric") == "realized"]
        if atr_results and real_results:
            atr_wins = 0
            real_wins = 0
            for strategy in strategies:
                for asset_id in asset_ids:
                    atr_best = max(
                        [
                            r
                            for r in atr_results
                            if r["strategy"] == strategy and r["asset_id"] == asset_id
                        ],
                        key=lambda r: r.get("composite", float("-inf")),
                        default=None,
                    )
                    real_best = max(
                        [
                            r
                            for r in real_results
                            if r["strategy"] == strategy and r["asset_id"] == asset_id
                        ],
                        key=lambda r: r.get("composite", float("-inf")),
                        default=None,
                    )
                    if atr_best and real_best:
                        if atr_best.get("composite", 0) >= real_best.get(
                            "composite", 0
                        ):
                            atr_wins += 1
                        else:
                            real_wins += 1
            total_pairs = atr_wins + real_wins
            lines.append(
                f"- ATR-based sizing outperforms realized vol in {atr_wins}/{total_pairs} "
                f"strategy/asset combinations (by composite score)."
            )

        # Finding 3: Variant C tail protection vs Sharpe
        if b_results and c_results:
            avg_sharpe_b = np.mean(
                [r.get("sharpe", 0) for r in b_results if r.get("sharpe") is not None]
            )
            avg_sharpe_c = np.mean(
                [r.get("sharpe", 0) for r in c_results if r.get("sharpe") is not None]
            )
            avg_worst5_b = np.mean(
                [
                    abs(r.get("worst_5_day_mean", 0))
                    for r in b_results
                    if r.get("worst_5_day_mean") is not None
                ]
            )
            avg_worst5_c = np.mean(
                [
                    abs(r.get("worst_5_day_mean", 0))
                    for r in c_results
                    if r.get("worst_5_day_mean") is not None
                ]
            )
            lines.append(
                f"- Variant C (vol-sized + stops) shows avg Sharpe={avg_sharpe_c:.3f} vs "
                f"B (no stops) avg Sharpe={avg_sharpe_b:.3f}; "
                f"avg |worst-5-day| C={avg_worst5_c:.3f} vs B={avg_worst5_b:.3f}."
            )

    lines.append("")
    lines.append("---")
    lines.append(f"*Generated by run_tail_risk_comparison.py on {ts_now}*")

    content = "\n".join(lines)
    report_path = output_dir / "SIZING_COMPARISON.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")
    logger.info("Report written to %s", report_path)
    return str(report_path)


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------


def _generate_charts(
    results: list[dict], strategies: list[str], asset_ids: list[int], output_dir: Path
) -> None:
    """Generate Plotly HTML charts saved to output_dir/charts/."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        logger.warning("plotly not installed -- skipping chart generation.")
        return

    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    # --- Chart 1: Sharpe heatmap ---
    # Group by (strategy, variant) averaged across risk budgets, one subplot per asset
    n_assets = len(asset_ids)

    fig1 = make_subplots(
        rows=1,
        cols=max(n_assets, 1),
        subplot_titles=[_ASSET_NAME.get(a, str(a)) for a in asset_ids],
    )

    for col_idx, asset_id in enumerate(asset_ids, start=1):
        combo = [r for r in results if r.get("asset_id") == asset_id]
        if not combo:
            continue

        # Pivot: rows = strategies, cols = variant labels
        variant_labels = sorted(set(r.get("variant", "?") for r in combo))
        z_data = []
        y_labels = []

        for strategy in strategies:
            row_data = []
            for vl in variant_labels:
                matching = [
                    r
                    for r in combo
                    if r["strategy"] == strategy and r.get("variant") == vl
                ]
                if matching:
                    # Average across risk budgets
                    sharpe_vals = [r.get("sharpe", float("nan")) for r in matching]
                    sharpe_clean = [
                        v for v in sharpe_vals if v is not None and not np.isnan(v)
                    ]
                    row_data.append(
                        np.mean(sharpe_clean) if sharpe_clean else float("nan")
                    )
                else:
                    row_data.append(float("nan"))
            z_data.append(row_data)
            y_labels.append(strategy)

        fig1.add_trace(
            go.Heatmap(
                z=z_data,
                x=variant_labels,
                y=y_labels,
                colorscale="RdYlGn",
                name=_ASSET_NAME.get(asset_id, str(asset_id)),
                showscale=(col_idx == 1),
            ),
            row=1,
            col=col_idx,
        )

    fig1.update_layout(
        title_text="Sharpe Ratio by Strategy and Variant",
        height=500,
    )
    path1 = charts_dir / "sizing_sharpe_heatmap.html"
    fig1.write_html(str(path1))
    logger.info("Sharpe heatmap saved to %s", path1)

    # --- Chart 2: MaxDD comparison (grouped bar chart) ---
    fig2 = go.Figure()

    variant_labels_all = sorted(set(r.get("variant", "?") for r in results))

    for variant_label in variant_labels_all:
        x_labels = []
        y_values = []
        for strategy in strategies:
            for asset_id in asset_ids:
                asset_name = _ASSET_NAME.get(asset_id, str(asset_id))
                matching = [
                    r
                    for r in results
                    if r["strategy"] == strategy
                    and r.get("asset_id") == asset_id
                    and r.get("variant") == variant_label
                ]
                if matching:
                    dd_vals = [
                        abs(r.get("max_dd", 0))
                        for r in matching
                        if r.get("max_dd") is not None
                        and not np.isnan(r.get("max_dd", float("nan")))
                    ]
                    avg_dd = np.mean(dd_vals) * 100 if dd_vals else 0.0
                else:
                    avg_dd = 0.0
                x_labels.append(f"{strategy}/{asset_name}")
                y_values.append(avg_dd)

        fig2.add_trace(
            go.Bar(
                name=variant_label,
                x=x_labels,
                y=y_values,
            )
        )

    fig2.update_layout(
        barmode="group",
        title_text="MaxDD Comparison Across Variants (avg across risk budgets)",
        yaxis_title="Max Drawdown (%)",
        height=600,
        xaxis_tickangle=-45,
    )
    path2 = charts_dir / "sizing_maxdd_comparison.html"
    fig2.write_html(str(path2))
    logger.info("MaxDD comparison chart saved to %s", path2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="TAIL-01 vol-sizing comparison: 3 variants x strategies x assets x vol metrics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=_DEFAULT_STRATEGIES,
        help="Strategy names (default: all 4 bakeoff strategies).",
    )
    parser.add_argument(
        "--asset-ids",
        nargs="+",
        type=int,
        default=_DEFAULT_ASSET_IDS,
        help="Asset IDs (default: 1 1027 for BTC/ETH).",
    )
    parser.add_argument(
        "--risk-budgets",
        nargs="+",
        type=float,
        default=_DEFAULT_RISK_BUDGETS,
        help="Risk budget fractions (default: 0.005 0.01 0.02).",
    )
    parser.add_argument(
        "--vol-metrics",
        nargs="+",
        default=_DEFAULT_VOL_METRICS,
        choices=["atr", "realized"],
        help="Vol metric types (default: atr realized).",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=_DEFAULT_STOP_PCT,
        help="Hard stop pct for Variant A and C (default: 0.07 = 7%%).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Report output directory (default: {_DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print configuration and exit without running backtests.",
    )
    parser.add_argument(
        "--fee-bps",
        type=float,
        default=_DEFAULT_FEE_BPS,
        help="Fee in basis points (default: 16).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable debug logging.",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # --- Dry run ---
    if args.dry_run:
        print("=== Tail Risk Comparison Configuration (Dry Run) ===")
        print(f"Strategies:    {args.strategies}")
        print(f"Asset IDs:     {args.asset_ids}")
        print(f"Risk budgets:  {[f'{r * 100:.1f}%' for r in args.risk_budgets]}")
        print(f"Vol metrics:   {args.vol_metrics}")
        print(f"Stop pct:      {args.stop_pct * 100:.1f}%")
        print(f"Fee (bps):     {args.fee_bps}")
        print(f"Output dir:    {args.output_dir}")
        print()
        n_combos = (
            len(args.strategies)
            * len(args.asset_ids)
            * (1 + len(args.vol_metrics) * len(args.risk_budgets) * 2)
        )
        print(
            f"Total backtests: {n_combos} "
            f"(1 Variant A + {len(args.vol_metrics)} vol x {len(args.risk_budgets)} budgets x 2 variants B/C "
            f"per strategy/asset)"
        )
        print()
        print("Variants:")
        print("  A: Fixed 30% allocation + hard stop")
        print("  B: Vol-sized position + no stop")
        print("  C: Vol-sized position + hard stop")
        sys.exit(0)

    # --- Build engine ---
    engine = create_engine(TARGET_DB_URL, poolclass=NullPool)

    # --- Run comparison ---
    logger.info(
        "Starting TAIL-01 comparison: %d strategies x %d assets x %d risk_budgets x %d vol_metrics",
        len(args.strategies),
        len(args.asset_ids),
        len(args.risk_budgets),
        len(args.vol_metrics),
    )

    results = run_comparison(
        engine=engine,
        strategies=args.strategies,
        asset_ids=args.asset_ids,
        risk_budgets=args.risk_budgets,
        vol_metrics=args.vol_metrics,
        stop_pct=args.stop_pct,
        fee_bps=args.fee_bps,
    )

    if not results:
        logger.error(
            "No results produced. Check data availability and strategy config."
        )
        sys.exit(1)

    logger.info("Comparison complete: %d result rows produced.", len(results))

    # --- Generate report ---
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = _generate_report(
        results=results,
        strategies=args.strategies,
        asset_ids=args.asset_ids,
        risk_budgets=args.risk_budgets,
        vol_metrics=args.vol_metrics,
        stop_pct=args.stop_pct,
        output_dir=args.output_dir,
    )
    print(f"Report: {report_path}")

    # --- Generate charts ---
    _generate_charts(results, args.strategies, args.asset_ids, args.output_dir)

    print()
    print(f"SIZING_COMPARISON.md: {args.output_dir / 'SIZING_COMPARISON.md'}")
    print(f"Charts: {args.output_dir / 'charts'}/")


if __name__ == "__main__":
    main()
