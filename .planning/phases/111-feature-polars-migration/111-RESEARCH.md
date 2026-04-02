# Phase 111: Feature Polars Migration - Research

**Researched:** 2026-04-01
**Domain:** Polars migration of pandas feature computation (vol, TA indicators, cycle stats, rolling extremes, microstructure, CS norms, unified assembly, CTF)
**Confidence:** HIGH (all key findings verified against installed polars 1.36.1 and actual source files)

---

## Summary

Phase 111 migrates 8 feature sub-phases from pandas to polars. The codebase already uses polars for bar builders (`polars_bar_operations.py`) and EMA computation (`polars_ema_operations.py`, `polars_helpers.py`), providing proven patterns. Polars 1.36.1 is installed (declared `>=0.19.0`).

The migration is high-risk because downstream signals, IC scores, and backtests were calibrated against pandas-computed values. Verification testing confirms that most operations produce **numerically identical results** within 1e-12 relative tolerance, with a few **known divergence points** that require explicit fixes.

The CS norms sub-phase is already pure SQL (PostgreSQL window functions on `features`), making it essentially a no-op for migration. The cycle.py library already uses **numba JIT on numpy arrays** — the migration target there is the per-asset groupby loop, not the numerical kernel. Microstructure also calls numba and numpy kernels directly; polars adds value only in the outer iteration.

**Primary recommendation:** Use the pandas-to-polars-to-pandas boundary pattern (load pandas, convert to polars for computation, convert back to pandas for DB write). This preserves the existing `write_to_db` path (which uses `df.to_sql`) and avoids the need for ADBC/connectorx (neither is installed). Polars `over()` expressions replace per-asset `groupby()` loops, which is where the 2-5x speedup comes from.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| polars | 1.36.1 (installed), `>=0.19.0` declared | Vectorized computation replacing pandas groupby loops | Already used in bar builders and EMA scripts |
| pandas | (existing) | DB I/O boundary (load from SQL, write to DB) | `df.to_sql` write path preserved |
| numpy | (existing) | Numba kernel inputs (cycle, microstructure) | No change needed |
| numba | (existing) | cycle.py and microstructure.py kernels | Not migrated — already optimized |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pyarrow | `>=14.0.0` (installed) | polars Arrow backend for from_pandas/to_pandas | Implicit in all polars round-trips |
| sqlalchemy | (existing) | DB connection for load/write boundary | No change needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| to_pandas() for DB write | polars write_database + ADBC | ADBC not installed; `write_database` requires connectorx or adbc which are absent |
| polars over() | polars group_by() + join | over() is simpler for rolling window operations within groups |

**Installation:** No new packages needed. Polars is already installed.

---

## Architecture Patterns

### Recommended Project Structure

The migration adds polars implementations alongside existing pandas implementations, using `--use-polars` flags to switch paths:

```
src/ta_lab2/features/
    vol.py                      # Add _polars variants of vol functions
    indicators.py               # Add _polars variants of indicator functions
    cycle.py                    # Add _polars groupby wrapper (kernel unchanged)
    feature_utils.py            # Add _polars zscore variant
scripts/features/
    base_feature.py             # Add use_polars flag propagation
    vol_feature.py              # Add _compute_features_polars() method
    ta_feature.py               # Add _compute_features_polars() method
    cycle_stats_feature.py      # Add _compute_features_polars() method
    rolling_extremes_feature.py # Add _compute_features_polars() method
    microstructure_feature.py   # Add _compute_features_polars() method
    daily_features_view.py      # Add polars join variant
    refresh_ctf.py              # Add polars join_asof variant
    refresh_cs_norms.py         # No change needed (pure SQL)
```

### Pattern 1: Pandas-to-Polars-to-Pandas Boundary

**What:** Load pandas from DB, compute in polars using over(), return pandas for DB write.
**When to use:** All feature sub-phases. Preserves existing write_to_db path.

