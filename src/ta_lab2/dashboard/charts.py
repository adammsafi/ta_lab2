# -*- coding: utf-8 -*-
"""
Plotly chart builder module for the Streamlit dashboard.

All functions return go.Figure objects ready for st.plotly_chart(fig, theme=None).
IC chart wrappers reuse Phase 37 helpers from ta_lab2.analysis.ic and apply
the plotly_dark template. Regime charts are built from scratch using go.Figure.

Public API:
    build_ic_decay_chart     -- IC decay bar chart (wraps plot_ic_decay)
    build_rolling_ic_chart   -- Rolling IC line chart (wraps plot_rolling_ic)
    build_regime_price_chart -- Price line chart with colored regime background bands
    build_regime_timeline    -- Regime timeline scatter chart with trend-state coloring
    chart_download_button    -- Streamlit download button that exports a figure as HTML
"""

from __future__ import annotations

import io

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ta_lab2.analysis.ic import plot_ic_decay, plot_rolling_ic

# ---------------------------------------------------------------------------
# Regime color constants
# ---------------------------------------------------------------------------

# RGBA colors for price chart background bands (low opacity overlay)
REGIME_COLORS: dict[str, str] = {
    "Up": "rgba(0, 200, 100, 0.15)",
    "Down": "rgba(220, 50, 50, 0.15)",
    "Sideways": "rgba(150, 150, 150, 0.12)",
}

# Solid RGB colors for timeline markers (distinct, full opacity)
REGIME_BAR_COLORS: dict[str, str] = {
    "Up": "rgb(0, 200, 100)",
    "Down": "rgb(220, 50, 50)",
    "Sideways": "rgb(150, 150, 150)",
}

# ---------------------------------------------------------------------------
# IC chart wrappers
# ---------------------------------------------------------------------------


def build_ic_decay_chart(
    ic_df: pd.DataFrame,
    feature: str,
    return_type: str = "arith",
) -> go.Figure:
    """
    Build an IC decay bar chart with plotly_dark template.

    Wraps ta_lab2.analysis.ic.plot_ic_decay() directly — no duplicate logic.

    Parameters
    ----------
    ic_df : pd.DataFrame
        Output of compute_ic() with columns horizon, ic, ic_p_value, return_type.
    feature : str
        Feature name for the chart title.
    return_type : str
        Return type to display ('arith' or 'log'). Default 'arith'.

    Returns
    -------
    go.Figure
        Plotly bar chart ready for st.plotly_chart(fig, theme=None).
    """
    fig: go.Figure = plot_ic_decay(ic_df, feature, return_type=return_type)
    fig.update_layout(template="plotly_dark")
    return fig


def build_rolling_ic_chart(
    rolling_ic_series: pd.Series,
    feature: str,
    window: int = 63,
) -> go.Figure:
    """
    Build a rolling IC line chart with plotly_dark template.

    Wraps ta_lab2.analysis.ic.plot_rolling_ic() directly — no duplicate logic.
    The ``window`` parameter is surfaced as the horizon label in the chart subtitle.

    Parameters
    ----------
    rolling_ic_series : pd.Series
        Rolling IC values indexed by timestamp. First element of
        compute_rolling_ic() return tuple.
    feature : str
        Feature name for the chart title.
    window : int
        Rolling window size (used as horizon label in title). Default 63.

    Returns
    -------
    go.Figure
        Plotly line chart ready for st.plotly_chart(fig, theme=None).
    """
    fig: go.Figure = plot_rolling_ic(rolling_ic_series, feature, horizon=window)
    fig.update_layout(template="plotly_dark")
    return fig


# ---------------------------------------------------------------------------
# Regime visualization charts
# ---------------------------------------------------------------------------


