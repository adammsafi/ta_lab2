#!/usr/bin/env python3
"""Clean ChatGPT exports by removing trash files.

This script maintains a persistent trash list and removes unwanted files from
ChatGPT exports. The trash list can be initialized from a tree_diff.json
(produced by chatgpt_export_diff.py) and then reused for subsequent exports.

Two modes
---------
1. Init mode: Create/update trash list from tree_diff.json
2. Clean mode: Remove trash files from an export using the trash list

The trash list is an explicit JSON file you maintain over time, ensuring
consistent cleaning across exports and avoiding accidental deletion of new
content types.

Example usage
-------------
1) Create the persisted trash list from the first diff:
  python -m ta_lab2.tools.data_tools.export.chatgpt_export_clean \\
    --init-from-tree-diff /path/to/tree_diff.json \\
    --trash-list /path/to/trash_list.json

2) Clean any future export using that list:
  python -m ta_lab2.tools.data_tools.export.chatgpt_export_clean \\
    /path/to/new_dump.zip \\
    --out /path/to/new_dump_clean \\
    --trash-list /path/to/trash_list.json \\
    --clobber

3) Add to the trash list over time:
  python -m ta_lab2.tools.data_tools.export.chatgpt_export_clean \\
    --init-from-tree-diff /path/to/new_diff/tree_diff.json \\
    --trash-list /path/to/trash_list.json \\
    --append

Trash list file format
----------------------
JSON with structure:
{
  "version": 1,
  "created_at": "...",
  "updated_at": "...",
  "paths": [
      "relative/path/to/file_or_folder",
      "some/folder/",   # folders MUST end with "/"
  ],
  "notes": {
      "relative/path": "optional note"
  }
}

Important cautions
------------------
- If OpenAI changes export layout and new junk appears, it won't be removed
  until you add it to the trash list.
- If you accidentally add something important to the trash list, it will be
  removed every time.
- The clean_run_manifest.json is created in the output directory for audit.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


def norm_rel(p: str) -> str:
    """Normalize relative path to posix style."""
    return p.replace("\\", "/").lstrip("/")


def is_zip_path(p: Path) -> bool:
    """Check if path is a valid zip file."""
    return p.is_file() and p.suffix.lower() == ".zip" and zipfile.is_zipfile(p)


def ensure_empty_dir(out_dir: Path, *, clobber: bool) -> None:
    """Ensure output directory is empty."""
    if out_dir.exists():
        if not clobber:
            raise SystemExit(
                f"ERROR: Output dir exists: {out_dir}\nUse --clobber to overwrite."
            )
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


def load_trash_list(path: Path) -> Dict:
    """Load trash list from JSON file, creating empty one if not exists."""
    if not path.exists():
        return {
            "version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "paths": [],
            "notes": {},
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise SystemExit(
            f"ERROR: Unsupported trash list version: {data.get('version')}"
        )
    if "paths" not in data or not isinstance(data["paths"], list):
        raise SystemExit("ERROR: trash list missing 'paths' list")
    if "notes" not in data or not isinstance(data["notes"], dict):
        data["notes"] = {}
    return data


def save_trash_list(path: Path, data: Dict) -> None:
    """Save trash list to JSON file."""
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def compile_trash_sets(paths: List[str]) -> Tuple[Set[str], List[str]]:
    """Compile trash paths into files set and folders list.

    Returns:
      - trash_files: exact relative file paths
      - trash_folders: list of folder prefixes (must end in "/")
    """
    trash_files: Set[str] = set()
    trash_folders: List[str] = []
    for raw in paths:
        p = norm_rel(raw)
        if not p:
            continue
        if p.endswith("/"):
            trash_folders.append(p)
        else:
            trash_files.add(p)
    # sort folders longest-first so more specific prefixes match first (not required but tidy)
    trash_folders.sort(key=len, reverse=True)
    return trash_files, trash_folders


def is_trashed(rel: str, *, trash_files: Set[str], trash_folders: List[str]) -> bool:
    """Check if a relative path is in the trash list."""
    r = norm_rel(rel)
    if r in trash_files:
        return True
    # folder prefix match
    for pref in trash_folders:
        if r.startswith(pref):
            return True
    return False


def init_from_tree_diff(
    tree_diff_json: Path, trash_list_path: Path, *, append: bool
) -> None:
    """Initialize trash list from a tree_diff.json file."""
    td = json.loads(tree_diff_json.read_text(encoding="utf-8"))

    removed_files = [norm_rel(x) for x in td.get("removed_files", [])]
    removed_folders = [norm_rel(x) for x in td.get("removed_folders", [])]

    # enforce folder trailing slash
    removed_folders = [x if x.endswith("/") else x + "/" for x in removed_folders]

    new_paths = removed_folders + removed_files

    data = load_trash_list(trash_list_path)
    existing = set(norm_rel(x) for x in data.get("paths", []))

    if append:
        merged = sorted(existing.union(new_paths))
    else:
        merged = sorted(set(new_paths))

    data["paths"] = merged

    # add a small note for provenance (optional)
    note_key = f"__init_from_tree_diff__:{tree_diff_json.name}"
    data["notes"].setdefault(note_key, f"Initialized from {tree_diff_json}")

    save_trash_list(trash_list_path, data)

    logger.info(f"Tree diff: {tree_diff_json}")
    logger.info(f"Trash list: {trash_list_path}")
    logger.info(f"Append: {append}")
    logger.info(
        f"Added from diff: folders={len(removed_folders)} files={len(removed_files)}"
    )
    logger.info(f"Trash list total paths: {len(merged)}")


def copy_dir_with_trash_list(
    in_dir: Path,
    out_dir: Path,
    *,
    trash_files: Set[str],
    trash_folders: List[str],
    dry_run: bool,
) -> Tuple[int, int, int]:
    """Copy directory excluding trash files."""
    kept = 0
    removed = 0
    removed_bytes = 0

    for abs_path in in_dir.rglob("*"):
        if not abs_path.is_file():
            continue
        rel = abs_path.relative_to(in_dir).as_posix()

        if is_trashed(rel, trash_files=trash_files, trash_folders=trash_folders):
            removed += 1
            try:
                removed_bytes += abs_path.stat().st_size
            except Exception:
                pass
            continue

        kept += 1
        if not dry_run:
            dst = out_dir / Path(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(abs_path, dst)

    return kept, removed, removed_bytes


def copy_zip_with_trash_list(
    in_zip: Path,
    out_dir: Path,
    *,
    trash_files: Set[str],
    trash_folders: List[str],
    dry_run: bool,
) -> Tuple[int, int, int]:
    """Extract zip excluding trash files."""
    kept = 0
    removed = 0
    removed_bytes = 0

    with zipfile.ZipFile(in_zip, "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = norm_rel(info.filename)

            if is_trashed(rel, trash_files=trash_files, trash_folders=trash_folders):
                removed += 1
                removed_bytes += int(info.file_size or 0)
                continue

            kept += 1
            if not dry_run:
                dst = out_dir / Path(rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(z.read(info.filename))

    return kept, removed, removed_bytes


def human_bytes(n: int) -> str:
    """Format bytes as human-readable string."""
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n)
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.1f}{u}" if u != "B" else f"{int(x)}B"
        x /= 1024.0
    return f"{n}B"


def clean_export(
    input_path: Path,
    out_dir: Path,
    trash_list_path: Path,
    clobber: bool = False,
    dry_run: bool = False,
) -> Dict[str, any]:
    """Clean an export using trash list.

    Args:
        input_path: Export .zip or folder
        out_dir: Output cleaned folder
        trash_list_path: Path to trash list JSON
        clobber: Overwrite output if exists
        dry_run: Don't write files, just report counts

    Returns:
        Dict with statistics: kept_files, removed_files, removed_bytes
    """
    data = load_trash_list(trash_list_path)
    trash_files, trash_folders = compile_trash_sets(data["paths"])

    ensure_empty_dir(out_dir, clobber=clobber)

    if is_zip_path(input_path):
        kept, removed, removed_bytes = copy_zip_with_trash_list(
            input_path,
            out_dir,
            trash_files=trash_files,
            trash_folders=trash_folders,
            dry_run=dry_run,
        )
        kind = "zip"
    elif input_path.is_dir():
        kept, removed, removed_bytes = copy_dir_with_trash_list(
            input_path,
            out_dir,
            trash_files=trash_files,
            trash_folders=trash_folders,
            dry_run=dry_run,
        )
        kind = "dir"
    else:
        raise ValueError(f"Input must be a .zip or folder: {input_path}")

    # Write a small run manifest into out_dir (unless dry-run)
    if not dry_run:
        run_manifest = {
            "ran_at": datetime.now().isoformat(timespec="seconds"),
            "input": str(input_path),
            "input_kind": kind,
            "trash_list": str(trash_list_path),
            "trash_paths_count": len(data["paths"]),
            "kept_files": kept,
            "removed_files": removed,
            "removed_bytes": removed_bytes,
        }
        (out_dir / "clean_run_manifest.json").write_text(
            json.dumps(run_manifest, indent=2), encoding="utf-8"
        )

    logger.info(f"Input: {input_path} ({kind})")
    logger.info(f"Output: {out_dir}")
    logger.info(f"Trash list: {trash_list_path} (paths={len(data['paths'])})")
    logger.info(f"Dry run: {dry_run}")
    logger.info(f"Kept: {kept} files")
    logger.info(f"Removed: {removed} files ({human_bytes(removed_bytes)})")

    return {
        "kept_files": kept,
        "removed_files": removed,
        "removed_bytes": removed_bytes,
        "input_kind": kind,
    }


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Clean a ChatGPT export by removing ONLY explicitly-listed trash paths (persistent list you maintain)."
    )
    ap.add_argument(
        "input",
        nargs="?",
        help="Export .zip or folder (omit when using --init-from-tree-diff)",
    )
    ap.add_argument(
        "--out",
        help="Output cleaned folder (required unless using --init-from-tree-diff)",
    )
    ap.add_argument(
        "--clobber", action="store_true", help="Overwrite --out if it exists"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Do not write files, just report counts"
    )

    ap.add_argument(
        "--trash-list",
        default="trash_list.json",
        help="Path to trash list json (created if missing)",
    )

    # Bootstrap trash list from a tree diff produced by chatgpt_export_diff.py
    ap.add_argument(
        "--init-from-tree-diff",
        help="Path to tree_diff.json to seed trash list from removed_* arrays",
    )
    ap.add_argument(
        "--append",
        action="store_true",
        help="When initing from tree diff, append to existing list instead of replace",
    )

    args = ap.parse_args()

    trash_list_path = Path(args.trash_list).expanduser()

    # Mode: init trash list
    if args.init_from_tree_diff:
        tree_diff_json = Path(args.init_from_tree_diff).expanduser()
        if not tree_diff_json.exists():
            raise SystemExit(f"ERROR: tree diff json not found: {tree_diff_json}")
        init_from_tree_diff(tree_diff_json, trash_list_path, append=bool(args.append))
        return 0

    # Mode: clean input using existing trash list
    if not args.input or not args.out:
        raise SystemExit(
            "ERROR: cleaning requires INPUT and --out (or use --init-from-tree-diff)"
        )

    in_path = Path(args.input).expanduser()
    out_dir = Path(args.out).expanduser()

    result = clean_export(
        in_path, out_dir, trash_list_path, clobber=args.clobber, dry_run=args.dry_run
    )

    print("\n=== CLEAN (EXPLICIT LIST ONLY) ===")
    print(f"Input:      {in_path} ({result['input_kind']})")
    print(f"Output:     {out_dir}")
    print(f"Kept:       {result['kept_files']} files")
    print(
        f"Removed:    {result['removed_files']} files ({human_bytes(result['removed_bytes'])})"
    )
    if not args.dry_run:
        print(f"Wrote:      {out_dir / 'clean_run_manifest.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
