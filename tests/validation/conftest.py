"""
Validation test fixtures.

Provides fixtures for gap detection and alignment validation tests.
"""

import os
import pytest
import pandas as pd
from datetime import datetime, timedelta
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
