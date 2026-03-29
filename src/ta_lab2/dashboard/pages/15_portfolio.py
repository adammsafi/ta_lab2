# -*- coding: utf-8 -*-
"""
Portfolio Allocation page -- optimizer weights, position sizing, exposure.

Queries the portfolio_allocations table for live allocation data and renders:
  1. Current Allocation -- treemap or stacked bar toggle
  2. Weight History     -- stacked area chart or table toggle
  3. Position Sizing    -- bet sizes + portfolio metrics
  4. Exposure Summary   -- full allocation table

NOTE: Do NOT call st.set_page_config() here -- only in the main app entry point.
Sidebar controls live OUTSIDE @st.fragment (widgets cannot be inside a fragment).
"""

from __future__ import annotations

import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ta_lab2.dashboard.charts import chart_download_button
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.portfolio import (
    load_allocation_history,
    load_available_optimizers,
    load_latest_allocations,
)
from ta_lab2.dashboard.queries.trading import load_starting_capital

AUTO_REFRESH_SECONDS = 900

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Page header (outside fragment -- always visible)
# ---------------------------------------------------------------------------

st.header("Portfolio Allocation")
st.caption(
    "Optimizer weights, position sizing, and exposure from portfolio_allocations"
)

# ---------------------------------------------------------------------------
# Sidebar controls (OUTSIDE @st.fragment -- widgets cannot be inside a fragment)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Portfolio Controls")

    as_of_date = st.date_input(
        "As of Date",
        value=datetime.date.today(),
        key="portfolio_as_of_date",
    )

    optimizers = load_available_optimizers(engine)
    if not optimizers:
        st.info(
            "No portfolio allocations found. Run the portfolio allocation "
            "refresh to populate data:\n\n"
            "`python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations "
            "--ids all --tf 1D`"
        )
        st.stop()

    selected_optimizer = st.selectbox(
        "Optimizer",
        options=optimizers,
        index=optimizers.index("hrp") if "hrp" in optimizers else 0,
        key="portfolio_optimizer",
    )


