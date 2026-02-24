"""
Cached query functions for Pipeline Monitor page.

All functions use @st.cache_data(ttl=300) and accept ``_engine`` (underscore-
prefixed) as the first argument so st.cache_data skips hashing the engine.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Allowlist of stats table names -- never derived from user input
# ---------------------------------------------------------------------------
_STATS_TABLES = [
    "price_bars_multi_tf_stats",
    "ema_multi_tf_stats",
    "ema_multi_tf_cal_stats",
    "ema_multi_tf_cal_anchor_stats",
    "returns_ema_stats",
    "cmc_features_stats",
]


@st.cache_data(ttl=300)
def load_table_freshness(_engine) -> pd.DataFrame:
    """Return one row per source_table with staleness info.

    Columns: source_table, n_assets, latest_data_ts, last_refresh,
             staleness_hours
    """
    sql = text(
        """
        SELECT
            source_table,
            COUNT(DISTINCT id)        AS n_assets,
            MAX(last_ts)              AS latest_data_ts,
            MAX(updated_at)           AS last_refresh
        FROM public.asset_data_coverage
        GROUP BY source_table
        ORDER BY source_table
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        return df

    df["latest_data_ts"] = pd.to_datetime(df["latest_data_ts"], utc=True)
    df["last_refresh"] = pd.to_datetime(df["last_refresh"], utc=True)
    df["staleness_hours"] = (
        pd.Timestamp.utcnow().tz_localize("UTC") - df["last_refresh"]
    ).dt.total_seconds() / 3600
    return df


@st.cache_data(ttl=300)
def load_stats_status(_engine) -> dict[str, dict[str, int]]:
    """Return status counts per stats table for the last 24 hours.

    Returns: {table_name: {status_value: count, ...}, ...}
    """
    result: dict[str, dict[str, int]] = {}
    for table in _STATS_TABLES:
        # Table name is from allowlist -- safe from injection
        sql = text(
            f"""
            SELECT status, COUNT(*) AS n
            FROM public.{table}
            WHERE checked_at >= NOW() - INTERVAL '24 hours'
            GROUP BY status
            """
        )
        try:
            with _engine.connect() as conn:
                df = pd.read_sql(sql, conn)
            if df.empty:
                result[table] = {}
            else:
                result[table] = dict(zip(df["status"], df["n"].astype(int)))
        except Exception:  # noqa: BLE001
            result[table] = {}
    return result


@st.cache_data(ttl=300)
def load_asset_coverage(_engine) -> pd.DataFrame:
    """Return per-asset, per-table coverage rows with staleness.

    Columns: symbol, id, source_table, granularity, n_rows, last_ts,
             updated_at, staleness_hours
    """
    sql = text(
        """
        SELECT
            a.symbol,
            c.id,
            c.source_table,
            c.granularity,
            c.n_rows,
            c.last_ts,
            c.updated_at
        FROM public.asset_data_coverage c
        JOIN public.dim_assets a ON a.id = c.id
        ORDER BY a.symbol, c.source_table
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        return df

    df["last_ts"] = pd.to_datetime(df["last_ts"], utc=True)
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True)
    df["staleness_hours"] = (
        pd.Timestamp.utcnow().tz_localize("UTC") - df["updated_at"]
    ).dt.total_seconds() / 3600
    return df


@st.cache_data(ttl=300)
def load_alert_history(_engine, days: int = 7) -> pd.DataFrame:
    """Return recent FAIL/WARN rows from all stats tables.

    Columns: stats_table, status, checked_at, check_name (nullable)
    """
    frames: list[pd.DataFrame] = []

    for table in _STATS_TABLES:
        # Table name is from allowlist -- safe from injection
        sql_with_check_name = text(
            f"""
            SELECT
                '{table}' AS stats_table,
                status,
                checked_at,
                check_name
            FROM public.{table}
            WHERE status IN ('FAIL', 'WARN')
              AND checked_at >= NOW() - INTERVAL :d
            ORDER BY checked_at DESC
            LIMIT 50
            """
        )
        sql_without_check_name = text(
            f"""
            SELECT
                '{table}' AS stats_table,
                status,
                checked_at,
                NULL::text AS check_name
            FROM public.{table}
            WHERE status IN ('FAIL', 'WARN')
              AND checked_at >= NOW() - INTERVAL :d
            ORDER BY checked_at DESC
            LIMIT 50
            """
        )
        interval = f"{days} days"
        try:
            try:
                with _engine.connect() as conn:
                    df = pd.read_sql(sql_with_check_name, conn, params={"d": interval})
            except Exception:  # noqa: BLE001
                with _engine.connect() as conn:
                    df = pd.read_sql(
                        sql_without_check_name, conn, params={"d": interval}
                    )
            if not df.empty:
                frames.append(df)
        except Exception:  # noqa: BLE001
            pass

    if not frames:
        return pd.DataFrame(
            columns=["stats_table", "status", "checked_at", "check_name"]
        )

    combined = pd.concat(frames, ignore_index=True)
    combined["checked_at"] = pd.to_datetime(combined["checked_at"], utc=True)
    return combined.sort_values("checked_at", ascending=False).reset_index(drop=True)
