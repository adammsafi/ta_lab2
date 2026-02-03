# Phase 15: Economic Data Strategy - Research

**Researched:** 2026-02-03
**Domain:** Economic data integration with FRED API
**Confidence:** HIGH

## Summary

Phase 15 evaluates two custom packages (fredtools2 and fedtools2) for integration into ta_lab2. Research reveals these are specialized, lightweight wrappers around the Federal Reserve Economic Data (FRED) API with distinct but complementary purposes. fredtools2 (167 lines) provides PostgreSQL-backed FRED data ingestion with a simple CLI for pulling series and release metadata. fedtools2 (659 lines) performs ETL consolidation of Federal Reserve policy target datasets (FEDFUNDS, DFEDTAR, DFEDTARL, DFEDTARU) into unified daily CSV outputs.

Both packages are custom-built for specific workflows and overlap minimally with mature ecosystem alternatives (fredapi, fedfred). The packages have clean structure, minimal dependencies (requests, pandas, psycopg2-binary, pyyaml), and no external users. They were indexed in Phase 11 memory preparation (6 fredtools2 files, unknown fedtools2 count).

**Primary recommendation:** Archive both packages to `.archive/economic_data/` with documentation. They are specialized, one-off tools with no current integration need in ta_lab2. If economic data becomes relevant, use ecosystem standard `fredapi` or modern `fedfred` packages instead of maintaining custom wrappers.

## Standard Stack

The established libraries/tools for FRED API integration:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fredapi | 0.5.2+ | FRED API client with pandas integration | Most established package (GitHub: mortada/fredapi), handles data revisions, ALFRED support, full FRED API coverage |
| requests | 2.32+ | HTTP client for direct API calls | Standard library for REST API integration, used by all FRED wrappers |
| pandas | 2.2+ | DataFrame manipulation for time series | Standard for financial/economic time series, native output format for FRED data |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| fedfred | 1.0+ | Modern FRED client with async/caching | Use for high-volume workflows: async support, built-in rate limiting (120 calls/min), pandas/polars/dask support |
| python-dotenv | 1.0+ | Environment variable management | Standard for API key management in .env files |
| psycopg2-binary | 2.9+ | PostgreSQL adapter | When persisting FRED data to PostgreSQL (fredtools2 use case) |
| pyyaml | 6.0+ | YAML configuration parsing | When using config-driven ETL pipelines (fedtools2 use case) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| fredapi | Direct REST API via requests | More control, but lose pandas integration, revision handling, search capabilities |
| Custom wrappers | FredBrain (AI-enhanced) | Adds OpenAI integration for analysis, but heavier dependency footprint |
| fedtools2 (custom ETL) | fredapi + manual consolidation | More flexible, but fedtools2 has domain-specific logic for Fed policy targets |

**Installation:**
```bash
# Ecosystem standard (recommended for new work)
pip install fredapi python-dotenv pandas

# Modern alternative with async support
pip install fedfred

# Custom packages (current state - in parent directory)
cd /c/Users/asafi/Downloads/fredtools2 && pip install -e .
cd /c/Users/asafi/Downloads/fedtools2 && pip install -e .
```

## Architecture Patterns

### Package Overview

**fredtools2** (Located: `/c/Users/asafi/Downloads/fredtools2`)
- **Purpose:** PostgreSQL-backed FRED data ingestion with CLI
- **Entry point:** `fred` command (3 jobs: init, releases, series)
- **Core functions:**
  - `pull_releases(conn, api_key, client)` - Fetch FRED release metadata
  - `pull_series(conn, api_key, client, series_list)` - Fetch series observations with incremental updates
  - `ensure_schema(conn)` - Initialize PostgreSQL schema (fred_series_values, fred_releases, pull_log tables)
  - `log_run(conn, job, rows_upserted, status, note)` - Audit logging
- **Dependencies:** requests, psycopg2-binary, python-dotenv
- **Total size:** 167 lines Python code (6 files)
- **Database schema:** 3 tables (fred_series_values, fred_releases, pull_log)

**fedtools2** (Located: `/c/Users/asafi/Downloads/fedtools2`)
- **Purpose:** ETL consolidation of Fed policy target series into unified daily dataset
- **Entry point:** `fedtools2` command (CLI with config, plotting, diagnostics)
- **Core functions:**
  - `build_dataset(cfg)` - Main ETL pipeline (load, merge, derive TARGET_MID/TARGET_SPREAD, add regime labels)
  - `combine_timeframes(dfs, names, persist, limit)` - Merge multiple time series with coverage tracking
  - `missing_ranges(mask)` - Gap analysis for data quality
  - `save_outputs(df, cfg)` - Write timestamped + latest CSV outputs
  - `_maybe_call_sql_sink(df, cfg, save_path)` - Optional PostgreSQL persistence via plugin
