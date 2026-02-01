# Phase 10: Release Validation - Research

**Researched:** 2026-02-01
**Domain:** Release validation pipelines, documentation generation, CI/CD automation
**Confidence:** HIGH

## Summary

Release validation for Python projects in 2026 follows a well-established pattern: CI-based validation gates using pytest with PostgreSQL service containers, automated release creation via GitHub Actions, and comprehensive documentation using either Sphinx or MkDocs Material. The key finding is that all three aspects—validation, documentation, and release automation—have mature, standardized tooling that works together seamlessly.

**For this project**: Use pytest with custom validation scripts as CI blockers, pytest-cov with dual JSON/markdown output for coverage, MkDocs Material + mkdocstrings for documentation (FastAPI already provides Swagger), and softprops/action-gh-release for automated GitHub releases. All three validations (time alignment, data consistency, backtest reproducibility) can run against PostgreSQL service containers in GitHub Actions with identical patterns used in integration tests.

**Primary recommendation:** Implement validation gates as pytest tests with `--maxfail=1` (fail fast on critical errors), use pytest-json-report for machine-readable validation output, generate markdown reports for human consumption, enforce coverage threshold with `--cov-fail-under=70`, and automate release creation on tag push using GitHub Actions with documentation bundle as release assets.

## Standard Stack

The established libraries/tools for release validation in Python projects:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 8.x | Test framework and validation runner | Universal Python testing framework, extensible plugin ecosystem |
| pytest-cov | 7.0+ | Coverage measurement with multiple report formats | Official coverage plugin, supports JSON/markdown/XML output natively |
| pytest-json-report | 1.5+ | Machine-readable test results | Structured output for CI processing, customizable via hooks |
| coverage.py | 7.13+ | Underlying coverage engine | Industry standard, used by pytest-cov, latest release Jan 2026 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-benchmark | 5.2+ | Performance regression testing | When performance validation is required |
| pytest-xdist | 3.x+ | Parallel test execution | For large test suites needing speed optimization |
| pytest-rerunfailures | 13.x+ | Flaky test handling | For non-deterministic tests in CI |
| pytest-md | 0.4+ | Markdown test reports | Alternative to pytest-json-report for simpler markdown output |

### Documentation
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| MkDocs Material | 9.x+ | Modern documentation site generator | Preferred for new projects, Markdown-based, beautiful theme |
| mkdocstrings-python | 1.x+ | API docs from docstrings | With MkDocs, supports Google/NumPy/Sphinx docstring styles |
| Sphinx | 7.x+ | Traditional documentation generator | Legacy projects, complex projects like NumPy/Django |
| FastAPI | Built-in | Automatic OpenAPI/Swagger UI | REST APIs (already have this—no additional tool needed) |

### Release Automation
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| softprops/action-gh-release | v2+ | GitHub release creation with assets | Standard for GitHub releases with file uploads |
| python-semantic-release | 10.5+ | Automated versioning from commits | When using Conventional Commits workflow |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| MkDocs Material | Sphinx autodoc | Sphinx: More powerful but steeper learning curve, reStructuredText vs Markdown |
| pytest-json-report | pytest-cov alone | pytest-cov only covers coverage, not full test results/metadata |
| softprops/action-gh-release | actions/create-release | Official action deprecated, softprops is community-maintained successor |
| Manual CHANGELOG | python-semantic-release | Automated: Requires Conventional Commits discipline, loses human curation |

**Installation:**
```bash
# Core validation
pip install pytest pytest-cov pytest-json-report pytest-benchmark

# Documentation
pip install mkdocs-material "mkdocstrings[python]"

# No additional install for GitHub Actions (YAML-based)
```

## Architecture Patterns

