# Feature Landscape: Pipeline Consolidation & Storage Optimization

**Domain:** Infrastructure consolidation for quantitative trading data pipeline
**Researched:** 2026-03-19
**Confidence:** HIGH (all findings derived from direct codebase analysis)

## Scope

This document maps the feature landscape for consolidating ta_lab2's data pipeline:

1. **1D Bar Builder Consolidation** -- 3 source-specific builders (CMC: 822 LOC, TVC: 511 LOC, HL: 585 LOC) into a generalized builder with source registry
2. **_u Table Direct-Write Migration** -- Eliminate 30 siloed tables (6 families x 5 variants) by writing directly to unified `_u` tables
3. **Sync Script Elimination** -- Remove 6 sync-to-_u scripts (771 LOC total) that become unnecessary

### Current Scale

| Category | Count | Lines |
|----------|-------|-------|
| 1D bar builders (source-specific) | 3 | 1,915 |
| Multi-TF bar builders (siloed) | 5 | 5,303 |
| Return builders (siloed) | 4 | 2,428 |
| Sync-to-_u scripts | 6 | 771 |
| EMA builders (siloed) | 3 | ~2,000 est. |
| AMA builders (siloed) | 3 | ~2,000 est. |
| **Total consolidation surface** | **24** | **~14,400** |

---

## Table Stakes

Features the consolidated pipeline MUST have. Missing any of these means the consolidation is unsafe or incomplete.

### TS-1: Source Registry with Declarative Configuration

**Why Expected:** The 3 existing 1D builders differ in exactly 5 dimensions: source table/JOINs, OHLC repair eligibility, backfill detection, venue_id mapping, and post-build hooks. A registry makes these differences explicit and declarative rather than duplicated across 3 files.

**Complexity:** Medium

**What It Looks Like:**

```python
@dataclass(frozen=True)
class SourceConfig:
    """Declarative config for one data source."""
    name: str                          # e.g. "CMC", "TVC", "Hyperliquid"
    source_table: str                  # e.g. "public.cmc_price_histories7"
    source_schema: str                 # JOINs needed to reach OHLCV
    venue_id: int                      # dim_venues FK (1=CMC_AGG, 2=HL, 9=TVC)
    venue_name: str                    # e.g. "HYPERLIQUID"
    id_resolution: IdResolution        # how to map source IDs to dim_assets.id
    ohlc_repair: bool                  # CMC has timehigh/timelow repair; TVC/HL do not
    backfill_detection: bool           # CMC tracks daily_min_seen; TVC/HL do not
    has_market_cap: bool               # CMC has marketcap; TVC/HL do not
    post_build_hooks: list[Callable]   # e.g. _sync_1d_to_multi_tf for TVC/HL
    asset_filter: AssetFilter | None   # e.g. HL_YN.csv filter, None for CMC/TVC
```

**Dependencies:** Requires dim_venues, dim_asset_identifiers, dim_listings to exist.

**Evidence from codebase:** Each builder currently hardcodes these 5 dimensions. The differences are well-defined and stable:
- CMC reads `cmc_price_histories7` directly (no JOIN), has 6-CTE OHLC repair, tracks `daily_min_seen`
- TVC reads `tvc_price_histories` via `dim_listings` JOIN, no repair, no backfill detection
- HL reads `hyperliquid.hl_candles` via `dim_asset_identifiers` + `dim_listings` JOIN, no repair, filters via `HL_YN.csv`

### TS-2: Preserved Source-Specific SQL Generation

**Why Expected:** The OHLC repair logic (lines 253-496 of `refresh_price_bars_1d.py`) is CMC-specific and critical for data quality. The TVC/HL builders legitimately skip it. The consolidation must preserve these source-specific SQL paths, not force a one-size-fits-all query.

**Complexity:** Low (these already exist; the task is not losing them)

**What It Looks Like:** The registry's `SourceConfig` determines which SQL template to use. CMC gets the 6-CTE repair pipeline. TVC/HL get simpler SELECTs with GREATEST/LEAST for OHLCV invariants. The generalized builder delegates SQL generation to a `build_insert_sql(source_config) -> str` function that dispatches on config flags.

**Dependencies:** None beyond current code.

**Risk:** Accidentally unifying the SQL when sources genuinely need different CTEs. The temptation to "simplify" by making one query serve all sources would break CMC's timehigh/timelow repair and HL's cross-schema JOIN.

