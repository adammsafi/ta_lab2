#!/usr/bin/env python
"""
PnL attribution report: separate alpha from multi-asset-class beta.

Decomposes portfolio PnL into systematic (beta) and idiosyncratic (alpha)
components per asset class, using OLS beta vs per-class benchmarks.

Usage:
    python -m ta_lab2.scripts.executor.run_pnl_attribution
    python -m ta_lab2.scripts.executor.run_pnl_attribution --period 30
    python -m ta_lab2.scripts.executor.run_pnl_attribution --start 2026-03-01 --end 2026-03-30
    python -m ta_lab2.scripts.executor.run_pnl_attribution --dry-run
    python -m ta_lab2.scripts.executor.run_pnl_attribution --verbose

Tables written: pnl_attribution

Asset class benchmarks:
  - crypto (spot): BTC (asset_id=1 in price_bars_multi_tf_u)
  - perp (perpetual futures): BTC (underlying spot; extensible for Phase 97)
  - all (blended portfolio): BTC
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# BTC asset_id in price_bars_multi_tf_u (primary benchmark for crypto + perp)
_BTC_ASSET_ID = 1
_BTC_BENCHMARK_LABEL = "BTC"

# Asset class -> benchmark label mapping (extensible for Phase 97 equities)
_BENCHMARK_MAP: dict[str, str] = {
    "crypto": _BTC_BENCHMARK_LABEL,
    "perp": _BTC_BENCHMARK_LABEL,
    "all": _BTC_BENCHMARK_LABEL,
}

# Asset class -> benchmark asset_id mapping
_BENCHMARK_ASSET_ID: dict[str, int] = {
    "crypto": _BTC_ASSET_ID,
    "perp": _BTC_ASSET_ID,
    "all": _BTC_ASSET_ID,
}


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
# Data structures
# ---------------------------------------------------------------------------


class AssetClassResult(NamedTuple):
    asset_class: str
    benchmark: str
    total_pnl: float | None
    beta_pnl: float | None
    alpha_pnl: float | None
    beta: float | None
    sharpe_alpha: float | None
    n_positions: int


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_fills_in_period(engine: Engine, start: datetime, end: datetime) -> list[dict]:
    """Load all fills and associated asset_ids in the period."""
    sql = """
        SELECT DISTINCT o.asset_id, o.signal_id,
               f.fill_price, f.fill_qty, f.side, f.filled_at
        FROM fills f
        JOIN orders o ON f.order_id = o.order_id
        WHERE f.filled_at BETWEEN :start AND :end
        ORDER BY o.asset_id, f.filled_at
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"start": start, "end": end}).fetchall()

    return [
        {
            "asset_id": r.asset_id,
            "signal_id": r.signal_id,
            "fill_price": float(r.fill_price),
            "fill_qty": float(r.fill_qty),
            "side": r.side,
            "filled_at": r.filled_at,
        }
        for r in rows
    ]


def _load_daily_prices(
    engine: Engine, asset_ids: list[int], start: datetime, end: datetime
) -> dict[int, list[tuple[date, float]]]:
    """Load daily close prices for asset_ids from price_bars_multi_tf_u.

    Returns {asset_id: [(date, close), ...]} sorted by date.
    """
    if not asset_ids:
        return {}

    sql = """
        SELECT id AS asset_id, ts::date AS trade_date, close
        FROM price_bars_multi_tf_u
        WHERE id = ANY(:asset_ids)
          AND tf = '1d'
          AND alignment_source = 'multi_tf'
          AND ts BETWEEN :start AND :end
        ORDER BY id, ts
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(sql),
            {"asset_ids": asset_ids, "start": start, "end": end},
        ).fetchall()

    result: dict[int, list[tuple[date, float]]] = defaultdict(list)
    for r in rows:
        result[r.asset_id].append((r.trade_date, float(r.close)))

    # Sort by date
    for asset_id in result:
        result[asset_id].sort(key=lambda x: x[0])

    return dict(result)


def _classify_asset(engine: Engine, asset_id: int) -> str:
    """Classify an asset_id into an asset class.

    Returns: 'perp' for Hyperliquid perps, 'crypto' for everything else.
    """
    sql = """
        SELECT asset_type
        FROM hyperliquid.hl_assets
        WHERE asset_id = :asset_id
        LIMIT 1
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(text(sql), {"asset_id": asset_id}).fetchone()
        if row and row.asset_type == "perp":
            return "perp"
    except Exception as exc:
        logger.debug("hl_assets lookup failed for asset_id=%d: %s", asset_id, exc)

    return "crypto"


