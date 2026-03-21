# Phase 78: Table Drops & Script Cleanup - Research

**Researched:** 2026-03-20
**Domain:** PostgreSQL DDL cleanup, Python codebase refactoring
**Confidence:** HIGH (all findings verified directly against live DB and codebase)

---

## Summary

Phase 78 drops 30 siloed data tables (plus 30 corresponding state tables), deletes 6
deprecated sync scripts, and fixes the one dependent view (`all_emas`). All 30 siloed
tables and 30 state tables exist in the database and were verified live. All 6 sync
scripts are confirmed no-ops (Phase 77 stubs). The one view that must be updated before
dropping is `all_emas`, which currently points at `ema_multi_tf` (a siloed table) but
must be recreated pointing at `ema_multi_tf_u`. No other views depend on siloed tables.

The database is 431 GB total. The 30 siloed tables consume approximately **207 GB** (48%
of total DB size), so VACUUM FULL after drops should recover substantial disk.

**Primary recommendation:** Drop views first, then data tables per-family, then state
tables, then delete scripts. No cascade complexity -- siloed tables have no incoming FK
constraints (only outgoing FKs to `dim_venues` which resolve when the tables are dropped).

**Critical discovery:** The siloed-path state tables (e.g. `price_bars_multi_tf_cal_us_state`,
`ema_multi_tf_state`, etc.) are **still actively used by the builders for watermark tracking**
even though the builders now write to `_u`. Dropping these state tables will break
incremental refresh. The CONTEXT.md says "drop state tables too -- clean break" but this
requires the builders to be updated to point at new or renamed state tables, OR the state
tables must be preserved. This is an open planning decision that MUST be resolved before
execution.

---

## Siloed Tables Inventory

### 30 Siloed Data Tables (all confirmed EXISTS in DB)

#### Family 1: price_bars (5 tables)
| Table | Approx Rows | Table Size | Total w/ Indexes |
|-------|-------------|-----------|-----------------|
| price_bars_multi_tf | 3,271,844 | 1,700 MB | 1,944 MB |
| price_bars_multi_tf_cal_us | 2,250,166 | 604 MB | 786 MB |
| price_bars_multi_tf_cal_iso | 2,099,350 | 613 MB | 794 MB |
| price_bars_multi_tf_cal_anchor_us | 2,117,113 | 753 MB | 959 MB |
| price_bars_multi_tf_cal_anchor_iso | 2,097,455 | 765 MB | 973 MB |
| **Family total** | **~11.8M** | **~4,435 MB** | **~5,456 MB** |

#### Family 2: returns_bars (5 tables)
| Table | Approx Rows | Table Size | Total w/ Indexes |
|-------|-------------|-----------|-----------------|
| returns_bars_multi_tf | 3,266,823 | 990 MB | 1,750 MB |
| returns_bars_multi_tf_cal_us | 2,252,910 | 507 MB | 947 MB |
| returns_bars_multi_tf_cal_iso | 2,252,365 | 490 MB | 910 MB |
| returns_bars_multi_tf_cal_anchor_us | 2,121,945 | 478 MB | 948 MB |
| returns_bars_multi_tf_cal_anchor_iso | 1,903,907 | 477 MB | 949 MB |
| **Family total** | **~11.8M** | **~2,942 MB** | **~5,504 MB** |

#### Family 3: ema (5 tables)
| Table | Approx Rows | Table Size | Total w/ Indexes |
|-------|-------------|-----------|-----------------|
| ema_multi_tf | 22,859,316 | 4,221 MB | 9,571 MB |
| ema_multi_tf_cal_us | 7,795,944 | 1,546 MB | 2,833 MB |
| ema_multi_tf_cal_iso | 7,834,847 | 1,588 MB | 2,868 MB |
| ema_multi_tf_cal_anchor_us | 7,768,220 | 1,713 MB | 3,101 MB |
| ema_multi_tf_cal_anchor_iso | 7,767,805 | 1,763 MB | 3,174 MB |
| **Family total** | **~54M** | **~10,831 MB** | **~21,547 MB** |

#### Family 4: returns_ema (5 tables)
| Table | Approx Rows | Table Size | Total w/ Indexes |
|-------|-------------|-----------|-----------------|
| returns_ema_multi_tf | 17,828,588 | 11 GB | 15 GB |
| returns_ema_multi_tf_cal_us | 7,912,815 | 3,141 MB | 5,899 MB |
| returns_ema_multi_tf_cal_iso | 7,869,358 | 3,091 MB | 5,516 MB |
| returns_ema_multi_tf_cal_anchor_us | 7,720,902 | 3,271 MB | 5,680 MB |
| returns_ema_multi_tf_cal_anchor_iso | 7,701,299 | 3,266 MB | 5,760 MB |
| **Family total** | **~49M** | **~23,769 MB** | **~37,855 MB** |

