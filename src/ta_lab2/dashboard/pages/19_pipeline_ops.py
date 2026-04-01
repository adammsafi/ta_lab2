# -*- coding: utf-8 -*-
"""
Pipeline Operations page -- Phase 107 Pipeline Operations Dashboard.

Provides a single operator-facing page to monitor, trigger, and kill daily
refresh pipeline runs without ad-hoc DB queries or terminal access.

Sections:
  1. Active Run Monitor -- auto-refreshes every 90 s via @st.fragment
  2. Operations Panel  -- trigger buttons (outside fragment, no re-trigger flicker)
  3. Run History       -- last 10 runs with expandable per-stage breakdown

NOTE: Do NOT call st.set_page_config() here -- it is called in the main app
entry point (app.py). Calling it again from a page script raises a
StreamlitAPIException.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from ta_lab2.dashboard.db import get_engine
from ta_lab2.dashboard.queries.pipeline_ops import (
    is_pipeline_running,
    load_active_run_stages,
    load_run_history,
    load_stage_details,
)
from ta_lab2.scripts.run_daily_refresh import STAGE_ORDER

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

# pages/ -> dashboard/ -> ta_lab2/ -> scripts/run_daily_refresh.py
SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "run_daily_refresh.py"
)

# pages/ -> dashboard/ -> ta_lab2/ -> src/ -> project_root/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

KILL_SWITCH_FILE = PROJECT_ROOT / ".pipeline_kill"

# ---------------------------------------------------------------------------
# Sub-stage mapping: "sync_vms" slot in STAGE_ORDER maps to these log rows
# ---------------------------------------------------------------------------

SYNC_SUB_STAGES = ["sync_fred_vm", "sync_hl_vm", "sync_cmc_vm"]

# ---------------------------------------------------------------------------
# Windows detached process flag
# ---------------------------------------------------------------------------

_CREATION_FLAGS = subprocess.DETACHED_PROCESS if platform.system() == "Windows" else 0

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.header("Pipeline Operations")
st.caption("Monitor, trigger, and kill the daily refresh pipeline")

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

try:
    engine = get_engine()
except Exception as exc:  # noqa: BLE001
    st.error(f"Database connection failed: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Section 1: Active Run Monitor (auto-refresh every 90 s)
# ---------------------------------------------------------------------------


@st.fragment(run_every=90)
def _active_run_monitor(_engine) -> None:
    """Auto-refreshing active run monitor section."""
    st.subheader("Active Run Monitor")

    try:
        run_info, stages_df = load_active_run_stages(_engine)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load active run data: {exc}")
        return

    if run_info is None:
        st.info("No pipeline run in progress.")
        st.caption("Auto-refreshes every 90 seconds")
        return

    # -----------------------------------------------------------------------
    # Run header KPIs
    # -----------------------------------------------------------------------

    run_id = run_info.get("run_id", "unknown")
    started_at = run_info.get("started_at")

    if hasattr(started_at, "strftime"):
        started_str = started_at.strftime("%Y-%m-%d %H:%M UTC")
    else:
        started_str = str(started_at) if started_at is not None else "N/A"

    # Elapsed time
    if started_at is not None:
        try:
            now_utc = pd.Timestamp.now(tz="UTC")
            if hasattr(started_at, "tzinfo") and started_at.tzinfo is None:
                started_ts = pd.Timestamp(started_at).tz_localize("UTC")
            else:
                started_ts = pd.Timestamp(started_at)
            elapsed_sec = int((now_utc - started_ts).total_seconds())
            elapsed_str = f"{elapsed_sec // 60}m {elapsed_sec % 60}s"
        except Exception:  # noqa: BLE001
            elapsed_str = "N/A"
    else:
        elapsed_str = "N/A"

    col1, col2, col3 = st.columns([2, 1, 1])
    col1.markdown(f"**Run ID**  \n`{run_id}`")
    col2.metric("Started", started_str)
    col3.metric("Elapsed", elapsed_str)

    # -----------------------------------------------------------------------
    # Overall progress bar
    # -----------------------------------------------------------------------

    total_count = len(STAGE_ORDER)

    if not stages_df.empty:
        completed_stages = stages_df[stages_df["status"] == "complete"][
            "stage_name"
        ].tolist()
        # Count sync_vms as complete only when all sub-stages are complete
        sub_stages_in_df = {
            s for s in SYNC_SUB_STAGES if s in stages_df["stage_name"].values
        }
        sync_vms_complete = len(sub_stages_in_df) == len(SYNC_SUB_STAGES) and all(
            stages_df.loc[stages_df["stage_name"] == s, "status"].iloc[0] == "complete"
            for s in SYNC_SUB_STAGES
        )

        # Count canonical STAGE_ORDER stages as complete
        completed_count = 0
        for stage in STAGE_ORDER:
            if stage == "sync_vms":
                if sync_vms_complete:
                    completed_count += 1
            elif stage in completed_stages:
                completed_count += 1

        progress_frac = completed_count / total_count if total_count > 0 else 0.0
        pct = int(progress_frac * 100)

        # ETA: use average duration of completed stages to estimate remaining
        eta_str = ""
        completed_durations = stages_df.loc[
            stages_df["status"] == "complete", "duration_sec"
        ].dropna()
        if len(completed_durations) > 0 and completed_count < total_count:
            avg_sec = float(completed_durations.mean())
            remaining = total_count - completed_count
            eta_sec = int(avg_sec * remaining)
            eta_str = f" — ETA ~{eta_sec // 60}m {eta_sec % 60:02d}s"

        st.progress(
            progress_frac,
            text=f"Pipeline: {completed_count}/{total_count} stages ({pct}%){eta_str}",
        )
    else:
        # No stage rows — pre-instrumentation run or just started
        st.info(
            "Pipeline is running but no stage data available. "
            "This run was started before stage logging was enabled, "
            "or is still initializing."
        )

    # -----------------------------------------------------------------------
    # Per-stage status list
    # -----------------------------------------------------------------------

    # Only show per-stage breakdown if we have stage data
    if stages_df.empty:
        st.caption("Per-stage breakdown will appear on the next instrumented run.")
    else:
        _render_stage_list(stages_df)

    # -----------------------------------------------------------------------
    # Kill button
    # -----------------------------------------------------------------------

    st.divider()
    if st.button("Kill Pipeline", type="secondary", key="kill_btn"):
        try:
            KILL_SWITCH_FILE.touch()
            st.warning(
                f"Kill signal sent. .pipeline_kill created at {KILL_SWITCH_FILE}. "
                "The pipeline will stop after the current stage completes."
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to create kill file: {exc}")

    st.caption("Auto-refreshes every 90 seconds")


# ---------------------------------------------------------------------------
# Helper: per-stage status rendering
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    "complete": ":green_circle:",
    "running": ":orange_circle:",
    "failed": ":red_circle:",
    "pending": ":white_circle:",
}


def _render_stage_list(stages_df: pd.DataFrame) -> None:
    """Render per-stage status list from pipeline_stage_log data."""
    st.markdown("**Stage Status:**")

    for stage in STAGE_ORDER:
        if stage == "sync_vms":
            # Resolve from sub-stages
            sub_rows = stages_df[stages_df["stage_name"].isin(SYNC_SUB_STAGES)]
            if sub_rows.empty:
                icon = _STATUS_ICONS["pending"]
                status_label = "pending"
            else:
                statuses = set(sub_rows["status"].tolist())
                if "failed" in statuses:
                    icon = _STATUS_ICONS["failed"]
                    status_label = "failed"
                elif "running" in statuses:
                    icon = _STATUS_ICONS["running"]
                    status_label = "running"
                elif all(r == "complete" for r in sub_rows["status"].tolist()) and len(
                    sub_rows
                ) == len(SYNC_SUB_STAGES):
                    icon = _STATUS_ICONS["complete"]
                    status_label = "complete"
                else:
                    icon = _STATUS_ICONS["running"]
                    status_label = "running"

            st.markdown(f"{icon} **sync_vms** — {status_label}")

            # Indented sub-stages
            for sub in SYNC_SUB_STAGES:
                sub_match = stages_df[stages_df["stage_name"] == sub]
                if sub_match.empty:
                    sub_icon = _STATUS_ICONS["pending"]
                    sub_status = "pending"
                else:
                    sub_status = sub_match.iloc[0]["status"]
                    sub_icon = _STATUS_ICONS.get(sub_status, _STATUS_ICONS["pending"])
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{sub_icon} {sub} — {sub_status}")

        else:
            stage_match = stages_df[stages_df["stage_name"] == stage]
            if stage_match.empty:
                icon = _STATUS_ICONS["pending"]
                status_label = "pending"
            else:
                status_label = stage_match.iloc[0]["status"]
                icon = _STATUS_ICONS.get(status_label, _STATUS_ICONS["pending"])

            # Show duration if available
            duration_sec = None
            if not stage_match.empty:
                dur = stage_match.iloc[0].get("duration_sec")
                if dur is not None and not pd.isna(dur):
                    duration_sec = float(dur)

            if duration_sec is not None:
                dur_str = f"{int(duration_sec // 60)}m {int(duration_sec % 60)}s"
                st.markdown(f"{icon} **{stage}** — {status_label} ({dur_str})")
            else:
                st.markdown(f"{icon} **{stage}** — {status_label}")


_active_run_monitor(engine)

st.divider()

# ---------------------------------------------------------------------------
# Section 2: Operations Panel (OUTSIDE fragment -- buttons must not re-trigger)
# ---------------------------------------------------------------------------

st.subheader("Operations Panel")


def _launch_pipeline(*extra_args: str) -> subprocess.Popen | None:
    """Launch run_daily_refresh.py as a detached subprocess.

    Returns the Popen object on success, None on failure (error shown in UI).
    """
    cmd = [sys.executable, str(SCRIPT_PATH), *extra_args]
    log_path = str(PROJECT_ROOT / ".pipeline_stdout.log")
    try:
        proc = subprocess.Popen(
            cmd,
            creationflags=_CREATION_FLAGS,
            stdout=open(log_path, "w", encoding="utf-8"),  # noqa: WPS515
            stderr=subprocess.STDOUT,
        )
        return proc
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to launch pipeline: {exc}")
        return None


# --- Full refresh ---
col_full, col_gap = st.columns([1, 3])
with col_full:
    if st.button("Run Full Refresh", type="primary", key="btn_full"):
        try:
            running = is_pipeline_running(engine)
        except Exception:  # noqa: BLE001
            running = False

        if running:
            st.warning(
                "Pipeline already running. Wait for it to finish or kill it first."
            )
        else:
            proc = _launch_pipeline("--all", "--ids", "all")
            if proc is not None:
                st.success(
                    f"Pipeline started (PID {proc.pid}). Check Active Run Monitor above."
                )

# --- Run From Stage ---
st.markdown("**Run From Stage**")
col_sel, col_btn = st.columns([2, 1])
with col_sel:
    selected_stage = st.selectbox(
        "Start from stage",
        options=STAGE_ORDER,
        key="stage_select",
        label_visibility="collapsed",
    )
with col_btn:
    if st.button("Run From Stage", key="btn_from_stage"):
        try:
            running = is_pipeline_running(engine)
        except Exception:  # noqa: BLE001
            running = False

        if running:
            st.warning("Pipeline already running.")
        else:
            proc = _launch_pipeline(
                "--all", "--ids", "all", "--from-stage", selected_stage
            )
            if proc is not None:
                st.success(
                    f"Pipeline started from '{selected_stage}' (PID {proc.pid})."
                )

# --- Quick actions ---
st.markdown("**Quick Actions**")
qa_col1, qa_col2, qa_col3 = st.columns(3)

with qa_col1:
    if st.button("Sync VMs Only", key="btn_sync_vms"):
        try:
            running = is_pipeline_running(engine)
        except Exception:  # noqa: BLE001
            running = False

        if running:
            st.warning("Pipeline already running.")
        else:
            proc = _launch_pipeline("--sync-vms")
            if proc is not None:
                st.success(f"Sync VMs started (PID {proc.pid}).")

with qa_col2:
    if st.button("Bars + EMAs Only", key="btn_bars_emas"):
        try:
            running = is_pipeline_running(engine)
        except Exception:  # noqa: BLE001
            running = False

        if running:
            st.warning("Pipeline already running.")
        else:
            proc = _launch_pipeline("--bars", "--emas", "--ids", "all")
            if proc is not None:
                st.success(f"Bars + EMAs started (PID {proc.pid}).")

with qa_col3:
    if st.button("Signals Only", key="btn_signals"):
        try:
            running = is_pipeline_running(engine)
        except Exception:  # noqa: BLE001
            running = False

        if running:
            st.warning("Pipeline already running.")
        else:
            proc = _launch_pipeline("--signals")
            if proc is not None:
                st.success(f"Signals started (PID {proc.pid}).")

st.divider()

# ---------------------------------------------------------------------------
# Section 3: Run History
# ---------------------------------------------------------------------------

st.subheader("Run History")


def _fmt_duration(sec: float | None) -> str:
    """Format seconds as mm:ss string."""
    if sec is None or pd.isna(sec):
        return "—"
    sec_int = int(sec)
    return f"{sec_int // 60}m {sec_int % 60:02d}s"


def _status_badge(status: str) -> str:
    """Return a colored text badge for pipeline status."""
    badges = {
        "complete": ":green[complete]",
        "failed": ":red[failed]",
        "killed": ":orange[killed]",
    }
    return badges.get(status.lower(), status)


try:
    history_df = load_run_history(engine, limit=10)
except Exception as exc:  # noqa: BLE001
    st.warning(f"Could not load run history: {exc}")
    history_df = pd.DataFrame()

if history_df.empty:
    st.info("No completed pipeline runs recorded yet.")
else:
    # Summary table
    display_df = history_df[
        [
            "started_at",
            "status",
            "total_duration_sec",
            "stage_count",
            "stages_ok",
            "stages_failed",
        ]
    ].copy()
    display_df["duration"] = display_df["total_duration_sec"].apply(_fmt_duration)
    display_df = display_df.drop(columns=["total_duration_sec"])

    # Rename for display
    display_df = display_df.rename(
        columns={
            "started_at": "Started",
            "status": "Status",
            "stage_count": "Stages",
            "stages_ok": "OK",
            "stages_failed": "Failed",
            "duration": "Duration",
        }
    )

    st.dataframe(display_df.reset_index(drop=True), use_container_width=True)

    # Per-run expanders with per-stage breakdown
    st.markdown("**Per-run stage detail:**")
    for _, row in history_df.iterrows():
        run_id = row["run_id"]
        started_at = row["started_at"]
        status = row.get("status", "unknown")
        duration_str = _fmt_duration(row.get("total_duration_sec"))

        if hasattr(started_at, "strftime"):
            run_label = f"{started_at.strftime('%Y-%m-%d %H:%M UTC')} — {_status_badge(status)} — {duration_str}"
        else:
            run_label = f"{run_id[:8]}... — {_status_badge(status)} — {duration_str}"

        with st.expander(run_label):
            try:
                stage_detail_df = load_stage_details(engine, run_id)
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Could not load stage details: {exc}")
                stage_detail_df = pd.DataFrame()

            if stage_detail_df.empty:
                st.info("No stage detail records for this run.")
            else:
                # Format duration column
                stage_detail_df["dur"] = stage_detail_df["duration_sec"].apply(
                    _fmt_duration
                )
                stage_display = stage_detail_df[
                    ["stage_name", "started_at", "status", "dur", "error_message"]
                ].rename(
                    columns={
                        "stage_name": "Stage",
                        "started_at": "Started",
                        "status": "Status",
                        "dur": "Duration",
                        "error_message": "Error",
                    }
                )
                st.dataframe(
                    stage_display.reset_index(drop=True), use_container_width=True
                )
