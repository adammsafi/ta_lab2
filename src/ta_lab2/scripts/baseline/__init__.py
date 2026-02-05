"""
Baseline capture utilities for Phase 25.

Provides:
- comparison_utils: Epsilon-aware comparison with NumPy allclose
- metadata_tracker: Audit trail capture and serialization
"""

from ta_lab2.scripts.baseline.comparison_utils import (
    COLUMN_TOLERANCES,
    ComparisonResult,
    compare_tables,
    compare_with_hybrid_tolerance,
    summarize_comparison,
)
from ta_lab2.scripts.baseline.metadata_tracker import (
    BaselineConfig,
    BaselineMetadata,
    capture_metadata,
    save_metadata,
)

__all__ = [
    "COLUMN_TOLERANCES",
    "ComparisonResult",
    "compare_tables",
    "compare_with_hybrid_tolerance",
    "summarize_comparison",
    "BaselineConfig",
    "BaselineMetadata",
    "capture_metadata",
    "save_metadata",
]
