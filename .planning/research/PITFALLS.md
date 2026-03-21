# Domain Pitfalls: v1.1.0 Pipeline Consolidation & Storage Optimization

**Domain:** Consolidating 36 siloed tables into 6 unified tables, merging duplicate scripts, and dropping large tables in a PostgreSQL-backed quant trading system (ta_lab2)
**Researched:** 2026-03-19
**Scope:** Infrastructure migration pitfalls specific to consolidating 6 table families (each with 5 variants + 1 unified), rewriting ETL scripts to target unified tables directly, and safely dropping 30 siloed source tables totaling ~200M+ rows

---

## 1. Table Drop & Schema Migration Pitfalls

### CRITICAL: DROP TABLE on 57M-Row AMA Tables Will Acquire ACCESS EXCLUSIVE Lock and Block All Concurrent Queries

**What goes wrong:** PostgreSQL `DROP TABLE` acquires an `ACCESS EXCLUSIVE` lock on the table. For small tables this is instantaneous, but for the 57M-row `ama_multi_tf` and `returns_ama_multi_tf` tables, PostgreSQL must also drop all indexes (which involve I/O proportional to index size). While the DROP itself is fast (it removes catalog entries, not data pages -- the OS reclaims space asynchronously), the lock acquisition can stall if any other session holds even a `SELECT` lock on the table. If the daily refresh pipeline is running a long `SELECT` on `ama_multi_tf` while the DROP is issued, the DROP will queue behind that SELECT, and ALL subsequent queries (including unrelated ones that touch the same table) will queue behind the DROP. This is the "lock queue cascade" problem.

**Why it matters for this system:** The `run_daily_refresh.py` orchestrator runs bars, EMAs, AMAs, and syncs sequentially but with configurable timeouts (AMA timeout: 3600s). If a migration is attempted during or near a refresh window, a queued DROP can stall the entire pipeline. The AMA state managers (`ama_state_manager.py`) hold connections open during state reads. On Windows with local PostgreSQL, there is no connection pooler (PgBouncer) to terminate idle connections, so stale sessions can hold locks indefinitely.

**Consequences:** Pipeline hangs for minutes to hours. On Windows, `Ctrl+C` may not cleanly release the lock (Python signal handling on Windows is limited). Manual `pg_terminate_backend()` required to break the deadlock.

**Prevention:**
- Before dropping any table, run this query to identify active sessions:
  ```sql
  SELECT pid, state, query_start, query
  FROM pg_stat_activity
  WHERE datname = 'marketdata'
    AND state != 'idle'
    AND query ILIKE '%ama_multi_tf%';
  ```
- Drop tables during a dedicated maintenance window when no refresh scripts are running. Given this is a research/paper-trading system (not live production), schedule drops outside the daily refresh window.
- Use `DROP TABLE IF EXISTS ... CASCADE` but FIRST run `DROP TABLE ... RESTRICT` (the default) to see what dependent objects exist. PostgreSQL will list dependent views and FK constraints in the error message without dropping anything.
- Drop tables one family at a time, not all 30 at once. Verify the pipeline works after each family is migrated before proceeding.
- Set a statement timeout on the migration session: `SET statement_timeout = '30s';` so a blocked DROP fails fast rather than waiting indefinitely.

**Warning signs:**
- `pg_stat_activity` showing `waiting` state for the DROP session
- Daily refresh script hanging at the AMA or EMA stage during migration
- Windows Task Manager showing multiple `python.exe` processes (stale workers from previous runs holding connections)

**Detection:** Before migration, add a pre-check in the Alembic migration script:
```python
# Fail fast if any active queries touch tables being dropped
active = conn.execute(text("""
    SELECT count(*) FROM pg_stat_activity
    WHERE datname = current_database()
      AND state != 'idle'
      AND pid != pg_backend_pid()
""")).scalar()
if active > 0:
    raise RuntimeError(f"{active} active sessions -- run migration when pipeline is idle")
```

**Phase:** Table drop phase. Must be the LAST step after all scripts are rewritten and verified against _u tables.

---

### CRITICAL: DROP TABLE CASCADE Will Silently Destroy the `corr_latest` Materialized View and `all_emas` View If They Reference Dropped Tables

**What goes wrong:** The migration at `a0b1c2d3e4f5` created several views that reference the current table names:
- `corr_latest` (MATERIALIZED VIEW) references `cross_asset_corr`
- `all_emas` (VIEW) references EMA tables
- `v_positions_agg` (VIEW) references `positions`
- `price_histories_u` (VIEW) references `cmc_price_histories7`

If any table that feeds a view or materialized view is dropped with `CASCADE`, the view is silently destroyed. PostgreSQL does not warn -- it just drops the dependent view as part of the cascade. The next time dashboard code or a stats script queries the view, it fails with "relation does not exist."

**Why it matters for this system:** The `corr_latest` materialized view is queried by `src/ta_lab2/dashboard/queries/asset_stats.py`. The `all_emas` view may be queried by ad-hoc analysis. If these are silently dropped during table migration, the dashboard breaks with a cryptic error.

**Consequences:** Dashboard pages crash. `REFRESH MATERIALIZED VIEW corr_latest` fails because the view no longer exists. Recreating it requires knowing the exact DDL, which is buried in the Alembic migration history.

**Prevention:**
- Before dropping ANY table, catalog all dependent views:
  ```sql
  SELECT DISTINCT dependent_ns.nspname AS dependent_schema,
         dependent_view.relname AS dependent_view,
         source_ns.nspname AS source_schema,
         source_table.relname AS source_table
  FROM pg_depend
  JOIN pg_rewrite ON pg_depend.objid = pg_rewrite.oid
  JOIN pg_class AS dependent_view ON pg_rewrite.ev_class = dependent_view.oid
  JOIN pg_class AS source_table ON pg_depend.refobjid = source_table.oid
  JOIN pg_namespace dependent_ns ON dependent_view.relnamespace = dependent_ns.oid
  JOIN pg_namespace source_ns ON source_table.relnamespace = source_ns.oid
  WHERE source_table.relname IN ('ema_multi_tf', 'ema_multi_tf_cal_iso', /* ... all tables being dropped */)
    AND source_table.relname != dependent_view.relname;
  ```