### TS-3: Venue-Aware State Table

**Why Expected:** The three builders currently use incompatible state table schemas. CMC uses PK `(id, tf)`, while HL uses PK `(id, venue_id, tf)`. The consolidated builder needs a single state table that handles multi-venue state.

**Complexity:** Medium

**Current state table schemas (incompatible):**

| Builder | State Table PK | Has venue_id | Has daily_min_seen |
|---------|---------------|--------------|-------------------|
| CMC 1D | `(id, tf)` | No | Yes |
| TVC 1D | `(id, tf)` (shared with CMC!) | No | No |
| HL 1D | `(id, venue_id, tf)` | Yes | No |

**What It Looks Like:** A single state table with PK `(id, venue_id, tf)` where `venue_id` defaults to 1 (CMC_AGG). Existing CMC/TVC state rows migrate by adding `venue_id=1`. Backfill detection columns (`daily_min_seen`) become optional per source registry config.

**Dependencies:** Must not break CMC/TVC which currently share the same state table.

**Risk:** CMC and TVC currently share `price_bars_1d_state` with PK `(id, tf)`. Adding `venue_id` to the PK requires an ALTER TABLE + data migration. This must happen before the consolidated builder runs.

### TS-4: alignment_source Tag for Direct _u Writes

**Why Expected:** The current _u tables use `alignment_source` (e.g. "multi_tf", "multi_tf_cal_us") to distinguish which pipeline produced each row. Direct-write builders must set this tag at write time, not in a separate sync step.

**Complexity:** Low

**What It Looks Like:** The `alignment_source` value is derived from the builder configuration, added to the output DataFrame/SQL before upsert. The existing `upsert_bars()` function in `common_snapshot_contract.py` already handles column lists dynamically.

**Dependencies:** The `alignment_source` column must exist in target tables (it already does in all _u tables).

**Evidence from codebase:** `sync_utils.py` line 68: `alignment_source_from_table()` derives the tag from table name. In the consolidated pipeline, this becomes a builder config property instead.

### TS-5: Idempotent Upsert with Correct PK for _u Tables

**Why Expected:** _u tables have a different PK than siloed tables -- they include `alignment_source`. The direct-write path must use the correct ON CONFLICT target.

**Complexity:** Low

**Current PKs across families:**

| Family | Siloed PK | _u Table PK (adds alignment_source) |
|--------|-----------|--------------------------------------|
| Price Bars | `(id, tf, bar_seq, venue_id, timestamp)` | + `alignment_source` |
| Bar Returns | `(id, venue_id, timestamp, tf)` | + `alignment_source` |
| EMA Values | `(id, venue_id, ts, tf, period)` | + `alignment_source` |
| EMA Returns | similar | + `alignment_source` |
| AMA Values | similar | + `alignment_source` |
| AMA Returns | similar | + `alignment_source` |

**What It Looks Like:** Each builder's `upsert_bars()` call specifies `conflict_cols` matching the _u table PK. This is already parameterized in `common_snapshot_contract.py` line 860.

### TS-6: Backward-Compatible CLI Interface

**Why Expected:** `run_all_bar_builders.py` orchestrates 9 builders via subprocess with specific CLI signatures. `run_daily_refresh.py` calls these in a defined order. The consolidated builder must maintain CLI compatibility or update the orchestrators.

**Complexity:** Medium

**Recommendation:** Thin wrapper scripts that instantiate the generalized builder with the right registry config. Each existing script becomes a 10-line wrapper:

```python
# refresh_price_bars_1d.py (wrapper, preserves CLI contract)
from ta_lab2.scripts.bars.generalized_1d_builder import Generalized1DBarBuilder
from ta_lab2.scripts.bars.source_registry import CMC_SOURCE

if __name__ == "__main__":
    Generalized1DBarBuilder.main(source_config=CMC_SOURCE)
```

This approach is safer than a `--source` flag because `run_all_bar_builders.py` calls builders by script path (line 194: `script_dir / builder.script_path`).

**Dependencies:** `run_all_bar_builders.py`, `run_daily_refresh.py` both call builders by script path.

### TS-7: Incremental Refresh Preserved (No Full Rebuild Required)

