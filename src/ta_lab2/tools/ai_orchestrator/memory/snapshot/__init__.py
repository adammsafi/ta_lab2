"""Memory snapshot infrastructure for codebase and conversation extraction.

This subpackage provides extraction and indexing infrastructure for Phase 11
memory snapshot operations, establishing reusable scripts for AST-based code
structure analysis, conversation history parsing, and batch memory operations.
"""

# Code extraction (Task 1)
from ta_lab2.tools.ai_orchestrator.memory.snapshot.extract_codebase import (
    extract_code_structure,
    get_file_git_metadata,
    extract_directory_tree,
)

# Conversation extraction (Task 2)
from ta_lab2.tools.ai_orchestrator.memory.snapshot.extract_conversations import (
    extract_conversation,
    extract_phase_boundaries,
    link_conversations_to_phases,
    find_conversation_files,
)

# Batch indexing (Task 3)
from ta_lab2.tools.ai_orchestrator.memory.snapshot.batch_indexer import (
    BatchIndexResult,
    batch_add_memories,
    create_snapshot_metadata,
    format_file_content_for_memory,
)

__all__ = [
    # Code extraction
    "extract_code_structure",
    "get_file_git_metadata",
    "extract_directory_tree",
    # Conversation extraction
    "extract_conversation",
    "extract_phase_boundaries",
    "link_conversations_to_phases",
    "find_conversation_files",
    # Batch indexing
    "BatchIndexResult",
    "batch_add_memories",
    "create_snapshot_metadata",
    "format_file_content_for_memory",
]
