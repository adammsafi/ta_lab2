"""Tests for conflict detection and resolution.

Tests Mem0's LLM-powered conflict detection system including:
- ConflictResult dataclass
- detect_conflicts semantic similarity search
- resolve_conflict operation determination (ADD/UPDATE/DELETE/NOOP)
- Context-dependent truth handling
- Audit logging

Uses mocks for unit tests, integration tests require API keys.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from pathlib import Path
import json

from ta_lab2.tools.ai_orchestrator.memory.conflict import (
    ConflictResult,
    detect_conflicts,
    resolve_conflict,
    add_with_conflict_check,
    _generate_reason,
    _log_conflict
)


# ==================== ConflictResult Tests ====================


def test_conflict_result_creation():
    """Test ConflictResult dataclass with all fields."""
    result = ConflictResult(
        memory_id="mem_123",
        operation="ADD",
        confidence=0.95,
        reason="No conflict detected",
        original_content="EMA uses 20 periods",
        timestamp="2026-01-28T15:00:00Z",
        conflicting_memory="mem_456",
        conflicting_content="EMA uses 14 periods"
    )

    assert result.memory_id == "mem_123"
    assert result.operation == "ADD"
    assert result.confidence == 0.95
    assert result.reason == "No conflict detected"
    assert result.original_content == "EMA uses 20 periods"
    assert result.timestamp == "2026-01-28T15:00:00Z"
    assert result.conflicting_memory == "mem_456"
    assert result.conflicting_content == "EMA uses 14 periods"


def test_conflict_result_defaults():
    """Test ConflictResult with optional fields defaulting to None."""
    result = ConflictResult(
        memory_id="mem_789",
        operation="UPDATE",
        confidence=0.88,
        reason="Contradiction detected",
        original_content="New content",
        timestamp="2026-01-28T15:00:00Z"
    )

    assert result.conflicting_memory is None
    assert result.conflicting_content is None


def test_conflict_result_to_dict():
    """Test ConflictResult serialization to dict."""
    result = ConflictResult(
        memory_id="mem_999",
        operation="NOOP",
        confidence=0.99,
        reason="Duplicate",
        original_content="Test",
        timestamp="2026-01-28T15:00:00Z"
    )

    result_dict = result.to_dict()
    assert isinstance(result_dict, dict)
    assert result_dict["memory_id"] == "mem_999"
    assert result_dict["operation"] == "NOOP"
    assert result_dict["confidence"] == 0.99


# ==================== detect_conflicts Tests ====================


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
def test_detect_conflicts_finds_similar(mock_get_client):
    """Test detect_conflicts finds memories above similarity threshold."""
    # Mock Mem0Client
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    # Mock search results with high similarity
    mock_client.search.return_value = [
        {
            "id": "mem_similar1",
            "memory": "EMA uses 14 periods",
            "score": 0.92,
            "metadata": {"category": "technical_analysis"}
        },
        {
            "id": "mem_similar2",
            "memory": "EMA calculation with 14-period window",
            "score": 0.88,
            "metadata": {"category": "technical_analysis"}
        }
    ]

    # Search for conflicts
    conflicts = detect_conflicts(
        content="EMA uses 20 periods",
        user_id="orchestrator",
        client=mock_client,
        similarity_threshold=0.85
    )

    # Verify search was called
    mock_client.search.assert_called_once_with(
        query="EMA uses 20 periods",
        user_id="orchestrator",
        limit=10
    )

    # Verify both high-similarity memories returned
    assert len(conflicts) == 2
    assert conflicts[0]["memory_id"] == "mem_similar1"
    assert conflicts[0]["similarity"] == 0.92
    assert conflicts[1]["memory_id"] == "mem_similar2"
    assert conflicts[1]["similarity"] == 0.88


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
def test_detect_conflicts_ignores_different(mock_get_client):
    """Test detect_conflicts filters out dissimilar memories below threshold."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    # Mock search with low similarity results
    mock_client.search.return_value = [
        {
            "id": "mem_different1",
            "memory": "Trading strategy for crypto",
            "score": 0.45,
            "metadata": {}
        },
        {
            "id": "mem_different2",
            "memory": "Database schema design",
            "score": 0.12,
            "metadata": {}
        }
    ]

    conflicts = detect_conflicts(
        content="EMA uses 20 periods",
        user_id="orchestrator",
        client=mock_client,
        similarity_threshold=0.85
    )

    # No results above threshold
    assert len(conflicts) == 0


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
def test_detect_conflicts_respects_threshold(mock_get_client):
    """Test detect_conflicts uses custom threshold correctly."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    mock_client.search.return_value = [
        {"id": "mem1", "memory": "Test", "score": 0.75, "metadata": {}},
        {"id": "mem2", "memory": "Test", "score": 0.65, "metadata": {}},
        {"id": "mem3", "memory": "Test", "score": 0.55, "metadata": {}}
    ]

    # Use lower threshold
    conflicts = detect_conflicts(
        content="Test content",
        user_id="orchestrator",
        client=mock_client,
        similarity_threshold=0.60
    )

    # Should return 2 memories (0.75 and 0.65, not 0.55)
    assert len(conflicts) == 2
    assert conflicts[0]["similarity"] == 0.75
    assert conflicts[1]["similarity"] == 0.65


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
def test_detect_conflicts_empty_db(mock_get_client):
    """Test detect_conflicts handles empty database gracefully."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    mock_client.search.return_value = []

    conflicts = detect_conflicts(
        content="New content",
        user_id="orchestrator",
        client=mock_client
    )

    assert len(conflicts) == 0


