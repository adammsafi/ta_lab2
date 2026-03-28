"""
Trading page -- PnL, Positions, and Trade Log.

Displays:
  1. Alert banners (kill switch / drift pause) -- always at top, impossible to miss
  2. Portfolio Summary KPIs (4 metrics)
  3. PnL + Drawdown stacked two-panel chart
  4. Drawdown KPIs
  5. Open Positions table with all 12 CONTEXT.md columns
  6. Recent Trades log (last 20 fills)

do NOT call st.set_page_config() here -- that is in app.py.
"""

from __future__ import annotations

import datetime

import streamlit as st

from ta_lab2.dashboard.charts import build_pnl_drawdown_chart, chart_download_button
from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.risk import load_risk_state
from ta_lab2.dashboard.queries.trading import (
    load_daily_pnl_series,
    load_open_positions,
    load_recent_fills,
)

# ---------------------------------------------------------------------------
# Module-level constant: change this to adjust auto-refresh interval
# ---------------------------------------------------------------------------
AUTO_REFRESH_SECONDS = 900  # 15 minutes

# ---------------------------------------------------------------------------
# Alert banners (outside fragment -- must react immediately, no cache delay)
# ---------------------------------------------------------------------------
st.header("Trading")
st.caption("Daily PnL, exposure, and fill activity for paper trading")

try:
    _banner_engine = get_engine()
    _risk_state = load_risk_state(_banner_engine)

    if _risk_state.get("trading_state") == "halted":
        _halted_by = _risk_state.get("halted_by") or "unknown"
        _halted_at = _risk_state.get("halted_at") or "unknown"
        _halted_reason = _risk_state.get("halted_reason") or "no reason recorded"
        st.error(
            f"**KILL SWITCH ACTIVE** -- Trading is halted. "
            f"Halted by: {_halted_by} | At: {_halted_at} | Reason: {_halted_reason}"
        )

    if _risk_state.get("drift_paused"):
        _paused_at = _risk_state.get("drift_paused_at") or "unknown"
        _paused_reason = _risk_state.get("drift_paused_reason") or "no reason recorded"
        st.warning(
            f"**DRIFT PAUSE ACTIVE** -- Signal generation paused. "
            f"Paused at: {_paused_at} | Reason: {_paused_reason}"
        )

except Exception as exc:  # noqa: BLE001
    st.warning(f"Could not load risk state for banners: {exc}")

# ---------------------------------------------------------------------------
# Sidebar controls (outside fragment -- st.sidebar not allowed in fragment)
# ---------------------------------------------------------------------------
show_per_strategy = st.sidebar.toggle(
    "Per-Strategy Breakdown",
    value=False,
    help="Show each strategy as separate rows in the positions table",
)

st.divider()


