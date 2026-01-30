"""
Test suite to validate EMA refresh scripts use dim_timeframe module.

This test suite uses static analysis to verify that:
1. All active EMA refresh scripts import from dim_timeframe
2. Scripts call list_tfs() to get TF definitions
3. No hardcoded TF arrays exist in active scripts
4. Old scripts are deprecated but preserved
5. Active scripts don't depend on deprecated code

These tests confirm SUCCESS CRITERION #4 from Phase 6 Plan 03:
"All active EMA refresh scripts reference dim_timeframe instead of hardcoded values"
"""

from pathlib import Path
import pytest

# Define project root (tests/ is at project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Active refresh scripts (production code)
ACTIVE_REFRESH_SCRIPTS = [
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py",
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_v2.py",
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_from_bars.py",
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py",
]

# Scripts that use dim_timeframe directly (import list_tfs)
DIRECT_DIM_TF_SCRIPTS = [
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py",
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_v2.py",
]

# Scripts that use dim_timeframe indirectly (via feature modules)
INDIRECT_DIM_TF_SCRIPTS = [
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_from_bars.py",
    "src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py",
]

# Feature modules used by calendar scripts
CALENDAR_FEATURE_MODULES = [
    "src/ta_lab2/features/m_tf/ema_multi_tf_cal.py",
    "src/ta_lab2/features/m_tf/ema_multi_tf_cal_anchor.py",
]

# Stats scripts (also production code)
STATS_SCRIPTS = [
    "src/ta_lab2/scripts/emas/stats/multi_tf/refresh_ema_multi_tf_stats.py",
    "src/ta_lab2/scripts/emas/stats/multi_tf_cal/refresh_ema_multi_tf_cal_stats.py",
    "src/ta_lab2/scripts/emas/stats/multi_tf_v2/refresh_ema_multi_tf_v2_stats.py",
    "src/ta_lab2/scripts/emas/stats/multi_tf_cal_anchor/refresh_ema_multi_tf_cal_anchor_stats.py",
]


@pytest.mark.parametrize(
    "script_path",
    [pytest.param(s, id=Path(s).name) for s in DIRECT_DIM_TF_SCRIPTS],
)
def test_scripts_import_dim_timeframe(script_path: str):
    """
    Verify scripts that directly use dim_timeframe import from that module.

    Direct usage: Scripts that call list_tfs() directly.
    Indirect usage: Calendar scripts that delegate to feature modules.

    This ensures scripts get TF definitions from centralized dim_timeframe
    table instead of hardcoding values.
    """
    full_path = PROJECT_ROOT / script_path
    assert full_path.exists(), f"Script not found: {script_path}"

    content = full_path.read_text(encoding="utf-8")

    # Check for import statement
    assert "from ta_lab2.time.dim_timeframe import" in content, (
        f"{script_path} does not import from dim_timeframe module. "
        "Expected: 'from ta_lab2.time.dim_timeframe import list_tfs' or similar."
    )


@pytest.mark.parametrize(
    "script_path",
    [pytest.param(s, id=Path(s).name) for s in DIRECT_DIM_TF_SCRIPTS],
)
def test_scripts_call_list_tfs(script_path: str):
    """
    Verify scripts that directly use dim_timeframe call list_tfs().

    This function dynamically loads timeframes from dim_timeframe table,
    ensuring consistency across all EMA computations.

    Note: Calendar scripts use dim_timeframe indirectly through their
    feature modules, so they don't call list_tfs() directly.
    """
    full_path = PROJECT_ROOT / script_path
    content = full_path.read_text(encoding="utf-8")

    # Check for function call
    assert "list_tfs(" in content, (
        f"{script_path} does not call list_tfs() function. "
        "Scripts should use list_tfs() to get TF definitions from dim_timeframe."
    )


@pytest.mark.parametrize(
    "script_path",
    [pytest.param(s, id=Path(s).name) for s in ACTIVE_REFRESH_SCRIPTS],
)
def test_no_hardcoded_tf_arrays(script_path: str):
    """
    Verify no hardcoded TF arrays exist in active scripts.

    Hardcoded TFs like ["1D", "7D", "30D"] defeat the purpose of
    centralized dim_timeframe table. TFs should come from list_tfs().

    Note: DEFAULT_PERIODS for EMA periods (e.g., [9, 10, 21]) is OK.
    We're checking for TF definitions, not period lists.
    """
    full_path = PROJECT_ROOT / script_path
    content = full_path.read_text(encoding="utf-8")

    # Patterns that indicate hardcoded TF lists
    hardcoded_patterns = [
        '["1D"',  # Start of TF array
        "['1D'",  # Single quotes variant
        'tfs = ["',  # Variable assignment with TF array
        "tfs = ['",  # Variable assignment single quotes
    ]

    for pattern in hardcoded_patterns:
        assert pattern not in content, (
            f"{script_path} contains hardcoded TF array pattern: {pattern}. "
            "Use list_tfs() from dim_timeframe instead."
        )


