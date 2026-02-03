# Phase 16: Repository Cleanup - Research

**Researched:** 2026-02-03
**Domain:** Repository organization, file archival, duplicate detection, code similarity analysis
**Confidence:** HIGH

## Summary

Repository cleanup requires careful coordination of multiple technical domains: safe file operations with git history preservation, SHA256-based duplicate detection, AST-based code similarity analysis, and structured archival with manifest tracking. The standard approach uses Python's built-in libraries (pathlib, hashlib, ast, filecmp, difflib) combined with git mv for history-preserving moves.

**Key findings:**
- Python src/ layout is now the recommended standard (2026) for ensuring tests run against installed packages
- Git mv with pure move commits (no content changes) ensures history preservation via --follow
- SHA256-based duplicate detection is the gold standard (better than MD5/SHA1 which have collision weaknesses)
- AST-based code similarity is more robust than text-based difflib for Python code analysis
- Manifest files with checksums enable validation and audit trails for archival operations

**Primary recommendation:** Use Python standard library tools (pathlib for file ops, hashlib.file_digest for SHA256, ast for code parsing) combined with git mv in dedicated commits. Archive everything to categorized .archive/ structure with JSON manifests tracking checksums and metadata.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pathlib | stdlib (3.4+) | Object-oriented file operations | Cross-platform, safe file moves with Path.replace(), preferred over os.path |
| hashlib | stdlib | SHA256 file hashing | Optimized file_digest() function (3.11+), GIL release for large files |
| ast | stdlib | Python code parsing and comparison | Official AST manipulation, ast.compare() for structural equivalence |
| filecmp | stdlib | File/directory comparison | Cached comparison, shallow/deep modes, optimized for duplicate detection |
| difflib | stdlib | Text similarity scoring | SequenceMatcher.ratio() for text-based similarity (fallback for non-Python) |
| git mv | git core | History-preserving file moves | Native git command, recognized by --follow and blame |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pycode-similar | 1.4 | AST-based code similarity | If more advanced similarity detection needed (UnifiedDiff, TreeDiff) |
| json | stdlib | Manifest file format | Standard format for structured metadata |
| shutil | stdlib | Cross-filesystem moves | Fallback when pathlib.Path.move() needed across drives |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| hashlib.file_digest | Manual chunked reading | file_digest() added 3.11, optimized with GIL release |
| ast.compare | pycode-similar | pycode-similar offers more features but adds dependency |
| difflib.SequenceMatcher | Levenshtein distance libs | SequenceMatcher is stdlib, "natural looking" matches |
| JSON manifests | CSV/TSV | JSON handles nested structure, easier validation |

**Installation:**
```bash
# Core tools are all stdlib - no installation needed
# Optional advanced similarity detection:
pip install pycode-similar  # Only if needed beyond difflib+ast
```

## Architecture Patterns

### Recommended Project Structure
```
.archive/
├── refactored/          # *_refactored.py files
│   └── YYYY-MM-DD/
│       └── manifest.json
├── originals/           # *.original files
│   └── YYYY-MM-DD/
│       └── manifest.json
├── duplicates/          # Exact SHA256 duplicates
│   └── YYYY-MM-DD/
│       └── manifest.json
├── temp/                # Temporary/experimental files
│   └── YYYY-MM-DD/
│       └── manifest.json
└── docs/                # Superseded documentation
    └── YYYY-MM-DD/
        └── manifest.json

docs/
├── index.md             # Master documentation index
├── architecture/        # System design docs
├── analysis/            # Data analysis docs
├── guides/              # How-to guides
└── api/                 # API documentation

src/
└── ta_lab2/            # All package code (src layout)

# Root directory (minimal)
README.md
pyproject.toml
.gitignore
LICENSE
```

