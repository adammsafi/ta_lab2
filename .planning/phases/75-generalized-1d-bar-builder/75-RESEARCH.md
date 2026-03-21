# Phase 75: Generalized 1D Bar Builder - Research

**Researched:** 2026-03-20
**Domain:** Python bar builder consolidation, SQL CTE template execution, psycopg integration
**Confidence:** HIGH (all findings from direct codebase inspection)

---

## Summary

Phase 75 consolidates three source-specific 1D bar builder scripts (CMC, TVC, HL) into a
single `refresh_price_bars_1d.py` script that dispatches by `--source cmc|tvc|hl|all`. The
Phase 74 foundation is complete: `ta_lab2.db.psycopg_helpers` is live, and `dim_data_sources`
has been seeded with all three sources including full SQL CTE templates.

The generalized builder's job is narrow: (1) read a `dim_data_sources` row by `source_key`,
(2) load asset IDs via that row's `id_loader_sql`, (3) iterate IDs and for each ID execute the
`src_cte_template` (interpolating `{dst}` and `{src}` placeholders), (4) update the state table,
and (5) upsert coverage. The existing `OneDayBarBuilder` class (CMC-only) provides the backbone;
it needs to become source-aware rather than being replaced entirely.

**Primary recommendation:** Rewrite `refresh_price_bars_1d.py` to accept `--source` and load
per-source config from `dim_data_sources`. Keep `BaseBarBuilder` inheritance and the psycopg
connection pattern. Add `--source` arg, `_load_source_spec()` helper, and branch the
`build_bars_for_id()` logic on `ohlc_repair` flag from the spec. Delete the two old files when
tests pass.

---

## Standard Stack

### Core (already present - no new installs needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ta_lab2.db.psycopg_helpers` | local | psycopg v3/v2 dual-driver helpers | Built in Phase 74-01 |
| `dim_data_sources` (PostgreSQL) | live | Per-source config + SQL CTE templates | Built in Phase 74-02 |
| `BaseBarBuilder` (abstract) | local | Template-method orchestration, state mgmt | Existing pattern |
| `BarBuilderConfig` (dataclass) | local | Frozen config object | Existing pattern |
| `common_snapshot_contract` | local | `resolve_db_url`, `get_engine`, `ensure_coverage_table`, `upsert_coverage`, `parse_ids` | Existing helpers |

### No new dependencies required

Phase 75 adds zero new pip packages. All needed infrastructure (psycopg helpers, dim_data_sources,
BaseBarBuilder, argument parser helpers) already exists.

---

## Architecture Patterns

### Recommended Project Structure (files affected)

```
src/ta_lab2/scripts/bars/
    refresh_price_bars_1d.py        # REWRITE: add --source, generalize
    refresh_tvc_price_bars_1d.py    # DELETE after tests pass
    refresh_hl_price_bars_1d.py     # DELETE after tests pass
    run_all_bar_builders.py         # UPDATE: replace 1d_tvc + 1d_hl entries
```

### Pattern 1: Source Spec Loading from dim_data_sources

```python
# Source: alembic/versions/g1h2i3j4k5l6_dim_data_sources_and_alignment_checks.py
# (dim_data_sources columns documented here)

def _load_source_spec(conn, source_key: str) -> dict:
    """Load per-source config from dim_data_sources."""
    row = fetchone(
        conn,
        """
        SELECT source_key, source_name, source_table, venue_id, default_venue,
               ohlc_repair, has_market_cap, has_timehigh,
               id_loader_sql, src_cte_template,
               join_clause, id_filter_sql, ts_column,
               conflict_columns, src_name_label, description
        FROM public.dim_data_sources
        WHERE source_key = %s
        """,
        [source_key],
    )
    if not row:
        raise ValueError(f"Unknown source_key: {source_key!r}. "
                         f"Run: SELECT source_key FROM dim_data_sources")
    cols = [
        "source_key", "source_name", "source_table", "venue_id", "default_venue",
        "ohlc_repair", "has_market_cap", "has_timehigh",
        "id_loader_sql", "src_cte_template",
        "join_clause", "id_filter_sql", "ts_column",
        "conflict_columns", "src_name_label", "description",
    ]
    return dict(zip(cols, row))
```