#### Family 5: ama (5 tables)
| Table | Approx Rows | Table Size | Total w/ Indexes |
|-------|-------------|-----------|-----------------|
| ama_multi_tf | 56,047,120 | 12 GB | 18 GB |
| ama_multi_tf_cal_us | 39,745,468 | 6,502 MB | 17 GB |
| ama_multi_tf_cal_iso | 38,890,176 | 6,518 MB | 17 GB |
| ama_multi_tf_cal_anchor_us | 14,144,382 | 2,871 MB | 7,232 MB |
| ama_multi_tf_cal_anchor_iso | 14,060,493 | 3,009 MB | 7,486 MB |
| **Family total** | **~162.9M** | **~30,900 MB** | **~66,718 MB** |

#### Family 6: returns_ama (5 tables)
| Table | Approx Rows | Table Size | Total w/ Indexes |
|-------|-------------|-----------|-----------------|
| returns_ama_multi_tf | 55,644,640 | 22 GB | 42 GB |
| returns_ama_multi_tf_cal_us | 11,317,170 | 3,186 MB | 7,894 MB |
| returns_ama_multi_tf_cal_iso | 11,306,082 | 3,155 MB | 7,830 MB |
| returns_ama_multi_tf_cal_anchor_us | 14,990,857 | 2,617 MB | 7,225 MB |
| returns_ama_multi_tf_cal_anchor_iso | 14,767,434 | 2,673 MB | 7,404 MB |
| **Family total** | **~108M** | **~33,631 MB** | **~72,353 MB** |

### Grand Total: 30 Tables
- **Total rows (approx):** 397,606,794 (~398M)
- **Total size including indexes:** ~207 GB
- **Current DB total:** 431 GB (462 GB raw)
- **Estimated reduction after VACUUM FULL:** ~48% of DB

---

## State Tables Inventory

### 30 Siloed-Path State Tables (all confirmed EXISTS, actively used by builders)

| State Table | Row Count | Notes |
|-------------|-----------|-------|
| price_bars_multi_tf_state | 1,442 | Used by refresh_price_bars_multi_tf.py |
| price_bars_multi_tf_cal_us_state | 5,610 | Used by refresh_price_bars_multi_tf_cal_us.py |
| price_bars_multi_tf_cal_iso_state | 5,610 | Used by refresh_price_bars_multi_tf_cal_iso.py |
| price_bars_multi_tf_cal_anchor_us_state | 5,440 | Used by refresh_price_bars_multi_tf_cal_anchor_us.py |
| price_bars_multi_tf_cal_anchor_iso_state | 5,440 | Used by refresh_price_bars_multi_tf_cal_anchor_iso.py |
| returns_bars_multi_tf_state | 1,442 | Used by refresh_returns_bars_multi_tf.py |
| returns_bars_multi_tf_cal_us_state | 2,346 | Used by refresh_returns_bars_multi_tf_cal_us.py |
| returns_bars_multi_tf_cal_iso_state | 2,346 | Used by refresh_returns_bars_multi_tf_cal_iso.py |
| returns_bars_multi_tf_cal_anchor_us_state | 2,224 | Used by refresh_returns_bars_multi_tf_cal_anchor_us.py |
| returns_bars_multi_tf_cal_anchor_iso_state | 2,224 | Used by refresh_returns_bars_multi_tf_cal_anchor_iso.py |
| ema_multi_tf_state | 8,001 | Used by refresh_ema_multi_tf_from_bars.py (default) |
| ema_multi_tf_cal_us_state | 10,945 | Used by EMA cal builders |
| ema_multi_tf_cal_iso_state | 10,947 | Used by EMA cal builders |
| ema_multi_tf_cal_anchor_us_state | 10,798 | Used by EMA cal anchor builders |
| ema_multi_tf_cal_anchor_iso_state | 10,800 | Used by EMA cal anchor builders |
| returns_ema_multi_tf_state | 32,279 | Used by returns EMA builders |
| returns_ema_multi_tf_cal_us_state | 10,945 | Used by returns EMA cal builders |
| returns_ema_multi_tf_cal_iso_state | 10,947 | Used by returns EMA cal builders |
| returns_ema_multi_tf_cal_anchor_us_state | 10,798 | Used by returns EMA cal anchor builders |
| returns_ema_multi_tf_cal_anchor_iso_state | 10,800 | Used by returns EMA cal anchor builders |
| ama_multi_tf_state | 15,192 | Used by refresh_ama_multi_tf.py |
| ama_multi_tf_cal_us_state | 37,476 | Used by AMA cal builders |
| ama_multi_tf_cal_iso_state | 37,476 | Used by AMA cal builders |
| ama_multi_tf_cal_anchor_us_state | 4,824 | Used by AMA cal anchor builders |
| ama_multi_tf_cal_anchor_iso_state | 5,346 | Used by AMA cal anchor builders |
| returns_ama_multi_tf_state | 828 | Used by refresh_returns_ama.py |
| returns_ama_multi_tf_cal_us_state | 0 | Empty |
| returns_ama_multi_tf_cal_iso_state | 0 | Empty |
| returns_ama_multi_tf_cal_anchor_us_state | 0 | Empty |
| returns_ama_multi_tf_cal_anchor_iso_state | 0 | Empty |

