"""
Standalone CLI: run Monte Carlo Sharpe ratio analysis for an existing backtest run.

Loads trade records from backtest_trades, bootstraps the Sharpe ratio
distribution by resampling trade PnL, and prints the 95% confidence interval
(2.5th/97.5th percentiles) plus the median.

Usage
-----
# Basic usage (1000 samples, seed 42):
    python -m ta_lab2.scripts.analysis.run_monte_carlo --run-id <uuid>

# Custom parameters:
    python -m ta_lab2.scripts.analysis.run_monte_carlo --run-id <uuid> --n-samples 5000 --seed 99

# Run AND write results back to backtest_metrics:
    python -m ta_lab2.scripts.analysis.run_monte_carlo --run-id <uuid> --write

Notes
-----
- At least 10 trades are required for meaningful Monte Carlo results.
- Results are printed to stdout even without --write.
- mc_sharpe_lo/hi/median/n_samples are written to backtest_metrics with --write.
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd
from sqlalchemy import create_engine, pool, text

from ta_lab2.scripts.refresh_utils import resolve_db_url
from ta_lab2.analysis.monte_carlo import monte_carlo_trades


def _get_engine():
    """Create a SQLAlchemy engine from environment configuration."""
    db_url = resolve_db_url()
    return create_engine(db_url, poolclass=pool.NullPool)


logger = logging.getLogger(__name__)


def _load_trades(engine, run_id: str) -> pd.DataFrame:
    """Load trade records from backtest_trades for this run."""
    sql = text(
        """
        SELECT trade_id, entry_ts, exit_ts, pnl_pct, direction, entry_price
        FROM public.backtest_trades
        WHERE run_id = :run_id
        ORDER BY entry_ts
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"run_id": run_id})

    return df


def _verify_run_exists(engine, run_id: str) -> bool:
    """Return True if run_id exists in backtest_runs."""
    sql = text("SELECT 1 FROM public.backtest_runs WHERE run_id = :run_id LIMIT 1")
    with engine.connect() as conn:
        row = conn.execute(sql, {"run_id": run_id}).fetchone()
    return row is not None


def run_monte_carlo_for_run(
    run_id: str,
    n_samples: int = 1000,
    seed: int = 42,
    write: bool = False,
) -> dict:
    """
    Run Monte Carlo Sharpe ratio analysis for an existing backtest run.

    Parameters
    ----------
    run_id : str
        UUID of the backtest run in backtest_runs.
    n_samples : int
        Number of bootstrap resamples. Default 1000.
    seed : int
        Random seed for reproducibility. Default 42.
    write : bool
        If True, UPDATE backtest_metrics with mc_sharpe_lo/hi/median/n_samples.

    Returns
    -------
    dict
        Monte Carlo results: mc_sharpe_lo, mc_sharpe_hi, mc_sharpe_median,
        mc_n_samples, n_trades.
    """
    engine = _get_engine()

    # 1. Verify run exists
    if not _verify_run_exists(engine, run_id):
        raise ValueError(f"run_id '{run_id}' not found in backtest_runs")

    # 2. Load trade records
    trades_df = _load_trades(engine, run_id)
    logger.info("Loaded %d trade records for run_id=%s", len(trades_df), run_id)

    if trades_df.empty:
        logger.warning("No trades found for run_id=%s — MC not applicable", run_id)
        return {
            "mc_sharpe_lo": None,
            "mc_sharpe_hi": None,
            "mc_sharpe_median": None,
            "mc_n_samples": n_samples,
            "n_trades": 0,
        }

    # 3. Run Monte Carlo via library function
    result = monte_carlo_trades(trades_df, n_samples=n_samples, seed=seed)
    logger.info(
        "Monte Carlo complete: lo=%.4f hi=%.4f median=%.4f n_trades=%d n_samples=%d",
        result.get("mc_sharpe_lo") or 0,
        result.get("mc_sharpe_hi") or 0,
        result.get("mc_sharpe_median") or 0,
        result.get("n_trades", 0),
        result.get("mc_n_samples", 0),
    )

    # 4. Optionally write back to backtest_metrics
    if write:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE public.backtest_metrics
                    SET mc_sharpe_lo     = :mc_sharpe_lo,
                        mc_sharpe_hi     = :mc_sharpe_hi,
                        mc_sharpe_median = :mc_sharpe_median,
                        mc_n_samples     = :mc_n_samples
                    WHERE run_id = :run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "mc_sharpe_lo": result.get("mc_sharpe_lo"),
                    "mc_sharpe_hi": result.get("mc_sharpe_hi"),
                    "mc_sharpe_median": result.get("mc_sharpe_median"),
                    "mc_n_samples": result.get("mc_n_samples"),
                },
            )
        logger.info(
            "Wrote Monte Carlo results to backtest_metrics for run_id=%s", run_id
        )

    return result


def main() -> None:
    """Entry point for CLI invocation."""
    parser = argparse.ArgumentParser(
        description=(
            "Run Monte Carlo Sharpe ratio analysis for an existing backtest run. "
            "Bootstraps trade PnL to produce a 95%% Sharpe CI (2.5th/97.5th percentiles)."
        )
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="UUID of the backtest run (backtest_runs.run_id)",
    )
    parser.add_argument(
        "--n-samples",
        type=int,
        default=1000,
        help="Number of bootstrap resamples (default: 1000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help="UPDATE backtest_metrics with mc_sharpe_lo/hi/median/n_samples",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    try:
        result = run_monte_carlo_for_run(
            run_id=args.run_id,
            n_samples=args.n_samples,
            seed=args.seed,
            write=args.write,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Print results to stdout
    n_trades = result.get("n_trades", 0)
    lo = result.get("mc_sharpe_lo")
    hi = result.get("mc_sharpe_hi")
    median = result.get("mc_sharpe_median")
    n_valid = result.get("mc_n_samples")

    print(f"\nMonte Carlo Sharpe CI ({args.n_samples} samples, seed={args.seed})")
    print(f"  run_id     : {args.run_id}")
    print(f"  n_trades   : {n_trades}")
    print(f"  n_valid_samples: {n_valid}")

    if lo is None:
        print("  Result     : insufficient trades (<10) — CI not computed")
    else:
        print(f"  Sharpe 2.5% : {lo:.4f}")
        print(f"  Sharpe median: {median:.4f}")
        print(f"  Sharpe 97.5%: {hi:.4f}")
        print(f"  CI width    : {(hi - lo):.4f}")

    if args.write:
        print(f"\n  Wrote results to backtest_metrics for run_id={args.run_id}")


if __name__ == "__main__":
    main()