**Why Expected:** The pipeline runs daily. Incremental refresh is the default mode, rebuilding only new data since the last watermark. This MUST work identically in the consolidated pipeline.

**Complexity:** Low (already implemented in BaseBarBuilder)

**What It Looks Like:** The `_run_incremental()` method in `BaseBarBuilder` already handles this via state table lookback. The consolidated builder inherits this behavior unchanged.

**Dependencies:** State table must be consistent (see TS-3).

### TS-8: Coverage Tracking

**Why Expected:** All three 1D builders upsert to `asset_data_coverage` after building bars. This metadata table tracks n_rows, n_days, first_ts, last_ts per (id, source_table, granularity). Downstream analytics depend on it.

**Complexity:** Low

**Evidence from codebase:** `upsert_coverage()` is called in all three builders identically. The consolidated builder does the same via the shared `common_snapshot_contract.py` helper.

---

## Differentiators

Features that improve the pipeline beyond its current state. Not expected, but high-value.

### D-1: Single-Pass Multi-Source Build

**Value Proposition:** Currently, running all 3 sources requires 3 separate invocations (3 process startups, 3 state table reads). A consolidated builder could run all sources in a single invocation with shared DB connections.

**Complexity:** Medium

**What It Looks Like:**

```bash
# Current: 3 separate invocations
python -m ta_lab2.scripts.bars.refresh_price_bars_1d --ids all
python -m ta_lab2.scripts.bars.refresh_tvc_price_bars_1d --ids all
python -m ta_lab2.scripts.bars.refresh_hl_price_bars_1d --ids all

# Consolidated: single invocation
python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source all --ids all
# or select specific sources:
python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source CMC,HL --ids all
```

**When to Build:** Phase 2 (after basic consolidation works). Not required for MVP.

### D-2: Automatic Post-Build Hooks

**Value Proposition:** TVC and HL builders currently have a manual `_sync_1d_to_multi_tf()` call after `builder.run()`. This is fragile -- if the sync fails, 1D bars exist but are invisible to the multi-TF pipeline. A hook system makes this automatic and retry-safe.

**Complexity:** Low

**What It Looks Like:** The source registry includes `post_build_hooks: list[Callable]`. After `build_bars_for_id()` succeeds, hooks run in order.

**Evidence from codebase:**
- `refresh_tvc_price_bars_1d.py` line 506: `_sync_1d_to_multi_tf(builder.config.db_url)` called after `builder.run()`
- `refresh_hl_price_bars_1d.py` line 580: `_sync_1d_to_multi_tf(builder.config.db_url)` called after `builder.run()`

Both are called outside the builder's transaction scope. If they fail, 1D bars exist but multi-TF pipeline does not see them until next sync.

### D-3: _u Migration Validation Framework

**Value Proposition:** When migrating from siloed-then-sync to direct-_u-write, you need to prove the new path produces identical results. `derive_multi_tf_from_1d.py` already has `validate_derivation_consistency()` (lines 738-807). Extending this pattern to validate _u migration provides safety.

**Complexity:** Medium

**What It Looks Like:**

```python
def validate_u_migration(
    engine: Engine,
    siloed_table: str,
    u_table: str,
    alignment_source: str,
    sample_ids: list[int],
    tolerance: float = 1e-10,
) -> tuple[bool, list[str]]:
    """Compare siloed table rows vs _u table rows for same alignment_source."""
```

Run during migration phase for each family. Once validated, flip write target.

**Dependencies:** Both siloed and _u tables must exist simultaneously during migration.

### D-4: Eliminate Duplicated psycopg Utilities

**Value Proposition:** Each of the 3 builders duplicates `_normalize_db_url()`, `_connect()`, `_exec()`, `_fetchone()`, `_fetchall()` -- 5 functions x 3 files = 15 duplicate function definitions, ~180 lines of identical code.

**Complexity:** Low

**What It Looks Like:** Extract to `ta_lab2.scripts.bars.psycopg_utils` module. Each builder imports instead of redefining.

**Evidence from codebase:**
- `refresh_price_bars_1d.py` lines 78-148: 5 utility functions
- `refresh_tvc_price_bars_1d.py` lines 56-100: same 5 functions (slightly simplified)
- `refresh_hl_price_bars_1d.py` lines 66-120: same 5 functions

### D-5: Unified Conflict Resolution Column Set

