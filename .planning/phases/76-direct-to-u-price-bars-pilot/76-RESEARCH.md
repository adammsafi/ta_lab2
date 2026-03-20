# Phase 76: Direct-to-_u Price Bars (Pilot) - Research

**Researched:** 2026-03-20
**Domain:** Bar builder migration -- write directly to `price_bars_multi_tf_u` with `alignment_source`, bypassing siloed tables and the sync script
**Confidence:** HIGH

## Summary

Phase 76 migrates all 5 multi-TF price bar builders to write directly to `price_bars_multi_tf_u` with a hardcoded `alignment_source` value, instead of writing to the 5 siloed tables (`price_bars_multi_tf`, `price_bars_multi_tf_cal_us`, etc.) which are then UNIONed into `_u` by `sync_price_bars_multi_tf_u.py`.

The 5 bar builders all inherit from `BaseBarBuilder` and delegate actual DB writes to `upsert_bars()` in `common_snapshot_contract.py`. The target `bars_table` is controlled by `BarBuilderConfig.bars_table` and the `get_output_table_name()` method in each builder subclass. Redirecting writes to `_u` requires: (1) changing the output table, (2) adding `alignment_source` to each row before upsert, and (3) populating state tables from `_u` actual MAX(ts) before the first direct-write run so incremental watermarks are correct.

The `_u` table PK is `(id, tf, bar_seq, venue_id, timestamp, alignment_source)` — different from siloed table PKs which use `(id, tf, bar_seq, venue_id, timestamp)` (no `alignment_source`). The `upsert_bars()` function has a `conflict_cols` parameter that defaults to `("id", "tf", "bar_seq", "venue", "timestamp")` and must be updated to include `alignment_source` in the conflict target.

The CHECK constraint on `alignment_source` in `price_bars_multi_tf_u` was added by Phase 74-02. The valid values are: `multi_tf`, `multi_tf_cal_us`, `multi_tf_cal_iso`, `multi_tf_cal_anchor_us`, `multi_tf_cal_anchor_iso`.

**Primary recommendation:** Each builder gets an `ALIGNMENT_SOURCE` class constant, sets it on every row before calling `upsert_bars()`, and passes it as part of `conflict_cols`. State tables are pre-populated from `_u` MAX(ts) before the first run. The sync script is disabled by removing it from `run_all_bar_builders.py` and `run_daily_refresh.py` (neither currently calls it — it is invoked standalone; confirming its invocation path is critical before disabling).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.x | `upsert_bars()` write pipeline, engine management | Already used in all bar builders |
| pandas | 2.x | DataFrame manipulation before upsert | Already used; `upsert_bars()` accepts DataFrame |
| polars | 0.x | Vectorized bar computation in some builders | Already used in full-build paths |

### No New Libraries Required
This phase adds no new dependencies. All mechanisms needed (`upsert_bars`, `conflict_cols`, `BarBuilderConfig`) already exist.

---

## Architecture Patterns

### Current Architecture (Before Phase 76)

```
cmc_price_histories7
        |
        v
refresh_price_bars_multi_tf.py  --> price_bars_multi_tf
refresh_price_bars_multi_tf_cal_us.py  --> price_bars_multi_tf_cal_us
refresh_price_bars_multi_tf_cal_iso.py --> price_bars_multi_tf_cal_iso
refresh_price_bars_multi_tf_cal_anchor_us.py  --> price_bars_multi_tf_cal_anchor_us
refresh_price_bars_multi_tf_cal_anchor_iso.py --> price_bars_multi_tf_cal_anchor_iso
                                                             |
                                                             v
                                             sync_price_bars_multi_tf_u.py
                                             (UNION ALL from all 5 tables)
                                                             |
                                                             v
                                                price_bars_multi_tf_u
                                          PK: (id, tf, bar_seq, venue_id,
                                               timestamp, alignment_source)
```

### Target Architecture (After Phase 76)