**Total state tables size: ~78 MB** (negligible, but CRITICAL -- see pitfalls)

### State Tables That Must NOT Be Dropped (kept for _u pipeline)
These are the `_u`-path state tables with `alignment_source` column -- they track
watermarks for the direct-to-`_u` write path. They use legacy `cmc_` naming:
- `cmc_ama_multi_tf_u_state` (has `alignment_source` column)
- `cmc_returns_ama_multi_tf_u_state` (has `alignment_source` column)
- `cmc_returns_ema_multi_tf_u_state` (has `alignment_source` column)

---

## Dependent Views

### Views in public Schema (5 total, only 1 affected)

| View | References Siloed Table? | Action Required |
|------|--------------------------|-----------------|
| `all_emas` | YES -- `SELECT ... FROM public.ema_multi_tf` | RECREATE pointing at `ema_multi_tf_u` |
| `ema_alpha_lut` | NO (uses `ema_alpha_lut_old` and `dim_timeframe_backup_20251218`) | No action |
| `price_histories_u` | NO (uses `cmc_price_histories7` and `tvc_price_histories`) | No action |
| `v_positions_agg` | NO (uses `positions`) | No action |
| `vw_dim_sessions_primary` | NO (uses `dim_sessions`) | No action |

### Materialized Views (2, none affected)
| Matview | References Siloed Table? | Action |
|---------|--------------------------|--------|
| `corr_latest` | NO (uses `cross_asset_corr`) | No action |
| `v_drift_summary` | NO (uses `drift_metrics`) | No action |

### all_emas View Migration

**Current definition (must be replaced BEFORE dropping ema_multi_tf):**
```sql
CREATE OR REPLACE VIEW public.all_emas AS
SELECT id, ts, tf, tf_days, period, ema, roll
FROM public.ema_multi_tf;
```

**New definition (points at _u, adds alignment_source filter for CMC_AGG data):**
```sql
CREATE OR REPLACE VIEW public.all_emas AS
SELECT id, ts, tf, tf_days, period, ema, roll
FROM public.ema_multi_tf_u;
```

**Schema compatibility confirmed:** `ema_multi_tf_u` has all columns used by `all_emas`
(`id`, `ts`, `tf`, `tf_days`, `period`, `ema`, `roll`) plus the additional `alignment_source`
column which the view does not select. Safe to recreate with no column changes.

**Source file:** `src/ta_lab2/features/m_tf/views.py` -- the `VIEW_ALL_EMAS_SQL` constant
must also be updated from `ema_multi_tf` to `ema_multi_tf_u`.

Note: `price_with_emas` and `price_with_emas_d1d2` views are defined in `views.py` but
do NOT exist in the database. No action needed for those.

---

## FK Constraints

### Outgoing FKs (from siloed tables to dim_venues)

All 30 siloed tables have exactly 1 FK constraint each: `venue_id -> dim_venues.venue_id`.
These resolve automatically when the table is dropped.

**Constraint names follow pattern:** `fk_{table_name}_venue`

Example:
```sql
-- Resolved automatically by DROP TABLE
fk_price_bars_multi_tf_venue
fk_ema_multi_tf_venue
fk_ama_multi_tf_venue
-- etc.
```

### Incoming FKs (other tables pointing at siloed tables)

**NONE.** No external tables hold FK references into any of the 30 siloed tables.
Verified via `information_schema.table_constraints` + `constraint_column_usage` query.

**Implication:** `DROP TABLE ... RESTRICT` is safe for all 30 tables. No need for CASCADE.

