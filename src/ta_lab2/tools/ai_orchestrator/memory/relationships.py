"""Relationship detection and memory linking.

Detects and stores relationships between code entities:
- contains: file contains function
- calls: function A calls function B
- imports: file imports module
- moved_to: file/function moved during reorganization
- similar_to: functions with high similarity (set by duplicate detection)

Usage:
    from ta_lab2.tools.ai_orchestrator.memory.relationships import (
        detect_calls,
        link_codebase_relationships
    )

    # Detect call relationships in a file
    calls = detect_calls(Path("src/ta_lab2/features/ema.py"))

    # Link all relationships for indexed functions
    result = link_codebase_relationships(Path("src/ta_lab2"))
"""
import ast
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict, Any, Optional

if TYPE_CHECKING:
    from .indexing import FunctionInfo
    from .mem0_client import Mem0Client

logger = logging.getLogger(__name__)


class RelationshipType(Enum):
    """Types of relationships between code entities."""

    CONTAINS = "contains"  # File contains function
    CALLS = "calls"  # Function A calls function B
    IMPORTS = "imports"  # File imports module
    MOVED_TO = "moved_to"  # Entity moved during reorganization
    SIMILAR_TO = "similar_to"  # Functions with high similarity


@dataclass
class Relationship:
    """Relationship between code entities.

    Attributes:
        relationship_type: Type of relationship
        source_file: Source file path (relative)
        source_entity: Optional source entity name (function for calls, None for file-level)
        target_file: Target file path (for contains/imports) or None
        target_entity: Target entity name (function/module name)
        metadata: Additional metadata (similarity score, move date, etc.)
    """

    relationship_type: RelationshipType
    source_file: str
    source_entity: Optional[str] = None
    target_file: Optional[str] = None
    target_entity: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LinkingResult:
    """Result of relationship linking operation.

    Attributes:
        total_files: Number of files scanned
        contains_count: Number of file-to-function contains relationships
        calls_count: Number of function-to-function call relationships
        imports_count: Number of file-to-module import relationships
        errors: List of (file_path, error_message) tuples
    """

    total_files: int = 0
    contains_count: int = 0
    calls_count: int = 0
    imports_count: int = 0
    errors: List[tuple[str, str]] = field(default_factory=list)


class CallDetector(ast.NodeVisitor):
    """Extract function call relationships using AST.

    Visits ast.Call nodes and tracks which function makes each call.
    Handles:
    - Simple function calls: foo()
    - Attribute calls: obj.method()
    - Nested calls: self.helper()

    Example:
        >>> detector = CallDetector()
        >>> tree = ast.parse(source_code)
        >>> detector.visit(tree)
        >>> calls = detector.calls  # List of (caller, called) tuples
    """

    def __init__(self):
        """Initialize call detector."""
        self.calls: List[tuple[str, str]] = []
        self.current_function: Optional[str] = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        """Visit function definition - track current function context.

        Args:
            node: AST FunctionDef or AsyncFunctionDef node
        """
        # Save previous context
        prev_function = self.current_function
        self.current_function = node.name

        # Visit function body
        self.generic_visit(node)

        # Restore previous context (for nested functions)
        self.current_function = prev_function

    # Handle async functions identically
    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> Any:
        """Visit function call - extract called function name.

        Args:
            node: AST Call node
        """
        if self.current_function:
            # Extract called function name
            called_name = self._extract_call_name(node.func)
            if called_name:
                self.calls.append((self.current_function, called_name))

        # Continue visiting nested calls
        self.generic_visit(node)

    def _extract_call_name(self, node: ast.expr) -> Optional[str]:
        """Extract function name from call expression.

        Args:
            node: AST expression node (Name, Attribute, etc.)

        Returns:
            Function name string or None
        """
        if isinstance(node, ast.Name):
            # Simple call: foo()
            return node.id
        elif isinstance(node, ast.Attribute):
            # Attribute call: obj.method()
            # Return just the method name (not full path)
            return node.attr
        else:
            # Complex expression (lambda, subscript, etc.)
            try:
                return ast.unparse(node)
            except Exception:
                return None