```python
# Source: verified against polars 1.36.1 + polars_bar_operations.py patterns

def _compute_features_polars(self, df_source: pd.DataFrame) -> pd.DataFrame:
    """Polars computation variant. Sorts, computes, returns pandas."""
    if df_source.empty:
        return pd.DataFrame()

    # 1. Ensure sorted before conversion (polars over() does NOT sort)
    df_sorted = df_source.sort_values(["id", "venue_id", "ts"]).reset_index(drop=True)

    # 2. Convert to polars
    pl_df = pl.from_pandas(df_sorted)

    # 3. Compute using over() for per-group rolling
    pl_result = pl_df.with_columns([
        pl.col("close")
            .log(base=math.e)
            .diff()
            .over(["id", "venue_id"])
            .alias("log_ret"),
        # Add more expressions ...
    ])

    # 4. Convert back to pandas for DB write
    return pl_result.to_pandas()
```

### Pattern 2: Polars over() Replacing pandas groupby Loop

**What:** Use polars `over()` to apply rolling/EWM operations per group in a single pass instead of Python-level groupby iteration.
**When to use:** Vol, TA indicators, rolling extremes, cycle stats outer loop.

```python
# Source: verified against polars_ema_operations.py + polars 1.36.1 tests

# OLD: pandas groupby loop (~60 min total)
for (id_val, venue_id_val), df_id in df.groupby(["id", "venue_id"]):
    df_id = df_id.sort_values("ts")
    add_parkinson_vol(df_id, ...)
    results.append(df_id)

# NEW: polars over() (single vectorized pass)
import math
coef = 1.0 / (4.0 * math.log(2.0))
pl_df = pl.from_pandas(df.sort_values(["id", "venue_id", "ts"]))
pl_result = pl_df.with_columns([
    (pl.lit(coef) *
     (pl.col("high").log(base=math.e) - pl.col("low").log(base=math.e))
     .pow(2)
     .rolling_mean(window, min_samples=window)
     .over(["id", "venue_id"])
    ).sqrt().alias(f"vol_parkinson_{window}")
    for window in [20, 63, 126]
])
```

### Pattern 3: ATR EWM with fill_nan(None)

**What:** Convert float NaN (from numpy max with NaN prev_close) to polars null before ewm_mean to match pandas ewm NaN-skipping behavior.
**When to use:** ATR computation in vol.py and ta_feature.py.

```python
# Source: empirically verified against polars 1.36.1 and pandas behavior
# CRITICAL: polars float NaN != polars null for ewm_mean ignore_nulls

import math

def add_atr_polars(df_pl: pl.DataFrame, period: int) -> pl.DataFrame:
    """ATR matching pandas ewm(alpha=1/period, adjust=False)."""
    prev_close = pl.col("close").shift(1).over(["id", "venue_id"])
    tr = pl.max_horizontal(
        (pl.col("high") - pl.col("low")).abs(),
        (pl.col("high") - prev_close).abs().fill_nan(None),
        (pl.col("low") - prev_close).abs().fill_nan(None),
    ).fill_nan(None)  # REQUIRED: convert float NaN to null for ewm
    return df_pl.with_columns([
        tr.ewm_mean(alpha=1/period, adjust=False, min_samples=1)
          .over(["id", "venue_id"])
          .alias(f"atr_{period}")
    ])
```

### Pattern 4: RSI in Polars

**What:** Polars RSI using diff, clip, ewm_mean. Numerically identical to pandas.
**When to use:** ta_feature.py RSI migration.

```python
# Source: verified exact numerical match against indicators.py + polars 1.36.1

def _compute_rsi_polars(df_pl: pl.DataFrame, period: int) -> pl.DataFrame:
    delta = pl.col("close").diff().over(["id", "venue_id"])
    gain = delta.clip(lower_bound=0.0)
    loss = (-delta).clip(lower_bound=0.0)
    avg_gain = gain.ewm_mean(alpha=1/period, adjust=False, min_samples=1).over(["id", "venue_id"])
    avg_loss = loss.ewm_mean(alpha=1/period, adjust=False, min_samples=1).over(["id", "venue_id"])
    rsi_val = 100.0 - (
        100.0 / (
            1.0 + avg_gain / pl.when(avg_loss == 0).then(None).otherwise(avg_loss)
        )
    )
    return df_pl.with_columns([rsi_val.alias(f"rsi_{period}")])
```