---

## Python Code References

### Files with active references to siloed table names that need review

The following files reference siloed table names. Most are builders that now write to
`_u` and only reference the old name in comments, docstrings, or string constants for
the state table. The planner must identify which need actual code changes:

#### Category A: Files that WRITE to siloed table names (builders -- already updated)
These builders reference siloed names in their `STATE_TABLE` constant only (for the
state table), not the output table. After dropping data tables but keeping state tables
this is fine. After dropping state tables too, these need updates.

| File | How It References Siloed Tables |
|------|---------------------------------|
| `scripts/bars/refresh_price_bars_multi_tf.py` | `OUTPUT_TABLE = "public.price_bars_multi_tf_u"` (safe); `STATE_TABLE = "public.price_bars_multi_tf_state"` (active dep) |
| `scripts/bars/refresh_price_bars_multi_tf_cal_us.py` | Same pattern: output=_u, state=siloed_state |
| `scripts/bars/refresh_price_bars_multi_tf_cal_iso.py` | Same |
| `scripts/bars/refresh_price_bars_multi_tf_cal_anchor_us.py` | Same |
| `scripts/bars/refresh_price_bars_multi_tf_cal_anchor_iso.py` | Same |
| `scripts/returns/refresh_returns_bars_multi_tf.py` | Same pattern |
| `scripts/returns/refresh_returns_bars_multi_tf_cal_*.py` (4 files) | Same |
| `scripts/emas/refresh_ema_multi_tf_from_bars.py` | `state_table="ema_multi_tf_state"` (active dep) |
| `scripts/emas/refresh_ema_multi_tf_cal_from_bars.py` | Same |
| `scripts/emas/refresh_ema_multi_tf_cal_anchor_from_bars.py` | Same |
| `scripts/amas/refresh_ama_multi_tf.py` | References siloed name only in docstring |
| `scripts/amas/refresh_ama_multi_tf_cal_from_bars.py` | State table dep |
| `scripts/amas/refresh_ama_multi_tf_cal_anchor_from_bars.py` | State table dep |
| `scripts/amas/refresh_returns_ama.py` | State table dep |

#### Category B: Files with sync script references (need cleanup)
| File | Reference | Action |
|------|-----------|--------|
| `scripts/amas/run_all_ama_refreshes.py` | POST_STEPS lists `sync_ama_multi_tf_u` and `sync_returns_ama_multi_tf_u` | Remove 2 PostStep entries |
| `scripts/pipeline/run_go_forward_daily_refresh.py` | `Step("ema_u_sync", emas_dir / "sync_ema_multi_tf_u.py", ...)` | Remove 1 Step definition |
| `scripts/returns/refresh_returns_zscore.py` | `_RESYNC_MODULES` dict maps family -> sync module path | Remove dict entries or dead code block |
| `scripts/setup/ensure_ema_unified_table.py` | Calls `sync_ema_multi_tf_u` via subprocess | Remove subprocess call |

#### Category C: Files with siloed table references in docstrings/comments only (no runtime impact)
These are safe -- no code changes required for correctness:
- `scripts/amas/refresh_ama_multi_tf.py` (mentions "previously wrote to ama_multi_tf")
- `scripts/emas/ema_runners.py` (mentions ema tables in docstring)
- `scripts/emas/ema_state_manager.py` (default state table name in docstring example)
- `features/m_tf/views.py` (VIEW_ALL_EMAS_SQL still points at ema_multi_tf -- MUST update)
- All 6 sync script files themselves

#### Category D: Audit/stats scripts (orphaned, likely dead-code candidates)
These audit scripts reference siloed table names for validation purposes:
- `scripts/returns/audit_returns_bars_multi_tf_cal_iso_integrity.py`
- `scripts/returns/audit_returns_bars_multi_tf_cal_anchor_us_integrity.py`
- `scripts/returns/audit_returns_bars_multi_tf_integrity.py`
- `scripts/returns/audit_returns_bars_multi_tf_cal_anchor_iso_integrity.py`
- `scripts/returns/audit_returns_bars_multi_tf_cal_us_integrity.py`
- `scripts/returns/audit_returns_ema_multi_tf_cal_anchor_integrity.py`
- `scripts/returns/audit_returns_ema_multi_tf_cal_integrity.py`
- `scripts/emas/audit_ema_expected_coverage.py`
- `scripts/emas/audit_ema_tables.py`
- `scripts/emas/audit_ema_integrity.py`
- `scripts/emas/audit_ema_samples.py`
- `scripts/bars/audit_price_bars_tables.py`
- `scripts/bars/audit_price_bars_integrity.py`
- `scripts/bars/audit_price_bars_samples.py`

