# Phase 77: Direct-to-_u Remaining Families - Research

**Researched:** 2026-03-20
**Domain:** PostgreSQL data pipeline migration — direct-to-_u write path for 5 table families
**Confidence:** HIGH (all findings verified from source code; no external dependencies)

---

## Summary

Phase 77 migrates 5 table families from the silo-then-sync pattern to direct writes
into the `_u` tables, following the Phase 76 pilot that proved the pattern on price bars.
The research reveals that each family uses a different write mechanism, so the migration
path is not a simple copy of Phase 76 — each family requires its own adaptation strategy.

The bar-returns family is closest to Phase 76 (pure-SQL CTE with `ON CONFLICT`) and is
the natural first step. The EMA and AMA value families use Python-side upsert paths
(`BaseEMAFeature._pg_upsert()` and `BaseAMAFeature.write_to_db()`) that must be extended
to stamp `alignment_source` before writing. The EMA and AMA returns families are also
pure-SQL CTE based, making them structurally similar to bar returns.

A critical structural difference: the EMA sync script currently uses
`ON CONFLICT (id, venue_id, ts, tf, period)` **without** `alignment_source` in the
conflict clause. This means `ema_multi_tf_u` may not have `alignment_source` in its
database PK, which must be verified before redirecting writes. AMA and all returns
families already include `alignment_source` in their `_u` table PKs.

**Primary recommendation:** Implement each family as a standalone redirect: add
`ALIGNMENT_SOURCE` constant to builder, include it in the INSERT (either as a SQL
literal or Python-side column), target the `_u` table directly, then deprecate the
silo table builder and disable the sync script.

---

## Standard Stack

All code is Python + SQLAlchemy + PostgreSQL. No new libraries are needed.

### Per-Family Builder Inventory

| Family | Builder Scripts (count) | Source Table(s) | Output _u Table |
|--------|------------------------|-----------------|-----------------|
| Bar returns | refresh_returns_bars_multi_tf.py, refresh_returns_bars_multi_tf_cal_us.py, refresh_returns_bars_multi_tf_cal_iso.py, refresh_returns_bars_multi_tf_cal_anchor_us.py, refresh_returns_bars_multi_tf_cal_anchor_iso.py (5) | price_bars_multi_tf (and cal variants) | returns_bars_multi_tf_u |
| EMA values | refresh_ema_multi_tf_from_bars.py, refresh_ema_multi_tf_cal_from_bars.py (handles us+iso), refresh_ema_multi_tf_cal_anchor_from_bars.py (handles us+iso) (3 scripts, 5 silo tables) | price_bars_multi_tf, price_bars_1d | ema_multi_tf_u |
| EMA returns | refresh_returns_ema_multi_tf.py, refresh_returns_ema_multi_tf_cal.py, refresh_returns_ema_multi_tf_cal_anchor.py (3 scripts) | ema_multi_tf (and cal variants) | returns_ema_multi_tf_u |
| AMA values | refresh_ama_multi_tf_cal_from_bars.py, refresh_ama_multi_tf_cal_anchor_from_bars.py (+ base script) | price_bars_multi_tf (and cal variants) | ama_multi_tf_u |
| AMA returns | refresh_returns_ama.py (1 script, handles all 5 via TABLE_MAP) | ama_multi_tf (and cal variants) | returns_ama_multi_tf_u |

### Sync Scripts (to disable per family)

| Family | Sync Script | Module Path |
|--------|-------------|-------------|
| Bar returns | sync_returns_bars_multi_tf_u.py | ta_lab2.scripts.returns |
| EMA values | sync_ema_multi_tf_u.py | ta_lab2.scripts.emas |
| EMA returns | sync_returns_ema_multi_tf_u.py | ta_lab2.scripts.returns |
| AMA values | sync_ama_multi_tf_u.py | ta_lab2.scripts.amas |
| AMA returns | sync_returns_ama_multi_tf_u.py | ta_lab2.scripts.amas |