- Recreate any dependent views AFTER drops to point at the _u tables instead. Script this as part of the Alembic migration, not as a manual step.
- NEVER use `CASCADE` unless you have explicitly inventoried what will be destroyed. Use `RESTRICT` (default) first, fix dependencies, then drop.
- Store the current view DDL before migration:
  ```sql
  SELECT pg_get_viewdef('corr_latest'::regclass, true);
  ```

**Warning signs:**
- Using `DROP TABLE ... CASCADE` without first checking dependent objects
- Dashboard returning "relation does not exist" errors after migration
- No `CREATE VIEW` / `CREATE MATERIALIZED VIEW` statements in the migration script

**Detection:** Add a post-migration check that queries `pg_matviews` and `pg_views` to confirm all expected views still exist.

**Phase:** Pre-drop inventory phase. Must be completed BEFORE any tables are dropped.

---

### CRITICAL: Foreign Key Constraints From `dim_venues` Will Block Table Drops Unless Properly Sequenced

**What goes wrong:** The `a0b1c2d3e4f5` migration added `FOREIGN KEY (venue_id) REFERENCES dim_venues(venue_id)` to every analytics table, including the siloed variants (`ema_multi_tf_cal_iso`, `ama_multi_tf_cal_us`, etc.). When dropping a table that has a FK constraint, `DROP TABLE ... RESTRICT` will succeed (FKs on the table being dropped are removed). BUT if you try to drop `dim_venues` before dropping the referencing tables, it will fail.

More subtly: if the siloed tables have triggers, rules, or policies attached (added manually outside Alembic), `DROP TABLE` may fail unexpectedly.

**Prevention:**
- Drop siloed tables BEFORE modifying `dim_venues`. The FK direction (siloed table -> dim_venues) means dropping the siloed table removes its own FK constraint automatically.
- Verify no circular or unexpected FK dependencies exist:
  ```sql
  SELECT conrelid::regclass AS table_name,
         confrelid::regclass AS references_table,
         conname AS constraint_name
  FROM pg_constraint
  WHERE contype = 'f'
    AND conrelid::regclass::text LIKE '%multi_tf_cal%';
  ```
- Include `IF EXISTS` on all drops for idempotency (migration may be re-run after partial failure).

**Phase:** Table drop phase. Drop siloed tables before any changes to dimension tables.

---

### MODERATE: State Tables for Dropped Siloed Tables Will Become Orphaned, Confusing Future Debugging

**What goes wrong:** Each siloed table has a companion state table (e.g., `ema_multi_tf_cal_iso` has `ema_multi_tf_cal_iso_state`). These state tables track watermarks for incremental refresh. When the siloed data table is dropped but the state table is forgotten, the state table persists with stale data. Future developers (or yourself in 6 months) will see 30 `*_state` tables with no corresponding data tables and wonder if something is broken.

Worse: if a consolidated script accidentally references an old state table name (copy-paste from the old script), it will successfully read stale watermarks from the orphaned state table and either skip data (watermark too high) or reprocess everything (watermark mismatch).

**Why it matters for this system:** The codebase has 4 separate state manager classes (`EMAStateManager`, `ama_state_manager.py`, `feature_state_manager.py`, `signal_state_manager.py`), each with hardcoded state table names. The state table name is often configured as a default parameter:
```python
state_table: str = "cmc_ema_state"  # Default in EMAStateConfig
```
If this default is not updated after consolidation, the state manager will look at a non-existent (or orphaned) table.

**Consequences:** Silent watermark corruption. Scripts either reprocess all data (wasting hours) or skip recent data (missing updates).

**Prevention:**
- Create a checklist of ALL state tables that correspond to dropped data tables. There are at least 24 state tables (4 calendar variants x 6 families):
  - `price_bars_multi_tf_cal_iso_state`, `price_bars_multi_tf_cal_us_state`, etc.
  - `ema_multi_tf_cal_iso_state`, `ema_multi_tf_cal_us_state`, etc.
  - `ama_multi_tf_cal_iso_state`, `ama_multi_tf_cal_us_state`, etc.
  - `returns_bars_multi_tf_cal_iso_state`, `returns_bars_multi_tf_cal_us_state`, etc.
  - `returns_ema_multi_tf_cal_iso_state`, `returns_ema_multi_tf_cal_us_state`, etc.
  - `returns_ama_multi_tf_cal_iso_state`, `returns_ama_multi_tf_cal_us_state`, etc.
- Drop each state table in the same migration as its data table.
- After migration, query for orphaned state tables:
  ```sql
  SELECT tablename FROM pg_tables
  WHERE schemaname = 'public'
    AND tablename LIKE '%_state'
  ORDER BY tablename;
  ```
  Cross-reference against the list of remaining data tables.
- Update all state manager default configs to reference the new consolidated state table names.

**Warning signs:**
- State tables remaining after data tables are dropped
- State manager configs still referencing old table names (grep for the old names)
- Incremental refresh processing 0 rows (reading stale watermark from wrong state table)

**Detection:** Post-migration, run `\dt *_state` in psql and verify every state table has a corresponding data table.

**Phase:** Table drop phase. State tables must be dropped alongside their data tables.

---

## 2. Watermark & Incremental Refresh Pitfalls

### CRITICAL: Unified _u Tables Use `ingested_at` Watermarks; Direct-Write Scripts Must Maintain This Column or Break Sync

**What goes wrong:** The current sync pattern (`sync_utils.py`) uses `ingested_at` as the watermark column:
```python
wm_clause = 'AND "ingested_at" > :wm'
```
This works because the siloed tables have an `ingested_at DEFAULT now()` column, and the sync script copies this value into the _u table. When scripts are rewritten to write directly to the _u table (bypassing the siloed table + sync pattern), they must set `ingested_at` explicitly. If a script uses a temp-table + upsert pattern and the temp table does not include `ingested_at`, the column will be NULL or use the DEFAULT (which is the insert time, not the data observation time).