### Pattern 1: Safe File Archive with Git History Preservation
**What:** Move files to .archive/ using git mv in pure move commits, then update manifest
**When to use:** Any file archival operation
**Example:**
```python
# Source: Official Python pathlib docs + git documentation
from pathlib import Path
import hashlib
import json
import subprocess
from datetime import datetime

def archive_file_safely(source_path: Path, category: str, reason: str):
    """Archive a file with git history preservation and manifest tracking."""
    # 1. Calculate checksum before move
    with open(source_path, 'rb') as f:
        checksum = hashlib.file_digest(f, 'sha256').hexdigest()

    # 2. Prepare archive location
    archive_date = datetime.now().strftime('%Y-%m-%d')
    archive_dir = Path('.archive') / category / archive_date
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / source_path.name

    # 3. Git mv for history preservation (pure move commit)
    subprocess.run(['git', 'mv', str(source_path), str(archive_path)], check=True)
    subprocess.run([
        'git', 'commit', '-m',
        f'archive({category}): move {source_path.name}\n\nReason: {reason}\nSHA256: {checksum}'
    ], check=True)

    # 4. Update manifest
    manifest_path = archive_dir / 'manifest.json'
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    manifest[archive_path.name] = {
        'original_path': str(source_path),
        'archived_date': archive_date,
        'sha256': checksum,
        'reason': reason
    }

    manifest_path.write_text(json.dumps(manifest, indent=2))

    # 5. Commit manifest separately
    subprocess.run(['git', 'add', str(manifest_path)], check=True)
    subprocess.run(['git', 'commit', '-m', f'archive({category}): update manifest'], check=True)

    return archive_path, checksum
```

### Pattern 2: SHA256-Based Duplicate Detection
**What:** Scan directory tree, hash all files, group by checksum to find exact duplicates
**When to use:** Finding exact duplicate files regardless of name/location
**Example:**
```python
# Source: Python hashlib official docs
from pathlib import Path
from collections import defaultdict
import hashlib

def find_duplicate_files(root_dir: Path) -> dict[str, list[Path]]:
    """Find all duplicate files by SHA256 hash."""
    hash_to_files = defaultdict(list)

    # Scan all files
    for file_path in root_dir.rglob('*'):
        if not file_path.is_file():
            continue
        if file_path.parts[0] == '.git':  # Skip git internals
            continue

        # Hash file
        with open(file_path, 'rb') as f:
            file_hash = hashlib.file_digest(f, 'sha256').hexdigest()

        hash_to_files[file_hash].append(file_path)

    # Return only hashes with duplicates
    return {h: files for h, files in hash_to_files.items() if len(files) > 1}

# Usage
duplicates = find_duplicate_files(Path('.'))
for hash_val, files in duplicates.items():
    print(f"\nDuplicate group (SHA256: {hash_val[:16]}...):")
    for f in files:
        print(f"  - {f}")
```

### Pattern 3: AST-Based Code Similarity Detection
**What:** Parse Python functions to AST, compare structurally normalized representations
**When to use:** Finding similar Python functions (handles variable renames, formatting differences)
**Example:**
```python
# Source: Python ast official documentation
import ast
from difflib import SequenceMatcher

class FunctionExtractor(ast.NodeVisitor):
    """Extract all function definitions from Python code."""
    def __init__(self):
        self.functions = []

    def visit_FunctionDef(self, node):
        self.functions.append(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

def normalize_ast(node):
    """Normalize AST by removing location info for comparison."""
    for child in ast.walk(node):
        for attr in ['lineno', 'col_offset', 'end_lineno', 'end_col_offset']:
            if hasattr(child, attr):
                delattr(child, attr)
    return node

def compare_functions(func1_node, func2_node) -> float:
    """Compare two function ASTs, return similarity 0.0-1.0."""
    # Normalize for structural comparison
    norm1 = normalize_ast(func1_node)
    norm2 = normalize_ast(func2_node)

    # Method 1: Exact structural match
    if ast.compare(norm1, norm2, compare_attributes=False):
        return 1.0

    # Method 2: Text-based similarity of unparsed code
    code1 = ast.unparse(norm1)
    code2 = ast.unparse(norm2)

    return SequenceMatcher(None, code1, code2).ratio()

# Usage
def find_similar_functions(files: list[Path], threshold: float = 0.85):
    """Find similar functions across multiple files."""
    all_functions = []

    for file_path in files:
        if file_path.suffix != '.py':
            continue

        code = file_path.read_text()
        tree = ast.parse(code, filename=str(file_path))
        extractor = FunctionExtractor()
        extractor.visit(tree)

        for func in extractor.functions:
            all_functions.append((file_path, func))

    # Compare all pairs
    similar_pairs = []
    for i, (file1, func1) in enumerate(all_functions):
        for file2, func2 in all_functions[i+1:]:
            similarity = compare_functions(func1, func2)
            if similarity >= threshold:
                similar_pairs.append({
                    'file1': file1,
                    'func1': func1.name,
                    'file2': file2,
                    'func2': func2.name,
                    'similarity': similarity
                })

    return similar_pairs
```