### Recommended Project Structure
```
.
├── .github/
│   └── workflows/
│       ├── validation.yml       # CI validation gates
│       └── release.yml          # Automated release on tag
├── docs/
│   ├── index.md                 # README content (tiered structure)
│   ├── design.md                # DESIGN.md - high-level concepts
│   ├── architecture.md          # ARCHITECTURE.md - implementation details
│   ├── deployment.md            # Deployment guide
│   └── api/                     # Auto-generated API reference
├── scripts/
│   └── validation/
│       ├── validate_time_alignment.py
│       ├── validate_data_consistency.py
│       └── validate_backtest_reproducibility.py
├── tests/
│   └── validation/              # Pytest wrappers for validation scripts
│       ├── test_time_alignment.py
│       ├── test_data_consistency.py
│       └── test_backtest_reproducibility.py
├── mkdocs.yml                   # MkDocs configuration
├── pyproject.toml               # Coverage config, pytest config
└── CHANGELOG.md                 # Keep a Changelog format
```

### Pattern 1: CI Validation Gates with PostgreSQL Service Container
**What:** Run validation tests against real PostgreSQL database in GitHub Actions using service containers
**When to use:** When validations require real database (as per CONTEXT.md decision)
**Example:**
```yaml
# Source: https://docs.github.com/en/actions/using-containerized-services/creating-postgresql-service-containers
name: Validation Gates

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: testdb
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest pytest-cov pytest-json-report

      - name: Run validation gates (fail-fast)
        env:
          TARGET_DB_URL: postgresql://postgres:postgres@localhost:5432/testdb
        run: |
          pytest tests/validation/ \
            --maxfail=1 \
            --cov=src \
            --cov-report=json:coverage.json \
            --cov-report=markdown:coverage.md \
            --cov-fail-under=70 \
            --json-report \
            --json-report-file=validation-report.json

      - name: Upload validation reports
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: validation-reports
          path: |
            coverage.json
            coverage.md
            validation-report.json
```

### Pattern 2: Dual-Output Validation Reports (JSON + Markdown)
**What:** Generate both machine-readable (JSON) and human-readable (Markdown) validation reports
**When to use:** When you need both automated processing and human review (as per CONTEXT.md decision)
**Example:**
```python
# Source: https://pytest-cov.readthedocs.io/en/latest/reporting.html
# pytest.ini or pyproject.toml
[tool.pytest.ini_options]
addopts = [
    "--cov=src",
    "--cov-report=json:reports/coverage.json",
    "--cov-report=markdown:reports/coverage.md",
    "--json-report",
    "--json-report-file=reports/validation.json",
    "--json-report-indent=2"
]
```

```python
# Custom validation script with dual output
# Source: Based on pytest-json-report customization patterns
import json
import pytest
from pathlib import Path

def pytest_json_modifyreport(json_report):
    """Add custom validation metadata to JSON report"""
    json_report['validation_type'] = 'time_alignment'
    json_report['critical_threshold'] = True

def generate_markdown_summary(json_report_path: Path, output_path: Path):
    """Generate human-readable markdown from JSON report"""
    with open(json_report_path) as f:
        data = json.load(f)

    markdown = f"""# Validation Report: {data.get('validation_type', 'Unknown')}

**Status:** {'PASS' if data['summary']['passed'] == data['summary']['total'] else 'FAIL'}
**Total Tests:** {data['summary']['total']}
**Passed:** {data['summary']['passed']}
**Failed:** {data['summary']['failed']}

## Details
"""
    for test in data.get('tests', []):
        status = '✅' if test['outcome'] == 'passed' else '❌'
        markdown += f"\n- {status} {test['nodeid']}"

    output_path.write_text(markdown)
```

### Pattern 3: MkDocs Material with Tiered Documentation
**What:** Multi-level documentation structure with quick start at top, detailed sections collapsible
**When to use:** For comprehensive project documentation (as per CONTEXT.md requirement)
**Example:**
```yaml
# Source: https://squidfunk.github.io/mkdocs-material/ + https://mkdocstrings.github.io/python/
# mkdocs.yml
site_name: ta_lab2 v0.4.0
site_description: Technical Analysis Laboratory - Time Series Analysis Framework

theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.expand
    - navigation.top
    - content.code.copy
  palette:
    - scheme: default
      primary: indigo
      accent: indigo

nav:
  - Home: index.md
  - Quick Start: index.md#quick-start
  - Design: design.md
  - Architecture: architecture.md
  - Deployment: deployment.md
  - API Reference:
    - Orchestrator: api/orchestrator.md
    - Memory: api/memory.md
    - TA Lab2: api/ta_lab2.md
  - Release Notes: CHANGELOG.md

plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          options:
            docstring_style: google
            show_source: true
            show_root_heading: true
            show_symbol_type_heading: true
            members_order: source

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.tabbed:
      alternate_style: true
  - toc:
      permalink: true
```

