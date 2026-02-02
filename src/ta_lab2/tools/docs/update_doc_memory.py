"""Update memory with document conversion relationships.

Provides batch memory operations for Phase 13 document consolidation,
creating memories for converted documents and their sections.
"""
import re
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
from ta_lab2.tools.ai_orchestrator.memory.snapshot.batch_indexer import BatchIndexResult

logger = logging.getLogger(__name__)


@dataclass
class DocConversionRecord:
    """Record of a document conversion for memory tracking.

    Attributes:
        original_path: Path to original .docx/.xlsx file
        converted_path: Path to converted .md file
        archive_path: Path in .archive/documentation/
        document_type: "docx" or "xlsx"
        sections: List of H2 headings extracted from converted doc
        converted_at: ISO timestamp of conversion

    Example:
        >>> record = DocConversionRecord(
        ...     original_path="ProjectTT/Foundational/CoreComponents.docx",
        ...     converted_path="docs/CoreComponents.md",
        ...     archive_path=".archive/documentation/2026-02-02/CoreComponents.docx",
        ...     document_type="docx",
        ...     sections=["Overview", "Components", "References"],
        ...     converted_at="2026-02-02T21:15:30Z"
        ... )
    """
    original_path: str
    converted_path: str
    archive_path: str
    document_type: str
    sections: list[str]
    converted_at: str


def extract_sections_from_markdown(md_path: Path) -> list[str]:
    """Parse Markdown file for H2 headings (## ...).

    Args:
        md_path: Path to Markdown file

    Returns:
        List of section titles (H2 headings without ##)

    Example:
        >>> sections = extract_sections_from_markdown(Path("docs/CoreComponents.md"))
        >>> print(sections)
        ['Overview', 'Components', 'Architecture']
    """
    try:
        if not md_path.exists():
            logger.warning(f"Markdown file not found: {md_path}")
            return []

        content = md_path.read_text(encoding='utf-8')

        # Extract H2 headings (## Heading)
        # Pattern: line starts with ##, followed by space, then heading text
        h2_pattern = re.compile(r'^##\s+(.+)$', re.MULTILINE)
        matches = h2_pattern.findall(content)

        # Clean up headings (strip whitespace, remove trailing punctuation)
        sections = [match.strip().rstrip(':.') for match in matches]

        logger.info(f"Extracted {len(sections)} sections from {md_path.name}")
        return sections

    except Exception as e:
        logger.error(f"Failed to extract sections from {md_path}: {e}")
        return []


def check_memory_exists(client, original_path: str) -> bool:
    """Search for existing conversion memory for document.

    Args:
        client: Mem0Client instance
        original_path: Original document path to check

    Returns:
        True if memory already exists for this document

    Example:
        >>> from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
        >>> client = get_mem0_client()
        >>> exists = check_memory_exists(client, "ProjectTT/CoreComponents.docx")
    """
    try:
        # Search for memories mentioning this original path
        results = client.search(
            query=f"Document {original_path} converted",
            user_id="orchestrator",
            limit=5
        )

        # Check if any result mentions this specific path
        for result in results:
            memory_text = result.get("memory", "")
            if original_path in memory_text:
                logger.info(f"Memory already exists for {original_path}")
                return True

        return False

    except Exception as e:
        logger.error(f"Failed to check memory existence for {original_path}: {e}")
        return False