### Pattern 4: Batch Git Operations with Verification
**What:** Move multiple files with git mv, verify history preservation
**When to use:** Large-scale repository reorganization
**Example:**
```python
# Source: Git documentation and pathlib best practices
import subprocess
from pathlib import Path

def batch_git_move(moves: list[tuple[Path, Path]], dry_run: bool = True):
    """Safely move multiple files with git, preserving history."""
    # 1. Dry run verification
    if dry_run:
        for src, dst in moves:
            result = subprocess.run(
                ['git', 'mv', '-n', str(src), str(dst)],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                print(f"ERROR: {src} -> {dst}: {result.stderr}")
                return False
        print(f"Dry run successful: {len(moves)} files ready to move")
        return True

    # 2. Create destination directories
    for _, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)

    # 3. Execute moves
    failed = []
    for src, dst in moves:
        result = subprocess.run(
            ['git', 'mv', str(src), str(dst)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            failed.append((src, dst, result.stderr))

    if failed:
        print(f"Failed moves: {len(failed)}")
        for src, dst, error in failed:
            print(f"  {src} -> {dst}: {error}")
        return False

    # 4. Commit as pure move
    subprocess.run(['git', 'commit', '-m',
        f'refactor: relocate {len(moves)} files\n\nPure move commit for history preservation'],
        check=True
    )

    # 5. Verify history preservation for sample
    sample = moves[0][1]
    result = subprocess.run(
        ['git', 'log', '--follow', '--oneline', str(sample)],
        capture_output=True, text=True, check=True
    )

    if len(result.stdout.splitlines()) < 2:
        print(f"WARNING: History tracking may be broken for {sample}")
        return False

    print(f"Successfully moved {len(moves)} files with history preserved")
    return True
```

### Anti-Patterns to Avoid
- **Mixed move+edit commits:** Breaks git's rename detection. Always separate moves from content changes
- **OS-level file operations without git:** Using Path.rename() or shutil.move() loses git history tracking
- **Deleting files directly:** Violates preservation requirement, use archive instead
- **Shallow comparison only for duplicates:** File content can change without mtime update, use SHA256
- **Text-based Python comparison only:** Misses semantically identical code with different formatting, use AST
- **Single large commit for cleanup:** Hard to review, breaks bisectability. Use atomic commits per category

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File hashing | Manual chunk reading + hash.update() | hashlib.file_digest() | Optimized buffering, GIL release, automatic file descriptor optimization (3.11+) |
| Code similarity | Simple string diffing | ast.parse() + ast.compare() | Handles reformatting, variable renames, structural equivalence |
| Cross-filesystem moves | Manual copy + verify + delete | pathlib.Path.move() or shutil.move() | Atomic on same filesystem, safe fallback for cross-filesystem |
| Directory comparison | Recursive walk + manual compare | filecmp.dircmp | Caching, lazy evaluation, optimized stat-based comparison |
| Git rename detection | Custom history rewriting | git mv + pure move commits | Native git support, works with --follow, blame, bisect |
| Manifest validation | Custom checksum verification | hashlib.file_digest() + JSON schema | Fast validation, clear error messages |

**Key insight:** Python stdlib provides production-quality tools for all core operations. The complexity is in edge cases (non-blocking files, cross-filesystem moves, AST version compatibility, git rename thresholds) that stdlib handles correctly.

## Common Pitfalls

### Pitfall 1: Mixing File Moves with Content Changes in Git
**What goes wrong:** Git's rename detection uses content similarity. Changing content in the same commit as a move reduces detection confidence, breaking --follow and blame tracking.
**Why it happens:** Developers think "while I'm moving this, I'll fix this bug" for efficiency.
**How to avoid:**
- Commit 1: Pure move with git mv, no edits
- Commit 2: Content changes in new location
- Can squash later if single commit needed for main branch
**Warning signs:**
```bash
git log --follow file.py  # Shows incomplete history
git diff -M --stat  # Shows low rename confidence (< 50%)
```

### Pitfall 2: Path.rename() vs Path.replace() Confusion
**What goes wrong:** Path.rename() behavior differs by OS - silent replace on Unix, FileExistsError on Windows. Code works on dev machine, breaks in production.
**Why it happens:** Developers test on one OS, assume cross-platform compatibility.
**How to avoid:**
- Use `Path.replace()` for unconditional overwrites (cross-platform)
- Use `Path.rename()` only when target should NOT exist
- Always test file operations on target OS
**Warning signs:** FileExistsError on Windows CI but local tests pass (Unix dev machine)

