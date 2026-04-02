# Phase 110: Feature Parallel Sub-Phases - Research

**Researched:** 2026-04-01
**Domain:** Python concurrent.futures / multiprocessing parallelism, PostgreSQL write concurrency, feature refresh pipeline
**Confidence:** HIGH

## Summary

Phase 110 adds Wave parallelism to the feature refresh so that independent sub-phases run
concurrently rather than sequentially. The CONTEXT.md lays out the target wave structure
(101 min serial -> ~61 min parallel). The codebase already has two precedents for exactly
this pattern: the `ThreadPoolExecutor(max_workers=3)` already running vol+ta in Phase 1 of
`run_all_feature_refreshes.py`, and the `ProcessPoolExecutor(max_workers=tf_workers,
max_tasks_per_child=1)` for TF-level parallelism in the same file.

The critical design question is **threads vs processes** for Wave 1 parallelism:

- **Threads (ThreadPoolExecutor)** are already in use for vol+ta (Phase 1) and work well
  because each sub-phase creates its own DB connections through the shared engine. The GIL
  is released during I/O (DB reads/writes, pandas computations involving numpy/C extensions),
  so threads provide real concurrency for I/O-bound work. The engine passed to threads is the
  same object, but each `engine.begin()` / `engine.connect()` call creates an independent
  connection from the pool. With the default `create_engine(..., future=True)` (no NullPool),
  SQLAlchemy's connection pool handles concurrent thread access safely.

- **Processes (ProcessPoolExecutor / multiprocessing.Pool)** are used for TF-level parallelism
  where each worker creates its own `NullPool` engine (Windows requirement). For Wave
  parallelism within a single TF, processes add pickling overhead and memory duplication of
  the loaded DataFrames. CTF already uses `Pool(maxtasksperchild=1)` for per-asset work; that
  is a different axis of parallelism (per-asset, not per-sub-phase).

**Primary recommendation:** Extend the existing `ThreadPoolExecutor` in `run_all_feature_refreshes.py`
to Wave 1 (vol + ta + cycle_stats + microstructure all in parallel), while keeping the
engine-passing pattern exactly as the current vol+ta parallel block does. No new mechanism needed.
**Critical exception:** Microstructure must run after `refresh_features_store` (it UPDATEs rows
that features_store INSERTs). This is a hard dependency — see Dependency Analysis below.

## Standard Stack

### Core
| Component | Version | Purpose | Why Standard |
|-----------|---------|---------|--------------|
| `concurrent.futures.ThreadPoolExecutor` | stdlib | Wave parallelism for I/O-bound sub-phases | Already used in `run_all_feature_refreshes.py` line 450 for vol+ta |
| `concurrent.futures.as_completed` | stdlib | Harvest results as futures complete | Already imported and used |
| `concurrent.futures.ProcessPoolExecutor` | stdlib | TF-level parallelism (already implemented) | `max_tasks_per_child=1` (Windows) |
| `multiprocessing.Pool(maxtasksperchild=1)` | stdlib | CTF per-asset parallelism (already implemented) | `refresh_ctf.py` line 755 |
| `sqlalchemy.pool.NullPool` | SQLAlchemy | Process-local engines (no shared pool) | Required for multiprocessing on Windows |

### Supporting
| Component | Version | Purpose | When to Use |
|-----------|---------|---------|-------------|
| `threading.Semaphore` | stdlib | Cap total worker count across waves | When waves share a total worker budget |
| `logging.getLogger(__name__)` | stdlib | Per-sub-phase log output | Log sub-phase start/end in each wave |

**Installation:** No new packages required.

## Architecture Patterns

### Recommended Project Structure

No new files needed. All changes go in one file:

```
src/ta_lab2/scripts/features/
    run_all_feature_refreshes.py    # only file modified
```

### Current Sub-Phase Execution Order (VERIFIED from code)

From `run_all_feature_refreshes.py` `run_all_refreshes()`:

