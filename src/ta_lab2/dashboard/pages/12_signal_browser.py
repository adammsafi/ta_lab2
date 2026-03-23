# -*- coding: utf-8 -*-
"""
Signal Browser dashboard page -- Phase 83 Signal Pages.

Displays all currently active (open) signals across EMA crossover, RSI
mean-revert, and ATR breakout generators.  Three switchable views:
  - Dashboard Cards: visual grid of signal cards
  - Live Table: sortable dataframe with ProgressColumn for signal strength
  - Heatmap Grid: assets x strategies direction pivot

Below the active views: Signal History with a timeline chart, event log
table, and CSV download.

NOTE: Do NOT call st.set_page_config() here -- it is called in the main
app entry point (app.py / Home.py).
"""

from __future__ import annotations


import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ta_lab2.dashboard.charts import (
    build_signal_timeline_chart,
    chart_download_button,
)
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.signals import (
    load_active_signals,
    load_signal_history,
    load_signal_strategies,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AUTO_REFRESH_SECONDS = 300

_VIEW_OPTIONS = ["Dashboard Cards", "Live Table", "Heatmap Grid"]
_DIRECTION_OPTIONS = ["All", "long", "short"]
_HISTORY_DAY_OPTIONS = [7, 14, 30, 60, 90]

# ---------------------------------------------------------------------------
# URL state (module level -- must be outside fragment)
# ---------------------------------------------------------------------------

_qp = st.query_params

_default_view = _qp.get("view", "Live Table")
if _default_view not in _VIEW_OPTIONS:
    _default_view = "Live Table"

_default_direction = _qp.get("direction", "All")
if _default_direction not in _DIRECTION_OPTIONS:
    _default_direction = "All"

_default_asset = _qp.get("asset", "")
_default_strategy = _qp.get("strategy_type", "")

# ---------------------------------------------------------------------------
# Signal strength computation (module level helper)
# ---------------------------------------------------------------------------


def compute_signal_strength(feature_snapshot: dict | None) -> int:
    """Compute a 0-100 signal strength score from a feature_snapshot JSONB dict.

    Uses defensive .get() for ALL dictionary accesses so missing keys (which
    vary by signal generator) never raise KeyError.

    Components:
    - Base: 20 points (always)
    - EMA separation (0-30): abs(fast_ema - slow_ema) / close * 100, clamped
    - RSI extremity (0-30): abs(rsi_14 - 50) / 50 * 30, clamped
    - ATR magnitude (0-20): atr_14 / close * 100 * 10, clamped
    """
    if feature_snapshot is None:
        return 50  # neutral default

    score: float = 20.0  # base

    close = feature_snapshot.get("close", None)
    fast_ema = feature_snapshot.get("fast_ema", None)
    slow_ema = feature_snapshot.get("slow_ema", None)
    rsi_14 = feature_snapshot.get("rsi_14", None)
    atr_14 = feature_snapshot.get("atr_14", None)

    # EMA separation component (0-30 pts)
    if close is not None and fast_ema is not None and slow_ema is not None:
        try:
            close_f = float(close)
            if close_f > 0:
                ema_sep = abs(float(fast_ema) - float(slow_ema)) / close_f * 100
                score += max(0.0, min(30.0, ema_sep))
        except (TypeError, ValueError):
            pass

    # RSI extremity component (0-30 pts)
    if rsi_14 is not None:
        try:
            rsi_f = float(rsi_14)
            rsi_pts = abs(rsi_f - 50.0) / 50.0 * 30.0
            score += max(0.0, min(30.0, rsi_pts))
        except (TypeError, ValueError):
            pass

    # ATR magnitude component (0-20 pts)
    if atr_14 is not None and close is not None:
        try:
            close_f = float(close)
            if close_f > 0:
                atr_pts = float(atr_14) / close_f * 100.0 * 10.0
                score += max(0.0, min(20.0, atr_pts))
        except (TypeError, ValueError):
            pass

    return int(max(0, min(100, round(score))))


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Signal Browser")
st.caption(
    "Live monitoring of active signals across EMA crossover, RSI mean-revert, "
    "and ATR breakout generators.  Auto-refreshes every 5 minutes."
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
# Sidebar controls (outside fragment)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Signal Filters")

    view_choice = st.radio(
        "Active Signal View",
        _VIEW_OPTIONS,
        index=_VIEW_OPTIONS.index(_default_view),
        horizontal=True,
        key="sb_view_radio",
    )

    available_strategies = load_signal_strategies(engine)

    strategy_filter = st.multiselect(
        "Strategy",
        options=available_strategies,
        default=[s for s in [_default_strategy] if s in available_strategies]
        if _default_strategy
        else [],
        key="sb_strategy_filter",
    )

    direction_filter = st.selectbox(
        "Direction",
        options=_DIRECTION_OPTIONS,
        index=_DIRECTION_OPTIONS.index(_default_direction),
        key="sb_direction_filter",
    )

    asset_search = st.text_input(
        "Search asset (symbol)",
        value=_default_asset,
        placeholder="e.g. BTC, ETH",
        key="sb_asset_search",
    )

    history_days = st.select_slider(
        "History (days)",
        options=_HISTORY_DAY_OPTIONS,
        value=30,
        key="sb_history_days",
    )

    # Update URL query params from sidebar selections
    st.query_params["view"] = view_choice
    st.query_params["direction"] = direction_filter
    st.query_params["asset"] = asset_search
    if strategy_filter:
        st.query_params["strategy_type"] = strategy_filter[0]
    else:
        if "strategy_type" in st.query_params:
            del st.query_params["strategy_type"]


# ---------------------------------------------------------------------------
# Helper: apply sidebar filters to a signals DataFrame
# ---------------------------------------------------------------------------


def _apply_filters(
    df: pd.DataFrame,
    strategy_filter: list[str],
    direction_filter: str,
    asset_search: str,
) -> pd.DataFrame:
    """Return a filtered copy of the signals DataFrame based on sidebar controls."""
    if df.empty:
        return df

    if strategy_filter:
        strategy_col = "signal_type" if "signal_type" in df.columns else None
        if strategy_col:
            df = df[df[strategy_col].isin(strategy_filter)]

    if direction_filter != "All" and "direction" in df.columns:
        df = df[df["direction"] == direction_filter]

    if asset_search and "symbol" in df.columns:
        mask = df["symbol"].str.upper().str.contains(asset_search.upper(), na=False)
        df = df[mask]

    return df


# ---------------------------------------------------------------------------
# Helper: format relative time
# ---------------------------------------------------------------------------


def _relative_time(ts) -> str:
    """Return human-readable relative time from a tz-aware timestamp."""
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return "unknown"
    try:
        now = pd.Timestamp.now(tz="UTC")
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        delta = now - ts
        days = delta.days
        hours = int(delta.total_seconds() // 3600)
        if days >= 1:
            return f"{days}d ago"
        elif hours >= 1:
            return f"{hours}h ago"
        else:
            mins = int(delta.total_seconds() // 60)
            return f"{max(1, mins)}m ago"
    except Exception:  # noqa: BLE001
        return str(ts)


# ---------------------------------------------------------------------------
# Auto-refreshing content fragment
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _signal_browser_content(
    _engine, view_choice, strategy_filter, direction_filter, asset_search, history_days
):
    """Auto-refreshing signal browser content."""

    # -----------------------------------------------------------------------
    # Load active signals
    # -----------------------------------------------------------------------

    try:
        active_df = load_active_signals(_engine)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to load active signals: {exc}")
        active_df = pd.DataFrame()

    # Apply sidebar filters
    filtered_df = _apply_filters(
        active_df.copy() if not active_df.empty else active_df,
        strategy_filter,
        direction_filter,
        asset_search,
    )

    # -----------------------------------------------------------------------
    # Compute signal_strength for filtered rows
    # -----------------------------------------------------------------------

    if not filtered_df.empty:
        # feature_snapshot may not be in the query results -- handle gracefully
        if "feature_snapshot" in filtered_df.columns:
            filtered_df["signal_strength"] = filtered_df["feature_snapshot"].apply(
                lambda x: compute_signal_strength(x if isinstance(x, dict) else None)
            )
        else:
            filtered_df["signal_strength"] = 50

    # -----------------------------------------------------------------------
    # Summary metrics row
    # -----------------------------------------------------------------------

    total_active = len(filtered_df)
    long_count = (
        int((filtered_df["direction"] == "long").sum()) if not filtered_df.empty else 0
    )
    short_count = (
        int((filtered_df["direction"] == "short").sum()) if not filtered_df.empty else 0
    )

    # Build by-strategy counts
    if not filtered_df.empty and "signal_type" in filtered_df.columns:
        by_strategy = filtered_df.groupby("signal_type").size().to_dict()
        strategy_summary = ", ".join(
            f"{k.replace('_', ' ')}: {v}" for k, v in sorted(by_strategy.items())
        )
    else:
        strategy_summary = "N/A"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Active", total_active)
    c2.metric("Long", long_count)
    c3.metric("Short", short_count)
    c4.metric("By Strategy", strategy_summary)

    st.divider()

    # -----------------------------------------------------------------------
    # Active signal views
    # -----------------------------------------------------------------------

    if view_choice == "Dashboard Cards":
        _render_cards_view(filtered_df)

    elif view_choice == "Live Table":
        _render_table_view(filtered_df)

    else:  # Heatmap Grid
        _render_heatmap_view(filtered_df)

    st.divider()

    # -----------------------------------------------------------------------
    # Signal History section
    # -----------------------------------------------------------------------

    st.subheader("Signal History")

    # Determine strategy_type filter for history query
    history_strategy = strategy_filter[0] if len(strategy_filter) == 1 else None

    try:
        history_df = load_signal_history(
            _engine, strategy_type=history_strategy, days=history_days
        )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load signal history: {exc}")
        history_df = pd.DataFrame()

    # Apply additional filters not supported by query layer
    history_filtered = _apply_filters(
        history_df.copy() if not history_df.empty else history_df,
        strategy_filter,
        direction_filter,
        asset_search,
    )

    # Timeline chart
    try:
        title = f"Signal History (last {history_days} days)"
        if not history_filtered.empty:
            title += f" — {len(history_filtered)} events"
        fig_timeline = build_signal_timeline_chart(history_filtered, title=title)
        st.plotly_chart(
            fig_timeline, use_container_width=True, theme=None, key="sig_timeline_chart"
        )
        chart_download_button(
            fig_timeline,
            label="Download timeline chart",
            filename=f"signal_timeline_{history_days}d.html",
        )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render signal timeline: {exc}")

    # Event log table
    if not history_filtered.empty:
        st.subheader("Event Log")

        event_cols = [
            c
            for c in [
                "ts",
                "symbol",
                "signal_type",
                "direction",
                "position_state",
                "entry_price",
                "exit_price",
                "pnl_pct",
            ]
            if c in history_filtered.columns
        ]

        event_display = history_filtered[event_cols].copy()

        # Format ts columns for display
        for col in ("ts", "entry_ts", "exit_ts"):
            if col in event_display.columns:
                event_display[col] = event_display[col].apply(
                    lambda x: x.strftime("%Y-%m-%d %H:%M UTC")
                    if hasattr(x, "strftime")
                    else str(x)
                )

        st.dataframe(
            event_display.reset_index(drop=True),
            use_container_width=True,
            key="sig_event_log_table",
        )

        # CSV download
        csv_bytes = history_filtered[event_cols].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download event log as CSV",
            data=csv_bytes,
            file_name=f"signal_history_{history_days}d.csv",
            mime="text/csv",
            key="sig_history_csv_download",
        )
    else:
        st.info(
            f"No signal history found in the last {history_days} days with current filters."
        )

    st.caption(f"Auto-refreshes every {AUTO_REFRESH_SECONDS // 60} minutes")


# ---------------------------------------------------------------------------
# View renderers (called from inside the fragment)
# ---------------------------------------------------------------------------


def _render_cards_view(df: pd.DataFrame) -> None:
    """Render the Dashboard Cards view -- 3 cards per row."""
    if df.empty:
        st.info("No active signals matching current filters.")
        return

    display_df = df.head(30)
    if len(df) > 30:
        st.caption(f"Showing 30 of {len(df)} active signals")

    rows = [display_df.iloc[i : i + 3] for i in range(0, len(display_df), 3)]

    for row_df in rows:
        cols = st.columns(3)
        for col_idx, (_, row) in enumerate(row_df.iterrows()):
            with cols[col_idx]:
                _render_single_card(row)


def _render_single_card(row: pd.Series) -> None:
    """Render a single signal card."""
    symbol = str(row.get("symbol", row.get("id", "?")))
    strategy = str(row.get("signal_type", row.get("signal_name", "unknown")))
    direction = str(row.get("direction", "flat")).lower()
    entry_price = row.get("entry_price")
    entry_ts = row.get("entry_ts")
    pnl_pct = row.get("pnl_pct")
    regime_key = row.get("regime_key", None)
    signal_strength = int(row.get("signal_strength", 50))

    # Direction color
    if direction == "long":
        dir_color = "#00c864"
        dir_label = "LONG"
    elif direction == "short":
        dir_color = "#dc3232"
        dir_label = "SHORT"
    else:
        dir_color = "#969696"
        dir_label = direction.upper()

    with st.container(border=True):
        # Top row: symbol + direction badge
        top_c1, top_c2 = st.columns([2, 1])
        with top_c1:
            st.markdown(f"**{symbol}**")
            st.caption(strategy.replace("_", " "))
        with top_c2:
            st.markdown(
                f'<span style="background-color:{dir_color};padding:2px 8px;'
                f'border-radius:3px;font-weight:bold;font-size:0.85em;color:#fff">'
                f"{dir_label}</span>",
                unsafe_allow_html=True,
            )

        # Middle row: entry info
        entry_str = f"${entry_price:,.4f}" if entry_price is not None else "N/A"
        time_str = _relative_time(entry_ts)
        st.caption(f"Entry: {entry_str} · {time_str}")

        # PnL if available
        if pnl_pct is not None:
            try:
                pnl_f = float(pnl_pct)
                pnl_color = "#00c864" if pnl_f >= 0 else "#dc3232"
                st.markdown(
                    f'<span style="color:{pnl_color};font-weight:bold">'
                    f"PnL: {pnl_f:+.2f}%</span>",
                    unsafe_allow_html=True,
                )
            except (TypeError, ValueError):
                pass

        # Signal strength bar
        st.progress(
            signal_strength / 100,
            text=f"Strength: {signal_strength}/100",
        )

        # Regime key if available
        if regime_key:
            st.caption(f"Regime: {regime_key}")


def _render_table_view(df: pd.DataFrame) -> None:
    """Render the Live Table view with ProgressColumn for signal_strength."""
    if df.empty:
        st.info("No active signals matching current filters.")
        return

    display_cols = [
        c
        for c in [
            "symbol",
            "signal_type",
            "direction",
            "entry_price",
            "entry_ts",
            "signal_strength",
            "regime_key",
            "signal_id",
        ]
        if c in df.columns
    ]

    display_df = df[display_cols].copy()

    # Format entry_ts for display
    if "entry_ts" in display_df.columns:
        display_df["entry_ts"] = display_df["entry_ts"].apply(
            lambda x: x.strftime("%Y-%m-%d %H:%M UTC")
            if hasattr(x, "strftime")
            else str(x)
        )

    # Build column config
    col_config = {}

    if "signal_strength" in display_df.columns:
        col_config["signal_strength"] = st.column_config.ProgressColumn(
            "Strength",
            min_value=0,
            max_value=100,
            format="%d",
        )

    if "direction" in display_df.columns:
        col_config["direction"] = st.column_config.TextColumn("Direction")

    st.dataframe(
        display_df.reset_index(drop=True),
        use_container_width=True,
        column_config=col_config,
        key="sig_live_table",
    )


def _render_heatmap_view(df: pd.DataFrame) -> None:
    """Render the Heatmap Grid view: symbols x strategies, color=direction."""
    if df.empty:
        st.info("No active signals matching current filters.")
        return

    if "symbol" not in df.columns or "signal_type" not in df.columns:
        st.warning("Heatmap requires symbol and signal_type columns.")
        return

    # Build pivot: rows=symbols, cols=strategy_types
    # Value: direction string or ""
    pivot = df.pivot_table(
        index="symbol",
        columns="signal_type",
        values="direction",
        aggfunc="first",
        fill_value="",
    )
    pivot = pivot.sort_index()

    symbols = pivot.index.tolist()
    strategies = pivot.columns.tolist()

    # Encode direction to numeric for color scale
    # long=1, short=-1, none=0
    def _dir_to_num(d: str) -> float:
        if d == "long":
            return 1.0
        elif d == "short":
            return -1.0
        return 0.0

    z_matrix = [
        [_dir_to_num(pivot.at[sym, strat]) for strat in strategies] for sym in symbols
    ]
    text_matrix = [[pivot.at[sym, strat] for strat in strategies] for sym in symbols]

    fig = go.Figure(
        data=go.Heatmap(
            z=z_matrix,
            x=strategies,
            y=symbols,
            text=text_matrix,
            texttemplate="%{text}",
            colorscale=[
                [0.0, "rgb(220,50,50)"],  # short = red
                [0.5, "rgb(60,60,80)"],  # none = dark gray
                [1.0, "rgb(0,200,100)"],  # long = green
            ],
            zmin=-1,
            zmax=1,
            showscale=True,
            colorbar=dict(
                tickvals=[-1, 0, 1],
                ticktext=["Short", "None", "Long"],
            ),
        )
    )
    fig.update_layout(
        template="plotly_dark",
        title="Active Signals Heatmap (assets x strategies)",
        xaxis_title="Strategy",
        yaxis_title="Asset",
        height=max(400, 20 * len(symbols) + 100),
        margin=dict(l=80, r=40, t=60, b=60),
    )

    st.plotly_chart(fig, use_container_width=True, theme=None, key="sig_heatmap_chart")
    chart_download_button(
        fig,
        label="Download heatmap chart",
        filename="signal_heatmap.html",
    )


# ---------------------------------------------------------------------------
# Invoke fragment
# ---------------------------------------------------------------------------

_signal_browser_content(
    engine,
    view_choice,
    strategy_filter,
    direction_filter,
    asset_search,
    history_days,
)
