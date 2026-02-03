"""Build memory source registry from memory collection manifests."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FM_START = "---\n"
FM_END = "\n---\n"


def has_front_matter(text: str) -> bool:
    t = text.lstrip("\ufeff\r\n\t ")
    return t.startswith(FM_START) and (FM_END in t[len(FM_START):])


def split_front_matter(text: str) -> Tuple[Optional[str], str]:
    t = text.lstrip("\ufeff\r\n\t ")
    if not has_front_matter(text):
        return None, text
    end_idx = t.find(FM_END, len(FM_START))
    if end_idx == -1:
        return None, text
    fm = t[len(FM_START):end_idx]
    rest = t[end_idx + len(FM_END):]
    return fm, rest


def parse_front_matter_minimal(fm: str) -> Dict[str, Any]:
    """
    Minimal YAML parser for restricted front matter:
      key: value
      key: []
      key:
        - item
    """
    out: Dict[str, Any] = {}
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line or line.lstrip().startswith("#"):
            i += 1
            continue

        # list header: "key:"
        m_list = re.match(r"^([A-Za-z0-9_]+):\s*$", line)
        if m_list:
            key = m_list.group(1)
            i += 1
            if i < len(lines) and lines[i].strip() == "[]":
                out[key] = []
                i += 1
                continue
            items: List[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                items.append(lines[i].lstrip()[2:].strip().strip('"'))
                i += 1
            out[key] = items
            continue

        # scalar: "key: value"
        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()

            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1].replace('\\"', '"').replace("\\\\", "\\")

            if val == "null":
                out[key] = None
            elif val in ("true", "false"):
                out[key] = (val == "true")
            else:
                if re.fullmatch(r"-?\d+", val):
                    out[key] = int(val)
                else:
                    out[key] = val

        i += 1
    return out


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def sha256_text(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a root memory registry (1 per conversation) from kept markdown YAML headers.")
    ap.add_argument("--kept-manifest", required=True, help="Path to kept_manifest.csv")
    ap.add_argument("--out-dir", required=True, help="Output directory for registry artifacts")
    ap.add_argument("--export-date", default="", help="Optional: export date (YYYY-MM-DD), stored in run manifest")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    kept_rows = read_csv(Path(args.kept_manifest))

    registry_jsonl = out_dir / "memory_registry_root.jsonl"
    registry_csv = out_dir / "memory_registry_root.csv"
    run_manifest = out_dir / "memory_registry_root_run_manifest.json"

    records: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    skipped = 0

    for kr in kept_rows:
        cid = (kr.get("id") or "").strip()
        md_path_s = (kr.get("dest_path") or kr.get("resolved_path") or kr.get("src_path") or "").strip()
        if not cid or not md_path_s:
            continue

        md_path = Path(md_path_s)
        if not md_path.exists():
            skipped += 1
            continue

        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
            fm_raw, body = split_front_matter(text)
            if fm_raw is None:
                skipped += 1
                continue

            fm = parse_front_matter_minimal(fm_raw)

            # Root memory record (conversation-level)
            rec = {
                "memory_id": fm.get("memory_id", ""),
                "conversation_id": fm.get("conversation_id", cid),
                "title": fm.get("title", ""),
                "created_utc": fm.get("created_utc", ""),
                "updated_utc": fm.get("updated_utc", ""),
                "message_count_user_assistant": fm.get("message_count_user_assistant", 0),
                "source": fm.get("source", "chatgpt"),
                "export_date": fm.get("export_date", ""),
                "memory_version": fm.get("memory_version", ""),
                "summary": fm.get("summary", ""),
                "tags": fm.get("tags", []),
                "projects": fm.get("projects", []),
                "people": fm.get("people", []),
                "confidence": fm.get("confidence", ""),
                "path": str(md_path),
                "body_sha256": sha256_text(body[:20000]),  # cheap fingerprint of body start
            }
            records.append(rec)

        except Exception as e:
            errors.append({"conversation_id": cid, "path": str(md_path), "error": repr(e)})

    # Write JSONL
    with registry_jsonl.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Write CSV (flatten lists as JSON)
    fieldnames = [
        "memory_id",
        "conversation_id",
        "title",
        "created_utc",
        "updated_utc",
        "message_count_user_assistant",
        "source",
        "export_date",
        "memory_version",
        "summary",
        "tags",
        "projects",
        "people",
        "confidence",
        "path",
        "body_sha256",
    ]
    with registry_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for rec in records:
            row = dict(rec)
            row["tags"] = json.dumps(row.get("tags", []), ensure_ascii=False)
            row["projects"] = json.dumps(row.get("projects", []), ensure_ascii=False)
            row["people"] = json.dumps(row.get("people", []), ensure_ascii=False)
            w.writerow(row)

    manifest = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "kept_manifest": str(Path(args.kept_manifest)),
        "out_dir": str(out_dir),
        "export_date": args.export_date,
        "root_memories": len(records),
        "skipped": skipped,
        "errors": errors,
    }
    run_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\n=== Summary ===")
    print(json.dumps({"root_memories": len(records), "skipped": skipped, "errors": len(errors)}, indent=2))
    print("out:", str(out_dir))


if __name__ == "__main__":
    main()