| Step | Code label | Table written | Source tables read | Write type |
|------|-----------|---------------|-------------------|------------|
| Phase 1 (parallel) | vol, ta, cycle_stats, rolling_extremes | `vol`, `ta`, `cycle_stats`, `rolling_extremes` | `price_bars_multi_tf_u` | DELETE+INSERT scoped by (id, tf, alignment_source, venue_id) |
| Phase 2 | features (unified) | `features` | `price_bars_multi_tf_u`, `returns_bars_multi_tf_u`, `vol`, `ta` | DELETE+INSERT scoped by id |
| Phase 2b | microstructure | `features` (UPDATE only) | `price_bars_multi_tf_u` | UPDATE existing rows |
| Phase 2c | CTF | `ctf` | `ta`, `vol`, `returns_*`, `features` | internal per-asset logic |
| Phase 3 | CS norms | `features` (UPDATE) | `features` (reads ret_arith, rsi_14, vol_parkinson_20) | UPDATE via window function |
| Phase 3b | codependence | `codependence` | `features` | pairwise INSERT |

### Dependency Analysis (What Can Run In Parallel?)

```
price_bars_multi_tf_u (source, read-only)
        |
        +---> vol          (writes vol)           \
        +---> ta           (writes ta)             |  WAVE 1: all read only price_bars
        +---> cycle_stats  (writes cycle_stats)    |
        +---> rolling_extremes (writes rolling_extremes)
                                                   /
        +---> features (unified)  <-- reads vol, ta, returns (must wait for vol+ta)
        |
        +---> microstructure  <-- UPDATES features rows (must wait for features unified)
        |
        +---> CTF  <-- reads ta, vol, features, returns (must wait for features+micro)
        |
        +---> CS norms  <-- UPDATEs features (must wait for features+micro)
        +---> codependence  <-- reads features (optional, separate run)
```

**CONTEXT.md Wave Structure vs Actual Dependencies:**

The CONTEXT.md proposes:
```
Wave 1: vol + ta + cycle_stats + microstructure
Wave 2: rolling_extremes + features (unified)
```

However, microstructure **cannot** run in Wave 1 alongside vol/ta/cycle_stats because:
- Microstructure does `UPDATE public.features SET ...` where it updates rows that the
  `features` (unified) step INSERTs. If no features rows exist yet, the UPDATE is a no-op.
- In `run_all_feature_refreshes.py` lines 508-524: microstructure is labeled "Phase 2b:
  MUST run after Phase 2 — microstructure does UPDATE on existing rows".

**Corrected Wave Structure:**

| Wave | Sub-phases | Source reads | Writes | Parallelizable? |
|------|-----------|-------------|--------|----------------|
| Wave 1 | vol, ta, cycle_stats, rolling_extremes | price_bars_multi_tf_u | vol, ta, cycle_stats, rolling_extremes | YES - all independent |
| Wave 2 | features (unified) | price_bars, returns, vol, ta | features | NO - depends on Wave 1 |
| Wave 2b | microstructure | price_bars_multi_tf_u | features (UPDATE) | NO - depends on Wave 2 |
| Wave 3 | CTF | ta, vol, features, returns | ctf | NO - depends on Wave 2b |
| Wave 4 | CS norms | features | features (UPDATE) | NO - depends on Wave 2b |

**Key insight:** The biggest single win is fully parallelizing Wave 1. Currently `run_all_feature_refreshes.py`
runs vol+ta+cycle_stats+rolling_extremes with `ThreadPoolExecutor(max_workers=3)` — meaning all 4
tasks are submitted but only 3 run simultaneously. Increasing `max_workers` to 4 lets all 4 run
at once and eliminates the sequencing of rolling_extremes.

**Timing estimate from CONTEXT.md:**
- Wave 1 serial: vol (varies) + ta (varies) + cycle_stats (varies) + rolling_extremes (varies) = ~53 min
- Wave 1 parallel with 4 workers: limited by the slowest = ~17 min
- Wave 2+2b+3+4: sequential, ~48 min total
- **Overall: ~65 min** (already within the 70 min target from FEAT-05)

### Pattern 1: Extend Wave 1 Thread Pool to 4 Workers

**What:** Change `max_workers=3` to `max_workers=4` in the existing `ThreadPoolExecutor` block.
This is the only code change needed for the primary Wave 1 optimization.

