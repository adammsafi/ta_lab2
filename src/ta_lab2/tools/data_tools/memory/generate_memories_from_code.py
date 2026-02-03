#!/usr/bin/env python3
"""Generate memory records from source code using OpenAI LLM.

Uses AST parsing to extract functions and classes from Python code, then
generates structured memory records describing each code chunk using
OpenAI's chat API. Output is JSONL format suitable for embedding.

Output format:
    Each line is a JSON object with:
    - title: Short descriptive summary
    - content: Detailed explanation of purpose and behavior
    - source_path: Original file path
    - source_chunk_name: Function/class name
    - source_chunk_start_line: Starting line number
    - source_chunk_end_line: Ending line number
    - source_chunk_content: Full source code

Usage:
    python -m ta_lab2.tools.data_tools.memory.generate_memories_from_code \\
        --repo-dir /path/to/repo \\
        --out-file memories.jsonl \\
        --chat-model gpt-4o

Dependencies:
    - openai: pip install openai
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    from openai import OpenAI
except ImportError:
    raise ImportError(
        "OpenAI library required. Install with: pip install openai"
    )

logger = logging.getLogger(__name__)


# --- AST-based Code Chunking (from embed_codebase.py) ---

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
                    chunks.append({
                        "file_path": str(file_path),
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                        "name": node.name,
                        "type": type(node).__name__,
                        "content": chunk_source,
                    })
    except Exception as e:
        logger.warning(f"Could not parse AST for file {file_path}: {e}")
    return chunks


# --- Memory Generation ---

def generate_memory_for_chunk(chunk: Dict[str, Any], client: OpenAI, model: str) -> Dict[str, Any] | None:
    """Generate a memory for a single code chunk using OpenAI's Chat Completions API.

    Args:
        chunk: Code chunk dict with file_path, name, content
        client: OpenAI client instance
        model: Chat model name (e.g., "gpt-4o")

    Returns:
        Memory dict with title, content, source metadata, or None on error
    """
    system_prompt = """
You are an expert programmer tasked with creating concise, high-quality memories about code.
Analyze the provided code chunk and generate a memory in the following JSON format.
The `title` should be a short, descriptive summary.
The `content` should be a more detailed explanation of what the code does, its purpose, and any important context.
Do not wrap the JSON in markdown code blocks.

Example:
{
  "title": "Function to calculate Exponential Moving Average (EMA) using pandas",
  "content": "This function, `compute_daily_ema`, calculates the Exponential Moving Average (EMA) for a given pandas Series of prices. It takes the price series and a `horizon_days` integer as input. It calculates the EMA alpha using the formula alpha = 2 / (horizon_days + 1) and then uses the `.ewm()` method from pandas to compute the mean. This is a standard and efficient way to calculate EMA on daily price data."
}
"""

    user_prompt = f"""
Here is the code chunk to analyze:
File: {chunk['file_path']}
Function/Class Name: {chunk['name']}
```python
{chunk['content']}
```
Please generate a memory for this code chunk in the specified JSON format.
"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        json_content = response.choices[0].message.content
        if not json_content:
            return None

        memory_data = json.loads(json_content)

        # Combine with source data
        memory_data['source_path'] = chunk['file_path']
        memory_data['source_chunk_name'] = chunk['name']
        memory_data['source_chunk_start_line'] = chunk['start_line']
        memory_data['source_chunk_end_line'] = chunk['end_line']
        memory_data['source_chunk_content'] = chunk['content']

        return memory_data

    except Exception as e:
        logger.error(f"Failed to generate or parse memory for chunk {chunk['name']} in {chunk['file_path']}: {e}")
        return None


# --- Main Execution ---

def main() -> int:
    """CLI entry point for memory generation from code."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    log = logging.getLogger()

    ap = argparse.ArgumentParser(
        description="Generate memories from the source code of a project."
    )
    ap.add_argument("--repo-dir", required=True, help="Path to the root of the code repository.")
    ap.add_argument("--out-file", required=True, help="Path to the output JSONL file for generated memories.")
    ap.add_argument("--chat-model", default="gpt-4o", help="OpenAI model for memory generation.")
    ap.add_argument(
        "--exclude-dirs",
        type=str,
        default=".venv,env,build,dist,archive,old,backup,tmp,temp",
        help="Comma-separated list of directory names to exclude."
    )
    args = ap.parse_args()

    if "OPENAI_API_KEY" not in os.environ:
        log.error("Error: The OPENAI_API_KEY environment variable is not set.")
        return 1

    client = OpenAI()
    repo_path = Path(args.repo_dir)
    out_file_path = Path(args.out_file)

    if not repo_path.is_dir():
        log.error(f"Repository directory not found: {repo_path}")
        return 1

    # --- 1. Find and Filter Python Files ---
    exclude_list = [d.strip() for d in args.exclude_dirs.split(',') if d.strip()]
    log.info(f"Excluding directories containing these names: {exclude_list}")
    log.info(f"Scanning for Python files in {repo_path}...")

    all_py_files = list(repo_path.rglob("*.py"))
    filtered_files = []
    for file_path in all_py_files:
        try:
            relative_path_parts = file_path.relative_to(repo_path).parts
            if not any(excluded_dir in relative_path_parts for excluded_dir in exclude_list):
                filtered_files.append(file_path)
        except ValueError:
            filtered_files.append(file_path)

    log.info(f"Found {len(all_py_files)} total Python files, processing {len(filtered_files)} after exclusions.")

    if not filtered_files:
        log.warning("No Python files found after applying exclusions. Exiting.")
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

    # --- 3. Generate Memories ---
    log.info(f"Generating memories for {len(all_chunks)} code chunks using model '{args.chat_model}'...")

    # Ensure output directory exists
    out_file_path.parent.mkdir(parents=True, exist_ok=True)

    generated_count = 0
    with out_file_path.open("w", encoding="utf-8") as f:
        for i, chunk in enumerate(all_chunks, 1):
            log.info(f"Processing chunk {i}/{len(all_chunks)}: '{chunk['name']}' in {chunk['file_path']}")

            memory = generate_memory_for_chunk(chunk, client, args.chat_model)

            if memory:
                f.write(json.dumps(memory, ensure_ascii=False) + "\n")
                generated_count += 1

    log.info(f"✅ Generation complete. Wrote {generated_count} memories to {out_file_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
