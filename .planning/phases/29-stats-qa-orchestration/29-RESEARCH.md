# Phase 29: Stats/QA Orchestration - Research

**Researched:** 2026-02-22
**Domain:** Pipeline orchestration, subprocess management, Telegram alerting, DB-backed stats tables
**Confidence:** HIGH

## Summary

Phase 29 wires 5 existing stats runners into `run_daily_refresh.py` as the final `--stats` stage, builds a `weekly_digest` script, gates the pipeline on FAIL status, and adds `timeout=` to all existing `subprocess.run()` calls. All source code was read directly — no hypothesis needed.

The pattern is already well-established: `run_daily_refresh.py` uses `ComponentResult` dataclasses, sequential subprocess execution with error capture, and a final summary function. The stats stage replicates this pattern but adds PASS/WARN/FAIL status reading (stats runners exit 0 on WARN or PASS, non-0 on crash) and post-run DB querying to determine aggregate status.

**Key finding:** Stats runners currently do NOT exit with non-zero codes on FAIL — they always exit 0 if the script ran without crashing. The stats status (PASS/WARN/FAIL) lives in the stats tables in the database, not in the subprocess return code. The orchestrator must query the DB after all runners complete to determine the aggregate pipeline gate decision.

**Primary recommendation:** Build `run_stats_runners.py` in a new `src/ta_lab2/scripts/stats/` directory following the exact same pattern as `run_all_audits.py`, then add `run_stats_runners()` to `run_daily_refresh.py` matching the `run_regime_refresher()` function structure. After all runners complete, query the stats tables to determine PASS/WARN/FAIL and send Telegram alerts accordingly.

## Standard Stack

All existing code uses these libraries — no new dependencies needed:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `subprocess` | stdlib | Run stats scripts as isolated processes | Already used throughout |
| `sqlalchemy` | existing | Query stats tables for aggregate status | Project-wide DB layer |
| `argparse` | stdlib | `--stats`, `--weekly-digest` CLI flags | Matches existing pattern |
| `dataclasses` | stdlib | `ComponentResult`, `StatsRunnerResult` | Matches existing pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ta_lab2.notifications.telegram` | internal | Send alerts on FAIL/WARN | Already used in project |
| `time.perf_counter` | stdlib | Duration tracking | Already used throughout |
| `pathlib.Path` | stdlib | Script path resolution | Already used throughout |

**Installation:** No new packages required.

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/scripts/stats/
├── __init__.py              # empty
└── weekly_digest.py         # standalone + invocable from orchestrator

src/ta_lab2/scripts/
├── run_daily_refresh.py     # MODIFIED: add --stats flag + run_stats_runners()
└── ...existing files...
```

### Existing Stats Runners (WRAP, DO NOT REWRITE)

| Runner | Script Module Path | CLI Args | Stats Table | Notes |
|--------|--------------------|----------|-------------|-------|
| bars | `ta_lab2.scripts.bars.stats.refresh_price_bars_stats` | `--full-refresh --db-url --log-level` | `public.price_bars_multi_tf_stats` | No `--ids` arg |
| ema_multi_tf | `ta_lab2.scripts.emas.stats.multi_tf.refresh_ema_multi_tf_stats` | `--full-refresh --db-url --log-level` | `public.ema_multi_tf_stats` | No `--ids` arg |
| ema_cal | `ta_lab2.scripts.emas.stats.multi_tf_cal.refresh_ema_multi_tf_cal_stats` | `--tables ... --full-refresh --db-url --log-level` | `public.ema_multi_tf_cal_stats` | Defaults to both cal_us and cal_iso |
| ema_cal_anchor | `ta_lab2.scripts.emas.stats.multi_tf_cal_anchor.refresh_ema_multi_tf_cal_anchor_stats` | `--tables ... --full-refresh --db-url --log-level` | `public.ema_multi_tf_cal_anchor_stats` | Defaults to both cal_anchor_us and cal_anchor_iso |
| returns_ema | `ta_lab2.scripts.returns.stats.refresh_returns_ema_stats` | `--families all --full-refresh --db-url --log-level` | `public.returns_ema_stats` | Use `--families all` |
| features | `ta_lab2.scripts.features.stats.refresh_cmc_features_stats` | `--full-refresh --db-url --log-level` | `public.cmc_features_stats` | No `--ids` arg |

