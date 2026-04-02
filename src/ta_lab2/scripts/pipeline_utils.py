"""
Shared pipeline infrastructure for all pipeline orchestration scripts.

Provides:
- ComponentResult dataclass
- TIMEOUT_* constants
- Pipeline run log helpers (_start_pipeline_run, _complete_pipeline_run, etc.)
- Kill switch (_maybe_kill, KILL_SWITCH_FILE)
- Dead-man switch (_check_dead_man, _fire_dead_man_alert)
- Summary printer (print_combined_summary)
- Pipeline completion alert (run_pipeline_completion_alert)
- STAGE_ORDER canonical ordering

Dependency direction (strictly one-way):
    pipeline_utils.py  (imports: stdlib, sqlalchemy, ta_lab2.notifications)
        ^
    run_daily_refresh.py  (imports from pipeline_utils)
        ^
    run_{X}_pipeline.py   (imports from both)

DO NOT import from run_daily_refresh.py here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Timeout tiers (seconds)
# ---------------------------------------------------------------------------
TIMEOUT_BARS = 7200  # 2 hours -- bar builders can be slow for full rebuilds
TIMEOUT_EMAS = 3600  # 1 hour -- EMA refreshers
TIMEOUT_AMAS = 3600  # 1 hour -- AMA refreshers
TIMEOUT_RETURNS_BARS = 1800  # 30 minutes -- bar returns (incremental, per-id SQL LAG)
TIMEOUT_RETURNS_EMA = 1800  # 30 minutes -- EMA returns (incremental, per-key watermark)
TIMEOUT_RETURNS_AMA = 3600  # 1 hour -- AMA returns (incremental, 5 alignment sources)
TIMEOUT_DESC_STATS = 3600  # 1 hour -- asset stats + correlation computation
TIMEOUT_REGIMES = 1800  # 30 minutes -- regime refresher
TIMEOUT_FEATURES = 7200  # 2 hours -- feature refresh for 492 assets at 1D
TIMEOUT_SIGNALS = 1800  # 30 minutes -- signal generation for all types
TIMEOUT_CALIBRATE_STOPS = (
    300  # 5 minutes -- iterates over asset x strategy combos, mostly SQL reads
)
TIMEOUT_PORTFOLIO = 600  # 10 minutes -- portfolio optimizer runs all three methods
TIMEOUT_EXECUTOR = (
    300  # 5 minutes -- daily executor is fast (2 strategies, ~100 assets)
)
TIMEOUT_STATS = 3600  # 1 hour -- stats runners scan large tables
TIMEOUT_EXCHANGE_PRICES = 120  # 2 minutes -- live price fetches from exchanges
TIMEOUT_DRIFT = 600  # 10 minutes -- drift runs replays which involve backtest execution
TIMEOUT_MACRO = 300  # 5 minutes -- small FRED dataset, fast computation
TIMEOUT_MACRO_REGIMES = (
    300  # 5 minutes -- 4-dimension classification over FRED features
)
TIMEOUT_MACRO_ANALYTICS = (
    900  # 15 minutes -- HMM fitting can be slow (10 restarts x 2-3 state models)
)
TIMEOUT_CROSS_ASSET_AGG = (
    600  # 10 minutes -- rolling correlations across all assets + funding z-scores
)
TIMEOUT_MACRO_GATES = 120  # 2 minutes -- gate evaluation against FRED features
TIMEOUT_MACRO_ALERTS = 60  # 1 minute -- transition detection + Telegram send
TIMEOUT_GARCH = 1800  # 30 minutes -- GARCH fitting for 99 assets x 4 models
TIMEOUT_SYNC_FRED = 300  # 5 minutes -- SSH + psql COPY from GCP VM
TIMEOUT_SYNC_HL = 600  # 10 minutes -- SSH + psql COPY from Singapore VM (~3M rows)
TIMEOUT_SYNC_CMC = (
    300  # 5 minutes -- SSH + psql COPY for 7 CMC assets from Singapore VM
)
TIMEOUT_SIGNAL_GATE = 120  # 2 minutes -- signal count queries are fast
TIMEOUT_IC_STALENESS = 300  # 5 minutes -- IC computation for ~10 features x 2 assets
TIMEOUT_PIPELINE_ALERT = 60  # 1 minute -- Telegram send only

# ---------------------------------------------------------------------------
# Canonical pipeline stage ordering
# ---------------------------------------------------------------------------
# Used by --from-stage to skip prior stages.
# New Phase 87 stages: signal_validation_gate, ic_staleness_check, pipeline_alerts.
STAGE_ORDER = [
    "sync_vms",
    "bars",
    "returns_bars",
    "emas",
    "returns_ema",
    "amas",
    "returns_ama",
    "desc_stats",
    "macro_features",
    "macro_regimes",
    "macro_analytics",
    "cross_asset_agg",
    "macro_gates",
    "macro_alerts",
    "regimes",
    "features",
    "garch",
    "signals",
    "signal_validation_gate",  # Phase 87
    "ic_staleness_check",  # Phase 87
    "calibrate_stops",
    "portfolio",
    "executor",
    "drift_monitor",
    "pipeline_alerts",  # Phase 87
    "stats",
]


# ---------------------------------------------------------------------------
# ComponentResult
# ---------------------------------------------------------------------------


@dataclass
class ComponentResult:
    """Result of running a pipeline component (bars, EMAs, signals, etc.)."""

    component: str
    success: bool
    duration_sec: float
    returncode: int
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Kill switch (Phase 107)
# ---------------------------------------------------------------------------

KILL_SWITCH_FILE = Path(__file__).parent.parent.parent.parent / ".pipeline_kill"


def _check_pipeline_kill_switch() -> bool:
    """Return True if kill switch file exists."""
    return KILL_SWITCH_FILE.exists()


def _maybe_kill(
    db_url: str,
    pipeline_run_id: str | None,
    results: list,
    pipeline_start_time: float,
) -> bool:
    """Check kill switch. If triggered, finalize run log and return True."""
    if not _check_pipeline_kill_switch():
        return False
    print("[KILL SWITCH] Pipeline kill file detected -- stopping after this stage")
    if pipeline_run_id:
        stages_completed = [name for name, r in results if r.success]
        total_duration = time.perf_counter() - pipeline_start_time
        _complete_pipeline_run(
            db_url, pipeline_run_id, "killed", stages_completed, total_duration, None
        )
    KILL_SWITCH_FILE.unlink(missing_ok=True)
    return True


# ---------------------------------------------------------------------------
# Pipeline run log helpers (Phase 87 + Phase 112 pipeline_name)
# ---------------------------------------------------------------------------


def _start_pipeline_run(db_url: str, pipeline_name: str = "daily") -> str | None:
    """Insert a pipeline_run_log row with status='running'. Return the UUID run_id.

    Args:
        db_url: Database connection URL.
        pipeline_name: Discriminator for multi-pipeline support (default 'daily').
            Falls back to legacy INSERT without pipeline_name if column doesn't
            exist yet (migration pending scenario).

    Returns:
        UUID run_id string, or None on DB error.
    """
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        engine = create_engine(db_url)
        row = None
        try:
            with engine.begin() as conn:
                row = conn.execute(
                    text(
                        "INSERT INTO pipeline_run_log (status, pipeline_name) "
                        "VALUES ('running', :name) "
                        "RETURNING run_id"
                    ),
                    {"name": pipeline_name},
                ).fetchone()
        except (OperationalError, ProgrammingError):
            # pipeline_name column may not exist yet (migration pending) --
            # fall back to legacy insert
            with engine.begin() as conn:
                row = conn.execute(
                    text(
                        "INSERT INTO pipeline_run_log (status) VALUES ('running') "
                        "RETURNING run_id"
                    )
                ).fetchone()
        engine.dispose()
        return str(row[0]) if row else None
    except (OperationalError, ProgrammingError) as exc:
        print(
            f"[WARN] Could not start pipeline_run_log row (migration pending?): {exc}"
        )
        return None
    except Exception as exc:
        print(f"[WARN] pipeline_run_log insert error: {exc}")
        return None


def _complete_pipeline_run(
    db_url: str,
    run_id: str,
    status: str,
    stages: list[str],
    duration: float,
    error_msg: str | None,
) -> None:
    """Update the pipeline_run_log row with completion details."""
    import json

    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE pipeline_run_log
                    SET completed_at        = now(),
                        status              = :status,
                        stages_completed    = CAST(:stages AS JSONB),
                        total_duration_sec  = :duration,
                        error_message       = :error
                    WHERE run_id = CAST(:run_id AS UUID)
                """),
                {
                    "run_id": run_id,
                    "status": status,
                    "stages": json.dumps(stages),
                    "duration": duration,
                    "error": error_msg,
                },
            )
        engine.dispose()
    except (OperationalError, ProgrammingError) as exc:
        print(f"[WARN] Could not update pipeline_run_log (migration pending?): {exc}")
    except Exception as exc:
        print(f"[WARN] pipeline_run_log update error: {exc}")


