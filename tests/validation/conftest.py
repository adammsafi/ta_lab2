"""
Validation test fixtures.

Provides fixtures for gap detection and alignment validation tests.
Includes validation report generation for dual-output (JSON + markdown).
"""

import os
import pytest
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def test_assets():
    """
    Sample asset IDs for validation tests.

    Returns commonly used asset IDs (BTC=1, ETH=52) for testing.
    """
    return [1, 52]  # BTC, ETH commonly used


@pytest.fixture
def expected_dates():
    """
    Generate expected date range for gap testing.

    Returns a 30-day date range ending today for testing gap detection.
    """
    end = datetime.now().date()
    start = end - timedelta(days=30)
    return pd.date_range(start, end, freq='D')


@pytest.fixture
def mock_dim_sessions():
    """
    Mock trading session data for testing session-aware gap detection.

    Returns session configurations for crypto (24/7) and equity (trading days).
    """
    return {
        'crypto': {
            'session': 'CRYPTO',
            'daily': True,
        },
        'equity': {
            'session': 'NYSE',
            'daily': False,
            'trading_days': [0, 1, 2, 3, 4],  # Monday-Friday
        },
    }


# Database fixtures for CI validation gates
@pytest.fixture(scope="session")
def skip_without_db():
    """Skip test if TARGET_DB_URL not set."""
    url = os.environ.get("TARGET_DB_URL")
    if not url:
        pytest.skip("TARGET_DB_URL not set")


@pytest.fixture(scope="session")
def db_engine():
    """Create SQLAlchemy engine for validation tests.

    Requires TARGET_DB_URL environment variable.
    Session-scoped for efficiency across validation tests.
    """
    url = os.environ.get("TARGET_DB_URL")
    if not url:
        pytest.skip("TARGET_DB_URL not set")

    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Create database session with transaction rollback.

    Function-scoped to ensure test isolation.
    Each test gets a clean transaction that's rolled back after test completion.
    """
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="session")
def ensure_schema(db_engine):
    """Ensure dim_timeframe and dim_sessions tables exist.

    Called once per test session to set up required schema.
    Uses existing ensure_dim_tables script if tables missing.
    """
    from sqlalchemy import inspect

    inspector = inspect(db_engine)
    existing_tables = inspector.get_table_names(schema="public")

    # Check if required dimension tables exist
    required_tables = ["dim_timeframe", "dim_sessions"]
    missing_tables = [t for t in required_tables if t not in existing_tables]

    if missing_tables:
        # Import and run ensure_dim_tables to create missing tables
        from ta_lab2.scripts.bars.ensure_dim_tables import main as ensure_dim_tables
        ensure_dim_tables()

    return db_engine


# ============================================================================
# Validation report generation
# ============================================================================

@pytest.fixture(scope="session")
def validation_summary():
    """
    Track validation test outcomes across session.

    Collects pass/fail counts for each validation category to generate
    summary report at end of test session.

    Returns:
        Dict with category -> {passed: int, failed: int} structure
    """
    return {
        "time_alignment": {"passed": 0, "failed": 0, "skipped": 0},
        "data_consistency": {"passed": 0, "failed": 0, "skipped": 0},
        "backtest_reproducibility": {"passed": 0, "failed": 0, "skipped": 0},
    }


@pytest.fixture(autouse=True)
def collect_validation_result(request, validation_summary):
    """
    Collect validation test results for summary report.

    Automatically tracks pass/fail/skip status for all validation tests.
    Uses test module name to categorize results.
    """
    yield

    # Determine category from test file name
    test_file = request.node.fspath.basename
    category = None

    if 'timeframe_alignment' in test_file or 'calendar_boundaries' in test_file:
        category = "time_alignment"
    elif 'gap_detection' in test_file or 'rowcount_validation' in test_file:
        category = "data_consistency"
    elif 'backtest_reproducibility' in test_file:
        category = "backtest_reproducibility"

    if category is None:
        return  # Not a validation test

    # Record result
    if hasattr(request.node, 'rep_call'):
        if request.node.rep_call.passed:
            validation_summary[category]["passed"] += 1
        elif request.node.rep_call.failed:
            validation_summary[category]["failed"] += 1
        elif request.node.rep_call.skipped:
            validation_summary[category]["skipped"] += 1


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Store test results for later access by collect_validation_result.

    This hook captures test outcomes and attaches them to the test node.
    """
    outcome = yield
    rep = outcome.get_result()

    # Store report on the item for access in fixture
    setattr(item, f"rep_{rep.when}", rep)


