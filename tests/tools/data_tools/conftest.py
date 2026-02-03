"""Shared fixtures for data_tools tests."""
import pytest
from pathlib import Path


@pytest.fixture
def data_tools_root():
    """Path to data_tools package."""
    return (
        Path(__file__).parent.parent.parent.parent
        / "src"
        / "ta_lab2"
        / "tools"
        / "data_tools"
    )
