# Phase 25: Baseline Capture - Research

**Researched:** 2026-02-05
**Domain:** Database snapshot testing, comparison validation, regression testing
**Confidence:** HIGH

## Summary

Baseline capture validates that Phase 22-24 refactoring preserved calculation correctness by creating snapshots of current bar and EMA outputs, truncating tables, rebuilding via refactored scripts, and comparing results with epsilon-aware tolerance.

The codebase already has snapshot infrastructure (`sql/snapshots/`), comparison queries (`sql/checks/`), and Phase 23 orchestration patterns (`run_all_ema_refreshes.py`). The research identifies:

1. **PostgreSQL snapshot strategy**: `CREATE TABLE AS SELECT` is the standard approach, already used in `create_cmc_price_bars_multi_tf_snapshot.sql` and `create_cmc_ema_snapshots_20251124.sql`
2. **Epsilon tolerance**: NumPy `allclose()` with `rtol=1e-5, atol=1e-8` is standard; existing EMA comparison SQL uses `ABS(ema - ema_snap)` suggesting absolute difference threshold approach
3. **Sampling strategy**: Beginning/end focus with random sampling for large time series, avoiding temporal ordering violations
4. **Orchestration pattern**: Phase 23 subprocess isolation with dry-run, verbose control, and summary reporting provides the template
5. **Metadata tracking**: Git commit hash + timestamp + asset count + date range + script versions for full reproducibility

**Primary recommendation:** Create Python orchestration script following Phase 23 patterns (subprocess isolation, summary reporting) that snapshots → truncates → rebuilds → compares with hybrid tolerance (absolute + relative) and comprehensive mismatch reporting.

## Standard Stack

The established tools for snapshot testing and validation in this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PostgreSQL | 16+ | Database snapshots via CREATE TABLE AS | Native feature, MVCC-based consistency, already used in codebase |
| NumPy | 1.26+ | Floating-point comparison (allclose, isclose) | Industry standard for numerical tolerance, supports both absolute and relative |
| pandas | 2.2+ | DataFrame comparison and sampling | Already used throughout codebase for data manipulation |
| subprocess | stdlib | Process isolation for rebuild scripts | Phase 23 pattern, prevents state leakage |
| SQLAlchemy | 2.0+ | Database operations and metadata queries | Already used in common_snapshot_contract.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 7.4+ | Test framework (if automated tests desired) | GAP-C04 addresses need for automated validation tests |
| logging | stdlib | Audit trail and diagnostic output | Already configured in logging_config.py |
| argparse | stdlib | CLI interface for orchestration script | Phase 23 pattern for orchestrators |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| CREATE TABLE AS | pg_dump partial | pg_dump adds serialization overhead, harder to query for comparison |
| NumPy allclose | Manual epsilon loops | Reinventing the wheel, allclose handles edge cases (NaN, infinity) |
| Python orchestration | Bash script | Python provides better error handling, summary reporting, already established pattern |

**Installation:**
```bash
# All dependencies already in environment (no new installations needed)
pip list | grep -E "numpy|pandas|sqlalchemy|pytest"
```

## Architecture Patterns

### Recommended Project Structure
```
.planning/phases/25-baseline-capture/
├── 25-CONTEXT.md                  # User decisions (already exists)
├── 25-RESEARCH.md                 # This document
├── 25-PLAN.md                     # Orchestration script plan
└── 25-SUMMARY.md                  # Execution results

src/ta_lab2/scripts/baseline/
├── capture_baseline.py            # Main orchestration script
├── comparison_utils.py            # Epsilon tolerance comparison functions
└── metadata_tracker.py            # Audit trail generation

sql/baseline/
├── snapshot_YYYYMMDD.sql          # Timestamped snapshot DDL
└── comparison_YYYYMMDD.sql        # Comparison queries for validation

.logs/
└── baseline-capture-YYYYMMDD.log  # Detailed execution log
```

### Pattern 1: Snapshot → Truncate → Rebuild → Compare Workflow

**What:** Four-phase validation workflow that proves rebuild produces identical results