This matters because any remaining consumers that still use the watermark pattern will see NULL watermarks and either reprocess everything or skip everything.

**Why it matters for this system:** The `sync_sources_to_unified()` function in `sync_utils.py` depends on `ingested_at` for incremental sync. During a phased migration where some families are consolidated but others still use the old sync pattern, the watermark column must remain consistent across ALL families.

**Consequences:** If `ingested_at` is NULL for direct-written rows, the watermark query `MAX(ingested_at)` returns NULL for that `alignment_source`, causing the next sync attempt to do a full reload (every row). On the 57M-row AMA tables, this means 57M row comparison on every run.

**Prevention:**
- Every direct-write script MUST set `ingested_at = now()` explicitly in its INSERT statement. Do not rely on the column DEFAULT.
- Add a NOT NULL constraint to `ingested_at` on _u tables before migration:
  ```sql
  ALTER TABLE ema_multi_tf_u
  ALTER COLUMN ingested_at SET NOT NULL;
  ```
  This will cause any script that forgets `ingested_at` to fail loudly at INSERT time, not silently write NULLs.
- During the transition period (some families consolidated, others not), keep the sync scripts running alongside the direct-write scripts. The sync script's `ON CONFLICT DO NOTHING` will harmlessly skip rows already written by the direct-write script.

**Warning signs:**
- `SELECT COUNT(*) FROM ema_multi_tf_u WHERE ingested_at IS NULL;` returning > 0
- Sync scripts reporting "no watermark -- full load" when they should be incremental
- Dramatic increase in sync script runtime (was 30 seconds, now 30 minutes)

**Detection:** Add a post-write assertion in consolidated scripts:
```python
null_count = conn.execute(text(
    f"SELECT COUNT(*) FROM {table} WHERE ingested_at IS NULL AND alignment_source = :src"
), {"src": alignment_source}).scalar()
assert null_count == 0, f"{null_count} rows with NULL ingested_at"
```

**Phase:** Script rewrite phase. Must be enforced from the first consolidated script.

---

### CRITICAL: Switching Write Target From Siloed Table to _u Table Requires Resetting or Migrating the State Table Watermark

**What goes wrong:** Each EMA/AMA refresh script has a state table that tracks the last-processed timestamp per `(id, venue_id, tf, period)`. The state table for `ema_multi_tf` stores watermarks for the siloed table. When the script is rewritten to write directly to `ema_multi_tf_u`, the state table watermark still points at the old table's timestamp range.

Two failure modes:
1. **Watermark too old:** The state table says "last processed: 2026-03-15" for the siloed table. The _u table already has data synced up to 2026-03-19. The rewritten script starts from 2026-03-15 and re-inserts 4 days of data. With `ON CONFLICT DO NOTHING`, this is wasteful but not harmful. With `ON CONFLICT DO UPDATE`, this could overwrite correct values with recomputed values that differ due to floating-point ordering.
2. **Watermark too new:** Less likely but possible if the state table was manually updated or if clock skew exists. The script skips data it should process.

**Why it matters for this system:** The EMA state manager (`ema_state_manager.py`) reads from `ema_multi_tf_state` with PK `(id, venue_id, tf, period)`. If the rewritten script now targets `ema_multi_tf_u` but the state table still tracks timestamps from the siloed `ema_multi_tf`, the watermarks are misaligned. The `alignment_source` column in the _u table adds another dimension that the state table does not track.

**Consequences:** Redundant reprocessing (hours of wasted compute on AMA tables), or worse, gaps in data if the watermark is ahead of the actual data in the new target table.

**Prevention:**
- When rewriting a script from siloed to unified target, create a NEW state table (or add an `alignment_source` column to the existing state table) rather than reusing the old one.
- Before the first run of the rewritten script, populate the new state table from the _u table's actual data:
  ```sql
  INSERT INTO ema_multi_tf_u_state (id, venue_id, tf, period, last_time_close, updated_at)
  SELECT id, venue_id, tf, period, MAX(ts), now()
  FROM ema_multi_tf_u
  WHERE alignment_source = 'multi_tf'
  GROUP BY id, venue_id, tf, period;
  ```
- Alternatively, run the first execution with `--full-rebuild` to establish the correct watermark from scratch, then switch to incremental.
- Document the state table migration as an explicit step in the migration plan, not an afterthought.

**Warning signs:**
- First run of rewritten script processing millions of rows when only a few thousand are expected
- State table's `last_time_close` not matching the actual MAX(ts) in the target table
- Different state tables for the same logical data (old `ema_multi_tf_state` and new `ema_multi_tf_u_state` both existing)

**Phase:** Script rewrite phase. State table migration must be tested per-family before moving to the next.

---

### MODERATE: The `alignment_source` Column in _u Tables Changes Semantics When Scripts Write Directly

**What goes wrong:** Currently, `alignment_source` is derived from the source table name:
```python
# sync_utils.py
def alignment_source_from_table(full_name: str, prefix: str) -> str:
    _, table = split_schema_table(full_name)
    if table.startswith(prefix):
        return table[len(prefix):]
    return table
```
This produces values like `multi_tf`, `multi_tf_cal_us`, `multi_tf_cal_iso`, etc. When scripts write directly to the _u table, they must set `alignment_source` explicitly to the same values. If a script sets it to a different value (e.g., `cal_us` instead of `multi_tf_cal_us`), downstream queries that filter on `alignment_source` will miss the data.

**Why it matters for this system:** The `regime_data_loader.py` filters EMAs with `alignment_source = 'multi_tf'`:
```python
# Daily EMAs in ema_multi_tf_u require alignment_source = 'multi_tf' filter
# to prevent duplicate rows per (id, ts, tf, period)
```
If a consolidated script writes with a different `alignment_source` value, the regime data loader returns empty results. Regimes stop updating. No error is raised -- the query returns 0 rows, which the regime labeler interprets as "no data" and skips the asset.

**Consequences:** Silent regime calculation failure. Regimes appear "stale" but no error is logged.

