"""
Cached query functions for Pipeline Operations page.

All functions use @st.cache_data and accept ``_engine`` (underscore-prefixed)
as the first argument so st.cache_data skips hashing the engine.

Active-run queries use ttl=0 (always live) for real-time monitoring.
History queries use ttl=60 (short cache) to avoid stale data.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=0)
def load_active_run_stages(_engine) -> tuple[dict | None, pd.DataFrame]:
    """Return the currently-running pipeline run and its stage rows.

    Returns:
        (run_row_dict, stages_df) where run_row_dict is None if no run is active.
        stages_df has columns: stage_name, started_at, completed_at, status,
        duration_sec, error_message.
    """
    run_sql = text(
        """
        SELECT run_id, started_at, status, error_message
        FROM public.pipeline_run_log
        WHERE status = 'running'
        ORDER BY started_at DESC
        LIMIT 1
        """
    )
    with _engine.connect() as conn:
        run_row = conn.execute(run_sql).fetchone()

    if run_row is None:
        return None, pd.DataFrame(
            columns=[
                "stage_name",
                "started_at",
                "completed_at",
                "status",
                "duration_sec",
                "error_message",
            ]
        )

    run_dict = dict(run_row._mapping)

    stages_sql = text(
        """
        SELECT
            stage_name,
            started_at,
            completed_at,
            status,
            duration_sec,
            error_message
        FROM public.pipeline_stage_log
        WHERE run_id = :run_id
        ORDER BY started_at
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(stages_sql, conn, params={"run_id": run_dict["run_id"]})

    if not df.empty:
        df["started_at"] = pd.to_datetime(df["started_at"], utc=True)
        df["completed_at"] = pd.to_datetime(df["completed_at"], utc=True)

    return run_dict, df


@st.cache_data(ttl=60)
def load_run_history(_engine, limit: int = 10) -> pd.DataFrame:
    """Return recent completed pipeline runs with per-run stage aggregates.

    Columns: run_id, started_at, completed_at, status, total_duration_sec,
    error_message, stage_count, stages_ok, stages_failed.

    Args:
        _engine: SQLAlchemy engine (underscore-prefix skips cache hashing).
        limit: Number of recent runs to return.
    """
    sql = text(
        """
        SELECT
            r.run_id,
            r.started_at,
            r.completed_at,
            r.status,
            EXTRACT(EPOCH FROM (r.completed_at - r.started_at))::FLOAT
                AS total_duration_sec,
            r.error_message,
            COUNT(s.stage_name)                        AS stage_count,
            COUNT(s.stage_name) FILTER (WHERE s.status = 'complete')
                                                       AS stages_ok,
            COUNT(s.stage_name) FILTER (WHERE s.status = 'failed')
                                                       AS stages_failed
        FROM public.pipeline_run_log r
        LEFT JOIN public.pipeline_stage_log s USING (run_id)
        WHERE r.status IN ('complete', 'failed', 'killed')
        GROUP BY r.run_id, r.started_at, r.completed_at, r.status, r.error_message
        ORDER BY r.started_at DESC
        LIMIT :lim
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"lim": limit})

    if not df.empty:
        df["started_at"] = pd.to_datetime(df["started_at"], utc=True)
        df["completed_at"] = pd.to_datetime(df["completed_at"], utc=True)
        df["stage_count"] = df["stage_count"].fillna(0).astype(int)
        df["stages_ok"] = df["stages_ok"].fillna(0).astype(int)
        df["stages_failed"] = df["stages_failed"].fillna(0).astype(int)

    return df


@st.cache_data(ttl=60)
def load_stage_details(_engine, run_id: str) -> pd.DataFrame:
    """Return per-stage timing rows for a specific run.

    Columns: stage_name, started_at, completed_at, status, duration_sec,
    error_message.

    Args:
        _engine: SQLAlchemy engine (underscore-prefix skips cache hashing).
        run_id: The pipeline run UUID to look up.
    """
    sql = text(
        """
        SELECT
            stage_name,
            started_at,
            completed_at,
            status,
            duration_sec,
            error_message
        FROM public.pipeline_stage_log
        WHERE run_id = :run_id
        ORDER BY started_at
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"run_id": run_id})

    if not df.empty:
        df["started_at"] = pd.to_datetime(df["started_at"], utc=True)
        df["completed_at"] = pd.to_datetime(df["completed_at"], utc=True)

    return df


@st.cache_data(ttl=0)
def is_pipeline_running(_engine) -> bool:
    """Return True if a pipeline run is currently active.

    Checks for a run with status='running' started within the last 4 hours
    (guards against stale 'running' rows from crashed processes).

    Args:
        _engine: SQLAlchemy engine (underscore-prefix skips cache hashing).
    """
    sql = text(
        """
        SELECT 1
        FROM public.pipeline_run_log
        WHERE status = 'running'
          AND started_at > NOW() - INTERVAL '4 hours'
        LIMIT 1
        """
    )
    with _engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    return row is not None