**Current code (lines 450-468):**
```python
# Source: run_all_feature_refreshes.py lines 439-491
phase1_tasks = [
    ("vol", refresh_vol),
    ("ta", refresh_ta),
    ("cycle_stats", refresh_cycle_stats),
    ("rolling_extremes", refresh_rolling_extremes),
]

if parallel:
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_name = {}
        for name, refresh_fn in phase1_tasks:
            future = executor.submit(
                refresh_fn,
                engine,
                ids,
                start,
                end,
                tf,
                alignment_source,
                venue_id=venue_id,
            )
            future_to_name[future] = name
```

**Change:** `max_workers=3` -> `max_workers=4` to run all 4 Wave 1 tasks simultaneously.

### Pattern 2: Worker Budget Parameter

**What:** Add a `wave1_workers` parameter to `run_all_refreshes()` so callers can cap
parallelism when memory is a concern (e.g., full recompute of 492 assets = 4 pandas DataFrames
in memory simultaneously).

```python
# Updated signature
def run_all_refreshes(
    engine,
    ids: list[int],
    tf: str = "1D",
    alignment_source: str = "multi_tf",
    full_refresh: bool = False,
    validate: bool = True,
    parallel: bool = True,
    codependence: bool = False,
    venue_id: int | None = None,
    skip_cs_norms: bool = False,
    wave1_workers: int = 4,       # NEW: controls Wave 1 thread pool size
) -> dict[str, RefreshResult]:
    ...
    if parallel:
        with ThreadPoolExecutor(max_workers=wave1_workers) as executor:
            ...
```

**CLI flag:** `--wave1-workers INT` (default 4, min 1, max 4). Expose in `parse_args()`.

### Pattern 3: --workers Flag as Total Budget

**CONTEXT.md specifies:** `--workers flag controls total parallelism budget`

The simplest interpretation: `--workers N` sets `wave1_workers=N`. Since only Wave 1 is
parallelized within a single TF, `--workers` directly maps to Wave 1 thread count.
If TF-level parallelism is also active (`--tf-workers > 1`), the total concurrent workers
across all TFs is `tf_workers * wave1_workers`. Guard: if `tf_workers * wave1_workers > 8`,
log a warning about potential memory pressure.

### Pattern 4: Engine Threading Safety

The engine passed to threaded workers is the shared `engine` object. This is safe because:
1. SQLAlchemy's connection pool (`QueuePool`, the default) is thread-safe
2. Each `engine.begin()` / `engine.connect()` acquires its own connection from the pool
3. Threads don't share connections — each sub-phase function creates its own context managers
4. `BaseFeature.write_to_db()` uses `engine.begin()` (separate transaction per call)

NullPool is only required for **process** workers, not thread workers. The existing vol+ta
ThreadPoolExecutor already passes the same engine object and works correctly.

### Anti-Patterns to Avoid

- **Making microstructure part of Wave 1:** Microstructure does `UPDATE features` — if features
  rows don't exist yet (because features_store hasn't run), the UPDATE is a silent no-op.
  The current code comment "MUST run after Phase 2" is accurate and must be preserved.
- **Using NullPool for the thread engine:** NullPool is for process workers (Windows multiprocessing
  safety). Thread workers share the parent engine safely. Adding NullPool in a thread context
  would break connection reuse and is unnecessary overhead.
- **Setting max_workers higher than 4 for Wave 1:** There are exactly 4 Wave 1 tasks. More
  workers than tasks is wasteful.
- **Removing the `parallel=False` escape hatch:** The `--sequential` flag is used for debugging
  and must remain functional. Don't merge the wave-control flags in a way that removes it.
- **Parallelizing Wave 2 (features_store + rolling_extremes together):** The `features_store`
  (daily_features_view) reads from the `vol` and `ta` tables that Wave 1 just wrote. This is
  safe sequentially (Wave 1 finishes, then Wave 2 starts), but `rolling_extremes` does NOT
  read from vol/ta — it only reads price_bars. Rolling_extremes could move to Wave 1 if desired
  (and it already is in Wave 1 in the current code structure at lines 439-441).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Thread pool | Custom Thread objects with join() | `ThreadPoolExecutor` + `as_completed` | Already used for vol+ta, stdlib, handles exceptions properly |