**Prevention:**
- Define `alignment_source` values as constants in a shared module (e.g., `ta_lab2.constants`):
  ```python
  ALIGNMENT_MULTI_TF = "multi_tf"
  ALIGNMENT_CAL_US = "multi_tf_cal_us"
  ALIGNMENT_CAL_ISO = "multi_tf_cal_iso"
  ALIGNMENT_CAL_ANCHOR_US = "multi_tf_cal_anchor_us"
  ALIGNMENT_CAL_ANCHOR_ISO = "multi_tf_cal_anchor_iso"
  ```
- Both the sync scripts and the consolidated direct-write scripts must use these constants. No string literals for `alignment_source` outside the constants module.
- Add a CHECK constraint on the _u tables:
  ```sql
  ALTER TABLE ema_multi_tf_u
  ADD CONSTRAINT chk_alignment_source
  CHECK (alignment_source IN ('multi_tf', 'multi_tf_cal_us', 'multi_tf_cal_iso',
                               'multi_tf_cal_anchor_us', 'multi_tf_cal_anchor_iso'));
  ```
  This catches typos at INSERT time.

**Warning signs:**
- Regime data loader returning 0 rows for assets that should have data
- `SELECT DISTINCT alignment_source FROM ema_multi_tf_u;` showing unexpected values
- String literal `alignment_source` values scattered across multiple scripts (grep to detect)

**Detection:** After each script rewrite, verify alignment_source values:
```sql
SELECT alignment_source, COUNT(*) FROM ema_multi_tf_u GROUP BY alignment_source ORDER BY 1;
```

**Phase:** Script rewrite phase. Constants module should be created as the FIRST step.

---

## 3. Script Consolidation Pitfalls

### CRITICAL: Consolidating 3 Source-Specific 1D Bar Builders Into One Generic Builder Risks Silently Losing Source-Specific SQL Logic

**What goes wrong:** The three 1D bar builders (`refresh_price_bars_1d.py` for CMC, `refresh_tvc_price_bars_1d.py` for TVC, `refresh_hl_price_bars_1d.py` for HL) share ~80% of their code but have critical differences documented in the todo:

| Aspect | CMC | TVC | HL |
|--------|-----|-----|-----|
| OHLC repair | YES (6 CTEs) | NO (4 CTEs) | NO (4 CTEs) |
| time_high/low | Real columns | Synthesized as `ts` | Synthesized as `ts` |
| market_cap | `s.marketcap` | NULL | NULL |
| Backfill detection | YES | **MISSING** | **MISSING** |
| Post-build sync | NO | YES | YES |

When consolidating into one `SourceSpec`-based builder, the OHLC repair logic (2 extra CTEs) must be conditionally included only for CMC. If the conditional logic is wrong (e.g., repair CTEs are always included, or never included), the consequences are:
- Always included: TVC and HL bars get unnecessary repair logic that may ALTER their data if the synthesized time_high/time_low values are treated as "real" and "repaired."
- Never included: CMC bars lose OHLC repair, causing bad time_high/time_low values to propagate into downstream bar computations.

**Consequences:** Subtle data corruption. OHLC bars with wrong time_high/time_low will produce incorrect high-to-close and low-to-close ratios in downstream features. Since the error is in timestamps (not prices), it is easy to miss in aggregate statistics.

**Prevention:**
- The `SourceSpec` dataclass should have a `has_real_time_highlow: bool` flag that controls CTE inclusion. This is already proposed in the todo. Verify it is tested.
- Capture baseline data BEFORE refactoring:
  ```sql
  SELECT src_name, venue, count(*), count(DISTINCT id),
         min(timestamp), max(timestamp),
         avg(EXTRACT(EPOCH FROM (time_high - time_open))) as avg_time_high_offset
  FROM price_bars_1d
  GROUP BY src_name, venue ORDER BY src_name, venue;
  ```
- After refactoring, run `--full-rebuild` for each source and compare row counts AND key aggregate statistics to the baseline. Row count match alone is insufficient -- the data could have different values.
- Write a targeted test: for CMC source, verify that time_high/time_low values that were outside [time_open, time_close] in the raw data are corrected in the output. For TVC/HL source, verify that time_high = time_low = ts.

**Warning signs:**
- Unit test only checking row counts, not OHLC repair behavior
- CMC bars with time_high values outside [time_open, time_close] range (repair not running)
- TVC/HL bars with time_high != ts (repair running when it should not)

**Phase:** 1D bar builder consolidation phase. Must include per-source regression testing, not just row count comparison.

---

### CRITICAL: Rewriting 4 Calendar-Variant EMA Scripts Into One Parameterized Script Can Break the Anchor Logic Silently

**What goes wrong:** The 4 calendar EMA scripts differ in TWO dimensions:
1. **Calendar system:** ISO (week starts Monday) vs US (week starts Sunday)
2. **Anchoring:** Standard calendar (bars align to period boundaries) vs anchored (bars have a fixed anchor point)

These produce different bar boundaries and different EMA values for the same underlying data. The anchor scripts (`ema_multi_tf_cal_anchor.py`) have additional logic for anchor point computation that the standard calendar scripts do not have.

If a consolidated script parameterizes `calendar_system` and `anchor_mode` but gets the combination logic wrong, it will produce bars with incorrect boundaries. For example, anchored ISO bars with US calendar boundaries would silently compute EMAs over wrong time windows. The EMA values would be numerically valid but semantically wrong.

**Why it matters for this system:** EMAs feed directly into regime labeling (`regime_data_loader.py` loads from `ema_multi_tf_u` with specific `alignment_source` filters). Wrong EMA values = wrong regime labels = wrong position sizing.

**Consequences:** Regime labels flip incorrectly. Position sizes change. In paper trading, P&L diverges from backtest. Drift monitor detects the divergence but attributes it to "execution drift" rather than "data computation error."