After drops, these will error if run. Claude's discretion on whether to update or delete
them (they are auditing the now-dropped siloed tables).

#### Category E: Experiment runner and feature code referencing siloed table names
These query siloed tables and WILL break at runtime after drops:
- `experiments/runner.py` -- references siloed table names in experiment config
- `scripts/regimes/regime_data_loader.py` -- reads from `ema_multi_tf` family
- `scripts/desc_stats/refresh_asset_stats.py` -- references `returns_bars_multi_tf`
- `scripts/desc_stats/refresh_cross_asset_corr.py` -- references `returns_bars_multi_tf`
- `scripts/features/ta_feature.py` -- references `price_bars_multi_tf`
- `scripts/features/daily_features_view.py` -- references `price_bars_multi_tf`
- `macro/lead_lag_analyzer.py` -- references `returns_bars_multi_tf`

**These need full grep + individual file review to determine if they query siloed tables
for data reads (breaking) vs just using the name as a string constant (safe if _u exists).**

---

## 6 Sync Scripts - Deletion Scope

### Scripts to Delete
All 6 are confirmed no-ops (Phase 77 stubs):

| Script Path | Content | Status |
|-------------|---------|--------|
| `src/ta_lab2/scripts/bars/sync_price_bars_multi_tf_u.py` | Prints deprecation, exits 0 | No-op |
| `src/ta_lab2/scripts/returns/sync_returns_bars_multi_tf_u.py` | Warns DeprecationWarning, exits | No-op |
| `src/ta_lab2/scripts/emas/sync_ema_multi_tf_u.py` | Prints deprecation, exits 0 | No-op |
| `src/ta_lab2/scripts/returns/sync_returns_ema_multi_tf_u.py` | Prints deprecation, exits 0 | No-op |
| `src/ta_lab2/scripts/amas/sync_ama_multi_tf_u.py` | Prints deprecation, exits 0 | No-op |
| `src/ta_lab2/scripts/amas/sync_returns_ama_multi_tf_u.py` | Prints deprecation, exits 0 | No-op |

### References to Sync Scripts in Orchestrators

| Orchestrator File | Reference | Action |
|------------------|-----------|--------|
| `scripts/amas/run_all_ama_refreshes.py` (line 122-131) | `POST_STEPS` list includes `sync_ama_multi_tf_u` and `sync_returns_ama_multi_tf_u` | Remove 2 `PostStep` entries |
| `scripts/pipeline/run_go_forward_daily_refresh.py` (line 262-270) | `Step("ema_u_sync", emas_dir / "sync_ema_multi_tf_u.py", ...)` | Remove step + update comment on line 219 + `--bars-only` help text line 296 |
| `scripts/returns/refresh_returns_zscore.py` (line 631-635) | `_RESYNC_MODULES` dict with 3 sync modules | Remove dict and `_resync_u_tables()` function (it truncates `_u` then calls sync -- this logic is wrong after Phase 77 anyway) |
| `scripts/setup/ensure_ema_unified_table.py` (line 261-279) | `subprocess.run(["python", "-m", "ta_lab2.scripts.emas.sync_ema_multi_tf_u"])` | Remove sync block (lines 257-282) |

### CLI Entry Points
**None in pyproject.toml.** Only one entry point exists: `ta-lab2 = "ta_lab2.cli:main"`.
No sync scripts are registered as CLI commands. Verified via grep on pyproject.toml.

### __init__.py Imports
No sync script imports found in any `__init__.py` file:
- `scripts/bars/__init__.py`: Does not exist
- `scripts/emas/__init__.py`: Contains only `# Package for ta_lab2 scripts...` -- no imports
- `scripts/amas/__init__.py`: Docstring only, no imports
- `scripts/returns/__init__.py`: Does not exist

### run_daily_refresh.py and run_all_bar_builders.py
- `run_daily_refresh.py`: **No sync step references at all.** The "sync" references in
  that file are for VM syncs (FRED, Hyperliquid) which are unrelated. No changes needed.
- `run_all_bar_builders.py`: **No sync step references.** The script only coordinates
  bar builders. No changes needed.

---

## Drop Ordering

### Recommended Sequence

