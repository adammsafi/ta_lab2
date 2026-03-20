# Requirements: ta_lab2 v1.1.0 Pipeline Consolidation & Storage Optimization

**Defined:** 2026-03-19
**Core Value:** Eliminate 100GB+ duplicate data and make adding new data sources mechanical (config, not code)

## v1 Requirements

### Bar Builder Consolidation (BAR)

- [x] **BAR-01**: Single `refresh_price_bars_1d.py` script handles all data sources via `--source cmc|tvc|hl|all` CLI argument
- [ ] **BAR-02**: SourceSpec registry pattern captures per-source differences as data (source table, JOINs, OHLC repair, venue_id mapping, ID loader)
- [x] **BAR-03**: Adding a new data source requires only a new SourceSpec entry — no new script file
- [x] **BAR-04**: Backfill detection works for all sources (currently CMC-only)
- [ ] **BAR-05**: Shared psycopg helper functions extracted from duplicated code (~600 lines deduplicated)
- [x] **BAR-06**: `run_all_bar_builders.py` orchestrator updated to invoke generic builder with `--source` flag
- [x] **BAR-07**: Old source-specific scripts (`refresh_tvc_price_bars_1d.py`, `refresh_hl_price_bars_1d.py`) deleted
- [x] **BAR-08**: Row counts per source match baseline before and after consolidation

### Direct-to-_u Migration (UTB)

- [ ] **UTB-01**: All multi-TF bar builder scripts write directly to `price_bars_multi_tf_u` with correct `alignment_source`
- [ ] **UTB-02**: All EMA builder scripts write directly to `ema_multi_tf_u` with correct `alignment_source`
- [ ] **UTB-03**: All AMA builder scripts write directly to `ama_multi_tf_u` with correct `alignment_source`
- [ ] **UTB-04**: All bar returns scripts write directly to `returns_bars_multi_tf_u` with correct `alignment_source`
- [ ] **UTB-05**: All EMA returns scripts write directly to `returns_ema_multi_tf_u` with correct `alignment_source`
- [ ] **UTB-06**: All AMA returns scripts write directly to `returns_ama_multi_tf_u` with correct `alignment_source`
- [ ] **UTB-07**: Incremental refresh with watermark tracking works correctly on _u tables
- [ ] **UTB-08**: Row counts in _u tables match pre-migration totals (per alignment_source)
- [ ] **UTB-09**: 30 siloed tables dropped from database
- [ ] **UTB-10**: 6 sync scripts deleted from codebase
- [ ] **UTB-11**: State tables updated or consolidated for _u-direct writes
- [ ] **UTB-12**: Dependent views (corr_latest, all_emas, etc.) inventoried and recreated if affected by drops

### Storage Cleanup (CLN)

- [ ] **CLN-01**: NULL first-observation rows pruned from returns tables (rows where all return columns are NULL)
- [ ] **CLN-02**: Returns scripts updated to skip first-observation inserts going forward

### VWAP Pipeline (VWP)

- [ ] **VWP-01**: VWAP bar builder runs for all multi-venue assets automatically (`--ids all`)
- [ ] **VWP-02**: VWAP integrated into `run_all_bar_builders.py` in correct execution order (after per-venue 1D, before multi-TF)

### MCP Cleanup (MCP)

- [ ] **MCP-01**: Dead REST API routes (`/api/v1/memory/*`) removed from memory server
- [ ] **MCP-02**: Stale `client.py` (ChromaDB PersistentClient) deleted

## Future Requirements

None — this milestone is self-contained infrastructure work.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Shadow-write transition period | Research system, not production — row count verification sufficient |
| Archive tables before drop | DROP immediately — no need for 30-60 day archive window |
| Multi-TF builder consolidation | Builders are already source-agnostic, consolidation adds complexity without clear benefit |
| New data source onboarding | BAR-03 enables this, but actually adding sources (e.g., Binance) is a separate milestone |
| EMA/AMA builder consolidation | Keep separate — different computation logic, consolidation not warranted |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BAR-01 | Phase 75 | Complete |
| BAR-02 | Phase 74 | Complete |
| BAR-03 | Phase 75 | Complete |
| BAR-04 | Phase 75 | Complete |
| BAR-05 | Phase 74 | Complete |
| BAR-06 | Phase 75 | Complete |
| BAR-07 | Phase 75 | Complete |
| BAR-08 | Phase 75 | Complete |
| UTB-01 | Phase 76 | Pending |
| UTB-02 | Phase 77 | Pending |
| UTB-03 | Phase 77 | Pending |
| UTB-04 | Phase 77 | Pending |
| UTB-05 | Phase 77 | Pending |
| UTB-06 | Phase 77 | Pending |
| UTB-07 | Phase 76 | Pending |
| UTB-08 | Phase 76 | Pending |
| UTB-09 | Phase 78 | Pending |
| UTB-10 | Phase 78 | Pending |
| UTB-11 | Phase 77 | Pending |
| UTB-12 | Phase 78 | Pending |
| CLN-01 | Phase 79 | Pending |
| CLN-02 | Phase 79 | Pending |
| VWP-01 | Phase 79 | Pending |
| VWP-02 | Phase 79 | Pending |
| MCP-01 | Phase 79 | Pending |
| MCP-02 | Phase 79 | Pending |

**Coverage:**
- v1 requirements: 26 total
- Mapped to phases: 26
- Unmapped: 0

---
*Requirements defined: 2026-03-19*
*Last updated: 2026-03-20 Phase 75 complete (BAR-01, BAR-03, BAR-04, BAR-06, BAR-07, BAR-08 → Complete)*
