"""Tests for metadata schema and migration script.

Tests enhanced metadata schema (created_at, last_verified, deprecated_since)
and idempotent migration script for enriching existing memories.
"""
import pytest
from unittest.mock import Mock
from datetime import datetime

from ta_lab2.tools.ai_orchestrator.memory.metadata import (
    MemoryMetadata,
    create_metadata,
    validate_metadata,
    mark_deprecated,
)
from ta_lab2.tools.ai_orchestrator.memory.migration import (
    MigrationResult,
    migrate_metadata,
    validate_migration,
)


class TestMetadataSchema:
    """Test metadata schema and utility functions."""

    def test_create_metadata_sets_timestamps(self):
        """Test that create_metadata generates created_at and last_verified."""
        meta = create_metadata(source="test", category="unit_test")

        assert "created_at" in meta
        assert "last_verified" in meta
        assert meta["source"] == "test"
        assert meta["category"] == "unit_test"
        assert meta["migration_version"] == 1

        # Verify timestamps are ISO 8601 format
        datetime.fromisoformat(meta["created_at"])
        datetime.fromisoformat(meta["last_verified"])

    def test_create_metadata_preserves_existing_created_at(self):
        """Test that existing created_at is preserved."""
        existing_created = "2025-01-01T00:00:00+00:00"
        existing = {"created_at": existing_created}

        meta = create_metadata(source="test", existing=existing)

        assert meta["created_at"] == existing_created
        # last_verified should be updated to current time
        assert meta["last_verified"] != existing_created

    def test_create_metadata_preserves_deprecated_fields(self):
        """Test that deprecated_since and deprecation_reason are preserved."""
        existing = {
            "created_at": "2025-01-01T00:00:00+00:00",
            "deprecated_since": "2026-01-15T00:00:00+00:00",
            "deprecation_reason": "Outdated",
        }

        meta = create_metadata(source="test", existing=existing)

        assert meta["deprecated_since"] == existing["deprecated_since"]
        assert meta["deprecation_reason"] == existing["deprecation_reason"]

    def test_validate_metadata_valid(self):
        """Test that valid metadata passes validation."""
        meta = create_metadata(source="test")
        is_valid, issues = validate_metadata(meta)

        assert is_valid is True
        assert len(issues) == 0

    def test_validate_metadata_missing_field(self):
        """Test that missing required field is detected."""
        invalid = {"source": "test"}
        is_valid, issues = validate_metadata(invalid)

        assert is_valid is False
        assert len(issues) > 0
        assert any("created_at" in issue for issue in issues)

    def test_validate_metadata_invalid_timestamp(self):
        """Test that invalid ISO 8601 timestamp is detected."""
        invalid = {
            "created_at": "not-a-timestamp",
            "last_verified": "2026-01-28T00:00:00+00:00",
            "source": "test",
            "migration_version": 1,
        }
        is_valid, issues = validate_metadata(invalid)

        assert is_valid is False
        assert any("created_at" in issue for issue in issues)

    def test_validate_metadata_missing_deprecation_reason(self):
        """Test that deprecated_since without reason is invalid."""
        meta = create_metadata(source="test")
        meta["deprecated_since"] = "2026-01-28T00:00:00+00:00"
        # No deprecation_reason set

        is_valid, issues = validate_metadata(meta)

        assert is_valid is False
        assert any("deprecation_reason" in issue for issue in issues)

    def test_mark_deprecated_adds_fields(self):
        """Test that mark_deprecated adds deprecated_since and reason."""
        meta = create_metadata(source="test")
        deprecated = mark_deprecated(meta, reason="Outdated config")

        assert "deprecated_since" in deprecated
        assert deprecated["deprecation_reason"] == "Outdated config"

        # Verify timestamp is ISO 8601
        datetime.fromisoformat(deprecated["deprecated_since"])

        # Original metadata should not be mutated
        assert "deprecated_since" not in meta

    def test_memory_metadata_to_dict(self):
        """Test MemoryMetadata.to_dict() excludes None values."""
        meta = MemoryMetadata(
            created_at="2026-01-28T00:00:00+00:00",
            last_verified="2026-01-28T00:00:00+00:00",
            source="test",
            category=None,  # None should be excluded
            migration_version=1,
        )

        meta_dict = meta.to_dict()

        assert "category" not in meta_dict  # None excluded
        assert meta_dict["source"] == "test"