NOTE: There is also a higher-level EMA stats orchestrator at `ta_lab2.scripts.emas.stats.run_all_stats_refreshes` which runs the 3 EMA stats scripts. The stats wiring can either call this orchestrator (simpler) or call each EMA stats script directly (more granular). Calling the sub-orchestrator is simpler.

### Stats Tables Schema (shared pattern, verified from source)

Every stats table uses the same DDL shape:
```sql
-- Columns present in ALL stats tables:
stat_id     BIGSERIAL PRIMARY KEY
table_name  TEXT NOT NULL           -- identifies which source table
test_name   TEXT NOT NULL           -- identifies which test within that table
asset_id    BIGINT                  -- NULL for global/TF-level tests
tf          TEXT                    -- NULL for global tests
period      INTEGER                 -- NULL unless EMA table (period dimension)
status      TEXT NOT NULL           -- 'PASS', 'WARN', or 'FAIL'
actual      NUMERIC
expected    NUMERIC
extra       JSONB
checked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
```

State tables (watermark pattern):
```sql
-- present for each stats table as <name>_state:
table_name       TEXT PRIMARY KEY
last_ingested_at TIMESTAMPTZ    -- or last_updated_at for features
updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
```

### Stats Tables Inventory
```
public.price_bars_multi_tf_stats       + price_bars_multi_tf_stats_state
public.ema_multi_tf_stats              + ema_multi_tf_stats_state
public.ema_multi_tf_cal_stats          + ema_multi_tf_cal_stats_state
public.ema_multi_tf_cal_anchor_stats   + ema_multi_tf_cal_anchor_stats_state
public.returns_ema_stats               + returns_ema_stats_state
public.cmc_features_stats              + cmc_features_stats_state

-- Also exists (not a stats table, but queryable for weekly digest):
public.audit_results                   -- DDL same shape, used by audit scripts
```

### Pattern 1: Adding --stats to run_daily_refresh.py

The existing pattern in `run_daily_refresh.py` for adding a new component:

```python
# Source: src/ta_lab2/scripts/run_daily_refresh.py (verified)

def run_stats_runners(args, db_url: str) -> ComponentResult:
    """Run stats orchestrator via subprocess."""
    script_dir = Path(__file__).parent / "stats"
    cmd = [sys.executable, str(script_dir / "run_all_stats_runners.py")]

    if args.verbose:
        cmd.append("--verbose")
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")

    # ... same try/except/ComponentResult pattern as run_regime_refresher()
```

In `main()`:
```python
# Add to argparse:
p.add_argument("--stats", action="store_true", help="Run stats runners only")

# Add to run logic:
run_stats = args.stats or args.all

# Wire after regimes:
if run_regimes:
    regime_result = run_regime_refresher(args, db_url, parsed_ids)
    results.append(("regimes", regime_result))
    if not regime_result.success and not args.continue_on_error:
        return 1

if run_stats:
    stats_result = run_stats_runners(args, db_url)
    results.append(("stats", stats_result))
```

### Pattern 2: Stats Runners Orchestrator (new file)

Follow `run_all_audits.py` exactly — it already handles the "run all, collect results, report" pattern. The key difference: after all stats runners exit 0 (meaning no crash), query the DB to determine the actual PASS/WARN/FAIL aggregate:

```python
# Source: pattern from src/ta_lab2/scripts/run_all_audits.py (verified)

ALL_STATS_SCRIPTS = [
    StatsScript(
        name="bars",
        module="ta_lab2.scripts.bars.stats.refresh_price_bars_stats",
        description="Price bars stats",
        extra_args=[],
    ),
    StatsScript(
        name="ema_multi_tf",
        module="ta_lab2.scripts.emas.stats.multi_tf.refresh_ema_multi_tf_stats",
        description="EMA multi-TF stats",
        extra_args=[],
    ),
    StatsScript(
        name="ema_cal",
        module="ta_lab2.scripts.emas.stats.multi_tf_cal.refresh_ema_multi_tf_cal_stats",
        description="EMA calendar stats",
        extra_args=[],
    ),
    StatsScript(
        name="ema_cal_anchor",
        module="ta_lab2.scripts.emas.stats.multi_tf_cal_anchor.refresh_ema_multi_tf_cal_anchor_stats",
        description="EMA calendar anchor stats",
        extra_args=[],
    ),
    StatsScript(
        name="returns_ema",
        module="ta_lab2.scripts.returns.stats.refresh_returns_ema_stats",
        description="Returns EMA stats",
        extra_args=["--families", "all"],
    ),
    StatsScript(
        name="features",
        module="ta_lab2.scripts.features.stats.refresh_cmc_features_stats",
        description="CMC features stats",
        extra_args=[],
    ),
]
```

Call as `-m module` not as script path (all have `if __name__ == "__main__": main()`):
```python
cmd = [sys.executable, "-m", script.module] + script.extra_args
```

### Pattern 3: Post-Run DB Query for Aggregate Status

After all stats runners complete (exit 0), query the stats tables to determine the actual outcome:

```python
# Source: stats table schema verified from all 6 stats scripts

def query_aggregate_status(engine) -> dict:
    """Query all stats tables and return aggregate PASS/WARN/FAIL counts."""
    stats_tables = [
        "public.price_bars_multi_tf_stats",
        "public.ema_multi_tf_stats",
        "public.ema_multi_tf_cal_stats",
        "public.ema_multi_tf_cal_anchor_stats",
        "public.returns_ema_stats",
        "public.cmc_features_stats",
    ]
    # Query: most recent checked_at per table, aggregate status counts
    # Use: SELECT table_name, status, count(*) FROM <table>
    #      WHERE checked_at >= NOW() - INTERVAL '1 hour'   -- latest run only
    #      GROUP BY table_name, status
```

Key design decision: need a time window or a run_id to identify "this run's results" vs prior runs. Since stats tables delete-before-insert for impacted keys (incremental), simply querying for latest checked_at per table is the right approach.

### Pattern 4: Telegram Alerting for FAIL/WARN

```python
# Source: src/ta_lab2/notifications/telegram.py (verified)

from ta_lab2.notifications import telegram

# FAIL: halt-worthy failures
telegram.send_alert(
    title="Stats Pipeline FAILED",
    message="Runners with FAIL status:\n- ema_multi_tf: pk_uniqueness_id_tf_period_ts (142 dupe rows)\n- features: row_count_vs_bars_canonical",
    severity="critical"
)

# WARN: continue but alert
telegram.send_alert(
    title="Stats Pipeline WARN",
    message="Runners with WARN status:\n- bars: max_gap_canonical_vs_tf_days",
    severity="warning"
)
```

The `send_alert()` function uses HTML parse mode with emoji prefix (red/yellow/blue circle). The `send_message()` is the primitive; `send_alert()` formats it. `is_configured()` checks env vars gracefully — always call `is_configured()` before trying to alert, or let the existing graceful degradation handle it.

### Pattern 5: Weekly Digest Query

```python
# Source: stats table schema verified, digest design from CONTEXT.md

# Week-over-week delta: query checked_at ranges
# This week: checked_at >= NOW() - INTERVAL '7 days'
# Last week: checked_at >= NOW() - INTERVAL '14 days' AND checked_at < NOW() - INTERVAL '7 days'

SQL_DIGEST = """
SELECT
    table_name,
    status,
    COUNT(*) AS n_tests,
    COUNT(DISTINCT test_name) AS n_test_types
FROM {stats_table}
WHERE checked_at >= NOW() - INTERVAL '7 days'
GROUP BY table_name, status
ORDER BY table_name, status
"""
```

