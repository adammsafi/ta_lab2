# -*- coding: utf-8 -*-
"""
Asset Hub page -- unified per-asset "trading terminal" view.

Combines candlestick chart, active signals, backtest results, and regime state
for a single selected asset. Supports deep linking via st.query_params.

NOTE: Do NOT call st.set_page_config() here -- it is called in the main app
entry point (Home.py). Calling it again from a page script raises a
StreamlitAPIException.
"""

from __future__ import annotations

import streamlit as st

from ta_lab2.dashboard.charts import (
    build_candlestick_chart,
    chart_download_button,
)
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.backtest import load_bakeoff_for_asset
from ta_lab2.dashboard.queries.research import (
    load_asset_list,
    load_ema_overlays,
    load_ohlcv_features,
    load_regimes,
    load_tf_list,
)
from ta_lab2.dashboard.queries.signals import load_active_signals

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Asset Hub")
st.caption("Unified asset view -- chart, signals, backtests, regimes")

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Load asset list and timeframe list (needed by sidebar)
# ---------------------------------------------------------------------------

try:
    assets_df = load_asset_list(engine)
    tf_list = load_tf_list(engine)
except Exception as exc:
    st.error(f"Error loading dimension data: {exc}")
    st.stop()

if assets_df.empty:
    st.warning("No assets found in dim_assets. Run data pipeline first.")
    st.stop()

if not tf_list:
    st.warning("No timeframes found in dim_timeframe.")
    st.stop()

# ---------------------------------------------------------------------------
# URL state: read query params for deep linking
# ---------------------------------------------------------------------------

qp_asset = st.query_params.get("asset", "")
qp_tf = st.query_params.get("tf", "1D")

# Resolve asset symbol -> id
asset_options = dict(zip(assets_df["symbol"], assets_df["id"]))
symbol_list = list(asset_options.keys())

# Default asset: from query param if valid, else first in list
if qp_asset and qp_asset in asset_options:
    default_asset_idx = symbol_list.index(qp_asset)
else:
    default_asset_idx = 0

# Default timeframe: from query param if valid, else "1D"
if qp_tf in tf_list:
    default_tf_idx = tf_list.index(qp_tf)
elif "1D" in tf_list:
    default_tf_idx = tf_list.index("1D")
else:
    default_tf_idx = 0

# ---------------------------------------------------------------------------
# Sidebar controls (outside any fragment -- widgets must be at module level)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Asset Hub Controls")

    selected_symbol = st.selectbox(
        "Asset",
        symbol_list,
        index=default_asset_idx,
        key="hub_asset",
    )
    selected_id = asset_options[selected_symbol]

    selected_tf = st.selectbox(
        "Timeframe",
        tf_list,
        index=default_tf_idx,
        key="hub_tf",
    )

    selected_ema_periods = st.multiselect(
        "EMA Overlays",
        [9, 21, 50, 200],
        default=[21, 50],
        key="hub_ema_periods",
    )

    # Update URL state on selection changes
    st.query_params["asset"] = selected_symbol
    st.query_params["tf"] = selected_tf

# ---------------------------------------------------------------------------
# Section 1: Candlestick Chart (full width)
# ---------------------------------------------------------------------------

st.subheader(f"Price Chart -- {selected_symbol} ({selected_tf})")

try:
    ohlcv_df = load_ohlcv_features(engine, selected_id, selected_tf)
    ema_df = None
    if selected_ema_periods:
        ema_df = load_ema_overlays(
            engine, selected_id, selected_tf, periods=selected_ema_periods
        )
        if ema_df is not None and ema_df.empty:
            ema_df = None

    regimes_df = load_regimes(engine, selected_id, selected_tf)
    if regimes_df is not None and regimes_df.empty:
        regimes_df = None

    fig_chart = build_candlestick_chart(
        ohlcv_df,
        ema_df=ema_df,
        regimes_df=regimes_df,
        title=f"{selected_symbol} ({selected_tf})",
    )
    st.plotly_chart(fig_chart, theme=None, key="hub_candlestick")
    chart_download_button(
        fig_chart,
        "Download Chart (HTML)",
        f"asset_hub_{selected_symbol}_{selected_tf}.html",
    )
except Exception as exc:
    st.warning(f"Could not render candlestick chart: {exc}")

st.divider()

# ---------------------------------------------------------------------------
# Section 2: Active Signals (2/3 width) + Regime State (1/3 width)
# ---------------------------------------------------------------------------

col_signals, col_regime = st.columns([2, 1])

