# -*- coding: utf-8 -*-
"""
Drift Monitor page -- Phase 52 Operational Dashboard.

Displays drift tracking error time series with threshold lines (DASH-L04),
paper vs replay equity overlay, drift summary cards, and attribution breakdown.

NOTE: Do NOT call st.set_page_config() here -- it is called in the main app
entry point (app.py). Calling it again from a page script raises a
StreamlitAPIException.
"""

from __future__ import annotations

import streamlit as st

from ta_lab2.dashboard.charts import (
    build_equity_overlay_chart,
    build_tracking_error_chart,
    chart_download_button,
)
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.drift import (
    load_drift_summary,
    load_drift_timeseries,
    load_executor_configs,
)
from ta_lab2.dashboard.queries.risk import load_risk_limits, load_risk_state

# ---------------------------------------------------------------------------
# Auto-refresh interval
# ---------------------------------------------------------------------------

AUTO_REFRESH_SECONDS = 900

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Drift Monitor")
st.caption("Paper vs replay tracking error and equity overlay")

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:  # noqa: BLE001
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Alert banners (outside fragment -- always visible)
# ---------------------------------------------------------------------------

try:
    risk_state = load_risk_state(engine)

    if risk_state.get("drift_paused"):
        paused_at = risk_state.get("drift_paused_at", "unknown time")
        paused_reason = risk_state.get("drift_paused_reason", "no reason recorded")
        st.warning(
            f"Drift monitoring paused since {paused_at}. Reason: {paused_reason}"
        )

    if risk_state.get("trading_state") == "halted":
        halted_at = risk_state.get("halted_at", "unknown time")
        halted_reason = risk_state.get("halted_reason", "no reason recorded")
        halted_by = risk_state.get("halted_by", "system")
        st.error(
            f"Trading HALTED since {halted_at} by {halted_by}. Reason: {halted_reason}"
        )

except Exception as exc:  # noqa: BLE001
    st.warning(f"Could not load risk state: {exc}")

# ---------------------------------------------------------------------------
# Sidebar controls (outside fragment)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Controls")

    # Load active executor configs for the strategy selector
    try:
        configs_df = load_executor_configs(engine)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load configs: {exc}")
        configs_df = None

    if configs_df is not None and not configs_df.empty:
        config_options = configs_df["config_name"].tolist()
        config_ids = configs_df["config_id"].tolist()
        selected_config_name = st.selectbox("Strategy", config_options)
        selected_config_id = config_ids[config_options.index(selected_config_name)]
    else:
        st.info("No active executor configurations.")
        selected_config_id = None
        selected_config_name = None

    history_days = st.select_slider(
        "History (days)",
        options=[7, 14, 30, 60, 90],
        value=30,
    )

    show_history = st.checkbox("Show 7-day history table", value=False)


