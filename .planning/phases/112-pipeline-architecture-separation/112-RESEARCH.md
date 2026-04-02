# Phase 112: Pipeline Architecture Separation - Research

**Researched:** 2026-04-01
**Domain:** Python subprocess orchestration, pipeline decomposition, cross-VM sync
**Confidence:** HIGH (all findings from direct source inspection)

---

## Summary

Phase 112 splits `run_daily_refresh.py` (4,717 lines) into 5 standalone pipeline scripts.
The monolith is already fully subprocess-based — every stage calls `subprocess.run()` on a
child script. There is no in-memory state shared between stages. The only in-process state
that crosses stage boundaries is `ids_for_emas` (passed from bars to EMAs/AMAs) and
`signal_gate_blocked` (a boolean that blocks the executor). Both are trivially reproduced in
a new pipeline that owns those stages.

The `pipeline_run_log` / `pipeline_stage_log` infrastructure (Phase 87/107) already exists
and is the correct handoff signal: each pipeline writes `status='complete'` when it finishes,
and the next pipeline in the chain queries for this before starting. The tables currently have
no `pipeline_name` column, so a migration is needed to add that discriminator.

The `sync_hl_from_vm.py` (pull, SSH + psql COPY) is the direct template for
`sync_signals_to_vm` (push). The only mechanical difference is direction: push uses
`COPY table TO STDOUT` on the local DB and `COPY table FROM STDIN` on the remote.

**Primary recommendation:** Extract a shared `pipeline_utils.py` module that re-exports
`ComponentResult`, `_start_pipeline_run`, `_complete_pipeline_run`, `_log_stage_start`,
`_log_stage_complete`, `_maybe_kill`, and all `TIMEOUT_*` constants. Each of the 5 new
pipeline scripts imports from this shared module and delegates all stage execution to the
existing `run_*` functions (which stay in `run_daily_refresh.py` or a new `pipeline_stages.py`
until a cleaner refactor is done in a later phase).

---

## Standard Stack

The project uses no external orchestration framework. The established internal pattern is:

| Component | Location | Purpose |
|-----------|----------|---------|
| `run_daily_refresh.py` | `scripts/` | Monolith — source of all stage functions |
| `refresh_utils.py` | `scripts/` | `parse_ids`, `get_fresh_ids`, `resolve_db_url` |
| `alembic_utils.py` | `scripts/` | `check_migration_status` |
| `pipeline_run_log` | DB table | Per-run audit row, handoff signal |
| `pipeline_stage_log` | DB table | Per-stage timing, FK to run_log |
| `pipeline_alert_log` | DB table | Telegram throttle log |
| `telegram.py` | `notifications/` | `send_alert(title, message, severity)` |
| `sync_hl_from_vm.py` | `scripts/etl/` | SSH + psql COPY pull pattern (template for push) |

**No new external libraries are needed.** The pattern is: subprocess + SQLAlchemy + psql COPY
over SSH. All already installed.

---

## Architecture Patterns

### Current Stage Function Structure

Every stage in `run_daily_refresh.py` follows an identical pattern:

```python
def run_X(args, db_url: str) -> ComponentResult:
    cmd = [sys.executable, "-m", "ta_lab2.scripts.X.do_thing", "--db-url", db_url, ...]
    if args.dry_run: cmd.append("--dry-run")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=TIMEOUT_X)
    duration = ...
    return ComponentResult(component="X", success=result.returncode==0, ...)
```

Stage functions take `args` (the parsed argparse namespace) and `db_url` (string). They return
`ComponentResult(component, success, duration_sec, returncode, error_message)`. This is the
unit of composition.

### In-Memory State That Crosses Stage Boundaries

Only two pieces of in-memory state flow between stages:

1. **`ids_for_emas` / `ids_for_amas`** — Fresh bar IDs after staleness check. In the Data
   pipeline, bars are just run; in the Features pipeline, the EMA/AMA stages replicate the
   staleness filter. When running Features standalone (without having just run bars), the
   pipeline should use `parsed_ids` directly (same as today's `--emas` standalone mode).

2. **`signal_gate_blocked`** — Boolean. Set when `signal_validation_gate` returns rc=2.
   Blocks `executor` stage. In the new architecture, `signal_gate_blocked` exists only within
   the Signals pipeline. The Execution pipeline on the VM does not need this flag — it has its
   own stale-signal guard that skips execution when signals haven't been updated since last run.

**Conclusion:** No inter-pipeline state needs to be carried across the API boundary.
Pipelines communicate only through database tables.

### Recommended Project Structure

```
src/ta_lab2/scripts/
├── run_daily_refresh.py          # Keep as thin backward-compat wrapper (calls all 5)
├── refresh_utils.py              # Existing: parse_ids, resolve_db_url, get_fresh_ids
├── pipeline_utils.py             # NEW: ComponentResult, logging helpers, TIMEOUT consts
├── pipelines/                    # NEW (or reuse existing empty scripts/pipelines/)
│   ├── run_data_pipeline.py      # Data: sync_vms, bars, returns_bars
│   ├── run_features_pipeline.py  # Features: emas, returns_ema, amas, returns_ama,
│   │                             #           desc_stats, macro_*, cross_asset_agg,
│   │                             #           regimes, features, garch
│   ├── run_signals_pipeline.py   # Signals: signals, signal_validation_gate,
│   │                             #          ic_staleness_check, macro_gates, macro_alerts
│   ├── run_execution_pipeline.py # Execution: calibrate_stops, portfolio, executor
│   └── run_monitoring_pipeline.py # Monitoring: drift_monitor, pipeline_alerts, stats
├── etl/
│   ├── sync_hl_from_vm.py        # Existing pull pattern
│   ├── sync_fred_from_vm.py      # Existing pull pattern
│   └── sync_signals_to_vm.py     # NEW: push pattern (inverted direction)
```

Note: `scripts/pipelines/` already exists with an `__init__.py`.
Note: `scripts/pipeline/` also exists (singular) — avoid collision.

### Pattern 1: Shared pipeline_utils.py

Extract from `run_daily_refresh.py` into `pipeline_utils.py`:

- `ComponentResult` dataclass
- All `TIMEOUT_*` constants
- `_start_pipeline_run(db_url)` → returns `run_id: str | None`
- `_complete_pipeline_run(db_url, run_id, status, stages, duration, error_msg)`
- `_log_stage_start(db_url, run_id, stage_name)` → returns `stage_log_id`
- `_log_stage_complete(db_url, stage_log_id, success, duration_sec, error_msg)`
- `_maybe_kill(db_url, run_id, results, start_time)` → bool
- `KILL_SWITCH_FILE` path
- `print_combined_summary(results)`
- `run_pipeline_completion_alert(args, db_url, results)`

Each pipeline script imports these and calls the stage functions (which stay in
`run_daily_refresh.py` for now, imported directly).

### Pattern 2: Pipeline-Specific main() Structure

Each pipeline script follows this template:

```python
# src/ta_lab2/scripts/pipelines/run_data_pipeline.py
from __future__ import annotations
import argparse, sys, time
from ta_lab2.scripts.pipeline_utils import (
    ComponentResult, _start_pipeline_run, _complete_pipeline_run,
    _log_stage_start, _log_stage_complete, _maybe_kill, print_combined_summary,
    run_pipeline_completion_alert, KILL_SWITCH_FILE,
)
from ta_lab2.scripts.run_daily_refresh import (
    run_sync_fred_vm, run_sync_hl_vm, run_sync_cmc_vm,
    run_bar_builders, run_returns_bars,
)
from ta_lab2.scripts.refresh_utils import parse_ids, resolve_db_url
from ta_lab2.scripts.alembic_utils import check_migration_status

PIPELINE_NAME = "data"

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Data pipeline: sync VMs, bars, returns")
    # Shared args: --ids, --db-url, --dry-run, --verbose, --continue-on-error
    # Data-specific: --no-sync-vms, --source, --num-processes
    args = p.parse_args(argv)
    db_url = resolve_db_url(args.db_url)
    pipeline_run_id = _start_pipeline_run(db_url, pipeline_name=PIPELINE_NAME)
    ...
    _complete_pipeline_run(db_url, pipeline_run_id, "complete", ...)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### Pattern 3: Auto-Chain (Data → Features → Signals)

The chain is invoked by triggering Data with a `--chain` flag. On Data completion,
it spawns Features as a subprocess; on Features completion, it spawns Signals; on Signals
completion, it runs `sync_signals_to_vm`.

```python
# In run_data_pipeline.py main(), after _complete_pipeline_run():
if args.chain and all_success:
    print("[CHAIN] Data complete -- launching Features pipeline")
    chain_cmd = [sys.executable, "-m",
                 "ta_lab2.scripts.pipelines.run_features_pipeline",
                 "--chain", "--ids", args.ids, "--db-url", db_url]
    subprocess.run(chain_cmd, check=False)
```

Alternative: The chain logic could live in a thin `run_full_chain.py` wrapper that calls
Data, then Features, then Signals in sequence using subprocess. This is simpler and decouples
the pipelines — each pipeline is unaware of the chain. This is the recommended approach
since it preserves each pipeline as independently invocable.

### Pattern 4: sync_signals_to_vm (Push Direction)

The `sync_hl_from_vm.py` pattern uses `COPY ... TO STDOUT` on the VM and
`COPY ... FROM STDIN` locally. For push (local → VM), the direction inverts:

```python
# Push: local → VM
def _local_copy_to_csv(engine, table: str, where_clause: str = "") -> str:
    """Export local table rows to CSV string."""
    with engine.raw_connection() as conn:
        cur = conn.cursor()
        buf = io.StringIO()
        cur.copy_expert(f"COPY ({select_sql}) TO STDOUT WITH CSV", buf)
        return buf.getvalue()

def _vm_copy_from_stdin(csv_data: str, table: str) -> None:
    """Push CSV data to VM table via SSH psql COPY FROM STDIN."""
    cmd = _ssh_cmd(
        f"PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} "
        f'-c "COPY {table} FROM STDIN WITH CSV"'
    )
    result = subprocess.run(cmd, input=csv_data, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"SSH COPY push failed: {result.stderr}")
```

Tables to push after Signals completes:
- `signals_ema_crossover`, `signals_rsi`, `signals_atr_breakout` (or whatever names exist)
- `portfolio_allocations`
- `dim_executor_config`
- `strategy_parity`
- `risk_overrides`

Each table should use incremental push: export only rows newer than the last-known VM watermark
(query `MAX(ts)` on VM before pushing, same as `sync_hl_from_vm` incremental pattern).

### Pattern 5: Executor Polling Loop on VM

The executor on the VM is an always-on service that polls for fresh signals on its own cadence.
The existing `run_paper_executor.py` is not a polling loop — it runs once and exits. The new
Execution pipeline wraps it in a loop:

```python
# run_execution_pipeline.py (VM mode: --loop)
import time

POLL_INTERVAL_SEC = 300  # 5 minutes (Claude's discretion)

def run_polling_loop(args, db_url: str) -> int:
    """Poll for fresh signals and execute when found."""
    while True:
        last_signal_ts = _get_last_signal_ts(db_url)
        last_exec_ts = _get_last_execution_ts(db_url)
        if last_signal_ts and (last_exec_ts is None or last_signal_ts > last_exec_ts):
            print(f"[EXEC] Fresh signals detected (ts={last_signal_ts}) -- running")
            result = run_paper_executor_stage(args, db_url)
            if not result.success:
                _send_telegram_alert("Executor failed", result.error_message)
        else:
            print(f"[EXEC] No new signals -- sleeping {POLL_INTERVAL_SEC}s")
        time.sleep(POLL_INTERVAL_SEC)
```

The stale-signal guard (`last_signal_ts > last_exec_ts`) prevents re-execution on the same
signals — this is the "existing stale-signal guard" mentioned in the CONTEXT.md.

When running as a systemd service on the VM (Phase 113), the Execution pipeline is invoked
with `--loop`. For local testing or manual one-shot runs, omit `--loop`.

### Pattern 6: Monitoring Pipeline (Timer Mode)

The Monitoring pipeline runs drift_monitor + pipeline_alerts + stats. On the VM it runs on a
timer (every 15-30 minutes). It is a single-shot script; the timer is external (systemd timer
or cron). The recommended interval is 20 minutes (midpoint of the 15-30 minute range).

```python
# run_monitoring_pipeline.py: always-on timer on VM (systemd .timer unit fires it every 20 min)
# The script itself is single-shot, not a loop.
def main(argv=None) -> int:
    # Runs: drift_monitor, pipeline_alerts, stats
    # Non-blocking: failures logged, pipeline continues
    ...
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Inter-pipeline handoff signal | Custom file locks or message queues | `pipeline_run_log.status='complete'` (DB) | Already exists, already queryable |
| Chain trigger | Process daemon / background thread | `subprocess.run()` sequential chain in wrapper | Simpler, debuggable, no daemon process to manage |
| Telegram alerts | New alert system | Existing `telegram.send_alert(title, msg, severity)` | Already handles throttle, degradation, formatting |
| VM SSH transport | Custom SSH library | `subprocess.run(["ssh", ...])` + psql COPY | Matches all existing patterns exactly |
| Stage timing | Custom timer | `time.perf_counter()` + `ComponentResult.duration_sec` | Already in use |
| Kill switch | Signal handling | `.pipeline_kill` file + `_maybe_kill()` | Already implemented in Phase 107 |

---

## Common Pitfalls

### Pitfall 1: pipeline_run_log Has No pipeline_name Column

**What goes wrong:** Multiple pipelines writing to `pipeline_run_log` without a discriminator
means the dead-man switch and dashboard cannot distinguish which pipeline ran.

**Why it happens:** The table was designed for a single monolithic run. Now there are 5.

**How to avoid:** Add a migration that adds `pipeline_name VARCHAR(30)` to both
`pipeline_run_log` and `pipeline_stage_log`. Insert with `pipeline_name = 'data'` etc.
The dead-man check should filter by `pipeline_name = 'data'` (or check all three
Data/Features/Signals as a unit).

**Warning signs:** Dead-man switch fires spuriously because it sees a Monitoring run and
thinks the main pipeline ran.

### Pitfall 2: run_daily_refresh.py Imports Create a Circular Dependency

**What goes wrong:** If `pipeline_utils.py` imports from `run_daily_refresh.py` and
`run_daily_refresh.py` imports from `pipeline_utils.py`, Python raises an ImportError.

**Why it happens:** Naive extraction moves shared functions to `pipeline_utils.py` but the
new pipeline scripts need to import stage functions from `run_daily_refresh.py`.

**How to avoid:** The dependency graph must be one-directional:
```
pipeline_utils.py         (no imports from run_daily_refresh)
    ↑
run_daily_refresh.py      (imports from pipeline_utils)
    ↑
run_{X}_pipeline.py       (imports from both)
```
Keep stage functions in `run_daily_refresh.py` (or a new `pipeline_stages.py`).
`pipeline_utils.py` imports only from stdlib and `ta_lab2.notifications`.

### Pitfall 3: State Scope of ids_for_emas / ids_for_amas

**What goes wrong:** The Features pipeline needs to do the bar freshness check that was
previously in the monolith (to get `ids_for_emas`). If it is omitted, EMAs run on stale IDs.

**Why it happens:** The staleness check logic lives inside the main() block of
`run_daily_refresh.py` (lines 4156-4188), not in `run_ema_refreshers()`.

**How to avoid:** In `run_features_pipeline.py`, reproduce the staleness gate before calling
`run_ema_refreshers`. When `--skip-stale-check` is passed (or `--all` ran Data first), skip
it. The logic is short (calls `get_fresh_ids()` from `refresh_utils.py`).

### Pitfall 4: signal_gate_blocked Does Not Cross Pipeline Boundary

**What goes wrong:** The Signals pipeline blocks execution via `signal_gate_blocked = True`
in the monolith. In the new architecture, the Execution pipeline is on a different machine
(Oracle VM). The boolean cannot cross the SSH boundary.

**Why it happens:** The monolith used an in-memory flag. The Execution pipeline polls the DB.

**How to avoid:** The Signals pipeline does NOT write anything to `pipeline_run_log` that
encodes gate status. Instead, the executor's existing stale-signal guard (`signals_ts > last_exec_ts`)
is the only guard the VM uses. The `signal_validation_gate` anomaly information is in
`signal_anomaly_log` — the executor can query this table before running and skip if any
`blocked=TRUE` rows exist since last execution. OR, simpler: `sync_signals_to_vm` simply does
NOT push new signals when `signal_gate_blocked = True`. The VM executor then sees no new
signals and does nothing. This is the zero-effort solution.

### Pitfall 5: macro_gates Ordering Relative to Features

**What goes wrong:** `macro_gates` and `macro_alerts` are in the Signals pipeline per CONTEXT.md,
but they depend on `macro_features` (which is in Features). This is correct — CONTEXT.md
puts them in Signals because they *evaluate* signals using macro context, not compute features.
But `macro_gates` and `macro_alerts` also need `regimes` and `cross_asset_agg` to have
completed.

**How to avoid:** Trust the CONTEXT.md boundary. All of `macro_features`, `macro_regimes`,
`macro_analytics`, `cross_asset_agg` finish in Features. `macro_gates` (which queries these
tables) runs at the start of Signals, before signal generation. The pipeline_run_log handoff
ensures Features completes before Signals starts.

Note: In `STAGE_ORDER` in run_daily_refresh.py, `macro_gates` and `macro_alerts` are
listed AFTER `cross_asset_agg` and BEFORE `regimes` (line 138-143). This needs correction
in the new pipeline's stage order — the CONTEXT.md boundary is authoritative.

### Pitfall 6: pipeline_run_log status CHECK Constraint Will Reject New pipeline_name

**What goes wrong:** `pipeline_run_log.status` has a CHECK constraint. Adding `pipeline_name`
does not touch status, so this is not a direct issue. However, the migration must be
backward-compatible with the existing monolith running alongside during transition.

**How to avoid:** Make `pipeline_name VARCHAR(30) DEFAULT 'daily'` — the existing monolith
continues to work unchanged. New pipelines set their name explicitly.

---

## Code Examples

### How pipeline_run_log Is Written (from source)

```python
# Source: run_daily_refresh.py lines 3167-3235

def _start_pipeline_run(db_url: str) -> str | None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO pipeline_run_log (status) VALUES ('running') RETURNING run_id"
        )).fetchone()
    return str(row[0]) if row else None

def _complete_pipeline_run(db_url, run_id, status, stages, duration, error_msg):
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE pipeline_run_log
            SET completed_at = now(), status = :status,
                stages_completed = CAST(:stages AS JSONB),
                total_duration_sec = :duration, error_message = :error
            WHERE run_id = CAST(:run_id AS UUID)
        """), {"run_id": run_id, "status": status,
               "stages": json.dumps(stages), "duration": duration, "error": error_msg})
```

After migration, the INSERT becomes:
```python
"INSERT INTO pipeline_run_log (status, pipeline_name) VALUES ('running', :name) RETURNING run_id"
```

### How sync_hl_from_vm.py Pulls (Template for Push)

```python
# Source: sync_hl_from_vm.py lines 76-87

def _vm_copy_to_stdout(copy_sql: str, timeout: int = 300) -> str:
    """Run COPY ... TO STDOUT on VM via SSH. Returns CSV data."""
    cmd = _ssh_cmd(
        f"PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} "
        f'-c "COPY ({copy_sql}) TO STDOUT WITH CSV"'
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"SSH COPY failed: {result.stderr}")
    return result.stdout.strip()
```

For push (local → VM), use `input=csv_data` to feed the local CSV to the remote psql process:
```python
def _local_to_vm_copy(csv_data: str, vm_table: str, timeout: int = 120) -> None:
    cmd = _ssh_cmd(
        f"PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} "
        f'-c "COPY {vm_table} FROM STDIN WITH CSV"'
    )
    result = subprocess.run(cmd, input=csv_data, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"SSH COPY push failed: {result.stderr}")
```

### Stage Logging Pattern (every pipeline stage)

```python
# Source: run_daily_refresh.py (repeated ~25 times in main())

_slid = _log_stage_start(db_url, pipeline_run_id, "bars")
bar_result = run_bar_builders(args, db_url, parsed_ids)
results.append(("bars", bar_result))
_log_stage_complete(db_url, _slid, bar_result.success,
                    bar_result.duration_sec, bar_result.error_message)

if not bar_result.success and not args.continue_on_error:
    return 1
if _maybe_kill(db_url, pipeline_run_id, results, pipeline_start_time):
    return 2
```

### Telegram Alert for Chain Failure

```python
# Pattern from run_pipeline_completion_alert (lines 3036-3163)
# Use existing telegram.send_alert() — no new code needed.

from ta_lab2.notifications import telegram

if not all_success:
    telegram.send_alert(
        title=f"{PIPELINE_NAME.title()} Pipeline FAILED",
        message=f"Chain halted at {PIPELINE_NAME}.\nFailed stages: ...",
        severity="warning"
    )
```

---

## Pipeline-Specific CLI Args

| Pipeline | Stage-specific args (in addition to shared `--ids`, `--db-url`, `--dry-run`, `--verbose`, `--continue-on-error`) |
|----------|-------------------------------------------------------|
| Data | `--no-sync-vms`, `--source {cmc,tvc,hl,all}`, `-n/--num-processes`, `--chain` |
| Features | `--skip-stale-check`, `--staleness-hours`, `-n/--num-processes`, `--no-macro`, `--no-macro-regimes`, `--no-macro-analytics`, `--no-cross-asset-agg`, `--no-garch`, `--chain` |
| Signals | `--no-signal-gate`, `--no-ic-staleness`, `--from-stage` (limited to signal stages) |
| Execution | `--loop` (polling mode), `--poll-interval` (seconds, default 300), `--calibrate-only`, `--portfolio-only` |
| Monitoring | `--paper-start` (for drift), `--no-telegram`, interval is external (systemd timer) |

The `--from-stage` mechanism should be preserved in each pipeline for the stages it owns.
For example, the Features pipeline supports `--from-stage emas` to skip `returns_bars` etc.

---

## Backward Compatibility — run_daily_refresh.py

**Recommendation: keep as thin wrapper, deprecate gradually.**

The wrapper approach:

```python
# run_daily_refresh.py becomes:
def main(argv=None):
    # If --all or combination of stage flags → invoke appropriate pipelines in sequence
    # If single-stage flags (--bars, --emas, etc.) → call run_X directly (unchanged)
    # Print deprecation notice pointing to new scripts
    ...
```

The alternative (full deprecation) risks breaking any external scripts, cron entries, or
documentation that references `run_daily_refresh`. Wrapper costs one sprint and buys a clean
transition. The CONTEXT.md marks this as Claude's discretion.

**Recommended approach:** Keep `run_daily_refresh.py` as-is for now. It imports from
`pipeline_utils.py` (after extraction). The new pipeline scripts are additive. Document both
entry points. Formal deprecation in a future phase once the wrapper is proven stable.

---

## Migration Required

Phase 112 needs one Alembic migration:

```sql
-- Add pipeline_name discriminator to both tables
ALTER TABLE public.pipeline_run_log
    ADD COLUMN IF NOT EXISTS pipeline_name VARCHAR(30) NOT NULL DEFAULT 'daily';

ALTER TABLE public.pipeline_stage_log
    ADD COLUMN IF NOT EXISTS pipeline_name VARCHAR(30);  -- inherits from parent via run_id

-- Add index for per-pipeline dead-man queries
CREATE INDEX IF NOT EXISTS ix_pipeline_run_log_name_ts
    ON public.pipeline_run_log (pipeline_name, completed_at);
```

The `status` CHECK constraint does not need changing — 'complete'/'failed'/'killed' covers
all pipelines.

---

## State of the Art

| Old Approach | Current/New Approach | When Changed | Impact |
|--------------|----------------------|--------------|--------|
| Single `run_daily_refresh.py --all` | 5 separate pipeline scripts | Phase 112 | Local vs VM deployment boundary |
| All stages on local PC | Data+Features+Signals local, Execution+Monitoring on VM | Phase 112/113 | Executor always-on, not dependent on local machine |
| Blocking executor in monolith | Polling loop on VM | Phase 112 | Executor runs independently of daily refresh timing |
| `pipeline_run_log` (no name) | `pipeline_run_log` with `pipeline_name` column | Phase 112 (migration) | Dead-man switch per pipeline |

---

## Open Questions

1. **Where do `macro_gates` and `macro_alerts` go in STAGE_ORDER?**
   - What we know: CONTEXT.md puts them in Signals pipeline. `run_daily_refresh.py` STAGE_ORDER
     places them at lines 138-143, between `cross_asset_agg` and `regimes`.
   - What's unclear: Are they actually run before `regimes` in the monolith? Checking STAGE_ORDER
     confirms: yes, `macro_gates` comes before `regimes` and `features` in the current pipeline.
   - Recommendation: In the new Signals pipeline, `macro_gates` and `macro_alerts` run at the
     START of the pipeline (before `signals` generation) to gate on macro conditions. This matches
     the CONTEXT.md intent: they check if macro conditions allow signal generation.

2. **How does the Execution pipeline know `sync_signals_to_vm` completed?**
   - What we know: `sync_signals_to_vm` is the final step of the auto-chain (after Signals).
   - What's unclear: Does the VM Execution pipeline poll `pipeline_run_log` for a `signals`
     completion row, or does it independently check signal table timestamps?
   - Recommendation: Use signal table timestamps (query `MAX(ts)` from `signals_*` on VM DB
     and compare to last executor run). This is self-contained and doesn't require the VM to
     poll the local DB. The VM never connects to the local PC's DB.

3. **Which DB does the VM executor connect to?**
   - What we know: "VM already has price data: HL candles, CMC, TVC — no price sync needed
     for executor." Sync pushes signals/config to VM after Signals completes.
   - What's unclear: Does the VM have its own PostgreSQL with a copy of the relevant tables,
     or does it connect to the local DB over the internet?
   - Recommendation: The VM has its own PostgreSQL. `sync_signals_to_vm` pushes rows to the
     VM DB. The executor reads from the VM's local DB. (This is how `sync_hl_from_vm` works
     in reverse.) Confirmed by "VM is source of truth for execution data" in CONTEXT.md.

