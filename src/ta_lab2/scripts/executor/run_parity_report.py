#!/usr/bin/env python
"""
Strategy parity report: live Sharpe vs backtest Sharpe per strategy.

Computes fill-to-fill Sharpe (execution quality) and mark-to-market daily
Sharpe (portfolio-level) for each active strategy, then compares against
the cross-validated backtest Sharpe from strategy_bakeoff_results.

Usage:
    python -m ta_lab2.scripts.executor.run_parity_report
    python -m ta_lab2.scripts.executor.run_parity_report --window 30
    python -m ta_lab2.scripts.executor.run_parity_report --strategy ema_trend_17_77_paper_v1
    python -m ta_lab2.scripts.executor.run_parity_report --dry-run
    python -m ta_lab2.scripts.executor.run_parity_report --verbose

Tables written: strategy_parity
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB resolution
# ---------------------------------------------------------------------------


def _resolve_db_url(db_url: str | None) -> str:
    """Resolve database URL from argument or environment."""
    if db_url:
        return db_url

    url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url

    config_path = "db_config.env"
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TARGET_DB_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    raise ValueError(
        "Database URL not found. Provide --db-url or set TARGET_DB_URL env var."
    )


# ---------------------------------------------------------------------------
# Strategy name extraction
# ---------------------------------------------------------------------------


def _extract_strategy_name(config_name: str) -> str:
    """Strip _paper_v<N> suffix from config_name to get strategy_name.

    Examples:
        ema_trend_17_77_paper_v1 -> ema_trend_17_77
        macd_crossover_12_26_paper_v2 -> macd_crossover_12_26
        rsi_mean_revert_14_paper_v1 -> rsi_mean_revert_14
    """
    return re.sub(r"_paper_v\d+$", "", config_name)


# ---------------------------------------------------------------------------
# Sharpe computation helpers
# ---------------------------------------------------------------------------


def _annualized_sharpe(returns: list[float], periods_per_year: float) -> float | None:
    """Compute annualized Sharpe ratio.

    Returns None if fewer than 2 observations or std is zero.
    """
    if len(returns) < 2:
        return None
    arr = np.array(returns, dtype=float)
    std = float(np.std(arr, ddof=1))
    if std == 0.0:
        return None
    mean = float(np.mean(arr))
    return float(mean / std * np.sqrt(periods_per_year))


# ---------------------------------------------------------------------------
# Per-strategy computation
# ---------------------------------------------------------------------------


def _load_active_configs(engine: Engine, strategy_filter: str | None) -> list[dict]:
    """Load active strategy configs from dim_executor_config."""
    sql = """
        SELECT config_id, config_name, signal_id, initial_capital
        FROM dim_executor_config
        WHERE is_active = TRUE
    """
    params: dict = {}
    if strategy_filter:
        sql += " AND config_name = :config_name"
        params["config_name"] = strategy_filter

    sql += " ORDER BY config_name"

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    return [
        {
            "config_id": r.config_id,
            "config_name": r.config_name,
            "signal_id": r.signal_id,
            "initial_capital": float(r.initial_capital),
        }
        for r in rows
    ]


def _compute_fill_to_fill_sharpe(
    engine: Engine, signal_id: int, window_start: datetime
) -> tuple[float | None, int]:
    """Compute fill-to-fill round-trip Sharpe for a strategy signal_id.

    Returns (sharpe, n_fills) where n_fills is the number of fills in window.
    Round-trips are matched as buy->sell (long) or sell->buy (short) pairs
    per asset_id, ordered by filled_at.
    """
    sql = """
        SELECT
            o.asset_id,
            f.fill_price,
            f.fill_qty,
            f.side,
            f.filled_at
        FROM fills f
        JOIN orders o ON f.order_id = o.order_id
        WHERE o.signal_id = :signal_id
          AND f.filled_at >= :window_start
        ORDER BY o.asset_id, f.filled_at
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(sql),
            {"signal_id": signal_id, "window_start": window_start},
        ).fetchall()

    if not rows:
        return None, 0

    n_fills = len(rows)

    # Group by asset_id and match round-trips (buy->sell or sell->buy)
    from collections import defaultdict

    fills_by_asset: dict[int, list] = defaultdict(list)
    for r in rows:
        fills_by_asset[r.asset_id].append(r)

    round_trip_returns: list[float] = []
    hold_days_list: list[float] = []

    for asset_id, asset_fills in fills_by_asset.items():
        # Simple FIFO pairing: match first buy with first sell
        buys: list = []
        sells: list = []
        for f in asset_fills:
            if f.side == "buy":
                buys.append(f)
            else:
                sells.append(f)

        # Match longs: buy -> sell
        for entry, exit_f in zip(buys, sells):
            entry_price = float(entry.fill_price)
            exit_price = float(exit_f.fill_price)
            if entry_price <= 0:
                continue
            ret = (exit_price - entry_price) / entry_price
            round_trip_returns.append(ret)
            hold_secs = (exit_f.filled_at - entry.filled_at).total_seconds()
            hold_days = max(hold_secs / 86400.0, 1.0 / 24)  # minimum 1 hour
            hold_days_list.append(hold_days)

    if len(round_trip_returns) < 2:
        return None, n_fills

    # Annualize using mean hold period
    mean_hold_days = float(np.mean(hold_days_list)) if hold_days_list else 1.0
    periods_per_year = 252.0 / mean_hold_days
    sharpe = _annualized_sharpe(round_trip_returns, periods_per_year)
    return sharpe, n_fills