| Process pool | Raw `subprocess.Popen` | `ProcessPoolExecutor(max_tasks_per_child=1)` | Already used for TF-level, handles Windows pickling |
| Result collection | Manual shared-state dict with locks | `as_completed(future_to_name)` | Futures handle thread safety, already implemented |
| Memory limit | Custom memory tracking | Just cap `max_workers` | 4 workers x 492 assets x ~50MB = ~200MB, within budget |

## Common Pitfalls

### Pitfall 1: Microstructure Dependency Misread

**What goes wrong:** Developer puts microstructure in Wave 1 with vol/ta/cycle_stats.
**Why it happens:** CONTEXT.md Wave proposal groups microstructure in Wave 1. The CONTEXT.md
table was written based on an approximate dependency assumption (microstructure reads price_bars,
same as vol/ta). But microstructure WRITES to `features` via UPDATE — and features rows must
exist first (written by `refresh_features_store`).
**How to avoid:** Read the code comment at line 508: "Phase 2b: MUST run after Phase 2 —
microstructure does UPDATE on existing rows, so the base rows from features must exist first."
**Warning signs:** Microstructure returns 0 rows updated on first run in a new environment.

### Pitfall 2: Thread Pool Max Workers Too Low

**What goes wrong:** `max_workers=3` runs vol, ta, cycle_stats in parallel, but rolling_extremes
waits. This is the current state — the fix is simply changing 3 to 4.
**Why it happens:** The original code was written when only vol+ta were parallel, and 3 was
chosen conservatively. Cycle_stats and rolling_extremes were added later.
**How to avoid:** Set `max_workers=len(phase1_tasks)` or explicitly `4`.

### Pitfall 3: DB Connection Exhaustion Under Parallel Load

**What goes wrong:** Multiple threads each open connections; PostgreSQL `max_connections=100`
(default) exceeded when multiple TF workers AND wave1 workers run simultaneously.
**Why it happens:** `tf_workers=4` x `wave1_workers=4` = 16 concurrent Wave 1 workers, each
needing a DB connection. Plus the parent process connections.
**How to avoid:** The `get_engine()` function in `common_snapshot_contract.py` uses
`create_engine(db_url, future=True)` with default `QueuePool(pool_size=5, max_overflow=10)`.
With thread workers sharing the same engine, the pool handles contention without creating
extra connections. For process workers (TF-level), each uses NullPool (1 connection per
worker per query). Guard: warn if `tf_workers * wave1_workers > 8`.

### Pitfall 4: Phase 109 Interaction — Changed IDs Must Flow Into All Waves

**What goes wrong:** After Phase 109 introduces `changed_ids`, developer only passes
`changed_ids` to Wave 1, but CS norms still runs on all IDs.
**Why it happens:** CS norms uses a SQL window function over all rows and doesn't accept an
id filter — it must run if ANY asset in the TF changed. This is correct behavior and
already documented in Phase 109 research (Pattern 5: CS Norms Special Case).
**How to avoid:** Wave 1 through Wave 2b use `changed_ids`. CS norms (Wave 4) runs if
`changed_ids` is non-empty but over all rows (no id filter). This is the same rule
established in Phase 109.

### Pitfall 5: CTF Skipping Its Own State Check

**What goes wrong:** Under Phase 109, `compute_changed_ids()` returns only 4 IDs. CTF's
`_should_skip_asset()` is then called for those 4 IDs and may also skip them if CTF state
is fresh. This double-checking is fine — CTF will correctly do nothing if its own state says
it's up-to-date. Do not bypass CTF's own skip logic.
**Why it happens:** Developer thinks "Phase 109 already filtered the IDs, CTF should skip
the state check." But CTF state is separate from feature_refresh_state.
**How to avoid:** Pass `changed_ids` to the CTF step as `ids=changed_ids` and let CTF's
own `_should_skip_asset()` run normally.

