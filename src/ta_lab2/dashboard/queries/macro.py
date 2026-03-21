"""
Cached query functions for the Macro Observability dashboard tab.

All functions use @st.cache_data(ttl=300) and accept ``_engine`` (underscore-
prefixed) as the first argument so st.cache_data skips hashing the engine.

Functions
---------
load_current_macro_regime      -- Single row: today's macro regime labels
load_macro_regime_history      -- Time series of regime labels for timeline chart
load_fred_freshness            -- Per-series staleness with frequency-aware thresholds
load_fred_series_quality       -- Per-series coverage and gap statistics
load_macro_transition_log      -- Regime transitions (days where regime_key changed)
"""

from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import text

# ---------------------------------------------------------------------------
# FRED series frequency mapping
# Used by load_fred_freshness to assign staleness thresholds.
# ---------------------------------------------------------------------------

# Series IDs by release frequency
_DAILY_SERIES: frozenset[str] = frozenset(
    {
        "DFF",
        "DGS2",
        "DGS10",
        "BAMLH0A0HYM2",
        "VIXCLS",
        "DTWEXBGS",
    }
)

_WEEKLY_SERIES: frozenset[str] = frozenset(
    {
        "ICSA",
    }
)

# All other series are treated as monthly.

# Freshness threshold (days) per frequency.
# Daily: 3 days (allows for weekends/holidays)
# Weekly: 10 days (allows for one week + buffer)
# Monthly: 45 days (allows for ~6-week release lag typical of FRED monthly)
_FRESH_THRESHOLD: dict[str, int] = {
    "daily": 3,
    "weekly": 10,
    "monthly": 45,
}