```
cmc_price_histories7
        |
        v
refresh_price_bars_multi_tf.py  --> price_bars_multi_tf_u (alignment_source='multi_tf')
refresh_price_bars_multi_tf_cal_us.py  --> price_bars_multi_tf_u (alignment_source='multi_tf_cal_us')
refresh_price_bars_multi_tf_cal_iso.py --> price_bars_multi_tf_u (alignment_source='multi_tf_cal_iso')
refresh_price_bars_multi_tf_cal_anchor_us.py --> price_bars_multi_tf_u (alignment_source='multi_tf_cal_anchor_us')
refresh_price_bars_multi_tf_cal_anchor_iso.py --> price_bars_multi_tf_u (alignment_source='multi_tf_cal_anchor_iso')

sync_price_bars_multi_tf_u.py -- DISABLED (no longer invoked)
price_bars_multi_tf, price_bars_multi_tf_cal_{us,iso}, price_bars_multi_tf_cal_anchor_{us,iso} -- still exist (dropped in Phase 78)
```

### Pattern 1: Changing Output Table per Builder

Each builder has two places that determine the output table:

1. **Class constant**: `OUTPUT_TABLE = "public.price_bars_multi_tf"` (or cal_us, etc.)
2. **`get_output_table_name()` method**: returns `self.OUTPUT_TABLE`

To redirect output:
```python
# In each builder class (e.g. MultiTFBarBuilder):
ALIGNMENT_SOURCE = "multi_tf"           # NEW: alignment constant
OUTPUT_TABLE = "public.price_bars_multi_tf_u"  # CHANGED: target _u table
```

The `DEFAULT_BARS_TABLE` constant is also used in the CLI `create_argument_parser()` method as a help text default and as the `args.bars_table` default. Both must change, or the CLI must be updated to accept `--bars-table` with the _u table as default.

### Pattern 2: Adding alignment_source to Rows Before Upsert

In each builder's `build_bars_for_id()` method, before calling `upsert_bars()`:

```python
# Source: common_snapshot_contract.py upsert_bars() — accepts DataFrame
# Add alignment_source column to bars DataFrame before upsert
bars_pd["alignment_source"] = self.ALIGNMENT_SOURCE
```

The `upsert_bars()` function in `common_snapshot_contract.py` filters to `valid_cols` (line 961-1010). `alignment_source` is NOT currently in that list. This is critical: **`alignment_source` must be added to `valid_cols` in `upsert_bars()` or the column will be silently dropped**.

Current `valid_cols` in `upsert_bars()` (lines 962-1009 of `common_snapshot_contract.py`):
```python
valid_cols = [
    "id", "tf", "tf_days", "bar_seq", "bar_anchor_offset",
    "time_open", "time_close", "time_high", "time_low",
    "time_open_bar", "time_close_bar",
    "open", "high", "low", "close", "volume", "market_cap",
    "ingested_at", "timestamp", "last_ts_half_open",
    "pos_in_bar", "is_partial_start", "is_partial_end",
    "is_missing_days", "count_days", "count_days_remaining",
    "count_missing_days", ... "venue", "venue_id", "venue_rank",
]
# NOTE: "alignment_source" is MISSING from this list
```

### Pattern 3: Updating conflict_cols for _u Table PK

The `upsert_bars()` function takes `conflict_cols` parameter (default: `("id", "tf", "bar_seq", "venue", "timestamp")`). The _u table PK is `(id, tf, bar_seq, venue_id, timestamp, alignment_source)`.

Each builder call to `upsert_bars()` must pass:
```python
upsert_bars(
    bars_pd,
    db_url=self.config.db_url,
    bars_table=self.get_output_table_name(),
    conflict_cols=("id", "tf", "bar_seq", "venue_id", "timestamp", "alignment_source"),
)
```

Note: siloed tables use `venue` (TEXT) in conflict, _u table uses `venue_id` (SMALLINT). The column `venue_id` is already set on bars (bar builders set it via `venue_id` column in `derive_multi_tf_bars()` or in `_build_bars_for_id_tf()`). Confirm `venue_id` is populated on the bars DataFrame before upsert — it is NOT the default in the `REQUIRED_COL_DEFAULTS` dict (defaults to `"venue": "CMC_AGG"`, `"venue_rank": 50`).

### Pattern 4: State Table Pre-Population (Watermark Bootstrap)

The state tables track `last_time_close` per `(id, tf, venue_id)`. Before the first direct-write run, the state tables are empty (they tracked writes to the old siloed tables, not to `_u`). If state is empty, builders default to full-history rebuild for every asset — expensive but safe.

The phase requires state tables to be populated from `_u` actual MAX(ts) before the first direct-write run. This avoids a full rebuild for 4M+ rows.

