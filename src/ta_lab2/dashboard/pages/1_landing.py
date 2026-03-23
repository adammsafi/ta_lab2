"""
Landing page -- Dashboard Home.

Provides at-a-glance pipeline health summary, research highlights, and
operational health traffic-light indicators.
do NOT call st.set_page_config() here -- that is in app.py.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import streamlit as st

from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.executor import load_executor_run_log
from ta_lab2.dashboard.queries.pipeline import load_stats_status, load_table_freshness
from ta_lab2.dashboard.queries.research import load_ic_results
from ta_lab2.dashboard.queries.risk import load_risk_state

st.header("Dashboard Home")
st.caption("Pipeline health + research highlights at a glance")

# ---------------------------------------------------------------------------
# Two-column layout: Pipeline Health (left) | Research Highlights (right)
# ---------------------------------------------------------------------------
col_left, col_right = st.columns(2)

# ---------------------------------------------------------------------------
# Left column: Pipeline Health Summary
# ---------------------------------------------------------------------------
with col_left:
    st.subheader("Pipeline Health")

    # -- Freshness metrics ---------------------------------------------------
    try:
        engine = get_engine()
        freshness_df = load_table_freshness(engine)

        if freshness_df.empty:
            st.info("No coverage data found in asset_data_coverage.")
        else:
            tables_tracked = int(freshness_df["source_table"].nunique())

            latest_refresh_ts = freshness_df["last_refresh"].max()
            if hasattr(latest_refresh_ts, "strftime"):
                latest_refresh_str = latest_refresh_ts.strftime("%m-%d %H:%M")
            else:
                latest_refresh_str = str(latest_refresh_ts)[:11]

            avg_staleness = freshness_df["staleness_hours"].mean()
            avg_staleness_str = (
                f"{avg_staleness:.1f}h" if not math.isnan(avg_staleness) else "N/A"
            )

            m1, m2, m3 = st.columns(3)
            m1.metric("Tables Tracked", tables_tracked)
            m2.metric("Latest Refresh", latest_refresh_str)
            m3.metric("Avg Staleness", avg_staleness_str)

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load freshness data: {exc}")

    # -- Stats pass rate -----------------------------------------------------
    try:
        engine = get_engine()
        stats_data = load_stats_status(engine)

        total_pass = sum(v.get("PASS", 0) for v in stats_data.values())
        total_fail = sum(v.get("FAIL", 0) for v in stats_data.values())
        total_warn = sum(v.get("WARN", 0) for v in stats_data.values())
        total_all = total_pass + total_fail + total_warn

        pass_rate = (total_pass / total_all) if total_all > 0 else 0.0
        st.metric("Stats Pass Rate", f"{pass_rate:.0%}")

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load stats data: {exc}")

# ---------------------------------------------------------------------------
# Right column: Research Highlights
# ---------------------------------------------------------------------------
with col_right:
    st.subheader("Top IC Scores")

    try:
        engine = get_engine()

        # Use BTC (asset_id=1) for IC scores -- most representative asset
        asset_id = 1

        ic_df = load_ic_results(engine, asset_id=asset_id, tf="1D")

        if ic_df.empty:
            st.info(
                "No IC results available. Run:\n"
                "```\npython -m ta_lab2.scripts.analysis.run_ic_eval\n```"
            )
        else:
            # Sort by absolute IC descending, take top 10
            ic_df = ic_df.copy()
            ic_df["abs_ic"] = ic_df["ic"].abs()
            top_ic_df = (
                ic_df.sort_values("abs_ic", ascending=False)
                .head(10)[["feature", "horizon", "ic", "ic_p_value"]]
                .reset_index(drop=True)
            )
            st.dataframe(top_ic_df, use_container_width=True)

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load IC data: {exc}")

# ---------------------------------------------------------------------------
# Operational Health section
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Operational Health")

try:
    engine = get_engine()
    risk_state = load_risk_state(engine)

    now_utc = datetime.now(timezone.utc)

    oh_col1, oh_col2, oh_col3, oh_col4 = st.columns(4)

    # -- Kill Switch (column 1) ----------------------------------------------
    with oh_col1:
        try:
            trading_state = risk_state.get("trading_state", "") if risk_state else ""
            halted_at = risk_state.get("halted_at") if risk_state else None

            if trading_state == "active":
                st.metric("Kill Switch", "OK", delta="Active", delta_color="normal")
            elif trading_state == "halted":
                if halted_at is not None:
                    if hasattr(halted_at, "strftime"):
                        halted_str = halted_at.strftime("%Y-%m-%d")
                    else:
                        halted_str = str(halted_at)[:10]
                    st.metric(
                        "Kill Switch",
                        "HALTED",
                        delta=f"Since {halted_str}",
                        delta_color="inverse",
                    )
                else:
                    st.metric("Kill Switch", "HALTED", delta_color="inverse")
            else:
                st.metric("Kill Switch", "UNKNOWN", delta_color="off")
        except Exception as exc:  # noqa: BLE001
            st.metric("Kill Switch", "ERR")
            st.caption(str(exc)[:60])

    # -- Drift Pause (column 2) ----------------------------------------------
    with oh_col2:
        try:
            drift_paused = (
                risk_state.get("drift_paused", False) if risk_state else False
            )
            drift_paused_at = risk_state.get("drift_paused_at") if risk_state else None

            if not drift_paused:
                st.metric("Drift Pause", "OK", delta="Monitoring", delta_color="normal")
            else:
                if drift_paused_at is not None:
                    if (
                        hasattr(drift_paused_at, "tzinfo")
                        and drift_paused_at.tzinfo is not None
                    ):
                        paused_dt = drift_paused_at
                    else:
                        paused_dt = datetime.fromisoformat(
                            str(drift_paused_at)
                        ).replace(tzinfo=timezone.utc)
                    days_paused = (now_utc - paused_dt).days
                else:
                    days_paused = 0

                if days_paused < 3:
                    st.metric(
                        "Drift Pause",
                        "PAUSED",
                        delta=f"{days_paused}d",
                        delta_color="off",
                    )
                else:
                    st.metric(
                        "Drift Pause",
                        "PAUSED",
                        delta=f"{days_paused}d - Escalate!",
                        delta_color="inverse",
                    )
        except Exception as exc:  # noqa: BLE001
            st.metric("Drift Pause", "ERR")
            st.caption(str(exc)[:60])

    # -- Executor Last Run (column 3) ----------------------------------------
    with oh_col3:
        try:
            run_log_df = load_executor_run_log(engine, limit=1)

            if run_log_df.empty:
                st.metric("Executor", "NO DATA", delta_color="off")
            else:
                finished_at = run_log_df.iloc[0]["finished_at"]
                if finished_at is None or (
                    hasattr(finished_at, "__class__")
                    and finished_at.__class__.__name__ == "NaTType"
                ):
                    st.metric("Executor", "NO DATA", delta_color="off")
                else:
                    if (
                        hasattr(finished_at, "tzinfo")
                        and finished_at.tzinfo is not None
                    ):
                        finished_dt = finished_at
                    else:
                        finished_dt = datetime.fromisoformat(str(finished_at)).replace(
                            tzinfo=timezone.utc
                        )
                    hours_since = (now_utc - finished_dt).total_seconds() / 3600

                    if hours_since < 26:
                        st.metric(
                            "Executor",
                            "OK",
                            delta=f"{hours_since:.0f}h ago",
                            delta_color="normal",
                        )
                    elif hours_since <= 48:
                        st.metric(
                            "Executor",
                            "STALE",
                            delta=f"{hours_since:.0f}h ago",
                            delta_color="off",
                        )
                    else:
                        st.metric(
                            "Executor",
                            "STALE",
                            delta=f"{hours_since:.0f}h ago",
                            delta_color="inverse",
                        )
        except Exception as exc:  # noqa: BLE001
            st.metric("Executor", "ERR")
            st.caption(str(exc)[:60])

    # -- Circuit Breaker (column 4) ------------------------------------------
    with oh_col4:
        try:
            cb_raw = risk_state.get("cb_breaker_tripped_at") if risk_state else None

            if cb_raw is None or cb_raw == "":
                tripped_keys: dict = {}
            elif isinstance(cb_raw, dict):
                tripped_keys = cb_raw
            elif isinstance(cb_raw, str):
                try:
                    tripped_keys = json.loads(cb_raw)
                    if not isinstance(tripped_keys, dict):
                        tripped_keys = {}
                except (json.JSONDecodeError, ValueError):
                    tripped_keys = {}
            else:
                tripped_keys = {}

            n_tripped = len(tripped_keys)
            if n_tripped == 0:
                st.metric(
                    "Circuit Breaker",
                    "OK",
                    delta="0 tripped",
                    delta_color="normal",
                )
            else:
                st.metric(
                    "Circuit Breaker",
                    "TRIPPED",
                    delta=f"{n_tripped} keys",
                    delta_color="inverse",
                )
        except Exception as exc:  # noqa: BLE001
            st.metric("Circuit Breaker", "ERR")
            st.caption(str(exc)[:60])

except Exception as exc:  # noqa: BLE001
    st.warning(f"Could not load operational health data: {exc}")

# ---------------------------------------------------------------------------
# Quick links at bottom
# ---------------------------------------------------------------------------
st.divider()
st.markdown("**Quick Links**")

ql_left, ql_right = st.columns(2)
with ql_left:
    st.page_link(
        "pages/2_pipeline_monitor.py",
        label="Pipeline Monitor",
        icon=":material/monitoring:",
    )
    st.page_link(
        "pages/6_trading.py",
        label="Trading",
        icon=":material/candlestick_chart:",
    )
with ql_right:
    st.page_link(
        "pages/3_research_explorer.py",
        label="Research Explorer",
        icon=":material/science:",
    )
    st.page_link(
        "pages/7_risk_controls.py",
        label="Risk & Controls",
        icon=":material/security:",
    )