**When to use:** After major refactoring (Phase 22-24) to validate calculation preservation

**Example:**
```python
# Source: Phase 25 CONTEXT.md user strategy
def validate_pipeline(config: BaselineConfig) -> ValidationResult:
    """
    End-to-end pipeline validation.

    Workflow from CONTEXT.md:
    1. CREATE TABLE ... AS SELECT * FROM ... (snapshot current state)
    2. TRUNCATE TABLE ... (clear existing data)
    3. subprocess.run(bar_builder) then subprocess.run(ema_refresher)
    4. Compare snapshots vs rebuilt tables with epsilon tolerance

    Returns detailed comparison report (mismatches, statistics, pass/fail).
    """
    metadata = capture_metadata()  # Git hash, timestamp, config

    # Phase 1: Snapshot
    snapshot_tables(config.tables, suffix=metadata.timestamp)

    # Phase 2: Truncate
    truncate_tables(config.tables)

    # Phase 3: Rebuild (following Phase 23 subprocess pattern)
    bar_result = run_bar_builders(config.assets, config.date_range)
    if not bar_result.success:
        return ValidationResult(phase="bar_rebuild", success=False, metadata=metadata)

    ema_result = run_ema_refreshers(config.assets, config.date_range)
    if not ema_result.success:
        return ValidationResult(phase="ema_rebuild", success=False, metadata=metadata)

    # Phase 4: Compare with epsilon-aware tolerance
    comparison = compare_snapshots_to_rebuilt(
        config.tables,
        snapshot_suffix=metadata.timestamp,
        tolerance=config.epsilon_config
    )

    log_validation_report(comparison, metadata)
    return ValidationResult(success=comparison.all_passed, metadata=metadata)
```

### Pattern 2: Epsilon-Aware Comparison with Hybrid Bounds

**What:** Combine absolute tolerance (for small values near zero) and relative tolerance (for large values) to handle floating-point precision

**When to use:** Comparing OHLCV bar data and EMA calculations after rebuild

**Example:**
```python
# Source: NumPy allclose documentation + Phase 22 EMA validation hybrid bounds concept
import numpy as np
import pandas as pd

def compare_with_hybrid_tolerance(
    baseline_df: pd.DataFrame,
    rebuilt_df: pd.DataFrame,
    *,
    float_columns: list[str],
    rtol: float = 1e-5,
    atol: float = 1e-8,
) -> pd.DataFrame:
    """
    Compare floating-point columns using NumPy allclose tolerance.

    Tolerance formula from numpy.allclose:
        abs(baseline - rebuilt) <= max(rtol * max(abs(baseline), abs(rebuilt)), atol)

    For OHLCV data (prices in dollars):
        - atol=1e-8: Absolute tolerance ~0.00000001 USD (catches exact equality)
        - rtol=1e-5: Relative tolerance 0.001% (catches floating-point rounding)

    For EMA values (similar to prices):
        - Same tolerances work well (EMA derived from OHLC)

    Returns DataFrame with columns:
        - id, tf, bar_seq (or period for EMAs)
        - timestamp
        - column_name
        - baseline_value
        - rebuilt_value
        - abs_diff
        - rel_diff
        - within_tolerance (bool)
    """
    merged = baseline_df.merge(
        rebuilt_df,
        on=["id", "tf", "bar_seq", "timestamp"],  # Adjust keys for EMA tables
        suffixes=("_baseline", "_rebuilt"),
    )

    mismatches = []
    for col in float_columns:
        baseline_col = f"{col}_baseline"
        rebuilt_col = f"{col}_rebuilt"

        # Use NumPy allclose element-wise
        baseline_vals = merged[baseline_col].values
        rebuilt_vals = merged[rebuilt_col].values

        # Handle NaN values (mark as mismatch if one is NaN and other isn't)
        both_nan = np.isnan(baseline_vals) & np.isnan(rebuilt_vals)
        neither_nan = ~np.isnan(baseline_vals) & ~np.isnan(rebuilt_vals)

        # Compute tolerance for non-NaN values
        abs_diff = np.abs(baseline_vals - rebuilt_vals)
        max_val = np.maximum(np.abs(baseline_vals), np.abs(rebuilt_vals))
        tolerance_threshold = np.maximum(rtol * max_val, atol)

        within_tolerance = (abs_diff <= tolerance_threshold) | both_nan

        # Flag mismatches
        mismatch_mask = ~within_tolerance
        if mismatch_mask.any():
            mismatch_rows = merged[mismatch_mask].copy()
            mismatch_rows["column_name"] = col
            mismatch_rows["baseline_value"] = baseline_vals[mismatch_mask]
            mismatch_rows["rebuilt_value"] = rebuilt_vals[mismatch_mask]
            mismatch_rows["abs_diff"] = abs_diff[mismatch_mask]
            mismatch_rows["rel_diff"] = abs_diff[mismatch_mask] / np.maximum(
                np.abs(baseline_vals[mismatch_mask]), 1e-10
            )
            mismatch_rows["within_tolerance"] = False
            mismatches.append(mismatch_rows)

    if not mismatches:
        return pd.DataFrame()  # All matched

    return pd.concat(mismatches, ignore_index=True)
```

