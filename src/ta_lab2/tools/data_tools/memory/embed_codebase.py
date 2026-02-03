#!/usr/bin/env python3
"""Embed codebase into ChromaDB vector store using OpenAI embeddings.

AST-based code chunking extracts functions and classes from Python files,
generates embeddings using OpenAI's API, and stores them in ChromaDB for
semantic code search.

Usage:
    python -m ta_lab2.tools.data_tools.memory.embed_codebase \\
        --repo-dir /path/to/repo \\
        --chroma-dir /path/to/chroma \\
        --collection-name my_codebase

Dependencies:
    - openai: pip install openai
    - chromadb: pip install chromadb
"""
from __future__ import annotations

import argparse
import ast
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("OpenAI library required. Install with: pip install openai")

try:
    import chromadb
except ImportError:
    raise ImportError("ChromaDB library required. Install with: pip install chromadb")

logger = logging.getLogger(__name__)


# --- AST-based Code Chunking ---


def get_code_chunks(file_path: Path) -> List[Dict[str, Any]]:
    """Parse a Python file and extract functions and classes as chunks.

    Args:
        file_path: Path to Python source file

    Returns:
        List of chunk dicts with file_path, start_line, end_line, name, type, content
    """
    chunks = []
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                chunk_source = ast.get_source_segment(source, node)
                if chunk_source:
                    chunks.append(
                        {
                            "file_path": str(file_path),
                            "start_line": node.lineno,
                            "end_line": node.end_lineno,
                            "name": node.name,
                            "type": type(node).__name__,
                            "content": chunk_source,
                        }
                    )
    except Exception as e:
        logger.warning(f"Could not parse AST for file {file_path}: {e}")
    return chunks


# --- OpenAI Embedding ---


def get_embedding(texts: List[str], client: OpenAI, model: str) -> List[List[float]]:
    """Generate embeddings for a batch of texts.

    Args:
        texts: List of text strings to embed
        client: OpenAI client instance
        model: Embedding model name (e.g., "text-embedding-3-small")

    Returns:
        List of embedding vectors (list of floats per text)
    """
    texts_to_embed = [text.replace("\n", " ") for text in texts]
    try:
        response = client.embeddings.create(input=texts_to_embed, model=model)
        return [embedding.embedding for embedding in response.data]
    except Exception as e:
        logger.error(f"Error calling OpenAI embedding API: {e}")
        return [[] for _ in texts]


# --- Main Execution ---


