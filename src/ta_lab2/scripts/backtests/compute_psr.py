"""
Standalone CLI for computing/recomputing PSR on historical backtest runs.

Uses trade-reconstructed returns (per-bar approximation) rather than the
portfolio-level returns available during online computation in backtest_from_signals.py.
The return_source column in psr_results distinguishes the two paths:
  - 'portfolio'            : pf.returns() during backtest execution (exact, fees-aware)
  - 'trade_reconstruction' : approximation from cmc_backtest_trades (this script)

Usage:
    # Single run
    python -m ta_lab2.scripts.backtests.compute_psr --run-id <UUID>

    # All runs without a psr_results row
    python -m ta_lab2.scripts.backtests.compute_psr --all

    # Force recompute even if psr_results row exists
    python -m ta_lab2.scripts.backtests.compute_psr --all --recompute

    # Dry-run (no writes)
    python -m ta_lab2.scripts.backtests.compute_psr --all --dry-run

    # Custom benchmark Sharpe (annualised, converted internally to per-bar)
    python -m ta_lab2.scripts.backtests.compute_psr --all --sr-star 1.0
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from typing import Optional

import pandas as pd
from scipy.stats import kurtosis, skew
from sqlalchemy import create_engine, pool, text

from ta_lab2.backtests.psr import compute_psr, min_trl
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Return reconstruction
# ─────────────────────────────────────────────────────────────────────────────


def reconstruct_bar_returns(
    bar_timestamps: pd.DatetimeIndex,
    trades_df: pd.DataFrame,
) -> pd.Series:
    """
    Build a bar-level return series from trade records.

    For each bar, returns 0.0 when not in a trade and an equal-distributed
    fraction of the total trade pnl_pct when inside a trade window.

    This is an approximation: it distributes trade P&L evenly across holding
    bars, unlike portfolio-level returns which account for exact position sizing
    and per-bar fee deductions.

    Args:
        bar_timestamps: DatetimeIndex of all trading bars in the backtest window.
        trades_df: DataFrame with columns entry_ts, exit_ts, pnl_pct.

    Returns:
        pd.Series indexed by bar_timestamps with per-bar return fractions.
    """
    returns = pd.Series(0.0, index=bar_timestamps)

    for _, trade in trades_df.iterrows():
        entry_ts = pd.Timestamp(trade["entry_ts"])
        exit_ts = (
            pd.Timestamp(trade["exit_ts"]) if pd.notna(trade.get("exit_ts")) else None
        )
        pnl_pct = trade.get("pnl_pct")

        if pnl_pct is None or (isinstance(pnl_pct, float) and math.isnan(pnl_pct)):
            continue

        # Normalize to tz-naive UTC for index alignment
        if hasattr(entry_ts, "tz") and entry_ts.tz is not None:
            entry_ts = entry_ts.tz_convert("UTC").replace(tzinfo=None)
        if exit_ts is not None and hasattr(exit_ts, "tz") and exit_ts.tz is not None:
            exit_ts = exit_ts.tz_convert("UTC").replace(tzinfo=None)

        if exit_ts is None:
            # Open position: skip (no completed P&L)
            continue

        mask = (bar_timestamps >= entry_ts) & (bar_timestamps <= exit_ts)
        n_holding_bars = int(mask.sum())

        if n_holding_bars > 0:
            # pnl_pct stored as percentage in DB; keep as % throughout for consistency
            per_bar_ret = float(pnl_pct) / n_holding_bars
            returns.loc[mask] = per_bar_ret

    return returns


# ─────────────────────────────────────────────────────────────────────────────
# Per-run PSR computation
# ─────────────────────────────────────────────────────────────────────────────


def compute_psr_for_run(
    conn,
    run_id: str,
    sr_star_annual: float = 0.0,
    dry_run: bool = False,
) -> Optional[float]:
    """
    Compute and persist PSR for a single backtest run using trade-reconstructed returns.

    Args:
        conn: SQLAlchemy connection (within a transaction).
        run_id: UUID string of the backtest run.
        sr_star_annual: Annualised benchmark Sharpe ratio (converted to per-bar internally).
        dry_run: If True, compute but do not write to DB.

    Returns:
        PSR value, or None if the run could not be processed (no trades, insufficient data).
    """
    # Convert annualised sr_star to per-bar (daily: 365 bars/year)
    sr_star_per_bar = sr_star_annual / math.sqrt(365)

    # Load run metadata
    run_row = conn.execute(
        text(
            "SELECT asset_id, start_ts, end_ts FROM public.cmc_backtest_runs WHERE run_id = :run_id"
        ),
        {"run_id": run_id},
    ).fetchone()

    if run_row is None:
        logger.warning(f"Run {run_id} not found in cmc_backtest_runs — skipping")
        return None

    asset_id, start_ts, end_ts = run_row[0], run_row[1], run_row[2]

    # Load bar timestamps for the backtest window
    bars_result = conn.execute(
        text(
            """
            SELECT ts FROM public.cmc_features
            WHERE id = :asset_id
              AND tf = '1D'
              AND ts BETWEEN :start_ts AND :end_ts
            ORDER BY ts
            """
        ),
        {"asset_id": asset_id, "start_ts": start_ts, "end_ts": end_ts},
    )
    bar_rows = bars_result.fetchall()

    if not bar_rows:
        logger.warning(
            f"No price bars found for run {run_id} (asset {asset_id}) — skipping"
        )
        return None

    # Build DatetimeIndex (tz-naive UTC)
    bar_timestamps = pd.DatetimeIndex(
        [
            pd.Timestamp(r[0]).tz_convert("UTC").replace(tzinfo=None)
            if hasattr(pd.Timestamp(r[0]), "tz") and pd.Timestamp(r[0]).tz is not None
            else pd.Timestamp(r[0])
            for r in bar_rows
        ]
    )

    # Load trades
    trades_result = conn.execute(
        text(
            """
            SELECT entry_ts, exit_ts, pnl_pct
            FROM public.cmc_backtest_trades
            WHERE run_id = :run_id
            ORDER BY entry_ts
            """
        ),
        {"run_id": run_id},
    )
    trade_rows = trades_result.fetchall()

    if not trade_rows:
        logger.warning(f"No trades found for run {run_id} — skipping")
        return None

    trades_df = pd.DataFrame(trade_rows, columns=["entry_ts", "exit_ts", "pnl_pct"])

    # Reconstruct bar-level returns from trades
    returns = reconstruct_bar_returns(bar_timestamps, trades_df)
    n_obs = len(returns)

    if n_obs < 30:
        logger.warning(
            f"Run {run_id}: only {n_obs} bars — insufficient for PSR (min 30)"
        )
        return None

    # Compute PSR
    psr_value = compute_psr(returns.values, sr_star=sr_star_per_bar)
    if math.isnan(psr_value):
        logger.warning(f"Run {run_id}: PSR returned NaN — skipping write")
        return None

    # Compute distributional stats
    skewness_val = float(skew(returns.values))
    kurtosis_pearson_val = float(kurtosis(returns.values, fisher=False))

    # Compute MinTRL
    trl = min_trl(
        returns.values, sr_star=sr_star_per_bar, target_psr=0.95, freq_per_year=365
    )
    min_trl_bars_val = (
        int(math.ceil(trl["n_obs"])) if math.isfinite(trl["n_obs"]) else None
    )
    min_trl_days_val = (
        int(trl["calendar_days"]) if math.isfinite(trl["calendar_days"]) else None
    )
    sr_hat_val = float(trl["sr_hat"])

    logger.info(
        f"Run {run_id}: PSR={psr_value:.4f}, SR_hat={sr_hat_val:.4f}, "
        f"n_obs={n_obs}, skew={skewness_val:.3f}, kurt={kurtosis_pearson_val:.3f}"
    )

    if dry_run:
        logger.info(f"  [dry-run] Would write psr={psr_value:.4f} to psr_results")
        return float(psr_value)

    # Write to psr_results
    conn.execute(
        text(
            """
            INSERT INTO public.psr_results
                (run_id, formula_version, return_source, psr, dsr, min_trl_bars, min_trl_days,
                 sr_hat, sr_star, n_obs, skewness, kurtosis_pearson)
            VALUES
                (:run_id, :formula_version, :return_source, :psr, :dsr, :min_trl_bars, :min_trl_days,
                 :sr_hat, :sr_star, :n_obs, :skewness, :kurtosis_pearson)
            ON CONFLICT (run_id, formula_version) DO UPDATE SET
                psr = EXCLUDED.psr,
                return_source = EXCLUDED.return_source,
                min_trl_bars = EXCLUDED.min_trl_bars,
                min_trl_days = EXCLUDED.min_trl_days,
                sr_hat = EXCLUDED.sr_hat,
                n_obs = EXCLUDED.n_obs,
                skewness = EXCLUDED.skewness,
                kurtosis_pearson = EXCLUDED.kurtosis_pearson,
                computed_at = now()
            """
        ),
        {
            "run_id": run_id,
            "formula_version": "lopez_de_prado_v1",
            "return_source": "trade_reconstruction",
            "psr": float(psr_value),
            "dsr": None,  # DSR requires multiple runs; deferred to Phase 37+
            "min_trl_bars": min_trl_bars_val,
            "min_trl_days": min_trl_days_val,
            "sr_hat": sr_hat_val,
            "sr_star": sr_star_annual,
            "n_obs": n_obs,
            "skewness": skewness_val,
            "kurtosis_pearson": kurtosis_pearson_val,
        },
    )

    # Also update cmc_backtest_metrics.psr column
    conn.execute(
        text(
            """
            UPDATE public.cmc_backtest_metrics
            SET psr = :psr
            WHERE run_id = :run_id
            """
        ),
        {"run_id": run_id, "psr": float(psr_value)},
    )

    logger.debug(
        f"Run {run_id}: wrote psr_results row (return_source=trade_reconstruction)"
    )
    return float(psr_value)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="compute_psr",
        description=(
            "Compute or recompute Probabilistic Sharpe Ratio (PSR) for historical "
            "backtest runs using trade-reconstructed returns.\n\n"
            "Returns are approximated by distributing each trade's pnl_pct evenly "
            "across its holding bars, treating all other bars as 0-return (cash). "
            "This differs from the portfolio-level returns computed during backtesting "
            "(which account for exact position sizing and per-bar fee deductions).\n"
            "The return_source column in psr_results records 'trade_reconstruction' "
            "for rows written by this script vs 'portfolio' for online computation."
        ),
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--run-id",
        metavar="UUID",
        help="Compute PSR for a single backtest run.",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Compute PSR for all runs that do not yet have a psr_results row.",
    )

    parser.add_argument(
        "--recompute",
        action="store_true",
        default=False,
        help=(
            "Force recomputation even if a psr_results row already exists. "
            "Only applicable with --all."
        ),
    )
    parser.add_argument(
        "--sr-star",
        type=float,
        default=0.0,
        metavar="FLOAT",
        dest="sr_star",
        help=(
            "Benchmark (annualised) Sharpe ratio used as PSR threshold. "
            "Default 0.0. Converted internally to per-bar units (sr_star / sqrt(365))."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be computed but do not write anything to the database.",
    )
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

    engine = create_engine(resolve_db_url(), poolclass=pool.NullPool)

    n_computed = 0
    n_skipped = 0
    n_failed = 0

    with engine.begin() as conn:
        if args.run_id:
            run_ids = [args.run_id]
        else:
            # --all: find runs without a psr_results row (or all runs if --recompute)
            if args.recompute:
                logger.info("--recompute: fetching ALL backtest runs")
                rows = conn.execute(
                    text(
                        "SELECT run_id FROM public.cmc_backtest_runs ORDER BY run_timestamp"
                    )
                ).fetchall()
            else:
                logger.info("Fetching runs WITHOUT an existing psr_results row")
                rows = conn.execute(
                    text(
                        """
                        SELECT r.run_id
                        FROM public.cmc_backtest_runs r
                        LEFT JOIN public.psr_results p
                            ON r.run_id = p.run_id AND p.formula_version = 'lopez_de_prado_v1'
                        WHERE p.result_id IS NULL
                        ORDER BY r.run_timestamp
                        """
                    )
                ).fetchall()

            run_ids = [str(r[0]) for r in rows]
            logger.info(f"Found {len(run_ids)} run(s) to process")

        if args.dry_run:
            logger.info(
                f"[dry-run] Would process {len(run_ids)} run(s) with sr_star={args.sr_star:.3f} (annual)"
            )

        for run_id in run_ids:
            try:
                result = compute_psr_for_run(
                    conn,
                    run_id=run_id,
                    sr_star_annual=args.sr_star,
                    dry_run=args.dry_run,
                )
                if result is not None:
                    n_computed += 1
                else:
                    n_skipped += 1
            except Exception as exc:
                logger.error(f"Run {run_id}: failed — {exc}", exc_info=True)
                n_failed += 1

    logger.info(
        f"PSR computation complete: "
        f"computed={n_computed}, skipped={n_skipped}, failed={n_failed}"
    )

    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
