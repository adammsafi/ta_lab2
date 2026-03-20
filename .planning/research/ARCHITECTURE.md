# Architecture Patterns: Pipeline Consolidation & Storage Optimization

**Domain:** Infrastructure refactoring for quant trading platform (ta_lab2 v1.1.0)
**Researched:** 2026-03-19
**Confidence:** HIGH (based on direct source code analysis of all 1D builders, sync scripts, base classes, and orchestration pipeline)

## Executive Summary

The v1.1.0 pipeline consolidation addresses two structural inefficiencies in the current architecture:

1. **Three separate 1D bar builders** (CMC, TVC, HL) that share 80%+ identical code but diverge in source queries, ID resolution, and venue handling
2. **Six families of 5 siloed tables + 1 _u table** where sync scripts copy data from siloed tables to unified tables using watermark-based INSERT...ON CONFLICT DO NOTHING

The consolidation strategy has two orthogonal work streams:
- **Generalized 1D Bar Builder**: Replace three 1D builder scripts with one configurable builder driven by a SourceSpec registry
- **Direct-to-_u Writes**: Eliminate siloed intermediate tables and sync scripts by having builders write directly to _u tables with alignment_source

Both changes integrate cleanly with the existing BaseBarBuilder template method pattern and common_snapshot_contract utilities.

---

## Current Architecture (BEFORE)

### Component Map

```
Source Tables                    1D Builders                Output
================               ===========                ======
cmc_price_histories7  -------> OneDayBarBuilder --------> price_bars_1d
tvc_price_histories   -------> TvcOneDayBarBuilder ----->     |
hyperliquid.hl_candles ------> HlOneDayBarBuilder ------>     |
                                                              v
                                                     price_bars_multi_tf
                                                     price_bars_multi_tf_cal_us
                                                     price_bars_multi_tf_cal_iso
                                                     price_bars_multi_tf_cal_anchor_us
                                                     price_bars_multi_tf_cal_anchor_iso
                                                              |
                                                    sync_price_bars_multi_tf_u.py
                                                              |
                                                              v
                                                     price_bars_multi_tf_u
                                                     (alignment_source column)
```

This same pattern repeats for 5 more families (ema, ama, returns_bars, returns_ema, returns_ama) = 6 families total, each with 5 siloed + 1 _u table = 36 tables.

### Current Data Flow (Price Bars)

```
Step 1: 1D Bar Building
  refresh_price_bars_1d.py         (CMC -> price_bars_1d, venue=CMC_AGG)
  refresh_tvc_price_bars_1d.py     (TVC -> price_bars_1d, venue=TVC_*)
  refresh_hl_price_bars_1d.py      (HL  -> price_bars_1d, venue=HYPERLIQUID)
    + _sync_1d_to_multi_tf()       (copies 1D rows to price_bars_multi_tf)

Step 2: Multi-TF Derivation
  refresh_price_bars_multi_tf.py         -> price_bars_multi_tf
  refresh_price_bars_multi_tf_cal_us.py  -> price_bars_multi_tf_cal_us
  refresh_price_bars_multi_tf_cal_iso.py -> price_bars_multi_tf_cal_iso
  refresh_price_bars_multi_tf_cal_anchor_us.py  -> price_bars_multi_tf_cal_anchor_us
  refresh_price_bars_multi_tf_cal_anchor_iso.py -> price_bars_multi_tf_cal_anchor_iso

Step 3: Sync to _u
  sync_price_bars_multi_tf_u.py  (INSERT...SELECT...ON CONFLICT DO NOTHING)
    - Reads from 5 siloed tables
    - Adds alignment_source column
    - Watermark-based incremental via ingested_at

Step 4: Downstream (reads from _u only)
  EMA builders read from price_bars_multi_tf_u
  Returns builders read from price_bars_multi_tf_u
  Feature scripts read from price_bars_multi_tf_u
```

### Current Code Duplication

**Across 1D Builders (1,905 lines total):**

