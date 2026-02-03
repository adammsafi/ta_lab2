#!/usr/bin/env python3
"""
Simple context retrieval from ChromaDB for LLM prompts.

Usage:
    OPENAI_API_KEY=your-key python get_context.py "your query here"

Returns relevant memories as formatted text to include in LLM prompts.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

try:
    from openai import OpenAI
except ImportError:
    print("Error: pip install openai")
    sys.exit(1)

try:
    import chromadb
except ImportError:
    print("Error: pip install chromadb")
    sys.exit(1)


def get_context(
    query: str,
    chroma_dir: Path,
    collection_name: str = "project_memories",
    top_k: int = 10,
    embedding_model: str = "text-embedding-3-small",
) -> str:
    """
    Retrieve relevant memories and format as context for LLM prompts.

    Returns:
        Formatted string containing relevant memories ready to inject into LLM prompt.
    """

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set")

    client = OpenAI()

    # Connect to ChromaDB
    chroma_client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = chroma_client.get_collection(name=collection_name)

    # Generate query embedding
    response = client.embeddings.create(input=[query], model=embedding_model)
    query_embedding = response.data[0].embedding

    # Search for relevant memories
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )

    # Format as context
    if not results or not results.get('documents'):
        return "No relevant memories found."

    context_parts = ["# Relevant Project Context\n"]

    for i, doc in enumerate(results['documents'][0], 1):
        context_parts.append(f"\n## Memory {i}\n{doc}\n")

    return "\n".join(context_parts)


def get_context_json(
    query: str,
    chroma_dir: Path,
    collection_name: str = "project_memories",
    top_k: int = 10,
    embedding_model: str = "text-embedding-3-small",
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant memories as structured JSON.

    Returns:
        List of memory objects with metadata.
    """

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set")

    client = OpenAI()

    # Connect to ChromaDB
    chroma_client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = chroma_client.get_collection(name=collection_name)

    # Generate query embedding
    response = client.embeddings.create(input=[query], model=embedding_model)
    query_embedding = response.data[0].embedding

    # Search
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=['documents', 'metadatas', 'distances']
    )

    memories = []
    if results and results.get('documents'):
        for i in range(len(results['documents'][0])):
            memories.append({
                'content': results['documents'][0][i],
                'metadata': results.get('metadatas', [[]])[0][i] if results.get('metadatas') else {},
                'distance': results.get('distances', [[]])[0][i] if results.get('distances') else None,
            })

    return memories


def main():
    parser = argparse.ArgumentParser(description="Retrieve context from ChromaDB memory bank")
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--chroma-dir",
        required=True,
        help="ChromaDB directory"
    )
    parser.add_argument("--collection", default="project_memories", help="Collection name")
    parser.add_argument("--top-k", type=int, default=10, help="Number of results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    chroma_dir = Path(args.chroma_dir)

    if args.json:
        # JSON output
        memories = get_context_json(
            args.query,
            chroma_dir,
            collection_name=args.collection,
            top_k=args.top_k
        )
        print(json.dumps(memories, indent=2))
    else:
        # Text output (ready for LLM prompt)
        context = get_context(
            args.query,
            chroma_dir,
            collection_name=args.collection,
            top_k=args.top_k
        )
        print(context)


if __name__ == "__main__":
    main()