def _log_stage_start(db_url: str, run_id: str | None, stage_name: str) -> str | None:
    """Insert pipeline_stage_log row with status='running'. Return stage_log_id UUID."""
    if run_id is None:
        return None
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO pipeline_stage_log (run_id, stage_name, status) "
                    "VALUES (CAST(:run_id AS UUID), :stage, 'running') "
                    "RETURNING stage_log_id"
                ),
                {"run_id": run_id, "stage": stage_name},
            ).fetchone()
        engine.dispose()
        return str(row[0]) if row else None
    except Exception as exc:
        print(f"[WARN] pipeline_stage_log insert failed: {exc}")
        return None


def _log_stage_complete(
    db_url: str,
    stage_log_id: str | None,
    success: bool,
    duration_sec: float,
    error_msg: str | None,
) -> None:
    """Update pipeline_stage_log row with outcome."""
    if stage_log_id is None:
        return
    status = "complete" if success else "failed"
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE pipeline_stage_log
                    SET completed_at   = now(),
                        status         = :status,
                        duration_sec   = :dur,
                        error_message  = :err
                    WHERE stage_log_id = CAST(:id AS UUID)
                """),
                {
                    "status": status,
                    "dur": duration_sec,
                    "err": error_msg,
                    "id": stage_log_id,
                },
            )
        engine.dispose()
    except Exception as exc:
        print(f"[WARN] pipeline_stage_log update failed: {exc}")


# ---------------------------------------------------------------------------
# Dead-man switch
# ---------------------------------------------------------------------------


def _check_dead_man(db_url: str, pipeline_name: str | None = None) -> bool:
    """Return True if yesterday's pipeline run is MISSING (dead-man should fire).

    Returns False when pipeline_run_log has 0 rows (first run) to avoid
    a false-positive alert on initial deployment.

    Args:
        db_url: Database connection URL.
        pipeline_name: When provided, filter to rows with matching pipeline_name.
            Default None = check any pipeline (backward compat with Phase 87 callers).
    """
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        engine = create_engine(db_url)
        with engine.connect() as conn:
            # First, check if table has ANY rows at all
            count_row = conn.execute(
                text("SELECT COUNT(*) FROM pipeline_run_log")
            ).fetchone()
            if count_row and count_row[0] == 0:
                engine.dispose()
                return False  # First ever run -- no false alarm

            # Check if yesterday's run completed
            if pipeline_name is not None:
                row = conn.execute(
                    text("""
                        SELECT 1
                        FROM pipeline_run_log
                        WHERE DATE(completed_at AT TIME ZONE 'UTC')
                              = CURRENT_DATE - INTERVAL '1 day'
                          AND status = 'complete'
                          AND pipeline_name = :name
                        LIMIT 1
                    """),
                    {"name": pipeline_name},
                ).fetchone()
            else:
                row = conn.execute(
                    text("""
                        SELECT 1
                        FROM pipeline_run_log
                        WHERE DATE(completed_at AT TIME ZONE 'UTC')
                              = CURRENT_DATE - INTERVAL '1 day'
                          AND status = 'complete'
                        LIMIT 1
                    """)
                ).fetchone()
        engine.dispose()
        return row is None  # True = no completed run yesterday
    except (OperationalError, ProgrammingError) as exc:
        print(f"[WARN] Could not check pipeline_run_log for dead-man switch: {exc}")
        return False
    except Exception as exc:
        print(f"[WARN] Dead-man switch check error: {exc}")
        return False


def _fire_dead_man_alert(db_url: str) -> None:
    """Send a CRITICAL dead-man switch alert (12h cooldown) via Telegram."""
    _ALERT_TYPE = "dead_man_switch"
    _ALERT_KEY = "daily"
    _COOLDOWN_HOURS = 12

    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        from ta_lab2.notifications import telegram

        engine = create_engine(db_url)

        # Check throttle
        throttled = False
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT 1 FROM pipeline_alert_log
                        WHERE alert_type = :atype
                          AND alert_key = :akey
                          AND sent_at > NOW() - (INTERVAL '1 hour' * :hours)
                          AND throttled = FALSE
                        LIMIT 1
                    """),
                    {
                        "atype": _ALERT_TYPE,
                        "akey": _ALERT_KEY,
                        "hours": _COOLDOWN_HOURS,
                    },
                ).fetchone()
                throttled = row is not None
        except (OperationalError, ProgrammingError):
            pass  # Table may not exist yet

        sent = False
        if not throttled:
            if telegram.is_configured():
                try:
                    sent = telegram.send_alert(
                        "Dead-Man Switch",
                        "Yesterday's pipeline run did not complete! "
                        "Check pipeline_run_log for details.",
                        severity="critical",
                    )
                except Exception as exc:
                    print(f"  [WARN] Dead-man Telegram send failed: {exc}")
            else:
                print("  [WARN] Dead-man switch fired but Telegram not configured")
        else:
            print("  [INFO] Dead-man alert throttled (within 12h cooldown)")

        # Log to pipeline_alert_log
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO pipeline_alert_log
                            (alert_type, alert_key, severity, message_preview, throttled)
                        VALUES (:atype, :akey, 'critical',
                                'Dead-man switch fired: yesterday pipeline incomplete',
                                :throttled)
                    """),
                    {"atype": _ALERT_TYPE, "akey": _ALERT_KEY, "throttled": throttled},
                )
        except (OperationalError, ProgrammingError) as exc:
            print(f"  [WARN] Could not log dead-man alert: {exc}")

        engine.dispose()
        status_msg = (
            "throttled"
            if throttled
            else ("sent" if sent else "skipped (Telegram unconfigured)")
        )
        print(f"  [CRITICAL] Dead-man switch: {status_msg}")

    except Exception as exc:
        print(f"[WARN] Dead-man switch alert error (non-blocking): {exc}")


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def print_combined_summary(results: list[tuple[str, ComponentResult]]) -> bool:
    """Print combined execution summary.

    Args:
        results: List of (component_name, result) tuples.

    Returns:
        True if all components succeeded, False otherwise.
    """
    print(f"\n{'=' * 70}")
    print("DAILY REFRESH SUMMARY")
    print(f"{'=' * 70}")

    total_duration = sum(r.duration_sec for _, r in results)
    successful = [r for _, r in results if r.success]
    failed = [r for _, r in results if not r.success]

    print(f"\nTotal components: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print(f"Total time: {total_duration:.1f}s")

    if successful:
        print("\n[OK] Successful components:")
        for name, r in results:
            if r.success:
                print(f"  - {name}: {r.duration_sec:.1f}s")

    if failed:
        print("\n[FAILED] Failed components:")
        for name, r in results:
            if not r.success:
                error_info = f" ({r.error_message})" if r.error_message else ""
                print(f"  - {name}: {r.duration_sec:.1f}s{error_info}")

    print(f"\n{'=' * 70}")

    if failed:
        print(f"\n[WARNING] {len(failed)} component(s) failed!")
        return False
    else:
        print("\n[OK] All components completed successfully!")
        return True


# ---------------------------------------------------------------------------
# Pipeline completion alert
# ---------------------------------------------------------------------------


def run_pipeline_completion_alert(
    args, db_url: str, results: list[tuple[str, ComponentResult]]
) -> ComponentResult:
    """Send a daily pipeline digest alert via Telegram.

    Non-blocking: alert failures are logged but never stop the pipeline.
    Throttled to one alert per 20 hours via pipeline_alert_log.
    """
    start = time.perf_counter()
    _ALERT_TYPE = "pipeline_complete"
    _ALERT_KEY = "daily"
    _COOLDOWN_HOURS = 20

    # Build digest
    successful = [name for name, r in results if r.success]
    failed_items = [(name, r) for name, r in results if not r.success]
    total_duration = sum(r.duration_sec for _, r in results)
    severity = "info" if not failed_items else "warning"

    lines = [
        f"Pipeline complete: {len(successful)}/{len(results)} stages OK",
        f"Total duration: {total_duration:.0f}s",
    ]
    if failed_items:
        lines.append("Failed stages:")
        for name, r in failed_items:
            err = f" ({r.error_message})" if r.error_message else ""
            lines.append(f"  - {name}{err}")
    message = "\n".join(lines)

    if getattr(args, "dry_run", False):
        print(f"\n[DRY RUN] Would send pipeline completion alert ({severity})")
        duration = time.perf_counter() - start
        return ComponentResult(
            component="pipeline_alerts",
            success=True,
            duration_sec=duration,
            returncode=0,
        )

    try:
        # Lazy import to avoid hard dependency when running dry-run / tests
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        from ta_lab2.notifications import telegram

        engine = create_engine(db_url)

        # Check throttle
        throttled = False
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT 1 FROM pipeline_alert_log
                        WHERE alert_type = :atype
                          AND alert_key = :akey
                          AND sent_at > NOW() - (INTERVAL '1 hour' * :hours)
                          AND throttled = FALSE
                        LIMIT 1
                    """),
                    {
                        "atype": _ALERT_TYPE,
                        "akey": _ALERT_KEY,
                        "hours": _COOLDOWN_HOURS,
                    },
                ).fetchone()
                throttled = row is not None
        except (OperationalError, ProgrammingError):
            pass  # Table may not exist yet -- proceed without throttle check

        sent = False
        if not throttled:
            if telegram.is_configured():
                title = "Daily Pipeline Complete"
                try:
                    sent = telegram.send_alert(title, message, severity=severity)
                except Exception as exc:
                    print(f"  [WARN] Telegram send failed: {exc}")
            else:
                print("  [INFO] Telegram not configured -- skipping completion alert")

        # Log to pipeline_alert_log
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO pipeline_alert_log
                            (alert_type, alert_key, severity, message_preview, throttled)
                        VALUES (:atype, :akey, :sev, :preview, :throttled)
                    """),
                    {
                        "atype": _ALERT_TYPE,
                        "akey": _ALERT_KEY,
                        "sev": severity,
                        "preview": message[:500],
                        "throttled": throttled,
                    },
                )
        except (OperationalError, ProgrammingError) as exc:
            print(f"  [WARN] Could not log to pipeline_alert_log: {exc}")

        engine.dispose()

        status = "throttled" if throttled else ("sent" if sent else "skipped")
        duration = time.perf_counter() - start
        print(f"  Pipeline completion alert: {status} ({duration:.1f}s)")
        return ComponentResult(
            component="pipeline_alerts",
            success=True,
            duration_sec=duration,
            returncode=0,
        )

    except Exception as e:
        duration = time.perf_counter() - start
        print(f"\n[WARN] Pipeline completion alert failed (non-blocking): {e}")
        return ComponentResult(
            component="pipeline_alerts",
            success=True,  # Non-blocking -- always succeeds
            duration_sec=duration,
            returncode=0,
        )