def _series_frequency(series_id: str) -> str:
    """Return 'daily', 'weekly', or 'monthly' for a FRED series ID."""
    if series_id in _DAILY_SERIES:
        return "daily"
    if series_id in _WEEKLY_SERIES:
        return "weekly"
    return "monthly"


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def load_current_macro_regime(_engine) -> pd.DataFrame:
    """Return the most recent macro regime row for the default profile.

    Queries macro_regimes for the latest date where profile='default'.

    Columns
    -------
    date, monetary_policy, liquidity, risk_appetite, carry,
    regime_key, macro_state

    Returns
    -------
    pd.DataFrame
        Single-row DataFrame.  Empty if macro_regimes has no rows.
    """
    sql = text(
        """
        SELECT
            date,
            monetary_policy,
            liquidity,
            risk_appetite,
            carry,
            regime_key,
            macro_state
        FROM public.macro_regimes
        WHERE profile = 'default'
          AND date = (
              SELECT MAX(date)
              FROM public.macro_regimes
              WHERE profile = 'default'
          )
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=300)
def load_macro_regime_history(_engine, days: int = 365) -> pd.DataFrame:
    """Return macro regime history over the last N days for the default profile.

    Ordered by date ascending, suitable for timeline chart rendering.

    Parameters
    ----------
    days : int
        Number of calendar days of history to return.  Default 365.

    Columns
    -------
    date, monetary_policy, liquidity, risk_appetite, carry,
    regime_key, macro_state

    Returns
    -------
    pd.DataFrame
        Time-ordered DataFrame.  Empty if no rows found.
    """
    sql = text(
        """
        SELECT
            date,
            monetary_policy,
            liquidity,
            risk_appetite,
            carry,
            regime_key,
            macro_state
        FROM public.macro_regimes
        WHERE profile = 'default'
          AND date >= CURRENT_DATE - :days
        ORDER BY date ASC
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"days": days})

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=300)
def load_fred_freshness(_engine) -> pd.DataFrame:
    """Return per-FRED-series staleness with frequency-aware freshness thresholds.

    Queries fred.series_values for the latest date and row count per series,
    then computes staleness_days, fresh_threshold_days, and a traffic-light
    status string matching the existing pipeline monitor convention.

    Staleness thresholds (from CONTEXT.md):
      - Daily series:   3 days
      - Weekly series:  10 days
      - Monthly series: 45 days

    Status rules:
      - "green"  : staleness_days <= threshold
      - "orange" : staleness_days <= threshold * 2.4
      - "red"    : staleness_days >  threshold * 2.4

    Columns
    -------
    series_id, latest_date, row_count, staleness_days,
    frequency, fresh_threshold_days, status

    Returns
    -------
    pd.DataFrame
        One row per FRED series.  Empty if fred.series_values has no rows.
    """
    sql = text(
        """
        SELECT
            series_id,
            MAX(date)   AS latest_date,
            COUNT(*)    AS row_count
        FROM fred.series_values
        GROUP BY series_id
        ORDER BY series_id
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        return df

    df["latest_date"] = pd.to_datetime(df["latest_date"])

    today = datetime.date.today()
    df["staleness_days"] = df["latest_date"].apply(
        lambda d: (today - d.date()).days if pd.notna(d) else None
    )

    df["frequency"] = df["series_id"].apply(_series_frequency)
    df["fresh_threshold_days"] = df["frequency"].map(_FRESH_THRESHOLD)

    def _status(row: pd.Series) -> str:
        if pd.isna(row["staleness_days"]):
            return "red"
        stale = row["staleness_days"]
        thresh = row["fresh_threshold_days"]
        if stale <= thresh:
            return "green"
        if stale <= thresh * 2.4:
            return "orange"
        return "red"

    df["status"] = df.apply(_status, axis=1)
    return df


@st.cache_data(ttl=300)
def load_fred_series_quality(_engine) -> pd.DataFrame:
    """Return per-FRED-series data quality statistics (coverage, gaps).

    Queries fred.series_values to compute first/last date, total rows, and
    gap count relative to expected rows given each series' frequency.

    Gap detection logic:
      - Daily: expect every calendar weekday (business day count via pandas)
      - Weekly: expect one row per ISO week present in date range
      - Monthly: expect one row per calendar month present in date range

    Columns
    -------
    series_id, first_date, last_date, total_rows, expected_rows,
    gap_count, coverage_pct

    Returns
    -------
    pd.DataFrame
        One row per FRED series.  Empty if fred.series_values has no rows.
    """
    sql = text(
        """
        SELECT series_id, date, value
        FROM fred.series_values
        ORDER BY series_id, date
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        return pd.DataFrame(
            columns=[
                "series_id",
                "first_date",
                "last_date",
                "total_rows",
                "expected_rows",
                "gap_count",
                "coverage_pct",
            ]
        )

    df["date"] = pd.to_datetime(df["date"])

    records: list[dict] = []
    for series_id, grp in df.groupby("series_id"):
        grp = grp.sort_values("date")
        first_date = grp["date"].iloc[0]
        last_date = grp["date"].iloc[-1]
        total_rows = len(grp)
        freq = _series_frequency(str(series_id))

        # Estimate expected rows based on frequency
        if freq == "daily":
            # Business days between first and last date (inclusive)
            expected_rows = int(
                pd.bdate_range(start=first_date, end=last_date).shape[0]
            )
        elif freq == "weekly":
            # One row per ISO week in range
            all_weeks = pd.date_range(start=first_date, end=last_date, freq="W-FRI")
            expected_rows = max(1, len(all_weeks))
        else:
            # Monthly: one row per calendar month
            all_months = pd.date_range(
                start=first_date.to_period("M").to_timestamp(),
                end=last_date.to_period("M").to_timestamp(),
                freq="MS",
            )
            expected_rows = max(1, len(all_months))

        gap_count = max(0, expected_rows - total_rows)
        coverage_pct = round(
            min(100.0, (total_rows / expected_rows) * 100)
            if expected_rows > 0
            else 0.0,
            2,
        )

        records.append(
            {
                "series_id": series_id,
                "first_date": first_date,
                "last_date": last_date,
                "total_rows": total_rows,
                "expected_rows": expected_rows,
                "gap_count": gap_count,
                "coverage_pct": coverage_pct,
            }
        )

    result = pd.DataFrame(records)
    result["first_date"] = pd.to_datetime(result["first_date"])
    result["last_date"] = pd.to_datetime(result["last_date"])
    return result


@st.cache_data(ttl=300)
def load_macro_transition_log(_engine, days: int = 90) -> pd.DataFrame:
    """Return rows where macro regime_key changed vs the previous calendar day.

    Uses a self-join on macro_regimes (curr.date = prev.date - 1) to find
    transition events.  Only rows where regime_key differs are returned.

    Parameters
    ----------
    days : int
        Number of calendar days of history to look back.  Default 90.

    Columns
    -------
    date, regime_key, macro_state, prev_regime_key, prev_macro_state,
    monetary_policy, liquidity, risk_appetite, carry,
    prev_monetary_policy, prev_liquidity, prev_risk_appetite, prev_carry

    Returns
    -------
    pd.DataFrame
        Ordered by date DESC.  Empty if no transitions found.
    """
    sql = text(
        """
        SELECT
            curr.date,
            curr.regime_key,
            curr.macro_state,
            prev.regime_key          AS prev_regime_key,
            prev.macro_state         AS prev_macro_state,
            curr.monetary_policy,
            curr.liquidity,
            curr.risk_appetite,
            curr.carry,
            prev.monetary_policy     AS prev_monetary_policy,
            prev.liquidity           AS prev_liquidity,
            prev.risk_appetite       AS prev_risk_appetite,
            prev.carry               AS prev_carry
        FROM public.macro_regimes curr
        JOIN public.macro_regimes prev
          ON prev.date    = curr.date - INTERVAL '1 day'
          AND prev.profile = curr.profile
        WHERE curr.profile   = 'default'
          AND curr.date      >= CURRENT_DATE - :days
          AND curr.regime_key != prev.regime_key
        ORDER BY curr.date DESC
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"days": days})

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    return df