The digest must query ALL 6 stats tables (each is a separate table, not a unified view) and the `audit_results` table. Telegram has a 4096 character limit per message — a long digest may need splitting or truncation.

### Pattern 6: Subprocess Timeout Addition

The pattern used throughout the codebase for subprocess.run is always either:
```python
# verbose mode (stream output)
result = subprocess.run(cmd, check=False)

# capture mode
result = subprocess.run(cmd, check=False, capture_output=True, text=True)
```

Adding timeout= requires handling `subprocess.TimeoutExpired`:
```python
# Source: Python stdlib docs (verified pattern)

TIMEOUT_SECS = 1800  # 30 minutes for heavy runners

try:
    if verbose:
        result = subprocess.run(cmd, check=False, timeout=TIMEOUT_SECS)
    else:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True,
                                timeout=TIMEOUT_SECS)
except subprocess.TimeoutExpired:
    # Log error, send Telegram alert, continue with other runners
    print(f"[TIMEOUT] Command timed out after {TIMEOUT_SECS}s: {cmd[0]}")
    return ComponentResult(
        component=name,
        success=False,
        duration_sec=TIMEOUT_SECS,
        returncode=-1,
        error_message=f"Timed out after {TIMEOUT_SECS}s",
    )
```

### Anti-Patterns to Avoid

- **Reading FAIL status from exit code only:** Stats runners currently exit 0 even when tests produce FAIL rows. Must query DB for aggregate status.
- **Calling runners in parallel without DB-level isolation:** Each runner deletes-then-inserts for its own table. Running them in parallel is safe, but the coordinator's DB query must happen after all runners finish.
- **Rewriting or replacing stats runners:** The decision is to WRAP only. Do not touch the runner internals.
- **Single subprocess.run call with check=True:** All existing callers use `check=False` and inspect `returncode` manually — this is intentional to allow error reporting.
- **Forgetting TimeoutExpired is a different exception from other subprocess errors:** `subprocess.TimeoutExpired` must be caught separately from general `Exception`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Telegram message sending | Custom HTTP client | `ta_lab2.notifications.telegram.send_alert()` | Already handles auth, error gracefully |
| Stats table querying | New SQLAlchemy models | Direct `text()` queries via existing engine | All stats scripts use raw SQL |
| Stats runner subprocess | New process management | Follow `run_all_audits.py` pattern | Pattern is already proven and consistent |
| DB connection | New connection setup | `get_engine()` + `resolve_db_url()` from `bars.common_snapshot_contract` | Standard project pattern |
| PASS/WARN/FAIL aggregation | Custom logic | SQL: `SELECT status, COUNT(*) FROM table GROUP BY status` | Single SQL query covers it |

## Common Pitfalls

### Pitfall 1: Stats Runner Exit Code vs DB Status

**What goes wrong:** Orchestrator assumes a non-zero exit code means FAIL. But stats runners exit 0 even when they write FAIL rows to the stats table — non-zero only means the script itself crashed (DB connection failed, unhandled exception, etc.).

**Why it happens:** Stats runners write results to DB and exit 0 on successful completion, regardless of whether any tests FAILed. This is by design — the script "succeeded" in running the tests.

**How to avoid:** After all runners exit 0, execute a DB query to aggregate status counts from the stats tables. Only then determine PASS/WARN/FAIL for pipeline gating. Exit code non-zero means "runner crashed" (treat as FAIL regardless of DB state).

**Warning signs:** Planner writing "check returncode for FAIL status" — wrong.

### Pitfall 2: Stats Table Timeout Window for Digest

**What goes wrong:** Weekly digest queries all rows without a time filter, getting every historical stat row, not just recent ones. Aggregation is misleading.

**Why it happens:** Stats tables use incremental delete-then-insert per impacted key. Old rows for un-impacted keys remain. A full aggregate is not "this week's run" — it's all history.

**How to avoid:** Filter by `checked_at >= NOW() - INTERVAL '7 days'` for weekly digest, and `checked_at >= NOW() - INTERVAL '2 hours'` for pipeline gate (post-run status check).

