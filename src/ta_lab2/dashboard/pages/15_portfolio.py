# -*- coding: utf-8 -*-
"""
Portfolio Allocation page -- Black-Litterman weights, position sizing, exposure.

Displays a placeholder layout with mock data demonstrating the intended final
structure. All data is generated inline as reproducible mock data. Live data
will replace mocks after Phase 86 (Portfolio Construction Pipeline) is complete.

Sections:
  1. Current Allocation -- treemap or stacked bar toggle
  2. Weight History     -- stacked area chart or table toggle
  3. Position Sizing    -- bet sizes + risk budget utilization
  4. Exposure Summary   -- full allocation table

NOTE: Do NOT call st.set_page_config() here -- only in the main app entry point.
Sidebar controls live OUTSIDE @st.fragment (widgets cannot be inside a fragment).
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ta_lab2.dashboard.charts import chart_download_button
from ta_lab2.dashboard.db import get_engine  # noqa: F401  # reserved for Phase 86

AUTO_REFRESH_SECONDS = 900

# ---------------------------------------------------------------------------
# Assets and strategies
# ---------------------------------------------------------------------------

_ASSETS: list[str] = [
    "BTC",
    "ETH",
    "SOL",
    "AVAX",
    "LINK",
    "DOT",
    "UNI",
    "AAVE",
    "MATIC",
    "ARB",
]

_STRATEGIES: list[str] = ["momentum", "mean_reversion", "trend_following"]

# Asset -> strategy mapping (used for grouping)
_ASSET_STRATEGY: dict[str, str] = {
    "BTC": "trend_following",
    "ETH": "trend_following",
    "SOL": "momentum",
    "AVAX": "momentum",
    "LINK": "momentum",
    "DOT": "mean_reversion",
    "UNI": "mean_reversion",
    "AAVE": "mean_reversion",
    "MATIC": "trend_following",
    "ARB": "momentum",
}

# ---------------------------------------------------------------------------
# Page header (outside fragment -- always visible)
# ---------------------------------------------------------------------------

st.header("Portfolio Allocation")
st.caption("Black-Litterman weights, position sizing, and exposure")
st.info(
    "This page uses mock data. Live portfolio data will be available after "
    "Phase 86 (Portfolio Construction Pipeline) is complete.",
    icon=":material/construction:",
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

    strategy_filter = st.multiselect(
        "Strategies",
        options=_STRATEGIES,
        default=_STRATEGIES,
        key="portfolio_strategy_filter",
    )


# ---------------------------------------------------------------------------
# Fragment: mock data generation + rendering (auto-refreshes every 15 min)
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _portfolio_content(
    as_of_date: datetime.date,
    strategy_filter: list[str],
) -> None:
    """Render all Portfolio Allocation page sections. Refreshes every 15 minutes."""

    # -----------------------------------------------------------------------
    # Mock data generation
    # TODO(Phase-86): Replace with load_bl_weights(engine)
    # -----------------------------------------------------------------------

    rng = np.random.default_rng(42)

    # Current BL weights (realistic allocation)
    raw_weights = np.array([35.0, 25.0, 10.0, 6.0, 5.0, 4.5, 4.0, 4.0, 3.5, 3.0])
    # Small perturbation to simulate live weights
    weight_pct = raw_weights + rng.normal(0, 0.3, len(_ASSETS))
    weight_pct = np.maximum(weight_pct, 0.5)
    weight_pct = weight_pct / weight_pct.sum() * 100.0

    # Position sizing mock data
    # TODO(Phase-86): Replace with load_position_sizing(engine)
    portfolio_nav = 100_000.0
    bet_size_usd = weight_pct / 100.0 * portfolio_nav
    risk_budget_pct = np.array([8.0, 7.0, 5.0, 4.0, 4.0, 3.5, 3.0, 3.0, 2.5, 2.0])
    risk_used_pct = risk_budget_pct * (0.7 + rng.random(len(_ASSETS)) * 0.3)
    max_position_pct = np.array([40.0, 30.0, 15.0, 10.0, 10.0, 8.0, 7.0, 7.0, 6.0, 5.0])

    # Risk tier labels
    risk_tier_colors = []
    for rp in risk_used_pct / risk_budget_pct:
        if rp < 0.6:
            risk_tier_colors.append("rgba(0, 200, 100, 0.8)")  # green = low risk
        elif rp < 0.85:
            risk_tier_colors.append("rgba(255, 193, 7, 0.8)")  # yellow = medium
        else:
            risk_tier_colors.append("rgba(220, 50, 50, 0.8)")  # red = high

    # Weight history (30-day daily snapshots with random walk)
    # TODO(Phase-86): Replace with load_weight_history(engine, days=30)
    n_days = 30
    dates = pd.date_range(end=pd.Timestamp(as_of_date), periods=n_days, freq="D")
    weight_history = np.zeros((n_days, len(_ASSETS)))
    weight_history[0] = weight_pct
    for day_idx in range(1, n_days):
        delta = rng.normal(0, 0.5, len(_ASSETS))
        w = weight_history[day_idx - 1] + delta
        w = np.maximum(w, 0.5)
        weight_history[day_idx] = w / w.sum() * 100.0
    # Reverse so index 0 = oldest, index -1 = most recent
    weight_history = weight_history[::-1]

    # Build allocation dataframe
    allocation_df = pd.DataFrame(
        {
            "asset": _ASSETS,
            "strategy": [_ASSET_STRATEGY[a] for a in _ASSETS],
            "weight_pct": weight_pct,
            "bet_size_usd": bet_size_usd,
            "risk_budget_pct": risk_budget_pct,
            "risk_used_pct": risk_used_pct,
            "max_position_pct": max_position_pct,
        }
    )

    # Apply strategy filter
    if strategy_filter:
        allocation_df = allocation_df[allocation_df["strategy"].isin(strategy_filter)]
    else:
        st.warning(
            "No strategies selected. Enable at least one strategy in the sidebar."
        )
        return

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
        # go.Treemap: labels=asset, values=weight_pct, parents=strategy
        fig_treemap = go.Figure(
            go.Treemap(
                labels=allocation_df["asset"].tolist(),
                values=allocation_df["weight_pct"].tolist(),
                parents=allocation_df["strategy"].tolist(),
                texttemplate="%{label}<br>%{value:.1f}%",
                hovertemplate="<b>%{label}</b><br>Weight: %{value:.2f}%<br>Strategy: %{parent}<extra></extra>",
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
        for asset_row in allocation_df.itertuples():
            fig_bar.add_trace(
                go.Bar(
                    name=asset_row.asset,
                    x=[asset_row.strategy],
                    y=[asset_row.weight_pct],
                    text=f"{asset_row.asset}<br>{asset_row.weight_pct:.1f}%",
                    textposition="inside",
                    hovertemplate=(
                        f"<b>{asset_row.asset}</b><br>"
                        f"Strategy: {asset_row.strategy}<br>"
                        f"Weight: {asset_row.weight_pct:.2f}%"
                        "<extra></extra>"
                    ),
                )
            )
        fig_bar.update_layout(
            barmode="stack",
            template="plotly_dark",
            height=400,
            xaxis_title="Strategy",
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

    # Filter history columns to strategy_filter assets
    filtered_assets = allocation_df["asset"].tolist()
    asset_indices = [_ASSETS.index(a) for a in filtered_assets if a in _ASSETS]
    filtered_history = weight_history[:, asset_indices]

    if history_toggle == "Area Chart":
        fig_area = go.Figure()
        cumulative_y = np.zeros(n_days)
        for col_idx, asset in enumerate(filtered_assets):
            asset_weights = filtered_history[:, col_idx]
            fig_area.add_trace(
                go.Scatter(
                    x=dates.tolist(),
                    y=(cumulative_y + asset_weights).tolist(),
                    mode="lines",
                    name=asset,
                    stackgroup="weights",
                    hovertemplate=f"<b>{asset}</b><br>Date: %{{x|%Y-%m-%d}}<br>Weight: %{{y:.2f}}%<extra></extra>",
                    fill="tonexty" if col_idx > 0 else "tozeroy",
                )
            )
            cumulative_y = cumulative_y + asset_weights
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
        history_dict: dict[str, object] = {"date": dates.strftime("%Y-%m-%d").tolist()}
        for col_idx, asset in enumerate(filtered_assets):
            history_dict[asset] = [f"{w:.1f}%" for w in filtered_history[:, col_idx]]
        history_display_df = pd.DataFrame(history_dict)
        st.dataframe(
            history_display_df,
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

        # Hover rationale based on strategy
        hover_texts = []
        for row in allocation_df.itertuples():
            ic_ir = 0.75 + (row.weight_pct / 100.0) * 2.0
            hover_texts.append(
                f"<b>{row.asset}</b><br>"
                f"Strategy: {row.strategy}<br>"
                f"Bet: ${row.bet_size_usd:,.0f}<br>"
                f"Rationale: {row.strategy.replace('_', ' ').title()} "
                f"allocation based on IC-IR={ic_ir:.2f}"
            )

        # Bar colors from risk tier
        bar_colors_for_filtered = []
        for asset in filtered_assets:
            orig_idx = _ASSETS.index(asset)
            bar_colors_for_filtered.append(risk_tier_colors[orig_idx])

        fig_bets = go.Figure(
            go.Bar(
                x=allocation_df["bet_size_usd"].tolist(),
                y=allocation_df["asset"].tolist(),
                orientation="h",
                marker_color=bar_colors_for_filtered,
                hovertemplate="%{customdata}<extra></extra>",
                customdata=hover_texts,
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
        st.markdown("**Risk Budget Utilization**")

        total_budget_used = float(allocation_df["risk_used_pct"].sum())
        total_budget = float(allocation_df["risk_budget_pct"].sum())
        utilization_pct = (
            total_budget_used / total_budget * 100.0 if total_budget > 0 else 0.0
        )

        # Summary metric
        color_class = (
            "normal"
            if utilization_pct < 60
            else "off"
            if utilization_pct < 85
            else "inverse"
        )
        st.metric(
            "Total Risk Budget Used",
            f"{utilization_pct:.1f}%",
            delta=f"{utilization_pct - 75:.1f}pp vs 75% target",
            delta_color=color_class,
            help="Percentage of total risk budget currently allocated",
        )

        # Per-asset risk budget progress bars
        for row in allocation_df.itertuples():
            used_frac = (
                float(row.risk_used_pct) / float(row.risk_budget_pct)
                if row.risk_budget_pct > 0
                else 0.0
            )
            used_frac = min(used_frac, 1.0)
            st.write(
                f"**{row.asset}** ({row.risk_used_pct:.1f}% / {row.risk_budget_pct:.1f}%)"
            )
            st.progress(used_frac, text=f"{used_frac * 100:.0f}% of budget")

    # -----------------------------------------------------------------------
    # Section 4: Exposure Summary
    # -----------------------------------------------------------------------

    st.subheader("Exposure Summary")

    # TODO(Phase-86): Replace with live positions from load_live_positions(engine)
    summary_df = allocation_df[
        [
            "asset",
            "strategy",
            "weight_pct",
            "bet_size_usd",
            "risk_budget_pct",
            "max_position_pct",
        ]
    ].copy()
    summary_df["weight_pct"] = summary_df["weight_pct"].map(lambda v: f"{v:.1f}%")
    summary_df["bet_size_usd"] = summary_df["bet_size_usd"].map(lambda v: f"${v:,.0f}")
    summary_df["risk_budget_pct"] = summary_df["risk_budget_pct"].map(
        lambda v: f"{v:.1f}%"
    )
    summary_df["max_position_pct"] = summary_df["max_position_pct"].map(
        lambda v: f"{v:.1f}%"
    )
    summary_df.columns = [
        "Asset",
        "Strategy",
        "Weight %",
        "Bet Size USD",
        "Risk Budget %",
        "Max Position %",
    ]

    # Totals row
    totals = pd.DataFrame(
        [
            {
                "Asset": "TOTAL",
                "Strategy": "--",
                "Weight %": f"{allocation_df['weight_pct'].sum():.1f}%",
                "Bet Size USD": f"${allocation_df['bet_size_usd'].sum():,.0f}",
                "Risk Budget %": f"{allocation_df['risk_budget_pct'].sum():.1f}%",
                "Max Position %": "--",
            }
        ]
    )
    display_df = pd.concat([summary_df, totals], ignore_index=True)

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
    as_of_date=as_of_date,
    strategy_filter=strategy_filter,
)
