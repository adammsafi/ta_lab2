"""
ta_lab2 Streamlit dashboard entrypoint.

Run with:
    streamlit run src/ta_lab2/dashboard/app.py
"""

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
    st.caption("Analysis + Operations + Monitoring")
    st.divider()
    if st.button("Refresh Now", type="primary"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Cache tiers: Live 2min | Pipeline 5min | Research 60min")
    st.divider()

# ---------------------------------------------------------------------------
# Multipage navigation
# ---------------------------------------------------------------------------
pages = {
    "Overview": [
        st.Page(
            "pages/1_landing.py",
            title="Dashboard Home",
            icon=":material/home:",
        ),
    ],
    "Research": [
        st.Page(
            "pages/13_asset_hub.py",
            title="Asset Hub",
            icon=":material/hub:",
        ),
        st.Page(
            "pages/11_backtest_results.py",
            title="Backtest Results",
            icon=":material/analytics:",
        ),
        st.Page(
            "pages/18_strategy_leaderboard.py",
            title="Strategy Leaderboard",
            icon=":material/leaderboard:",
        ),
        st.Page(
            "pages/12_signal_browser.py",
            title="Signal Browser",
            icon=":material/signal_cellular_alt:",
        ),
        st.Page(
            "pages/3_research_explorer.py",
            title="Research Explorer",
            icon=":material/science:",
        ),
        st.Page(
            "pages/5_experiments.py",
            title="Feature Experiments",
            icon=":material/experiment:",
        ),
        st.Page(
            "pages/4_asset_stats.py",
            title="Asset Statistics",
            icon=":material/bar_chart:",
        ),
    ],
    "Markets": [
        st.Page(
            "pages/14_perps.py",
            title="Perps",
            icon=":material/currency_exchange:",
        ),
        st.Page(
            "pages/15_portfolio.py",
            title="Portfolio",
            icon=":material/account_balance:",
        ),
        st.Page(
            "pages/16_regime_heatmap.py",
            title="Regime Heatmap",
            icon=":material/grid_view:",
        ),
        st.Page(
            "pages/17_ama_inspector.py",
            title="AMA Inspector",
            icon=":material/ssid_chart:",
        ),
    ],
    "Operations": [
        st.Page(
            "pages/6_trading.py",
            title="Trading",
            icon=":material/candlestick_chart:",
        ),
        st.Page(
            "pages/7_risk_controls.py",
            title="Risk & Controls",
            icon=":material/security:",
        ),
        st.Page(
            "pages/8_drift_monitor.py",
            title="Drift Monitor",
            icon=":material/trending_up:",
        ),
        st.Page(
            "pages/9_executor_status.py",
            title="Executor Status",
            icon=":material/play_circle:",
        ),
        st.Page(
            "pages/19_pipeline_ops.py",
            title="Pipeline Ops",
            icon=":material/manage_history:",
        ),
        st.Page(
            "pages/10_macro.py",
            title="Macro",
            icon=":material/public:",
        ),
    ],
    "Monitor": [
        st.Page(
            "pages/2_pipeline_monitor.py",
            title="Pipeline Monitor",
            icon=":material/monitoring:",
        ),
    ],
}

pg = st.navigation(pages)
pg.run()
