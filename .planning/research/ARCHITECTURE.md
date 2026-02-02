# Architecture Research: Ecosystem Reorganization

**Domain:** Python monorepo consolidation (quantitative trading platform)
**Researched:** 2026-02-02
**Confidence:** HIGH

## Executive Summary

This research addresses how to consolidate 4 external directories (ProjectTT documentation, Data_Tools scripts, fredtools2/fedtools2 economic data packages) into the existing ta_lab2 v0.4.0 architecture without deletion, maintaining git history, and ensuring import validation.

The recommended approach follows 2026 Python monorepo best practices with phased integration: (1) archive management for backup artifacts, (2) documentation consolidation using centralized knowledge base patterns, (3) tools integration as internal utilities, and (4) economic data packages as optional dependencies with clear integration boundaries.

**Critical Finding:** Modern Python monorepos (2026) favor living-at-HEAD with editable installs, atomic changes, and workspace-level dependency management. The ta_lab2 src layout provides strong foundation for this consolidation.

## Current Architecture (Baseline)

### Existing ta_lab2 v0.4.0 Structure

```
ta_lab2/
├── src/ta_lab2/              # Main package (src layout)
│   ├── features/             # Technical indicators (EMAs, RSI, ATR)
│   ├── signals/              # Trading signal generators
│   ├── regimes/              # Market regime detection
│   ├── backtests/            # Backtesting engines
│   ├── pipelines/            # Orchestration workflows
│   ├── scripts/              # Executable data processing
│   │   ├── bars/             # Price bar refresh
│   │   ├── emas/             # EMA calculation
│   │   ├── pipeline/         # Daily refresh orchestration
│   │   └── etl/              # ETL tasks
│   ├── tools/                # Database utilities (existing)
│   │   ├── ai_orchestrator/  # AI coordination system
│   │   ├── dbtool.py         # DB maintenance
│   │   └── snapshot_diff.py  # Snapshot comparison
│   ├── time/                 # Time dimension (sessions, calendars)
│   ├── observability/        # Metrics, tracing, health
│   └── viz/                  # Visualization
├── .planning/                # GSD workflow (phases, research, codebase docs)
├── docs/                     # Documentation (existing)
│   ├── api/                  # API reference
│   ├── cheatsheets/          # Quick reference guides
│   ├── ops/                  # Operational docs
│   ├── qa/                   # QA documentation
│   ├── time/                 # Time model docs
│   └── *.md                  # Root-level docs (DESIGN.md, deployment.md)
├── tests/                    # Test suite
└── sql/                      # Database DDL and migrations
```

**Strengths:**
- Src layout (testing against installed package, not working directory)
- Clear separation: features → signals → backtests → observability
- Database-driven configuration (dim_timeframe, dim_sessions, dim_signals)
- State management for incremental refresh (watermarks per entity)
- Existing tools/ namespace for utilities

**Integration Capacity:**
- tools/ can absorb utility scripts without structural change
- docs/ has subcategories ready for consolidation
- src layout protects against import confusion during migration
- .planning/ provides research/decision documentation home

## Directories to Integrate

### 1. ProjectTT (Documentation Archive)

**Content Type:** Excel/Word documentation (domain knowledge, legacy specs)
**Format:** Binary files (.xlsx, .docx)
**Purpose:** Historical reference, domain expertise capture

**Integration Challenges:**
- Binary formats not git-friendly for diffs
- May contain sensitive information (trading strategies, API keys)
- Excel as computation tool vs documentation artifact

**Recommended Strategy:** Archive with conversion
- Extract text-based content (convert to Markdown where possible)
- Preserve originals in .archive/ for reference
- Index key information in docs/ with pointers to archive

### 2. Data_Tools (Python Utility Scripts)

**Content Type:** Python scripts for data manipulation
**Likely Contents:** ETL helpers, data validation, ad-hoc analysis scripts
**Current Status:** Standalone directory outside ta_lab2 package

**Integration Challenges:**
- Unknown import structure (standalone vs package-aware)
- Potential hardcoded paths or environment assumptions
- May have overlapping functionality with ta_lab2.scripts/

