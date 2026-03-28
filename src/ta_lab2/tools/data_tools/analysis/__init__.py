"""Code analysis tools for ta_lab2.

Tools:
- generate_function_map: Simple function/class signature CSV (thin wrapper)
- generate_function_map_with_purpose: Full function mapper with purpose inference,
  LLM enrichment, class summaries, script summaries, and diff mode
- generate_script_summaries: Per-module summary CSV and markdown
- generate_diff_report: Compare two function map CSVs
- tree_structure: Directory tree in multiple formats (txt/md/json/csv/API_MAP)

Usage examples:
    # Unified runner (recommended)
    python -m ta_lab2.tools.data_tools.analysis --all

    # Import functions directly
    from ta_lab2.tools.data_tools.analysis import (
        generate_function_map_with_purpose,
        generate_script_summaries,
        generate_diff_report,
    )
"""

from ta_lab2.tools.data_tools.analysis.generate_function_map import (
    generate_function_map,
)
from ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose import (
    generate_diff_report,
    generate_function_map_with_purpose,
    generate_script_summaries,
)
from ta_lab2.tools.data_tools.analysis.tree_structure import (
    build_structure_json,
    describe_package_ast,
    emit_hybrid_markdown,
    generate_tree_structure,
    print_tree,
    save_structure_csv,
    save_structure_json,
    save_tree_markdown,
)

__all__ = [
    # Function map generation
    "generate_function_map",
    "generate_function_map_with_purpose",
    "generate_script_summaries",
    "generate_diff_report",
    # Tree structure generation
    "print_tree",
    "generate_tree_structure",
    "save_tree_markdown",
    "build_structure_json",
    "save_structure_json",
    "save_structure_csv",
    "emit_hybrid_markdown",
    "describe_package_ast",
]
