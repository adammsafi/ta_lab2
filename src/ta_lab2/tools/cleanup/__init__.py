"""Cleanup tools for repository maintenance.

Provides tools for duplicate detection, similarity analysis, and
repository organization.
"""
from ta_lab2.tools.cleanup.duplicates import (
    DuplicateGroup,
    EXCLUDE_DIRS,
    find_duplicates,
    generate_duplicate_report,
)
from ta_lab2.tools.cleanup.similarity import (
    FunctionInfo,
    SimilarityMatch,
    EXCLUDE_DIRS as SIMILARITY_EXCLUDE_DIRS,
    extract_functions,
    find_similar_functions,
    generate_similarity_report,
)

__all__ = [
    # Duplicate detection
    "DuplicateGroup",
    "EXCLUDE_DIRS",
    "find_duplicates",
    "generate_duplicate_report",
    # Similarity analysis
    "FunctionInfo",
    "SimilarityMatch",
    "SIMILARITY_EXCLUDE_DIRS",
    "extract_functions",
    "find_similar_functions",
    "generate_similarity_report",
]