def _compute_mtm_daily_sharpe(
    engine: Engine,
    signal_id: int,
    window_start: datetime,
    window_end: datetime,
) -> tuple[float | None, int]:
    """Compute mark-to-market daily portfolio Sharpe.

    Uses positions table to find asset_ids with exposure, then loads daily
    close prices from price_bars_multi_tf_u to compute daily portfolio returns.

    Returns (sharpe, n_mtm_days).
    """
    # Find assets that had fills for this signal_id in the window
    assets_sql = """
        SELECT DISTINCT o.asset_id
        FROM fills f
        JOIN orders o ON f.order_id = o.order_id
        WHERE o.signal_id = :signal_id
          AND f.filled_at BETWEEN :window_start AND :window_end
    """
    with engine.connect() as conn:
        asset_rows = conn.execute(
            text(assets_sql),
            {
                "signal_id": signal_id,
                "window_start": window_start,
                "window_end": window_end,
            },
        ).fetchall()

    if not asset_rows:
        return None, 0

    asset_ids = [r.asset_id for r in asset_rows]

    # Load daily closes for these assets in the window
    prices_sql = """
        SELECT id AS asset_id, ts::date AS trade_date, close
        FROM price_bars_multi_tf_u
        WHERE id = ANY(:asset_ids)
          AND tf = '1d'
          AND alignment_source = 'multi_tf'
          AND ts BETWEEN :window_start AND :window_end
        ORDER BY id, ts
    """
    with engine.connect() as conn:
        price_rows = conn.execute(
            text(prices_sql),
            {
                "asset_ids": asset_ids,
                "window_start": window_start,
                "window_end": window_end,
            },
        ).fetchall()

    if not price_rows:
        return None, 0

    # Build daily price dict: {(asset_id, date): close}
    from collections import defaultdict

    prices_by_asset: dict[int, list[tuple]] = defaultdict(list)
    for r in price_rows:
        prices_by_asset[r.asset_id].append((r.trade_date, float(r.close)))

    # Compute per-asset daily returns, then equal-weight portfolio
    all_dates: set = set()
    asset_returns: dict[int, dict] = {}

    for asset_id, date_prices in prices_by_asset.items():
        date_prices.sort(key=lambda x: x[0])
        asset_ret: dict = {}
        for i in range(1, len(date_prices)):
            prev_close = date_prices[i - 1][1]
            curr_close = date_prices[i][1]
            if prev_close > 0:
                date_ = date_prices[i][0]
                asset_ret[date_] = (curr_close - prev_close) / prev_close
                all_dates.add(date_)
        asset_returns[asset_id] = asset_ret

    if not all_dates:
        return None, 0

    sorted_dates = sorted(all_dates)

    # Portfolio daily return = equal-weight average across assets with data
    portfolio_returns: list[float] = []
    for date_ in sorted_dates:
        daily_rets = []
        for asset_id in asset_ids:
            ret = asset_returns.get(asset_id, {}).get(date_)
            if ret is not None:
                daily_rets.append(ret)
        if daily_rets:
            portfolio_returns.append(float(np.mean(daily_rets)))

    n_mtm_days = len(portfolio_returns)
    if n_mtm_days < 5:
        return None, n_mtm_days

    sharpe = _annualized_sharpe(portfolio_returns, 252.0)
    return sharpe, n_mtm_days


