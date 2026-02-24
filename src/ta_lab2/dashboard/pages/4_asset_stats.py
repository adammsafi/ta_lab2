# -*- coding: utf-8 -*-
"""
Asset Statistics & Correlation page -- Phase 41 Streamlit Dashboard page.

Shows per-asset descriptive statistics (latest snapshot) and a cross-asset
correlation heatmap computed from rolling pairwise correlations.

NOTE: Do NOT call st.set_page_config() here -- it is called in the main app entry
point (app.py). Calling it again from a page script raises a StreamlitAPIException.
"""

from __future__ import annotations

import streamlit as st

from ta_lab2.dashboard.charts import (
    build_correlation_heatmap,
    build_stat_timeseries_chart,
    chart_download_button,
)
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.asset_stats import (
    load_asset_stats_latest,
    load_asset_stats_timeseries,
    load_asset_symbols,
    load_corr_latest,
)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Asset Statistics & Correlation")
st.caption("Rolling descriptive stats per asset and cross-asset correlation heatmap")

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Filters")

    # Timeframe selector -- hardcoded common TFs; could query dim_timeframe
    tf_options = ["1D", "4H", "1H", "1W"]
    selected_tf = st.selectbox("Timeframe", tf_options, index=0)

    # Window selector for correlation and rolling stats display
    window_options = [30, 60, 90, 252]
    selected_window = st.selectbox(
        "Rolling Window",
        window_options,
        index=2,  # default to 90
        format_func=lambda w: f"{w} bars",
    )

# ---------------------------------------------------------------------------
# Section 1: Latest Asset Statistics
# ---------------------------------------------------------------------------

st.subheader("Latest Asset Statistics")

try:
    stats_df = load_asset_stats_latest(engine, tf=selected_tf)
except Exception as exc:
    st.error(f"Error loading asset statistics: {exc}")
    stats_df = None

if stats_df is None or stats_df.empty:
    st.info(
        "No asset statistics found. "
        "Run `python -m ta_lab2.scripts.desc_stats.refresh_cmc_asset_stats --ids all` first."
    )
else:
    # Build list of numeric stat columns for the multiselect
    non_stat_cols = {"symbol", "id", "ts", "tf", "ingested_at", "rf_rate"}
    stat_cols_available = [c for c in stats_df.columns if c not in non_stat_cols]

    # Default: show the 252-window stats (most useful overview)
    default_stat_cols = [c for c in stat_cols_available if c.endswith("_252")]
    if not default_stat_cols:
        default_stat_cols = stat_cols_available[:8]

    selected_stat_cols = st.multiselect(
        "Stat columns to display",
        options=stat_cols_available,
        default=default_stat_cols,
        key="stats_multiselect",
    )

    if not selected_stat_cols:
        st.info("Select at least one stat column above to display the table.")
    else:
        display_cols = ["symbol", "ts"] + selected_stat_cols
        display_cols = [c for c in display_cols if c in stats_df.columns]

        # Format numeric columns to 4 decimal places
        fmt_map = {c: "{:.4f}" for c in selected_stat_cols if c in stats_df.columns}
        st.dataframe(
            stats_df[display_cols].style.format(fmt_map, na_rep="—"),
            use_container_width=True,
        )

        # CSV download
        csv_bytes = stats_df[display_cols].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Stats Table (CSV)",
            data=csv_bytes,
            file_name=f"asset_stats_latest_{selected_tf}.csv",
            mime="text/csv",
        )

# ---------------------------------------------------------------------------
# Section 2: Cross-Asset Correlation Heatmap
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Cross-Asset Correlation Heatmap")

metric_label = st.radio(
    "Correlation metric",
    ["Pearson", "Spearman"],
    horizontal=True,
    key="corr_metric_radio",
)
metric_col = "pearson_r" if metric_label == "Pearson" else "spearman_r"

try:
    corr_df = load_corr_latest(engine, tf=selected_tf, window=selected_window)
except Exception as exc:
    st.error(f"Error loading correlation data: {exc}")
    corr_df = None

if corr_df is None or corr_df.empty:
    st.info(
        f"No correlation data found for TF={selected_tf}, window={selected_window} bars. "
        "Run `python -m ta_lab2.scripts.desc_stats.refresh_cmc_cross_asset_corr --ids all` "
        "and then refresh the materialized view."
    )