| Component | CMC (822 LOC) | TVC (511 LOC) | HL (585 LOC) | Shared? |
|-----------|:---:|:---:|:---:|---------|
| psycopg helpers (_connect, _exec, _fetchone, _fetchall) | Yes | Yes | Yes | Copy-pasted |
| _normalize_db_url() | Yes | Yes | Yes | Copy-pasted |
| _get_last_src_ts() | Yes | Yes | Yes | Copy-pasted |
| ensure_state_table_exists() DDL | Yes | Yes | Yes | Similar DDL |
| _build_insert_bars_sql() | Yes | Yes | Yes | 80% similar SQL CTEs |
| build_bars_for_id() | Yes | Yes | Yes | 70% similar logic |
| _sync_1d_to_multi_tf() | No | Yes | Yes | Copy-pasted |
| from_cli_args() | Yes | Yes | Yes | Similar pattern |
| Source query structure | Unique | Unique | Unique | **Different** |
| ID resolution | parse_ids | _load_tvc_ids | _load_hl_ids | **Different** |
| Venue handling | Implicit CMC_AGG | Multi-venue | Hardcoded HL | **Different** |
| OHLC repair | Complex CTE | Simple clamp | Simple clamp | **Different** |

**The 3 axes of variation** are: (a) source query, (b) ID resolution, (c) venue/repair logic.

**Across 6 Sync Scripts (total ~600 LOC):**

| Script | Family | Pattern |
|--------|--------|---------|
| sync_price_bars_multi_tf_u.py | Bars | sync_utils.sync_sources_to_unified() |
| sync_ema_multi_tf_u.py | EMA | Custom (predates sync_utils) |
| sync_ama_multi_tf_u.py | AMA | sync_utils.sync_sources_to_unified() |
| sync_returns_bars_multi_tf_u.py | Bar returns | sync_utils.sync_sources_to_unified() |
| sync_returns_ema_multi_tf_u.py | EMA returns | sync_utils.sync_sources_to_unified() |
| sync_returns_ama_multi_tf_u.py | AMA returns | sync_utils.sync_sources_to_unified() |

Five of six already use the generic sync_utils; the EMA sync is a legacy implementation that should be migrated.

---

## Recommended Architecture (AFTER)

### 1. SourceSpec Registry Pattern

A `SourceSpec` dataclass encapsulates the three axes of variation between 1D builders:

```python
# src/ta_lab2/scripts/bars/source_spec.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional

@dataclass(frozen=True)
class SourceSpec:
    """
    Declarative specification for a 1D bar data source.

    Encapsulates the three axes of variation:
    1. Source query (how to read raw data)
    2. ID resolution (how to determine which IDs to process)
    3. Venue/repair semantics (how to handle source-specific quirks)
    """

    # Identity
    name: str                              # e.g., "CMC", "TVC", "HYPERLIQUID"
    venue_id: int                          # dim_venues FK (1=CMC_AGG, 2=HL, etc.)
    venue_label: str                       # Written to venue column
    src_name: str                          # Written to src_name column

    # Source table
    source_table: str                      # e.g., "public.cmc_price_histories7"

    # SQL template for the INSERT CTE
    # Must accept: %s for id, %s for start_ts, %s for end_ts
    # Must produce columns: id, timestamp, open, high, low, close, volume,
    #   market_cap, venue, venue_id, venue_rank, bar_seq, tf, src_name, ...
    insert_cte_builder: Callable[[str, str], str]

    # ID resolution
    id_loader: Callable[[str], list[int]]  # db_url -> list of IDs

    # Venue
    default_venue_rank: int = 50

    # Repair
    needs_ohlc_repair: bool = True         # CMC: True (has timehigh/timelow issues)
    needs_timehigh_timelow: bool = True    # TVC/HL: False (synthesize from ts)

    # Coverage tracking
    coverage_source_table: str = ""        # For asset_data_coverage upserts
    coverage_granularity: str = "1D"

    # Backfill detection
    supports_backfill_detection: bool = True  # CMC: True, others: False initially
```

**Registry of known sources:**

