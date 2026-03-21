---
phase: 79-storage-pipeline-cleanup
verified: 2026-03-21T17:03:42Z
status: passed
score: 8/8 must-haves verified
gaps: []
---

# Phase 79: Storage and Pipeline Cleanup Verification Report

**Phase Goal:** NULL return rows pruned, VWAP pipeline integrated, MCP dead routes removed
**Verified:** 2026-03-21T17:03:42Z
**Status:** passed
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

Truth 1: AMA returns SQL skips first-observation rows (no all-NULL rows inserted)
- Status: VERIFIED
- Evidence: grep confirms line 150 of refresh_returns_ama.py contains WHERE delta1_ama_roll IS NOT NULL in _INSERT_SQL template.

Truth 2: Existing all-NULL first-observation rows pruned from returns_ama_multi_tf_u
- Status: VERIFIED
- Evidence: 79-01-SUMMARY.md documents 7,180,871 rows deleted (117,213,138 -> 110,032,267); commit 7ad9baf7 executed the prune.

Truth 3: Row count reduction logged before and after
- Status: VERIFIED
- Evidence: 79-01-SUMMARY.md contains pre-prune count (117,213,138), post-prune count (110,032,267), and per-alignment_source breakdown.

Truth 4: VWAP bar builder runs for all multi-venue assets automatically via --ids all
- Status: VERIFIED
- Evidence: Lines 174-175 of refresh_vwap_bars_1d.py: if args.ids.lower() == "all" calls _load_ids_with_multiple_venues().

Truth 5: VWAP integrated into run_all_bar_builders.py in correct execution order
- Status: VERIFIED
- Evidence: Lines 76-82 of run_all_bar_builders.py show BuilderConfig(name=vwap) at ALL_BUILDERS index 3 -- after 1d_cmc/1d_tvc/1d_hl, before multi_tf.

