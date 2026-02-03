#!/usr/bin/env python3
"""Generate code/project review digests from memory JSONL files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

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
        # Use a blockquote for the extracted content
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


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Convert a final_memory.jsonl file into a human-readable Markdown digest."
    )
    ap.add_argument(
        "--input", 
        required=True, 
        help="Path to the final_memory.jsonl file."
    )
    ap.add_argument(
        "--output", 
        required=True, 
        help="Path to write the output Markdown file (e.g., review_digest.md)."
    )
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    if not in_path.exists():
        raise FileNotFoundError(f"Input file not found: {in_path}")

    memories = list(read_jsonl(in_path))
    
    # Sort memories, for example by source path and then memory ID
    memories.sort(key=lambda m: (m.get("source_path", ""), m.get("memory_id", "")))

    md_blocks: List[str] = []
    for mem in memories:
        md_blocks.append(format_memory_as_markdown(mem))
        
    # Write header
    header = [
        f"# Memory Review Digest",
        f"Generated from: `{in_path.name}`",
        f"Total Memories: {len(memories)}",
        "",
    ]
    
    full_content = "\n".join(header + md_blocks)
    
    out_path.write_text(full_content, encoding="utf-8")

    print(f"Successfully generated review digest at: {out_path}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
