"""
Standalone CLI: generate a QuantStats HTML tear sheet for an existing backtest run.

Reconstructs the equity curve from trade records stored in backtest_trades
WITHOUT re-running the backtest. This makes it safe to regenerate tear sheets
retroactively for any completed run.

Usage
-----
# Generate tear sheet to default output path (reports/tearsheets/<run_id>.html):
    python -m ta_lab2.scripts.analysis.run_quantstats_report --run-id <uuid>

# Specify custom output path:
    python -m ta_lab2.scripts.analysis.run_quantstats_report --run-id <uuid> --output /tmp/report.html

# Generate AND write tearsheet_path back to backtest_runs:
    python -m ta_lab2.scripts.analysis.run_quantstats_report --run-id <uuid> --write

Notes
-----
- Equity curve is reconstructed from backtest_trades (pnl_pct column).
- BTC benchmark is loaded from features (id=1, tf=1D). If unavailable, benchmark
  is omitted and a benchmark-free tear sheet is generated instead.
- Requires quantstats to be installed: pip install 'ta_lab2[analytics]'
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import pandas as pd
from sqlalchemy import create_engine, pool, text

from ta_lab2.scripts.refresh_utils import resolve_db_url
from ta_lab2.analysis.quantstats_reporter import (
    generate_tear_sheet,
    _load_btc_benchmark_returns,
)


def _get_engine():
    """Create a SQLAlchemy engine from environment configuration."""
    db_url = resolve_db_url()
    return create_engine(db_url, poolclass=pool.NullPool)


logger = logging.getLogger(__name__)


def _load_run_metadata(engine, run_id: str) -> dict:
    """Load run metadata from backtest_runs."""
    sql = text(
        """
        SELECT run_id, signal_type, asset_id, start_ts, end_ts, trade_count
        FROM public.backtest_runs
        WHERE run_id = :run_id
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"run_id": run_id}).fetchone()

    if row is None:
        raise ValueError(f"run_id '{run_id}' not found in backtest_runs")

    return {
        "run_id": str(row[0]),
        "signal_type": row[1],
        "asset_id": row[2],
        "start_ts": row[3],
        "end_ts": row[4],
        "trade_count": row[5],
    }


def _load_trades(engine, run_id: str) -> pd.DataFrame:
    """Load trade records from backtest_trades for this run."""
    sql = text(
        """
        SELECT entry_ts, exit_ts, pnl_pct, direction, entry_price, exit_price
        FROM public.backtest_trades
        WHERE run_id = :run_id
        ORDER BY entry_ts
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"run_id": run_id})

    return df


def _reconstruct_daily_returns(
    trades_df: pd.DataFrame,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.Series:
    """
    Reconstruct a daily returns Series from trade records.

    Strategy: allocate each trade's pnl_pct to its exit date (realized P&L
    approach). Days with no exits have 0.0 return. The resulting Series is
    suitable for passing to QuantStats.

    Parameters
    ----------
    trades_df : pd.DataFrame
        Must contain exit_ts (tz-aware) and pnl_pct (percentage points).
    start_ts : pd.Timestamp
        Start of the date range (for index construction).
    end_ts : pd.Timestamp
        End of the date range (for index construction).

    Returns
    -------
    pd.Series
        Daily return Series (decimal, e.g. 0.025 for +2.5%), tz-naive index,
        sorted ascending.
    """
    # Build full date range
    date_range = pd.date_range(
        start=pd.Timestamp(start_ts).normalize(),
        end=pd.Timestamp(end_ts).normalize(),
        freq="D",
    )
    daily_returns = pd.Series(0.0, index=date_range, name="portfolio")

    if trades_df.empty:
        return daily_returns

    # Convert pnl_pct to decimal and assign to exit date
    for _, row in trades_df.iterrows():
        exit_ts = row.get("exit_ts")
        pnl_pct = row.get("pnl_pct")

        if (
            exit_ts is None
            or pd.isnull(exit_ts)
            or pnl_pct is None
            or pd.isnull(pnl_pct)
        ):
            continue

        # Normalize exit timestamp to tz-naive date
        exit_dt = pd.Timestamp(exit_ts)
        if exit_dt.tzinfo is not None:
            exit_dt = exit_dt.tz_convert("UTC").tz_localize(None)
        exit_date = exit_dt.normalize()

        if exit_date in daily_returns.index:
            daily_returns[exit_date] += float(pnl_pct) / 100.0

    return daily_returns


def run_quantstats_report(
    run_id: str,
    output: str | None = None,
    write: bool = False,
) -> str | None:
    """
    Generate a QuantStats HTML tear sheet for an existing backtest run.

    Parameters
    ----------
    run_id : str
        UUID of the backtest run in backtest_runs.
    output : str or None
        Output path for the HTML file. Defaults to reports/tearsheets/<run_id>.html.
    write : bool
        If True, UPDATE backtest_runs.tearsheet_path after generation.

    Returns
    -------
    str or None
        Absolute path to the generated HTML file, or None on failure.
    """
    engine = _get_engine()

    # 1. Load run metadata
    meta = _load_run_metadata(engine, run_id)
    logger.info(
        "Loaded run: signal_type=%s asset_id=%d trade_count=%d",
        meta["signal_type"],
        meta["asset_id"],
        meta["trade_count"],
    )

    # 2. Load trade records
    trades_df = _load_trades(engine, run_id)
    logger.info("Loaded %d trade records", len(trades_df))

    # 3. Reconstruct equity curve from trade records (NO re-running backtest)
    daily_returns = _reconstruct_daily_returns(
        trades_df,
        start_ts=meta["start_ts"],
        end_ts=meta["end_ts"],
    )
    logger.info(
        "Reconstructed daily returns: %d days, sum=%.4f",
        len(daily_returns),
        daily_returns.sum(),
    )

    # 4. Load BTC benchmark (gracefully handle missing data)
    benchmark = _load_btc_benchmark_returns(
        engine,
        start_ts=meta["start_ts"],
        end_ts=meta["end_ts"],
    )
    if benchmark is None:
        logger.info("BTC benchmark unavailable — tear sheet will have no benchmark")

    # 5. Determine output path
    if output is None:
        output = os.path.join("reports", "tearsheets", f"{run_id}.html")

    title = f"{meta['signal_type']} / asset {meta['asset_id']} / {run_id[:8]}"

    # 6. Generate tear sheet
    path = generate_tear_sheet(
        portfolio_returns=daily_returns,
        benchmark_returns=benchmark,
        output_path=output,
        title=title,
    )

    if path is None:
        logger.error("Tear sheet generation failed (quantstats likely not installed)")
        return None

    abs_path = os.path.abspath(path)
    print(f"Tear sheet written: {abs_path}")

    # 7. Optionally write path back to DB
    if write:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE public.backtest_runs "
                    "SET tearsheet_path = :path "
                    "WHERE run_id = :run_id"
                ),
                {"path": abs_path, "run_id": run_id},
            )
        print(f"Updated backtest_runs.tearsheet_path for run_id={run_id}")

    return abs_path


def main() -> None:
    """Entry point for CLI invocation."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate a QuantStats HTML tear sheet for an existing backtest run. "
            "Reconstructs equity curve from trade records — does NOT re-run the backtest."
        )
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="UUID of the backtest run (backtest_runs.run_id)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for the HTML tear sheet. Default: reports/tearsheets/<run_id>.html",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help="UPDATE backtest_runs.tearsheet_path after generation",
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

    result = run_quantstats_report(
        run_id=args.run_id,
        output=args.output,
        write=args.write,
    )

    if result is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
