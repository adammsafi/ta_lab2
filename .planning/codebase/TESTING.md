# Testing Patterns

**Analysis Date:** 2026-01-21

## Test Framework

**Runner:**
- pytest >= 8.0
- Config file: `pytest.ini` at project root
- Entry point: `pytest`

**Pytest Configuration:**
```ini
[pytest]
testpaths = tests
pythonpath = src
```

**Assertion Library:**
- Standard Python `assert` statements
- pytest provides additional assertion introspection

**Run Commands:**
```bash
pytest                                # Run all tests
pytest -q                             # Quiet mode (fewer details)
pytest -vv                            # Verbose output
pytest tests/test_features_ema.py     # Run specific test file
pytest tests/test_db_snapshot_check.py::test_snapshot_check_output_shape_and_warning_gating  # Run specific test
pytest -m pytest                      # Run via python module (Spyder/IPython console: %run -m pytest)
```

**Additional Tools (in dev dependencies):**
- `pytest-benchmark`: Benchmarking tests if needed
- `hypothesis`: Property-based testing (optional)

## Test File Organization

**Location:**
- Separate from source code: `tests/` directory at project root
- Source in `src/ta_lab2/`, tests in `tests/`
- Pattern: co-located by module name

**Naming:**
- Test files: `test_{module_name}.py`
- Examples: `test_features_ema.py`, `test_calendar.py`, `test_bar_contract.py`
- Test functions: `test_{functionality}()`
- Example: `def test_compute_ema_basic():`, `def test_snapshot_check_output_shape_and_warning_gating():`

**Structure:**
```
tests/
├── conftest.py                       # Shared fixtures and configuration
├── fixtures/                         # Test data (JSON, CSV, etc.)
│   └── db_schema_snapshot_min.json
├── old/                              # Archived/old tests
│   └── test_bar_ohlc_correctness_old.py
├── test_bar_contract.py              # Database contract tests
├── test_bar_ohlc_correctness.py      # Bar calculation correctness
├── test_calendar.py                  # Calendar feature tests
├── test_cli_paths.py                 # CLI path handling
├── test_db_snapshot_check.py         # Snapshot validation
├── test_features_ema.py              # EMA feature tests
├── test_pipeline.py                  # Pipeline integration
└── test_smoke_imports.py             # Import sanity checks
```

## Test Structure

**Suite Organization:**
```python
# Basic pattern from test_features_ema.py
import pandas as pd
from ta_lab2.features.ema import compute_ema

def test_compute_ema_basic():
    s = pd.Series([1, 2, 3, 4, 5])
    out = compute_ema(s, window=3)
    assert len(out) == 5
    assert pd.notna(out.iloc[-1])
```

**Patterns:**
- Single test function per concept
- Arrange-Act-Assert structure (implicit)
- Simple assertions preferred: `assert len(out) == 5`, `assert pd.notna(out.iloc[-1])`

**Test Data Setup (Fixtures):**
Example from `conftest.py`:
```python
@pytest.fixture
def tiny_csv(tmp_path: Path) -> Path:
    """Create temporary CSV for testing."""
    df = pd.DataFrame({
        "Date": ["2024-01-01","2024-01-02","2024-01-03"],
        "Open": [100, 101, 102],
        "High": [101, 102, 103],
        "Low":  [ 99, 100, 101],
        "Close":[100.5, 101.5, 102.5],
        "Volume": [1000, 1200, 1100],
        "Market Cap": [1e9, 1.01e9, 1.02e9],
    })
    p = tmp_path / "tiny.csv"
    df.to_csv(p, index=False)
    return p
```

**Fixture Access:**
- Use `tmp_path` built-in pytest fixture for temporary files
- Custom fixtures in `conftest.py` available to all tests
- Example: `def test_pipeline_minimal(tmp_path):` - tmp_path automatically provided

## Mocking

**Framework:** No explicit mocking library detected in test files
- Database tests use real DB connection (skipped if DB_URL not available)
- File system tests use `tmp_path` fixture instead of mocks

**Patterns:**
- Skip tests when dependencies unavailable:
  ```python
  if not DB_URL:
      pytest.skip("DB tests skipped: set TARGET_DB_URL (or TA_LAB2_DB_URL).", allow_module_level=True)
  ```
- Check for optional imports:
  ```python
  try:
      import psycopg  # type: ignore
      PSYCOPG3 = True
  except Exception:
      psycopg = None
      PSYCOPG3 = False
  ```

**What to Mock:**
- External database calls: Use real connections if DB_URL available, else skip test
- File operations: Use `tmp_path` instead of mocking file system
- External APIs: Not present in codebase; would use real connections if available

**What NOT to Mock:**
- Internal pandas operations (test with real DataFrames)
- Mathematical computations (test with real numbers)
- Import chains (test real imports via `test_smoke_imports.py`)

