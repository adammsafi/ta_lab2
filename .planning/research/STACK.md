# Stack Research: EMA & Bar Architecture Standardization

**Domain:** Code review, validation testing, and standardization for data pipeline architecture
**Researched:** 2026-02-05
**Confidence:** HIGH

## Executive Summary

This milestone requires comprehensive review and standardization of existing bar builders and EMA calculators. The focus is on **analysis and validation tools** rather than new feature libraries. The existing stack (PostgreSQL, Python, psycopg2, SQLAlchemy, pandas, pytest) remains the foundation. Stack additions target three capabilities:

1. **Code Analysis**: Detect inconsistencies across 6 similar EMA variants
2. **Validation Testing**: Verify data flow correctness and schema contracts
3. **Schema Comparison**: Ensure structural consistency across similar tables

## Recommended Stack Additions

### Core Analysis Tools

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| ast (stdlib) | Python 3.11+ | Programmatic AST analysis | Built-in, stable, enables custom pattern detection across similar scripts |
| radon | 6.0.1 | Code complexity metrics | Industry standard for cyclomatic complexity; identifies refactoring candidates |
| hypothesis | 6.151.4+ | Property-based testing | Already in requirements.txt; ideal for validating OHLC invariants across different data sources |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pycode-similar | 1.0.3 | AST-based code similarity | Compare 6 EMA variants to detect structural inconsistencies |
| pytest-cov | 6.0+ | Coverage reporting | Verify validation test completeness across bar/EMA scripts |
| SQLAlchemy Inspector | 2.0.44 (existing) | Schema reflection | Programmatically compare table structures (already available) |
| pdoc | 15.0+ | API documentation generation | Generate reference docs for standardized patterns post-standardization |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| ruff | Linting + formatting | Already in requirements.txt (0.14.3); use for consistency enforcement |
| mypy | Type checking | Already in requirements.txt (1.18.2); enforce type contracts during standardization |
| pytest-benchmark | Performance comparison | Already in requirements.txt; compare bar builder performance before/after |

## Installation

```bash
# New additions only (existing tools already in requirements-311.txt)
pip install radon==6.0.1
pip install pycode-similar==1.0.3
pip install pytest-cov>=6.0
pip install pdoc==15.0.0

# Verify existing tools are current
pip install --upgrade pytest>=9.0
pip install --upgrade hypothesis>=6.151.4
pip install --upgrade ruff>=0.15.0
```

## Stack Integration with Existing Architecture

### PostgreSQL Schema Analysis

**Use:** SQLAlchemy Inspector (already available in requirements.txt)
```python
from sqlalchemy import create_engine, inspect

engine = create_engine(DATABASE_URL)
inspector = inspect(engine)

# Compare table schemas programmatically
for table in ['cmc_ema_multi_tf', 'cmc_ema_multi_tf_v2', ...]:
    columns = inspector.get_columns(table)
    indexes = inspector.get_indexes(table)
    pk = inspector.get_pk_constraint(table)
```

**Why not external tools:** pgdiff, pgquarrel require separate installation and produce SQL diffs. For analysis purposes, SQLAlchemy Inspector provides programmatic access to schema metadata already in Python.

### Code Similarity Detection

**Use:** pycode-similar for structural comparison
```python
from pycode_similar import detect

# Compare EMA refresher implementations
results = detect(['refresh_cmc_ema_multi_tf_from_bars.py',
                  'refresh_cmc_ema_multi_tf_cal_from_bars.py',
                  'refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py'])
```

**Why pycode-similar:** AST-based (not text-based), normalizes variable names, integrates with Python workflows. Alternative (CoSi) focuses on plagiarism detection rather than refactoring analysis.

### Complexity Analysis

**Use:** radon for cyclomatic complexity
```bash
# Identify refactoring candidates
radon cc src/ta_lab2/scripts/bars/ -a -s
radon cc src/ta_lab2/scripts/emas/ -a -s

# Generate maintainability index
radon mi src/ta_lab2/scripts/bars/ -s
```

**Why radon:** Industry standard, fast, supports multiple metrics (CC, MI, Halstead). Extracts from AST, no dependencies on code execution.

### Property-Based Testing

**Use:** hypothesis (already in requirements.txt)
```python
from hypothesis import given
from hypothesis.strategies import floats, integers

@given(open=floats(min_value=0.01), high=floats(min_value=0.01),
       low=floats(min_value=0.01), close=floats(min_value=0.01))
def test_ohlc_invariants(open, high, low, close):
    # Verify: low <= open/close <= high
    # Test bar builder validation logic with generated data
```

