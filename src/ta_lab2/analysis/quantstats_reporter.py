"""QuantStats HTML tear sheet reporter.

Generates self-contained HTML tear sheets from portfolio returns with
optional BTC benchmark comparison. Wraps ``qs.reports.html`` from the
``quantstats`` library.

Usage::

    from ta_lab2.analysis.quantstats_reporter import (
        generate_tear_sheet,
        _load_btc_benchmark_returns,
    )

    bench = _load_btc_benchmark_returns(engine, start_ts, end_ts)
    path = generate_tear_sheet(
        portfolio_returns=pf.returns(),
        benchmark_returns=bench,
        output_path="/tmp/report.html",
        title="BTC RSI Strategy",
    )
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# CoinMarketCap ID for Bitcoin
BTC_ID: int = 1


def _strip_tz(series: pd.Series) -> pd.Series:
    """Return *series* with a tz-naive DatetimeIndex.

    QuantStats requires tz-naive indices. This helper removes timezone
    information only when it is present so we never accidentally call
    ``tz_localize(None)`` on an already-naive index (which raises a
    ``TypeError``).
    """
    if series.index.tz is not None:
        series = series.copy()
        series.index = series.index.tz_localize(None)
    return series


def generate_tear_sheet(
    portfolio_returns: pd.Series,
    benchmark_returns: Optional[pd.Series],
    output_path: str,
    title: str = "Portfolio Tear Sheet",
) -> Optional[str]:
    """Generate a self-contained HTML tear sheet using QuantStats.

    Parameters
    ----------
    portfolio_returns:
        Daily portfolio return Series (e.g. from ``vectorbt pf.returns()``).
        May be tz-aware or tz-naive.
    benchmark_returns:
        Daily benchmark return Series (``pct_change``-based), or ``None``
        to produce a tear sheet without a benchmark comparison.
    output_path:
        Filesystem path for the output HTML file.  Parent directory is
        created automatically if it does not already exist.
    title:
        Report title embedded in the HTML output.

    Returns
    -------
    str or None
        Absolute path to the generated HTML file on success, or ``None``
        if QuantStats is not installed (ImportError caught gracefully).
    """
    try:
        import quantstats as qs  # lazy import — optional dependency
    except ImportError:
        logger.warning(
            "quantstats is not installed; skipping tear sheet generation. "
            "Install with: pip install 'ta_lab2[analytics]'"
        )
        return None

    # Ensure output directory exists
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # Strip timezone for QuantStats compatibility
    ret = _strip_tz(portfolio_returns)

    common_kwargs: dict = dict(
        output=output_path,
        title=title,
        periods_per_year=365,
        compounded=True,
    )

    if benchmark_returns is not None and len(benchmark_returns) > 0:
        bench = _strip_tz(benchmark_returns)
        qs.reports.html(ret, benchmark=bench, **common_kwargs)
    else:
        # No benchmark — generate benchmark-free tear sheet
        qs.reports.html(ret, **common_kwargs)

    logger.info("Tear sheet written to %s", output_path)
    return output_path


def _load_btc_benchmark_returns(
    engine,
    start_ts,
    end_ts,
) -> Optional[pd.Series]:
    """Load daily BTC close prices from ``cmc_features`` and return pct_change.

    Queries the ``public.cmc_features`` table for BTC (id=1) daily bars in
    [start_ts, end_ts] and converts close prices to arithmetic returns via
    ``pct_change().dropna()``.

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the project database.
    start_ts:
        Start of the date range (inclusive).  Any type accepted by
        ``pd.to_datetime``.
    end_ts:
        End of the date range (inclusive).

    Returns
    -------
    pd.Series or None
        tz-naive DatetimeIndex with arithmetic daily returns, or ``None``
        when no BTC data is available for the requested range (prevents
        passing an empty Series to QuantStats).
    """
    from sqlalchemy import text

    sql = text(
        """
        SELECT ts, close
        FROM public.cmc_features
        WHERE id = :btc_id
          AND tf = '1D'
          AND ts >= :start
          AND ts <= :end
        ORDER BY ts
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(
            sql, conn, params={"btc_id": BTC_ID, "start": start_ts, "end": end_ts}
        )

    if df.empty:
        logger.warning(
            "No BTC data found in cmc_features for range %s – %s; "
            "benchmark will be omitted from tear sheet.",
            start_ts,
            end_ts,
        )
        return None

    # Fix timezone: parse as UTC then strip for QuantStats compatibility
    ts_series = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
    close_series = pd.Series(df["close"].values, index=ts_series, name="btc_close")
    close_series = close_series.sort_index()

    returns = close_series.pct_change().dropna()

    if returns.empty:
        logger.warning(
            "BTC close prices were loaded but pct_change produced an empty "
            "Series (likely only 1 row); benchmark will be omitted."
        )
        return None

    returns.name = "BTC"
    return returns
