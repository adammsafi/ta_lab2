# -*- coding: utf-8 -*-
"""
Backtest Results dashboard page -- Phase 83.

Displays walk-forward bakeoff results across 109 assets, 13 strategies, and
16 cost scenarios. Provides three switchable views (Leaderboard, Strategy-First,
Asset-First), a cost scenario comparison matrix, Monte Carlo Sharpe CI card,
equity sparkline thumbnails, and a trade table with MAE/MFE for closed signals.

NOTE: Do NOT call set_page_config() here -- it is called in the main app
entry point (app.py). Calling it again from a page script raises a
StreamlitAPIException.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from ta_lab2.analysis.mae_mfe import _load_close_prices, compute_mae_mfe
from ta_lab2.dashboard.charts import build_equity_sparkline, chart_download_button
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.backtest import (
    load_bakeoff_assets,
    load_bakeoff_cost_matrix,
    load_bakeoff_fold_metrics,
    load_bakeoff_leaderboard,
    load_bakeoff_strategies,
    load_closed_signals_for_strategy,
)

# ---------------------------------------------------------------------------
# Auto-refresh interval (bakeoff data is static -- infrequently regenerated)
# ---------------------------------------------------------------------------

AUTO_REFRESH_SECONDS = 3600

# ---------------------------------------------------------------------------
# Cost scenario catalogue (full 16-scenario set)
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

st.header("Backtest Results")
st.caption(
    "Walk-forward bakeoff across 109 assets, 13 strategies, and 16 cost scenarios. "
    "Results from Phase 82 walk-forward cross-validation."
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
# URL state (module level, outside fragment)
# ---------------------------------------------------------------------------

_qp = st.query_params
_default_view = _qp.get("view", "Leaderboard")
_default_tf = _qp.get("tf", "1D")
_default_cv = _qp.get("cv_method", "purged_kfold")
_default_cost = _qp.get("cost_scenario", "spot_fee16_slip10")
_default_strategy = _qp.get("strategy", "")
_default_asset = _qp.get("asset", "")

# ---------------------------------------------------------------------------
# Sidebar controls (outside fragment -- must not be inside @st.fragment)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Backtest Filters")

    view_mode = st.radio(
        "View",
        ["Leaderboard", "Strategy-First", "Asset-First"],
        index=["Leaderboard", "Strategy-First", "Asset-First"].index(
            _default_view
            if _default_view in ["Leaderboard", "Strategy-First", "Asset-First"]
            else "Leaderboard"
        ),
        horizontal=True,
        key="backtest_view_radio",
    )

    tf_choice = st.selectbox(
        "Timeframe",
        options=["1D"],
        index=0,
        key="backtest_tf_select",
    )

    cv_choice = st.selectbox(
        "CV Method",
        options=_CV_METHODS,
        index=_CV_METHODS.index(_default_cv) if _default_cv in _CV_METHODS else 0,
        key="backtest_cv_select",
    )

    cost_choice = st.selectbox(
        "Cost Scenario",
        options=_COST_SCENARIOS,
        index=_COST_SCENARIOS.index(_default_cost)
        if _default_cost in _COST_SCENARIOS
        else 4,
        key="backtest_cost_select",
    )

    # Strategy multiselect -- populated from DB
    try:
        all_strategies = load_bakeoff_strategies(engine)
    except Exception:  # noqa: BLE001
        all_strategies = []

    strategy_filter = st.multiselect(
        "Filter Strategies",
        options=all_strategies,
        default=[],
        key="backtest_strategy_multiselect",
    )

    # Asset multiselect -- show symbol, filter by asset_id
    try:
        assets_df = load_bakeoff_assets(engine)
    except Exception:  # noqa: BLE001
        assets_df = pd.DataFrame(columns=["asset_id", "symbol"])

    asset_symbols = assets_df["symbol"].tolist() if not assets_df.empty else []
    asset_filter_symbols = st.multiselect(
        "Filter Assets",
        options=asset_symbols,
        default=[],
        key="backtest_asset_multiselect",
    )

    # Resolve symbol -> asset_id for downstream filtering
    if asset_filter_symbols and not assets_df.empty:
        asset_filter_ids = assets_df[assets_df["symbol"].isin(asset_filter_symbols)][
            "asset_id"
        ].tolist()
    else:
        asset_filter_ids = []

# Persist URL state after widget interactions
st.query_params["view"] = view_mode
st.query_params["tf"] = tf_choice
st.query_params["cv_method"] = cv_choice
st.query_params["cost_scenario"] = cost_choice


# ---------------------------------------------------------------------------
# Helper: apply client-side filters to a leaderboard DataFrame
# ---------------------------------------------------------------------------


def _apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Apply strategy and asset multiselect filters to a loaded DataFrame."""
    if strategy_filter:
        df = df[df["strategy_name"].isin(strategy_filter)]
    if asset_filter_ids:
        df = df[df["asset_id"].isin(asset_filter_ids)]
    return df