def build_regime_price_chart(
    close_series: pd.Series,
    regimes_df: pd.DataFrame,
) -> go.Figure:
    """
    Build a price chart with colored regime background bands.

    Parameters
    ----------
    close_series : pd.Series
        Close prices indexed by tz-aware UTC timestamps.
    regimes_df : pd.DataFrame
        Regime data with columns: ts (datetime), trend_state (str).
        Typically loaded via load_regimes_for_asset() which returns a DataFrame
        indexed by ts — the caller should reset_index() before passing here if
        ts is the index, or pass with ts as a column.

    Returns
    -------
    go.Figure
        Plotly figure with close price line and colored vrect bands per regime period.
    """
    fig = go.Figure()

    # Handle empty close series
    if close_series is None or len(close_series) == 0:
        fig.add_annotation(
            text="No price data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(template="plotly_dark", title="Price with Regime Overlay")
        return fig

    # Handle empty regimes
    if regimes_df is None or len(regimes_df) == 0:
        # Render price only, no regime bands
        fig.add_trace(
            go.Scatter(
                x=close_series.index,
                y=close_series.values,
                mode="lines",
                name="Close",
                line={"color": "white", "width": 1.5},
            )
        )
        fig.update_layout(
            template="plotly_dark",
            title="Price with Regime Overlay",
            xaxis_title="Date",
            yaxis_title="Close Price",
        )
        return fig

    # Add close price line
    fig.add_trace(
        go.Scatter(
            x=close_series.index,
            y=close_series.values,
            mode="lines",
            name="Close",
            line={"color": "white", "width": 1.5},
        )
    )

    # Normalize regimes_df: ensure ts is a column, not the index
    if "ts" not in regimes_df.columns:
        regimes_work = regimes_df.reset_index()
        if "ts" not in regimes_work.columns:
            # Index was not named ts -- rename the first column (the reset index)
            regimes_work = regimes_work.rename(columns={regimes_work.columns[0]: "ts"})
    else:
        regimes_work = regimes_df.copy()

    regimes_work = regimes_work.sort_values("ts").reset_index(drop=True)

    last_price_ts = close_series.index[-1]

    # Add vrect background bands for each regime period
    for i, row in regimes_work.iterrows():
        start_ts = row["ts"]
        trend_state = row.get("trend_state", "Sideways")

        # End of band is the next regime's ts, or end of price series for last row
        if i + 1 < len(regimes_work):
            end_ts = regimes_work.loc[i + 1, "ts"]
        else:
            end_ts = last_price_ts

        color = REGIME_COLORS.get(str(trend_state), REGIME_COLORS["Sideways"])

        fig.add_vrect(
            x0=start_ts,
            x1=end_ts,
            fillcolor=color,
            opacity=1,
            layer="below",
            line_width=0,
        )

    fig.update_layout(
        template="plotly_dark",
        title="Price with Regime Overlay",
        xaxis_title="Date",
        yaxis_title="Close Price",
    )

    return fig


def build_regime_timeline(regimes_df: pd.DataFrame) -> go.Figure:
    """
    Build a regime timeline scatter chart colored by trend state.

    Each regime period is shown as a marker at its timestamp, colored by trend state.
    Useful for visually inspecting regime coverage over time.

    Parameters
    ----------
    regimes_df : pd.DataFrame
        Regime data with columns: ts (datetime), trend_state (str), vol_state (str).
        ts may be the index or a column.

    Returns
    -------
    go.Figure
        Plotly scatter chart ready for st.plotly_chart(fig, theme=None).
    """
    fig = go.Figure()

    # Handle empty regimes
    if regimes_df is None or len(regimes_df) == 0:
        fig.add_annotation(
            text="No regime data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(template="plotly_dark", title="Regime Timeline")
        return fig

    # Normalize regimes_df: ensure ts is a column
    if "ts" not in regimes_df.columns:
        regimes_work = regimes_df.reset_index()
        if "ts" not in regimes_work.columns:
            regimes_work = regimes_work.rename(columns={regimes_work.columns[0]: "ts"})
    else:
        regimes_work = regimes_df.copy()

    regimes_work = regimes_work.sort_values("ts").reset_index(drop=True)

    # Add one Scatter trace per trend state for legend grouping
    for trend, color in REGIME_BAR_COLORS.items():
        subset = regimes_work[
            regimes_work.get("trend_state", pd.Series(dtype=str)) == trend
        ]

        # Handle case where trend_state column may not exist
        if "trend_state" not in regimes_work.columns:
            subset = pd.DataFrame()
        else:
            subset = regimes_work[regimes_work["trend_state"] == trend]

        if len(subset) == 0:
            # Add empty trace to preserve legend entry
            fig.add_trace(
                go.Scatter(
                    x=[],
                    y=[],
                    mode="markers",
                    name=trend,
                    marker={"color": color, "symbol": "square", "size": 10},
                )
            )
            continue

        # Build hover text including vol_state if available
        if "vol_state" in subset.columns:
            hover_text = [
                f"Trend: {t}<br>Vol: {v}<br>Date: {d}"
                for t, v, d in zip(
                    subset["trend_state"],
                    subset["vol_state"],
                    subset["ts"],
                )
            ]
        else:
            hover_text = [
                f"Trend: {t}<br>Date: {d}"
                for t, d in zip(
                    subset.get("trend_state", [trend] * len(subset)), subset["ts"]
                )
            ]

        fig.add_trace(
            go.Scatter(
                x=subset["ts"],
                y=[trend] * len(subset),
                mode="markers",
                name=trend,
                marker={"color": color, "symbol": "square", "size": 10},
                text=hover_text,
                hoverinfo="text",
            )
        )

    fig.update_layout(
        template="plotly_dark",
        title="Regime Timeline",
        xaxis_title="Date",
        yaxis_title="Trend State",
    )

    return fig


# ---------------------------------------------------------------------------
# Asset stats and correlation charts
# ---------------------------------------------------------------------------


def build_correlation_heatmap(
    corr_df: pd.DataFrame,
    metric: str = "pearson_r",
) -> go.Figure:
    """
    Build a symmetric N x N correlation heatmap from pairwise data.

    Parameters
    ----------
    corr_df : pd.DataFrame
        Output of load_corr_latest() with columns symbol_a, symbol_b, and
        the metric column (pearson_r or spearman_r).  Each row is one pair.
    metric : str
        Column to use for correlation values: ``"pearson_r"`` or ``"spearman_r"``.
        Default ``"pearson_r"``.

    Returns
    -------
    go.Figure
        Plotly heatmap ready for st.plotly_chart(fig, theme=None).
    """
    fig = go.Figure()

    if corr_df is None or corr_df.empty:
        fig.add_annotation(
            text="No correlation data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(template="plotly_dark", title="Correlation Heatmap")
        return fig

    if metric not in corr_df.columns:
        fig.add_annotation(
            text=f"Metric '{metric}' not found in correlation data",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(template="plotly_dark", title="Correlation Heatmap")
        return fig

    # Collect all unique symbol names for axis ordering
    symbols_a = set(corr_df["symbol_a"].tolist())
    symbols_b = set(corr_df["symbol_b"].tolist())
    all_symbols = sorted(symbols_a | symbols_b)
    n = len(all_symbols)

    if n == 0:
        fig.update_layout(template="plotly_dark", title="Correlation Heatmap")
        return fig

    sym_idx = {s: i for i, s in enumerate(all_symbols)}

    # Build symmetric N x N matrix — diagonal is 1.0
    import numpy as np

    mat = [[None] * n for _ in range(n)]
    for i in range(n):
        mat[i][i] = 1.0

    for _, row in corr_df.iterrows():
        sa = row["symbol_a"]
        sb = row["symbol_b"]
        val = row[metric]
        if sa in sym_idx and sb in sym_idx:
            ia, ib = sym_idx[sa], sym_idx[sb]
            mat[ia][ib] = (
                float(val) if val is not None and not np.isnan(float(val)) else None
            )
            mat[ib][ia] = (
                float(val) if val is not None and not np.isnan(float(val)) else None
            )

    # Build text annotation matrix (2 decimal places, empty for None)
    text_mat = []
    for row in mat:
        text_row = []
        for v in row:
            if v is None:
                text_row.append("")
            else:
                text_row.append(f"{v:.2f}")
        text_mat.append(text_row)

    title_label = "Pearson" if "pearson" in metric else "Spearman"

    fig.add_trace(
        go.Heatmap(
            z=mat,
            x=all_symbols,
            y=all_symbols,
            colorscale="RdBu",
            zmid=0,
            zmin=-1,
            zmax=1,
            text=text_mat,
            texttemplate="%{text}",
            colorbar={"title": title_label},
        )
    )

    fig.update_layout(
        template="plotly_dark",
        title=f"Cross-Asset Correlation ({title_label})",
        xaxis_title="Asset",
        yaxis_title="Asset",
        yaxis={"autorange": "reversed"},
    )

    return fig


def build_stat_timeseries_chart(
    df: pd.DataFrame,
    stat_col: str,
    title: str,
) -> go.Figure:
    """
    Build a simple time-series line chart for a rolling stat column.

    Parameters
    ----------
    df : pd.DataFrame
        Output of load_asset_stats_timeseries() — indexed by ts with stat columns.
    stat_col : str
        Column name to plot (e.g. ``"sharpe_ann_252"``).
    title : str
        Chart title string.

    Returns
    -------
    go.Figure
        Plotly line chart ready for st.plotly_chart(fig, theme=None).
    """
    fig = go.Figure()

    if df is None or df.empty:
        fig.add_annotation(
            text="No time-series data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(template="plotly_dark", title=title)
        return fig

    if stat_col not in df.columns:
        fig.add_annotation(
            text=f"Column '{stat_col}' not found",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(template="plotly_dark", title=title)
        return fig

    series = df[stat_col].dropna()

    fig.add_trace(
        go.Scatter(
            x=series.index,
            y=series.values,
            mode="lines",
            name=stat_col,
            line={"width": 1.5},
        )
    )

    fig.update_layout(
        template="plotly_dark",
        title=title,
        xaxis_title="Date",
        yaxis_title=stat_col,
    )

    return fig


# ---------------------------------------------------------------------------
# Operational charts
# ---------------------------------------------------------------------------


def build_pnl_drawdown_chart(pnl_df: pd.DataFrame) -> go.Figure:
    """
    Build a two-panel stacked cumulative PnL + drawdown chart.

    Top panel (65%): cumulative PnL line in green.
    Bottom panel (35%): drawdown % as a filled red area.

    Parameters
    ----------
    pnl_df : pd.DataFrame
        Output of load_daily_pnl_series() with columns: trade_date,
        cumulative_pnl, drawdown_pct.

    Returns
    -------
    go.Figure
        Plotly figure ready for st.plotly_chart(fig, theme=None).
    """
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.05,
    )

    if pnl_df is None or pnl_df.empty:
        fig.add_annotation(
            text="No PnL data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(template="plotly_dark", height=500)
        return fig

    # Use .tolist() to avoid tz-aware datetime .values pitfall (MEMORY.md)
    x_dates = pnl_df["trade_date"].tolist()

    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=pnl_df["cumulative_pnl"],
            mode="lines",
            name="Cumulative PnL",
            line={"color": "rgb(0,200,100)", "width": 1.5},
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=pnl_df["drawdown_pct"],
            mode="lines",
            name="Drawdown %",
            fill="tozeroy",
            line={"color": "rgb(220,50,50)", "width": 1.5},
        ),
        row=2,
        col=1,
    )

    fig.update_yaxes(title_text="Cumulative PnL ($)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown %", row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=500,
        showlegend=True,
    )

    return fig


def build_tracking_error_chart(
    drift_df: pd.DataFrame,
    threshold_5d: float | None = None,
    threshold_30d: float | None = None,
) -> go.Figure:
    """
    Build a tracking error time series chart with optional threshold lines.

    Parameters
    ----------
    drift_df : pd.DataFrame
        Output of load_drift_timeseries() with columns: metric_date,
        tracking_error_5d, tracking_error_30d.
    threshold_5d : float | None
        5-day tracking error threshold to draw as a dashed red horizontal line.
    threshold_30d : float | None
        30-day tracking error threshold to draw as a dotted red horizontal line.

    Returns
    -------
    go.Figure
        Plotly figure ready for st.plotly_chart(fig, theme=None).
    """
    fig = go.Figure()

    if drift_df is None or drift_df.empty:
        fig.add_annotation(
            text="No drift data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(
            template="plotly_dark",
            title="Tracking Error Time Series",
            height=400,
        )
        return fig

    x_dates = drift_df["metric_date"].tolist()

    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=drift_df["tracking_error_5d"],
            mode="lines",
            name="TE 5d",
            line={"color": "rgb(255,165,0)", "width": 1.5},
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=drift_df["tracking_error_30d"],
            mode="lines",
            name="TE 30d",
            line={"color": "rgb(100,149,237)", "width": 1.5},
        )
    )

    if threshold_5d is not None:
        fig.add_hline(
            y=threshold_5d,
            line_dash="dash",
            line_color="red",
            annotation_text="5d threshold",
        )

    if threshold_30d is not None:
        fig.add_hline(
            y=threshold_30d,
            line_dash="dot",
            line_color="red",
            annotation_text="30d threshold",
        )

    fig.update_layout(
        template="plotly_dark",
        title="Tracking Error Time Series",
        yaxis_title="Tracking Error",
        height=400,
    )

    return fig


def build_equity_overlay_chart(drift_df: pd.DataFrame) -> go.Figure:
    """
    Build a paper vs replay equity overlay chart.

    Two lines on a single panel: paper cumulative PnL vs replay PIT cumulative PnL.

    Parameters
    ----------
    drift_df : pd.DataFrame
        Output of load_drift_timeseries() with columns: metric_date,
        paper_cumulative_pnl, replay_pit_cumulative_pnl.

    Returns
    -------
    go.Figure
        Plotly figure ready for st.plotly_chart(fig, theme=None).
    """
    fig = go.Figure()

    if drift_df is None or drift_df.empty:
        fig.add_annotation(
            text="No drift data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(
            template="plotly_dark",
            title="Paper vs Replay Equity",
            height=400,
        )
        return fig

    x_dates = drift_df["metric_date"].tolist()

    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=drift_df["paper_cumulative_pnl"],
            mode="lines",
            name="Paper PnL",
            line={"color": "rgb(0,200,100)", "width": 1.5},
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x_dates,
            y=drift_df["replay_pit_cumulative_pnl"],
            mode="lines",
            name="Replay PnL (PIT)",
            line={"color": "rgb(100,149,237)", "width": 1.5},
        )
    )

    fig.update_layout(
        template="plotly_dark",
        title="Paper vs Replay Equity",
        yaxis_title="Cumulative PnL ($)",
        height=400,
    )

    return fig


