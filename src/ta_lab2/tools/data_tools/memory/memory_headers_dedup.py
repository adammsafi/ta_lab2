"""Deduplicate duplicate YAML front-matter blocks in markdown files."""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

FM_START = "---\n"
FM_END = "\n---\n"


def dedup_front_matter(text: str) -> str:
    # normalize leading BOM/whitespace for detection but preserve original content after dedup
    t = text.lstrip("\ufeff\r\n\t ")
    if not t.startswith(FM_START):
        return text

    # Find first FM
    end1 = t.find(FM_END, len(FM_START))
    if end1 == -1:
        return text
    rest1 = t[end1 + len(FM_END) :]

    # If the rest starts with another FM, drop it
    rest1_stripped = rest1.lstrip("\ufeff\r\n\t ")
    if rest1_stripped.startswith(FM_START):
        end2 = rest1_stripped.find(FM_END, len(FM_START))
        if end2 == -1:
            return text
        body = rest1_stripped[end2 + len(FM_END) :]
        # Keep only the first FM + body
        first_fm = t[: end1 + len(FM_END)]
        return first_fm + body

    return text


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Deduplicate duplicate YAML front-matter blocks in markdown files"
    )
    ap.add_argument("--kept-manifest", required=True, help="Path to kept_manifest.csv")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without writing",
    )
    args = ap.parse_args()

    with open(args.kept_manifest, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    changed = 0
    for r in rows:
        p = r.get("dest_path") or r.get("resolved_path") or r.get("src_path")
        if not p:
            continue
        path = Path(p)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        new_text = dedup_front_matter(text)
        if new_text != text:
            changed += 1
            if args.dry_run:
                print("[DRY] would dedup:", path.name)
            else:
                path.write_text(new_text, encoding="utf-8")

    print("dedup_changed:", changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