### Orchestrator References

**run_daily_refresh.py** — grep confirmed zero references to any `sync_*_u.py` script.
The daily orchestrator calls bar builders, EMA refreshers, and AMA refreshers but does
NOT invoke sync scripts. Sync scripts are run manually or ad-hoc only.

**run_all_bar_builders.py** — does NOT reference any sync scripts.

Implication: disabling sync scripts requires no orchestrator cleanup. The only
references are ad-hoc CLI invocations.

---

## Architecture Patterns

### Phase 76 Pilot Pattern (Reference Implementation)

From `refresh_price_bars_multi_tf_cal_us.py` (already migrated):

```python
# Source: src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_us.py

# 1. Class constant declaring this builder's identity in the _u table
ALIGNMENT_SOURCE = "multi_tf_cal_us"

# 2. DEFAULT_BARS_TABLE already points to _u
DEFAULT_BARS_TABLE = "public.price_bars_multi_tf_u"

# 3. upsert_bars() in common_snapshot_contract.py already accepts alignment_source:
#    - valid_cols list includes "alignment_source"
#    - conflict_cols tuple includes "alignment_source"
#    - delete_bars_for_id_tf() accepts alignment_source param to scope deletes
```

The Phase 76 pattern works because `upsert_bars()` was extended to accept
`alignment_source`. The other families do NOT use `upsert_bars()`.

### Per-Family Write Path Analysis

#### Family 1: Bar Returns (Pure SQL CTE)

File: `src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf.py`

The builder constructs a multi-CTE SQL string and calls `ON CONFLICT`:

```python
# Source: refresh_returns_bars_multi_tf.py lines 102-110
_INSERT_COLS = (
    'id, venue_id, "timestamp", tf, venue, venue_rank, roll,\n'
    + ",\n".join(_VALUE_COLS)
    + ",\ningested_at"
)
# ON CONFLICT at line ~380:
#   ON CONFLICT (id, "timestamp", tf, venue_id) DO UPDATE SET ...
```

**Migration approach for bar returns:**
1. Add `ALIGNMENT_SOURCE = "multi_tf"` (or per-variant suffix) as a class/module constant
2. Change `DEFAULT_OUT_TABLE` to point to `returns_bars_multi_tf_u`
3. Add `alignment_source` to `_INSERT_COLS`
4. Add `CAST(:alignment_source AS text)` in the SELECT expression
5. Change `ON CONFLICT (id, "timestamp", tf, venue_id)` to include `alignment_source`
6. Confirm `returns_bars_multi_tf_u` has `alignment_source` in its PK

**_u PK verified from sync script:**
`PK_COLS = ["id", "venue_id", "timestamp", "tf", "alignment_source"]`
(`alignment_source` IS in the PK — ready for direct writes)

**alignment_source values per builder:**
- refresh_returns_bars_multi_tf.py → `"multi_tf"`
- refresh_returns_bars_multi_tf_cal_us.py → `"multi_tf_cal_us"`
- refresh_returns_bars_multi_tf_cal_iso.py → `"multi_tf_cal_iso"`
- refresh_returns_bars_multi_tf_cal_anchor_us.py → `"multi_tf_cal_anchor_us"`
- refresh_returns_bars_multi_tf_cal_anchor_iso.py → `"multi_tf_cal_anchor_iso"`

**State table:** `returns_bars_multi_tf_state`, PK = `(id, venue_id, tf)`
State is written by the same CTE SQL. No separate state manager class.

**No _load_last_snapshot_info.** No from_1d path.

---

#### Family 2: EMA Values (Python-Side Upsert via BaseEMAFeature)

Files: `src/ta_lab2/features/m_tf/base_ema_feature.py` (write path)
       `src/ta_lab2/scripts/emas/base_ema_refresher.py` (orchestration)

The write path uses `pandas.to_sql()` with a custom `_pg_upsert` method:

```python
# Source: base_ema_feature.py lines ~253-328
def write_to_db(self, df: pd.DataFrame) -> int:
    df.to_sql(
        name=self.config.output_table,
        con=engine,
        schema=self.config.output_schema,
        if_exists="append",
        index=False,
        method=self._pg_upsert,
    )

def _pg_upsert(self, table, conn, keys, data_iter):
    pk_cols = self._get_pk_columns()
    insert_stmt = pg_insert(table.table)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=pk_cols,
        set_={...},
    )
    conn.execute(upsert_stmt, ...)

def _get_pk_columns(self):
    # Reads from get_output_schema() dict
    return ["id", "venue_id", "tf", "ts", "period"]
```

**Critical issue:** `_get_pk_columns()` is hardcoded to `["id", "venue_id", "tf", "ts", "period"]`.
When redirecting to `ema_multi_tf_u`, `alignment_source` must be added to this list,
AND `ema_multi_tf_u` must have `alignment_source` in its database PRIMARY KEY.

**IMPORTANT: Verify ema_multi_tf_u PK before migration.**
The sync script `sync_ema_multi_tf_u.py` uses:
```python
ON CONFLICT (id, venue_id, ts, tf, period) DO NOTHING
```
`alignment_source` is NOT in the current EMA sync ON CONFLICT clause. This may mean
the DB table's PK does not include `alignment_source`. **Run this before migrating:**
```sql
SELECT indexdef FROM pg_indexes
WHERE tablename = 'ema_multi_tf_u' AND indexname LIKE '%pkey%';
```
If `alignment_source` is absent from the PK, a schema migration (ALTER TABLE) is needed
before the builders can write there with `alignment_source` in conflict resolution.

**alignment_source values per builder:**
- refresh_ema_multi_tf_from_bars.py → `"multi_tf"`
- refresh_ema_multi_tf_cal_from_bars.py (us) → `"multi_tf_cal_us"`
- refresh_ema_multi_tf_cal_from_bars.py (iso) → `"multi_tf_cal_iso"`
- refresh_ema_multi_tf_cal_anchor_from_bars.py (us) → `"multi_tf_cal_anchor_us"`
- refresh_ema_multi_tf_cal_anchor_from_bars.py (iso) → `"multi_tf_cal_anchor_iso"`

**State table:** `ema_multi_tf_state`, PK = `(id, venue_id, tf, period)`
`EMAStateManager.update_state_from_output()` reads `MAX(ts)` from the output table
grouped by `(id, venue_id, tf, period)`. When builders redirect to `ema_multi_tf_u`,
state queries will aggregate across ALL alignment_sources for the same (id, tf, period).
**Must scope the state query by `alignment_source`** to avoid cross-source contamination.

**No _load_last_snapshot_info.** No from_1d path (1D bars are treated as a special
`tf_subset` case using `price_bars_1d` as source, but output still goes to `ema_multi_tf`).

---

#### Family 3: EMA Returns (Pure SQL CTE)

File: `src/ta_lab2/scripts/returns/refresh_returns_ema_multi_tf.py`

Similar structure to bar returns but with `period` in the PK:

```python
# Source: refresh_returns_ema_multi_tf.py
DEFAULT_EMA_TABLE = "public.ema_multi_tf"
DEFAULT_OUT_TABLE = "public.returns_ema_multi_tf"
DEFAULT_STATE_TABLE = "public.returns_ema_multi_tf_state"
# PK: (id, venue_id, ts, tf, period)
# ON CONFLICT (id, venue_id, ts, tf, period) DO UPDATE SET ...
```

**_u PK verified from sync script:**
`PK_COLS = ["id", "venue_id", "ts", "tf", "period", "alignment_source"]`
(`alignment_source` IS in the PK — ready for direct writes)

**Migration approach:** Same as bar returns but adding `period` to the conflict clause
is already present. Add `alignment_source` literal to SELECT and to ON CONFLICT.

