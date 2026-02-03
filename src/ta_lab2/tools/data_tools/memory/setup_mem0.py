#!/usr/bin/env python3
"""Load memories from JSONL into Mem0 with ChromaDB backend.

Migrates memory records from JSONL file format into Mem0 memory system.
Uses ChromaDB as the vector store backend with OpenAI embeddings.

Memory JSONL format:
    Each line should be a JSON object with:
    - title: Memory title/summary
    - content or summary: Memory content
    - memory_id: Unique identifier
    - type or memory_type: Memory category
    - source_commit, source_path, confidence, tags: Optional metadata

Usage:
    # Set required environment variable
    export OPENAI_API_KEY=your-key

    # Optional configuration
    export MEM0_USER_ID=adam  # default: adam
    export MEM0_DB_PATH=~/.mem0/chroma.db  # default: ~/.mem0

    python -m ta_lab2.tools.data_tools.memory.setup_mem0 \\
        --memory-file all_memories_final.jsonl

Dependencies:
    - mem0: pip install mem0
    - openai: pip install openai (required by mem0)

Note:
    For production memory operations, use ta_lab2.tools.ai_orchestrator.memory
    which provides Qdrant integration. This tool uses ChromaDB backend for
    data preparation and experimentation.
"""
import argparse
import json
import os
import logging
from pathlib import Path
from typing import Dict, Any, List

try:
    from mem0 import Memory
except ImportError:
    raise ImportError(
        "Mem0 library required. Install with: pip install mem0"
    )

logger = logging.getLogger(__name__)


def load_memories_from_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load all memories from JSONL file.

    Args:
        path: Path to JSONL file with memory records

    Returns:
        List of memory dicts
    """
    memories = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                memories.append(json.loads(line))
    return memories


def init_mem0(db_path: str) -> Memory:
    """Initialize Mem0 with ChromaDB backend.

    Args:
        db_path: Path to ChromaDB storage directory

    Returns:
        Configured Memory instance

    Note:
        Uses OpenAI text-embedding-3-small for embeddings (OPENAI_API_KEY required)
    """
    # mem0 uses OpenAI embeddings by default (text-embedding-3-small)
    # It stores in ~/.mem0/ by default

    config = {
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "text-embedding-3-small",
            }
        },
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": "mem0_memories",
                "path": db_path,
            }
        },
    }

    return Memory.from_config(config)


def add_memory_to_mem0(
    mem0: Memory,
    memory: Dict[str, Any],
    user_id: str,
) -> Dict[str, Any]:
    """Add a single memory to Mem0.

    Args:
        mem0: Memory instance
        memory: Memory dict with title, content, metadata
        user_id: User identifier for scoping

    Returns:
        Result dict from Mem0 add operation
    """
    # Build text content from memory fields
    text_parts = []

    # Title
    if memory.get("title"):
        text_parts.append(f"Title: {memory['title']}")

    # Content
    if memory.get("content"):
        text_parts.append(f"Content: {memory['content']}")
    elif memory.get("summary"):
        text_parts.append(f"Summary: {memory['summary']}")

    text_content = "\n".join(text_parts)

    # Build metadata
    metadata = {
        "memory_id": memory.get("memory_id", "unknown"),
        "type": memory.get("type", memory.get("memory_type", "other")),
        "source": "chromadb_migration",
    }

    # Add source info if available
    if memory.get("source_commit"):
        metadata["source_commit"] = memory["source_commit"]
    if memory.get("source_path"):
        metadata["source_path"] = memory["source_path"]
    if memory.get("confidence"):
        metadata["confidence"] = memory["confidence"]
    if memory.get("tags"):
        metadata["tags"] = ",".join(memory["tags"]) if isinstance(memory["tags"], list) else memory["tags"]

    # Add to mem0
    result = mem0.add(
        messages=text_content,
        user_id=user_id,
        metadata=metadata,
    )

    return result


def main() -> int:
    """CLI entry point for Mem0 setup."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    log = logging.getLogger()

    ap = argparse.ArgumentParser(
        description="Load memories from JSONL into Mem0 with ChromaDB backend."
    )
    ap.add_argument("--memory-file", required=True, help="Path to JSONL file with memory records.")
    ap.add_argument("--user-id", help="User ID for memory scoping (default: from MEM0_USER_ID env or 'adam')")
    ap.add_argument("--db-path", help="Path to ChromaDB storage (default: from MEM0_DB_PATH env or ~/.mem0)")
    ap.add_argument("--batch-size", type=int, default=50, help="Batch size for progress reporting.")
    args = ap.parse_args()

    # Config
    user_id = args.user_id or os.getenv("MEM0_USER_ID", "adam")
    db_path = args.db_path or os.getenv("MEM0_DB_PATH", str(Path.home() / ".mem0"))
    input_file = Path(args.memory_file)

    if not os.getenv("OPENAI_API_KEY"):
        log.error("OPENAI_API_KEY environment variable is required")
        return 1

    if not input_file.exists():
        log.error(f"Memory file not found: {input_file}")
        return 1

    log.info(f"Initializing Mem0 for user: {user_id}")
    log.info(f"Storage path: {db_path}")

    mem0 = init_mem0(db_path)

    log.info(f"Loading memories from: {input_file}")
    memories = load_memories_from_jsonl(input_file)
    log.info(f"Loaded {len(memories)} memories")

    # Add memories in batches
    batch_size = args.batch_size
    total = len(memories)
    added = 0
    failed = 0

    for i in range(0, total, batch_size):
        batch = memories[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size

        log.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} memories)...")

        for mem in batch:
            try:
                result = add_memory_to_mem0(mem0, mem, user_id)
                added += 1
            except Exception as e:
                log.warning(f"Failed to add memory {mem.get('memory_id', 'unknown')}: {e}")
                failed += 1

        log.info(f"Batch complete. Total added: {added}, failed: {failed}")

    log.info(f"✓ Migration complete!")
    log.info(f"  Added: {added}")
    log.info(f"  Failed: {failed}")
    log.info(f"  Total: {total}")

    # Test retrieval
    log.info(f"--- Testing Mem0 retrieval ---")
    test_query = "validation framework"
    results = mem0.search(query=test_query, user_id=user_id, limit=3)
    log.info(f"Query: {test_query}")
    log.info(f"Results: {len(results)} memories found")
    for idx, result in enumerate(results, 1):
        log.info(f"{idx}. {result.get('memory', 'N/A')[:100]}...")
        log.info(f"   Metadata: {result.get('metadata', {})}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
