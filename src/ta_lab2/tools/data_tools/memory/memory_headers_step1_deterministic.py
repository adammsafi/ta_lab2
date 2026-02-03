from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -----------------------------
# Front-matter helpers (no PyYAML dependency)
# -----------------------------

FM_START = "---\n"
FM_END = "\n---\n"

def has_front_matter(text: str) -> bool:
    t = text.lstrip("\ufeff\r\n\t ")
    return t.startswith(FM_START) and (FM_END in t[len(FM_START):])

def split_front_matter(text: str) -> Tuple[Optional[str], str]:
    """
    Returns (front_matter_yaml, rest_of_doc). front_matter_yaml excludes the --- fences.
    If no front-matter, returns (None, original_text).
    """
    if not has_front_matter(text):
        return None, text
    end_idx = text.find(FM_END, len(FM_START))
    fm = text[len(FM_START):end_idx]
    rest = text[end_idx + len(FM_END):]
    return fm, rest

def yaml_escape(s: str) -> str:
    # Minimal escaping; quote if special chars or leading/trailing spaces
    if s is None:
        return '""'
    needs_quotes = (
        s == "" or
        s.strip() != s or
        any(ch in s for ch in [":", "#", "{", "}", "[", "]", "\n", "\r", "\t", "\""])
    )
    if not needs_quotes:
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

def yaml_dump_simple(d: Dict[str, Any]) -> str:
    """
    Deterministic YAML emitter for a restricted schema:
    - scalars: str/int/bool/None
    - lists of strings
    """
    lines: List[str] = []
    for k, v in d.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            if not v:
                lines.append("  []")
            else:
                # If list is empty, we keep on same line. Otherwise emit '-'
                if v == []:
                    lines.append("  []")
                else:
                    for item in v:
                        lines.append(f"  - {yaml_escape(str(item))}")
        else:
            if v is None:
                lines.append(f"{k}: null")
            elif isinstance(v, bool):
                lines.append(f"{k}: {'true' if v else 'false'}")
            elif isinstance(v, int):
                lines.append(f"{k}: {v}")
            else:
                lines.append(f"{k}: {yaml_escape(str(v))}")
    return "\n".join(lines) + "\n"

# -----------------------------
# CSV loading
# -----------------------------

def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]

def pick(row: Dict[str, str], key: str) -> Optional[str]:
    v = row.get(key)
    if v is None:
        return None
    v = str(v).strip()
    return v if v != "" and v.lower() != "nan" else None

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

# -----------------------------
# Title derivation
# -----------------------------

def title_from_filename(md_path: Path) -> str:
    # e.g. "11_13_2025_-_Git__Recap_of_recent_discussions__<id>.md"
    stem = md_path.stem
    # Strip trailing __<uuid> if present
    m = re.match(r"^(.*)__[0-9a-fA-F-]{8,}$", stem)
    if m:
        stem = m.group(1)
    # Friendlier title
    stem = stem.replace("__", " - ").replace("_-_", " - ")
    stem = stem.replace("_", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem

# -----------------------------
# Main header build
# -----------------------------

def build_header(
    conversation_id: str,
    title: str,
    created_utc: Optional[str],
    updated_utc: Optional[str],
    n_msgs: Optional[int],
    export_date: str,
    memory_version: str,
) -> Dict[str, Any]:
    return {
        "memory_id": f"chatgpt_{export_date.replace('-', '')}_{conversation_id}",
        "conversation_id": conversation_id,
        "title": title,
        "created_utc": created_utc or "",
        "updated_utc": updated_utc or "",
        "message_count_user_assistant": n_msgs if n_msgs is not None else 0,
        "source": "chatgpt",
        "export_date": export_date,
        "memory_version": memory_version,

        # semantic fields (to be filled later by OpenAI or manual CSV)
        "summary": "",
        "tags": [],
        "projects": [],
        "people": [],
        "confidence": "",
    }

def main() -> None:
    ap = argparse.ArgumentParser(description="Prepend deterministic Memory Header v1 YAML to kept ChatGPT markdown files.")
    ap.add_argument("--index-csv", required=True, help="Path to index.csv (from export_chatgpt_conversations.py)")
    ap.add_argument("--kept-manifest", required=True, help="Path to kept_manifest.csv")
    ap.add_argument("--export-date", default="2025-12-28", help="Export date YYYY-MM-DD (default 2025-12-28)")
    ap.add_argument("--memory-version", default="v1", help="Memory header version label (default v1)")
    ap.add_argument("--dry-run", action="store_true", help="Print what would change, do not write")
    ap.add_argument("--only-missing", action="store_true", help="Only add header to files with no front-matter (default true behavior)")
    args = ap.parse_args()

    index_rows = read_csv(Path(args.index_csv))
    kept_rows = read_csv(Path(args.kept_manifest))

    # Build map: conversation_id -> metadata (title/created_utc/updated_utc/n_msgs)
    idx_map: Dict[str, Dict[str, str]] = {}
    for r in index_rows:
        cid = pick(r, "conversation_id")
        if not cid:
            continue
        idx_map[cid] = r

    changed = 0
    skipped = 0
    missing = 0

    for kr in kept_rows:
        cid = pick(kr, "id")
        dest_path_s = pick(kr, "dest_path") or pick(kr, "resolved_path") or pick(kr, "src_path")
        status = pick(kr, "status") or ""

        if not cid or not dest_path_s:
            continue

        md_path = Path(dest_path_s)

        if not md_path.exists():
            print(f"[MISSING] {cid} -> {md_path} (status={status})")
            missing += 1
            continue

        text = md_path.read_text(encoding="utf-8", errors="replace")
        if has_front_matter(text):
            skipped += 1
            continue

        idx = idx_map.get(cid, {})
        title = pick(idx, "title") or title_from_filename(md_path)
        created_utc = pick(idx, "created_utc")
        updated_utc = pick(idx, "updated_utc")

        n_msgs_raw = pick(idx, "n_msgs")
        n_msgs = int(float(n_msgs_raw)) if n_msgs_raw else None

        header = build_header(
            conversation_id=cid,
            title=title,
            created_utc=created_utc,
            updated_utc=updated_utc,
            n_msgs=n_msgs,
            export_date=args.export_date,
            memory_version=args.memory_version,
        )

        fm = FM_START + yaml_dump_simple(header) + FM_END
        new_text = fm + text

        if args.dry_run:
            print(f"[DRY] would add header: {md_path}")
        else:
            md_path.write_text(new_text, encoding="utf-8")
        changed += 1

    print("\n=== Summary ===")
    print(f"changed: {changed}")
    print(f"skipped_already_has_header: {skipped}")
    print(f"missing_files: {missing}")

if __name__ == "__main__":
    main()