# ---------------------------------------------------------------------------
# Helper: Monte Carlo bootstrap CI from fold Sharpe values
# ---------------------------------------------------------------------------


def _compute_mc_ci(
    fold_metrics: list[dict],
    n_bootstrap: int = 1000,
    ci_lower: float = 0.05,
    ci_upper: float = 0.95,
) -> tuple[float, float, float]:
    """Bootstrap CI for mean fold Sharpe.

    Returns (mean_sharpe, ci_low, ci_high). Returns (0.0, 0.0, 0.0) if
    fold_metrics is empty or has no sharpe values.
    """
    sharpe_vals = [
        float(f["sharpe"]) for f in fold_metrics if f.get("sharpe") is not None
    ]
    if len(sharpe_vals) < 2:
        mean_val = float(np.mean(sharpe_vals)) if sharpe_vals else 0.0
        return mean_val, mean_val, mean_val

    arr = np.array(sharpe_vals)
    rng = np.random.default_rng(42)
    boot_means = np.array(
        [
            rng.choice(arr, size=len(arr), replace=True).mean()
            for _ in range(n_bootstrap)
        ]
    )
    return (
        float(arr.mean()),
        float(np.quantile(boot_means, ci_lower)),
        float(np.quantile(boot_means, ci_upper)),
    )


