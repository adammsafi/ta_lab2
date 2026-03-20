# Project Research Summary

**Project:** ta_lab2 v1.1.0 Pipeline Consolidation & Storage Optimization
**Domain:** Infrastructure refactoring for quantitative trading data pipeline (PostgreSQL, Python)
**Researched:** 2026-03-19
**Confidence:** HIGH

## Executive Summary

The v1.1.0 milestone is infrastructure surgery, not a technology adoption exercise. The existing stack (Python 3.12, PostgreSQL 14+, SQLAlchemy 2.0, Alembic, psycopg2) already contains every tool required. No new core dependencies are needed. The work decomposes into two orthogonal streams: (1) consolidating three copy-pasted 1D bar builders (1,915 LOC across CMC, TVC, HL) into a single configurable builder driven by a SourceSpec registry, and (2) eliminating 30 siloed intermediate tables (~200M+ rows, ~100-130 GB) by rewriting ~26 multi-TF/EMA/AMA builder scripts to write directly to unified `_u` tables with `alignment_source` tags, then dropping the now-redundant siloed tables and 6 sync scripts.

The recommended approach is a phased migration with strict validation gates between each phase. Research unanimously recommends against a big-bang cutover. The architecture already supports the target state: downstream consumers (features, regimes, signals, backtests, risk, drift) already read exclusively from `_u` tables, so the migration is invisible to them as long as the `_u` table schema remains unchanged. The existing `BaseBarBuilder` template method pattern, `common_snapshot_contract.py` utilities, and `sync_utils.py` patterns provide the scaffolding. The core consolidation work is extracting source-specific SQL CTEs into a registry and changing output table targets in ~26 scripts.

The primary risks are data integrity during migration and irreversible table drops. The most dangerous pitfall is dropping 30 tables (200M+ rows) without adequate verification that `_u` tables contain all the data. Mitigation is straightforward: archive tables via `ALTER TABLE ... RENAME TO _archive_*` instead of `DROP TABLE`, validate with row counts and aggregate checksums before any archival, define `alignment_source` values as shared constants with database CHECK constraints, and migrate one table family at a time with validation between each. The "no deletion" project convention strongly favors RENAME over DROP. Secondary risks include orphaned state tables, stale watermarks after switching write targets, `ACCESS EXCLUSIVE` lock contention during drops, and the silent destruction of dependent views (`corr_latest`, `all_emas`) if `CASCADE` is used without prior inventory.

## Key Findings

### Recommended Stack

No new core dependencies. The existing stack is battle-tested across 290+ scripts and fully sufficient for this milestone. One optional dev dependency (`pytest-alembic>=0.12.1`) is recommended for migration testing but not required.

**Core technologies (all existing):**
- **PostgreSQL 14+**: Transactional DDL for safe migrations, `DROP TABLE` for immediate disk reclamation, `pg_total_relation_size()` for monitoring
- **Alembic**: Migration scripts for dependency-ordered table drops with fail-fast validation
- **Python dataclasses**: `SourceSpec` frozen dataclass for the source registry pattern -- no external registry library needed
- **psycopg2 + raw SQL CTEs**: Performance-critical bar building stays as raw SQL, not ORM -- the consolidation unifies Python scaffolding, not SQL cores

**What NOT to add:** pg_partman (tables not large enough), pgloader (not migrating between databases), Great Expectations (overkill for row count + checksum validation), dbt (would create a second paradigm), any ORM for tables about to be dropped.

See: [STACK.md](STACK.md) for full decision rationale.

### Expected Features

**Must have (table stakes):**
- **TS-1: SourceSpec registry** -- Declarative config for CMC/TVC/HL source differences (source table, venue_id, OHLC repair flag, ID loader, SQL CTE builder)
- **TS-2: Preserved source-specific SQL** -- CMC keeps its 6-CTE OHLC repair pipeline; TVC/HL keep their simpler SELECTs; no forced unification of SQL
- **TS-3: Venue-aware state table** -- Unified PK `(id, venue_id, tf)` replacing incompatible CMC/TVC/HL state schemas
- **TS-4: alignment_source tag at write time** -- Direct-write scripts set this explicitly, not derived from a sync step
- **TS-5: Correct _u table PK in ON CONFLICT** -- All 6 families include `alignment_source` in conflict columns
- **TS-6: Backward-compatible CLI** -- Thin wrapper scripts preserve `run_all_bar_builders.py` orchestration
- **TS-7: Incremental refresh preserved** -- State-table-driven watermarks continue working identically
- **TS-8: Coverage tracking** -- `asset_data_coverage` upserts continue from consolidated builder

