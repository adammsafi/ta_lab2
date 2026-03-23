"""
Cached query functions for Backtest Results and Signal pages.

All functions use @st.cache_data and accept ``_engine`` (underscore-prefixed)
as the first argument so st.cache_data skips hashing the engine.

server-side filtering is critical: strategy_bakeoff_results has 76,970+ rows.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Bakeoff leaderboard queries (ttl=3600 -- results rarely change)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600)
def load_bakeoff_leaderboard(
    _engine,
    tf: str = "1D",
    cv_method: str = "purged_kfold",
    cost_scenario: str = "spot_fee16_slip10",
) -> pd.DataFrame:
    """Return leaderboard rows filtered by tf, cv_method, cost_scenario.

    Server-side filtering is mandatory -- 76K+ rows in table.

    Columns: strategy_name, asset_id, symbol, tf, params_json, cost_scenario,
             cv_method, sharpe_mean, sharpe_std, max_drawdown_worst, psr, dsr,
             turnover, trade_count_total, pbo_prob, experiment_name, computed_at
    """
    sql = text(
        """
        SELECT
            r.strategy_name,
            r.asset_id,
            da.symbol,
            r.tf,
            r.params_json,
            r.cost_scenario,
            r.cv_method,
            r.sharpe_mean,
            r.sharpe_std,
            r.max_drawdown_worst,
            r.psr,
            r.dsr,
            r.turnover,
            r.trade_count_total,
            r.pbo_prob,
            r.experiment_name,
            r.computed_at
        FROM public.strategy_bakeoff_results r
        JOIN public.dim_assets da ON da.id = r.asset_id
        WHERE r.tf = :tf
          AND r.cv_method = :cv_method
          AND r.cost_scenario = :cost_scenario
        ORDER BY r.sharpe_mean DESC
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={"tf": tf, "cv_method": cv_method, "cost_scenario": cost_scenario},
        )

    if df.empty:
        return df

    if "computed_at" in df.columns:
        df["computed_at"] = pd.to_datetime(df["computed_at"], utc=True)
    return df


@st.cache_data(ttl=3600)
def load_bakeoff_for_asset(
    _engine,
    asset_id: int,
    tf: str = "1D",
) -> pd.DataFrame:
    """Return all bakeoff rows for a specific asset and timeframe.

    Columns: strategy_name, asset_id, symbol, tf, params_json, cost_scenario,
             cv_method, sharpe_mean, sharpe_std, max_drawdown_worst, psr, dsr,
             turnover, trade_count_total, pbo_prob, experiment_name, computed_at
    """
    sql = text(
        """
        SELECT
            r.strategy_name,
            r.asset_id,
            da.symbol,
            r.tf,
            r.params_json,
            r.cost_scenario,
            r.cv_method,
            r.sharpe_mean,
            r.sharpe_std,
            r.max_drawdown_worst,
            r.psr,
            r.dsr,
            r.turnover,
            r.trade_count_total,
            r.pbo_prob,
            r.experiment_name,
            r.computed_at
        FROM public.strategy_bakeoff_results r
        JOIN public.dim_assets da ON da.id = r.asset_id
        WHERE r.asset_id = :asset_id
          AND r.tf = :tf
        ORDER BY r.cost_scenario, r.cv_method, r.sharpe_mean DESC
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "tf": tf})

    if df.empty:
        return df

    if "computed_at" in df.columns:
        df["computed_at"] = pd.to_datetime(df["computed_at"], utc=True)
    return df


@st.cache_data(ttl=3600)
def load_bakeoff_cost_matrix(
    _engine,
    strategy_name: str,
    asset_id: int,
    tf: str = "1D",
    cv_method: str = "purged_kfold",
) -> pd.DataFrame:
    """Return all cost scenarios for a strategy/asset/tf/cv_method combination.

    Useful for side-by-side cost scenario comparison.

    Columns: cost_scenario, sharpe_mean, sharpe_std, max_drawdown_worst,
             psr, dsr, turnover, trade_count_total
    """
    sql = text(
        """
        SELECT
            r.cost_scenario,
            r.sharpe_mean,
            r.sharpe_std,
            r.max_drawdown_worst,
            r.psr,
            r.dsr,
            r.turnover,
            r.trade_count_total
        FROM public.strategy_bakeoff_results r
        WHERE r.strategy_name = :strategy_name
          AND r.asset_id = :asset_id
          AND r.tf = :tf
          AND r.cv_method = :cv_method
        ORDER BY r.cost_scenario
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={
                "strategy_name": strategy_name,
                "asset_id": asset_id,
                "tf": tf,
                "cv_method": cv_method,
            },
        )
    return df