def _classify_assets_bulk(engine: Engine, asset_ids: list[int]) -> dict[int, str]:
    """Bulk classify asset_ids into asset classes."""
    if not asset_ids:
        return {}

    sql = """
        SELECT asset_id, asset_type
        FROM hyperliquid.hl_assets
        WHERE asset_id = ANY(:asset_ids)
    """
    perp_ids: set[int] = set()
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), {"asset_ids": asset_ids}).fetchall()
        for r in rows:
            if r.asset_type == "perp":
                perp_ids.add(r.asset_id)
    except Exception as exc:
        logger.debug("hl_assets bulk lookup failed: %s", exc)

    return {aid: ("perp" if aid in perp_ids else "crypto") for aid in asset_ids}


# ---------------------------------------------------------------------------
# Daily return computation
# ---------------------------------------------------------------------------


def _compute_daily_returns(
    prices: list[tuple[date, float]],
) -> list[tuple[date, float]]:
    """Compute daily returns from price series.

    Returns [(date, return), ...] starting from day 1.
    """
    if len(prices) < 2:
        return []
    returns = []
    for i in range(1, len(prices)):
        prev_price = prices[i - 1][1]
        curr_date = prices[i][0]
        curr_price = prices[i][1]
        if prev_price > 0:
            ret = (curr_price - prev_price) / prev_price
            returns.append((curr_date, ret))
    return returns


def _compute_portfolio_daily_returns(
    asset_ids: list[int],
    price_data: dict[int, list[tuple[date, float]]],
) -> list[tuple[date, float]]:
    """Compute equal-weight portfolio daily returns across asset_ids.

    Uses only dates where at least one asset has return data.
    Returns [(date, portfolio_return), ...] sorted by date.
    """
    all_dates: set[date] = set()
    asset_ret_map: dict[int, dict[date, float]] = {}

    for asset_id in asset_ids:
        prices = price_data.get(asset_id, [])
        daily_rets = _compute_daily_returns(prices)
        if daily_rets:
            asset_ret_map[asset_id] = dict(daily_rets)
            all_dates.update(d for d, _ in daily_rets)

    if not all_dates:
        return []

    portfolio_returns = []
    for trade_date in sorted(all_dates):
        day_rets = []
        for asset_id in asset_ids:
            ret = asset_ret_map.get(asset_id, {}).get(trade_date)
            if ret is not None:
                day_rets.append(ret)
        if day_rets:
            portfolio_returns.append((trade_date, float(np.mean(day_rets))))

    return portfolio_returns


# ---------------------------------------------------------------------------
# OLS beta and attribution
# ---------------------------------------------------------------------------


def _compute_beta(
    portfolio_returns: list[float], benchmark_returns: list[float]
) -> float | None:
    """Compute OLS beta of portfolio vs benchmark.

    Returns None if benchmark variance is zero or inputs are too short.
    """
    if len(portfolio_returns) < 2 or len(benchmark_returns) < 2:
        return None

    port = np.array(portfolio_returns, dtype=float)
    bench = np.array(benchmark_returns, dtype=float)

    bench_var = float(np.var(bench))
    if bench_var == 0.0:
        return None

    cov_matrix = np.cov(port, bench)
    beta = float(cov_matrix[0, 1] / bench_var)
    return beta


