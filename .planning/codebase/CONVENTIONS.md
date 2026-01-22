# Coding Conventions

**Analysis Date:** 2026-01-21

## Naming Patterns

**Files:**
- Lowercase with underscores: `ema.py`, `feature_pack.py`, `snapshot_diff.py`
- Private modules use leading underscore: `_maybe_round`, `_flip_for_direction`, `_return`
- Test files follow pattern: `test_{module_name}.py`
- Example paths: `src/ta_lab2/features/ema.py`, `tests/test_features_ema.py`

**Functions:**
- Lowercase with underscores (snake_case): `compute_ema()`, `add_ema_columns()`, `build_daily_ema_frame()`
- Private functions (internal only) prefixed with single underscore: `_ensure_list()`, `_flip_for_direction()`, `_maybe_round()`
- Public API functions exported via `__all__` at module top

**Variables:**
- Lowercase with underscores: `work`, `base_price_cols`, `ema_periods`, `out_name`, `seed_dict`
- Single letter acceptable for loop indices: `i`, `w`, `p` (loop iterators in performance-sensitive code)
- Boolean flags use `is_` prefix or clear suffix: `flipped`, `overwrite`, `need`, `match_close`
- Abbreviated but clear: `df` (DataFrame), `s` (Series), `conn` (connection), `cur` (cursor)

**Types:**
- CapitalCase (PascalCase) for classes: `Settings`, `MultiResult`, `CarryForwardInputs`
- Type aliases and constants in UPPERCASE_WITH_UNDERSCORES: `REGISTRY`, `PSYCOPG3`, `TARGET_DB_URL`
- Private classes use leading underscore (rare)

**Constants:**
- Uppercase with underscores, defined at module top: `REQUIRED_COL_DEFAULTS`, `DEFAULT_TZ`, `BAR_TABLES`
- Example from `test_bar_contract.py`: `DEFAULT_TZ = os.environ.get("TA_LAB2_BAR_TEST_TZ", "America/New_York")`

## Code Style

**Formatting:**
- Python 3.10+ required (from `pyproject.toml`: `requires-python = ">=3.10"`)
- Uses `from __future__ import annotations` at top of all modules (enables postponed evaluation)
- Line length: No explicit config detected; code examples show 80-120 character lines
- Spaces around operators: `df["col"] = s.ewm(span=w, adjust=False).mean()`

**Linting:**
- Tool: `ruff>=0.1.5` (in dev dependencies, `pyproject.toml`)
- MyPy type checking enabled: `mypy>=1.8` (in dev dependencies)
- No `.pylintrc` or `.flake8` detected

**Indentation:**
- 4 spaces (standard Python)
- Multiline function calls use hanging indent:
  ```python
  out = (
      s.astype(float)
      .ewm(span=period, adjust=adjust, min_periods=min_periods)
      .mean()
  )
  ```

## Import Organization

**Order:**
1. Future imports first: `from __future__ import annotations`
2. Standard library: `import os`, `import sys`, `from pathlib import Path`, `from typing import ...`
3. Third-party: `import pandas as pd`, `import numpy as np`, `from sqlalchemy import ...`
4. Local/package imports: `from ta_lab2.config import ...`, `from .vbt_runner import ...`
5. Relative imports for same-package: `from .vbt_runner import`, `from ..signals.registry import REGISTRY`

**Path Aliases:**
- No explicit path aliases configured (no `tsconfig` equivalent for Python)
- Uses package-relative imports: `from ta_lab2.features.ema import compute_ema`
- Imports configured to work from `src/` layout per `pyproject.toml` setuptools config

**Example from `src/ta_lab2/features/ema.py`:**
```python
from __future__ import annotations
from typing import Iterable, Optional, Sequence
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from ta_lab2.config import TARGET_DB_URL
from ta_lab2.io import load_cmc_ohlcv_daily
```

## Error Handling

**Patterns:**
- Specific exception types: `raise TypeError()`, `raise ValueError()`, `raise KeyError()`, `raise RuntimeError()`, `raise ImportError()`
- All errors include descriptive messages with context:
  ```python
  if period is None and window is None:
      raise TypeError("compute_ema() requires either `period` or `window`")
  ```
- Check for missing columns with explicit KeyError:
  ```python
  if col not in obj.columns:
      raise KeyError(f"Column '{col}' not found in DataFrame.")
  ```
