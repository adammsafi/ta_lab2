#!/usr/bin/env python
"""
Backtest parity verification report.

Compares paper executor replay fills against stored backtest results.
Prerequisite: Run executor in replay mode first:
    python -m ta_lab2.scripts.executor.run_paper_executor --replay-historical \\
        --start 2024-01-01 --end 2025-01-01

Usage:
    python -m ta_lab2.scripts.executor.run_parity_check \\
        --signal-id 1 --start 2024-01-01 --end 2025-01-01

    python -m ta_lab2.scripts.executor.run_parity_check \\
        --signal-id 1 --start 2024-01-01 --end 2025-01-01 --verbose

    # Auto-discover winning strategies from bake-off results
    python -m ta_lab2.scripts.executor.run_parity_check \\
        --bakeoff-winners --start 2024-01-01 --end 2025-01-01

    # Phase 88 burn-in: softer correlation gate (0.90)
    python -m ta_lab2.scripts.executor.run_parity_check \\
        --bakeoff-winners --start 2024-01-01 --end 2025-01-01 \\
        --pnl-correlation-threshold 0.90

Exit codes:
    0  Parity check PASSED
    1  Parity check FAILED (or error)
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from ta_lab2.executor.parity_checker import ParityChecker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strategy name -> signal_type mapping (Phase 83 decision)
# AMA strategies reuse the EMA signal lifecycle in dim_signals.
# ---------------------------------------------------------------------------
_STRATEGY_SIGNAL_MAP: dict[str, str] = {
    "ama_momentum": "ema_crossover",
    "ama_mean_reversion": "ema_crossover",
    "ama_regime_conditional": "ema_crossover",
    "ema_trend": "ema_crossover",
    "macd_crossover": "ema_crossover",
    "rsi_mean_revert": "rsi_mean_revert",
    "breakout_atr": "atr_breakout",
}


def _resolve_db_url(db_url: str | None) -> str:
    """Resolve database URL from argument or environment."""
    if db_url:
        return db_url

    import os

    url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url

    # Try reading from db_config.env
    config_path = "db_config.env"
    if os.path.exists(config_path):
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("TARGET_DB_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    raise ValueError(
        "Database URL not found. Provide --db-url or set TARGET_DB_URL env var."
    )


def _discover_bakeoff_winners(engine: Engine) -> list[dict]:
    """
    Auto-discover winning strategies from strategy_bakeoff_results.

    Ranks by sharpe_mean (DESC) per (strategy_name, asset_id) and takes
    top-1 row.  Prefers CPCV cv_method; falls back to PKF if no CPCV rows.

    Then resolves signal_id from dim_signals via _STRATEGY_SIGNAL_MAP.

    Returns
    -------
    list of dicts with keys:
        strategy_name, asset_id, tf, sharpe_mean, signal_id
    """
    # SQL: rank by sharpe_mean per (strategy_name, asset_id) using CPCV first
    _WINNER_SQL = """
        WITH ranked AS (
            SELECT
                strategy_name,
                asset_id,
                tf,
                sharpe_mean,
                ROW_NUMBER() OVER (
                    PARTITION BY strategy_name, asset_id
                    ORDER BY sharpe_mean DESC
                ) AS rn
            FROM strategy_bakeoff_results
            WHERE cv_method = :cv_method
              AND sharpe_mean IS NOT NULL
        )
        SELECT strategy_name, asset_id, tf, sharpe_mean
        FROM ranked
        WHERE rn = 1
        ORDER BY strategy_name, asset_id
    """

    _SIGNAL_LOOKUP_SQL = """
        SELECT signal_id
        FROM dim_signals
        WHERE signal_type = :signal_type
        LIMIT 1
    """

    winners: list[dict] = []

    with engine.connect() as conn:
        # Try CPCV first, fall back to PKF
        for cv_method in ("CPCV", "PKF"):
            rows = conn.execute(text(_WINNER_SQL), {"cv_method": cv_method}).fetchall()
            if rows:
                logger.info(
                    "Discovered %d bakeoff winners using cv_method=%s",
                    len(rows),
                    cv_method,
                )
                break
        else:
            rows = []

        # Resolve signal_id for each winner row
        signal_id_cache: dict[str, int | None] = {}
        for row in rows:
            strategy_name = row.strategy_name
            asset_id = row.asset_id
            tf = row.tf
            sharpe_mean = float(row.sharpe_mean)

            signal_type = _STRATEGY_SIGNAL_MAP.get(strategy_name)
            if signal_type is None:
                # Fallback: try strategy_name as signal_type directly
                signal_type = strategy_name
                logger.info(
                    "No explicit mapping for strategy=%s -- trying as signal_type",
                    strategy_name,
                )

            # Cache lookup to avoid duplicate queries for the same signal_type
            if signal_type not in signal_id_cache:
                signal_row = conn.execute(
                    text(_SIGNAL_LOOKUP_SQL), {"signal_type": signal_type}
                ).fetchone()
                signal_id_cache[signal_type] = (
                    signal_row.signal_id if signal_row else None
                )

            signal_id = signal_id_cache[signal_type]
            if signal_id is None:
                logger.warning(
                    "No signal found in dim_signals for signal_type=%s "
                    "(strategy=%s) -- skipping",
                    signal_type,
                    strategy_name,
                )
                continue

            winners.append(
                {
                    "strategy_name": strategy_name,
                    "asset_id": asset_id,
                    "tf": tf,
                    "sharpe_mean": sharpe_mean,
                    "signal_id": signal_id,
                }
            )

    return winners


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_parity_check",
        description=(
            "Backtest parity verification: compare executor replay fills "
            "against stored backtest trades."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--signal-id",
        type=int,
        required=False,
        default=None,
        help=(
            "Signal ID to compare (must match backtest_runs.signal_id). "
            "Required unless --bakeoff-winners is used."
        ),
    )
    parser.add_argument(
        "--bakeoff-winners",
        action="store_true",
        help=(
            "Auto-discover winning strategies from strategy_bakeoff_results "
            "and run parity checks for each.  When used, --signal-id is optional."
        ),
    )
    parser.add_argument(
        "--config-id",
        type=int,
        default=None,
        help="Executor config ID (optional; used for labelling only).",
    )
    parser.add_argument(
        "--start",
        required=True,
        metavar="DATE",
        help="Start date inclusive (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end",
        required=True,
        metavar="DATE",
        help="End date inclusive (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--slippage-mode",
        default="zero",
        choices=["zero", "fixed", "lognormal"],
        help=(
            "Expected slippage mode. 'zero' requires exact fill price match "
            "(<1 bps); 'fixed'/'lognormal' requires P&L correlation >= threshold. "
            "Default: zero (or 'fixed' when --bakeoff-winners is used)."
        ),
    )
    parser.add_argument(
        "--pnl-correlation-threshold",
        type=float,
        default=0.99,
        metavar="FLOAT",
        help=(
            "Minimum P&L correlation for PASS in fixed/lognormal modes. "
            "Default: 0.99. Phase 88 burn-in uses 0.90."
        ),
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (overrides TARGET_DB_URL env var).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-trade price comparison detail.",
    )
    return parser


def _print_verbose_comparison(
    bt_trades: list[dict],
    exec_fills: list[dict],
) -> None:
    """Print per-trade price comparison table."""
    if not bt_trades or not exec_fills:
        print("\n[verbose] No trade data to compare.")
        return

    print("\n[verbose] Per-trade price comparison:")
    header = f"{'#':>4}  {'BT Entry Price':>16}  {'Exec Fill Price':>16}  {'Divergence (bps)':>18}"
    print(header)
    print("-" * len(header))

    for i, (bt, ex) in enumerate(zip(bt_trades, exec_fills), start=1):
        bt_price = float(bt.get("entry_price") or 0)
        ex_price = float(ex.get("fill_price") or 0)
        if bt_price > 0:
            bps = abs(ex_price - bt_price) / bt_price * 10_000
        else:
            bps = float("nan")
        print(f"{i:>4}  {bt_price:>16.4f}  {ex_price:>16.4f}  {bps:>18.4f}")


def main() -> int:
    """Run parity check. Returns 0 on PASS, 1 on FAIL."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args()

    # Validate: either --signal-id or --bakeoff-winners must be provided
    if not args.bakeoff_winners and args.signal_id is None:
        print(
            "ERROR: --signal-id is required unless --bakeoff-winners is used.",
            file=sys.stderr,
        )
        parser.print_usage(sys.stderr)
        return 1

    try:
        db_url = _resolve_db_url(args.db_url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    engine = create_engine(db_url, poolclass=NullPool)
    checker = ParityChecker(engine)

    # ------------------------------------------------------------------
    # Bakeoff-winners path: auto-discover strategies and run multi-signal
    # parity loop
    # ------------------------------------------------------------------
    if args.bakeoff_winners:
        # Default to 'fixed' for bakeoff winners (historical replay has fill
        # price differences; direction and timing are what matters)
        slippage_mode = args.slippage_mode
        if slippage_mode == "zero":
            # User did not override default -- switch to 'fixed' for bakeoff
            slippage_mode = "fixed"

        try:
            winners = _discover_bakeoff_winners(engine)
        except Exception as exc:
            logger.exception("Failed to discover bakeoff winners")
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        if not winners:
            print(
                "No bakeoff winners found in strategy_bakeoff_results. "
                "Run Phase 82 bake-off sweep first."
            )
            return 1

        print(
            f"\nDiscovered {len(winners)} bakeoff winner(s). "
            f"Slippage mode: {slippage_mode}\n"
        )

        passed = 0
        failed = 0
        for winner in winners:
            strategy_name = winner["strategy_name"]
            signal_id = winner["signal_id"]
            asset_id = winner["asset_id"]
            sharpe_mean = winner["sharpe_mean"]

            print(
                f"\n--- Parity check: strategy={strategy_name} "
                f"asset_id={asset_id} signal_id={signal_id} "
                f"sharpe_mean={sharpe_mean:.3f} ---"
            )

            # Warn when no backtest_trades exist for this signal_id
            # (Phase 82 bake-off writes to strategy_bakeoff_results, not
            # backtest_trades; parity will correctly report 0 backtest trades)
            try:
                report = checker.check(
                    config_id=args.config_id,
                    signal_id=signal_id,
                    start_date=args.start,
                    end_date=args.end,
                    slippage_mode=slippage_mode,
                    pnl_correlation_threshold=args.pnl_correlation_threshold,
                )
            except Exception as exc:
                logger.exception(
                    "Parity check error for signal_id=%s strategy=%s",
                    signal_id,
                    strategy_name,
                )
                print(f"ERROR: {exc}", file=sys.stderr)
                failed += 1
                continue

            if report.get("backtest_trade_count", 0) == 0:
                print(
                    f"[WARN] No backtest trades found for signal_id={signal_id} "
                    f"(strategy={strategy_name}). "
                    "Phase 82 bake-off results are in strategy_bakeoff_results, "
                    "not backtest_trades. A backtest run linking step may be needed."
                )

            print(checker.format_report(report))

            if args.verbose:
                try:
                    bt_trades = checker._load_backtest_trades(
                        signal_id, args.start, args.end
                    )
                    exec_fills = checker._load_executor_fills(
                        signal_id, args.start, args.end
                    )
                    _print_verbose_comparison(bt_trades, exec_fills)
                except Exception as exc:
                    logger.warning(
                        "Could not load per-trade data for verbose output: %s", exc
                    )

            if report.get("parity_pass"):
                passed += 1
            else:
                failed += 1

        total = passed + failed
        print(f"\n{'=' * 50}")
        print(f"BAKEOFF PARITY SUMMARY: {passed}/{total} signals passed parity")
        print(f"{'=' * 50}")

        return 0 if failed == 0 else 1

    # ------------------------------------------------------------------
    # Single signal-id path (original behavior -- unchanged)
    # ------------------------------------------------------------------
    try:
        report = checker.check(
            config_id=args.config_id,
            signal_id=args.signal_id,
            start_date=args.start,
            end_date=args.end,
            slippage_mode=args.slippage_mode,
            pnl_correlation_threshold=args.pnl_correlation_threshold,
        )
    except Exception as exc:
        logger.exception("Parity check failed with error")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Print formatted report
    print(checker.format_report(report))

    # Verbose: per-trade comparison
    if args.verbose:
        try:
            bt_trades = checker._load_backtest_trades(
                args.signal_id, args.start, args.end
            )
            exec_fills = checker._load_executor_fills(
                args.signal_id, args.start, args.end
            )
            _print_verbose_comparison(bt_trades, exec_fills)
        except Exception as exc:
            logger.warning("Could not load per-trade data for verbose output: %s", exc)

    return 0 if report.get("parity_pass") else 1


if __name__ == "__main__":
    sys.exit(main())