```python
# src/ta_lab2/scripts/bars/source_registry.py

SOURCE_SPECS: dict[str, SourceSpec] = {
    "CMC": SourceSpec(
        name="CMC",
        venue_id=1,
        venue_label="CMC_AGG",
        src_name="CoinMarketCap",
        source_table="public.cmc_price_histories7",
        insert_cte_builder=build_cmc_insert_cte,
        id_loader=load_cmc_ids,
        needs_ohlc_repair=True,
        needs_timehigh_timelow=True,
        coverage_source_table="public.cmc_price_histories7",
        supports_backfill_detection=True,
    ),
    "TVC": SourceSpec(
        name="TVC",
        venue_id=9,
        venue_label="TVC",  # Per-venue from dim_listings
        src_name="TradingView",
        source_table="public.tvc_price_histories",
        insert_cte_builder=build_tvc_insert_cte,
        id_loader=load_tvc_ids,
        needs_ohlc_repair=False,
        needs_timehigh_timelow=False,
        coverage_source_table="public.tvc_price_histories",
        supports_backfill_detection=False,
    ),
    "HYPERLIQUID": SourceSpec(
        name="HYPERLIQUID",
        venue_id=2,
        venue_label="HYPERLIQUID",
        src_name="Hyperliquid",
        source_table="hyperliquid.hl_candles",
        insert_cte_builder=build_hl_insert_cte,
        id_loader=load_hl_ids,
        needs_ohlc_repair=False,
        needs_timehigh_timelow=False,
        coverage_source_table="hyperliquid.hl_candles",
        supports_backfill_detection=False,
    ),
}
```

**Why a registry and not just CLI args?** Because the CTE SQL for each source is fundamentally different (JOIN structure, column mappings, repair logic). A registry maps source name to its full behavior specification, making the builder truly generic while keeping source-specific SQL isolated.

### 2. Generalized 1D Bar Builder

```python
# src/ta_lab2/scripts/bars/refresh_price_bars_1d_generic.py

class GenericOneDayBarBuilder(BaseBarBuilder):
    """
    Single 1D bar builder that handles all data sources via SourceSpec.

    Replaces: refresh_price_bars_1d.py, refresh_tvc_price_bars_1d.py,
              refresh_hl_price_bars_1d.py

    Usage:
        python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source CMC --ids all
        python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source TVC --ids all
        python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source HYPERLIQUID --ids all
        python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source all --ids all
    """

    def __init__(self, config: BarBuilderConfig, engine: Engine, spec: SourceSpec):
        super().__init__(config, engine)
        self.spec = spec
        self.psycopg_conn = _connect(config.db_url)  # Shared helper, not copy-pasted

    def get_state_table_name(self) -> str:
        return "public.price_bars_1d_state"

    def get_output_table_name(self) -> str:
        return "public.price_bars_1d"

    def build_bars_for_id(self, id_: int, start_ts=None) -> int:
        # Common flow:
        # 1. Check backfill (if spec.supports_backfill_detection)
        # 2. Get last_src_ts from state
        # 3. Build and execute CTE via spec.insert_cte_builder
        # 4. Update state
        # 5. Update coverage
        ...
```

### 3. Direct-to-_u Write Architecture

**Core idea:** Instead of writing to 5 siloed tables then syncing, write directly to the _u table with alignment_source set at write time.

```
BEFORE (3-step):
  Builder writes to -> price_bars_multi_tf_cal_us
  Sync copies to    -> price_bars_multi_tf_u (alignment_source='multi_tf_cal_us')

AFTER (1-step):
  Builder writes directly to -> price_bars_multi_tf_u (alignment_source='multi_tf_cal_us')
```

**This affects these builder families:**

| Family | # Builders | # Sync Scripts | Write Target Change |
|--------|-----------|----------------|---------------------|
| Price bars | 5 multi-TF | 1 | price_bars_multi_tf_* -> price_bars_multi_tf_u |
| EMA values | 3 | 1 | ema_multi_tf_* -> ema_multi_tf_u |
| AMA values | 5 | 1 | ama_multi_tf_* -> ama_multi_tf_u |
| Bar returns | 5 | 1 | returns_bars_multi_tf_* -> returns_bars_multi_tf_u |
| EMA returns | 3 | 1 | returns_ema_multi_tf_* -> returns_ema_multi_tf_u |
| AMA returns | 5 | 1 | returns_ama_multi_tf_* -> returns_ama_multi_tf_u |
| **Total** | **26 builders** | **6 sync scripts** | |

**Modified components:**

Each builder needs one change: its output table name changes and it sets alignment_source on each row.

