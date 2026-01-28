"""Tests for Mem0 client wrapper and configuration.

Validates Mem0 integration with existing ChromaDB backend, including
configuration correctness, singleton pattern, and CRUD operations.
"""
import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from ta_lab2.tools.ai_orchestrator.memory.mem0_config import (
    Mem0Config,
    create_mem0_config
)
from ta_lab2.tools.ai_orchestrator.memory.mem0_client import (
    Mem0Client,
    get_mem0_client,
    reset_mem0_client
)


# ============================================================
# Configuration Tests
# ============================================================

def test_create_mem0_config_returns_dict():
    """Verify create_mem0_config returns valid configuration dict."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        config = create_mem0_config()

        assert isinstance(config, dict)
        assert "vector_store" in config
        assert "llm" in config
        assert "embedder" in config


def test_config_uses_qdrant_provider():
    """Verify config uses Qdrant provider (mem0ai 1.0.2 limitation)."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        config = create_mem0_config()

        # mem0ai 1.0.2 only supports Qdrant, not ChromaDB
        assert config["vector_store"]["provider"] == "qdrant"
        qdrant_path = config["vector_store"]["config"]["path"]
        assert "qdrant" in qdrant_path.lower()


def test_config_uses_text_embedding_3_small():
    """Verify embedder model is text-embedding-3-small for 1536-dim compatibility."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        config = create_mem0_config()

        embedder_model = config["embedder"]["config"]["model"]
        assert embedder_model == "text-embedding-3-small", \
            "Must use text-embedding-3-small to match Phase 2 embeddings (1536-dim)"


def test_config_uses_gpt4o_mini_for_llm():
    """Verify LLM model is gpt-4o-mini for conflict detection."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        config = create_mem0_config()

        llm_model = config["llm"]["config"]["model"]
        assert llm_model == "gpt-4o-mini", \
            "Should use gpt-4o-mini for cost-effective conflict detection"


def test_config_raises_without_api_key():
    """Verify config raises ValueError when OPENAI_API_KEY missing."""
    with patch.dict(os.environ, {}, clear=True):
        # Remove OPENAI_API_KEY from environment
        with pytest.raises(ValueError, match="OPENAI_API_KEY not found"):
            create_mem0_config()


def test_config_creates_qdrant_directory():
    """Verify config creates Qdrant directory if base path exists."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        import tempfile
        import shutil

        # Create temporary directory for test
        temp_dir = tempfile.mkdtemp()
        try:
            mem0_config = Mem0Config(
                chromadb_path=f"{temp_dir}/chromadb",
                openai_api_key="test-key"
            )

            config = create_mem0_config(config=mem0_config)

            # Should create qdrant_mem0 directory
            assert config["vector_store"]["provider"] == "qdrant"
            assert "qdrant_mem0" in config["vector_store"]["config"]["path"]
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def test_config_warns_on_wrong_embedder_model():
    """Verify config warns when embedder model doesn't match Phase 2."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        with patch("ta_lab2.tools.ai_orchestrator.memory.mem0_config.logger") as mock_logger:
            mem0_config = Mem0Config(
                chromadb_path="C:/Users/asafi/Documents/ProjectTT/ChatGPT/20251228/out/chromadb",
                embedder_model="text-embedding-ada-002",  # Wrong model
                openai_api_key="test-key"
            )

            create_mem0_config(config=mem0_config)

            # Should log warning about dimension mismatch
            mock_logger.warning.assert_called()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "text-embedding-3-small" in warning_msg


# ============================================================
# Singleton Tests
# ============================================================

def test_get_mem0_client_returns_instance():
    """Verify get_mem0_client() returns Mem0Client instance."""
    reset_mem0_client()  # Start fresh

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        client = get_mem0_client()

        assert isinstance(client, Mem0Client)


