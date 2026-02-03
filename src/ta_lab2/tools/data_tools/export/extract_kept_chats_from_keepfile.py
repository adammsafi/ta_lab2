"""Extract kept ChatGPT chats from a keep CSV file.

Reads a keep CSV and copies referenced ChatGPT transcript markdown files into a single folder.

Your keep CSV format
--------------------
- Column A: id   (conversation_id)
- Column B: path (path to transcript .md file)  [may be stale / wrong root]

Problem this version solves
---------------------------
Sometimes the 'path' column points to files that no longer exist at that exact location
(e.g., you moved the export folder, or paths were generated in a different machine layout).

This script:
1) Tries the provided path
2) If missing, tries: <search_root>/chats/<basename>
3) If missing, searches by conversation_id for pattern: *__<id>.md
   under search roots.

Outputs
-------
- <out_dir>/kept/  (copied .md files)
- <out_dir>/kept_manifest.csv  (what happened per row)

Example runs
------------
Command line:
  python -m ta_lab2.tools.data_tools.export.extract_kept_chats_from_keepfile \\
    --keep-csv /path/to/keep.csv \\
    --search-root /path/to/chatgpt/export \\
    --out-dir /path/to/output
"""

from __future__ import annotations

import argparse
import csv
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _strip_wrapping_quotes(s: str) -> str:
    """Strip wrapping quotes from CSV values."""
    s = (s or "").strip()
    if len(s) >= 2 and ((s[0] == s[-1]) and s[0] in {"'", '"'}):
        return s[1:-1].strip()
    return s


def _find_by_id(cid: str, search_roots: List[Path]) -> Optional[Path]:
    """Find transcript markdown by conversation id.

    Filenames from the exporter look like:
      <title>__<conversation_id>.md

    So we search for:
      *__<cid>.md
    """
    pattern = f"*__{cid}.md"
    for root in search_roots:
        if not root.exists():
            continue
        # rglob can be a bit heavy, but with ~60 ids it's fine.
        matches = list(root.rglob(pattern))
        if matches:
            # Prefer the shortest path (often the most direct hit)
            matches.sort(key=lambda p: len(str(p)))
            return matches[0]
    return None