Bootstrap query pattern per builder:
```sql
-- Populate state table from existing _u data (one-time bootstrap)
-- For price_bars_multi_tf_state (standard/multi_tf):
INSERT INTO public.price_bars_multi_tf_state (id, tf, venue_id, venue, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at)
SELECT
    u.id,
    u.tf,
    u.venue_id,
    COALESCE(dv.venue, 'CMC_AGG') AS venue,
    MIN(u.timestamp) AS daily_min_seen,
    MAX(u.timestamp) AS daily_max_seen,
    MAX(u.bar_seq) AS last_bar_seq,
    MAX(u.timestamp) AS last_time_close,
    NOW() AS updated_at
FROM public.price_bars_multi_tf_u u
LEFT JOIN public.dim_venues dv ON dv.venue_id = u.venue_id
WHERE u.alignment_source = 'multi_tf'
GROUP BY u.id, u.tf, u.venue_id, dv.venue
ON CONFLICT (id, tf, venue_id) DO UPDATE SET
    last_time_close = EXCLUDED.last_time_close,
    last_bar_seq = EXCLUDED.last_bar_seq,
    daily_max_seen = EXCLUDED.daily_max_seen,
    updated_at = NOW();
```

This must be done separately for each of the 5 alignment_source values (each populates its own state table).

**Important**: The state table PK is `(id, tf)` per `ensure_state_table()` (lines 690-727 of `common_snapshot_contract.py`). But `upsert_state()` (line 809) supports `with_venue=True` which makes PK `(id, tf, venue_id)`. Calendar builders use `with_venue=True`. The bootstrap INSERT must match the actual state table PK for each builder type.

### Pattern 5: Disabling sync_price_bars_multi_tf_u.py

**Finding:** `sync_price_bars_multi_tf_u.py` is NOT invoked from `run_daily_refresh.py` or `run_all_bar_builders.py`. It is run standalone via:
```
python -m ta_lab2.scripts.bars.sync_price_bars_multi_tf_u
```
There is NO orchestrator that automatically calls it. Disabling means: (a) adding a `--disabled` flag that prints a deprecation message and exits 0, OR (b) removing it from the CLI entry points in `pyproject.toml`. Either approach satisfies success criterion #4.

**Recommended approach:** Keep the file but have `main()` print a deprecation notice and exit 0 immediately. Do not delete the file — Phase 78 will remove it along with the siloed tables.

### Anti-Patterns to Avoid

- **Writing to both siloed table and _u**: Double-write complexity and conflicts. Write only to _u.
- **Reusing the existing state table names unchanged**: The existing state tables tracked writes to siloed tables. After Phase 76, state tables still work correctly because they track `(id, tf, venue_id) -> last_time_close` regardless of which table was the destination. No state table schema changes are needed.
- **Relying on `upsert_bars()` default `conflict_cols`**: Default is `("id", "tf", "bar_seq", "venue", "timestamp")` which is wrong for the _u table. Always pass explicit `conflict_cols`.
- **Forgetting `alignment_source` in `valid_cols`**: The `upsert_bars()` function silently strips columns not in `valid_cols`. If `alignment_source` is not added to `valid_cols`, it gets dropped and the INSERT will fail with a NOT NULL constraint violation.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DB upsert to _u | Custom INSERT logic | `upsert_bars()` with updated `conflict_cols` | Already handles OHLC sanity, NaT->None, schema normalization |
| State watermark bootstrap | Complex migration script | Single SQL INSERT...SELECT with ON CONFLICT | Standard upsert pattern, idempotent |
| alignment_source validation | Runtime Python checks | CHECK constraint already on table (Phase 74-02) | DB enforces it; wrong value raises immediately |
| Disabling sync script | Delete the file | Add deprecation guard in `main()` | Phase 78 cleans up; don't cause cascading breakage |

---

## Common Pitfalls

### Pitfall 1: alignment_source Silently Dropped by upsert_bars()
**What goes wrong:** `upsert_bars()` filters the DataFrame to `valid_cols` (lines 962-1009 of `common_snapshot_contract.py`). `alignment_source` is not in this list. The column is silently dropped before the INSERT, causing a NOT NULL constraint violation on the `_u` table.
**Why it happens:** `valid_cols` was written for the siloed tables which don't have `alignment_source`.
**How to avoid:** Add `"alignment_source"` to the `valid_cols` list in `upsert_bars()` BEFORE modifying any builders.
**Warning signs:** `psycopg2.errors.NotNullViolation: null value in column "alignment_source"` on first run.