### Pitfall 6: Windows GIL / Thread Safety for Numpy Computations

**What goes wrong:** Multiple threads running rolling_extremes and cycle_stats simultaneously
corrupt shared numpy arrays.
**Why it happens:** If feature functions use global state or shared mutable objects.
**How to avoid:** Each `VolatilityFeature`, `TAFeature`, etc. instance is created inside the
thread-local `refresh_vol()`, `refresh_ta()` functions with its own `engine` reference and
local DataFrames. No shared mutable state exists between wave threads. The existing vol+ta
ThreadPoolExecutor already demonstrates this is safe.

### Pitfall 7: Phase 109 State Update Timing With Parallel Waves

**What goes wrong:** Phase 109's state update (`_update_feature_refresh_state`) is called
after all sub-phases. If Phase 110 changes the ordering (e.g., error in Wave 1 doesn't stop
Wave 2 from starting), the state could be advanced for a partially-refreshed asset.
**Why it happens:** Waves run sequentially (Wave 1 finishes → Wave 2 starts → ...), so this
is not a real risk IF the wave orchestration stops on the first wave failure. The current
code collects results and logs errors but does not abort the pipeline.
**How to avoid:** After each wave, check for failures before proceeding. If any Wave 1 task
failed, skip subsequent waves for the failed assets (or abort entirely). Only update
`feature_refresh_state` after all waves succeed for a given ID set.

## Code Examples

### Wave 1 Thread Pool (4 workers)

```python
# Source: run_all_feature_refreshes.py lines 439-491 (current code with fix)
phase1_tasks = [
    ("vol", refresh_vol),
    ("ta", refresh_ta),
    ("cycle_stats", refresh_cycle_stats),
    ("rolling_extremes", refresh_rolling_extremes),
]

if parallel:
    logger.info("Wave 1: Running vol/ta/cycle_stats/rolling_extremes in parallel (4 workers)")

    with ThreadPoolExecutor(max_workers=wave1_workers) as executor:
        future_to_name = {}
        for name, refresh_fn in phase1_tasks:
            future = executor.submit(
                refresh_fn,
                engine,
                ids,
                start,
                end,
                tf,
                alignment_source,
                venue_id=venue_id,
            )
            future_to_name[future] = name

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            result = future.result()
            results[result.table] = result
            ...

# Wave 2: features_store (MUST be sequential — reads from Wave 1 outputs)
logger.info("Wave 2: Running features (unified) — depends on Wave 1")
result = refresh_features_store(engine, ids, start, end, tf, alignment_source, venue_id=venue_id)

# Wave 2b: microstructure (MUST be sequential — UPDATEs Wave 2 rows)
logger.info("Wave 2b: Microstructure UPDATE — depends on Wave 2")
micro_result = refresh_microstructure(engine, ids, start, end, tf, alignment_source, venue_id=venue_id)
```

### CLI Wave Workers Flag

```python
# In parse_args() — add after --tf-workers argument
parser.add_argument(
    "--workers",
    type=int,
    default=4,
    dest="wave1_workers",
    help="Number of parallel workers for Wave 1 sub-phases (vol/ta/cycle_stats/rolling_extremes). Default 4.",
)
```

### Worker Budget Guard

