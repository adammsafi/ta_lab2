"""Function extraction and memory indexing using AST.

Extracts function definitions with full signatures for memory indexing.
Supports src/ and tests/ directories, filtering by significance threshold.

Usage:
    from ta_lab2.tools.ai_orchestrator.memory.indexing import (
        extract_functions,
        index_codebase_functions
    )

    # Extract from single file
    functions = extract_functions(Path("src/ta_lab2/features/ema.py"))

    # Index entire codebase to memory
    result = index_codebase_functions(Path("src/ta_lab2"))
"""
import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .mem0_client import Mem0Client

logger = logging.getLogger(__name__)


@dataclass
class FunctionInfo:
    """Metadata for extracted function definition.

    Attributes:
        name: Function name
        file_path: Relative path from project root
        lineno: Line number in source file
        docstring: First line or full docstring if exists
        parameters: List of parameter dicts with name, annotation, default
        return_annotation: Return type annotation as string
        is_async: Whether function is async
        source: Full function source code
        is_test: Whether function name starts with "test_"
        decorators: List of decorator names
    """

    name: str
    file_path: str
    lineno: int
    docstring: Optional[str] = None
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    return_annotation: Optional[str] = None
    is_async: bool = False
    source: str = ""
    is_test: bool = False
    decorators: List[str] = field(default_factory=list)

    @property
    def signature(self) -> str:
        """Generate function signature string.

        Returns:
            Human-readable signature like "func(a: int, b: str = 'default') -> bool"
        """
        params = []
        for p in self.parameters:
            param_str = p["name"]
            if p.get("annotation"):
                param_str += f": {p['annotation']}"
            if p.get("default"):
                param_str += f" = {p['default']}"
            params.append(param_str)

        sig = f"{self.name}({', '.join(params)})"
        if self.return_annotation:
            sig += f" -> {self.return_annotation}"
        return sig


@dataclass
class IndexingResult:
    """Result of codebase function indexing operation.

    Attributes:
        total_files: Number of Python files scanned
        total_functions: Number of functions extracted
        memories_created: Number of function_definition memories stored
        errors: List of (file_path, error_message) tuples
        functions_by_file: Dict mapping file paths to function counts
    """

    total_files: int = 0
    total_functions: int = 0
    memories_created: int = 0
    errors: List[tuple[str, str]] = field(default_factory=list)
    functions_by_file: Dict[str, int] = field(default_factory=dict)


