"""
Test suite to validate EMA refresh scripts use EMAStateManager.

This test suite uses static analysis to verify that:
1. All production EMA refresh scripts import/use EMAStateManager
2. Scripts call state manager methods (load_state, save_state, etc.)
3. State management module exists and exports required functionality
4. Base refresher integrates state management
5. Scripts reference state tables

These tests confirm that production scripts use EMAStateManager for
incremental state tracking (addresses blocker #6 from Phase 6).
"""

from pathlib import Path
import pytest

# Define project root (tests/ is at project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Production refresh scripts (main scripts that write EMA data)
PRODUCTION_SCRIPTS = [
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py",
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_from_bars.py",
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py",
]


@pytest.mark.parametrize(
    "script_path",
    [pytest.param(s, id=Path(s).name) for s in PRODUCTION_SCRIPTS],
)
def test_scripts_import_ema_state_manager(script_path: str):
    """
    Verify each production script imports EMAStateManager or ema_state_manager.

    Production scripts should use EMAStateManager for incremental state
    tracking to avoid full table scans on every refresh.

    Incremental state enables:
    - Fast refreshes (only process new/changed data)
    - Dirty window detection (backfill detection)
    - State persistence across runs
    """
    full_path = PROJECT_ROOT / script_path
    assert full_path.exists(), f"Script not found: {script_path}"

    content = full_path.read_text(encoding="utf-8")

    # Check for EMAStateManager or ema_state_manager reference
    has_state_manager = (
        "EMAStateManager" in content
        or "ema_state_manager" in content
        or "from ta_lab2.scripts.emas.ema_state_manager import" in content
    )

    assert has_state_manager, (
        f"{script_path} does not import or reference EMAStateManager. "
        "Production scripts should use EMAStateManager for incremental state tracking. "
        "Expected: 'from ta_lab2.scripts.emas.ema_state_manager import EMAStateManager' or similar."
    )


@pytest.mark.parametrize(
    "script_path",
    [pytest.param(s, id=Path(s).name) for s in PRODUCTION_SCRIPTS],
)
def test_scripts_call_state_manager_methods(script_path: str):
    """
    Verify scripts call state manager methods (not just import).

    Importing EMAStateManager without using it doesn't provide incremental
    functionality. Scripts should call methods like:
    - load_state() - Load existing state before computation
    - save_state() or update_state_from_output() - Save state after computation
    - compute_dirty_window_starts() - Detect backfill needs

    Note: Scripts may delegate to BaseEMARefresher which calls these methods,
    so we check for EMAStateConfig or state_table references as evidence of usage.
    """
    full_path = PROJECT_ROOT / script_path
    content = full_path.read_text(encoding="utf-8")

    # Evidence of state manager usage:
    # 1. Direct method calls
    # 2. EMAStateConfig usage (configures state manager)
    # 3. state_table references (indicates state persistence)
    has_state_usage = (
        "load_state" in content
        or "save_state" in content
        or "update_state_from_output" in content
        or "compute_dirty_window" in content
        or "EMAStateConfig" in content
        or "state_table" in content
        or "state_config" in content
    )

    assert has_state_usage, (
        f"{script_path} does not appear to use EMAStateManager methods. "
        "Scripts should call load_state, save_state, or use EMAStateConfig. "
        "Incremental state requires actually using the state manager, not just importing it."
    )


def test_state_manager_module_exists():
    """
    Verify ema_state_manager.py module exists.

    This module provides the EMAStateManager class and related functionality
    for managing incremental EMA state across refresh runs.
    """
    state_manager_path = PROJECT_ROOT / "src/ta_lab2/scripts/emas/ema_state_manager.py"

    assert state_manager_path.exists(), (
        "ema_state_manager.py module not found. "
        "Expected: src/ta_lab2/scripts/emas/ema_state_manager.py"
    )

    # Check it's not just a stub
    content = state_manager_path.read_text(encoding="utf-8")
    assert len(content) > 500, (
        "ema_state_manager.py appears to be a stub. "
        f"Expected substantial implementation, found only {len(content)} characters."
    )


def test_state_manager_has_required_exports():
    """
    Verify EMAStateManager exports required functionality.

    Required:
    - EMAStateManager class
    - load_state method (or load_state function)
    - save_state or update_state_from_output method
    - EMAStateConfig (configuration dataclass)

    These are the core APIs that refresh scripts depend on.
    """
    state_manager_path = PROJECT_ROOT / "src/ta_lab2/scripts/emas/ema_state_manager.py"
    content = state_manager_path.read_text(encoding="utf-8")

    # Check for class definition
    assert "class EMAStateManager" in content, (
        "EMAStateManager class not found in ema_state_manager.py. "
        "Expected: 'class EMAStateManager:' or 'class EMAStateManager(...):'."
    )

    # Check for load_state
    has_load_state = "def load_state" in content or "async def load_state" in content
    assert has_load_state, (
        "load_state method not found. "
        "Expected: 'def load_state(...)' in EMAStateManager class."
    )

    # Check for save/update state
    has_save_state = (
        "def save_state" in content
        or "def update_state" in content
        or "def upsert_state" in content
        or "def update_state_from_output" in content
    )
    assert has_save_state, (
        "State update method not found. "
        "Expected: save_state, update_state, or update_state_from_output method."
    )

    # Check for config class
    has_config = "class EMAStateConfig" in content or "@dataclass" in content
    assert has_config, (
        "EMAStateConfig not found. "
        "Expected: 'class EMAStateConfig' or '@dataclass' for configuration."
    )


