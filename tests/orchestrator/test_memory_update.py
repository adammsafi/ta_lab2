"""Tests for memory update module."""
import pytest
from unittest.mock import MagicMock, patch
from ta_lab2.tools.ai_orchestrator.memory.update import (
    MemoryInput,
    MemoryUpdateResult,
    add_memory,
    add_memories,
    delete_memory,
    get_embedding,
    EMBEDDING_DIMENSIONS,
)
from ta_lab2.tools.ai_orchestrator.memory import reset_memory_client


class TestMemoryUpdateResult:
    """Tests for MemoryUpdateResult dataclass."""

    def test_result_str(self):
        """Test string representation."""
        result = MemoryUpdateResult(added=5, updated=2, failed=1, duration_ms=100.5)
        output = str(result)
        assert "added=5" in output
        assert "updated=2" in output
        assert "failed=1" in output

    def test_total_processed(self):
        """Test total_processed property."""
        result = MemoryUpdateResult(added=5, updated=2, failed=1)
        assert result.total_processed == 8


class TestGetEmbedding:
    """Tests for embedding generation."""

    @patch("openai.OpenAI")
    def test_get_embedding_calls_openai(self, mock_openai_class):
        """Test embedding generation calls OpenAI API."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * EMBEDDING_DIMENSIONS)]
        mock_client.embeddings.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            embeddings = get_embedding(["test text"])

        assert len(embeddings) == 1
        assert len(embeddings[0]) == EMBEDDING_DIMENSIONS
        mock_client.embeddings.create.assert_called_once()

    @patch("openai.OpenAI")
    def test_get_embedding_validates_dimensions(self, mock_openai_class):
        """Test embedding validation rejects wrong dimensions."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 768)]  # Wrong size
        mock_client.embeddings.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with pytest.raises(ValueError, match="dimensions"):
                get_embedding(["test text"])


class TestAddMemories:
    """Tests for add_memories function."""

    def setup_method(self):
        reset_memory_client()

    def teardown_method(self):
        reset_memory_client()

    @patch("ta_lab2.tools.ai_orchestrator.memory.update.get_embedding")
    @patch("ta_lab2.tools.ai_orchestrator.memory.client.get_memory_client")
    def test_add_memories_upserts(self, mock_get_client, mock_get_embedding):
        """Test add_memories uses upsert."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}  # No existing
        mock_client.collection = mock_collection
        mock_get_client.return_value = mock_client

        mock_get_embedding.return_value = [[0.1] * EMBEDDING_DIMENSIONS]

        memories = [
            MemoryInput(
                memory_id="test1", content="Test content", metadata={"type": "test"}
            )
        ]

        result = add_memories(memories, client=mock_client)

        assert result.added == 1
        assert result.updated == 0
        assert result.failed == 0
        mock_collection.upsert.assert_called_once()

    @patch("ta_lab2.tools.ai_orchestrator.memory.update.get_embedding")
    @patch("ta_lab2.tools.ai_orchestrator.memory.client.get_memory_client")
    def test_add_memories_counts_updates(self, mock_get_client, mock_get_embedding):
        """Test add_memories correctly counts updates vs adds."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": ["existing1"]}  # One exists
        mock_client.collection = mock_collection
        mock_get_client.return_value = mock_client

        mock_get_embedding.return_value = [[0.1] * EMBEDDING_DIMENSIONS] * 2

        memories = [
            MemoryInput(memory_id="existing1", content="Updated", metadata={}),
            MemoryInput(memory_id="new1", content="New", metadata={}),
        ]

        result = add_memories(memories, client=mock_client)

        assert result.added == 1
        assert result.updated == 1

    @patch("ta_lab2.tools.ai_orchestrator.memory.update.get_embedding")
    @patch("ta_lab2.tools.ai_orchestrator.memory.client.get_memory_client")
    def test_add_memories_handles_embedding_failure(
        self, mock_get_client, mock_get_embedding
    ):
        """Test add_memories handles embedding generation failure."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_embedding.side_effect = Exception("API error")

        memories = [MemoryInput(memory_id="test1", content="Test", metadata={})]

        result = add_memories(memories, client=mock_client)

        assert result.failed == 1
        assert len(result.errors) == 1
        assert "Embedding generation failed" in result.errors[0]


class TestAddMemory:
    """Tests for add_memory convenience function."""

    def setup_method(self):
        reset_memory_client()

    def teardown_method(self):
        reset_memory_client()

    @patch("ta_lab2.tools.ai_orchestrator.memory.update.get_embedding")
    @patch("ta_lab2.tools.ai_orchestrator.memory.client.get_memory_client")
    def test_add_single_memory(self, mock_get_client, mock_get_embedding):
        """Test adding a single memory."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}
        mock_client.collection = mock_collection
        mock_get_client.return_value = mock_client

        mock_get_embedding.return_value = [[0.1] * EMBEDDING_DIMENSIONS]

        result = add_memory(
            memory_id="single1",
            content="Single memory content",
            metadata={"type": "test"},
            client=mock_client,
        )

        assert result.added == 1
        assert result.failed == 0


class TestDeleteMemory:
    """Tests for delete_memory function."""

    def setup_method(self):
        reset_memory_client()

    def teardown_method(self):
        reset_memory_client()

    @patch("ta_lab2.tools.ai_orchestrator.memory.client.get_memory_client")
    def test_delete_existing_memory(self, mock_get_client):
        """Test deleting existing memory."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": ["test1"]}
        mock_client.collection = mock_collection
        mock_get_client.return_value = mock_client

        result = delete_memory("test1", client=mock_client)

        assert result is True
        mock_collection.delete.assert_called_once_with(ids=["test1"])

    @patch("ta_lab2.tools.ai_orchestrator.memory.client.get_memory_client")
    def test_delete_nonexistent_memory(self, mock_get_client):
        """Test deleting non-existent memory returns False."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}  # Not found
        mock_client.collection = mock_collection
        mock_get_client.return_value = mock_client

        result = delete_memory("nonexistent", client=mock_client)

        assert result is False
        mock_collection.delete.assert_not_called()


class TestMemoryInput:
    """Tests for MemoryInput dataclass."""

    def test_memory_input_defaults(self):
        """Test MemoryInput has correct defaults."""
        mem = MemoryInput(memory_id="id1", content="content")
        assert mem.metadata == {}

    def test_memory_input_with_metadata(self):
        """Test MemoryInput accepts metadata."""
        mem = MemoryInput(
            memory_id="id1",
            content="content",
            metadata={"type": "insight", "source": "test"},
        )
        assert mem.metadata["type"] == "insight"