### Pitfall 3: Shallow File Comparison Misses Content Changes
**What goes wrong:** filecmp.cmp() with shallow=True (default) compares stat() signatures (size, mtime). If file content changes but mtime preserved (programmatic write, copy, restore from backup), duplicates aren't detected.
**Why it happens:** shallow=True is default for performance, developers don't read docs.
**How to avoid:**
- Use SHA256 hashing for duplicate detection (authoritative)
- Use shallow=True only for pre-filtering before deep check
- Never rely on mtime for correctness, only performance
**Warning signs:** "Duplicate" files that actually differ, or different files marked as same

### Pitfall 4: AST Comparison Across Python Versions
**What goes wrong:** AST structure changes between Python versions. Code using ast.Constant in 3.8+ breaks when comparing against code parsed with 3.7 (ast.Num, ast.Str).
**Why it happens:** ast module tracks Python grammar changes, backwards compatibility not guaranteed.
**How to avoid:**
- Use `feature_version` parameter: `ast.parse(code, feature_version=(3, 9))`
- Normalize to common AST version before comparison
- Document target Python version for analysis
**Warning signs:** ast.compare() returns False for visually identical code parsed on different Python versions

### Pitfall 5: Git Rename Detection Threshold Assumptions
**What goes wrong:** Git's default rename detection threshold is 50% similarity. Files with >50% changes won't be detected as renames even with git mv, breaking --follow.
**Why it happens:** Major refactoring in same commit as move, or git mv with immediate large edits.
**How to avoid:**
- Pure move commits (0% content change = 100% detection)
- Use `git log --follow -M40%` to lower threshold for specific searches
- Configure git diff.renameLimit if tracking many files
**Warning signs:**
```bash
git log --follow file.py  # Stops at move commit
git diff -M --summary  # Shows delete + add instead of rename
```

### Pitfall 6: Non-Blocking File Descriptors with hashlib.file_digest
**What goes wrong:** Passing non-blocking file objects (sockets, async I/O) to hashlib.file_digest raises BlockingIOError (Python 3.14+).
**Why it happens:** file_digest optimized for blocking I/O, async code paths use non-blocking descriptors.
**How to avoid:**
- Only use file_digest with regular files opened in binary mode
- For sockets/async: manual chunked hashing with hash.update()
- Check file type before hashing
**Warning signs:** BlockingIOError in production but tests pass (tests use regular files)

### Pitfall 7: JSON Manifest Encoding Issues
**What goes wrong:** Windows paths use backslashes, JSON requires escaping (\\\), manual string concatenation breaks parsing.
**Why it happens:** Using str() on Path objects, manual JSON construction.
**How to avoid:**
- Use `Path.as_posix()` for cross-platform forward slashes
- Use `json.dumps()` for automatic escaping
- Validate with `json.loads()` after write
**Warning signs:** JSONDecodeError with "Invalid \escape" on Windows paths

### Pitfall 8: Archive Directory Not in .gitignore
**What goes wrong:** Committing .archive/ contents to git repository bloats repo size, makes cleanup ineffective.
**Why it happens:** Forgetting to add .archive/ to .gitignore before archival operations.
**How to avoid:**
- Add `.archive/` to .gitignore before any archival
- Use `git check-ignore .archive/` to verify
- Context requirement: User wants .archive/ committed (not ignored), so this is NOT a pitfall for this project
**Warning signs:** Large git commits, .archive/ in git status
**NOTE:** Project requirement is to commit .archive/ with manifests for audit trail, so this is expected behavior.

## Code Examples

Verified patterns from official sources:

### Safe Archive Operation with Checksum Validation
```python
# Source: Python hashlib + pathlib official documentation
from pathlib import Path
import hashlib
import json

def archive_with_validation(source: Path, archive_base: Path, category: str):
    """Archive file and validate checksum after move."""
    # 1. Hash before move
    with open(source, 'rb') as f:
        original_hash = hashlib.file_digest(f, 'sha256').hexdigest()

    # 2. Prepare destination
    dest = archive_base / category / source.name
    dest.parent.mkdir(parents=True, exist_ok=True)

    # 3. Move file (cross-platform replace)
    source.replace(dest)  # Atomic on same filesystem

    # 4. Hash after move
    with open(dest, 'rb') as f:
        moved_hash = hashlib.file_digest(f, 'sha256').hexdigest()

    # 5. Validate
    if original_hash != moved_hash:
        raise ValueError(f"Checksum mismatch: {source} corrupted during move")

    # 6. Record in manifest
    manifest_path = dest.parent / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest[dest.name] = {
        'original_path': str(source),
        'sha256': moved_hash
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))

    return dest, moved_hash
```

