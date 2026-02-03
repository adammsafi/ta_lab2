#!/usr/bin/env python3
"""Complete pipeline: Claude Code conversations → Memories → ChromaDB.

This script orchestrates processing Claude Code conversation history:
1. Convert Claude Code JSONL files to ChatGPT format
2. Generate memories from conversations (via external script)
3. Combine with existing memories
4. Embed into ChromaDB (via external script)

Requires OPENAI_API_KEY environment variable and external scripts for
memory generation and embedding.

Example usage
-------------
Command line:
  OPENAI_API_KEY=key python -m ta_lab2.tools.data_tools.export.process_claude_history \\
    --claude-dir ~/.claude/projects \\
    --output-dir /path/to/output \\
    --generate-memories-script /path/to/generate_memories.py \\
    --embed-memories-script /path/to/embed_memories.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def run_command(cmd: list, description: str) -> bool:
    """Run a command and handle errors."""
    logger.info(f"\nSTEP: {description}")

    try:
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True, env={**os.environ}
        )
        logger.info(result.stdout)
        if result.stderr:
            logger.warning(f"Warnings: {result.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error: {e}")
        logger.error(f"stdout: {e.stdout}")
        logger.error(f"stderr: {e.stderr}")
        return False


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Process Claude Code conversations: convert, extract memories, embed"
    )
    ap.add_argument(
        "--claude-dir", help="Claude projects directory (default: ~/.claude/projects)"
    )
    ap.add_argument("--output-dir", required=True, help="Output directory")
    ap.add_argument(
        "--generate-memories-script", help="Path to generate_memories script"
    )
    ap.add_argument("--embed-memories-script", help="Path to embed_memories script")
    args = ap.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY not set")
        return 1

    claude_dir = (
        Path(args.claude_dir)
        if args.claude_dir
        else (Path.home() / ".claude" / "projects")
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # File paths
    claude_json = output_dir / "claude_code_conversations.json"
    claude_memories = output_dir / "claude_code_memories.jsonl"
    all_memories_original = output_dir / "all_memories_final.jsonl"
    all_memories_combined = output_dir / "all_memories_with_claude.jsonl"
    chroma_dir = output_dir / "chromadb"

    logger.info("=" * 60)
    logger.info("CLAUDE CODE MEMORY EXTRACTION PIPELINE")
    logger.info("=" * 60)

    # Step 1: Convert Claude Code conversations
    logger.info("\n[STEP 1] Converting Claude Code conversations...")
    if not run_command(
        [
            "python",
            "-m",
            "ta_lab2.tools.data_tools.export.convert_claude_code_to_chatgpt_format",
            "--claude-dir",
            str(claude_dir),
            "--output",
            str(claude_json),
        ],
        "Convert Claude Code JSONL -> ChatGPT JSON",
    ):
        logger.error("Conversion failed")
        return 1

    if not claude_json.exists():
        logger.error(f"Output file not created: {claude_json}")
        return 1

    # Load conversation count
    with claude_json.open("r") as f:
        conversations = json.load(f)
    logger.info(f"Converted {len(conversations)} Claude Code conversations")

    # Step 2: Generate memories
    if args.generate_memories_script:
        logger.info("\n[STEP 2] Generating memories...")
        if not run_command(
            [
                "python",
                args.generate_memories_script,
                "--input-file",
                str(claude_json),
                "--output-file",
                str(claude_memories),
                "--batch-size",
                "10",
            ],
            "Extract memories using GPT-4",
        ):
            logger.error("Memory generation failed")
            return 1

        with claude_memories.open("r") as f:
            claude_mem_count = sum(1 for line in f if line.strip())
        logger.info(f"Generated {claude_mem_count} memories from Claude Code")
    else:
        logger.warning("Memory generation script not provided, skipping")
        claude_mem_count = 0

    # Step 3: Combine with existing memories
    logger.info("\n[STEP 3] Combining memories...")

    existing_count = 0
    if all_memories_original.exists():
        with all_memories_original.open("r") as f:
            existing_count = sum(1 for line in f if line.strip())

    # Merge
    with all_memories_combined.open("w", encoding="utf-8") as out:
        if all_memories_original.exists():
            with all_memories_original.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        out.write(line)

        if claude_memories.exists():
            with claude_memories.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        out.write(line)

    total_count = existing_count + claude_mem_count
    logger.info(
        f"Combined {existing_count} existing + {claude_mem_count} Claude = {total_count} total"
    )

    # Step 4: Re-embed
    if args.embed_memories_script:
        logger.info("\n[STEP 4] Re-embedding into ChromaDB...")
        if not run_command(
            [
                "python",
                args.embed_memories_script,
                "--memory-file",
                str(all_memories_combined),
                "--chroma-dir",
                str(chroma_dir),
                "--collection-name",
                "project_memories",
                "--batch-size",
                "50",
            ],
            "Embed memories into ChromaDB",
        ):
            logger.error("Embedding failed")
            return 1
    else:
        logger.warning("Embedding script not provided, skipping")

    logger.info("\n" + "=" * 60)
    logger.info("SUCCESS! PIPELINE COMPLETE!")
    logger.info("=" * 60)
    logger.info(f"Total memories: {total_count}")
    logger.info(f"ChromaDB location: {chroma_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
