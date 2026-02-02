"""DOCX to Markdown conversion with YAML front matter support.

Converts Microsoft Word documents to Markdown format, extracting metadata
from document properties and adding YAML front matter. Images are extracted
to separate assets directory.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import shutil

try:
    import pypandoc
except ImportError:
    pypandoc = None

try:
    from markdownify import markdownify as md
except ImportError:
    md = None

try:
    from docx import Document
except ImportError:
    Document = None

# Set up logger
logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """Result of batch document conversion operation.

    Tracks outcomes for batch conversion operations, following the
    ArchiveResult pattern from tools/archive/types.py.

    Attributes:
        total: Total files in operation
        converted: Successfully converted files
        skipped: Files skipped (already exist or not found)
        errors: Files that failed during conversion
        error_paths: List of paths that failed (for debugging)

    Example:
        >>> result = ConversionResult(total=10, converted=8, skipped=1, errors=1)
        >>> print(result)
        Conversion Result:
          Total: 10
          Converted: 8
          Skipped: 1 (already exist)
          Errors: 1
          Success Rate: 90.0%
    """
    total: int
    converted: int
    skipped: int
    errors: int
    error_paths: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        """Human-readable summary."""
        success_rate = (self.converted + self.skipped) / self.total * 100 if self.total > 0 else 0
        return (
            f"Conversion Result:\n"
            f"  Total: {self.total}\n"
            f"  Converted: {self.converted}\n"
            f"  Skipped: {self.skipped} (already exist)\n"
            f"  Errors: {self.errors}\n"
            f"  Success Rate: {success_rate:.1f}%"
        )


def extract_docx_metadata(docx_path: Path) -> dict:
    """Extract metadata from DOCX file using python-docx.

    Extracts core document properties (title, author, created, modified)
    and falls back to filename for title if not set in document properties.

    Args:
        docx_path: Path to DOCX file

    Returns:
        Dictionary with keys: title, author, created, modified,
        original_path, original_size_bytes

    Example:
        >>> metadata = extract_docx_metadata(Path("report.docx"))
        >>> print(metadata['title'])
        'Q4 Analysis Report'
    """
    if Document is None:
        logger.error("python-docx not installed, cannot extract metadata")
        return {
            "title": docx_path.stem,
            "author": "Unknown",
            "created": None,
            "modified": None,
            "original_path": str(docx_path),
            "original_size_bytes": docx_path.stat().st_size if docx_path.exists() else 0,
        }

    try:
        doc = Document(str(docx_path))
        props = doc.core_properties

        # Get title, fallback to filename
        title = props.title or docx_path.stem

        # Format dates as ISO strings if available
        created = props.created.isoformat() if props.created else None
        modified = props.modified.isoformat() if props.modified else None

        metadata = {
            "title": title,
            "author": props.author or "Unknown",
            "created": created,
            "modified": modified,
            "original_path": str(docx_path),
            "original_size_bytes": docx_path.stat().st_size if docx_path.exists() else 0,
        }

        logger.debug(f"Extracted metadata from {docx_path.name}: {metadata}")
        return metadata

    except Exception as e:
        logger.error(f"Failed to extract metadata from {docx_path}: {e}")
        # Return minimal metadata on error
        return {
            "title": docx_path.stem,
            "author": "Unknown",
            "created": None,
            "modified": None,
            "original_path": str(docx_path),
            "original_size_bytes": docx_path.stat().st_size if docx_path.exists() else 0,
        }


def convert_docx_to_markdown(
    docx_path: Path,
    output_path: Path,
    extract_media: bool = True,
    dry_run: bool = False
) -> dict:
    """Convert DOCX file to Markdown with YAML front matter.

    Two-step conversion process:
    1. DOCX -> HTML using pypandoc
    2. HTML -> Markdown using markdownify

    Extracts images to output_path.parent / "assets" / output_path.stem
    and adds YAML front matter with document metadata.

    Args:
        docx_path: Path to source DOCX file
        output_path: Path to output Markdown file
        extract_media: If True, extract images to assets directory
        dry_run: If True, simulate operation without writing files

    Returns:
        Dictionary with keys: source, output, metadata, media_dir, media_count

    Example:
        >>> result = convert_docx_to_markdown(
        ...     Path("docs/report.docx"),
        ...     Path("docs/report.md"),
        ...     extract_media=True
        ... )
        >>> print(f"Converted with {result['media_count']} images")
    """
    if pypandoc is None:
        logger.error("pypandoc not installed, cannot convert DOCX")
        return {
            "source": str(docx_path),
            "output": str(output_path),
            "metadata": {},
            "media_dir": None,
            "media_count": 0,
            "error": "pypandoc not installed"
        }

    if md is None:
        logger.error("markdownify not installed, cannot convert to Markdown")
        return {
            "source": str(docx_path),
            "output": str(output_path),
            "metadata": {},
            "media_dir": None,
            "media_count": 0,
            "error": "markdownify not installed"
        }

    if not docx_path.exists():
        logger.error(f"Source file not found: {docx_path}")
        return {
            "source": str(docx_path),
            "output": str(output_path),
            "metadata": {},
            "media_dir": None,
            "media_count": 0,
            "error": "Source file not found"
        }

    logger.info(f"Converting {docx_path.name} to Markdown{' (dry run)' if dry_run else ''}")

    try:
        # Extract metadata
        metadata = extract_docx_metadata(docx_path)

        # Setup media extraction directory
        media_dir = None
        media_count = 0
        if extract_media:
            media_dir = output_path.parent / "assets" / output_path.stem
            if not dry_run:
                media_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Media directory: {media_dir}")

        # Step 1: Convert DOCX to HTML using pypandoc
        # Extract media to temp directory if needed
        html_content = pypandoc.convert_file(
            str(docx_path),
            'html',
            format='docx',
            extra_args=['--extract-media=.' if extract_media and media_dir else '']
        )

        # Step 2: Convert HTML to Markdown using markdownify
        markdown_content = md(html_content, heading_style="ATX")

        # Create YAML front matter
        yaml_lines = ["---"]
        yaml_lines.append(f"title: \"{metadata['title']}\"")
        yaml_lines.append(f"author: \"{metadata['author']}\"")
        if metadata['created']:
            yaml_lines.append(f"created: {metadata['created']}")
        if metadata['modified']:
            yaml_lines.append(f"modified: {metadata['modified']}")
        yaml_lines.append(f"original_path: \"{metadata['original_path']}\"")
        yaml_lines.append(f"original_size_bytes: {metadata['original_size_bytes']}")
        yaml_lines.append("---")
        yaml_lines.append("")  # Blank line after front matter

        # Combine front matter and content
        full_content = "\n".join(yaml_lines) + markdown_content

        # Write output file
        if not dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(full_content, encoding='utf-8')
            logger.info(f"Converted: {output_path.name}")

            # Count media files if extracted
            if media_dir and media_dir.exists():
                media_count = len(list(media_dir.glob('*')))
        else:
            logger.info(f"[DRY RUN] Would write: {output_path}")

        return {
            "source": str(docx_path),
            "output": str(output_path),
            "metadata": metadata,
            "media_dir": str(media_dir) if media_dir else None,
            "media_count": media_count,
        }

    except Exception as e:
        logger.error(f"Failed to convert {docx_path}: {e}")
        return {
            "source": str(docx_path),
            "output": str(output_path),
            "metadata": {},
            "media_dir": None,
            "media_count": 0,
            "error": str(e)
        }


__all__ = [
    "ConversionResult",
    "extract_docx_metadata",
    "convert_docx_to_markdown",
]
