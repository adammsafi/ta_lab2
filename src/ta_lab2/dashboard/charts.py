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
