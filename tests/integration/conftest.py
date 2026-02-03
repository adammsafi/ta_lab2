"""
Integration test fixtures.

Provides fixtures for testing cross-component interactions with flexible
dependency management (real infrastructure, mixed, or fully mocked).
"""

import pytest


@pytest.fixture(scope="function")
def clean_database(database_engine):
    """
    Transaction rollback for test isolation.

    Yields a connection with an open transaction that rolls back after test.
    """
    connection = database_engine.connect()
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()


@pytest.fixture
def mock_orchestrator(mocker):
    """
    Mocked orchestrator for testing without real AI APIs.

    Returns a MagicMock with AsyncMock for async methods.
    """
    from ta_lab2.tools.ai_orchestrator.execution import AsyncOrchestrator

    mock = mocker.MagicMock(spec=AsyncOrchestrator)

    # Mock async execute_single with AsyncMock
    mock.execute_single = mocker.AsyncMock(
        return_value=mocker.MagicMock(
            output="Test output",
            success=True,
            error=None,
        )
    )

    return mock


@pytest.fixture
def mock_memory_client(mocker):
    """
    Mocked memory client for testing without real Qdrant/OpenAI.

    Returns a mock that simulates Mem0 memory operations.
    """
    mock = mocker.MagicMock()

    # Mock search returns Mem0 format: {"results": [...]}
    mock.search.return_value = {
        "results": [
            {
                "id": "test_memory_1",
                "content": "Test memory content",
                "metadata": {"created_at": "2024-01-01T00:00:00Z"},
            }
        ]
    }

    # Mock add returns memory ID
    mock.add.return_value = "test_memory_1"

    return mock


@pytest.fixture
def test_task():
    """
    Sample task for testing orchestrator integration.

    Returns a basic Task object for testing routing and execution.
    """
    from ta_lab2.tools.ai_orchestrator.core import Task, TaskType

    return Task(
        type=TaskType.CODE_ANALYSIS,
        prompt="Test task: analyze sample data",
    )