def detect_calls(file_path: Path) -> List[Relationship]:
    """Detect function-to-function call relationships in a file.

    Args:
        file_path: Path to Python file to analyze

    Returns:
        List of CALLS relationships

    Example:
        >>> calls = detect_calls(Path("src/ta_lab2/features/ema.py"))
        >>> for rel in calls:
        ...     print(f"{rel.source_entity} calls {rel.target_entity}")
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))

        # Make path relative
        relative_path = str(file_path)
        if file_path.is_absolute():
            try:
                relative_path = str(file_path.relative_to(Path.cwd()))
            except ValueError:
                relative_path = str(file_path)

        # Detect calls
        detector = CallDetector()
        detector.visit(tree)

        # Convert to Relationship objects
        relationships = []
        for caller, called in detector.calls:
            rel = Relationship(
                relationship_type=RelationshipType.CALLS,
                source_file=relative_path,
                source_entity=caller,
                target_file=relative_path,  # Calls within same file
                target_entity=called,
            )
            relationships.append(rel)

        logger.info(
            f"Detected {len(relationships)} call relationships in {file_path.name}"
        )
        return relationships

    except SyntaxError as e:
        logger.warning(f"SyntaxError parsing {file_path}: {e}")
        return []
    except Exception as e:
        logger.error(f"Error detecting calls in {file_path}: {e}")
        return []


def detect_imports(file_path: Path) -> List[Relationship]:
    """Detect file-to-module import relationships.

    Args:
        file_path: Path to Python file to analyze

    Returns:
        List of IMPORTS relationships

    Example:
        >>> imports = detect_imports(Path("src/ta_lab2/features/ema.py"))
        >>> for rel in imports:
        ...     print(f"imports {rel.target_entity}")
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))

        # Make path relative
        relative_path = str(file_path)
        if file_path.is_absolute():
            try:
                relative_path = str(file_path.relative_to(Path.cwd()))
            except ValueError:
                relative_path = str(file_path)

        # Extract imports
        relationships = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # import foo, bar
                for alias in node.names:
                    rel = Relationship(
                        relationship_type=RelationshipType.IMPORTS,
                        source_file=relative_path,
                        source_entity=None,  # File-level import
                        target_file=None,
                        target_entity=alias.name,
                        metadata={"alias": alias.asname} if alias.asname else {},
                    )
                    relationships.append(rel)

            elif isinstance(node, ast.ImportFrom):
                # from foo import bar
                module = node.module or ""
                for alias in node.names:
                    rel = Relationship(
                        relationship_type=RelationshipType.IMPORTS,
                        source_file=relative_path,
                        source_entity=None,
                        target_file=None,
                        target_entity=f"{module}.{alias.name}"
                        if module
                        else alias.name,
                        metadata={
                            "from_module": module,
                            "alias": alias.asname if alias.asname else None,
                        },
                    )
                    relationships.append(rel)

        logger.info(
            f"Detected {len(relationships)} import relationships in {file_path.name}"
        )
        return relationships

    except SyntaxError as e:
        logger.warning(f"SyntaxError parsing {file_path}: {e}")
        return []
    except Exception as e:
        logger.error(f"Error detecting imports in {file_path}: {e}")
        return []


def create_contains_relationships(
    file_path: Path, functions: List["FunctionInfo"]
) -> List[Relationship]:
    """Create file-to-function contains relationships.

    Args:
        file_path: Path to file containing functions
        functions: List of FunctionInfo objects extracted from file

    Returns:
        List of CONTAINS relationships

    Example:
        >>> from .indexing import extract_functions
        >>> functions = extract_functions(Path("src/ta_lab2/features/ema.py"))
        >>> contains = create_contains_relationships(Path("..."), functions)
    """
    # Make path relative
    relative_path = str(file_path)
    if file_path.is_absolute():
        try:
            relative_path = str(file_path.relative_to(Path.cwd()))
        except ValueError:
            relative_path = str(file_path)

    relationships = []
    for func in functions:
        rel = Relationship(
            relationship_type=RelationshipType.CONTAINS,
            source_file=relative_path,
            source_entity=None,  # File-level (file contains function)
            target_file=None,
            target_entity=func.name,
            metadata={
                "lineno": func.lineno,
                "is_async": func.is_async,
                "is_test": func.is_test,
            },
        )
        relationships.append(rel)

    logger.info(
        f"Created {len(relationships)} contains relationships for {file_path.name}"
    )
    return relationships