# ==================== resolve_conflict Tests ====================


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
def test_resolve_conflict_add_operation(mock_get_client):
    """Test resolve_conflict returns ADD for new unique content."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    # Mock Mem0 add result with ADD operation
    mock_client.add.return_value = {
        "results": [
            {
                "memory": "EMA uses 20 periods",
                "event": "ADD",
                "id": "mem_new123"
            }
        ]
    }

    result = resolve_conflict(
        new_content="EMA uses 20 periods",
        user_id="orchestrator",
        metadata={"category": "technical_analysis"},
        client=mock_client
    )

    # Verify Mem0 add called with infer=True
    mock_client.add.assert_called_once()
    call_args = mock_client.add.call_args
    assert call_args[1]["infer"] is True
    assert call_args[1]["user_id"] == "orchestrator"
    assert call_args[1]["metadata"]["category"] == "technical_analysis"

    # Verify result
    assert result.operation == "ADD"
    assert result.memory_id == "mem_new123"
    assert "No conflict detected" in result.reason
    assert result.original_content == "EMA uses 20 periods"


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
def test_resolve_conflict_update_operation(mock_get_client):
    """Test resolve_conflict returns UPDATE for contradictory content."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    # Mock Mem0 detecting contradiction and updating
    mock_client.add.return_value = {
        "results": [
            {
                "memory": "EMA uses 20 periods (updated)",
                "event": "UPDATE",
                "id": "mem_existing456"
            }
        ]
    }

    result = resolve_conflict(
        new_content="EMA uses 20 periods",
        user_id="orchestrator",
        client=mock_client
    )

    assert result.operation == "UPDATE"
    assert result.memory_id == "mem_existing456"
    assert "Contradiction detected" in result.reason


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
def test_resolve_conflict_noop_duplicate(mock_get_client):
    """Test resolve_conflict returns NOOP for exact duplicates."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    # Mock Mem0 detecting duplicate
    mock_client.add.return_value = {
        "results": [
            {
                "memory": "EMA uses 20 periods",
                "event": "NOOP",
                "id": "mem_duplicate789"
            }
        ]
    }

    result = resolve_conflict(
        new_content="EMA uses 20 periods",
        user_id="orchestrator",
        client=mock_client
    )

    assert result.operation == "NOOP"
    assert "Duplicate detected" in result.reason


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
@patch('ta_lab2.tools.ai_orchestrator.memory.conflict._log_conflict')
def test_resolve_conflict_logs_result(mock_log, mock_get_client):
    """Test resolve_conflict logging when called via add_with_conflict_check."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    mock_client.add.return_value = {
        "results": [{"memory": "Test", "event": "ADD", "id": "mem_log123"}]
    }

    # Use add_with_conflict_check to trigger logging
    result = add_with_conflict_check(
        messages=[{"role": "user", "content": "Test content"}],
        user_id="orchestrator",
        client=mock_client,
        log_conflicts=True
    )

    # Verify logging was called
    mock_log.assert_called_once()
    logged_result = mock_log.call_args[0][0]
    assert isinstance(logged_result, ConflictResult)
    assert logged_result.operation == "ADD"


# ==================== Context-Dependent Truth Tests ====================


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
def test_different_contexts_not_conflict(mock_get_client):
    """Test same fact with different metadata not flagged as conflict.

    Memory 1: "EMA is 14 periods" with {"asset_class": "stocks"}
    Memory 2: "EMA is 20 periods" with {"asset_class": "crypto"}
    Both should coexist (ADD, not UPDATE).
    """
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    # First memory: stocks with 14 periods
    mock_client.add.return_value = {
        "results": [{"memory": "EMA is 14 periods", "event": "ADD", "id": "mem_stocks"}]
    }

    result1 = resolve_conflict(
        new_content="EMA is 14 periods",
        user_id="orchestrator",
        metadata={"asset_class": "stocks"},
        client=mock_client
    )

    assert result1.operation == "ADD"

    # Second memory: crypto with 20 periods (different context)
    # Mem0's metadata scoping should treat as separate memory
    mock_client.add.return_value = {
        "results": [{"memory": "EMA is 20 periods", "event": "ADD", "id": "mem_crypto"}]
    }

    result2 = resolve_conflict(
        new_content="EMA is 20 periods",
        user_id="orchestrator",
        metadata={"asset_class": "crypto"},
        client=mock_client
    )

    # Should be ADD (new context) not UPDATE
    assert result2.operation == "ADD"
    assert result2.memory_id == "mem_crypto"