### Pattern 5: Timestamp Handling for polars Round-Trip

**What:** Strip UTC tz before polars, restore after. Follows `normalize_timestamps_for_polars` pattern from `polars_bar_operations.py`.
**When to use:** Any sub-phase that passes timestamps through polars.

```python
# Source: polars_bar_operations.py normalize_timestamps_for_polars

# Before polars:
df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(None)  # strip tz

# After polars to_pandas():
df["ts"] = pd.to_datetime(df["ts"], utc=True)  # restore UTC
```

### Anti-Patterns to Avoid

- **Not sorting before over()**: Polars `over()` does NOT sort within groups. Stateful operations (ATH, cummax, rolling) require `df.sort_values(["id", "venue_id", "ts"])` BEFORE `pl.from_pandas()`.
- **Using min_periods= keyword**: Renamed to `min_samples=` in polars 1.21+. Use `min_samples=window` to match pandas `min_periods=window` behavior.
- **Float NaN vs polars null in EWM**: When computing TR (max of 3 values where prev_close has NaN first row), must call `.fill_nan(None)` to convert float NaN to polars null before `ewm_mean`. Otherwise EWM starts from first non-null value silently.
- **Using polars write_database for Postgres**: ADBC and connectorx are not installed. Keep `df.to_sql` via pandas for DB writes.
- **Migrating numba kernels**: `cycle.py` (`_ath_cycle_kernel`, `_rolling_argmax_deque`) and `microstructure.py` functions are already compiled numba kernels on numpy arrays. Don't rewrite them in polars — the bottleneck is the Python-level groupby loop, not the kernel.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-group rolling operations | Python for loop over groupby | `pl.col().rolling_mean().over(["id", "venue_id"])` | O(N) vectorized vs O(G*N) Python overhead |
| Per-group EWM | Python for loop | `pl.col().ewm_mean(...).over(["id", "venue_id"])` | Same speedup as EMA batch builder |
| Timestamp tz management | Custom round-trip logic | `normalize_timestamps_for_polars` / `restore_utc_timezone` from `polars_bar_operations.py` | Already proven pattern in bar builders |
| Postgres write with polars | polars write_database | `df.to_pandas()` then existing `df.to_sql` path | ADBC not installed; write boundary is not the bottleneck |
| CS norms in polars | Translate UPDATE SQL to polars | Keep as pure SQL (already pure PostgreSQL window functions) | The computation runs in PostgreSQL, not Python |

**Key insight:** The speedup comes entirely from eliminating the Python-level per-asset groupby loop. The underlying math functions (numpy, numba) are already fast. Using `over()` applies the same computation vectorized across all groups in one polars pass.

---

## Common Pitfalls

### Pitfall 1: min_periods API Rename (polars 1.21+)

**What goes wrong:** `rolling_mean(w, min_periods=w)` raises a DeprecationWarning in polars 1.21+ and will eventually error. Currently produces a warning and still works in 1.36.1, but code should use the new API.
**Why it happens:** polars renamed `min_periods` to `min_samples` in version 1.21.0.
**How to avoid:** Always use `min_samples=w` not `min_periods=w`.
**Warning signs:** `DeprecationWarning: the argument 'min_periods' for 'Expr.rolling_mean' is deprecated. It was renamed to 'min_samples' in version 1.21.0.`

### Pitfall 2: over() Ordering Is Not Guaranteed

**What goes wrong:** Cumulative operations (ATH cummax, rolling extremes argmax) produce wrong results because polars `over()` does not sort rows within groups.
**Why it happens:** Polars `group_by().agg()` and `over()` make no ordering guarantees within groups.
**How to avoid:** Always sort by `["id", "venue_id", "ts"]` BEFORE converting to polars. Never rely on insertion order being preserved.
**Warning signs:** Cycle number counts don't match expected; ATH values are wrong; bars_since_ath jumps erratically.

### Pitfall 3: Float NaN vs Polars Null in EWM

