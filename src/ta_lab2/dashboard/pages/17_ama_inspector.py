# -*- coding: utf-8 -*-
"""
AMA/EMA Inspector dashboard page -- Phase 84.

Lets the user inspect AMA behavior per asset: efficiency ratio (KAMA only),
derivative curves (d1/d2), and compare adaptive vs fixed EMAs.
Uses dim_ama_params for human-readable labels instead of raw params_hash values.

Two modes:
  - Per-Asset Deep Dive: value curves, derivatives, ER (KAMA only), AMA vs EMA
  - Cross-Asset Comparison: two assets on the same chart with different line styles

Auto-refreshes every 15 minutes via @st.fragment(run_every=900).

NOTE: Do NOT call st.set_page_config() here -- it is called in the main app
entry point (app.py / Home.py). Calling it again from a page script raises a
StreamlitAPIException.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from ta_lab2.dashboard.charts import chart_download_button
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.ama import (
    load_ama_curves,
    load_ama_params_catalogue,
    load_ema_for_comparison,
)
from ta_lab2.dashboard.queries.research import load_asset_list, load_tf_list

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AUTO_REFRESH_SECONDS = 900  # 15 minutes

_INDICATOR_OPTIONS = ["KAMA", "DEMA", "HMA", "TEMA"]
_PERIOD_OPTIONS = ["Short (1Y)", "Medium (2Y)", "Long (3Y)", "Custom"]
_PERIOD_DAYS = {"Short (1Y)": 365, "Medium (2Y)": 730, "Long (3Y)": 1095}
_DERIVATIVE_OPTIONS = ["d1", "d2", "d1_roll", "d2_roll"]
_DEFAULT_EMA_PERIODS = [21, 50]
_ALL_EMA_PERIODS = [9, 21, 50, 200]

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("AMA/EMA Inspector")
st.caption(
    "Inspect adaptive moving average behavior per asset -- efficiency ratio "
    "(KAMA only), derivative curves, and AMA vs fixed EMA comparison. "
    "Auto-refreshes every 15 minutes."
)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:  # noqa: BLE001
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Load dimension data (needed by sidebar)
# ---------------------------------------------------------------------------

try:
    assets_df = load_asset_list(engine)
    tf_list = load_tf_list(engine)
    params_catalogue = load_ama_params_catalogue(engine)
except Exception as exc:  # noqa: BLE001
    st.error(f"Error loading dimension data: {exc}")
    st.stop()

if assets_df.empty:
    st.warning("No assets found in dim_assets. Run data pipeline first.")
    st.stop()

if not tf_list:
    st.warning("No timeframes found in dim_timeframe.")
    st.stop()

# Build asset lookup
asset_options = dict(zip(assets_df["symbol"], assets_df["id"]))
symbol_list = list(asset_options.keys())

# Default tf index
default_tf_idx = tf_list.index("1D") if "1D" in tf_list else 0

# ---------------------------------------------------------------------------
# Sidebar controls (outside fragment -- widgets must be at module level)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("AMA Inspector Controls")

    # Mode toggle
    mode = st.radio(
        "Mode",
        ["Per-Asset Deep Dive", "Cross-Asset Comparison"],
        key="ama_mode",
    )

    # Asset A selector
    selected_symbol = st.selectbox(
        "Asset",
        symbol_list,
        index=0,
        key="ama_asset",
    )
    selected_id = asset_options[selected_symbol]

    # Asset B selector (only in cross-asset mode)
    if mode == "Cross-Asset Comparison":
        # Default to second asset in list if possible
        default_b_idx = 1 if len(symbol_list) > 1 else 0
        compare_symbol = st.selectbox(
            "Compare With",
            symbol_list,
            index=default_b_idx,
            key="ama_compare_asset",
        )
        compare_id = asset_options[compare_symbol]
    else:
        compare_symbol = None
        compare_id = None

    # Timeframe selector
    selected_tf = st.selectbox(
        "Timeframe",
        tf_list,
        index=default_tf_idx,
        key="ama_tf",
    )

    # Indicator selector
    selected_indicator = st.selectbox(
        "Indicator",
        _INDICATOR_OPTIONS,
        index=0,
        key="ama_indicator",
    )

    # Period range presets
    period_choice = st.radio(
        "Period Range",
        _PERIOD_OPTIONS,
        index=0,
        key="ama_period_range",
    )
    if period_choice == "Custom":
        days_back = st.number_input(
            "Custom days",
            min_value=30,
            max_value=3650,
            value=365,
            step=30,
            key="ama_custom_days",
        )
    else:
        days_back = _PERIOD_DAYS[period_choice]

    # EMA comparison periods
    ema_periods = st.multiselect(
        "EMA Comparison Periods",
        _ALL_EMA_PERIODS,
        default=_DEFAULT_EMA_PERIODS,
        key="ama_ema_periods",
    )
    if not ema_periods:
        ema_periods = _DEFAULT_EMA_PERIODS

    # Derivative toggles (per-asset mode only)
    if mode == "Per-Asset Deep Dive":
        selected_derivatives = st.multiselect(
            "Derivative Curves",
            _DERIVATIVE_OPTIONS,
            default=["d1", "d2"],
            key="ama_derivatives",
        )

        # Comparison view toggle (per-asset mode only)
        comparison_view = st.radio(
            "Comparison View",
            ["Overlay", "Side by Side"],
            index=0,
            key="ama_comparison_view",
        )
    else:
        selected_derivatives = ["d1", "d2"]
        comparison_view = "Overlay"


# ---------------------------------------------------------------------------
# Auto-refreshing content fragment
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _ama_inspector_content(
    _engine,
    mode,
    selected_symbol,
    selected_id,
    compare_symbol,
    compare_id,
    selected_tf,
    selected_indicator,
    days_back,
    ema_periods,
    selected_derivatives,
    comparison_view,
    params_catalogue,
):
    """Auto-refreshing AMA/EMA Inspector content."""

    if mode == "Per-Asset Deep Dive":
        _render_per_asset_mode(
            _engine,
            selected_symbol,
            selected_id,
            selected_tf,
            selected_indicator,
            days_back,
            ema_periods,
            selected_derivatives,
            comparison_view,
            params_catalogue,
        )
    else:
        _render_cross_asset_mode(
            _engine,
            selected_symbol,
            selected_id,
            compare_symbol,
            compare_id,
            selected_tf,
            selected_indicator,
            days_back,
            params_catalogue,
        )

    st.caption(f"Auto-refreshes every {AUTO_REFRESH_SECONDS // 60} minutes")


# ---------------------------------------------------------------------------
# Per-Asset Deep Dive mode renderer
# ---------------------------------------------------------------------------


def _render_per_asset_mode(
    _engine,
    symbol,
    asset_id,
    tf,
    indicator,
    days_back,
    ema_periods,
    selected_derivatives,
    comparison_view,
    params_catalogue,
):
    """Render per-asset deep-dive view with four sections."""

    # -----------------------------------------------------------------------
    # Load AMA curves
    # -----------------------------------------------------------------------
    try:
        ama_df = load_ama_curves(_engine, asset_id, tf, indicator, days_back)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load AMA curves: {exc}")
        ama_df = None

    # -----------------------------------------------------------------------
    # Section 1: AMA Value Chart
    # -----------------------------------------------------------------------
    st.subheader(f"AMA Value Curves -- {symbol} ({tf}) [{indicator}]")

    try:
        if ama_df is None or ama_df.empty:
            st.info(
                f"No AMA data for {symbol} ({tf}, {indicator}). "
                "Run AMA refresh pipeline first."
            )
        else:
            fig_ama = go.Figure()
            labels = ama_df["label"].unique() if "label" in ama_df.columns else []
            for lbl in sorted(labels):
                subset = ama_df[ama_df["label"] == lbl]
                fig_ama.add_trace(
                    go.Scatter(
                        x=subset["ts"],
                        y=subset["ama"],
                        mode="lines",
                        name=lbl,
                        line=dict(width=1.5),
                    )
                )
            fig_ama.update_layout(
                template="plotly_dark",
                title=f"{symbol} {indicator} AMA Values ({tf})",
                xaxis_title="Date",
                yaxis_title="AMA Value",
                height=400,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=60, r=40, t=60, b=60),
            )
            st.plotly_chart(
                fig_ama, use_container_width=True, theme=None, key="ama_value_chart"
            )
            chart_download_button(
                fig_ama,
                "Download AMA Value Chart",
                f"ama_values_{symbol}_{tf}_{indicator}.html",
            )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render AMA value chart: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Section 2: Derivative Curves
    # -----------------------------------------------------------------------
    st.subheader(f"Derivative Curves -- {symbol} ({tf}) [{indicator}]")

    try:
        if ama_df is None or ama_df.empty:
            st.info("No AMA data available for derivative curves.")
        elif not selected_derivatives:
            st.info("Select at least one derivative curve from the sidebar.")
        else:
            fig_deriv = go.Figure()
            labels = ama_df["label"].unique() if "label" in ama_df.columns else []

            for lbl in sorted(labels):
                subset = ama_df[ama_df["label"] == lbl]
                for deriv_col in selected_derivatives:
                    if deriv_col in subset.columns:
                        fig_deriv.add_trace(
                            go.Scatter(
                                x=subset["ts"],
                                y=subset[deriv_col],
                                mode="lines",
                                name=f"{lbl} {deriv_col}",
                                line=dict(width=1),
                            )
                        )

            # Add zero reference lines for d1/d2
            if "d1" in selected_derivatives or "d2" in selected_derivatives:
                fig_deriv.add_hline(
                    y=0,
                    line_dash="dash",
                    line_color="rgba(255,255,255,0.3)",
                    annotation_text="Zero",
                )

            fig_deriv.update_layout(
                template="plotly_dark",
                title=f"{symbol} {indicator} Derivatives ({tf})",
                xaxis_title="Date",
                yaxis_title="Derivative Value",
                height=350,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=60, r=40, t=60, b=60),
            )
            st.plotly_chart(
                fig_deriv, use_container_width=True, theme=None, key="ama_deriv_chart"
            )
            chart_download_button(
                fig_deriv,
                "Download Derivative Chart",
                f"ama_derivatives_{symbol}_{tf}_{indicator}.html",
            )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render derivative chart: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Section 3: Efficiency Ratio (KAMA only)
    # -----------------------------------------------------------------------
    st.subheader(f"Efficiency Ratio -- {symbol} ({tf})")

    try:
        if indicator != "KAMA":
            st.info(
                "Efficiency Ratio is only computed for KAMA. "
                "Select KAMA indicator to view ER."
            )
        elif ama_df is None or ama_df.empty:
            st.info("No AMA data available for Efficiency Ratio.")
        elif "er" not in ama_df.columns or ama_df["er"].isna().all():
            st.info("Efficiency Ratio (er) column is empty for this selection.")
        else:
            fig_er = go.Figure()
            labels = ama_df["label"].unique() if "label" in ama_df.columns else []
            for lbl in sorted(labels):
                subset = ama_df[ama_df["label"] == lbl].dropna(subset=["er"])
                if subset.empty:
                    continue
                fig_er.add_trace(
                    go.Scatter(
                        x=subset["ts"],
                        y=subset["er"],
                        mode="lines",
                        name=f"{lbl} ER",
                        line=dict(width=1.5),
                    )
                )

            # Reference lines: 0.3 (choppy) and 0.7 (trending)
            fig_er.add_hline(
                y=0.3,
                line_dash="dot",
                line_color="rgba(255,80,80,0.6)",
                annotation_text="Choppy (0.3)",
                annotation_position="bottom right",
            )
            fig_er.add_hline(
                y=0.7,
                line_dash="dot",
                line_color="rgba(80,255,80,0.6)",
                annotation_text="Trending (0.7)",
                annotation_position="top right",
            )

            fig_er.update_layout(
                template="plotly_dark",
                title=f"{symbol} KAMA Efficiency Ratio ({tf})",
                xaxis_title="Date",
                yaxis_title="Efficiency Ratio (0-1)",
                yaxis=dict(range=[-0.05, 1.05]),
                height=300,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=60, r=40, t=60, b=60),
            )
            st.plotly_chart(
                fig_er, use_container_width=True, theme=None, key="ama_er_chart"
            )
            chart_download_button(
                fig_er,
                "Download ER Chart",
                f"ama_er_{symbol}_{tf}.html",
            )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render Efficiency Ratio chart: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Section 4: AMA vs EMA Comparison
    # -----------------------------------------------------------------------
    st.subheader(f"AMA vs EMA Comparison -- {symbol} ({tf})")

    try:
        ema_df = load_ema_for_comparison(_engine, asset_id, tf, ema_periods, days_back)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load EMA data: {exc}")
        ema_df = None

    try:
        if comparison_view == "Overlay":
            _render_comparison_overlay(
                ama_df, ema_df, symbol, tf, indicator, key_suffix="overlay"
            )
        else:
            col_left, col_right = st.columns([1, 1])
            with col_left:
                st.caption(f"AMA ({indicator})")
                _render_ama_only_chart(
                    ama_df, symbol, tf, indicator, key_suffix="side_ama"
                )
            with col_right:
                st.caption("EMA")
                _render_ema_only_chart(ema_df, symbol, tf, key_suffix="side_ema")
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render AMA vs EMA comparison: {exc}")


# ---------------------------------------------------------------------------
# Cross-Asset Comparison mode renderer
# ---------------------------------------------------------------------------


def _render_cross_asset_mode(
    _engine,
    symbol_a,
    asset_id_a,
    symbol_b,
    asset_id_b,
    tf,
    indicator,
    days_back,
    params_catalogue,
):
    """Render cross-asset comparison -- both assets on the same AMA chart."""
    st.subheader(
        f"Cross-Asset Comparison -- {symbol_a} vs {symbol_b} ({tf}) [{indicator}]"
    )

    if symbol_b is None or asset_id_b is None:
        st.info("Select a second asset in the sidebar to compare.")
        return

    # Load AMA for both assets
    try:
        ama_a = load_ama_curves(_engine, asset_id_a, tf, indicator, days_back)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load AMA for {symbol_a}: {exc}")
        ama_a = None

    try:
        ama_b = load_ama_curves(_engine, asset_id_b, tf, indicator, days_back)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load AMA for {symbol_b}: {exc}")
        ama_b = None

    try:
        fig = go.Figure()

        # Plot asset A as solid lines
        if ama_a is not None and not ama_a.empty:
            labels_a = ama_a["label"].unique() if "label" in ama_a.columns else []
            for lbl in sorted(labels_a):
                subset = ama_a[ama_a["label"] == lbl]
                fig.add_trace(
                    go.Scatter(
                        x=subset["ts"],
                        y=subset["ama"],
                        mode="lines",
                        name=f"{symbol_a} {lbl}",
                        line=dict(width=1.5, dash="solid"),
                    )
                )
        else:
            st.info(f"No AMA data for {symbol_a} ({tf}, {indicator}).")

        # Plot asset B as dashed lines
        if ama_b is not None and not ama_b.empty:
            labels_b = ama_b["label"].unique() if "label" in ama_b.columns else []
            for lbl in sorted(labels_b):
                subset = ama_b[ama_b["label"] == lbl]
                fig.add_trace(
                    go.Scatter(
                        x=subset["ts"],
                        y=subset["ama"],
                        mode="lines",
                        name=f"{symbol_b} {lbl}",
                        line=dict(width=1.5, dash="dash"),
                        yaxis="y2",
                    )
                )
        else:
            st.info(f"No AMA data for {symbol_b} ({tf}, {indicator}).")

        if (ama_a is not None and not ama_a.empty) or (
            ama_b is not None and not ama_b.empty
        ):
            fig.update_layout(
                template="plotly_dark",
                title=f"{symbol_a} vs {symbol_b} {indicator} AMA ({tf})",
                xaxis_title="Date",
                yaxis=dict(title=f"{symbol_a} Price"),
                yaxis2=dict(
                    title=f"{symbol_b} Price",
                    overlaying="y",
                    side="right",
                ),
                height=500,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=60, r=80, t=60, b=60),
            )
            st.plotly_chart(
                fig, use_container_width=True, theme=None, key="ama_cross_asset_chart"
            )
            chart_download_button(
                fig,
                "Download Cross-Asset Chart",
                f"ama_cross_{symbol_a}_{symbol_b}_{tf}_{indicator}.html",
            )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render cross-asset comparison: {exc}")


# ---------------------------------------------------------------------------
# Comparison chart helpers
# ---------------------------------------------------------------------------


def _render_comparison_overlay(ama_df, ema_df, symbol, tf, indicator, key_suffix=""):
    """Render AMA and EMA on the same chart (overlay mode)."""
    fig = go.Figure()

    # AMA traces -- solid lines
    if ama_df is not None and not ama_df.empty:
        labels = ama_df["label"].unique() if "label" in ama_df.columns else []
        for lbl in sorted(labels):
            subset = ama_df[ama_df["label"] == lbl]
            fig.add_trace(
                go.Scatter(
                    x=subset["ts"],
                    y=subset["ama"],
                    mode="lines",
                    name=f"{indicator} {lbl}",
                    line=dict(width=2, dash="solid"),
                )
            )
    else:
        st.info(f"No AMA data for overlay comparison ({symbol}, {tf}, {indicator}).")

    # EMA traces -- dashed lines
    if ema_df is not None and not ema_df.empty:
        periods = ema_df["period"].unique() if "period" in ema_df.columns else []
        for period in sorted(periods):
            subset = ema_df[ema_df["period"] == period]
            fig.add_trace(
                go.Scatter(
                    x=subset["ts"],
                    y=subset["ema"],
                    mode="lines",
                    name=f"EMA({period})",
                    line=dict(width=1.5, dash="dash"),
                )
            )
    else:
        st.info("No EMA data available for the selected periods.")

    if (ama_df is not None and not ama_df.empty) or (
        ema_df is not None and not ema_df.empty
    ):
        fig.update_layout(
            template="plotly_dark",
            title=f"{symbol} {indicator} vs EMA ({tf})",
            xaxis_title="Date",
            yaxis_title="Price",
            height=400,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=60, r=40, t=60, b=60),
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            theme=None,
            key=f"ama_vs_ema_overlay_{key_suffix}",
        )
        chart_download_button(
            fig,
            "Download AMA vs EMA Chart",
            f"ama_vs_ema_{symbol}_{tf}_{indicator}.html",
        )


def _render_ama_only_chart(ama_df, symbol, tf, indicator, key_suffix=""):
    """Render AMA-only chart for side-by-side comparison."""
    if ama_df is None or ama_df.empty:
        st.info(f"No AMA data for {symbol} ({tf}, {indicator}).")
        return

    fig = go.Figure()
    labels = ama_df["label"].unique() if "label" in ama_df.columns else []
    for lbl in sorted(labels):
        subset = ama_df[ama_df["label"] == lbl]
        fig.add_trace(
            go.Scatter(
                x=subset["ts"],
                y=subset["ama"],
                mode="lines",
                name=lbl,
                line=dict(width=1.5),
            )
        )
    fig.update_layout(
        template="plotly_dark",
        title=f"{symbol} {indicator} ({tf})",
        xaxis_title="Date",
        yaxis_title="AMA",
        height=350,
        margin=dict(l=60, r=40, t=50, b=60),
    )
    st.plotly_chart(
        fig, use_container_width=True, theme=None, key=f"ama_side_{key_suffix}"
    )


def _render_ema_only_chart(ema_df, symbol, tf, key_suffix=""):
    """Render EMA-only chart for side-by-side comparison."""
    if ema_df is None or ema_df.empty:
        st.info(f"No EMA data for {symbol} ({tf}).")
        return

    fig = go.Figure()
    periods = ema_df["period"].unique() if "period" in ema_df.columns else []
    for period in sorted(periods):
        subset = ema_df[ema_df["period"] == period]
        fig.add_trace(
            go.Scatter(
                x=subset["ts"],
                y=subset["ema"],
                mode="lines",
                name=f"EMA({period})",
                line=dict(width=1.5),
            )
        )
    fig.update_layout(
        template="plotly_dark",
        title=f"{symbol} EMA ({tf})",
        xaxis_title="Date",
        yaxis_title="EMA",
        height=350,
        margin=dict(l=60, r=40, t=50, b=60),
    )
    st.plotly_chart(
        fig, use_container_width=True, theme=None, key=f"ema_side_{key_suffix}"
    )


# ---------------------------------------------------------------------------
# Invoke fragment
# ---------------------------------------------------------------------------

_ama_inspector_content(
    engine,
    mode,
    selected_symbol,
    selected_id,
    compare_symbol,
    compare_id,
    selected_tf,
    selected_indicator,
    days_back,
    ema_periods,
    selected_derivatives,
    comparison_view,
    params_catalogue,
)
