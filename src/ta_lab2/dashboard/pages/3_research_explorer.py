# -*- coding: utf-8 -*-
"""
Research Explorer page -- Mode A of the Streamlit Dashboard.

Lets users explore IC evaluation results and regime data interactively
without running CLI commands.

NOTE: Do NOT call st.set_page_config() here -- it is called in the main app entry
point (Home.py). Calling it again from a page script raises a StreamlitAPIException.
"""

from __future__ import annotations

import streamlit as st

from ta_lab2.dashboard.charts import (
    build_ic_decay_chart,
    build_regime_price_chart,
    build_regime_timeline,
    chart_download_button,
)
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.research import (
    load_asset_list,
    load_close_prices,
    load_feature_names,
    load_ic_results,
    load_regimes,
    load_tf_list,
)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Research Explorer")
st.caption("Explore IC scores, feature predictive power, and market regimes")

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Selection controls: Asset / Timeframe / Feature search
# ---------------------------------------------------------------------------

try:
    col1, col2, col3 = st.columns(3)

    with col1:
        assets_df = load_asset_list(engine)
        if assets_df.empty:
            st.warning("No assets found in dim_assets")
            st.stop()
        asset_options = dict(zip(assets_df["symbol"], assets_df["id"]))
        selected_symbol = st.selectbox("Asset", list(asset_options.keys()))
        selected_id = asset_options[selected_symbol]

    with col2:
        tf_list = load_tf_list(engine)
        if not tf_list:
            st.warning("No timeframes found in dim_timeframe")
            st.stop()
        default_tf_idx = tf_list.index("1D") if "1D" in tf_list else 0
        selected_tf = st.selectbox("Timeframe", tf_list, index=default_tf_idx)

    with col3:
        feature_names = load_feature_names(engine, selected_id, selected_tf)
        search_query = st.text_input("Search features", "")
        if search_query:
            filtered_features = [
                f for f in feature_names if search_query.lower() in f.lower()
            ]
        else:
            filtered_features = feature_names

except Exception as exc:
    st.error(f"Error loading selection controls: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Feature selector
# ---------------------------------------------------------------------------

if not filtered_features:
    st.info(
        "No IC features found for the selected asset/timeframe combination. "
        "Run IC evaluation first (e.g. `python -m ta_lab2.scripts.ic.run_ic_evaluation`)."
    )
    st.stop()

selected_feature = st.selectbox("Select feature", filtered_features)

# ---------------------------------------------------------------------------
# Load IC results for selected asset / TF
# ---------------------------------------------------------------------------

try:
    ic_df = load_ic_results(engine, selected_id, selected_tf)
except Exception as exc:
    st.error(f"Error loading IC results: {exc}")
    st.stop()

# Filter to the selected feature
if ic_df.empty:
    feature_ic = ic_df.copy()
else:
    feature_ic = ic_df[ic_df["feature"] == selected_feature].copy()

# ---------------------------------------------------------------------------
# IC Score Table section
# ---------------------------------------------------------------------------

st.subheader("IC Scores")

if feature_ic.empty:
    st.info(
        f"No IC data found for feature '{selected_feature}' "
        f"on {selected_symbol} ({selected_tf}). "
        "Run IC evaluation for this asset and timeframe first."
    )
else:
    # Show relevant columns in a friendly order
    display_cols = [
        c
        for c in [
            "horizon",
            "return_type",
            "regime_col",
            "regime_label",
            "ic",
            "ic_p_value",
            "ic_t_stat",
            "ic_ir",
            "turnover",
            "n_obs",
            "computed_at",
        ]
        if c in feature_ic.columns
    ]
    st.dataframe(feature_ic[display_cols], use_container_width=True)

    # CSV download for the feature IC data
    csv_bytes = feature_ic.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download IC Table (CSV)",
        data=csv_bytes,
        file_name=f"ic_{selected_symbol}_{selected_tf}_{selected_feature}.csv",
        mime="text/csv",
    )