def _compute_sharpe(returns: list[float]) -> float | None:
    """Compute annualized Sharpe ratio (252-day basis)."""
    if len(returns) < 2:
        return None
    arr = np.array(returns, dtype=float)
    std = float(np.std(arr, ddof=1))
    if std == 0.0:
        return None
    return float(np.mean(arr) / std * np.sqrt(252.0))


def _align_returns_by_date(
    series_a: list[tuple[date, float]],
    series_b: list[tuple[date, float]],
) -> tuple[list[float], list[float]]:
    """Align two date-indexed return series on common dates."""
    dict_a = dict(series_a)
    dict_b = dict(series_b)
    common_dates = sorted(set(dict_a) & set(dict_b))
    return (
        [dict_a[d] for d in common_dates],
        [dict_b[d] for d in common_dates],
    )


# ---------------------------------------------------------------------------
# Per-asset-class attribution
# ---------------------------------------------------------------------------


def _compute_class_attribution(
    asset_class: str,
    asset_ids: list[int],
    price_data: dict[int, list[tuple[date, float]]],
    benchmark_returns_dated: list[tuple[date, float]],
    n_positions: int,
) -> AssetClassResult:
    """Compute beta-adjusted PnL attribution for one asset class."""
    benchmark_label = _BENCHMARK_MAP.get(asset_class, _BTC_BENCHMARK_LABEL)

    if not asset_ids:
        return AssetClassResult(
            asset_class=asset_class,
            benchmark=benchmark_label,
            total_pnl=None,
            beta_pnl=None,
            alpha_pnl=None,
            beta=None,
            sharpe_alpha=None,
            n_positions=0,
        )

    # Portfolio daily returns
    portfolio_dated = _compute_portfolio_daily_returns(asset_ids, price_data)

    if not portfolio_dated:
        logger.warning("No portfolio returns for asset_class=%s", asset_class)
        return AssetClassResult(
            asset_class=asset_class,
            benchmark=benchmark_label,
            total_pnl=None,
            beta_pnl=None,
            alpha_pnl=None,
            beta=None,
            sharpe_alpha=None,
            n_positions=n_positions,
        )

    # Align portfolio and benchmark returns on common dates
    port_rets, bench_rets = _align_returns_by_date(
        portfolio_dated, benchmark_returns_dated
    )

    if not port_rets:
        logger.warning(
            "No common dates between portfolio and benchmark for asset_class=%s",
            asset_class,
        )
        return AssetClassResult(
            asset_class=asset_class,
            benchmark=benchmark_label,
            total_pnl=None,
            beta_pnl=None,
            alpha_pnl=None,
            beta=None,
            sharpe_alpha=None,
            n_positions=n_positions,
        )

    # Total PnL as cumulative sum of portfolio returns (in pct terms)
    total_pnl = float(np.sum(port_rets))
    benchmark_total = float(np.sum(bench_rets))

    # OLS beta
    beta = _compute_beta(port_rets, bench_rets)

    # Beta and alpha PnL decomposition
    if beta is not None:
        beta_pnl = beta * benchmark_total
        alpha_pnl = total_pnl - beta_pnl
        # Alpha daily returns: residual after removing beta*benchmark contribution
        alpha_daily = [p - beta * b for p, b in zip(port_rets, bench_rets)]
        sharpe_alpha = _compute_sharpe(alpha_daily)
    else:
        logger.warning(
            "Zero benchmark variance for asset_class=%s; alpha = total_pnl",
            asset_class,
        )
        beta_pnl = None
        alpha_pnl = total_pnl
        sharpe_alpha = _compute_sharpe(port_rets)

    return AssetClassResult(
        asset_class=asset_class,
        benchmark=benchmark_label,
        total_pnl=round(total_pnl, 6),
        beta_pnl=round(beta_pnl, 6) if beta_pnl is not None else None,
        alpha_pnl=round(alpha_pnl, 6) if alpha_pnl is not None else None,
        beta=round(beta, 4) if beta is not None else None,
        sharpe_alpha=round(sharpe_alpha, 4) if sharpe_alpha is not None else None,
        n_positions=n_positions,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist_attribution(
    engine: Engine,
    period_start: date,
    period_end: date,
    result: AssetClassResult,
) -> None:
    """Insert one row into pnl_attribution table."""
    sql = """
        INSERT INTO pnl_attribution
            (period_start, period_end, asset_class, benchmark,
             total_pnl, beta_pnl, alpha_pnl, beta, sharpe_alpha, n_positions)
        VALUES
            (:period_start, :period_end, :asset_class, :benchmark,
             :total_pnl, :beta_pnl, :alpha_pnl, :beta, :sharpe_alpha, :n_positions)
    """
    with engine.begin() as conn:
        conn.execute(
            text(sql),
            {
                "period_start": period_start,
                "period_end": period_end,
                "asset_class": result.asset_class,
                "benchmark": result.benchmark,
                "total_pnl": result.total_pnl,
                "beta_pnl": result.beta_pnl,
                "alpha_pnl": result.alpha_pnl,
                "beta": result.beta,
                "sharpe_alpha": result.sharpe_alpha,
                "n_positions": result.n_positions,
            },
        )


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.2f}%"


