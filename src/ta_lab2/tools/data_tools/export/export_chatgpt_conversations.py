# -*- coding: utf-8 -*-
"""Export ChatGPT conversations to Markdown and CSV.

This module converts a ChatGPT data export (conversations.json) into:
  1) One Markdown transcript per conversation (out/chats/*.md)
  2) A CSV index file (out/index.csv) that includes a "likely_noise" flag

This is useful when you want to bulk-review and bulk-summarize conversations without
opening each chat in the UI. You can filter the index.csv (e.g., likely_noise == False)
to decide which chats are worth summarizing.

What this script does
---------------------
- Reads the ChatGPT export file: conversations.json
- For each conversation:
    - Extracts all user/assistant messages in chronological order
    - Writes a transcript Markdown file to: <out>/chats/<safe_title>__<conversation_id>.md
    - Adds a row to <out>/index.csv with metadata:
        title, conversation_id, created_utc, updated_utc, n_msgs, likely_noise, md_path
- Skips conversations with fewer than --min-msgs user/assistant messages.

Notes about ChatGPT export variability
--------------------------------------
ChatGPT exports can differ across time. Message content can appear as:
- content_type="text" with parts=["..."]
- content_type="multimodal_text" with parts including strings or dicts with {"text": "..."}
This script uses a defensive extractor to handle common variations.

Example run commands
--------------------

Command line:
  python -m ta_lab2.tools.data_tools.export.export_chatgpt_conversations \\
    --in /path/to/conversations.json \\
    --out /path/to/output \\
    --min-msgs 6

Output
------
- <out>/index.csv
- <out>/chats/*.md

Filtering strategy
------------------
The index.csv contains "likely_noise" which uses simple heuristics:
- If n_msgs < 8 -> likely noise
- If title contains certain keywords (fix/error/import/npm/runfile/new chat/export/link/apply patch) -> likely noise

These heuristics are intentionally conservative. Treat "likely_noise" as a starting point,
then do your final KEEP/NO KEEP pass in Excel.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Filename helpers
# -----------------------------------------------------------------------------
def _safe_filename(s: str, max_len: int = 120) -> str:
    """Convert an arbitrary string into a filename-safe slug.

    - Strips leading/trailing whitespace
    - Removes weird punctuation
    - Replaces whitespace runs with underscores
    - Truncates to max_len

    This keeps filenames stable and avoids Windows path issues.
    """
    s = s.strip() or "untitled"
    s = re.sub(r"[^\w\s\-.]", "", s)  # keep word chars, whitespace, dash/dot
    s = re.sub(r"\s+", "_", s)  # whitespace -> underscore
    return s[:max_len].rstrip("_") or "untitled"


def _ts_to_iso(ts: Optional[float]) -> str:
    """Convert a Unix timestamp (seconds) to ISO-8601 UTC string.

    Returns "" for missing/falsey ts.
    """
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


# -----------------------------------------------------------------------------
# ChatGPT export parsing helpers
# -----------------------------------------------------------------------------
def _extract_text_from_message(msg: Dict[str, Any]) -> str:
    """Extract text from a message dict in the ChatGPT export.

    The export format can vary; commonly:
      content = {"content_type": "text", "parts": ["..."]}
    but sometimes:
      content = {"content_type": "multimodal_text", "parts": ["...", {"text":"..."}]}

    This function tries to recover text robustly, returning "" if no text is present.
    """
    content = (msg or {}).get("content") or {}
    ctype = content.get("content_type")

    # Most common: {"content_type": "text", "parts": ["..."]}
    if ctype == "text":
        parts = content.get("parts") or []
        parts = [p for p in parts if isinstance(p, str)]
        return "\n".join(parts).strip()

    # Some exports: {"content_type": "multimodal_text", "parts":[...]}
    parts = content.get("parts")
    if isinstance(parts, list):
        out: List[str] = []
        for p in parts:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict):
                # sometimes a dict with "text"
                t = p.get("text")
                if isinstance(t, str):
                    out.append(t)
        return "\n".join(out).strip()

    # Fallback: sometimes stored as a string
    if isinstance(content, str):
        return content.strip()

    return ""


def _walk_mapping(conv: Dict[str, Any]) -> List[Tuple[float, str, str]]:
    """Walk a conversation "mapping" and return chronological message tuples.

    Returns:
        List of (create_time, role, text) tuples
        - create_time is float seconds since epoch
        - role is typically "user" or "assistant" (sometimes "system"/"tool")
        - text is the extracted message string
    """
    mapping = conv.get("mapping") or {}
    rows: List[Tuple[float, str, str]] = []

    for _node_id, node in mapping.items():
        msg = (node or {}).get("message")
        if not msg:
            continue

        role = (((msg.get("author") or {}).get("role")) or "").strip()
        create_time = msg.get("create_time") or 0.0
        text = _extract_text_from_message(msg)

        # Skip empty assistant/tool artifacts, but keep empty user messages out too
        if not text.strip():
            continue

        rows.append((float(create_time), role, text))

    # Ensure chronological order
    rows.sort(key=lambda x: x[0])
    return rows


# -----------------------------------------------------------------------------
# Noise heuristic (used in index.csv)
# -----------------------------------------------------------------------------
def likely_noise(row: Dict[str, Any]) -> bool:
    """Heuristic classifier for index rows.

    Returns True if the conversation is likely "noise" (debugging, short, meta),
    based on:
      - n_msgs < 8
      - title contains certain keywords

    Treat this as a starting point for triage, not a truth oracle.
    """
    title = (row.get("title") or "").lower()
    n_msgs = int(row.get("n_msgs") or 0)

    if n_msgs < 8:
        return True

    keywords = [
        "fix",
        "error",
        "import",
        "npm",
        "runfile",
        "new chat",
        "export",
        "link",
        "apply patch",
    ]
    return any(k in title for k in keywords)


def export_conversations(
    in_path: Path,
    out_dir: Path,
    min_msgs: int = 4,
) -> Dict[str, Any]:
    """Export ChatGPT conversations.json to Markdown transcripts and CSV index.

    Args:
        in_path: Path to conversations.json
        out_dir: Output directory for chats/ and index.csv
        min_msgs: Minimum messages to include conversation

    Returns:
        Dict with keys: chats_written, csv_path, chats_dir
    """
    chats_dir = out_dir / "chats"

    # Create output folders
    out_dir.mkdir(parents=True, exist_ok=True)
    chats_dir.mkdir(parents=True, exist_ok=True)

    # Read conversations.json (top-level list of conversations)
    logger.info(f"Reading conversations from {in_path}")
    data = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Expected conversations.json top-level list")

    index_rows: List[Dict[str, Any]] = []

    for conv in data:
        # Conversation-level metadata
        title = (conv.get("title") or "").strip()
        cid = conv.get("id") or ""
        create_time = conv.get("create_time")
        update_time = conv.get("update_time")

        # Extract all messages from mapping, then keep only user/assistant text
        msgs = _walk_mapping(conv)
        meaningful = [
            (t, r, x) for (t, r, x) in msgs if r in {"user", "assistant"} and x.strip()
        ]

        # Skip tiny chats (often junk or accidental)
        if len(meaningful) < min_msgs:
            continue

        created_iso = _ts_to_iso(create_time)
        updated_iso = _ts_to_iso(update_time)

        # Build a stable markdown filename
        safe = _safe_filename(title or "untitled")
        md_path = chats_dir / f"{safe}__{cid}.md"

        # Write Markdown transcript
        lines: List[str] = []
        lines.append(f"# {title or 'Untitled'}")
        lines.append("")
        lines.append(f"- conversation_id: `{cid}`")
        lines.append(f"- created_utc: `{created_iso}`")
        lines.append(f"- updated_utc: `{updated_iso}`")
        lines.append(f"- message_count_user_assistant: `{len(meaningful)}`")
        lines.append("")
        lines.append("---")
        lines.append("")

        for t, role, text in meaningful:
            ts_iso = _ts_to_iso(t)
            role_label = "USER" if role == "user" else "ASSISTANT"
            lines.append(f"## {role_label} ({ts_iso})")
            lines.append("")
            lines.append(text.strip())
            lines.append("")

        md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

        # Index row (for Excel filtering)
        row: Dict[str, Any] = {
            "title": title or "Untitled",
            "conversation_id": cid,
            "created_utc": created_iso,
            "updated_utc": updated_iso,
            "n_msgs": len(meaningful),
            "md_path": str(md_path.as_posix()),
        }
        row["likely_noise"] = likely_noise(row)

        index_rows.append(row)

    # Sort index by created date (ISO strings sort lexicographically)
    index_rows.sort(key=lambda r: r.get("created_utc") or "")

    # Write CSV index
    csv_path = out_dir / "index.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "title",
                "conversation_id",
                "created_utc",
                "updated_utc",
                "n_msgs",
                "likely_noise",
                "md_path",
            ],
        )
        w.writeheader()
        for r in index_rows:
            w.writerow(r)

    logger.info(f"Wrote {len(index_rows)} chats to {chats_dir}")
    logger.info(f"Index: {csv_path}")

    return {
        "chats_written": len(index_rows),
        "csv_path": csv_path,
        "chats_dir": chats_dir,
    }


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Convert ChatGPT conversations.json to per-chat Markdown + index CSV (with likely_noise flag)."
    )
    ap.add_argument(
        "--in", dest="in_path", required=True, help="Path to conversations.json"
    )
    ap.add_argument(
        "--out", dest="out_dir", default="out_chatgpt", help="Output folder"
    )
    ap.add_argument(
        "--min-msgs",
        type=int,
        default=4,
        help="Skip conversations with fewer than this many (user+assistant) messages",
    )
    args = ap.parse_args()

    in_path = Path(args.in_path)
    out_dir = Path(args.out_dir)

    result = export_conversations(in_path, out_dir, args.min_msgs)

    print(f"Wrote {result['chats_written']} chats")
    print(f"Index: {result['csv_path']}")
    print(f"Chats: {result['chats_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