```markdown
<!-- docs/index.md - Tiered README structure -->
# ta_lab2 v0.4.0

Quick overview paragraph.

## Quick Start

```bash
# Installation
pip install -e .

# Basic usage
python -m ta_lab2.orchestrator
```

## Components

<details>
<summary>Memory System (click to expand)</summary>

Detailed information about memory system...
- Architecture
- Usage examples
- Configuration

</details>

<details>
<summary>Orchestrator (click to expand)</summary>

Detailed orchestrator documentation...

</details>

<details>
<summary>TA Lab2 Signals (click to expand)</summary>

Signal calculation details...

</details>
```

### Pattern 4: Automated Release with Documentation Bundle
**What:** Automatically create GitHub release with compiled documentation as assets on tag push
**When to use:** For automated release workflow (as per CONTEXT.md decision)
**Example:**
```yaml
# Source: https://github.com/softprops/action-gh-release
name: Release

on:
  push:
    tags:
      - 'v*.*.*'

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install documentation dependencies
        run: |
          pip install mkdocs-material "mkdocstrings[python]"

      - name: Build documentation bundle
        run: |
          mkdocs build
          cd site && zip -r ../docs-bundle.zip . && cd ..

      - name: Extract release notes
        id: notes
        run: |
          # Extract section for this version from CHANGELOG.md
          VERSION=${GITHUB_REF#refs/tags/v}
          sed -n "/## \[${VERSION}\]/,/## \[/p" CHANGELOG.md | sed '$d' > release-notes.md

      - name: Create Release
        uses: softprops/action-gh-release@v2
        with:
          body_path: release-notes.md
          files: |
            docs-bundle.zip
          fail_on_unmatched_files: true
          generate_release_notes: false
          draft: false
          prerelease: false
```

### Pattern 5: FastAPI OpenAPI Documentation (Already Built-in)
**What:** Use FastAPI's automatic OpenAPI/Swagger UI generation for REST APIs
**When to use:** For interactive API documentation (as per CONTEXT.md requirement)
**Example:**
```python
# Source: https://fastapi.tiangolo.com/tutorial/metadata/
from fastapi import FastAPI

description = """
ta_lab2 API provides programmatic access to orchestrator and signal calculations.

## Orchestrator
* **Run workflows** - Execute end-to-end signal calculation pipelines
* **Query status** - Check workflow execution status

## Signals
* **Calculate EMA** - Exponential Moving Averages with multi-timeframe support
* **Retrieve results** - Query calculated signal values
"""

app = FastAPI(
    title="ta_lab2 API",
    description=description,
    summary="Technical Analysis Laboratory API",
    version="0.4.0",
    contact={
        "name": "ta_lab2 Team",
    },
    license_info={
        "name": "MIT",
    },
    docs_url="/api/docs",      # Swagger UI at /api/docs
    redoc_url="/api/redoc",    # ReDoc at /api/redoc
    openapi_url="/api/openapi.json"
)

# FastAPI automatically generates:
# - /api/docs (Swagger UI - interactive, try-it-out functionality)
# - /api/redoc (ReDoc - clean read-only documentation)
# - /api/openapi.json (OpenAPI schema for tools/integrations)
```

### Anti-Patterns to Avoid