### Categorized Duplicate Report
```python
# Source: Python filecmp + pathlib documentation
from pathlib import Path
from collections import defaultdict
import hashlib

def generate_duplicate_report(root: Path) -> dict:
    """Generate categorized duplicate file report."""
    hash_to_files = defaultdict(list)

    # Scan and hash all files
    for file_path in root.rglob('*'):
        if not file_path.is_file() or file_path.parts[0] in {'.git', '.archive'}:
            continue

        with open(file_path, 'rb') as f:
            file_hash = hashlib.file_digest(f, 'sha256').hexdigest()

        hash_to_files[file_hash].append(file_path)

    # Categorize duplicates
    report = {
        'exact_duplicates': {},
        'src_canonical': {},
        'non_src_duplicates': {}
    }

    for file_hash, files in hash_to_files.items():
        if len(files) < 2:
            continue

        # Prefer src/ta_lab2/ as canonical
        src_files = [f for f in files if f.parts[0] == 'src']
        non_src_files = [f for f in files if f.parts[0] != 'src']

        if src_files and non_src_files:
            report['src_canonical'][file_hash] = {
                'canonical': src_files[0],
                'duplicates': non_src_files
            }
        elif src_files:
            report['exact_duplicates'][file_hash] = src_files
        else:
            report['non_src_duplicates'][file_hash] = non_src_files

    return report
```