def _lookup_bt_sharpe(engine: Engine, strategy_name: str) -> float | None:
    """Look up cross-asset aggregate backtest Sharpe from strategy_bakeoff_results.

    Prefers CPCV cv_method; falls back to PKF.
    Computes AVG(sharpe_mean) across all asset_ids for the strategy.
    """
    sql = """
        SELECT AVG(sharpe_mean) AS sharpe_mean
        FROM strategy_bakeoff_results
        WHERE strategy_name = :strategy_name
          AND cv_method = :cv_method
          AND sharpe_mean IS NOT NULL
    """
    with engine.connect() as conn:
        for cv_method in ("CPCV", "PKF"):
            row = conn.execute(
                text(sql),
                {"strategy_name": strategy_name, "cv_method": cv_method},
            ).fetchone()
            if row and row.sharpe_mean is not None:
                logger.debug(
                    "BT Sharpe for %s (cv=%s): %.4f",
                    strategy_name,
                    cv_method,
                    float(row.sharpe_mean),
                )
                return float(row.sharpe_mean)
    return None


def _persist_parity(
    engine: Engine,
    strategy: str,
    window_days: int,
    live_sharpe_fill: float | None,
    live_sharpe_mtm: float | None,
    bt_sharpe: float | None,
    ratio_fill: float | None,
    ratio_mtm: float | None,
    n_fills: int,
    n_mtm_days: int,
) -> None:
    """Insert a row into strategy_parity table."""
    sql = """
        INSERT INTO strategy_parity
            (strategy, window_days, live_sharpe_fill, live_sharpe_mtm,
             bt_sharpe, ratio_fill, ratio_mtm, n_fills, n_mtm_days)
        VALUES
            (:strategy, :window_days, :live_sharpe_fill, :live_sharpe_mtm,
             :bt_sharpe, :ratio_fill, :ratio_mtm, :n_fills, :n_mtm_days)
    """
    with engine.begin() as conn:
        conn.execute(
            text(sql),
            {
                "strategy": strategy,
                "window_days": window_days,
                "live_sharpe_fill": live_sharpe_fill,
                "live_sharpe_mtm": live_sharpe_mtm,
                "bt_sharpe": bt_sharpe,
                "ratio_fill": ratio_fill,
                "ratio_mtm": ratio_mtm,
                "n_fills": n_fills,
                "n_mtm_days": n_mtm_days,
            },
        )


def _compute_ratio(live: float | None, bt: float | None) -> float | None:
    """Compute live/bt ratio safely."""
    if live is None or bt is None:
        return None
    if bt == 0.0:
        return None
    return round(live / bt, 4)


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------


def _fmt_sharpe(
    value: float | None, label: str, bt: float | None, ratio: float | None
) -> str:
    if value is None:
        return f"  {label:<22}: n/a"
    bt_str = f"BT: {bt:.2f}, " if bt is not None else ""
    ratio_str = f"ratio: {ratio:.2f}" if ratio is not None else "ratio: n/a"
    return f"  {label:<22}: {value:.2f} ({bt_str}{ratio_str})"