**Warning signs:** Query `SELECT status, count(*) FROM stats_table GROUP BY status` without WHERE clause.

### Pitfall 3: Subprocess Timeout on Windows

**What goes wrong:** On Windows, `subprocess.TimeoutExpired` is raised but the child process may still be running. Windows does not have SIGKILL equivalent for graceful cleanup.

**Why it happens:** Windows process termination is more complex than Unix kill signals.

**How to avoid:** After catching `TimeoutExpired`, call `proc.kill()` (if using `Popen`) or accept that `subprocess.run` with timeout will call `proc.kill()` automatically on timeout. The `subprocess.run()` call does handle killing on timeout — just catch the exception and continue.

**Warning signs:** Leaving zombie processes after timeout.

### Pitfall 4: Telegram 4096 Character Limit

**What goes wrong:** Weekly digest with per-test detail across 6 tables exceeds Telegram's message size limit, causing 400 Bad Request.

**Why it happens:** 6 stats tables x many assets x many tests can be hundreds of rows.

**How to avoid:** Truncate per-table detail to top N issues, or split into multiple messages (top-level summary first, then per-table breakdown as reply). Keep alert messages brief (runner names + counts).

**Warning signs:** Building a message string without checking length.

### Pitfall 5: Missing stats Directory Package

**What goes wrong:** `python -m ta_lab2.scripts.stats.weekly_digest` fails with ModuleNotFoundError.

**Why it happens:** The `stats/` directory needs an `__init__.py` to be a Python package.

**How to avoid:** Create `src/ta_lab2/scripts/stats/__init__.py` (empty file) alongside `weekly_digest.py`.

### Pitfall 6: subprocess.run in Old/Archive Scripts

**What goes wrong:** STAT-04 requires timeout on ALL subprocess.run() calls, but scanning only `scripts/` misses calls in `tools/` and `baseline/`.

**The full inventory of calls needing timeout= (from source scan):**

**In `src/ta_lab2/scripts/` (primary scope):**
1. `run_daily_refresh.py:101` — verbose bars subprocess
2. `run_daily_refresh.py:104` — capture bars subprocess
3. `run_daily_refresh.py:205` — verbose EMA subprocess
4. `run_daily_refresh.py:208` — capture EMA subprocess
5. `run_daily_refresh.py:305` — verbose regime subprocess
6. `run_daily_refresh.py:308` — capture regime subprocess
7. `run_all_audits.py:221` — verbose audit subprocess
8. `run_all_audits.py:224` — capture audit subprocess
9. `bars/run_all_bar_builders.py:237` — verbose bar builder subprocess
10. `bars/run_all_bar_builders.py:241` — capture bar builder subprocess
11. `emas/run_all_ema_refreshes.py:227` — verbose EMA refresher subprocess
12. `emas/run_all_ema_refreshes.py:231` — capture EMA refresher subprocess
13. `emas/stats/run_all_stats_refreshes.py:132` — verbose EMA stats subprocess
14. `emas/stats/run_all_stats_refreshes.py:135` — capture EMA stats subprocess
15. `returns/stats/run_all_returns_stats_refreshes.py:113` — verbose returns stats subprocess
16. `returns/stats/run_all_returns_stats_refreshes.py:115` — capture returns stats subprocess
17. `baseline/capture_baseline.py:361` — verbose bars subprocess
18. `baseline/capture_baseline.py:363` — capture bars subprocess
19. `baseline/capture_baseline.py:450` — verbose EMA subprocess
20. `baseline/capture_baseline.py:452` — capture EMA subprocess
21. `baseline/metadata_tracker.py:170` — git diff --quiet (fast, timeout=30)
22. `setup/ensure_ema_unified_table.py:262` — sync after table creation
23. `figure out.py:57` — one-off script, low priority

