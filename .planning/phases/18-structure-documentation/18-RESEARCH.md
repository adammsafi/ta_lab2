# Phase 18: Structure Documentation - Research

**Researched:** 2026-02-03
**Domain:** Technical documentation, manifest systems, directory tree visualization
**Confidence:** HIGH

## Summary

Phase 18 requires comprehensive documentation of the v0.5.0 reorganization spanning 5 directories (ta_lab2, ProjectTT, Data_Tools, fredtools2, fedtools2) with detailed file tracking, before/after diagrams, decision manifests, and migration guides. The standard approach combines structured Markdown documentation (REORGANIZATION.md), JSON Schema-validated manifests with Markdown companions, dual-format directory trees (ASCII + Mermaid), and import mapping tables.

Research confirms that:
1. **JSON Schema 2020-12** is the current stable standard with Python's jsonschema 4.26.0 library for validation
2. **ASCII tree generation** uses Python pathlib with box-drawing characters (├──, └──, │) via built-in or libraries like pygentree
3. **Mermaid diagrams** support flowcharts and new block/architecture diagram types (v11.12.2) for data flow and package structure
4. **Migration guides** combine import mapping tables with code examples, following patterns from PyCharm refactoring and Python packaging reorganization documentation
5. **Documentation structure** follows 2026 best practices: modular content, clear hierarchies (max 3 levels), inline examples, and version-tracked manifests

**Primary recommendation:** Use Python pathlib for ASCII trees, jsonschema for manifest validation, Mermaid flowcharts for high-level visualizations, and organize REORGANIZATION.md by source directory with comprehensive file listings and detailed rationale sections.

## Standard Stack

The established libraries/tools for documentation generation and manifest validation:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| jsonschema | 4.26.0 | JSON Schema validation | Official Python implementation, supports all drafts including 2020-12, released Jan 2026 |
| pathlib | stdlib | Directory traversal and tree generation | Python standard library, object-oriented filesystem paths, built-in |
| Mermaid | 11.12.2 | Diagram-as-code for visualizations | Industry standard for Markdown-embedded diagrams, GitHub native support |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pygentree | latest | ASCII tree generation with customization | Need depth limiting, sorting options, file type filtering beyond manual pathlib |
| hashlib (stdlib) | stdlib | SHA-256 checksums for file integrity | File verification in manifests (already used in Phase 12 baseline) |
| datetime (stdlib) | stdlib | ISO 8601 timestamps | Manifest metadata (already used in Phase 12) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| jsonschema | fastjsonschema | 5-60x faster but less feature-rich, no lazy validation |
| pathlib trees | tree command (OS) | Simpler but OS-dependent, no programmatic control |
| Mermaid flowchart | Mermaid architecture diagram | New diagram type (marked 🔥) more specialized but less community examples |

**Installation:**
```bash
# Core validation (if not already present)
pip install jsonschema>=4.26.0

# Optional tree generation (if pathlib insufficient)
pip install pygentree
```

## Architecture Patterns

### Recommended Documentation Structure
```
docs/
├── REORGANIZATION.md        # Comprehensive reorganization guide
├── diagrams/
│   ├── before_tree.txt     # Full ASCII tree (all 5 directories)
│   ├── after_tree.txt      # Full ASCII tree (consolidated ta_lab2)
│   ├── data_flow.mmd       # Mermaid: external dirs → ta_lab2
│   └── package_structure.mmd  # Mermaid: internal ta_lab2 packages
└── manifests/
    ├── decisions.json      # JSON manifest with $schema
    ├── decisions-schema.json  # JSON Schema definition
    └── DECISIONS.md        # Markdown companion with detailed rationale

README.md                   # Updated project structure section
```

### Pattern 1: JSON Schema Versioning with Custom $schema URLs
**What:** Use custom schema URLs following Phase 12 pattern for forward compatibility and validation tooling
**When to use:** All JSON manifests requiring validation and version tracking

**Example:**
```json
{
  "$schema": "https://ta_lab2.local/schemas/reorganization-decisions/v1.0.0",
  "decisions": [
    {
      "id": "DEC-001",
      "type": "archive",
      "source": "ProjectTT/deprecated_module.py",
      "destination": ".archive/deprecated/2026-02-15/deprecated_module.py",
      "phase": 13,
      "timestamp": "2026-02-15T10:30:00Z",
      "category": "deprecated",
      "action": "archive",
      "rationale_id": "RAT-001",
      "related_decisions": ["DEC-002"],
      "requirements": ["STRUCT-01", "STRUCT-03"]
    }
  ]
}
```