```python
# In base class or config:
class BarBuilderConfig:
    ...
    alignment_source: str | None = None   # NEW: if set, write directly to _u table

# In upsert_bars():
if config.alignment_source:
    # Add alignment_source column to output DataFrame
    df["alignment_source"] = config.alignment_source
    # Use _u table PK for conflict resolution
    conflict_cols = PK_COLS_U  # includes alignment_source
```

### 4. Component Boundary Diagram

```
+-------------------------------------------------------------------+
|                    SourceSpec Registry                              |
|  CMC: { source_table, insert_cte, id_loader, repair_flags }       |
|  TVC: { source_table, insert_cte, id_loader, repair_flags }       |
|  HL:  { source_table, insert_cte, id_loader, repair_flags }       |
+-------------------------------------------------------------------+
          |
          v
+-------------------------------------------------------------------+
|            GenericOneDayBarBuilder (BaseBarBuilder)                 |
|  - Accepts SourceSpec via constructor                               |
|  - Delegates SQL generation to spec.insert_cte_builder             |
|  - Handles state, backfill, coverage uniformly                     |
+-------------------------------------------------------------------+
          |
          v
+-------------------------------------------------------------------+
|                     price_bars_1d                                   |
|  (all sources write here, venue/venue_id distinguishes)            |
+-------------------------------------------------------------------+
          |
          v
+-------------------------------------------------------------------+
|  Multi-TF Builders (5 variants)                                    |
|  - Read from price_bars_1d                                         |
|  - Each writes DIRECTLY to price_bars_multi_tf_u                   |
|    with alignment_source = 'multi_tf' | 'cal_us' | etc.           |
+-------------------------------------------------------------------+
          |
          v
+-------------------------------------------------------------------+
|  Downstream (EMA, AMA, Returns, Features, Signals, Regimes)       |
|  - All read from _u tables (no change needed)                      |
+-------------------------------------------------------------------+
```

### 5. Shared psycopg Utilities

Extract the duplicated psycopg helpers into a shared module:

```python
# src/ta_lab2/scripts/bars/psycopg_helpers.py

def normalize_db_url(url: str) -> str: ...
def connect(db_url: str): ...
def exec_sql(conn, sql: str, params=None) -> None: ...
def fetchone(conn, sql: str, params=None): ...
def fetchall(conn, sql: str, params=None): ...
```

This eliminates ~120 lines of identical copy-pasted code across the three 1D builders.

---

## Detailed Data Flow (AFTER)

### 1D Bar Building (After)

```
Source Tables                    Generic 1D Builder            Output
================               ==================            ======
cmc_price_histories7  --+
                        |
tvc_price_histories   --+--> GenericOneDayBarBuilder -----> price_bars_1d
                        |    (--source CMC|TVC|HL|all)      (all venues coexist)
hyperliquid.hl_candles -+
```

### Multi-TF Derivation (After)

```
price_bars_1d
    |
    +---> refresh_price_bars_multi_tf.py --------> price_bars_multi_tf_u
    |     (alignment_source='multi_tf')            (direct write)
    |
    +---> refresh_price_bars_multi_tf_cal_us.py -> price_bars_multi_tf_u
    |     (alignment_source='multi_tf_cal_us')     (direct write)
    |
    +---> refresh_price_bars_multi_tf_cal_iso.py -> price_bars_multi_tf_u
    |     (alignment_source='multi_tf_cal_iso')     (direct write)
    |
    +---> ...anchor_us.py -----------------------> price_bars_multi_tf_u
    |     (alignment_source='multi_tf_cal_anchor_us')
    |
    +---> ...anchor_iso.py ----------------------> price_bars_multi_tf_u
          (alignment_source='multi_tf_cal_anchor_iso')

No sync step needed. Siloed tables become unused.
```

### Full Pipeline (After)

```
run_all_bar_builders.py
  |
  +-- GenericOneDayBarBuilder --source CMC --ids all
  +-- GenericOneDayBarBuilder --source TVC --ids all
  +-- GenericOneDayBarBuilder --source HL  --ids all
  +-- VWAP builder (unchanged)
  +-- refresh_price_bars_multi_tf.py (writes to _u)
  +-- refresh_price_bars_multi_tf_cal_us.py (writes to _u)
  +-- refresh_price_bars_multi_tf_cal_iso.py (writes to _u)
  +-- refresh_price_bars_multi_tf_cal_anchor_us.py (writes to _u)
  +-- refresh_price_bars_multi_tf_cal_anchor_iso.py (writes to _u)
  |
  [NO sync_price_bars_multi_tf_u.py step]
  |
  v
run_all_ema_refreshes.py (reads from price_bars_multi_tf_u -- unchanged)
  +-- refresh_ema_multi_tf_from_bars.py (writes to ema_multi_tf_u)
  +-- ...
  |
  [NO sync_ema_multi_tf_u.py step]
```