# ---------------------------------------------------------------------------
# Macro regime color constants
# ---------------------------------------------------------------------------

# Low-opacity RGBA fills for composite macro state background bands.
# Keyed by macro_state label from macro_regimes.macro_state column.
MACRO_STATE_COLORS: dict[str, str] = {
    "favorable": "rgba(0,200,100,0.20)",
    "constructive": "rgba(100,200,100,0.15)",
    "neutral": "rgba(150,150,150,0.12)",
    "cautious": "rgba(255,165,0,0.15)",
    "adverse": "rgba(220,50,50,0.20)",
}

# Per-dimension label colors for the 4 dimension band panels in the timeline.
# Keyed by dimension name, then by label value from macro_regimes columns.
MACRO_DIMENSION_COLORS: dict[str, dict[str, str]] = {
    "monetary_policy": {
        "Cutting": "rgba(0,200,100,0.25)",
        "Holding": "rgba(150,150,150,0.15)",
        "Hiking": "rgba(220,50,50,0.25)",
    },
    "liquidity": {
        "Strongly_Expanding": "rgba(0,200,100,0.30)",
        "Expanding": "rgba(0,200,100,0.15)",
        "Neutral": "rgba(150,150,150,0.12)",
        "Contracting": "rgba(220,50,50,0.15)",
        "Strongly_Contracting": "rgba(220,50,50,0.30)",
    },
    "risk_appetite": {
        "RiskOn": "rgba(0,200,100,0.25)",
        "Neutral": "rgba(150,150,150,0.15)",
        "RiskOff": "rgba(220,50,50,0.25)",
    },
    "carry": {
        "Stable": "rgba(0,200,100,0.20)",
        "Stress": "rgba(255,165,0,0.20)",
        "Unwind": "rgba(220,50,50,0.25)",
    },
}

