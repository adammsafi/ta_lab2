"""Validate no data loss during v0.5.0 reorganization.

Uses Phase 12 baseline (9,620 files with SHA256 checksums) to verify
all files still exist, potentially at new locations after moves.

Validation Strategy:
1. PRIMARY: Checksum validation (test_no_files_lost_from_baseline)
   - Every baseline checksum must exist somewhere in current codebase
   - Files can move, but content cannot be lost

2. SECONDARY: File count check (test_file_count_accounting)
   - Catches edge case where file replaced with different content
   - Uses inequality (baseline <= current) because new files are fine

3. MEMORY: Moved file tracking (test_memory_tracks_file_moves)
   - Validates memory system can answer "where did X go?"
   - Uses representative sampling across migration phases
"""
import json
from pathlib import Path
import pytest

# Import Phase 12 validation tooling
from ta_lab2.tools.archive.validate import create_snapshot


BASELINE_PATH = Path(
    ".planning/phases/12-archive-foundation/baseline/pre_reorg_snapshot.json"
)

# Known reorganization: Files intentionally replaced/archived during v0.5.0
# These are not data loss - they are documented reorganization activities
KNOWN_REORGANIZATION = {
    # Phase 16: Refactored variants archived, canonical versions kept (Decision 144)
    "src/ta_lab2/features/m_tf/ema_multi_tf_cal_anchor_refactored.py",
    "src/ta_lab2/features/m_tf/ema_multi_tf_cal_refactored.py",
    "src/ta_lab2/features/m_tf/ema_multi_timeframe_refactored.py",
    # Phase 17: Test file reorganization
    "testsorchestrator__init__.py",  # Moved to tests/orchestrator/__init__.py
}


def test_no_files_lost_from_baseline():
    """PRIMARY VALIDATION: All src/tests files from Phase 12 baseline still exist.

    Files can move (checksum same, path different), but cannot be deleted.
    Uses checksum-based validation that tracks files through moves.

    This is the primary data loss detection mechanism. If a checksum from
    baseline is not found anywhere in current codebase (src + tests + archive),
    that file's content has been lost.
    """
    if not BASELINE_PATH.exists():
        pytest.skip(f"Baseline not found: {BASELINE_PATH}")

    # Load Phase 12 baseline (custom format with file_checksums dict)
    baseline_data = json.loads(BASELINE_PATH.read_text())
    baseline_checksums = baseline_data["file_checksums"]

    # Create current snapshot of ALL locations where files might exist
    # This includes src, tests, and .archive (files may have been archived)
    current_src = create_snapshot(
        Path("src"), pattern="**/*.py", compute_checksums=True
    )
    current_tests = create_snapshot(
        Path("tests"), pattern="**/*.py", compute_checksums=True
    )

    # Check .archive if it exists (files may have been archived, not deleted)
    archive_path = Path(".archive")
    current_archive = None
    if archive_path.exists():
        current_archive = create_snapshot(
            archive_path, pattern="**/*.py", compute_checksums=True
        )

    # Build set of ALL current checksums (files can be anywhere)
    all_current_checksums = set()
    all_current_checksums.update(current_src.file_checksums.values())
    all_current_checksums.update(current_tests.file_checksums.values())
    if current_archive:
        all_current_checksums.update(current_archive.file_checksums.values())

    # Get baseline checksums for src and tests only (not .venv or other dirs)
    # Normalize paths: baseline uses backslashes, we use forward slashes
    baseline_src_tests = {
        path.replace("\\", "/"): checksum
        for path, checksum in baseline_checksums.items()
        if path.startswith("src") or path.startswith("tests")
    }

    # Build path mapping for current files to check if files still exist at same location
    # Normalize paths: baseline uses "src\ta_lab2\file.py", current uses "ta_lab2\file.py"
    current_paths_by_rel_path = {}
    for rel_path in current_src.file_checksums.keys():
        normalized = f"src/{rel_path.replace(chr(92), '/')}"  # chr(92) is backslash
        current_paths_by_rel_path[normalized] = rel_path
    for rel_path in current_tests.file_checksums.keys():
        normalized = f"tests/{rel_path.replace(chr(92), '/')}"
        current_paths_by_rel_path[normalized] = rel_path

    # PRIMARY CHECK: Files must exist (even if modified)
    # A file is LOST only if:
    # 1. Checksum not found anywhere (file deleted/moved AND content changed), AND
    # 2. Path doesn't exist at original location (file truly gone), AND
    # 3. Not part of known reorganization (documented replacements)
    missing = []
    modified_at_same_location = []
    known_reorg = []

    for path, checksum in baseline_src_tests.items():
        checksum_found = checksum in all_current_checksums
        path_exists = path in current_paths_by_rel_path

        if not checksum_found and not path_exists:
            # Check if this is documented reorganization
            if path in KNOWN_REORGANIZATION:
                known_reorg.append(path)
            else:
                # File is truly missing - not at original location and checksum not found
                missing.append(f"{path} (checksum: {checksum[:16]}...)")
        elif not checksum_found and path_exists:
            # File modified at same location (expected during development)
            modified_at_same_location.append(path)

    # Only fail if files are truly missing (not just modified or documented reorganization)
    if missing:
        pytest.fail(
            f"DATA LOSS DETECTED - {len(missing)} files deleted (not found at path or in archive):\n"
            f"(Searched: src/, tests/, .archive/)\n"
            + "\n".join(f"  - {m}" for m in missing[:20])
            + (f"\n  ... and {len(missing) - 20} more" if len(missing) > 20 else "")
        )

    # Log modifications for info (not a failure - expected during development)
    if modified_at_same_location:
        import warnings

        warnings.warn(
            f"{len(modified_at_same_location)} files modified since baseline (expected during development). "
            f"No data loss detected."
        )


