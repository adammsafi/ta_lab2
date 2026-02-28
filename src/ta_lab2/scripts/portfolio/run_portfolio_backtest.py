#!/usr/bin/env python
"""
Portfolio backtest: TopkDropout vs fixed sizing vs equal weight vs per-asset baselines.

Slices price history over a date range, runs portfolio construction for each
rebalance period, and prints Sharpe ratio comparisons.

ASCII-only file -- no UTF-8 box-drawing characters.

Usage:
    python -m ta_lab2.scripts.portfolio.run_portfolio_backtest \\
        --start 2023-01-01 --end 2024-12-31 --tf 1D

    python -m ta_lab2.scripts.portfolio.run_portfolio_backtest \\
        --start 2023-01-01 --strategy topk_dropout --output results.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from ta_lab2.portfolio.cost_tracker import TurnoverTracker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _resolve_db_url(db_url_arg: Optional[str]) -> str:
    import os

    if db_url_arg:
        return db_url_arg
    url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url
    config_path = "db_config.env"
    try:
        p = Path(config_path)
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith("TARGET_DB_URL=") or line.startswith(
                    "DATABASE_URL="
                ):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    raise RuntimeError(
        "No database URL found. Set TARGET_DB_URL env var or pass --db-url."
    )


def _make_engine(db_url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    return create_engine(db_url, poolclass=NullPool)


def _load_signal_probabilities(engine, tf: str) -> pd.DataFrame:
    """
    Load the latest trade_probability per asset from cmc_meta_label_results.

    Returns DataFrame with columns [id, trade_probability].
    Returns empty DataFrame if table does not exist or has no data.
    """
    from sqlalchemy import text

    query = text(
        """
        SELECT DISTINCT ON (asset_id)
            asset_id AS id, trade_probability, t0 AS ts
        FROM cmc_meta_label_results
        WHERE trade_probability IS NOT NULL
        ORDER BY asset_id, t0 DESC
        """
    )
    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)
        if df.empty:
            logger.warning("cmc_meta_label_results has no trade_probability data.")
            return pd.DataFrame()
        # Ensure numeric type (NUMERIC comes back as Decimal)
        df["trade_probability"] = df["trade_probability"].astype(float)
        df["id"] = df["id"].astype(int)
        return df[["id", "trade_probability"]]
    except Exception as exc:
        logger.warning(
            "Could not load signal probabilities from cmc_meta_label_results: %s. "
            "Falling back to default probability.",
            exc,
        )
        return pd.DataFrame()


def _load_all_prices(tf: str, start: datetime, end: datetime, engine) -> pd.DataFrame:
    """
    Load close prices from cmc_price_bars_multi_tf_u for all assets in the date range.

    CRITICAL: uses 'timestamp' column (NOT 'ts').

    Returns wide DataFrame: DatetimeIndex x asset_id columns.
    """
    from sqlalchemy import text

    query = text(
        """
        SELECT id, timestamp, close
        FROM cmc_price_bars_multi_tf_u
        WHERE tf = :tf
          AND timestamp >= :start
          AND timestamp <= :end
        ORDER BY timestamp, id
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(
            query,
            conn,
            params={
                "tf": tf,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )

    if df.empty:
        logger.warning("No price data found for tf=%s in range %s..%s", tf, start, end)
        return pd.DataFrame()

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    prices = df.pivot(index="timestamp", columns="id", values="close")
    prices.index.name = "ts"
    prices.columns = [int(c) for c in prices.columns]

    logger.info(
        "Loaded %d rows x %d assets for tf=%s range %s..%s",
        len(prices),
        len(prices.columns),
        tf,
        start.date(),
        end.date(),
    )
    return prices


# ---------------------------------------------------------------------------
# Return computation helpers
# ---------------------------------------------------------------------------


def _compute_period_returns(prices: pd.DataFrame) -> pd.Series:
    """
    Compute 1-period forward returns from a price slice (close-to-close).

    Returns arithmetic return for the LAST bar of the slice vs one bar ahead.
    Uses the last two rows of prices.
    """
    if len(prices) < 2:
        return pd.Series(dtype=float)
    last = prices.iloc[-1]
    prev = prices.iloc[-2]
    rets = (last - prev) / prev.where(prev != 0)
    return rets


def _compute_sharpe(returns: pd.Series, periods_per_year: float = 252.0) -> float:
    """Annualized Sharpe ratio from a series of period returns."""
    if returns.empty or returns.std() == 0:
        return float("nan")
    mean = returns.mean()
    std = returns.std(ddof=1)
    return float((mean / std) * (periods_per_year**0.5))


def _tf_periods_per_year(tf: str) -> float:
    """Map timeframe to approximate annualized periods for Sharpe scaling."""
    _MAP = {
        "1D": 252.0,
        "7D": 52.0,
        "1W": 52.0,
        "1M": 12.0,
        "4H": 252.0 * 6,
        "1H": 252.0 * 24,
    }
    return _MAP.get(tf, 252.0)


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------


def _strategy_topk_dropout(
    prices_window: pd.DataFrame,
    config: dict,
    current_holdings: set,
    signal_probs: dict[int, float] | None = None,
) -> tuple[dict, set]:
    """
    TopkDropout strategy: PortfolioOptimizer + TopkDropoutSelector + BetSizer.

    Returns (weights_dict, new_holdings_set).
    Weights are probability-scaled (bet-sized).
    """
    from ta_lab2.portfolio import BetSizer, PortfolioOptimizer, TopkDropoutSelector

    try:
        opt = PortfolioOptimizer(config=config)
        result = opt.run_all(prices_window)
        active_weights = opt.get_active_weights(result)

        if not active_weights:
            return {}, current_holdings

        # TopK selection
        selector = TopkDropoutSelector(config=config)
        scores = pd.Series(active_weights)
        new_assets, removed = selector.select(scores, current_holdings)
        new_holdings = (current_holdings - removed) | new_assets

        # Keep only selected holdings
        held_weights = {a: active_weights.get(a, 0.0) for a in new_holdings}
        total_w = sum(abs(w) for w in held_weights.values())
        if total_w > 0:
            held_weights = {a: w / total_w for a, w in held_weights.items()}

        # Real trade_probability from cmc_meta_label_results; falls back to 0.6 if unavailable.
        default_prob = 0.6
        probs = {
            a: signal_probs.get(a, default_prob) if signal_probs else default_prob
            for a in held_weights
        }
        sides = {a: 1 for a in held_weights}
        sizer = BetSizer(config=config)
        sized = sizer.scale_weights(held_weights, probs, sides)

        # Re-normalize after sizing
        total_s = sum(abs(w) for w in sized.values())
        if total_s > 0:
            sized = {a: w / total_s for a, w in sized.items()}

        return sized, new_holdings

    except Exception as exc:
        logger.debug("topk_dropout strategy failed: %s", exc)
        return {}, current_holdings


def _strategy_fixed_sizing(
    prices_window: pd.DataFrame,
    config: dict,
    current_holdings: set,
    **kwargs,
) -> tuple[dict, set]:
    """
    Fixed sizing: TopK selection + uniform 1/K weights (NO probability scaling).

    Baseline strategy -- same asset selection as topk_dropout but equal allocation.
    """
    from ta_lab2.portfolio import PortfolioOptimizer, TopkDropoutSelector

    try:
        opt = PortfolioOptimizer(config=config)
        result = opt.run_all(prices_window)
        active_weights = opt.get_active_weights(result)

        if not active_weights:
            return {}, current_holdings

        selector = TopkDropoutSelector(config=config)
        scores = pd.Series(active_weights)
        new_assets, removed = selector.select(scores, current_holdings)
        new_holdings = (current_holdings - removed) | new_assets

        k = len(new_holdings)
        if k == 0:
            return {}, new_holdings

        uniform_weight = 1.0 / k
        weights = {a: uniform_weight for a in new_holdings}
        return weights, new_holdings

    except Exception as exc:
        logger.debug("fixed_sizing strategy failed: %s", exc)
        return {}, current_holdings


def _strategy_equal_weight(
    prices_window: pd.DataFrame,
    config: dict,  # noqa: ARG001
    current_holdings: set,  # noqa: ARG001
    **kwargs,
) -> tuple[dict, set]:
    """
    Equal weight: 1/N across ALL assets in the current price universe.
    """
    assets = list(prices_window.columns)
    n = len(assets)
    if n == 0:
        return {}, set()
    w = 1.0 / n
    weights = {a: w for a in assets}
    return weights, set(assets)


def _strategy_per_asset(
    prices_window: pd.DataFrame,
    config: dict,  # noqa: ARG001
    current_holdings: set,  # noqa: ARG001
    **kwargs,
) -> tuple[dict, set]:
    """
    Per-asset best strategy (Phase 42 bake-off baseline).

    Uses momentum score: 1-period return ranked descending, top 10 equally weighted.
    This is a simplified stand-in for the Phase 42 per-asset signal champion.
    """
    if len(prices_window) < 2:
        return {}, set()

    last_ret = prices_window.iloc[-1] / prices_window.iloc[-2] - 1.0
    last_ret = last_ret.dropna()
    topk = 10
    top_assets = set(last_ret.nlargest(min(topk, len(last_ret))).index)
    k = len(top_assets)
    if k == 0:
        return {}, set()
    weights = {a: 1.0 / k for a in top_assets}
    return weights, top_assets


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------


def _run_backtest(
    prices: pd.DataFrame,
    strategy: str,
    config: dict,
    rebalance_days: int = 1,
    signal_probs: dict[int, float] | None = None,
) -> tuple[pd.Series, "TurnoverTracker"]:
    """
    Run a single-strategy backtest over the full price history.

    Slices a rolling window, calls the strategy, computes 1-period returns.
    Tracks turnover cost per rebalance via TurnoverTracker.

    Returns (pd.Series of per-period portfolio returns, TurnoverTracker).
    """
    from ta_lab2.portfolio import TurnoverTracker

    tracker = TurnoverTracker(config)

    all_dates = prices.index
    if len(all_dates) < 60:
        logger.warning("Price history too short for backtest (%d bars)", len(all_dates))
        return pd.Series(dtype=float), tracker

    strategy_fn = {
        "topk_dropout": _strategy_topk_dropout,
        "fixed_sizing": _strategy_fixed_sizing,
        "equal_weight": _strategy_equal_weight,
        "per_asset": _strategy_per_asset,
    }.get(strategy)

    if strategy_fn is None:
        raise ValueError(f"Unknown strategy: {strategy!r}")

    # Lookback window (bars)
    opt_cfg = config.get("optimizer", {})
    lookback_cal = int(opt_cfg.get("lookback_calendar_days", 180))
    tf_days = 1.0  # assume 1D for this loop; caller guarantees consistent tf
    lookback_bars = max(
        int(opt_cfg.get("min_lookback_bars", 60)), round(lookback_cal / tf_days)
    )

    portfolio_returns: list[tuple] = []
    current_weights: dict = {}
    current_holdings: set = set()
    rebalance_counter = 0

    for i in range(lookback_bars, len(all_dates) - 1):
        ts = all_dates[i]

        # Save old weights before any potential rebalance
        old_weights_before = dict(current_weights)

        # Rebalance on schedule
        if rebalance_counter % rebalance_days == 0:
            window = prices.iloc[i - lookback_bars : i + 1]
            # Drop columns with too many NaNs
            valid_cols = [
                c
                for c in window.columns
                if window[c].notna().sum() >= lookback_bars // 2
            ]
            window = window[valid_cols].copy()
            if len(window.columns) >= 2:
                try:
                    new_weights, new_holdings = strategy_fn(
                        window,
                        config,
                        current_holdings,
                        signal_probs=signal_probs,
                    )
                    if new_weights:
                        current_weights = new_weights
                        current_holdings = new_holdings
                except Exception as exc:
                    logger.debug(
                        "Strategy %s rebalance failed at %s: %s", strategy, ts, exc
                    )

        # 1-period forward return
        next_prices = prices.iloc[i + 1]
        curr_prices = prices.iloc[i]

        period_return = 0.0
        for asset_id, w in current_weights.items():
            if asset_id in next_prices.index and asset_id in curr_prices.index:
                p1 = float(next_prices[asset_id])
                p0 = float(curr_prices[asset_id])
                if p0 > 0 and not np.isnan(p1) and not np.isnan(p0):
                    period_return += w * ((p1 - p0) / p0)

        # Track turnover cost: weight change at start of period + gross return earned
        tracker.track(
            ts=ts,
            old_weights=old_weights_before,
            new_weights=current_weights,
            gross_return=period_return,
            portfolio_value=1.0,
        )

        portfolio_returns.append((ts, period_return))
        rebalance_counter += 1

    if not portfolio_returns:
        return pd.Series(dtype=float), tracker

    return pd.Series(
        [r for _, r in portfolio_returns],
        index=[t for t, _ in portfolio_returns],
        name=strategy,
    ), tracker


# ---------------------------------------------------------------------------
# Main backtest logic
# ---------------------------------------------------------------------------


def run_backtest(
    start: datetime,
    end: datetime,
    tf: str,
    strategies: list[str],
    config_path: str,
    output: Optional[str],
    db_url: str,
) -> int:
    """
    Run portfolio backtest comparing the specified strategies.

    Returns 0 on success, 1 on error.
    """
    from ta_lab2.portfolio import load_portfolio_config

    try:
        config = load_portfolio_config(config_path)
    except FileNotFoundError:
        logger.error("Config file not found: %s", config_path)
        return 1

    engine = _make_engine(db_url)

    # Load prices for the date range + lookback buffer
    opt_cfg = config.get("optimizer", {})
    lookback_cal = int(opt_cfg.get("lookback_calendar_days", 180))
    buffer_start = start - timedelta(days=lookback_cal + 30)

    prices = _load_all_prices(tf, buffer_start, end, engine)
    if prices.empty:
        logger.error("No price data loaded. Cannot run backtest.")
        return 1

    # Drop assets with very sparse data
    min_bars = int(opt_cfg.get("min_lookback_bars", 60))
    valid_cols = [c for c in prices.columns if prices[c].count() >= min_bars]
    prices = prices[valid_cols]
    logger.info("Using %d assets after sparse-data filter.", len(prices.columns))

    if len(prices.columns) < 2:
        logger.error("Fewer than 2 assets with sufficient history.")
        return 1

    periods_per_year = _tf_periods_per_year(tf)

    # --- Load signal probabilities for probability-varying bet sizing ---
    prob_df = _load_signal_probabilities(engine, tf)
    if not prob_df.empty:
        signal_probs_map: dict[int, float] = dict(
            zip(prob_df["id"], prob_df["trade_probability"])
        )
        logger.info(
            "Loaded %d signal probabilities from cmc_meta_label_results.",
            len(signal_probs_map),
        )
    else:
        signal_probs_map = {}
        logger.info(
            "No signal probabilities available; bet sizing will use default 0.6 fallback."
        )

    # --- Run each requested strategy ---
    results: dict[str, pd.Series] = {}
    trackers: dict[str, "TurnoverTracker"] = {}
    strategy_display = {
        "topk_dropout": "TopkDropout (probability-scaled)",
        "fixed_sizing": "Fixed Sizing (uniform weights)",
        "equal_weight": "Equal Weight (full universe)",
        "per_asset": "Per-Asset (Phase 42 momentum)",
    }

    for strat in strategies:
        logger.info("Running strategy: %s ...", strat)
        try:
            rets, tracker = _run_backtest(
                prices,
                strat,
                config,
                signal_probs=signal_probs_map or None,
            )
            # Trim to requested date range
            rets = rets[rets.index >= pd.Timestamp(start, tz="UTC")]
            results[strat] = rets
            trackers[strat] = tracker
            sharpe = _compute_sharpe(rets, periods_per_year)
            logger.info(
                "  %s: %d periods, Sharpe=%.3f",
                strat,
                len(rets),
                sharpe,
            )
        except Exception as exc:
            logger.warning("Strategy %s failed: %s", strat, exc)
            results[strat] = pd.Series(dtype=float)

    # --- Sharpe comparison table ---
    print(f"\n{'=' * 60}")
    print("PORTFOLIO BACKTEST SUMMARY")
    print(f"{'=' * 60}")
    print(f"  TF    : {tf}")
    print(f"  Start : {start.date()}")
    print(f"  End   : {end.date()}")
    print(f"  Assets: {len(prices.columns)}")
    print()
    print("=== Sharpe Ratio Comparison ===")

    sharpes: dict[str, float] = {}
    for strat in strategies:
        rets = results.get(strat, pd.Series(dtype=float))
        sh = _compute_sharpe(rets, periods_per_year)
        sharpes[strat] = sh
        label = strategy_display.get(strat, strat)
        sharpe_str = f"{sh:.3f}" if not np.isnan(sh) else "  N/A"
        print(f"  {label:<40s}: {sharpe_str}")

    # Comparative delta: topk_dropout vs fixed_sizing
    if "topk_dropout" in sharpes and "fixed_sizing" in sharpes:
        sh_topk = sharpes["topk_dropout"]
        sh_fixed = sharpes["fixed_sizing"]
        if not np.isnan(sh_topk) and not np.isnan(sh_fixed) and sh_fixed != 0:
            delta_abs = sh_topk - sh_fixed
            delta_pct = (delta_abs / abs(sh_fixed)) * 100.0
            sign = "+" if delta_abs >= 0 else ""
            print(
                f"\n  {'TopkDropout vs Fixed Sizing':<40s}: "
                f"{sign}{delta_abs:.3f} ({sign}{delta_pct:.1f}%)"
            )
        elif not np.isnan(sh_topk) and not np.isnan(sh_fixed):
            delta_abs = sh_topk - sh_fixed
            sign = "+" if delta_abs >= 0 else ""
            print(f"\n  {'TopkDropout vs Fixed Sizing':<40s}: {sign}{delta_abs:.3f}")

    print(f"{'=' * 60}")

    # --- Per-strategy stats with decomposed cost reporting ---
    print("\n=== Per-Strategy Statistics ===")
    for strat in strategies:
        rets = results.get(strat, pd.Series(dtype=float))
        if rets.empty:
            print(f"  {strat}: no data")
            continue
        gross_return = float((1 + rets).prod() - 1)
        ann_vol = float(rets.std(ddof=1) * (periods_per_year**0.5))
        max_dd = float(((1 + rets).cumprod() / (1 + rets).cumprod().cummax() - 1).min())

        # Decomposed turnover cost from TurnoverTracker
        trk = trackers.get(strat)
        turnover_cost = sum(r["cost_pct"] for r in trk.history) if trk else 0.0
        net_return = gross_return - turnover_cost

        print(
            f"  {strat:20s}: gross_ret={gross_return:+.2%}  turnover_cost={turnover_cost:.2%}  "
            f"net_ret={net_return:+.2%}  ann_vol={ann_vol:.2%}  max_dd={max_dd:.2%}  "
            f"n_periods={len(rets)}"
        )

    # --- Optional CSV output ---
    if output:
        returns_df = pd.DataFrame(results)
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        returns_df.to_csv(output_path)
        print(f"\n  Results saved to: {output_path}")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Portfolio backtest: TopkDropout vs fixed sizing vs equal weight "
            "vs per-asset baselines. Prints Sharpe comparison."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full comparison of all 4 strategies
  python -m ta_lab2.scripts.portfolio.run_portfolio_backtest \\
      --start 2023-01-01 --end 2024-12-31

  # Single strategy
  python -m ta_lab2.scripts.portfolio.run_portfolio_backtest \\
      --start 2023-01-01 --strategy topk_dropout

  # Save returns to CSV
  python -m ta_lab2.scripts.portfolio.run_portfolio_backtest \\
      --start 2023-01-01 --output /tmp/backtest.csv
        """,
    )

    p.add_argument(
        "--start", required=True, metavar="YYYY-MM-DD", help="Backtest start date"
    )
    p.add_argument(
        "--end",
        default=None,
        metavar="YYYY-MM-DD",
        help="Backtest end date (default: today)",
    )
    p.add_argument("--tf", default="1D", help="Timeframe (default: 1D)")
    p.add_argument(
        "--strategy",
        default="all",
        choices=["topk_dropout", "fixed_sizing", "equal_weight", "per_asset", "all"],
        help=(
            "Strategy to run: topk_dropout | fixed_sizing | equal_weight | per_asset | all "
            "(default: all)"
        ),
    )
    p.add_argument(
        "--config",
        default="configs/portfolio.yaml",
        help="Path to portfolio.yaml (default: configs/portfolio.yaml)",
    )
    p.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Save per-period returns CSV to this path",
    )
    p.add_argument(
        "--db-url",
        default=None,
        help="Database URL (default: TARGET_DB_URL env or db_config.env)",
    )
    p.add_argument("--verbose", action="store_true", help="Enable debug logging")

    args = p.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        db_url = _resolve_db_url(args.db_url)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    start = _parse_date(args.start)
    end = _parse_date(args.end) if args.end else datetime.now(tz=timezone.utc)

    if args.strategy == "all":
        strategies = ["topk_dropout", "fixed_sizing", "equal_weight", "per_asset"]
    else:
        strategies = [args.strategy]

    return run_backtest(
        start=start,
        end=end,
        tf=args.tf,
        strategies=strategies,
        config_path=args.config,
        output=args.output,
        db_url=db_url,
    )


if __name__ == "__main__":
    sys.exit(main())