# Ordered list of dimension columns and their display labels for the 4 bands.
_MACRO_DIMENSIONS: list[tuple[str, str]] = [
    ("monetary_policy", "Monetary Policy"),
    ("liquidity", "Liquidity"),
    ("risk_appetite", "Risk Appetite"),
    ("carry", "Carry"),
]

# Default band color when a label is not found in MACRO_DIMENSION_COLORS.
_DIMENSION_FALLBACK_COLOR = "rgba(150,150,150,0.12)"


# ---------------------------------------------------------------------------
# Macro regime charts
# ---------------------------------------------------------------------------


def build_macro_regime_timeline(
    regimes_df: pd.DataFrame,
    overlay_df: pd.DataFrame | None = None,
    overlay_label: str = "Portfolio PnL",
) -> go.Figure:
    """Build a 5-panel macro regime timeline chart.

    Layout (shared x-axis, shared_xaxes=True):
      Panel 1 (top, 40%): Overlay line (PnL or asset price) or placeholder.
      Panel 2 (15%):      monetary_policy dimension band.
      Panel 3 (15%):      liquidity dimension band.
      Panel 4 (15%):      risk_appetite dimension band.
      Panel 5 (15%):      carry dimension band.

    Each dimension panel draws consecutive vrect blocks colored by label value
    from MACRO_DIMENSION_COLORS.  Vertical dashed transition lines are drawn
    on all panels at dates where regime_key changes between consecutive rows.

    Parameters
    ----------
    regimes_df : pd.DataFrame
        Output of load_macro_regime_history().  Required columns:
        date (datetime), monetary_policy, liquidity, risk_appetite, carry,
        regime_key.  Use .tolist() internally for x-axis to avoid tz pitfall.
    overlay_df : pd.DataFrame or None
        Optional overlay for panel 1.  Required columns: date, value.
        If None, a placeholder annotation is shown.
    overlay_label : str
        Legend label for the overlay trace.  Default "Portfolio PnL".

    Returns
    -------
    go.Figure
        5-panel Plotly figure with plotly_dark template, height=800.
    """
    fig = make_subplots(
        rows=5,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.40, 0.15, 0.15, 0.15, 0.15],
        vertical_spacing=0.02,
    )

    # Handle empty regimes_df
    if regimes_df is None or len(regimes_df) == 0:
        fig.add_annotation(
            text="No macro regime data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(template="plotly_dark", height=800)
        return fig

    regimes_work = regimes_df.sort_values("date").reset_index(drop=True)

    # ── Panel 1: Overlay trace ─────────────────────────────────────────────
    if overlay_df is not None and len(overlay_df) > 0:
        overlay_work = overlay_df.sort_values("date").reset_index(drop=True)
        x_overlay = overlay_work["date"].tolist()
        fig.add_trace(
            go.Scatter(
                x=x_overlay,
                y=overlay_work["value"].tolist(),
                mode="lines",
                name=overlay_label,
                line={"color": "rgb(0,200,100)", "width": 1.5},
            ),
            row=1,
            col=1,
        )
    else:
        fig.add_annotation(
            text="Select an overlay in the sidebar",
            xref="x domain",
            yref="y domain",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 13, "color": "rgb(180,180,180)"},
            row=1,
            col=1,
        )

    # ── Compute transition dates (regime_key changes) ──────────────────────
    transition_dates: list = []
    for i in range(1, len(regimes_work)):
        if regimes_work.loc[i, "regime_key"] != regimes_work.loc[i - 1, "regime_key"]:
            transition_dates.append(regimes_work.loc[i, "date"])

    # ── Panels 2-5: Per-dimension vrect bands ─────────────────────────────
    for panel_idx, (dim_col, dim_label) in enumerate(_MACRO_DIMENSIONS, start=2):
        dim_colors = MACRO_DIMENSION_COLORS.get(dim_col, {})

        for i, row in regimes_work.iterrows():
            start_date = row["date"]
            label_val = str(row.get(dim_col, ""))

            # End of band: next row's date, or same day + 1 for last row
            if i + 1 < len(regimes_work):
                end_date = regimes_work.loc[i + 1, "date"]
            else:
                end_date = start_date + pd.Timedelta(days=1)

            color = dim_colors.get(label_val, _DIMENSION_FALLBACK_COLOR)

            fig.add_vrect(
                x0=start_date,
                x1=end_date,
                fillcolor=color,
                opacity=1,
                layer="below",
                line_width=0,
                row=panel_idx,  # type: ignore[arg-type]
                col=1,
            )

        # Set y-axis title for this dimension panel
        fig.update_yaxes(
            title_text=dim_label,
            showticklabels=False,
            row=panel_idx,
            col=1,
        )

    # ── Transition markers: vertical dashed lines on all panels ───────────
    for tr_date in transition_dates:
        # Find old -> new transition labels for hover annotation
        idx = regimes_work[regimes_work["date"] == tr_date].index
        if len(idx) > 0:
            i = idx[0]
            new_key = regimes_work.loc[i, "regime_key"]
            old_key = regimes_work.loc[i - 1, "regime_key"] if i > 0 else "?"
        else:
            old_key, new_key = "?", "?"

        hover_txt = f"{old_key} -> {new_key}"

        # Draw line on each panel (panels 1-5)
        for panel_row in range(1, 6):
            fig.add_vline(
                x=tr_date,
                line_dash="dash",
                line_color="rgba(255,255,255,0.35)",
                line_width=1,
                annotation_text=hover_txt if panel_row == 1 else "",
                annotation_font_size=9,
                annotation_position="top",
                row=panel_row,  # type: ignore[arg-type]
                col=1,
            )

    # ── Layout ────────────────────────────────────────────────────────────
    fig.update_yaxes(title_text=overlay_label, row=1, col=1)
    fig.update_xaxes(title_text="Date", row=5, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=800,
        showlegend=True,
    )

    return fig


