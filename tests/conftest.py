from pathlib import Path
import os
import pandas as pd
import pytest


@pytest.fixture
def tiny_csv(tmp_path: Path) -> Path:
    df = pd.DataFrame({
        "Date": ["2024-01-01","2024-01-02","2024-01-03"],
        "Open": [100, 101, 102],
        "High": [101, 102, 103],
        "Low":  [ 99, 100, 101],
        "Close":[100.5, 101.5, 102.5],
        "Volume": [1000, 1200, 1100],
        "Market Cap": [1e9, 1.01e9, 1.02e9],
    })
    p = tmp_path / "tiny.csv"
    df.to_csv(p, index=False)
    return p


# ============================================================================
# Infrastructure fixtures for three-tier test pattern
# ============================================================================


@pytest.fixture(scope="session")
def database_url():
    """Get database URL from environment or skip test."""
    url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("No database URL configured (set TARGET_DB_URL or DATABASE_URL)")
    return url


@pytest.fixture(scope="session")
def database_engine(database_url):
    """Create SQLAlchemy engine for testing."""
    from sqlalchemy import create_engine
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def skip_without_database():
    """Skip test if database is not available."""
    url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("Database not available")


@pytest.fixture(scope="function")
def skip_without_qdrant():
    """Skip test if Qdrant is not running."""
    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))

    # Try to connect to Qdrant
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex((qdrant_host, qdrant_port))
    sock.close()

    if result != 0:
        pytest.skip(f"Qdrant not running at {qdrant_host}:{qdrant_port}")


def pytest_configure(config):
    """Validate pytest configuration at startup."""
    # Verify markers are registered
    markers = [
        "real_deps",
        "mixed_deps",
        "mocked_deps",
        "integration",
        "observability",
        "validation",
        "slow",
    ]

    # This is called automatically by pytest - markers should be in pyproject.toml
    # Just validate they're accessible
    for marker in markers:
        config.addinivalue_line(
            "markers",
            f"{marker}: Marker defined in pyproject.toml"
        )