**Prevention:**
- Do NOT merge anchor and non-anchor logic into a single code path. Keep them as separate template method implementations that share a base class (the existing `BaseEMARefresher` pattern). The parameterization should be `calendar_system: Literal["iso", "us"]`, NOT `anchor_mode: bool`.
- Create a "golden dataset" before refactoring: for 2-3 test assets, export the full EMA history from each of the 4 siloed tables:
  ```sql
  \copy (SELECT * FROM ema_multi_tf_cal_iso WHERE id = 1 ORDER BY ts, tf, period) TO 'golden_ema_cal_iso_id1.csv' CSV HEADER;
  \copy (SELECT * FROM ema_multi_tf_cal_anchor_iso WHERE id = 1 ORDER BY ts, tf, period) TO 'golden_ema_cal_anchor_iso_id1.csv' CSV HEADER;
  ```
- After refactoring, run the consolidated script for the same assets and diff the output against the golden dataset. ANY difference (even in the 15th decimal place) indicates a logic error.
- The diff must compare on matching PK columns `(id, venue_id, ts, tf, period)`, not just row counts.

**Warning signs:**
- Consolidated script producing identical output for ISO and US calendar modes (they should differ)
- Anchor and non-anchor modes producing identical output (they should differ on period boundaries)
- No golden dataset comparison in the test plan

**Phase:** EMA/AMA script consolidation phase. Golden dataset capture is a prerequisite.

---

### MODERATE: The `base_ema_refresher.py` Template Method Pattern Already Consolidates 3 of 4 EMA Scripts -- Consolidating Further May Not Save Significant Code

**What goes wrong:** The existing codebase already has `base_ema_refresher.py` that implements the Template Method pattern for EMA scripts. The 3 subclasses (`refresh_ema_multi_tf_from_bars.py`, `refresh_ema_multi_tf_cal_from_bars.py`, `refresh_ema_multi_tf_cal_anchor_from_bars.py`) implement only the variant-specific methods. Further consolidation (merging these 3 into 1 with parameters) saves ~100-200 lines of boilerplate but adds conditional complexity that makes the code harder to understand and debug.

The same pattern exists for AMAs (`base_ama_feature.py` is the template, with `ama_multi_tf_cal.py` and `ama_multi_tf_cal_anchor.py` as subclasses).

**Risk:** Over-consolidation produces a "god script" with complex conditional branches that is harder to maintain than 3 focused scripts with a shared base class.

**Prevention:**
- Evaluate the actual LOC savings before consolidating. If the subclasses are <200 lines each and differ primarily in configuration (table names, calendar mode), a configuration-driven approach may work. If they differ in algorithm (anchor computation logic), keep them as separate subclasses.
- The consolidation goal should be "fewer TABLE FAMILIES" (drop the 4 siloed variants, keep only the _u table), not necessarily "fewer script files." Having 3 script files that write to 1 table is fine.
- Measure the maintenance burden: how often have bugs been copy-pasted across the variant scripts? If rarely, the duplication is not causing real problems.

**Warning signs:**
- Consolidated script with >5 `if calendar_mode == ...` branches in core computation logic
- Consolidated script that is longer than the sum of the scripts it replaced
- Developers needing to understand all variants to modify one

**Phase:** Planning phase. Decide consolidation scope BEFORE writing code.

---

## 4. Data Integrity & Downstream Consumer Pitfalls

### CRITICAL: 21+ Downstream Scripts Read From _u Tables -- Changing PK Structure or Column Names Breaks Them Silently

**What goes wrong:** Grep shows 25 files that reference `alignment_source` and 21+ files that query _u tables. These include:
- `regime_data_loader.py` (regime labeling)
- `daily_features_view.py` (feature store)
- `vol_feature.py`, `ta_feature.py`, `rolling_extremes_feature.py` (features)
- `run_ic_sweep.py`, `run_optuna_sweep.py` (ML)
- `run_portfolio_backtest.py` (portfolio)
- `risk_engine.py` (risk)
- `audit_returns_ema_multi_tf_u_integrity.py` (data quality)

If the consolidation changes the _u table schema (adding columns, renaming columns, changing PK), every downstream consumer must be updated. A single missed consumer will fail at runtime with a SQL error, or worse, silently return wrong results if a column was renamed.

**Why it matters for this system:** The _u tables are the primary read interface for all downstream analytics. The consolidation's goal is to eliminate the siloed tables and make _u tables the write target. But the _u table schema was designed for the sync pattern (it has `alignment_source` in the PK to distinguish data sources). If consolidation changes the semantics of `alignment_source`, downstream queries that filter on it will break.

**Consequences:** Runtime failures in feature computation, regime labeling, signal generation, and portfolio allocation. The daily pipeline will fail at the first downstream step that touches a changed table.

**Prevention:**
- The _u table schema should NOT change during consolidation. The consolidation changes WHERE data is written (directly vs via sync), not WHAT the table looks like. If schema changes are needed, do them in a separate migration.
- Create a comprehensive grep inventory of all files that reference each _u table:
  ```bash
  grep -rn "ema_multi_tf_u" src/ta_lab2/ --include="*.py" | grep -v __pycache__
  ```
  For each file found, verify that the query still works after consolidation.
- Add a smoke test that runs the full daily pipeline on 1-2 test assets after consolidation:
  ```bash
  python -m ta_lab2.scripts.run_daily_refresh --all --ids 1 --dry-run
  ```
  If `--dry-run` is not available for all stages, run with a single asset to minimize risk.

**Warning signs:**
- _u table schema changes bundled with script consolidation in the same PR
- No grep audit of downstream consumers before migration
- Daily pipeline succeeding for bars/EMAs but failing at features/regimes/signals

**Detection:** Post-migration, run the full pipeline for 1 asset end-to-end and verify all stages complete.

**Phase:** Pre-migration audit phase. Consumer inventory must be complete before any changes.

---

### CRITICAL: ON CONFLICT Behavior Differs Between DO NOTHING (Sync Pattern) and DO UPDATE (Direct Write) -- Switching Patterns Can Cause Data Overwrites