### Pattern 3: Intelligent Sampling for Large Time Series

**What:** Sample beginning/end with randomness to validate data quality without comparing entire dataset

**When to use:** When baseline tables contain millions of rows (full comparison too slow)

**Example:**
```python
# Source: Time series sampling research + CONTEXT.md "intelligent sampling with randomness"
def sample_for_comparison(
    baseline_table: str,
    *,
    assets: list[int],
    beginning_days: int = 30,
    end_days: int = 30,
    random_sample_pct: float = 0.05,
) -> pd.DataFrame:
    """
    Intelligent sampling strategy for time series validation.

    Strategy from CONTEXT.md:
    - Focus on beginning and end of time series (data quality issues often appear here)
    - Add random sampling to catch interior issues
    - Preserve temporal ordering within samples (avoid cross-validation anti-pattern)

    Rationale:
    - Beginning: Tests backfill detection, initial state correctness
    - End: Tests incremental refresh correctness (most recent data)
    - Random: Catches interior calculation drift without full scan

    Returns sampled DataFrame suitable for epsilon-aware comparison.
    """
    samples = []

    for asset_id in assets:
        # Get min/max timestamps for this asset
        min_max_query = f"""
        SELECT
            MIN(timestamp) as min_ts,
            MAX(timestamp) as max_ts
        FROM {baseline_table}
        WHERE id = {asset_id}
        """
        min_ts, max_ts = execute_query(min_max_query)

        # Sample beginning: first N days of data
        beginning_query = f"""
        SELECT * FROM {baseline_table}
        WHERE id = {asset_id}
          AND timestamp <= '{min_ts}'::timestamptz + INTERVAL '{beginning_days} days'
        ORDER BY timestamp
        """
        samples.append(execute_query(beginning_query))

        # Sample end: last N days of data
        end_query = f"""
        SELECT * FROM {baseline_table}
        WHERE id = {asset_id}
          AND timestamp >= '{max_ts}'::timestamptz - INTERVAL '{end_days} days'
        ORDER BY timestamp
        """
        samples.append(execute_query(end_query))

        # Random sample from interior: stratified by time period
        # IMPORTANT: Use TABLESAMPLE or random sample WITHIN time windows
        # to preserve temporal ordering (don't shuffle across time)
        random_query = f"""
        WITH time_buckets AS (
            SELECT
                *,
                ntile(10) OVER (ORDER BY timestamp) as bucket
            FROM {baseline_table}
            WHERE id = {asset_id}
              AND timestamp > '{min_ts}'::timestamptz + INTERVAL '{beginning_days} days'
              AND timestamp < '{max_ts}'::timestamptz - INTERVAL '{end_days} days'
        )
        SELECT * FROM time_buckets
        WHERE random() < {random_sample_pct}
        ORDER BY timestamp
        """
        samples.append(execute_query(random_query))

    return pd.concat(samples, ignore_index=True)
```