**Value Proposition:** The three builders have slightly different ON CONFLICT column sets because the PK evolved incrementally:
- CMC: `ON CONFLICT (id, tf, bar_seq, "timestamp")` -- no venue in PK
- TVC: `ON CONFLICT (id, tf, bar_seq, venue, "timestamp")` -- venue as TEXT
- HL: `ON CONFLICT (id, tf, bar_seq, venue_id, "timestamp")` -- venue_id as SMALLINT

This inconsistency is a latent correctness issue. The consolidated builder uses a single, correct conflict target.

**Complexity:** Low (but requires careful PK analysis)

**Risk:** The `price_bars_1d` table DDL (in `common_snapshot_contract.py` line 165) defines PK as `(id, tf, bar_seq, venue, timestamp)` using TEXT venue. But HL writes `venue_id` as SMALLINT. This mismatch must be resolved -- likely by standardizing to `venue_id` across all sources, matching the PK migration already underway on the `refactor/strip-cmc-prefix-add-venue-id` branch.

### D-6: Source-Aware Backfill Detection (Generalized)

**Value Proposition:** Currently only CMC has backfill detection (tracks `daily_min_seen`, rebuilds if MIN(timestamp) decreases). TVC and HL lack this. A generalized builder could offer opt-in backfill detection for any source.

**Complexity:** Medium

**What It Looks Like:** The `backfill_detection: bool` flag in the source registry enables/disables the backfill check per source. When enabled, the same `_check_for_backfill()` logic from CMC applies to any source.

**When to Build:** Phase 2. TVC and HL sources are less likely to have historical backfills, but future sources might.

### D-7: Shadow-Write Migration Pattern

**Value Proposition:** Instead of a hard cutover from siloed to _u, implement shadow writing: builders write to BOTH siloed and _u tables during a transition period. Once validation confirms parity (D-3), stop writing to siloed tables.

**Complexity:** Medium

**What It Looks Like:**

```python
class MigrationWriteMode(Enum):
    SILOED_ONLY = "siloed"        # Current behavior
    SHADOW = "shadow"             # Write to both siloed + _u
    UNIFIED_ONLY = "unified"      # Target state (post-migration)
```

The mode is configurable per family, per environment. Shadow mode doubles write load but ensures safe migration with rollback capability.

**When to Build:** Essential for the _u migration phase. Without this, migration is a risky big-bang cutover.

### D-8: Dead Table Cleanup Registry

**Value Proposition:** After migration, 30 siloed tables and 6 sync scripts become dead weight. A cleanup registry tracks which tables are deprecated, when they were last written to, and whether any consumers still read them.

**Complexity:** Low

**What It Looks Like:** A `dim_table_lifecycle` table or YAML config that marks tables as ACTIVE, SHADOW, DEPRECATED, or ARCHIVED. The daily refresh orchestrator warns if deprecated tables are still referenced.

---

## Anti-Features

Things to deliberately NOT build during this consolidation. Common over-engineering traps.

### AF-1: Generic ORM-Based Bar Builder

**Why Avoid:** The 1D builders use raw psycopg + SQL CTEs for performance. CMC's bar building is a single 500-line SQL CTE that does bar_seq assignment, OHLC repair, invariant enforcement, and upsert in one round-trip. Replacing this with ORM-based Python logic would be 5-10x slower and lose atomicity.

**What to Do Instead:** Keep SQL CTEs per source. The consolidation unifies Python scaffolding (CLI, state, logging), not the SQL core.

**Evidence:** `refresh_price_bars_1d.py` lines 253-496 is a single CTE that runs in ~1 second per asset. A Python-side row-by-row equivalent would take 10-30 seconds.

### AF-2: Real-Time / Streaming Bar Builder

**Why Avoid:** The pipeline is daily-batch. Adding real-time capability requires a fundamentally different architecture (message queues, streaming state, exactly-once delivery). This is out of scope for v1.1.0 consolidation.

**What to Do Instead:** Keep batch mode. If real-time is needed later, it would be a separate system.

### AF-3: Auto-Discovery of New Sources

**Why Avoid:** Tempting to build a system that auto-discovers new source tables and registers them. But each source has unique SQL (JOINs, column mappings, repair logic). Auto-discovery cannot derive these.

