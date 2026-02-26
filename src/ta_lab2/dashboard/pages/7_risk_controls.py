"""
Risk & Controls page -- Kill Switch, Limits, Circuit Breakers, and Event Audit Trail.

Displays:
  1. Alert banners (kill switch / drift pause) -- always at top, impossible to miss
  2. Risk Status Cards (kill switch, drift pause, circuit breaker, last update)
  3. Proximity Gauges (daily loss consumed, max position utilization)
  4. Circuit Breaker Details (expandable, per-asset/strategy breakdown)
  5. Risk Event History (filterable table)

do NOT call st.set_page_config() here -- that is in app.py.
"""

from __future__ import annotations

import datetime
import json

import streamlit as st

from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.risk import (
    load_risk_events,
    load_risk_limits,
    load_risk_state,
)
from ta_lab2.dashboard.queries.trading import load_open_positions

# ---------------------------------------------------------------------------
# Module-level constant: change this to adjust auto-refresh interval
# ---------------------------------------------------------------------------
AUTO_REFRESH_SECONDS = 900  # 15 minutes

# ---------------------------------------------------------------------------
# Known event_type values from cmc_risk_events CHECK constraint
# ---------------------------------------------------------------------------
RISK_EVENT_TYPES: list[str] = [
    "kill_switch_activated",
    "kill_switch_lifted",
    "drift_pause_activated",
    "drift_pause_lifted",
    "circuit_breaker_tripped",
    "circuit_breaker_reset",
    "daily_loss_limit_hit",
    "position_limit_hit",
    "manual_override",
]

# ---------------------------------------------------------------------------
# Alert banners (outside fragment -- must react immediately, no cache delay)
# ---------------------------------------------------------------------------
st.header("Risk & Controls")
st.caption(
    "Kill switch state, limit proximity, circuit breakers, and event audit trail"
)

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
_event_type_options: list[str | None] = [None] + RISK_EVENT_TYPES
_event_type_labels: list[str] = ["All types"] + RISK_EVENT_TYPES
_event_type_idx = st.sidebar.selectbox(
    "Event Type Filter",
    options=range(len(_event_type_options)),
    format_func=lambda i: _event_type_labels[i],
    index=0,
)
_selected_event_type: str | None = _event_type_options[_event_type_idx]

_event_days = st.sidebar.select_slider(
    "Event History (days)",
    options=[7, 14, 30, 60, 90],
    value=30,
)

st.divider()


# ---------------------------------------------------------------------------
# Auto-refreshing content section
# ---------------------------------------------------------------------------