class FunctionExtractor(ast.NodeVisitor):
    """Extract function definitions with full signatures using AST.

    Extracts all "significant" functions based on threshold:
    - Has docstring, OR
    - >= 3 lines of code, OR
    - Name doesn't start with "_" (private)

    Handles:
    - Regular and async functions
    - Type annotations (params and return)
    - Default values (positional and keyword-only)
    - *args and **kwargs
    - Decorators

    Example:
        >>> extractor = FunctionExtractor(file_path="module.py")
        >>> tree = ast.parse(source_code)
        >>> extractor.visit(tree)
        >>> functions = extractor.functions
    """

    def __init__(self, file_path: str):
        """Initialize extractor.

        Args:
            file_path: Relative path to file being extracted (for metadata)
        """
        self.file_path = file_path
        self.functions: List[FunctionInfo] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        """Visit function definition node (regular or async).

        Args:
            node: AST FunctionDef or AsyncFunctionDef node
        """
        # Extract basic info
        func_info = FunctionInfo(
            name=node.name,
            file_path=self.file_path,
            lineno=node.lineno,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_test=node.name.startswith("test_"),
        )

        # Extract docstring
        func_info.docstring = ast.get_docstring(node)

        # Extract return annotation
        if node.returns:
            try:
                func_info.return_annotation = ast.unparse(node.returns)
            except Exception:
                func_info.return_annotation = None

        # Extract decorators
        for decorator in node.decorator_list:
            try:
                if isinstance(decorator, ast.Name):
                    func_info.decorators.append(decorator.id)
                elif isinstance(decorator, ast.Attribute):
                    func_info.decorators.append(ast.unparse(decorator))
                elif isinstance(decorator, ast.Call):
                    # Decorator with arguments
                    if isinstance(decorator.func, ast.Name):
                        func_info.decorators.append(decorator.func.id)
                    else:
                        func_info.decorators.append(ast.unparse(decorator.func))
            except Exception:
                pass  # Skip decorators we can't parse

        # Extract parameters
        args = node.args

        # Positional arguments with defaults
        num_args = len(args.args)
        num_defaults = len(args.defaults)

        for i, arg in enumerate(args.args):
            param = {
                "name": arg.arg,
                "annotation": ast.unparse(arg.annotation) if arg.annotation else None,
                "default": None,
            }

            # Align defaults from right (defaults apply to last N args)
            default_idx = i - (num_args - num_defaults)
            if default_idx >= 0:
                try:
                    param["default"] = ast.unparse(args.defaults[default_idx])
                except Exception:
                    param["default"] = "<unparseable>"

            func_info.parameters.append(param)

        # Keyword-only arguments (*args separator)
        for i, arg in enumerate(args.kwonlyargs):
            param = {
                "name": arg.arg,
                "annotation": ast.unparse(arg.annotation) if arg.annotation else None,
                "default": None,
                "keyword_only": True,
            }

            # Keyword defaults aligned 1:1
            if i < len(args.kw_defaults) and args.kw_defaults[i]:
                try:
                    param["default"] = ast.unparse(args.kw_defaults[i])
                except Exception:
                    param["default"] = "<unparseable>"

            func_info.parameters.append(param)

        # *args
        if args.vararg:
            param = {
                "name": f"*{args.vararg.arg}",
                "annotation": ast.unparse(args.vararg.annotation)
                if args.vararg.annotation
                else None,
                "default": None,
            }
            func_info.parameters.append(param)

        # **kwargs
        if args.kwarg:
            param = {
                "name": f"**{args.kwarg.arg}",
                "annotation": ast.unparse(args.kwarg.annotation)
                if args.kwarg.annotation
                else None,
                "default": None,
            }
            func_info.parameters.append(param)

        # Extract full source
        try:
            func_info.source = ast.unparse(node)
        except Exception:
            func_info.source = ""

        # Filter by significance threshold
        if self._is_significant(func_info, node):
            self.functions.append(func_info)

        # Continue visiting nested functions
        self.generic_visit(node)

    # Handle async functions identically
    visit_AsyncFunctionDef = visit_FunctionDef

    def _is_significant(self, func_info: FunctionInfo, node: ast.FunctionDef) -> bool:
        """Determine if function meets significance threshold.

        Criteria (any of):
        - Has docstring
        - >= 3 lines of code
        - Name doesn't start with "_" (not private)

        Args:
            func_info: Extracted function info
            node: AST node

        Returns:
            True if function is significant enough to index
        """
        # Has docstring
        if func_info.docstring:
            return True

        # Name doesn't start with "_"
        if not func_info.name.startswith("_"):
            return True

        # >= 3 lines of code (count statements in body)
        if len(node.body) >= 3:
            return True

        return False


