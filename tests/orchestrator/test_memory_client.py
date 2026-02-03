"""Tests for MemoryClient and memory validation."""
import pytest
from unittest.mock import patch, MagicMock

from ta_lab2.tools.ai_orchestrator.memory import (
    MemoryClient,
    get_memory_client,
    reset_memory_client,
    MemoryValidationResult,
    validate_memory_store,
    quick_health_check,
)
from ta_lab2.tools.ai_orchestrator.config import OrchestratorConfig


@pytest.fixture
def mock_config():
    """Create a mock OrchestratorConfig for testing."""
    return OrchestratorConfig(
        chromadb_path="/mock/path/to/chromadb",
        chromadb_collection_name="test_memories",
        expected_memory_count=3763,
        embedding_dimensions=1536,
    )


@pytest.fixture
def mock_chromadb_client():
    """Create a mock ChromaDB client."""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_collection.count.return_value = 3763
    mock_collection.metadata = {"hnsw:space": "cosine"}
    mock_client.get_collection.return_value = mock_collection
    return mock_client, mock_collection


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset MemoryClient singleton before and after each test."""
    reset_memory_client()
    yield
    reset_memory_client()


class TestMemoryClient:
    """Test MemoryClient wrapper."""

    def test_initialization(self, mock_chromadb_client):
        """Test MemoryClient initialization."""
        mock_client, _ = mock_chromadb_client

        with patch("chromadb.PersistentClient", return_value=mock_client):
            client = MemoryClient(
                chroma_path="/test/path", collection_name="test_collection"
            )

            assert client._client == mock_client
            assert client._collection_name == "test_collection"

    def test_lazy_collection_loading(self, mock_chromadb_client):
        """Test that collection is loaded lazily on first access."""
        mock_client, mock_collection = mock_chromadb_client

        with patch("chromadb.PersistentClient", return_value=mock_client):
            client = MemoryClient("/test/path", "test_collection")

            # Collection should not be loaded yet
            assert client._collection is None

            # Access collection property
            collection = client.collection

            # Collection should now be loaded
            assert collection == mock_collection
            mock_client.get_collection.assert_called_once_with(name="test_collection")

            # Second access should not reload
            collection2 = client.collection
            assert collection2 is collection
            assert mock_client.get_collection.call_count == 1

    def test_count_method(self, mock_chromadb_client):
        """Test count() returns total memory count."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 3763

        with patch("chromadb.PersistentClient", return_value=mock_client):
            client = MemoryClient("/test/path", "test_collection")
            count = client.count()

            assert count == 3763
            mock_collection.count.assert_called_once()

    def test_get_metadata(self, mock_chromadb_client):
        """Test get_metadata() returns collection metadata."""
        mock_client, mock_collection = mock_chromadb_client
        expected_metadata = {"hnsw:space": "cosine", "custom_field": "value"}
        mock_collection.metadata = expected_metadata

        with patch("chromadb.PersistentClient", return_value=mock_client):
            client = MemoryClient("/test/path", "test_collection")
            metadata = client.get_metadata()

            assert metadata == expected_metadata

    def test_get_metadata_empty(self, mock_chromadb_client):
        """Test get_metadata() returns empty dict when metadata is None."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.metadata = None

        with patch("chromadb.PersistentClient", return_value=mock_client):
            client = MemoryClient("/test/path", "test_collection")
            metadata = client.get_metadata()

            assert metadata == {}

    def test_client_property(self, mock_chromadb_client):
        """Test client property returns underlying ChromaDB client."""
        mock_client, _ = mock_chromadb_client

        with patch("chromadb.PersistentClient", return_value=mock_client):
            client = MemoryClient("/test/path", "test_collection")

            assert client.client == mock_client


class TestMemoryClientFactory:
    """Test get_memory_client factory function."""

    def test_singleton_pattern(self, mock_config, mock_chromadb_client):
        """Test that get_memory_client returns the same instance."""
        mock_client, _ = mock_chromadb_client

        with patch("chromadb.PersistentClient", return_value=mock_client):
            client1 = get_memory_client(mock_config)
            client2 = get_memory_client(mock_config)

            assert client1 is client2

    def test_loads_config_if_not_provided(self, mock_config, mock_chromadb_client):
        """Test that factory loads config from environment if not provided."""
        mock_client, _ = mock_chromadb_client

        with patch("chromadb.PersistentClient", return_value=mock_client), patch(
            "ta_lab2.tools.ai_orchestrator.config.load_config", return_value=mock_config
        ):
            client = get_memory_client()

            assert client is not None
            assert client._collection_name == "test_memories"

    def test_reset_memory_client(self, mock_config, mock_chromadb_client):
        """Test that reset_memory_client clears singleton."""
        mock_client, _ = mock_chromadb_client

        with patch("chromadb.PersistentClient", return_value=mock_client):
            client1 = get_memory_client(mock_config)
            reset_memory_client()
            client2 = get_memory_client(mock_config)

            assert client1 is not client2


class TestMemoryValidationResult:
    """Test MemoryValidationResult dataclass."""

    def test_creation(self):
        """Test MemoryValidationResult creation."""
        result = MemoryValidationResult(
            is_valid=True,
            total_count=3763,
            expected_count=3763,
            sample_valid=True,
            metadata_complete=True,
            distance_metric="cosine",
            embedding_dimensions=1536,
            issues=[],
        )

        assert result.is_valid is True
        assert result.total_count == 3763
        assert result.distance_metric == "cosine"
        assert len(result.issues) == 0

    def test_string_representation(self):
        """Test __str__ provides readable summary."""
        result = MemoryValidationResult(
            is_valid=True,
            total_count=3800,
            expected_count=3763,
            sample_valid=True,
            metadata_complete=True,
            distance_metric="cosine",
            embedding_dimensions=1536,
            issues=[],
        )

        string_repr = str(result)
        assert "VALID" in string_repr
        assert "3800/3763" in string_repr
        assert "cosine" in string_repr
        assert "1536" in string_repr

    def test_invalid_result_string(self):
        """Test __str__ shows INVALID when not valid."""
        result = MemoryValidationResult(
            is_valid=False,
            total_count=100,
            expected_count=3763,
            sample_valid=False,
            metadata_complete=False,
            distance_metric="l2",
            embedding_dimensions=1536,
            issues=["Count too low", "Wrong metric"],
        )

        string_repr = str(result)
        assert "INVALID" in string_repr
        assert "100/3763" in string_repr


class TestValidateMemoryStore:
    """Test validate_memory_store function."""

    def test_valid_store(self, mock_chromadb_client):
        """Test validation passes for valid store."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 3800
        mock_collection.metadata = {"hnsw:space": "cosine"}
        mock_collection.get.return_value = {
            "embeddings": [[0.1] * 1536 for _ in range(10)],
            "metadatas": [{"key": f"value{i}"} for i in range(10)],
            "documents": [f"doc{i}" for i in range(10)],
        }

        with patch("chromadb.PersistentClient", return_value=mock_client):
            memory_client = MemoryClient("/test/path", "test_collection")
            result = validate_memory_store(
                client=memory_client,
                expected_count=3763,
                expected_dimensions=1536,
                sample_size=10,
            )

            assert result.is_valid is True
            assert result.total_count == 3800
            assert result.distance_metric == "cosine"
            assert result.embedding_dimensions == 1536
            assert len(result.issues) == 0

    def test_count_too_low(self, mock_chromadb_client):
        """Test validation fails when count is below expected."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 100
        mock_collection.metadata = {"hnsw:space": "cosine"}
        mock_collection.get.return_value = {
            "embeddings": [[0.1] * 1536 for _ in range(10)],
            "metadatas": [{"key": f"value{i}"} for i in range(10)],
            "documents": [f"doc{i}" for i in range(10)],
        }

        with patch("chromadb.PersistentClient", return_value=mock_client):
            memory_client = MemoryClient("/test/path", "test_collection")
            result = validate_memory_store(client=memory_client, expected_count=3763)

            assert result.is_valid is False
            assert any("Count mismatch" in issue for issue in result.issues)

    def test_l2_distance_warning(self, mock_chromadb_client):
        """Test validation warns about L2 distance but doesn't fail."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 3800
        mock_collection.metadata = {"hnsw:space": "l2"}
        mock_collection.get.return_value = {
            "embeddings": [[0.1] * 1536 for _ in range(10)],
            "metadatas": [{"key": f"value{i}"} for i in range(10)],
            "documents": [f"doc{i}" for i in range(10)],
        }

        with patch("chromadb.PersistentClient", return_value=mock_client):
            memory_client = MemoryClient("/test/path", "test_collection")
            result = validate_memory_store(client=memory_client)

            # Should be valid (L2 is acceptable, just not recommended)
            assert result.is_valid is True
            assert result.distance_metric == "l2"
            assert any("Distance metric" in issue for issue in result.issues)

    def test_wrong_embedding_dimensions(self, mock_chromadb_client):
        """Test validation fails when embeddings have wrong dimensions."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 3800
        mock_collection.metadata = {"hnsw:space": "cosine"}
        mock_collection.get.return_value = {
            "embeddings": [[0.1] * 768 for _ in range(10)],  # Wrong dimension
            "metadatas": [{"key": f"value{i}"} for i in range(10)],
            "documents": [f"doc{i}" for i in range(10)],
        }

        with patch("chromadb.PersistentClient", return_value=mock_client):
            memory_client = MemoryClient("/test/path", "test_collection")
            result = validate_memory_store(
                client=memory_client, expected_dimensions=1536
            )

            assert result.is_valid is False
            assert any("dimension" in issue.lower() for issue in result.issues)

    def test_missing_metadata(self, mock_chromadb_client):
        """Test validation fails when metadata is missing."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 3800
        mock_collection.metadata = {"hnsw:space": "cosine"}
        mock_collection.get.return_value = {
            "embeddings": [[0.1] * 1536 for _ in range(10)],
            "metadatas": [None] * 10,  # Missing metadata
            "documents": [f"doc{i}" for i in range(10)],
        }

        with patch("chromadb.PersistentClient", return_value=mock_client):
            memory_client = MemoryClient("/test/path", "test_collection")
            result = validate_memory_store(client=memory_client)

            assert result.is_valid is False
            assert result.metadata_complete is False
            assert any("metadata is empty" in issue for issue in result.issues)

    def test_null_embeddings(self, mock_chromadb_client):
        """Test validation fails when embeddings are None."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 3800
        mock_collection.metadata = {"hnsw:space": "cosine"}
        mock_collection.get.return_value = {
            "embeddings": [None] * 10,  # Null embeddings
            "metadatas": [{"key": f"value{i}"} for i in range(10)],
            "documents": [f"doc{i}" for i in range(10)],
        }

        with patch("chromadb.PersistentClient", return_value=mock_client):
            memory_client = MemoryClient("/test/path", "test_collection")
            result = validate_memory_store(client=memory_client)

            assert result.is_valid is False
            assert result.sample_valid is False
            assert any("embedding is None" in issue for issue in result.issues)

    def test_loads_client_if_not_provided(self, mock_config, mock_chromadb_client):
        """Test validation loads client if not provided."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 3800
        mock_collection.metadata = {"hnsw:space": "cosine"}
        mock_collection.get.return_value = {
            "embeddings": [[0.1] * 1536 for _ in range(10)],
            "metadatas": [{"key": f"value{i}"} for i in range(10)],
            "documents": [f"doc{i}" for i in range(10)],
        }

        with patch("chromadb.PersistentClient", return_value=mock_client), patch(
            "ta_lab2.tools.ai_orchestrator.memory.validation.get_memory_client"
        ) as mock_get_client:
            mock_memory_client = MemoryClient("/test/path", "test_collection")
            mock_get_client.return_value = mock_memory_client

            result = validate_memory_store(client=None)

            mock_get_client.assert_called_once()
            assert result.is_valid is True