def build_fred_quality_chart(quality_df: pd.DataFrame) -> go.Figure:
    """Build a horizontal bar chart showing FRED series coverage percentage.

    Bars are sorted ascending by coverage_pct (worst coverage at top).
    Color coding: green (>95%), orange (80-95%), red (<80%).

    Parameters
    ----------
    quality_df : pd.DataFrame
        Output of load_fred_series_quality() with columns:
        series_id, coverage_pct.

    Returns
    -------
    go.Figure
        Plotly horizontal bar chart with plotly_dark template.
    """
    fig = go.Figure()

    if quality_df is None or quality_df.empty:
        fig.add_annotation(
            text="No FRED quality data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(
            template="plotly_dark",
            title="FRED Series Data Coverage",
            height=400,
        )
        return fig

    # Sort ascending by coverage_pct (worst at top of horizontal bar chart)
    df_sorted = quality_df.sort_values("coverage_pct", ascending=True).reset_index(
        drop=True
    )

    def _bar_color(pct: float) -> str:
        if pct > 95:
            return "rgb(0,200,100)"
        if pct >= 80:
            return "rgb(255,165,0)"
        return "rgb(220,50,50)"

    colors = [_bar_color(float(p)) for p in df_sorted["coverage_pct"]]

    fig.add_trace(
        go.Bar(
            x=df_sorted["coverage_pct"].tolist(),
            y=df_sorted["series_id"].tolist(),
            orientation="h",
            marker={"color": colors},
            text=[f"{p:.1f}%" for p in df_sorted["coverage_pct"]],
            textposition="outside",
            name="Coverage %",
        )
    )

    fig.update_xaxes(title_text="Coverage %", range=[0, 110])
    fig.update_yaxes(title_text="Series ID")

    fig.update_layout(
        template="plotly_dark",
        title="FRED Series Data Coverage",
        height=max(300, 30 * len(df_sorted) + 80),
        showlegend=False,
    )

    return fig


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------