```
Step 1: Pre-drop validation
  - For each family: COUNT(*) on all 5 siloed tables + _u table
  - Abort if any family shows _u < sum(siloed) by more than 0.1% (unexpected data loss)
  - NOTE: _u is expected to be slightly larger (direct writes post-Phase 76/77)

Step 2: Drop all_emas view (before dropping ema_multi_tf)
  DROP VIEW public.all_emas;

Step 3: Recreate all_emas pointing at ema_multi_tf_u
  CREATE OR REPLACE VIEW public.all_emas AS
  SELECT id, ts, tf, tf_days, period, ema, roll
  FROM public.ema_multi_tf_u;

Step 4: Update views.py source (VIEW_ALL_EMAS_SQL constant)
  Change: FROM public.ema_multi_tf
  To:     FROM public.ema_multi_tf_u

Step 5: Drop 30 siloed data tables (per-family batches recommended)
  -- Family 1: price_bars
  DROP TABLE public.price_bars_multi_tf;
  DROP TABLE public.price_bars_multi_tf_cal_us;
  DROP TABLE public.price_bars_multi_tf_cal_iso;
  DROP TABLE public.price_bars_multi_tf_cal_anchor_us;
  DROP TABLE public.price_bars_multi_tf_cal_anchor_iso;
  -- repeat for remaining 5 families

Step 6: Drop 30 state tables (ONLY if builders are updated first)
  -- See critical pitfall below before executing
  DROP TABLE public.price_bars_multi_tf_state;
  -- etc.

Step 7: Delete 6 sync scripts + remove orchestrator references
  git rm <6 files>
  Edit run_all_ama_refreshes.py
  Edit run_go_forward_daily_refresh.py
  Edit refresh_returns_zscore.py
  Edit ensure_ema_unified_table.py

Step 8: VACUUM FULL
  VACUUM FULL;

Step 9: Capture after-size
  SELECT pg_size_pretty(pg_database_size('marketdata'));
```

### Transaction Scope Recommendation

**Per-family batches.** Each family's 5 DROP TABLE statements can be in a single
transaction. This gives atomic rollback per family if something goes wrong, without
locking the entire DB. State tables can be separate transactions after builders are updated.

---

## Common Pitfalls

### Pitfall 1: Dropping State Tables Will Break Incremental Refresh
**What goes wrong:** The CONTEXT.md says "drop state tables too -- clean break" but all
active builders still use siloed-path state tables for watermark tracking. Dropping them
without first updating the builders to use new state tables will cause every incremental
refresh to fail (builders query state table at startup for `last_canonical_ts`).

**Evidence:** `refresh_price_bars_multi_tf_cal_us.py` has `STATE_TABLE = "public.price_bars_multi_tf_cal_us_state"` as a class constant. `refresh_ema_multi_tf_from_bars.py` has `state_table="ema_multi_tf_state"` as the default. All builders call `ensure_state_table()` on startup.