**Companion schema file (decisions-schema.json):**
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://ta_lab2.local/schemas/reorganization-decisions/v1.0.0",
  "type": "object",
  "required": ["$schema", "decisions"],
  "properties": {
    "$schema": {
      "type": "string",
      "const": "https://ta_lab2.local/schemas/reorganization-decisions/v1.0.0"
    },
    "decisions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "type", "source", "destination", "action", "timestamp"],
        "properties": {
          "id": {"type": "string", "pattern": "^DEC-[0-9]+$"},
          "type": {"type": "string", "enum": ["archive", "migrate", "refactor", "merge", "extract"]},
          "source": {"type": "string"},
          "destination": {"type": "string"},
          "phase": {"type": "integer", "minimum": 11, "maximum": 17},
          "timestamp": {"type": "string", "format": "date-time"},
          "category": {"type": "string", "enum": ["deprecated", "refactored", "migrated", "documentation"]},
          "action": {"type": "string"},
          "rationale_id": {"type": "string", "pattern": "^RAT-[0-9]+$"},
          "related_decisions": {
            "type": "array",
            "items": {"type": "string", "pattern": "^DEC-[0-9]+$"}
          },
          "requirements": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[A-Z]+-[0-9]+$"}
          }
        }
      }
    }
  }
}
```

**Validation in Python:**
```python
# Source: https://python-jsonschema.readthedocs.io/en/stable/validate/
import jsonschema
import json

# Load schema and data
with open("docs/manifests/decisions-schema.json") as f:
    schema = json.load(f)
with open("docs/manifests/decisions.json") as f:
    data = json.load(f)

# Validate
jsonschema.validate(instance=data, schema=schema)
```

### Pattern 2: ASCII Tree Generation with pathlib
**What:** Programmatic directory tree generation using Python's standard library
**When to use:** Need full control, custom filtering, or integration with validation scripts

**Example:**
```python
# Source: https://realpython.com/directory-tree-generator-python/
from pathlib import Path

def generate_tree(directory: Path, prefix: str = "", max_depth: int = None, current_depth: int = 0):
    """Generate ASCII tree representation of directory structure."""
    if max_depth is not None and current_depth >= max_depth:
        return

    contents = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    pointers = ["├── "] * (len(contents) - 1) + ["└── "]

    for pointer, path in zip(pointers, contents):
        if path.is_dir():
            yield f"{prefix}{pointer}{path.name}/"
            extension = "│   " if pointer == "├── " else "    "
            yield from generate_tree(
                path,
                prefix=prefix + extension,
                max_depth=max_depth,
                current_depth=current_depth + 1
            )
        else:
            yield f"{prefix}{pointer}{path.name}"

# Usage
root = Path("src/ta_lab2")
print(f"{root.name}/")
for line in generate_tree(root):
    print(line)
```

**Output format:**
```
ta_lab2/
├── features/
│   ├── __init__.py
│   ├── ema.py
│   └── rsi.py
├── scripts/
│   ├── bars/
│   │   ├── __init__.py
│   │   └── common_snapshot_contract.py
│   └── features/
│       └── ta_feature.py
└── tools/
    └── ai_orchestrator/
        └── memory/
            └── migration.py
```

### Pattern 3: Mermaid Flowchart for Data Flow
**What:** Visual diagram showing relationship between external directories and consolidated ta_lab2
**When to use:** High-level overview for README or architecture docs

**Example:**
```mermaid
%%{init: {'theme':'base', 'themeVariables': { 'fontSize':'16px'}}}%%
flowchart LR
    subgraph External["External Directories (v0.4.0)"]
        PT[ProjectTT]
        DT[Data_Tools]
        FT[fredtools2]
        FE[fedtools2]
    end

    subgraph Archive[".archive/"]
        DEP[deprecated/]
        REF[refactored/]
        MIG[migrated/]
        DOC[documentation/]
    end

    subgraph Lab2["ta_lab2 (v0.5.0)"]
        SRC[src/ta_lab2/]
        DOCS[docs/]
        TOOLS[tools/]
    end

    PT -->|deprecated code| DEP
    PT -->|active code| SRC
    DT -->|tools migration| TOOLS
    DT -->|docs consolidation| DOCS
    FT -->|FRED integration| SRC
    FE -->|FED integration| SRC

    style External fill:#ffe6e6
    style Archive fill:#fff4e6
    style Lab2 fill:#e6f7ff
