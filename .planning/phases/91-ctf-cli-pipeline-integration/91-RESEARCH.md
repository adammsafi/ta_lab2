# Phase 91: CTF CLI & Pipeline Integration - Research

**Researched:** 2026-03-23
**Domain:** Python CLI scripting, multiprocessing, watermark-based incremental refresh, Alembic migrations
**Confidence:** HIGH

## Summary

Phase 91 wires the Phase 90 CTF engine (already complete in `src/ta_lab2/features/cross_timeframe.py`) into a standalone CLI refresh script and into the `run_all_feature_refreshes.py` pipeline as Phase 1b. All research was conducted against the live codebase. No external library research was required -- this phase reuses established project patterns.

The project has three well-documented multiprocessing patterns: (1) `multiprocessing.Pool` with `maxtasksperchild=1` and NullPool engines (bakeoff, AMA refreshers), (2) `pool.imap_unordered` for streaming progress (IC sweep), and (3) `ProcessPoolExecutor` with `max_tasks_per_child=1` (run_all_feature_refreshes.py TF workers). All use the identical NullPool-per-worker rule. The CTF script should use pattern (1) or (2) since the work units are per-asset (not per-TF).

The existing `feature_state` table (PK: `id, feature_type, feature_name, venue_id`) is the established state tracking mechanism, but it lacks the `base_tf` and `ref_tf` dimensions CTF needs. A dedicated `ctf_state` table via a new Alembic migration is the correct approach -- consistent with how AMA has its own `ama_multi_tf_state` table separate from `feature_state`.

**Primary recommendation:** Use `multiprocessing.Pool.imap_unordered` with `maxtasksperchild=1` and NullPool per worker, parallelizing by asset (one task per `id`), with a progress counter printed every N completions. tqdm is installed (v4.67.1) but has no existing imports in `src/` -- use manual logger-based progress (matching IC sweep pattern) unless user explicitly asked for tqdm bars.

## Standard Stack

### Core (all already installed, no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `multiprocessing.Pool` | stdlib | Per-asset parallel workers | Project standard for data-intensive parallel tasks |
| `sqlalchemy.pool.NullPool` | 2.0+ | Worker engine pool class | Prevents "too many clients" in forked processes |
| `argparse` | stdlib | CLI argument parsing | All feature refresh scripts use it |
| `logging` | stdlib | Structured logs | All scripts use standard Python logging |
| `pyyaml` | installed | YAML config reading | CTFFeature._load_ctf_config already uses it |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tqdm` | 4.67.1 | Progress bars | Installed but not used in src/. Use manual logger progress (IC sweep pattern) for consistency |
| `concurrent.futures.ProcessPoolExecutor` | stdlib | Alternative pool | Used only in run_all_feature_refreshes.py for TF-level parallelism; CTF workers should use `multiprocessing.Pool` |
| `time` | stdlib | Duration measurement | For per-indicator timing logs |

## Architecture Patterns

### Recommended Project Structure for refresh_ctf.py
```
src/ta_lab2/scripts/features/refresh_ctf.py  # New file
```

### Pattern 1: Module-Level Worker Function (REQUIRED for pickling)

**What:** Worker function must be module-level, not a method. CTFFeature is instantiated inside the worker from `db_url + task params`.

**When to use:** Whenever `multiprocessing.Pool.map/imap_unordered` is used.

**Example (from base_ama_refresher.py):**
```python
# Source: src/ta_lab2/scripts/amas/base_ama_refresher.py lines 100-120