**How to avoid:** Before dropping state tables, either:
  - Option A: Update all builders to use new state table names (e.g. `price_bars_multi_tf_u_state`), migrate watermark data, then drop old state tables
  - Option B: Keep state tables even though data tables are dropped (they're only 78 MB total)
  - Option C: Accept that builders will re-create state tables from scratch (losing watermarks, forcing full rebuild on next run)

**Recommendation:** Confirm with user which option is intended. Option B is safest for Phase 78 scope. Option C is acceptable if a full rebuild is acceptable.

### Pitfall 2: all_emas View Blocks ema_multi_tf Drop
**What goes wrong:** Attempting `DROP TABLE public.ema_multi_tf` will fail with
`ERROR: cannot drop table ema_multi_tf because other objects depend on it -- VIEW all_emas`
unless the view is dropped or recreated first.

**How to avoid:** Always drop/recreate `all_emas` BEFORE dropping `ema_multi_tf`.
The recreation SQL is safe (schema-compatible with ema_multi_tf_u).

### Pitfall 3: refresh_returns_zscore.py _RESYNC_MODULES Logic is Obsolete
**What goes wrong:** `refresh_returns_zscore.py` has a `_resync_u_tables()` function that
TRUNCATES the `_u` returns tables then calls the sync scripts. After sync scripts are
deleted, calling `refresh_returns_zscore.py --resync` would attempt to import a missing
module and crash.

**Why it matters:** The TRUNCATE + sync logic was the old model. Since Phase 77 builders
write directly to `_u`, truncating and re-syncing would now WIPE all the data and never
restore it. This function should be removed entirely, not just the module references.

**How to avoid:** Delete the entire `_resync_u_tables()` function and `_RESYNC_MODULES`
dict from `refresh_returns_zscore.py`, not just the sync module references.

### Pitfall 4: VACUUM FULL Requires Exclusive Lock
**What goes wrong:** VACUUM FULL acquires an exclusive lock on each table being vacuumed.
For a 431 GB database, this can take hours and blocks all reads/writes.

**Mitigating factor:** No downtime concerns per CONTEXT.md (research/dev DB).
**How to avoid:** Run during off-hours or with a script that VACUUMs one table at a time.
VACUUM without FULL reclaims space within PostgreSQL's internal accounting but does not
return disk to the OS -- FULL is required to return pages to the OS.

### Pitfall 5: pg_depend Does Not Catch Text-Based References
**What goes wrong:** The `pg_depend` query only finds view-level structural dependencies.
Python scripts that hardcode siloed table names as strings (e.g. `text("SELECT ... FROM price_bars_multi_tf")`) are NOT caught by pg_depend.

**How to avoid:** The Category E files listed above (experiments/runner.py,
regime_data_loader.py, etc.) must be individually reviewed. Each one that queries siloed
tables at runtime will break after drops.

### Pitfall 6: Estimates vs Actual Counts
**What goes wrong:** `reltuples` is PostgreSQL's statistics estimate, not an exact count.
Using `reltuples` for parity checks can give false confidence.

**How to avoid:** For the pre-drop parity check, use exact `COUNT(*)` per table, not
`reltuples`. Wrap in explicit transaction:
```sql
BEGIN;
-- COUNT(*) all 5 siloed tables in the family
-- COUNT(*) the _u table
-- Compare: _u >= sum(siloed) OR _u within 1% of sum(siloed)
COMMIT;
```

---

## Code Examples

### Drop View Before Table
```sql
-- Source: research verified 2026-03-20
-- Run BEFORE DROP TABLE public.ema_multi_tf

-- Step 1: Drop dependent view
DROP VIEW public.all_emas;

-- Step 2: Recreate pointing at _u (schema-compatible: same columns + alignment_source in _u)
CREATE OR REPLACE VIEW public.all_emas AS
SELECT id, ts, tf, tf_days, period, ema, roll
FROM public.ema_multi_tf_u;
```

### Per-Family Drop Pattern
```sql
-- Source: research verified 2026-03-20
-- Safe: RESTRICT is fine because no incoming FK constraints exist on siloed tables

BEGIN;
DROP TABLE public.price_bars_multi_tf RESTRICT;
DROP TABLE public.price_bars_multi_tf_cal_us RESTRICT;
DROP TABLE public.price_bars_multi_tf_cal_iso RESTRICT;
DROP TABLE public.price_bars_multi_tf_cal_anchor_us RESTRICT;
DROP TABLE public.price_bars_multi_tf_cal_anchor_iso RESTRICT;
COMMIT;

-- Repeat for returns_bars, ema, returns_ema, ama, returns_ama families
```

### Pre-Drop Parity Validation Query (exact counts)
```sql
-- Source: research verified 2026-03-20
-- Run for each family before any drops

SELECT
    'price_bars' AS family,
    (SELECT COUNT(*) FROM public.price_bars_multi_tf) +
    (SELECT COUNT(*) FROM public.price_bars_multi_tf_cal_us) +
    (SELECT COUNT(*) FROM public.price_bars_multi_tf_cal_iso) +
    (SELECT COUNT(*) FROM public.price_bars_multi_tf_cal_anchor_us) +
    (SELECT COUNT(*) FROM public.price_bars_multi_tf_cal_anchor_iso) AS siloed_total,
    (SELECT COUNT(*) FROM public.price_bars_multi_tf_u) AS u_total;
```

### Remove PostStep from run_all_ama_refreshes.py
```python
# Source: codebase research 2026-03-20
# File: src/ta_lab2/scripts/amas/run_all_ama_refreshes.py, lines 116-137

# BEFORE (current code):
POST_STEPS = [
    PostStep(
        name="returns",
        module="ta_lab2.scripts.amas.refresh_returns_ama",
        description="AMA returns",
    ),
    PostStep(                          # DELETE THIS BLOCK
        name="sync_values",            # DELETE
        module="ta_lab2.scripts.amas.sync_ama_multi_tf_u",   # DELETE
        description="Sync AMA values to _u",   # DELETE
    ),                                 # DELETE
    PostStep(                          # DELETE THIS BLOCK
        name="sync_returns",           # DELETE
        module="ta_lab2.scripts.amas.sync_returns_ama_multi_tf_u",  # DELETE
        description="Sync AMA returns to _u",  # DELETE
    ),                                 # DELETE
    PostStep(
        name="zscores",
        module="ta_lab2.scripts.returns.refresh_returns_zscore",
        description="AMA z-scores",
        extra_args=["--tables", "amas"],
    ),
]

# AFTER:
POST_STEPS = [
    PostStep(
        name="returns",
        module="ta_lab2.scripts.amas.refresh_returns_ama",
        description="AMA returns",
    ),
    PostStep(
        name="zscores",
        module="ta_lab2.scripts.returns.refresh_returns_zscore",
        description="AMA z-scores",
        extra_args=["--tables", "amas"],
    ),
]
```

### Storage Measurement Query
```sql
-- Source: verified 2026-03-20
-- Run before drops and after VACUUM FULL

-- Before
SELECT pg_size_pretty(pg_database_size('marketdata')) AS db_size_before;

-- After VACUUM FULL
VACUUM FULL;
SELECT pg_size_pretty(pg_database_size('marketdata')) AS db_size_after;
```

---

## State of the Art

| Old Approach | Current Approach | Changed | Impact |
|--------------|------------------|---------|--------|
| Write to siloed table, sync to `_u` | Write directly to `_u` with `alignment_source` | Phase 76-77 | 6 sync scripts are now no-ops |
| `all_emas` view reads `ema_multi_tf` | Should read `ema_multi_tf_u` | Phase 78 (this phase) | One view recreation needed |
| State tables named after siloed tables | State tables still use siloed naming | Not yet changed | See Pitfall 1 above |

---

## Open Questions

1. **State table drop strategy**
   - What we know: State tables are actively used by builders for watermark tracking (they hold `last_canonical_ts`, `last_bar_seq` etc.)
   - What's unclear: Whether the intent is to (A) update builders first, (B) keep state tables, or (C) accept full rebuild
   - Recommendation: Clarify with user. The safest option for Phase 78 is to DROP the data tables only and KEEP the state tables until builders are updated. State tables are only 78 MB.

2. **Category E files (experiment runner, regime_data_loader, etc.)**
   - What we know: ~7 files contain active SQL queries against siloed table names
   - What's unclear: Whether these query `ema_multi_tf` directly vs going through `ema_multi_tf_u`
   - Recommendation: Individual file audit required; each file in Category E section above needs line-level grep for actual `SELECT FROM <siloed_table>` patterns.

3. **EMA stats tables**
   - What we know: `ema_multi_tf_stats`, `ema_multi_tf_cal_stats`, `ema_multi_tf_cal_anchor_stats` and their `*_state` tables exist (187K+ rows)
   - What's unclear: Whether these are derived from the siloed EMA tables and should be dropped, or if they are independent analytical outputs that should be kept
   - Recommendation: Treat as out-of-scope for Phase 78 unless explicitly included. These are not in the 30 siloed tables list.

---

## Database Size Summary

| Metric | Value | Source |
|--------|-------|--------|
| Current DB size | 431 GB (pretty-printed) | `pg_database_size()` verified 2026-03-20 |
| Siloed tables (30 tables, data only) | ~207 GB | `pg_total_relation_size()` sum |
| State tables (30 tables) | ~78 MB | `pg_total_relation_size()` sum |
| Estimated DB after drops | ~224 GB | 431 - 207 = 224 GB |
| Estimated reduction | ~48% | Applies only after VACUUM FULL |

---

## Sources

### Primary (HIGH confidence)
- Live DB query: `pg_class`, `pg_depend`, `information_schema` -- 2026-03-20
- Live DB query: `pg_views`, `pg_matviews` -- 2026-03-20
- Live DB query: `pg_total_relation_size()` per table -- 2026-03-20
- Codebase grep: all 6 sync script file contents -- verified no-ops
- Codebase grep: all orchestrator references to sync scripts -- identified 4 files

### Secondary (MEDIUM confidence)
- Row counts via `reltuples` -- approximate, needs COUNT(*) for final validation
- Category E runtime risk assessment -- requires individual file audit to confirm

---

## Metadata

**Confidence breakdown:**
- 30 siloed tables (existence, size): HIGH -- verified live DB
- 30 state tables (existence, row counts): HIGH -- verified live DB
- Dependent views (all_emas only): HIGH -- verified via pg_views and pg_depend
- FK constraints (none incoming): HIGH -- verified via information_schema
- Sync script content (no-ops): HIGH -- read all 6 files
- Orchestrator references to sync scripts: HIGH -- found 4 files with specific line numbers
- State table active dependency: HIGH -- read builder source code (STATE_TABLE constants)
- Category E runtime-breaking references: MEDIUM -- files identified but not line-audited

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable domain -- tables won't change between now and execution)