- **Don't mock database in validation tests**: CONTEXT.md explicitly requires real database for validations. Mocking defeats the purpose of data consistency validation.
- **Don't use git log as CHANGELOG**: Raw commit messages are noise-filled and user-hostile. Curate releases manually or use Conventional Commits with tooling.
- **Don't fail entire test suite on single validation**: Use `--maxfail=1` to fail fast but report which specific validation failed.
- **Don't embed coverage reports in git**: Coverage reports are artifacts, not source. Generate in CI, upload as artifacts, don't commit.
- **Don't duplicate API docs**: FastAPI already provides OpenAPI/Swagger. Don't manually write what's auto-generated.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Coverage reporting | Custom coverage tracker | pytest-cov with coverage.py | Handles edge cases (multiprocessing, subprocess, .coveragerc config), mature ecosystem |
| Test result JSON | Custom pytest plugin | pytest-json-report | Handles fixtures, parametrization, metadata, customization hooks |
| GitHub releases | Manual gh CLI scripts | softprops/action-gh-release | Handles glob patterns, cross-platform paths, retries, idempotency |
| API documentation | Manual OpenAPI writing | FastAPI built-in | Auto-syncs with code, interactive UI, validates requests/responses |
| Documentation site | Custom static site generator | MkDocs Material | Themes, search, navigation, mobile support, versioning |
| Changelog generation | Parsing git log manually | Keep a Changelog format OR python-semantic-release | Keep a Changelog: human-curated quality; PSR: automated consistency |
| PostgreSQL test setup | Manual docker-compose | GitHub Actions service containers | Built-in health checks, automatic teardown, port mapping, network isolation |
| Markdown from docstrings | String parsing | mkdocstrings-python with Griffe | AST parsing, cross-references, type annotations, multiple docstring styles |

**Key insight:** Release validation has mature tooling because it's a solved problem. Every Python project needs it, so the tools are battle-tested. Custom solutions miss edge cases that took years to discover.

## Common Pitfalls

### Pitfall 1: Coverage Threshold Too High on First Release
**What goes wrong:** Setting `--cov-fail-under=90` on initial release when current coverage is 60% blocks all CI
**Why it happens:** Aspirational thinking—"we should have 90% coverage"—conflicts with current reality
**How to avoid:** Start with current coverage level (e.g., 70%), increment by 5% each release until target reached
**Warning signs:** CI failing with "coverage 72% below threshold 90%" when no code changed

### Pitfall 2: Validation Tests Don't Use Same Database Config as Production
**What goes wrong:** Validation passes in CI but fails in production due to different PostgreSQL version, extensions, or configuration
**Why it happens:** CI uses `postgres:latest`, production uses `postgres:14` with specific extensions
**How to avoid:** Pin PostgreSQL version in CI service container to match production (e.g., `postgres:16`), document required extensions
**Warning signs:** "Function not found" or "Type not found" errors in production that don't occur in CI

### Pitfall 3: GitHub Actions Token Permissions Insufficient
**What goes wrong:** Release workflow fails with "Resource not accessible by integration" when creating release
**Why it happens:** Default `GITHUB_TOKEN` has read-only permissions; release creation needs `contents: write`
**How to avoid:** Add `permissions: contents: write` to job or workflow level in release.yml
**Warning signs:** GitHub Actions log shows 403 Forbidden when calling GitHub API

### Pitfall 4: pytest-benchmark Breaks CI on Performance Regression
**What goes wrong:** CI fails because performance regressed 5% but failure is unintended—no baseline established
**Why it happens:** Using `--benchmark-compare-fail=min:5%` without saving baseline first
**How to avoid:** Save baseline with `--benchmark-save=baseline` on main branch, then compare in PRs. For v0.4.0, defer benchmarks or use smoke test without fail threshold.
**Warning signs:** `BenchmarkComparisonError: No previous benchmark to compare against`

### Pitfall 5: Markdown Report Overwrites Instead of Appends
**What goes wrong:** Multiple test runs (time alignment, data consistency, backtest) each overwrite previous markdown report
**Why it happens:** Using `--cov-report=markdown:report.md` instead of `--cov-report=markdown-append:report.md`
**How to avoid:** Use separate files per validation type OR use append mode with clear section headers
**Warning signs:** Final report only shows last validation, missing earlier results

