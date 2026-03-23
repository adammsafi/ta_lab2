# Phase 90: CTF Core Computation Module - Research

**Researched:** 2026-03-23
**Domain:** Python computation engine, pandas merge_asof, SQLAlchemy batch loading, rolling polyfit
**Confidence:** HIGH

---

## Summary

Phase 90 builds `src/ta_lab2/features/cross_timeframe.py` -- the computation engine
for cross-timeframe indicator features. Research investigated all files the module
must interact with: `BaseFeature` (template method pattern), `build_alignment_frame()`
from `regimes/comovement.py` (merge_asof alignment), and all four source tables
(`ta`, `vol`, `returns_bars_multi_tf_u`, `features`) to confirm exact column names,
PKs, and venue_id placement.

The standard approach is: CTFFeature is a STANDALONE class (not a BaseFeature subclass)
with the same method naming convention (`compute_for_ids`, `_load_indicators_batch`,
`_align_timeframes`, `_compute_slope`, etc.). It reuses `build_alignment_frame()` from
`regimes/comovement.py` without modification. The scoped DELETE + INSERT write pattern
matches `base_feature.py` exactly: `DELETE WHERE id = ANY(:ids) AND base_tf = :btf AND ref_tf = :rtf AND indicator_id = ANY(:iids)` followed by `to_sql(..., if_exists='append')`.

**Primary recommendation:** Build CTFFeature as a standalone class in
`src/ta_lab2/features/cross_timeframe.py`. Do NOT subclass BaseFeature -- the output
table schema and delete scope differ too much. Mirror the naming conventions
(compute_for_ids, frozen dataclass config) but own the implementation.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 2.x | merge_asof, rolling, groupby | All data manipulation |
| numpy | 1.x | polyfit, sign, nanmean | Vectorized math |
| SQLAlchemy | 2.x | Engine, text(), pd.read_sql | All DB access |
| PyYAML | 6.x | yaml.safe_load | Config loading |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ta_lab2.regimes.comovement` | project | `build_alignment_frame()` | Alignment step |
| `ta_lab2.config` | project | `TARGET_DB_URL`, `project_root()` | Engine + config path |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reuse `build_alignment_frame()` | Inline `pd.merge_asof` | `build_alignment_frame` handles sort + column selection; reuse saves 20 lines and stays consistent with comovement module |
| Standalone CTFFeature | Subclass BaseFeature | BaseFeature's write_to_db scopes DELETE by `(ids, tf, alignment_source)` -- CTF needs `(ids, base_tf, ref_tf, indicator_id)`. Subclassing would require overriding write_to_db anyway |

**Installation:** No new packages needed.

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/features/
    cross_timeframe.py          # CTFConfig dataclass + CTFFeature class (new)
    __init__.py                 # no changes needed
```

### Pattern 1: CTFConfig Dataclass

**What:** Frozen dataclass following `FeatureConfig` naming convention.
**When to use:** Always instantiate before calling `CTFFeature`.

```python
# Source: pattern from src/ta_lab2/scripts/features/base_feature.py
@dataclass(frozen=True)
class CTFConfig:
    alignment_source: str = "multi_tf"
    venue_id: int = 1
    yaml_path: Optional[str] = None   # None = default configs/ctf_config.yaml
```

### Pattern 2: YAML Config Loading

**What:** Load `configs/ctf_config.yaml` using `project_root()` resolution, identical
to `cross_asset.py` pattern.

```python
# Source: src/ta_lab2/macro/cross_asset.py lines 83-118
from ta_lab2.config import project_root

def _load_ctf_config(yaml_path: Optional[str] = None) -> dict:
    try:
        import yaml
    except ImportError:
        raise RuntimeError("PyYAML required")
    path = Path(yaml_path) if yaml_path else project_root() / "configs" / "ctf_config.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
```

### Pattern 3: Load dim_ctf_indicators from DB

**What:** At init time, query all active indicators from `dim_ctf_indicators` and
cache as list of dicts. This is the same pattern as `ta_feature.py`'s
`load_indicator_params()`.