### Pattern 2: CTE Template Execution

The SQL templates in `dim_data_sources.src_cte_template` use two kinds of substitution:

- `{dst}` / `{src}` — Python `.format()` for structural table name injection (cannot be
  parameterized in SQL)
- `%s` — psycopg positional parameters for runtime data values (id, timestamps)

```python
# Source: alembic/versions/g1h2i3j4k5l6 — _CMC_CTE_TEMPLATE, _TVC_CTE_TEMPLATE, _HL_CTE_TEMPLATE

def _build_sql_from_template(spec: dict, dst: str) -> str:
    """Interpolate {dst} and {src} structural placeholders."""
    template = spec["src_cte_template"]
    # HL template has no {src} (source is fixed in the CTE JOIN)
    if "{src}" in template:
        return template.format(dst=dst, src=spec["source_table"])
    return template.format(dst=dst)
```

### Pattern 3: Per-Source ID Loading

Each source has its own `id_loader_sql` in `dim_data_sources`:

```python
# Source: dim_data_sources seed data (see alembic migration)
# CMC:  "SELECT DISTINCT id FROM public.cmc_price_histories7"
# TVC:  "SELECT DISTINCT id FROM public.tvc_price_histories"
# HL:   "SELECT DISTINCT dai.id FROM dim_asset_identifiers dai
#         JOIN hyperliquid.hl_candles c
#           ON dai.id_type = 'HL' AND dai.id_value::int = c.asset_id
#         WHERE c.interval = '1d' ORDER BY dai.id"
#
# Note: HL builder currently also filters via HL_YN.csv (Y-marked assets only).
# The id_loader_sql loads ALL HL assets. The --csv filter is source-specific
# behavior that either needs to be preserved or dropped (see Open Questions).

def _load_ids_for_source(conn, spec: dict) -> list[int]:
    """Execute id_loader_sql to get all asset IDs for a source."""
    rows = fetchall(conn, spec["id_loader_sql"])
    return [int(r[0]) for r in rows]
```

### Pattern 4: State Table PK Differences

The three existing builders have diverged state table PKs:

| Builder | State table PK | venue_id column |
|---------|---------------|-----------------|
| CMC (`refresh_price_bars_1d.py`) | `(id, tf)` | No |
| TVC (`refresh_tvc_price_bars_1d.py`) | `(id, tf)` | No |
| HL (`refresh_hl_price_bars_1d.py`) | `(id, venue_id, tf)` | YES (hardcoded `_HL_VENUE_ID = 2`) |

The generalized builder must use `(id, venue_id, tf)` as the unified PK to support all sources.
The state table DDL in `OneDayBarBuilder.ensure_state_table_exists()` has TWO different DDLs
(CMC/TVC use `(id, tf)`, HL uses `(id, venue_id, tf)`). The migration path:

1. Use `(id, venue_id, tf)` as state table PK in the new unified builder
2. Pre-migrate existing CMC/TVC state rows by setting `venue_id` from the source spec
3. This avoids state loss during transition

### Pattern 5: Backfill Detection (CMC-only currently)

The backfill detection logic (`_check_for_backfill`, `_handle_backfill`) is currently CMC-only
(`refresh_price_bars_1d.py` lines 107-131). It checks if new historical data appeared BEFORE
`daily_min_seen`. The generalization requires:

1. Track `daily_min_seen` per source in the state table (already in the schema)
2. Query MIN timestamp from the source-specific table (different column name: `timestamp` for
   CMC, `ts` for TVC/HL)