**Should have (differentiators):**
- **D-4: Deduplicated psycopg utilities** -- Extract ~180 lines of copy-pasted helpers to shared module (immediate, no risk)
- **D-5: Unified conflict resolution columns** -- Standardize ON CONFLICT target across all sources to `venue_id` SMALLINT
- **D-3: Validation framework** -- Row-by-row comparison of old vs new output using existing `validate_derivation_consistency()` pattern

**Defer (post v1.1.0):**
- **D-1: Single-pass multi-source build** -- Nice optimization, not blocking
- **D-2: Automatic post-build hooks** -- Current manual `_sync_1d_to_multi_tf()` is adequate
- **D-6: Generalized backfill detection for TVC/HL** -- Not needed yet

**Anti-features (do NOT build):**
- Generic ORM-based bar builder (5-10x slower, loses atomicity)
- Real-time / streaming bar builder (out of scope -- daily-batch system)
- Auto-discovery of new sources (source SQL is too unique for automation)
- Parallel multi-source ID processing (write conflicts on shared output table)
- Materialized view replacement for _u (terrible refresh performance)
- Over-abstracting 6 table families into one "DataFamily" class

See: [FEATURES.md](FEATURES.md) for full feature landscape and dependency graph.

### Architecture Approach

The consolidation has two orthogonal work streams that share no code changes. Stream 1 (SourceSpec registry + generic 1D builder) replaces 3 builder scripts with 1 configurable builder. Stream 2 (direct-to-_u writes) changes the output target of ~26 multi-TF/EMA/AMA builder scripts from siloed tables to `_u` tables with `alignment_source`. Both integrate cleanly with the existing `BaseBarBuilder` template method pattern. Downstream consumers read from `_u` tables and require zero changes.

**Major components:**
1. **SourceSpec registry** (`source_spec.py` + `source_registry.py`) -- Frozen dataclass encapsulating the 3 axes of variation: source query, ID resolution, venue/repair semantics
2. **Source-specific CTE builders** (`cte_builders/cmc_cte.py`, `tvc_cte.py`, `hl_cte.py`) -- Isolated SQL templates per source, referenced by registry
3. **GenericOneDayBarBuilder** -- Single builder accepting SourceSpec; delegates SQL to CTE builder, handles state/coverage uniformly
4. **Shared psycopg helpers** (`psycopg_helpers.py`) -- Extracted `_connect()`, `_exec()`, `_fetchone()`, `_fetchall()`, `_normalize_db_url()`
5. **alignment_source constants module** -- Shared constants preventing typo-driven silent failures

**Key architecture decision -- shadow-write vs atomic cutover:** FEATURES.md recommends shadow-write (write to both siloed and _u during transition). ARCHITECTURE.md recommends against shadow-write (doubles write I/O, introduces consistency risks). **Recommendation: Follow ARCHITECTURE.md -- atomic cutover per-family, per-alignment_source, is safer and simpler.** Keep sync scripts running for non-migrated families during the transition. This avoids the complexity of dual-write and the risk of inconsistency between the two write paths.

See: [ARCHITECTURE.md](ARCHITECTURE.md) for component diagrams and integration point analysis.

### Critical Pitfalls

The top 5 pitfalls that the roadmap must explicitly address:

1. **Irreversible table drops without verification** -- DROP TABLE on 200M+ rows is permanent. Use `ALTER TABLE ... RENAME TO _archive_*` instead of DROP. Verify row counts AND aggregate checksums for every family before archival. Create `pg_dump` backup as belt-and-suspenders. This is the single highest-risk action in the milestone.