### Pitfall 2: Wrong conflict_cols for _u Table PK
**What goes wrong:** Siloed table PKs are `(id, tf, bar_seq, venue_id, timestamp)`. The _u table PK is `(id, tf, bar_seq, venue_id, timestamp, alignment_source)`. Using the default `conflict_cols` or the siloed-table conflict cols causes either duplicate inserts (if conflict target is too narrow) or constraint errors (if using `venue` TEXT vs `venue_id` SMALLINT).
**Why it happens:** `upsert_bars()` default conflict_cols use `venue` (TEXT), but _u table PK uses `venue_id` (SMALLINT).
**How to avoid:** Always pass `conflict_cols=("id", "tf", "bar_seq", "venue_id", "timestamp", "alignment_source")` when upserting to _u.
**Warning signs:** `ON CONFLICT DO UPDATE command cannot affect row a second time` error, or duplicate rows in _u.

### Pitfall 3: State Tables Not Pre-Populated (Full Rebuild on First Run)
**What goes wrong:** Each builder checks its state table for `last_time_close`. If state table is empty (no previous runs targeting _u), the builder does full-history rebuild for every asset — processing 4M+ rows unnecessarily.
**Why it happens:** State tables tracked writes to siloed tables, not _u.
**How to avoid:** Execute the bootstrap SQL for all 5 state tables before the first direct-write run. The bootstrap populates `last_time_close` from `_u` MAX(ts) per `(id, tf, venue_id)`.
**Warning signs:** First run takes 2+ hours instead of minutes; log shows "No existing state found - will build full history" for hundreds of IDs.

### Pitfall 4: venue_id Not Set on Bars DataFrame
**What goes wrong:** The _u table PK uses `venue_id` (SMALLINT). If bars DataFrame lacks `venue_id`, `conflict_cols` referencing `venue_id` will fail with a key error or produce wrong SQL.
**Why it happens:** Some builder paths set `venue` (TEXT) but not `venue_id`. The `REQUIRED_COL_DEFAULTS` dict does not include `venue_id`.
**How to avoid:** Verify that every builder's output DataFrame includes `venue_id`. Calendar builders call `_resolve_venue_id(venue)` to populate it. The standard `MultiTFBarBuilder` sets venue_id via `load_daily_prices_for_id()` which joins `price_bars_1d` for `venue_rank` but venue_id comes from `price_bars_1d.venue_id`. Check this explicitly for each builder.
**Warning signs:** `KeyError: 'venue_id'` or NULL venue_id values triggering FK constraint violation against dim_venues.

### Pitfall 5: delete_bars_for_id_tf() Deletes From Wrong Table
**What goes wrong:** During full rebuild or backfill, builders call `_delete_bars_and_state()` which calls `delete_bars_for_id_tf()`. This deletes from `self.get_output_table_name()`. After the redirect to `_u`, this will delete rows from `price_bars_multi_tf_u`. Since `alignment_source` is part of the PK but not part of the DELETE clause in `delete_bars_for_id_tf()`, the function will delete ALL alignment_source variants for that (id, tf, venue).
**Why it happens:** `delete_bars_for_id_tf()` uses `WHERE id=:id AND tf=:tf [AND venue=:venue]` — no `alignment_source` filter.
**How to avoid:** Extend `delete_bars_for_id_tf()` to accept an optional `alignment_source` parameter, or scope the DELETE with `AND alignment_source = :alignment_source` in each builder's `_delete_bars_and_state()` method.
**Warning signs:** After full rebuild of one builder, other alignment_source variants disappear from _u (row count drops dramatically).

### Pitfall 6: row count verification must filter by alignment_source
**What goes wrong:** Success criterion #3 says row counts in `_u` per `alignment_source` match pre-migration totals. If the verification query counts ALL rows in _u without filtering by `alignment_source`, counts will appear to match (other variants haven't changed) even if one variant is broken.
**How to avoid:** Always verify:
```sql
SELECT alignment_source, COUNT(*)
FROM public.price_bars_multi_tf_u
GROUP BY alignment_source;
```
Compare each alignment_source count to the count in the corresponding siloed table.

---

## Code Examples

