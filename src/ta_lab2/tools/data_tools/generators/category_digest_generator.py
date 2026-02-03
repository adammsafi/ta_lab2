#!/usr/bin/env python3
"""Generate category-based digests from memory collections."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, DefaultDict
from collections import defaultdict

# Reusing the formatting function from review_generator.py for consistency
def format_memory_as_markdown(mem: Dict[str, Any]) -> str:
    """Formats a single memory dictionary into a Markdown string."""
    lines: List[str] = []
    
    title = mem.get("title", "Untitled Memory")
    mem_id = mem.get("memory_id", "N/A")
    reg_key = mem.get("registry_key", "N/A")
    confidence = mem.get("confidence", "N/A")
    conflict_key = mem.get("conflict_key") or "_none_"
    
    parent_summary = mem.get("parent_summary", "").strip() or "_not available_"
    parent_tags = mem.get("parent_tags", [])
    tags_str = ", ".join(f"`{t}`" for t in parent_tags) if parent_tags else "_none_"

    content = (mem.get("content", "") or "").strip()
    source_chunk = (mem.get("source_chunk", "") or "").strip()

    source_path = mem.get("source_path", "N/A")
    reason = mem.get("accepted_reason", "N/A")

    lines.append("---")
    lines.append(f"### {title}")
    lines.append("")
    lines.append(f"- **Memory ID:** `{mem_id}`")
    lines.append(f"- **Registry Key:** `{reg_key}`")
    lines.append(f"- **Confidence:** `{confidence}`")
    lines.append(f"- **Conflict Key:** `{conflict_key}`")
    lines.append(f"- **Parent Summary:** {parent_summary}")
    lines.append(f"- **Parent Tags:** {tags_str}")
    lines.append("")
    
    if content:
        lines.append("**Content:**")
        content_bq = "\n".join([f"> {line}" for line in content.splitlines()])
        lines.append(content_bq)
        lines.append("")

    if source_chunk:
        lines.append("**Source Chunk:**")
        lines.append("```")
        lines.append(source_chunk)
        lines.append("```")
        lines.append("")
    
    lines.append("**Provenance:**")
    lines.append(f"- **Source Path:** `{source_path}`")
    lines.append(f"- **Accepted Reason:** `{reason}`")
    lines.append("")

    return "\n".join(lines)


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """Reads a JSONL file line by line."""
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as e:
                raise RuntimeError(f"Invalid JSON on line {i} in {path}: {e}") from e


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Convert a final_memory.jsonl file into a human-readable Markdown digest, categorized by memory type."
    )
    ap.add_argument(
        "--input", 
        required=True, 
        help="Path to the final_memory.jsonl file."
    )
    ap.add_argument(
        "--output", 
        required=True, 
        help="Path to write the output Markdown file (e.g., categorized_review_digest.md)."
    )
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    if not in_path.exists():
        raise FileNotFoundError(f"Input file not found: {in_path}")

    memories = list(read_jsonl(in_path))
    
    # Group memories by type
    memories_by_type: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for mem in memories:
        mem_type = mem.get("type", "uncategorized")
        memories_by_type[mem_type].append(mem)

    # Sort types alphabetically for consistent output
    sorted_types = sorted(memories_by_type.keys())

    md_blocks: List[str] = []
    
    # Add main header
    md_blocks.append(f"# Memory Digest - Categorized by Type")
    md_blocks.append(f"Generated from: `{in_path.name}`")
    md_blocks.append(f"Total Memories: {len(memories)}")
    md_blocks.append("")

    for mem_type in sorted_types:
        categorized_memories = memories_by_type[mem_type]
        # Sort memories within each type, e.g., by title
        categorized_memories.sort(key=lambda m: m.get("title", ""))

        md_blocks.append(f"## <u>{mem_type.capitalize()}</u> ({len(categorized_memories)} Memories)")
        md_blocks.append("")
        for mem in categorized_memories:
            md_blocks.append(format_memory_as_markdown(mem))
            md_blocks.append("") # Add an extra newline between memories

    full_content = "\n".join(md_blocks)
    
    out_path.write_text(full_content, encoding="utf-8")

    print(f"Successfully generated categorized review digest at: {out_path}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