**What to Do Instead:** Manual registry. Adding a new source means adding one `SourceConfig` entry with its SQL template. This is a 10-minute task, not a daily operation.

### AF-4: Parallel Multi-Source ID Processing

**Why Avoid:** Running CMC, TVC, and HL builders concurrently for the same asset ID could cause write conflicts on `price_bars_1d` (same output table, same PK). The current sequential-per-source approach is safe.

**What to Do Instead:** Sources run sequentially (CMC, then TVC, then HL). Within each source, IDs can run in parallel (existing `--num-processes` flag).

### AF-5: Dynamic Schema Evolution for _u Tables

**Why Avoid:** Tempting to build a system that automatically adds columns to _u tables when source schemas change. But schema changes require careful thought about defaults, NULL handling, and downstream consumers.

**What to Do Instead:** Schema changes are explicit Alembic migrations. The `_build_column_mapping()` in `sync_utils.py` already handles missing columns by inserting NULL.

### AF-6: Materialized View Replacement for _u

**Why Avoid:** A materialized view that UNIONs all 5 siloed tables would "look like" a _u table but have terrible performance (full refresh on every REFRESH). The current approach (INSERT ON CONFLICT DO NOTHING with ingested_at watermark) is incrementally maintainable.

**What to Do Instead:** Direct writes to _u tables with alignment_source tag.

### AF-7: Over-Abstracting the 6 Table Families

**Why Avoid:** Price bars, EMA values, EMA returns, AMA values, AMA returns, and bar returns have similar pipeline structure but different semantics (different PKs, different column sets, different computation logic). Over-abstracting into a single "DataFamily" class that handles all 6 loses domain clarity.

**What to Do Instead:** Handle each family's _u migration independently. Share the `sync_utils.py` pattern and the shadow-write mechanism, but keep family-specific upsert logic.

### AF-8: Premature Siloed Table Deletion

**Why Avoid:** Dropping 30 tables before confirming all downstream consumers (features, signals, regimes, backtests) have migrated to reading from _u tables is catastrophic. Some consumers may still query siloed tables directly.

**What to Do Instead:** The migration has 3 explicit stages: (1) shadow-write, (2) redirect consumers, (3) deprecate siloed tables after a retention period with zero-read confirmation.

---

## Feature Dependencies

```
TS-1 (Source Registry)
  |
  +---> TS-2 (Source-Specific SQL)
  |
  +---> TS-3 (Venue-Aware State) ---> TS-7 (Incremental Refresh)
  |
  +---> TS-6 (CLI Compatibility)
  |
  +---> D-1 (Multi-Source Single Pass)  [optional, Phase 2]
  |
  +---> D-2 (Post-Build Hooks)         [optional, Phase 2]

TS-4 (alignment_source Tag)
  |
  +---> TS-5 (Correct _u PK)
  |
  +---> D-7 (Shadow-Write Migration)   [Phase 2]

D-4 (Dedupe psycopg utils)  [standalone, no dependencies]

D-3 (Validation Framework)
  |
  +---> D-7 (Shadow-Write) ---> D-8 (Dead Table Cleanup)  [Phase 3]
```

---

## MVP Recommendation

### Phase 1: Foundation (1D Bar Builder Consolidation)

Build these in order:

1. **D-4**: Extract duplicated psycopg utilities to shared module (Low effort, immediate savings: ~180 lines)
2. **TS-1**: Build source registry with declarative config for CMC, TVC, HL
3. **TS-2**: Preserve source-specific SQL CTEs as registry-referenced templates
4. **TS-3**: Migrate state table to venue-aware PK `(id, venue_id, tf)`
5. **TS-8**: Coverage tracking in consolidated builder
6. **TS-6**: Thin wrapper scripts for backward compatibility
7. **D-5**: Unified conflict resolution column set

**Outcome:** 3 builders (1,915 LOC) become 1 generalized builder (~600 LOC) + 3 wrapper scripts (~30 LOC) + registry (~100 LOC). Net reduction: ~1,100 LOC.

### Phase 2: _u Direct Write Migration

1. **TS-4**: Add alignment_source tag to builder output
2. **TS-5**: Configure correct _u table PKs for upsert
3. **D-7**: Shadow-write mode (write to both siloed and _u simultaneously)
4. **D-3**: Validation framework to compare siloed vs _u output
5. Validate shadow-write parity per family, per sample of IDs

