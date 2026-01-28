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

    @patch('ta_lab2.tools.ai_orchestrator.memory.health.MemoryHealthMonitor')
    def test_get_memory_health_returns_report(self, mock_monitor_class, client):
        """Test health endpoint returns valid report."""
        from ta_lab2.tools.ai_orchestrator.memory.health import HealthReport

        mock_monitor = MagicMock()
        mock_monitor_class.return_value = mock_monitor

        mock_report = HealthReport(
            total_memories=100,
            healthy=80,
            stale=15,
            deprecated=5,
            missing_metadata=0,
            age_distribution={"0-30d": 50, "30-60d": 30, "60-90d": 0, "90+d": 20},
            stale_memories=[],
            scan_timestamp="2026-01-28T15:00:00Z"
        )
        mock_monitor.generate_health_report.return_value = mock_report

        response = client.get("/api/v1/memory/health")

        assert response.status_code == 200
        data = response.json()
        assert data["total_memories"] == 100
        assert data["healthy"] == 80
        assert data["stale"] == 15
        assert data["deprecated"] == 5
        assert data["age_distribution"]["0-30d"] == 50

    @patch('ta_lab2.tools.ai_orchestrator.memory.health.MemoryHealthMonitor')
    def test_get_memory_health_custom_staleness(self, mock_monitor_class, client):
        """Test health endpoint with custom staleness_days parameter."""
        from ta_lab2.tools.ai_orchestrator.memory.health import HealthReport

        mock_monitor = MagicMock()
        mock_monitor_class.return_value = mock_monitor

        mock_report = HealthReport(
            total_memories=100,
            healthy=90,
            stale=10,
            deprecated=0,
            missing_metadata=0,
            age_distribution={"0-30d": 60, "30-60d": 30, "60-90d": 0, "90+d": 10},
            stale_memories=[],
            scan_timestamp="2026-01-28T15:00:00Z"
        )
        mock_monitor.generate_health_report.return_value = mock_report

        response = client.get("/api/v1/memory/health?staleness_days=60")

        assert response.status_code == 200
        # Verify custom staleness_days passed to constructor
        mock_monitor_class.assert_called_once_with(staleness_days=60)

    @patch('ta_lab2.tools.ai_orchestrator.memory.health.scan_stale_memories')
    def test_get_stale_memories_returns_list(self, mock_scan, client):
        """Test stale memories endpoint returns list."""
        mock_scan.return_value = [
            {
                "id": "mem_123",
                "content": "Old memory content",
                "last_verified": "2025-10-01T00:00:00Z",
                "age_days": 120
            },
            {
                "id": "mem_456",
                "content": "Another old memory",
                "last_verified": "never",
                "age_days": None
            }
        ]

        response = client.get("/api/v1/memory/health/stale")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == "mem_123"
        assert data[0]["age_days"] == 120
        assert data[1]["last_verified"] == "never"

    @patch('ta_lab2.tools.ai_orchestrator.memory.health.scan_stale_memories')
    def test_get_stale_memories_limit(self, mock_scan, client):
        """Test stale memories endpoint respects limit parameter."""
        # Mock 100 stale memories
        mock_scan.return_value = [
            {
                "id": f"mem_{i}",
                "content": f"Memory {i}",
                "last_verified": "2025-10-01T00:00:00Z",
                "age_days": 120
            }
            for i in range(100)
        ]

        response = client.get("/api/v1/memory/health/stale?limit=10")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 10  # Respects limit

    @patch('ta_lab2.tools.ai_orchestrator.memory.health.MemoryHealthMonitor')
    def test_refresh_verification_updates(self, mock_monitor_class, client):
        """Test refresh endpoint updates timestamps."""
        mock_monitor = MagicMock()
        mock_monitor_class.return_value = mock_monitor
        mock_monitor.refresh_verification.return_value = 2

        response = client.post(
            "/api/v1/memory/health/refresh",
            json={"memory_ids": ["mem_123", "mem_456"]}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["refreshed"] == 2
        assert "mem_123" in data["memory_ids"]
        assert "mem_456" in data["memory_ids"]

    def test_refresh_verification_validation(self, client):
        """Test refresh endpoint validates request."""
        # Empty memory_ids list (min_items=1)
        response = client.post(
            "/api/v1/memory/health/refresh",
            json={"memory_ids": []}
        )

        assert response.status_code == 422  # Validation error

    @patch('ta_lab2.tools.ai_orchestrator.memory.conflict.detect_conflicts')
    def test_check_conflicts_no_conflicts(self, mock_detect, client):
        """Test conflict check with no conflicts found."""
        mock_detect.return_value = []

        response = client.post(
            "/api/v1/memory/conflict/check",
            json={"content": "New unique content"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["has_conflicts"] is False
        assert len(data["conflicts"]) == 0

    @patch('ta_lab2.tools.ai_orchestrator.memory.conflict.detect_conflicts')
    def test_check_conflicts_finds_conflict(self, mock_detect, client):
        """Test conflict check finds similar content."""
        mock_detect.return_value = [
            {
                "memory_id": "mem_789",
                "content": "Similar existing content",
                "similarity": 0.92,
                "metadata": {"type": "insight"}
            }
        ]

        response = client.post(
            "/api/v1/memory/conflict/check",
            json={"content": "Similar content"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["has_conflicts"] is True
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["memory_id"] == "mem_789"
        assert data["conflicts"][0]["similarity"] == 0.92

    @patch('ta_lab2.tools.ai_orchestrator.memory.conflict.detect_conflicts')
    def test_check_conflicts_custom_threshold(self, mock_detect, client):
        """Test conflict check with custom threshold."""
        mock_detect.return_value = []

        response = client.post(
            "/api/v1/memory/conflict/check",
            json={
                "content": "Test content",
                "similarity_threshold": 0.75
            }
        )

        assert response.status_code == 200
        # Verify custom threshold passed to detect_conflicts
        call_kwargs = mock_detect.call_args.kwargs
        assert call_kwargs["similarity_threshold"] == 0.75

    @patch('ta_lab2.tools.ai_orchestrator.memory.conflict.add_with_conflict_check')
    def test_add_with_conflict_resolution(self, mock_add, client):
        """Test add endpoint returns resolution."""
        mock_add.return_value = {
            "memory_id": "mem_new_123",
            "operation": "ADD",
            "confidence": 0.9,
            "reason": "No conflict detected - new unique memory added"
        }

        response = client.post(
            "/api/v1/memory/conflict/add",
            json={"content": "New memory content"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["memory_id"] == "mem_new_123"
        assert data["operation"] == "ADD"
        assert data["confidence"] == 0.9

    @patch('ta_lab2.tools.ai_orchestrator.memory.conflict.add_with_conflict_check')
    def test_add_with_conflict_metadata(self, mock_add, client):
        """Test add endpoint passes metadata through."""
        mock_add.return_value = {
            "memory_id": "mem_new_456",
            "operation": "UPDATE",
            "confidence": 0.85,
            "reason": "Contradiction detected - updated existing memory"
        }

        response = client.post(
            "/api/v1/memory/conflict/add",
            json={
                "content": "Updated content",
                "metadata": {"asset_class": "crypto"}
            }
        )

        assert response.status_code == 200
        # Verify metadata passed to add_with_conflict_check
        call_kwargs = mock_add.call_args.kwargs
        assert call_kwargs["metadata"]["asset_class"] == "crypto"

    @pytest.mark.integration
    @patch('ta_lab2.tools.ai_orchestrator.memory.query.search_memories')
    @patch('ta_lab2.tools.ai_orchestrator.memory.conflict.add_with_conflict_check')
    @patch('ta_lab2.tools.ai_orchestrator.memory.health.MemoryHealthMonitor')
    def test_full_workflow_add_search_health(self, mock_monitor_class, mock_add, mock_search, client):
        """Test end-to-end workflow: add memory, search, check health."""
        from ta_lab2.tools.ai_orchestrator.memory.query import SearchResult, SearchResponse
        from ta_lab2.tools.ai_orchestrator.memory.health import HealthReport

        # 1. Add memory with conflict check
        mock_add.return_value = {
            "memory_id": "mem_workflow_123",
            "operation": "ADD",
            "confidence": 0.9,
            "reason": "No conflict detected - new unique memory added"
        }

        add_response = client.post(
            "/api/v1/memory/conflict/add",
            json={"content": "EMA 20-period for crypto"}
        )
        assert add_response.status_code == 200
        assert add_response.json()["operation"] == "ADD"

        # 2. Search for the memory
        mock_search.return_value = SearchResponse(
            query="EMA crypto",
            results=[SearchResult(
                memory_id="mem_workflow_123",
                content="EMA 20-period for crypto",
                metadata={"type": "insight"},
                similarity=0.95,
                distance=0.05
            )],
            total_found=1,
            filtered_count=1,
            search_time_ms=10.0,
            threshold_used=0.7
        )

        search_response = client.post(
            "/api/v1/memory/search",
            json={"query": "EMA crypto"}
        )
        assert search_response.status_code == 200
        assert search_response.json()["count"] == 1

        # 3. Check health status
        mock_monitor = MagicMock()
        mock_monitor_class.return_value = mock_monitor
        mock_report = HealthReport(
            total_memories=101,
            healthy=100,
            stale=1,
            deprecated=0,
            missing_metadata=0,
            age_distribution={"0-30d": 100, "30-60d": 0, "60-90d": 0, "90+d": 1},
            stale_memories=[],
            scan_timestamp="2026-01-28T15:00:00Z"
        )
        mock_monitor.generate_health_report.return_value = mock_report

        health_response = client.get("/api/v1/memory/health")
        assert health_response.status_code == 200
        assert health_response.json()["total_memories"] == 101


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
