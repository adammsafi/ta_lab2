"""ProjectTT document discovery and categorization.

Discovers all .docx and .xlsx files in ProjectTT directory,
categorizes by content type, and determines conversion priority.

Example:
    >>> from ta_lab2.tools.docs.discover_projecttt import discover_projecttt
    >>> docs = discover_projecttt()
    >>> print(f'Found {len(docs)} documents')
"""
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List
import json


@dataclass
class DocumentInfo:
    """Information about a ProjectTT document."""

    path: str
    name: str
    size_bytes: int
    extension: str
    subdirectory: str  # Features, Foundational, Plans&Status, root
    category: str  # architecture, features, planning, development
    priority: int  # 1=high, 2=medium, 3=low (based on size/importance)
    has_txt_version: bool  # Some already have .txt conversions

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


def categorize_document(doc_path: Path, subdirectory: str) -> str:
    """Categorize document by content type.

    Args:
        doc_path: Path to document
        subdirectory: Subdirectory location (Foundational, Features, etc.)

    Returns:
        Category string (architecture, features/*, planning, development, reference)
    """
    name_lower = doc_path.stem.lower()

    # Foundational/* -> architecture
    if subdirectory == "Foundational":
        return "architecture"

    # Features/EMAs/* -> features/emas
    if subdirectory.startswith("Features"):
        if "ema" in subdirectory.lower():
            return "features/emas"
        elif "bar" in subdirectory.lower():
            return "features/bars"
        elif "memory" in subdirectory.lower():
            return "features/memory"
        else:
            return "features"

    # Plans&Status/* -> planning
    if subdirectory == "Plans&Status":
        return "planning"

    # Root level categorization by filename
    if subdirectory == "root":
        # Architecture files (large schemas, workspace docs)
        if any(
            keyword in name_lower
            for keyword in ["schema", "workspace", "genesis", "core", "key"]
        ):
            return "architecture"
        # Planning/status files
        if any(keyword in name_lower for keyword in ["plan", "status", "vision"]):
            return "planning"
        # Excel study files
        if "study" in name_lower or "analysis" in name_lower:
            return "architecture"
        # Default root level
        return "reference"

    # Unknown subdirectory
    return "reference"


def determine_priority(doc_path: Path, size_bytes: int, category: str) -> int:
    """Determine conversion priority based on size and importance.

    Args:
        doc_path: Path to document
        size_bytes: File size in bytes
        category: Document category

    Returns:
        Priority (1=high, 2=medium, 3=low)
    """
    name_lower = doc_path.stem.lower()

    # Priority 1: Key docs or large files (>100KB)
    key_docs = [
        "workspace",
        "schema",
        "keyterms",
        "corecomponents",
        "genesis",
    ]
    if any(keyword in name_lower for keyword in key_docs):
        return 1

    if size_bytes > 100 * 1024:  # >100KB
        return 1

    # Priority 2: Feature docs or medium files (20KB-100KB)
    if category.startswith("features/") or (20 * 1024 <= size_bytes <= 100 * 1024):
        return 2

    # Priority 3: Status/temp docs or small files (<20KB)
    if "status" in name_lower or "temp" in name_lower or size_bytes < 20 * 1024:
        return 3

    # Default to medium priority
    return 2


def discover_projecttt(root_path: Path = None) -> List[DocumentInfo]:
    """Discover all .docx and .xlsx files in ProjectTT directory.

    Args:
        root_path: Root ProjectTT path (default: C:/Users/asafi/Documents/ProjectTT)

    Returns:
        List of DocumentInfo objects sorted by priority then path
    """
    if root_path is None:
        root_path = Path("C:/Users/asafi/Documents/ProjectTT")

    if not root_path.exists():
        raise FileNotFoundError(f"ProjectTT directory not found: {root_path}")

    documents = []

    # Find all .docx and .xlsx files (excluding temp files)
    for ext in ["*.docx", "*.xlsx"]:
        for file_path in root_path.rglob(ext):
            # Skip temp files (start with ~$)
            if file_path.name.startswith("~$"):
                continue

            # Determine subdirectory
            try:
                relative = file_path.relative_to(root_path)
                if len(relative.parts) > 1:
                    subdirectory = relative.parts[0]
                else:
                    subdirectory = "root"
            except ValueError:
                subdirectory = "unknown"

            # Categorize and prioritize
            category = categorize_document(file_path, subdirectory)
            size_bytes = file_path.stat().st_size
            priority = determine_priority(file_path, size_bytes, category)

            # Check for existing .txt version
            txt_version = file_path.with_suffix(".txt")
            has_txt_version = txt_version.exists()

            doc_info = DocumentInfo(
                path=str(file_path),
                name=file_path.name,
                size_bytes=size_bytes,
                extension=file_path.suffix[1:],  # Remove leading dot
                subdirectory=subdirectory,
                category=category,
                priority=priority,
                has_txt_version=has_txt_version,
            )
            documents.append(doc_info)

    # Sort by priority (ascending), then by path
    documents.sort(key=lambda d: (d.priority, d.path))

    return documents


def generate_inventory_report(docs: List[DocumentInfo]) -> dict:
    """Generate inventory report with categorization and conversion order.

    Args:
        docs: List of DocumentInfo objects

    Returns:
        JSON-serializable inventory dict
    """
    # Aggregate statistics
    total_files = len(docs)
    total_size_bytes = sum(d.size_bytes for d in docs)

    # Group by category
    by_category: Dict[str, List[dict]] = {}
    for doc in docs:
        doc_dict = doc.to_dict()
        by_category.setdefault(doc.category, []).append(doc_dict)

    # Group by priority
    by_priority: Dict[int, List[dict]] = {}
    for doc in docs:
        doc_dict = doc.to_dict()
        by_priority.setdefault(doc.priority, []).append(doc_dict)

    # Conversion order (paths sorted by priority)
    conversion_order = [doc.path for doc in docs]

    # Count by extension
    docx_count = sum(1 for d in docs if d.extension == "docx")
    xlsx_count = sum(1 for d in docs if d.extension == "xlsx")

    return {
        "total_files": total_files,
        "total_size_bytes": total_size_bytes,
        "docx_count": docx_count,
        "xlsx_count": xlsx_count,
        "by_category": by_category,
        "by_priority": by_priority,
        "conversion_order": conversion_order,
    }


def save_inventory_json(
    inventory: dict, output_path: Path, indent: int = 2
) -> None:
    """Save inventory report to JSON file.

    Args:
        inventory: Inventory report dict
        output_path: Path for output JSON file
        indent: JSON indentation (default: 2)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(inventory, indent=indent), encoding="utf-8")


if __name__ == "__main__":
    # Command-line execution
    docs = discover_projecttt()
    inventory = generate_inventory_report(docs)

    print(f"ProjectTT Document Inventory")
    print(f"=" * 60)
    print(f"Total files: {inventory['total_files']}")
    print(f"  DOCX: {inventory['docx_count']}")
    print(f"  XLSX: {inventory['xlsx_count']}")
    print(f"Total size: {inventory['total_size_bytes'] / 1024:.1f} KB")
    print()
    print("By Category:")
    for category, docs_list in inventory["by_category"].items():
        print(f"  {category}: {len(docs_list)} files")
    print()
    print("By Priority:")
    for priority, docs_list in sorted(inventory["by_priority"].items()):
        priority_name = {1: "High", 2: "Medium", 3: "Low"}.get(priority, "Unknown")
        print(f"  {priority_name}: {len(docs_list)} files")