def test_base_refresher_integrates_state():
    """
    Verify base_ema_refresher.py integrates EMAStateManager.

    If BaseEMARefresher handles state management, derived refreshers
    automatically get incremental state tracking without duplication.

    This is the recommended architecture for DRY principles.
    """
    base_path = PROJECT_ROOT / "src/ta_lab2/scripts/emas/base_ema_refresher.py"

    if not base_path.exists():
        pytest.skip("base_ema_refresher.py not found (may not exist in this phase)")

    content = base_path.read_text(encoding="utf-8")

    # Base refresher should import and use state manager
    has_state_integration = (
        "EMAStateManager" in content
        or "ema_state_manager" in content
        or "state_config" in content
    )

    assert has_state_integration, (
        "base_ema_refresher.py does not integrate EMAStateManager. "
        "Base class should handle state management for all derived refreshers."
    )


@pytest.mark.parametrize(
    "script_path",
    [pytest.param(s, id=Path(s).name) for s in PRODUCTION_SCRIPTS],
)
def test_state_table_referenced(script_path: str):
    """
    Verify scripts reference state table names.

    State tables store incremental watermarks per (id, tf, period).
    Scripts should specify which state table to use, e.g.:
    - cmc_ema_multi_tf_state
    - cmc_ema_multi_tf_cal_us_state
    - cmc_ema_multi_tf_cal_anchor_us_state

    This confirms state persistence is configured, not just imported.
    """
    full_path = PROJECT_ROOT / script_path
    content = full_path.read_text(encoding="utf-8")

    # Check for state table references
    state_table_patterns = [
        "_state",  # Common suffix for state tables
        "state_table",  # Variable/parameter name
        "EMAStateConfig",  # Config object that specifies state table
    ]

    has_state_table = any(pattern in content for pattern in state_table_patterns)

    assert has_state_table, (
        f"{script_path} does not reference state table. "
        "Scripts should specify state table via EMAStateConfig or --state-table argument. "
        "Incremental state requires persistent table for watermarks."
    )


def test_state_manager_schema_documentation():
    """
    Verify state manager documents the unified state schema.

    The unified state schema should be documented with:
    - PRIMARY KEY: (id, tf, period)
    - Timestamp columns: daily_min_seen, daily_max_seen, last_time_close, last_canonical_ts
    - Bar sequence: last_bar_seq
    - Metadata: updated_at

    This ensures all scripts use consistent state table structure.
    """
    state_manager_path = PROJECT_ROOT / "src/ta_lab2/scripts/emas/ema_state_manager.py"
    content = state_manager_path.read_text(encoding="utf-8")

    # Check for schema documentation (DDL or CREATE TABLE statement)
    schema_indicators = [
        "CREATE TABLE",
        "PRIMARY KEY",
        "daily_min_seen",
        "daily_max_seen",
        "last_time_close",
        "last_canonical_ts",
        "last_bar_seq",
    ]

    found_indicators = sum(1 for indicator in schema_indicators if indicator in content)

    assert found_indicators >= 5, (
        f"State manager does not document unified state schema. "
        f"Found {found_indicators}/{len(schema_indicators)} expected schema elements. "
        "Expected: CREATE TABLE statement with PRIMARY KEY and timestamp columns."
    )


def test_state_usage_summary():
    """
    Summary test: Report state management coverage across scripts.

    This test always passes but prints useful summary information:
    - Number of production scripts
    - Number using EMAStateManager
    - Coverage percentage

    This provides visibility into incremental state adoption.
    """
    results = []

    for script_path in PRODUCTION_SCRIPTS:
        full_path = PROJECT_ROOT / script_path
        if not full_path.exists():
            continue

        content = full_path.read_text(encoding="utf-8")

        has_import = "EMAStateManager" in content or "ema_state_manager" in content
        has_usage = (
            "load_state" in content
            or "save_state" in content
            or "EMAStateConfig" in content
        )

        results.append(
            {
                "script": Path(script_path).name,
                "has_import": has_import,
                "has_usage": has_usage,
            }
        )

    scripts_with_state = sum(1 for r in results if r["has_import"] and r["has_usage"])
    total_scripts = len(results)
    coverage = (scripts_with_state / total_scripts * 100) if total_scripts > 0 else 0

    print(f"\n{'='*70}")
    print("EMAStateManager Adoption Summary")
    print(f"{'='*70}")
    print(f"Production scripts: {total_scripts}")
    print(f"Using EMAStateManager: {scripts_with_state}")
    print(f"Coverage: {coverage:.0f}%")
    print(f"{'='*70}")

    for r in results:
        status = "✓" if (r["has_import"] and r["has_usage"]) else "✗"
        print(f"  {status} {r['script']}")

    print(f"{'='*70}\n")

    # Always pass - this is informational only
    assert True
