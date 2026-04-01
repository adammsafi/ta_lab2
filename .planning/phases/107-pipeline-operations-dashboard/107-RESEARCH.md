# Phase 107: Pipeline Operations Dashboard - Research

**Researched:** 2026-04-01
**Domain:** Streamlit dashboard + PostgreSQL pipeline instrumentation
**Confidence:** HIGH

---

## Summary

Phase 107 adds a pipeline operations page to the existing 14-page Streamlit dashboard. The page
needs four capabilities: real-time stage monitoring with progress bars, run history, trigger/kill
buttons, and a file-based pipeline kill switch. All data comes from a new `pipeline_stage_log`
table written to by `run_daily_refresh.py` as it sequences stages.

The existing codebase already has almost every pattern needed. `pipeline_run_log` (Phase 87)
already tracks whole-run status with a UUID PK. The new `pipeline_stage_log` is a child table
that adds per-stage rows. The dashboard already uses `@st.fragment(run_every=N)` for auto-refresh
(see `7_risk_controls.py`, `9_executor_status.py`). The kill switch pattern in the trading risk
system uses DB state; the pipeline kill switch should use a sentinel file instead (no DB dependency,
simpler signal path, same pattern used elsewhere in Python subprocess orchestration).

Subprocess launching from Streamlit is safe if the process is detached (non-blocking). The
existing `run_daily_refresh.py` is already a self-contained Python module, so it can be launched
with `subprocess.Popen` from a button handler. Windows requires `creationflags=subprocess.DETACHED_PROCESS`
to avoid the child being killed when the Streamlit process closes.

**Primary recommendation:** Instrument `run_daily_refresh.py` by wrapping every stage call with
a thin helper that writes `pipeline_stage_log` rows at start/complete/fail. Do not change any
stage function signatures. The new `19_pipeline_ops.py` page is a new entry in the "Operations"
section of `app.py` with page number 19.

---

## Standard Stack

### Core (already in project)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | current | Dashboard UI | Already used for all 14 pages |
| sqlalchemy | current | DB reads/writes | Project standard, NullPool in dashboard |
| psycopg2 | current | PostgreSQL driver | Project standard |
| alembic | current | Schema migrations | All DB changes go through Alembic |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `subprocess` (stdlib) | - | Launching pipeline from trigger buttons | Popen for non-blocking launch on Windows |
| `pathlib.Path` (stdlib) | - | File-based kill switch sentinel | No extra dependency needed |
| `threading` (stdlib) | - | Storing Popen handle in Streamlit session state | Track if pipeline is already running |

### No New Dependencies

Do not add `streamlit-autorefresh` or similar packages. The project already uses
`@st.fragment(run_every=N)` for auto-refresh, which is the native Streamlit mechanism as of
Streamlit 1.33+. Using it is consistent with `7_risk_controls.py` and `9_executor_status.py`.

**Installation:** No new packages needed.

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
├── dashboard/
│   ├── app.py                          # Add page 19 entry in "Operations"
│   ├── pages/
│   │   └── 19_pipeline_ops.py          # NEW: the ops page
│   └── queries/
│       └── pipeline_ops.py             # NEW: SQL queries for pipeline_stage_log
├── scripts/
│   └── run_daily_refresh.py            # Modify: add stage logging wrapper
alembic/
└── versions/
    └── t4u5v6w7x8y9_phase107_pipeline_stage_log.py  # NEW: migration