---

## Integration Points

### What Changes

| Component | Change | Risk |
|-----------|--------|------|
| `refresh_price_bars_1d.py` | Replaced by generic builder | LOW -- preserves exact same SQL CTEs |
| `refresh_tvc_price_bars_1d.py` | Replaced by generic builder | LOW |
| `refresh_hl_price_bars_1d.py` | Replaced by generic builder | LOW |
| `refresh_price_bars_multi_tf.py` | Output table changes to _u | MEDIUM -- PK conflict cols change |
| `refresh_price_bars_multi_tf_cal_*.py` (4 scripts) | Output table changes to _u | MEDIUM -- PK conflict cols change |
| `sync_price_bars_multi_tf_u.py` | Deprecated/deleted | LOW -- just stops running |
| `sync_ema_multi_tf_u.py` | Deprecated/deleted | LOW |
| `sync_ama_multi_tf_u.py` | Deprecated/deleted | LOW |
| `sync_returns_bars_multi_tf_u.py` | Deprecated/deleted | LOW |
| `sync_returns_ema_multi_tf_u.py` | Deprecated/deleted | LOW |
| `sync_returns_ama_multi_tf_u.py` | Deprecated/deleted | LOW |
| `run_all_bar_builders.py` | Update builder list | LOW |
| `run_daily_refresh.py` | Remove sync steps (if present) | LOW |
| `common_snapshot_contract.py` | Add alignment_source support to upsert_bars | LOW |
| `bar_builder_config.py` | Add alignment_source field | LOW |
| `base_bar_builder.py` | No changes needed | NONE |
| Downstream consumers | No changes (read from _u) | NONE |

### What Does NOT Change

- **BaseBarBuilder**: Template method pattern is unchanged. All abstract methods remain the same.
- **common_snapshot_contract**: Core utilities (enforce_ohlc_sanity, upsert_bars, state helpers) stay the same. alignment_source is additive.
- **derive_multi_tf_from_1d.py**: Already reads from price_bars_1d and produces correct output. Just needs output target changed.
- **polars_bar_operations.py**: Pure computation module, no I/O changes.
- **All downstream consumers**: They read from _u tables, which have the same schema.
- **dim_venues, dim_timeframe**: Dimension tables unchanged.

### PK Conflict Resolution

The key integration detail is that _u tables have alignment_source in their PK:

```sql
-- Siloed table PK (current):
PRIMARY KEY (id, tf, bar_seq, venue_id, timestamp)

-- _u table PK:
PRIMARY KEY (id, tf, bar_seq, venue_id, timestamp, alignment_source)
```

When builders write directly to _u, they must include alignment_source in their conflict columns. The `upsert_bars()` function in common_snapshot_contract.py already accepts `conflict_cols` as a parameter, so this is a configuration change, not a code change.

```python
# Current:
upsert_bars(df, db_url=..., bars_table="price_bars_multi_tf",
            conflict_cols=("id", "tf", "bar_seq", "venue_id", "timestamp"))

# After:
upsert_bars(df, db_url=..., bars_table="price_bars_multi_tf_u",
            conflict_cols=("id", "tf", "bar_seq", "venue_id", "timestamp", "alignment_source"))
```

---

## Build Order (Dependency-Driven)

### Phase 1: Shared Utilities (No Risk)

Create shared psycopg helpers and SourceSpec abstractions. No existing code modified.

**Files created:**
- `src/ta_lab2/scripts/bars/psycopg_helpers.py` (extract from 1D builders)
- `src/ta_lab2/scripts/bars/source_spec.py` (SourceSpec dataclass)
- `src/ta_lab2/scripts/bars/source_registry.py` (registry of CMC/TVC/HL specs)
- `src/ta_lab2/scripts/bars/cte_builders/` (source-specific SQL CTE functions)
  - `cmc_cte.py`
  - `tvc_cte.py`
  - `hl_cte.py`

