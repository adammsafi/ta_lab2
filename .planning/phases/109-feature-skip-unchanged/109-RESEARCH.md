# Phase 109: Feature Skip-Unchanged - Research

**Researched:** 2026-04-01
**Domain:** Feature refresh pipeline, watermark state tables, PostgreSQL incremental patterns
**Confidence:** HIGH

## Summary

Phase 109 adds per-asset watermark-based skip logic to `run_all_feature_refreshes.py`. Before
processing any sub-phase, the orchestrator compares MAX(ingested_at or time_close) from the source
bars per asset against the `feature_refresh_state.last_bar_ts`. Assets with no new bar data are
skipped entirely, cutting the daily incremental from ~100 min to ~10 min.

The codebase already has multiple analogous state tables and skip patterns to follow exactly:
- `ctf_state` / `_should_skip_asset()` in `refresh_ctf.py` is the closest model (per-asset skip)
- `_should_skip_tf()` in `run_all_feature_refreshes.py` is a simpler TF-level skip already in place
- `ema_multi_tf_state`, `ama_multi_tf_state`, `feature_state` show the DDL conventions

The new table is `feature_refresh_state` with PK `(id, tf, alignment_source)` — deliberately
different from the existing `feature_state` table (which has PK `(id, feature_type, feature_name,
venue_id)` and serves a different purpose: per-feature-column state tracking).

**Primary recommendation:** Follow the `ctf_state` + `_should_skip_asset()` pattern precisely.
The only difference is that `feature_refresh_state` is keyed per `(id, tf, alignment_source)`
instead of per CTF scope, and the watermark is sourced from `price_bars_multi_tf_u.ingested_at`
rather than a computed_at column.

## Standard Stack

### Core
| Component | Version/Name | Purpose | Why Standard |
|-----------|-------------|---------|--------------|
| PostgreSQL | project-wide | State table storage | All state tables use Postgres |
| SQLAlchemy | project-wide | ORM/connection | Project-standard; NullPool for multiprocessing |
| Alembic | project-wide | Migration | All schema changes go through alembic |

### Supporting
| Component | Version/Name | Purpose | When to Use |
|-----------|-------------|---------|-------------|
| `sqlalchemy.text()` | project-wide | Parameterized SQL | All raw SQL in project |
| `pd.read_sql()` | project-wide | Read state as DataFrame | Consistent with EMAStateManager pattern |
| `ANY(:ids)` | PostgreSQL | Batch IN clause | Used throughout codebase for list params |

**Installation:** No new packages required.

## Architecture Patterns

### Recommended Project Structure

The change spans two files:
```
alembic/versions/u5v6w7x8y9z0_phase109_feature_refresh_state.py   # new migration
src/ta_lab2/scripts/features/
    run_all_feature_refreshes.py                                    # main changes here
```

No new Python module is needed — the state helper functions go directly in
`run_all_feature_refreshes.py`, matching how CTF state helpers live in `refresh_ctf.py`.

### Pattern 1: New State Table DDL (Alembic Migration)

**What:** Alembic migration file that creates `feature_refresh_state`.

**Key design decisions from CONTEXT.md:**
- PK: `(id, tf, alignment_source)` — no `venue_id` in PK (feature_refresh_state is keyed per
  source context, not per venue; venue_id=1 is default for CMC bars)
- Columns: `last_bar_ts TIMESTAMPTZ`, `last_refresh_ts TIMESTAMPTZ`, `rows_written INTEGER`
- `down_revision` must be `"t4u5v6w7x8y9"` (latest migration as of 2026-04-01)
- All SQL comments in ASCII only (Windows cp1252 — see Phase 107 migration as reference)

```python
# Source: alembic/versions/k5l6m7n8o9p0_ctf_state.py (pattern reference)
revision: str = "u5v6w7x8y9z0"
down_revision: Union[str, Sequence[str], None] = "t4u5v6w7x8y9"

def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS public.feature_refresh_state (
            id                  INTEGER      NOT NULL,
            tf                  TEXT         NOT NULL,
            alignment_source    TEXT         NOT NULL DEFAULT 'multi_tf',
            last_bar_ts         TIMESTAMPTZ  NULL,
            last_refresh_ts     TIMESTAMPTZ  NULL,
            rows_written        INTEGER      NULL,
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (id, tf, alignment_source)
        )
    """))

def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS public.feature_refresh_state"))
```

