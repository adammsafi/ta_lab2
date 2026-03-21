# Phase 78: Table Drops & Script Cleanup - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Drop 30 siloed data tables (plus their state tables), delete 6 sync scripts, fix dependent views to point at _u tables, and verify storage reclamation. This is destructive cleanup after Phase 77 validated all families write directly to _u tables (~400M rows verified).

</domain>

<decisions>
## Implementation Decisions

### Drop ordering & safety
- Run pre-drop row count parity validation for all 6 families before any DROP (re-verify _u matches siloed)
- If any family shows mismatch, abort that family's drops
- Drop all 30 siloed data tables -- no exceptions, no archive
- Drop state tables too (for siloed paths) -- clean break
- Claude decides transaction scope (one-at-a-time vs batch per family)

### Dependent view handling
- Inventory all dependent views via pg_depend before any drops
- Recreate dependent views (corr_latest, all_emas, etc.) pointing at _u tables before dropping siloed tables
- Grep Python codebase for any remaining references to old siloed table names and fix them
- Claude decides FK handling approach per table (CASCADE vs explicit drop)

### Script deletion scope
- Delete all 6 sync scripts (deprecated no-ops from Phase 77)
- Full cleanup: remove CLI entry points, __init__.py imports, and orchestrator references
- Remove sync steps from run_daily_refresh.py and run_all_bar_builders.py
- Claude scans for any other dead-code scripts related to siloed tables and cleans those too

### Storage verification
- Run VACUUM FULL after all drops to reclaim disk space back to OS
- Capture pg_database_size() before and after as a phase artifact
- No downtime concerns -- this is a research/dev DB

### Claude's Discretion
- Transaction boundaries for DROP statements (per-table vs per-family batch)
- FK constraint handling strategy per table
- Discovery of additional dead-code scripts beyond the 6 sync scripts
- Order of operations (views first, then tables, or interleaved)

</decisions>

<specifics>
## Specific Ideas

- Pre-drop validation reuses the same row count parity queries from Phase 76-77 verification artifacts
- The 6 sync scripts: sync_price_bars_multi_tf_u.py, sync_ema_multi_tf_u.py, sync_returns_bars_multi_tf_u.py, sync_returns_ema_multi_tf_u.py, sync_ama_multi_tf_u.py, sync_returns_ama_multi_tf_u.py

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 78-table-drops-script-cleanup*
*Context gathered: 2026-03-20*