@st.cache_data(ttl=3600)
def load_bakeoff_strategies(_engine) -> list[str]:
    """Return distinct strategy names from strategy_bakeoff_results."""
    sql = text(
        """
        SELECT DISTINCT strategy_name
        FROM public.strategy_bakeoff_results
        ORDER BY strategy_name
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return []
    return df["strategy_name"].tolist()


@st.cache_data(ttl=3600)
def load_bakeoff_assets(_engine) -> pd.DataFrame:
    """Return distinct assets that have bakeoff results.

    Columns: asset_id, symbol
    """
    sql = text(
        """
        SELECT DISTINCT sbr.asset_id, da.symbol
        FROM public.strategy_bakeoff_results sbr
        JOIN public.dim_assets da ON da.id = sbr.asset_id
        ORDER BY da.symbol
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    return df


@st.cache_data(ttl=3600)
def load_bakeoff_fold_metrics(
    _engine,
    strategy_name: str,
    asset_id: int,
    tf: str = "1D",
    cost_scenario: str = "spot_fee16_slip10",
    cv_method: str = "purged_kfold",
) -> list[dict]:
    """Return fold_metrics_json for a specific bakeoff row.

    The fold_metrics_json column is JSONB and is auto-deserialized by
    psycopg2 -- do NOT call json.loads() on the result.

    Returns
    -------
    list[dict]
        List of fold metric dicts (one per CV fold), or empty list if not found.
    """
    sql = text(
        """
        SELECT fold_metrics_json
        FROM public.strategy_bakeoff_results
        WHERE strategy_name = :strategy_name
          AND asset_id = :asset_id
          AND tf = :tf
          AND cost_scenario = :cost_scenario
          AND cv_method = :cv_method
        LIMIT 1
        """
    )
    with _engine.connect() as conn:
        row = conn.execute(
            sql,
            {
                "strategy_name": strategy_name,
                "asset_id": asset_id,
                "tf": tf,
                "cost_scenario": cost_scenario,
                "cv_method": cv_method,
            },
        ).fetchone()

    if row is None or row[0] is None:
        return []

    # fold_metrics_json is JSONB -- psycopg2 returns a Python list/dict already
    val = row[0]
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val]
    return []


# ---------------------------------------------------------------------------
# Closed signals for strategy (ttl=300 -- signals update frequently)
# ---------------------------------------------------------------------------


def _strategy_to_signal_table(strategy_name: str) -> str:
    """Map a bakeoff strategy name to the corresponding signal table.

    Mapping rules:
    - ema_* or ama_* -> signals_ema_crossover
    - rsi_* -> signals_rsi_mean_revert
    - breakout_atr* or atr_* -> signals_atr_breakout

    Falls back to signals_ema_crossover for unknown names.
    """
    sn = strategy_name.lower()
    if sn.startswith("rsi"):
        return "signals_rsi_mean_revert"
    if sn.startswith("breakout_atr") or sn.startswith("atr_"):
        return "signals_atr_breakout"
    # ema_* and ama_* both route here
    return "signals_ema_crossover"


@st.cache_data(ttl=300)
def load_closed_signals_for_strategy(
    _engine,
    strategy_name: str,
    asset_id: int,
    tf: str = "1D",
) -> pd.DataFrame:
    """Return closed signal rows for a strategy/asset pair.

    Routes to the correct signal table based on strategy_name prefix.

    Columns: id, ts, signal_id, direction, position_state, entry_price,
             entry_ts, exit_price, exit_ts, pnl_pct, created_at, symbol
    """
    table = _strategy_to_signal_table(strategy_name)

    # Validate table name against known set to prevent SQL injection
    _valid_tables = frozenset(
        ["signals_ema_crossover", "signals_rsi_mean_revert", "signals_atr_breakout"]
    )
    if table not in _valid_tables:
        return pd.DataFrame()

    sql = text(
        f"""
        SELECT
            s.id,
            s.ts,
            s.signal_id,
            s.direction,
            s.position_state,
            s.entry_price,
            s.entry_ts,
            s.exit_price,
            s.exit_ts,
            s.pnl_pct,
            s.created_at,
            da.symbol
        FROM public.{table} s
        JOIN public.dim_assets da ON da.id = s.id
        WHERE s.id = :asset_id
          AND s.position_state = 'closed'
        ORDER BY s.entry_ts DESC
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"asset_id": asset_id})

    if df.empty:
        return df

    for col in ("ts", "entry_ts", "exit_ts", "created_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    return df