else:
    try:
        fig_heatmap = build_correlation_heatmap(corr_df, metric=metric_col)
        st.plotly_chart(fig_heatmap, theme=None, key="corr_heatmap")
        chart_download_button(
            fig_heatmap,
            "Download Correlation Heatmap (HTML)",
            f"corr_heatmap_{selected_tf}_w{selected_window}.html",
        )
    except Exception as exc:
        st.warning(f"Could not render correlation heatmap: {exc}")

    # Raw correlation table in expander
    with st.expander("Raw Correlation Table"):
        display_corr_cols = [
            c
            for c in [
                "symbol_a",
                "symbol_b",
                "pearson_r",
                "pearson_p",
                "spearman_r",
                "spearman_p",
                "n_obs",
                "ts",
            ]
            if c in corr_df.columns
        ]
        corr_fmt = {
            "pearson_r": "{:.4f}",
            "pearson_p": "{:.4f}",
            "spearman_r": "{:.4f}",
            "spearman_p": "{:.4f}",
        }
        st.dataframe(
            corr_df[display_corr_cols].style.format(corr_fmt, na_rep="—"),
            use_container_width=True,
        )

        corr_csv_bytes = corr_df[display_corr_cols].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Correlation Table (CSV)",
            data=corr_csv_bytes,
            file_name=f"corr_{selected_tf}_w{selected_window}.csv",
            mime="text/csv",
        )

# ---------------------------------------------------------------------------
# Section 3: Asset Stats Time Series (expandable)
# ---------------------------------------------------------------------------

st.divider()

with st.expander("Asset Stats Time Series", expanded=False):
    # Load symbol map for asset selector
    try:
        symbol_map = load_asset_symbols(engine)
    except Exception as exc:
        st.error(f"Error loading asset list: {exc}")
        symbol_map = {}

    if not symbol_map:
        st.info("No assets found in dim_assets.")
    else:
        # Asset selector
        id_to_sym = symbol_map  # {id: symbol}
        sym_to_id = {v: k for k, v in id_to_sym.items()}
        symbol_list = sorted(sym_to_id.keys())

        col_left, col_right = st.columns(2)

        with col_left:
            selected_sym = st.selectbox(
                "Asset",
                symbol_list,
                key="ts_asset_selector",
            )
            selected_asset_id = sym_to_id[selected_sym]

        # Stat column selector — build from known column patterns
        _stat_bases = [
            "mean_ret",
            "std_ret",
            "sharpe_raw",
            "sharpe_ann",
            "skew",
            "kurt_fisher",
            "kurt_pearson",
            "max_dd_window",
        ]
        _windows = [30, 60, 90, 252]
        all_stat_col_names = [f"{base}_{w}" for w in _windows for base in _stat_bases]
        all_stat_col_names += ["max_dd_from_ath"]

        with col_right:
            selected_ts_col = st.selectbox(
                "Stat column",
                all_stat_col_names,
                index=all_stat_col_names.index("sharpe_ann_252")
                if "sharpe_ann_252" in all_stat_col_names
                else 0,
                key="ts_stat_selector",
            )

        # Load and render
        try:
            ts_df = load_asset_stats_timeseries(
                engine, asset_id=selected_asset_id, tf=selected_tf
            )
        except Exception as exc:
            st.error(f"Error loading time series data: {exc}")
            ts_df = None

        if ts_df is None or ts_df.empty:
            st.info(
                f"No time-series data for {selected_sym} ({selected_tf}). "
                "Run the stats refresh first."
            )
        else:
            try:
                chart_title = f"{selected_sym} — {selected_ts_col} ({selected_tf})"
                fig_ts = build_stat_timeseries_chart(
                    ts_df, selected_ts_col, title=chart_title
                )
                st.plotly_chart(fig_ts, theme=None, key="stat_timeseries")
                chart_download_button(
                    fig_ts,
                    "Download Time Series (HTML)",
                    f"stat_ts_{selected_sym}_{selected_tf}_{selected_ts_col}.html",
                )
            except Exception as exc:
                st.warning(f"Could not render time-series chart: {exc}")