class TestMigration:
    """Test migration script with mocks."""

    def test_migrate_metadata_dry_run(self):
        """Test that dry run does not call update."""
        mock_client = Mock()
        mock_client.get_all.return_value = [
            {
                "id": "mem_1",
                "memory": "Test memory",
                "metadata": {},  # Missing metadata
            }
        ]

        result = migrate_metadata(client=mock_client, dry_run=True)

        assert result.total == 1
        assert result.updated == 1
        assert result.skipped == 0
        assert result.errors == 0
        # update should NOT be called in dry run
        mock_client.update.assert_not_called()

    def test_migrate_metadata_updates_missing(self):
        """Test that memories without metadata get enriched."""
        mock_client = Mock()
        mock_client.get_all.return_value = [
            {
                "id": "mem_1",
                "memory": "Test memory",
                "metadata": {},  # Missing metadata
            },
            {
                "id": "mem_2",
                "memory": "Another memory",
                "metadata": {"source": "old"},  # Incomplete metadata
            },
        ]

        result = migrate_metadata(client=mock_client, batch_size=10)

        assert result.total == 2
        assert result.updated == 2
        assert result.skipped == 0
        assert result.errors == 0

        # update should be called twice
        assert mock_client.update.call_count == 2

    def test_migrate_metadata_skips_existing(self):
        """Test that memories with valid metadata are skipped."""
        mock_client = Mock()
        valid_meta = create_metadata(source="existing")

        mock_client.get_all.return_value = [
            {
                "id": "mem_1",
                "memory": "Test memory",
                "metadata": valid_meta,  # Already valid
            }
        ]

        result = migrate_metadata(client=mock_client)

        assert result.total == 1
        assert result.updated == 0
        assert result.skipped == 1
        assert result.errors == 0

        # update should NOT be called
        mock_client.update.assert_not_called()

    def test_migrate_metadata_handles_errors(self):
        """Test that errors are logged but don't stop migration."""
        mock_client = Mock()
        mock_client.get_all.return_value = [
            {"id": "mem_1", "memory": "Test memory", "metadata": {}},
            {"id": "mem_2", "memory": "Another memory", "metadata": {}},
        ]

        # First update succeeds, second fails
        mock_client.update.side_effect = [None, Exception("Update failed")]

        result = migrate_metadata(client=mock_client)

        assert result.total == 2
        assert result.updated == 1  # Only first succeeded
        assert result.skipped == 0
        assert result.errors == 1
        assert "mem_2" in result.error_ids

    def test_migrate_metadata_handles_missing_memory_id(self):
        """Test handling of memories without ID."""
        mock_client = Mock()
        mock_client.get_all.return_value = [
            {
                "memory": "Test memory",
                "metadata": {},
                # No "id" field
            }
        ]

        result = migrate_metadata(client=mock_client)

        assert result.total == 1
        assert result.updated == 0
        assert result.skipped == 0
        assert result.errors == 1

    def test_migrate_metadata_handles_missing_memory_text(self):
        """Test handling of memories without text content."""
        mock_client = Mock()
        mock_client.get_all.return_value = [
            {
                "id": "mem_1",
                "metadata": {},
                # No "memory" field
            }
        ]

        result = migrate_metadata(client=mock_client)

        assert result.total == 1
        assert result.updated == 0
        assert result.skipped == 0
        assert result.errors == 1
        assert "mem_1" in result.error_ids

    def test_migration_is_idempotent(self):
        """Test that running migration twice produces same result."""
        mock_client = Mock()
        mock_client.get_all.return_value = [
            {"id": "mem_1", "memory": "Test memory", "metadata": {}}
        ]

        # First run
        result1 = migrate_metadata(client=mock_client)
        assert result1.updated == 1
        assert result1.skipped == 0

        # Update mock to return memory with valid metadata
        valid_meta = create_metadata(source="chromadb_phase2")
        mock_client.get_all.return_value = [
            {"id": "mem_1", "memory": "Test memory", "metadata": valid_meta}
        ]

        # Second run should skip (already valid)
        result2 = migrate_metadata(client=mock_client)
        assert result2.updated == 0
        assert result2.skipped == 1

    def test_migration_result_str(self):
        """Test MigrationResult string representation."""
        result = MigrationResult(
            total=100, updated=90, skipped=8, errors=2, error_ids=["mem_1", "mem_2"]
        )

        result_str = str(result)
        assert "100" in result_str
        assert "90" in result_str
        assert "8" in result_str
        assert "2" in result_str
        assert "98.0%" in result_str  # Success rate


class TestValidateMigration:
    """Test migration validation."""

    def test_validate_migration_sample(self):
        """Test that validate_migration samples and validates memories."""
        mock_client = Mock()
        valid_meta = create_metadata(source="test")

        # Create 10 memories with valid metadata
        mock_client.get_all.return_value = [
            {"id": f"mem_{i}", "memory": f"Memory {i}", "metadata": valid_meta}
            for i in range(10)
        ]

        success, message = validate_migration(client=mock_client, sample_size=5)

        assert success is True
        assert "5 memories" in message
        assert "5 valid" in message

    def test_validate_migration_detects_invalid(self):
        """Test that validate_migration detects invalid metadata."""
        mock_client = Mock()
        valid_meta = create_metadata(source="test")

        mock_client.get_all.return_value = [
            {"id": "mem_1", "memory": "Valid memory", "metadata": valid_meta},
            {
                "id": "mem_2",
                "memory": "Invalid memory",
                "metadata": {},  # Invalid
            },
        ]

        success, message = validate_migration(client=mock_client, sample_size=10)

        assert success is False
        assert "1 invalid" in message

    def test_validate_migration_empty_memories(self):
        """Test validation with no memories."""
        mock_client = Mock()
        mock_client.get_all.return_value = []

        success, message = validate_migration(client=mock_client)

        assert success is True
        assert "No memories" in message


@pytest.mark.integration
class TestMigrationIntegration:
    """Integration tests requiring actual Mem0 client.

    These tests are marked as integration and may be skipped in CI.
    """

    def test_validate_migration_with_real_client(self):
        """Test validate_migration with real Mem0Client (if available).

        This test will be skipped if Mem0 is not configured.
        """
        pytest.skip("Integration test - requires configured Mem0 client")

        # Example integration test (uncomment when ready):
        # from ta_lab2.tools.ai_orchestrator.memory import get_mem0_client
        # client = get_mem0_client()
        # success, message = validate_migration(client=client, sample_size=10)
        # assert success is True or "invalid" in message.lower()