**Recommended Strategy:** Merge into ta_lab2.tools/ with triage
- Audit for overlap with existing scripts/tools
- Convert standalone scripts to package-aware imports
- Deprecate duplicates, integrate unique capabilities

### 3. fredtools2 (FRED API Package)

**Content Type:** Proper Python package with src/ structure
**Purpose:** Federal Reserve Economic Data API integration
**Standard Pattern:** Wrapper around FRED API (similar to fredapi, pyfredapi)

**Integration Challenges:**
- Already a proper package (has src/ structure)
- May have own pyproject.toml with dependencies
- Unclear if used by ta_lab2 currently

**Recommended Strategy:** Optional dependency with namespace preservation
- Keep as separate package in monorepo (monorepo doesn't mean one package)
- Reference as path dependency in ta_lab2's pyproject.toml (optional group)
- Install editable for local development: `pip install -e ./lib/fredtools2`

### 4. fedtools2 (Fed Funds ETL Package)

**Content Type:** Fed funds rate ETL pipeline
**Purpose:** Federal funds rate data extraction, transformation, loading
**Relationship:** Likely companion to fredtools2 (specific use case)

**Integration Challenges:**
- Similar to fredtools2 (proper package structure)
- May share code with fredtools2 (consider merging)
- Specialized use case (Fed funds vs general FRED data)

**Recommended Strategy:** Evaluate merge vs separate
- Assess code overlap with fredtools2
- If <30% code sharing, keep separate with path dependency
- If >30% overlap, merge into fredtools2.fedfunds submodule

## Recommended Integration Architecture

### Phase 1: Archive Management

**Create .archive/ structure for deprecated/backup artifacts**

```
ta_lab2/
└── .archive/
    ├── 00-README.md           # Index of archive contents
    ├── code/                  # Deprecated code (*.original, *_refactored.py)
    │   ├── bars/              # Old bar builder implementations
    │   ├── emas/              # Old EMA calculation variants
    │   └── features/          # Deprecated feature implementations
    ├── docs/                  # Historical documentation
    │   └── ProjectTT/         # ProjectTT documentation archive
    │       ├── 00-INDEX.md    # Catalog of documents
    │       ├── original/      # Unmodified Excel/Word files
    │       └── converted/     # Markdown conversions
    ├── notebooks/             # Research notebooks (if any)
    └── configs/               # Old configuration files
```

**Archival Rules:**
1. Nothing deleted from git history (preserve all commits)
2. Move to .archive/ with git mv (preserves history)
3. Create index files (00-README.md, 00-INDEX.md) for discoverability
4. Add .gitattributes rules for binary files (LFS if >100MB)

**What to Archive:**
- `*.original` files (backup artifacts scattered in src/)
- `*_refactored.py` files after integration validation
- Root directory clutter (temp scripts, test files)
- ProjectTT documentation (after extraction to docs/)

### Phase 2: Documentation Consolidation

**Integrate ProjectTT into docs/ with unified taxonomy**

```
ta_lab2/
└── docs/
    ├── index.md               # Central hub (enhanced with ProjectTT content)
    ├── api/                   # API reference (existing)
    ├── architecture/          # NEW: Architecture documentation
    │   ├── overview.md        # System architecture
    │   ├── feature-pipeline.md
    │   ├── signal-system.md
    │   └── time-model.md
    ├── domain/                # NEW: Domain knowledge from ProjectTT
    │   ├── strategies/        # Trading strategy documentation
    │   │   ├── ema-crossover.md
    │   │   ├── rsi-mean-revert.md
    │   │   └── atr-breakout.md
    │   ├── indicators/        # Indicator definitions
    │   │   ├── ema.md
    │   │   ├── rsi.md
    │   │   └── atr.md
    │   └── markets/           # Market structure, sessions, hours
    │       ├── crypto.md
    │       └── equity.md
    ├── ops/                   # Operational docs (existing, enhanced)
    │   ├── daily-refresh.md
    │   ├── backtest-workflow.md
    │   └── troubleshooting.md
    ├── migration/             # NEW: Migration and reorganization docs
    │   ├── v0.5-reorganization.md  # This milestone
    │   └── archived-content.md     # Index to .archive/
    └── external/              # NEW: External package integration
        ├── fredtools2.md      # FRED API usage
        └── fedtools2.md       # Fed funds integration
```

**Documentation Consolidation Pattern:**
1. **Audit Phase:** Inventory ProjectTT content (Excel sheets → topics, Word docs → sections)
2. **Extraction Phase:** Convert binary to Markdown (pandoc for Word, manual for Excel)
3. **Taxonomy Phase:** Map content to docs/ structure (domain/, architecture/, ops/)
4. **Integration Phase:** Create unified index (docs/index.md links to all sections)
5. **Archive Phase:** Move originals to .archive/docs/ProjectTT/original/

**Unified Style Guide:**
- Markdown for all text content (consistency with existing docs/)
- Code examples use python syntax highlighting
- Inline links to source code (e.g., `src/ta_lab2/features/ema.py`)
- Versioned documentation (tag with v0.5.0 for reorganization)

### Phase 3: Tools Integration

**Merge Data_Tools into ta_lab2.tools/ with namespace organization**

```
ta_lab2/
└── src/ta_lab2/tools/
    ├── __init__.py            # Export public tools API
    ├── ai_orchestrator/       # Existing: AI coordination
    ├── dbtool.py              # Existing: Database utilities
    ├── snapshot_diff.py       # Existing: Snapshot comparison
    ├── data_tools/            # NEW: Migrated from Data_Tools/
    │   ├── __init__.py        # Expose data manipulation utilities
    │   ├── validators/        # Data validation scripts
    │   │   ├── schema_check.py
    │   │   └── integrity_check.py
    │   ├── transforms/        # Data transformation utilities
    │   │   ├── normalizer.py
    │   │   └── aggregator.py
    │   ├── exporters/         # Data export helpers
    │   │   ├── csv_export.py
    │   │   └── parquet_export.py
    │   └── legacy/            # Scripts needing refactor
    │       └── 00-README.md   # Migration status tracker
    └── cli/                   # NEW: Unified CLI for tools
        ├── __init__.py
        ├── data_tools_cli.py  # Data_Tools commands
        └── orchestrator_cli.py # AI orchestrator commands (moved)
```

**Migration Strategy:**
1. **Audit Phase:** Inventory Data_Tools scripts, identify dependencies
2. **Categorize Phase:** Group by function (validators, transforms, exporters)
3. **Refactor Phase:** Update imports to use ta_lab2 namespace
   - Change: `from data_utils import X` → `from ta_lab2.tools.data_tools import X`
4. **Test Phase:** Validate imports work after migration
5. **Deprecate Phase:** Add deprecation warnings to old paths (if discoverable)

**Import Validation Pattern:**
```python
# In ta_lab2/tools/data_tools/__init__.py
from .validators import schema_check, integrity_check
from .transforms import normalizer, aggregator
from .exporters import csv_export, parquet_export

__all__ = [
    "schema_check",
    "integrity_check",
    "normalizer",
    "aggregator",
    "csv_export",
    "parquet_export"
]
```

**Testing Strategy:**
```python
# tests/tools/test_data_tools_imports.py
def test_data_tools_namespace():
    """Validate all data_tools utilities are importable."""
    from ta_lab2.tools.data_tools import (
        schema_check,
        integrity_check,
        normalizer,
        aggregator,
    )
    assert callable(schema_check)
    assert callable(integrity_check)
```

### Phase 4: Economic Data Packages

**Monorepo structure with separate packages and path dependencies**

```
ta_lab2/
├── src/ta_lab2/              # Main package (unchanged)
├── lib/                      # NEW: Shared libraries (monorepo pattern)
│   ├── fredtools2/           # FRED API wrapper
│   │   ├── pyproject.toml    # Own dependencies (requests, pandas)
│   │   ├── src/
│   │   │   └── fredtools2/
│   │   │       ├── __init__.py
│   │   │       ├── client.py
│   │   │       ├── series.py
│   │   │       └── categories.py
│   │   ├── tests/
│   │   └── README.md
│   └── fedtools2/            # Fed funds ETL (or merge into fredtools2)
│       ├── pyproject.toml
│       ├── src/
│       │   └── fedtools2/
│       │       ├── __init__.py
│       │       ├── etl.py
│       │       └── pipeline.py
│       ├── tests/
│       └── README.md
├── pyproject.toml            # Root workspace manifest (NEW)
└── uv.lock                   # Unified lock file (NEW, if using uv)
```

**Root pyproject.toml (Workspace Configuration):**
```toml
[tool.uv.workspace]
members = [
    "src/ta_lab2",
    "lib/fredtools2",
    "lib/fedtools2"
]

[project]
name = "ta_lab2-workspace"
version = "0.5.0"

[project.optional-dependencies]
economic-data = [
    "fredtools2",
    "fedtools2"
]
```

**ta_lab2 pyproject.toml (Main Package):**
```toml
[project]
name = "ta_lab2"
version = "0.5.0"

[project.optional-dependencies]
economic-data = [
    "fredtools2 @ file:///${PROJECT_ROOT}/lib/fredtools2",
    "fedtools2 @ file:///${PROJECT_ROOT}/lib/fedtools2"
]

# Install with: pip install -e ".[economic-data]"
```

**Integration Pattern (Optional Dependency):**
```python
# In ta_lab2/scripts/etl/fetch_fred_data.py
try:
    from fredtools2 import FredClient
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False

def fetch_unemployment_rate():
    if not FRED_AVAILABLE:
        raise RuntimeError(
            "fredtools2 not installed. "
            "Install with: pip install -e '.[economic-data]'"
        )
    client = FredClient(api_key=os.getenv("FRED_API_KEY"))
    return client.get_series("UNRATE")
```

**Decision Matrix: Merge vs Separate**

| Criterion | Merge into fredtools2 | Keep Separate |
|-----------|----------------------|---------------|
| Code overlap | >30% shared code | <30% shared code |
| Dependencies | Identical deps | Different deps |
| Release cycle | Same cadence | Independent updates |
| API surface | Cohesive single API | Distinct use cases |

**Recommendation:** Start separate, merge later if overlap discovered

## Integration Points

### A. Archive → Documentation Flow

```
ProjectTT/strategy_notes.docx
    ↓ (pandoc conversion)
docs/domain/strategies/ema-crossover.md
    ↓ (git mv original)
.archive/docs/ProjectTT/original/strategy_notes.docx
    ↓ (index update)
.archive/docs/ProjectTT/00-INDEX.md (new entry)
```

### B. Data_Tools → ta_lab2.tools Flow

```
Data_Tools/validate_bars.py
    ↓ (refactor imports)
src/ta_lab2/tools/data_tools/validators/bar_validator.py
    ↓ (expose in __init__)
ta_lab2.tools.data_tools.validators.bar_validator
    ↓ (test import)
tests/tools/test_bar_validator.py (validates import works)
```

### C. Economic Packages → Optional Dependency Flow

```
fredtools2/ (standalone)
    ↓ (move to lib/)
lib/fredtools2/ (monorepo package)
    ↓ (add to workspace)
pyproject.toml [tool.uv.workspace] members
    ↓ (install editable)
pip install -e ./lib/fredtools2
    ↓ (import in ta_lab2)
ta_lab2.scripts.etl.fetch_fred_data imports fredtools2
    ↓ (graceful degradation)
ImportError → helpful message with install command
```

### D. Root Cleanup → Archive Flow

```
Root directory clutter (run_btc.py, test_*.py, convert_*.py)
    ↓ (categorize: scripts, tests, utilities)
Categorize into: archive_scripts/, archive_tests/, archive_utils/
    ↓ (git mv to .archive/)
.archive/code/scripts/, .archive/code/tests/
    ↓ (update .archive/00-README.md)
Index with purpose, migration date, replacement location
```

## Component Responsibilities

| Component | Responsibility | Integration Touch Points |
|-----------|----------------|--------------------------|
| **ta_lab2/** (main) | Core trading infrastructure | Imports from lib/ (optional), uses tools/ |
| **lib/fredtools2** | FRED API client | Standalone, optional dependency of ta_lab2 |
| **lib/fedtools2** | Fed funds ETL | Standalone, optional dependency of ta_lab2 |
| **tools/data_tools** | Data manipulation utilities | Used by scripts/, pipelines/ |
| **docs/** | Unified documentation | References .archive/, lib/ packages |
| **.archive/** | Historical artifacts | Read-only reference, git history preserved |
| **.planning/** | GSD workflow artifacts | Documents decisions, research, roadmap |

## Data Flow

### 1. Development Workflow (Post-Reorganization)

```
Developer checks out ta_lab2
    ↓
pip install -e . (installs ta_lab2 in editable mode)
    ↓
Optional: pip install -e ".[economic-data]" (installs lib packages)
    ↓
Import validation: python -c "import ta_lab2; import ta_lab2.tools.data_tools"
    ↓
Run tests: pytest tests/
    ↓
Verify imports work after reorganization
```

### 2. Documentation Lookup Flow

```
User seeks strategy documentation
    ↓
docs/index.md (central hub)
    ↓
docs/domain/strategies/ (consolidated content)
    ↓
If needs historical reference: docs/migration/archived-content.md
    ↓
.archive/docs/ProjectTT/original/ (original files)
```

### 3. Economic Data Integration Flow

```
ta_lab2 pipeline needs unemployment rate
    ↓
scripts/etl/fetch_fred_data.py
    ↓
Check if fredtools2 available (try import)
    ↓
If available: FredClient.get_series("UNRATE")
    ↓
If not available: Helpful error with install command
    ↓
Store in ta_lab2 database (integration complete)
```

### 4. Tool Discovery Flow

```
User needs data validation utility
    ↓
ta_lab2 CLI: python -m ta_lab2.tools.cli data-tools --list
    ↓
Discover: bar_validator, schema_check, integrity_check
    ↓
Run: python -m ta_lab2.tools.data_tools.validators.bar_validator --table cmc_price_bars_1d
    ↓
Validation report with metrics
```

## Architectural Patterns

### Pattern 1: Graceful Optional Dependencies

**What:** Import external packages with try/except, provide helpful errors

**When to use:** Economic data packages (fredtools2, fedtools2) - not all users need them

**Trade-offs:**
- Pros: Minimal install, pay-for-what-you-use, clear error messages
- Cons: Runtime detection (not install-time), needs documentation

**Example:**
```python
# ta_lab2/integrations/fred.py
try:
    from fredtools2 import FredClient
    HAS_FRED = True
except ImportError:
    HAS_FRED = False
    FredClient = None

def get_fred_series(series_id: str, api_key: str):
    """Fetch FRED series data.

    Requires fredtools2 package:
        pip install -e ".[economic-data]"
    """
    if not HAS_FRED:
        raise ImportError(
            "fredtools2 not available. "
            "Install with: pip install -e '.[economic-data]'"
        )
    client = FredClient(api_key=api_key)
    return client.get_series(series_id)
```

### Pattern 2: Archive with Index

**What:** Move deprecated content to .archive/ with comprehensive indexes

**When to use:** Deprecating code, consolidating documentation, cleaning root directory

**Trade-offs:**
- Pros: Preserves git history, maintains discoverability, reduces clutter
- Cons: Requires index maintenance, adds directory depth

**Example:**
```markdown
# .archive/00-README.md

## Archive Organization

This directory preserves deprecated code and historical documentation.
All content maintains full git history via `git mv`.

### Code Archives
- **code/bars/**: Deprecated bar builder implementations (pre-v0.4.0)
  - Last used: 2026-01-15
  - Replacement: `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py`
- **code/emas/**: Old EMA calculation variants
  - Last used: 2026-01-20
  - Replacement: `src/ta_lab2/features/m_tf/`

### Documentation Archives
- **docs/ProjectTT/**: Original Excel/Word documentation
  - Consolidated into: `docs/domain/` (2026-02-02)
  - Index: `.archive/docs/ProjectTT/00-INDEX.md`
```

### Pattern 3: Namespace Preservation in Monorepo

**What:** Keep separate packages as separate namespaces, use path dependencies

**When to use:** Proper packages with distinct purposes (fredtools2, fedtools2)

**Trade-offs:**
- Pros: Clear boundaries, independent versioning, testable in isolation
- Cons: More complex dependency management, requires workspace tooling

**Example:**
```python
# Separate namespaces (NOT merged into ta_lab2)
from fredtools2 import FredClient  # lib/fredtools2/
from fedtools2 import FedFundsPipeline  # lib/fedtools2/
from ta_lab2.tools.data_tools import schema_check  # merged into ta_lab2

# Integration in ta_lab2 script
def enrich_with_economic_data(df):
    """Enrich price data with economic indicators."""
    if HAS_FRED:
        unemployment = get_fred_series("UNRATE", api_key)
        df = df.merge(unemployment, on="date", how="left")
    return df
```

### Pattern 4: Phased Migration with Validation Gates

**What:** Migrate incrementally with tests validating each phase completion

**When to use:** All integration phases (archives, docs, tools, packages)

**Trade-offs:**
- Pros: Safe incremental progress, clear rollback points, test coverage
- Cons: Takes longer than big-bang migration

**Example:**
```python
# tests/integration/test_phase2_docs_consolidated.py
def test_projecttt_docs_consolidated():
    """Validate ProjectTT documentation consolidated into docs/."""
    docs_domain = Path("docs/domain")
    assert docs_domain.exists(), "docs/domain/ should exist"

    strategy_docs = list(docs_domain.glob("strategies/*.md"))
    assert len(strategy_docs) >= 3, "Should have ≥3 strategy docs"

    archive_index = Path(".archive/docs/ProjectTT/00-INDEX.md")
    assert archive_index.exists(), "Archive index should exist"

def test_data_tools_importable():
    """Validate Data_Tools migrated and importable."""
    from ta_lab2.tools.data_tools import (
        schema_check,
        integrity_check,
        normalizer
    )
    assert callable(schema_check)
    assert callable(integrity_check)
    assert callable(normalizer)
```

## Scaling Considerations

| Scale | Approach |
|-------|----------|
| **Current (v0.5.0)** | Single developer, local workstation, simple pip installs |
| **Near-term (v0.6-0.8)** | Small team (2-3), introduce uv for workspace management, CI validates imports |
| **Mid-term (v1.0+)** | Team of 5-10, consider Pants/Bazel for fine-grained caching, automated dependency updates |

### Scaling Priorities

1. **First bottleneck:** Import confusion from reorganization
   - **Fix:** Comprehensive import validation tests (phase-gated)
   - **Prevention:** Namespace consistency, clear __init__.py exports

2. **Second bottleneck:** Dependency drift across lib/ packages
   - **Fix:** Unified lock file (uv.lock or poetry.lock)
   - **Prevention:** Workspace-aware tooling (uv workspaces, poetry path deps)

## Anti-Patterns

### Anti-Pattern 1: Delete Instead of Archive

**What people do:** Delete deprecated files to "clean up" repository

**Why it's wrong:**
- Loses git history context (why was this approach tried?)
- No reference for future investigations
- Can't compare old vs new implementations
- Breaks git blame chains

**Do this instead:**
- git mv to .archive/ (preserves full history)
- Create index files explaining deprecation rationale
- Link to replacement locations
- Keep files readable for future reference

### Anti-Pattern 2: Merge All Packages into One

**What people do:** Import fredtools2/fedtools2 directly into ta_lab2 namespace

**Why it's wrong:**
- Breaks separation of concerns (FRED API != trading logic)
- Forces all users to install economic data dependencies
- Makes independent versioning impossible
- Complicates testing (can't test FRED integration without ta_lab2)

**Do this instead:**
- Keep as separate packages in lib/
- Use optional dependencies ([economic-data] extra)
- Import with try/except for graceful degradation
- Document integration points clearly

### Anti-Pattern 3: Documentation Duplication

**What people do:** Copy Excel content to Markdown, keep both in docs/

**Why it's wrong:**
- Creates maintenance burden (update in two places)
- Confuses users (which is source of truth?)
- Wastes repository space with binary files in docs/

**Do this instead:**
- Convert Excel to Markdown (single source of truth in docs/)
- Move Excel originals to .archive/ (reference only)
- Create index linking docs/ to archive/ (traceability)
- Use docs/index.md as central hub (no duplication)

### Anti-Pattern 4: Hardcoded Paths in Migrated Scripts

**What people do:** Move Data_Tools scripts without updating hardcoded paths

**Why it's wrong:**
- Scripts break when directory structure changes
- Tight coupling to specific filesystem layout
- Fails on different machines (Windows vs Linux paths)

**Do this instead:**
- Use __file__ and Path for relative imports
- Reference package resources via importlib.resources
- Environment variables for configurable paths (FRED_API_KEY, DB_URL)
- Document required environment setup in README

Example refactor:
```python
# BAD: Hardcoded path
data_dir = "/Users/asafi/data/fred"

# GOOD: Relative to package
from pathlib import Path
data_dir = Path(__file__).parent.parent / "data" / "fred"

# BETTER: Environment variable with default
import os
data_dir = Path(os.getenv("FRED_DATA_DIR", "./data/fred"))
```

## Build Order (Phased Approach)

### Phase 1: Archive Management (Week 1, Days 1-2)
**Goal:** Move backup artifacts to .archive/, establish indexing pattern

**Steps:**
1. Create .archive/ structure (code/, docs/, configs/)
2. Identify candidates: `*.original`, `*_refactored.py`, root clutter
3. git mv candidates to .archive/ (preserves history)
4. Create .archive/00-README.md with index
5. Validate: git log --follow shows history

**Validation Gate:**
- All *.original files in .archive/code/
- .archive/00-README.md comprehensively documents contents
- git log --follow works for archived files

### Phase 2: Documentation Consolidation (Week 1, Days 3-4)
**Goal:** Integrate ProjectTT docs into docs/, archive originals

**Steps:**
1. Audit ProjectTT content (inventory Excel sheets, Word docs)
2. Create docs/domain/, docs/architecture/, docs/migration/
3. Convert Excel/Word to Markdown (pandoc, manual extraction)
4. Organize into taxonomy (strategies/, indicators/, markets/)
5. git mv ProjectTT originals to .archive/docs/ProjectTT/original/
6. Create .archive/docs/ProjectTT/00-INDEX.md
7. Update docs/index.md with new sections

**Validation Gate:**
- All ProjectTT content accessible via docs/index.md
- Archive index maps old content to new locations
- Markdown files render correctly in docs/

### Phase 3: Tools Integration (Week 2, Days 1-3)
**Goal:** Merge Data_Tools into ta_lab2.tools/, validate imports

**Steps:**
1. Audit Data_Tools scripts (categorize by function)
2. Create src/ta_lab2/tools/data_tools/ structure
3. Refactor imports to use ta_lab2 namespace
4. Update __init__.py to expose public API
5. Write import validation tests (tests/tools/test_data_tools_imports.py)
6. Run tests: pytest tests/tools/
7. Document migration in docs/migration/v0.5-reorganization.md

**Validation Gate:**
- All Data_Tools scripts importable via ta_lab2.tools.data_tools
- Import tests pass (100% coverage of public API)
- No hardcoded paths remain

### Phase 4: Economic Data Packages (Week 2, Days 4-5)
**Goal:** Integrate fredtools2/fedtools2 as optional dependencies

**Steps:**
1. Assess fredtools2/fedtools2 structure (confirm proper packages)
2. Decide: merge vs separate (use decision matrix)
3. Create lib/ directory, move packages
4. Create root pyproject.toml with workspace config
5. Add optional-dependencies to ta_lab2 pyproject.toml
6. Install editable: pip install -e ./lib/fredtools2
7. Create integration example in ta_lab2/scripts/etl/
8. Write graceful degradation tests

**Validation Gate:**
- fredtools2/fedtools2 installable via pip install -e ./lib/*
- ta_lab2 imports work with and without economic-data extra
- Helpful error message when not installed

### Phase 5: Root Cleanup (Week 2, Day 5)
**Goal:** Clean root directory, archive remaining clutter

**Steps:**
1. Categorize root clutter (scripts, tests, temp files)
2. git mv to .archive/ appropriate subdirectories
3. Update .archive/00-README.md with new entries
4. Verify root directory clean (only essential files)
5. Update .gitignore if needed

**Validation Gate:**
- Root directory contains only: src/, lib/, docs/, tests/, .planning/, config files
- All clutter archived with git history
- .archive/00-README.md complete

### Phase 6: Structure Documentation (Week 2, Day 5)
**Goal:** Document new structure, write migration guide

**Steps:**
1. Update .planning/codebase/STRUCTURE.md (new architecture)
2. Create docs/migration/v0.5-reorganization.md (migration guide)
3. Update README.md with ecosystem structure
4. Create visual diagrams (optional, if time permits)

**Validation Gate:**
- STRUCTURE.md reflects post-reorganization state
- Migration guide explains all changes
- README.md updated with new structure

### Phase 7: Final Verification (Week 2, Day 5)
**Goal:** End-to-end validation, smoke tests

**Steps:**
1. Fresh clone test: git clone → pip install -e . → pytest
2. Import smoke test: python -c "import ta_lab2; import ta_lab2.tools.data_tools"
3. Run daily refresh pipeline (validate operational scripts work)
4. Check docs render (mkdocs serve or similar)
5. Tag release: git tag v0.5.0

**Validation Gate:**
- Fresh install works (all imports resolve)
- All tests pass (no import errors)
- Daily refresh pipeline runs successfully
- Documentation builds without errors

## Sources

### Python Monorepo Structure
- [Python Monorepo: an Example. Part 1: Structure and Tooling - Tweag](https://www.tweag.io/blog/2023-04-04-python-monorepo-1/)
- [Python monorepos - Graphite](https://graphite.dev/guides/python-monorepos)
- [Building a Monorepo with Python - Earthly Blog](https://earthly.dev/blog/python-monorepo/)
- [Our Python Monorepo - Opendoor Labs](https://medium.com/opendoor-labs/our-python-monorepo-d34028f2b6fa)
- [The State of Python Packaging in 2026 - RepoForge](https://learn.repoforge.io/posts/the-state-of-python-packaging-in-2026/)

### Python Project Structure
- [src layout vs flat layout - Python Packaging User Guide](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
- [Python Package Structure & Layout - PyOpenSci](https://www.pyopensci.org/python-package-guide/package-structure-code/python-package-structure.html)
- [Package structure and distribution - Python Packages](https://py-pkgs.org/04-package-structure.html)

### Documentation Consolidation
- [How to structure technical documentation - GitBook](https://gitbook.com/docs/guides/docs-best-practices/documentation-structure-tips)
- [Multi-Product Documentation Strategy - Document360](https://document360.com/blog/multi-product-documentation-strategy/)
- [Centralized Documentation: Definition & Best Practices - Docsie](https://www.docsie.io/blog/glossary/centralized-documentation/)

### Economic Data Integration
- [fredapi - PyPI](https://pypi.org/project/fredapi/)
- [GitHub - mortada/fredapi](https://github.com/mortada/fredapi)
- [pyfredapi - GitHub](https://github.com/gw-moore/pyfredapi)
- [Federal Reserve Economic Data (FRED) Client - FRB](https://frb.readthedocs.io/)

---
*Architecture research for: ta_lab2 v0.5.0 Ecosystem Reorganization*
*Researched: 2026-02-02*
