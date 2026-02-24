"""
ta_lab2 Streamlit dashboard entrypoint.

Run with:
    streamlit run src/ta_lab2/dashboard/app.py
"""

from pathlib import Path

import streamlit as st

# MUST be the first Streamlit call -- never call set_page_config elsewhere
st.set_page_config(
    page_title="ta_lab2 Dashboard",
    page_icon=":bar_chart:",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Shared sidebar (runs on every rerun)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("ta_lab2")
    st.caption("Pipeline Monitor + Research + Experiments")
    st.divider()
    st.slider(
        "Cache TTL (s)",
        min_value=30,
        max_value=3600,
        value=300,
        step=30,
        key="cache_ttl_display",
    )
    if st.button("Refresh Now", type="primary"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.caption("Cache TTL: 300s (fixed). Use Refresh to clear.")

# ---------------------------------------------------------------------------
# Multipage navigation
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent

pages = {
    "Overview": [
        st.Page(
            str(_HERE / "pages" / "1_landing.py"),
            title="Dashboard Home",
            icon=":material/home:",
        )
    ],
    "Monitor": [
        st.Page(
            str(_HERE / "pages" / "2_pipeline_monitor.py"),
            title="Pipeline Monitor",
            icon=":material/monitoring:",
        )
    ],
    "Research": [
        st.Page(
            str(_HERE / "pages" / "3_research_explorer.py"),
            title="Research Explorer",
            icon=":material/science:",
        )
    ],
    "Analytics": [
        st.Page(
            str(_HERE / "pages" / "4_asset_stats.py"),
            title="Asset Statistics & Correlation",
            icon=":material/bar_chart:",
        )
    ],
    "Experiments": [
        st.Page(
            str(_HERE / "pages" / "5_experiments.py"),
            title="Feature Experiments",
            icon=":material/experiment:",
        )
    ],
}

pg = st.navigation(pages)
pg.run()