```

### Pattern 1: Stage Logging Wrapper in run_daily_refresh.py

**What:** A thin context manager or helper function wraps every `run_XYZ()` call to write
`pipeline_stage_log` rows without changing any stage function.

**When to use:** Every stage call inside `main()` that appends to `results`.

**Example:**
```python
# Source: modeled on _start_pipeline_run / _complete_pipeline_run in run_daily_refresh.py
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
    rows_written: int | None,
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
                        rows_written   = :rows,
                        error_message  = :err
                    WHERE stage_log_id = CAST(:id AS UUID)
                """),
                {"status": status, "dur": duration_sec,
                 "rows": rows_written, "err": error_msg, "id": stage_log_id},
            )
        engine.dispose()
    except Exception as exc:
        print(f"[WARN] pipeline_stage_log update failed: {exc}")
```

Usage in `main()`:
```python
# Before each run_XYZ() call:
stage_log_id = _log_stage_start(db_url, pipeline_run_id, "bars")
bar_result = run_bar_builders(args, db_url, parsed_ids)
results.append(("bars", bar_result))
_log_stage_complete(db_url, stage_log_id, bar_result.success,
                    bar_result.duration_sec, None, bar_result.error_message)
```

### Pattern 2: Streamlit Auto-Refresh via @st.fragment

**What:** Wrap the monitoring section in a fragment that re-runs independently every N seconds.
This is the project standard pattern.

**When to use:** Any section that needs to poll DB without a full page reload.

**Example (from 7_risk_controls.py):**
```python
# Source: src/ta_lab2/dashboard/pages/7_risk_controls.py
AUTO_REFRESH_SECONDS = 90  # Use 90 per DASH-02 requirement

@st.fragment(run_every=AUTO_REFRESH_SECONDS)
def _pipeline_monitor_content(_engine) -> None:
    """Auto-refreshes every AUTO_REFRESH_SECONDS."""
    # ... load and render stage data
    _now_str = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    st.caption(f"Last updated: {_now_str} | Auto-refreshes every {AUTO_REFRESH_SECONDS}s")

_pipeline_monitor_content(get_engine())
```

### Pattern 3: File-Based Pipeline Kill Switch

**What:** A sentinel file at a known path signals the pipeline to stop between stages.
The pipeline checks for the file after each stage completes. The dashboard creates/deletes the file.

**When to use:** Stopping a running pipeline without killing the OS process (allows the current
stage to finish cleanly, no DB corruption).

**Sentinel file location:** `{project_root}/.pipeline_kill`

**In run_daily_refresh.py:**
```python
# Source: project pattern from file-based kill switch pattern
KILL_SWITCH_FILE = Path(__file__).parent.parent.parent.parent / ".pipeline_kill"

def _check_pipeline_kill_switch() -> bool:
    """Return True if kill switch file exists."""
    return KILL_SWITCH_FILE.exists()

# Check after each stage in main():
if _check_pipeline_kill_switch():
    print("[KILL SWITCH] Pipeline kill file detected -- stopping after this stage")
    _complete_pipeline_run(db_url, pipeline_run_id, "killed", stages, None)
    KILL_SWITCH_FILE.unlink(missing_ok=True)
    return 2  # distinct exit code for "killed"
```

**In the dashboard (kill button):**
```python
KILL_SWITCH_FILE = Path(__file__).parent.parent.parent.parent.parent / ".pipeline_kill"

if st.button("Kill Pipeline", type="secondary"):
    KILL_SWITCH_FILE.touch()
    st.warning("Kill signal sent. Pipeline will stop after the current stage completes.")
```

**Clear the file on startup:** `run_daily_refresh.py` should delete the file at the top of
`main()` to avoid stale files from a previous killed run blocking the next scheduled run.

### Pattern 4: Trigger Buttons (Non-Blocking Subprocess.Popen)

**What:** Dashboard button launches `run_daily_refresh.py --all` as a detached subprocess.
Streamlit does not wait for it. The run status is visible via `pipeline_run_log` and
`pipeline_stage_log`.

**Windows requirement:** `creationflags=subprocess.DETACHED_PROCESS` prevents the child from
dying when Streamlit closes.

**Example:**
```python
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "run_daily_refresh.py"

if "pipeline_proc" not in st.session_state:
    st.session_state.pipeline_proc = None

if st.button("Run Full Refresh", type="primary"):
    # Check if already running via pipeline_run_log (status='running')
    if not _is_pipeline_running(engine):
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--all", "--ids", "all"],
            # On Windows: detach so child outlives the Streamlit process
            creationflags=subprocess.DETACHED_PROCESS,
            # Redirect output to a log file for debugging
            stdout=open(".pipeline_stdout.log", "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        st.session_state.pipeline_proc = proc
        st.success(f"Pipeline started (PID {proc.pid}). Monitor below.")
    else:
        st.warning("Pipeline already running.")
```

**CRITICAL:** Do not use `subprocess.run()` (blocking) in a button handler. Use `Popen` only.

**"Run From Stage" button:** Same pattern but adds `--from-stage STAGE` to the command.
Populate the stage selectbox from `STAGE_ORDER` (importable from `run_daily_refresh`).

### Pattern 5: Adding a New Dashboard Page

**What:** Add a `st.Page()` entry in `app.py` under the "Operations" section.

**Page numbering:** Current pages go up to 18. Use 19 for the new page.

**Example (from app.py):**
```python
# Source: src/ta_lab2/dashboard/app.py
# In the "Operations" dict key, add:
st.Page(
    "pages/19_pipeline_ops.py",
    title="Pipeline Ops",
    icon=":material/manage_history:",
),
```

### Anti-Patterns to Avoid

- **Calling `st.set_page_config()` in the page file.** All existing pages omit it; it lives only in `app.py`.
- **Using `@st.cache_data` on queries that need real-time data.** The active run monitor must bypass cache. Use `ttl=0` or no cache decorator for "active run" queries; use `ttl=300` for run history (same as existing `pipeline.py` queries).
- **Blocking `subprocess.run()` in a button handler.** The pipeline takes 1.5+ hours; this would freeze the Streamlit server.
- **Relying on `subprocess.DETACHED_PROCESS` alone for security.** This flag only prevents signal propagation; the launched process inherits the same DB credentials. The dashboard is local-only, so this is acceptable.
- **Writing `rows_written` from the stage log.** `run_daily_refresh.py` does not capture row counts from subprocesses (they run as child processes with captured stdout). Leave `rows_written` NULL initially; future phases can plumb row counts through if needed.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Auto-refresh timer | Custom JS or `streamlit-autorefresh` | `@st.fragment(run_every=N)` | Already used in 7_risk_controls.py, 9_executor_status.py |
| DB engine in page | `create_engine()` inline | `from ta_lab2.dashboard.db import get_engine` | NullPool singleton, same URL resolution |
| Stage name list | Hard-code strings | Import `STAGE_ORDER` from `run_daily_refresh` | Already authoritative, 25 stages |
| Kill switch state check | Re-query DB on every render | Query `pipeline_run_log WHERE status='running'` | Single-row read, fast |
| "Is running" detection | PID file | `pipeline_run_log WHERE status='running' AND started_at > NOW()-'4h'` | DB already has this, PID files are fragile on Windows |

**Key insight:** Nearly everything needed exists. The work is wiring, not building from scratch.

---

## Common Pitfalls

### Pitfall 1: Stale Kill Switch File Blocks Next Scheduled Run

**What goes wrong:** The `.pipeline_kill` file exists from a previous kill, and the next morning's
scheduled run checks for it immediately and exits.
**Why it happens:** The dashboard creates the file, but nobody deletes it after the kill completes.
**How to avoid:** `run_daily_refresh.py` must delete `.pipeline_kill` at the very start of `main()`
(before any stage runs) unconditionally. The dashboard kill button is "create only"; the pipeline
is responsible for cleanup.
**Warning signs:** Pipeline completes instantly with exit code 2 and no stages appear in `pipeline_stage_log`.

### Pitfall 2: Streamlit Fragment Does Not Get Updated Engine

**What goes wrong:** `@st.fragment` captures the engine argument at first render; DB reconnects
fail silently if the engine is stale.
**Why it happens:** `st.cache_resource` returns a singleton; if the engine is disposed externally,
queries fail with `OperationalError`.
**How to avoid:** Pass `_engine` (underscore prefix) to the fragment — this tells Streamlit not
to hash it, and the engine is always the live singleton from `get_engine()`. This is the pattern
in all existing pages.

### Pitfall 3: Concurrent Pipeline Launch from Multiple Browser Sessions

**What goes wrong:** Two users each click "Run Full Refresh" within seconds of each other,
launching two simultaneous pipelines that write to the same tables.
**Why it happens:** `subprocess.Popen` does not check if a pipeline is already running.
**How to avoid:** Before launching, query `pipeline_run_log WHERE status='running' AND
started_at > NOW() - INTERVAL '4 hours'`. If a row exists, show a warning instead of launching.
The 4-hour window ensures a crashed pipeline (which stays `running` forever) doesn't block for
too long.

### Pitfall 4: Windows creationflags Compatibility

**What goes wrong:** Using `subprocess.CREATE_NEW_CONSOLE` instead of `subprocess.DETACHED_PROCESS`
opens a visible console window each time, which is disruptive.
**Why it happens:** Confusion between Windows subprocess creation flags.
**How to avoid:** Use `subprocess.DETACHED_PROCESS` (value `0x00000008`) only. Do not combine
with `subprocess.CREATE_NEW_CONSOLE`. Pass output to a log file via `stdout=open(...)`.

### Pitfall 5: UTF-8 Box-Drawing Characters in SQL

**What goes wrong:** SQL files with box-drawing characters (e.g., from copy-pasted table diagrams)
cause `UnicodeDecodeError` on Windows cp1252.
**Why it happens:** This is a known project gotcha documented in MEMORY.md.
**How to avoid:** The Alembic migration for `pipeline_stage_log` must use ASCII-only comments.
The phase87 migration already has the comment: "All comments use ASCII only (Windows cp1252 compatibility)."

### Pitfall 6: pipeline_stage_log rows for stages that were skipped

**What goes wrong:** The run history panel shows only stages that actually ran, but no indication
of which stages were skipped (e.g., due to `--from-stage` or `--no-features`).
**Why it happens:** Skipped stages never get a `pipeline_stage_log` row.
**How to avoid:** This is acceptable behavior for MVP. Do not log skipped stages; the run history
already captures `stages_completed` as a JSONB list in `pipeline_run_log` which shows what ran.
Skipped stages are simply absent.

---

## Code Examples

### pipeline_stage_log Table Schema (Alembic migration body)

```sql
-- Source: modeled on pipeline_run_log in n8o9p0q1r2s3_phase87_pipeline_wiring.py
CREATE TABLE IF NOT EXISTS public.pipeline_stage_log (
    stage_log_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID        NOT NULL REFERENCES public.pipeline_run_log(run_id)
                                    ON DELETE CASCADE,
    stage_name      VARCHAR(50) NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    status          VARCHAR(20) NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'complete', 'failed', 'killed')),
    duration_sec    NUMERIC,
    rows_written    INTEGER,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS ix_pipeline_stage_log_run_id
    ON public.pipeline_stage_log (run_id, started_at);
```

**PK:** `stage_log_id` UUID (consistent with project pattern: `run_id` in `pipeline_run_log`,
`check_id` in `signal_anomaly_log`, `alert_id` in `pipeline_alert_log`).

**FK:** `run_id` references `pipeline_run_log(run_id)` with `ON DELETE CASCADE` so stage rows
are cleaned up when run rows are purged.

**No `venue_id`:** This is an operational/audit table, not a data table. The project convention
for `venue_id` applies to data tables (price_bars, ema, ama families); operational tables like
`pipeline_run_log`, `risk_events`, `executor_run_log` do not have it.

### Dashboard Query: Active Run with Stage Progress

```python
# Source: pattern from ta_lab2/dashboard/queries/pipeline.py (st.cache_data with ttl)

@st.cache_data(ttl=0)  # No cache for active run -- must be real-time
def load_active_run_stages(_engine) -> tuple[dict | None, pd.DataFrame]:
    """Return (run_row, stages_df) for the most recent running pipeline.

    run_row keys: run_id, started_at, status
    stages_df columns: stage_name, started_at, completed_at, status, duration_sec, error_message
    """
    with _engine.connect() as conn:
        run_row = conn.execute(text("""
            SELECT run_id, started_at, status
            FROM pipeline_run_log
            WHERE status = 'running'
            ORDER BY started_at DESC
            LIMIT 1
        """)).fetchone()

    if run_row is None:
        return None, pd.DataFrame()

    run_id = run_row[0]
    with _engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT stage_name, started_at, completed_at, status,
                   duration_sec, error_message
            FROM pipeline_stage_log
            WHERE run_id = CAST(:run_id AS UUID)
            ORDER BY started_at
        """), conn, params={"run_id": str(run_id)})

    return dict(run_row._mapping), df


