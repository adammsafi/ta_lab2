"""
Cached query functions for Trading page.

All functions use @st.cache_data(ttl=N) and accept ``_engine`` (underscore-
prefixed) as the first argument so st.cache_data skips hashing the engine.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=120)
def load_open_positions(_engine) -> pd.DataFrame:
    """Return open positions (quantity != 0) for paper exchange, with regime label.

    Columns: symbol, asset_id, exchange, strategy_id, config_name, signal_type,
             quantity, avg_cost_basis, last_mark_price, unrealized_pnl,
             unrealized_pnl_pct, realized_pnl, last_updated, entry_date,
             regime_label
    """
    sql = text(
        """
        SELECT
            a.symbol,
            p.asset_id,
            p.exchange,
            p.strategy_id,
            ec.config_name,
            ec.signal_type,
            p.quantity,
            p.avg_cost_basis,
            p.last_mark_price,
            p.unrealized_pnl,
            p.unrealized_pnl_pct,
            p.realized_pnl,
            p.last_updated,
            p.created_at AS entry_date,
            r.l2_label AS regime_label
        FROM public.positions p
        JOIN public.dim_assets a ON a.id = p.asset_id
        LEFT JOIN public.dim_executor_config ec ON ec.config_id = p.strategy_id
        LEFT JOIN public.regimes r
            ON r.id = p.asset_id
            AND r.tf = '1D'
            AND r.ts = (
                SELECT MAX(ts)
                FROM public.regimes
                WHERE id = p.asset_id
                  AND tf = '1D'
            )
        WHERE p.quantity != 0
          AND p.exchange = 'paper'
        ORDER BY a.symbol, p.strategy_id
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        return df

    df["last_updated"] = pd.to_datetime(df["last_updated"], utc=True)
    df["entry_date"] = pd.to_datetime(df["entry_date"], utc=True)
    return df


@st.cache_data(ttl=120)
def load_recent_fills(_engine, limit: int = 20) -> pd.DataFrame:
    """Return the most recent paper fills with order and asset context.

    Columns: filled_at, symbol, side, fill_qty, fill_price, fee_amount,
             order_avg_price, signal_id
    """
    sql = text(
        """
        SELECT
            f.filled_at,
            a.symbol,
            f.side,
            f.fill_qty,
            f.fill_price,
            f.fee_amount,
            o.avg_fill_price AS order_avg_price,
            o.signal_id
        FROM public.fills f
        JOIN public.orders o ON o.order_id = f.order_id
        JOIN public.dim_assets a ON a.id = o.asset_id
        WHERE o.exchange = 'paper'
        ORDER BY f.filled_at DESC
        LIMIT :limit
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"limit": limit})

    if df.empty:
        return df

    df["filled_at"] = pd.to_datetime(df["filled_at"], utc=True)
    return df


@st.cache_data(ttl=300)
def load_daily_pnl_series(_engine) -> pd.DataFrame:
    """Return daily realized P&L aggregated from paper fills with equity curve columns.

    Columns: trade_date, daily_realized_pnl, cumulative_pnl, peak_equity,
             drawdown_pct
    """
    sql = text(
        """
        SELECT
            DATE(f.filled_at AT TIME ZONE 'UTC') AS trade_date,
            SUM(
                CASE f.side
                    WHEN 'sell' THEN  f.fill_qty * f.fill_price - f.fee_amount
                    WHEN 'buy'  THEN -(f.fill_qty * f.fill_price + f.fee_amount)
                END
            ) AS daily_realized_pnl
        FROM public.fills f
        JOIN public.orders o ON o.order_id = f.order_id
        WHERE o.exchange = 'paper'
        GROUP BY DATE(f.filled_at AT TIME ZONE 'UTC')
        ORDER BY trade_date ASC
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        return df

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["cumulative_pnl"] = df["daily_realized_pnl"].cumsum()
    df["peak_equity"] = df["cumulative_pnl"].cummax()
    df["drawdown_pct"] = (df["cumulative_pnl"] - df["peak_equity"]) / df[
        "peak_equity"
    ].where(df["peak_equity"] != 0, 1)
    return df