3. The `ts_column` field in `dim_data_sources` encodes this difference:
   - CMC: `ts_column = 'timestamp'`
   - TVC: `ts_column = 'ts'`
   - HL: `ts_column = 'ts'`

```python
# Source: refresh_price_bars_1d.py lines 107-131
def _check_for_backfill_generic(conn, spec: dict, id_: int,
                                state_dict: Optional[dict]) -> bool:
    """Check if historical data was backfilled before first processed date."""
    if state_dict is None or state_dict.get("daily_min_seen") is None:
        return False

    ts_col = spec["ts_column"]  # 'timestamp' or 'ts'
    src = spec["source_table"]
    row = fetchone(
        conn,
        f"SELECT MIN({ts_col}) FROM {src} WHERE id = %s",
        [id_],
    )
    if row and row[0] is not None:
        return str(row[0]) < state_dict["daily_min_seen"]
    return False
```

### Pattern 6: run_all_bar_builders.py Update

The orchestrator currently lists `1d`, `1d_tvc`, and `1d_hl` as separate entries. After Phase 75
these collapse to three invocations of the same script:

```python
# Current ALL_BUILDERS list entries (from run_all_bar_builders.py lines 52-72):
#   name="1d",     script_path="refresh_price_bars_1d.py"
#   name="1d_tvc", script_path="refresh_tvc_price_bars_1d.py"  # DELETE
#   name="1d_hl",  script_path="refresh_hl_price_bars_1d.py"   # DELETE

# Replacement pattern:
BuilderConfig(
    name="1d_cmc",
    script_path="refresh_price_bars_1d.py",
    description="1D canonical bars from CMC",
    requires_tz=False,
    supports_full_rebuild=True,
    custom_args={"source": "cmc"},
),
BuilderConfig(
    name="1d_tvc",
    script_path="refresh_price_bars_1d.py",
    description="1D canonical bars from TradingView",
    requires_tz=False,
    supports_full_rebuild=True,
    custom_args={"source": "tvc"},
),
BuilderConfig(
    name="1d_hl",
    script_path="refresh_price_bars_1d.py",
    description="1D canonical bars from Hyperliquid",
    requires_tz=False,
    supports_full_rebuild=True,
    custom_args={"source": "hl"},
),
```

The `build_command()` function needs updating to pass `--source <value>` from `custom_args`.
Note: the name `"1d_tvc"` and `"1d_hl"` are preserved so existing `--builders 1d_tvc` invocations
keep working. The name `"1d"` becomes `"1d_cmc"` (or alternatively add `--source all` as the
default for backwards compat).

### Anti-Patterns to Avoid

- **Duplicating SQL templates in Python:** The SQL CTEs live in `dim_data_sources`. The Python
  builder reads them; it never redefines them. If a template needs changing, UPDATE the DB row.
- **Hardcoding `_HL_VENUE_ID = 2`:** The venue_id is in `spec["venue_id"]`. Use the spec.
- **Forking `build_bars_for_id()` per source:** The only real branching is `ohlc_repair`
  (CMC needs it; TVC/HL do not) and `has_market_cap` (CMC has it; TVC/HL use NULL). The CTE
  templates already handle this divergence in SQL — the Python method stays unified.
- **Re-implementing HL_YN.csv filtering inside the generalized builder:** See Open Questions.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SQL CTE templates | New Python CTE builder functions | `dim_data_sources.src_cte_template` | Already seeded in Phase 74-02 |
| psycopg v2/v3 detection | Per-file driver-detection boilerplate | `ta_lab2.db.psycopg_helpers.connect` | Shared module built in Phase 74-01 |
| ON CONFLICT clause | Build dynamically | `spec["conflict_columns"]` string from DB | Already stored correctly as `id,venue_id,tf,bar_seq,timestamp` |
| Asset ID loading | New per-source Python functions | `spec["id_loader_sql"]` executed via `fetchall` | Already in dim table |
| DB URL resolution | New URL parsing | `common_snapshot_contract.resolve_db_url` | Already handles db_config.env + env vars |