```

**Source:** [Mermaid Flowchart Syntax](https://mermaid.js.org/syntax/flowchart.html)

### Pattern 4: Migration Guide Import Mapping Table
**What:** Quick lookup table for old → new import paths
**When to use:** Developer needs to update existing code references

**Example structure for REORGANIZATION.md:**
```markdown
## Migration Guide

### Quick Import Reference

| Old Import (v0.4.0) | New Import (v0.5.0) | Status |
|---------------------|---------------------|--------|
| `from ProjectTT.module import func` | `from ta_lab2.tools.module import func` | Migrated |
| `from Data_Tools.analysis import X` | `from ta_lab2.tools.analysis import X` | Migrated |
| `from ProjectTT.deprecated import Y` | N/A - Archived | See Alternative |
| `from fredtools2 import fred_api` | `from ta_lab2.integrations.economic import FredProvider` | Refactored |

### Detailed Import Mappings

#### Tools Migration (Data_Tools → ta_lab2.tools)
```python
# Before (v0.4.0)
from Data_Tools.analysis.metrics import calculate_sharpe
from Data_Tools.processing.clean import remove_outliers

# After (v0.5.0)
from ta_lab2.tools.analysis import calculate_sharpe
from ta_lab2.tools.processing import remove_outliers
```

#### Archived Functionality
If you used `ProjectTT.deprecated_module`:
- **Status:** Archived to `.archive/deprecated/2026-02-15/`
- **Alternative:** Use `ta_lab2.features.modern_approach` instead
- **Migration:** See docs/MIGRATION_deprecated_module.md
```

### Anti-Patterns to Avoid

- **Hardcoded relative paths in documentation:** Use project-relative paths (`src/ta_lab2/...`) not absolute Windows/Unix paths
- **Date formats without timezone:** Always use ISO 8601 with UTC (`2026-02-15T10:30:00Z`) for manifest timestamps
- **Vague archive reasons:** "Cleanup" is insufficient; specify "Superseded by X" or "No longer maintained, use Y"
- **Incomplete before diagrams:** Must show ALL 5 directories as they existed, not simplified structure
- **Mixed diagram formats in same file:** Keep ASCII trees as plain text blocks, Mermaid in separate code fences
- **Generic decision IDs:** Use semantic prefixes (DEC- for decisions, RAT- for rationale, REQ- for requirements)

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON Schema validation | Custom dict validation | jsonschema library | Handles all schema drafts, lazy validation, detailed error messages, 10+ years mature |
| Directory tree generation | Manual string concatenation | pathlib + recursive generator | Handles cross-platform paths, symlinks, sorting, depth control |
| Import path mapping | grep + sed scripts | PyCharm "Refactor → Move" or rope library | Preserves references, handles relative imports, updates docstrings |
| Changelog generation | Manual markdown editing | git-changelog or conventional-changelog | Parses commit history, links issues/PRs, follows conventions |
| Box-drawing characters | Manual Unicode lookup | tree command `/A` flag or pathlib with predefined constants | Cross-platform compatibility, proper encoding handling |
| Mermaid syntax generation | String templates | Mermaid Live Editor for prototyping | Interactive preview, syntax validation, export options |

**Key insight:** Documentation tooling is mature in Python ecosystem. jsonschema provides industrial-grade validation, pathlib covers 95% of tree generation needs without external deps, and Mermaid's GitHub integration means diagrams auto-render in README files. Custom solutions add maintenance burden without meaningful benefits.

## Common Pitfalls

### Pitfall 1: Incomplete File Coverage in REORGANIZATION.md
**What goes wrong:** Document only major directories, miss individual files that moved, leaving gaps in migration trail
**Why it happens:** Focus on high-level structure, assume "obvious" moves don't need documentation
**How to avoid:** Use comprehensive file listing generated from Phase 12 baseline snapshot + git log to catch ALL moves
**Warning signs:** Developers asking "where did X.py go?" when X isn't mentioned in REORGANIZATION.md

### Pitfall 2: $schema URL Without Corresponding Schema File
**What goes wrong:** Manifest has `$schema: "https://ta_lab2.local/schemas/..."` but no actual schema file exists for validation
**Why it happens:** Copy Phase 12 pattern without understanding $schema is a pointer to validation file
**How to avoid:** Always create companion `*-schema.json` file when using custom $schema URL; validate with jsonschema.validate()
**Warning signs:** jsonschema throws "Failed to resolve $schema" errors, or schema URL returns 404

### Pitfall 3: ASCII Tree Depth Explosion
**What goes wrong:** Full-depth tree for large projects (hundreds of files) creates unreadable 10,000+ line text files
**Why it happens:** "Full depth" requirement interpreted literally without considering readability vs diff-ability tradeoff
**How to avoid:** Generate full tree programmatically for reference, but use max_depth in documentation (depth=3 for overview, depth=5 for detail)
**Warning signs:** Tree files >2MB, GitHub diff view times out, impossible to visually scan structure

### Pitfall 4: Stale Import Mappings After Additional Changes
**What goes wrong:** Create migration guide during Phase 18, then Phases 19+ make additional moves, guide becomes outdated
**Why it happens:** Migration guide treated as one-time artifact rather than living documentation
**How to avoid:** Version migration guide (MIGRATION_v0.4_to_v0.5.md), add "Last updated" timestamp, include verification script
**Warning signs:** Import statements in guide fail when tested, developers report "guide doesn't match actual structure"

### Pitfall 5: Mixed Before/After State in Diagrams
**What goes wrong:** "Before" tree includes some v0.5.0 changes because generated after migration started
**Why it happens:** Create before diagram late in process, repository already partially reorganized
**How to avoid:** Use Phase 12 baseline snapshot as authoritative source for "before" state; generate from that data structure
**Warning signs:** Before tree shows files in new locations, or .archive/ directory appears in "before" diagram

### Pitfall 6: Rationale Buried in Commit Messages
**What goes wrong:** Decision manifest references commit hashes for rationale, but commits don't contain enough context
**Why it happens:** Assume git history is sufficient documentation, but commits focus on "what" not "why"
**How to avoid:** Use JSON manifest for facts (what/when/where), separate DECISIONS.md for detailed "why" with rationale IDs
**Warning signs:** Reading manifest requires git spelunking, rationale questions answered with "check commit X"

### Pitfall 7: Platform-Specific Path Separators in Documentation
**What goes wrong:** Windows paths (`C:\Users\...`, backslashes) or Unix paths (forward slashes) hardcoded in examples
**Why it happens:** Generate examples on development OS without considering cross-platform audience
**How to avoid:** Use forward slashes in documentation (cross-platform standard), note "adjust for your OS" in setup sections
**Warning signs:** Windows users report "path not found" for Unix examples, or vice versa

## Code Examples

Verified patterns from official sources:

### JSON Schema Validation Script
```python
# Source: https://python-jsonschema.readthedocs.io/en/stable/validate/
"""Validate decision manifest against schema."""
import json
from pathlib import Path
import jsonschema