**In `src/ta_lab2/tools/` (secondary scope):**
24. `tools/ai_orchestrator/adapters.py:496` — already has context, timeout=60 at line 559
25. `tools/data_tools/memory/generate_memories_from_diffs.py:215`
26. `tools/data_tools/generators/generate_commits_txt.py:91`
27. `tools/data_tools/export/process_new_chatgpt_dump.py:195`
28. `tools/data_tools/export/process_new_chatgpt_dump.py:260`
29. `tools/data_tools/export/process_claude_history.py:40`
30. `tools/data_tools/export/chatgpt_pipeline.py:55`

The `emas/old/run_ema_refresh_examples.py:295` is in the `old/` directory — add timeout but low priority.

### Pitfall 7: Cal/Cal-Anchor Stats Runners Use --tables not --ids

**What goes wrong:** Stats runner invocations pass `--ids` (not an accepted flag) to cal/cal_anchor stats runners.

**Why it happens:** Bars and EMA multi-tf stats runners don't filter by asset ID (they process all impacted keys). Cal runners use `--tables` to specify which EMA table variants to process.

**How to avoid:** Use module-level invocation (`-m module`) with the correct args as documented in the stats runner inventory above.

## Code Examples

### Run Stats Runners as Subprocess (verified pattern)

```python
# Source: run_all_audits.py pattern (verified)

def run_stats_script(
    script: StatsScript,
    db_url: str | None,
    verbose: bool,
    dry_run: bool,
    timeout_sec: int = 3600,
) -> ComponentResult:
    cmd = [sys.executable, "-m", script.module] + script.extra_args
    if db_url:
        cmd.extend(["--db-url", db_url])

    if dry_run:
        return ComponentResult(name=script.name, success=True, duration_sec=0.0, returncode=0)

    start = time.perf_counter()
    try:
        if verbose:
            result = subprocess.run(cmd, check=False, timeout=timeout_sec)
        else:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout_sec)

        duration = time.perf_counter() - start
        success = result.returncode == 0
        return ComponentResult(
            name=script.name,
            success=success,
            duration_sec=duration,
            returncode=result.returncode,
            error_message=f"Exited with code {result.returncode}" if not success else None,
        )
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        return ComponentResult(
            name=script.name,
            success=False,
            duration_sec=duration,
            returncode=-1,
            error_message=f"Timed out after {timeout_sec}s",
        )
    except Exception as e:
        duration = time.perf_counter() - start
        return ComponentResult(
            name=script.name, success=False, duration_sec=duration,
            returncode=-1, error_message=str(e),
        )
```

### Query Aggregate Stats Status After Runners (new pattern)

```python
# Source: stats table schema verified from refresh_price_bars_stats.py and others

def query_stats_status(engine, window_hours: int = 2) -> dict[str, dict]:
    """
    Query all stats tables for PASS/WARN/FAIL counts from the last window_hours.
    Returns: {table_name: {'PASS': N, 'WARN': M, 'FAIL': K}}
    """
    stats_tables = [
        "public.price_bars_multi_tf_stats",
        "public.ema_multi_tf_stats",
        "public.ema_multi_tf_cal_stats",
        "public.ema_multi_tf_cal_anchor_stats",
        "public.returns_ema_stats",
        "public.cmc_features_stats",
    ]

    results = {}
    with engine.connect() as conn:
        for table in stats_tables:
            rows = conn.execute(text(f"""
                SELECT status, COUNT(*) as n
                FROM {table}
                WHERE checked_at >= NOW() - INTERVAL '{window_hours} hours'
                GROUP BY status
            """)).fetchall()
            results[table] = {row[0]: row[1] for row in rows}
    return results
```

### Telegram Alert for Stats Failure (verified API)

```python
# Source: src/ta_lab2/notifications/telegram.py (verified)

from ta_lab2.notifications import telegram

def send_stats_alert(failed_runners: list[str], warn_runners: list[str]) -> None:
    if not telegram.is_configured():
        print("[INFO] Telegram not configured, skipping alert")
        return

    if failed_runners:
        msg = "Stats pipeline FAILED. Runners with FAIL status:\n"
        msg += "\n".join(f"  - {r}" for r in failed_runners)
        telegram.send_alert(
            title="Daily Refresh: Stats FAILED",
            message=msg,
            severity="critical"
        )

    if warn_runners:
        msg = "Stats pipeline WARN. Runners with WARN status:\n"
        msg += "\n".join(f"  - {r}" for r in warn_runners)
        telegram.send_alert(
            title="Daily Refresh: Stats WARN",
            message=msg,
            severity="warning"
        )
```

