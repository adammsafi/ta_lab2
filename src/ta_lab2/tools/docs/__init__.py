"""Documentation tools for Phase 13 consolidation."""

from ta_lab2.tools.docs.update_doc_memory import (
    DocConversionRecord,
    extract_sections_from_markdown,
    update_memory_for_doc,
    batch_update_memories,
    create_phase_snapshot
)

from ta_lab2.tools.docs.convert_docx import (
    ConversionResult,
    convert_docx_to_markdown,
    extract_docx_metadata
)

from ta_lab2.tools.docs.convert_excel import (
    convert_excel_to_markdown,
    batch_convert_excel
)

__all__ = [
    # Memory update utilities
    "DocConversionRecord",
    "extract_sections_from_markdown",
    "update_memory_for_doc",
    "batch_update_memories",
    "create_phase_snapshot",
    # DOCX conversion utilities
    "ConversionResult",
    "convert_docx_to_markdown",
    "extract_docx_metadata",
    # Excel conversion utilities
    "convert_excel_to_markdown",
    "batch_convert_excel"
]