def _ctf_worker(task: CTFWorkerTask) -> dict:
    """Module-level worker -- must be picklable."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from ta_lab2.features.cross_timeframe import CTFFeature, CTFConfig

    engine = create_engine(task.db_url, poolclass=NullPool)
    try:
        config = CTFConfig(
            alignment_source=task.alignment_source,
            venue_id=task.venue_id,
        )
        feature = CTFFeature(config=config, engine=engine)
        rows = feature.compute_for_ids(ids=[task.asset_id])
        return {"asset_id": task.asset_id, "rows": rows, "error": None}
    except Exception as exc:
        return {"asset_id": task.asset_id, "rows": 0, "error": str(exc)}
    finally:
        engine.dispose()
```

### Pattern 2: imap_unordered with Progress Counter

**What:** Stream results as workers complete, log progress every N tasks.

**When to use:** When tasks are variable duration and you want responsive progress feedback.

**Example (from run_ic_sweep.py lines 645-663):**
```python
# Source: src/ta_lab2/scripts/analysis/run_ic_sweep.py

total_written = 0
n_done = 0
n_errors = 0

with Pool(processes=n_workers, maxtasksperchild=1) as p:
    for result in p.imap_unordered(_ctf_worker, tasks):
        n_done += 1
        total_written += result["rows"]
        if result["error"]:
            n_errors += 1
            logger.warning("asset_id=%d failed: %s", result["asset_id"], result["error"])

        if n_done % 10 == 0 or n_done == len(tasks):
            logger.info(
                "CTF progress: %d/%d done, %d rows written, %d errors",
                n_done, len(tasks), total_written, n_errors,
            )
```

### Pattern 3: Auto-Detect Worker Count

**What:** Default workers = `min(6, cpu_count())`. Used by base_ama_refresher.py.

**Example:**
```python
# Source: src/ta_lab2/scripts/amas/base_ama_refresher.py

from multiprocessing import Pool, cpu_count

def _default_workers() -> int:
    return min(6, cpu_count())

parser.add_argument(
    "--workers",
    type=int,
    default=None,
    help="Parallel worker processes. Default: min(6, cpu_count()).",
)
# In main: effective_workers = args.workers or _default_workers()
```

### Pattern 4: run_all_feature_refreshes.py Phase Structure

**What:** The pipeline has numbered phases. Phase 1 = vol/ta/cycle_stats/rolling_extremes (parallel). Phase 2 = features store. Phase 2b = microstructure. Phase 3 = CS norms.

**Phase 1b placement decision:** CTF depends on `ta`, `vol`, `returns_bars_multi_tf_u`, and `features` source tables. `features` is written by Phase 2. Therefore:
- CTF CANNOT run in Phase 1 (before features is populated).
- CTF should run as Phase 2c: after Phase 2b (microstructure), before Phase 3 (CS norms).
- CTF is independent of CS norms -- Phase 3 can proceed regardless of CTF result.

**Phase 2c placement pattern:**
```python
# After microstructure (Phase 2b), before CS norms (Phase 3)

logger.info("Phase 2c: Running CTF features (cross-timeframe)")
ctf_result = refresh_ctf_step(engine, ids=ids, tf=tf)
results[ctf_result.table] = ctf_result

if ctf_result.success:
    logger.info(f"  {ctf_result.table} (tf={tf}): {ctf_result.rows_inserted} rows"
                f" in {ctf_result.duration_seconds:.1f}s")
else:
    logger.warning(f"  {ctf_result.table} (tf={tf}): FAILED - {ctf_result.error}")
    # Non-fatal: log warning, continue to Phase 3
```

### Pattern 5: CLI ID Loading (run_all_feature_refreshes.py)

**What:** `--ids` takes space-separated integers (argparse nargs='+') or comma-separated (existing scripts). The orchestrator uses comma-separated via `add_mutually_exclusive_group(required=True)`.

**Current exact pattern from existing refresh scripts:**
```python
# Source: src/ta_lab2/scripts/features/run_all_feature_refreshes.py

id_group = parser.add_mutually_exclusive_group(required=True)
id_group.add_argument("--ids", help="Comma-separated IDs (e.g., '1,52,1027')")
id_group.add_argument("--all", action="store_true", help="Process all IDs")
```

**For refresh_ctf.py specifically** (matching refresh_ta_daily.py and refresh_vol_daily.py pattern):
```python
id_group.add_argument("--ids", type=str, help="Comma-separated IDs (e.g., '1,52,1027')")
```

### Anti-Patterns to Avoid
- **Method-level worker function:** Cannot be pickled for multiprocessing. Always module-level.
- **Creating engine outside worker:** Forked processes inherit parent connections. Create engine inside worker with NullPool.
- **Passing engine/connection to worker:** Not picklable. Pass `db_url: str` instead.
- **CTFFeature._yaml_config caching across workers:** Each worker creates its own CTFFeature instance -- caching is per-instance, safe.
- **Using CREATE TABLE IF NOT EXISTS for state table:** Project convention is Alembic migrations. The CONTEXT.md explicitly requires this.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Watermark comparison | Custom SQL | Pattern from `_should_skip_tf()` in run_all_feature_refreshes.py | Already solved: compare `MAX(ingested_at)` from source vs `MAX(last_ts)` from state table |
| Worker pool | Custom thread pool | `multiprocessing.Pool` with `maxtasksperchild=1` | Handles memory leaks on Windows, established project convention |
| DB connection in workers | Pooled engine | `NullPool` engine created inside worker | Prevents `too many clients already` PostgreSQL errors |
| Auto worker count | Manual CPU check | `min(6, cpu_count())` from base_ama_refresher.py | Established pattern, prevents overloading |
| State table DDL | `CREATE TABLE IF NOT EXISTS` | Alembic migration | Project convention, CONTEXT.md decision |

**Key insight:** The CTF state problem is fundamentally like the AMA state problem (multi-dimensional watermark), not the simpler `feature_state` pattern (which tracks only id/feature_type/feature_name). Use a dedicated table.

## Common Pitfalls

### Pitfall 1: CTF Dependencies Require Phase 2c Not Phase 1b
**What goes wrong:** Placing CTF before features is materialized means `features` source table has stale data.
**Why it happens:** CTF reads from `features` table (close_fracdiff, sadf_stat). Phase 2 writes features.
**How to avoid:** Place CTF as Phase 2c -- after Phase 2b (microstructure), before Phase 3 (CS norms).
**Warning signs:** CTF rows for `features`-sourced indicators have timestamps lagging by 1 run cycle.

### Pitfall 2: tqdm Not in pyproject.toml Core Dependencies
**What goes wrong:** `import tqdm` works in dev venv but fails in CI or fresh installs.
**Why it happens:** tqdm v4.67.1 is installed in `.venv311` but not listed in `pyproject.toml` dependencies.
**How to avoid:** Either add `tqdm` to `pyproject.toml` dependencies, or use logger-based progress (IC sweep pattern) which needs no new dependency. The safer choice is logger-based progress.
**Warning signs:** `ModuleNotFoundError: No module named 'tqdm'` in CI.

### Pitfall 3: CTF State Granularity Must Cover base_tf/ref_tf
**What goes wrong:** Using existing `feature_state` (PK: id, feature_type, feature_name, venue_id) loses the TF-pair dimension.
**Why it happens:** CTF has distinct watermarks per (id, base_tf, ref_tf, indicator_id) -- same asset may be fully up-to-date for 1D->7D but stale for 1D->30D.
**How to avoid:** New `ctf_state` table with PK: `(id, venue_id, base_tf, ref_tf, indicator_id, alignment_source)`. State columns: `last_ts TIMESTAMPTZ, row_count INTEGER, updated_at TIMESTAMPTZ`.
**Warning signs:** Incremental refresh recomputes already-current scopes (performance waste).

### Pitfall 4: --full-refresh Must Delete ctf Rows AND Reset State
**What goes wrong:** Resetting only the state table causes DELETE+INSERT duplicates because old ctf rows remain.
**Why it happens:** CTFFeature._write_to_db uses scoped DELETE by (ids, venue_id, base_tf, ref_tf, indicator_ids). If state is cleared but ctf rows are not, the next run recomputes and the scoped DELETE handles it -- but if state is cleared AND we skip the DELETE, duplicates arise.
**How to avoid:** For `--full-refresh`: (1) DELETE from `ctf` WHERE id = ANY(ids) AND base_tf/ref_tf in scope, (2) DELETE from `ctf_state` WHERE id = ANY(ids). Then compute normally. CTFFeature._write_to_db already handles the scoped DELETE per indicator, so step (1) is optional but clean.
**Warning signs:** ctf row counts growing unexpectedly on re-runs.

### Pitfall 5: Windows maxtasksperchild=1 is NOT Optional
**What goes wrong:** Memory leaks accumulate when workers process multiple tasks on Windows.
**Why it happens:** Windows uses spawn (not fork) for multiprocessing; each worker keeps residual state.
**How to avoid:** Always set `maxtasksperchild=1` on Windows. Project comment in bakeoff_orchestrator.py: "Use maxtasksperchild=1 on Windows (project convention)".
**Warning signs:** Memory usage growing unboundedly during long --all runs.

### Pitfall 6: CTFFeature.compute_for_ids Signature Is Fixed
**What goes wrong:** Planner tries to add `base_tf`, `ref_tfs`, `indicator_names` filtering to CTFFeature itself.
**Why it happens:** The success criteria require `--base-tf` and `--indicators` CLI filtering, but those could be implemented at the CLI layer (filtering the work) or at the engine layer (filtering inside CTFFeature).
**How to avoid:** The CLI script handles filtering BEFORE calling `compute_for_ids`. The YAML config can be filtered at load time by passing a modified copy. The `dim_ctf_indicators` query can be pre-filtered. `compute_for_ids` itself stays clean.
**Warning signs:** Modifying cross_timeframe.py unnecessarily (Phase 90 is complete).

## Code Examples

### Verified: CTFFeature Instantiation and compute_for_ids
```python
# Source: src/ta_lab2/features/cross_timeframe.py

from ta_lab2.features.cross_timeframe import CTFFeature, CTFConfig

config = CTFConfig(
    alignment_source="multi_tf",
    venue_id=1,
    yaml_path=None,  # uses default configs/ctf_config.yaml
)
feature = CTFFeature(config=config, engine=engine)
total_rows = feature.compute_for_ids(ids=[1, 52, 1027])
```

### Verified: NullPool Engine in Worker
```python
# Source: src/ta_lab2/scripts/amas/base_ama_refresher.py lines 118-120

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

engine = create_engine(task.db_url, poolclass=NullPool)
```

### Verified: Alembic Migration Head Revision
```
Current head: j4k5l6m7n8o9 (CTF schema -- dim_ctf_indicators and ctf fact table)
New migration for ctf_state must set: down_revision = "j4k5l6m7n8o9"
```

### Verified: YAML Config Current State (4 base TFs)
```yaml
# Source: configs/ctf_config.yaml -- current state

timeframe_pairs:
  - base_tf: "1D"
    ref_tfs: ["7D", "14D", "30D", "90D", "180D", "365D"]
  - base_tf: "7D"
    ref_tfs: ["30D", "90D", "180D", "365D"]
  - base_tf: "14D"
    ref_tfs: ["90D", "180D", "365D"]
  - base_tf: "30D"
    ref_tfs: ["180D", "365D"]
```

**Expansion candidates** (user wants more base TFs): The project supports `2D`, `3D`, `4D`, `5D` daily-granularity TFs (seen in old EMA code). Reasonable additions are `2D` and `3D` base TFs with appropriate ref_tfs. This stays within daily granularity where CTF computation is meaningful.

### Verified: Existing run_all_feature_refreshes Phase Structure
```python
# Source: src/ta_lab2/scripts/features/run_all_feature_refreshes.py lines 427-530

# Phase 1: vol/ta/cycle_stats/rolling_extremes (parallel via ThreadPoolExecutor)
# Phase 2: features store (depends on Phase 1)
# Phase 2b: microstructure UPDATE on features rows (depends on Phase 2)
# [Phase 2c: CTF -- NEW, depends on Phase 2 for features source table]
# Phase 3: CS norms (depends on Phase 2, independent of CTF)
# Phase 3b: codependence (optional)
# Phase 4: validation
```

### Verified: RefreshResult Dataclass Pattern
```python
# Source: src/ta_lab2/scripts/features/run_all_feature_refreshes.py lines 64-72

@dataclass
class RefreshResult:
    table: str
    rows_inserted: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None
```

### Verified: State Watermark Skip Pattern
```python
# Source: src/ta_lab2/scripts/features/run_all_feature_refreshes.py lines 608-635

def _should_skip_tf(engine, tf, alignment_source):
    """Returns True if features are up-to-date (skip), False if refresh needed."""
    # Compare MAX(ingested_at) from source vs MAX(updated_at) from state
    ...
    return feature_ts >= source_ts
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `CREATE TABLE IF NOT EXISTS` for state | Alembic migration | Project-wide since v1.0.0 | State tables are version-controlled, reversible |
| `feature_state` for all features | Dedicated state tables per feature family | AMA introduced its own `ama_multi_tf_state` | Cleaner PK structure, no multi-dimensional key hacks |
| ProcessPoolExecutor for workers | `multiprocessing.Pool` with `maxtasksperchild=1` | Established convention | Windows-safe memory management |

**Deprecated/outdated:**
- `ensure_state_table()` with `CREATE TABLE IF NOT EXISTS`: Do not use for CTF state. Use Alembic.
- Using `feature_state` table for CTF: Lacks base_tf/ref_tf/indicator_id dimensions.

## Open Questions

1. **CTF YAML expansion: exactly which base TFs to add**
   - What we know: User wants more than 4 base TFs. Project supports 2D, 3D, 4D daily TFs.
   - What's unclear: Whether to add intraday (4h, 8h, 12h) or stay daily. Intraday CTF would require hourly bars to exist, which is uncertain.
   - Recommendation: Add `2D` and `3D` as base TFs only. Stay daily. Verify bars exist for these TFs before adding to YAML.

2. **CTF failure handling in pipeline: fatal vs non-fatal**
   - What we know: CTF is Phase 2c. Phase 3 (CS norms) does not depend on CTF rows.
   - What's unclear: Whether downstream consumers (analysis, signals) depend on ctf being fresh.
   - Recommendation: Non-fatal (log-and-continue). This matches how microstructure (Phase 2b) and codependence (Phase 3b) handle failures. Return `success=False` in RefreshResult, continue to Phase 3.

3. **--dry-run flag complexity**
   - What we know: `refresh_vol_daily.py` has `--dry-run`. `run_all_feature_refreshes.py` does not.
   - What's unclear: Whether CTF dry-run needs to simulate DB writes or just report what would run.
   - Recommendation: Include `--dry-run` flag. Implementation: compute but skip `_write_to_db` and skip state updates. Add `dry_run: bool` to CTFWorkerTask.

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/features/cross_timeframe.py` -- CTFFeature API surface, CTFConfig, compute_for_ids signature
- `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` -- Phase structure, RefreshResult, NullPool ProcessPoolExecutor pattern, _should_skip_tf watermark pattern
- `src/ta_lab2/scripts/features/feature_state_manager.py` -- feature_state schema (PK: id/feature_type/feature_name/venue_id)
- `src/ta_lab2/scripts/amas/base_ama_refresher.py` -- Module-level worker pattern, NullPool, maxtasksperchild=1, cpu_count auto-detect
- `src/ta_lab2/scripts/analysis/run_ic_sweep.py` -- imap_unordered progress counter pattern
- `alembic/versions/j4k5l6m7n8o9_ctf_schema.py` -- Current Alembic head revision (j4k5l6m7n8o9), ctf fact table schema
- `configs/ctf_config.yaml` -- Current 4 base TFs, YAML structure

### Secondary (MEDIUM confidence)
- `.venv311/Lib/site-packages/tqdm-4.67.1.dist-info/` -- tqdm installed but not in pyproject.toml core deps
- `src/ta_lab2/scripts/features/refresh_vol_daily.py` -- --dry-run CLI flag pattern
- `pyproject.toml` -- tqdm not listed in dependencies section

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified in live codebase
- Architecture: HIGH -- patterns read directly from working scripts
- Pitfalls: HIGH for items 1-5, MEDIUM for item 6 (CTF signature assumption)
- State table design: HIGH -- verified feature_state and AMA state table patterns

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable internal patterns, no external library dependencies)