The source EMA table changes after EMA values migrate. If EMA values redirect
to `ema_multi_tf_u`, then EMA-returns builders must read from `ema_multi_tf_u`
as their source. Coordinate this: EMA values → verify → THEN redirect EMA-returns
source table. (The family ordering in CONTEXT.md — EMA then EMA-returns — handles this.)

**State table:** `returns_ema_multi_tf_state`, PK = `(id, venue_id, tf, period)`
with `last_ts` watermark column.

**No _load_last_snapshot_info.** No from_1d path.

---

#### Family 4: AMA Values (Python-Side DELETE + INSERT via BaseAMAFeature)

Files: `src/ta_lab2/features/ama/base_ama_feature.py` (write path)
       `src/ta_lab2/scripts/amas/base_ama_refresher.py` (orchestration)

The write path uses scoped DELETE + INSERT (not upsert):

```python
# Source: base_ama_feature.py
def write_to_db(self, df: pd.DataFrame) -> int:
    # 1. DELETE WHERE (id IN ids) AND (venue_id IN venue_ids)
    #    AND (tf = tf) AND (ts >= min_ts)
    # 2. df.to_sql(..., method=self._pg_upsert)
    # where _pg_upsert uses:
    #   ON CONFLICT (id, venue_id, ts, tf, indicator, params_hash) DO NOTHING

def _get_pk_columns(self):
    return ["id", "venue_id", "ts", "tf", "indicator", "params_hash"]
```

**_u PK verified from sync script:**
`AMA_PK_COLS = ["id", "venue_id", "ts", "tf", "indicator", "params_hash", "alignment_source"]`
(`alignment_source` IS in the PK — ready for direct writes)

**Migration approach for AMA values:**
1. Add `ALIGNMENT_SOURCE` constant to each AMA builder
2. Add `alignment_source` column to DataFrame before calling `write_to_db()`
3. Add `alignment_source` to `_get_pk_columns()` return value (or override in subclass)
4. Scope the DELETE in `write_to_db()` to also filter `alignment_source = :alignment_source`
   to avoid deleting rows from other builders when using shared _u table
5. Change `output_table` to `ama_multi_tf_u`

**State table:** `ama_multi_tf_state`, PK = `(id, venue_id, tf, indicator, params_hash)`
`AMAStateManager.save_states_batch()` handles bulk state updates.

**Scale note:** AMA tables are ~91M rows each. Bootstrap (if needed) and verification
will take significantly longer than other families. Allow extra time for row-count queries.

**No _load_last_snapshot_info.** No from_1d path.

---

#### Family 5: AMA Returns (Pure SQL CTE with DELETE + INSERT)

File: `src/ta_lab2/scripts/amas/refresh_returns_ama.py`

Single script handles all 5 AMA→returns table mappings via `TABLE_MAP`:

```python
# Source: refresh_returns_ama.py
TABLE_MAP = {
    "ama_multi_tf":               "returns_ama_multi_tf",
    "ama_multi_tf_cal_us":        "returns_ama_multi_tf_cal_us",
    "ama_multi_tf_cal_iso":       "returns_ama_multi_tf_cal_iso",
    "ama_multi_tf_cal_anchor_us": "returns_ama_multi_tf_cal_anchor_us",
    "ama_multi_tf_cal_anchor_iso":"returns_ama_multi_tf_cal_anchor_iso",
}
# Worker: DELETE WHERE id=:id [AND tf=:tf] then INSERT
# ON CONFLICT (id, venue_id, ts, tf, indicator, params_hash) DO NOTHING
```

**_u PK verified from sync script:**
`AMA_RETURNS_PK_COLS = ["id", "venue_id", "ts", "tf", "indicator", "params_hash", "alignment_source"]`
(`alignment_source` IS in the PK — ready for direct writes)

**Migration approach:** Single-script multi-source migration. Add `alignment_source`
literal to each SQL branch, add to ON CONFLICT clause, retarget output to
`returns_ama_multi_tf_u`. The DELETE scope must include `alignment_source` filter.