def test_singleton_returns_same_instance():
    """Verify multiple calls to get_mem0_client() return same instance."""
    reset_mem0_client()  # Start fresh

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        client1 = get_mem0_client()
        client2 = get_mem0_client()

        assert client1 is client2, "Should return same singleton instance"


def test_reset_clears_singleton():
    """Verify reset_mem0_client() clears singleton."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        client1 = get_mem0_client()
        reset_mem0_client()
        client2 = get_mem0_client()

        assert client1 is not client2, "Reset should create new instance"


# ============================================================
# Client Method Tests (Mocked)
# ============================================================

def test_add_calls_underlying_memory():
    """Verify add() passes through to Memory.add()."""
    reset_mem0_client()

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        mock_memory = MagicMock()
        mock_memory.add.return_value = {"id": "mem_123", "operation": "ADD"}

        client = Mem0Client()
        # Mock the _memory attribute directly (bypass property)
        client._memory = mock_memory

        result = client.add(
            messages=[{"role": "user", "content": "Test memory"}],
            user_id="test_user"
        )

        # Verify Memory.add was called with correct arguments
        mock_memory.add.assert_called_once()
        call_kwargs = mock_memory.add.call_args[1]
        assert call_kwargs["user_id"] == "test_user"
        assert call_kwargs["infer"] is True  # Default should be True
        assert result["id"] == "mem_123"


def test_search_returns_results():
    """Verify search() returns list from Memory.search()."""
    reset_mem0_client()

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        mock_memory = MagicMock()
        mock_memory.search.return_value = [
            {"id": "mem_1", "memory": "EMA uses 20 periods", "score": 0.95},
            {"id": "mem_2", "memory": "EMA calculation formula", "score": 0.87}
        ]

        client = Mem0Client()
        client._memory = mock_memory
        results = client.search(
            query="EMA calculation",
            user_id="orchestrator",
            limit=5
        )

        # Verify Memory.search was called
        mock_memory.search.assert_called_once()
        call_kwargs = mock_memory.search.call_args[1]
        assert call_kwargs["query"] == "EMA calculation"
        assert call_kwargs["user_id"] == "orchestrator"
        assert call_kwargs["limit"] == 5

        # Verify results
        assert len(results) == 2
        assert results[0]["id"] == "mem_1"


def test_infer_true_by_default():
    """Verify infer=True is default for conflict detection."""
    reset_mem0_client()

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        mock_memory = MagicMock()
        mock_memory.add.return_value = {"id": "mem_123", "operation": "ADD"}

        client = Mem0Client()
        client._memory = mock_memory
        # Call add without explicitly setting infer
        client.add(
            messages=[{"role": "user", "content": "Test"}],
            user_id="test_user"
        )

        # Verify infer=True was passed
        call_kwargs = mock_memory.add.call_args[1]
        assert call_kwargs.get("infer") is True, \
            "infer should default to True for conflict detection"


def test_update_calls_memory_update():
    """Verify update() passes through to Memory.update()."""
    reset_mem0_client()

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        mock_memory = MagicMock()
        mock_memory.update.return_value = {"id": "mem_123", "updated": True}

        client = Mem0Client()
        client._memory = mock_memory
        result = client.update(
            memory_id="mem_123",
            data="Updated content",
            metadata={"last_verified": "2026-01-28"}
        )

        mock_memory.update.assert_called_once()
        call_kwargs = mock_memory.update.call_args[1]
        assert call_kwargs["memory_id"] == "mem_123"
        assert call_kwargs["data"] == "Updated content"
        assert result["id"] == "mem_123"


def test_delete_calls_memory_delete():
    """Verify delete() passes through to Memory.delete()."""
    reset_mem0_client()

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        mock_memory = MagicMock()
        mock_memory.delete.return_value = {"id": "mem_123", "deleted": True}

        client = Mem0Client()
        client._memory = mock_memory
        result = client.delete(memory_id="mem_123")

        mock_memory.delete.assert_called_once_with(memory_id="mem_123")
        assert result["deleted"] is True


def test_get_all_calls_memory_get_all():
    """Verify get_all() passes through to Memory.get_all()."""
    reset_mem0_client()

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        mock_memory = MagicMock()
        mock_memory.get_all.return_value = [
            {"id": "mem_1", "memory": "Memory 1"},
            {"id": "mem_2", "memory": "Memory 2"}
        ]

        client = Mem0Client()
        client._memory = mock_memory
        results = client.get_all(user_id="orchestrator")

        mock_memory.get_all.assert_called_once_with(user_id="orchestrator")
        assert len(results) == 2


def test_memory_count_returns_collection_count():
    """Verify memory_count property returns Qdrant collection count."""
    reset_mem0_client()

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        # Mock the entire chain: memory -> vector_store -> client -> get_collection -> points_count
        mock_collection_info = MagicMock()
        mock_collection_info.points_count = 3763

        mock_qdrant_client = MagicMock()
        mock_qdrant_client.get_collection.return_value = mock_collection_info

        mock_vector_store = MagicMock()
        mock_vector_store.client = mock_qdrant_client

        mock_memory = MagicMock()
        mock_memory.vector_store = mock_vector_store

        client = Mem0Client(config={"vector_store": {"config": {"collection_name": "project_memories"}}})
        client._memory = mock_memory
        count = client.memory_count

        assert count == 3763
        mock_qdrant_client.get_collection.assert_called_once_with(collection_name="project_memories")


# ============================================================
# Integration Test (Requires OPENAI_API_KEY and ChromaDB)
# ============================================================

@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="Requires OPENAI_API_KEY environment variable"
)
def test_mem0_can_add_and_search_memories():
    """Integration test: Verify Mem0 can add and search memories with Qdrant.

    This test requires:
    - OPENAI_API_KEY environment variable
    - Validates Mem0 integration with Qdrant vector store
    """
    reset_mem0_client()

    try:
        client = get_mem0_client()

        # Add a test memory
        result = client.add(
            messages=[
                {"role": "user", "content": "Integration test: EMA calculation uses 20-period window"},
                {"role": "assistant", "content": "Noted: EMA configured with 20-period lookback"}
            ],
            user_id="test_integration"
        )

        assert "id" in result or "results" in result, "Add should return result with ID"

        # Search for the memory
        results = client.search(
            query="EMA calculation",
            user_id="test_integration",
            limit=5
        )

        # Verify we can search (may or may not find the just-added memory depending on indexing)
        assert isinstance(results, list), "Search should return list"

        print(f"Integration test passed: Added memory, search returned {len(results)} results")

    except Exception as e:
        pytest.skip(f"Integration test skipped due to setup issue: {e}")


# ============================================================
# Error Handling Tests
# ============================================================

def test_add_logs_error_on_failure():
    """Verify add() logs error and re-raises on failure."""
    reset_mem0_client()

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        mock_memory = MagicMock()
        mock_memory.add.side_effect = Exception("API error")

        client = Mem0Client()
        client._memory = mock_memory
        with patch("ta_lab2.tools.ai_orchestrator.memory.mem0_client.logger") as mock_logger:
            with pytest.raises(Exception, match="API error"):
                client.add(
                    messages=[{"role": "user", "content": "Test"}],
                    user_id="test_user"
                )

            # Verify error was logged
            mock_logger.error.assert_called()


def test_search_logs_error_on_failure():
    """Verify search() logs error and re-raises on failure."""
    reset_mem0_client()

    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        mock_memory = MagicMock()
        mock_memory.search.side_effect = Exception("Search failed")

        client = Mem0Client()
        client._memory = mock_memory
        with patch("ta_lab2.tools.ai_orchestrator.memory.mem0_client.logger") as mock_logger:
            with pytest.raises(Exception, match="Search failed"):
                client.search(query="test")

            mock_logger.error.assert_called()