# ---------------------------------------------------------------------------
# Auto-refreshing content fragment
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _backtest_content(
    _engine,
    view_mode: str,
    tf: str,
    cv_method: str,
    cost_scenario: str,
) -> None:
    """Auto-refreshing backtest results section."""

    # =====================================================================
    # Load leaderboard (server-side filtered by tf/cv_method/cost_scenario)
    # =====================================================================

    try:
        lb_df = load_bakeoff_leaderboard(
            _engine,
            tf=tf,
            cv_method=cv_method,
            cost_scenario=cost_scenario,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to load bakeoff leaderboard: {exc}")
        lb_df = pd.DataFrame()

    # Apply client-side filters (strategy, asset)
    filtered_df = _apply_filters(lb_df) if not lb_df.empty else lb_df

    # =====================================================================
    # View: Leaderboard
    # =====================================================================

    if view_mode == "Leaderboard":
        st.subheader("Strategy Leaderboard")
        st.caption(f"Ranked by Sharpe (mean) -- {tf} / {cv_method} / {cost_scenario}")

        if filtered_df.empty:
            st.info(
                "No results found. Check that bakeoff has been run and filters match "
                "available data."
            )
        else:
            display_cols = [
                c
                for c in [
                    "strategy_name",
                    "symbol",
                    "sharpe_mean",
                    "sharpe_std",
                    "psr",
                    "dsr",
                    "max_drawdown_worst",
                    "turnover",
                    "trade_count_total",
                    "pbo_prob",
                    "experiment_name",
                ]
                if c in filtered_df.columns
            ]

            st.dataframe(
                filtered_df[display_cols].reset_index(drop=True),
                use_container_width=True,
                key="backtest_leaderboard_table",
                column_config={
                    "sharpe_mean": st.column_config.NumberColumn(
                        "Sharpe (mean)",
                        format="%.3f",
                        help="Mean out-of-sample Sharpe ratio across CV folds",
                    ),
                    "sharpe_std": st.column_config.NumberColumn(
                        "Sharpe (std)",
                        format="%.3f",
                        help="Standard deviation of fold Sharpe values",
                    ),
                    "psr": st.column_config.NumberColumn(
                        "PSR",
                        format="%.3f",
                        help=(
                            "Probabilistic Sharpe Ratio: probability that true Sharpe > 0. "
                            ">0.95 = strong, >0.50 = moderate"
                        ),
                    ),
                    "dsr": st.column_config.NumberColumn(
                        "DSR",
                        format="%.3f",
                        help=(
                            "Deflated Sharpe Ratio: PSR adjusted for multiple testing. "
                            ">0.95 = strong after deflation"
                        ),
                    ),
                    "max_drawdown_worst": st.column_config.NumberColumn(
                        "Max DD (worst fold)",
                        format="%.3f",
                        help="Worst out-of-sample max drawdown across CV folds",
                    ),
                    "turnover": st.column_config.NumberColumn(
                        "Turnover",
                        format="%.3f",
                        help="Average daily turnover as fraction of portfolio",
                    ),
                    "trade_count_total": st.column_config.NumberColumn(
                        "Trades",
                        format="%d",
                        help="Total trade count across all CV folds",
                    ),
                    "pbo_prob": st.column_config.NumberColumn(
                        "PBO Prob",
                        format="%.3f",
                        help="Probability of Backtest Overfitting (lower is better)",
                    ),
                },
            )

            # CSV download of leaderboard
            csv_bytes = filtered_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download leaderboard CSV",
                data=csv_bytes,
                file_name=f"bakeoff_leaderboard_{tf}_{cv_method}_{cost_scenario}.csv",
                mime="text/csv",
                key="backtest_leaderboard_csv_download",
            )

    # =====================================================================
    # View: Strategy-First
    # =====================================================================

    elif view_mode == "Strategy-First":
        st.subheader("Strategy-First View")
        st.caption(
            "Each strategy grouped with its top assets by Sharpe. "
            "Equity sparklines shown for top 3 assets."
        )

        if filtered_df.empty:
            st.info("No results found for the current filter selection.")
        else:
            grouped = filtered_df.groupby("strategy_name")

            for strategy_name, group_df in grouped:
                group_sorted = group_df.sort_values(
                    "sharpe_mean", ascending=False
                ).reset_index(drop=True)

                with st.expander(
                    f"{strategy_name} ({len(group_sorted)} assets)", expanded=False
                ):
                    # Summary table for this strategy
                    summary_cols = [
                        c
                        for c in [
                            "symbol",
                            "sharpe_mean",
                            "sharpe_std",
                            "psr",
                            "dsr",
                            "max_drawdown_worst",
                            "turnover",
                            "trade_count_total",
                        ]
                        if c in group_sorted.columns
                    ]
                    st.dataframe(
                        group_sorted[summary_cols],
                        use_container_width=True,
                        key=f"strategy_first_table_{strategy_name}",
                    )

                    # Equity sparklines for top 3 assets
                    top3 = group_sorted.head(3)
                    if not top3.empty:
                        st.caption("Equity sparklines -- top 3 assets by Sharpe")
                        spark_cols = st.columns(min(len(top3), 3))

                        for col_idx, (_, asset_row) in enumerate(top3.iterrows()):
                            asset_id = int(asset_row["asset_id"])
                            symbol = str(asset_row.get("symbol", asset_id))

                            try:
                                fold_metrics = load_bakeoff_fold_metrics(
                                    _engine,
                                    strategy_name=str(strategy_name),
                                    asset_id=asset_id,
                                    tf=tf,
                                    cost_scenario=cost_scenario,
                                    cv_method=cv_method,
                                )
                                sparkline_fig = build_equity_sparkline(
                                    fold_metrics, height=150
                                )
                            except Exception:  # noqa: BLE001
                                sparkline_fig = build_equity_sparkline([], height=150)

                            with spark_cols[col_idx]:
                                st.caption(symbol)
                                st.plotly_chart(
                                    sparkline_fig,
                                    use_container_width=True,
                                    theme=None,
                                    key=f"sparkline_strat_{strategy_name}_{symbol}_{col_idx}",
                                )

    # =====================================================================
    # View: Asset-First
    # =====================================================================

    elif view_mode == "Asset-First":
        st.subheader("Asset-First View")
        st.caption("Each asset grouped with all strategies for comparison by Sharpe.")

        if filtered_df.empty:
            st.info("No results found for the current filter selection.")
        else:
            # Group by symbol if available, else asset_id
            group_col = "symbol" if "symbol" in filtered_df.columns else "asset_id"
            grouped = filtered_df.groupby(group_col)

            for group_key, group_df in grouped:
                group_sorted = group_df.sort_values(
                    "sharpe_mean", ascending=False
                ).reset_index(drop=True)

                with st.expander(
                    f"{group_key} ({len(group_sorted)} strategies)", expanded=False
                ):
                    summary_cols = [
                        c
                        for c in [
                            "strategy_name",
                            "sharpe_mean",
                            "sharpe_std",
                            "psr",
                            "dsr",
                            "max_drawdown_worst",
                            "turnover",
                            "trade_count_total",
                            "experiment_name",
                        ]
                        if c in group_sorted.columns
                    ]
                    st.dataframe(
                        group_sorted[summary_cols],
                        use_container_width=True,
                        key=f"asset_first_table_{group_key}",
                    )

    # =====================================================================
    # Section: Cost Scenario Comparison
    # =====================================================================

    st.divider()
    st.subheader("Cost Scenario Comparison")
    st.caption("Compare all cost scenarios for a selected strategy and asset.")

    cost_col1, cost_col2 = st.columns(2)

    with cost_col1:
        if all_strategies:
            selected_strategy = st.selectbox(
                "Strategy",
                options=all_strategies,
                key="cost_matrix_strategy_select",
            )
        else:
            selected_strategy = None
            st.info("No strategies available.")

    with cost_col2:
        if asset_symbols:
            selected_asset_symbol = st.selectbox(
                "Asset",
                options=asset_symbols,
                key="cost_matrix_asset_select",
            )
            # Resolve to asset_id
            if not assets_df.empty:
                _match = assets_df[assets_df["symbol"] == selected_asset_symbol]
                selected_asset_id = (
                    int(_match["asset_id"].iloc[0]) if not _match.empty else None
                )
            else:
                selected_asset_id = None
        else:
            selected_asset_symbol = None
            selected_asset_id = None
            st.info("No assets available.")

    if selected_strategy and selected_asset_id is not None:
        try:
            cost_df = load_bakeoff_cost_matrix(
                _engine,
                strategy_name=selected_strategy,
                asset_id=selected_asset_id,
                tf=tf,
                cv_method=cv_method,
            )

            if cost_df.empty:
                st.info(
                    f"No cost scenario data found for {selected_strategy} / "
                    f"{selected_asset_symbol}. Ensure bakeoff ran all 16 scenarios."
                )
            else:
                # Pivot: rows = metrics, columns = cost scenarios
                metric_cols = [
                    c
                    for c in [
                        "sharpe_mean",
                        "psr",
                        "dsr",
                        "max_drawdown_worst",
                        "turnover",
                        "trade_count_total",
                    ]
                    if c in cost_df.columns
                ]
                pivot = cost_df.set_index("cost_scenario")[metric_cols].T
                pivot.index.name = "metric"

                st.dataframe(
                    pivot,
                    use_container_width=True,
                    key="cost_matrix_pivot_table",
                )

        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load cost matrix: {exc}")

    # =====================================================================
    # Section: Monte Carlo Sharpe CI
    # =====================================================================

    st.divider()
    st.subheader("Monte Carlo Sharpe CI")
    st.caption(
        "Bootstrap confidence interval for mean fold Sharpe "
        "(1000 resamples, 5th-95th percentile CI)."
    )

    if selected_strategy and selected_asset_id is not None:
        try:
            fold_metrics = load_bakeoff_fold_metrics(
                _engine,
                strategy_name=selected_strategy,
                asset_id=selected_asset_id,
                tf=tf,
                cost_scenario=cost_scenario,
                cv_method=cv_method,
            )

            if not fold_metrics:
                st.info(
                    f"No fold metrics found for {selected_strategy} / "
                    f"{selected_asset_symbol} / {cost_scenario}."
                )
            else:
                mean_sharpe, ci_low, ci_high = _compute_mc_ci(fold_metrics)

                mc_c1, mc_c2, mc_c3 = st.columns(3)
                mc_c1.metric(
                    "Sharpe (mean)",
                    f"{mean_sharpe:.3f}",
                    help="Mean fold Sharpe ratio",
                )
                mc_c2.metric(
                    "95% CI Lower (5th pct)",
                    f"{ci_low:.3f}",
                    help="5th percentile of 1000 bootstrap resamples of mean fold Sharpe",
                )
                mc_c3.metric(
                    "95% CI Upper (95th pct)",
                    f"{ci_high:.3f}",
                    help="95th percentile of 1000 bootstrap resamples of mean fold Sharpe",
                )

                # Equity sparkline
                sparkline_fig = build_equity_sparkline(fold_metrics, height=180)
                st.plotly_chart(
                    sparkline_fig,
                    use_container_width=True,
                    theme=None,
                    key="mc_equity_sparkline",
                )
                chart_download_button(
                    sparkline_fig,
                    label="Download equity sparkline",
                    filename=f"equity_sparkline_{selected_strategy}_{selected_asset_symbol}.html",
                )

        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not compute Monte Carlo CI: {exc}")
    else:
        st.info("Select a strategy and asset above to view Monte Carlo CI.")

    # =====================================================================
    # Section: Trade Table with MAE/MFE
    # =====================================================================

    st.divider()
    st.subheader("Trade Detail (MAE/MFE)")
    st.caption(
        "Closed trade table with MAE = worst intra-trade drawdown, "
        "MFE = best intra-trade gain (as % of entry price)."
    )

    if selected_strategy and selected_asset_id is not None:
        try:
            trades_df = load_closed_signals_for_strategy(
                _engine,
                strategy_name=selected_strategy,
                asset_id=selected_asset_id,
                tf=tf,
            )

            if trades_df.empty:
                st.info(
                    f"No closed trades found for {selected_strategy} / "
                    f"{selected_asset_symbol}. Signals may all be open or not yet generated."
                )
            else:
                # Load close prices for the MAE/MFE window
                has_entry = (
                    "entry_ts" in trades_df.columns
                    and not trades_df["entry_ts"].isna().all()
                )
                has_exit = (
                    "exit_ts" in trades_df.columns
                    and not trades_df["exit_ts"].isna().all()
                )

                if has_entry and has_exit:
                    start_ts = trades_df["entry_ts"].dropna().min()
                    end_ts = trades_df["exit_ts"].dropna().max()

                    try:
                        close_series = _load_close_prices(
                            _engine,
                            asset_id=selected_asset_id,
                            start_ts=start_ts,
                            end_ts=end_ts,
                            tf=tf,
                        )

                        if not close_series.empty:
                            trades_with_mae = compute_mae_mfe(trades_df, close_series)
                        else:
                            trades_with_mae = trades_df.copy()
                            trades_with_mae["mae"] = None
                            trades_with_mae["mfe"] = None
                            st.caption(
                                "Close prices not available for MAE/MFE computation. "
                                "Ensure features table is populated."
                            )

                    except Exception as exc:  # noqa: BLE001
                        trades_with_mae = trades_df.copy()
                        trades_with_mae["mae"] = None
                        trades_with_mae["mfe"] = None
                        st.caption(f"Could not load close prices for MAE/MFE: {exc}")
                else:
                    trades_with_mae = trades_df.copy()
                    if "mae" not in trades_with_mae.columns:
                        trades_with_mae["mae"] = None
                    if "mfe" not in trades_with_mae.columns:
                        trades_with_mae["mfe"] = None

                display_trade_cols = [
                    c
                    for c in [
                        "direction",
                        "entry_ts",
                        "entry_price",
                        "exit_ts",
                        "exit_price",
                        "pnl_pct",
                        "mae",
                        "mfe",
                        "regime_key",
                    ]
                    if c in trades_with_mae.columns
                ]

                # Convert to % for MAE/MFE display (stored as decimals)
                trades_display = trades_with_mae[display_trade_cols].copy()
                if "mae" in trades_display.columns:
                    trades_display["mae"] = trades_display["mae"].apply(
                        lambda v: float(v) * 100 if v is not None else None
                    )
                if "mfe" in trades_display.columns:
                    trades_display["mfe"] = trades_display["mfe"].apply(
                        lambda v: float(v) * 100 if v is not None else None
                    )
                if "pnl_pct" in trades_display.columns:
                    trades_display["pnl_pct"] = trades_display["pnl_pct"].apply(
                        lambda v: float(v) * 100 if v is not None else None
                    )

                st.dataframe(
                    trades_display.reset_index(drop=True),
                    use_container_width=True,
                    key="backtest_trade_mae_mfe_table",
                    column_config={
                        "pnl_pct": st.column_config.NumberColumn(
                            "PnL %",
                            format="%.2f%%",
                            help="Realized PnL as % of entry price",
                        ),
                        "mae": st.column_config.NumberColumn(
                            "MAE %",
                            format="%.2f%%",
                            help="Maximum Adverse Excursion: worst intra-trade drawdown as % of entry",
                        ),
                        "mfe": st.column_config.NumberColumn(
                            "MFE %",
                            format="%.2f%%",
                            help="Maximum Favorable Excursion: best intra-trade gain as % of entry",
                        ),
                    },
                )

                st.caption(
                    "MAE = worst intra-trade drawdown, MFE = best intra-trade gain "
                    "(as % of entry). Negative MAE = trade moved against position."
                )

        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load trade table: {exc}")
    else:
        st.info(
            "Select a strategy and asset in the Cost Scenario section to view trades."
        )

    # -----------------------------------------------------------------------
    # Refresh caption
    # -----------------------------------------------------------------------

    st.caption(f"Auto-refreshes every {AUTO_REFRESH_SECONDS // 60} minutes")


# ---------------------------------------------------------------------------
# Invoke fragment
# ---------------------------------------------------------------------------

_backtest_content(
    engine,
    view_mode=view_mode,
    tf=tf_choice,
    cv_method=cv_choice,
    cost_scenario=cost_choice,
)
