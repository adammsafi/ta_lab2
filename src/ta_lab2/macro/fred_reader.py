"""fred_reader.py

Read FRED raw series from fred.series_values, pivot to wide DataFrame,
and reindex to a full calendar-daily date range.

The raw series stay sparse in fred.series_values (actual observation dates only).
This module produces the dense wide DataFrame that forward_fill.py and
feature_computer.py operate on.

Usage:
    from ta_lab2.macro.fred_reader import load_series_wide, SERIES_TO_LOAD
"""

from __future__ import annotations

import logging
from typing import Sequence

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# ── Series needed for FRED-03 through FRED-16 ─────────────────────────────
# Listed in logical groupings per phase requirement.
SERIES_TO_LOAD: list[str] = [
    # FRED-03: Net liquidity components
    "WALCL",  # Fed balance sheet (weekly, H.4.1)
    "WTREGEN",  # Treasury General Account / TGA (weekly, H.4.1)
    "RRPONTSYD",  # Overnight Reverse Repo (daily)
    # FRED-04: Rate spread components
    "DFF",  # Fed Funds Effective Rate (daily)
    "IRSTCI01JPM156N",  # Japan short-term rate (monthly)
    "ECBDFR",  # ECB Deposit Facility Rate (daily)
    "DGS10",  # 10-Year Treasury Yield (daily)
    "IRLTLT01JPM156N",  # Japan 10-year bond yield (monthly)
    # FRED-05: Yield curve
    "T10Y2Y",  # 10Y minus 2Y spread (daily)
    # FRED-06: VIX regime
    "VIXCLS",  # CBOE Volatility Index (daily)
    # FRED-07: Dollar strength
    "DTWEXBGS",  # Trade-Weighted USD Index: Broad (daily)
    # ── Phase 66 additions (FRED-08 through FRED-16) ──────────────────
    # FRED-08: Credit stress
    "BAMLH0A0HYM2",  # HY OAS spread (daily)
    # FRED-09: Financial conditions
    "NFCI",  # Chicago Fed NFCI (weekly)
    # FRED-10: M2 money supply
    "M2SL",  # M2 (monthly)
    # FRED-11: Carry trade FX
    "DEXJPUS",  # USD/JPY exchange rate (daily)
    # FRED-13/16: Fed regime (DFEDTARU/DFEDTARL already synced from VM)
    "DFEDTARU",  # Fed Funds target upper bound (daily)
    "DFEDTARL",  # Fed Funds target lower bound (daily)
    # FRED-15: CPI proxy
    "CPIAUCSL",  # CPI All Items (monthly)
    # -- Phase 97 additions: US equity indices (daily, business days only) --
    "SP500",  # S&P 500 Index (daily)
    "NASDAQCOM",  # NASDAQ Composite Index (daily)
    "DJIA",  # Dow Jones Industrial Average (daily)
]


def load_series_wide(
    engine: Engine,
    series_ids: Sequence[str] = SERIES_TO_LOAD,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Load FRED series from fred.series_values, pivot to wide, reindex to daily cadence.

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the marketdata database.
    series_ids:
        FRED series IDs to load. Defaults to SERIES_TO_LOAD (21 series: 11 Phase 65 + 7 Phase 66 + 3 Phase 97).
    start_date:
        Optional lower bound on observation date (inclusive), e.g. "2015-01-01".
        If None, loads from the earliest available date.
    end_date:
        Optional upper bound on observation date (inclusive), e.g. "2026-03-01".
        If None, loads up to the latest available date.

    Returns
    -------
    pd.DataFrame
        Wide DataFrame with:
        - Index: DatetimeIndex (UTC-unaware, calendar-daily freq='D')
        - Columns: FRED series IDs in uppercase (e.g. "WALCL", "VIXCLS")
        - Values: float or NaN (NaN for calendar days without an actual observation
          before forward-filling)

    Notes
    -----
    - Weekends and holidays are included in the reindexed output (NaN until ffilled).
    - Column names are uppercase FRED series IDs to match FFILL_LIMITS keys.
    - If a series has zero rows in fred.series_values, it will be absent from the
      returned DataFrame (not a zero-filled column).
    """
    if not series_ids:
        raise ValueError("series_ids must be non-empty")

    # Build parameterized query
    clauses: list[str] = ["series_id = ANY(:ids)"]
    # Use str values for dates to avoid mypy Mapping value type issues with pd.read_sql
    bind_params: dict[str, str | list[str]] = {"ids": list(series_ids)}

    if start_date is not None:
        clauses.append("date >= :start_date")
        bind_params["start_date"] = start_date

    if end_date is not None:
        clauses.append("date <= :end_date")
        bind_params["end_date"] = end_date

    where_sql = " AND ".join(clauses)

    query = text(
        f"""
        SELECT series_id, date, value
        FROM fred.series_values
        WHERE {where_sql}
        ORDER BY series_id, date
        """
    )

    with engine.connect() as conn:
        df_long = pd.read_sql(query, conn, params=bind_params)  # type: ignore[arg-type]

    if df_long.empty:
        logger.warning(
            "fred.series_values returned no rows for series_ids=%s "
            "start_date=%s end_date=%s",
            list(series_ids),
            start_date,
            end_date,
        )
        return pd.DataFrame()

    # Convert date column to datetime (avoids tz-aware issues — stays tz-naive)
    # CRITICAL: use pd.to_datetime() explicitly, NOT index_col+parse_dates on read_sql
    df_long["date"] = pd.to_datetime(df_long["date"])

    # Pivot to wide: index=date, columns=series_id (uppercase FRED IDs), values=value
    df_wide = df_long.pivot(index="date", columns="series_id", values="value")
    df_wide.index.name = "date"

    # Ensure column names are uppercase (fred.series_values stores uppercase IDs)
    df_wide.columns = [str(c).upper() for c in df_wide.columns]

    # Reindex to full calendar date range (weekends and holidays included)
    # This is correct for crypto consumers which trade 24/7
    date_min = df_wide.index.min()
    date_max = df_wide.index.max()
    full_range = pd.date_range(start=date_min, end=date_max, freq="D")
    df_wide = df_wide.reindex(full_range)
    df_wide.index.name = "date"

    logger.info(
        "Loaded %d series, %d calendar days (%s to %s)",
        len(df_wide.columns),
        len(df_wide),
        date_min.date(),
        date_max.date(),
    )

    return df_wide