**What goes wrong:** The current sync pattern uses `ON CONFLICT DO NOTHING`:
```python
# sync_utils.py line 196
ON CONFLICT ({pk_sql}) DO NOTHING
```
This is safe because the sync just copies data -- if it already exists, skip it. But direct-write scripts typically use `ON CONFLICT DO UPDATE` to ensure the latest computation overwrites any previous value:
```python
# ema_state_manager.py line 309
ON CONFLICT (id, venue_id, tf, period) DO UPDATE SET
    last_canonical_ts = EXCLUDED.last_canonical_ts,
    ...
```

If a consolidated script writes directly to the _u table with `DO UPDATE`, and a sync script also runs for the same `alignment_source` with `DO NOTHING`, the behavior depends on execution order. If the sync runs first (with old data), then the direct-write runs (with new data), the final result is correct. If the direct-write runs first and the sync runs later, the sync skips the rows (DO NOTHING), which is also correct. BUT if both run simultaneously, there is a race condition where the sync could insert an old version of a row between the direct-write's DELETE and INSERT (if the direct-write uses the scoped DELETE + INSERT pattern from feature scripts).

**Consequences:** Stale data in the _u table that is overwritten on the next run, causing a 1-cycle data staleness window. For daily refreshes this is a 24-hour data lag.

**Prevention:**
- During the transition period, do NOT run both sync scripts and direct-write scripts for the same `alignment_source`. Migrate one alignment_source at a time:
  1. Rewrite the cal_iso EMA script to write to _u directly
  2. Remove cal_iso from the sync script's source list
  3. Verify data integrity
  4. Repeat for cal_us, cal_anchor_iso, cal_anchor_us
- If parallel running is unavoidable, ensure the direct-write script uses `ON CONFLICT DO UPDATE` (not DO NOTHING) so it always wins over stale sync data.
- Add an `updated_at` column (or use `ingested_at`) to track which process last wrote each row. Monitor for rows where `ingested_at` is older than expected.

**Warning signs:**
- Both sync and direct-write scripts enabled for the same alignment_source
- Rows in _u table with `ingested_at` timestamps older than the last direct-write run
- Daily refresh running sync scripts for alignment_sources that are already handled by direct-write scripts

**Phase:** Script rewrite phase. Transition one alignment_source at a time.

---

### MODERATE: The `run_daily_refresh.py` Orchestrator Hardcodes Script Paths -- Consolidated Scripts Need New Entries

**What goes wrong:** The daily refresh orchestrator (`run_daily_refresh.py`) runs scripts via `subprocess.Popen` with hardcoded script paths:
```python
TIMEOUT_BARS = 7200  # bar builders
TIMEOUT_EMAS = 3600  # EMA refreshers
TIMEOUT_AMAS = 3600  # AMA refreshers
```
The orchestrator calls `run_all_bar_builders.py`, which has a `BuilderConfig` list:
```python
ALL_BUILDERS = [
    BuilderConfig(name="1d", script_path="refresh_price_bars_1d.py", ...),
    BuilderConfig(name="1d_tvc", script_path="refresh_tvc_price_bars_1d.py", ...),
    BuilderConfig(name="1d_hl", script_path="refresh_hl_price_bars_1d.py", ...),
    ...
]
```

When the 3 source-specific 1D builders are consolidated into one, the `BuilderConfig` entries must be updated. If the old script paths remain and the old files are deleted, `run_all_bar_builders.py` will fail with `FileNotFoundError`.

**Prevention:**
- Update `run_all_bar_builders.py` in the SAME commit that deletes old scripts. Never leave the orchestrator pointing at deleted files.
- The consolidated builder should accept `--source cmc|tvc|hl|all` as already proposed in the todo. Update `BuilderConfig` entries to pass the appropriate `--source` flag.
- Add a smoke test: `python -m ta_lab2.scripts.bars.run_all_bar_builders --ids 1 --dry-run` should complete without errors after the change.
- Similarly, update `run_daily_refresh.py` if it calls any of the deleted scripts directly (check via grep).

**Warning signs:**
- `run_all_bar_builders.py` referencing script files that no longer exist
- Daily pipeline failing at the bars stage with `FileNotFoundError` or `ModuleNotFoundError`
- New consolidated script not callable via the orchestrator

**Detection:** After script deletion, run `python -m ta_lab2.scripts.bars.run_all_bar_builders --dry-run` to verify.

**Phase:** Script consolidation phase. Orchestrator updates and script deletion must be atomic.

---

## 5. PostgreSQL Performance & Storage Pitfalls

### MODERATE: Dropping 30 Tables Does Not Immediately Reclaim Disk Space on Windows -- VACUUM Is Required for the Tablespace

**What goes wrong:** When PostgreSQL drops a table, it unlinks the data files, but the OS may not immediately reclaim the space (especially on NTFS with write-ahead log and Windows file handle caching). The `pg_total_relation_size()` will show 0 for the dropped table, but `du` on the PostgreSQL data directory may still show the old size for some time.

More importantly: if the tables were heavily updated before dropping (e.g., a final sync was run), the WAL segments generated by those updates persist until checkpointed. On a system with `max_wal_size = 1GB` (default), the WAL can grow significantly during large operations.

**Why it matters for this system:** The AMA tables alone are ~57M rows each. On a local Windows development machine (not a server), disk space may be constrained. If all 30 tables are dropped in sequence with WAL generation, temporary disk usage could spike before it decreases.

**Consequences:** "No space left on device" errors if disk is near capacity during migration. WAL archive growth if archiving is enabled.

**Prevention:**
- Check disk space before starting: ensure at least 2x the size of the largest table being dropped is available as free space.
  ```sql
  SELECT pg_size_pretty(pg_total_relation_size('ama_multi_tf')) AS ama_size;
  ```
- After dropping each table family, run `CHECKPOINT;` to force WAL flush:
  ```sql
  DROP TABLE IF EXISTS ama_multi_tf;
  DROP TABLE IF EXISTS ama_multi_tf_state;
  CHECKPOINT;
  ```
- Do NOT run `VACUUM FULL` on remaining tables during the migration window. Regular `VACUUM` is sufficient and non-blocking.
- Monitor disk usage during migration: `SELECT pg_size_pretty(pg_database_size('marketdata'));`