Note: After AMA values migrate to write directly to `ama_multi_tf_u`, the AMA-returns
builder must read from `ama_multi_tf_u` as its source. Coordinate ordering (AMA values
first, then AMA returns).

**No _load_last_snapshot_info.** No from_1d path.

---

### State Table Bootstrapping Decision Logic

Per CONTEXT.md, Claude decides bootstrap strategy per family. Research recommendation:

```sql
-- Check if state table is empty or stale
SELECT COUNT(*) FROM {family}_state;
-- If empty → bootstrap from output table using pg_index PK discovery
-- If populated → check max(last_ts) or max(last_timestamp)
--   If max(last_ts) >= (SELECT MAX(ts) FROM source_table) - 1 day
--     → state is current, skip bootstrap
--   Else → bootstrap stale entries
```

**EMA state extra consideration:** Once EMA builders write to `ema_multi_tf_u`, the
state manager queries `MAX(ts)` from `ema_multi_tf_u` grouped by `(id, venue_id, tf, period)`.
If other alignment_sources already have rows in `ema_multi_tf_u`, the state will reflect
all sources, not just this builder. Add `WHERE alignment_source = :alignment_source` to
the state update query in `EMAStateManager.update_state_from_output()`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DB PK discovery | Manual schema inspection | `pg_index` catalog query (Phase 76 pattern) | Already proven in Phase 76; avoids hardcoded column lists |
| Sync script deprecation | Delete file immediately | No-op wrapper with `print("DEPRECATED")` + exit(0) | Preserves CLI discoverability; avoids breaking automated scripts or cron jobs |
| Per-family verification | Custom verification script | Row-count SQL + spot-check queries | EXISTS pattern works; don't build a framework |
| alignment_source derivation | Complex logic | Simple string constant in each builder | The suffix is stable; no computation needed |
| State contamination fix | New state table | Add `WHERE alignment_source = :a` to existing query | Minimally invasive change |

---

## Common Pitfalls

### Pitfall 1: EMA _u Table Missing alignment_source in PK

**What goes wrong:** Builder writes rows with `alignment_source` populated, but the
database PK for `ema_multi_tf_u` is `(id, venue_id, ts, tf, period)` without
`alignment_source`. ON CONFLICT resolution works but rows from different alignment_sources
for the same (id, ts, tf, period) will conflict and overwrite each other.

**Why it happens:** The current EMA sync script (`sync_ema_multi_tf_u.py`) uses
`ON CONFLICT (id, venue_id, ts, tf, period) DO NOTHING` — implying `alignment_source`
may not be in the DB-level PK constraint.

**How to avoid:** Before any EMA migration work, run:
```sql
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'ema_multi_tf_u'::regclass AND contype = 'p';
```
If `alignment_source` is absent, run an `ALTER TABLE` to drop and recreate the PK
including `alignment_source` before redirecting any builders.

**Warning signs:** Multiple rows for the same (id, ts, tf, period) after migration,
or unexpected row counts being lower than expected.

---

### Pitfall 2: AMA write_to_db DELETE Scope Too Broad

**What goes wrong:** `BaseAMAFeature.write_to_db()` does a DELETE before INSERT to
handle idempotent recomputation. The current DELETE is scoped to
`(ids, venue_ids, tf, ts >= min_ts)`. When targeting `ama_multi_tf_u`, this DELETE
would also erase rows written by other alignment_sources for the same ids/tf/ts range.

**Why it happens:** The original design assumed each builder owns its own table.
In a shared _u table, scoped DELETE must additionally filter by `alignment_source`.

**How to avoid:** Add `AND alignment_source = :alignment_source` to the DELETE WHERE
clause in `write_to_db()` (either override in subclass or add param to base class).

**Warning signs:** Row counts in `ama_multi_tf_u` for a given alignment_source
dropping to zero after another alignment_source runs.

---

### Pitfall 3: EMA State Manager Aggregating Across All alignment_sources

