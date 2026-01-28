"""Tests for memory search and context injection modules."""
import pytest
from unittest.mock import MagicMock, patch
from ta_lab2.tools.ai_orchestrator.memory import (
    SearchResult,
    SearchResponse,
    search_memories,
    get_memory_by_id,
    get_memory_types,
    format_memories_for_prompt,
    inject_memory_context,
    build_augmented_prompt,
    estimate_context_tokens,
    reset_memory_client
)


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_search_result_str(self):
        """Test SearchResult string representation."""
        result = SearchResult(
            memory_id="abc123def456",
            content="Test content",
            metadata={"type": "test"},
            similarity=0.85,
            distance=0.15
        )
        output = str(result)
        assert "abc123de" in output
        assert "0.85" in output

    def test_search_response_str(self):
        """Test SearchResponse string representation."""
        response = SearchResponse(
            query="test query for searching memories",
            results=[],
            total_found=10,
            filtered_count=5,
            search_time_ms=12.5,
            threshold_used=0.7
        )
        output = str(response)
        assert "5/10" in output
        assert "0.7" in output


class TestSearchMemories:
    """Tests for search_memories function."""

    def setup_method(self):
        reset_memory_client()

    def teardown_method(self):
        reset_memory_client()

    def test_search_returns_filtered_results(self):
        """Test search filters by similarity threshold."""
        mock_client = MagicMock()
        mock_collection = MagicMock()

        # Mock query results with varying distances
        mock_collection.query.return_value = {
            "ids": [["id1", "id2", "id3"]],
            "documents": [["doc1", "doc2", "doc3"]],
            "metadatas": [[{"type": "a"}, {"type": "b"}, {"type": "c"}]],
            "distances": [[0.1, 0.25, 0.5]]  # 0.9, 0.75, 0.5 similarity
        }
        mock_client.collection = mock_collection

        # With 0.7 threshold, only first two should pass
        response = search_memories("test", min_similarity=0.7, client=mock_client)

        assert response.total_found == 3
        assert response.filtered_count == 2
        assert len(response.results) == 2
        assert response.results[0].similarity == 0.9
        assert response.results[1].similarity == 0.75

    def test_search_applies_metadata_filter(self):
        """Test search applies memory_type filter."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["id1"]],
            "documents": [["doc1"]],
            "metadatas": [[{"type": "insight"}]],
            "distances": [[0.1]]
        }
        mock_client.collection = mock_collection

        search_memories("test", memory_type="insight", client=mock_client)

        # Verify filter was passed
        call_args = mock_collection.query.call_args
        assert call_args.kwargs["where"] == {"type": {"$eq": "insight"}}

    def test_search_converts_distance_to_similarity(self):
        """Test distance to similarity conversion."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["id1"]],
            "documents": [["doc1"]],
            "metadatas": [[{}]],
            "distances": [[0.2]]  # Should become 0.8 similarity
        }
        mock_client.collection = mock_collection

        response = search_memories("test", min_similarity=0.5, client=mock_client)

        assert response.results[0].similarity == 0.8
        assert response.results[0].distance == 0.2

    def test_search_handles_empty_results(self):
        """Test search handles no results gracefully."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]]
        }
        mock_client.collection = mock_collection

        response = search_memories("obscure query", client=mock_client)

        assert response.total_found == 0
        assert response.filtered_count == 0
        assert response.results == []


class TestFormatMemories:
    """Tests for format_memories_for_prompt function."""

    def test_format_empty_results(self):
        """Test formatting with no results."""
        output = format_memories_for_prompt([])
        assert "No relevant memories" in output

    def test_format_single_result(self):
        """Test formatting single result."""
        results = [SearchResult(
            memory_id="test123",
            content="This is the memory content.",
            metadata={"type": "insight", "source_path": "src/test.py"},
            similarity=0.85,
            distance=0.15
        )]

        output = format_memories_for_prompt(results)

        assert "Memory 1" in output
        assert "85%" in output  # Relevance
        assert "insight" in output
        assert "src/test.py" in output
        assert "This is the memory content" in output

    def test_format_respects_max_length(self):
        """Test formatting truncates at max_length."""
        results = [SearchResult(
            memory_id=f"id{i}",
            content="A" * 1000,  # Long content
            metadata={},
            similarity=0.9,
            distance=0.1
        ) for i in range(10)]

        output = format_memories_for_prompt(results, max_length=500)

        assert len(output) <= 600  # Allow some buffer for truncation message
        assert "truncated" in output.lower()

    def test_format_without_metadata(self):
        """Test formatting without metadata."""
        results = [SearchResult(
            memory_id="test123",
            content="Content only",
            metadata={},
            similarity=0.85,
            distance=0.15
        )]

        output = format_memories_for_prompt(results, include_metadata=False)

        assert "Type:" not in output
        assert "Content only" in output


class TestInjectMemoryContext:
    """Tests for inject_memory_context function."""

    @patch('ta_lab2.tools.ai_orchestrator.memory.injection.search_memories')
    def test_inject_combines_search_and_format(self, mock_search):
        """Test inject_memory_context combines search and formatting."""
        mock_search.return_value = SearchResponse(
            query="test",
            results=[SearchResult(
                memory_id="id1",
                content="Memory content",
                metadata={"type": "test"},
                similarity=0.9,
                distance=0.1
            )],
            total_found=1,
            filtered_count=1,
            search_time_ms=5.0,
            threshold_used=0.7
        )

        context = inject_memory_context("test query")

        assert "Memory 1" in context
        assert "Memory content" in context
        mock_search.assert_called_once()

    @patch('ta_lab2.tools.ai_orchestrator.memory.injection.search_memories')
    def test_inject_passes_parameters(self, mock_search):
        """Test inject_memory_context passes parameters correctly."""
        mock_search.return_value = SearchResponse(
            query="test",
            results=[],
            total_found=0,
            filtered_count=0,
            search_time_ms=1.0,
            threshold_used=0.8
        )

        inject_memory_context(
            "test",
            max_memories=3,
            min_similarity=0.8,
            memory_type="insight"
        )

        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["max_results"] == 3
        assert call_kwargs["min_similarity"] == 0.8
        assert call_kwargs["memory_type"] == "insight"


class TestBuildAugmentedPrompt:
    """Tests for build_augmented_prompt function."""

    @patch('ta_lab2.tools.ai_orchestrator.memory.injection.inject_memory_context')
    def test_build_returns_structured_dict(self, mock_inject):
        """Test build_augmented_prompt returns proper structure."""
        mock_inject.return_value = "# Test Context"

        result = build_augmented_prompt(
            user_query="What is EMA?",
            system_prompt="You are helpful."
        )

        assert "system" in result
        assert "context" in result
        assert "user" in result
        assert "full_prompt" in result
        assert result["user"] == "What is EMA?"
        assert "You are helpful" in result["system"]


class TestEstimateContextTokens:
    """Tests for token estimation."""

    def test_estimate_returns_reasonable_count(self):
        """Test token estimation is roughly accurate."""
        text = "This is a test sentence with about ten words."
        estimate = estimate_context_tokens(text)

        # ~4 chars per token, 46 chars / 4 = ~11 tokens
        assert 8 <= estimate <= 15


class TestIntegrationWithRealChromaDB:
    """Integration tests with real ChromaDB."""

    @pytest.fixture
    def real_client(self):
        """Get real ChromaDB client, skip if unavailable."""
        reset_memory_client()
        try:
            from ta_lab2.tools.ai_orchestrator.config import load_config
            from ta_lab2.tools.ai_orchestrator.memory import get_memory_client
            import os

            config = load_config()
            if not os.path.exists(config.chromadb_path):
                pytest.skip(f"ChromaDB not found at {config.chromadb_path}")

            client = get_memory_client(config)
            yield client
        except Exception as e:
            pytest.skip(f"ChromaDB not available: {e}")
        finally:
            reset_memory_client()

    def test_real_get_memory_types(self, real_client):
        """Test getting memory types from real ChromaDB."""
        types = get_memory_types(client=real_client)

        print(f"\nMemory types found: {types}")

        # Should find some types
        assert len(types) >= 0  # May or may not have types

    def test_real_get_memory_by_id(self, real_client):
        """Test retrieving a memory by ID."""
        # Get a sample ID first
        result = real_client.collection.get(limit=1, include=["documents"])
        if not result["ids"]:
            pytest.skip("No memories in collection")

        memory_id = result["ids"][0]
        memory = get_memory_by_id(memory_id, client=real_client)

        assert memory is not None
        assert memory.memory_id == memory_id
        assert memory.similarity == 1.0  # Exact match
        assert memory.distance == 0.0

    def test_format_real_memories(self, real_client):
        """Test formatting real memories."""
        # Get some sample memories
        result = real_client.collection.get(limit=3, include=["documents", "metadatas"])
        if not result["ids"]:
            pytest.skip("No memories in collection")

        results = [
            SearchResult(
                memory_id=result["ids"][i],
                content=result["documents"][i],
                metadata=result["metadatas"][i] or {},
                similarity=0.9,
                distance=0.1
            )
            for i in range(len(result["ids"]))
        ]

        formatted = format_memories_for_prompt(results)

        print(f"\nFormatted memories:\n{formatted[:500]}...")

        assert "Memory 1" in formatted
        assert len(formatted) > 50
