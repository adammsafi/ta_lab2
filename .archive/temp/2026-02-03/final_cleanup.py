"""Final cleanup script for remaining root items.

Handles:
- archive_original_files.py, archive_refactored_files.py (archival scripts)
- Remaining corrupted path files
- Special files (nul, -p, .codex_write_access)
- Untracked temp directories

Usage: python final_cleanup.py
"""
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ta_lab2.tools.archive import compute_file_checksum


def archive_file_safe(
    source: Path,
    archive_dir: Path,
    reason: str,
) -> Dict:
    """Archive a file safely, handling permission errors."""
    if not source.exists():
        return None

    try:
        checksum = compute_file_checksum(source)
        size_bytes = source.stat().st_size
    except Exception as e:
        print(f"  WARNING: Cannot process {source.name}: {e}")
        return None

    # Prepare destination
    archive_path = archive_dir / source.name

    # Handle name conflicts
    counter = 1
    while archive_path.exists():
        stem = source.stem
        suffix = source.suffix
        archive_path = archive_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    # Get commit hash
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        commit_hash = result.stdout.strip()
    except Exception:
        commit_hash = "unknown"

    # Copy file (not move, due to permission issues)
    try:
        source.replace(archive_path)
        print(f"  MOVED: {source.name}")
    except Exception as e:
        print(f"  ERROR: Cannot move {source.name}: {e}")
        return None

    return {
        "original_path": str(source),
        "archive_path": str(archive_path),
        "action": "moved",
        "timestamp": datetime.now().isoformat(),
        "sha256_checksum": checksum,
        "size_bytes": size_bytes,
        "commit_hash": commit_hash,
        "phase_number": "16",
        "archive_reason": reason,
    }


def main():
    """Main cleanup function."""
    root = Path.cwd()
    temp_archive = root / ".archive" / "temp" / "2026-02-03"
    temp_archive.mkdir(parents=True, exist_ok=True)

    entries = []

    print("=" * 80)
    print("FINAL CLEANUP: Remaining root files")
    print("=" * 80)

    # Archive remaining Python scripts
    print("\n--- Archiving remaining Python scripts ---")
    for script_name in [
        "archive_original_files.py",
        "archive_refactored_files.py",
        "final_cleanup.py",
    ]:
        script_path = root / script_name
        if script_path.exists():
            entry = archive_file_safe(
                script_path,
                temp_archive,
                "Temporary archival script from Phase 16-01",
            )
            if entry:
                entries.append(entry)

    # Try to remove special files (may fail due to Windows permissions)
    print("\n--- Removing special Windows files ---")
    for special_file in ["nul", "-p"]:
        file_path = root / special_file
        if file_path.exists():
            try:
                # These are Windows special device names, try to delete
                file_path.unlink()
                print(f"  REMOVED: {special_file}")
            except Exception as e:
                print(f"  WARNING: Cannot remove {special_file}: {e}")

    # Archive .codex_write_access
    print("\n--- Archiving .codex_write_access ---")
    codex_file = root / ".codex_write_access"
    if codex_file.exists():
        entry = archive_file_safe(
            codex_file,
            temp_archive,
            "Codex write access marker file",
        )
        if entry:
            entries.append(entry)

    # Update manifest
    manifest_path = root / ".archive" / "temp" / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            manifest = {
                "$schema": "https://ta_lab2.local/schemas/archive-manifest/v1.0.0",
                "version": "1.0.0",
                "category": "temp",
                "created_at": datetime.now().isoformat(),
                "total_files": 0,
                "total_size_bytes": 0,
                "files": [],
            }
    else:
        manifest = {
            "$schema": "https://ta_lab2.local/schemas/archive-manifest/v1.0.0",
            "version": "1.0.0",
            "category": "temp",
            "created_at": datetime.now().isoformat(),
            "total_files": 0,
            "total_size_bytes": 0,
            "files": [],
        }

    # Add new entries
    for entry in entries:
        manifest["files"].append(entry)

    # Update totals
    manifest["total_files"] = len(manifest["files"])
    manifest["total_size_bytes"] = sum(f["size_bytes"] for f in manifest["files"])

    # Save manifest
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\nUpdated manifest with {len(entries)} additional files")
    print("\n" + "=" * 80)
    print("FINAL CLEANUP COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
