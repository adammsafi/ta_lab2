# -*- coding: utf-8 -*-
"""
Executor Status page -- Phase 52 Operational Dashboard.

Displays executor run history, active strategy configurations, summary KPIs,
and a failed runs detail expander.

NOTE: Do NOT call st.set_page_config() here -- it is called in the main app
entry point (app.py). Calling it again from a page script raises a
StreamlitAPIException.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.executor import (
    load_executor_config,
    load_executor_run_log,
)

# ---------------------------------------------------------------------------
# Auto-refresh interval
# ---------------------------------------------------------------------------

AUTO_REFRESH_SECONDS = 900

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Executor Status")
st.caption("Run history, active strategy configurations, and operational KPIs")

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
    st.subheader("Controls")
    run_limit = st.select_slider(
        "Run History Limit",
        options=[10, 25, 50, 100],
        value=50,
    )


# ---------------------------------------------------------------------------
# Auto-refreshing content section
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _executor_content(_engine, run_limit: int) -> None:
    """Auto-refreshing executor status section."""

    # -----------------------------------------------------------------------
    # Load data
    # -----------------------------------------------------------------------

    try:
        run_log_df = load_executor_run_log(_engine, limit=run_limit)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load executor run log: {exc}")
        run_log_df = pd.DataFrame()

    try:
        config_df = load_executor_config(_engine)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load executor config: {exc}")
        config_df = pd.DataFrame()

    # -----------------------------------------------------------------------
    # Executor Summary KPIs
    # -----------------------------------------------------------------------

    st.subheader("Latest Run Summary")

    if run_log_df.empty:
        st.info("No executor runs recorded yet.")
        last_run_str = "N/A"
        last_status = "N/A"
        last_signals = "N/A"
        last_fills = "N/A"
    else:
        latest = run_log_df.iloc[0]

        started_at = latest.get("started_at")
        if hasattr(started_at, "strftime"):
            last_run_str = started_at.strftime("%Y-%m-%d %H:%M UTC")
        else:
            last_run_str = str(started_at) if started_at is not None else "N/A"

        last_status = str(latest.get("status", "N/A"))
        last_signals = int(latest.get("signals_read", 0) or 0)
        last_fills = int(latest.get("fills_processed", 0) or 0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Last Run", last_run_str)
    c2.metric("Status", last_status)
    c3.metric("Signals Read", last_signals)
    c4.metric("Fills Processed", last_fills)

    st.divider()

    # -----------------------------------------------------------------------
    # Active Strategies Config Table
    # -----------------------------------------------------------------------

    st.subheader("Active Strategies")

    if config_df.empty:
        st.info("No active executor configurations.")
    else:
        active_df = config_df[config_df["is_active"] == True].copy()  # noqa: E712

        if active_df.empty:
            st.info("No active executor configurations.")
        else:
            display_cols = [
                "config_id",
                "config_name",
                "signal_type",
                "exchange",
                "environment",
                "sizing_mode",
                "position_fraction",
                "slippage_mode",
                "cadence_hours",
            ]
            available_cols = [c for c in display_cols if c in active_df.columns]
            st.dataframe(
                active_df[available_cols].reset_index(drop=True),
                use_container_width=True,
            )

    st.divider()

    # -----------------------------------------------------------------------
    # Run History Table
    # -----------------------------------------------------------------------

    st.subheader("Executor Run Log")

    if run_log_df.empty:
        st.info("No executor runs recorded yet.")
    else:
        display_df = run_log_df.copy()

        # Parse config_ids from TEXT JSON for display
        def _parse_config_ids(val) -> str:
            if val is None:
                return ""
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, list):
                        return ", ".join(str(v) for v in parsed)
                    return str(parsed)
                except (json.JSONDecodeError, ValueError):
                    return val
            return str(val)

        if "config_ids" in display_df.columns:
            display_df["config_ids"] = display_df["config_ids"].apply(_parse_config_ids)

        # Compute duration column
        if "started_at" in display_df.columns and "finished_at" in display_df.columns:
            valid_mask = (
                display_df["finished_at"].notna() & display_df["started_at"].notna()
            )
            display_df["duration_s"] = None
            if valid_mask.any():
                delta = (
                    display_df.loc[valid_mask, "finished_at"]
                    - display_df.loc[valid_mask, "started_at"]
                )
                display_df.loc[valid_mask, "duration_s"] = (
                    delta.dt.total_seconds().round(1).astype(str) + "s"
                )

        # Color-code status via text prefix
        def _format_status(val: str) -> str:
            status_map = {
                "success": "OK: success",
                "failed": "FAIL: failed",
                "stale_signal": "WARN: stale_signal",
                "running": "...: running",
            }
            return status_map.get(str(val).lower(), str(val))

        if "status" in display_df.columns:
            display_df["status"] = display_df["status"].apply(_format_status)

        # Mark replay runs
        if "replay_historical" in display_df.columns:
            display_df["replay_historical"] = display_df["replay_historical"].apply(
                lambda v: "Yes (replay)" if v else ""
            )

        log_display_cols = [
            "started_at",
            "finished_at",
            "duration_s",
            "status",
            "config_ids",
            "dry_run",
            "replay_historical",
            "signals_read",
            "orders_generated",
            "fills_processed",
            "skipped_no_delta",
            "error_message",
        ]
        available_log_cols = [c for c in log_display_cols if c in display_df.columns]
        st.dataframe(
            display_df[available_log_cols].reset_index(drop=True),
            use_container_width=True,
        )

    st.divider()

    # -----------------------------------------------------------------------
    # Failed Runs Expander
    # -----------------------------------------------------------------------

    with st.expander("Recent Failures"):
        if run_log_df.empty:
            st.info("No recent failures.")
        else:
            failed_statuses = {"failed", "stale_signal"}
            failed_df = run_log_df[run_log_df["status"].isin(failed_statuses)].copy()

            if failed_df.empty:
                st.success("No recent failures.")
            else:
                st.warning(f"{len(failed_df)} failed run(s) in the log.")
                for _, row in failed_df.iterrows():
                    started = row.get("started_at")
                    status = row.get("status", "failed")
                    error_msg = row.get("error_message") or "No error message recorded."

                    if hasattr(started, "strftime"):
                        started_str = started.strftime("%Y-%m-%d %H:%M UTC")
                    else:
                        started_str = str(started)

                    st.markdown(f"**{started_str}** — {status}")
                    st.code(str(error_msg), language=None)

    # -----------------------------------------------------------------------
    # Refresh caption
    # -----------------------------------------------------------------------

    st.caption(f"Auto-refreshes every {AUTO_REFRESH_SECONDS // 60} minutes")


# ---------------------------------------------------------------------------
# Invoke fragment
# ---------------------------------------------------------------------------

_executor_content(engine, run_limit)
