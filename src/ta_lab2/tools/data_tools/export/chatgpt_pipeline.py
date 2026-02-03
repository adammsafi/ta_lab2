#!/usr/bin/env python3
"""Orchestrate ChatGPT export cleaning and transcript extraction.

This pipeline script coordinates multiple steps:
1. Optional cleaning (using chatgpt_export_clean.py)
2. Transcript extraction (using export_chatgpt_conversations.py)
3. Optional keep filtering (using extract_kept_chats_from_keepfile.py)
4. Optional zip of kept chats

This provides a single command-line interface for common export workflows.

Example usage
-------------
Basic export:
  python -m ta_lab2.tools.data_tools.export.chatgpt_pipeline \\
    --export /path/to/export.zip \\
    --out /path/to/output \\
    --min-msgs 4

With cleaning:
  python -m ta_lab2.tools.data_tools.export.chatgpt_pipeline \\
    --export /path/to/export.zip \\
    --out /path/to/output \\
    --trash-list /path/to/trash_list.json \\
    --clean-out /path/to/cleaned \\
    --clobber

With keep filtering:
  python -m ta_lab2.tools.data_tools.export.chatgpt_pipeline \\
    --export /path/to/export.zip \\
    --out /path/to/output \\
    --keep-csv /path/to/keep.csv \\
    --zip-kept
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def _run(cmd: List[str]) -> None:
    """Run subprocess command."""
    logger.info("+ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def _shortest_path(paths: List[Path]) -> Optional[Path]:
    """Return shortest path from list."""
    if not paths:
        return None
    paths.sort(key=lambda p: len(str(p)))
    return paths[0]


def _find_conversations_json(root: Path) -> Optional[Path]:
    """Find conversations.json in directory tree."""
    candidates = list(root.rglob("conversations.json"))
    return _shortest_path(candidates)


def _extract_conversations_json_from_zip(zip_path: Path, out_dir: Path) -> Path:
    """Extract conversations.json from zip file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        names = [n for n in z.namelist() if n.endswith("conversations.json")]
        if not names:
            raise SystemExit(f"No conversations.json in zip: {zip_path}")
        names.sort(key=len)
        member = names[0]
        target = out_dir / Path(member).name
        target.write_bytes(z.read(member))
        return target


def _normalize_path(s: str) -> str:
    """Normalize path string."""
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in {"'", '"'}:
        s = s[1:-1].strip()
    s = os.path.expandvars(s)
    s = s.replace("/", "\\")
    return s


def _find_by_id(cid: str, search_roots: List[Path]) -> Optional[Path]:
    """Find transcript by conversation ID."""
    pattern = f"*__{cid}.md"
    for root in search_roots:
        if not root.exists():
            continue
        matches = list(root.rglob(pattern))
        if matches:
            return _shortest_path(matches)
    return None