---

## Common Pitfalls

### Pitfall 1: State Table PK Mismatch

**What goes wrong:** CMC/TVC state rows use `(id, tf)` PK; HL state rows use `(id, venue_id, tf)`.
If the unified builder always writes `venue_id`, existing CMC/TVC state rows won't be found by the
new upsert (different conflict target), causing full rebuilds for already-processed assets.

**Why it happens:** The CMC and TVC builders were written before `venue_id` was added to analytics
tables.

**How to avoid:** The new builder must migrate state: when `ensure_state_table_exists()` runs,
ALTER TABLE to add `venue_id` column if missing, then backfill from the source spec's `venue_id`.
Alternatively, use `ON CONFLICT (id, tf) DO UPDATE SET venue_id = ...` with a dual-PK approach.
The cleanest path: the new DDL uses `(id, venue_id, tf)` as PK; the migration step backfills
`venue_id = spec["venue_id"]` for rows with NULL `venue_id` before the first run.

**Warning signs:** Full rebuild runs for all CMC/TVC assets even though they were already built.

### Pitfall 2: TVC ON CONFLICT Clause in CTE Template

**What goes wrong:** The `_TVC_CTE_TEMPLATE` in the Alembic migration (lines 407-432) has:
`ON CONFLICT (id, venue_id, tf, bar_seq, "timestamp") DO UPDATE SET ...` but does NOT include
`venue_id` in the INSERT column list (the `ins AS (INSERT INTO {dst} (...) ...)` section).
If `venue_id` is required NOT NULL in the destination table, the INSERT will fail.

**Why it happens:** The TVC template was extracted from the old builder which predated the
venue_id migration. The migration fixed the ON CONFLICT target but may not have added `venue_id`
to the SELECT list.

**How to avoid:** Before planning tasks, verify the TVC and HL CTE templates in the live DB:
```sql
SELECT source_key,
       src_cte_template LIKE '%venue_id%' AS has_venue_id_in_template
FROM dim_data_sources;
```
If `venue_id` is missing from TVC's INSERT columns, UPDATE the template in dim_data_sources
as a pre-task fix.

**Warning signs:** `null value in column "venue_id"` errors when running `--source tvc`.

### Pitfall 3: HL ID Loader SQL and HL_YN.csv Divergence

**What goes wrong:** The existing `_load_hl_ids()` filters by HL_YN.csv (Y-marked assets only),
but `dim_data_sources.id_loader_sql` for HL loads ALL HL assets via dim_asset_identifiers JOIN.
Running `--source hl --ids all` with the generalized builder would process more assets than
the old builder did, breaking the row count parity check (BAR-08).

**Why it happens:** The HL_YN.csv filter was a business decision made when writing the HL builder
but was not encoded in dim_data_sources.

**How to avoid:** Either:
(a) Accept the broader scope: process ALL HL assets (removes CSV dependency, cleaner)
(b) Add a `--csv` flag to the generalized builder for HL-specific filtering, but only apply when
    `source_key == 'hl'`
(c) UPDATE the HL `id_loader_sql` in dim_data_sources to incorporate a WHERE filter based on
    a DB table instead of a CSV file

Option (a) is cleanest but changes row counts (BAR-08 baseline must be re-captured for HL).
Option (b) introduces source-specific code back into the supposedly generic builder.
Option (c) requires a separate migration. Document this choice explicitly in the plan.

### Pitfall 4: `_sync_1d_to_multi_tf()` Not Present in CMC Builder

**What goes wrong:** Both the TVC and HL builders call `_sync_1d_to_multi_tf(db_url)` after
`builder.run()` (see `refresh_tvc_price_bars_1d.py` line 447 and `refresh_hl_price_bars_1d.py`
line 511). The CMC builder does NOT have this step. After consolidation, if the generalized
builder always calls the sync, CMC assets would be double-synced (or synced unnecessarily).