### Pattern 4: Metadata Capture for Reproducibility

**What:** Capture full audit trail (git hash, timestamp, config) to reproduce baseline capture later

**When to use:** Every baseline capture execution (mandatory per CONTEXT.md)

**Example:**
```python
# Source: Audit trail best practices research + CONTEXT.md metadata requirements
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

@dataclass
class BaselineMetadata:
    """Full audit trail for baseline capture reproducibility."""

    # Timestamp (ISO-8601 UTC)
    capture_timestamp: str

    # Git commit hash (for exact code version)
    git_commit_hash: str
    git_branch: str
    git_is_dirty: bool  # Uncommitted changes present

    # Asset and date range coverage
    asset_count: int
    asset_ids: list[int]
    date_range_start: str
    date_range_end: str

    # Script versions (which bar builders, EMA refreshers ran)
    bar_builders_invoked: list[str]
    ema_refreshers_invoked: list[str]

    # Database state
    db_url: str  # Redact password for logging
    snapshot_table_suffix: str

    # Configuration
    epsilon_rtol: float
    epsilon_atol: float
    sampling_strategy: dict

    def to_dict(self) -> dict:
        """Serialize to JSON for logging."""
        return {
            "capture_timestamp": self.capture_timestamp,
            "git": {
                "commit_hash": self.git_commit_hash,
                "branch": self.git_branch,
                "dirty": self.git_is_dirty,
            },
            "assets": {
                "count": self.asset_count,
                "ids": self.asset_ids,
            },
            "date_range": {
                "start": self.date_range_start,
                "end": self.date_range_end,
            },
            "scripts": {
                "bar_builders": self.bar_builders_invoked,
                "ema_refreshers": self.ema_refreshers_invoked,
            },
            "database": {
                "url": self.db_url.split("@")[-1],  # Remove password
                "snapshot_suffix": self.snapshot_table_suffix,
            },
            "comparison_config": {
                "epsilon_rtol": self.epsilon_rtol,
                "epsilon_atol": self.epsilon_atol,
                "sampling": self.sampling_strategy,
            },
        }

def capture_metadata(config: BaselineConfig) -> BaselineMetadata:
    """
    Capture full metadata for audit trail.

    Best practices from research:
    - Git hash: Exact code version for reproducibility
    - Timestamp: ISO-8601 UTC for unambiguous ordering
    - Asset count: Scope of validation
    - Date range: Time window validated
    - Script versions: Which builders/refreshers executed
    """
    # Git commit hash
    git_hash = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).parent,
        text=True,
    ).strip()

    git_branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=Path(__file__).parent,
        text=True,
    ).strip()

    git_dirty = subprocess.call(
        ["git", "diff", "--quiet"],
        cwd=Path(__file__).parent,
    ) != 0

    # Timestamp in ISO-8601 UTC
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    return BaselineMetadata(
        capture_timestamp=timestamp,
        git_commit_hash=git_hash,
        git_branch=git_branch,
        git_is_dirty=git_dirty,
        asset_count=len(config.assets),
        asset_ids=config.assets,
        date_range_start=config.start_date,
        date_range_end=config.end_date,
        bar_builders_invoked=config.bar_scripts,
        ema_refreshers_invoked=config.ema_scripts,
        db_url=config.db_url,
        snapshot_table_suffix=timestamp,
        epsilon_rtol=config.epsilon_rtol,
        epsilon_atol=config.epsilon_atol,
        sampling_strategy=config.sampling,
    )
```

### Anti-Patterns to Avoid