- Optional imports wrapped in try/except with None fallback for graceful degradation:
  ```python
  try:
      from ta_lab2.scripts.pipeline.refresh_all import main as pipeline_main
  except Exception:
      pipeline_main = None
  ```
- Database connections use context managers: `with engine.begin() as conn:` and `with conn.cursor() as cur:`
- File existence checked explicitly: `if not FIXTURE.exists(): raise FileNotFoundError(...)`

**Example from `src/ta_lab2/features/indicators.py`:**
```python
if window is None and period is not None:
    window = period
if window is None:
    window = 14
if out_col is None:
    out_col = f"rsi_{window}"

s = _ensure_series(obj, col=price_col)
if s is None:
    raise ValueError("Could not extract series from input")
```

## Logging

**Framework:** `print()` for simple output; no structured logging library detected

**Patterns:**
- Informational output via `print()`: `print("No daily EMA rows generated.")`
- Database operations show affected row counts: `print(f"Updated {rowcount} rows")`
- Error diagnostics in exceptions, not via logging

**Example from `src/ta_lab2/features/ema.py`:**
```python
if df.empty:
    print("No daily EMA rows generated.")
    return 0
```

## Comments

**When to Comment:**
- Section headers with comment lines: `# ---------------------------------------------------------------------------`
- Purpose of private helpers: `def _flip_for_direction(obj, direction): """If data are newest-first, flip to ..."""`
- Non-obvious logic in tight loops or performance-critical sections
- Column naming conventions or database mapping explained inline

**JSDoc/TSDoc:**
- Uses Python docstrings (triple-quote format)
- NumPy docstring style for functions with Parameters/Returns:
  ```python
  """
  Build a longform daily EMA DataFrame suitable for cmc_ema_daily:

      id, tf, ts, period, ema, tf_days, roll, d1, d2, d1_roll, d2_roll

  Parameters
  ----------
  ids : iterable of int
      Asset ids to compute.
  start, end : str or None
      Date range passed through to build_daily_ema_frame.
  update_existing : bool, default True
      If True, existing EMA rows in [start, end] are UPDATED on conflict.
  """
  ```
- Short functions get single-line docstrings: `"""Return a Series from either a Series or DataFrame+col."""`

## Function Design

**Size:** Functions typically 20-150 lines; longer functions decompose into helpers
- Example: `build_daily_ema_frame()` is ~150 lines with clear section comments
- Private helpers extract reusable logic: `_maybe_round()`, `_ensure_series()`, `_return()`

**Parameters:**
- Keyword-only parameters use `*` separator for clarity: `add_ema_columns(..., direction: str = "oldest_top", ...)`
- Type hints always present: `def compute_ema(s: pd.Series, period: int | None = None, ...) -> pd.Series:`
- Optional parameters with clear defaults: `min_periods: Optional[int] = None`, `round_places: Optional[int] = None`
- Backward-compatible aliases accepted and ignored: `price_cols` parameter kept for legacy support

**Return Values:**
- Always typed: `-> pd.DataFrame`, `-> pd.Series`, `-> int`, `-> MultiResult`
- Consistent return type (never mix returning Series vs None)
- DataFrames returned after in-place modifications: `return df`
- Example: `def add_ema_columns(...) -> pd.DataFrame:` - always returns DataFrame

## Module Design

**Exports:**
- Module-level `__all__` list documents public API:
  ```python
  __all__ = [
      "compute_ema",
      "add_ema_columns",
      "add_ema_d1",
      "add_ema_d2",
      "prepare_ema_helpers",
      "add_ema_diffs_longform",
  ]
  ```
- Private functions not in `__all__` (leading underscore convention enforced)

**Barrel Files:**
- `src/ta_lab2/__init__.py` re-exports key public APIs with try/except for optional features
- Example: Graceful failure if optional matplotlib not installed
- Pattern: `from .features.ema import compute_ema` (direct import re-export)

**Organization:**
- Public functions documented with full docstrings
- Private helpers grouped below with `# ---------------------` markers
- Related functions grouped together (all EMA variants together)
- Section markers with dashes make navigation clear:
  ```python
  # ---------------------------------------------------------------------------
  # Core EMA helper
  # ---------------------------------------------------------------------------

  # ---------------------------------------------------------------------------
  # Utilities
  # ---------------------------------------------------------------------------
  ```

---

*Convention analysis: 2026-01-21*
