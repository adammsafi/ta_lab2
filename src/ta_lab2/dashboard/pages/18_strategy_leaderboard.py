# -*- coding: utf-8 -*-
"""
Strategy Leaderboard dashboard page -- Phase 99.

Displays MC Sharpe confidence bands (real when available, sharpe_std fallback),
PBO heatmap (strategy x asset), and feature-to-signal lineage for CTF strategies.

NOTE: Do NOT call set_page_config() here -- it is called in the main app
entry point (app.py). Calling it again from a page script raises a
StreamlitAPIException.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.backtest import (
    load_ctf_lineage,
    load_leaderboard_with_mc,
    load_pbo_heatmap_data,
)

# ---------------------------------------------------------------------------
# Auto-refresh interval (bakeoff data is static -- infrequently regenerated)
# ---------------------------------------------------------------------------

AUTO_REFRESH_SECONDS = 3600

# ---------------------------------------------------------------------------
# Catalogue constants
# ---------------------------------------------------------------------------

_COST_SCENARIOS: list[str] = [
    "spot_fee10_slip5",
    "spot_fee10_slip10",
    "spot_fee10_slip20",
    "spot_fee16_slip5",
    "spot_fee16_slip10",
    "spot_fee16_slip20",
    "spot_fee25_slip5",
    "spot_fee25_slip10",
    "spot_fee25_slip20",
    "perp_fee2_slip3",
    "perp_fee2_slip5",
    "perp_fee2_slip10",
    "perp_fee4_slip3",
    "perp_fee4_slip5",
    "perp_fee4_slip10",
    "perp_fee6_slip3",
]

_CV_METHODS: list[str] = ["purged_kfold", "cpcv"]

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Strategy Leaderboard")
st.caption(
    "MC Sharpe confidence bands (real bootstrap when available, sharpe_std proxy "
    "otherwise), PBO overfitting heatmap, and CTF feature lineage."
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
# Sidebar controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Leaderboard Filters")

    tf_choice = st.selectbox(
        "Timeframe",
        options=["1D"],
        index=0,
        key="lb_tf_select",
    )

    cv_choice = st.selectbox(
        "CV Method",
        options=_CV_METHODS,
        index=0,
        key="lb_cv_select",
    )

    cost_choice = st.selectbox(
        "Cost Scenario (PBO Heatmap)",
        options=_COST_SCENARIOS,
        index=4,  # spot_fee16_slip10
        key="lb_cost_select",
    )

    min_trades = st.slider(
        "Min Trades (leaderboard filter)",
        min_value=1,
        max_value=100,
        value=10,
        step=1,
        key="lb_min_trades_slider",
    )

    st.divider()
    st.caption("Leaderboard groups all assets per strategy.")
    st.caption("PBO heatmap uses CPCV cv_method rows.")


# ---------------------------------------------------------------------------
# Main content (auto-refreshing fragment)
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _leaderboard_content(
    _engine,
    tf: str,
    cv_method: str,
    cost_scenario: str,
    min_trades_val: int,
) -> None:
    """Auto-refreshing leaderboard sections."""

    tab1, tab2, tab3 = st.tabs(
        [
            "Sharpe Leaderboard",
            "PBO Heatmap",
            "CTF Feature Lineage",
        ]
    )

    # =========================================================================
    # Tab 1: Strategy Leaderboard Table with MC Confidence Bands
    # =========================================================================

    with tab1:
        st.subheader("Strategy Leaderboard")
        st.caption(
            f"Grouped by strategy -- {tf} / {cv_method} / min {min_trades_val} trades"
        )

        try:
            lb_df = load_leaderboard_with_mc(
                _engine,
                tf=tf,
                cv_method=cv_method,
                min_trades=min_trades_val,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to load leaderboard: {exc}")
            lb_df = pd.DataFrame()

        if lb_df.empty:
            st.info(
                "No leaderboard results found. Check that the bakeoff has been run "
                "with the selected timeframe and CV method."
            )
        else:
            # ----------------------------------------------------------------
            # Plotly bar chart: avg_sharpe with CI error bars
            # ----------------------------------------------------------------
            chart_df = lb_df.copy()
            chart_df["hi_err"] = (chart_df["ci_hi"] - chart_df["avg_sharpe"]).clip(
                lower=0.0
            )
            chart_df["lo_err"] = (chart_df["avg_sharpe"] - chart_df["ci_lo"]).clip(
                lower=0.0
            )

            # Sort by avg_sharpe descending for the chart
            chart_df = chart_df.sort_values("avg_sharpe", ascending=False).head(30)

            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=chart_df["strategy_name"],
                    y=chart_df["avg_sharpe"],
                    name="Avg Sharpe",
                    error_y=dict(
                        type="data",
                        array=chart_df["hi_err"].tolist(),
                        arrayminus=chart_df["lo_err"].tolist(),
                        visible=True,
                    ),
                    marker_color="steelblue",
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "Avg Sharpe: %{y:.3f}<br>"
                        "CI lo: %{customdata[0]:.3f}<br>"
                        "CI hi: %{customdata[1]:.3f}<br>"
                        "Source: %{customdata[2]}<extra></extra>"
                    ),
                    customdata=list(
                        zip(
                            chart_df["ci_lo"].tolist(),
                            chart_df["ci_hi"].tolist(),
                            chart_df["ci_source"].tolist(),
                        )
                    ),
                )
            )
            fig.update_layout(
                title="Strategy Avg Sharpe with Confidence Bands (top 30)",
                xaxis_title="Strategy",
                yaxis_title="Avg Sharpe",
                height=420,
                margin=dict(b=120),
                xaxis_tickangle=-45,
            )
            st.plotly_chart(
                fig, use_container_width=True, theme=None, key="lb_bar_chart"
            )
            st.caption(
                "Confidence bands source: MC bootstrap (from fold-level Sharpe "
                "resampling) when available; sharpe_std proxy otherwise. "
                "Run backfill_mc_bands.py to populate real MC bands."
            )

            # ----------------------------------------------------------------
            # Leaderboard table
            # ----------------------------------------------------------------
            display_cols = [
                c
                for c in [
                    "strategy_name",
                    "cost_scenario",
                    "n_assets",
                    "n_runs",
                    "avg_sharpe",
                    "ci_lo",
                    "ci_hi",
                    "ci_source",
                    "avg_max_dd",
                    "avg_psr",
                    "avg_pbo",
                    "avg_trades",
                    "best_sharpe",
                    "experiment_name",
                ]
                if c in lb_df.columns
            ]

            st.dataframe(
                lb_df[display_cols].reset_index(drop=True),
                use_container_width=True,
                key="lb_leaderboard_table",
                column_config={
                    "strategy_name": st.column_config.TextColumn(
                        "Strategy",
                        help="Strategy name",
                    ),
                    "cost_scenario": st.column_config.TextColumn(
                        "Cost Scenario",
                    ),
                    "n_assets": st.column_config.NumberColumn(
                        "Assets",
                        format="%d",
                        help="Distinct assets in this group",
                    ),
                    "n_runs": st.column_config.NumberColumn(
                        "Runs",
                        format="%d",
                        help="Total bakeoff runs in this group",
                    ),
                    "avg_sharpe": st.column_config.NumberColumn(
                        "Avg Sharpe",
                        format="%.3f",
                        help="Mean Sharpe across all assets/params",
                    ),
                    "ci_lo": st.column_config.NumberColumn(
                        "CI Low",
                        format="%.3f",
                        help="Lower CI bound (MC bootstrap or sharpe_std proxy)",
                    ),
                    "ci_hi": st.column_config.NumberColumn(
                        "CI High",
                        format="%.3f",
                        help="Upper CI bound (MC bootstrap or sharpe_std proxy)",
                    ),
                    "ci_source": st.column_config.TextColumn(
                        "CI Source",
                        help="'MC bootstrap' = real MC bands; 'sharpe_std proxy' = fallback",
                    ),
                    "avg_max_dd": st.column_config.NumberColumn(
                        "Avg Max DD",
                        format="%.3f",
                        help="Average worst-fold max drawdown (0-1 scale)",
                    ),
                    "avg_psr": st.column_config.NumberColumn(
                        "Avg PSR",
                        format="%.3f",
                        help="Average Probabilistic Sharpe Ratio",
                    ),
                    "avg_pbo": st.column_config.NumberColumn(
                        "Avg PBO",
                        format="%.3f",
                        help="Average Probability of Backtest Overfitting (lower is better)",
                    ),
                    "avg_trades": st.column_config.NumberColumn(
                        "Avg Trades",
                        format="%.0f",
                        help="Average trade count per run",
                    ),
                    "best_sharpe": st.column_config.NumberColumn(
                        "Best Sharpe",
                        format="%.3f",
                        help="Best single-run Sharpe in this strategy group",
                    ),
                },
            )

            # CSV download
            csv_bytes = lb_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download leaderboard CSV",
                data=csv_bytes,
                file_name=f"strategy_leaderboard_{tf}_{cv_method}.csv",
                mime="text/csv",
                key="lb_csv_download",
            )

    # =========================================================================
    # Tab 2: PBO Heatmap
    # =========================================================================

    with tab2:
        st.subheader("Probability of Backtest Overfitting")
        st.caption(
            f"Strategy x Asset PBO matrix -- {tf} / cpcv / {cost_scenario}. "
            "Lower PBO is better."
        )

        try:
            pbo_df = load_pbo_heatmap_data(
                _engine,
                tf=tf,
                cv_method="cpcv",
                cost_scenario=cost_scenario,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to load PBO heatmap data: {exc}")
            pbo_df = pd.DataFrame()

        if pbo_df.empty:
            st.info(
                "No PBO data found for the selected filters. "
                "Ensure CPCV runs have been completed for this timeframe and cost scenario."
            )
        else:
            # pbo_df has strategy_name column + one column per asset symbol
            if "strategy_name" in pbo_df.columns:
                pbo_matrix = pbo_df.set_index("strategy_name")
            else:
                pbo_matrix = pbo_df

            # Filter out all-NaN columns and rows
            pbo_matrix = pbo_matrix.dropna(axis=1, how="all").dropna(axis=0, how="all")

            if pbo_matrix.empty:
                st.info(
                    "PBO matrix is empty after removing rows/columns with all-NaN values."
                )
            else:
                fig_pbo = px.imshow(
                    pbo_matrix,
                    color_continuous_scale="RdYlGn_r",
                    zmin=0.0,
                    zmax=1.0,
                    aspect="auto",
                    title="PBO Probability (strategy x asset)",
                    labels=dict(
                        x="Asset",
                        y="Strategy",
                        color="PBO Prob",
                    ),
                )
                fig_pbo.update_layout(
                    height=max(300, 40 * len(pbo_matrix) + 100),
                    margin=dict(l=160),
                )
                st.plotly_chart(
                    fig_pbo,
                    use_container_width=True,
                    theme=None,
                    key="lb_pbo_heatmap",
                )
                st.caption(
                    "PBO values from CPCV (fraction of folds below median Sharpe). "
                    "Lower is better. Values near 0.5 indicate no overfitting evidence. "
                    "Green = low PBO (good), Red = high PBO (bad)."
                )

    # =========================================================================
    # Tab 3: CTF Feature Lineage
    # =========================================================================

    with tab3:
        st.subheader("CTF Feature Lineage")
        st.caption(
            "Feature-to-signal mapping for CTF threshold strategies. "
            "Shows which CTF features drive the best backtest performance."
        )

        try:
            lineage_df = load_ctf_lineage(_engine, tf=tf)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to load CTF lineage: {exc}")
            lineage_df = pd.DataFrame()

        if lineage_df.empty:
            st.info(
                "No CTF threshold backtest results yet. "
                "Run mass backtest with --strategies ctf_threshold first."
            )
        else:
            display_lineage_cols = [
                c
                for c in [
                    "feature_col",
                    "n_assets",
                    "avg_sharpe",
                    "best_sharpe",
                    "avg_pbo",
                    "mean_abs_ic",
                ]
                if c in lineage_df.columns
            ]

            st.dataframe(
                lineage_df[display_lineage_cols].reset_index(drop=True),
                use_container_width=True,
                key="lb_ctf_lineage_table",
                column_config={
                    "feature_col": st.column_config.TextColumn(
                        "Feature Column",
                        help="CTF feature column from params_json",
                    ),
                    "n_assets": st.column_config.NumberColumn(
                        "Assets",
                        format="%d",
                        help="Number of assets this feature was backtested on",
                    ),
                    "avg_sharpe": st.column_config.NumberColumn(
                        "Avg Sharpe",
                        format="%.3f",
                        help="Average Sharpe across all asset runs for this feature",
                    ),
                    "best_sharpe": st.column_config.NumberColumn(
                        "Best Sharpe",
                        format="%.3f",
                        help="Best Sharpe for any single asset run",
                    ),
                    "avg_pbo": st.column_config.NumberColumn(
                        "Avg PBO",
                        format="%.3f",
                        help="Average PBO probability (lower is better)",
                    ),
                    "mean_abs_ic": st.column_config.NumberColumn(
                        "Mean |IC|",
                        format="%.4f",
                        help="Mean absolute information coefficient from ic_results (if available)",
                    ),
                },
            )

            st.caption(
                "feature_col is extracted from params_json for ctf_threshold strategy rows. "
                "Mean |IC| is joined from ic_results when available."
            )

    # -----------------------------------------------------------------------
    # Refresh caption
    # -----------------------------------------------------------------------
    st.caption(f"Auto-refreshes every {AUTO_REFRESH_SECONDS // 60} minutes")


# ---------------------------------------------------------------------------
# Invoke fragment
# ---------------------------------------------------------------------------

_leaderboard_content(
    engine,
    tf=tf_choice,
    cv_method=cv_choice,
    cost_scenario=cost_choice,
    min_trades_val=min_trades,
)
