---
phase: 14-tools-integration
plan: 01
subsystem: tools
tags: [ast, openai, chromadb, mem0, pandas, code-analysis, memory-systems]

# Dependency graph
requires:
  - phase: 13-documentation-consolidation
    provides: Document conversion and memory update patterns
provides:
  - Discovery manifest categorizing 51 Data_Tools scripts into migrate (40) vs archive (11)
  - Functional groupings: analysis (3), processing (1), memory (16), export (7), context (5), generators (6)
  - External dependency inventory for pyproject.toml updates
  - Hardcoded path identification for refactoring
affects: [14-02, 14-03, 14-04]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created:
    - ".planning/phases/14-tools-integration/14-01-discovery.json"
  modified: []

key-decisions:
  - "Categorize 40 scripts for migration: analysis tools, memory infrastructure, export processors, context/RAG tools, and report generators"
  - "Archive 11 scripts: 5 one-off runners (duplicate ta_lab2 functionality), 6 prototypes/test scripts (numbered iterations, experimental code)"
  - "Six functional categories: analysis (AST/tree tools), processing (DataFrame utils), memory (embeddings/OpenAI), export (ChatGPT/Claude), context (RAG/reasoning), generators (reports/finetuning)"
  - "Identified 7 external dependencies: openai, chromadb, mem0, google.auth, google.auth.transport.requests, requests, pandas"

patterns-established: []

# Metrics
duration: 5min
completed: 2026-02-02
---

# Phase 14 Plan 01: Tools Integration Discovery Summary

**Categorized 51 Data_Tools scripts: 40 for migration across 6 functional categories (memory/export/context/analysis/generators/processing), 11 for archiving (one-offs and prototypes)**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-03T00:31:40Z
- **Completed:** 2026-02-03T00:36:42Z
- **Tasks:** 3 (combined into single deliverable)
- **Files modified:** 1

## Accomplishments
- Inspected all 51 Python scripts in Data_Tools directory (9 root + 42 chatgpt/)
- Created comprehensive categorization manifest with migrate/archive decisions and rationales
- Identified 6 functional categories for organized migration structure
- Documented external dependencies, hardcoded paths, and complexity levels for each script
- Established migration scope: 40 scripts to integrate, 11 to archive

## Task Commits

All three tasks completed as single atomic deliverable:

1. **Tasks 1-3: Discovery and categorization** - `6830b00` (feat)
   - Inspected root-level scripts (analysis tools, database runners, processing utils)
   - Inspected chatgpt/ scripts (memory, export, context, generators, prototypes)
   - Created functional grouping summary with counts and dependency lists

**Plan metadata:** Not yet committed (will commit with SUMMARY.md and STATE.md updates)

## Files Created/Modified
- `.planning/phases/14-tools-integration/14-01-discovery.json` - Complete discovery manifest with 51 script entries, categorization decisions, rationales, target directories, dependencies, and summary statistics

## Decisions Made

**1. Migration categories established**
- **analysis (3):** AST-based code analysis tools (function maps, tree structure, purpose inference)
- **processing (1):** DataFrame consolidation utilities for multi-timeframe data
- **memory (16):** AI memory/embedding infrastructure (OpenAI, ChromaDB, Mem0, multi-step pipelines)
- **export (7):** ChatGPT/Claude conversation export processing and format conversion
- **context (5):** RAG tools, semantic search, reasoning engines (Vertex AI integration)
- **generators (6):** Report generators (intelligence, reviews, finetuning data, git commits)

**2. Archive categorization established**
- **one_offs (5):** Simple runner scripts that duplicate existing ta_lab2 functionality (write_daily_emas, write_multi_tf_emas, write_ema_multi_tf_cal, upsert_new_emas_canUpdate, github instruction)
- **prototypes (6):** Experimental/test scripts (chatgpt_script_look* numbered series, pipeline, main stub, test runners)

**3. Migration scope: 40 scripts vs 11 archived**
Default to migrate when in doubt - better to have and clean up than lose useful tools. Archive only when:
- Clear duplicate of existing ta_lab2 functionality (simple import wrappers)
- Numbered variations indicating prototyping/iteration (look, look1, look2)
- Test/experimental markers (test_*, empty stubs, pipeline experiments)

**4. External dependencies identified**
For pyproject.toml updates in subsequent plans:
- openai (used by 16 memory scripts, RAG tools, generators)
- chromadb (used by memory/embedding tools, context search)
- mem0 (used by memory setup scripts)
- google.auth + google.auth.transport.requests (used by Vertex AI integrations)
- requests (used by REST clients)
- pandas (used by processing tools)

**5. Hardcoded path refactoring needed**
6 scripts have hardcoded paths requiring parameterization:
- tree_structure.py (line 327: ROOT path)
- chatgpt_script_look*.py (all have hardcoded project paths)
- github instruction.py (hardcoded repo URL - archiving, no fix needed)

## Deviations from Plan

None - plan executed exactly as written. All 51 scripts inspected and categorized per plan specification.

## Issues Encountered

None. Discovery proceeded smoothly with clear categorization patterns emerging:
- Root scripts cleanly split between reusable tools (analysis/processing) and one-off runners
- Chatgpt scripts naturally grouped by function (memory infrastructure, export processing, context/RAG, generators)
- Numbered file variations (look, look1, look2) clearly indicated prototypes for archiving

## Next Phase Readiness

**Ready for 14-02 (Migration Execution):**
- All 40 migrate scripts identified with target directories
- Functional categories defined for organized directory structure
- External dependencies documented for pyproject.toml updates
- Hardcoded paths flagged for refactoring
- Complexity levels assessed (18 simple, 23 moderate, 10 complex)

**Largest/most complex scripts flagged:**
1. generate_memories_from_diffs.py (58KB) - comprehensive git diff processing
2. chatgpt_export_diff.py (24KB) - export comparison tool
3. memory_instantiate_children_step3.py (20KB) - complex memory pipeline
4. ask_project.py (17KB) - RAG-based project Q&A
5. instantiate_final_memories.py (16KB) - memory finalization

These may require extra care during import refactoring and testing.

**No blockers.** Discovery phase complete, migration can proceed.

---
*Phase: 14-tools-integration*
*Completed: 2026-02-02*