### Pitfall 6: FastAPI Docs Exposed in Production
**What goes wrong:** `/docs` and `/redoc` endpoints are publicly accessible in production environment
**Why it happens:** FastAPI enables docs by default; no environment-based disabling
**How to avoid:** Set `docs_url=None, redoc_url=None` when `ENV != 'development'`
**Warning signs:** Security scan reports "API documentation endpoint exposed"

### Pitfall 7: CHANGELOG.md Out of Sync with Releases
**What goes wrong:** GitHub release created but CHANGELOG.md not updated, or vice versa
**Why it happens:** Manual process has no enforcement mechanism
**How to avoid:** Either (1) generate release notes FROM CHANGELOG.md in release workflow, or (2) use python-semantic-release to keep both in sync
**Warning signs:** Release v0.4.0 exists but CHANGELOG.md still shows v0.3.0 as latest

### Pitfall 8: Validation Scripts Not Importable by Pytest
**What goes wrong:** Validation scripts in `scripts/validation/` can't be imported by pytest tests
**Why it happens:** Scripts written as standalone executables, not modules; missing `__init__.py`
**How to avoid:** Make validation logic importable (class/function), create thin CLI wrapper, import in pytest test
**Warning signs:** `ModuleNotFoundError` when pytest tries to import validation logic

## Code Examples

Verified patterns from official sources:

### Coverage with Fail-Under Threshold
```python
# Source: https://pytest-cov.readthedocs.io/en/latest/config.html
# pyproject.toml
[tool.pytest.ini_options]
addopts = [
    "--cov=src/ta_lab2",
    "--cov-report=term-missing",
    "--cov-report=json:reports/coverage.json",
    "--cov-report=markdown:reports/coverage.md",
    "--cov-fail-under=70",
]

[tool.coverage.run]
source = ["src"]
omit = [
    "*/tests/*",
    "*/migrations/*",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
```

### PostgreSQL Service Container with Health Checks
```yaml
# Source: https://docs.github.com/en/actions/using-containerized-services/creating-postgresql-service-containers
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: ta_lab2_test
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
    ports:
      - 5432:5432

# In test steps:
env:
  TARGET_DB_URL: postgresql://postgres:postgres@localhost:5432/ta_lab2_test
```

### pytest-json-report with Custom Metadata
```python
# Source: https://github.com/numirias/pytest-json-report
# conftest.py
def pytest_json_modifyreport(json_report):
    """Add custom validation context to JSON report"""
    json_report['validation_suite'] = 'release_validation'
    json_report['phase'] = 'v0.4.0'
    json_report['database_backend'] = 'postgresql'

def pytest_json_runtest_metadata(item, call):
    """Add per-test metadata"""
    if call.when == 'call':
        return {
            'validation_type': item.get_closest_marker('validation_type').args[0] if item.get_closest_marker('validation_type') else None,
            'critical': item.get_closest_marker('critical') is not None,
        }

# tests/validation/test_time_alignment.py
import pytest

@pytest.mark.validation_type("time_alignment")
@pytest.mark.critical
def test_time_alignment_all_calculations_use_dim_timeframe(db_session):
    """Validate all calculations use correct timeframe from dim_timeframe"""
    # ... validation logic ...
    assert all_calculations_aligned, "Time alignment validation failed"
```

### Keep a Changelog Format
```markdown
<!-- Source: https://keepachangelog.com/en/1.1.0/ -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-02-XX

### Added
- Time alignment validation ensuring all calculations use dim_timeframe
- Data consistency validation for gap detection and rowcount verification
- Backtest reproducibility validation for deterministic results
- Comprehensive documentation suite (README, DESIGN, ARCHITECTURE, API, deployment)
- Automated release workflow with documentation bundle

### Changed
- Updated observability module with workflow state tracking
- Enhanced E2E integration tests covering orchestrator → memory → ta_lab2

### Fixed
- Fixed EMA calculation edge case in multi-timeframe scenarios

## [0.3.0] - 2026-01-15

...
```