**Files modified:**
- `bar_builder_config.py`: Add `alignment_source` and `source_name` fields

### Phase 2: Generalized 1D Builder (Additive)

Create the generic builder alongside existing builders. Both coexist.

**Files created:**
- `src/ta_lab2/scripts/bars/refresh_price_bars_1d_generic.py`

**Validation:** Run generic builder for each source, compare output row-by-row against existing builder output using validate_derivation_consistency() pattern (already exists in derive_multi_tf_from_1d.py).

### Phase 3: Direct-to-_u for Price Bars (One Family)

Convert the 5 multi-TF price bar builders to write directly to price_bars_multi_tf_u.

**Files modified:**
- `refresh_price_bars_multi_tf.py`: Change output table, add alignment_source
- `refresh_price_bars_multi_tf_cal_us.py`: Same
- `refresh_price_bars_multi_tf_cal_iso.py`: Same
- `refresh_price_bars_multi_tf_cal_anchor_us.py`: Same
- `refresh_price_bars_multi_tf_cal_anchor_iso.py`: Same
- `common_snapshot_contract.py`: Extend upsert_bars to handle alignment_source

**Validation:** Compare _u table row counts and sample data before/after. Ensure no downstream consumer breaks.

### Phase 4: Direct-to-_u for Remaining Families

Apply the same pattern to EMA, AMA, and returns families.

**Files modified:** 3 EMA builders, 5 AMA builders, 5 bar returns builders, 3 EMA returns builders, 5 AMA returns builders = ~21 scripts.

Each change is mechanical: output table name + alignment_source column.

### Phase 5: Retire Old Builders and Sync Scripts

Once direct-to-_u is validated:

**Files archived (moved to `scripts/_deprecated/`):**
- `refresh_price_bars_1d.py`
- `refresh_tvc_price_bars_1d.py`
- `refresh_hl_price_bars_1d.py`
- `sync_price_bars_multi_tf_u.py`
- `sync_ema_multi_tf_u.py`
- `sync_ama_multi_tf_u.py`
- `sync_returns_bars_multi_tf_u.py`
- `sync_returns_ema_multi_tf_u.py`
- `sync_returns_ama_multi_tf_u.py`

**Files updated:**
- `run_all_bar_builders.py`: Replace three 1D entries with generic builder entries
- `run_daily_refresh.py`: Remove any sync step references
- `run_go_forward_daily_refresh.py`: Remove ema_u_sync step

### Phase 6: Drop Siloed Tables (Optional, Deferred)

After running direct-to-_u successfully for 2+ weeks:

```sql
-- Verify siloed tables are truly unused
SELECT schemaname, relname, last_seq_scan, last_idx_scan
FROM pg_stat_user_tables
WHERE relname IN ('price_bars_multi_tf', 'price_bars_multi_tf_cal_us', ...)
ORDER BY last_seq_scan DESC NULLS LAST;

-- If no scans in 2 weeks, archive (rename, don't drop)
ALTER TABLE price_bars_multi_tf RENAME TO _archive_price_bars_multi_tf;
```

This frees ~250M+ rows of duplicate storage across the 30 siloed tables.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Big-Bang Migration

**What:** Try to change all 6 families and all 3 builders in one phase.
**Why bad:** If something breaks, the blast radius is the entire pipeline. Rollback is impossible.
**Instead:** One family at a time, with a validation gate between each. Price bars first (most critical), then EMA, then returns, then AMA.

### Anti-Pattern 2: Modifying Siloed Table PKs

**What:** Try to add alignment_source to siloed table PKs to make them "compatible" with _u.
**Why bad:** Siloed tables should not need alignment_source. They exist to be single-alignment. The goal is to stop using them.
**Instead:** Leave siloed tables as-is. Only modify builder output targets.

### Anti-Pattern 3: Dual-Write Transition

**What:** Have builders write to BOTH siloed and _u tables during transition.
**Why bad:** Doubles write I/O, doubles maintenance surface, introduces subtle consistency issues if one write succeeds and the other fails.
**Instead:** Switch output table atomically (one builder at a time). Keep sync scripts running until all builders are switched, then remove sync scripts.