with col_signals:
    st.subheader("Active Signals")
    try:
        active_signals_df = load_active_signals(engine)
        # Filter to selected asset
        if not active_signals_df.empty and "id" in active_signals_df.columns:
            asset_signals = active_signals_df[
                active_signals_df["id"] == selected_id
            ].copy()
        else:
            asset_signals = active_signals_df

        if asset_signals.empty:
            st.info(
                f"No active signals for {selected_symbol}. "
                "Signals populate during daily refresh."
            )
        else:
            display_cols = [
                c
                for c in [
                    "direction",
                    "signal_name",
                    "entry_price",
                    "entry_ts",
                    "signal_type",
                ]
                if c in asset_signals.columns
            ]
            st.dataframe(
                asset_signals[display_cols] if display_cols else asset_signals,
                use_container_width=True,
                key="hub_signals_table",
            )
    except Exception as exc:
        st.warning(f"Could not load active signals: {exc}")

with col_regime:
    st.subheader("Regime State")
    try:
        # Use regimes_df loaded above; if not set yet, reload
        try:
            regime_data = regimes_df
        except NameError:
            regime_data = load_regimes(engine, selected_id, selected_tf)

        if regime_data is not None and len(regime_data) > 0:
            latest_regime = regime_data.iloc[-1]
            trend_state = latest_regime.get("trend_state", "Unknown")
            vol_state = latest_regime.get("vol_state", "Unknown")
            l2_label = latest_regime.get("l2_label", "Unknown")
            regime_ts = latest_regime.get("ts", "")

            st.metric(
                "Trend State",
                str(trend_state),
                help="L2 regime trend component",
            )
            st.metric(
                "Vol State",
                str(vol_state),
                help="L2 regime volatility component",
            )
            st.caption(f"Label: {l2_label}")
            if regime_ts:
                st.caption(f"As of: {regime_ts}")
        else:
            st.info(
                f"No regime data for {selected_symbol} ({selected_tf}). "
                "Run regime refresh first."
            )
    except Exception as exc:
        st.warning(f"Could not load regime state: {exc}")

st.divider()

# ---------------------------------------------------------------------------
# Section 3: Backtest Results for this asset
# ---------------------------------------------------------------------------

st.subheader(f"Backtest Results -- {selected_symbol} ({selected_tf})")

try:
    bakeoff_df = load_bakeoff_for_asset(engine, selected_id, selected_tf)

    if bakeoff_df.empty:
        st.info(
            f"No backtest results for {selected_symbol} ({selected_tf}). "
            "Run bakeoff pipeline to populate results."
        )
    else:
        # Sort by sharpe_mean DESC and limit to top 20
        if "sharpe_mean" in bakeoff_df.columns:
            bakeoff_df = bakeoff_df.sort_values("sharpe_mean", ascending=False)

        total_rows = len(bakeoff_df)
        display_bakeoff = bakeoff_df.head(20)

        st.caption(
            f"Top {min(20, total_rows)} of {total_rows} strategy/cost combinations"
        )

        display_cols = [
            c
            for c in [
                "strategy_name",
                "cost_scenario",
                "cv_method",
                "sharpe_mean",
                "psr",
                "dsr",
                "max_drawdown_worst",
                "trade_count_total",
                "experiment_name",
            ]
            if c in display_bakeoff.columns
        ]
        st.dataframe(
            display_bakeoff[display_cols] if display_cols else display_bakeoff,
            use_container_width=True,
            key="hub_bakeoff_table",
        )
except Exception as exc:
    st.warning(f"Could not load backtest results: {exc}")

st.divider()

# ---------------------------------------------------------------------------
# Section 4: Quick links
# ---------------------------------------------------------------------------

st.subheader("Quick Links")

col_link1, col_link2, col_link3 = st.columns(3)

with col_link1:
    research_url = f"?asset={selected_symbol}&tf={selected_tf}"
    st.markdown(
        f"[View in Research Explorer](/Research_Explorer{research_url})",
        help="Open this asset in the Research Explorer page",
    )

with col_link2:
    backtest_url = f"?asset={selected_symbol}&tf={selected_tf}"
    st.markdown(
        f"[View all backtests](/Backtest_Results{backtest_url})",
        help="Open all backtest results filtered to this asset",
    )

with col_link3:
    signals_url = f"?asset={selected_symbol}"
    st.markdown(
        f"[View all signals](/Signal_Browser{signals_url})",
        help="Open all signals filtered to this asset",
    )