def chart_download_button(
    fig: go.Figure,
    label: str,
    filename: str,
) -> None:
    """
    Render a Streamlit download button that exports a Plotly figure as an HTML file.

    Uses fig.write_html() (no kaleido dependency). The exported HTML is self-contained
    with Plotly JS loaded from CDN.

    Parameters
    ----------
    fig : go.Figure
        Plotly figure to export.
    label : str
        Button label text shown to the user.
    filename : str
        Filename for the downloaded file (should end with .html).
    """
    import streamlit as st

    buffer = io.StringIO()
    fig.write_html(buffer, include_plotlyjs="cdn")
    html_bytes = buffer.getvalue().encode("utf-8")

    st.download_button(
        label=label,
        data=html_bytes,
        file_name=filename,
        mime="text/html",
    )


# ---------------------------------------------------------------------------
# Backtest and signal chart builders
# ---------------------------------------------------------------------------


def build_candlestick_chart(
    ohlcv_df: pd.DataFrame,
    ema_df: pd.DataFrame | None = None,
    regimes_df: pd.DataFrame | None = None,
    title: str = "",
) -> go.Figure:
    """
    Build an interactive OHLCV candlestick chart with optional overlays.

    Layout (shared x-axis):
      Row 1 (60%): Candlestick + EMA overlays + regime vrect bands
      Row 2 (20%): Volume bars
      Row 3 (20%): RSI-14 subplot (if rsi_14 column present)

    Parameters
    ----------
    ohlcv_df : pd.DataFrame
        OHLCV data with columns: ts (datetime), open, high, low, close, volume.
        Optionally includes rsi_14 for the RSI subplot.
        Use .tolist() on ts to avoid tz-aware datetime pitfall (MEMORY.md).
    ema_df : pd.DataFrame or None
        EMA data with columns: ts (datetime), period (int), ema_value (float).
        Each unique period gets its own line overlay on row 1.
    regimes_df : pd.DataFrame or None
        Regime data with columns: ts (datetime), trend_state (str).
        Consecutive rows with the same trend_state are grouped into vrect bands.
    title : str
        Chart title. Default empty string.

    Returns
    -------
    go.Figure
        3-row Plotly figure with plotly_dark template, height=600.
    """
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.60, 0.20, 0.20],
        vertical_spacing=0.03,
    )

    # Handle empty input
    if ohlcv_df is None or ohlcv_df.empty:
        fig.add_annotation(
            text="No OHLCV data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(
            template="plotly_dark",
            title=title or "Candlestick Chart",
            height=600,
        )
        return fig

    # Ensure ts is a column, not the index
    if "ts" not in ohlcv_df.columns:
        ohlcv_work = ohlcv_df.reset_index()
        if "ts" not in ohlcv_work.columns:
            ohlcv_work = ohlcv_work.rename(columns={ohlcv_work.columns[0]: "ts"})
    else:
        ohlcv_work = ohlcv_df.copy()

    ohlcv_work = ohlcv_work.sort_values("ts").reset_index(drop=True)

    # CRITICAL: .tolist() avoids tz-aware datetime .values pitfall (MEMORY.md)
    x_ts = ohlcv_work["ts"].tolist()

    # ── Row 1: Candlestick ────────────────────────────────────────────────
    fig.add_trace(
        go.Candlestick(
            x=x_ts,
            open=ohlcv_work["open"],
            high=ohlcv_work["high"],
            low=ohlcv_work["low"],
            close=ohlcv_work["close"],
            name="OHLCV",
            increasing_line_color="rgb(0,200,100)",
            decreasing_line_color="rgb(220,50,50)",
            increasing_fillcolor="rgb(0,200,100)",
            decreasing_fillcolor="rgb(220,50,50)",
        ),
        row=1,
        col=1,
    )

    # ── Row 1: EMA overlays ───────────────────────────────────────────────
    if ema_df is not None and not ema_df.empty:
        # Normalize ts to column
        if "ts" not in ema_df.columns:
            ema_work = ema_df.reset_index()
            if "ts" not in ema_work.columns:
                ema_work = ema_work.rename(columns={ema_work.columns[0]: "ts"})
        else:
            ema_work = ema_df.copy()

        # EMA line colors cycle through a fixed palette
        _ema_colors = [
            "rgb(255,165,0)",  # orange
            "rgb(100,149,237)",  # cornflower blue
            "rgb(255,105,180)",  # hot pink
            "rgb(144,238,144)",  # light green
            "rgb(255,215,0)",  # gold
        ]

        if "period" in ema_work.columns:
            periods = sorted(ema_work["period"].unique())
            for i, period in enumerate(periods):
                period_df = ema_work[ema_work["period"] == period].sort_values("ts")
                color = _ema_colors[i % len(_ema_colors)]
                fig.add_trace(
                    go.Scatter(
                        x=period_df["ts"].tolist(),
                        y=period_df["ema_value"]
                        if "ema_value" in period_df.columns
                        else period_df.iloc[:, -1],
                        mode="lines",
                        name=f"EMA-{period}",
                        line={"color": color, "width": 1.2},
                    ),
                    row=1,
                    col=1,
                )

    # ── Row 1: Regime vrect bands ─────────────────────────────────────────
    if regimes_df is not None and not regimes_df.empty:
        # Normalize ts to column
        if "ts" not in regimes_df.columns:
            regimes_work = regimes_df.reset_index()
            if "ts" not in regimes_work.columns:
                regimes_work = regimes_work.rename(
                    columns={regimes_work.columns[0]: "ts"}
                )
        else:
            regimes_work = regimes_df.copy()

        regimes_work = regimes_work.sort_values("ts").reset_index(drop=True)

        # Group consecutive rows with the same trend_state into bands
        if "trend_state" in regimes_work.columns and len(ohlcv_work) > 0:
            last_price_ts = ohlcv_work["ts"].iloc[-1]

            for i, row in regimes_work.iterrows():
                start_ts = row["ts"]
                trend_state = str(row.get("trend_state", "Sideways"))

                if i + 1 < len(regimes_work):
                    end_ts = regimes_work.loc[i + 1, "ts"]
                else:
                    end_ts = last_price_ts

                color = REGIME_COLORS.get(trend_state, REGIME_COLORS["Sideways"])

                fig.add_vrect(
                    x0=start_ts,
                    x1=end_ts,
                    fillcolor=color,
                    opacity=1,
                    layer="below",
                    line_width=0,
                    row=1,  # type: ignore[arg-type]
                    col=1,
                )

    # ── Row 2: Volume bars ────────────────────────────────────────────────
    if "volume" in ohlcv_work.columns:
        # Color volume bars green/red based on close vs open
        vol_colors = [
            "rgb(0,200,100)" if c >= o else "rgb(220,50,50)"
            for c, o in zip(ohlcv_work["close"], ohlcv_work["open"])
        ]
        fig.add_trace(
            go.Bar(
                x=x_ts,
                y=ohlcv_work["volume"],
                name="Volume",
                marker={"color": vol_colors},
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    # ── Row 3: RSI-14 subplot ─────────────────────────────────────────────
    if "rsi_14" in ohlcv_work.columns:
        fig.add_trace(
            go.Scatter(
                x=x_ts,
                y=ohlcv_work["rsi_14"],
                mode="lines",
                name="RSI-14",
                line={"color": "rgb(255,165,0)", "width": 1.2},
            ),
            row=3,
            col=1,
        )
        # Overbought / oversold reference lines
        fig.add_hline(
            y=70,
            line_dash="dash",
            line_color="rgba(220,50,50,0.6)",
            line_width=1,
            row=3,
            col=1,
        )  # type: ignore[arg-type]
        fig.add_hline(
            y=30,
            line_dash="dash",
            line_color="rgba(0,200,100,0.6)",
            line_width=1,
            row=3,
            col=1,
        )  # type: ignore[arg-type]

    # ── Layout ────────────────────────────────────────────────────────────
    fig.update_xaxes(rangeslider_visible=False)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])

    fig.update_layout(
        template="plotly_dark",
        title=title or "Candlestick",
        height=600,
        showlegend=True,
    )

    return fig