@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _risk_content(
    _engine,  # noqa: ANN001
    event_type_filter: str | None,
    event_days: int,
) -> None:
    """Render the main risk & controls content. Auto-refreshes every AUTO_REFRESH_SECONDS."""

    # -----------------------------------------------------------------------
    # Risk Status Cards
    # -----------------------------------------------------------------------
    st.subheader("Risk Status")

    try:
        _rs = load_risk_state(_engine)

        if not _rs:
            st.info("No risk state found (dim_risk_state table is empty).")
        else:
            _trading_state = _rs.get("trading_state", "active")
            _drift_paused = bool(_rs.get("drift_paused", False))
            _halted_at = _rs.get("halted_at")
            _drift_paused_at = _rs.get("drift_paused_at")
            _updated_at = _rs.get("updated_at")

            # Parse circuit breaker tripped JSON to count tripped keys
            _cb_tripped_raw = _rs.get("cb_breaker_tripped_at") or "{}"
            try:
                _cb_tripped: dict = (
                    json.loads(_cb_tripped_raw)
                    if isinstance(_cb_tripped_raw, str)
                    else dict(_cb_tripped_raw or {})
                )
            except (json.JSONDecodeError, TypeError):
                _cb_tripped = {}
            _tripped_count = sum(1 for v in _cb_tripped.values() if v is not None)

            # Compute time-since for halted_at / drift_paused_at
            def _time_since(ts_val) -> str:  # noqa: ANN001
                if ts_val is None:
                    return ""
                try:
                    if isinstance(ts_val, str):
                        ts_dt = datetime.datetime.fromisoformat(
                            ts_val.replace("Z", "+00:00")
                        )
                    else:
                        ts_dt = ts_val
                    now = datetime.datetime.now(tz=datetime.timezone.utc)
                    if ts_dt.tzinfo is None:
                        ts_dt = ts_dt.replace(tzinfo=datetime.timezone.utc)
                    delta = now - ts_dt
                    hours = int(delta.total_seconds() // 3600)
                    minutes = int((delta.total_seconds() % 3600) // 60)
                    if hours > 0:
                        return f"{hours}h {minutes}m ago"
                    return f"{minutes}m ago"
                except Exception:  # noqa: BLE001
                    return str(ts_val)

            s1, s2, s3, s4 = st.columns(4)

            with s1:
                if _trading_state == "active":
                    st.metric("Kill Switch", "ACTIVE", delta=None)
                    st.caption(":large_green_circle: Trading enabled")
                else:
                    _since = _time_since(_halted_at)
                    st.metric(
                        "Kill Switch",
                        "HALTED",
                        delta=_since if _since else None,
                        delta_color="off",
                    )
                    st.caption(":red_circle: Trading halted")

            with s2:
                if not _drift_paused:
                    st.metric("Drift Pause", "OK", delta=None)
                    st.caption(":large_green_circle: Signal generation active")
                else:
                    _since_drift = _time_since(_drift_paused_at)
                    st.metric(
                        "Drift Pause",
                        "PAUSED",
                        delta=_since_drift if _since_drift else None,
                        delta_color="off",
                    )
                    st.caption(":large_orange_circle: Signal generation paused")

            with s3:
                _cb_label = (
                    f"{_tripped_count} tripped" if _tripped_count > 0 else "0 tripped"
                )
                _cb_color = (
                    ":red_circle:" if _tripped_count > 0 else ":large_green_circle:"
                )
                st.metric("Circuit Breakers", _cb_label)
                st.caption(
                    f"{_cb_color} {'Active breakers!' if _tripped_count > 0 else 'All clear'}"
                )

            with s4:
                _upd_str = str(_updated_at) if _updated_at else "N/A"
                st.metric("Last Update", "")
                st.caption(f"Risk state updated: {_upd_str}")

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load risk status cards: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Proximity Gauges
    # -----------------------------------------------------------------------
    st.subheader("Limit Proximity")

    try:
        _rs = load_risk_state(_engine)
        _limits = load_risk_limits(_engine)
        _positions = load_open_positions(_engine)

        g1, g2 = st.columns(2)

        with g1:
            st.markdown("**Daily Loss**")
            _daily_loss_cap = float(_limits.get("daily_loss_pct_threshold") or 0.0)
            _day_open_value = float(_rs.get("day_open_portfolio_value") or 0.0)
            _unrealized_sum = (
                float(_positions["unrealized_pnl"].sum())
                if not _positions.empty
                else 0.0
            )
            _current_value = _day_open_value + _unrealized_sum

            if _day_open_value > 0 and _daily_loss_cap > 0:
                _pnl_change = (_current_value - _day_open_value) / _day_open_value
                # Daily loss consumed is the negative of the return (loss is positive consumed)
                _consumed_pct = max(0.0, -_pnl_change)
                _progress_val = (
                    min(1.0, _consumed_pct / _daily_loss_cap)
                    if _daily_loss_cap > 0
                    else 0.0
                )
                st.progress(
                    _progress_val,
                    text=f"Daily Loss: {_consumed_pct:.1%} consumed / {_daily_loss_cap:.1%} cap",
                )
                _util_pct = (
                    _consumed_pct / _daily_loss_cap if _daily_loss_cap > 0 else 0.0
                )
                if _util_pct > 0.90:
                    st.caption(
                        ":red_circle: Near limit -- immediate attention required"
                    )
                elif _util_pct > 0.70:
                    st.caption(":large_orange_circle: Approaching limit")
                else:
                    st.caption(":large_green_circle: Within limits")
            else:
                st.progress(
                    0.0, text="Daily Loss: N/A (no baseline or limit configured)"
                )
                st.caption("No day-open portfolio value or daily loss cap configured")

        with g2:
            st.markdown("**Position Utilization**")
            _max_pos_cap = float(_limits.get("max_position_pct") or 0.0)
            _total_value = _day_open_value + _unrealized_sum

            if not _positions.empty and _total_value > 0 and _max_pos_cap > 0:
                _pos_pcts = (
                    _positions["quantity"].abs() * _positions["last_mark_price"]
                ).abs() / _total_value
                _max_pos_pct = float(_pos_pcts.max()) if len(_pos_pcts) > 0 else 0.0
                _progress_pos = min(1.0, _max_pos_pct / _max_pos_cap)
                st.progress(
                    _progress_pos,
                    text=f"Largest Position: {_max_pos_pct:.1%} / {_max_pos_cap:.0%} cap",
                )
                _pos_util = _max_pos_pct / _max_pos_cap if _max_pos_cap > 0 else 0.0
                if _pos_util > 0.90:
                    st.caption(":red_circle: Near position limit")
                elif _pos_util > 0.70:
                    st.caption(":large_orange_circle: Approaching position limit")
                else:
                    st.caption(":large_green_circle: Within position limits")
            else:
                st.progress(0.0, text="Position Utilization: N/A")
                st.caption("No open positions or limit not configured")

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render proximity gauges: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Circuit Breaker Details
    # -----------------------------------------------------------------------
    st.subheader("Circuit Breakers")

    try:
        _rs = load_risk_state(_engine)
        _limits = load_risk_limits(_engine)

        _cb_consec_raw = _rs.get("cb_consecutive_losses") or "{}"
        _cb_tripped_raw = _rs.get("cb_breaker_tripped_at") or "{}"
        _cb_threshold = int(_limits.get("cb_consecutive_losses_n") or 0)

        try:
            _cb_consec: dict = (
                json.loads(_cb_consec_raw)
                if isinstance(_cb_consec_raw, str)
                else dict(_cb_consec_raw or {})
            )
        except (json.JSONDecodeError, TypeError):
            _cb_consec = {}

        try:
            _cb_tripped: dict = (
                json.loads(_cb_tripped_raw)
                if isinstance(_cb_tripped_raw, str)
                else dict(_cb_tripped_raw or {})
            )
        except (json.JSONDecodeError, TypeError):
            _cb_tripped = {}

        _tripped_keys = {k for k, v in _cb_tripped.items() if v is not None}

        with st.expander(
            f"Circuit Breaker Details ({len(_tripped_keys)} tripped, threshold: {_cb_threshold} consecutive losses)",
            expanded=bool(_tripped_keys),
        ):
            if not _cb_consec and not _cb_tripped:
                st.info("No circuit breaker data available.")
            else:
                if _tripped_keys:
                    st.markdown("**Tripped Breakers**")
                    for _key in sorted(_tripped_keys):
                        _tripped_ts = _cb_tripped.get(_key, "unknown")
                        st.error(f"- `{_key}` tripped at {_tripped_ts}")
                else:
                    st.success("No circuit breakers currently tripped.")

                if _cb_consec:
                    st.markdown(
                        f"**Consecutive Loss Counts** (threshold: {_cb_threshold})"
                    )
                    for _key, _count in sorted(_cb_consec.items()):
                        _bar = int(float(_count)) if _count is not None else 0
                        _pct = (
                            min(1.0, _bar / _cb_threshold) if _cb_threshold > 0 else 0.0
                        )
                        st.progress(
                            _pct,
                            text=f"`{_key}`: {_bar} / {_cb_threshold} consecutive losses",
                        )

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render circuit breaker details: {exc}")

    st.divider()

    # -----------------------------------------------------------------------
    # Risk Event History (filterable)
    # -----------------------------------------------------------------------
    st.subheader("Risk Event History")

    try:
        _events = load_risk_events(
            _engine,
            days=event_days,
            event_type=event_type_filter,
        )

        if _events.empty:
            st.info(
                f"No risk events in the last {event_days} days"
                + (f" of type '{event_type_filter}'" if event_type_filter else "")
                + "."
            )
        else:
            _event_display_cols = [
                c
                for c in [
                    "event_ts",
                    "event_type",
                    "trigger_source",
                    "reason",
                    "operator",
                    "asset_id",
                    "strategy_id",
                ]
                if c in _events.columns
            ]
            _event_rename = {
                "event_ts": "Time",
                "event_type": "Type",
                "trigger_source": "Source",
                "reason": "Reason",
                "operator": "Operator",
                "asset_id": "Asset ID",
                "strategy_id": "Strategy ID",
            }
            _events_out = _events[_event_display_cols].rename(columns=_event_rename)
            st.dataframe(_events_out, use_container_width=True)

    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load risk events: {exc}")

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
_risk_content(_main_engine, _selected_event_type, _event_days)