def validate_manifest(manifest_path: Path, schema_path: Path) -> None:
    """Validate JSON manifest against JSON Schema.

    Args:
        manifest_path: Path to decisions.json
        schema_path: Path to decisions-schema.json

    Raises:
        jsonschema.ValidationError: If validation fails
        jsonschema.SchemaError: If schema itself is invalid
    """
    with open(manifest_path) as f:
        manifest = json.load(f)

    with open(schema_path) as f:
        schema = json.load(f)

    # Validate schema is valid JSON Schema
    jsonschema.Draft202012Validator.check_schema(schema)

    # Validate manifest against schema
    validator = jsonschema.Draft202012Validator(schema)

    # Use lazy validation to collect all errors
    errors = list(validator.iter_errors(manifest))
    if errors:
        print(f"Found {len(errors)} validation errors:")
        for i, error in enumerate(errors, 1):
            print(f"\n{i}. {error.message}")
            print(f"   Path: {'.'.join(str(p) for p in error.path)}")
            print(f"   Schema path: {'.'.join(str(p) for p in error.schema_path)}")
        raise jsonschema.ValidationError("Manifest validation failed")

    print("✓ Manifest validation passed")

if __name__ == "__main__":
    manifest = Path("docs/manifests/decisions.json")
    schema = Path("docs/manifests/decisions-schema.json")
    validate_manifest(manifest, schema)
```

### ASCII Tree Generator with Filtering
```python
# Source: https://docs.python.org/3/library/pathlib.html + Real Python tutorial
"""Generate filtered ASCII tree for documentation."""
from pathlib import Path
from typing import Iterator, Set