# ---------------------------------------------------------------------------
# Auto-refreshing content section
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _trading_content(_engine, show_per_strategy: bool) -> None:  # noqa: ANN001
    """Render the main trading page content. Auto-refreshes every AUTO_REFRESH_SECONDS."""

    # -----------------------------------------------------------------------
    # Portfolio Summary KPIs
    # -----------------------------------------------------------------------
    st.subheader("Portfolio Summary")

    try:
        _rs = load_risk_state(_engine)
        _positions = load_open_positions(_engine)
        _pnl_series = load_daily_pnl_series(_engine)

        _day_open_value = float(_rs.get("day_open_portfolio_value") or 0.0)
        _unrealized_sum = (
            float(_positions["unrealized_pnl"].sum()) if not _positions.empty else 0.0
        )
        _total_portfolio_value = _day_open_value + _unrealized_sum

        _daily_pnl = (
            float(_pnl_series["daily_realized_pnl"].iloc[-1])
            if not _pnl_series.empty
            else 0.0
        )
        _cum_pnl = (
            float(_pnl_series["cumulative_pnl"].iloc[-1])
            if not _pnl_series.empty
            else 0.0
        )
        _open_count = (
            int((~_positions.empty) and len(_positions)) if not _positions.empty else 0
        )

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Portfolio Value", f"${_total_portfolio_value:,.2f}")
        k2.metric(
            "Daily P&L",
            f"${_daily_pnl:,.2f}",
            delta=f"{_daily_pnl:+.2f}",
            delta_color="normal",
        )
        k3.metric("Cumulative P&L", f"${_cum_pnl:,.2f}")
        k4.metric("Open Positions", _open_count)

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load portfolio KPIs: {exc}")
        _positions = None
        _pnl_series = None
        _total_portfolio_value = 0.0

    st.divider()

    # -----------------------------------------------------------------------
    # PnL + Drawdown chart
    # -----------------------------------------------------------------------
    st.subheader("Equity Curve & Drawdown")

    try:
        if _pnl_series is None:
            _pnl_series = load_daily_pnl_series(_engine)

        _fig = build_pnl_drawdown_chart(_pnl_series)
        st.plotly_chart(_fig, use_container_width=True, theme=None)
        chart_download_button(
            _fig, label="Export chart (HTML)", filename="pnl_drawdown.html"
        )

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render PnL chart: {exc}")
        _pnl_series = None

    # -----------------------------------------------------------------------
    # Drawdown KPIs
    # -----------------------------------------------------------------------
    try:
        if _pnl_series is not None and not _pnl_series.empty:
            _peak = float(_pnl_series["peak_equity"].max())
            _current_dd_pct = float(_pnl_series["drawdown_pct"].iloc[-1])
            _max_dd_pct = float(_pnl_series["drawdown_pct"].min())

            if "drawdown_usd" in _pnl_series.columns:
                _current_dd_usd = float(_pnl_series["drawdown_usd"].iloc[-1])
                _max_dd_usd = float(_pnl_series["drawdown_usd"].min())
            else:
                _current_dd_usd = 0.0
                _max_dd_usd = 0.0

            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Peak Equity", f"${_peak:,.2f}")
            d2.metric("Current Drawdown", f"{_current_dd_pct:.1%}")
            d3.metric("Current DD ($)", f"${_current_dd_usd:,.2f}")
            d4.metric("Max Drawdown", f"{_max_dd_pct:.1%} (${_max_dd_usd:,.2f})")

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not compute drawdown KPIs: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Open Positions table -- 12 CONTEXT.md columns
    # -----------------------------------------------------------------------
    st.subheader("Open Positions")

    try:
        if _positions is None:
            _positions = load_open_positions(_engine)

        if _positions.empty:
            st.info("No open positions.")
        else:
            _pos_display = _positions.copy()

            # Derived columns
            _pos_display["Side"] = _pos_display["quantity"].apply(
                lambda q: "Long" if float(q) > 0 else "Short"
            )

            # % of Portfolio
            if _total_portfolio_value > 0:
                _pos_display["pct_of_portfolio"] = (
                    (
                        _pos_display["quantity"].abs() * _pos_display["last_mark_price"]
                    ).abs()
                    / _total_portfolio_value
                    * 100.0
                )
            else:
                _pos_display["pct_of_portfolio"] = 0.0

            # Column renames for display
            _col_rename = {
                "symbol": "Asset",
                "quantity": "Qty",
                "avg_cost_basis": "Avg Cost",
                "last_mark_price": "Current Price",
                "unrealized_pnl": "Unrealized PnL",
                "pct_of_portfolio": "% of Portfolio",
                "config_name": "Strategy",
                "entry_date": "Entry Date",
                "realized_pnl": "Realized PnL",
                "signal_type": "Signal Type",
                "regime_label": "Regime Label",
            }
            _display_cols = [
                "symbol",
                "Side",
                "quantity",
                "avg_cost_basis",
                "last_mark_price",
                "unrealized_pnl",
                "pct_of_portfolio",
                "config_name",
                "entry_date",
                "realized_pnl",
                "signal_type",
                "regime_label",
            ]

            if show_per_strategy:
                # Keep all rows (each strategy is a separate row)
                _display_cols_filtered = [
                    c for c in _display_cols if c in _pos_display.columns or c == "Side"
                ]
            else:
                # Aggregate view: group by asset, sum numeric cols
                _agg_cols = {
                    "quantity": "sum",
                    "unrealized_pnl": "sum",
                    "realized_pnl": "sum",
                    "avg_cost_basis": "mean",
                    "last_mark_price": "last",
                    "pct_of_portfolio": "sum",
                }
                _grp_cols = [
                    c
                    for c in ["symbol", "signal_type", "regime_label"]
                    if c in _pos_display.columns
                ]
                if _grp_cols:
                    _agg_existing = {
                        k: v for k, v in _agg_cols.items() if k in _pos_display.columns
                    }
                    _pos_display = _pos_display.groupby(_grp_cols, as_index=False).agg(
                        _agg_existing
                    )
                    _pos_display["Side"] = _pos_display["quantity"].apply(
                        lambda q: "Long" if float(q) > 0 else "Short"
                    )
                _display_cols_filtered = [
                    c for c in _display_cols if c in _pos_display.columns or c == "Side"
                ]
                # Exclude per-strategy columns in aggregate view
                _display_cols_filtered = [
                    c
                    for c in _display_cols_filtered
                    if c not in ("config_name", "entry_date")
                ]

            # Filter to columns that exist
            _final_cols = [
                c for c in _display_cols_filtered if c in _pos_display.columns
            ]
            _pos_out = _pos_display[_final_cols].rename(columns=_col_rename)

            # Format numeric columns
            _num_fmt: dict[str, str] = {}
            for _col in _pos_out.columns:
                if _col in ("Avg Cost", "Current Price"):
                    _num_fmt[_col] = "%.2f"
                elif _col in ("Unrealized PnL", "Realized PnL", "Daily P&L"):
                    _num_fmt[_col] = "%.2f"
                elif _col == "% of Portfolio":
                    _num_fmt[_col] = "%.1f"

            st.dataframe(_pos_out, use_container_width=True)

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load positions table: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Trade Log -- last 20 fills
    # -----------------------------------------------------------------------
    st.subheader("Recent Trades")

    try:
        _fills = load_recent_fills(_engine)

        if _fills.empty:
            st.info("No fills recorded yet.")
        else:
            _fill_cols = [
                c
                for c in [
                    "filled_at",
                    "symbol",
                    "side",
                    "fill_qty",
                    "fill_price",
                    "fee_amount",
                    "signal_id",
                ]
                if c in _fills.columns
            ]
            _fill_rename = {
                "filled_at": "Time",
                "symbol": "Asset",
                "side": "Side",
                "fill_qty": "Qty",
                "fill_price": "Price",
                "fee_amount": "Fee",
                "signal_id": "Signal ID",
            }
            _fill_out = _fills[_fill_cols].rename(columns=_fill_rename)
            st.dataframe(_fill_out, use_container_width=True)

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load recent fills: {exc}")

    # -----------------------------------------------------------------------
    # Refresh caption
    # -----------------------------------------------------------------------
    _now_str = datetime.datetime.now(tz=datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    st.caption(
        f"Last updated: {_now_str} | Auto-refreshes every {AUTO_REFRESH_SECONDS // 60} minutes"
    )


# ---------------------------------------------------------------------------
# Invoke the fragment
# ---------------------------------------------------------------------------
_main_engine = get_engine()
_trading_content(_main_engine, show_per_strategy)
