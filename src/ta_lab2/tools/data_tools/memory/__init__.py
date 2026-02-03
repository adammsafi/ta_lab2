"""Memory and embedding tools migrated from Data_Tools/chatgpt/.

This module provides utilities for:
- Embedding codebases into vector stores
- Generating memories from code, diffs, and conversations
- REST API for memory bank access (Vertex AI, Mem0)
- Memory header processing pipelines
- Final memory instantiation with semantic evidence checking

Dependencies:
- OpenAI (for embeddings/LLM): pip install openai
- ChromaDB (for vector store): pip install chromadb
- Mem0 (for memory management): pip install mem0
- Google Auth (for Vertex AI Memory Bank): pip install google-auth
- tiktoken (optional, for accurate token counting): pip install tiktoken

Usage:
    # Embed a codebase
    from ta_lab2.tools.data_tools.memory import get_code_chunks, get_embedding

    # Or run as CLI
    python -m ta_lab2.tools.data_tools.memory.embed_codebase --repo-dir /path --chroma-dir /path

    # Generate memories from diffs
    python -m ta_lab2.tools.data_tools.memory.generate_memories_from_diffs analyze --repo-path /path

    # Process memory headers
    python -m ta_lab2.tools.data_tools.memory.memory_headers_step1_deterministic --index-csv index.csv

Note:
    For production memory operations, use ta_lab2.tools.ai_orchestrator.memory
    which provides Mem0/Qdrant integration. These tools are utilities for
    data preparation and experimentation.

Scripts in this module:

**Embedding & Indexing:**
- embed_codebase.py: AST-based code chunking and embedding
- embed_memories.py: Memory object embedding for semantic search

**Memory Generation:**
- generate_memories_from_code.py: OpenAI-based memory generation from code
- generate_memories_from_diffs.py: Large-scale memory extraction from git diffs (58KB)
- generate_memories_from_conversations.py: Extract memories from ChatGPT conversation exports

**Memory Bank Clients:**
- memory_bank_rest.py: Vertex AI Memory Bank REST client
- memory_bank_engine_rest.py: Enhanced Memory Bank with reasoning engine support

**Memory Processing Pipeline:**
- memory_headers_dedup.py: Deduplicate duplicate YAML front-matter blocks
- memory_headers_step1_deterministic.py: Step 1 - Deterministic header extraction
- memory_headers_step2_openai_enrich.py: Step 2 - OpenAI-based semantic enrichment
- memory_instantiate_children_step3.py: Step 3 - Child memory instantiation (20KB)
- instantiate_final_memories.py: Final memory processing with semantic evidence checking (16KB)

**Utilities:**
- memory_build_registry.py: Build registry of memory sources and metadata
- combine_memories.py: Merge multiple memory JSONL files
- setup_mem0.py: Mem0 integration setup
"""

# Embedding tools
from ta_lab2.tools.data_tools.memory.embed_codebase import (
    get_code_chunks,
    get_embedding,
    main as embed_codebase_cli,
)
from ta_lab2.tools.data_tools.memory.embed_memories import (
    read_jsonl,
    main as embed_memories_cli,
)

# Memory generation
from ta_lab2.tools.data_tools.memory.generate_memories_from_code import (
    generate_memory_for_chunk,
    main as generate_memories_cli,
)

# Vertex AI Memory Bank
from ta_lab2.tools.data_tools.memory.memory_bank_rest import (
    MemoryBankConfig,
    MemoryBankREST,
)

# Mem0 setup
from ta_lab2.tools.data_tools.memory.setup_mem0 import (
    load_memories_from_jsonl,
    init_mem0,
    add_memory_to_mem0,
    main as setup_mem0_cli,
)

__all__ = [
    # Code chunking and embedding
    "get_code_chunks",
    "get_embedding",
    "embed_codebase_cli",
    # Memory embedding
    "read_jsonl",
    "embed_memories_cli",
    # Memory generation
    "generate_memory_for_chunk",
    "generate_memories_cli",
    # Vertex AI Memory Bank
    "MemoryBankConfig",
    "MemoryBankREST",
    # Mem0 setup
    "load_memories_from_jsonl",
    "init_mem0",
    "add_memory_to_mem0",
    "setup_mem0_cli",
    # Note: The following modules are designed primarily as CLI tools
    # and may not export specific functions for programmatic use:
    # - generate_memories_from_diffs (large CLI tool with sub-commands)
    # - generate_memories_from_conversations
    # - memory_headers_dedup
    # - memory_headers_step1_deterministic
    # - memory_headers_step2_openai_enrich
    # - memory_instantiate_children_step3
    # - instantiate_final_memories
    # - memory_bank_engine_rest
    # - memory_build_registry
    # - combine_memories
    #
    # Use them via: python -m ta_lab2.tools.data_tools.memory.<script_name> [args]
]