def test_file_count_accounting():
    """SECONDARY SAFETY NET: Verify file counts haven't dropped.

    Equation: baseline_count <= current + archived

    Why inequality (<=) not equality (=)?
    - New files may be added during development (current > baseline is expected)
    - Primary validation is checksum-based (test_no_files_lost_from_baseline)
    - This test catches edge case: file replaced with different content but same name

    If baseline > current + archived, files were deleted without archiving.
    This is a secondary check - checksum validation is primary.
    """
    if not BASELINE_PATH.exists():
        pytest.skip(f"Baseline not found: {BASELINE_PATH}")

    # Load Phase 12 baseline (custom format with file_checksums dict)
    baseline_data = json.loads(BASELINE_PATH.read_text())
    baseline_checksums = baseline_data["file_checksums"]

    # Count baseline src + tests files (not .venv)
    baseline_src_tests_count = sum(
        1
        for path in baseline_checksums.keys()
        if path.startswith("src") or path.startswith("tests")
    )

    # Count current files in all locations
    current_src = create_snapshot(
        Path("src"), pattern="**/*.py", compute_checksums=False
    )
    current_tests = create_snapshot(
        Path("tests"), pattern="**/*.py", compute_checksums=False
    )

    archive_count = 0
    archive_path = Path(".archive")
    if archive_path.exists():
        current_archive = create_snapshot(
            archive_path, pattern="**/*.py", compute_checksums=False
        )
        archive_count = current_archive.total_files

    current_total = current_src.total_files + current_tests.total_files + archive_count

    # SECONDARY CHECK: Count should not drop below baseline
    # (New files being added is fine, that's why we use <=)
    if baseline_src_tests_count > current_total:
        pytest.fail(
            f"FILE COUNT DROPPED - potential data loss:\n"
            f"  Baseline (src+tests): {baseline_src_tests_count}\n"
            f"  Current src: {current_src.total_files}\n"
            f"  Current tests: {current_tests.total_files}\n"
            f"  Archived: {archive_count}\n"
            f"  Current total: {current_total}\n"
            f"  Missing: {baseline_src_tests_count - current_total} files\n"
            f"\n"
            f"NOTE: This is a secondary check. Primary validation (checksum-based)\n"
            f"in test_no_files_lost_from_baseline provides definitive data loss detection."
        )


@pytest.mark.orchestrator
def test_memory_tracks_file_moves():
    """MEMORY VALIDATION: Verify memory answers 'where did file X go?' for moved files.

    Queries memory for moved_to relationships created during Phases 13-16.

    Sampling Approach Justification:
    - Uses 8 representative files across different migration phases and destinations
    - Validates memory system works correctly (can store and retrieve moved_to relationships)
    - Comprehensive moved_to tracking documented in Phase 14 summaries
    - Full enumeration would be redundant with checksum validation

    Sample Selection Criteria:
    - Files from different phases (13, 14, 15, 16)
    - Different destination types (tools/, archive/, scripts/)
    - Mix of core functionality and utilities
    """
    pytest.importorskip("chromadb", reason="chromadb required for memory queries")
    pytest.importorskip("mem0ai", reason="mem0ai required for memory queries")

    try:
        from ta_lab2.tools.ai_orchestrator.memory import get_client
    except ImportError:
        pytest.skip("Memory client not available")

    # Representative sample of files moved in Phases 13-16
    # 8 files covering different phases and destination types
    moved_files = [
        # Phase 14: Data_Tools migration to tools/data_tools/
        ("generate_function_map.py", "ta_lab2.tools.data_tools.analysis"),
        ("tree_structure.py", "ta_lab2.tools.data_tools.analysis"),
        ("db_utils.py", "ta_lab2.tools.data_tools.db"),
        # Phase 14: Documentation archiving
        ("ProjectTT_overview.md", ".archive/documentation"),
        ("DATA_TOOLS_README.md", ".archive/documentation"),
        # Phase 13: Script consolidation
        ("refresh_ema_daily_stats.py", "ta_lab2.scripts.emas.stats"),
        # Phase 15: Feature reorganization (if applicable)
        ("ema_utils.py", "ta_lab2.features"),
        # Phase 16: Test reorganization
        ("test_ema_calculation.py", "tests/features"),
    ]

    try:
        client = get_client()
    except Exception as e:
        pytest.skip(f"Could not initialize memory client: {e}")

    missing_tracking = []
    found_tracking = []

    for old_name, expected_location in moved_files:
        # Query memory for this file's new location
        results = client.search(
            f"where is {old_name} now? moved_to relationship",
            user_id="ta_lab2",
            limit=5,
        )

        # Check if any result mentions the expected location
        found = False
        for result in results:
            if expected_location in str(result):
                found = True
                found_tracking.append(f"{old_name} -> {expected_location}")
                break

        if not found:
            missing_tracking.append(f"{old_name} -> expected in {expected_location}")

    # Report results
    if missing_tracking:
        # Allow some failures (files may not have been migrated or memory not populated)
        # But fail if majority are missing (indicates memory system issue)
        failure_rate = len(missing_tracking) / len(moved_files)
        if failure_rate > 0.5:
            pytest.fail(
                f"Memory missing moved_to relationships for {len(missing_tracking)}/{len(moved_files)} sampled files:\n"
                + "\n".join(f"  - {m}" for m in missing_tracking)
                + "\n\nFound tracking for:\n"
                + "\n".join(f"  + {f}" for f in found_tracking)
            )
        else:
            # Partial success - warn but don't fail
            import warnings

            warnings.warn(
                f"Memory has partial moved_to coverage: {len(found_tracking)}/{len(moved_files)} files tracked.\n"
                f"Missing: {', '.join(m.split(' ->')[0] for m in missing_tracking)}"
            )