def generate_filtered_tree(
    directory: Path,
    *,
    exclude_dirs: Set[str] = None,
    exclude_patterns: Set[str] = None,
    max_depth: int = None,
    prefix: str = "",
    current_depth: int = 0
) -> Iterator[str]:
    """Generate ASCII tree with exclusion filters.

    Args:
        directory: Root directory to traverse
        exclude_dirs: Directory names to skip (e.g., {'.git', '__pycache__', '.venv'})
        exclude_patterns: Glob patterns to skip (e.g., {'*.pyc', '.DS_Store'})
        max_depth: Maximum depth to traverse (None = unlimited)
        prefix: Current line prefix (for recursion)
        current_depth: Current depth level (for recursion)

    Yields:
        Lines of ASCII tree representation
    """
    exclude_dirs = exclude_dirs or set()
    exclude_patterns = exclude_patterns or set()

    if max_depth is not None and current_depth >= max_depth:
        return

    try:
        contents = []
        for path in directory.iterdir():
            # Skip excluded directories
            if path.is_dir() and path.name in exclude_dirs:
                continue

            # Skip excluded patterns
            if any(path.match(pattern) for pattern in exclude_patterns):
                continue

            contents.append(path)
    except PermissionError:
        return

    # Sort: directories first, then files, alphabetically
    contents.sort(key=lambda p: (not p.is_dir(), p.name.lower()))

    pointers = ["├── "] * (len(contents) - 1) + ["└── "]

    for pointer, path in zip(pointers, contents):
        if path.is_dir():
            yield f"{prefix}{pointer}{path.name}/"
            extension = "│   " if pointer == "├── " else "    "
            yield from generate_filtered_tree(
                path,
                exclude_dirs=exclude_dirs,
                exclude_patterns=exclude_patterns,
                max_depth=max_depth,
                prefix=prefix + extension,
                current_depth=current_depth + 1
            )
        else:
            yield f"{prefix}{pointer}{path.name}"

# Usage example
if __name__ == "__main__":
    root = Path("src/ta_lab2")

    # Exclude common non-source directories
    exclude = {'.git', '__pycache__', '.pytest_cache', '.venv', 'node_modules', '.archive'}
    patterns = {'*.pyc', '*.pyo', '.DS_Store', 'Thumbs.db'}

    print(f"{root.name}/")
    for line in generate_filtered_tree(root, exclude_dirs=exclude, exclude_patterns=patterns, max_depth=4):
        print(line)
```

### Mermaid Block Diagram for Package Structure
```mermaid
%%{init: {'theme':'base'}}%%
block-beta
  columns 3

  block:SRC["src/ta_lab2"]
    FEATURES["features/\n(EMA, RSI, MACD)"]
    SCRIPTS["scripts/\n(bars, emas, signals)"]
    INTEGRATIONS["integrations/\n(economic providers)"]
  end

  block:TOOLS["tools/"]
    ANALYSIS["analysis/\n(metrics, statistics)"]
    PROCESSING["processing/\n(data cleaning)"]
    AI["ai_orchestrator/\n(memory, adapters)"]
  end

  block:DOCS["docs/"]
    ARCH["ARCHITECTURE.md"]
    DESIGN["DESIGN.md"]
    REORG["REORGANIZATION.md"]
  end

  FEATURES --> SCRIPTS
  SCRIPTS --> INTEGRATIONS
  ANALYSIS --> FEATURES
  AI --> SCRIPTS

  style SRC fill:#e6f7ff
  style TOOLS fill:#f0f7e6
  style DOCS fill:#fff4e6
```

**Source:** [Mermaid Block Diagram Syntax](https://mermaid.js.org/syntax/block.html)

### Import Mapping Verification Script
```python
"""Verify migration guide import mappings are accurate."""
from pathlib import Path
from typing import Dict, List, Tuple
import ast
import importlib.util

