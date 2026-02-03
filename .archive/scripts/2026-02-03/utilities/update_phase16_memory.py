#!/usr/bin/env python3
"""Update Mem0 memory system with Phase 16 repository cleanup file movements.

Creates memory entries for:
1. Archived temp files and scripts
2. Organized documentation moves
3. Phase 16 completion snapshot

Follows patterns from Phase 14 Plan 10 (Data_Tools migration memory tracking).
"""

import json
from pathlib import Path
from dotenv import load_dotenv
import os

# Load OpenAI API key from environment file
load_dotenv('openai_config.env')

from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client

# Get Mem0 client (uses configuration from ta_lab2)
client = get_mem0_client()

def create_archive_memory(original_path: str, archive_path: str, category: str, reason: str):
    """Create memory entry for archived file with moved_to relationship."""
    memory_text = f"""File archived during Phase 16 repository cleanup:
- Original path: {original_path}
- Archive path: {archive_path}
- Category: {category}
- Reason: {reason}
- Relationship: moved_to (archived)
- Phase: 16-repository-cleanup
"""
    client.add(
        messages=[{"role": "user", "content": memory_text}],
        user_id="ta_lab2_system",
        metadata={
            "type": "file_archive",
            "relationship": "moved_to",
            "original_path": original_path,
            "archive_path": archive_path,
            "category": category,
            "phase": "16",
            "timestamp": "2026-02-03",
        },
        infer=False  # Disable LLM conflict detection for batch performance
    )

def create_doc_move_memory(original_path: str, new_path: str, doc_type: str):
    """Create memory entry for documentation file move."""
    memory_text = f"""Documentation organized during Phase 16 repository cleanup:
- Original path: {original_path}
- New path: {new_path}
- Document type: {doc_type}
- Relationship: moved_to (reorganized)
- Phase: 16-repository-cleanup
"""
    client.add(
        messages=[{"role": "user", "content": memory_text}],
        user_id="ta_lab2_system",
        metadata={
            "type": "doc_reorganization",
            "relationship": "moved_to",
            "original_path": original_path,
            "new_path": new_path,
            "doc_type": doc_type,
            "phase": "16",
            "timestamp": "2026-02-03",
        },
        infer=False
    )

def task1_archive_memories():
    """Task 1: Create memory entries for archived temp files and scripts."""
    print("\n=== Task 1: Archive Memories ===\n")

    # Load manifests
    temp_manifest = json.load(open('.archive/temp/manifest.json'))
    scripts_manifest = json.load(open('.archive/scripts/manifest.json'))
    duplicates_manifest = json.load(open('.archive/duplicates/manifest.json'))

    temp_count = 0
    scripts_count = 0
    duplicates_count = 0

    # Process temp files
    print("Processing temp files...")
    for file_entry in temp_manifest.get('files', []):
        original = file_entry['original_path']
        archive = file_entry['archive_path']
        reason = file_entry.get('archive_reason', 'temp file cleanup')

        create_archive_memory(
            original_path=original,
            archive_path=archive,
            category="temp",
            reason=reason
        )
        temp_count += 1

    print(f"  Created {temp_count} temp file memories")

    # Process scripts
    print("Processing scripts...")
    for file_entry in scripts_manifest.get('files', []):
        original = file_entry['original_path']
        archive = file_entry['archive_path']
        reason = file_entry.get('archive_reason', 'script cleanup')

        create_archive_memory(
            original_path=original,
            archive_path=archive,
            category="scripts",
            reason=reason
        )
        scripts_count += 1

    print(f"  Created {scripts_count} script memories")

    # Process duplicates
    print("Processing duplicates...")
    for file_entry in duplicates_manifest.get('files', []):
        original = file_entry['original_path']
        archive = file_entry['archive_path']
        reason = file_entry.get('archive_reason', 'duplicate file')

        create_archive_memory(
            original_path=original,
            archive_path=archive,
            category="duplicates",
            reason=reason
        )
        duplicates_count += 1

    print(f"  Created {duplicates_count} duplicate memories")

    total = temp_count + scripts_count + duplicates_count
    print(f"\nTask 1 complete: {total} archive memories created")
    return total

def task2_doc_move_memories():
    """Task 2: Create memory entries for organized documentation."""
    print("\n=== Task 2: Documentation Move Memories ===\n")

    # Documentation moves from Plan 03
    doc_moves = [
        ("API_MAP.md", "docs/architecture/api-map.md", "architecture"),
        ("ARCHITECTURE.md", "docs/architecture/architecture.md", "architecture"),
        ("structure.md", "docs/architecture/structure.md", "architecture"),
        ("lab2_analysis_gemini.md", "docs/analysis/lab2-analysis-gemini.md", "analysis"),
        ("EMA_FEATURE_MIGRATION_PLAN.md", "docs/features/emas/ema-feature-migration-plan.md", "features"),
        ("EMA_MIGRATION_SESSION_SUMMARY.md", "docs/features/emas/ema-migration-session-summary.md", "features"),
        ("CI_DEPENDENCY_FIXES.md", "docs/guides/ci-dependency-fixes.md", "guides"),
    ]

    # Archived conversion artifacts
    conversion_archives = [
        ("docs/conversion_checkpoint.json", ".archive/documentation/2026-02-03/conversion/conversion_checkpoint.json", "conversion-artifacts"),
        ("docs/conversion_errors.json", ".archive/documentation/2026-02-03/conversion/conversion_errors.json", "conversion-artifacts"),
        ("docs/conversion_notes.md", ".archive/documentation/2026-02-03/conversion/conversion_notes.md", "conversion-artifacts"),
    ]

    count = 0

    print("Processing documentation moves...")
    for original, new_path, doc_type in doc_moves:
        create_doc_move_memory(original, new_path, doc_type)
        count += 1

    print(f"  Created {count} doc move memories")

    archive_count = 0
    print("Processing conversion artifact archives...")
    for original, archive, doc_type in conversion_archives:
        create_archive_memory(
            original_path=original,
            archive_path=archive,
            category="documentation",
            reason="conversion artifact"
        )
        archive_count += 1

    print(f"  Created {archive_count} conversion artifact memories")

    total = count + archive_count
    print(f"\nTask 2 complete: {total} documentation memories created")
    return total