**What goes wrong:** `EMAStateManager.update_state_from_output()` reads
`MAX(ts) FROM ema_multi_tf_u GROUP BY (id, venue_id, tf, period)`. After migration,
the _u table contains rows from all 5 builders. The state update sees the MAX(ts)
across all sources, not just this builder's. This causes the builder to skip rows
that haven't been computed for this specific alignment yet.

**Why it happens:** State was designed for a single-source output table.

**How to avoid:** Extend `update_state_from_output()` to accept an optional
`alignment_source` filter parameter. When building to `ema_multi_tf_u`,
add `WHERE alignment_source = :alignment_source` to the state query.

**Warning signs:** After migration, EMA builder reports 0 new rows on every run
except full refresh.

---

### Pitfall 4: Returns Builder Reading from Silo Table After Values Table Migrated

**What goes wrong:** EMA-returns builder reads from `public.ema_multi_tf` (the silo).
After EMA-values migration, new EMA rows go to `ema_multi_tf_u` only. The returns
builder sees no new data and produces no returns for new bars.

**Why it happens:** Source table reference in returns builder not updated after
values builder redirect.

**How to avoid:** When migrating EMA-values, update the EMA-returns builder's
`DEFAULT_EMA_TABLE` to `ema_multi_tf_u` in the same PR or immediately after.
Same applies for AMA-values → AMA-returns.

**Warning signs:** Returns tables stop growing after values migration.

---

### Pitfall 5: Missing `alignment_source` Column in _INSERT_COLS

**What goes wrong:** SQL `_INSERT_COLS` string doesn't include `alignment_source`,
causing an `ERROR: column "alignment_source" of relation "returns_bars_multi_tf_u"
does not exist` or silently omitting the column (NULL in the _u table).

**How to avoid:** For each SQL-CTE family (bar-returns, EMA-returns, AMA-returns),
add `alignment_source` to the INSERT column list AND include
`CAST(:alignment_source AS text)` in the SELECT expression. Pass
`{"alignment_source": ALIGNMENT_SOURCE}` in the execute params dict.

---

### Pitfall 6: Sync Disable Before Verify Completes

**What goes wrong:** Sync script is disabled before row-count parity is confirmed.
If the builder has a bug, data gaps can go undetected.

**How to avoid:** Always: (1) redirect builder → (2) run one full refresh → (3) verify
row counts → (4) then disable sync. Never disable sync first.

---

## Code Examples

### Pattern: Adding alignment_source to a Pure-SQL CTE Builder

```python
# Source: pattern derived from Phase 76 + bar-returns code structure

ALIGNMENT_SOURCE = "multi_tf"   # Set per-script to the appropriate suffix

# In _INSERT_COLS (add alignment_source at end):
_INSERT_COLS = (
    'id, venue_id, "timestamp", tf, venue, venue_rank, roll,\n'
    + ",\n".join(_VALUE_COLS)
    + ",\ningested_at, alignment_source"
)

# In the CTE SELECT expression (add literal at end):
# ... previous columns ...
# now(), -- ingested_at
# CAST(:alignment_source AS text)

# In ON CONFLICT clause:
# ON CONFLICT (id, "timestamp", tf, venue_id, alignment_source) DO UPDATE SET ...

# Pass alignment_source as a bind parameter:
params = {
    "id": one_id,
    "tf": one_tf,
    "venue_id": one_venue_id,
    "alignment_source": ALIGNMENT_SOURCE,
}
conn.execute(text(sql), params)
```

### Pattern: Scoping AMA DELETE by alignment_source

```python
# Source: extension of base_ama_feature.py write_to_db() pattern

# Current DELETE (too broad for shared _u table):
# DELETE FROM ama_multi_tf_u
# WHERE id = ANY(:ids) AND venue_id = ANY(:venue_ids)
#   AND tf = :tf AND ts >= :min_ts

# Corrected DELETE (scoped by alignment_source):
# DELETE FROM ama_multi_tf_u
# WHERE id = ANY(:ids) AND venue_id = ANY(:venue_ids)
#   AND tf = :tf AND ts >= :min_ts
#   AND alignment_source = :alignment_source
```