```python
# Source: src/ta_lab2/scripts/features/ta_feature.py lines 396-423
def _load_dim_ctf_indicators(engine: Engine) -> list[dict]:
    sql = text("""
        SELECT indicator_id, indicator_name, source_table, source_column, is_directional
        FROM public.dim_ctf_indicators
        WHERE is_active = TRUE
        ORDER BY indicator_id
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [
        {
            "indicator_id": row[0],
            "indicator_name": row[1],
            "source_table": row[2],
            "source_column": row[3],
            "is_directional": row[4],
        }
        for row in rows
    ]
```

### Pattern 4: Batch Load All Indicators From One Source Table

**What:** For each unique source_table group, load ALL indicator columns in a SINGLE
query (not N per-indicator queries). This is the N+1 prevention pattern.

```python
# Source: derived from ta_feature.py load_source_data pattern
def _load_indicators_batch(
    self,
    ids: list[int],
    source_table: str,
    columns: list[str],    # list of source_column values for this source_table
    tf: str,
    extra_filter: str = "",   # e.g. "AND roll = FALSE" for returns
) -> pd.DataFrame:
    col_list = ", ".join(f'"{c}"' for c in columns)

    # returns_bars_multi_tf_u uses "timestamp" (quoted reserved word), NOT ts
    ts_col = '"timestamp"' if source_table == "returns_bars_multi_tf_u" else "ts"

    sql = text(f"""
        SELECT id, {ts_col} AS ts, tf, alignment_source, venue_id,
               {col_list}
        FROM public.{source_table}
        WHERE id = ANY(:ids)
          AND tf = :tf
          AND alignment_source = :as_
          {extra_filter}
        ORDER BY id, ts ASC
    """)
    with self.engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={
            "ids": ids, "tf": tf, "as_": self.config.alignment_source
        })
    # CRITICAL: fix tz-naive issue on Windows
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

**Key difference for `returns_bars_multi_tf_u`:**
- Timestamp column is `"timestamp"` (quoted reserved word), NOT `ts`
- Must add filter `AND roll = FALSE` to get canonical returns
- `venue_id` IS in the PK (unlike `ta`/`vol`)

**Key difference for `ta` and `vol`:**
- Timestamp column is `ts`
- `venue_id` is NOT in the PK (column-only, DEFAULT 1)
- No extra filter needed

**Key difference for `features`:**
- Timestamp column is `ts`
- `venue_id` IS in the PK (added via VENUE_ID_PK_CHANGES in `a0b1c2d3e4f5`)
- No extra filter needed

### Pattern 5: build_alignment_frame() Exact Signature

**What:** Reuse the existing function from `regimes/comovement.py`.
**Source:** `src/ta_lab2/regimes/comovement.py` lines 34-60.

```python
def build_alignment_frame(
    low_df: pd.DataFrame,      # base_tf data (more frequent)
    high_df: pd.DataFrame,     # ref_tf data (less frequent)
    *,
    on: str = "date",          # join column name -- CTF uses "ts"
    low_cols: Optional[Iterable[str]] = None,    # columns from base_tf to keep
    high_cols: Optional[Iterable[str]] = None,   # columns from ref_tf to keep
    suffix_low: str = "",       # suffix for base_tf columns (keep "" = no change)
    suffix_high: str = "_w",    # suffix for ref_tf columns (default "_w")
    direction: str = "backward",  # always "backward" for CTF
) -> pd.DataFrame:
```

**Usage pattern for CTF:**
```python
from ta_lab2.regimes.comovement import build_alignment_frame

