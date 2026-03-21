# -*- coding: utf-8 -*-
"""
Macro Regime dashboard page -- Phase 72 Macro Observability.

Displays current macro regime status (OBSV-01), regime timeline with 4 stacked
dimension bands and optional overlay (OBSV-05), recent transitions, and FRED
data quality (OBSV-06).

NOTE: Do NOT call st.set_page_config() here -- it is called in the main app
entry point (app.py). Calling it again from a page script raises a
StreamlitAPIException.
"""

from __future__ import annotations

import streamlit as st

from ta_lab2.dashboard.charts import (
    build_fred_quality_chart,
    build_macro_regime_timeline,
    chart_download_button,
)
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.macro import (
    load_current_macro_regime,
    load_fred_freshness,
    load_fred_series_quality,
    load_macro_regime_history,
    load_macro_transition_log,
)

# ---------------------------------------------------------------------------
# Auto-refresh interval
# ---------------------------------------------------------------------------

AUTO_REFRESH_SECONDS = 900

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Macro Regime")
st.caption("Current macro conditions, regime timeline, and FRED data health")

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:  # noqa: BLE001
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Alert banners (outside fragment -- always visible)
# ---------------------------------------------------------------------------

try:
    _current_df = load_current_macro_regime(engine)

    if not _current_df.empty:
        _macro_state = str(_current_df.iloc[0]["macro_state"]).lower()

        if _macro_state == "adverse":
            st.error("Macro regime is ADVERSE -- risk-off conditions detected")
        elif _macro_state == "cautious":
            st.warning("Macro regime is CAUTIOUS -- elevated macro risk")

except Exception as exc:  # noqa: BLE001
    st.warning(f"Could not load macro regime state: {exc}")

# ---------------------------------------------------------------------------
# Sidebar controls (outside fragment)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Macro Controls")

    history_days = st.select_slider(
        "History (days)",
        options=[30, 90, 180, 365, 730],
        value=365,
    )

    overlay_choice = st.selectbox(
        "Chart Overlay",
        options=["None", "Portfolio PnL", "BTC", "ETH"],
    )

    show_quality = st.checkbox(
        "Show FRED data quality details",
        value=False,
    )


# ---------------------------------------------------------------------------
# Traffic-light helper for FRED freshness
# ---------------------------------------------------------------------------


def _traffic_light_fred(status: str) -> str:
    """Return a coloured circle emoji for FRED series freshness status."""
    if status == "green":
        return ":large_green_circle:"
    if status == "orange":
        return ":large_orange_circle:"
    return ":red_circle:"