def create_relationship_memory(relationship: Relationship, client: "Mem0Client") -> str:
    """Create memory entry for a relationship.

    Args:
        relationship: Relationship to store
        client: Mem0Client instance for memory storage

    Returns:
        Memory ID

    Example:
        >>> from .mem0_client import get_mem0_client
        >>> client = get_mem0_client()
        >>> memory_id = create_relationship_memory(relationship, client)
    """
    # Build metadata
    metadata = {
        "category": "function_relationship",
        "relationship_type": relationship.relationship_type.value,
        "source_file": relationship.source_file,
    }

    if relationship.source_entity:
        metadata["source_function"] = relationship.source_entity

    if relationship.target_file:
        metadata["target_file"] = relationship.target_file

    if relationship.target_entity:
        metadata["target_function"] = relationship.target_entity

    # Add relationship-specific metadata
    metadata.update(relationship.metadata)

    # Create human-readable content
    if relationship.relationship_type == RelationshipType.CONTAINS:
        content = f"File {relationship.source_file} contains function {relationship.target_entity}"
    elif relationship.relationship_type == RelationshipType.CALLS:
        content = (
            f"Function {relationship.source_entity} calls {relationship.target_entity}"
        )
    elif relationship.relationship_type == RelationshipType.IMPORTS:
        content = (
            f"File {relationship.source_file} imports {relationship.target_entity}"
        )
    elif relationship.relationship_type == RelationshipType.MOVED_TO:
        content = f"Entity {relationship.source_entity} moved from {relationship.source_file} to {relationship.target_file}"
    elif relationship.relationship_type == RelationshipType.SIMILAR_TO:
        similarity = relationship.metadata.get("similarity_score", "unknown")
        content = f"Function {relationship.source_entity} is {similarity}% similar to {relationship.target_entity}"
    else:
        content = f"Relationship: {relationship.relationship_type.value}"

    # Add to memory (use infer=False for performance with batch operations)
    messages = [
        {"role": "user", "content": content},
    ]

    result = client.add(
        messages=messages,
        user_id="orchestrator",
        metadata=metadata,
        infer=False,  # Disable LLM conflict detection for performance
    )

    # Extract memory ID from result
    memory_id = result.get("results", [{}])[0].get("id", "")
    logger.debug(f"Created relationship memory: {memory_id}")

    return memory_id


def link_codebase_relationships(
    root: Path, client: Optional["Mem0Client"] = None
) -> LinkingResult:
    """Link all relationships for Python files in directory tree.

    Detects and stores:
    - CONTAINS: file -> function
    - CALLS: function -> function
    - IMPORTS: file -> module

    Args:
        root: Root directory to scan
        client: Optional Mem0Client (if None, creates one)

    Returns:
        LinkingResult with counts and errors

    Example:
        >>> result = link_codebase_relationships(Path("src/ta_lab2"))
        >>> print(f"Linked {result.calls_count} call relationships")
    """
    from .indexing import extract_functions
    from .mem0_client import get_mem0_client

    if client is None:
        client = get_mem0_client()

    result = LinkingResult()

    # Directories to skip
    skip_dirs = {"__pycache__", ".venv", ".git", ".pytest_cache", ".tox", "venv", "env"}

    # Walk directory tree
    for py_file in root.rglob("*.py"):
        # Skip if in excluded directory
        if any(skip_dir in py_file.parts for skip_dir in skip_dirs):
            continue

        try:
            result.total_files += 1

            # Extract functions for CONTAINS relationships
            functions = extract_functions(py_file)
            contains_rels = create_contains_relationships(py_file, functions)
            result.contains_count += len(contains_rels)

            # Detect CALLS relationships
            call_rels = detect_calls(py_file)
            result.calls_count += len(call_rels)

            # Detect IMPORTS relationships
            import_rels = detect_imports(py_file)
            result.imports_count += len(import_rels)

            # Add all relationships to memory
            all_rels = contains_rels + call_rels + import_rels
            for rel in all_rels:
                create_relationship_memory(rel, client)

        except Exception as e:
            error_msg = f"Failed to link relationships for {py_file}: {e}"
            logger.error(error_msg)
            result.errors.append((str(py_file), str(e)))

    logger.info(
        f"Linking complete: {result.total_files} files, "
        f"{result.contains_count} contains, {result.calls_count} calls, "
        f"{result.imports_count} imports ({len(result.errors)} errors)"
    )

    return result


if __name__ == "__main__":
    from pathlib import Path

    # Test call detection on a known file with function calls
    test_file = Path(__file__).parent / "client.py"
    if test_file.exists():
        calls = detect_calls(test_file)
        print(f"Detected {len(calls)} call relationships in {test_file.name}")
        for rel in calls[:5]:
            print(f"  - {rel.source_entity} calls {rel.target_entity}")

        imports = detect_imports(test_file)
        print(f"Detected {len(imports)} import relationships")
        for rel in imports[:5]:
            print(f"  - imports {rel.target_entity}")

    # Test on memory module (dry run - no actual memory writes)
    print("\nDry run summary:")
    memory_dir = Path(__file__).parent
    from .indexing import extract_functions

    total_contains = 0
    total_calls = 0
    for py_file in memory_dir.glob("*.py"):
        functions = extract_functions(py_file)
        total_contains += len(functions)
        total_calls += len(detect_calls(py_file))
    print(f"  Contains relationships: {total_contains}")
    print(f"  Calls relationships: {total_calls}")