```python
# In main(), after parsing args
if getattr(args, "tf_workers", 1) > 1:
    total_workers = args.tf_workers * getattr(args, "wave1_workers", 4)
    if total_workers > 8:
        logger.warning(
            "Total concurrent workers=%d (tf_workers=%d x wave1_workers=%d) may cause "
            "memory pressure with 492 assets. Consider reducing --tf-workers or --workers.",
            total_workers,
            args.tf_workers,
            args.wave1_workers,
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| All sub-phases sequential | vol+ta parallel, rest sequential | Phase pre-110 code | Already 2x faster for vol+ta |
| `max_workers=3` for 4 tasks | `max_workers=4` | Phase 110 | rolling_extremes no longer waits |
| No `--workers` CLI flag | `--workers N` controls Wave 1 parallelism | Phase 110 | User can tune memory vs speed |

**What already exists and must NOT be changed:**
- `ThreadPoolExecutor` with `as_completed` for Phase 1 (lines 447-475) — extend, don't replace
- `ProcessPoolExecutor(max_tasks_per_child=1)` for TF-level (lines 957-965) — leave as-is
- `Pool(maxtasksperchild=1)` in CTF (line 755) — leave as-is, CTF manages its own parallelism
- The `parallel=False` / `--sequential` escape hatch — must remain

## Open Questions

1. **Rolling_extremes is already in Phase 1 list**
   - What we know: `phase1_tasks` at line 439 already includes `rolling_extremes`. The CONTEXT.md
     Wave 2 includes it separately ("Wave 2: rolling_extremes + features (unified)"). But in actual
     code, rolling_extremes is already in the Phase 1 parallel block.
   - What's unclear: Was rolling_extremes moved to Phase 1 recently? The comment at line 439 says
     "Phase 1: Vol, TA, Cycle Stats, Rolling Extremes (can run in parallel)".
   - Recommendation: Rolling_extremes is already in Wave 1. The CONTEXT.md was slightly stale.
     The actual change needed is only `max_workers=3 → 4`.

2. **Expected per-sub-phase timing breakdown**
   - What we know: Total is ~101 min for full recompute (from TIMEOUT_FEATURES comment). The
     CONTEXT.md estimates 53 min for Wave 1 serial.
   - What's unclear: Individual sub-phase timing breakdown (vol=X min, ta=Y min, etc.) — no
     logged timing benchmarks found in the codebase.
   - Recommendation: The planner should note that individual timing is not available from static
     analysis. The 60-min target is based on the CONTEXT.md estimate that the slowest Wave 1
     task is ~17 min. This should be verified with an actual run with the current 4-task parallel
     block after the max_workers fix.

3. **Phase 109 interaction: When does the watermark state get written?**
   - What we know: Phase 109's `_update_feature_refresh_state()` should run after all sub-phases
     succeed. Phase 110 doesn't change this — waves complete sequentially, state is updated at end.
   - What's unclear: Does the planner need to coordinate state update with wave success tracking?
   - Recommendation: State update (Phase 109) runs after Wave 4 (CS norms) completes. If any wave
     fails, state is not advanced. This interaction requires no extra work beyond what Phase 109
     already designs for.

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` — full orchestrator code, verified
  existing phase1_tasks list, max_workers=3, ThreadPoolExecutor usage, wave ordering comments
- `src/ta_lab2/scripts/features/microstructure_feature.py` — verified "UPDATE features" write
  strategy and "MUST run after Phase 2" constraint
- `src/ta_lab2/scripts/features/daily_features_view.py` — verified FeaturesStore reads from
  `vol` and `ta` tables (dependency on Wave 1 outputs)
- `src/ta_lab2/scripts/features/refresh_ctf.py` — verified `Pool(maxtasksperchild=1)` pattern
  and CTF's own skip logic
- `src/ta_lab2/scripts/run_daily_refresh.py` line 90 — `TIMEOUT_FEATURES = 7200 # ~101min observed`
- `.planning/phases/110-feature-parallel-subphases/110-CONTEXT.md` — wave structure, timing estimates, success criteria
- `.planning/phases/109-feature-skip-unchanged/109-RESEARCH.md` — Phase 109 patterns, CS norms
  special case, state update timing

### Secondary (MEDIUM confidence)
- `src/ta_lab2/scripts/bars/common_snapshot_contract.py` — `get_engine()` uses default QueuePool,
  thread-safe; `NullPool` is only needed for process workers
- `src/ta_lab2/scripts/features/base_feature.py` — `write_to_db()` uses `engine.begin()` per call
  (independent transaction, thread-safe)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, exact same pattern as existing vol+ta ThreadPoolExecutor
- Architecture: HIGH — full code reading confirms microstructure constraint, wave ordering,
  and rolling_extremes already in phase1_tasks (max_workers fix is the primary change)
- Pitfalls: HIGH — all derived from actual code (microstructure dependency comment, NullPool
  threading semantics, CS norms window function behavior)

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable codebase patterns)