### Pattern 2: Batch Watermark Pre-check

**What:** Single SQL query fetching MAX(ingested_at) per (id, tf, alignment_source) from source,
then a second query fetching last_bar_ts from feature_refresh_state for all IDs at once. Compare
to build `changed_ids` and `unchanged_ids`.

**When to use:** Called at the top of `run_all_refreshes()` when `full_refresh=False`.

**Key insight:** Use `ingested_at` (not `time_close` or `ts`) as the source watermark because
`ingested_at` is updated any time a bar is inserted/updated, including reprocessed historical bars.
The existing `_should_skip_tf()` in the same file already uses `MAX(ingested_at)`.

```python
# Source: run_all_feature_refreshes.py _should_skip_tf() + refresh_ctf.py _should_skip_asset()
def _load_bar_watermarks(engine, ids: list[int], tf: str, alignment_source: str) -> dict[int, Any]:
    """Fetch MAX(ingested_at) per id from price_bars_multi_tf_u.

    Returns dict: id -> max_ingested_at (or None if no bars).
    """
    sql = text("""
        SELECT id, MAX(ingested_at) AS max_ingested_at
        FROM public.price_bars_multi_tf_u
        WHERE id = ANY(:ids)
          AND tf = :tf
          AND alignment_source = :as_
        GROUP BY id
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"ids": ids, "tf": tf, "as_": alignment_source}).fetchall()
    return {row[0]: row[1] for row in rows}


def _load_feature_state(engine, ids: list[int], tf: str, alignment_source: str) -> dict[int, Any]:
    """Fetch last_bar_ts per id from feature_refresh_state.

    Returns dict: id -> last_bar_ts (or None if no state row).
    """
    sql = text("""
        SELECT id, last_bar_ts
        FROM public.feature_refresh_state
        WHERE id = ANY(:ids)
          AND tf = :tf
          AND alignment_source = :as_
    """)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, {"ids": ids, "tf": tf, "as_": alignment_source}).fetchall()
        return {row[0]: row[1] for row in rows}
    except Exception:
        return {}  # Table not yet created — treat all as changed


def compute_changed_ids(
    engine, ids: list[int], tf: str, alignment_source: str
) -> tuple[list[int], list[int]]:
    """Split ids into (changed_ids, unchanged_ids).

    changed_ids:   source bars have new ingested_at since last feature refresh
    unchanged_ids: no new bars, skip entirely
    """
    bar_wm = _load_bar_watermarks(engine, ids, tf, alignment_source)
    state_wm = _load_feature_state(engine, ids, tf, alignment_source)

    changed, unchanged = [], []
    for id_ in ids:
        source_ts = bar_wm.get(id_)
        feature_ts = state_wm.get(id_)
        if source_ts is None:
            unchanged.append(id_)   # no bar data at all, nothing to compute
        elif feature_ts is None:
            changed.append(id_)     # never computed, must run
        elif source_ts > feature_ts:
            changed.append(id_)     # new bars since last refresh
        else:
            unchanged.append(id_)   # feature_ts >= source_ts, skip
    return changed, unchanged
```

### Pattern 3: State Update After All Sub-phases

**What:** Upsert feature_refresh_state rows for changed_ids after all sub-phases succeed.

