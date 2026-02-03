"""Code analysis tools migrated from Data_Tools.

Tools:
- generate_function_map: Extract function/class signatures to CSV using AST parsing
- generate_function_map_with_purpose: Enhanced function mapper with purpose inference
- tree_structure: Generate directory tree in multiple formats (txt/md/json/csv/API_MAP)

Usage examples:
    # Import functions directly
    from ta_lab2.tools.data_tools.analysis import generate_function_map, print_tree

    # Enhanced function map with purpose inference
    from ta_lab2.tools.data_tools.analysis import generate_function_map_with_purpose
    generate_function_map_with_purpose(root=".", output="function_map.csv")

    # Import modules
    from ta_lab2.tools.data_tools import analysis
"""

from ta_lab2.tools.data_tools.analysis.generate_function_map import (
    generate_function_map,
)
from ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose import (
    generate_function_map_with_purpose,
)
from ta_lab2.tools.data_tools.analysis.tree_structure import (
    build_structure_json,
    generate_tree_structure,
    print_tree,
    save_structure_csv,
    save_structure_json,
    save_tree_markdown,
    emit_hybrid_markdown,
    describe_package_ast,
)

__all__ = [
    # Function map generation
    "generate_function_map",
    "generate_function_map_with_purpose",
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