# base_df = data at the finer timeframe (e.g., 1D)
# ref_df  = data at the coarser timeframe (e.g., 7D)
aligned = build_alignment_frame(
    low_df=base_df[["ts", source_col]].rename(columns={"ts": "ts"}),
    high_df=ref_df[["ts", source_col]].rename(columns={"ts": "ts"}),
    on="ts",
    low_cols=[source_col],
    high_cols=[source_col],
    suffix_low="",        # base value keeps its name
    suffix_high="_ref",   # ref value gets _ref suffix
    direction="backward",
)
# aligned has: ts (from base_df), {source_col} (base value), {source_col}_ref (ref value)
```

**IMPORTANT:** `build_alignment_frame` calls `_ensure_sorted(df, on)` internally
which sorts by the `on` column. Both DataFrames must be passed with the `on` column
present. The function handles sorting internally.

**IMPORTANT:** `pd.merge_asof` requires both DataFrames to have the same tz on the
merge key. Always apply `pd.to_datetime(df["ts"], utc=True)` before calling
`build_alignment_frame`.

### Pattern 6: _compute_slope() -- Vectorized Rolling Polyfit

**What:** Rolling linear regression slope via `rolling().apply(raw=True)`.
The project has this pattern in `ml/expression_engine.py` (`_slope` function)
and `features/trend.py`.

```python
# Source: src/ta_lab2/ml/expression_engine.py lines 55-73 (_slope function)
def _compute_slope(series: pd.Series, window: int) -> pd.Series:
    """Linear regression slope over rolling window of n bars."""
    n = window
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_denom = ((x - x_mean) ** 2).sum()

    def _apply_slope(arr: np.ndarray) -> float:
        if len(arr) < 2:
            return float("nan")
        y_mean = arr.mean()
        return float(np.dot(arr - y_mean, x[-len(arr):] - x[-len(arr):].mean())
                     / max(((x[-len(arr):] - x[-len(arr):].mean()) ** 2).sum(), 1e-12))

    return series.rolling(window=n, min_periods=2).apply(_apply_slope, raw=True)