### Pattern: EMA State Query Scoped by alignment_source

```python
# Source: extension of EMAStateManager.update_state_from_output()

# Current (unscoped, aggregates all sources):
# SELECT id, venue_id, tf, period, MAX(ts) as last_ts
# FROM ema_multi_tf_u
# GROUP BY id, venue_id, tf, period

# Corrected (scoped to this builder's alignment_source):
# SELECT id, venue_id, tf, period, MAX(ts) as last_ts
# FROM ema_multi_tf_u
# WHERE alignment_source = :alignment_source
# GROUP BY id, venue_id, tf, period
```

### Pattern: No-op Sync Script Deprecation

```python
# Source: sync_price_bars_multi_tf_u.py (Phase 76 proven pattern)

"""
DEPRECATED: sync_returns_bars_multi_tf_u.py

This script is now a no-op. As of Phase 77, bar-returns builders write
directly to returns_bars_multi_tf_u with alignment_source stamped.
This script is retained for CLI discoverability only.
"""
import sys

def main() -> None:
    print(
        "[ret_bars_u_sync] DEPRECATED: direct-write active. "
        "Builders now write to returns_bars_multi_tf_u directly. "
        "This sync script is a no-op and will be removed in a future phase."
    )
    sys.exit(0)

if __name__ == "__main__":
    main()
```

### Verification Queries Per Family

```sql
-- Bar returns parity check
SELECT alignment_source, COUNT(*) as n_rows
FROM returns_bars_multi_tf_u
GROUP BY alignment_source
ORDER BY alignment_source;

-- Compare against individual silo tables
SELECT 'multi_tf' as src, COUNT(*) FROM returns_bars_multi_tf
UNION ALL
SELECT 'multi_tf_cal_us', COUNT(*) FROM returns_bars_multi_tf_cal_us
UNION ALL
SELECT 'multi_tf_cal_iso', COUNT(*) FROM returns_bars_multi_tf_cal_iso
UNION ALL
SELECT 'multi_tf_cal_anchor_us', COUNT(*) FROM returns_bars_multi_tf_cal_anchor_us
UNION ALL
SELECT 'multi_tf_cal_anchor_iso', COUNT(*) FROM returns_bars_multi_tf_cal_anchor_iso;

-- EMA parity (same structure, swap table names)
-- AMA parity: ~91M rows each — add LIMIT or sample by specific ids
SELECT alignment_source, COUNT(*) FROM ama_multi_tf_u
GROUP BY alignment_source;
```

---

## Per-Family Summary Table

| Family | Write Mechanism | _u PK has alignment_source? | State Table PK | Extra PK Cols vs Price Bars | _load_last_snapshot_info? | from_1d path? |
|--------|----------------|---------------------------|---------------|---------------------------|--------------------------|---------------|
| Bar returns | Pure SQL CTE | YES | (id, venue_id, tf) | None (timestamp vs ts) | No | No |
| EMA values | BaseEMAFeature._pg_upsert | VERIFY FIRST | (id, venue_id, tf, period) | period | No | No |
| EMA returns | Pure SQL CTE | YES | (id, venue_id, tf, period) | period | No | No |
| AMA values | BaseAMAFeature.write_to_db (DELETE + INSERT) | YES | (id, venue_id, tf, indicator, params_hash) | indicator, params_hash | No | No |
| AMA returns | Pure SQL CTE (DELETE + INSERT) | YES | varies per table | indicator, params_hash | No | No |

---

## State of the Art

| Old Approach | Current Approach | Phase | Impact |
|--------------|-----------------|-------|--------|
| Silo table + sync job | Direct _u write with alignment_source | 76 (price bars) | Eliminates 2-step latency, removes sync scripts |
| upsert_bars() only | Per-family write path adaptation | 77 | Each family needs its own migration pattern |
| EMA sync: alignment_source not in PK | Must add to DB PK before migration | 77 | Schema migration required before EMA redirect |