---

## Sources

### Primary (HIGH confidence)

All findings are from direct source inspection:

- `src/ta_lab2/scripts/run_daily_refresh.py` — full read of stage functions, main() logic,
  pipeline_run_log helpers, STAGE_ORDER, signal_gate_blocked state
- `src/ta_lab2/scripts/etl/sync_hl_from_vm.py` — SSH + psql COPY pull pattern
- `alembic/versions/n8o9p0q1r2s3_phase87_pipeline_wiring.py` — pipeline_run_log schema
- `alembic/versions/t4u5v6w7x8y9_phase107_pipeline_stage_log.py` — pipeline_stage_log schema
- `src/ta_lab2/notifications/telegram.py` — send_alert() API
- `.planning/phases/112-pipeline-architecture-separation/112-CONTEXT.md` — all decisions

---

## Metadata

**Confidence breakdown:**
- Current monolith structure: HIGH — read directly from source
- Stage function extraction pattern: HIGH — all functions follow identical template
- pipeline_run_log handoff mechanism: HIGH — from alembic migrations + source code
- sync_signals_to_vm push pattern: HIGH — direct inversion of verified pull pattern
- Executor polling loop design: MEDIUM — pattern is clear but interval (5 min) is discretionary
- Monitoring timer interval (20 min): MEDIUM — discretionary within user-provided range

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable codebase, no external dependencies)