- **Dependencies:** pandas, numpy, pyyaml, matplotlib, sqlalchemy, python-dotenv
- **Total size:** 659 lines Python code (11 files)
- **Target datasets:** FEDFUNDS, DFEDTAR, DFEDTARL, DFEDTARU
- **Derived fields:** TARGET_MID (midpoint or single target), TARGET_SPREAD (upper - lower), regime labels

### Recommended Project Structure

**If integrating (NOT RECOMMENDED - see Don't Hand-Roll section):**
```
ta_lab2/
└── lib/                          # Monorepo shared libraries pattern
    ├── fredtools2/               # FRED API wrapper
    │   ├── pyproject.toml        # Own dependencies
    │   ├── src/fredtools2/
    │   │   ├── __init__.py
    │   │   ├── cli.py            # CLI entrypoint
    │   │   ├── config.py         # Env var parsing
    │   │   ├── db.py             # PostgreSQL helpers
    │   │   ├── fred_api.py       # REST API client
    │   │   └── jobs/
    │   │       ├── releases.py
    │   │       └── series.py
    │   └── tests/
    └── fedtools2/                # Fed funds ETL
        ├── pyproject.toml
        ├── src/fedtools2/
        │   ├── __init__.py
        │   ├── etl.py            # Main pipeline
        │   └── utils/
        │       ├── consolidation.py  # Time series merging
        │       └── io.py             # File I/O helpers
        └── tests/
```

**Recommended approach (archive with documentation):**
```
.archive/economic_data/2026-02-03/
├── fredtools2/                   # Full package preserved
│   ├── src/
│   ├── tests/
│   ├── pyproject.toml
│   └── README.md
├── fedtools2/                    # Full package preserved
│   ├── src/
│   ├── tests/
│   ├── pyproject.toml
│   └── README.md
├── manifest.json                 # Archive manifest with checksums
└── INTEGRATION_GUIDE.md          # How to use if needed later
```

### Pattern 1: Optional Dependency with Graceful Degradation

**What:** Allow economic data features without requiring FRED packages for all users
**When to use:** When feature is niche but valuable (e.g., macro regime detection using Fed data)

**Example:**
```python
# Source: Derived from ta_lab2 existing optional dependency pattern (orchestrator, astro)
# In ta_lab2/scripts/etl/fetch_fred_data.py

try:
    from fredapi import Fred
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False

def fetch_unemployment_rate():
    """Fetch UNRATE series from FRED (optional dependency)."""
    if not FRED_AVAILABLE:
        raise RuntimeError(
            "fredapi not installed. "
            "Install with: pip install ta_lab2[economic-data]"
        )

    import os
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise ValueError("FRED_API_KEY environment variable not set")

    fred = Fred(api_key=api_key)
    return fred.get_series("UNRATE")

# pyproject.toml configuration
[project.optional-dependencies]
economic-data = [
    "fredapi>=0.5.2",
]
```

### Pattern 2: Monorepo Path Dependencies (If integrating lib/)

**What:** Include local packages in monorepo without publishing to PyPI
**When to use:** When maintaining custom wrappers alongside main package

**Example:**
```toml
# Source: Python monorepo patterns 2026 (uv workspace, poetry path dependencies)
# In ta_lab2/pyproject.toml

[project.optional-dependencies]
economic-data = [
    "fredtools2 @ file:///${PROJECT_ROOT}/lib/fredtools2",
    "fedtools2 @ file:///${PROJECT_ROOT}/lib/fedtools2"
]

# Or with uv workspace (recommended 2026 pattern)
[tool.uv.workspace]
members = [
    "src/ta_lab2",
    "lib/fredtools2",
    "lib/fedtools2"
]

[tool.uv.sources]
fredtools2 = { workspace = true }
fedtools2 = { workspace = true }
```

### Anti-Patterns to Avoid

- **Custom FRED wrappers without ecosystem justification:** fredapi/fedfred already handle 99% of use cases. Custom wrappers add maintenance burden without value unless domain-specific logic is required (like fedtools2's policy target consolidation).

- **Mixing ETL concerns with API concerns:** fredtools2 (API client) and fedtools2 (ETL pipeline) are correctly separated. Don't merge them into single package unless they share >30% code.

- **Hardcoded paths in config:** fedtools2 has fallback path `C:\Users\asafi\Downloads\FinancialData\FedData` in etl.py line 63. This is acceptable as last-resort fallback but should be documented and overridable.

- **Database coupling in CLI tools:** fredtools2 tightly couples FRED API with PostgreSQL schema. Better pattern: separate fetcher from storage layer, support multiple backends (CSV, Parquet, PostgreSQL).

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| FRED API client | Custom requests wrapper (fredtools2 pattern) | fredapi or fedfred | Mature packages handle pagination, rate limiting, data revisions (ALFRED), error handling, all FRED endpoints (series, releases, categories, tags, sources) |
| FRED data caching | Manual file-based cache | fredapi with shelve backend, or fedfred with built-in cache | Ecosystem packages have cache invalidation, TTL management, concurrent access handling |
| Time series gap analysis | Custom missing_ranges() logic | pandas .isna() + .groupby() or specialized libs | fedtools2.utils.consolidation.missing_ranges() is 12 lines but reinvents pandas patterns |
| API rate limiting | Manual sleep/retry | tenacity, ratelimit, or fredfred's built-in limiter | Edge cases: burst limits, exponential backoff, concurrent requests |
| Economic data storage | Custom PostgreSQL schema | pandas .to_sql() with SQLAlchemy or time-series DBs (TimescaleDB, InfluxDB) | fredtools2's schema is simple but non-standard (no TimescaleDB hypertables, no partitioning) |

**Key insight:** FRED API integration is a solved problem. Custom wrappers only justified if (1) domain-specific consolidation logic (fedtools2's TARGET_MID calculation), or (2) organizational constraints (air-gapped environments, custom auth). For ta_lab2, neither applies—use ecosystem standards.

## Common Pitfalls

### Pitfall 1: Maintaining Custom Wrappers Without User Base

**What goes wrong:** fredtools2 and fedtools2 were built for specific workflows but have no active users. They become technical debt—code to maintain, test, document, and migrate during refactors.

**Why it happens:** Initial development solves immediate need without assessing long-term maintenance cost vs ecosystem alternatives.

**How to avoid:**
- Archive custom packages if no active users (Phase 15 recommendation)
- Use ecosystem standards (fredapi/fedfred) for future FRED integration
- Document archive decision: "Archived because [no users, ecosystem alternatives exist, maintenance burden]"

**Warning signs:**
- Package has no imports in main codebase (ta_lab2 doesn't import fredtools2/fedtools2)
- Last commit >3 months ago with no issues/PRs
- Dependencies pinned to outdated versions

### Pitfall 2: Split Packages with Unclear Boundaries

**What goes wrong:** fredtools2 (API client) and fedtools2 (ETL pipeline) serve related but distinct purposes. Confusion arises: "Which package do I use for FRED data?"

**Why it happens:** Incremental development without upfront design. fredtools2 built first for general FRED access, fedtools2 built later for Fed policy targets specifically.

**How to avoid:**
- Merge packages if >30% code overlap or shared dependencies
- Keep separate if distinct use cases and release cycles
- Document decision matrix (see Architecture Patterns section)

**Warning signs:**
- Users asking "what's the difference between X and Y?"
- Duplicate code (both have db connection helpers, config parsing)
- Circular dependencies or import confusion

### Pitfall 3: Environment-Specific Hardcoded Paths

**What goes wrong:** fedtools2/etl.py line 63 has fallback path `C:\Users\asafi\Downloads\FinancialData\FedData`. Works on developer machine, breaks elsewhere.

**Why it happens:** Convenience during development, path becomes "emergency fallback" that ships to production.

**How to avoid:**
- Environment variables for all paths (with clear error messages if unset)
- Config files with validation (YAML with required keys)
- Fail fast with helpful error: "Set FEDTOOLS2_FED_DATA_DIR or config.fed_data_dir"

**Warning signs:**
- Absolute paths in code (especially Windows paths like `C:\Users\...`)
- "Works on my machine" bugs
- Silent fallbacks that succeed unexpectedly

### Pitfall 4: Optional Dependencies Without Clear Value Proposition

**What goes wrong:** Adding `[economic-data]` extra to ta_lab2 without demonstrating use case. Users ask: "Should I install this? What do I get?"

**Why it happens:** Feature creep—"we might need economic data someday" without concrete requirements.

**How to avoid:**
- Only add optional dependencies when feature exists and documented
- Clear value proposition: "Install `[economic-data]` to enable macro regime detection using Fed funds rate"
- Graceful degradation: feature unavailable but main package still works

**Warning signs:**
- Optional dependency with no code using it
- Documentation says "for future use"
- No tests for optional feature paths

### Pitfall 5: Database Schema Migration Debt

**What goes wrong:** fredtools2/db.py line 13 runs `schema.sql` on every init. If schema changes, no migration strategy (ALTER TABLE vs recreate).

**Why it happens:** CLI tool mentality ("it's just a script") vs library mentality ("users depend on stability").

**How to avoid:**
- Use migration tools (Alembic, SQLAlchemy-Migrate) even for small projects
- Version schemas (CREATE TABLE IF NOT EXISTS only works for new installs)
- Document upgrade path in CHANGELOG

**Warning signs:**
- Schema defined in .sql file with no versioning
- `DROP TABLE IF EXISTS` in production scripts
- No rollback plan for schema changes

## Code Examples

Verified patterns from ecosystem and existing codebase:

### Using fredapi for Economic Data (Recommended Pattern)

```python
# Source: https://github.com/mortada/fredapi (fredapi ecosystem standard)
from fredapi import Fred
import os

# Initialize client with API key from environment
fred = Fred(api_key=os.getenv('FRED_API_KEY'))

# Fetch series as pandas Series
unemployment = fred.get_series('UNRATE')
fed_funds = fred.get_series('FEDFUNDS')

# Search for series
results = fred.search('unemployment rate')
# Returns DataFrame: series_id, title, observation_start, observation_end, frequency, units

# Get series metadata
info = fred.get_series_info('UNRATE')
# Returns dict: id, title, observation_start, observation_end, frequency, units, seasonal_adjustment

# ALFRED: Historical data revisions (what was known when)
vintage_data = fred.get_series_all_releases('UNRATE')
# Returns DataFrame with vintage_dates as columns
```

### Optional Dependency Pattern for ta_lab2

```python
# Source: Derived from ta_lab2/tools/ai_orchestrator/__init__.py (existing pattern)
# In ta_lab2/lib/economic_data.py (if integrating)

"""
Economic data utilities (optional dependency).

Install with: pip install ta_lab2[economic-data]
"""

try:
    from fredapi import Fred
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False


def require_fred():
    """Decorator to ensure FRED dependencies are installed."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            if not FRED_AVAILABLE:
                raise ImportError(
                    f"Function '{func.__name__}' requires economic-data dependencies. "
                    "Install with: pip install ta_lab2[economic-data]"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator


@require_fred()
def fetch_fed_funds_rate(start_date=None, end_date=None):
    """
    Fetch Federal Funds Rate from FRED.

    Args:
        start_date: Optional start date (YYYY-MM-DD or datetime)
        end_date: Optional end date (YYYY-MM-DD or datetime)

    Returns:
        pandas.Series with date index and FEDFUNDS values

    Raises:
        ImportError: If fredapi not installed
        ValueError: If FRED_API_KEY not set
    """
    import os

    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise ValueError(
            "FRED_API_KEY environment variable not set. "
            "Get key at: https://fred.stlouisfed.org/docs/api/api_key.html"
        )

    fred = Fred(api_key=api_key)
    series = fred.get_series("FEDFUNDS")

    # Filter by date range if provided
    if start_date:
        series = series[series.index >= start_date]
    if end_date:
        series = series[series.index <= end_date]

    return series
```

### pyproject.toml Configuration for Optional Economic Data

```toml
# Source: ta_lab2/pyproject.toml (existing optional-dependencies pattern)
[project.optional-dependencies]
# ... existing extras (dev, viz, astro, orchestrator, docs) ...

# Economic data integration (FRED API)
economic-data = [
  "fredapi>=0.5.2",
]

# Combined group for development + all optional features
all = [
  # ... existing all dependencies ...
  "fredapi>=0.5.2",
]
```

### Archive Manifest for Economic Data Packages

```json
// Source: .archive/data_tools/2026-02-03/manifest.json (Phase 14 pattern)
{
  "archive_date": "2026-02-03T12:00:00Z",
  "phase": "15-economic-data-strategy",
  "category": "economic_data",
  "decision": "archive",
  "rationale": "Specialized, single-purpose packages with no active users in ta_lab2. Ecosystem alternatives (fredapi, fedfred) provide superior functionality with active maintenance. Archive preserves packages for reference without maintenance burden.",
  "files": [
    {
      "original_path": "../fredtools2",
      "archive_path": ".archive/economic_data/2026-02-03/fredtools2",
      "package_name": "fredtools2",
      "version": "0.1.0",
      "description": "FRED API client with PostgreSQL persistence",
      "entry_point": "fred [init|releases|series]",
      "dependencies": ["requests>=2.32", "psycopg2-binary>=2.9", "python-dotenv>=1.0"],
      "file_count": 6,
      "total_lines": 167,
      "last_modified": "2024-12-11T08:57:00Z",
      "sha256_pyproject": "abcd1234...",
      "sha256_src": "efgh5678..."
    },
    {
      "original_path": "../fedtools2",
      "archive_path": ".archive/economic_data/2026-02-03/fedtools2",
      "package_name": "fedtools2",
      "version": "0.1.0",
      "description": "ETL consolidation of Federal Reserve policy target datasets",
      "entry_point": "fedtools2 [--config] [--plot] [--verbose-missing]",
      "dependencies": ["pandas>=2.2", "numpy>=1.26", "pyyaml>=6.0", "matplotlib>=3.8", "sqlalchemy>=2.0", "python-dotenv>=1.0"],
      "file_count": 11,
      "total_lines": 659,
      "last_modified": "2024-11-11T08:58:00Z",
      "sha256_pyproject": "ijkl9012...",
      "sha256_src": "mnop3456..."
    }
  ],
  "ecosystem_alternatives": [
    {
      "name": "fredapi",
      "version": "0.5.2+",
      "pypi": "https://pypi.org/project/fredapi/",
      "github": "https://github.com/mortada/fredapi",
      "replaces": ["fredtools2"],
      "advantages": ["Data revision handling (ALFRED)", "Full FRED API coverage", "Active maintenance", "Search capabilities", "Series metadata"]
    },
    {
      "name": "fedfred",
      "version": "1.0+",
      "pypi": "https://pypi.org/project/fedfred/",
      "github": "https://github.com/nikhilxsunder/fedfred",
      "replaces": ["fredtools2"],
      "advantages": ["Async support", "Built-in caching", "Rate limiting (120 calls/min)", "Pandas/Polars/Dask/GeoPandas support", "Modern 2025+ design"]
    }
  ],
  "restoration_notes": "To restore packages: (1) Copy from archive to project root or lib/; (2) pip install -e ./fredtools2 and ./fedtools2; (3) Set environment variables FRED_API_KEY, PG_HOST, PG_USER, PG_PASSWORD, PG_DATABASE; (4) For fedtools2, set FEDTOOLS2_FED_DATA_DIR or config fed_data_dir. See INTEGRATION_GUIDE.md for details."
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| requests + manual pagination | fredapi with automatic pagination | 2019+ (fredapi 0.4.0+) | Eliminates boilerplate, handles FRED API quirks (offset limits, file_type param) |
| Sync-only HTTP clients | fedfred with async support | 2025 (fedfred 1.0) | Non-blocking FRED queries for high-volume workflows, 5-10x faster for bulk fetches |
| Manual caching to disk | Built-in caching with TTL (fredfred) | 2025 (fedfred 1.0) | Automatic cache invalidation, no stale data bugs |
| CSV-only output | Native pandas/polars/dask DataFrames | 2020+ (fredapi 0.5.0+) | Direct integration with analysis pipelines, no intermediate files |
| Monolithic package managers | Monorepo workspaces (uv, poetry) | 2024-2026 (uv 0.5+, poetry 2.0) | Path dependencies with unified lock files, faster installs, atomic cross-package changes |
| setup.py + requirements.txt | pyproject.toml with optional-dependencies | 2022+ (PEP 621) | Single source of truth, declarative dependencies, standard format |

**Deprecated/outdated:**
- **Custom FRED API wrappers without ecosystem gap:** fredtools2 pattern (minimal wrapper around requests) superseded by fredapi/fedfred which handle edge cases, revisions, search, caching.
- **setup.py for package configuration:** Replaced by pyproject.toml (PEP 621 standard since Python 3.11+). fredtools2 still has setup.py but not required.
- **Workspace members without uv/poetry:** Manual path dependencies brittle. Use `[tool.uv.workspace]` or poetry plugin-monorepo for proper monorepo support.

## Open Questions

Things that couldn't be fully resolved:

1. **fedtools2 usage in ta_lab2 workflows**
   - What we know: fedtools2 produces unified Fed policy target dataset (TARGET_MID, TARGET_SPREAD, regime labels)
   - What's unclear: Are these derived fields used in ta_lab2 regime detection or calendar features? No imports found in codebase search.
   - Recommendation: Assume not used (no imports = no dependency). Archive package. If regime detection needs Fed data later, reconstruct logic from archived code or use fredapi.

2. **PostgreSQL schema migration strategy for fredtools2**
   - What we know: fredtools2/db.py runs schema.sql on init, creates 3 tables (fred_series_values, fred_releases, pull_log)
   - What's unclear: Does any ta_lab2 script query these tables? Are they populated and maintained?
   - Recommendation: Check database for table existence. If tables exist with data, document in archive manifest. If empty/non-existent, confirms no usage.

3. **FRED API key availability**
   - What we know: .fred.env file exists in parent directory (../Downloads/.fred.env per Phase 11 verification)
   - What's unclear: Is FRED_API_KEY actively used? Is it valid?
   - Recommendation: Not blocking for Phase 15 (archiving packages). If future integration needed, user can obtain new key from https://fred.stlouisfed.org/docs/api/api_key.html (free, instant approval).

4. **Memory system linkage to archived packages**
   - What we know: Phase 11 indexed fredtools2 (6 files) and fedtools2 (unknown count) with `source="pre_integration_v0.5.0"` tag
   - What's unclear: After archiving, should memory be updated with `archived=true` metadata or `moved_to` relationship?
   - Recommendation: Follow MEMO-13 pattern from Phase 14. Create memory update with `moved_to` relationship linking old path to archive path. Tag with `phase=15` and `action=archived`.

## Sources

### Primary (HIGH confidence)
- fredtools2 codebase inspection: `/c/Users/asafi/Downloads/fredtools2/` (6 Python files, 167 lines, pyproject.toml, structure documented in fredStructure&VM_Key.txt)
- fedtools2 codebase inspection: `/c/Users/asafi/Downloads/fedtools2/` (11 Python files, 659 lines, pyproject.toml, README.md)
- ta_lab2 pyproject.toml: Existing optional-dependencies pattern (orchestrator, astro, viz, docs, dev, all)
- Phase 11 verification report: Confirmed fredtools2/fedtools2 indexed in memory (6 fredtools2 files per manifest)
- Phase 14 verification report: Archive manifest pattern, memory update pattern (MEMO-13)

### Secondary (MEDIUM confidence)
- [fredapi PyPI](https://pypi.org/project/fredapi/) - Official package, version 0.5.2+, pandas integration
- [fredapi GitHub](https://github.com/mortada/fredapi) - Source code, ALFRED support, search capabilities
- [fedfred PyPI](https://pypi.org/project/fedfred/) - Modern alternative, async/caching, version 1.0+
- [FRED API Official Docs](https://fred.stlouisfed.org/docs/api/fred/) - API specification, endpoints, authentication
- [Python Packaging User Guide - pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) - Optional dependencies specification
- [PEP 621](https://peps.python.org/pep-0631/) - Dependency specification in pyproject.toml (standard since Python 3.11+)
- [Python Monorepo with UV (Medium 2025)](https://medium.com/@life-is-short-so-enjoy-it/python-monorepo-with-uv-f4ced6f1f425) - Workspace patterns, path dependencies
- [Tweag Python Monorepo (2023)](https://www.tweag.io/blog/2023-04-04-python-monorepo-1/) - Structure and tooling for lib/ directories

### Tertiary (LOW confidence)
- WebSearch results for "FRED API economic data integration Python best practices 2026" - General patterns, not package-specific
- WebSearch results for "optional dependencies pyproject.toml extras_require pattern 2026" - Syntax examples, community discussions

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - fredapi/fedfred are established ecosystem standards with active maintenance and clear documentation
- Architecture: HIGH - Direct codebase inspection of fredtools2/fedtools2, clear function inventory and dependency analysis
- Pitfalls: MEDIUM - Derived from codebase patterns (hardcoded paths, schema management) and general Python packaging experience, not FRED-specific incidents

**Research date:** 2026-02-03
**Valid until:** 2026-05-03 (90 days - stable domain, FRED API unchanged since 2010, Python packaging patterns mature)

**Package locations verified:**
- fredtools2: `/c/Users/asafi/Downloads/fredtools2/` (exists, 6 Python files)
- fedtools2: `/c/Users/asafi/Downloads/fedtools2/` (exists, 11 Python files)
- .fred.env: `/c/Users/asafi/Downloads/.fred.env` (exists per ls output)
- fredStructure&VM_Key.txt: `/c/Users/asafi/Downloads/fredStructure&VM_Key.txt` (exists, documents fredtools2 structure and VM deployment)