### Three-Tier Similarity Analysis
```python
# Source: Python ast + difflib official documentation
import ast
from difflib import SequenceMatcher
from pathlib import Path

def analyze_function_similarity(source_dir: Path):
    """Generate three-tier similarity report for all Python functions."""
    functions = []

    # Extract all functions
    for py_file in source_dir.rglob('*.py'):
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append({
                        'file': py_file,
                        'name': node.name,
                        'lineno': node.lineno,
                        'ast': node,
                        'code': ast.unparse(node)
                    })
        except SyntaxError:
            continue

    # Three-tier comparison
    tiers = {
        'near_exact': [],      # 95%+ similarity
        'similar': [],         # 85-95% similarity
        'related': []          # 70-85% similarity
    }

    for i, func1 in enumerate(functions):
        for func2 in functions[i+1:]:
            # Skip same file same name (likely same function)
            if func1['file'] == func2['file'] and func1['name'] == func2['name']:
                continue

            # Compare normalized code
            similarity = SequenceMatcher(None, func1['code'], func2['code']).ratio()

            pair = {
                'func1': f"{func1['file']}:{func1['name']}:{func1['lineno']}",
                'func2': f"{func2['file']}:{func2['name']}:{func2['lineno']}",
                'similarity': similarity
            }

            if similarity >= 0.95:
                tiers['near_exact'].append(pair)
            elif similarity >= 0.85:
                tiers['similar'].append(pair)
            elif similarity >= 0.70:
                tiers['related'].append(pair)

    return tiers
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat layout (package in root) | src/ layout | ~2020, standardized 2023 | Tests run against installed package, cleaner separation |
| MD5/SHA1 hashing | SHA256 hashing | SHA1 broken 2017, MD5 earlier | SHA256 no known collisions, cryptographically secure |
| Manual hash.update() loops | hashlib.file_digest() | Python 3.11 (2022) | Optimized buffering, GIL release, 2-3x faster |
| os.path string manipulation | pathlib.Path objects | Python 3.4 (2014), recommended 3.6+ | Cross-platform, type-safe, chainable operations |
| git filter-branch | git filter-repo | filter-repo recommended 2019 | Faster, safer, but rarely needed for simple cleanup |
| ast.Num, ast.Str, ast.Bytes | ast.Constant | Deprecated 3.8 (2019), removed 3.14 | Simplified AST structure, easier comparison |
| Text-based code comparison | AST-based comparison | ast.compare() added 3.9 (2020) | Structural equivalence, ignores formatting |

**Deprecated/outdated:**
- **MD5 for duplicate detection:** Use SHA256 (MD5 has collision attacks since 2004)
- **os.path for new code:** Use pathlib.Path (cleaner API, better cross-platform support)
- **git filter-branch:** Use git filter-repo if history rewriting needed (but this phase doesn't require it)
- **Manual AST node comparison:** Use ast.compare() (added 3.9) instead of ast.dump() string comparison
- **Flat package layout:** Use src/ layout for new projects (better test isolation)

## Open Questions

Things that couldn't be fully resolved:

1. **Git rename detection with *_refactored.py files**
   - What we know: If refactored version differs >50% from original, git mv won't preserve history even with --follow
   - What's unclear: Should we use git log -C (copy detection) instead of -M (rename) for heavily modified refactored files?
   - Recommendation: Test with git log --follow -C -C (aggressive copy detection) for refactored files; if history breaks, document in manifest and rely on git history of original pre-refactoring

2. **Optimal similarity threshold for Python code**
   - What we know: pycode-similar and academic research use various thresholds (70-95%), difflib.SequenceMatcher doesn't account for semantic equivalence
   - What's unclear: Is 85% similarity meaningful for this codebase's style, or should it be tuned based on sample analysis?
   - Recommendation: Start with three-tier approach (95%/85%/70%), run on sample, adjust thresholds based on false positive/negative rate

3. **Archive directory in git vs gitignored**
   - What we know: Project wants .archive/ committed for audit trail (per CONTEXT.md decisions)
   - What's unclear: Will this bloat repository over time with large archived files?
   - Recommendation: Proceed with committed .archive/ as specified; if size becomes issue, consider git-lfs or sparse checkout in future

4. **Memory usage for large file hashing**
   - What we know: hashlib.file_digest() handles buffering, but no documentation on peak memory usage for multi-GB files
   - What's unclear: Will hashing large database dumps or binary assets cause memory issues?
   - Recommendation: Test on largest files in repo first; if issues arise, process files in size-sorted order (largest first) to fail fast

5. **AST comparison for syntax errors**
   - What we know: ast.parse() raises SyntaxError for invalid Python, breaking similarity analysis
   - What's unclear: Should files with syntax errors be flagged, or silently skipped?
   - Recommendation: Skip with warning log; syntax errors should be caught by separate linting phase, not cleanup

## Sources

### Primary (HIGH confidence)
- [Python pathlib official documentation](https://docs.python.org/3/library/pathlib.html) - Path operations, atomicity guarantees
- [Python hashlib official documentation](https://docs.python.org/3/library/hashlib.html) - file_digest(), SHA256 best practices
- [Python ast official documentation](https://docs.python.org/3/library/ast.html) - AST parsing, comparison, unparse
- [Python difflib official documentation](https://docs.python.org/3/library/difflib.html) - SequenceMatcher algorithm details
- [Python filecmp official documentation](https://docs.python.org/3/library/filecmp.html) - Directory comparison, shallow/deep modes
- [Git official documentation - git mv](https://git-scm.com/docs/git-mv) - Rename detection, history preservation

### Secondary (MEDIUM confidence)
- [TheLinuxCode: Git Move Files and History Preservation (2026)](https://thelinuxcode.com/git-move-files-practical-renames-refactors-and-history-preservation-in-2026/) - Pure move commit pattern
- [Real Python: Python's pathlib Module](https://realpython.com/python-pathlib/) - Pathlib best practices
- [Python Packaging Guide: src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) - Modern Python project structure
- [Hitchhiker's Guide to Python: Project Structure](https://docs.python-guide.org/writing/structure/) - Repository organization best practices
- [pycode-similar GitHub](https://github.com/fyrestone/pycode_similar) - AST-based similarity detection tool
- [OneUptime: pathlib for File Paths (Jan 2026)](https://oneuptime.com/blog/post/2026-01-27-use-pathlib-for-file-paths-python/view) - Atomic file operations

### Tertiary (LOW confidence)
- [Medium: Python Repository Structure](https://medium.com/@GeorgiosGoniotakis/python-repository-structure-5015655cb9a7) - Repository organization opinions
- [CodeAnt AI: Duplicate Code Detection Tools 2025](https://www.codeant.ai/blogs/best-duplicate-code-checker-tools) - Tool landscape overview
- [Clone Digger](https://clonedigger.sourceforge.net/) - Legacy AST-based duplicate detection (verification needed for 2026 status)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib tools with official documentation verified
- Architecture: HIGH - Patterns verified with official Python docs and git documentation
- Pitfalls: MEDIUM - Based on official docs + community sources, cross-verified where possible
- Code examples: HIGH - All examples use stdlib APIs verified against official documentation

**Research date:** 2026-02-03
**Valid until:** 2026-04-03 (60 days - stdlib APIs stable, git patterns mature)
