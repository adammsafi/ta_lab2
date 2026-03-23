# -*- coding: utf-8 -*-
"""
Hyperliquid Perps page -- funding rates, OI, and candle charts.

Sections:
  1. Top Perps Dashboard -- landing table + metric cards for top 3 assets
  2. Funding Rate Analysis -- single asset time series + multi-asset comparison
  3. Funding Rate Heatmap -- assets x days, color-coded by avg funding
  4. Candle Chart + OI -- daily candlestick with Coinalyze OI overlay

NOTE: Do NOT call st.set_page_config() here -- only in the main app entry point.
Sidebar controls live OUTSIDE @st.fragment (widgets cannot be inside a fragment).
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from ta_lab2.dashboard.charts import chart_download_button
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.perps import (
    load_hl_candles,
    load_hl_funding_heatmap,
    load_hl_funding_history,
    load_hl_oi_timeseries,
    load_hl_perp_list,
    load_hl_top_perps,
)

AUTO_REFRESH_SECONDS = 900

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Perps")
st.caption("Hyperliquid perpetuals: funding rates, open interest, candle charts")

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Load perp list for dropdowns (needed before sidebar)
# ---------------------------------------------------------------------------

try:
    perp_list_df = load_hl_perp_list(engine)
except Exception as exc:
    st.error(f"Error loading perp list: {exc}")
    st.stop()

if perp_list_df.empty:
    st.warning("No Hyperliquid perp assets found. Run sync_hl_from_vm first.")
    st.stop()

perp_options: dict[str, int] = dict(
    zip(perp_list_df["symbol"], perp_list_df["asset_id"])
)
perp_symbols = list(perp_options.keys())
_btc_idx = perp_symbols.index("BTC") if "BTC" in perp_symbols else 0
_default_multi = [s for s in ["BTC", "ETH", "SOL"] if s in perp_symbols]
if not _default_multi:
    _default_multi = perp_symbols[:3] if len(perp_symbols) >= 3 else perp_symbols

# ---------------------------------------------------------------------------
# Sidebar controls (global filters only)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Perps Filters")

    days_back = st.slider(
        "Days back",
        min_value=7,
        max_value=90,
        value=30,
        step=1,
        key="perps_days_back",
    )

    top_n_heatmap = st.slider(
        "Top N perps (heatmap)",
        min_value=5,
        max_value=50,
        value=20,
        step=5,
        key="perps_top_n_heatmap",
    )

# ---------------------------------------------------------------------------
# Inline asset selectors (OUTSIDE @st.fragment -- widgets cannot be inside)
# ---------------------------------------------------------------------------

_sel_col1, _sel_col2, _sel_col3 = st.columns(3)

with _sel_col1:
    single_symbol = st.selectbox(
        "Funding Rate Asset",
        perp_symbols,
        index=_btc_idx,
        key="perps_single_symbol",
    )
    single_asset_id = perp_options[single_symbol]

with _sel_col2:
    multi_symbols = st.multiselect(
        "Multi-Asset Comparison",
        perp_symbols,
        default=_default_multi,
        max_selections=5,
        key="perps_multi_symbols",
    )
    multi_asset_ids = [perp_options[s] for s in multi_symbols]

with _sel_col3:
    candle_symbol = st.selectbox(
        "Candle Chart Asset",
        perp_symbols,
        index=_btc_idx,
        key="perps_candle_symbol",
    )
    candle_asset_id = perp_options[candle_symbol]

st.divider()


# ---------------------------------------------------------------------------
# Fragment: all data loading and rendering auto-refreshes every 15 min
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _perps_content(
    _engine,
    days_back: int,
    top_n_heatmap: int,
    single_asset_id: int,
    single_symbol: str,
    multi_asset_ids: list[int],
    multi_symbols: list[str],
    candle_asset_id: int,
    candle_symbol: str,
) -> None:
    """Render all Perps page sections. Refreshes every 15 minutes."""

    # -----------------------------------------------------------------------
    # Section 1: Top Perps Dashboard
    # -----------------------------------------------------------------------

    st.subheader("Top Perps by Volume")

    try:
        top_df = load_hl_top_perps(_engine, limit=15)

        if top_df.empty:
            st.info("No top perps data available. Sync Hyperliquid data first.")
        else:
            # Metric cards for top 3
            top3 = top_df.head(3)
            cols = st.columns(3)
            for i, (col, row) in enumerate(zip(cols, top3.itertuples())):
                vol_str = (
                    f"${row.day_ntl_vlm / 1e6:,.1f}M"
                    if row.day_ntl_vlm is not None and row.day_ntl_vlm >= 1e6
                    else f"${row.day_ntl_vlm:,.0f}"
                    if row.day_ntl_vlm is not None
                    else "N/A"
                )
                funding_str = (
                    f"{float(row.funding) * 100:.4f}%"
                    if row.funding is not None
                    else "N/A"
                )
                col.metric(
                    label=f"#{i + 1} {row.symbol}",
                    value=vol_str,
                    delta=f"Funding: {funding_str}",
                )

            st.divider()

            # Full table with formatting
            display_df = top_df.copy()

            if "day_ntl_vlm" in display_df.columns:
                display_df["volume_24h"] = display_df["day_ntl_vlm"].apply(
                    lambda v: f"${v / 1e6:.1f}M" if v is not None else "N/A"
                )
            if "funding" in display_df.columns:
                display_df["funding_rate"] = display_df["funding"].apply(
                    lambda v: f"{float(v) * 100:.4f}%" if v is not None else "N/A"
                )
            if "mark_px" in display_df.columns:
                display_df["mark_price"] = display_df["mark_px"].apply(
                    lambda v: f"${float(v):,.2f}" if v is not None else "N/A"
                )
            if "open_interest" in display_df.columns:
                display_df["oi_base"] = display_df["open_interest"].apply(
                    lambda v: f"{float(v):,.2f}" if v is not None else "N/A"
                )
            if (
                "open_interest" in display_df.columns
                and "mark_px" in display_df.columns
            ):
                display_df["oi_usd"] = display_df.apply(
                    lambda r: f"${float(r['open_interest']) * float(r['mark_px']):,.0f}"
                    if r["open_interest"] is not None and r["mark_px"] is not None
                    else "N/A",
                    axis=1,
                )

            show_cols = [
                c
                for c in [
                    "symbol",
                    "volume_24h",
                    "funding_rate",
                    "oi_base",
                    "oi_usd",
                    "mark_price",
                    "max_leverage",
                ]
                if c in display_df.columns
            ]
            st.dataframe(
                display_df[show_cols] if show_cols else display_df,
                use_container_width=True,
                key="perps_top_table",
            )
    except Exception as exc:
        st.warning(f"Could not load top perps data: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Section 2: Funding Rate Analysis
    # -----------------------------------------------------------------------

    st.subheader("Funding Rate Analysis")

    tab_single, tab_multi = st.tabs(["Single Asset", "Multi-Asset Comparison"])

    with tab_single:
        try:
            funding_df = load_hl_funding_history(
                _engine, [single_asset_id], days_back=days_back
            )

            if funding_df.empty:
                st.info(
                    f"No funding rate data for {single_symbol} "
                    f"in the last {days_back} days."
                )
            else:
                fig_funding = go.Figure()
                fig_funding.add_trace(
                    go.Scatter(
                        x=funding_df["ts"].tolist(),
                        y=funding_df["funding_rate"].tolist(),
                        mode="lines",
                        name=single_symbol,
                        line={"color": "#00cc88", "width": 1.5},
                    )
                )
                fig_funding.add_hline(
                    y=0,
                    line_dash="dash",
                    line_color="rgba(255,255,255,0.4)",
                    annotation_text="zero",
                )
                fig_funding.update_layout(
                    template="plotly_dark",
                    title=f"{single_symbol} Funding Rate (last {days_back} days)",
                    xaxis_title="Date",
                    yaxis_title="8h Funding Rate",
                    height=400,
                    margin={"l": 50, "r": 20, "t": 50, "b": 40},
                )
                st.plotly_chart(
                    fig_funding,
                    theme=None,
                    key="perps_funding_single_chart",
                    use_container_width=True,
                )
                chart_download_button(
                    fig_funding,
                    "Download Chart (HTML)",
                    f"perps_funding_{single_symbol}_{days_back}d.html",
                )
        except Exception as exc:
            st.warning(f"Could not render single-asset funding chart: {exc}")

    with tab_multi:
        if not multi_asset_ids:
            st.info("Select up to 5 perps in the sidebar for comparison.")
        else:
            try:
                multi_funding_df = load_hl_funding_history(
                    _engine, multi_asset_ids, days_back=days_back
                )

                if multi_funding_df.empty:
                    st.info(
                        "No funding rate data for selected assets "
                        f"in the last {days_back} days."
                    )
                else:
                    colors = [
                        "#00cc88",
                        "#ff6b6b",
                        "#4dabf7",
                        "#ffd43b",
                        "#cc5de8",
                    ]
                    fig_multi = go.Figure()

                    for i, sym in enumerate(multi_symbols):
                        asset_id = perp_options.get(sym)
                        if asset_id is None:
                            continue
                        subset = multi_funding_df[
                            multi_funding_df["asset_id"] == asset_id
                        ]
                        if subset.empty:
                            continue
                        fig_multi.add_trace(
                            go.Scatter(
                                x=subset["ts"].tolist(),
                                y=subset["funding_rate"].tolist(),
                                mode="lines",
                                name=sym,
                                line={"color": colors[i % len(colors)], "width": 1.5},
                            )
                        )

                    fig_multi.add_hline(
                        y=0,
                        line_dash="dash",
                        line_color="rgba(255,255,255,0.4)",
                    )
                    fig_multi.update_layout(
                        template="plotly_dark",
                        title=f"Funding Rate Comparison (last {days_back} days)",
                        xaxis_title="Date",
                        yaxis_title="8h Funding Rate",
                        height=450,
                        margin={"l": 50, "r": 20, "t": 50, "b": 40},
                        legend={"orientation": "h", "yanchor": "bottom", "y": -0.25},
                    )
                    st.plotly_chart(
                        fig_multi,
                        theme=None,
                        key="perps_funding_multi_chart",
                        use_container_width=True,
                    )
                    chart_download_button(
                        fig_multi,
                        "Download Chart (HTML)",
                        f"perps_funding_multi_{days_back}d.html",
                    )
            except Exception as exc:
                st.warning(f"Could not render multi-asset funding chart: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Section 3: Funding Rate Heatmap
    # -----------------------------------------------------------------------

    st.subheader(f"Funding Rate Heatmap (Top {top_n_heatmap} by Volume)")

    try:
        heatmap_df = load_hl_funding_heatmap(
            _engine, days_back=days_back, top_n=top_n_heatmap
        )

        if heatmap_df.empty:
            st.info(
                f"No heatmap data for the last {days_back} days. "
                "Funding history may be limited."
            )
        else:
            # Pivot: rows = symbol, columns = date
            pivot = heatmap_df.pivot_table(
                index="symbol",
                columns="date",
                values="avg_funding_rate",
                aggfunc="mean",
            )
            pivot.columns = [str(c) for c in pivot.columns]
            symbols_ordered = pivot.index.tolist()
            dates_ordered = pivot.columns.tolist()
            z_values = pivot.values.tolist()

            # Format text for each cell
            text_values = [
                [
                    f"{v * 100:.4f}%" if v is not None and str(v) != "nan" else ""
                    for v in row
                ]
                for row in z_values
            ]

            fig_heatmap = go.Figure(
                data=go.Heatmap(
                    z=z_values,
                    x=dates_ordered,
                    y=symbols_ordered,
                    colorscale="RdBu",
                    zmid=0,
                    text=text_values,
                    texttemplate="%{text}",
                    textfont={"size": 8},
                    colorbar={"title": "Avg 8h Funding"},
                    reversescale=True,
                )
            )
            fig_heatmap.update_layout(
                template="plotly_dark",
                title=f"Daily Average Funding Rate Heatmap (last {days_back} days)",
                xaxis_title="Date",
                yaxis_title="Asset",
                height=max(350, len(symbols_ordered) * 22 + 100),
                margin={"l": 80, "r": 20, "t": 50, "b": 60},
                xaxis={"tickangle": -45},
            )
            st.plotly_chart(
                fig_heatmap,
                theme=None,
                key="perps_funding_heatmap",
                use_container_width=True,
            )
            chart_download_button(
                fig_heatmap,
                "Download Heatmap (HTML)",
                f"perps_funding_heatmap_{days_back}d.html",
            )
    except Exception as exc:
        st.warning(f"Could not render funding heatmap: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Section 4: Candle Chart + OI
    # -----------------------------------------------------------------------

    st.subheader(f"Daily Candles + OI -- {candle_symbol}")

    try:
        candle_df = load_hl_candles(_engine, candle_asset_id, days_back=days_back)
        oi_df = load_hl_oi_timeseries(_engine, candle_asset_id, days_back=days_back)

        if candle_df.empty:
            st.info(
                f"No daily candle data for {candle_symbol} "
                f"in the last {days_back} days."
            )
        else:
            has_oi = not oi_df.empty

            if has_oi:
                fig_candle = make_subplots(
                    rows=2,
                    cols=1,
                    shared_xaxes=True,
                    vertical_spacing=0.05,
                    row_heights=[0.7, 0.3],
                    subplot_titles=[
                        f"{candle_symbol} Daily Candles",
                        "Open Interest (Coinalyze)",
                    ],
                )
            else:
                fig_candle = make_subplots(rows=1, cols=1)

            # Candlestick trace
            fig_candle.add_trace(
                go.Candlestick(
                    x=candle_df["ts"].tolist(),
                    open=candle_df["open"].tolist(),
                    high=candle_df["high"].tolist(),
                    low=candle_df["low"].tolist(),
                    close=candle_df["close"].tolist(),
                    name=candle_symbol,
                    increasing_line_color="#00cc88",
                    decreasing_line_color="#ff6b6b",
                ),
                row=1,
                col=1,
            )

            # Disable rangeslider on candle xaxis
            fig_candle.update_xaxes(rangeslider_visible=False, row=1, col=1)

            if has_oi:
                fig_candle.add_trace(
                    go.Scatter(
                        x=oi_df["ts"].tolist(),
                        y=oi_df["oi_close"].tolist(),
                        mode="lines",
                        name="OI Close",
                        line={"color": "#4dabf7", "width": 1.5},
                        fill="tozeroy",
                        fillcolor="rgba(77,171,247,0.15)",
                    ),
                    row=2,
                    col=1,
                )
                fig_candle.update_xaxes(rangeslider_visible=False, row=2, col=1)

            fig_candle.update_layout(
                template="plotly_dark",
                height=550 if has_oi else 400,
                margin={"l": 50, "r": 20, "t": 50, "b": 40},
                showlegend=True,
                legend={"orientation": "h", "yanchor": "bottom", "y": -0.15},
            )

            st.plotly_chart(
                fig_candle,
                theme=None,
                key="perps_candle_chart",
                use_container_width=True,
            )
            chart_download_button(
                fig_candle,
                "Download Candles (HTML)",
                f"perps_candles_{candle_symbol}_{days_back}d.html",
            )

            if not has_oi:
                st.info(
                    f"No Coinalyze OI data available for {candle_symbol}. "
                    "OI history is available for major perp assets only."
                )

    except Exception as exc:
        st.warning(f"Could not render candle chart: {exc}")


# ---------------------------------------------------------------------------
# Run the fragment
# ---------------------------------------------------------------------------

_perps_content(
    engine,
    days_back=days_back,
    top_n_heatmap=top_n_heatmap,
    single_asset_id=single_asset_id,
    single_symbol=single_symbol,
    multi_asset_ids=multi_asset_ids,
    multi_symbols=multi_symbols,
    candle_asset_id=candle_asset_id,
    candle_symbol=candle_symbol,
)