### Adding alignment_source to valid_cols (single-file change)
```python
# Source: src/ta_lab2/scripts/bars/common_snapshot_contract.py
# In upsert_bars(), add "alignment_source" to valid_cols list:

valid_cols = [
    "id",
    "tf",
    "tf_days",
    "bar_seq",
    "bar_anchor_offset",
    "alignment_source",   # ADD THIS LINE
    "time_open",
    # ... rest unchanged
    "venue",
    "venue_id",
    "venue_rank",
]
```

### Builder Class Change Pattern (same for all 5 builders)
```python
# Example for MultiTFBarBuilder in refresh_price_bars_multi_tf.py

class MultiTFBarBuilder(BaseBarBuilder):
    ALIGNMENT_SOURCE = "multi_tf"                     # ADD
    STATE_TABLE = "public.price_bars_multi_tf_state"  # unchanged
    OUTPUT_TABLE = "public.price_bars_multi_tf_u"     # CHANGED from price_bars_multi_tf

    # In build_bars_for_id() or _build_bars_for_id_tf():
    # Before calling upsert_bars():
    bars_pd["alignment_source"] = self.ALIGNMENT_SOURCE

    # Call upsert_bars with updated conflict_cols:
    upsert_bars(
        bars_pd,
        db_url=self.config.db_url,
        bars_table=self.get_output_table_name(),
        conflict_cols=("id", "tf", "bar_seq", "venue_id", "timestamp", "alignment_source"),
    )
```

### The 5 Builders and Their alignment_source Values
```python
# refresh_price_bars_multi_tf.py (MultiTFBarBuilder)
ALIGNMENT_SOURCE = "multi_tf"
OUTPUT_TABLE = "public.price_bars_multi_tf_u"

# refresh_price_bars_multi_tf_cal_us.py (CalendarUSBarBuilder)
ALIGNMENT_SOURCE = "multi_tf_cal_us"
OUTPUT_TABLE = "public.price_bars_multi_tf_u"

# refresh_price_bars_multi_tf_cal_iso.py (CalendarISOBarBuilder)
ALIGNMENT_SOURCE = "multi_tf_cal_iso"
OUTPUT_TABLE = "public.price_bars_multi_tf_u"

# refresh_price_bars_multi_tf_cal_anchor_us.py (AnchorCalendarUSBarBuilder)
ALIGNMENT_SOURCE = "multi_tf_cal_anchor_us"
OUTPUT_TABLE = "public.price_bars_multi_tf_u"

# refresh_price_bars_multi_tf_cal_anchor_iso.py (AnchorCalendarISOBarBuilder)
ALIGNMENT_SOURCE = "multi_tf_cal_anchor_iso"
OUTPUT_TABLE = "public.price_bars_multi_tf_u"
```

### State Table Bootstrap SQL (run once before first direct-write run)
```sql
-- Bootstrap state tables from existing _u data
-- Run once per builder, before the first direct-write run.

-- 1. price_bars_multi_tf_state (standard, alignment_source='multi_tf')
INSERT INTO public.price_bars_multi_tf_state
    (id, tf, venue_id, venue, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at)
SELECT
    u.id,
    u.tf,
    u.venue_id,
    COALESCE(dv.venue, 'CMC_AGG') AS venue,
    MIN(u.timestamp) AS daily_min_seen,
    MAX(u.timestamp) AS daily_max_seen,
    MAX(u.bar_seq) AS last_bar_seq,
    MAX(u.timestamp) AS last_time_close,
    NOW() AS updated_at
FROM public.price_bars_multi_tf_u u
LEFT JOIN public.dim_venues dv ON dv.venue_id = u.venue_id
WHERE u.alignment_source = 'multi_tf'
GROUP BY u.id, u.tf, u.venue_id, dv.venue
ON CONFLICT (id, tf) DO UPDATE SET
    last_time_close = GREATEST(price_bars_multi_tf_state.last_time_close, EXCLUDED.last_time_close),
    last_bar_seq    = EXCLUDED.last_bar_seq,
    daily_max_seen  = EXCLUDED.daily_max_seen,
    updated_at      = NOW();
-- Repeat with alignment_source = 'multi_tf_cal_us' -> price_bars_multi_tf_cal_us_state
-- Repeat with alignment_source = 'multi_tf_cal_iso' -> price_bars_multi_tf_cal_iso_state
-- etc.
```

**Note on state table PK:** `ensure_state_table()` creates state tables with `PRIMARY KEY (id, tf)`. The `with_venue=True` path adds `venue_id` to the PK. Calendar builders call `ensure_state_table(db_url, state_table, with_tz=True)` which uses `(id, tf)` as PK. The bootstrap ON CONFLICT target must match the actual state table PK. Inspect each state table's actual PK before writing the bootstrap.

