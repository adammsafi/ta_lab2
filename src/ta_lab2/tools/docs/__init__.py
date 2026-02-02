"""Document conversion utilities for ProjectTT documentation migration.

Provides utilities for converting DOCX and Excel files to Markdown format
with metadata extraction and YAML front matter support.

Example:
    >>> from ta_lab2.tools.docs import convert_docx_to_markdown, extract_docx_metadata
    >>> metadata = extract_docx_metadata(Path("doc.docx"))
    >>> result = convert_docx_to_markdown(Path("doc.docx"), Path("output.md"))
"""
from ta_lab2.tools.docs.convert_docx import (
    extract_docx_metadata,
    convert_docx_to_markdown,
    ConversionResult,
)
from ta_lab2.tools.docs.discover_projecttt import (
    discover_projecttt,
    categorize_document,
    generate_inventory_report,
    DocumentInfo,
)

__all__ = [
    # DOCX conversion
    "extract_docx_metadata",
    "convert_docx_to_markdown",
    "ConversionResult",
    # ProjectTT discovery
    "discover_projecttt",
    "categorize_document",
    "generate_inventory_report",
    "DocumentInfo",
]