**What goes wrong:** ATR first-row divergence. Pandas `ewm(alpha=1/14, adjust=False)` treats NaN as "missing, skip" and starts accumulating from the first non-NaN TR value. Polars `ewm_mean(alpha=1/14, adjust=False)` with a float NaN (not polars null) starts accumulating from row 0 using the NaN.
**Why it happens:** In polars, `float('nan')` and `None` are different types. `is_nan()` != `is_null()`. EWM ignores polars null but treats float NaN as a real (bad) value unless you convert first.
**How to avoid:** After computing TR via `pl.max_horizontal(...)`, chain `.fill_nan(None)` before `ewm_mean`.
**Warning signs:** ATR values differ from pandas starting at the second row. `atr_14` values ~2x expected magnitude.

### Pitfall 4: Polars Nulls Become 0 in Some Operations

**What goes wrong:** `pl.max_horizontal(a, b, c)` where `b` or `c` is null (from shift(1)) may propagate null or silently treat null as 0 depending on polars version.
**Why it happens:** `pl.max_horizontal` propagates null by default in polars 1.x.
**How to avoid:** After `pl.max_horizontal`, always chain `.fill_nan(None)` to standardize. Test with actual NaN/null data before deploying.
**Warning signs:** First-row ATR is 0.0 instead of null.

### Pitfall 5: Stochastic Bollinger Rolling with NaN Inputs

**What goes wrong:** If source price data has NaN values (from forward-fill not applied), polars `rolling_min` and `rolling_max` propagate null across the entire window containing any null. Pandas behaves identically. No divergence here, but both produce null for windows containing any NaN.
**Why it happens:** Both libraries apply the same `min_periods`/`min_samples` semantics — verified as identical.
**How to avoid:** Apply null_strategy (forward_fill or interpolate) before polars computation, same as pandas path.
**Warning signs:** Excessive nulls in TA output when source data had gaps.

### Pitfall 6: MACD Nested EWM Precision on Long Series

**What goes wrong:** After hundreds of EWM steps, polars and pandas may diverge by ~1e-14 due to different floating-point instruction ordering (Rust SIMD vs numpy). This is below IC regression threshold (1%) but above strict bit-for-bit equality.
**Why it happens:** IEEE 754 arithmetic is order-dependent; parallel SIMD instructions reorder adds.
**How to avoid:** Accept ~1e-12 relative tolerance as the regression threshold for floats, not exact equality.
**Warning signs:** Diff script reports small relative differences (1e-14 to 1e-12) in MACD/RSI on old series — this is acceptable.

### Pitfall 7: CTF join_asof Timezone Precision

**What goes wrong:** CTF uses pandas `merge_asof` which operates on `datetime64[ns, UTC]`. Polars `join_asof` operates on `Datetime(time_unit='ns', time_zone='UTC')` when converted from pandas ns datetimes. For **daily bars** (midnight UTC), ns vs us precision is irrelevant (midnight timestamps have zero sub-microsecond component). However, if intraday timestamps are involved, precision loss from pandas ns -> polars us conversion could cause off-by-one-microsecond join mismatches.
**Why it happens:** Polars default Datetime is microsecond; pandas default is nanosecond.
**How to avoid:** For daily bar timestamps (which are always midnight UTC), the precision difference is zero. Verify by confirming `bar_ts.value % 1000 == 0` for all timestamps before CTF migration.
**Warning signs:** CTF join produces unexpected nulls on timestamps that had valid matches in the pandas path.

---

## Code Examples

Verified patterns from official sources and empirical tests against polars 1.36.1:

### Full Parkinson Vol in Polars (verified exact match)

```python
# Source: tested against vol.py + polars 1.36.1 - produces exact same values
import math
import polars as pl

COEF = 1.0 / (4.0 * math.log(2.0))

def add_parkinson_vol_polars(
    pl_df: pl.DataFrame,
    windows: tuple[int, ...] = (20, 63, 126),
    periods_per_year: int = 252,
    group_cols: list[str] = ["id", "venue_id"],
) -> pl.DataFrame:
    """Parkinson vol in polars. Input must be sorted by group_cols + ts."""
    new_cols = []
    for w in windows:
        col = (
            (
                pl.lit(COEF) *
                (pl.col("high").log(base=math.e) - pl.col("low").log(base=math.e))
                .pow(2)
                .rolling_mean(w, min_samples=w)
                .over(group_cols)
            ).sqrt() * math.sqrt(periods_per_year)
        ).alias(f"vol_parkinson_{w}")
        new_cols.append(col)
    return pl_df.with_columns(new_cols)
```

