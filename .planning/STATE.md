# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-19)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v1.1.0 Pipeline Consolidation & Storage Optimization

## Current Position

Phase: 78 of 79 (Table Drops & Script Cleanup) -- Gap closure complete (78-04, 78-05, 78-06 all done)
Plan: 6 of 6 complete
Status: Phase complete
Last activity: 2026-03-21 -- Completed 78-06: All EMA feature classes and builder scripts redirected to price_bars_multi_tf_u; EMAStateConfig carries alignment_source for bar_metadata CTE scoping

Progress: [##########] 100% v0.4.0 | [##########] 100% v0.5.0 | [##########] 100% v0.6.0 | [##########] 100% v0.7.0 | [##########] 100% v0.8.0 | [##########] 100% v0.9.0 | [##########] 100% v1.0.0 | [##########] 100% v1.0.1 | [#########.] 78% v1.1.0

## Performance Metrics

**Velocity:**
- Total plans completed: 353
- Average duration: 7 min
- Total execution time: ~28.9 hours

**Recent Trend:**
- v0.8.0: 6 phases, 16 plans, ~1.2 hours
- v0.9.0: 8 phases, 35 plans + 3 cleanup, ~4.0 hours
- v1.0.0: 22 phases, 104 plans, ~14.5 hours
- v1.0.1: 10 phases, 29 plans, ~2.0 hours
- Trend: Stable (~5-7 min/plan)

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Direct-to-_u writes, drop siloed tables (no archive period, DROP immediately)
- Generalized 1D bar builder with source registry (config, not code for new sources)
- Per-family rollout for _u migration (price_bars pilot first, then remaining)
- Bar builder consolidation independent from _u migration (parallel or sequential)
- Row count verification sufficient (no shadow-write period)
- MCP cleanup and VWAP are small independent items
- Raw psycopg helpers centralised in ta_lab2.db.psycopg_helpers; all new bar builders import from there (74-01)
- dim_data_sources table stores SQL CTE templates as TEXT with Python .format() placeholders; Phase 75 builder reads from this table (74-02)
- conflict_columns in dim_data_sources reflects current post-venue_id-migration PK: id,venue_id,tf,bar_seq,timestamp (74-02)
- alignment_source CHECK constraints on all 6 _u tables; 5 valid values enforced at DB level (74-02)
- TVC bars use venue_id=11 (TVC data source) not per-exchange venue_ids; venue TEXT field still distinguishes exchanges (75-01)
- Full-rebuild path deletes by src_name AND venue_id to handle legacy data with wrong venue_ids (75-01)
- NULL::timestamptz cast required in state migration INSERT when using psycopg2 without %s params (75-01)
- Orchestrator builder name "1d" renamed to "1d_cmc"; all 1D builders point to generic script via custom_args source flag (75-02)
- Unified 1d_ prefix handler in build_command(); --keep-rejects only for CMC; --source from custom_args dict (75-02)
- alignment_source in valid_cols of upsert_bars() prevents silent column drop (76-01)
- delete_bars_for_id_tf() accepts alignment_source param (default None) to scope deletes when targeting _u tables (76-01)
- Cal/cal_anchor state tables have tz NOT NULL column; bootstrap hardcodes 'America/New_York' (only value in existing data) (76-01)
- All 5 price bar state tables bootstrapped from price_bars_multi_tf_u; ON CONFLICT uses GREATEST() to advance watermarks (76-01)
- venue_id = bars.get('venue_id', 1) unconditional pattern on all output DataFrames before upsert (76-02)
- from_1d DELETE scoped by alignment_source to avoid wiping other variants' _u rows (76-02)
- All 5 builders now write to price_bars_multi_tf_u with ALIGNMENT_SOURCE class constant (76-02)
- conflict_cols=(id, tf, bar_seq, venue_id, timestamp, alignment_source) is the standard _u upsert tuple (76-02)
- sync_price_bars_multi_tf_u.py disabled as no-op; Phase 78 will remove it (76-03)
- Row count parity confirmed: all 5 alignment_sources show exact MATCH (12,029,626 total rows) (76-03)
- Bar returns _u migration follows identical pattern to price bars pilot (77-01)
- del_state_params split from del_out params: state tables lack alignment_source column (77-01)
- sync_returns_bars_multi_tf_u.py disabled as no-op with DeprecationWarning; Phase 78 will remove it (77-01)
- Bar returns parity confirmed: all 5 sources MATCH (12,019,640 total rows in returns_bars_multi_tf_u) (77-01)
- EMAFeatureConfig.alignment_source (Optional[str]=None) gates both PK extension and DataFrame stamp before to_sql (77-02)
- ema_multi_tf_u PK rebuilt to include alignment_source: (id, venue_id, ts, tf, period, alignment_source) (77-02)
- ISO backfill required: +1.7M (cal_iso) + +1.6M (cal_anchor_iso) rows to fix sync gaps before retiring sync path (77-02)
- EMA parity confirmed: all 5 sources MATCH (55,796,615 total rows in ema_multi_tf_u) (77-02)
- sync_ema_multi_tf_u.py disabled as no-op with DeprecationWarning; Phase 78 will remove it (77-02)
- EMA returns builders read from ema_multi_tf_u scoped by alignment_source (critical: prevents cross-source LAG contamination) (77-03)
- _load_keys() scoped by alignment_source when source is _u table (prevents enumerating all 5 variants' keys) (77-03)
- _tables_for_scheme() returns 4-tuple including alignment_source for clean propagation through dual-scheme loop (77-03)
- EMA returns parity confirmed: all 5 sources MATCH (48,830,818 total rows in returns_ema_multi_tf_u) (77-03)
- sync_returns_ema_multi_tf_u.py disabled as no-op with deprecation message; Phase 78 will remove it (77-03)
- AMAFeatureConfig.alignment_source (Optional[str]=None) gates PK extension, DELETE scope, and DataFrame stamp (77-04)
- get_alignment_source() hook on BaseAMARefresher (default None) propagates to AMAWorkerTask and AMAFeatureConfig (77-04)
- alignment_source stamped on df_write after column filtering in write_to_db() (source DataFrame never has this column) (77-04)
- SCHEME_MAP alignment_source key added to cal/cal_anchor AMA scripts alongside output_table (77-04)
- AMA parity confirmed: all 5 sources MATCH (170,447,220 total rows in ama_multi_tf_u) (77-04)
- sync_ama_multi_tf_u.py disabled as no-op with DEPRECATED message; Phase 78 will remove it (77-04)
- TABLE_MAP 4-tuple (src, dst, state_table, alignment_source) used in refresh_returns_ama.py for _u migration (77-05)
- AMA returns scoped by alignment_source in WHERE prevents cross-source LAG contamination from shared ama_multi_tf_u source (77-05)
- AMA returns parity confirmed: all 5 sources MATCH (113,125,842 total rows in returns_ama_multi_tf_u) (77-05)
- sync_returns_ama_multi_tf_u.py disabled as no-op with deprecation message; Phase 78 will remove it (77-05)
- --skip-resync arg removed from refresh_returns_zscore.py entirely (function gone, arg would be confusing) (78-02)
- ensure_ema_unified_table --sync-after now logs no-op message (flag kept for backward compat; sync scripts removed) (78-02)
- _resync_u_tables() (TRUNCATE + sync) fully removed; builders own _u table writes directly (78-02)
- alignment_source for base table is 'multi_tf' not 'default'; all _u query filters use 'multi_tf' (78-01)
- all_emas view recreated pointing at ema_multi_tf_u (55.8M rows); safe to DROP ema_multi_tf (78-01)
- experiments/runner.py _ALLOWED_TABLES and _TABLES_WITH_TIMESTAMP_COL purged of siloed names (78-01)
- 30 siloed-path state tables kept: all actively referenced by builder STATE_TABLE constants; dropping breaks incremental refresh (78-03)
- State table count in DB is 50 total (not 30): extra stats/feature/signal/pipeline state tables not in RESEARCH.md enumeration; verify by name not count (78-03)
- VACUUM FULL yielded 254 GB (-59%) vs 207 GB (-48%) estimated: compacted _u tables and other tables too (78-03)
- DB size after Phase 78: 177 GB (was 431 GB at start of phase)
- alignment_source='multi_tf' (not 'default') is the correct WHERE filter for base table rows in price_bars_multi_tf_u; applied consistently in all runtime queries (78-04)
- ALL_AUDIT_SCRIPTS in run_all_audits.py trimmed to 3 scripts verified on disk; 14 deleted-script entries removed (78-04)
- AMA feature preload_all_bars uses f-string alignment_filter injection; _load_bars uses where_clauses.append() -- both correct patterns for conditional alignment_source filtering (78-05)
- AMA bar reads now conditional on config.alignment_source (None = reads all variants; set = scoped to one source); normal path always has alignment_source set via SCHEME_MAP (78-05)
- Cal/cal_anchor EMA feature classes compute alignment_source = f"multi_tf_cal_{scheme.lower()}" inline at query time (not stored as attr); scheme is single source of truth (78-06)
- EMAStateConfig.alignment_source field added; bar_metadata CTE uses effective_alignment_source = alignment_source or config.alignment_source to scope bar_seq reads from _u table (78-06)
- EMA pipeline fully redirected to price_bars_multi_tf_u: zero siloed bar table references remain in any EMA builder, feature class, or state manager (78-06)

### Pending Todos

3 pending todos -- see .planning/todos/pending/:
- 2026-03-13: Prune null return rows (addressed by CLN-01/CLN-02 in Phase 79)
- 2026-03-15: Consolidate 1D bar builders (addressed by BAR-01 through BAR-08 in Phases 74-75)
- 2026-03-15: VWAP consolidation and daily pipeline (addressed by VWP-01/VWP-02 in Phase 79)

### Blockers/Concerns

- Legacy TVC/HL data in price_bars_multi_tf still has old venue_ids -- sync path will warn until that data is migrated. Not blocking for Phase 75 remaining plans.

## Session Continuity

Last session: 2026-03-21
Stopped at: Completed 78-06-PLAN.md -- EMA feature classes and builder scripts redirected to price_bars_multi_tf_u; Phase 78 gap closure complete
Resume file: None

---
*Created: 2025-01-22*
*Last updated: 2026-03-21 (78-06 complete -- EMA layer fully redirected to price_bars_multi_tf_u; Phase 78 all 6 plans done)*