def _print_report(results: list[dict], window_days: int) -> None:
    """Print formatted parity report to console (ASCII only)."""
    print("=" * 60)
    print(f"STRATEGY PARITY REPORT ({window_days}-day window)")
    print("=" * 60)
    for r in results:
        print(f"Strategy: {r['config_name']}")
        # Fill-to-fill Sharpe line
        if r["n_fills"] < 2:
            print(f"  {'Fill-to-fill Sharpe':<22}: n/a (< 2 round-trips)")
        else:
            print(
                _fmt_sharpe(
                    r["live_sharpe_fill"],
                    "Fill-to-fill Sharpe",
                    r["bt_sharpe"],
                    r["ratio_fill"],
                )
            )
        # MTM Sharpe line
        if r["n_mtm_days"] < 5:
            print(
                f"  {'MTM daily Sharpe':<22}: n/a "
                f"(< 5 MTM days, have {r['n_mtm_days']})"
            )
        else:
            print(
                _fmt_sharpe(
                    r["live_sharpe_mtm"],
                    "MTM daily Sharpe",
                    r["bt_sharpe"],
                    r["ratio_mtm"],
                )
            )
        print(f"  {'Fills in window':<22}: {r['n_fills']}")
        print(f"  {'MTM days':<22}: {r['n_mtm_days']}")
        if r["bt_sharpe"] is None:
            print(f"  {'BT reference':<22}: no backtest reference found")
        print("---")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_parity_report",
        description=(
            "Strategy parity report: live Sharpe vs backtest Sharpe per strategy. "
            "Writes results to strategy_parity table."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--window",
        type=int,
        default=30,
        metavar="DAYS",
        help="Rolling window in days for Sharpe computation (default: 30).",
    )
    parser.add_argument(
        "--strategy",
        default=None,
        metavar="CONFIG_NAME",
        help="Filter to a single strategy config_name (optional).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print but do not write to DB.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (overrides TARGET_DB_URL env var).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Run parity report. Returns 0 on success, 1 on error."""
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        db_url = _resolve_db_url(args.db_url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    engine = create_engine(db_url, poolclass=NullPool)

    # Load active configs
    try:
        configs = _load_active_configs(engine, args.strategy)
    except Exception as exc:
        logger.exception("Failed to load executor configs")
        print(f"ERROR loading configs: {exc}", file=sys.stderr)
        return 1

    if not configs:
        if args.strategy:
            print(f"No active executor config found for strategy '{args.strategy}'.")
        else:
            print("No active executor configs found in dim_executor_config.")
        return 0

    now_utc = datetime.now(tz=timezone.utc)
    from datetime import timedelta

    window_start = now_utc - timedelta(days=args.window)

    results: list[dict] = []

    for cfg in configs:
        config_name = cfg["config_name"]
        signal_id = cfg["signal_id"]
        strategy_name = _extract_strategy_name(config_name)

        logger.info(
            "Computing parity for config=%s (signal_id=%d)", config_name, signal_id
        )

        # Fill-to-fill Sharpe
        try:
            live_sharpe_fill, n_fills = _compute_fill_to_fill_sharpe(
                engine, signal_id, window_start
            )
        except Exception as exc:
            logger.warning("Fill-to-fill Sharpe failed for %s: %s", config_name, exc)
            live_sharpe_fill, n_fills = None, 0

        # MTM daily Sharpe
        try:
            live_sharpe_mtm, n_mtm_days = _compute_mtm_daily_sharpe(
                engine, signal_id, window_start, now_utc
            )
        except Exception as exc:
            logger.warning("MTM Sharpe failed for %s: %s", config_name, exc)
            live_sharpe_mtm, n_mtm_days = None, 0

        # Backtest reference
        try:
            bt_sharpe = _lookup_bt_sharpe(engine, strategy_name)
        except Exception as exc:
            logger.warning("BT Sharpe lookup failed for %s: %s", strategy_name, exc)
            bt_sharpe = None

        # Ratios
        ratio_fill = _compute_ratio(live_sharpe_fill, bt_sharpe)
        ratio_mtm = _compute_ratio(live_sharpe_mtm, bt_sharpe)

        result = {
            "config_name": config_name,
            "signal_id": signal_id,
            "live_sharpe_fill": live_sharpe_fill,
            "live_sharpe_mtm": live_sharpe_mtm,
            "bt_sharpe": bt_sharpe,
            "ratio_fill": ratio_fill,
            "ratio_mtm": ratio_mtm,
            "n_fills": n_fills,
            "n_mtm_days": n_mtm_days,
        }
        results.append(result)

        # Persist
        if not args.dry_run:
            try:
                _persist_parity(
                    engine=engine,
                    strategy=config_name,
                    window_days=args.window,
                    live_sharpe_fill=live_sharpe_fill,
                    live_sharpe_mtm=live_sharpe_mtm,
                    bt_sharpe=bt_sharpe,
                    ratio_fill=ratio_fill,
                    ratio_mtm=ratio_mtm,
                    n_fills=n_fills,
                    n_mtm_days=n_mtm_days,
                )
                logger.debug("Persisted parity row for %s", config_name)
            except Exception as exc:
                logger.error("Failed to persist parity for %s: %s", config_name, exc)

    _print_report(results, args.window)

    if args.dry_run:
        print("[dry-run] No rows written to strategy_parity.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