# ---------------------------------------------------------------------------
# IC Decay Chart section
# ---------------------------------------------------------------------------

st.subheader("IC Decay")

if not feature_ic.empty:
    try:
        return_type = st.radio(
            "Return type", ["arith", "log"], horizontal=True, key="ic_decay_return_type"
        )

        fig_decay = build_ic_decay_chart(
            feature_ic, selected_feature, return_type=return_type
        )
        st.plotly_chart(fig_decay, theme=None, key="ic_decay")
        chart_download_button(
            fig_decay,
            "Download IC Decay (HTML)",
            f"ic_decay_{selected_symbol}_{selected_tf}_{selected_feature}.html",
        )
    except Exception as exc:
        st.warning(f"Could not render IC decay chart: {exc}")
else:
    st.info("Run IC evaluation to view the IC decay chart.")

# ---------------------------------------------------------------------------
# Regime Analysis section
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Regime Analysis")

try:
    regimes_df = load_regimes(engine, selected_id, selected_tf)
    close_series = load_close_prices(engine, selected_id, selected_tf)
except Exception as exc:
    st.error(f"Error loading regime/price data: {exc}")
    regimes_df = None
    close_series = None

# Price chart with regime overlay
if close_series is not None and len(close_series) > 0:
    try:
        fig_price = build_regime_price_chart(close_series, regimes_df)
        st.plotly_chart(fig_price, theme=None, key="regime_price")
        chart_download_button(
            fig_price,
            "Download Price Chart (HTML)",
            f"price_regime_{selected_symbol}_{selected_tf}.html",
        )
    except Exception as exc:
        st.warning(f"Could not render price + regime chart: {exc}")
else:
    st.info(
        f"No price data available for {selected_symbol} ({selected_tf}). "
        "Run cmc_features refresh to populate price data."
    )

# Regime timeline
if regimes_df is not None and len(regimes_df) > 0:
    try:
        fig_timeline = build_regime_timeline(regimes_df)
        st.plotly_chart(fig_timeline, theme=None, key="regime_timeline")
        chart_download_button(
            fig_timeline,
            "Download Regime Timeline (HTML)",
            f"regime_timeline_{selected_symbol}_{selected_tf}.html",
        )
    except Exception as exc:
        st.warning(f"Could not render regime timeline: {exc}")
else:
    st.info(
        f"No regime data available for {selected_symbol} ({selected_tf}). "
        "Run regime refresh to populate regime labels."
    )

# ---------------------------------------------------------------------------
# Full IC Summary Table (all features, sorted by |IC|)
# ---------------------------------------------------------------------------

st.divider()
st.subheader("All Features IC Summary")

if ic_df.empty:
    st.info(
        f"No IC data found for {selected_symbol} ({selected_tf}). "
        "Run IC evaluation first."
    )
else:
    try:
        # Show a summary collapsed by feature: best IC per feature across horizons
        summary_cols = [
            c
            for c in [
                "feature",
                "horizon",
                "return_type",
                "ic",
                "ic_p_value",
                "ic_ir",
                "n_obs",
            ]
            if c in ic_df.columns
        ]
        summary_df = ic_df[summary_cols].copy()

        # Sort by absolute IC descending so strongest predictors appear first
        if "ic" in summary_df.columns:
            summary_df = (
                summary_df.assign(_abs_ic=summary_df["ic"].abs())
                .sort_values("_abs_ic", ascending=False)
                .drop(columns="_abs_ic")
            )

        st.dataframe(summary_df, use_container_width=True)

        # CSV download for the full IC table
        full_csv_bytes = ic_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Full IC Table (CSV)",
            data=full_csv_bytes,
            file_name=f"ic_full_{selected_symbol}_{selected_tf}.csv",
            mime="text/csv",
        )
    except Exception as exc:
        st.warning(f"Could not render full IC summary table: {exc}")