```python
# Source: refresh_ctf.py _update_ctf_state() pattern
def _update_feature_refresh_state(
    engine,
    changed_ids: list[int],
    tf: str,
    alignment_source: str,
    bar_watermarks: dict[int, Any],
    total_rows_written: int,
) -> None:
    """Upsert feature_refresh_state for successfully refreshed assets."""
    for id_ in changed_ids:
        last_bar_ts = bar_watermarks.get(id_)
        sql = text("""
            INSERT INTO public.feature_refresh_state
                (id, tf, alignment_source, last_bar_ts, last_refresh_ts, rows_written, updated_at)
            VALUES
                (:id, :tf, :as_, :last_bar_ts, NOW() AT TIME ZONE 'UTC', :rows_written,
                 NOW() AT TIME ZONE 'UTC')
            ON CONFLICT (id, tf, alignment_source) DO UPDATE SET
                last_bar_ts     = EXCLUDED.last_bar_ts,
                last_refresh_ts = EXCLUDED.last_refresh_ts,
                rows_written    = EXCLUDED.rows_written,
                updated_at      = EXCLUDED.updated_at
        """)
        with engine.begin() as conn:
            conn.execute(sql, {
                "id": id_, "tf": tf, "as_": alignment_source,
                "last_bar_ts": last_bar_ts,
                "rows_written": total_rows_written,
            })
```

Note: `total_rows_written` here is an approximation (sum across all sub-phases for this id set).
Alternatively, pass 0 and only track the timestamp — CONTEXT.md only requires the skip logic to
work correctly, not per-ID row counts.

### Pattern 4: Integration into run_all_refreshes()

**What:** Modify `run_all_refreshes()` to accept `full_rebuild` parameter, run watermark check,
pass `changed_ids` to each sub-phase, log skip count, update state at end.

```python
def run_all_refreshes(
    engine,
    ids: list[int],
    tf: str = "1D",
    alignment_source: str = "multi_tf",
    full_refresh: bool = False,
    full_rebuild: bool = False,        # NEW: bypasses skip logic
    ...
) -> dict[str, RefreshResult]:

    if not full_rebuild:
        changed_ids, unchanged_ids = compute_changed_ids(engine, ids, tf, alignment_source)
        bar_watermarks = _load_bar_watermarks(engine, ids, tf, alignment_source)
        if unchanged_ids:
            logger.info(f"Skipping {len(unchanged_ids)} unchanged assets"
                        f" (no new bars for tf={tf})")
        if not changed_ids:
            logger.info("All assets up-to-date, nothing to refresh")
            return {}
        process_ids = changed_ids
    else:
        process_ids = ids
        bar_watermarks = {}

    # Pass process_ids (not all ids) to every sub-phase
    ...

    # After all sub-phases, update state
    if not full_rebuild and changed_ids:
        _update_feature_refresh_state(
            engine, changed_ids, tf, alignment_source, bar_watermarks, total_rows
        )
```

### Pattern 5: CS Norms Special Case

**What:** CS norms runs a window UPDATE over ALL assets at a given (ts, tf), not a scoped
DELETE+INSERT per ID. It cannot be limited to `changed_ids` — it must run if ANY asset in the
timeframe has been updated.

**Rule:** If `changed_ids` is non-empty, CS norms must still run on ALL rows (its SQL already
does this via `PARTITION BY (ts, tf)` — no id filter passed to `_refresh_cs_norms()`).

### Anti-Patterns to Avoid

- **Watermark on `ts`/`time_close` instead of `ingested_at`:** `ts` doesn't change when a bar is
  reprocessed. `ingested_at` is set on every INSERT and is the correct indicator of new data. This
  is the same choice made in `_should_skip_tf()`.
- **Per-asset upsert loop instead of batch check:** Do watermark check as two bulk SQL queries
  (one for bars, one for state), then compare in Python. Don't loop per-asset to the DB.
- **Updating state before sub-phases complete:** Only update state after all sub-phases succeed.
  If vol succeeds but ta fails, state should not be advanced for that asset.
- **Skipping CTF per the new skip logic:** CTF already has its own `_should_skip_asset()` logic
  using `ctf_state`. The CTF step will naturally be a no-op for unchanged assets because CTF
  checks its own state independently. Do not double-skip CTF from `run_all_refreshes`.
- **Using `feature_state` (existing table) as the watermark:** `feature_state` has PK
  `(id, feature_type, feature_name, venue_id)` — too granular for the per-asset skip needed here.
  A new `feature_refresh_state` with PK `(id, tf, alignment_source)` is the right design.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Watermark comparison | Custom timestamp diff logic | `source_ts > feature_ts` Python comparison | Timestamps are tz-aware TIMESTAMPTZ; Python comparison works correctly |