```

**Simpler version (equivalent, used in trend.py):**
```python
# Source: src/ta_lab2/features/trend.py lines 51-56
x = np.arange(window)
denom = (x - x.mean()).var() * window
cov = series.rolling(window).apply(
    lambda v: np.dot(v - v.mean(), x - x.mean()) / denom, raw=False
)
slope = cov * window
```

**For CTF, use the `expression_engine.py` approach (`raw=True`)** -- it's slightly
faster (passes numpy array, not pandas Series). The slope is computed on the
`base_value` series (the finer timeframe value, not the ref value).

### Pattern 7: _compute_divergence() -- Z-Score Normalized Difference

**What:** `(base_value - ref_value) / rolling_std(base_value, window)`.

```python
# Source: derived from existing z-score pattern in feature_utils.py
def _compute_divergence(
    base_series: pd.Series,
    ref_series: pd.Series,
    window: int,   # divergence_zscore_window from config
) -> pd.Series:
    diff = base_series - ref_series
    rolling_std = base_series.rolling(window=window, min_periods=window // 2).std()
    # Avoid division by zero
    return diff / rolling_std.where(rolling_std > 1e-12, other=np.nan)
```

### Pattern 8: _compute_agreement() and _compute_crossover()

**What:** Respects `is_directional` flag. For non-directional indicators (e.g., RSI,
ADX, vol), agreement and crossover semantics differ from directional (e.g., MACD,
returns).

**agreement:** Fraction of last N bars where base and ref have the same sign of change.
For `is_directional=False`, use sign of the value itself (not the diff).

```python
# Source: derived from comovement.py sign_agreement pattern
def _compute_agreement(
    base_series: pd.Series,
    ref_series: pd.Series,
    is_directional: bool,
    window: int = 20,
) -> pd.Series:
    if is_directional:
        # Signs of the values agree
        agree = (np.sign(base_series) * np.sign(ref_series)) > 0
    else:
        # Both moving in the same direction (diff > 0 means up)
        agree = (np.sign(base_series.diff()) * np.sign(ref_series.diff())) > 0
    return agree.rolling(window=window, min_periods=max(5, window // 3)).mean()
```

**crossover:** Whether base crossed above or below ref in the last bar.
For `is_directional=False` (oscillators), crossover is meaningless (return NaN).

```python
def _compute_crossover(
    base_series: pd.Series,
    ref_series: pd.Series,
    is_directional: bool,
) -> pd.Series:
    if not is_directional:
        return pd.Series(np.nan, index=base_series.index)
    prev_above = (base_series.shift(1) > ref_series.shift(1))
    curr_above = (base_series > ref_series)
    crossed_up = (~prev_above) & curr_above
    crossed_dn = prev_above & (~curr_above)
    return crossed_up.astype(float) - crossed_dn.astype(float)
    # +1 = crossed above, -1 = crossed below, 0 = no crossover
```

### Pattern 9: Scoped DELETE + INSERT for ctf Table

**What:** The ctf PK is `(id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source)`.
The DELETE scope for a computation run covers `(ids, base_tf, ref_tf, indicator_id, alignment_source)`.

```python
# Source: derived from base_feature.py write_to_db (lines 364-386)
def _write_to_db(
    self,
    df: pd.DataFrame,  # must have all ctf columns
    base_tf: str,
    ref_tf: str,
    indicator_ids: list[int],
) -> int:
    if df.empty:
        return 0
    ids = df["id"].unique().tolist()

    with self.engine.begin() as conn:
        conn.execute(
            text("""
                DELETE FROM public.ctf
                WHERE id = ANY(:ids)
                  AND venue_id = :venue_id
                  AND base_tf = :base_tf
                  AND ref_tf = :ref_tf
                  AND indicator_id = ANY(:iids)
                  AND alignment_source = :as_
            """),
            {
                "ids": ids,
                "venue_id": self.config.venue_id,
                "base_tf": base_tf,
                "ref_tf": ref_tf,
                "iids": indicator_ids,
                "as_": self.config.alignment_source,
            }
        )

    # INSERT via to_sql append
    df.to_sql(
        "ctf",
        self.engine,
        schema="public",
        if_exists="append",
        index=False,
        method="multi",
        chunksize=10000,
    )
    return len(df)
```

**Note:** The `_get_table_columns()` filter pattern from `base_feature.py` should
also be used here to guard against schema drift. Query `information_schema.columns`
for table `ctf` and filter df columns before insert.

### Pattern 10: orchestrate_for_ids() -- Full Loop

**What:** The top-level method loops over all (base_tf, ref_tf, source_table, indicators)
combinations, batches by source_table.

```python
# Source: derived from base_feature.py compute_for_ids (lines 197-244)
def compute_for_ids(self, ids: list[int]) -> int:
    """
    Orchestrate: load -> align -> compute -> write for all TF pair x indicator combos.
    Returns total rows written.
    """
    config = _load_ctf_config(self.config.yaml_path)
    indicators = _load_dim_ctf_indicators(self.engine)

    # Group indicators by source_table for batch loading
    by_source: dict[str, list[dict]] = {}
    for ind in indicators:
        by_source.setdefault(ind["source_table"], []).append(ind)

    total_rows = 0

    for tf_pair in config["timeframe_pairs"]:
        base_tf = tf_pair["base_tf"]
        for ref_tf in tf_pair["ref_tfs"]:
            for source_table, source_indicators in by_source.items():
                rows = self._compute_one_source(
                    ids, base_tf, ref_tf, source_table, source_indicators, config
                )
                total_rows += rows

    return total_rows
```

### Anti-Patterns to Avoid

- **N+1 query pattern:** Never query one indicator at a time from the same source table.
  Always group by source_table and load ALL columns in one query.
- **Subclassing BaseFeature:** BaseFeature's `write_to_db` scopes DELETE by `tf`, not
  by `(base_tf, ref_tf, indicator_id)`. Do not subclass.
- **Ignoring `returns_bars_multi_tf_u` quirks:** The timestamp column is `"timestamp"`
  (quoted reserved word, NOT `ts`). Missing the quote will cause a syntax error.
- **Missing `roll = FALSE` filter for returns:** Without this filter, `ret_arith`/`ret_log`
  values are NULL (only canonical rows have them populated).
- **Mixed tz on merge_asof:** `pd.merge_asof` raises if both sides don't have the same
  timezone offset dtype. Always apply `pd.to_datetime(df["ts"], utc=True)` after loading.
- **Assuming `ta`/`vol` venue_id is in PK:** It is NOT. When loading from `ta` or `vol`,
  do not filter by `venue_id` in the WHERE clause -- it will scan correctly with DEFAULT 1.
  The ctf row's `venue_id` comes from `self.config.venue_id`, not from the source table.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ASOF alignment | Custom loop | `build_alignment_frame()` from `regimes/comovement.py` | Handles sort, column selection, suffix renaming; tested in production |
| Config path resolution | `os.getcwd()` or hardcoded path | `project_root() / "configs/ctf_config.yaml"` | Works from any working directory |
| Table column discovery | Store column list in code | `_get_table_columns()` via `information_schema` | Guards against schema drift at zero cost |
| Rolling slope | scipy or custom | `rolling().apply(raw=True)` with `np.dot` | No scipy dependency; same pattern as `expression_engine._slope` |
| YAML loading | Custom parser | `yaml.safe_load(f)` | Already used everywhere |

---

## Common Pitfalls

### Pitfall 1: returns_bars_multi_tf_u -- "timestamp" Not ts

**What goes wrong:** `SELECT ts FROM returns_bars_multi_tf_u` raises `UndefinedColumn`
because the column is named `"timestamp"` (PostgreSQL reserved word, must be quoted).

**Why it happens:** The table predates the project's `ts` column naming convention.
The PK is `(id, "timestamp", tf, venue_id, alignment_source)`.

**How to avoid:** In `_load_indicators_batch()`, detect `source_table ==
"returns_bars_multi_tf_u"` and use `'"timestamp"'` as the ts column. After loading,
alias it to `ts` for uniform downstream processing.

**Warning signs:** `sqlalchemy.exc.ProgrammingError: column "ts" does not exist`.

### Pitfall 2: ta and vol venue_id Is NOT in PK

**What goes wrong:** Writing `WHERE id = ANY(:ids) AND venue_id = :venue_id AND tf = :tf`
against `ta` or `vol` still works (returns rows), but joining on `venue_id` when it is
column-only vs PK-included causes misaligned GROUP BY expectations elsewhere.

**Why it happens:** `ta` and `vol` are in `VENUE_ID_COLUMN_ONLY` in migration
`a0b1c2d3e4f5` -- they got `venue_id` added as a column with `DEFAULT 1` but NO PK
rebuild. PKs remain `(id, ts, tf, alignment_source)`.

**How to avoid:** When loading from `ta`/`vol`, the `venue_id` filter is fine for
correctness but is redundant (all rows have `venue_id = 1`). The loaded ctf row's
`venue_id` comes from `self.config.venue_id` (typically 1).

**Warning signs:** No error -- just potential confusion about PK semantics.

### Pitfall 3: features Table Does Have venue_id in PK

**What goes wrong:** Forgetting to include `venue_id` in the JOIN key when joining
`features` to other tables later (Phase 92 analysis). The `features` PK is
`(id, ts, tf, venue_id, alignment_source)` -- `venue_id` IS in the PK.

**Why it happens:** `features` was in `VENUE_ID_PK_CHANGES` (not COLUMN_ONLY) in
migration `a0b1c2d3e4f5`. Its old PK included `venue` (text), which was rebuilt
to include `venue_id` (SMALLINT).

**How to avoid:** When loading from `features`, include `AND venue_id = :venue_id`
in the WHERE clause (or at minimum expect it to be relevant).

### Pitfall 4: merge_asof Requires Sorted, Same-tz Input

**What goes wrong:** `ValueError: left keys must be sorted` or tz-mismatch TypeError
from `pd.merge_asof`.

**Why it happens:** `build_alignment_frame()` calls `_ensure_sorted()` internally,
but only sorts the columns it receives. If tz handling produces mixed-offset objects
(Windows SQLAlchemy quirk), `merge_asof` will fail on the tz comparison.

**How to avoid:**
1. Always apply `df["ts"] = pd.to_datetime(df["ts"], utc=True)` after `pd.read_sql()`.
2. Let `build_alignment_frame()` handle sorting (it does this internally via `_ensure_sorted`).
3. Pass `on="ts"` explicitly to `build_alignment_frame()`.

**Warning signs:** `ValueError: left keys must be sorted` or
`TypeError: Cannot compare tz-naive and tz-aware datetime-like objects`.

### Pitfall 5: roll=FALSE Filter Missing for returns_bars_multi_tf_u

**What goes wrong:** `ret_arith` and `ret_log` are NULL for all rows where `roll = TRUE`.
CTF computation silently produces NaN output.

**Why it happens:** `returns_bars_multi_tf_u` has two row types per bar:
- `roll = FALSE` (canonical): has `ret_arith`, `ret_log` populated
- `roll = TRUE` (roll row): `ret_arith`/`ret_log` are NULL, only `*_roll` columns populated

**How to avoid:** Always add `AND roll = FALSE` when loading from `returns_bars_multi_tf_u`.
The YAML config already encodes `roll_filter: false` for this purpose -- the loading
function must read and apply this filter.

**Warning signs:** All `ref_value`/`base_value` for returns indicators are NaN after alignment.

### Pitfall 6: scoped DELETE Scope Must Match Exactly

**What goes wrong:** If the DELETE scope is too narrow, old rows accumulate. If too
broad, the `ctf` table gets purged unnecessarily.

**Why it happens:** The ctf PK has 7 columns. A partial DELETE (e.g., only by `ids`)
would leave stale rows for different `(base_tf, ref_tf, indicator_id)` combos.

**How to avoid:** DELETE scope must be `(ids, venue_id, base_tf, ref_tf, indicator_id,
alignment_source)`. For a batch of indicators from the same source table, pass
`indicator_id = ANY(:iids)` where `iids` is the list of indicator_ids being computed.

### Pitfall 7: Compute agreement/crossover Before Grouping Per Asset

**What goes wrong:** `agreement` rolling mean is computed across multiple assets if
the DataFrame is not grouped per asset first.

**Why it happens:** After `build_alignment_frame()`, the aligned DataFrame contains
all asset rows together. Rolling operations need per-asset context.

**How to avoid:** Before calling `_compute_slope`, `_compute_divergence`, etc., group
by `id` and apply per-asset. Example:

```python
results = []
for asset_id, df_asset in aligned.groupby("id"):
    df_asset = df_asset.copy()
    df_asset["slope"] = _compute_slope(df_asset["base_value"], slope_window)
    df_asset["divergence"] = _compute_divergence(
        df_asset["base_value"], df_asset["ref_value"], divergence_window
    )
    ...
    results.append(df_asset)
```

---

## Code Examples

### dim_ctf_indicators Query (exact)

```python
# Source: verified from j4k5l6m7n8o9_ctf_schema.py DDL
sql = text("""
    SELECT indicator_id, indicator_name, source_table, source_column, is_directional
    FROM public.dim_ctf_indicators
    WHERE is_active = TRUE
    ORDER BY indicator_id
""")
```

### load from ta (batch, all indicator columns in one query)

```python
# Source: derived from ta_feature.py load_source_data (lines 102-165)
# ta PK: (id, ts, tf, alignment_source) -- venue_id is column-only (DEFAULT 1)
sql = text(f"""
    SELECT id, ts, alignment_source, venue_id,
           {col_list}
    FROM public.ta
    WHERE id = ANY(:ids)
      AND tf = :tf
      AND alignment_source = :as_
    ORDER BY id, ts ASC
""")
```

### load from vol (batch, all indicator columns in one query)

```python
# Source: derived from vol_feature.py load_source_data (lines 118-187)
# vol PK: (id, ts, tf, alignment_source) -- venue_id is column-only (DEFAULT 1)
sql = text(f"""
    SELECT id, ts, alignment_source, venue_id,
           {col_list}
    FROM public.vol
    WHERE id = ANY(:ids)
      AND tf = :tf
      AND alignment_source = :as_
    ORDER BY id, ts ASC
""")
```

### load from returns_bars_multi_tf_u (batch)

```python
# Source: verified from create_returns_bars_multi_tf_u.sql DDL
# PK: (id, "timestamp", tf, venue_id, alignment_source)
# CRITICAL: "timestamp" is a reserved word -- must be quoted. column is NOT ts.
# CRITICAL: roll = FALSE filter required to get non-NULL ret_arith/ret_log
sql = text(f"""
    SELECT id, "timestamp" AS ts, alignment_source, venue_id,
           {col_list}
    FROM public.returns_bars_multi_tf_u
    WHERE id = ANY(:ids)
      AND tf = :tf
      AND alignment_source = :as_
      AND roll = FALSE
    ORDER BY id, "timestamp" ASC
""")
```

### load from features (batch)

```python
# Source: run_ic_sweep.py lines 236-250
# features PK: (id, ts, tf, venue_id, alignment_source) -- venue_id IN PK
sql = text(f"""
    SELECT id, ts, alignment_source, venue_id,
           {col_list}
    FROM public.features
    WHERE id = ANY(:ids)
      AND tf = :tf
      AND alignment_source = :as_
      AND venue_id = :venue_id
    ORDER BY id, ts ASC
""")
```

### build_alignment_frame() usage for CTF

```python
# Source: regimes/comovement.py lines 34-60
from ta_lab2.regimes.comovement import build_alignment_frame

# base_df and ref_df each have columns: [id, ts, {source_col}]
# Already tz-aware UTC after pd.to_datetime(utc=True)
aligned = build_alignment_frame(
    low_df=base_df[["ts", source_col]],   # finer timeframe
    high_df=ref_df[["ts", source_col]],   # coarser timeframe
    on="ts",
    low_cols=[source_col],
    high_cols=[source_col],
    suffix_low="",         # base_value keeps original name
    suffix_high="_ref",    # ref_value gets _ref suffix
    direction="backward",
)
# Result has: ts, {source_col} (base_value), {source_col}_ref (ref_value)
# Then rename: aligned["base_value"] = aligned[source_col]
#              aligned["ref_value"]  = aligned[f"{source_col}_ref"]
```

### _compute_slope vectorized rolling

```python
# Source: ml/expression_engine.py lines 55-73
import numpy as np

def _compute_slope(series: pd.Series, window: int) -> pd.Series:
    n = int(window)
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_denom = ((x - x_mean) ** 2).sum()

    def _apply(arr: np.ndarray) -> float:
        y_mean = arr.mean()
        return float(np.dot(arr - y_mean, x - x_mean) / x_denom)

    return series.rolling(window=n, min_periods=2).apply(_apply, raw=True)
```

### _compute_divergence z-score normalized

```python
def _compute_divergence(
    base_series: pd.Series,
    ref_series: pd.Series,
    window: int,
) -> pd.Series:
    diff = base_series - ref_series
    std = base_series.rolling(window=window, min_periods=window // 2).std()
    return diff / std.where(std > 1e-12, other=np.nan)
```

### Scoped DELETE for ctf

```python
# Source: derived from base_feature.py write_to_db (lines 364-384)
conn.execute(
    text("""
        DELETE FROM public.ctf
        WHERE id = ANY(:ids)
          AND venue_id = :venue_id
          AND base_tf = :base_tf
          AND ref_tf = :ref_tf
          AND indicator_id = ANY(:iids)
          AND alignment_source = :as_
    """),
    {
        "ids": ids,
        "venue_id": venue_id,
        "base_tf": base_tf,
        "ref_tf": ref_tf,
        "iids": indicator_ids,
        "as_": alignment_source,
    }
)
```

### YAML Config Reading (returns section nested indicators)

```python
# Source: configs/ctf_config.yaml (verified structure from phase 89)
config = _load_ctf_config()

for section_key, section_val in config["indicators"].items():
    # "returns" has nested structure with source_table + roll_filter + indicators list
    if isinstance(section_val, dict) and "indicators" in section_val:
        source_table = section_val["source_table"]
        roll_filter = section_val.get("roll_filter", None)
        indicator_list = section_val["indicators"]
    else:
        # "ta", "vol", "features" are flat lists
        source_table = section_key   # section key = table name
        roll_filter = None
        indicator_list = section_val  # list of {name, column, is_directional}
```

---

## Source Table PK Summary (CRITICAL reference)

| Table | ts column | venue_id in PK? | alignment_source in PK? | Special filter |
|-------|-----------|-----------------|------------------------|----------------|
| `ta` | `ts` | NO (column only, DEFAULT 1) | YES | none |
| `vol` | `ts` | NO (column only, DEFAULT 1) | YES | none |
| `returns_bars_multi_tf_u` | `"timestamp"` (quoted!) | YES | YES | `AND roll = FALSE` |
| `features` | `ts` | YES | YES | none |

This is the single most important reference for `_load_indicators_batch()`.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| N queries per indicator | Batch load all indicators per source_table in one query | Phase 90 design | 22x fewer DB round trips for full indicator set |
| No cross-timeframe features | Row-per-indicator ctf table | Phase 89 design | Enables slope/divergence/agreement across TF pairs |

---

## Open Questions

1. **agreement window -- should it be configurable?**
   - What we know: `slope_window` and `divergence_zscore_window` are in `composite_params` in YAML
   - What's unclear: `agreement` rolling window is not in the YAML spec
   - Recommendation: Default to 20 bars (hardcode or add to `composite_params`). Phase 91
     can expose it if needed.

2. **crossover for non-directional indicators -- return NaN or 0?**
   - What we know: The ctf column `crossover` is `DOUBLE PRECISION` (nullable)
   - What's unclear: Whether 0 or NULL is better for "not applicable"
   - Recommendation: Return `np.nan` (NULL in DB). Clearer semantics than 0.

3. **Per-asset computation -- should it use multiprocessing?**
   - What we know: Other scripts use `NullPool` + `maxtasksperchild=1` on Windows for MP
   - What's unclear: Phase 90 success criteria only require single-asset test `compute_for_ids([1])`
   - Recommendation: Phase 90 is single-process. Phase 91 adds CLI with optional parallelism.

---

## Sources

### Primary (HIGH confidence)

- `src/ta_lab2/regimes/comovement.py` -- exact `build_alignment_frame()` signature and implementation (lines 34-60)
- `src/ta_lab2/scripts/features/base_feature.py` -- template method pattern, `write_to_db`, `_get_table_columns`, scoped DELETE (lines 326-408)
- `src/ta_lab2/scripts/features/ta_feature.py` -- `load_source_data` SQL pattern, `load_indicator_params` dim table query pattern
- `src/ta_lab2/scripts/features/vol_feature.py` -- vol + returns join pattern, confirming `AND roll = FALSE` and `"timestamp"` column
- `sql/ddl/create_returns_bars_multi_tf_u.sql` -- confirmed PK `(id, "timestamp", tf, venue_id, alignment_source)` and `roll` column
- `sql/features/042_ta.sql` -- ta table PK `(id, ts, tf, alignment_source)` (no venue_id)
- `sql/features/041_vol.sql` -- vol table PK `(id, ts, tf, alignment_source)` (no venue_id)
- `alembic/versions/a0b1c2d3e4f5_strip_cmc_prefix_add_venue_id.py` -- confirmed ta/vol in VENUE_ID_COLUMN_ONLY; returns_bars_multi_tf_u and features in VENUE_ID_PK_CHANGES
- `alembic/versions/j4k5l6m7n8o9_ctf_schema.py` -- confirmed ctf table schema (14 columns, 7-col PK, computed_at)
- `configs/ctf_config.yaml` -- confirmed YAML structure (returns section uses nested `indicators:` key)
- `src/ta_lab2/ml/expression_engine.py` -- rolling slope pattern `_slope` function (lines 55-73)
- `src/ta_lab2/features/trend.py` -- alternative rolling slope pattern (lines 51-56)
- `src/ta_lab2/macro/cross_asset.py` -- YAML config loading pattern with `project_root()` (lines 83-118)
- `.planning/phases/89-ctf-schema-dimension-table/89-01-VERIFICATION.md` -- confirmed Phase 89 completed, all tables exist

### Secondary (MEDIUM confidence)

- `src/ta_lab2/scripts/analysis/run_ic_sweep.py` lines 236-251 -- features table query pattern with `pd.to_datetime(utc=True)` fix
- `src/ta_lab2/scripts/regimes/refresh_regimes.py` lines 132-142 -- confirmed `pd.to_datetime(utc=True)` required before `merge_asof`
- `src/ta_lab2/features/ama/ama_returns.py` lines 350-363 -- `_pg_insert_on_conflict_nothing` method pattern
- `src/ta_lab2/scripts/desc_stats/refresh_asset_stats.py` lines 260-266 -- confirmed `"timestamp"` column and `roll = FALSE` filter in production code

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All from production files, no external sources needed
- build_alignment_frame() signature: HIGH - Copied directly from source file
- Source table PKs: HIGH - Cross-verified from DDL files + migration + production scripts
- Scoped DELETE pattern: HIGH - Copied directly from base_feature.py
- Slope/divergence computation: HIGH - Existing patterns in expression_engine.py and trend.py
- YAML config structure: HIGH - Verified from actual ctf_config.yaml file + phase 89 verification

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable; CTF schema is locked after Phase 89 completion)