@pytest.mark.parametrize(
    "feature_path",
    [pytest.param(f, id=Path(f).name) for f in CALENDAR_FEATURE_MODULES],
)
def test_calendar_feature_modules_use_dim(feature_path: str):
    """
    Verify calendar feature modules query dim_timeframe table.

    Calendar scripts (cal/cal_anchor) delegate TF loading to their
    feature modules, which should query dim_timeframe via SQL.

    This ensures calendar EMAs also use centralized TF definitions.
    """
    full_path = PROJECT_ROOT / feature_path

    if not full_path.exists():
        pytest.skip(f"Feature module not found: {feature_path}")

    content = full_path.read_text(encoding="utf-8")

    # Check for dim_timeframe reference (usually in SQL queries)
    assert "dim_timeframe" in content, (
        f"{feature_path} does not reference dim_timeframe. "
        "Calendar feature modules should query dim_timeframe table for TF specs."
    )

    # Should query for calendar alignment
    assert "alignment_type = 'calendar'" in content or "alignment_type='calendar'" in content, (
        f"{feature_path} does not query for calendar alignment. "
        "Expected SQL: WHERE alignment_type = 'calendar'"
    )


def test_base_ema_refresher_uses_dim():
    """
    Verify base_ema_refresher.py imports from dim_timeframe.

    If the base class imports dim_timeframe, all derived refreshers
    inherit this dependency, ensuring consistency.
    """
    base_path = PROJECT_ROOT / "src/ta_lab2/scripts/emas/base_ema_refresher.py"

    if not base_path.exists():
        pytest.skip("base_ema_refresher.py not found (may not exist in this phase)")

    content = base_path.read_text(encoding="utf-8")

    # Base class should import or reference dim_timeframe
    # (May be abstract and delegate to subclasses, so this is a soft check)
    has_import = "from ta_lab2.time.dim_timeframe import" in content
    has_reference = "dim_timeframe" in content

    assert has_import or has_reference, (
        "base_ema_refresher.py should import or reference dim_timeframe "
        "to enforce centralized TF definitions."
    )


@pytest.mark.parametrize(
    "script_path",
    [pytest.param(s, id=Path(s).name) for s in STATS_SCRIPTS],
)
def test_stats_scripts_use_dim(script_path: str):
    """
    Verify stats scripts also use dim_timeframe for TF validation.

    Stats scripts validate EMA output against dim_timeframe definitions,
    so they need to import and use the centralized TF model.
    """
    full_path = PROJECT_ROOT / script_path

    if not full_path.exists():
        pytest.skip(f"Stats script not found: {script_path}")

    content = full_path.read_text(encoding="utf-8")

    # Stats scripts should reference dim_timeframe (usually in SQL queries)
    assert "dim_timeframe" in content, (
        f"{script_path} does not reference dim_timeframe. "
        "Stats scripts should validate TFs against dim_timeframe table."
    )


def test_old_scripts_are_deprecated():
    """
    Verify scripts in old/ directory exist (not deleted) but are deprecated.

    Old scripts are preserved for reference and rollback capability,
    but should not be imported or used by active code.
    """
    old_dir = PROJECT_ROOT / "src/ta_lab2/scripts/emas/old"

    assert old_dir.exists(), (
        "old/ directory should exist to preserve deprecated scripts. "
        "Don't delete old code - move it to old/ for reference."
    )

    # Check that old directory contains Python files
    old_scripts = list(old_dir.glob("refresh_*.py"))
    assert len(old_scripts) > 0, (
        "old/ directory should contain deprecated refresh scripts. "
        f"Found {len(old_scripts)} scripts."
    )


def test_count_active_vs_deprecated():
    """
    Report ratio of active vs deprecated scripts.

    Refactoring should reduce code duplication, so we expect:
    - Active scripts: small number (4 main + 4 stats = 8)
    - Deprecated scripts: larger number (~14+)

    This confirms the refactoring reduced duplication successfully.
    """
    old_dir = PROJECT_ROOT / "src/ta_lab2/scripts/emas/old"

    if not old_dir.exists():
        pytest.skip("old/ directory not found")

    # Count active scripts
    active_count = len(ACTIVE_REFRESH_SCRIPTS) + len(STATS_SCRIPTS)

    # Count deprecated scripts (recursive to catch old/ subdirs in stats/)
    deprecated_scripts = list(old_dir.rglob("refresh_*.py"))
    # Also check stats/*/old/ directories
    stats_old_dirs = (PROJECT_ROOT / "src/ta_lab2/scripts/emas/stats").rglob("old/refresh_*.py")
    deprecated_scripts.extend(stats_old_dirs)
    deprecated_count = len(set(deprecated_scripts))  # Remove duplicates

    print(f"\nRefactoring summary:")
    print(f"  Active scripts: {active_count}")
    print(f"  Deprecated scripts: {deprecated_count}")
    print(f"  Ratio: {deprecated_count / active_count:.1f}x code reduction")

    # Assert that refactoring actually reduced duplication
    # (We should have fewer active scripts than deprecated)
    assert active_count < deprecated_count, (
        f"Expected refactoring to reduce code. "
        f"Active: {active_count}, Deprecated: {deprecated_count}. "
        f"Active should be < Deprecated."
    )


@pytest.mark.parametrize(
    "script_path",
    [pytest.param(s, id=Path(s).name) for s in ACTIVE_REFRESH_SCRIPTS],
)
def test_no_active_script_imports_old(script_path: str):
    """
    Verify active scripts don't import from old/ directory.

    Active scripts should not depend on deprecated code.
    All shared logic should be in base classes or utility modules.
    """
    full_path = PROJECT_ROOT / script_path
    content = full_path.read_text(encoding="utf-8")

    # Check for imports from old directory
    old_import_patterns = [
        "from ta_lab2.scripts.emas.old",
        "from .old",
        "import ta_lab2.scripts.emas.old",
    ]

    for pattern in old_import_patterns:
        assert pattern not in content, (
            f"{script_path} imports from old/ directory: {pattern}. "
            "Active scripts should not depend on deprecated code."
        )
