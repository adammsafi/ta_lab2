# -*- coding: utf-8 -*-
"""
Feature Experiments page -- Streamlit Dashboard.

Displays cmc_feature_experiments results including IC scores,
BH-corrected significance, and feature comparison across assets and horizons.

NOTE: Do NOT call st.set_page_config() here -- it is called in the main app
entry point (app.py). Calling it again from a page script raises a
StreamlitAPIException.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.experiments import (
    load_experiment_feature_names,
    load_experiment_results,
    load_experiment_summary,
)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Feature Experiments")
st.caption("Explore experimental feature IC results with BH significance")

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Summary table section
# ---------------------------------------------------------------------------

st.subheader("Experiment Summary")

try:
    summary_df = load_experiment_summary(engine)
except Exception as exc:
    st.error(f"Error loading experiment summary: {exc}")
    summary_df = pd.DataFrame()

if summary_df.empty:
    st.info("No experiment results found. Run experiments first.")
else:
    st.dataframe(summary_df, use_container_width=True)

# ---------------------------------------------------------------------------
# Feature detail section
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Feature Detail")

try:
    feature_names = load_experiment_feature_names(engine)
except Exception as exc:
    st.error(f"Error loading feature names: {exc}")
    feature_names = []

if not feature_names:
    st.info(
        "No experiment features found. Run feature experiments first "
        "(e.g. `python -m ta_lab2.scripts.experiments.run_feature_experiments`)."
    )
else:
    selected_feature = st.selectbox("Select feature", feature_names)

    try:
        results_df = load_experiment_results(engine, selected_feature)
    except Exception as exc:
        st.error(f"Error loading experiment results: {exc}")
        results_df = pd.DataFrame()

    if results_df.empty:
        st.info(f"No results found for feature '{selected_feature}'.")
    else:
        # Add BH significance flag
        results_df = results_df.copy()
        results_df["significant"] = results_df["ic_p_value_bh"] < 0.05

        # Display columns (those present in the DataFrame)
        display_cols = [
            c
            for c in [
                "asset_id",
                "tf",
                "horizon",
                "return_type",
                "ic",
                "ic_p_value",
                "ic_p_value_bh",
                "ic_ir",
                "n_obs",
                "significant",
            ]
            if c in results_df.columns
        ]

        st.dataframe(
            results_df[display_cols],
            use_container_width=True,
            column_config={
                "significant": st.column_config.CheckboxColumn(
                    "BH Significant",
                    help="True when BH-corrected p-value < 0.05",
                )
            },
        )

        # CSV download
        csv_bytes = results_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Results (CSV)",
            data=csv_bytes,
            file_name=f"experiments_{selected_feature}.csv",
            mime="text/csv",
        )

        # -------------------------------------------------------------------
        # BH significance breakdown by horizon
        # -------------------------------------------------------------------

        st.divider()
        st.subheader("BH Significance by Horizon")

        try:
            horizon_group = (
                results_df.groupby("horizon")["significant"]
                .agg(["sum", "count"])
                .rename(columns={"sum": "n_significant", "count": "n_total"})
            )
            horizon_group["fraction_significant"] = (
                horizon_group["n_significant"] / horizon_group["n_total"]
            )
            horizon_group = horizon_group.sort_index()
            st.bar_chart(
                horizon_group["fraction_significant"],
                x_label="Horizon (bars)",
                y_label="Fraction BH-Significant",
            )
        except Exception as exc:
            st.warning(f"Could not render BH significance chart: {exc}")