### Anti-Pattern 4: Abstract SourceSpec Too Early

**What:** Try to make SourceSpec handle future sources we don't have yet (e.g., Binance, Kraken candles).
**Why bad:** Premature generalization. We don't know what future source quirks look like.
**Instead:** Design SourceSpec for the 3 known sources. Add extensibility points (id_loader, insert_cte_builder) but don't over-engineer the interface.

### Anti-Pattern 5: Changing _u Table Schema

**What:** Alter the _u table schema (add columns, change PKs) as part of this refactor.
**Why bad:** _u tables are the production read path for all downstream consumers. Schema changes affect everything.
**Instead:** _u table schema stays EXACTLY as-is. The only change is WHO writes to it (builders instead of sync scripts).

---

## Scalability Considerations

| Concern | Current | After Consolidation |
|---------|---------|---------------------|
| Storage | ~4.1M rows x 6 tables per family = ~24.6M duplicated rows (price bars alone) | ~4.1M rows in _u only, siloed tables archived |
| Write I/O | Write to siloed + sync to _u = 2x writes | Write to _u only = 1x writes |
| Pipeline latency | Sync step adds 5-15 min per family | No sync step = 5-15 min saved per family |
| Maintenance | 6 sync scripts + 3 duplicate 1D builders | 0 sync scripts + 1 generic 1D builder |
| Adding a venue | Copy-paste 500+ LOC 1D builder | Add a SourceSpec entry (~30 lines) |

---

## Risk Assessment

| Risk | Severity | Probability | Mitigation |
|------|----------|-------------|------------|
| _u table PK collision during migration | HIGH | LOW | Siloed tables already sync to _u with ON CONFLICT DO NOTHING. Direct writes use same PK. |
| Downstream consumer breaks | HIGH | VERY LOW | Consumers read from _u tables. _u schema is unchanged. |
| Data loss during table archival | HIGH | LOW | Archive (rename), never drop. Verify via pg_stat before archive. |
| Generic builder produces different output than original | MEDIUM | LOW | Row-by-row comparison using validate_derivation_consistency() |
| State table schema incompatibility | MEDIUM | LOW | State tables already share PK (id, tf). Generic builder uses same state table. |
| Performance regression in direct-to-_u writes | LOW | LOW | _u table has same indexes. PK includes alignment_source, so no wider conflict check. |

---

## Sources

All findings based on direct source code analysis:

- `src/ta_lab2/scripts/bars/base_bar_builder.py` (557 lines) - Template method base class
- `src/ta_lab2/scripts/bars/bar_builder_config.py` (53 lines) - Configuration dataclass
- `src/ta_lab2/scripts/bars/common_snapshot_contract.py` (1,813 lines) - Shared utilities
- `src/ta_lab2/scripts/bars/refresh_price_bars_1d.py` (822 lines) - CMC 1D builder
- `src/ta_lab2/scripts/bars/refresh_tvc_price_bars_1d.py` (511 lines) - TVC 1D builder
- `src/ta_lab2/scripts/bars/refresh_hl_price_bars_1d.py` (585 lines) - HL 1D builder
- `src/ta_lab2/scripts/bars/run_all_bar_builders.py` (537 lines) - Orchestrator
- `src/ta_lab2/scripts/bars/sync_price_bars_multi_tf_u.py` (72 lines) - Sync to _u
- `src/ta_lab2/scripts/bars/derive_multi_tf_from_1d.py` (807 lines) - Multi-TF derivation
- `src/ta_lab2/scripts/sync_utils.py` (304 lines) - Generic sync utility
- `src/ta_lab2/scripts/emas/sync_ema_multi_tf_u.py` (360 lines) - Legacy EMA sync
- `src/ta_lab2/scripts/emas/base_ema_refresher.py` - EMA template method
- `src/ta_lab2/scripts/amas/sync_ama_multi_tf_u.py` (97 lines) - AMA sync
- `src/ta_lab2/scripts/returns/sync_returns_bars_multi_tf_u.py` (69 lines) - Returns sync
- `src/ta_lab2/scripts/run_daily_refresh.py` - Daily pipeline orchestrator
- `src/ta_lab2/scripts/pipeline/run_go_forward_daily_refresh.py` - Go-forward pipeline