@st.cache_data(ttl=60)  # Short cache for history
def load_run_history(_engine, limit: int = 10) -> pd.DataFrame:
    """Return last N completed runs with per-stage timing breakdown."""
    with _engine.connect() as conn:
        return pd.read_sql(text("""
            SELECT
                r.run_id,
                r.started_at,
                r.completed_at,
                r.status,
                r.total_duration_sec,
                r.error_message,
                COUNT(s.stage_log_id)                   AS stage_count,
                SUM(CASE WHEN s.status = 'complete' THEN 1 ELSE 0 END) AS stages_ok,
                SUM(CASE WHEN s.status = 'failed'   THEN 1 ELSE 0 END) AS stages_failed
            FROM pipeline_run_log r
            LEFT JOIN pipeline_stage_log s ON s.run_id = r.run_id
            WHERE r.status IN ('complete', 'failed', 'killed')
            GROUP BY r.run_id, r.started_at, r.completed_at, r.status,
                     r.total_duration_sec, r.error_message
            ORDER BY r.started_at DESC
            LIMIT :lim
        """), conn, params={"lim": limit})
```

### Dashboard: Progress Bar Rendering (Active Monitor)

```python
# Source: pattern from 7_risk_controls.py progress bars
from ta_lab2.scripts.run_daily_refresh import STAGE_ORDER