def pytest_sessionfinish(session, exitstatus):
    """
    Generate validation summary after all tests complete.

    Creates markdown report summarizing validation test results across
    all three validation categories (time alignment, data consistency,
    backtest reproducibility).

    Report saved to: reports/validation_summary.md
    """
    if not hasattr(session.config, 'validation_summary_data'):
        # No validation tests ran
        return

    summary_data = session.config.validation_summary_data

    # Create reports directory if needed
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    # Generate markdown report
    report_path = reports_dir / "validation_summary.md"

    with open(report_path, 'w') as f:
        f.write("# Validation Test Summary\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # Overall status
        total_passed = sum(cat["passed"] for cat in summary_data.values())
        total_failed = sum(cat["failed"] for cat in summary_data.values())
        total_skipped = sum(cat["skipped"] for cat in summary_data.values())

        overall_status = "PASS" if total_failed == 0 else "FAIL"
        f.write(f"**Overall Status:** {overall_status}\n\n")

        f.write("## Summary by Category\n\n")
        f.write("| Category | Passed | Failed | Skipped | Status |\n")
        f.write("|----------|--------|--------|---------|--------|\n")

        for category, counts in summary_data.items():
            status = "PASS" if counts["failed"] == 0 else "FAIL"
            display_name = category.replace('_', ' ').title()

            f.write(
                f"| {display_name} | {counts['passed']} | {counts['failed']} | "
                f"{counts['skipped']} | {status} |\n"
            )

        f.write("\n## Details\n\n")

        # Time Alignment
        f.write("### Time Alignment Validation\n\n")
        if summary_data["time_alignment"]["failed"] == 0:
            f.write("All timeframe alignment checks passed.\n\n")
        else:
            f.write(
                f"**FAILED:** {summary_data['time_alignment']['failed']} tests failed. "
                "Check pytest output for details.\n\n"
            )

        # Data Consistency
        f.write("### Data Consistency Validation\n\n")
        if summary_data["data_consistency"]["failed"] == 0:
            f.write("All gap detection and rowcount checks passed.\n\n")
        else:
            f.write(
                f"**FAILED:** {summary_data['data_consistency']['failed']} tests failed. "
                "Check pytest output for details.\n\n"
            )

        # Backtest Reproducibility
        f.write("### Backtest Reproducibility Validation\n\n")
        if summary_data["backtest_reproducibility"]["failed"] == 0:
            f.write("All reproducibility checks passed. Backtests are deterministic.\n\n")
        else:
            f.write(
                f"**FAILED:** {summary_data['backtest_reproducibility']['failed']} tests failed. "
                "Backtests are NOT reproducible. This is a critical issue.\n\n"
            )

        # Release readiness
        f.write("## Release Readiness\n\n")
        if total_failed == 0:
            f.write("**Status:** READY FOR RELEASE\n\n")
            f.write("All validation gates passed. System is ready for v0.4.0 release.\n")
        else:
            f.write("**Status:** NOT READY FOR RELEASE\n\n")
            f.write(
                f"**Blockers:** {total_failed} validation tests failed. "
                "All validation tests must pass before release.\n"
            )

    print(f"\nValidation summary written to: {report_path}")


@pytest.fixture(scope="session", autouse=True)
def setup_validation_summary(request, validation_summary):
    """
    Setup validation summary collection at session start.

    Attaches validation_summary to session config for access in
    pytest_sessionfinish hook.
    """
    request.config.validation_summary_data = validation_summary
    yield
