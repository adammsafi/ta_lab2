#!/usr/bin/env python3
"""Process new ChatGPT dump: extract new conversations, filter trash, generate memories.

This script orchestrates the workflow for processing a new ChatGPT data export:
1. Load conversation IDs from old and new exports
2. Filter to only new conversations (not in old export, not in trash)
3. Generate memories from filtered conversations (via external script)
4. Combine with existing memory bank
5. Re-embed into ChromaDB (via external script)

This script is a pipeline coordinator - it calls other scripts for actual
memory generation and embedding. You need to have those scripts available
and OPENAI_API_KEY set.

Example usage
-------------
Command line:
  OPENAI_API_KEY=key python -m ta_lab2.tools.data_tools.export.process_new_chatgpt_dump \\
    --new-dump /path/to/new/conversations.json \\
    --old-dump /path/to/old/conversations.json \\
    --trash-list /path/to/trash_list.json \\
    --output-dir /path/to/output

Note: This script has external dependencies on memory generation and embedding
scripts that may need to be migrated separately.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Set, List, Dict, Any

logger = logging.getLogger(__name__)


def load_conversation_ids(conversations_file: Path) -> Set[str]:
    """Load conversation IDs from a conversations.json file."""
    with conversations_file.open("r", encoding="utf-8") as f:
        conversations = json.load(f)

    ids = set()
    for conv in conversations:
        conv_id = conv.get("id")
        if conv_id:
            ids.add(conv_id)

    return ids


def load_trash_list(trash_file: Path) -> Set[str]:
    """Load trash conversation IDs from trash_list.json.

    Extracts conversation IDs from path patterns like "conversation-id/"
    """
    with trash_file.open("r", encoding="utf-8") as f:
        trash_data = json.load(f)

    trash_ids = set()

    # Extract conversation IDs from paths (format: "conversation-id/")
    for path in trash_data.get("paths", []):
        if isinstance(path, str) and "/" in path:
            conv_id = path.split("/")[0]
            # Only add if it looks like a conversation ID (UUID format)
            if "-" in conv_id and len(conv_id) > 20:
                trash_ids.add(conv_id)

    return trash_ids


def filter_new_conversations(
    new_conversations: List[Dict[str, Any]],
    old_ids: Set[str],
    trash_ids: Set[str]
) -> List[Dict[str, Any]]:
    """Filter to only new, non-trash conversations."""
    filtered = []

    for conv in new_conversations:
        conv_id = conv.get("id")

        if not conv_id:
            continue

        # Skip if already processed
        if conv_id in old_ids:
            continue

        # Skip if in trash
        if conv_id in trash_ids:
            continue

        filtered.append(conv)

    return filtered


def process_new_dump(
    new_dump: Path,
    output_dir: Path,
    old_dump: Optional[Path] = None,
    trash_list: Optional[Path] = None,
    generate_memories_script: Optional[Path] = None,
    embed_memories_script: Optional[Path] = None,
) -> Dict[str, Any]:
    """Process new ChatGPT dump.

    Args:
        new_dump: Path to new conversations.json
        output_dir: Output directory for filtered conversations and memories
        old_dump: Optional path to old conversations.json to filter duplicates
        trash_list: Optional path to trash_list.json to filter trash
        generate_memories_script: Path to memory generation script
        embed_memories_script: Path to embedding script

    Returns:
        Dict with processing statistics
    """
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY environment variable not set")

    output_dir.mkdir(parents=True, exist_ok=True)

    new_filtered_file = output_dir / "new_conversations_filtered.json"
    new_memories_file = output_dir / "new_chatgpt_memories.jsonl"
    combined_memories_file = output_dir / "all_memories_with_claude_and_new.jsonl"
    existing_memories_file = output_dir / "all_memories_with_claude.jsonl"
    chroma_dir = output_dir / "chromadb"

    logger.info("="*60)
    logger.info("NEW CHATGPT DUMP PROCESSOR")
    logger.info("="*60)

    # Step 1: Load conversation IDs
    logger.info("\n[STEP 1] Loading conversation IDs...")

    if not new_dump.exists():
        raise FileNotFoundError(f"New conversations file not found: {new_dump}")

    logger.info(f"  Loading new conversations from: {new_dump}")
    with new_dump.open("r", encoding="utf-8") as f:
        new_conversations = json.load(f)
    logger.info(f"  Found {len(new_conversations)} conversations in new dump")

    old_ids = set()
    if old_dump and old_dump.exists():
        logger.info(f"  Loading old conversations from: {old_dump}")
        old_ids = load_conversation_ids(old_dump)
        logger.info(f"  Found {len(old_ids)} conversations in old dump")
    else:
        logger.info("  No old dump provided, will process all conversations")

    trash_ids = set()
    if trash_list and trash_list.exists():
        logger.info(f"  Loading trash list from: {trash_list}")
        trash_ids = load_trash_list(trash_list)
        logger.info(f"  Found {len(trash_ids)} conversations in trash")
    else:
        logger.info("  No trash list provided")

    # Step 2: Filter conversations
    logger.info("\n[STEP 2] Filtering conversations...")
    filtered = filter_new_conversations(new_conversations, old_ids, trash_ids)
    logger.info(f"  New conversations: {len(filtered)}")
    logger.info(f"  Skipped (already processed): {len([c for c in new_conversations if c.get('id') in old_ids])}")
    logger.info(f"  Skipped (trash): {len([c for c in new_conversations if c.get('id') in trash_ids])}")

    if not filtered:
        logger.info("\n  No new conversations to process!")
        return {
            "filtered_count": 0,
            "new_memories": 0,
            "total_memories": 0,
        }

    # Save filtered conversations
    with new_filtered_file.open("w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=2)
    logger.info(f"  Saved filtered conversations to: {new_filtered_file}")

    # Step 3: Generate memories (if script provided)
    new_mem_count = 0
    if generate_memories_script and generate_memories_script.exists():
        logger.info(f"\n[STEP 3] Generating memories from {len(filtered)} new conversations...")

        result = subprocess.run(
            [
                "python", str(generate_memories_script),
                "--input-file", str(new_filtered_file),
                "--output-file", str(new_memories_file),
                "--batch-size", "10",
            ],
            env={**os.environ},
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            logger.error(f"  Error generating memories: {result.stderr}")
            raise RuntimeError("Memory generation failed")

        logger.info(result.stdout)

        # Count new memories
        if new_memories_file.exists():
            with new_memories_file.open("r") as f:
                new_mem_count = sum(1 for line in f if line.strip())

        logger.info(f"  Generated {new_mem_count} new memories")
    else:
        logger.warning("  Memory generation script not provided, skipping...")

    # Step 4: Combine with existing memories
    logger.info("\n[STEP 4] Combining with existing memory bank...")

    existing_count = 0
    if existing_memories_file.exists():
        with existing_memories_file.open("r") as f:
            existing_count = sum(1 for line in f if line.strip())

    with combined_memories_file.open("w", encoding="utf-8") as out:
        # Copy existing
        if existing_memories_file.exists():
            with existing_memories_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        out.write(line)

        # Add new
        if new_memories_file.exists():
            with new_memories_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        out.write(line)

    total_count = existing_count + new_mem_count
    logger.info(f"  Combined {existing_count} existing + {new_mem_count} new = {total_count} total")

    # Step 5: Re-embed (if script provided)
    if embed_memories_script and embed_memories_script.exists():
        logger.info(f"\n[STEP 5] Re-embedding all {total_count} memories into ChromaDB...")

        result = subprocess.run(
            [
                "python", str(embed_memories_script),
                "--memory-file", str(combined_memories_file),
                "--chroma-dir", str(chroma_dir),
                "--collection-name", "project_memories",
                "--batch-size", "50",
            ],
            env={**os.environ},
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            logger.error(f"  Error embedding: {result.stderr}")
            raise RuntimeError("Embedding failed")

        logger.info(result.stdout)
    else:
        logger.warning("  Embedding script not provided, skipping...")

    logger.info("\n" + "="*60)
    logger.info("SUCCESS! NEW DUMP PROCESSED")
    logger.info("="*60)
    logger.info(f"New conversations processed: {len(filtered)}")
    logger.info(f"New memories extracted: {new_mem_count}")
    logger.info(f"Total memories in database: {total_count}")

    return {
        "filtered_count": len(filtered),
        "new_memories": new_mem_count,
        "total_memories": total_count,
        "filtered_file": new_filtered_file,
        "combined_memories": combined_memories_file,
        "chroma_dir": chroma_dir,
    }


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Process new ChatGPT dump: filter, generate memories, re-embed"
    )
    ap.add_argument("--new-dump", required=True, help="Path to new conversations.json")
    ap.add_argument("--output-dir", required=True, help="Output directory")
    ap.add_argument("--old-dump", help="Path to old conversations.json (for filtering)")
    ap.add_argument("--trash-list", help="Path to trash_list.json (for filtering)")
    ap.add_argument("--generate-memories-script", help="Path to generate_memories script")
    ap.add_argument("--embed-memories-script", help="Path to embed_memories script")
    args = ap.parse_args()

    new_dump = Path(args.new_dump)
    output_dir = Path(args.output_dir)
    old_dump = Path(args.old_dump) if args.old_dump else None
    trash_list = Path(args.trash_list) if args.trash_list else None
    generate_script = Path(args.generate_memories_script) if args.generate_memories_script else None
    embed_script = Path(args.embed_memories_script) if args.embed_memories_script else None

    result = process_new_dump(
        new_dump,
        output_dir,
        old_dump=old_dump,
        trash_list=trash_list,
        generate_memories_script=generate_script,
        embed_memories_script=embed_script,
    )

    print(f"\nChromaDB location: {result.get('chroma_dir')}")
    print(f"\nYou can now query using context tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