# ---------------------------------------------------------------------------
# Fragment: live data rendering (auto-refreshes every 15 min)
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _portfolio_content(
    _engine,
    as_of_date: datetime.date,
    selected_optimizer: str,
) -> None:
    """Render all Portfolio Allocation page sections. Refreshes every 15 minutes."""

    # -----------------------------------------------------------------------
    # Load live data
    # -----------------------------------------------------------------------

    alloc_df = load_latest_allocations(_engine, optimizer=selected_optimizer)

    if alloc_df.empty:
        st.info(
            "No portfolio allocations found. Run:\n\n"
            "`python -m ta_lab2.scripts.portfolio.refresh_portfolio_allocations "
            "--ids all --tf 1D`"
        )
        return

    alloc_df["weight_pct"] = alloc_df["weight"] * 100.0

    # Portfolio NAV from executor config, fallback to 100k
    portfolio_nav = load_starting_capital(_engine)
    if portfolio_nav == 0:
        portfolio_nav = 100_000.0

    alloc_df["bet_size_usd"] = alloc_df["weight"] * portfolio_nav

    # -----------------------------------------------------------------------
    # Section 1: Current Allocation
    # -----------------------------------------------------------------------

    st.subheader("Current Allocation")

    view_toggle = st.radio(
        "View",
        ["Treemap", "Stacked Bar"],
        horizontal=True,
        key="portfolio_view_toggle",
    )

    if view_toggle == "Treemap":
        # Flat treemap: each asset is a root-level tile
        hover_parts = []
        for _, row in alloc_df.iterrows():
            regime = row.get("regime_label") or "N/A"
            hover_parts.append(
                f"<b>{row['symbol']}</b><br>"
                f"Weight: {row['weight_pct']:.2f}%<br>"
                f"Regime: {regime}"
            )

        fig_treemap = go.Figure(
            go.Treemap(
                labels=alloc_df["symbol"].tolist(),
                values=alloc_df["weight_pct"].tolist(),
                parents=[""] * len(alloc_df),
                texttemplate="%{label}<br>%{value:.1f}%",
                hovertext=hover_parts,
                hoverinfo="text",
                marker=dict(
                    colorscale="Greens",
                    colorbar=dict(title="Weight %"),
                ),
            )
        )
        fig_treemap.update_layout(
            template="plotly_dark",
            height=450,
            margin=dict(t=10, b=10, l=10, r=10),
        )
        st.plotly_chart(fig_treemap, use_container_width=True, key="portfolio_treemap")
        chart_download_button(fig_treemap, "Download Treemap", "portfolio_treemap.html")

    else:  # Stacked Bar
        fig_bar = go.Figure()
        for row in alloc_df.itertuples():
            fig_bar.add_trace(
                go.Bar(
                    name=row.symbol,
                    x=["Portfolio"],
                    y=[row.weight_pct],
                    text=f"{row.symbol}<br>{row.weight_pct:.1f}%",
                    textposition="inside",
                    hovertemplate=(
                        f"<b>{row.symbol}</b><br>"
                        f"Weight: {row.weight_pct:.2f}%"
                        "<extra></extra>"
                    ),
                )
            )
        fig_bar.update_layout(
            barmode="stack",
            template="plotly_dark",
            height=400,
            xaxis_title="",
            yaxis_title="Weight (%)",
            showlegend=True,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
            margin=dict(t=50, b=40, l=60, r=10),
        )
        st.plotly_chart(fig_bar, use_container_width=True, key="portfolio_stacked_bar")
        chart_download_button(
            fig_bar, "Download Stacked Bar", "portfolio_stacked_bar.html"
        )

    # -----------------------------------------------------------------------
    # Section 2: Weight History
    # -----------------------------------------------------------------------

    st.subheader("Weight History (30 Days)")

    history_toggle = st.radio(
        "Format",
        ["Area Chart", "Table"],
        horizontal=True,
        key="portfolio_history_toggle",
    )

    history_df = load_allocation_history(_engine, optimizer=selected_optimizer, days=30)

    if history_df.empty:
        st.info("No allocation history available yet.")
    elif history_toggle == "Area Chart":
        fig_area = go.Figure()
        for symbol in history_df.columns:
            fig_area.add_trace(
                go.Scatter(
                    x=history_df.index.tolist(),
                    y=(history_df[symbol] * 100.0).tolist(),
                    mode="lines",
                    name=symbol,
                    stackgroup="weights",
                    hovertemplate=(
                        f"<b>{symbol}</b><br>"
                        "Date: %{x|%Y-%m-%d}<br>"
                        "Weight: %{y:.2f}%"
                        "<extra></extra>"
                    ),
                )
            )
        fig_area.update_layout(
            template="plotly_dark",
            height=380,
            xaxis_title="Date",
            yaxis_title="Weight (%)",
            showlegend=True,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
            margin=dict(t=50, b=40, l=60, r=10),
        )
        st.plotly_chart(fig_area, use_container_width=True, key="portfolio_area_chart")
        chart_download_button(
            fig_area, "Download Weight History", "portfolio_weight_history.html"
        )
    else:  # Table
        table_df = history_df.copy()
        table_df.index = table_df.index.strftime("%Y-%m-%d")
        table_df.index.name = "Date"
        for col in table_df.columns:
            table_df[col] = table_df[col].map(lambda v: f"{v * 100:.1f}%")
        st.dataframe(
            table_df.reset_index(),
            use_container_width=True,
            height=350,
            key="portfolio_history_table",
        )

    # -----------------------------------------------------------------------
    # Section 3: Position Sizing
    # -----------------------------------------------------------------------

    st.subheader("Position Sizing")

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Bet Size per Asset (USD)**")

        fig_bets = go.Figure(
            go.Bar(
                x=alloc_df["bet_size_usd"].tolist(),
                y=alloc_df["symbol"].tolist(),
                orientation="h",
                marker_color="rgba(0, 200, 100, 0.8)",
                hovertemplate=("<b>%{y}</b><br>Bet: $%{x:,.0f}<extra></extra>"),
            )
        )
        fig_bets.update_layout(
            template="plotly_dark",
            height=350,
            xaxis_title="Bet Size (USD)",
            yaxis_title="Asset",
            xaxis=dict(tickformat="$,.0f"),
            margin=dict(t=20, b=50, l=60, r=10),
        )
        st.plotly_chart(fig_bets, use_container_width=True, key="portfolio_bet_sizes")

    with col_right:
        st.markdown("**Portfolio Metrics**")

        st.metric(
            "Portfolio NAV",
            f"${portfolio_nav:,.0f}",
            help="Total starting capital from active executor configs",
        )
        st.metric("Assets Allocated", len(alloc_df))
        st.metric("Optimizer", selected_optimizer.upper())

        # Condition number (diagnostic from covariance matrix)
        cond = alloc_df["condition_number"].dropna()
        if not cond.empty:
            st.metric(
                "Condition Number",
                f"{cond.iloc[0]:.1f}",
                help="Lower is better (< 100 ideal). "
                "Measures covariance matrix stability.",
            )

    # -----------------------------------------------------------------------
    # Section 4: Exposure Summary
    # -----------------------------------------------------------------------

    st.subheader("Exposure Summary")

    summary_df = alloc_df[["symbol", "weight_pct", "bet_size_usd"]].copy()

    # Add final weight column if available
    if "final_weight" in alloc_df.columns and alloc_df["final_weight"].notna().any():
        summary_df["final_weight_pct"] = alloc_df["final_weight"] * 100.0

    # Add regime label if available
    if "regime_label" in alloc_df.columns and alloc_df["regime_label"].notna().any():
        summary_df["regime"] = alloc_df["regime_label"]

    # Format for display
    fmt_df = pd.DataFrame()
    fmt_df["Symbol"] = summary_df["symbol"]
    fmt_df["Weight %"] = summary_df["weight_pct"].map(lambda v: f"{v:.1f}%")
    fmt_df["Bet Size USD"] = summary_df["bet_size_usd"].map(lambda v: f"${v:,.0f}")
    if "final_weight_pct" in summary_df.columns:
        fmt_df["Final Weight %"] = summary_df["final_weight_pct"].map(
            lambda v: f"{v:.1f}%"
        )
    if "regime" in summary_df.columns:
        fmt_df["Regime"] = summary_df["regime"]

    # Totals row
    totals_dict: dict[str, str] = {
        "Symbol": "TOTAL",
        "Weight %": f"{alloc_df['weight_pct'].sum():.1f}%",
        "Bet Size USD": f"${alloc_df['bet_size_usd'].sum():,.0f}",
    }
    if "Final Weight %" in fmt_df.columns and "final_weight_pct" in summary_df.columns:
        totals_dict["Final Weight %"] = f"{summary_df['final_weight_pct'].sum():.1f}%"
    if "Regime" in fmt_df.columns:
        totals_dict["Regime"] = "--"

    totals = pd.DataFrame([totals_dict])
    display_df = pd.concat([fmt_df, totals], ignore_index=True)

    st.dataframe(
        display_df,
        use_container_width=True,
        height=420,
        key="portfolio_exposure_summary",
    )


# ---------------------------------------------------------------------------
# Invoke fragment
# ---------------------------------------------------------------------------

_portfolio_content(
    _engine=engine,
    as_of_date=as_of_date,
    selected_optimizer=selected_optimizer,
)
