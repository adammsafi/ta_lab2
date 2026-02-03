#!/usr/bin/env python3
"""Generate review queue triage reports from memory data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, DefaultDict
from collections import defaultdict
import logging
import time

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

def format_review_memory_as_markdown(mem: Dict[str, Any]) -> str:
    """Formats a single memory from the review queue into a Markdown string."""
    lines: List[str] = []
    
    meta = mem.get("_decision_meta", {})
    title = mem.get("title", "Untitled Memory")
    mem_id = mem.get("memory_id", "N/A")
    reg_key = meta.get("registry_key", "N/A")
    review_reason = meta.get("reason", "No reason provided.")

    lines.append("---")
    lines.append(f"### {title}")
    lines.append("")
    lines.append(f"- **Memory ID:** `{mem_id}`")
    lines.append(f"- **Registry Key:** `{reg_key}`")
    lines.append(f"- **Review Reason:** **{review_reason}**")
    lines.append("")
    
    parent_summary = mem.get("parent_summary", "").strip() or "_not available_"
    lines.append(f"**Parent Summary:** {parent_summary}")
    lines.append("")

    content = (mem.get("content", "") or "").strip()
    if content:
        lines.append("**Content:**")
        content_bq = "\n".join([f"> {line}" for line in content.splitlines()])
        lines.append(content_bq)
        lines.append("")

    source_chunk = (mem.get("source_chunk", "") or "").strip()
    if source_chunk:
        lines.append("**Source Chunk:**")
        lines.append("```")
        lines.append(source_chunk)
        lines.append("```")
        lines.append("")
    
    evidence = meta.get("evidence", {}) or {}
    evidence_sample = evidence.get("sample", [])
    if evidence_sample:
        lines.append("**Evidence Found in Code:**")
        lines.append("```")
        for sample_line in evidence_sample:
            lines.append(sample_line)
        lines.append("```")
        lines.append("")
    else:
        lines.append("**Evidence Found in Code:** `None`")
        lines.append("")

    # Actionable override snippet
    override_snippet = {
        "registry_key": reg_key,
        "decision": "accept",
        "note": "Manually reviewed and approved." 
    }
    lines.append("**To accept this memory, add this to `decision_overrides.jsonl`:**")
    lines.append("```json")
    lines.append(json.dumps(override_snippet, indent=2))
    lines.append("```")
    lines.append("")

    return "\n".join(lines)

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    log = logging.getLogger()

    ap = argparse.ArgumentParser(
        description="Generate a triage report for memories in the review queue."
    )
    ap.add_argument("--review-file", required=True, help="Path to the review_queue.jsonl file.")
    ap.add_argument("--output", required=True, help="Path for the output review_triage_report.md file.")
    args = ap.parse_args()

    review_path = Path(args.review_file)
    out_path = Path(args.output)

    if not review_path.exists():
        log.error(f"Review queue file not found: {review_path}")
        return 1

    log.info(f"Loading memories from {review_path}...")
    review_memories = list(read_jsonl(review_path))
    log.info(f"Loaded {len(review_memories)} memories for review.")

    # Group memories by review reason
    memories_by_reason: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for mem in review_memories:
        reason = (mem.get("_decision_meta") or {}).get("reason", "unknown_reason")
        memories_by_reason[reason].append(mem)
    
    log.info(f"Found {len(memories_by_reason)} unique review reasons.")

    # Generate Markdown Content
    md_content: List[str] = [
        f"# Review Triage Report",
        f"Generated from: `{review_path.name}`",
        f"Total Memories for Review: {len(review_memories)}",
    ]

    sorted_reasons = sorted(memories_by_reason.keys())

    for reason in sorted_reasons:
        categorized_memories = memories_by_reason[reason]
        md_content.append(f"\n---\n## Reason: {reason} ({len(categorized_memories)} memories)\n")
        
        for mem in categorized_memories:
            md_content.append(format_review_memory_as_markdown(mem))

    log.info("Writing report to disk...")
    out_path.write_text("\n".join(md_content), encoding="utf-8")
    log.info(f"Successfully generated review triage report at: {out_path}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