def _extract_kept(keep_csv: Path, out_root: Path, kept_dir: Path) -> Path:
    """Extract kept chats from keep CSV."""
    kept_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / "kept_manifest.csv"
    chats_dir = out_root / "chats"

    search_roots = [chats_dir, out_root, out_root.parent]

    results = []
    with keep_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader, start=1):
            if not row or all(not (c or "").strip() for c in row):
                continue

            if len(row) < 2:
                results.append({
                    "row": str(i),
                    "id": "",
                    "src_path": "",
                    "resolved_path": "",
                    "dest_path": "",
                    "status": "BAD_ROW",
                    "error": "Row has fewer than 2 columns (expected: id, path)",
                })
                continue

            cid = (row[0] or "").strip().strip("'\"")
            src_path_str = _normalize_path(row[1])

            if cid.lower() in {"conversation_id", "id"}:
                continue
            if src_path_str.lower() in {"md_path", "path"}:
                continue

            if not cid:
                results.append({
                    "row": str(i),
                    "id": "",
                    "src_path": src_path_str,
                    "resolved_path": "",
                    "dest_path": "",
                    "status": "BAD_ROW",
                    "error": "Missing id in column A",
                })
                continue

            src = Path(src_path_str)
            dest = kept_dir / (src.name if src.name else f"unknown__{cid}.md")

            resolved: Optional[Path] = None
            status = ""
            err = ""

            if src.exists():
                resolved = src
                status = "FOUND_PATH"

            if resolved is None and src.name:
                alt = chats_dir / src.name
                if alt.exists():
                    resolved = alt
                    status = "FOUND_BASENAME_IN_CHATS"

            if resolved is None:
                hit = _find_by_id(cid, search_roots)
                if hit is not None:
                    resolved = hit
                    status = "FOUND_BY_ID_SEARCH"

            if resolved is None:
                results.append({
                    "row": str(i),
                    "id": cid,
                    "src_path": src_path_str,
                    "resolved_path": "",
                    "dest_path": str(dest),
                    "status": "MISSING",
                    "error": "File not found via path, basename, or id search",
                })
                continue

            shutil.copy2(resolved, dest)
            results.append({
                "row": str(i),
                "id": cid,
                "src_path": src_path_str,
                "resolved_path": str(resolved),
                "dest_path": str(dest),
                "status": status,
                "error": err,
            })

    with manifest_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["row", "id", "src_path", "resolved_path", "dest_path", "status", "error"],
        )
        writer.writeheader()
        writer.writerows(results)

    return manifest_path


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Orchestrate ChatGPT export cleaning and transcript extraction."
    )
    ap.add_argument("--export", required=True, help="Path to export zip, folder, or conversations.json")
    ap.add_argument("--out", required=True, help="Output folder for chats/index")
    ap.add_argument("--min-msgs", type=int, default=4, help="Minimum user/assistant messages")
    ap.add_argument("--trash-list", help="Persistent trash_list.json for cleaning")
    ap.add_argument("--clean-out", help="Output folder for cleaned export")
    ap.add_argument("--clobber", action="store_true", help="Allow overwrite when cleaning")
    ap.add_argument("--keep-csv", help="CSV with keep rows (id, path)")
    ap.add_argument("--zip-kept", action="store_true", help="Zip kept folder after extract")

    args = ap.parse_args()

    # Reference the other scripts via Python module imports
    # (They'll be executed in the same package)
    here = Path(__file__).resolve().parent

    export_path = Path(args.export)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    working_root = export_path

    if args.trash_list:
        if export_path.is_file() and export_path.suffix.lower() == ".json":
            raise SystemExit("--trash-list requires a zip or folder export, not a .json")

        clean_out = Path(args.clean_out) if args.clean_out else (out_dir / "_clean_export")

        # Call chatgpt_export_clean.py via Python module
        cmd = [
            sys.executable,
            "-m",
            "ta_lab2.tools.data_tools.export.chatgpt_export_clean",
            str(export_path),
            "--out",
            str(clean_out),
            "--trash-list",
            str(Path(args.trash_list)),
        ]
        if args.clobber:
            cmd.append("--clobber")
        _run(cmd)
        working_root = clean_out

    if working_root.is_file() and working_root.suffix.lower() == ".json":
        conversations_json = working_root
    elif working_root.is_dir():
        conversations_json = _find_conversations_json(working_root)
        if conversations_json is None:
            raise SystemExit(f"Could not find conversations.json under: {working_root}")
    elif working_root.is_file() and working_root.suffix.lower() == ".zip":
        tmp_dir = out_dir / "_tmp_export"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        conversations_json = _extract_conversations_json_from_zip(working_root, tmp_dir)
    else:
        raise SystemExit(f"Unsupported export path: {working_root}")

    # Call export_chatgpt_conversations.py via Python module
    _run([
        sys.executable,
        "-m",
        "ta_lab2.tools.data_tools.export.export_chatgpt_conversations",
        "--in",
        str(conversations_json),
        "--out",
        str(out_dir),
        "--min-msgs",
        str(args.min_msgs),
    ])

    if args.keep_csv:
        keep_csv = Path(args.keep_csv)
        kept_dir = out_dir / "kept"
        manifest = _extract_kept(keep_csv, out_dir, kept_dir)
        logger.info(f"Wrote: {manifest}")

        if args.zip_kept:
            zip_path = out_dir / "kept_chats.zip"
            base_name = str(zip_path)[:-4]
            shutil.make_archive(base_name, "zip", root_dir=str(kept_dir))
            logger.info(f"Wrote: {zip_path}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