### ATR with fill_nan(None) (verified exact match)

```python
# Source: tested against vol.py add_atr + polars 1.36.1
# fill_nan(None) is REQUIRED to match pandas ewm NaN-skipping semantics

def add_atr_polars(
    pl_df: pl.DataFrame,
    period: int = 14,
    group_cols: list[str] = ["id", "venue_id"],
) -> pl.DataFrame:
    """Wilder ATR. fill_nan(None) converts float NaN to polars null for EWM."""
    prev_close = pl.col("close").shift(1).over(group_cols)
    tr = pl.max_horizontal(
        (pl.col("high") - pl.col("low")).abs(),
        (pl.col("high") - prev_close).abs().fill_nan(None),
        (pl.col("low") - prev_close).abs().fill_nan(None),
    ).fill_nan(None)
    return pl_df.with_columns([
        tr.ewm_mean(alpha=1/period, adjust=False, min_samples=1)
          .over(group_cols)
          .alias(f"atr_{period}")
    ])
```

### RSI in Polars (verified exact numerical match to indicators.py)

```python
# Source: tested against indicators.py rsi() + polars 1.36.1

def compute_rsi_polars(
    pl_df: pl.DataFrame,
    period: int = 14,
    group_cols: list[str] = ["id", "venue_id"],
) -> pl.DataFrame:
    """RSI. Numerically identical to pandas indicators.py rsi() to 6 decimal places."""
    delta = pl.col("close").diff().over(group_cols)
    gain = delta.clip(lower_bound=0.0)
    loss = (-delta).clip(lower_bound=0.0)
    avg_gain = gain.ewm_mean(alpha=1/period, adjust=False, min_samples=1).over(group_cols)
    avg_loss = loss.ewm_mean(alpha=1/period, adjust=False, min_samples=1).over(group_cols)
    rsi_expr = (
        100.0 - 100.0 / (
            1.0 + avg_gain / pl.when(avg_loss == 0).then(None).otherwise(avg_loss)
        )
    )
    return pl_df.with_columns([rsi_expr.alias(f"rsi_{period}")])
```

### join_asof for CTF (polars equivalent of merge_asof)

```python
# Source: polars 1.36.1 join_asof API - verified syntax
# For daily bars, ns/us precision difference is zero (midnight timestamps)

# pandas pattern:
# pd.merge_asof(df_1d, df_7d, on="ts", by=["id"], direction="backward")

# polars equivalent:
df_1d_pl = pl.from_pandas(df_1d.sort_values(["id", "ts"]))
df_7d_pl = pl.from_pandas(df_7d.sort_values(["id", "ts"]))

result = df_1d_pl.join_asof(
    df_7d_pl,
    on="ts",
    by="id",
    strategy="backward",
)
```

### Snapshot Baseline CSV Pattern for Regression Testing

```python
# Source: per CONTEXT.md regression protocol

import pandas as pd
from pathlib import Path

def capture_feature_snapshot(engine, ids: list[int], tf: str, output_path: Path) -> None:
    """Capture full feature output for test assets as regression baseline."""
    with engine.connect() as conn:
        df = pd.read_sql(
            "SELECT * FROM public.features WHERE id = ANY(:ids) AND tf = :tf ORDER BY id, ts",
            conn,
            params={"ids": ids, "tf": tf}
        )
    df.to_csv(output_path, index=False)

def compare_feature_snapshots(
    baseline_path: Path,
    current_path: Path,
    float_rtol: float = 1e-10,
) -> dict:
    """
    Compare before/after snapshots.
    Returns dict with: row_count_match, null_positions_match, float_max_rel_diff
    """
    baseline = pd.read_csv(baseline_path)
    current = pd.read_csv(current_path)
    # ... comparison logic
```

---

## Sub-Phase Migration Complexity Analysis

Based on actual source code inspection:

| Sub-phase | Source Location | Key Pandas Operations | Polars Complexity | Kernel Status |
|-----------|-----------------|----------------------|-------------------|---------------|
| CS norms | `refresh_cs_norms.py` | Pure SQL UPDATE | **None** — already SQL | N/A |
| cycle_stats | `cycle_stats_feature.py` + `cycle.py` | `groupby` loop + numba kernel | **Low** — wrap kernel call with polars sort | numba preserved |
| rolling_extremes | `rolling_extremes_feature.py` + `cycle.py` | `groupby` loop + O(n) deque kernel | **Low** — same as cycle_stats | numba preserved |
| vol | `vol_feature.py` + `vol.py` | `rolling().mean()`, `.ewm()`, groupby | **Medium** — ATR needs `fill_nan(None)` fix | numpy |
| ta | `ta_feature.py` + `indicators.py` | `.ewm()`, `.rolling()`, `.diff()`, `.clip()` | **Medium-High** — 6 indicators, each needs polars variant | numpy |
| microstructure | `microstructure_feature.py` + `microstructure.py` | groupby loop, numpy kernels (FFD, entropy, ADF) | **Low** — outer loop only; kernels are numpy | numba + numpy |
| features (unified) | `daily_features_view.py` | SQL JOIN assembly, not computation | **Low** — SQL remains SQL | N/A |
| CTF | `refresh_ctf.py` + YAML config | `merge_asof`, groupby, per-indicator computation | **High** — `join_asof` + tz handling | numpy |

### CS Norms: Already Pure SQL

`refresh_cs_norms.py` runs 3 SQL UPDATE statements using PostgreSQL `PARTITION BY` window functions. **There is nothing to migrate.** The "sub-phase" in the migration order list is misleading — CS norms runs entirely in PostgreSQL. Include it in the migration as "verified no migration needed."

### Microstructure: Only Outer Loop

`microstructure_feature.py` loops over `df.groupby(["id", "venue_id"])` and calls:
- `find_min_d(close)` — numpy/scipy
- `frac_diff_ffd(log_close, d=d_opt)` — numpy
- `kyle_lambda / amihud_lambda / hasbrouck_lambda` — numpy rolling
- `rolling_adf` — statsmodels via numpy
- `rolling_entropy` — pure numpy

None of these accept polars DataFrames. The polars value here is eliminating the Python `groupby` for-loop overhead, not the computation itself. The pattern: polars groups and batches IDs efficiently, then calls numpy kernels per group.

---

## DB Write Patterns

The `base_feature.py` write pattern:
1. Scoped DELETE: `DELETE FROM {table} WHERE id = ANY(:ids) AND tf = :tf AND alignment_source = :as_ AND venue_id = ANY(:venue_ids)`
2. Insert: `df.to_sql(table, engine, schema=schema, if_exists="append", index=False, method="multi", chunksize=10000)`

**Polars does not change the write path.** The polars computation produces a pandas DataFrame via `.to_pandas()`, which flows into the existing `write_to_db` method unchanged. Polars `write_database` is NOT used (requires connectorx or ADBC, neither installed).

**Key: `.to_pandas()` preserves UTC timezone.** Verified: polars `Datetime(time_unit='us', time_zone='UTC')` converts to pandas `datetime64[us, UTC]` correctly.

---

## Test Harness

### Existing Test Infrastructure
- `tests/features/test_vol_feature.py` — unit tests with mocked engine
- `tests/features/test_ta_feature.py` — unit tests with mocked engine
- `tests/features/test_base_feature.py` — template method tests
- `tests/test_polars_bar_operations.py` — polars unit test pattern (no DB)
- `src/ta_lab2/analysis/ic.py` — IC/IC-IR computation (`batch_compute_ic`, `compute_rolling_ic`)

### Regression Test Pattern

For each sub-phase migration, the test protocol from CONTEXT.md requires:

1. **Baseline CSV**: Run pandas path for test assets (id=1, 1027, 5426), all TFs, save to `.planning/phases/111-feature-polars-migration/baselines/`
2. **Polars CSV**: Run polars path for same test assets, same TFs
3. **Diff assertions**:
   - Row counts match exactly
   - Null/NaN positions match exactly
   - Float columns within 1e-10 relative tolerance
   - Integer and boolean columns match exactly