2. **Silent destruction of dependent views via CASCADE** -- `corr_latest` (materialized view) and `all_emas` (view) reference tables being dropped. Using `DROP TABLE ... CASCADE` will silently destroy them. Must catalog all dependent views BEFORE any drops using `pg_depend` queries and recreate them pointing at `_u` tables.

3. **alignment_source value mismatch between old sync and new direct-write** -- If a consolidated script writes `alignment_source = 'cal_us'` instead of `'multi_tf_cal_us'`, downstream queries (especially `regime_data_loader.py` which filters on `alignment_source = 'multi_tf'`) silently return 0 rows. Regimes stop updating with no error. Prevention: shared constants module + CHECK constraint on `_u` tables.

4. **Source-specific SQL logic lost during 1D builder consolidation** -- CMC's 6-CTE OHLC repair must be conditionally included ONLY for CMC. If repair runs on TVC/HL (synthesized `time_high/time_low`), it corrupts the data. If repair is omitted for CMC, bad timestamps propagate. Prevention: golden dataset comparison per source before and after.

5. **State table watermark misalignment after switching write targets** -- When a script switches from writing to `ema_multi_tf` to `ema_multi_tf_u`, the state table still tracks the old table's watermark. First run either reprocesses everything (wasteful, hours for AMA) or skips data (gaps). Prevention: populate new state from `_u` table's actual `MAX(ts)` before first run.

See: [PITFALLS.md](PITFALLS.md) for all 15 pitfalls with prevention strategies and detection queries.

## Implications for Roadmap

Based on combined research, the milestone should be structured as 6 phases with explicit validation gates. The two work streams (1D builder consolidation and direct-to-_u migration) are independent and can be parallelized, but the table archival/drop phase must come last after both streams are validated.

### Phase 1: Foundation & Constants

**Rationale:** Creates shared infrastructure that all subsequent phases depend on. Zero risk -- additive only, no existing code modified.

**Delivers:**
- `alignment_source` constants module (prevents typo-driven failures in all subsequent phases)
- Shared `psycopg_helpers.py` module (eliminates ~180 LOC duplication)
- `SourceSpec` dataclass and `source_registry.py` with CMC/TVC/HL entries
- Source-specific CTE builder functions extracted from existing builders
- CHECK constraint on `_u` tables for valid `alignment_source` values