- **Random shuffling of time series data:** WebSearch research shows this violates temporal ordering and causes data leakage in validation (models "peek into future")
- **Single absolute epsilon for all data types:** OHLCV prices ($0.01-$100K) and EMA values require both absolute AND relative tolerance (NumPy allclose hybrid approach)
- **Stopping on first mismatch:** CONTEXT.md specifies "always run to completion, report only" - collect ALL mismatches for comprehensive analysis
- **Manual snapshot table naming:** Timestamped pattern from CONTEXT.md prevents collisions and tracks multiple baselines over time

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Floating-point comparison with tolerance | Custom epsilon loops checking `abs(a - b) < eps` | `numpy.allclose()` or `numpy.isclose()` | Handles NaN, infinity, negative zero, provides both absolute and relative tolerance in single call |
| Database snapshot consistency | Row-by-row INSERT with locks | `CREATE TABLE AS SELECT` in single transaction | PostgreSQL MVCC ensures consistent snapshot automatically, single transaction is atomic |
| Process isolation for rebuild scripts | `runpy.run_path()` (Phase 22 initial approach) | `subprocess.run()` (Phase 23 pattern) | Prevents state leakage, matches established orchestration pattern |
| Timestamp formatting for audit trails | Manual string formatting | `datetime.utcnow().isoformat()` or `.strftime("%Y-%m-%dT%H:%M:%SZ")` | ISO-8601 standard, timezone-aware, sortable |
| CLI argument parsing for orchestrator | Manual `sys.argv` parsing | `argparse.ArgumentParser` (Phase 23 pattern) | Type conversion, help text, validation, already established pattern |

**Key insight:** PostgreSQL CREATE TABLE AS SELECT is MVCC-based and provides automatic snapshot consistency - trying to manually lock tables or copy row-by-row adds complexity and breaks ACID guarantees. The research confirms this is the standard approach (used in existing `sql/snapshots/` files).

## Common Pitfalls

### Pitfall 1: Ignoring NaN and NULL Differences

**What goes wrong:** Comparison logic treats NaN != NaN and NULL differently across SQL vs Python

**Why it happens:** SQL `NULL != NULL` evaluates to NULL (unknown), NumPy `np.nan != np.nan` is True, pandas has both

**How to avoid:** Use `IS NOT DISTINCT FROM` in SQL, `equal_nan=True` in NumPy allclose, document NULL handling strategy

**Warning signs:**
- Comparison reports mismatches where both values are NULL/NaN
- Mismatch counts change when filtering NULL values
- SQL query returns different counts than pandas merge

**Example from codebase:**
```sql
-- From check_ema_multi_tf_snapshot_detailed_diff.sql lines 26-34
SUM(CASE WHEN
    (ema      IS NOT DISTINCT FROM ema_snap) AND  -- Handles NULL = NULL as TRUE
    (tf_days  IS NOT DISTINCT FROM tf_days_snap) AND
    ...
  THEN 1 ELSE 0 END
) AS n_exact_match
```

### Pitfall 2: Using Wrong Tolerance for Data Type

**What goes wrong:** Single `atol=1e-8` applied to all columns produces false positives or false negatives

**Why it happens:** OHLCV prices range from $0.0001 (altcoins) to $100,000 (BTC), volume ranges from 0 to billions

**How to avoid:** Per-column tolerance based on data characteristics:
- **Price columns (open, high, low, close):** `atol=1e-6, rtol=1e-5` (allow 0.001% relative difference)
- **Volume columns:** `atol=1e-2, rtol=1e-4` (volume has lower precision requirements)
- **EMA columns:** `atol=1e-6, rtol=1e-5` (same as prices, EMA derived from OHLC)

**Warning signs:**
- All mismatches are in one column (e.g., volume) while prices match exactly
- Mismatch percentages differ wildly across columns (0% for prices, 50% for volume)

**Best practice from research:**
```python
# From NumPy documentation: "Be sure to select atol for the use case at hand"
COLUMN_TOLERANCES = {
    "open": {"atol": 1e-6, "rtol": 1e-5},
    "high": {"atol": 1e-6, "rtol": 1e-5},
    "low": {"atol": 1e-6, "rtol": 1e-5},
    "close": {"atol": 1e-6, "rtol": 1e-5},
    "volume": {"atol": 1e-2, "rtol": 1e-4},  # Lower precision OK
    "ema": {"atol": 1e-6, "rtol": 1e-5},
}
```

### Pitfall 3: Temporal Ordering Violations in Sampling

