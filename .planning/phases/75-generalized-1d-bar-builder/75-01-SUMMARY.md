---
phase: 75-generalized-1d-bar-builder
plan: 01
subsystem: database
tags: [bars, psycopg, dim_data_sources, cmc, tvc, hyperliquid, venue_id, cte, state-migration]

# Dependency graph
requires:
  - phase: 74-02
    provides: dim_data_sources table with CMC/TVC/HL seed rows and CTE templates, psycopg helpers, TVC venue_id=11

provides:
  - Generalized refresh_price_bars_1d.py with --source cmc|tvc|hl|all CLI
  - _load_source_spec() loads per-source config from dim_data_sources
  - _preflight_fix_cte_templates() fixes CMC/TVC templates to include venue_id (idempotent, Python string detection)
  - _migrate_state_table_pk() handles overlapping CMC/TVC/HL IDs with ON CONFLICT DO NOTHING
  - GenericOneDayBarBuilder class with source_spec parameter
  - Generalized backfill detection via ts_column from spec; HL uses dim_asset_identifiers JOIN
  - Post-build sync to price_bars_multi_tf for TVC/HL sources

affects:
  - 75-02 and beyond: all phases that call refresh_price_bars_1d.py
  - BAR-03: new source = new dim_data_sources row (no code change needed)
  - BAR-04: backfill detection works for all sources

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Source registry pattern: per-source config in dim_data_sources.src_cte_template loaded at runtime"
    - "Idempotent pre-flight fix: Python string detection (not SQL LIKE) for CTE template venue_id check"
    - "Overlap-safe state migration: ON CONFLICT DO NOTHING for non-CMC source rows using explicit NULL::timestamptz casts"
    - "Full-rebuild also deletes by src_name to handle legacy data with wrong venue_ids"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/bars/refresh_price_bars_1d.py

key-decisions:
  - "TVC bars use venue_id=11 (TVC source) not per-exchange venue_ids (BYBIT=3/GATE=5/etc.) -- source identity over exchange identity"
  - "Full rebuild path deletes by src_name in addition to venue_id to handle migration from old TVC data with wrong venue_ids"
  - "NULL::timestamptz explicit cast required in state migration INSERT (plain NULL ambiguous in psycopg2 for TIMESTAMPTZ columns)"
  - "Python string detection for CTE template idempotence check ('1::smallint AS venue_id' not in template_text)"

patterns-established:
  - "Pre-flight fix pattern: check in Python before deciding to UPDATE, prevents spurious DB writes on every startup"
  - "Source spec dict: flat dict from dim_data_sources row, passed to builder constructor as source_spec"

# Metrics
duration: 34min
completed: 2026-03-20
---

# Phase 75 Plan 01: Generalized 1D Bar Builder Summary

**GenericOneDayBarBuilder replacing OneDayBarBuilder: one script for CMC/TVC/HL via dim_data_sources config registry, --source CLI flag, state table (id,venue_id,tf) PK migration, and idempotent CTE template venue_id preflight fix**

## Performance

- **Duration:** 34 min
- **Started:** 2026-03-20T11:46:17Z
- **Completed:** 2026-03-20T12:20:30Z
- **Tasks:** 3 (Task 1+2 combined, Task 3 smoke tests)
- **Files modified:** 1

## Accomplishments
- Rewrote `refresh_price_bars_1d.py` as a generalized builder that reads per-source config from `dim_data_sources` at runtime
- CMC, TVC, HL all build 1D bars through single script with `--source` CLI flag
- Pre-flight `_preflight_fix_cte_templates()` fixes CMC/TVC CTE templates to include `venue_id` in INSERT column lists using Python string detection (not SQL LIKE) -- idempotent, no spurious UPDATEs on repeat runs
- State table migration (`_migrate_state_table_pk`) creates new rows for non-CMC sources with `ON CONFLICT DO NOTHING` -- handles overlapping CMC/TVC/HL IDs correctly
- Backfill detection generalized: HL uses explicit JOIN through `dim_asset_identifiers`, CMC/TVC use direct `id` column
- Post-build sync to `price_bars_multi_tf` wired for TVC/HL via `src_name_label` from spec
- Smoke tests: CMC id=1 (5614 rows), TVC id=12573 (2876 rows, full-rebuild), HL id=1 (1167 rows)

