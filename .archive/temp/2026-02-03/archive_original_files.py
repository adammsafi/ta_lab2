"""
Archive *.original files with manifest tracking.
Phase 16-02: Resolve refactored/original file pairs.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 checksum of file."""
    with open(file_path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def archive_original_files():
    """Archive all *.original files and create manifest."""

    base_dir = Path(r"C:\Users\asafi\Downloads\ta_lab2")
    archive_dir = base_dir / ".archive" / "originals" / "2026-02-03"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Find all .original files
    original_files = list(base_dir.rglob("*.original"))

    manifest_entries = []
    files_to_move = []

    for src_path in original_files:
        rel_path = src_path.relative_to(base_dir)

        # Compute checksum before move
        checksum = compute_sha256(src_path)
        size_bytes = src_path.stat().st_size

        # Archive destination
        archive_name = src_path.name
        dest_path = archive_dir / archive_name

        # Create manifest entry
        entry = {
            "original_path": str(rel_path).replace("\\", "/"),
            "archive_path": str(dest_path.relative_to(base_dir)).replace("\\", "/"),
            "action": "archived",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sha256_checksum": checksum,
            "size_bytes": size_bytes,
            "phase_number": "16",
            "archive_reason": "Git history tracks originals; .original backup files redundant",
        }

        manifest_entries.append(entry)
        files_to_move.append((src_path, dest_path, archive_name, rel_path))

        print(f"PREPARED: {rel_path}")
        print(f"  -> {dest_path.relative_to(base_dir)}")
        print(f"  SHA256: {checksum}")
        print(f"  Size: {size_bytes:,} bytes")
        print()

    # Write manifest
    manifest_path = base_dir / ".archive" / "originals" / "manifest.json"

    manifest = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "schema_version": "1.0.0",
        "category": "originals",
        "description": "Manifest tracking .original file archiving (git history provides canonical versions)",
        "entries": manifest_entries,
    }

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"MANIFEST: {manifest_path.relative_to(base_dir)}")
    print(f"  Entries: {len(manifest_entries)}")
    print()

    return files_to_move, manifest_path


if __name__ == "__main__":
    files_to_move, manifest_path = archive_original_files()

    print("\n=== ARCHIVE SUMMARY ===")
    print(f"Prepared {len(files_to_move)} .original files for archiving")
    print(f"Manifest: {manifest_path}")
    print("\nFiles prepared:")
    for src, dest, name, rel_path in files_to_move:
        print(f"  - {rel_path}")