### MkDocs Material with mkdocstrings Auto-API Docs
```markdown
<!-- Source: https://mkdocstrings.github.io/python/ -->
<!-- docs/api/orchestrator.md -->
# Orchestrator API Reference

The orchestrator module coordinates workflow execution across memory and signal calculation systems.

## WorkflowOrchestrator

::: ta_lab2.orchestrator.WorkflowOrchestrator
    options:
      show_source: true
      members:
        - execute
        - validate_workflow
        - get_status

## Workflow Models

::: ta_lab2.orchestrator.models.Workflow
::: ta_lab2.orchestrator.models.WorkflowStatus
```

### Automated Release with softprops/action-gh-release
```yaml
# Source: https://github.com/softprops/action-gh-release
name: Release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build documentation
        run: |
          pip install mkdocs-material "mkdocstrings[python]"
          mkdocs build
          cd site && zip -r ../ta_lab2-docs-${{ github.ref_name }}.zip . && cd ..

      - name: Create Release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            ta_lab2-docs-${{ github.ref_name }}.zip
          body: |
            ## ta_lab2 ${{ github.ref_name }}

            See [CHANGELOG.md](https://github.com/${{ github.repository }}/blob/main/CHANGELOG.md) for full release notes.

            **Documentation**: Download `ta_lab2-docs-*.zip` and open `index.html`
          draft: false
          prerelease: false
          fail_on_unmatched_files: true
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| actions/create-release + actions/upload-release-asset | softprops/action-gh-release | 2021-2022 | Single action handles both release creation and asset uploads, simpler workflow |
| Sphinx with manual setup | MkDocs Material + mkdocstrings | 2020-2023 | Lower barrier to entry, Markdown instead of reStructuredText, modern UI out of box |
| coverage.py CLI | pytest-cov plugin | Established 2015+ | Integrated pytest execution and coverage in single command, better CI integration |
| Manual CHANGELOG writing | Keep a Changelog OR python-semantic-release | Formalized 2017+ | Keep a Changelog: standardized format; PSR: automated from commits |
| unittest | pytest | Established 2010+ | Better fixtures, parametrization, plugin ecosystem, industry standard |
| Docker Compose for CI databases | GitHub Actions service containers | 2019-2020 | Built-in health checks, automatic cleanup, no manual docker-compose needed |

**Deprecated/outdated:**
- **actions/create-release**: Deprecated by GitHub in favor of community-maintained softprops/action-gh-release
- **travis-ci.org**: Shut down 2021, migrated to GitHub Actions or GitLab CI
- **nose/nose2**: End of life, pytest is successor
- **setup.py test**: Deprecated in favor of pytest direct invocation
- **Python 2 coverage.py 4.x**: Python 2 EOL 2020, coverage.py 7.x requires Python 3.8+

## Open Questions

Things that couldn't be fully resolved:

1. **Performance Benchmark Baseline Establishment**
   - What we know: pytest-benchmark can fail on regression with `--benchmark-compare-fail`, requires saved baseline
   - What's unclear: Should v0.4.0 establish first baseline (smoke test) or defer benchmarks entirely given CONTEXT.md marks this as Claude's discretion
   - Recommendation: Defer comprehensive benchmarks to post-v0.4.0. If smoke test desired, add `--benchmark-autosave --benchmark-disable-gc` without fail threshold.

2. **Coverage Threshold: 70% vs 85%**
   - What we know: Industry standard varies (70% minimum, 80-85% recommended, 90%+ aspirational)
   - What's unclear: Current project coverage unknown without running pytest-cov
   - Recommendation: Start with 70% (common minimum), increment by 5% each release. Check current coverage first: `pytest --cov=src --cov-report=term`

3. **Validation Strictness: Zero Tolerance vs Thresholds**
   - What we know: CONTEXT.md says validations are "CI blockers" but doesn't define tolerance for warnings vs errors
   - What's unclear: Should data consistency allow N missing rows if <0.1%, or must be exactly zero?
   - Recommendation: Zero tolerance for v0.4.0 (strict quality gate), can relax in future if legitimate edge cases found

4. **CHANGELOG Format: Manual vs Automated**
   - What we know: Keep a Changelog provides human-curated quality; python-semantic-release provides automation from Conventional Commits
   - What's unclear: Current commit message discipline unknown—are commits following Conventional Commits?
   - Recommendation: Use Keep a Changelog for v0.4.0 (manual curation ensures quality). Consider python-semantic-release post-v0.4.0 if team adopts Conventional Commits.

5. **Documentation Deployment: GitHub Pages vs Release Assets**
   - What we know: CONTEXT.md says "documentation attached as release assets (PDF/HTML bundle)"
   - What's unclear: Should docs also be deployed to GitHub Pages for live browsing, or only as downloadable bundle?
   - Recommendation: Start with release assets only (per CONTEXT.md). GitHub Pages optional enhancement if users request live docs.

## Sources

### Primary (HIGH confidence)
- [pytest-cov 7.0.0 documentation - Reporting](https://pytest-cov.readthedocs.io/en/latest/reporting.html) - Coverage report formats (JSON, markdown, XML, etc.)
- [pytest documentation - CI Pipelines](https://docs.pytest.org/en/stable/explanation/ci.html) - Official pytest CI guidance
- [FastAPI - Metadata and Docs URLs](https://fastapi.tiangolo.com/tutorial/metadata/) - OpenAPI/Swagger automatic documentation
- [GitHub Docs - Creating PostgreSQL service containers](https://docs.github.com/en/actions/using-containerized-services/creating-postgresql-service-containers) - Official GitHub Actions pattern
- [softprops/action-gh-release](https://github.com/softprops/action-gh-release) - GitHub release automation with assets
- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) - Changelog format specification
- [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) - Commit message convention for automation
- [pytest-json-report](https://github.com/numirias/pytest-json-report) - JSON test reporting plugin
- [pytest-benchmark usage](https://pytest-benchmark.readthedocs.io/en/latest/usage.html) - Performance regression testing
- [mkdocstrings-python overview](https://mkdocstrings.github.io/python/) - Python API documentation generation
- [python-semantic-release GitHub Actions](https://python-semantic-release.readthedocs.io/en/latest/configuration/automatic-releases/github-actions.html) - Automated release workflow

### Secondary (MEDIUM confidence)
- [pytest How to handle test failures](https://docs.pytest.org/en/7.1.x/how-to/failures.html) - --exitfirst and --maxfail flags
- [Python Packaging User Guide - Publishing with GitHub Actions](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/) - Official Python packaging guidance
- [Sphinx autodoc documentation](https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html) - Alternative documentation tool
- [Python Packaging User Guide - Versioning](https://packaging.python.org/en/latest/discussions/versioning/) - Python semantic versioning best practices
- [PostgreSQL Documentation - Data Consistency Checks](https://www.postgresql.org/docs/current/applevel-consistency.html) - Application-level consistency validation

### Tertiary (LOW confidence - WebSearch only)
- [Integrating Pytest into a CI/CD Pipeline](https://intellinotebook.com/programming/test-automation/integrating-pytest-into-a-ci-cd-pipeline/) - CI/CD patterns
- [Quality Gates: Automated Quality Enforcement in CI/CD](https://testkube.io/glossary/quality-gates) - Quality gate concepts
- [13 Proven Ways To Improve Test Runtime With Pytest](https://pytest-with-eric.com/pytest-advanced/pytest-improve-runtime/) - CI optimization strategies
- [AAAI-26 Reproducibility Checklist](https://aaai.org/conference/aaai/aaai-26/reproducibility-checklist/) - Reproducibility standards
- [Common Changelog](https://common-changelog.org/) - Alternative changelog format

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All tools verified with official documentation, versions confirmed as of Jan 2026
- Architecture patterns: HIGH - Patterns sourced from official docs (GitHub, pytest-cov, FastAPI, mkdocstrings)
- Pitfalls: MEDIUM - Based on community experience (GitHub issues, blog posts) and official documentation warnings
- Code examples: HIGH - All examples sourced from official documentation with URLs provided
- Open questions: MEDIUM - Gaps exist due to CONTEXT.md leaving items to "Claude's discretion" without project-specific data

**Research date:** 2026-02-01
**Valid until:** 2026-03-01 (30 days - tools are mature/stable, but check for pytest/coverage.py minor updates)