---

## Open Questions

1. **ema_multi_tf_u PK definition**
   - What we know: sync script uses `ON CONFLICT (id, venue_id, ts, tf, period)` — no alignment_source
   - What's unclear: whether the DB-level PRIMARY KEY constraint includes `alignment_source`
   - Recommendation: Run `pg_constraint` query before planning EMA migration tasks. If missing, plan an ALTER TABLE step as the first EMA task.

2. **AMA state per alignment_source**
   - What we know: `AMAStateManager` uses `(id, venue_id, tf, indicator, params_hash)` as state PK
   - What's unclear: whether state reads are already scoped per-table or read from the shared output
   - Recommendation: Inspect `save_states_batch()` and `load_state()` in `ama_state_manager.py` to confirm state doesn't mix alignment_sources.

3. **EMA-returns source table after EMA-values migration**
   - What we know: EMA-returns builders read from `public.ema_multi_tf` by default
   - What's unclear: exact timing of source table redirect
   - Recommendation: Plan explicitly — migrate EMA-values in Step A, update EMA-returns `DEFAULT_EMA_TABLE` in Step B (same plan or immediately sequential).

4. **AMA row-count margins**
   - What we know: AMA tables are ~91M rows each
   - What's unclear: expected parity tolerance (1%? 0.1%?)
   - Recommendation: Use 0.5% tolerance for AMA (larger tables have more natural variation from partial recomputes). Tighten to 0.1% for bar-returns (smaller, simpler).

---

## Sources

### Primary (HIGH confidence — source code)
- `src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf.py` — bar returns builder, state table DDL, ON CONFLICT clause
- `src/ta_lab2/scripts/returns/sync_returns_bars_multi_tf_u.py` — _u PK for bar returns
- `src/ta_lab2/scripts/emas/sync_ema_multi_tf_u.py` — EMA _u ON CONFLICT clause (alignment_source absent)
- `src/ta_lab2/scripts/returns/sync_returns_ema_multi_tf_u.py` — EMA returns _u PK
- `src/ta_lab2/scripts/amas/sync_ama_multi_tf_u.py` — AMA _u PK with alignment_source
- `src/ta_lab2/scripts/amas/sync_returns_ama_multi_tf_u.py` — AMA returns _u PK
- `src/ta_lab2/features/m_tf/base_ema_feature.py` — write_to_db, _pg_upsert, _get_pk_columns
- `src/ta_lab2/features/ama/base_ama_feature.py` — write_to_db DELETE+INSERT pattern
- `src/ta_lab2/scripts/amas/ama_state_manager.py` — state table PK
- `src/ta_lab2/scripts/emas/ema_state_manager.py` — state table PK, update_state_from_output
- `src/ta_lab2/scripts/amas/refresh_returns_ama.py` — TABLE_MAP, single-script multi-source
- `src/ta_lab2/scripts/returns/refresh_returns_ema_multi_tf.py` — EMA returns state PK
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_us.py` — Phase 76 pilot reference
- `src/ta_lab2/scripts/run_daily_refresh.py` — confirmed zero sync script calls
- `src/ta_lab2/scripts/bars/run_all_bar_builders.py` — confirmed zero sync script calls

---

## Metadata

**Confidence breakdown:**
- Per-family inventory (builder scripts, tables, PKs): HIGH — read directly from source
- Write path mechanics (SQL CTE vs Python upsert): HIGH — read from implementation
- EMA _u PK with alignment_source: LOW until DB verified — sync script implies it may be absent
- AMA _u PK with alignment_source: HIGH — confirmed in sync script constants
- State manager contamination risk: HIGH — logic analyzed from source
- Orchestrator references to sync scripts: HIGH — grep confirmed zero matches

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable codebase; only invalidated by schema changes)