class TestQuickHealthCheck:
    """Test quick_health_check function."""

    def test_healthy_store(self, mock_chromadb_client):
        """Test health check passes for accessible store with memories."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 3763

        with patch("chromadb.PersistentClient", return_value=mock_client):
            memory_client = MemoryClient("/test/path", "test_collection")
            is_healthy = quick_health_check(client=memory_client)

            assert is_healthy is True

    def test_empty_store(self, mock_chromadb_client):
        """Test health check fails for empty store."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 0

        with patch("chromadb.PersistentClient", return_value=mock_client):
            memory_client = MemoryClient("/test/path", "test_collection")
            is_healthy = quick_health_check(client=memory_client)

            assert is_healthy is False

    def test_exception_handling(self, mock_chromadb_client):
        """Test health check handles exceptions gracefully."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.side_effect = Exception("Connection failed")

        with patch("chromadb.PersistentClient", return_value=mock_client):
            memory_client = MemoryClient("/test/path", "test_collection")
            is_healthy = quick_health_check(client=memory_client)

            assert is_healthy is False

    def test_loads_client_if_not_provided(self, mock_config, mock_chromadb_client):
        """Test health check loads client if not provided."""
        mock_client, mock_collection = mock_chromadb_client
        mock_collection.count.return_value = 3763

        with patch("chromadb.PersistentClient", return_value=mock_client), patch(
            "ta_lab2.tools.ai_orchestrator.memory.validation.get_memory_client"
        ) as mock_get_client:
            mock_memory_client = MemoryClient("/test/path", "test_collection")
            mock_get_client.return_value = mock_memory_client

            is_healthy = quick_health_check(client=None)

            mock_get_client.assert_called_once()
            assert is_healthy is True