4. **IC-IR regression**: Use `batch_compute_ic()` from `ic.py` against saved IC results
5. **Signal regression**: Compare signal counts and directions per `signals_rsi/ema/atr` tables
6. **Backtest regression**: Run `BakeoffOrchestrator` on test assets; Sharpe within 5%

No new test framework needed. pytest with synthetic DataFrames (no DB) covers the computation tests. Regression tests against live DB are integration tests run manually.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pandas groupby loops for vol | polars over() | This phase | 2-5x speedup |
| pandas ewm for ATR/RSI | polars ewm_mean with fill_nan fix | This phase | Identical numerics, faster |
| pandas merge_asof for CTF | polars join_asof | This phase | Faster, but tz handling needed |
| `min_periods=` in polars | `min_samples=` | polars 1.21 | Breaking rename (DeprecationWarning) |

**Deprecated/outdated:**
- `min_periods=` keyword: Use `min_samples=` for all polars rolling operations in version 1.21+
- polars `polars_helpers.py` `fast_merge()` / `fast_groupby_agg()`: These exist but use `pl.from_pandas` round-trips per-call. The direct `over()` pattern is better for feature computation.

---

## Open Questions

1. **Microstructure polars value-add**
   - What we know: The outer groupby loop calls numpy/numba kernels. Polars `over()` doesn't help when the kernel itself accepts a numpy array.
   - What's unclear: Whether replacing the Python `groupby` loop with polars `group_by().map_groups()` (which still calls Python per group) actually improves performance.
   - Recommendation: Profile microstructure specifically before and after. May be minimal gain — keep as low priority.

2. **CTF indicator computation**
   - What we know: CTF computes slopes, divergence, agreement via per-indicator groupby on the YAML config. `refresh_ctf.py` is the most complex file.
   - What's unclear: Whether the join_asof can handle all CTF reference-TF pairs (multiple ref TFs per base TF).
   - Recommendation: Keep CTF as last migration and profile first. The join_asof fix is straightforward; the indicator computation loop needs careful inspection.

3. **--use-polars flag propagation**
   - What we know: No `--use-polars` flag exists anywhere yet. All sub-phases have pure pandas implementations.
   - What's unclear: Whether the flag should live on CLI args only, or also be a `FeatureConfig` field.
   - Recommendation: Add `use_polars: bool = False` to `FeatureConfig` and thread through all sub-phase constructors. Default False until regression tests pass. Then flip to True and keep pandas path as `--use-pandas` fallback.

---

## Sources

### Primary (HIGH confidence)
- Polars 1.36.1 installed (`python -c "import polars; print(polars.__version__)"`) — all API signatures and behaviors verified empirically
- Source code inspection: `vol.py`, `indicators.py`, `cycle.py`, `microstructure.py`, `feature_utils.py`, `base_feature.py`, `vol_feature.py`, `ta_feature.py`, `cycle_stats_feature.py`, `rolling_extremes_feature.py`, `microstructure_feature.py`, `refresh_cs_norms.py`, `refresh_ctf.py`, `daily_features_view.py`
- Existing patterns: `polars_bar_operations.py`, `polars_ema_operations.py`, `polars_helpers.py`

### Secondary (MEDIUM confidence)
- polars changelog for 1.21+ (min_periods -> min_samples rename) — verified via DeprecationWarning in local tests
- `tests/test_polars_bar_operations.py` and `tests/features/test_vol_feature.py` — test patterns observed

### Tertiary (LOW confidence)
- Performance estimate "2-5x faster" — based on phase description and polars documentation claims; actual speedup will depend on asset count and TF count

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — polars 1.36.1 installed, exact versions verified
- Architecture: HIGH — all source files inspected, write patterns confirmed no ADBC needed
- API compatibility: HIGH — all key operations empirically tested (ATR fill_nan, RSI, Parkinson vol, MACD, rolling min/max, over() sort order)
- Pitfalls: HIGH — all pitfalls verified against actual polars 1.36.1 behavior
- Performance estimate: LOW — "2-5x" is claimed but not profiled against actual data volumes

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (polars is fast-moving; verify API against 1.36.1 specifically)