def _render_active_run(run_row: dict, stages_df: pd.DataFrame) -> None:
    stage_statuses = {}
    if not stages_df.empty:
        for _, row in stages_df.iterrows():
            stage_statuses[row["stage_name"]] = row["status"]

    completed = sum(1 for s in STAGE_ORDER if stage_statuses.get(s) == "complete")
    total = len(STAGE_ORDER)
    progress_val = completed / total if total > 0 else 0.0

    st.progress(progress_val, text=f"Pipeline: {completed}/{total} stages complete")

    for stage in STAGE_ORDER:
        status = stage_statuses.get(stage, "pending")
        if status == "complete":
            icon = ":large_green_circle:"
        elif status == "running":
            icon = ":large_orange_circle:"
        elif status == "failed":
            icon = ":red_circle:"
        else:
            icon = ":white_circle:"
        st.caption(f"{icon} {stage}")
```

---

## Existing Infrastructure to Reuse

### pipeline_run_log (Phase 87 - already exists)

The `pipeline_run_log` table already exists with these columns:
- `run_id` UUID PK
- `started_at` TIMESTAMPTZ
- `completed_at` TIMESTAMPTZ
- `status` VARCHAR(20) CHECK IN ('running', 'complete', 'failed')
- `stages_completed` JSONB (list of stage names that ran)
- `total_duration_sec` NUMERIC
- `error_message` TEXT

`pipeline_stage_log` is a child table of this. No change to `pipeline_run_log` schema needed.
The `status` CHECK constraint needs `'killed'` added for kill-switch terminations (or just use
`'failed'` for simplicity — acceptable since killed runs are abnormal).

### _start_pipeline_run / _complete_pipeline_run helpers (already exist)

Lines 3167-3235 of `run_daily_refresh.py`. These helpers already pattern what stage logging
should look like. Copy the pattern directly.

### STAGE_ORDER constant (already exists)

Line 126 of `run_daily_refresh.py`. This list of 25 stage names is the authoritative ordering.
Import it in the dashboard page to build the progress bar and the "Run From Stage" selectbox.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `st.experimental_rerun()` loop | `@st.fragment(run_every=N)` | Streamlit 1.33 (2024) | Fragment re-runs only its section, not the whole page — no flicker |
| `streamlit-autorefresh` package | `@st.fragment(run_every=N)` | Streamlit 1.33 | No extra dependency needed |
| `subprocess.CREATE_NEW_CONSOLE` | `subprocess.DETACHED_PROCESS` | Always | Avoids visible console window on Windows |

**Deprecated/outdated:**
- `st.experimental_rerun()`: Replaced by `st.rerun()` (stable) and `@st.fragment(run_every=N)` for polling.

---

## Open Questions

1. **`rows_written` plumbing**
   - What we know: `run_daily_refresh.py` does not receive row counts from child subprocesses (they run with captured stdout and no structured output protocol).
   - What's unclear: Whether worth parsing stdout for "N rows written" patterns.
   - Recommendation: Leave `rows_written` NULL for now. It is a nullable column; the dashboard should hide it when NULL rather than show 0.

2. **Kill switch for pipeline vs trading kill switch**
   - What we know: The trading kill switch lives in `dim_risk_state` (DB-based). The pipeline kill switch should be file-based (no DB dependency during a DB-heavy pipeline run).
   - What's unclear: Whether the file path should be configurable.
   - Recommendation: Hard-code to `{project_root}/.pipeline_kill` (a dotfile, gitignored). Document it in CLAUDE.md.

3. **`pipeline_run_log.status` CHECK constraint for 'killed'**
   - What we know: Current CHECK allows only `('running', 'complete', 'failed')`.
   - What's unclear: Whether to add `'killed'` or map killed runs to `'failed'`.
   - Recommendation: Add `'killed'` to the CHECK constraint in the Alembic migration. A killed run is distinct from a failed run — it stopped intentionally, not due to an error.

---

## Sources

### Primary (HIGH confidence)

- Direct code reading: `src/ta_lab2/scripts/run_daily_refresh.py` — full stage list (STAGE_ORDER, 25 stages), pipeline_run_log helpers, subprocess patterns
- Direct code reading: `src/ta_lab2/dashboard/app.py` — page registration pattern, page numbering (1-18 existing)
- Direct code reading: `src/ta_lab2/dashboard/pages/7_risk_controls.py` — `@st.fragment(run_every=N)` pattern
- Direct code reading: `src/ta_lab2/dashboard/pages/9_executor_status.py` — `@st.fragment` pattern, sidebar controls outside fragment
- Direct code reading: `src/ta_lab2/dashboard/pages/2_pipeline_monitor.py` — existing pipeline monitor structure
- Direct code reading: `src/ta_lab2/dashboard/queries/pipeline.py` — `@st.cache_data(ttl=300)`, underscore-prefix engine convention
- Direct code reading: `src/ta_lab2/dashboard/db.py` — `get_engine()` NullPool singleton
- Direct code reading: `src/ta_lab2/risk/kill_switch.py` — DB-based kill switch pattern (contrast with file-based approach needed here)
- Direct code reading: `alembic/versions/n8o9p0q1r2s3_phase87_pipeline_wiring.py` — `pipeline_run_log` schema, ASCII-only comments convention

### Secondary (MEDIUM confidence)

- Streamlit docs (training knowledge, consistent with code observed): `@st.fragment(run_every=N)` stable since Streamlit 1.33
- Python docs (stdlib): `subprocess.DETACHED_PROCESS` = `0x00000008`, Windows-specific flag

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all from direct code reading of existing files
- Architecture: HIGH — all patterns directly observed in existing pages
- Pitfalls: HIGH — most derived from MEMORY.md known gotchas + direct code reading
- `rows_written` gap: LOW — cannot determine without running the pipeline

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable codebase, no fast-moving external dependencies)