def _fmt_float(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{decimals}f}"


def _print_report(
    results: list[AssetClassResult],
    period_start: date,
    period_end: date,
) -> None:
    """Print formatted PnL attribution report to console (ASCII only)."""
    print("=" * 60)
    print(
        f"PNL ATTRIBUTION REPORT "
        f"({period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')})"
    )
    print("=" * 60)

    blended: AssetClassResult | None = None

    for r in results:
        if r.asset_class == "all":
            blended = r
            continue

        print(f"Asset Class: {r.asset_class} (benchmark: {r.benchmark})")
        print(f"  {'Positions':<18}: {r.n_positions}")
        print(f"  {'Total PnL':<18}: {_fmt_pct(r.total_pnl)}")
        print(f"  {'Beta':<18}: {_fmt_float(r.beta, 4)}")
        print(f"  {'Beta PnL':<18}: {_fmt_pct(r.beta_pnl)}")
        print(f"  {'Alpha PnL':<18}: {_fmt_pct(r.alpha_pnl)}")
        print(f"  {'Alpha Sharpe':<18}: {_fmt_float(r.sharpe_alpha, 4)}")
        print("---")

    if blended:
        print("BLENDED PORTFOLIO")
        print(f"  {'Positions':<18}: {blended.n_positions}")
        print(f"  {'Total PnL':<18}: {_fmt_pct(blended.total_pnl)}")
        print(f"  {'Beta PnL':<18}: {_fmt_pct(blended.beta_pnl)}")
        print(f"  {'Alpha PnL':<18}: {_fmt_pct(blended.alpha_pnl)}")
        print(f"  {'Alpha Sharpe':<18}: {_fmt_float(blended.sharpe_alpha, 4)}")
        print("---")

    print("=" * 60)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_pnl_attribution",
        description=(
            "PnL attribution report: decomposes portfolio PnL into alpha and "
            "multi-asset-class beta components. Writes results to pnl_attribution table."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--period",
        type=int,
        default=30,
        metavar="DAYS",
        help="Lookback in days from today (default: 30). Ignored if --start/--end given.",
    )
    parser.add_argument(
        "--start",
        default=None,
        metavar="YYYY-MM-DD",
        help="Period start date (inclusive). Overrides --period.",
    )
    parser.add_argument(
        "--end",
        default=None,
        metavar="YYYY-MM-DD",
        help="Period end date (inclusive). Overrides --period.",
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
    """Run PnL attribution report. Returns 0 on success, 1 on error."""
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

    # Resolve period
    today = datetime.now(tz=timezone.utc)
    if args.start and args.end:
        try:
            period_start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            period_end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError as exc:
            print(f"ERROR: Invalid date format: {exc}", file=sys.stderr)
            return 1
    else:
        period_end_dt = today
        period_start_dt = today - timedelta(days=args.period)

    period_start_date = period_start_dt.date()
    period_end_date = period_end_dt.date()

    engine = create_engine(db_url, poolclass=NullPool)

    # Load all fills in the period
    try:
        fills = _load_fills_in_period(engine, period_start_dt, period_end_dt)
    except Exception as exc:
        logger.exception("Failed to load fills")
        print(f"ERROR loading fills: {exc}", file=sys.stderr)
        return 1

    if not fills:
        print(
            f"No fills in period "
            f"({period_start_date} to {period_end_date}). "
            "Skipping attribution (no data to process)."
        )
        return 0

    # Unique asset_ids with positions
    all_asset_ids = list({f["asset_id"] for f in fills})
    n_total_positions = len(all_asset_ids)

    logger.info(
        "Found %d fills across %d unique assets in period %s to %s",
        len(fills),
        n_total_positions,
        period_start_date,
        period_end_date,
    )

    # Classify assets by class
    asset_class_map = _classify_assets_bulk(engine, all_asset_ids)

    # Group asset_ids by class
    assets_by_class: dict[str, list[int]] = defaultdict(list)
    for asset_id, asset_class in asset_class_map.items():
        assets_by_class[asset_class].append(asset_id)

    # Load price data for all assets + BTC benchmark
    price_asset_ids = list(set(all_asset_ids) | {_BTC_ASSET_ID})
    try:
        price_data = _load_daily_prices(
            engine, price_asset_ids, period_start_dt, period_end_dt
        )
    except Exception as exc:
        logger.exception("Failed to load price data")
        print(f"ERROR loading price data: {exc}", file=sys.stderr)
        return 1

    # Compute benchmark returns (BTC)
    btc_prices = price_data.get(_BTC_ASSET_ID, [])
    btc_returns_dated = _compute_daily_returns(btc_prices)
    if not btc_returns_dated:
        logger.warning(
            "No BTC price data available for benchmark (asset_id=%d). "
            "Attribution results will have beta=None.",
            _BTC_ASSET_ID,
        )

    # Compute per-class attribution
    results: list[AssetClassResult] = []

    for asset_class in sorted(assets_by_class.keys()):
        class_asset_ids = assets_by_class[asset_class]
        n_pos = len(class_asset_ids)
        logger.info(
            "Computing attribution for asset_class=%s (%d assets)",
            asset_class,
            n_pos,
        )

        result = _compute_class_attribution(
            asset_class=asset_class,
            asset_ids=class_asset_ids,
            price_data=price_data,
            benchmark_returns_dated=btc_returns_dated,
            n_positions=n_pos,
        )
        results.append(result)

    # Compute blended portfolio ("all" asset class)
    blended = _compute_class_attribution(
        asset_class="all",
        asset_ids=all_asset_ids,
        price_data=price_data,
        benchmark_returns_dated=btc_returns_dated,
        n_positions=n_total_positions,
    )
    blended = blended._replace(benchmark=_BENCHMARK_MAP["all"])
    results.append(blended)

    # Print report
    _print_report(results, period_start_date, period_end_date)

    # Persist to DB
    if not args.dry_run:
        persisted_count = 0
        for r in results:
            try:
                _persist_attribution(engine, period_start_date, period_end_date, r)
                persisted_count += 1
                logger.debug(
                    "Persisted pnl_attribution row for asset_class=%s", r.asset_class
                )
            except Exception as exc:
                logger.error(
                    "Failed to persist attribution for asset_class=%s: %s",
                    r.asset_class,
                    exc,
                )
        logger.info(
            "Persisted %d/%d attribution rows to pnl_attribution",
            persisted_count,
            len(results),
        )
    else:
        print("[dry-run] No rows written to pnl_attribution.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
