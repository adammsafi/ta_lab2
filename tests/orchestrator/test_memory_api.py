"""Tests for memory REST API."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from ta_lab2.tools.ai_orchestrator.memory.api import create_memory_api


class TestMemoryAPI:
    """Tests for memory REST API endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        app = create_memory_api()
        return TestClient(app)

    @patch('ta_lab2.tools.ai_orchestrator.memory.validation.quick_health_check')
    def test_health_endpoint(self, mock_health, client):
        """Test health check endpoint."""
        mock_health.return_value = True

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @patch('ta_lab2.tools.ai_orchestrator.memory.validation.quick_health_check')
    def test_health_endpoint_unhealthy(self, mock_health, client):
        """Test health check reports unhealthy status."""
        mock_health.return_value = False

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "unhealthy"

    @patch('ta_lab2.tools.ai_orchestrator.memory.validation.validate_memory_store')
    @patch('ta_lab2.tools.ai_orchestrator.memory.client.get_memory_client')
    def test_stats_endpoint(self, mock_get_client, mock_validate, client):
        """Test stats endpoint."""
        mock_client = MagicMock()
        mock_client._collection_name = "test_collection"
        mock_get_client.return_value = mock_client

        mock_validation = MagicMock()
        mock_validation.total_count = 3763
        mock_validation.distance_metric = "cosine"
        mock_validation.is_valid = True
        mock_validate.return_value = mock_validation

        response = client.get("/api/v1/memory/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_memories"] == 3763
        assert data["distance_metric"] == "cosine"
        assert data["is_valid"] is True

    @patch('ta_lab2.tools.ai_orchestrator.memory.query.search_memories')
    def test_search_endpoint(self, mock_search, client):
        """Test search endpoint."""
        from ta_lab2.tools.ai_orchestrator.memory.query import SearchResult, SearchResponse

        mock_search.return_value = SearchResponse(
            query="test",
            results=[SearchResult(
                memory_id="id1",
                content="Test content",
                metadata={"type": "test"},
                similarity=0.9,
                distance=0.1
            )],
            total_found=1,
            filtered_count=1,
            search_time_ms=5.0,
            threshold_used=0.7
        )

        response = client.post(
            "/api/v1/memory/search",
            json={"query": "test query", "max_results": 5, "min_similarity": 0.7}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["memories"][0]["similarity"] == 0.9
        assert data["memories"][0]["content"] == "Test content"

    @patch('ta_lab2.tools.ai_orchestrator.memory.query.search_memories')
    def test_search_endpoint_with_type_filter(self, mock_search, client):
        """Test search endpoint with memory_type filter."""
        from ta_lab2.tools.ai_orchestrator.memory.query import SearchResponse

        mock_search.return_value = SearchResponse(
            query="test",
            results=[],
            total_found=0,
            filtered_count=0,
            search_time_ms=2.0,
            threshold_used=0.7
        )

        response = client.post(
            "/api/v1/memory/search",
            json={"query": "test", "memory_type": "insight"}
        )

        assert response.status_code == 200
        # Verify filter was passed
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["memory_type"] == "insight"

    @patch('ta_lab2.tools.ai_orchestrator.memory.query.search_memories')
    @patch('ta_lab2.tools.ai_orchestrator.memory.injection.inject_memory_context')
    @patch('ta_lab2.tools.ai_orchestrator.memory.injection.estimate_context_tokens')
    def test_context_endpoint(self, mock_tokens, mock_inject, mock_search, client):
        """Test context injection endpoint."""
        from ta_lab2.tools.ai_orchestrator.memory.query import SearchResponse

        mock_search.return_value = SearchResponse(
            query="test",
            results=[],
            total_found=2,
            filtered_count=2,
            search_time_ms=5.0,
            threshold_used=0.7
        )
        mock_inject.return_value = "# Formatted Context\n\n## Memory 1..."
        mock_tokens.return_value = 100

        response = client.post(
            "/api/v1/memory/context",
            json={"query": "test query"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["context"] == "# Formatted Context\n\n## Memory 1..."
        assert data["memory_count"] == 2
        assert data["estimated_tokens"] == 100

    @patch('ta_lab2.tools.ai_orchestrator.memory.query.get_memory_types')
    def test_types_endpoint(self, mock_types, client):
        """Test memory types endpoint."""
        mock_types.return_value = ["insight", "code", "decision"]

        response = client.get("/api/v1/memory/types")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert "insight" in data["types"]
        assert "code" in data["types"]

    def test_search_endpoint_validation(self, client):
        """Test search endpoint validates input."""
        # Missing required query field
        response = client.post(
            "/api/v1/memory/search",
            json={"max_results": 5}
        )

        assert response.status_code == 422  # Validation error

    def test_search_endpoint_bounds_validation(self, client):
        """Test search endpoint validates parameter bounds."""
        # max_results out of bounds
        response = client.post(
            "/api/v1/memory/search",
            json={"query": "test", "max_results": 100}  # Max is 20
        )

        assert response.status_code == 422


class TestAPIDocumentation:
    """Tests for API documentation endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        app = create_memory_api()
        return TestClient(app)

    def test_openapi_schema_available(self, client):
        """Test OpenAPI schema is available."""
        response = client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "ta_lab2 Memory API"

    def test_docs_endpoint_available(self, client):
        """Test Swagger UI docs endpoint."""
        response = client.get("/docs")

        assert response.status_code == 200