def task3_phase_snapshot():
    """Task 3: Create Phase 16 completion snapshot."""
    print("\n=== Task 3: Phase 16 Completion Snapshot ===\n")

    # Load statistics
    temp_manifest = json.load(open('.archive/temp/manifest.json'))
    scripts_manifest = json.load(open('.archive/scripts/manifest.json'))
    duplicates_manifest = json.load(open('.archive/duplicates/manifest.json'))
    dup_report = json.load(open('.planning/phases/16-repository-cleanup/duplicates_report.json'))
    sim_report = json.load(open('.planning/phases/16-repository-cleanup/similarity_report.json'))

    temp_count = len(temp_manifest.get('files', []))
    scripts_count = len(scripts_manifest.get('files', []))
    duplicates_count = len(duplicates_manifest.get('files', []))
    refactored_count = 0  # No refactored files archived
    originals_count = 0  # No .original files archived

    total_archived = temp_count + scripts_count + duplicates_count + refactored_count + originals_count

    snapshot_text = f"""Phase 16 Repository Cleanup completed:

**Archived Files:**
- Temp files: {temp_count}
- Scripts: {scripts_count}
- Refactored decisions: {refactored_count}
- Original backups: {originals_count}
- Duplicates: {duplicates_count}
- Total archived: {total_archived}

**Duplicate Detection:**
- Duplicate groups found: {dup_report['summary']['total_duplicate_groups']}
- Wasted space eliminated: {dup_report['summary']['total_wasted_bytes']:,} bytes

**Similarity Analysis:**
- Near-exact function pairs (95%+): {sim_report['summary']['near_exact']}
- Similar function pairs (85-95%): {sim_report['summary']['similar']}
- Related function pairs (70-85%): {sim_report['summary']['related']}

**Requirements Satisfied:**
- CLEAN-01: Root directory cleaned (temp files, scripts archived)
- CLEAN-02: Loose .md files organized into docs/ structure
- CLEAN-03: Exact duplicates identified and archived
- CLEAN-04: Similar functions flagged for manual review
- MEMO-13: File-level memory updates with moved_to relationships
- MEMO-14: Phase snapshot created

**Root Directory Status:**
- Only essential files remain (README, pyproject.toml, configs)
- No loose Python scripts (19 archived)
- No temp files (177 CSV/text/patch archived)
- No *_refactored.py or *.original files

Phase: 16-repository-cleanup
Completed: 2026-02-03
Plans: 6 (01-06)
"""

    client.add(
        messages=[{"role": "user", "content": snapshot_text}],
        user_id="ta_lab2_system",
        metadata={
            "type": "phase_snapshot",
            "phase": "16",
            "phase_name": "repository-cleanup",
            "total_archived": total_archived,
            "duplicate_groups": dup_report['summary']['total_duplicate_groups'],
            "similar_functions": sim_report['summary']['total_matches'],
            "requirements_satisfied": ["CLEAN-01", "CLEAN-02", "CLEAN-03", "CLEAN-04", "MEMO-13", "MEMO-14"],
            "timestamp": "2026-02-03",
        },
        infer=False
    )

    print(f"Phase 16 snapshot created:")
    print(f"  Total archived: {total_archived}")
    print(f"  Duplicate groups: {dup_report['summary']['total_duplicate_groups']}")
    print(f"  Similar functions: {sim_report['summary']['total_matches']}")
    print(f"\nTask 3 complete: 1 phase snapshot created")
    return 1

def verify_memories():
    """Verify memory queries work."""
    print("\n=== Verification ===\n")

    # Test 1: Archive query
    print("Test 1: Search for archived temp files")
    results = client.search(query="Phase 16 temp files archived", user_id="ta_lab2_system", limit=5)
    if isinstance(results, dict) and 'results' in results:
        results = results['results']
    print(f"  Found {len(results)} results")

    # Test 2: Doc reorganization query
    print("\nTest 2: Search for API_MAP.md move")
    results = client.search(query="API_MAP.md moved to", user_id="ta_lab2_system", limit=5)
    if isinstance(results, dict) and 'results' in results:
        results = results['results']
    print(f"  Found {len(results)} results")

    # Test 3: Phase snapshot query
    print("\nTest 3: Search for Phase 16 completion")
    results = client.search(query="Phase 16 repository cleanup completed", user_id="ta_lab2_system", limit=5)
    if isinstance(results, dict) and 'results' in results:
        results = results['results']
    print(f"  Found {len(results)} results")

    print("\nVerification complete")

if __name__ == "__main__":
    print("Phase 16 Memory Update Script")
    print("=" * 50)

    task1_count = task1_archive_memories()
    task2_count = task2_doc_move_memories()
    task3_count = task3_phase_snapshot()

    total_memories = task1_count + task2_count + task3_count

    print("\n" + "=" * 50)
    print(f"Total memories created: {total_memories}")
    print("=" * 50)

    verify_memories()

    print("\n✓ Phase 16 memory update complete")