### Weekly Digest Query (new pattern)

```python
# Source: stats table schema + audit_results schema verified

DIGEST_TABLES = [
    ("bars", "public.price_bars_multi_tf_stats"),
    ("ema_multi_tf", "public.ema_multi_tf_stats"),
    ("ema_cal", "public.ema_multi_tf_cal_stats"),
    ("ema_cal_anchor", "public.ema_multi_tf_cal_anchor_stats"),
    ("returns_ema", "public.returns_ema_stats"),
    ("features", "public.cmc_features_stats"),
    ("audit", "public.audit_results"),
]

def build_weekly_summary(engine) -> str:
    """Build human-readable PASS/WARN/FAIL summary for Telegram."""
    lines = ["Weekly QC Digest\n"]
    total = {"PASS": 0, "WARN": 0, "FAIL": 0}

    for label, table in DIGEST_TABLES:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT status, COUNT(*) as n
                FROM {table}
                WHERE checked_at >= NOW() - INTERVAL '7 days'
                GROUP BY status
            """)).fetchall()
        counts = {r[0]: r[1] for r in rows}
        for s in ("PASS", "WARN", "FAIL"):
            total[s] += counts.get(s, 0)
        n_fail = counts.get("FAIL", 0)
        n_warn = counts.get("WARN", 0)
        n_pass = counts.get("PASS", 0)
        status_icon = "PASS" if n_fail == 0 and n_warn == 0 else ("WARN" if n_fail == 0 else "FAIL")
        lines.append(f"{status_icon} {label}: {n_pass} pass / {n_warn} warn / {n_fail} fail")

    lines.insert(1, f"Overall: {total['PASS']} pass / {total['WARN']} warn / {total['FAIL']} fail\n")
    return "\n".join(lines)
```

### Adding timeout= to Existing subprocess.run Pattern