# ---------------------------------------------------------------------------
# Auto-refreshing content section
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _macro_content(_engine, history_days, overlay_choice, show_quality):
    """Auto-refreshing macro regime metrics section."""

    # =======================================================================
    # Section 1: Current Macro Regime (OBSV-01)
    # =======================================================================

    st.subheader("Current Regime")

    try:
        current_df = load_current_macro_regime(_engine)

        if current_df.empty:
            st.info("No macro regime data. Run refresh_macro_regimes.py first.")
        else:
            row = current_df.iloc[0]
            macro_state = str(row["macro_state"]).lower()

            # Color-coded macro state badge
            _state_colors: dict[str, str] = {
                "favorable": "#00c864",
                "constructive": "#64c864",
                "neutral": "#969696",
                "cautious": "#ffa500",
                "adverse": "#dc3232",
            }
            color = _state_colors.get(macro_state, "#969696")
            st.markdown(
                f'<span style="background-color:{color};padding:4px 12px;'
                f'border-radius:4px;font-weight:bold;font-size:1.2em;color:#fff">'
                f"{macro_state.upper()}</span>",
                unsafe_allow_html=True,
            )

            st.write("")  # spacer

            # Per-dimension labels
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Monetary Policy", row["monetary_policy"])
            c2.metric("Liquidity", row["liquidity"])
            c3.metric("Risk Appetite", row["risk_appetite"])
            c4.metric("Carry", row["carry"])

            st.caption(
                f"Composite key: {row['regime_key']} | "
                f"As of: {row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else row['date']}"
            )

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load current macro regime: {exc}")

    st.divider()

    # =======================================================================
    # Section 2: Macro Regime Timeline (OBSV-05)
    # =======================================================================

    st.subheader("Regime Timeline")

    try:
        regimes_df = load_macro_regime_history(_engine, days=history_days)

        # Build overlay dataframe based on sidebar choice
        overlay_df = None
        if overlay_choice == "Portfolio PnL":
            try:
                from ta_lab2.dashboard.queries.trading import load_daily_pnl_series  # noqa: PLC0415

                overlay_df = load_daily_pnl_series(_engine)
            except Exception:  # noqa: BLE001
                st.caption("Overlay data not available")
        elif overlay_choice in ("BTC", "ETH"):
            try:
                from sqlalchemy import text  # noqa: PLC0415

                _symbol_map = {"BTC": "BTC", "ETH": "ETH"}
                _symbol = _symbol_map[overlay_choice]
                _sql = text(
                    """
                    SELECT
                        date_trunc('day', ts AT TIME ZONE 'UTC') AS date,
                        AVG(close) AS close
                    FROM public.price_bars_multi_tf_u pb
                    JOIN public.dim_assets da ON da.id = pb.id
                    WHERE da.symbol = :symbol
                      AND pb.tf = '1d'
                      AND pb.alignment_source = 'multi_tf'
                      AND pb.ts >= NOW() - (:days_back || ' days')::interval
                    GROUP BY 1
                    ORDER BY 1
                    """
                )
                with _engine.connect() as _conn:
                    import pandas as pd  # noqa: PLC0415

                    overlay_df = pd.read_sql(
                        _sql,
                        _conn,
                        params={"symbol": _symbol, "days_back": history_days},
                    )
                if overlay_df is not None and not overlay_df.empty:
                    overlay_df["date"] = pd.to_datetime(overlay_df["date"])
            except Exception:  # noqa: BLE001
                overlay_df = None
                st.caption("Overlay data not available")

        if regimes_df.empty:
            st.info(
                "No regime history found. Run refresh_macro_regimes.py to generate data."
            )
        else:
            fig = build_macro_regime_timeline(
                regimes_df,
                overlay_df,
                overlay_label=overlay_choice if overlay_choice != "None" else None,
            )
            st.plotly_chart(fig, use_container_width=True, theme=None)
            chart_download_button(
                fig,
                label="Download timeline chart",
                filename="macro_regime_timeline.html",
            )

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load regime timeline: {exc}")

    st.divider()

    # =======================================================================
    # Section 3: Recent Transitions
    # =======================================================================

    st.subheader("Recent Transitions")

    try:
        transitions_df = load_macro_transition_log(_engine, days=90)

        if transitions_df.empty:
            st.info("No regime transitions in the last 90 days.")
        else:
            display_cols = [
                c
                for c in [
                    "date",
                    "prev_regime_key",
                    "regime_key",
                    "macro_state",
                    "monetary_policy",
                    "liquidity",
                    "risk_appetite",
                    "carry",
                ]
                if c in transitions_df.columns
            ]
            st.dataframe(
                transitions_df[display_cols].reset_index(drop=True),
                use_container_width=True,
            )

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load transition log: {exc}")

    st.divider()

    # =======================================================================
    # Section 4: FRED Data Quality (OBSV-06)
    # =======================================================================

    st.subheader("FRED Data Health")

    try:
        fred_df = load_fred_freshness(_engine)

        if fred_df.empty:
            st.info("No FRED data found in fred.series_values.")
        else:
            n_green = int((fred_df["status"] == "green").sum())
            n_orange = int((fred_df["status"] == "orange").sum())
            n_red = int((fred_df["status"] == "red").sum())

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Series", len(fred_df))
            c2.metric(":large_green_circle: Fresh", n_green)
            c3.metric(":large_orange_circle: Stale", n_orange)
            c4.metric(":red_circle: Critical", n_red)

            # Freshness table with traffic-light column
            display_df = fred_df[
                ["series_id", "latest_date", "staleness_days", "frequency", "status"]
            ].copy()
            display_df["indicator"] = display_df["status"].apply(_traffic_light_fred)
            st.dataframe(
                display_df[
                    [
                        "indicator",
                        "series_id",
                        "latest_date",
                        "staleness_days",
                        "frequency",
                    ]
                ].reset_index(drop=True),
                use_container_width=True,
            )

            # Optional detailed quality section
            if show_quality:
                try:
                    quality_df = load_fred_series_quality(_engine)

                    if not quality_df.empty:
                        quality_fig = build_fred_quality_chart(quality_df)
                        st.plotly_chart(
                            quality_fig, use_container_width=True, theme=None
                        )

                        with st.expander("Quality Details", expanded=False):
                            st.dataframe(
                                quality_df.reset_index(drop=True),
                                use_container_width=True,
                            )

                except Exception as exc:  # noqa: BLE001
                    st.warning(f"Could not load FRED quality details: {exc}")

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load FRED data health: {exc}")

    # -----------------------------------------------------------------------
    # Refresh caption
    # -----------------------------------------------------------------------

    st.caption(f"Auto-refreshes every {AUTO_REFRESH_SECONDS // 60} minutes")


# ---------------------------------------------------------------------------
# Invoke fragment
# ---------------------------------------------------------------------------

_macro_content(engine, history_days, overlay_choice, show_quality)