def build_equity_sparkline(
    fold_metrics: list[dict],
    height: int = 150,
) -> go.Figure:
    """
    Build a compact cumulative return sparkline from bakeoff fold metrics.

    Plots each fold's total_return as a cumulative equity curve.

    Parameters
    ----------
    fold_metrics : list[dict]
        Deserialized fold_metrics_json from strategy_bakeoff_results.
        Each dict is expected to contain at least a 'total_return' key.
        If empty or None, returns a placeholder figure.
    height : int
        Figure height in pixels. Default 150 for compact sparkline.

    Returns
    -------
    go.Figure
        Plotly figure with plotly_dark template and no margins.
    """
    fig = go.Figure()

    if not fold_metrics:
        fig.add_annotation(
            text="No fold data",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 12, "color": "rgb(150,150,150)"},
        )
        fig.update_layout(
            template="plotly_dark",
            height=height,
            margin={"l": 0, "r": 0, "t": 0, "b": 0},
            showlegend=False,
        )
        return fig

    # Build cumulative equity from fold total_return values
    cumulative: list[float] = [0.0]
    fold_labels: list[str] = ["Start"]
    running = 0.0

    for i, fold in enumerate(fold_metrics):
        ret = fold.get("total_return", 0.0)
        if ret is None:
            ret = 0.0
        running += float(ret)
        cumulative.append(running)
        fold_labels.append(f"Fold {i + 1}")

    # Color based on final return
    final_return = cumulative[-1]
    line_color = "rgb(0,200,100)" if final_return >= 0 else "rgb(220,50,50)"

    fig.add_trace(
        go.Scatter(
            x=fold_labels,
            y=cumulative,
            mode="lines+markers",
            name="Cumulative Return",
            line={"color": line_color, "width": 1.5},
            marker={"size": 4},
        )
    )

    # Add zero reference line
    fig.add_hline(
        y=0,
        line_dash="dot",
        line_color="rgba(150,150,150,0.5)",
        line_width=1,
    )

    fig.update_layout(
        template="plotly_dark",
        height=height,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        showlegend=False,
        yaxis_title="Cumul. Return",
    )

    return fig


