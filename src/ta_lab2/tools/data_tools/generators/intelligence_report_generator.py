#!/usr/bin/env python3
"""Generate intelligence reports with indexing from memory JSONL."""
from __future__ import annotations

import argparse
import json
import re
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, DefaultDict
from collections import defaultdict

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

def format_memory_as_markdown(mem: Dict[str, Any], is_full_report: bool = False) -> str:
    """Formats a single memory dictionary into a Markdown string."""
    lines: List[str] = []
    
    title = mem.get("title", "Untitled Memory")
    mem_id = mem.get("memory_id", "N/A")
    mem_type = mem.get("type", "uncategorized").capitalize()
    
    if is_full_report:
        lines.append("---")
        # Add an anchor for direct linking
        lines.append(f"#### <a name=\"{mem_id}\"></a>{mem_type}: {title}")
    else:
        lines.append(f"### {title}")

    lines.append("")
    lines.append(f"- **Memory ID:** `{mem_id}`")
    lines.append(f"- **Confidence:** `{mem.get('confidence', 'N/A')}`")
    lines.append(f"- **Conflict Key:** `{mem.get('conflict_key') or '_none_'}`")
    lines.append(f"- **Parent Summary:** {mem.get('parent_summary', '').strip() or '_not available_'}")
    
    parent_tags = mem.get("parent_tags", [])
    tags_str = ", ".join(f'`{t}`' for t in parent_tags) if parent_tags else "_none_"
    lines.append(f"- **Parent Tags:** {tags_str}")
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
    
    evidence = mem.get("evidence", {}) or {}
    evidence_sample = evidence.get("sample", [])
    if evidence_sample:
        lines.append("**Evidence in Code:**")
        lines.append("```")
        for sample_line in evidence_sample:
            lines.append(sample_line)
        lines.append("```")
        lines.append("")

    lines.append("**Provenance:**")
    lines.append(f"- **Source Path:** `{mem.get('source_path', 'N/A')}`")
    lines.append(f"- **Accepted Reason:** `{mem.get('accepted_reason', 'N/A')}`")
    lines.append("")

    return "\n".join(lines)


def sanitize_anchor_link(text: str) -> str:
    """Sanitizes a string to be used in a Markdown anchor link."""
    # Replace slashes and backslashes with underscores
    text = text.replace("/", "_").replace("\\", "_")
    # Keep only alphanumeric, underscores, and hyphens
    return re.sub(r'[^a-zA-Z0-9_-]', '', text)


def main() -> int:
    # --- Setup Logging ---
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger()

    start_time = time.time()
    log.info("Starting report generation...")
    
    ap = argparse.ArgumentParser(
        description="Generate a comprehensive Project Intelligence Report from final_memory.jsonl."
    )
    ap.add_argument("--input", required=True, help="Path to the final_memory.jsonl file.")
    ap.add_argument("--output", required=True, help="Path for the output Markdown report.")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    log.info(f"Input file: {in_path}")
    log.info(f"Output file: {out_path}")

    if not in_path.exists():
        log.error(f"Input file not found: {in_path}")
        return 1

    # --- 1. Reading Input File ---
    t1 = time.time()
    log.info("Reading input file...")
    try:
        memories = list(read_jsonl(in_path))
    except Exception as e:
        log.error(f"Failed to read or parse JSONL file: {e}")
        return 1
    t2 = time.time()
    log.info(f"Finished reading {len(memories)} memories in {t2 - t1:.2f} seconds.")

    # --- 2. Building Indexes ---
    t1 = time.time()
    log.info("Building indexes...")
    memories_by_topic: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    memories_by_file: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)

    for mem in memories:
        # Group by topic (conflict_key)
        topic = mem.get("conflict_key") or "uncategorized"
        memories_by_topic[topic].append(mem)

        # Group by file evidence
        evidence_sample = (mem.get("evidence") or {}).get("sample", [])
        referenced_files = set()
        for evidence_line in evidence_sample:
            parts = evidence_line.split(':', 2)
            if len(parts) > 1:
                file_path = parts[0].replace("\\", "/")
                referenced_files.add(file_path)
        
        for file_path in referenced_files:
            memories_by_file[file_path].append(mem)
    t2 = time.time()
    log.info(f"Finished building indexes in {t2 - t1:.2f} seconds.")

    # --- 3. Generating Markdown Content ---
    t1 = time.time()
    log.info("Generating Markdown content...")
    md_content: List[str] = [
        f"# Project Intelligence Report",
        f"Generated from: `{in_path.name}` on {datetime.now().isoformat()}",
        f"Total Memories: {len(memories)}",
    ]

    # Index by Topic
    md_content.append("\n---\n## 1. Index by Topic (Conflict Key)\n")
    sorted_topics = sorted(memories_by_topic.keys())
    for topic in sorted_topics:
        anchor = sanitize_anchor_link(f"topic-{topic}")
        count = len(memories_by_topic[topic])
        md_content.append(f"- [`{topic}`](#{anchor}) ({count} memories)")

    # Index by File
    md_content.append("\n---\n## 2. Index by File Evidence\n")
    sorted_files = sorted(memories_by_file.keys())
    for file_path in sorted_files:
        anchor = sanitize_anchor_link(f"file-{file_path}")
        md_content.append(f"### <a name=\"{anchor}\"></a>`{file_path}`")
        mem_ids = [f"[`{m.get('memory_id')}`](#{m.get('memory_id')})" for m in memories_by_file[file_path]]
        md_content.append(f"Referenced by: {', '.join(mem_ids)}\n")

    # Full Memory Details by Topic
    md_content.append("\n---\n## 3. Full Memory Details (Grouped by Topic)\n")
    for topic in sorted_topics:
        anchor = sanitize_anchor_link(f"topic-{topic}")
        md_content.append(f"### <a name=\"{anchor}\"></a>Topic: `{topic}`\n")
        
        topic_memories = sorted(memories_by_topic[topic], key=lambda m: m.get('memory_id'))
        
        for mem in topic_memories:
            md_content.append(format_memory_as_markdown(mem, is_full_report=True))
    t2 = time.time()
    log.info(f"Finished generating Markdown content in {t2 - t1:.2f} seconds.")

    # --- 4. Writing Output File ---
    t1 = time.time()
    log.info("Writing to output file...")
    try:
        out_path.write_text("\n".join(md_content), encoding="utf-8")
    except Exception as e:
        log.error(f"Failed to write to output file: {e}")
        return 1
    t2 = time.time()
    log.info(f"Finished writing output file in {t2 - t1:.2f} seconds.")

    total_time = time.time() - start_time
    log.info(f"Successfully generated Project Intelligence Report at: {out_path}")
    log.info(f"Total execution time: {total_time:.2f} seconds.")
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main())