### Scoped Delete (Pitfall 5 fix)
```python
# In each builder's _delete_bars_and_state() method:
# Replace the current delete_bars_for_id_tf() call with a scoped version:

def _delete_bars_and_state(self, id_: int, tf: str, venue: str | None = None) -> None:
    """Delete bars for this builder's alignment_source only."""
    engine = get_engine(self.config.db_url)
    params: dict = {"id": int(id_), "tf": tf, "alignment_source": self.ALIGNMENT_SOURCE}
    where = "WHERE id = :id AND tf = :tf AND alignment_source = :alignment_source"
    if venue is not None:
        where += " AND venue_id = (SELECT venue_id FROM dim_venues WHERE venue = :venue LIMIT 1)"
        params["venue"] = venue
    sql = text(f"DELETE FROM {self.get_output_table_name()} {where};")
    with engine.begin() as conn:
        conn.execute(sql, params)
    # ... also delete state (unchanged)
```

### Disabling sync_price_bars_multi_tf_u.py
```python
# src/ta_lab2/scripts/bars/sync_price_bars_multi_tf_u.py
def main() -> None:
    print(
        "[DEPRECATED] sync_price_bars_multi_tf_u.py is disabled. "
        "Bar builders now write directly to price_bars_multi_tf_u "
        "(Phase 76). This script will be removed in Phase 78."
    )
    # Exit 0 so any pipeline that still calls it doesn't fail
    return

if __name__ == "__main__":
    main()
```