```python
# Source: existing pattern from run_daily_refresh.py, modified to add timeout

# BEFORE:
result = subprocess.run(cmd, check=False)
result = subprocess.run(cmd, check=False, capture_output=True, text=True)

# AFTER (tiered by operation type):
TIMEOUT_BARS = 7200    # 2h — bar builders can be slow
TIMEOUT_EMAS = 3600    # 1h — EMA refreshers
TIMEOUT_REGIMES = 1800 # 30m — regime refresher
TIMEOUT_STATS = 3600   # 1h — stats runners
TIMEOUT_GIT = 30       # 30s — git commands

try:
    result = subprocess.run(cmd, check=False, timeout=TIMEOUT_BARS)
except subprocess.TimeoutExpired:
    print(f"[TIMEOUT] Timed out after {TIMEOUT_BARS}s")
    # handle...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No stats orchestration | 5 isolated stats runners with no pipeline integration | Phase 27-28 | Need Phase 29 to wire them together |
| No timeout on subprocess | All subprocess.run() calls lack timeout= | Throughout project | Silent hangs possible on Windows |
| No pipeline gating | Pipeline completes regardless of data quality | Pre-Phase 29 | Data consumers get bad data silently |
| No weekly digest | Manual SQL queries to inspect stats | Pre-Phase 29 | No proactive quality visibility |

**Deprecated/outdated:**
- `emas/old/run_ema_refresh_examples.py` — old script in `old/` directory, still has subprocess.run without timeout. Add timeout but treat as low priority.
- `run_refresh_ema_multi_tf_stats_old.py` files in `old/` directories — ignored (not in scope).

## Open Questions

1. **Timeout values — actual runtimes unknown**
   - What we know: Tiered timeouts make more sense than uniform (git diff is 30s, bar builders can be >1h)
   - What's unclear: Actual runtime of each operation on this machine
   - Recommendation: Use conservative high values (2h bars, 1h EMAs, 30m regimes, 1h stats) and refine after observing actual runtimes. Add a comment noting these are initial estimates.

2. **Stats runners: call 3 EMA runners individually or call run_all_stats_refreshes.py?**
   - What we know: `run_all_stats_refreshes.py` exists and orchestrates the 3 EMA stats runners
   - What's unclear: Whether calling the sub-orchestrator or each directly gives better granularity
   - Recommendation: Call each of the 6 runners directly (bars, ema_multi_tf, ema_cal, ema_cal_anchor, returns_ema, features) for maximum granularity in failure reporting. Skip the intermediate orchestrator.

3. **Weekly digest scheduling**
   - What we know: Must be invocable standalone AND via orchestrator flag
   - What's unclear: Whether there's a cron mechanism already in place
   - Recommendation: Implement as standalone script only (no scheduler), add `--weekly-digest` flag to `run_daily_refresh.py`, and document that the caller (cron/manual) determines schedule.

4. **Week-over-week delta implementation**
   - What we know: Stats tables have `checked_at` column, all rows have timestamps
   - What's unclear: The delete-before-insert pattern means old PASS rows for stable keys may not be present if key wasn't re-processed this week
   - Recommendation: For week-over-week delta, compare aggregate counts (total FAIL this week vs last week), not individual row comparisons. Flag if total FAIL count increased.

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/scripts/run_daily_refresh.py` — full file read, ComponentResult pattern, argparse flags, subprocess.run calls
- `src/ta_lab2/scripts/run_all_audits.py` — full file read, AuditScript dataclass, orchestration pattern
- `src/ta_lab2/scripts/bars/stats/refresh_price_bars_stats.py` — full file read, stats table DDL, CLI args, runner function signature
- `src/ta_lab2/scripts/emas/stats/multi_tf/refresh_ema_multi_tf_stats.py` — full file read, stats table DDL, CLI args
- `src/ta_lab2/scripts/emas/stats/multi_tf_cal/refresh_ema_multi_tf_cal_stats.py` — main() read, --tables CLI arg
- `src/ta_lab2/scripts/emas/stats/multi_tf_cal_anchor/refresh_ema_multi_tf_cal_anchor_stats.py` — main() read, --tables CLI arg
- `src/ta_lab2/scripts/returns/stats/refresh_returns_ema_stats.py` — full file read, --families CLI arg, all 6 family configs
- `src/ta_lab2/scripts/features/stats/refresh_cmc_features_stats.py` — full file read, stats table DDL, CLI args
- `src/ta_lab2/scripts/emas/stats/run_all_stats_refreshes.py` — full file read, EMA stats sub-orchestrator
- `src/ta_lab2/scripts/returns/stats/run_all_returns_stats_refreshes.py` — full file read, returns stats sub-orchestrator
- `src/ta_lab2/notifications/telegram.py` — full file read, AlertSeverity enum, send_alert(), send_message(), is_configured()
- `src/ta_lab2/scripts/audit/audit_db.py` — full file read, audit_results table DDL
- `src/ta_lab2/scripts/regimes/regime_stats.py` — full file read (regime_stats is a compute module, not a pipeline stats runner)
- grep scan of all subprocess.run calls across src/ta_lab2/scripts — complete inventory

### Secondary (MEDIUM confidence)
- CONTEXT.md for phase 29 — user decisions confirmed directly
- MEMORY.md — project architecture context

### Tertiary (LOW confidence)
- None — all findings verified from source code

## Metadata

**Confidence breakdown:**
- Stats runner interfaces: HIGH — read every runner's main() directly
- Stats table schemas: HIGH — read DDL from all 6 stats scripts
- subprocess.run inventory: HIGH — grep scan of entire scripts directory
- Telegram API: HIGH — read full telegram.py
- Weekly digest design: MEDIUM — design inferred from schema + CONTEXT.md requirements
- Timeout values: LOW — no runtime profiling data available

**Research date:** 2026-02-22
**Valid until:** 2026-03-22 (stable codebase, 30-day validity)