| Batch ID check | Per-ID SELECT loop | `WHERE id = ANY(:ids)` + `GROUP BY id` | Project-standard pattern, one round-trip for all assets |
| State upsert | Multi-row INSERT VALUES | Per-row upsert in a loop (OK for ~10 rows) | changed_ids is 4-10 rows daily — loop is fine; batch only needed for 500+ |
| Table existence guard | Try/except on state load | Catch exception, return empty dict | This is the established pattern in `_load_feature_state` |

## Common Pitfalls

### Pitfall 1: feature_state vs feature_refresh_state confusion
**What goes wrong:** Developer modifies `feature_state` thinking it's the new skip table.
**Why it happens:** Both names contain "feature" and "state".
**How to avoid:** `feature_state` has PK `(id, feature_type, feature_name, venue_id)` and tracks
per-column per-asset state. `feature_refresh_state` is new and has PK `(id, tf, alignment_source)`.
**Warning signs:** Code referencing `feature_type` or `feature_name` columns in the new table.

### Pitfall 2: TF-level skip already exists, per-asset skip is different
**What goes wrong:** Thinking `_should_skip_tf()` already solves this.
**Why it happens:** `_should_skip_tf()` skips an entire TF if ANY asset's features are fresh.
For the per-asset skip we need to know WHICH assets are fresh per-asset.
**How to avoid:** Keep `_should_skip_tf()` as-is (TF-level early exit). The new
`compute_changed_ids()` runs within the TF that passed the coarse check.

### Pitfall 3: Forgetting `--full-rebuild` is distinct from `--full-refresh`
**What goes wrong:** CONTEXT.md specifies `--full-rebuild` bypasses skip logic. But `--full-refresh`
already exists in `run_all_feature_refreshes.py` and means "delete+recompute all rows".
**Why it happens:** Both flags sound similar.
**How to avoid:** `--full-rebuild` → bypasses skip logic, passes all IDs to sub-phases. It can
also set `full_refresh=True` internally if full recompute is desired, but the key semantic is
"ignore state table". They can be the same flag or separate. Check CONTEXT.md: it says
`--full-rebuild bypasses skip logic` — treat it as an alias for the existing `--full-refresh`
that additionally clears/ignores `feature_refresh_state`.

### Pitfall 4: State update if any sub-phase fails
**What goes wrong:** State is updated even though ta or vol failed, so next run skips the asset.
**Why it happens:** State update code runs unconditionally after sub-phase loop.
**How to avoid:** Only update state if all sub-phase results show `success=True`. Check
`all(r.success for r in results.values() if hasattr(r, 'success'))`.

### Pitfall 5: Windows UTF-8 / ASCII-only SQL comments
**What goes wrong:** Alembic migration fails on Windows with UnicodeDecodeError.
**Why it happens:** Windows uses cp1252 by default; box-drawing or UTF-8 chars in SQL strings fail.
**How to avoid:** Use ASCII-only comments in all SQL strings inside Alembic migrations. See Phase
107 migration (`t4u5v6w7x8y9_phase107_pipeline_stage_log.py`) — it explicitly states
"All comments use ASCII only (Windows cp1252 compatibility)."

### Pitfall 6: ingested_at not present on all bar variants
**What goes wrong:** Query `price_bars_1d` instead of `price_bars_multi_tf_u` for the watermark.
**Why it happens:** Some sub-phases source from `price_bars_1d`; developer uses that table.
**How to avoid:** The orchestrator (`run_all_feature_refreshes.py`) already sources IDs from
`price_bars_multi_tf_u`. Use the same table for the watermark check for consistency. Note that
`ingested_at` is confirmed present on `price_bars_multi_tf_u` — it is used in `_should_skip_tf()`
in the same file.

## Code Examples

### Batch watermark check (verified against existing _should_skip_tf pattern)
```python
# Source: run_all_feature_refreshes.py lines 649-671
# Existing TF-level check uses MAX(ingested_at) from price_bars_multi_tf_u
# The per-asset variant groups by id instead of using a global MAX:
sql = text("""
    SELECT id, MAX(ingested_at) AS max_ingested_at
    FROM public.price_bars_multi_tf_u
    WHERE id = ANY(:ids)
      AND tf = :tf
      AND alignment_source = :as_
    GROUP BY id
""")
```