### Row Count Verification SQL
```sql
-- Pre-migration: count siloed tables
SELECT 'price_bars_multi_tf' AS src, COUNT(*) FROM public.price_bars_multi_tf
UNION ALL
SELECT 'price_bars_multi_tf_cal_us', COUNT(*) FROM public.price_bars_multi_tf_cal_us
UNION ALL
SELECT 'price_bars_multi_tf_cal_iso', COUNT(*) FROM public.price_bars_multi_tf_cal_iso
UNION ALL
SELECT 'price_bars_multi_tf_cal_anchor_us', COUNT(*) FROM public.price_bars_multi_tf_cal_anchor_us
UNION ALL
SELECT 'price_bars_multi_tf_cal_anchor_iso', COUNT(*) FROM public.price_bars_multi_tf_cal_anchor_iso;

-- Post-migration: count _u table per alignment_source
SELECT alignment_source, COUNT(*)
FROM public.price_bars_multi_tf_u
GROUP BY alignment_source
ORDER BY alignment_source;
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `cmc_price_bars_multi_tf_u` | `price_bars_multi_tf_u` (no prefix) | Phase 73 (Mar 2026) | Table renamed, all references updated |
| No `venue_id` in PKs | `venue_id` SMALLINT in PKs | Phase 73 (Mar 2026) | _u table PK includes venue_id |
| No CHECK on alignment_source | CHECK constraint on all 6 _u tables | Phase 74-02 (Mar 2026) | Wrong values fail immediately at DB |
| alignment_source derived from table name at sync time | Still string-derived (this phase fixes it for bars family) | Not yet | Phase 76 eliminates derivation — builders hardcode it |
| UNION ALL sync pattern | Direct write (this phase) | Not yet | Removes intermediate siloed tables dependency |

**Currently outdated in the codebase:**
- `sync_price_bars_multi_tf_u.py` PK_COLS list uses `"venue_id"` but the old DDL (before migration) used `"venue"` — it has been updated to `venue_id` in the sync script, confirming the script is already migration-aware.
- The sync script derives `alignment_source` from table name string stripping (`price_bars_` prefix removed). After Phase 76, this derivation is no longer the source of truth.

---

## Open Questions

1. **State table PK for calendar builders (with_venue=True)**
   - What we know: `upsert_state()` with `with_venue=True` makes PK `(id, tf, venue_id)`. The calendar state tables (`price_bars_multi_tf_cal_us_state`, etc.) were created with `ensure_state_table(db_url, state_table, with_tz=True)` which uses `with_tz=True` but NOT `with_venue=True` in `ensure_state_table()`. However, in the calendar builder's `_update_state()`, it calls `upsert_state(..., with_tz=True, with_venue=True)`.
   - What's unclear: Whether the actual state tables have `(id, tf)` or `(id, tf, venue_id)` as their PK in the live DB. The DDL generated by `ensure_state_table(with_tz=True)` uses `PRIMARY KEY (id, tf)`. But `upsert_state(with_venue=True)` uses conflict target `(id, tf, venue_id)`, which only works if the table has a UNIQUE constraint on that triple.
   - Recommendation: Read the actual state table schema from the DB at plan time to confirm PK. Use the same conflict target in the bootstrap SQL.

2. **venue_id population in cal_anchor builders**
   - What we know: `AnchorCalendarUSBarBuilder.build_bars_for_id()` sets `venue_id` via `_resolve_venue_id(venue)` and passes it to `upsert_state()`. The `upsert_bars()` call in the from_1d path uses `conflict_cols=("id", "tf", "bar_seq", "venue_id", "timestamp")`. The direct-mode path calls `upsert_bars(bars, db_url=..., bars_table=...)` WITHOUT specifying `conflict_cols` — meaning it uses the default `("id", "tf", "bar_seq", "venue", "timestamp")`.
   - What's unclear: Whether the `bars` DataFrame in the direct-mode path has `venue_id` set or only `venue` text.
   - Recommendation: Audit each builder's `upsert_bars()` call site to confirm `venue_id` is present in the DataFrame and add it to `conflict_cols`.

3. **`delete_bars_for_id_tf` scope after redirect**
   - What we know: This function deletes by `(id, tf)` or `(id, tf, venue)` — no `alignment_source` filter.
   - What's unclear: The function uses `venue` (TEXT) not `venue_id` (SMALLINT) in its WHERE clause. After redirecting to `_u`, this could delete wrong rows (no alignment_source scope) or fail (if `venue` column is queried but _u uses `venue_id`).
   - Recommendation: Extend `delete_bars_for_id_tf()` to accept `alignment_source` parameter, or override `_delete_bars_and_state()` in each builder to issue a scoped DELETE directly.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/scripts/bars/sync_price_bars_multi_tf_u.py` — Current sync script, full content read
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf.py` — Standard builder, lines 1-250 read
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_us.py` — Calendar US builder, full content read
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_anchor_us.py` — Anchor US builder, full content read
- `src/ta_lab2/scripts/bars/base_bar_builder.py` — Base class, full content read
- `src/ta_lab2/scripts/bars/common_snapshot_contract.py` — Shared utilities, full content read (1813 lines)
- `src/ta_lab2/scripts/bars/bar_builder_config.py` — Config dataclass, full content read
- `src/ta_lab2/scripts/bars/run_all_bar_builders.py` — Orchestrator, full content read
- `src/ta_lab2/scripts/run_daily_refresh.py` — Daily refresh orchestrator, lines 80-237 read
- `sql/ddl/create_price_bars_multi_tf_u.sql` — _u table DDL, full content read
- `alembic/versions/a0b1c2d3e4f5_strip_cmc_prefix_add_venue_id.py` — Migration that established venue_id in _u PK
- `alembic/versions/g1h2i3j4k5l6_dim_data_sources_and_alignment_checks.py` — Phase 74-02 migration (CHECK constraints on alignment_source)
- `.planning/phases/74-foundation-shared-infrastructure/74-RESEARCH.md` — Phase 74 research (alignment_source values, _u table PKs)
- `.planning/phases/74-foundation-shared-infrastructure/74-02-SUMMARY.md` — Phase 74-02 delivery summary

### Secondary (MEDIUM confidence)
- `src/ta_lab2/scripts/bars/derive_multi_tf_from_1d.py` — Used by cal builders for from_1d path
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf_cal_anchor_iso.py` — Not read directly; assumed symmetric with cal_anchor_us based on codebase pattern

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, all mechanisms already exist
- Architecture (output table redirect): HIGH — direct code reading, clear change locations
- Architecture (alignment_source handling): HIGH — `upsert_bars()` `valid_cols` gap confirmed via code read
- Architecture (conflict_cols): HIGH — PK from DDL and migration confirmed
- Pitfalls (alignment_source dropped): HIGH — directly traced through `upsert_bars()` code
- Pitfalls (state bootstrap): HIGH — `_run_incremental()` behavior confirmed in base class
- Pitfalls (delete scope): MEDIUM — `delete_bars_for_id_tf()` code read, exact behavior on _u table after redirect is inferred

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable codebase; no external dependencies changing)
