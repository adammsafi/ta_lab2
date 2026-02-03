---
phase: 14-tools-integration
plan: 06
subsystem: tools
tags: [chatgpt, claude, export, processing, conversation-analysis, format-conversion, data-pipeline]

# Dependency graph
requires:
  - phase: 14-02
    provides: Empty data_tools package structure with 6 functional subdirectories
provides:
  - Complete export module with 9 tools for ChatGPT/Claude conversation processing
  - Export conversations from ChatGPT data exports to Markdown/CSV
  - Semantic diff tool for comparing exports (conversation-level changes)
  - Trash list cleaning system for removing unwanted files
  - Claude Code conversation format converter (JSONL to ChatGPT JSON)
  - Pipeline orchestration tools for processing new dumps
affects: [14-07, memory-tools, context-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Export processing pipeline pattern: filter → process → combine → embed"
    - "Semantic conversation diffing (content hash vs file-level comparison)"
    - "Persistent trash list approach for consistent export cleaning"

key-files:
  created:
    - "src/ta_lab2/tools/data_tools/export/export_chatgpt_conversations.py"
    - "src/ta_lab2/tools/data_tools/export/chatgpt_export_diff.py"
    - "src/ta_lab2/tools/data_tools/export/chatgpt_export_clean.py"
    - "src/ta_lab2/tools/data_tools/export/chatgpt_pipeline.py"
    - "src/ta_lab2/tools/data_tools/export/extract_kept_chats_from_keepfile.py"
    - "src/ta_lab2/tools/data_tools/export/process_new_chatgpt_dump.py"
    - "src/ta_lab2/tools/data_tools/export/process_claude_history.py"
    - "src/ta_lab2/tools/data_tools/export/convert_claude_code_to_chatgpt_format.py"
  modified:
    - "src/ta_lab2/tools/data_tools/export/__init__.py"

key-decisions:
  - "Migrated all 7 export scripts plus 1 orchestrator (8 total) from Data_Tools/chatgpt/"
  - "Updated chatgpt_pipeline.py to call scripts via Python module paths (-m ta_lab2.tools...)"
  - "Removed all hardcoded user-specific paths, converted to CLI arguments"
  - "Added programmatic functions (export_conversations, diff_exports, clean_export, etc.) for library usage"
  - "Maintained semantic diff functionality (conversation-level content analysis, not just file checksums)"

patterns-established:
  - "Export module provides both CLI scripts and importable functions for flexibility"
  - "All cross-script references use ta_lab2.tools.data_tools.export module paths"
  - "Pipeline scripts coordinate external tools via subprocess with proper error handling"

# Metrics
duration: 11min
completed: 2026-02-03
---

# Phase 14 Plan 06: ChatGPT/Claude Export Tools Migration Summary

**Migrated 9 conversation export/processing tools: ChatGPT export to Markdown/CSV, semantic diff analyzer, trash list cleaner, format converter, and processing pipelines**

## Performance

- **Duration:** 11 min
- **Started:** 2026-02-03T00:47:35Z
- **Completed:** 2026-02-03T00:58:36Z
- **Tasks:** 3
- **Files modified:** 9 (8 created, 1 updated)

## Accomplishments
- Migrated all ChatGPT export processing tools (export, diff, clean, pipeline)
- Added Claude Code conversation format converter (JSONL → ChatGPT JSON)
- Implemented processing pipelines for new dumps and Claude history
- Created public API in __init__.py for programmatic usage
- All scripts use argparse CLI patterns with comprehensive logging
- Removed all hardcoded user-specific paths

## Task Commits

Each task was committed atomically:

1. **Task 1: Migrate core export tools** - `3cd46f5` (feat)
   - export_chatgpt_conversations.py: Convert conversations.json to Markdown/CSV with noise detection
   - extract_kept_chats_from_keepfile.py: Filter and copy chat transcripts from keep list

2. **Task 2: Migrate diff and cleaning tools** - `e86768e` (feat)
   - chatgpt_export_diff.py: Compare two exports with semantic conversation analysis
   - chatgpt_export_clean.py: Remove trash files using persistent trash list
   - chatgpt_pipeline.py: Orchestrate cleaning and extraction workflow

3. **Task 3: Migrate processing tools, update __init__.py, and verify cross-imports** - `1054328` (feat)
   - process_new_chatgpt_dump.py: Filter and process new ChatGPT exports
   - process_claude_history.py: Convert Claude Code history to ChatGPT format
   - convert_claude_code_to_chatgpt_format.py: JSONL to JSON conversation converter
   - Updated __init__.py with public function exports

**Plan metadata:** Will be committed with STATE.md updates

## Files Created/Modified
- `src/ta_lab2/tools/data_tools/export/export_chatgpt_conversations.py` - Export ChatGPT conversations.json to per-chat Markdown files + CSV index with noise detection heuristics
- `src/ta_lab2/tools/data_tools/export/chatgpt_export_diff.py` - Semantic diff tool comparing two ChatGPT exports (zip/folder) at conversation level with content hashing
- `src/ta_lab2/tools/data_tools/export/chatgpt_export_clean.py` - Remove unwanted files using persistent trash list (initialized from diff output)
- `src/ta_lab2/tools/data_tools/export/chatgpt_pipeline.py` - Orchestrate multi-step workflow: clean → export → filter → zip
- `src/ta_lab2/tools/data_tools/export/extract_kept_chats_from_keepfile.py` - Extract subset of chats from keep CSV with fallback path resolution
- `src/ta_lab2/tools/data_tools/export/process_new_chatgpt_dump.py` - Pipeline for new dumps: filter new conversations, generate memories, re-embed
- `src/ta_lab2/tools/data_tools/export/process_claude_history.py` - Pipeline for Claude Code: convert → generate memories → combine → embed
- `src/ta_lab2/tools/data_tools/export/convert_claude_code_to_chatgpt_format.py` - Convert Claude Code JSONL to ChatGPT JSON format
- `src/ta_lab2/tools/data_tools/export/__init__.py` - Public API exports for programmatic usage

## Decisions Made

**1. Updated chatgpt_pipeline.py to use Python module paths**
- Original used file-based subprocess calls to sibling scripts
- Migrated version uses `python -m ta_lab2.tools.data_tools.export.script_name`
- Ensures consistent import paths across all orchestration

**2. Created dual interfaces: CLI + programmatic**
- All scripts have main() with argparse for CLI usage
- Extracted core functions (export_conversations, diff_exports, clean_export, etc.) for library usage
- Exported via __init__.py for `from ta_lab2.tools.data_tools.export import export_conversations`

**3. Removed all hardcoded user-specific paths**
- Original scripts had hardcoded `C:\Users\asafi\...` paths
- Converted to CLI arguments with sensible defaults (e.g., ~/.claude/projects)
- Verified no hardcoded paths remain: grep found zero matches

**4. Maintained semantic diff functionality**
- chatgpt_export_diff.py does content-aware conversation analysis (not just file checksums)
- Detects append-only changes, truncations, internal edits, meta-only changes
- Generates per-conversation patches with unified diffs

**5. Preserved pipeline coordination pattern**
- Processing scripts (process_new_chatgpt_dump.py, process_claude_history.py) coordinate external tools
- Accept script paths as arguments for flexibility (memory generation, embedding tools)
- Use subprocess with proper error handling and output capture

## Deviations from Plan

None - plan executed exactly as written. All 7 core scripts + 1 pipeline script migrated, imports updated to ta_lab2 paths, hardcoded paths removed, __init__.py exports added, verification passed.

## Issues Encountered

None. Migration proceeded smoothly:
- All original scripts had clean structure with no complex dependencies
- chatgpt_pipeline.py only referenced other scripts via subprocess (no import-based coupling)
- All scripts already used pathlib.Path, just needed argument extraction
- Import verification confirmed no bare module imports remain

## Next Phase Readiness

**Ready for 14-07 (Generators and Context Tools):**
- Export module complete with 9 working tools
- All scripts importable and executable via CLI
- Pattern established for script migration: remove hardcoded paths, add logging, extract functions, update __init__.py
- Cross-import verification workflow established: grep for non-ta_lab2 imports excluding stdlib

**Export module capabilities:**
1. Export conversations from ChatGPT data exports
2. Diff two exports to find new/changed conversations
3. Clean exports with persistent trash list
4. Extract subset of chats from keep list
5. Convert Claude Code history to ChatGPT format
6. Process new ChatGPT dumps (filter → generate memories)
7. Process Claude history (convert → generate memories)
8. Pipeline orchestration for multi-step workflows
9. All available as both CLI tools and library functions

**No blockers.** Export tools complete and verified. Ready for next migration wave.

---
*Phase: 14-tools-integration*
*Completed: 2026-02-03*