def main() -> int:
    """CLI entry point for codebase embedding."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger()

    ap = argparse.ArgumentParser(
        description="Generate embeddings for a codebase and store them in a ChromaDB vector store."
    )
    ap.add_argument(
        "--repo-dir", required=True, help="Path to the root of the code repository."
    )
    ap.add_argument(
        "--chroma-dir",
        required=True,
        help="Path to the directory to store ChromaDB files.",
    )
    ap.add_argument(
        "--collection-name",
        required=True,
        help="Name for the ChromaDB collection for the code.",
    )
    ap.add_argument(
        "--embedding-model",
        default="text-embedding-3-small",
        help="OpenAI model for embeddings.",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of code chunks to process in one API call.",
    )
    ap.add_argument(
        "--exclude-dirs",
        type=str,
        default=".venv,env,build,dist,archive,old,backup,tmp,temp",
        help="Comma-separated list of directory names to exclude (e.g., '.venv,node_modules,build').",
    )
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        log.error("Error: The OPENAI_API_KEY environment variable is not set.")
        return 1

    client = OpenAI()
    repo_path = Path(args.repo_dir)
    chroma_path = Path(args.chroma_dir)

    if not repo_path.is_dir():
        log.error(f"Repository directory not found: {repo_path}")
        return 1

    # --- 1. Find and Filter Python Files ---
    exclude_list = [d.strip() for d in args.exclude_dirs.split(",") if d.strip()]
    log.info(f"Excluding directories containing these names: {exclude_list}")
    log.info(f"Scanning for Python files in {repo_path}...")

    all_py_files = list(repo_path.rglob("*.py"))
    filtered_files = []
    excluded_files = []

    for file_path in all_py_files:
        try:
            relative_path_parts = file_path.relative_to(repo_path).parts
            if any(
                excluded_dir in relative_path_parts for excluded_dir in exclude_list
            ):
                excluded_files.append(file_path)
            else:
                filtered_files.append(file_path)
        except ValueError:
            filtered_files.append(file_path)

    log.info("--- FILTERING SUMMARY ---")
    log.info(f"Total files found: {len(all_py_files)}")
    log.info(f"Files excluded: {len(excluded_files)}")
    log.info(f"Files to be processed: {len(filtered_files)}")

    if excluded_files:
        log.info("First 10 EXCLUDED files:")
        for p in excluded_files[:10]:
            log.info(f"  - {p}")

    if filtered_files:
        log.info("First 10 INCLUDED files:")
        for p in filtered_files[:10]:
            log.info(f"  - {p}")
    log.info("-------------------------")

    if not filtered_files:
        log.warning("No Python files to process after applying exclusions. Exiting.")
        return 0

    # --- 2. Extract Code Chunks ---
    log.info("Extracting functions and classes from filtered files...")
    all_chunks = []
    for file_path in filtered_files:
        all_chunks.extend(get_code_chunks(file_path))

    log.info(f"Extracted {len(all_chunks)} total code chunks.")
    if not all_chunks:
        log.warning("No code chunks were extracted. Exiting.")
        return 0

    # --- 3. Initialize ChromaDB ---
    log.info(f"Initializing ChromaDB client at: {chroma_path}")
    chroma_client = chromadb.PersistentClient(path=str(chroma_path))

    log.info(f"Getting or creating collection: '{args.collection_name}'")
    if args.collection_name in [c.name for c in chroma_client.list_collections()]:
        log.warning(
            f"Collection '{args.collection_name}' already exists. Deleting it for a fresh build."
        )
        chroma_client.delete_collection(name=args.collection_name)

    collection = chroma_client.create_collection(name=args.collection_name)

    # --- 4. Batch process and store embeddings ---
    log.info(f"Processing {len(all_chunks)} chunks in batches of {args.batch_size}.")
    total_start_time = time.time()

    for i in range(0, len(all_chunks), args.batch_size):
        batch_start_time = time.time()
        batch = all_chunks[i : i + args.batch_size]
        log.info(
            f"Processing batch {i//args.batch_size + 1}/{(len(all_chunks) + args.batch_size - 1)//args.batch_size}..."
        )

        docs_to_embed = [chunk["content"] for chunk in batch]
        metadatas = [
            {
                "file_path": chunk["file_path"],
                "start_line": chunk["start_line"],
                "name": chunk["name"],
            }
            for chunk in batch
        ]
        ids = [
            f"{chunk['file_path']}::{chunk['name']}::{chunk['start_line']}"
            for chunk in batch
        ]

        embeddings = get_embedding(docs_to_embed, client, model=args.embedding_model)

        valid_embeddings, valid_docs, valid_metadatas, valid_ids = [], [], [], []
        for j, emb in enumerate(embeddings):
            if emb:
                valid_embeddings.append(emb)
                valid_docs.append(docs_to_embed[j])
                valid_metadatas.append(metadatas[j])
                valid_ids.append(ids[j])
            else:
                log.warning(f"Failed to generate embedding for ID {ids[j]}. Skipping.")

        if valid_ids:
            collection.add(
                embeddings=valid_embeddings,
                documents=valid_docs,
                metadatas=valid_metadatas,
                ids=valid_ids,
            )

        batch_end_time = time.time()
        log.info(f"Batch processed in {batch_end_time - batch_start_time:.2f} seconds.")

    total_end_time = time.time()
    log.info(
        f"✅ Successfully embedded {collection.count()} code chunks into the '{args.collection_name}' collection."
    )
    log.info(f"Total processing time: {total_end_time - total_start_time:.2f} seconds.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