**Why hypothesis:** Already validated in this project (6.142.5 in requirements.txt). Generates edge cases automatically; ideal for testing OHLC invariants across different bar table sources.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| SQLAlchemy Inspector | pgdiff, pgquarrel | When generating migration scripts (not needed for analysis) |
| pycode-similar | CoSi, MOSS | CoSi: Jupyter notebook analysis; MOSS: academic plagiarism detection (external service) |
| radon | pylint (complexity only) | pylint when you need full linting (radon focuses on metrics) |
| pdoc | Sphinx + autodoc | Sphinx when building comprehensive documentation sites (overkill for internal API reference) |
| pytest-cov | coverage.py direct | coverage.py for advanced use cases; pytest-cov for standard pytest integration |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Black | Replaced by ruff formatter (faster, already in stack) | ruff format |
| Flake8 | Replaced by ruff linter (10-100x faster) | ruff check |
| isort | Replaced by ruff import sorting | ruff check --select I |
| Pylint (for complexity) | Slower than radon for metrics-only use case | radon for metrics; ruff for linting |
| External schema migration tools (Liquibase, Alembic) | Not modifying schemas in this milestone; analysis only | SQLAlchemy Inspector |

## Stack Patterns by Use Case

**For detecting EMA variant inconsistencies:**
1. Use `pycode-similar` to compute structural similarity scores
2. Use `ast` module to extract specific patterns (state management, data source selection)
3. Use `radon` to identify complexity outliers

**For validating bar builder correctness:**
1. Use `hypothesis` to generate test cases for OHLC invariants
2. Use `pytest-cov` to verify test coverage across all bar builder scripts
3. Use existing `pytest-benchmark` to detect performance regressions

**For schema analysis:**
1. Use SQLAlchemy `Inspector` to reflect table structures
2. Write comparison scripts using reflected metadata
3. Generate schema documentation using reflected DDL

**For standardization documentation:**
1. Use `pdoc` to generate API reference after standardization
2. Use `ruff` to enforce consistent formatting
3. Use `mypy` to enforce consistent type contracts

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| pytest 9.0+ | hypothesis 6.151.4+ | Seamless integration; hypothesis registers as pytest plugin |
| pytest-cov 6.0+ | pytest 9.0+ | Dropped Python 3.8; requires pytest 8.0+ |
| radon 6.0.1 | Python 3.11 | Supports Python 2.7-3.12; no compatibility issues |
| pycode-similar 1.0.3 | Python 3.11 | No known conflicts with existing stack |
| SQLAlchemy 2.0.44 | psycopg2-binary 2.9.11 | Already validated in existing stack |
| ruff 0.15.0+ | Python 3.11 | Use 2026 style guide formatting |

## Why These Additions, Not Others

### Prioritization Rationale

**Analysis over generation:** This milestone reviews existing code, not builds new features. Tools focus on understanding current architecture.

**Programmatic over GUI:** Analysis needs automation across 6 EMA variants and multiple bar builder scripts. Command-line/Python tools enable scripting.

**Incremental over replacement:** Existing stack (PostgreSQL, psycopg2, SQLAlchemy, pandas, pytest) works. Additions complement rather than replace.

**Focused over comprehensive:** Tools target specific gaps:
- No code similarity tool → add pycode-similar
- No complexity metrics → add radon
- Coverage not measured → add pytest-cov
- No API docs → add pdoc (post-standardization)

### What's Already Sufficient

**Database connectivity:** psycopg2-binary 2.9.11 (already installed)
**Data manipulation:** pandas 2.2.3, polars (via pyproject.toml)
**Testing framework:** pytest 8.4.2 (upgrade to 9.0+ recommended)
**Property testing:** hypothesis 6.142.5 (already installed, works perfectly)
**Type checking:** mypy 1.18.2
**Linting/formatting:** ruff 0.14.3 (upgrade to 0.15.0 for 2026 style guide)
**ORM/schema tools:** SQLAlchemy 2.0.44 with Inspector

## Sources

### High Confidence (Official Documentation)
- [Python ast module documentation](https://docs.python.org/3/library/ast.html) — Built-in AST analysis capabilities
- [Radon documentation](https://radon.readthedocs.io/en/latest/) — Code metrics computation
- [pytest 9.0 release notes](https://docs.pytest.org/en/stable/changelog.html) — Latest pytest features 2026
- [Ruff documentation](https://docs.astral.sh/ruff/) — Linter/formatter capabilities
- [SQLAlchemy reflection documentation](https://docs.sqlalchemy.org/en/20/core/reflection.html) — Schema introspection
- [Hypothesis documentation](https://hypothesis.readthedocs.io/) — Property-based testing

### Medium Confidence (Community Resources, Verified)
- [Top Python Code Analysis Tools 2026](https://www.jit.io/resources/appsec-tools/top-python-code-analysis-tools-to-improve-code-quality) — AST tool landscape
- [PyPI pycode-similar](https://pypi.org/project/pycode-similar/) — Code similarity library
- [pytest-cov best practices](https://enodeas.com/pytest-code-coverage-explained/) — Coverage configuration
- [PostgreSQL schema comparison tools](https://www.bytebase.com/blog/top-postgres-schema-compare-tools/) — Alternative tools survey

### Low Confidence (Background Research)
- [Python documentation tools survey](https://medium.com/blueriders/python-autogenerated-documentation-3-tools-that-will-help-document-your-project-c6d7623814ef) — pdoc alternatives
- [Property-based testing tutorial](https://semaphore.io/blog/property-based-testing-python-hypothesis-pytest) — Hypothesis integration patterns

---
*Stack research for: EMA & Bar Architecture Standardization*
*Researched: 2026-02-05*