**What goes wrong:** Random sampling across entire time series creates train-on-future data leakage

**Why it happens:** Treating time series as i.i.d. data and shuffling before split

**How to avoid:** Preserve temporal ordering within samples:
- Sample beginning N days (ordered by timestamp)
- Sample end N days (ordered by timestamp)
- For random interior sampling, use stratified sampling WITHIN time buckets (don't shuffle across time)

**Warning signs:**
- Comparison finds mismatches in beginning/end but random sample shows no issues
- Sampling code uses `df.sample(frac=0.1)` without temporal stratification

**Research citation:** Time series cross-validation research emphasizes "safer to use a time-series aware scheme rather than random approaches that ignore temporal ordering" to avoid accidentally allowing models to "peek into the future."

### Pitfall 4: Insufficient Metadata for Reproducibility

**What goes wrong:** Can't reproduce baseline capture 3 months later because git commit hash, date range, or asset list not logged

**Why it happens:** Assuming current state is always reproducible, not logging execution context

**How to avoid:** Capture comprehensive metadata (see Pattern 4 above):
- Git commit hash + dirty flag
- ISO-8601 timestamp with timezone
- Full asset list (not just count)
- Date range boundaries
- Script versions and arguments
- Database connection details (redact password)
- Epsilon tolerance configuration

**Warning signs:**
- Log files contain only timestamp and pass/fail status
- No way to know which version of code produced baseline
- Can't determine if differences are due to data changes or code changes

**Best practice:** Store metadata as JSON alongside comparison results for programmatic access.

## Code Examples

Verified patterns from official sources and existing codebase:

### Database Snapshot Creation (PostgreSQL Standard)

```sql
-- Source: sql/snapshots/create_cmc_price_bars_multi_tf_snapshot.sql
-- Pattern: CREATE TABLE AS SELECT with timestamped naming
CREATE TABLE public.cmc_price_bars_multi_tf_snapshot_20260205
AS
SELECT *
FROM public.cmc_price_bars_multi_tf;

-- Add primary key for efficient comparison queries
ALTER TABLE public.cmc_price_bars_multi_tf_snapshot_20260205
  ADD CONSTRAINT cmc_price_bars_multi_tf_snapshot_20260205_pkey
  PRIMARY KEY (id, tf, bar_seq);

-- Repeat for all 6 EMA variants
CREATE TABLE public.cmc_ema_multi_tf_snapshot_20260205
(LIKE public.cmc_ema_multi_tf INCLUDING ALL);

INSERT INTO public.cmc_ema_multi_tf_snapshot_20260205
SELECT * FROM public.cmc_ema_multi_tf;
```

### Epsilon-Aware Comparison (NumPy Standard)

```python
# Source: NumPy allclose documentation + Phase 22 validation patterns
import numpy as np
import pandas as pd

def compare_bar_tables(
    baseline: pd.DataFrame,
    rebuilt: pd.DataFrame,
    float_cols: list[str] = ["open", "high", "low", "close", "volume"],
) -> dict:
    """
    Compare bar tables with epsilon tolerance.

    Uses NumPy allclose formula:
        abs(a - b) <= max(rtol * max(abs(a), abs(b)), atol)

    Returns summary with match_rate, max_diff, mean_diff, std_diff.
    """
    # Merge on composite key
    merged = baseline.merge(
        rebuilt,
        on=["id", "tf", "bar_seq", "time_close"],
        suffixes=("_base", "_rebuild"),
    )

    results = {}
    for col in float_cols:
        base_col = f"{col}_base"
        rebuild_col = f"{col}_rebuild"

        base_vals = merged[base_col].values
        rebuild_vals = merged[rebuild_col].values

        # NumPy allclose with default tolerances
        matches = np.isclose(
            base_vals,
            rebuild_vals,
            rtol=1e-5,
            atol=1e-8,
            equal_nan=True,  # Treat NaN = NaN as match
        )

        match_rate = np.sum(matches) / len(matches)

        # Compute statistics on mismatches
        diffs = np.abs(base_vals - rebuild_vals)
        results[col] = {
            "match_rate": match_rate,
            "max_diff": np.nanmax(diffs),
            "mean_diff": np.nanmean(diffs),
            "std_diff": np.nanstd(diffs),
        }

    return results
```

### SQL-Based Comparison (Existing Pattern)

```sql
-- Source: sql/checks/check_ema_multi_tf_snapshot_detailed_diff.sql
-- Pattern: Join baseline and rebuilt, compute absolute differences
WITH joined AS (
  SELECT
    current.id, current.tf, current.ts, current.period,
    current.ema AS ema_rebuilt,
    snapshot.ema AS ema_baseline,
    ABS(current.ema - snapshot.ema) AS ema_abs_diff
  FROM public.cmc_ema_multi_tf current
  JOIN public.cmc_ema_multi_tf_snapshot_20260205 snapshot
    USING (id, tf, ts, period)
  WHERE current.ema IS NOT NULL AND snapshot.ema IS NOT NULL
)
SELECT
  COUNT(*) AS total_rows,
  SUM(CASE WHEN ema_abs_diff < 1e-6 THEN 1 ELSE 0 END) AS exact_matches,
  SUM(CASE WHEN ema_abs_diff >= 1e-6 THEN 1 ELSE 0 END) AS mismatches,
  MAX(ema_abs_diff) AS max_diff,
  AVG(ema_abs_diff) AS avg_diff,
  STDDEV(ema_abs_diff) AS stddev_diff
FROM joined;

-- Top mismatches for investigation
SELECT *
FROM joined
ORDER BY ema_abs_diff DESC
LIMIT 50;
```

### Phase 23 Orchestration Pattern (Subprocess Isolation)

```python
# Source: src/ta_lab2/scripts/emas/run_all_ema_refreshes.py
# Pattern: Subprocess execution with dry-run, verbose, summary reporting
import subprocess
import sys
from pathlib import Path

def run_bar_builders(
    *,
    ids: list[int],
    start_date: str,
    end_date: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Run all bar builders following Phase 23 subprocess pattern.

    Returns dict with success status and duration.
    """
    script_dir = Path(__file__).parent.parent / "bars"

    # Build command (following Phase 23 build_command pattern)
    cmd = [
        sys.executable,
        str(script_dir / "run_all_bar_builders.py"),
        "--ids", " ".join(map(str, ids)),
        "--start", start_date,
        "--end", end_date,
    ]

    if dry_run:
        print(f"[DRY RUN] Would execute: {' '.join(cmd)}")
        return {"success": True, "duration_sec": 0.0}

    print(f"\n{'='*70}")
    print("Running: Bar Builders")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*70}")

    import time
    start = time.perf_counter()

    # Subprocess isolation (Phase 23 pattern)
    if verbose:
        result = subprocess.run(cmd, check=False)
    else:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"\n[ERROR] Bar builders failed with code {result.returncode}")
            if result.stdout:
                print(f"\nSTDOUT:\n{result.stdout}")
            if result.stderr:
                print(f"\nSTDERR:\n{result.stderr}")

    duration = time.perf_counter() - start
    success = result.returncode == 0

    return {"success": success, "duration_sec": duration}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual SQL snapshot queries | Timestamped CREATE TABLE AS pattern | Existing (sql/snapshots/ 2025-12) | Reproducible snapshots, no table name collisions |
| Hard epsilon thresholds in SQL | NumPy allclose hybrid tolerance | Current standard (NumPy 1.26+) | Handles both small and large values correctly |
| runpy.run_path for orchestration | subprocess.run with isolation | Phase 23 (2026-01) | Process isolation prevents state leakage |
| Manual validation queries | Automated comparison with statistics | Current goal (Phase 25) | Comprehensive mismatch reporting with severity levels |
| No metadata capture | Git hash + timestamp audit trail | Best practice 2026 | Full reproducibility and investigation capability |

**Deprecated/outdated:**
- **Simple diff-based comparison (PostgreSQL regression tests):** Research shows this is "sensitive to small system differences" - modern approach uses epsilon tolerance
- **Random sampling without temporal awareness:** Research emphasizes time-series cross-validation must preserve ordering to avoid data leakage
- **Single absolute tolerance for all columns:** NumPy documentation warns this produces incorrect results for values near zero or very large magnitudes

## Open Questions

Things that couldn't be fully resolved:

1. **Exact epsilon values per column type**
   - What we know: OHLCV prices need `atol=1e-6, rtol=1e-5` based on dollar precision, EMA values similar
   - What's unclear: Volume column tolerance - research suggests `atol=1e-2, rtol=1e-4` but depends on exchange precision
   - Recommendation: Start with conservative values, log actual diff distributions, tune based on real data

2. **Sampling percentage for random interior sampling**
   - What we know: CONTEXT.md specifies "intelligent sampling with randomness", beginning/end focus
   - What's unclear: Optimal random sample percentage (1%? 5%? 10%?) for catching issues without excessive runtime
   - Recommendation: 5% stratified sample as starting point, measure comparison runtime, adjust if needed

3. **Snapshot retention policy**
   - What we know: CONTEXT.md specifies "manual cleanup only" - keep until user explicitly drops
   - What's unclear: How many baseline snapshots to retain (all of them? last 3? last 30 days?)
   - Recommendation: Keep all snapshots indefinitely (disk space cheap), document naming convention for manual cleanup

4. **Comparison result storage format**
   - What we know: CONTEXT.md leans toward "log files only, not persistent table"
   - What's unclear: Should mismatch details be queryable later for investigation?
   - Recommendation: Write detailed log file + optional summary table for high-level metrics (pass/fail per table/column)

## Sources

### Primary (HIGH confidence)
- [NumPy allclose documentation](https://numpy.org/doc/stable/reference/generated/numpy.allclose.html) - Standard floating-point comparison API
- [PostgreSQL CREATE TABLE AS Statement](https://neon.com/postgresql/postgresql-tutorial/postgresql-create-table-as) - Official snapshot creation pattern
- [PEP 485 – math.isclose](https://peps.python.org/pep-0485/) - Python standard library floating-point comparison
- Existing codebase:
  - `sql/snapshots/create_cmc_ema_snapshots_20251124.sql` - Snapshot DDL pattern
  - `sql/checks/check_ema_multi_tf_snapshot_detailed_diff.sql` - Comparison query pattern
  - `src/ta_lab2/scripts/emas/run_all_ema_refreshes.py` - Phase 23 orchestration pattern
  - `src/ta_lab2/scripts/bars/common_snapshot_contract.py` - Validation infrastructure

### Secondary (MEDIUM confidence)
- [RegreSQL: Regression Testing for PostgreSQL Queries](https://boringsql.com/posts/regresql-testing-queries/) - 2026 tool for query regression testing
- [Time Series Cross-Validation Best Practices](https://otexts.com/fpp3/tscv.html) - Temporal ordering preservation
- [Pytest Approx for Numeric Testing](https://pytest-with-eric.com/pytest-advanced/pytest-approx/) - Testing framework comparison patterns
- [Audit Trail Best Practices](https://www.datasunrise.com/knowledge-center/data-audit-trails/) - Metadata capture strategies

### Tertiary (LOW confidence)
- [Database Testing Tools 2026](https://thectoclub.com/tools/best-database-testing-tools/) - General overview, not PostgreSQL-specific
- [Snapshot Testing in Data Science](https://martinahindura.medium.com/snapshot-testing-in-data-science-f2a9bac5b48a) - Conceptual overview, not implementation details

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All tools already in use in codebase, NumPy/pandas/PostgreSQL are industry standards
- Architecture: HIGH - Existing sql/snapshots/ and Phase 23 patterns provide proven templates
- Pitfalls: MEDIUM - Based on research + codebase review, not hands-on testing with this specific data

**Research date:** 2026-02-05
**Valid until:** 60 days (2026-04-06) - NumPy/PostgreSQL/pandas are stable, snapshot patterns unlikely to change