**Warning signs:**
- Database size not decreasing after table drops (check `pg_database_size()`)
- WAL directory growing unexpectedly (check `pg_wal_lsn_diff()`)
- "could not extend file" errors during migration

**Phase:** Table drop phase. Monitor disk space throughout.

---

### MODERATE: Indexes on _u Tables May Need Rebuilding After Direct-Write Migration Changes Access Patterns

**What goes wrong:** The _u tables currently have indexes optimized for the sync pattern (bulk INSERT from source tables). When scripts switch to direct writes (INSERT one batch at a time, per-id), the index maintenance cost per INSERT increases. Additionally, if the _u table was initially populated via bulk INSERT (ordered by source table), the index pages are well-organized. After months of per-id direct writes, the index becomes fragmented, leading to B-tree bloat.

This is a long-term concern (months), not an immediate migration risk. But it should be planned for.

**Prevention:**
- After the migration is complete and the system has been running for 2-4 weeks, check index bloat:
  ```sql
  SELECT
      schemaname, tablename, indexname,
      pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
      idx_scan, idx_tup_read, idx_tup_fetch
  FROM pg_stat_user_indexes
  WHERE tablename LIKE '%_u'
  ORDER BY pg_relation_size(indexrelid) DESC;
  ```
- If index bloat exceeds 30%, run `REINDEX CONCURRENTLY` (PostgreSQL 12+):
  ```sql
  REINDEX INDEX CONCURRENTLY idx_ema_multi_tf_u_pk;
  ```
  `CONCURRENTLY` avoids the ACCESS EXCLUSIVE lock that a normal REINDEX would require.
- Consider adding partial indexes for common access patterns (e.g., `WHERE alignment_source = 'multi_tf'`) if queries become slow.

**Warning signs:**
- Query performance degradation on _u tables 2-4 weeks after migration
- Index size growing faster than data size
- `EXPLAIN ANALYZE` showing index scans taking significantly longer than before migration

**Phase:** Post-migration monitoring phase. Schedule an index health check 4 weeks after cutover.

---

## 6. Data Verification & Rollback Pitfalls

### CRITICAL: No Rollback Plan for a Migration That Drops 30 Tables -- Once Data Is Gone, It Is Gone

**What goes wrong:** `DROP TABLE` is not reversible. Once the siloed tables are dropped, the only way to recover that data is from a backup. If the _u table data is found to be incorrect after the siloed tables are dropped, there is no way to re-derive it.

The current architecture provides a natural safety net: the _u tables are populated FROM the siloed tables via sync. If the _u table has a bug, the siloed tables are the source of truth. After the siloed tables are dropped, the _u tables become the only copy. Any corruption in the _u table is permanent.

**Why it matters for this system:** The "no deletion" project convention (`Always archive (files, data, columns)`) explicitly prohibits deleting data. Dropping 30 tables with 200M+ total rows is the single largest data deletion in the project's history.

**Consequences:** Unrecoverable data loss if the _u table data is discovered to be incomplete or incorrect after drops.

**Prevention:**
- Create a `pg_dump` backup of all 30 siloed tables before dropping them:
  ```bash
  pg_dump -U postgres -d marketdata \
    -t ema_multi_tf -t ema_multi_tf_cal_iso -t ema_multi_tf_cal_us \
    -t ema_multi_tf_cal_anchor_iso -t ema_multi_tf_cal_anchor_us \
    --format=custom --file=siloed_tables_backup_20260319.dump
  ```
  For the 57M-row AMA tables, the dump will be large (~5-10GB). Ensure disk space is available.
- Alternatively, rename rather than drop:
  ```sql
  ALTER TABLE ema_multi_tf RENAME TO _archive_ema_multi_tf;
  ```
  This preserves the data while removing it from the active namespace. Archive tables can be dropped later (30-60 days) after thorough verification.
- Verify data completeness BEFORE dropping:
  ```sql
  -- For each family, verify _u table has >= the siloed table's row count
  SELECT 'ema_multi_tf' AS source,
         (SELECT COUNT(*) FROM ema_multi_tf) AS source_count,
         (SELECT COUNT(*) FROM ema_multi_tf_u WHERE alignment_source = 'multi_tf') AS u_count;
  ```
  The _u count should be >= the source count (it may be higher if other alignment_sources contribute rows).
- Run aggregate checksums (not just row counts):
  ```sql
  SELECT alignment_source,
         COUNT(*) AS n_rows,
         SUM(HASHTEXT(id::text || tf || period::text || ts::text)) AS row_hash
  FROM ema_multi_tf_u
  GROUP BY alignment_source;
  ```
  Store these checksums. After migration, re-run and verify they have not changed.

**Warning signs:**
- Plan to drop tables without a backup or archive strategy
- No row count verification between siloed and _u tables before dropping
- Dropping tables in the same transaction as schema changes (if the schema change fails, the drop is rolled back -- but if they are in separate transactions, the drop may succeed while the schema change fails)

**Detection:** Pre-drop verification script that compares row counts and checksums for every siloed table against its _u counterpart.

**Phase:** Pre-drop phase. Verification and backup must be complete before any drops.

---

### MODERATE: Alembic Migration for Table Drops Should Be Separate From Script Refactoring to Enable Independent Rollback

**What goes wrong:** If the Alembic migration (drop tables) and the script refactoring (new consolidated scripts) are deployed simultaneously and something goes wrong, it is impossible to roll back just one part. The Alembic downgrade would need to recreate the dropped tables, which requires data -- but the data is gone.

**Prevention:**
- Split the migration into phases with independent rollback:
  1. **Phase A: Script consolidation** (no schema changes). Rewrite scripts to write to _u directly. Keep siloed tables and sync scripts. Both paths write to _u -- redundant but safe. Rollback: revert to old scripts.
  2. **Phase B: Validation** (no schema changes). Run both old and new paths in parallel for 1-2 weeks. Compare outputs. Rollback: N/A (verification only).
  3. **Phase C: Disable sync** (no schema changes). Stop running sync scripts. Siloed tables stop receiving new data but retain historical data. Rollback: re-enable sync scripts.
  4. **Phase D: Archive/drop tables** (Alembic migration). Rename or drop siloed tables. Rollback: rename back (if renamed) or restore from backup (if dropped).