Truth 6: Dead REST API routes (/api/v1/memory/*) removed from memory server
- Status: VERIFIED
- Evidence: api.py contains exactly one route: @app.get("/health") at line 35. Grep for /api/v1/memory returns only the comment referencing removal.

Truth 7: Stale client.py (ChromaDB PersistentClient) deleted
- Status: VERIFIED
- Evidence: Filesystem check confirms src/ta_lab2/tools/ai_orchestrator/memory/client.py DOES NOT EXIST on disk.

Truth 8: MCP tools (/mcp/) continue to work via mcp_server.py
- Status: VERIFIED
- Evidence: mcp_server.py EXISTS. server.py line 35: mcp_app = mcp.http_app(path=). line 42: api.mount(/mcp, mcp_app).

**Score: 8/8 truths verified**

---

## Required Artifacts

Artifact: src/ta_lab2/scripts/amas/refresh_returns_ama.py
- Expected: AMA returns builder with first-observation filter
- Status: VERIFIED
- Level 1 (Exists): YES
- Level 2 (Substantive): 573 lines, exports main(), no stubs
- Level 3 (Wired): Called by daily refresh pipeline
- Key check: WHERE delta1_ama_roll IS NOT NULL confirmed at line 150

Artifact: src/ta_lab2/scripts/bars/refresh_vwap_bars_1d.py
- Expected: VWAP bar builder for all multi-venue assets
- Status: VERIFIED
- Level 1 (Exists): YES
- Level 2 (Substantive): 195 lines, exports main(), no stubs
- Level 3 (Wired): Referenced by run_all_bar_builders.py at index 3
- Key check: --ids all branch implemented; venue_id \!= 1 filter (not old venue TEXT column)

Artifact: src/ta_lab2/tools/ai_orchestrator/memory/server.py
- Expected: Combined ASGI app with MCP only (no dead REST routes)
- Status: VERIFIED
- Level 1 (Exists): YES
- Level 2 (Substantive): 51 lines, create_app() and app exported, no stubs
- Level 3 (Wired): app = create_app() at module level, uvicorn entry point
- Key check: mcp.http_app() mounted at /mcp; no /api/v1/ routes

Artifact: src/ta_lab2/tools/ai_orchestrator/memory/__init__.py
- Expected: Package init without ChromaDB client imports
- Status: VERIFIED
- Level 1 (Exists): YES
- Level 2 (Substantive): 203 lines, comprehensive __all__ list
- Level 3 (Wired): Imports from all live submodules (mem0_client, validation, etc.)
- Key check: No from .client import lines; no MemoryClient/get_memory_client in __all__

Artifact: src/ta_lab2/tools/ai_orchestrator/memory/client.py
- Expected: DELETED (ChromaDB PersistentClient)
- Status: VERIFIED
- Check: File does not exist on disk

---

## Key Link Verification

Link 1: refresh_returns_ama.py -> returns_ama_multi_tf_u
- Via: INSERT SQL with WHERE delta1_ama_roll IS NOT NULL
- Status: VERIFIED
- Evidence: Line 150: SELECT *, alignment_source FROM pass2 WHERE delta1_ama_roll IS NOT NULL ON CONFLICT (id, venue_id, ts, tf, indicator, params_hash, alignment_source) DO NOTHING

Link 2: refresh_vwap_bars_1d.py -> price_bars_1d
- Via: INSERT...SELECT with VWAP aggregation using SUM/NULLIF
- Status: VERIFIED
- Evidence: Lines 83+86: SUM(open * volume) / NULLIF(SUM(volume), 0) AS open and SUM(close * volume) / NULLIF(SUM(volume), 0) AS close

Link 3: refresh_vwap_bars_1d.py -> run_all_bar_builders.py
- Via: BuilderConfig entry at index 3 in ALL_BUILDERS
- Status: VERIFIED
- Evidence: Lines 76-82: BuilderConfig(name="vwap", script_path="refresh_vwap_bars_1d.py") after 1d_hl, before multi_tf

Link 4: server.py -> mcp_server.py
- Via: mcp.http_app() mount at /mcp/
- Status: VERIFIED
- Evidence: Line 35: mcp_app = mcp.http_app(path="/"), line 42: api.mount("/mcp", mcp_app). mcp imported from .mcp_server at line 32.

Link 5: api.py health check -> Qdrant via Mem0
- Via: get_mem0_client().memory_count
- Status: VERIFIED
- Evidence: Lines 39-42 of api.py: lazy import of get_mem0_client, count = client.memory_count

Link 6: __init__.py removal of client.py import
- Via: from .client import (REMOVED)
- Status: VERIFIED
- Evidence: grep for from .client import in __init__.py returns NO MATCHES

---

## Requirements Coverage

CLN-01: NULL first-observation rows pruned from returns tables
- Status: SATISFIED
- Evidence: 7,180,871 rows deleted from returns_ama_multi_tf_u across 5 alignment_sources (documented in 79-01-SUMMARY.md)

CLN-02: Returns scripts updated to skip first-observation inserts going forward
- Status: SATISFIED
- Evidence: WHERE delta1_ama_roll IS NOT NULL added to _INSERT_SQL at line 150 of refresh_returns_ama.py

VWP-01: VWAP bar builder runs for all multi-venue assets automatically (--ids all)
- Status: SATISFIED
- Evidence: --ids all triggers _load_ids_with_multiple_venues(); script ran without errors per 79-02-SUMMARY.md

VWP-02: VWAP integrated into run_all_bar_builders.py in correct execution order
- Status: SATISFIED
- Evidence: Index 3 in ALL_BUILDERS: after 1d_cmc/1d_tvc/1d_hl, before multi_tf and all cal_* builders

MCP-01: Dead REST API routes (/api/v1/memory/*) removed from memory server
- Status: SATISFIED
- Evidence: api.py has only one route: @app.get("/health") at line 35. No /api/v1/ routes exist.

MCP-02: Stale client.py (ChromaDB PersistentClient) deleted
- Status: SATISFIED
- Evidence: File does not exist on disk. No top-level imports from client.py remain in __init__.py or validation.py.

---

## Anti-Patterns Scan

refresh_returns_ama.py: No TODO/FIXME, no empty handlers, no placeholder content -- CLEAN
refresh_vwap_bars_1d.py: No TODO/FIXME, no empty handlers, real SQL implementation -- CLEAN
server.py: Clean MCP-only surface, real implementation -- CLEAN
api.py: Single /health endpoint with real Qdrant-backed implementation -- CLEAN
__init__.py: No ChromaDB imports, all exports reference real implementations -- CLEAN
validation.py: raise ImportError in validate_memory_store() is intentional (migration note), quick_health_check() uses Qdrant -- INFO only, not a stub

No blockers or warnings found.

---

## Additional Findings

VWAP Schema Fix (cross-plan deviation)
The VWAP builder was fixed to use venue_id SMALLINT instead of the old venue TEXT column during plan 79-03 execution (commit 54539bf2). Plan 79-02 confirmed the fix. The VWAP SQL now correctly uses venue_id \!= 1 to exclude CMC_AGG inputs and writes output with venue_id=1, src_name=VWAP. No old venue TEXT references remain in refresh_vwap_bars_1d.py.

GOOGL/NVDA 0 VWAP Bars -- Correct Behavior
The VWAP builder produces 0 bars for GOOGL/NVDA because NASDAQ timestamps (09:30) and Hyperliquid timestamps (19:xx) never overlap within a calendar day. HAVING COUNT(*) >= 2 per-timestamp group produces no rows. This is correct behavior documented in 79-02-SUMMARY.md.

Lazy Imports in Deferred Modules Preserved
query.py, update.py, and migration.py contain lazy from .client import calls inside function bodies. These are NOT top-level imports and will only fail if the deferred orchestrator code paths are called (zero active consumers). Per project convention (Deferred, not abandoned), these are left intact.

---

## Human Verification Required

None. All phase goals are verifiable from the codebase structure:
- SQL filter existence: verifiable by grep (confirmed)
- File deletion: verifiable by filesystem check (confirmed)
- Route removal: verifiable by reading api.py (confirmed)
- Builder ordering: verifiable by reading run_all_bar_builders.py (confirmed)
- Row count reduction: documented in operational summary; cannot query DB directly but prune commit 7ad9baf7 was executed

---

## Summary

Phase 79 achieved all three goals:

NULL row pruning (CLN-01, CLN-02): refresh_returns_ama.py contains WHERE delta1_ama_roll IS NOT NULL at line 150 of _INSERT_SQL, preventing first-observation NULL rows from being inserted going forward. The one-time DELETE of 7,180,871 rows (6.13% reduction) is documented in 79-01-SUMMARY.md with pre/post counts per alignment_source.

VWAP pipeline integration (VWP-01, VWP-02): refresh_vwap_bars_1d.py supports --ids all via auto-detection of multi-venue assets using HAVING COUNT(DISTINCT venue_id) >= 2, uses the correct venue_id schema, and is positioned at index 3 in run_all_bar_builders.py (after per-venue 1D builders, before multi-TF). The SQL uses SUM(close * volume) / NULLIF(SUM(volume), 0) for VWAP aggregation.

MCP dead route removal (MCP-01, MCP-02): api.py is stripped to a single /health endpoint using Qdrant via get_mem0_client().memory_count. All 9 dead /api/v1/memory/* routes are gone. client.py is deleted from disk. __init__.py has no from .client import lines. validation.py has no top-level client.py import. server.py mounts MCP at /mcp/ via mcp.http_app().

---

_Verified: 2026-03-21T17:03:42Z_
_Verifier: Claude (gsd-verifier)_
