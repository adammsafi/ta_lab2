#!/usr/bin/env python3
"""Embed memory records into ChromaDB vector store using OpenAI embeddings.

Reads memory records from JSONL file (with title, content, type fields),
generates embeddings using OpenAI's API, and stores them in ChromaDB for
semantic memory search.

Memory JSONL format:
    Each line should be a JSON object with:
    - title: Memory title/summary
    - content: Detailed memory content (or 'summary' field)
    - type: Memory type category
    - memory_id: Unique identifier
    - source_path: Optional source file path

Usage:
    python -m ta_lab2.tools.data_tools.memory.embed_memories \\
        --memory-file /path/to/memories.jsonl \\
        --chroma-dir /path/to/chroma \\
        --collection-name my_memories

Dependencies:
    - openai: pip install openai
    - chromadb: pip install chromadb
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    from openai import OpenAI
except ImportError:
    raise ImportError(
        "OpenAI library required. Install with: pip install openai"
    )

try:
    import chromadb
except ImportError:
    raise ImportError(
        "ChromaDB library required. Install with: pip install chromadb"
    )

logger = logging.getLogger(__name__)


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """Read a JSONL file line by line.

    Args:
        path: Path to JSONL file

    Yields:
        Parsed JSON objects from each line

    Raises:
        RuntimeError: If JSON parsing fails
    """
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as e:
                raise RuntimeError(f"Invalid JSON on line {i} in {path}: {e}") from e


def get_embedding(texts: List[str], client: OpenAI, model: str) -> List[List[float]]:
    """Generate embeddings for a batch of texts.

    Args:
        texts: List of text strings to embed
        client: OpenAI client instance
        model: Embedding model name (e.g., "text-embedding-3-small")

    Returns:
        List of embedding vectors (list of floats per text), empty list on error
    """
    texts_to_embed = [text.replace("\n", " ") for text in texts]
    try:
        response = client.embeddings.create(input=texts_to_embed, model=model)
        return [embedding.embedding for embedding in response.data]
    except Exception as e:
        logger.error(f"Error calling OpenAI embedding API: {e}")
        # Return a list of empty lists to match the expected structure, so the caller can handle it.
        return [[] for _ in texts]


def main() -> int:
    """CLI entry point for memory embedding."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    log = logging.getLogger()

    ap = argparse.ArgumentParser(
        description="Generate embeddings for memories and store them in a ChromaDB vector store."
    )
    ap.add_argument("--memory-file", required=True, help="Path to the final_memory.jsonl file.")
    ap.add_argument("--chroma-dir", required=True, help="Path to the directory to store ChromaDB files.")
    ap.add_argument("--collection-name", required=True, help="Name for the ChromaDB collection.")
    ap.add_argument("--embedding-model", default="text-embedding-3-small", help="OpenAI model for embeddings.")
    ap.add_argument("--batch-size", type=int, default=50, help="Number of memories to process in one API call.")
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        log.error("Error: The OPENAI_API_KEY environment variable is not set.")
        return 1

    client = OpenAI()
    memory_path = Path(args.memory_file)
    chroma_path = Path(args.chroma_dir)

    if not memory_path.exists():
        log.error(f"Memory file not found: {memory_path}")
        return 1

    # --- Initialize ChromaDB ---
    log.info(f"Initializing ChromaDB client at: {chroma_path}")
    chroma_client = chromadb.PersistentClient(path=str(chroma_path))

    log.info(f"Getting or creating collection: '{args.collection_name}'")
    # Delete collection if it exists to ensure a fresh build
    if args.collection_name in [c.name for c in chroma_client.list_collections()]:
        log.warning(f"Collection '{args.collection_name}' already exists. Deleting it for a fresh build.")
        chroma_client.delete_collection(name=args.collection_name)

    collection = chroma_client.create_collection(name=args.collection_name)

    # --- Load and Process Memories ---
    log.info(f"Loading memories from {memory_path}...")
    memories = list(read_jsonl(memory_path))
    log.info(f"Loaded {len(memories)} memories. Processing in batches of {args.batch_size}.")

    total_start_time = time.time()

    for i in range(0, len(memories), args.batch_size):
        batch_start_time = time.time()
        batch = memories[i:i + args.batch_size]
        log.info(f"Processing batch {i//args.batch_size + 1}/{(len(memories) + args.batch_size - 1)//args.batch_size}...")

        # Prepare data for embedding and storage
        docs_to_embed = [f"Title: {mem.get('title', '')}\nType: {mem.get('type', '')}\nContent: {mem.get('content', '')}" for mem in batch]
        metadatas = [{"source_path": mem.get("source_path", ""), "type": mem.get("type", "")} for mem in batch]
        ids = [mem.get("memory_id", f"unknown-id-{i+j}") for j, mem in enumerate(batch)]

        # Generate embeddings
        embeddings = get_embedding(docs_to_embed, client, model=args.embedding_model)

        valid_embeddings = []
        valid_docs = []
        valid_metadatas = []
        valid_ids = []

        for j, emb in enumerate(embeddings):
            if emb:
                valid_embeddings.append(emb)
                valid_docs.append(docs_to_embed[j])
                valid_metadatas.append(metadatas[j])
                valid_ids.append(ids[j])
            else:
                log.warning(f"Failed to generate embedding for memory ID {ids[j]}. Skipping.")

        # Add to ChromaDB collection
        if valid_ids:
            collection.add(
                embeddings=valid_embeddings,
                documents=valid_docs,
                metadatas=valid_metadatas,
                ids=valid_ids
            )

        batch_end_time = time.time()
        log.info(f"Batch processed in {batch_end_time - batch_start_time:.2f} seconds.")

    total_end_time = time.time()
    log.info(f"✅ Successfully embedded {collection.count()} memories into the '{args.collection_name}' collection.")
    log.info(f"Total processing time: {total_end_time - total_start_time:.2f} seconds.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