**Why it happens:** CMC writes directly to `price_bars_1d` which IS `price_bars_multi_tf` for
CMC assets in the current schema. TVC/HL builders write to `price_bars_1d` then sync to
`price_bars_multi_tf` with a filter on `src_name`.

**How to avoid:** Check whether `price_bars_1d` and `price_bars_multi_tf` are still separate
tables or if they've been merged. If they ARE separate, the generalized builder should conditionally
call sync based on whether the source's `src_name_label` differs from 'CoinMarketCap'. If they
are the SAME table (direct-to-multi_tf writes), no sync step is needed.

**Warning signs:** Duplicate rows or incorrect row counts in `price_bars_multi_tf`.

### Pitfall 5: Python `.format()` Collision with `%s` Parameters

**What goes wrong:** The CTE templates contain both Python `.format()` style placeholders
(`{dst}`, `{src}`) AND psycopg `%s` placeholders. If the template text is accidentally passed
through `.format()` with extra kwargs, or if `%s` sequences appear in string interpolation context,
errors occur.

**Why it happens:** Mixed interpolation systems in the same SQL string.

**How to avoid:** Always interpolate `{dst}` and `{src}` with `.format(dst=..., src=...)` FIRST,
producing a complete SQL string, THEN pass that string to `fetchone(conn, sql, params)` with
positional `%s` params. Never use `f-strings` or `.format()` on the already-interpolated SQL.

```python
# CORRECT
sql = template.format(dst=dst_table, src=src_table)
row = fetchone(conn, sql, [id_, last_src_ts, last_src_ts, ...])

# WRONG - would try to format %s as a named arg
sql = template.format(dst=dst_table, src=src_table, id=id_)  # KeyError: 's'
```

### Pitfall 6: CMC Backfill Detection Requires Extra psycopg Parameters

**What goes wrong:** The CMC CTE template (11 `%s` positional params) differs from TVC/HL
templates (6 `%s` positional params). If a single `build_bars_for_id()` method constructs the
params list generically without knowing which source it's dealing with, it will pass the wrong
number of params.

**Why it happens:** CMC CTE includes `ranked_all` + `src_rows` CTEs that use extra params for
`time_max` and `lookback_days`. TVC/HL CTEs are simpler.

**How to avoid:** The `ohlc_repair` flag in the spec is the discriminator. If `ohlc_repair=True`
(CMC), build the 11-param list. If `ohlc_repair=False` (TVC, HL), build the 6-param list. This
is the ONE remaining source-specific branch in the Python code.

---

## Code Examples

### Full Source-Aware build_bars_for_id()

```python
# Source: synthesized from refresh_price_bars_1d.py, refresh_tvc_price_bars_1d.py,
# and refresh_hl_price_bars_1d.py patterns

def build_bars_for_id(self, id_: int, start_ts: Optional[str] = None) -> int:
    conn = self.psycopg_conn
    spec = self.source_spec  # dict from dim_data_sources
    dst = self.OUTPUT_TABLE
    state = self.STATE_TABLE
    venue_id = spec["venue_id"]

    # Backfill detection (CMC-only historically, now generalized)
    state_dict = _get_state(conn, state, id_, venue_id)
    if _check_for_backfill_generic(conn, spec, id_, state_dict):
        self.logger.info(f"ID={id_}: Backfill detected, triggering full rebuild")
        _handle_backfill(conn, dst, state, id_, venue_id)
        state_dict = None

    last_src_ts = _get_last_src_ts(conn, state, id_, venue_id)

    # Build SQL from template
    sql = spec["src_cte_template"]
    if "{src}" in sql:
        sql = sql.format(dst=dst, src=spec["source_table"])
    else:
        sql = sql.format(dst=dst)  # HL: no {src} placeholder

    # Build params based on source type
    if spec["ohlc_repair"]:  # CMC: 11 params
        time_max = None
        lookback_days = 3
        params = [id_, time_max, time_max, id_, None, None,
                  time_max, time_max, last_src_ts, last_src_ts, lookback_days]
    else:  # TVC/HL: 6 params
        time_max = None
        params = [id_, id_, last_src_ts, last_src_ts, time_max, time_max]

    row = fetchone(conn, sql, params)
    upserted = int(row[0]) if row and row[0] is not None else 0
    max_src_ts = row[1] if row else None

    if max_src_ts is not None:
        _update_state(conn, state, id_, venue_id, max_src_ts, upserted)
        _update_coverage(self.engine, spec, id_)

    return upserted
```