def extract_functions(file_path: Path) -> List[FunctionInfo]:
    """Extract all significant functions from a Python file.

    Args:
        file_path: Path to Python file to parse

    Returns:
        List of FunctionInfo objects for significant functions

    Raises:
        None (handles SyntaxError gracefully, logs and returns empty list)

    Example:
        >>> functions = extract_functions(Path("src/ta_lab2/features/ema.py"))
        >>> for func in functions:
        ...     print(f"{func.name} at line {func.lineno}")
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))

        # Make path relative for storage
        relative_path = str(file_path)
        if file_path.is_absolute():
            # Try to make relative to cwd
            try:
                relative_path = str(file_path.relative_to(Path.cwd()))
            except ValueError:
                # Not relative to cwd, use as-is
                relative_path = str(file_path)

        extractor = FunctionExtractor(file_path=relative_path)
        extractor.visit(tree)

        logger.info(
            f"Extracted {len(extractor.functions)} functions from {file_path.name}"
        )
        return extractor.functions

    except SyntaxError as e:
        logger.warning(f"SyntaxError parsing {file_path}: {e}")
        return []
    except Exception as e:
        logger.error(f"Error extracting functions from {file_path}: {e}")
        return []


def index_codebase_functions(
    root: Path,
    include_tests: bool = True,
    store_to_memory: bool = True,
    client: Optional["Mem0Client"] = None,
) -> IndexingResult:
    """Extract all functions from Python files in directory tree.

    Walks directory tree, extracts functions from .py files, and adds to
    memory with category="function_definition".

    Skips:
    - __pycache__, .venv, .git directories
    - Binary/hidden files

    Args:
        root: Root directory to scan
        include_tests: Whether to include test files (default: True)
        store_to_memory: Whether to store function_definition memories (default: True)
        client: Optional Mem0Client instance (created if None and store_to_memory=True)

    Returns:
        IndexingResult with counts, errors, and per-file statistics

    Example:
        >>> from pathlib import Path
        >>> result = index_codebase_functions(Path("src/ta_lab2"))
        >>> print(f"Indexed {result.total_functions} functions from {result.total_files} files")
        >>> print(f"Memories created: {result.memories_created}")
        >>> print(f"Errors: {len(result.errors)}")
    """
    result = IndexingResult()

    # Get Mem0 client if storing to memory
    mem0_client = None
    if store_to_memory:
        if client is not None:
            mem0_client = client
        else:
            from .mem0_client import get_mem0_client

            mem0_client = get_mem0_client()

    # Directories to skip
    skip_dirs = {"__pycache__", ".venv", ".git", ".pytest_cache", ".tox", "venv", "env"}

    # Collect all files first for progress reporting
    py_files = []
    for py_file in root.rglob("*.py"):
        # Skip if in excluded directory
        if any(skip_dir in py_file.parts for skip_dir in skip_dirs):
            continue

        # Skip tests if not including
        if not include_tests and ("test" in py_file.name or "tests" in py_file.parts):
            continue

        py_files.append(py_file)

    logger.info(f"Found {len(py_files)} Python files to index")

    # Process files
    for py_file in py_files:
        try:
            functions = extract_functions(py_file)

            result.total_files += 1
            result.total_functions += len(functions)
            result.functions_by_file[str(py_file)] = len(functions)

            # Add each function to memory
            if mem0_client and functions:
                for func_info in functions:
                    try:
                        # Create memory content
                        content = f"Function {func_info.name} in {Path(func_info.file_path).name}"
                        if func_info.docstring:
                            # Include first line of docstring
                            first_line = func_info.docstring.split("\n")[0].strip()
                            content += f": {first_line}"

                        memory_data = {
                            "role": "user",
                            "content": content,
                        }

                        metadata = {
                            "category": "function_definition",
                            "file_path": func_info.file_path,
                            "function_name": func_info.name,
                            "signature": func_info.signature,
                            "docstring": func_info.docstring or "",
                            "line_number": func_info.lineno,
                            "is_async": func_info.is_async,
                            "is_test": func_info.is_test,
                        }

                        mem0_client.add(
                            messages=[memory_data],
                            user_id="orchestrator",
                            metadata=metadata,
                            infer=False,  # Disable LLM inference for bulk operations
                        )
                        result.memories_created += 1

                    except Exception as e:
                        logger.warning(
                            f"Failed to store memory for {func_info.name}: {e}"
                        )

        except Exception as e:
            error_msg = f"Failed to process {py_file}: {e}"
            logger.error(error_msg)
            result.errors.append((str(py_file), str(e)))

    logger.info(
        f"Indexing complete: {result.total_functions} functions from "
        f"{result.total_files} files, {result.memories_created} memories created "
        f"({len(result.errors)} errors)"
    )

    return result


if __name__ == "__main__":
    # Quick validation
    from pathlib import Path

    # Test on a known file (check if client.py exists, otherwise use this file)
    test_file = Path(__file__).parent / "client.py"
    if not test_file.exists():
        test_file = Path(__file__).parent / "mem0_client.py"

    if test_file.exists():
        functions = extract_functions(test_file)
        print(f"Extracted {len(functions)} functions from {test_file.name}")
        for func in functions[:3]:
            print(f"  - {func.name}({len(func.parameters)} params)")

    # Test on memory module
    memory_dir = Path(__file__).parent
    result = index_codebase_functions(memory_dir, include_tests=False)
    print(
        f"\nIndexing result: {result.total_files} files, {result.total_functions} functions"
    )
    if result.errors:
        print(f"Errors: {len(result.errors)}")
        for file_path, error in result.errors[:3]:
            print(f"  - {Path(file_path).name}: {error}")