# ---------------------------------------------------------------------------
# Auto-refreshing content section
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _drift_content(_engine, selected_config_id, history_days, show_history):
    """Auto-refreshing drift metrics section."""

    # -----------------------------------------------------------------------
    # Drift Summary Cards
    # -----------------------------------------------------------------------

    st.subheader("Drift Summary")

    try:
        summary_df = load_drift_summary(_engine)

        if summary_df.empty:
            st.info("No drift metrics computed yet. Run the drift monitor first.")
            summary_df = None
        elif selected_config_id is not None:
            config_summary = summary_df[summary_df["config_id"] == selected_config_id]
            if config_summary.empty:
                st.info(
                    f"No drift data for config {selected_config_id}. "
                    "Run the drift monitor first."
                )
                summary_df = None
            else:
                summary_df = config_summary

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load drift summary: {exc}")
        summary_df = None

    if summary_df is not None and not summary_df.empty:
        # Aggregate across assets if multiple rows (one per asset)
        current_te_5d = summary_df["current_tracking_error_5d"].mean()
        avg_te_5d = summary_df["avg_tracking_error_5d"].mean()
        avg_te_30d = summary_df["avg_tracking_error_30d"].mean()
        days_monitored = int(summary_df["days_monitored"].max())
        breach_count = int(summary_df["breach_count"].sum())
        last_metric_date = summary_df["last_metric_date"].max()

        te_5d_delta = current_te_5d - avg_te_5d if avg_te_5d else None

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Current TE 5d",
            f"{current_te_5d:.4f}" if current_te_5d is not None else "N/A",
            delta=f"{te_5d_delta:+.4f}" if te_5d_delta is not None else None,
            delta_color="inverse",
        )
        c2.metric(
            "Avg TE 30d",
            f"{avg_te_30d:.4f}" if avg_te_30d is not None else "N/A",
        )
        c3.metric("Days Monitored", days_monitored)
        c4.metric(
            "Threshold Breaches",
            breach_count,
            delta=-breach_count if breach_count > 0 else None,
            delta_color="inverse",
        )
    else:
        last_metric_date = None

    st.divider()

    # -----------------------------------------------------------------------
    # Load timeseries data (shared for both charts below)
    # -----------------------------------------------------------------------

    drift_df = None

    if selected_config_id is not None:
        try:
            drift_df = load_drift_timeseries(_engine, selected_config_id, history_days)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load drift timeseries: {exc}")

    # Load risk limits for threshold lines
    try:
        risk_limits = load_risk_limits(_engine)
        threshold_5d = risk_limits.get("drift_tracking_error_threshold_5d")
        threshold_30d = risk_limits.get("drift_tracking_error_threshold_30d")
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load risk limits: {exc}")
        threshold_5d = None
        threshold_30d = None

    # -----------------------------------------------------------------------
    # Tracking Error Chart (DASH-L04)
    # -----------------------------------------------------------------------

    st.subheader("Tracking Error Time Series")

    if selected_config_id is None:
        st.info("Select a strategy in the sidebar to view tracking error.")
    else:
        te_fig = build_tracking_error_chart(drift_df, threshold_5d, threshold_30d)
        st.plotly_chart(te_fig, use_container_width=True, theme=None)
        chart_download_button(
            te_fig,
            label="Download TE chart",
            filename="tracking_error.html",
        )

        if last_metric_date is not None:
            st.caption(f"Data as of {last_metric_date}")
        elif drift_df is not None and not drift_df.empty:
            st.caption(
                f"Data as of {drift_df['metric_date'].max().strftime('%Y-%m-%d')}"
            )

    st.divider()

    # -----------------------------------------------------------------------
    # Equity Overlay Chart
    # -----------------------------------------------------------------------

    st.subheader("Paper vs Replay Equity")

    if selected_config_id is None:
        st.info("Select a strategy in the sidebar to view equity overlay.")
    else:
        eq_fig = build_equity_overlay_chart(drift_df)
        st.plotly_chart(eq_fig, use_container_width=True, theme=None)
        chart_download_button(
            eq_fig,
            label="Download equity chart",
            filename="equity_overlay.html",
        )

    st.divider()

    # -----------------------------------------------------------------------
    # Drift Attribution (expandable)
    # -----------------------------------------------------------------------

    with st.expander("Attribution Breakdown"):
        if drift_df is not None and not drift_df.empty:
            attribution_cols = [
                "attr_fee_delta",
                "attr_slippage_delta",
                "attr_timing_delta",
                "attr_data_revision_delta",
                "attr_sizing_delta",
                "attr_regime_delta",
                "attr_unexplained_delta",
            ]
            present_cols = [c for c in attribution_cols if c in drift_df.columns]

            if present_cols:
                latest_row = drift_df.iloc[-1]
                display_labels = {
                    "attr_fee_delta": "Fees",
                    "attr_slippage_delta": "Slippage",
                    "attr_timing_delta": "Timing",
                    "attr_data_revision_delta": "Data Revision",
                    "attr_sizing_delta": "Sizing",
                    "attr_regime_delta": "Regime",
                    "attr_unexplained_delta": "Unexplained",
                }
                attr_cols = st.columns(min(len(present_cols), 4))
                for i, col_name in enumerate(present_cols):
                    label = display_labels.get(col_name, col_name)
                    value = latest_row[col_name]
                    attr_cols[i % len(attr_cols)].metric(
                        label,
                        f"${value:,.2f}" if value is not None else "N/A",
                    )
            else:
                st.info("Attribution not yet computed.")
        else:
            st.info("Attribution not yet computed.")

    # -----------------------------------------------------------------------
    # Drift Summary Table (collapsible based on checkbox)
    # -----------------------------------------------------------------------

    if show_history:
        st.subheader("Full Drift Summary Table")
        try:
            full_summary = load_drift_summary(_engine)
            if full_summary.empty:
                st.info("No drift metrics computed yet.")
            else:
                st.dataframe(full_summary, use_container_width=True)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load drift summary table: {exc}")

    # -----------------------------------------------------------------------
    # Refresh caption
    # -----------------------------------------------------------------------

    st.caption(f"Auto-refreshes every {AUTO_REFRESH_SECONDS // 60} minutes")


# ---------------------------------------------------------------------------
# Invoke fragment
# ---------------------------------------------------------------------------

_drift_content(engine, selected_config_id, history_days, show_history)
