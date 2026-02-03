"""Memory and embedding tools migrated from Data_Tools/chatgpt/.

This module provides utilities for:
- Embedding codebases into vector stores
- Generating memories from code
- REST API for memory bank access
- Mem0 setup utilities

Dependencies:
- OpenAI (for embeddings): pip install openai
- ChromaDB (for vector store): pip install chromadb
- Mem0 (for memory management): pip install mem0
- Google Auth (for Vertex AI Memory Bank): pip install google-auth

Usage:
    # Embed a codebase
    from ta_lab2.tools.data_tools.memory import get_code_chunks, get_embedding

    # Or run as CLI
    python -m ta_lab2.tools.data_tools.memory.embed_codebase --repo-dir /path --chroma-dir /path

Note:
    For production memory operations, use ta_lab2.tools.ai_orchestrator.memory
    which provides Mem0/Qdrant integration. These tools are utilities for
    data preparation and experimentation.

Scripts in this module:
- embed_codebase.py: AST-based code chunking and embedding
- embed_memories.py: Memory object embedding for semantic search
- generate_memories_from_code.py: OpenAI-based memory generation from code
- memory_bank_rest.py: Vertex AI Memory Bank REST client
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
]