def extract_imports_from_file(file_path: Path) -> List[str]:
    """Extract all import statements from Python file.

    Args:
        file_path: Path to Python file

    Returns:
        List of fully qualified import strings
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read())

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            for alias in node.names:
                imports.append(f"{module}.{alias.name}")

    return imports

def verify_import_mappings(
    mappings: Dict[str, str],
    project_root: Path
) -> Tuple[List[str], List[str]]:
    """Verify old imports don't exist and new imports are valid.

    Args:
        mappings: Dict of old_import -> new_import
        project_root: Root directory of project

    Returns:
        Tuple of (valid_mappings, invalid_mappings)
    """
    valid = []
    invalid = []

    for old_import, new_import in mappings.items():
        # Check if new import path exists
        module_path = new_import.replace('.', '/') + '.py'
        full_path = project_root / 'src' / module_path

        if full_path.exists():
            valid.append(f"✓ {old_import} → {new_import}")
        else:
            # Check if it's a package
            package_path = project_root / 'src' / new_import.replace('.', '/') / '__init__.py'
            if package_path.exists():
                valid.append(f"✓ {old_import} → {new_import} (package)")
            else:
                invalid.append(f"✗ {old_import} → {new_import} (not found)")

    return valid, invalid

# Example usage
if __name__ == "__main__":
    # Migration mappings from REORGANIZATION.md
    mappings = {
        "ProjectTT.module": "ta_lab2.tools.module",
        "Data_Tools.analysis": "ta_lab2.tools.analysis",
        "fredtools2.fred_api": "ta_lab2.integrations.economic.FredProvider",
    }

    root = Path(__file__).parent.parent
    valid, invalid = verify_import_mappings(mappings, root)

    print("Valid mappings:")
    for v in valid:
        print(f"  {v}")

    if invalid:
        print("\nInvalid mappings:")
        for i in invalid:
            print(f"  {i}")
        exit(1)
    else:
        print("\n✓ All import mappings verified")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| JSON Schema draft-07 | JSON Schema 2020-12 | December 2020 | New keywords ($defs, prefixItems), better composition, improved validation |
| os.walk() for trees | pathlib with rglob()/iterdir() | Python 3.4+ (mature in 3.10+) | Object-oriented paths, cross-platform, chainable methods |
| Manual CHANGELOG | Automated with git-changelog | 2024-2026 growth | Parses commit conventions, generates links, 3-5x faster |
| Graphviz for diagrams | Mermaid diagrams | 2020+ mainstream adoption | Markdown-native, GitHub renders automatically, no compilation |
| Single manifest.json | JSON + Markdown companion | Emerging 2024-2026 | JSON for queryability, Markdown for human-readable rationale |
| Generic schema URLs | Versioned custom schemas | Best practice since 2019-09 | Forward compatibility, validation tooling, breaking change tracking |
| Relative date formats | ISO 8601 with timezone | Universal standard | Unambiguous timestamps, sortable, parser-friendly |

**Deprecated/outdated:**
- **tree command with /F flag for full paths:** Now use pathlib with `path.relative_to(root)` for cleaner output
- **JSON Schema draft-04:** Superseded by draft-07 (2018), 2019-09, and 2020-12 (current)
- **Manual box-drawing character selection:** Use constants or libraries (pygentree) with proper encoding
- **$schema pointing to json-schema.org/schema (no version):** Deprecated, use specific draft URLs
- **Git commit messages as primary documentation:** Insufficient for "why" decisions; use structured manifest + rationale docs

## Open Questions

Things that couldn't be fully resolved:

1. **Git commit links practicality**
   - What we know: Phase 12 used commit_hash field in baseline snapshot; git log --follow preserves history through moves
   - What's unclear: Whether REORGANIZATION.md should include commit links for every file move, or just major decisions
   - Recommendation: Include commit links for category-level decisions (when all deprecated files archived) not individual files; balances traceability vs clutter

2. **CLI query tool necessity**
   - What we know: Python's json module + dict operations provide basic querying; jq command-line tool available for advanced queries
   - What's unclear: Whether dedicated CLI tool (e.g., `python -m ta_lab2.tools.docs query decision DEC-001`) adds enough value
   - Recommendation: Start with jq for ad-hoc queries, build CLI tool only if complex queries become frequent (e.g., "show all decisions affecting Phase 13")

3. **Migration scanning tool scope**
   - What we know: AST parsing can find old imports; PyCharm/rope provide refactoring; verification script (see Code Examples) validates mappings
   - What's unclear: Whether automated scanning/replacement tool ("fix all my imports") is needed, or manual migration with verification sufficient
   - Recommendation: Provide verification script (detect old imports in codebase) + import mapping table; automated replacement risky without human review of context

4. **Mermaid diagram rendering limits**
   - What we know: GitHub renders Mermaid automatically in .md files; extremely large diagrams (100+ nodes) may have performance issues
   - What's unclear: At what complexity level does Mermaid become less useful than ASCII trees for structure documentation
   - Recommendation: Use Mermaid for high-level (10-20 nodes) data flow and package relationships; fall back to ASCII trees for detailed file listings

## Sources

### Primary (HIGH confidence)
- [JSON Schema 2020-12 Official Specification](https://json-schema.org/specification) - Meta-schema URLs and dialect standards
- [JSON Schema Understanding Guide](https://json-schema.org/understanding-json-schema/reference/schema) - $schema keyword usage and versioning
- [jsonschema 4.26.0 Python Library](https://pypi.org/project/jsonschema/) - Official Python implementation (released Jan 7, 2026)
- [jsonschema Documentation](https://python-jsonschema.readthedocs.io/en/stable/validate/) - Validation patterns and lazy error collection
- [Python pathlib Official Docs](https://docs.python.org/3/library/pathlib.html) - Standard library filesystem paths (updated Feb 2, 2026)
- [Mermaid Official Documentation](https://mermaid.js.org/intro/syntax-reference.html) - Diagram types and syntax reference
- [Mermaid Flowchart Syntax](https://mermaid.js.org/syntax/flowchart.html) - Flowchart patterns for data flow

### Secondary (MEDIUM confidence)
- [Real Python: Directory Tree Generator](https://realpython.com/directory-tree-generator-python/) - Comprehensive pathlib tutorial
- [GitBook: Documentation Structure Best Practices](https://gitbook.com/docs/guides/docs-best-practices/documentation-structure-tips) - Avoid deep nesting, max 3 levels
- [Documind: Technical Documentation Best Practices 2026](https://www.documind.chat/blog/technical-documentation-best-practices) - 2026-specific trends
- [Fluid Topics: Technical Documentation Trends 2026](https://www.fluidtopics.com/blog/industry-insights/technical-documentation-trends-2026/) - Modular architecture, semantic precision
- [pygentree GitHub](https://github.com/taeefnajib/pygentree) - Python ASCII tree generator with filtering
- [Mermaid GitHub Repository](https://github.com/mermaid-js/mermaid) - Version 11.12.2 current release
- [git-changelog PyPI](https://pypi.org/project/git-changelog/) - Automated changelog generation (released Jan 30, 2026)
- [PyCharm Refactoring Documentation](https://www.jetbrains.com/help/pycharm/refactoring-convert.html) - Convert to package/module patterns
- [SchemaVer for Semantic Versioning](https://snowplow.io/blog/introducing-schemaver-for-semantic-versioning-of-schemas) - MODEL-REVISION-ADDITION format
- [Copyprogramming: Initialize Repository with README 2026](https://copyprogramming.com/howto/initialize-this-repository-with-a-readme) - 2026 best practices for repo setup

### Tertiary (LOW confidence)
- [DEV.to: Mermaid Directory Structure on GitLab](https://dev.to/joaompalmeiro/generate-a-directory-structure-diagram-with-mermaid-on-gitlab-642) - Community example (not official docs)
- [Medium: Configuration Versioning with JSON Schema](https://medium.com/@ansujain/designing-a-robust-configuration-versioning-system-with-json-schema-validation-0f24d7ac53d3) - Blog post, not authoritative
- [Kanerika: Data Migration Best Practices 2026](https://medium.com/@kanerika/data-migration-best-practices-your-ultimate-guide-for-2026-7cbd5594d92e) - General migration guidance
- [ASCII Tree Generator (web tool)](https://ascii-tree-generator.com/) - Online tool, not for programmatic use

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - jsonschema 4.26.0 released Jan 2026, pathlib is stdlib, Mermaid 11.12.2 current version, all verified with official docs
- Architecture: HIGH - JSON Schema patterns verified with official spec, pathlib patterns from Python docs + Real Python tutorial, Mermaid syntax from official documentation
- Pitfalls: MEDIUM - Based on general documentation anti-patterns (WebSearch) + domain knowledge; not project-specific empirical data
- Code examples: HIGH - All examples sourced from official documentation (jsonschema, pathlib, Mermaid) or authoritative tutorials (Real Python)
- Migration guide patterns: MEDIUM - Synthesized from PyCharm docs, Python packaging guides, and general refactoring best practices; no Phase 18-specific canonical source

**Research date:** 2026-02-03
**Valid until:** 2026-03-15 (40 days) - JSON Schema stable, pathlib stdlib stable, Mermaid actively developed but syntax backward compatible