- Each phase can be rolled back independently. Phase D is the only irreversible step.

**Warning signs:**
- Single PR that both refactors scripts AND drops tables
- No parallel-running validation period
- Alembic migration that drops tables with no corresponding downgrade that can restore data

**Phase:** Planning phase. Phase structure must be defined before implementation begins.

---

## Phase-Specific Warnings Summary

| Phase Topic | Likely Pitfall | Severity | Mitigation |
|---|---|---|---|
| Pre-migration inventory | Dependent views (corr_latest, all_emas) silently dropped by CASCADE | Critical | Catalog all dependent views; recreate pointing at _u tables |
| Pre-migration inventory | Downstream _u table consumers not audited | Critical | Grep inventory of all 21+ files; smoke test full pipeline |
| Pre-migration backup | No rollback plan after 200M+ row drop | Critical | pg_dump or RENAME TO _archive before any drops |
| Constants & contracts | alignment_source values inconsistent between old sync and new direct-write | Moderate | Constants module with CHECK constraint on _u tables |
| Script consolidation (1D bars) | Source-specific SQL logic lost during consolidation | Critical | Golden dataset comparison per source; per-source regression tests |
| Script consolidation (EMAs) | Anchor vs non-anchor logic merged incorrectly | Critical | Golden dataset export; diff to 15th decimal place; keep separate subclasses |
| Script consolidation (orchestrator) | run_all_bar_builders.py referencing deleted scripts | Moderate | Update orchestrator in same commit as script deletion |
| Watermark migration | State table watermarks misaligned with new write target | Critical | Populate new state table from _u actual data; or full-rebuild first run |
| Watermark migration | ingested_at NULL in direct-written rows breaks sync watermark | Critical | NOT NULL constraint on ingested_at; explicit now() in all INSERTs |
| Transition period | Sync and direct-write both active for same alignment_source | Critical | Migrate one alignment_source at a time; disable sync before enabling direct-write |
| Table drops | ACCESS EXCLUSIVE lock blocks concurrent queries during drop | Critical | Drop during maintenance window; SET statement_timeout; verify no active sessions |
| Table drops | Orphaned state tables confuse future debugging | Moderate | Drop state tables alongside data tables; post-drop inventory |
| Table drops | FK constraints from dim_venues block drops | Moderate | Drop siloed tables before modifying dimension tables |
| Disk space | WAL growth during mass table drops on Windows | Moderate | CHECKPOINT between drop batches; monitor disk usage |
| Post-migration | Index bloat on _u tables after access pattern change | Moderate | Schedule REINDEX CONCURRENTLY 4 weeks post-migration |
| Post-migration | No verification that dropped data was fully captured in _u | Critical | Row count + checksum comparison before any drops |

---

## Sources

- [PostgreSQL Documentation: DROP TABLE](https://www.postgresql.org/docs/current/sql-droptable.html) -- HIGH confidence (official documentation on CASCADE behavior and locking)
- [PostgreSQL Documentation: Routine Vacuuming](https://www.postgresql.org/docs/current/routine-vacuuming.html) -- HIGH confidence (official documentation on VACUUM, bloat, and space reclamation)
- [Cybertec: Why VACUUM doesn't shrink PostgreSQL tables](https://www.cybertec-postgresql.com/en/vacuum-does-not-shrink-my-postgresql-table/) -- MEDIUM confidence (authoritative PostgreSQL consultancy)
- [Pete Graham: Rename Postgres table with Alembic migrations](https://petegraham.co.uk/rename-postgres-table-with-alembic/) -- MEDIUM confidence (practitioner guide, consistent with Alembic docs)
- [Alembic Documentation: Auto Generating Migrations](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) -- HIGH confidence (official documentation on rename detection limitations)
- [Sequin: Using watermarks for CDC in Postgres](https://blog.sequinstream.com/using-watermarks-to-coordinate-change-data-capture-in-postgres/) -- MEDIUM confidence (practitioner article, details race conditions in watermark-based sync)
- [Airbyte: 5 Critical ETL Pipeline Design Pitfalls (2026)](https://airbyte.com/data-engineering-resources/etl-pipeline-pitfalls-to-avoid) -- MEDIUM confidence (general ETL best practices)
- [Monte Carlo: Data Migration Risks Checklist](https://www.montecarlodata.com/blog-data-migration-risks-checklist/) -- MEDIUM confidence (practitioner checklist for data migration)
- [Codacy: How to update large tables in PostgreSQL](https://blog.codacy.com/how-to-update-large-tables-in-postgresql) -- MEDIUM confidence (practical guide to batch operations)
- Codebase direct inspection -- HIGH confidence. Examined:
  - `sync_utils.py` (watermark pattern, ON CONFLICT DO NOTHING, alignment_source derivation)
  - `ema_state_manager.py` (state table schema with venue_id, watermark logic)
  - `base_ema_refresher.py` (Template Method pattern, 3 subclasses)
  - `sync_price_bars_multi_tf_u.py` (5 source tables, PK structure, sync pattern)
  - `run_all_bar_builders.py` (BuilderConfig hardcoded paths, ALL_BUILDERS list)
  - `run_daily_refresh.py` (orchestrator timeout tiers, stage ordering)
  - `regime_data_loader.py` (alignment_source = 'multi_tf' filter for daily EMAs)
  - `daily_features_view.py` (FeaturesStore reading from _u tables)
  - `common_snapshot_contract.py` (DDL generation, table type enum)
  - `a0b1c2d3e4f5_strip_cmc_prefix_add_venue_id.py` (FK constraints, view recreation, 80 table renames)
  - `.planning/todos/pending/2026-03-15-consolidate-1d-bar-builders.md` (SourceSpec design, per-source differences)