### State Table DDL (Unified)

```python
# Unified state table DDL for all sources
# Key change from existing builders: adds venue_id to PK
ddl = f"""
CREATE TABLE IF NOT EXISTS {fq_table} (
    id                      INTEGER      NOT NULL,
    venue_id                SMALLINT     NOT NULL DEFAULT 1,
    tf                      TEXT         NOT NULL DEFAULT '1D',
    last_src_ts             TIMESTAMPTZ,
    daily_min_seen          TIMESTAMPTZ,
    daily_max_seen          TIMESTAMPTZ,
    last_bar_seq            INTEGER,
    last_time_close         TIMESTAMPTZ,
    last_run_ts             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_upserted           INTEGER      NOT NULL DEFAULT 0,
    last_repaired_timehigh  INTEGER      NOT NULL DEFAULT 0,
    last_repaired_timelow   INTEGER      NOT NULL DEFAULT 0,
    last_rejected           INTEGER      NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, venue_id, tf)
);
"""
```

### Verifying dim_data_sources Content

```bash
python -c "
from sqlalchemy import create_engine, text
from ta_lab2.scripts.bars.common_snapshot_contract import resolve_db_url
e = create_engine(resolve_db_url(None))
with e.connect() as conn:
    rows = conn.execute(text(
        'SELECT source_key, venue_id, ohlc_repair, ts_column, conflict_columns '
        'FROM dim_data_sources ORDER BY source_key'
    ))
    for r in rows: print(r)
"
# Expected output:
# ('cmc', 1, True, 'timestamp', 'id,venue_id,tf,bar_seq,timestamp')
# ('hl', 2, False, 'ts', 'id,venue_id,tf,bar_seq,timestamp')
# ('tvc', 11, False, 'ts', 'id,venue_id,tf,bar_seq,timestamp')
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Three separate builder scripts | Single script + `--source` flag | Phase 75 | Adding a source = INSERT one DB row |
| Per-file psycopg helpers | `ta_lab2.db.psycopg_helpers` | Phase 74-01 | ~222 lines eliminated |
| Per-source state table PKs `(id, tf)` | Unified `(id, venue_id, tf)` | Phase 75 | State table survives across sources |
| SQL CTEs hardcoded in Python | SQL templates in `dim_data_sources` | Phase 74-02 | Templates queryable and updatable without deploy |
| `1d`, `1d_tvc`, `1d_hl` in orchestrator | `1d_cmc`, `1d_tvc`, `1d_hl` all pointing to same script | Phase 75 | Orchestrator stays clean |

**Deprecated/outdated after Phase 75:**
- `refresh_tvc_price_bars_1d.py`: Deleted (replaced by `--source tvc`)
- `refresh_hl_price_bars_1d.py`: Deleted (replaced by `--source hl`)
- `OneDayBarBuilder.SOURCE_TABLE = "public.cmc_price_histories7"` class constant: replaced by
  spec lookup

---

## Open Questions

1. **HL_YN.csv filter: keep or drop?**
   - What we know: Existing HL builder filters to Y-marked assets via HL_YN.csv (~190 assets).
     dim_data_sources id_loader_sql loads ALL HL assets with 1d candles (potentially more).
   - What's unclear: Whether BAR-08 baseline was captured from the filtered or unfiltered set.
     Whether there are HL assets in dim_asset_identifiers that should NOT get 1D bars.
   - Recommendation: Plan should capture the current HL row count baseline FIRST, then decide.
     If the current HL builder with CSV filtering produces N rows, the new builder must also
     produce N rows for BAR-08 to pass. The safest path is to encode the same asset set in a
     DB table (or update id_loader_sql to JOIN a DB-resident allow-list) rather than keep a
     CSV file dependency.

2. **`_sync_1d_to_multi_tf()` - needed or not?**
   - What we know: TVC and HL builders call this after `builder.run()`. CMC builder does not.
     The sync copies rows from `price_bars_1d` to `price_bars_multi_tf` filtered by `src_name`.
   - What's unclear: Whether these are still separate tables or if the schema has been unified.
     Check: `SELECT COUNT(*) FROM price_bars_1d` vs `price_bars_multi_tf` for TVC/HL rows.
   - Recommendation: Query both tables before planning tasks to determine if sync is still
     needed. If the tables are the same object (renamed), no sync step is needed.

3. **TVC/HL CTE template venue_id coverage**
   - What we know: The migration's TVC CTE template was extracted from `refresh_tvc_price_bars_1d.py`
     which predated full venue_id coverage. The ON CONFLICT clause was updated to include
     `venue_id` but the INSERT column list may not include it.
   - What's unclear: Whether the TVC template in the live DB properly inserts `venue_id`.
   - Recommendation: First task in Phase 75 should verify the templates produce valid INSERTs
     before building the generalized wrapper. If broken, fix the templates via UPDATE to
     dim_data_sources (not by modifying Python).

4. **Backwards compat for `--ids all` with multiple sources**
   - What we know: `--source all` must invoke all three sources. Each has a different ID space
     (CMC IDs vs TVC IDs vs HL IDs). `parse_ids("all")` calls `load_all_ids(db_url, daily_table)`
     which is source-specific.
   - What's unclear: Whether `--source all --ids all` should process each source's full ID list
     independently (correct) or try to intersect them (wrong).
   - Recommendation: For `--source all`, iterate sources and for each source call the source's
     `id_loader_sql`. For `--source cmc --ids 1,2,3`, use the explicit IDs directly.

---

## Sources

### Primary (HIGH confidence)

- Direct inspection of `refresh_price_bars_1d.py` (CMC builder, 728 lines)
- Direct inspection of `refresh_tvc_price_bars_1d.py` (TVC builder, 452 lines)
- Direct inspection of `refresh_hl_price_bars_1d.py` (HL builder, 517 lines)
- Direct inspection of `alembic/versions/g1h2i3j4k5l6_dim_data_sources_and_alignment_checks.py`
  (Phase 74-02 migration — contains all 3 CTE templates and dim_data_sources schema)
- Direct inspection of `ta_lab2/db/psycopg_helpers.py` (Phase 74-01 shared module)
- Direct inspection of `run_all_bar_builders.py` (orchestrator, 537 lines)
- Direct inspection of `base_bar_builder.py` (abstract base class, 557 lines)
- Direct inspection of `bar_builder_config.py` (BarBuilderConfig dataclass)
- Direct inspection of `.planning/phases/74-foundation-shared-infrastructure/74-02-SUMMARY.md`
  (Phase 74 decisions and confirmed state)

### No WebSearch used

All research was performed against live codebase files. No external sources consulted.
All findings are HIGH confidence derived from direct code inspection.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Phase 74 deliverables confirmed in codebase
- Architecture (source spec pattern): HIGH — dim_data_sources schema and CTE templates verified
- Pitfalls: HIGH — identified from actual code divergences between the 3 builders
- Open questions: flagged honestly — require live DB inspection before planning tasks

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable domain; dim_data_sources schema only changes via Alembic)