## Fixtures and Factories

**Test Data:**
From `test_pipeline.py`:
```python
def test_pipeline_minimal(tmp_path):
    p = tmp_path / "btc.csv"
    pd.DataFrame({
        "timestamp":["2025-01-01T00:00:00Z","2025-01-02T00:00:00Z"],
        "open":[1,1.1],"high":[1.1,1.2],"low":[0.9,1.0],"close":[1.05,1.15],"volume":[10,12]
    }).to_csv(p, index=False)
    res = run_btc_pipeline(str(p))
    assert res["summary"]["n_rows"] == 2
```

**Location:**
- Fixtures in `tests/conftest.py` for sharing across tests
- Test-specific setup in test file itself if not reused
- Fixture data files in `tests/fixtures/` subdirectory

**Built-in Pytest Fixtures Used:**
- `tmp_path`: Temporary directory for test files
- `tmp_path_factory`: Create multiple temp paths
- Module-level fixtures via `scope="module"`

## Coverage

**Requirements:** Not explicitly enforced (no `--cov` in pytest.ini)

**View Coverage:**
```bash
pytest --cov=src/ta_lab2 --cov-report=html  # If coverage.py installed
```

**Coverage Configuration:** None detected in codebase
- No `.coveragerc` or coverage config in `pyproject.toml`

**Gap Analysis:**
- Integration tests present: `test_bar_contract.py`, `test_pipeline.py`, `test_db_snapshot_*`
- Unit tests present: `test_features_ema.py`, `test_calendar.py`
- Smoke tests: `test_smoke_imports.py` validates all major imports work

## Test Types

**Unit Tests:**
- Scope: Single function or class behavior
- Example: `test_compute_ema_basic()` - tests `compute_ema()` with simple input
- Approach: Small DataFrames (3-5 rows), direct assertions

**Integration Tests:**
- Scope: Multiple components working together
- Examples: `test_pipeline_minimal()` - entire pipeline
- Approach: Real CSV files, real computation, check output structure/values

**Database Tests:**
- Scope: Schema validation and data integrity
- Examples: `test_bar_contract.py` - validates OHLC candle integrity, one-row-per-day contracts
- Approach: Real PostgreSQL connection (requires `TARGET_DB_URL` env var)
- Skip logic: Tests auto-skip if DB unavailable

**E2E Tests:**
- Framework: None explicit (integration tests serve this purpose)
- Database tests are closest to E2E (real DB, real data validation)

## Common Patterns

**Async Testing:**
- Not used (no async/await in codebase)
- Database tests use synchronous connections (psycopg2/psycopg)

**Error Testing:**
```python
# From test_bar_contract.py - checking schema enforcement
rows = _fetchall(
    conn,
    """
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = %s AND table_name = %s
    LIMIT 1
    """,
    [schema, name],
)
assert bool(rows), f"Table {table} does not exist"
```

**Database Assertions:**
```python
# From test_db_snapshot_check.py
for k in ["meta", "ok", "source", "warnings", "top_tables_by_total_bytes", "top_tables_by_rows"]:
    assert k in out, f"Missing key: {k}"

assert out["ok"] is True
assert out["source"]  # should be path-like string

warnings = out["warnings"]
assert isinstance(warnings, list)
assert len(warnings) == len(set(warnings)), "Warnings list has duplicates"
```

**DataFrame Assertions:**
```python
# From test_calendar.py
def test_calendar_expands():
    df = pd.DataFrame({"ts":["2025-01-01T00:00:00Z","2025-01-02T00:00:00Z"]})
    expand_datetime_features_inplace(df, "ts", prefix="ts", add_moon=False)
    assert {"ts_quarter","ts_week_of_year","ts_day_of_year"} <= set(df.columns)
```

**CLI Subprocess Tests:**
```python
# From test_db_snapshot_check.py
cmd = ["ta-lab2", "db", "snapshot-check", "--in-path", str(FIXTURE), "--min-rows", "1", "--top-n", "20"]
try:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode == 0:
        return json.loads(p.stdout)
except FileNotFoundError:
    # Fallback to python -m if console script not available
    pass
```

## Environment Configuration

**Database Tests:**
- Require environment variable: `TARGET_DB_URL` or `TA_LAB2_DB_URL`
- Format: PostgreSQL connection string (psycopg2/psycopg3 compatible)
- Example: `postgresql://user:pass@localhost/ta_lab2`
- Behavior: Tests skip if not set (pytest.skip at module level)

**Optional Environment Variables:**
- `TA_LAB2_BAR_TEST_TZ`: Timezone for bar tests (default: "America/New_York")

**Pytest Configuration:**
- `pythonpath = src` in `pytest.ini` - allows importing from `src/ta_lab2` without installation

---

*Testing analysis: 2026-01-21*
