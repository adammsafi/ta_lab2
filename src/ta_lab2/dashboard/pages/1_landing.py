"""
Landing page -- Dashboard Home.

Provides at-a-glance pipeline health summary and research highlights.
do NOT call st.set_page_config() here -- that is in app.py.
"""

from __future__ import annotations

import streamlit as st

from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.pipeline import load_stats_status, load_table_freshness
from ta_lab2.dashboard.queries.research import load_asset_list, load_ic_results

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
                latest_refresh_str = latest_refresh_ts.strftime("%Y-%m-%d %H:%M UTC")
            else:
                latest_refresh_str = str(latest_refresh_ts)

            avg_staleness = freshness_df["staleness_hours"].mean()
            avg_staleness_str = (
                f"{avg_staleness:.1f}h"
                if not __import__("math").isnan(avg_staleness)
                else "N/A"
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
        asset_df = load_asset_list(engine)

        if asset_df.empty:
            asset_id = 1  # BTC fallback
        else:
            asset_id = int(asset_df.iloc[0]["id"])

        ic_df = load_ic_results(engine, asset_id=asset_id, tf="1D")

        if ic_df.empty:
            st.info(
                "No IC results available. Run:\n"
                "```\npython -m ta_lab2.scripts.ic.run_ic_eval\n```"
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
with ql_right:
    st.page_link(
        "pages/3_research_explorer.py",
        label="Research Explorer",
        icon=":material/science:",
    )