def build_signal_timeline_chart(
    history_df: pd.DataFrame,
    title: str = "Signal History",
) -> go.Figure:
    """
    Build a horizontal bar chart showing signal on/off periods over time.

    Each bar spans from entry_ts to exit_ts (or now if position is still open).
    Bars are colored by direction: long=green, short=red.

    Parameters
    ----------
    history_df : pd.DataFrame
        Output of load_signal_history() with columns: symbol, signal_name,
        direction, entry_ts, exit_ts, position_state, pnl_pct.
        ts columns should be tz-aware UTC datetimes.
    title : str
        Chart title. Default "Signal History".

    Returns
    -------
    go.Figure
        Plotly figure with plotly_dark template, height=400.
    """

    fig = go.Figure()

    if history_df is None or history_df.empty:
        fig.add_annotation(
            text="No signal history available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        fig.update_layout(
            template="plotly_dark",
            title=title,
            height=400,
        )
        return fig

    now_utc = pd.Timestamp.now(tz="UTC")

    # Build y-axis labels: "SYMBOL | signal_name"
    def _row_label(row: pd.Series) -> str:
        symbol = str(row.get("symbol", row.get("id", "?")))
        sig_name = str(row.get("signal_name", row.get("signal_id", "")))
        return f"{symbol} | {sig_name}"

    _direction_colors: dict[str, str] = {
        "long": "rgb(0,200,100)",
        "short": "rgb(220,50,50)",
        "flat": "rgb(150,150,150)",
    }

    for _, row in history_df.iterrows():
        entry_ts = row.get("entry_ts")
        exit_ts = row.get("exit_ts")
        position_state = str(row.get("position_state", "closed"))
        direction = str(row.get("direction", "flat")).lower()
        pnl_pct = row.get("pnl_pct")

        # Use now for open positions without exit_ts
        if (
            exit_ts is None
            or (hasattr(exit_ts, "isnull") and exit_ts.isnull())
            or (isinstance(exit_ts, float) and pd.isna(exit_ts))
        ):
            exit_ts = now_utc

        if entry_ts is None or (isinstance(entry_ts, float) and pd.isna(entry_ts)):
            continue

        label = _row_label(row)
        color = _direction_colors.get(direction, _direction_colors["flat"])

        pnl_text = (
            f"{float(pnl_pct):.2f}%"
            if pnl_pct is not None
            and not (isinstance(pnl_pct, float) and pd.isna(pnl_pct))
            else "Open"
        )
        hover_text = (
            f"Symbol: {row.get('symbol', '?')}<br>"
            f"Signal: {row.get('signal_name', '?')}<br>"
            f"Direction: {direction}<br>"
            f"Entry: {entry_ts}<br>"
            f"Exit: {exit_ts if position_state == 'closed' else 'Open'}<br>"
            f"PnL: {pnl_text}"
        )

        fig.add_trace(
            go.Bar(
                x=[pd.Timestamp(exit_ts) - pd.Timestamp(entry_ts)],
                y=[label],
                base=[entry_ts],
                orientation="h",
                marker={"color": color},
                text=pnl_text,
                textposition="inside",
                hovertext=hover_text,
                hoverinfo="text",
                showlegend=False,
                name=direction,
            )
        )

    fig.update_layout(
        template="plotly_dark",
        title=title,
        height=max(400, 30 * len(history_df) + 80),
        barmode="overlay",
        xaxis={
            "type": "date",
            "title": "Date",
        },
        yaxis={"title": "Asset | Signal"},
    )

    return fig
