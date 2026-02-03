"""
Archive refactored files with manifest tracking.
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


def archive_refactored_files():
    """Archive all *_refactored.py files and create manifest."""

    base_dir = Path(r"C:\Users\asafi\Downloads\ta_lab2")
    archive_dir = base_dir / ".archive" / "refactored" / "2026-02-03"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Files to archive (all are duplicates or stubs inferior to canonical)
    files_to_archive = [
        {
            "original_path": "src/ta_lab2/features/m_tf/ema_multi_timeframe_refactored.py",
            "reason": "Duplicate of canonical ema_multi_timeframe.py (already refactored)",
            "comparison": {
                "decision": "archive_refactored",
                "reason": "Canonical file is already the refactored version; _refactored.py is redundant duplicate",
                "original_lines": 571,
                "refactored_lines": 571,
                "files_identical": True,
            }
        },
        {
            "original_path": "src/ta_lab2/features/m_tf/ema_multi_tf_cal_refactored.py",
            "reason": "Incomplete stub; canonical ema_multi_tf_cal.py is complete refactored version",
            "comparison": {
                "decision": "archive_refactored",
                "reason": "Canonical has full dual EMA implementation (607 LOC); refactored is incomplete stub (289 LOC)",
                "original_lines": 607,
                "refactored_lines": 289,
                "canonical_complete": True,
                "refactored_stub": True,
            }
        },
        {
            "original_path": "src/ta_lab2/features/m_tf/ema_multi_tf_cal_anchor_refactored.py",
            "reason": "Incomplete stub; canonical ema_multi_tf_cal_anchor.py is complete refactored version",
            "comparison": {
                "decision": "archive_refactored",
                "reason": "Canonical has full dual EMA + anchor logic (570 LOC); refactored is incomplete stub (198 LOC)",
                "original_lines": 570,
                "refactored_lines": 198,
                "canonical_complete": True,
                "refactored_stub": True,
            }
        },
    ]

    manifest_entries = []
    archived_files = []

    for file_info in files_to_archive:
        src_path = base_dir / file_info["original_path"]
        if not src_path.exists():
            print(f"SKIP: {file_info['original_path']} (does not exist)")
            continue

        # Compute checksum before move
        checksum = compute_sha256(src_path)
        size_bytes = src_path.stat().st_size

        # Archive destination
        archive_name = src_path.name
        dest_path = archive_dir / archive_name

        # Create manifest entry
        entry = {
            "original_path": file_info["original_path"],
            "archive_path": str(dest_path.relative_to(base_dir)).replace("\\", "/"),
            "action": "archived",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sha256_checksum": checksum,
            "size_bytes": size_bytes,
            "comparison_result": file_info["comparison"],
            "phase_number": "16",
            "archive_reason": file_info["reason"],
        }

        manifest_entries.append(entry)
        archived_files.append((src_path, dest_path, archive_name))

        print(f"PREPARED: {file_info['original_path']}")
        print(f"  -> {dest_path.relative_to(base_dir)}")
        print(f"  SHA256: {checksum}")
        print(f"  Size: {size_bytes:,} bytes")
        print(f"  Reason: {file_info['reason']}")
        print()

    # Write manifest
    manifest_path = base_dir / ".archive" / "refactored" / "manifest.json"

    manifest = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "schema_version": "1.0.0",
        "category": "refactored",
        "description": "Manifest tracking refactored file archiving decisions",
        "entries": manifest_entries,
    }

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"MANIFEST: {manifest_path.relative_to(base_dir)}")
    print(f"  Entries: {len(manifest_entries)}")
    print()

    return archived_files, manifest_path


if __name__ == "__main__":
    archived_files, manifest_path = archive_refactored_files()

    print("\n=== ARCHIVE SUMMARY ===")
    print(f"Prepared {len(archived_files)} files for archiving")
    print(f"Manifest: {manifest_path}")
    print("\nFiles prepared (not yet moved - will be done via git mv):")
    for src, dest, name in archived_files:
        print(f"  - {name}")