**Addresses:** TS-1 (Source Registry), D-4 (Dedupe psycopg utils), part of TS-4 (alignment_source constants)
**Avoids:** alignment_source mismatch pitfall (Pitfall #3)

### Phase 2: Generalized 1D Bar Builder

**Rationale:** Depends on Phase 1 (SourceSpec registry). The generic builder is created ALONGSIDE existing builders -- both coexist during validation. This is the highest-code-complexity phase but lowest-risk because output is compared against existing builders.

**Delivers:**
- `GenericOneDayBarBuilder` class accepting SourceSpec
- Thin wrapper scripts for backward compatibility with `run_all_bar_builders.py`
- Per-source regression tests with golden dataset comparison
- Venue-aware state table with PK `(id, venue_id, tf)`

**Addresses:** TS-2 (Source-Specific SQL), TS-3 (Venue-Aware State), TS-6 (CLI Compatibility), TS-7 (Incremental Refresh), TS-8 (Coverage Tracking), D-5 (Unified Conflict Resolution)
**Avoids:** Source-specific SQL logic loss (Pitfall #4), orchestrator referencing deleted scripts (Pitfall #6)

### Phase 3: Direct-to-_u for Price Bars (Pilot Family)

**Rationale:** Price bars are the first family in the pipeline dependency chain and the smallest (~4.1M rows). Migrating them first validates the pattern with minimal blast radius. Lessons learned inform the remaining 5 families.

**Delivers:**
- 5 multi-TF price bar builders writing directly to `price_bars_multi_tf_u`
- `ingested_at = now()` explicitly set in all INSERT statements
- State table populated from `_u` actual data
- Validation: row count + checksum comparison between siloed and `_u` data
- `sync_price_bars_multi_tf_u.py` disabled (kept but not run)

**Addresses:** TS-4, TS-5, part of D-3 (Validation)
**Avoids:** ingested_at NULL pitfall, watermark misalignment (Pitfall #5), ON CONFLICT DO NOTHING vs DO UPDATE race

### Phase 4: Direct-to-_u for Remaining Families

**Rationale:** Mechanical repetition of Phase 3 pattern across 5 remaining families. EMA and bar returns first (medium-sized, ~14-16M rows), then AMA (largest, ~91M rows) last because AMA reprocessing is the most expensive if something goes wrong.

**Delivers:**
- 21 remaining builder scripts writing directly to `_u` tables
- 5 remaining sync scripts disabled
- Per-family validation (row counts + checksums)

**Suggested order within phase (by risk and size):**
1. Bar returns (~4.1M rows) -- smallest, validates returns pipeline
2. EMA values (~14.8M rows) -- medium, critical for regime labeling
3. EMA returns (~16M rows) -- medium, follows EMA values
4. AMA values (~91.3M rows) -- largest, most compute-intensive
5. AMA returns (~91.3M rows) -- largest, follows AMA values

**Addresses:** Same as Phase 3 for all families
**Avoids:** Big-bang migration anti-pattern (one family at a time)

### Phase 5: Cleanup & Archival

**Rationale:** Only after ALL families are validated on direct-to-_u writes (2+ weeks of successful daily refreshes). This is the only irreversible phase. Archive (RENAME) rather than DROP, per project "no deletion" convention.

**Delivers:**
- 6 sync scripts deleted (771 LOC removed)
- 3 old 1D builder scripts archived to `scripts/_deprecated/`
- `run_all_bar_builders.py` and `run_daily_refresh.py` updated to remove sync steps
- Dependent views (`corr_latest`, `all_emas`) recreated pointing at `_u` tables
- 30 siloed data tables renamed to `_archive_*` (not dropped)
- 24+ orphaned state tables dropped alongside their data tables
- Storage verification: `pg_database_size()` before and after

**Addresses:** D-8 (Dead Table Cleanup)
**Avoids:** Irreversible data loss (Pitfall #1), CASCADE destroying views (Pitfall #2), orphaned state tables, FK constraint blocking

### Phase 6: Auxiliary Items

**Rationale:** Independent of the main consolidation stream. Can be done in parallel with any phase or deferred without blocking the milestone.

**Delivers:**
- NULL first-observation row pruning from returns tables (~4% of rows)
- VWAP pipeline integration for multi-venue assets
- MCP REST route cleanup (remove dead ChromaDB endpoints)

**Addresses:** Milestone items 3, 4, 5 from the milestone definition
**Avoids:** No specific pitfalls -- these are low-risk, independent changes

### Phase Ordering Rationale

- **Phase 1 before 2:** Registry and constants are dependencies for the generic builder
- **Phase 2 before 3-4:** 1D builder consolidation is independent of direct-to-_u, but completing it first reduces the number of scripts that need target-table changes in Phases 3-4
- **Phase 3 before 4:** Price bars are the smallest and first in the pipeline dependency chain; validates the pattern
- **Phase 4 ordered by size:** Smallest families first to build confidence; AMA (largest, most expensive to reprocess) last
- **Phase 5 after 4:** Table archival ONLY after all families are validated with 2+ weeks of successful direct-to-_u operation
- **Phase 6 any time:** No dependencies on other phases

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 2 (1D Builder):** The state table migration from PK `(id, tf)` to `(id, venue_id, tf)` requires careful analysis of existing state data. CMC and TVC currently share `price_bars_1d_state` -- adding `venue_id` to the PK requires an ALTER TABLE + data migration. Need to audit how many rows exist and what the migration path looks like.
- **Phase 3 (Pilot direct-to-_u):** The exact set of columns in each builder's INSERT statement must be audited against the `_u` table's column set. The `_build_column_mapping()` in `sync_utils.py` handles missing columns by inserting NULL -- the direct-write path must handle this identically.
- **Phase 5 (Archival):** The dependent view inventory (`pg_depend` query) must be run against the actual database to discover ALL views/matviews referencing siloed tables. The research identified `corr_latest` and `all_emas` but there may be others.

**Phases with standard patterns (skip research):**
- **Phase 1 (Foundation):** Pure Python code extraction and constant definition -- well-understood patterns
- **Phase 4 (Remaining Families):** Mechanical repetition of Phase 3 pattern -- no new research needed
- **Phase 6 (Auxiliary):** Independent, well-scoped items with existing patterns

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All decisions verified against existing codebase; no new dependencies needed; PostgreSQL behavior confirmed via official docs |
| Features | HIGH | All findings derived from direct codebase analysis of 16+ source files; feature dependencies mapped from actual code |
| Architecture | HIGH | Component boundaries drawn from existing BaseBarBuilder pattern; integration points verified via source inspection |
| Pitfalls | HIGH | 15 pitfalls identified from codebase analysis + PostgreSQL official docs + practitioner guides; detection queries provided for each |

**Overall confidence: HIGH**

All four research streams were based on direct codebase inspection of the actual files involved. No speculative "what if" analysis -- every pitfall references specific files, line numbers, and existing patterns. The stack decision ("change nothing") is the highest-confidence recommendation possible.

### Gaps to Address

1. **Exact dependent view inventory:** Research identified `corr_latest` and `all_emas` as potentially dependent on siloed tables, but the actual `pg_depend` query must be run against the live database to get the complete list. Do this as the first step of Phase 5 planning.

2. **State table row counts:** The migration from `(id, tf)` to `(id, venue_id, tf)` PK for the shared `price_bars_1d_state` table needs a row count audit. If CMC and TVC have overlapping `(id, tf)` pairs (same asset ID processed by both sources), the PK migration will fail on duplicate rows. Verify before Phase 2.

3. **EMA/AMA script consolidation scope:** PITFALLS.md raises a valid point that `base_ema_refresher.py` already implements the Template Method pattern, so further consolidation of EMA subclasses may yield diminishing returns (<200 LOC savings per family). During Phase 4 planning, evaluate whether to consolidate the EMA/AMA subclass scripts or simply change their output table target. **Recommendation: change output targets only; do not merge subclasses.** The savings from merging subclasses are small and the risk of breaking anchor logic is high.

4. **Shadow-write vs atomic cutover:** FEATURES.md and ARCHITECTURE.md disagree on the migration strategy. Research synthesis recommends atomic cutover (per Architecture) because shadow-write doubles I/O and introduces consistency risks. However, this means each family cutover has no automatic rollback -- if the direct-write produces wrong data, manual intervention is needed. Validate this decision during Phase 3 planning based on actual pipeline runtime constraints.

5. **VWAP pipeline integration scope:** The VWAP item in the milestone definition is not deeply covered by any research file. During Phase 6 planning, scope the VWAP work: which assets, which venue combinations, whether it requires new tables or extends existing ones.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis of 20+ source files (see individual research files for file-level citations)
- [PostgreSQL DROP TABLE Documentation](https://www.postgresql.org/docs/current/sql-droptable.html) -- Lock behavior, CASCADE semantics, disk reclamation
- [PostgreSQL VACUUM Documentation](https://www.postgresql.org/docs/current/sql-vacuum.html) -- VACUUM FULL not needed for DROP TABLE
- [Alembic Operation Reference](https://alembic.sqlalchemy.org/en/latest/ops.html) -- `op.drop_table()` transactional DDL

### Secondary (MEDIUM confidence)
- [pytest-alembic on PyPI](https://pypi.org/project/pytest-alembic/) -- v0.12.1, May 2025
- [Cybertec: Why VACUUM doesn't shrink tables](https://www.cybertec-postgresql.com/en/vacuum-does-not-shrink-my-postgresql-table/) -- Space reclamation on Windows
- [Sequin: Watermarks for CDC in Postgres](https://blog.sequinstream.com/using-watermarks-for-CDC-in-postgres/) -- Watermark race conditions
- [Monte Carlo: Data Migration Risks Checklist](https://www.montecarlodata.com/blog-data-migration-risks-checklist/) -- General migration risk patterns

### Tertiary (LOW confidence)
- None -- all findings verified against codebase or official documentation

---
*Research completed: 2026-03-19*
*Ready for roadmap: yes*