**Outcome:** Builders write to _u directly. Siloed tables still receive writes during shadow period for rollback safety.

### Phase 3: Cutover & Cleanup

1. Confirm all downstream consumers read from _u tables
2. Flip write mode to `UNIFIED_ONLY`
3. Remove 6 sync scripts (771 LOC)
4. **D-8**: Mark 30 siloed tables as DEPRECATED
5. Archive siloed tables after a configured retention period (suggest 30 days)

**Outcome:** 30 tables eliminated, 6 sync scripts removed, storage halved for pipeline tables.

### Defer to Post-Consolidation

- **D-1** (Multi-source single pass): Nice optimization, not blocking
- **D-6** (Generalized backfill detection for TVC/HL): Not needed yet
- **D-2** (Post-build hooks): Current manual `_sync_1d_to_multi_tf` is adequate

---

## Quantified Impact

### LOC Reduction

| Target | Current | After | Savings |
|--------|---------|-------|---------|
| 1D bar builders | 1,915 | ~730 | ~1,185 |
| Duplicated psycopg utils | ~180 (3x60) | ~60 (1x) | ~120 |
| Sync-to-_u scripts | 771 | 0 | 771 |
| **Total Phase 1+3** | **~2,866** | **~790** | **~2,076** |

### Table Count Reduction

| Current | After | Reduction |
|---------|-------|-----------|
| 30 siloed tables + 6 _u tables = 36 | 6 _u tables | 30 tables dropped |

### Storage Impact

The 30 siloed tables are near-exact duplicates of _u table data (sync scripts use `ON CONFLICT DO NOTHING` to copy rows). With ~230M total rows across all 6 families, the siloed tables duplicate approximately half the pipeline storage. Elimination saves disk and vacuum overhead.

### Operational Simplification

| Metric | Current | After |
|--------|---------|-------|
| 1D builder scripts to maintain | 3 (separate codebases) | 1 (+ 3 thin wrappers) |
| Daily sync operations | 6 (one per _u family) | 0 |
| State table schemas | 3 (incompatible PKs) | 1 (unified) |
| ON CONFLICT variants in 1D builders | 3 (different PK cols) | 1 (standard) |
| Risk of sync failure leaving stale _u data | Ongoing | Eliminated |

---

## Sources

All findings derived from direct codebase analysis of the following files:

- `src/ta_lab2/scripts/bars/base_bar_builder.py` (557 lines) -- Template Method pattern for bar builders
- `src/ta_lab2/scripts/bars/refresh_price_bars_1d.py` (822 lines) -- CMC 1D builder with OHLC repair
- `src/ta_lab2/scripts/bars/refresh_tvc_price_bars_1d.py` (511 lines) -- TVC 1D builder
- `src/ta_lab2/scripts/bars/refresh_hl_price_bars_1d.py` (585 lines) -- HL 1D builder
- `src/ta_lab2/scripts/bars/common_snapshot_contract.py` (1,813 lines) -- Shared utilities
- `src/ta_lab2/scripts/bars/bar_builder_config.py` (53 lines) -- Config dataclass
- `src/ta_lab2/scripts/bars/derive_multi_tf_from_1d.py` (807 lines) -- 1D-to-multi-TF derivation
- `src/ta_lab2/scripts/bars/run_all_bar_builders.py` (537 lines) -- Builder orchestrator
- `src/ta_lab2/scripts/bars/sync_price_bars_multi_tf_u.py` (71 lines) -- Price bars sync
- `src/ta_lab2/scripts/sync_utils.py` (304 lines) -- Generic sync utilities
- `src/ta_lab2/scripts/emas/sync_ema_multi_tf_u.py` (359 lines) -- EMA sync (older pattern)
- `src/ta_lab2/scripts/emas/ema_state_manager.py` -- State management pattern
- `src/ta_lab2/scripts/bars/refresh_price_bars_multi_tf.py` (1,237 lines) -- Multi-TF builder
- `src/ta_lab2/scripts/returns/sync_returns_bars_multi_tf_u.py` (68 lines) -- Returns sync
- `src/ta_lab2/scripts/amas/sync_ama_multi_tf_u.py` (96 lines) -- AMA sync
- `src/ta_lab2/scripts/amas/sync_returns_ama_multi_tf_u.py` (105 lines) -- AMA returns sync