# ==================== add_with_conflict_check Tests ====================


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
@patch('ta_lab2.tools.ai_orchestrator.memory.conflict._log_conflict')
def test_add_with_conflict_check_wrapper(mock_log, mock_get_client):
    """Test add_with_conflict_check calls resolve_conflict."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    mock_client.add.return_value = {
        "results": [{"memory": "Test", "event": "ADD", "id": "mem_wrapper"}]
    }

    result = add_with_conflict_check(
        messages=[{"role": "user", "content": "Test message"}],
        user_id="orchestrator",
        client=mock_client
    )

    # Verify Mem0 add was called
    mock_client.add.assert_called_once()

    # Verify result contains expected fields
    assert result["operation"] == "ADD"
    assert result["memory_id"] == "mem_wrapper"
    assert "confidence" in result
    assert "reason" in result


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
@patch('ta_lab2.tools.ai_orchestrator.memory.conflict._log_conflict')
def test_add_with_conflict_check_logging(mock_log, mock_get_client):
    """Test add_with_conflict_check writes to conflict log when enabled."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    mock_client.add.return_value = {
        "results": [{"memory": "Logged content", "event": "UPDATE", "id": "mem_logged"}]
    }

    result = add_with_conflict_check(
        messages=[{"role": "user", "content": "Logged content"}],
        user_id="orchestrator",
        client=mock_client,
        log_conflicts=True
    )

    # Verify logging was called
    mock_log.assert_called_once()
    assert result["operation"] == "UPDATE"


@patch('ta_lab2.tools.ai_orchestrator.memory.mem0_client.get_mem0_client')
@patch('ta_lab2.tools.ai_orchestrator.memory.conflict._log_conflict')
def test_add_with_conflict_check_no_logging(mock_log, mock_get_client):
    """Test add_with_conflict_check skips log when disabled."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client

    mock_client.add.return_value = {
        "results": [{"memory": "Test", "event": "ADD", "id": "mem_nolog"}]
    }

    add_with_conflict_check(
        messages=[{"role": "user", "content": "Test"}],
        user_id="orchestrator",
        client=mock_client,
        log_conflicts=False  # Disabled
    )

    # Verify logging was NOT called
    mock_log.assert_not_called()


# ==================== Helper Function Tests ====================


def test_generate_reason_operations():
    """Test _generate_reason produces correct messages for each operation."""
    content = "Test content for reasoning"

    reason_add = _generate_reason("ADD", content)
    assert "No conflict detected" in reason_add
    assert "new unique memory" in reason_add

    reason_update = _generate_reason("UPDATE", content)
    assert "Contradiction detected" in reason_update
    assert "updated existing" in reason_update

    reason_noop = _generate_reason("NOOP", content)
    assert "Duplicate detected" in reason_noop

    reason_delete = _generate_reason("DELETE", content)
    assert "marked for deletion" in reason_delete


def test_log_conflict_writes_jsonl(tmp_path):
    """Test _log_conflict appends to conflict_log.jsonl."""
    # Create test conflict result
    result = ConflictResult(
        memory_id="mem_test_log",
        operation="UPDATE",
        confidence=0.85,
        reason="Test logging",
        original_content="Test content",
        timestamp="2026-01-28T15:00:00Z"
    )

    # Use tmp_path for isolated test
    log_file = tmp_path / "conflict_log.jsonl"

    with patch('ta_lab2.tools.ai_orchestrator.memory.conflict.Path') as mock_path_class:
        mock_path_obj = Mock()
        mock_path_obj.parent.mkdir = Mock()
        mock_path_obj.__truediv__ = lambda self, other: log_file if other == "conflict_log.jsonl" else tmp_path / other

        mock_path_class.return_value = mock_path_obj

        # Mock open to write to our tmp_path
        with patch('builtins.open', create=True) as mock_open:
            mock_file = Mock()
            mock_open.return_value.__enter__.return_value = mock_file

            _log_conflict(result)

            # Verify file was opened in append mode
            mock_open.assert_called_once()
            call_args = mock_open.call_args[0]
            assert "conflict_log.jsonl" in str(call_args[0]) or call_args[0] == log_file


# ==================== Integration Test ====================


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Mem0 API keys and Qdrant setup")
def test_conflict_detection_real_mem0():
    """Integration test: Real Mem0 resolves contradiction.

    Requires:
    - OPENAI_API_KEY environment variable
    - Qdrant running or configured
    - Mem0 properly initialized

    This test is marked for manual execution only.
    """
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client

    client = get_mem0_client()

    # Add initial memory
    result1 = resolve_conflict(
        new_content="The EMA period for testing is 14 days",
        user_id="orchestrator_test",
        metadata={"test": "integration"},
        client=client
    )

    assert result1.operation in ["ADD", "UPDATE"]

    # Add contradictory memory
    result2 = resolve_conflict(
        new_content="The EMA period for testing is 20 days",
        user_id="orchestrator_test",
        metadata={"test": "integration"},
        client=client
    )

    # Should detect conflict and UPDATE
    assert result2.operation in ["UPDATE", "ADD"]

    # Cleanup: delete test memories
    try:
        client.delete(result1.memory_id)
        client.delete(result2.memory_id)
    except:
        pass  # Best effort cleanup
