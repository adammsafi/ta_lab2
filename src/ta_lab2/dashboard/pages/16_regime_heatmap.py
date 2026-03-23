# -*- coding: utf-8 -*-
"""
Regime Heatmap dashboard page -- Phase 84.

Provides a cross-asset view of regime states across all assets.
Shows current regime distribution, cross-asset heatmap, timeline,
and per-asset EMA comovement data.

Views:
  - Section 1: Overview metric cards (total assets, % Up/Down/Sideways)
  - Section 2: Cross-asset regime heatmap (top 30 default, all-assets toggle)
  - Section 3: Regime timeline (compact strip or paginated flip log)
  - Section 4: EMA comovement table (7 assets, 21 rows)

NOTE: Do NOT call st.set_page_config() here -- it is called in the main
app entry point (app.py / Home.py).

CRITICAL: regimes table has NO trend_state column.
  trend_state is derived via split_part(l2_label, '-', 1) in SQL (queries/regimes.py).

NOTE: regime_comovement is NOT cross-asset correlation.
  It tracks how EMAs within a single asset co-move (7 assets, 3 EMA pairs each).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ta_lab2.dashboard.charts import REGIME_BAR_COLORS
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.regimes import (
    load_regime_all_assets,
    load_regime_comovement,
    load_regime_flips_recent,
    load_regime_stats_summary,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AUTO_REFRESH_SECONDS = 900
_TF_DEFAULT = "1D"
_DAYS_BACK_DEFAULT = 365
_TOP_N_DEFAULT = 30

# Trend state numeric encoding for heatmap
_STATE_ENCODING: dict[str, int] = {"Up": 1, "Sideways": 0, "Down": -1}

# Custom colorscale derived from REGIME_BAR_COLORS: Down=red, Sideways=gray, Up=green
# Encoding: Down=-1 -> 0.0, Sideways=0 -> 0.5, Up=1 -> 1.0
_HEATMAP_COLORSCALE = [
    [0.0, REGIME_BAR_COLORS["Down"]],
    [0.5, REGIME_BAR_COLORS["Sideways"]],
    [1.0, REGIME_BAR_COLORS["Up"]],
]

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Regime Heatmap")
st.caption("Cross-asset regime state across all assets with trend distribution")

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar controls (OUTSIDE fragment -- widgets must be at module level)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Regime Heatmap Controls")

    selected_tf = st.selectbox(
        "Timeframe",
        ["1D", "4H", "1H", "1W"],
        index=0,
        key="regime_heatmap_tf",
    )

    days_back = st.slider(
        "Days Back",
        min_value=30,
        max_value=730,
        value=_DAYS_BACK_DEFAULT,
        step=30,
        key="regime_heatmap_days_back",
    )

    show_all_assets = st.toggle(
        "Show all assets",
        value=False,
        key="regime_heatmap_show_all",
    )

    flip_limit = st.slider(
        "Recent Flips Limit",
        min_value=20,
        max_value=200,
        value=100,
        step=20,
        key="regime_heatmap_flip_limit",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_trend(state: str) -> int:
    """Map trend_state string to numeric value for heatmap."""
    return _STATE_ENCODING.get(state, 0)


def _get_current_state(df: pd.DataFrame) -> pd.DataFrame:
    """Return the most recent regime_key per asset."""
    if df.empty:
        return df
    return df.sort_values("ts").groupby("id", as_index=False).last()


def _build_heatmap_figure(
    regime_df: pd.DataFrame,
    title: str,
    fig_height: int = 600,
) -> go.Figure:
    """Build a cross-asset regime heatmap from daily regime data.

    Bins dates to weekly frequency for readability.
    Encodes trend_state as numeric: Up=1, Sideways=0, Down=-1.
    """
    if regime_df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, template="plotly_dark")
        return fig

    # Bin timestamps to weekly for readability
    df = regime_df.copy()
    df["week"] = df["ts"].dt.to_period("W").dt.start_time
    # Take the most common trend_state per (symbol, week)
    mode_df = (
        df.groupby(["symbol", "week"])["trend_state"]
        .agg(lambda x: x.mode()[0] if not x.empty else "Sideways")
        .reset_index()
    )
    mode_df["trend_num"] = mode_df["trend_state"].map(_STATE_ENCODING).fillna(0)

    # Pivot: rows=symbol, columns=week
    pivot = mode_df.pivot(index="symbol", columns="week", values="trend_num")
    pivot_text = mode_df.pivot(index="symbol", columns="week", values="trend_state")

    symbols = pivot.index.tolist()
    weeks = [str(c.date()) for c in pivot.columns]
    z_values = pivot.values.tolist()
    text_values = pivot_text.values.tolist()

    fig = go.Figure(
        data=go.Heatmap(
            z=z_values,
            x=weeks,
            y=symbols,
            text=text_values,
            texttemplate="%{text}",
            colorscale=_HEATMAP_COLORSCALE,
            zmin=-1,
            zmax=1,
            showscale=True,
            colorbar=dict(
                title="Trend",
                tickvals=[-1, 0, 1],
                ticktext=["Down", "Sideways", "Up"],
            ),
        )
    )
    fig.update_layout(
        title=title,
        template="plotly_dark",
        height=fig_height,
        xaxis=dict(title="Week"),
        yaxis=dict(title="Asset", autorange="reversed"),
    )
    return fig


# ---------------------------------------------------------------------------
# Main content (wrapped in @st.fragment for auto-refresh)
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _render_regime_content(
    tf: str,
    n_days: int,
    expand_all: bool,
    n_flips: int,
) -> None:
    """Auto-refreshing regime content fragment."""

    # -----------------------------------------------------------------------
    # Load data
    # -----------------------------------------------------------------------

    try:
        regime_df = load_regime_all_assets(engine, tf=tf, days_back=n_days)
        stats_df = load_regime_stats_summary(engine, tf=tf)
        flips_df = load_regime_flips_recent(engine, tf=tf, limit=n_flips)
        comov_df = load_regime_comovement(engine, tf=tf)
    except Exception as exc:
        st.error(f"Error loading regime data: {exc}")
        return

    # -----------------------------------------------------------------------
    # Section 1: Overview Cards
    # -----------------------------------------------------------------------

    st.subheader("Current Regime Distribution")

    if regime_df.empty:
        st.warning(
            "No regime data found for the selected timeframe and date range. "
            "Run the regime refresh script first."
        )
    else:
        # Get latest regime per asset
        current_df = _get_current_state(regime_df)
        total_assets = current_df["id"].nunique()
        state_counts = current_df["trend_state"].value_counts()

        n_up = int(state_counts.get("Up", 0))
        n_down = int(state_counts.get("Down", 0))
        n_sideways = int(state_counts.get("Sideways", 0))

        pct_up = round(n_up / total_assets * 100, 1) if total_assets > 0 else 0.0
        pct_down = round(n_down / total_assets * 100, 1) if total_assets > 0 else 0.0
        pct_side = (
            round(n_sideways / total_assets * 100, 1) if total_assets > 0 else 0.0
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "Total Assets",
                total_assets,
                help="Assets with regime data in selected period",
            )
        with col2:
            st.metric(
                "Uptrend",
                f"{n_up} ({pct_up}%)",
                delta=f"+{pct_up}%" if pct_up >= 50 else None,
                delta_color="normal",
            )
        with col3:
            st.metric(
                "Downtrend",
                f"{n_down} ({pct_down}%)",
                delta=f"-{pct_down}%" if pct_down >= 50 else None,
                delta_color="inverse",
            )
        with col4:
            st.metric(
                "Sideways",
                f"{n_sideways} ({pct_side}%)",
            )

    st.divider()

    # -----------------------------------------------------------------------
    # Section 2: Cross-Asset Regime Heatmap
    # -----------------------------------------------------------------------

    st.subheader("Cross-Asset Regime Heatmap")

    if regime_df.empty:
        st.info("No data available for heatmap.")
    else:
        if expand_all:
            heatmap_df = regime_df.copy()
            heatmap_title = f"All Assets -- Regime State by Week ({tf}, {n_days}d)"
            n_symbols = heatmap_df["symbol"].nunique()
            fig_height = max(600, n_symbols * 18)
        else:
            # Top 30 assets by row count (most regime data = most history)
            top_symbols = (
                regime_df.groupby("symbol")["ts"]
                .count()
                .nlargest(_TOP_N_DEFAULT)
                .index.tolist()
            )
            heatmap_df = regime_df[regime_df["symbol"].isin(top_symbols)].copy()
            heatmap_title = (
                f"Top {_TOP_N_DEFAULT} Assets -- Regime State by Week ({tf}, {n_days}d)"
            )
            fig_height = 600

        if not expand_all:
            st.caption(
                f"Showing top {_TOP_N_DEFAULT} assets by history length. "
                "Toggle 'Show all assets' in sidebar to see all."
            )

        try:
            fig_heatmap = _build_heatmap_figure(
                heatmap_df,
                title=heatmap_title,
                fig_height=fig_height,
            )
            st.plotly_chart(
                fig_heatmap,
                theme=None,
                use_container_width=True,
                key="regime_heatmap_main",
            )
        except Exception as exc:
            st.warning(f"Could not render heatmap: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Section 3: Regime Timeline
    # -----------------------------------------------------------------------

    st.subheader("Regime Timeline")

    timeline_view = st.radio(
        "View",
        ["Compact Strip", "Paginated Detail"],
        horizontal=True,
        key="regime_timeline_view",
    )

    if timeline_view == "Compact Strip":
        if regime_df.empty:
            st.info("No data for compact strip.")
        else:
            # Use same set as heatmap (top 30 or all)
            if expand_all:
                strip_df = regime_df.copy()
                strip_title = f"All Assets -- Regime Strip ({tf})"
            else:
                top_symbols_strip = (
                    regime_df.groupby("symbol")["ts"]
                    .count()
                    .nlargest(_TOP_N_DEFAULT)
                    .index.tolist()
                )
                strip_df = regime_df[regime_df["symbol"].isin(top_symbols_strip)].copy()
                strip_title = f"Top {_TOP_N_DEFAULT} Assets -- Regime Strip ({tf})"

            try:
                # Build compact strip using Heatmap at daily granularity
                strip_df["date_str"] = strip_df["ts"].dt.strftime("%Y-%m-%d")
                strip_df["trend_num"] = (
                    strip_df["trend_state"].map(_STATE_ENCODING).fillna(0)
                )
                pivot_strip = strip_df.pivot_table(
                    index="symbol",
                    columns="date_str",
                    values="trend_num",
                    aggfunc="last",
                )
                n_strip = pivot_strip.index.nunique()
                strip_height = max(400, n_strip * 14)

                fig_strip = go.Figure(
                    data=go.Heatmap(
                        z=pivot_strip.values.tolist(),
                        x=pivot_strip.columns.tolist(),
                        y=pivot_strip.index.tolist(),
                        colorscale=_HEATMAP_COLORSCALE,
                        zmin=-1,
                        zmax=1,
                        showscale=False,
                    )
                )
                fig_strip.update_layout(
                    title=strip_title,
                    template="plotly_dark",
                    height=strip_height,
                    xaxis=dict(title="Date", tickangle=-45),
                    yaxis=dict(title="Asset", autorange="reversed"),
                )
                st.plotly_chart(
                    fig_strip,
                    theme=None,
                    use_container_width=True,
                    key="regime_strip_chart",
                )
            except Exception as exc:
                st.warning(f"Could not render compact strip: {exc}")

    else:  # Paginated Detail
        st.caption("Most recent regime transitions across all assets.")
        if flips_df.empty:
            st.info("No regime flips found for selected timeframe.")
        else:
            display_flips = flips_df[
                ["symbol", "ts", "old_regime", "new_regime", "duration_bars"]
            ].copy()
            display_flips["ts"] = display_flips["ts"].dt.strftime("%Y-%m-%d %H:%M UTC")
            st.dataframe(
                display_flips,
                use_container_width=True,
                key="regime_flips_table",
                column_config={
                    "symbol": st.column_config.TextColumn("Asset"),
                    "ts": st.column_config.TextColumn("Timestamp"),
                    "old_regime": st.column_config.TextColumn("Previous Regime"),
                    "new_regime": st.column_config.TextColumn("New Regime"),
                    "duration_bars": st.column_config.NumberColumn(
                        "Duration (bars)", format="%d"
                    ),
                },
            )
            st.caption(f"Showing {len(display_flips)} most recent flips.")

    # Show regime stats below timeline
    if not stats_df.empty:
        with st.expander("Regime Stats by Asset", expanded=False):
            st.dataframe(
                stats_df[["symbol", "regime_key", "n_bars", "pct_of_history"]].rename(
                    columns={
                        "symbol": "Asset",
                        "regime_key": "Regime",
                        "n_bars": "Bars",
                        "pct_of_history": "% of History",
                    }
                ),
                use_container_width=True,
                key="regime_stats_table",
            )

    st.divider()

    # -----------------------------------------------------------------------
    # Section 4: EMA Comovement (Per-Asset)
    # -----------------------------------------------------------------------

    st.subheader("EMA Comovement (Per-Asset)")
    st.caption(
        "EMA indicator comovement within each asset (7 assets, 3 EMA pairs each). "
        "This is NOT cross-asset correlation. "
        "Each row shows how two EMAs within the same asset co-move."
    )

    if comov_df.empty:
        st.info("No comovement data found. Run regime analysis pipeline first.")
    else:
        display_comov = comov_df[
            [
                "symbol",
                "ema_a",
                "ema_b",
                "correlation",
                "sign_agree_rate",
                "best_lead_lag",
                "n_obs",
            ]
        ].copy()
        st.dataframe(
            display_comov,
            use_container_width=True,
            key="regime_comovement_table",
            column_config={
                "symbol": st.column_config.TextColumn("Asset"),
                "ema_a": st.column_config.NumberColumn("EMA A (period)", format="%d"),
                "ema_b": st.column_config.NumberColumn("EMA B (period)", format="%d"),
                "correlation": st.column_config.NumberColumn(
                    "Correlation", format="%.3f"
                ),
                "sign_agree_rate": st.column_config.NumberColumn(
                    "Sign Agreement", format="%.3f"
                ),
                "best_lead_lag": st.column_config.NumberColumn(
                    "Best Lead/Lag (bars)", format="%d"
                ),
                "n_obs": st.column_config.NumberColumn("Observations", format="%d"),
            },
        )
        st.caption(
            f"Total: {len(display_comov)} rows across "
            f"{display_comov['symbol'].nunique()} assets."
        )


# ---------------------------------------------------------------------------
# Render fragment with sidebar control values
# ---------------------------------------------------------------------------

_render_regime_content(
    tf=selected_tf,
    n_days=days_back,
    expand_all=show_all_assets,
    n_flips=flip_limit,
)