def update_memory_for_doc(
    record: DocConversionRecord,
    dry_run: bool = False
) -> int:
    """Create memories for a single converted document.

    Creates:
    1. Document-level memory with conversion details
    2. Section-level memories for each H2 heading

    Args:
        record: DocConversionRecord with conversion details
        dry_run: If True, log what would be created but don't add to memory

    Returns:
        Count of memories created

    Example:
        >>> record = DocConversionRecord(
        ...     original_path="ProjectTT/Foundational/CoreComponents.docx",
        ...     converted_path="docs/CoreComponents.md",
        ...     archive_path=".archive/documentation/2026-02-02/CoreComponents.docx",
        ...     document_type="docx",
        ...     sections=["Overview", "Components"],
        ...     converted_at="2026-02-02T21:15:30Z"
        ... )
        >>> count = update_memory_for_doc(record, dry_run=False)
    """
    try:
        client = get_mem0_client()
        memories_created = 0

        # Check for duplicates
        if not dry_run and check_memory_exists(client, record.original_path):
            logger.info(f"Skipping {record.original_path} (memory exists)")
            return 0

        # Create document-level memory
        doc_memory = (
            f"Document {record.original_path} converted to Markdown at {record.converted_path}. "
            f"Original archived in {record.archive_path}."
        )

        doc_metadata = {
            "source": "doc_conversion_phase13",
            "category": "file_migration",
            "phase": 13,
            "original_path": record.original_path,
            "converted_path": record.converted_path,
            "archive_path": record.archive_path,
            "document_type": record.document_type,
            "converted_at": record.converted_at,
            "tags": ["phase_13", "doc_conversion", record.document_type]
        }

        if dry_run:
            logger.info(f"[DRY RUN] Would create doc memory: {doc_memory[:100]}...")
        else:
            client.add(
                messages=[{"role": "user", "content": doc_memory}],
                user_id="orchestrator",
                metadata=doc_metadata,
                infer=False  # Bulk operation, skip LLM conflict detection
            )
            memories_created += 1
            logger.info(f"Created doc memory for {record.original_path}")

        # Create section-level memories
        for section in record.sections:
            section_memory = (
                f"Section '{section}' in {record.converted_path} "
                f"(converted from {record.original_path})."
            )

            section_metadata = {
                "source": "doc_conversion_phase13",
                "category": "file_migration",
                "phase": 13,
                "section_name": section,
                "document_path": record.converted_path,
                "original_path": record.original_path,
                "tags": ["phase_13", "doc_section", record.document_type]
            }

            if dry_run:
                logger.info(f"[DRY RUN] Would create section memory: {section_memory[:80]}...")
            else:
                client.add(
                    messages=[{"role": "user", "content": section_memory}],
                    user_id="orchestrator",
                    metadata=section_metadata,
                    infer=False
                )
                memories_created += 1

        logger.info(
            f"Created {memories_created} memories for {record.original_path} "
            f"(1 doc + {len(record.sections)} sections)"
        )
        return memories_created

    except Exception as e:
        logger.error(f"Failed to create memories for {record.original_path}: {e}")
        return 0


def batch_update_memories(
    records: list[DocConversionRecord],
    dry_run: bool = False
) -> BatchIndexResult:
    """Process all conversion records and create memories.

    Args:
        records: List of DocConversionRecord objects
        dry_run: If True, log what would be created but don't add to memory

    Returns:
        BatchIndexResult with counts and error details

    Example:
        >>> records = [
        ...     DocConversionRecord(...),
        ...     DocConversionRecord(...)
        ... ]
        >>> result = batch_update_memories(records, dry_run=False)
        >>> print(result)
    """
    result = BatchIndexResult(
        total=len(records),
        added=0,
        skipped=0,
        errors=0,
        error_ids=[]
    )

    logger.info(f"Starting batch memory update for {len(records)} documents (dry_run={dry_run})")

    for i, record in enumerate(records, 1):
        try:
            memories_created = update_memory_for_doc(record, dry_run=dry_run)

            if memories_created > 0:
                result.added += memories_created
            else:
                result.skipped += 1

            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(records)} documents processed")

        except Exception as e:
            logger.error(f"Error processing {record.original_path}: {e}")
            result.errors += 1
            result.error_ids.append(record.original_path)

    logger.info(f"Batch memory update complete: {result}")
    return result


def create_phase_snapshot(
    documents_converted: int,
    memories_created: int
) -> dict:
    """Create Phase 13 completion memory snapshot.

    Args:
        documents_converted: Number of documents converted to Markdown
        memories_created: Number of memories created

    Returns:
        Result dict from Mem0 add operation

    Example:
        >>> result = create_phase_snapshot(
        ...     documents_converted=44,
        ...     memories_created=250
        ... )
    """
    try:
        client = get_mem0_client()

        snapshot_message = (
            f"Phase 13 Documentation Consolidation complete. "
            f"Converted {documents_converted} ProjectTT documents to Markdown in docs/. "
            f"Original files archived in .archive/documentation/. "
            f"Memory updated with {memories_created} document relationships."
        )

        metadata = {
            "source": "phase_snapshot",
            "phase": 13,
            "phase_name": "documentation-consolidation",
            "milestone": "v0.5.0",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "documents_converted": documents_converted,
            "memories_created": memories_created,
            "categories": ["architecture", "features", "planning", "reference"],
            "tags": ["phase_13_complete", "doc_consolidation_v0.5.0"]
        }

        result = client.add(
            messages=[{"role": "user", "content": snapshot_message}],
            user_id="orchestrator",
            metadata=metadata,
            infer=False
        )

        logger.info(f"Created Phase 13 snapshot: {documents_converted} docs, {memories_created} memories")
        return result

    except Exception as e:
        logger.error(f"Failed to create phase snapshot: {e}")
        raise


__all__ = [
    "DocConversionRecord",
    "extract_sections_from_markdown",
    "check_memory_exists",
    "update_memory_for_doc",
    "batch_update_memories",
    "create_phase_snapshot"
]