## Task Commits

1. **Task 1+2: GenericOneDayBarBuilder with source registry and state migration** - `efaa279d` (feat)
2. **Task 3: Bug fixes from smoke tests** - `b5370d9c` (fix)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `src/ta_lab2/scripts/bars/refresh_price_bars_1d.py` - Complete rewrite: GenericOneDayBarBuilder class, _load_source_spec, _preflight_fix_cte_templates, _migrate_state_table_pk, _check_for_backfill_generic, _sync_1d_to_multi_tf, --source CLI argument

## Decisions Made
- **TVC venue_id=11 for all TVC rows:** All TVC-sourced bars get `venue_id=11` (TVC data source) regardless of the exchange venue text (BYBIT/GATE/etc.). The `venue` TEXT column still distinguishes exchanges; `venue_id` reflects the data source. This matches the `dim_data_sources.venue_id = 11` design from Phase 74.
- **Full-rebuild deletes by src_name:** When rebuilding with `--full-rebuild`, also delete old bars by `src_name = spec['src_name_label']` before deleting by `venue_id`. This handles migration from old data that had different venue_ids (old TVC builder wrote BYBIT=3, GATE=5, etc.).
- **NULL::timestamptz cast:** Plain `NULL` in SQL is ambiguous for TIMESTAMPTZ columns when using psycopg2 without %s params. Must use `NULL::timestamptz` in the state migration INSERT SELECT.
- **Python string detection for idempotence:** Check `'1::smallint AS venue_id' not in template_text` in Python before deciding to UPDATE dim_data_sources. SQL LIKE `NOT LIKE '%venue_id%INSERT%'` was noted as wrong (venue_id appears after INSERT in ON CONFLICT clause).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed NULL::timestamptz ambiguity in state migration INSERT**
- **Found during:** Task 3 (TVC smoke test)
- **Issue:** `SELECT DISTINCT id, 11::smallint, '1D', NULL, NULL, now(), ...` failed with `DatatypeMismatch: column "last_src_ts" is of type timestamp with time zone but expression is of type text` because psycopg2 infers plain NULL as text
- **Fix:** Changed to `NULL::timestamptz, NULL::timestamptz` in both HL and TVC migration INSERT queries
- **Files modified:** `src/ta_lab2/scripts/bars/refresh_price_bars_1d.py`
- **Verification:** TVC smoke test passed after fix
- **Committed in:** b5370d9c

**2. [Rule 1 - Bug] Added src_name deletion to full-rebuild to handle legacy venue_id mismatch**
- **Found during:** Task 3 (TVC incremental smoke test)
- **Issue:** Old TVC data (written before this plan) used per-exchange venue_ids (BYBIT=3, GATE=5, etc.); new TVC template writes venue_id=11. Incremental run hit `UniqueViolation` on partial index `(id, tf, venue, timestamp)` because old BYBIT row with venue_id=3 conflicted with new BYBIT row with venue_id=11 (different PK, same unique index)
- **Fix:** In full-rebuild path, also `DELETE ... WHERE id = %s AND src_name = %s` before the venue_id deletion
- **Files modified:** `src/ta_lab2/scripts/bars/refresh_price_bars_1d.py`
- **Verification:** TVC full-rebuild smoke test produced 2876 rows without errors
- **Committed in:** b5370d9c

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both bugs were blocking smoke tests. Fixes are correct and don't change scope.

## Issues Encountered
- TVC sync to `price_bars_multi_tf` produced a warning for old multi_tf data with stale venue_ids (same root cause as deviation 2). This is expected for this plan -- the multi_tf data migration is a separate concern (future phase).

## User Setup Required
None - no external service configuration required. All changes are code-only.

## Next Phase Readiness
- `refresh_price_bars_1d.py` now handles CMC, TVC, and HL via `--source` flag
- Adding new source requires only a new `dim_data_sources` row (BAR-03 satisfied)
- Backfill detection works for all three sources (BAR-04 satisfied)
- CTE templates in dim_data_sources include venue_id in INSERT column lists
- State table has unified `(id, venue_id, tf)` PK
- Note: Legacy TVC/HL data in `price_bars_multi_tf` still has old venue_ids -- a data migration will be needed before the sync path is fully clean

---
*Phase: 75-generalized-1d-bar-builder*
*Completed: 2026-03-20*
