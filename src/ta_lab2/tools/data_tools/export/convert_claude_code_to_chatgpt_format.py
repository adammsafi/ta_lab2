#!/usr/bin/env python3
"""Convert Claude Code conversation JSONL files to ChatGPT export format.

This script reads Claude Code conversation history (JSONL format) and converts
it to ChatGPT export format for compatibility with memory generation tools.

Example usage
-------------
Command line:
  python -m ta_lab2.tools.data_tools.export.convert_claude_code_to_chatgpt_format \\
    --claude-dir ~/.claude/projects \\
    --output /path/to/output/claude_conversations.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def extract_message_content(msg: Dict[str, Any]) -> str:
    """Extract text content from Claude message."""
    content = msg.get("content", [])

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                # Extract thinking
                if item.get("type") == "thinking":
                    parts.append(f"[Thinking: {item.get('thinking', '')}]")
                # Extract text
                elif item.get("type") == "text":
                    parts.append(item.get("text", ""))
                # Extract tool use
                elif item.get("type") == "tool_use":
                    parts.append(f"[Tool: {item.get('name')}]")
                # Extract tool result
                elif item.get("type") == "tool_result":
                    content_val = item.get("content", "")
                    if isinstance(content_val, str):
                        parts.append(f"[Result: {content_val[:200]}...]" if len(content_val) > 200 else f"[Result: {content_val}]")
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)

    return ""


def convert_claude_code_conversation(jsonl_path: Path) -> Optional[Dict[str, Any]]:
    """Convert a Claude Code JSONL conversation to ChatGPT format."""
    messages = []
    session_id = jsonl_path.stem

    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            try:
                entry = json.loads(line)

                # Skip file history snapshots
                if entry.get("type") == "file-history-snapshot":
                    continue

                # Process user messages
                if entry.get("type") == "user":
                    msg = entry.get("message", {})
                    content = msg.get("content", "")

                    # Handle tool results
                    if isinstance(content, list):
                        content = extract_message_content({"content": content})
                    elif isinstance(content, dict):
                        content = json.dumps(content)

                    messages.append({
                        "role": "user",
                        "content": content,
                        "timestamp": entry.get("timestamp"),
                    })

                # Process assistant messages
                elif entry.get("type") == "assistant":
                    msg = entry.get("message", {})
                    content = extract_message_content(msg)

                    messages.append({
                        "role": "assistant",
                        "content": content,
                        "timestamp": entry.get("timestamp"),
                    })

            except json.JSONDecodeError as e:
                logger.warning(f"Skipping invalid JSON line in {jsonl_path.name}: {e}")
                continue

    if not messages:
        return None

    # Get first timestamp for conversation ID
    first_ts = messages[0].get("timestamp", datetime.now().isoformat())

    # Create ChatGPT-style conversation
    conversation = {
        "id": session_id,
        "title": f"Claude Code Session {session_id[:8]}",
        "create_time": first_ts,
        "update_time": messages[-1].get("timestamp", first_ts) if messages else first_ts,
        "mapping": {},
    }

    # Build message tree
    parent_id = None
    for i, msg in enumerate(messages):
        msg_id = hashlib.md5(f"{session_id}_{i}".encode()).hexdigest()

        conversation["mapping"][msg_id] = {
            "id": msg_id,
            "message": {
                "id": msg_id,
                "author": {"role": msg["role"]},
                "content": {"content_type": "text", "parts": [msg["content"]]},
                "create_time": msg.get("timestamp"),
            },
            "parent": parent_id,
            "children": [],
        }

        if parent_id:
            conversation["mapping"][parent_id]["children"].append(msg_id)

        parent_id = msg_id

    return conversation


def convert_claude_conversations(
    claude_dir: Path,
    output_file: Path,
) -> int:
    """Convert all Claude Code conversations to ChatGPT format.

    Args:
        claude_dir: Directory containing Claude .jsonl conversation files
        output_file: Output file for converted conversations

    Returns:
        Number of conversations converted
    """
    if not claude_dir.exists():
        raise FileNotFoundError(f"Claude directory not found: {claude_dir}")

    logger.info(f"Scanning for Claude Code conversations in: {claude_dir}")

    # Find all JSONL files
    jsonl_files = list(claude_dir.glob("**/*.jsonl"))
    logger.info(f"Found {len(jsonl_files)} conversation files")

    conversations = []

    for jsonl_path in jsonl_files:
        logger.info(f"Processing: {jsonl_path.name}")

        try:
            conv = convert_claude_code_conversation(jsonl_path)
            if conv:
                conversations.append(conv)
                logger.info(f"  OK Converted ({len(conv['mapping'])} messages)")
            else:
                logger.info("  -- Skipped (empty)")
        except Exception as e:
            logger.error(f"  ERROR: {e}")

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(conversations, indent=2), encoding="utf-8")

    logger.info(f"\nOK Converted {len(conversations)} conversations")
    logger.info(f"OK Output: {output_file}")

    return len(conversations)


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Convert Claude Code conversations to ChatGPT format"
    )
    ap.add_argument(
        "--claude-dir",
        help="Claude projects directory (default: ~/.claude/projects)",
    )
    ap.add_argument(
        "--output",
        required=True,
        help="Output file for converted conversations",
    )
    args = ap.parse_args()

    claude_dir = Path(args.claude_dir) if args.claude_dir else (Path.home() / ".claude" / "projects")
    output_file = Path(args.output)

    count = convert_claude_conversations(claude_dir, output_file)

    print(f"\nNext step: Generate memories from {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