def extract_kept_chats(
    keep_csv: Path,
    search_root: Path,
    out_dir: Path,
) -> Dict[str, Any]:
    """Extract kept chats based on keep CSV.

    Args:
        keep_csv: CSV file with conversation_id and path columns
        search_root: Root directory to search for chat files
        out_dir: Output directory for kept files and manifest

    Returns:
        Dict with keys: copied, recovered, missing, bad_rows, manifest_path
    """
    if not keep_csv.exists():
        raise FileNotFoundError(f"KEEP_CSV not found: {keep_csv}")

    kept_dir = out_dir / "kept"
    manifest_path = out_dir / "kept_manifest.csv"

    kept_dir.mkdir(parents=True, exist_ok=True)

    # Where we expect chats to be (based on export script)
    chats_dir = search_root / "chats"

    # Search roots for fallback lookup by id
    search_roots = [
        chats_dir,                 # most likely
        search_root,               # if chats live deeper
        search_root.parent,        # one level up in case you changed folder structure
    ]

    results: List[Dict[str, str]] = []
    copied = 0
    missing = 0
    bad_rows = 0
    recovered = 0

    logger.info(f"Reading keep CSV: {keep_csv}")
    logger.info(f"Search roots: {search_roots}")

    with keep_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)

        for i, row in enumerate(reader, start=1):
            if not row or all(not (c or "").strip() for c in row):
                continue

            if len(row) < 2:
                bad_rows += 1
                results.append(
                    {
                        "row": str(i),
                        "id": "",
                        "src_path": "",
                        "resolved_path": "",
                        "dest_path": "",
                        "status": "BAD_ROW",
                        "error": "Row has fewer than 2 columns (expected: id, path)",
                    }
                )
                continue

            cid = _strip_wrapping_quotes(row[0])
            src_path_str = _strip_wrapping_quotes(row[1])

            # Skip header rows like: conversation_id, md_path
            if cid.strip().lower() in {"conversation_id", "id"}:
                continue
            if src_path_str.strip().lower() in {"md_path", "path"}:
                continue

            if not cid:
                bad_rows += 1
                results.append(
                    {
                        "row": str(i),
                        "id": "",
                        "src_path": src_path_str,
                        "resolved_path": "",
                        "dest_path": "",
                        "status": "BAD_ROW",
                        "error": "Missing id in column A",
                    }
                )
                continue

            src = Path(src_path_str)
            dest = kept_dir / (src.name if src.name else f"unknown__{cid}.md")

            resolved: Optional[Path] = None
            status = ""

            # 1) Try provided path
            if src.exists():
                resolved = src
                status = "FOUND_PATH"

            # 2) Try search_root/chats/<basename>
            if resolved is None and src.name:
                alt = chats_dir / src.name
                if alt.exists():
                    resolved = alt
                    status = "FOUND_BASENAME_IN_CHATS"

            # 3) Search by id for *__<id>.md
            if resolved is None:
                hit = _find_by_id(cid, search_roots)
                if hit is not None:
                    resolved = hit
                    status = "FOUND_BY_ID_SEARCH"
                    recovered += 1

            if resolved is None:
                missing += 1
                results.append(
                    {
                        "row": str(i),
                        "id": cid,
                        "src_path": str(src),
                        "resolved_path": "",
                        "dest_path": str(dest),
                        "status": "MISSING",
                        "error": "Could not resolve file from path or id search",
                    }
                )
                continue

            # Copy resolved file
            try:
                dest = kept_dir / resolved.name
                shutil.copy2(resolved, dest)
                copied += 1
                results.append(
                    {
                        "row": str(i),
                        "id": cid,
                        "src_path": str(src),
                        "resolved_path": str(resolved),
                        "dest_path": str(dest),
                        "status": "COPIED_" + status,
                        "error": "",
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "row": str(i),
                        "id": cid,
                        "src_path": str(src),
                        "resolved_path": str(resolved),
                        "dest_path": str(dest),
                        "status": "ERROR",
                        "error": repr(e),
                    }
                )

    # Write manifest
    with manifest_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["row", "id", "src_path", "resolved_path", "dest_path", "status", "error"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow(r)

    logger.info(f"Copied: {copied}, Recovered: {recovered}, Missing: {missing}, Bad rows: {bad_rows}")
    logger.info(f"Manifest written to: {manifest_path}")

    return {
        "copied": copied,
        "recovered": recovered,
        "missing": missing,
        "bad_rows": bad_rows,
        "manifest_path": manifest_path,
        "kept_dir": kept_dir,
    }


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Extract kept ChatGPT chats from keep CSV file."
    )
    ap.add_argument(
        "--keep-csv",
        required=True,
        help="Path to keep CSV file (columns: id, path)",
    )
    ap.add_argument(
        "--search-root",
        required=True,
        help="Root directory to search for chat files",
    )
    ap.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for kept files and manifest",
    )
    args = ap.parse_args()

    keep_csv = Path(args.keep_csv)
    search_root = Path(args.search_root)
    out_dir = Path(args.out_dir)

    result = extract_kept_chats(keep_csv, search_root, out_dir)

    print(f"KEEP_CSV:   {keep_csv}")
    print(f"SEARCH_ROOT: {search_root}")
    print(f"OUT_DIR:    {out_dir}")
    print(f"KEPT_DIR:   {result['kept_dir']}")
    print(f"MANIFEST:   {result['manifest_path']}")
    print(f"Copied:     {result['copied']}")
    print(f"Recovered:  {result['recovered']}  (found by id search)")
    print(f"Missing:    {result['missing']}")
    print(f"Bad rows:   {result['bad_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