### Alembic migration pattern (verified against k5l6m7n8o9p0_ctf_state.py)
```python
# Source: alembic/versions/k5l6m7n8o9p0_ctf_state.py
def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS public.feature_refresh_state (
            ...
            PRIMARY KEY (id, tf, alignment_source)
        )
    """))

def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS public.feature_refresh_state"))
```

### Per-asset skip with graceful table-not-exists handling
```python
# Source: refresh_ctf.py _should_skip_asset() lines 88-162
try:
    with engine.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {row[0]: row[1] for row in rows}
except Exception:
    return {}  # table not yet created, treat all as changed
```

### Logging skip count (required by FEAT-03)
```python
# Pattern from refresh_ctf.py _ctf_worker lines 278-285
logger.info(
    "Skipping %d unchanged assets (no new bars since last refresh, tf=%s)",
    len(unchanged_ids),
    tf,
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No per-asset skip, process all 492 | TF-level skip only (`_should_skip_tf`) | Phase 109 pre | Still processes all 492 per-asset |
| Per-asset skip via `feature_refresh_state` | New in Phase 109 | Phase 109 | 492 → ~10 assets daily |
| CTF has its own `_should_skip_asset` | Will still be independent | No change | CTF handles its own skip |

## Open Questions

1. **rows_written tracking**
   - What we know: CONTEXT.md says track `rows_written` in the state table
   - What's unclear: Is this per-asset or total for the entire changed_ids batch?
   - Recommendation: Store the total rows written across all sub-phases for the entire
     `changed_ids` batch (easiest to implement; sufficient for monitoring). If per-asset
     granularity is needed later, it can be added.

2. **venue_id in feature_refresh_state**
   - What we know: CONTEXT.md says PK is `(id, tf, alignment_source)` — no venue_id
   - What's unclear: Most analytics tables include venue_id. Is it intentional to exclude?
   - Recommendation: Follow CONTEXT.md exactly — no venue_id. The daily refresh uses
     `venue_id=1` (CMC_AGG) for features. If multi-venue feature support is added later,
     the migration can add venue_id to the PK then.

3. **full-rebuild vs full-refresh flag name**
   - What we know: CONTEXT.md says `--full-rebuild`; existing CLI has `--full-refresh`
   - What's unclear: Should these be the same flag or separate?
   - Recommendation: Reuse `--full-refresh`. When `full_refresh=True`, also bypass the
     `feature_refresh_state` skip logic. This avoids adding a new CLI flag. The planner
     should verify this interpretation with CONTEXT.md requirements.

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` — orchestrator, existing skip logic
- `src/ta_lab2/scripts/features/refresh_ctf.py` — `_should_skip_asset()` pattern (closest analog)
- `src/ta_lab2/scripts/features/feature_state_manager.py` — existing feature_state table DDL
- `src/ta_lab2/scripts/emas/ema_state_manager.py` — state manager pattern reference
- `src/ta_lab2/scripts/features/base_feature.py` — `compute_for_ids()` signature (what sub-phases accept)
- `alembic/versions/k5l6m7n8o9p0_ctf_state.py` — ctf_state migration DDL pattern
- `alembic/versions/t4u5v6w7x8y9_phase107_pipeline_stage_log.py` — latest migration, down_revision

### Secondary (MEDIUM confidence)
- `.planning/phases/109-feature-skip-unchanged/109-CONTEXT.md` — user decisions / requirements
- `.planning/phases/108-pipeline-batch-performance/108-CONTEXT.md` — upstream phase context

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, all existing patterns
- Architecture: HIGH — directly derived from ctf_state + _should_skip_asset + _should_skip_tf patterns in codebase
- Pitfalls: HIGH — all derived from actual code reading (feature_state vs feature_refresh_state, ASCII-only SQL, CS norms special case)

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable patterns, unlikely to change)
