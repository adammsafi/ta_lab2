# Phase 27: Regime Integration - Research

**Researched:** 2026-02-20
**Domain:** Regime labeling, policy resolution, signal integration, PostgreSQL pipeline
**Confidence:** HIGH (all findings from direct source code inspection)

---

## Summary

Phase 27 connects an already-complete 13-file regime module to the DB-backed feature pipeline. The regime module (`src/ta_lab2/regimes/`) is fully implemented — this is integration work, not greenfield. The primary tasks are: building `refresh_cmc_regimes.py` (the DB-backed orchestrator), writing DDL for three new output tables, and extending the three signal generators to accept a `TightenOnlyPolicy` object.

The column-mapping gap is the biggest integration risk. The labelers expect column names like `close_ema_20`, `close_ema_50`, `close_ema_200` but the DB stores EMAs as long-format rows in `cmc_ema_multi_tf_u` (with column `ema`) indexed by `period`. A Python-side pivot-and-rename step is required before calling any labeler. This step is not pre-built — it must be written.

The signal integration is a parameter-passing problem, not a structural change. All three generators already follow the same `generate_for_ids(ids, signal_config, ...)` pattern. Adding a `regime_context: Optional[TightenOnlyPolicy]` parameter and applying tighten-only scaling inside each generator's transformation logic is the correct insertion point.

**Primary recommendation:** Write `refresh_cmc_regimes.py` that queries bars + EMAs per TF, pivots EMAs to wide format, calls labelers, resolves policy, and upserts to `cmc_regimes`. Then extend signal generators with an optional `regime_context` parameter. Follow the scoped DELETE + INSERT write pattern from `BaseFeature`.

---

## Standard Stack

### Core (confirmed from source)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | existing | DataFrame operations, pivot, rename | Used throughout codebase |
| numpy | existing | Vectorized labeling, where/full | Used in labels.py |
| sqlalchemy | existing | Engine, text(), connection management | Used in all DB scripts |
| PyYAML | optional (graceful fallback) | YAML policy overlay via `--policy-file` | Already supported in policy_loader.py |

### EMA Periods in the Pipeline

**CONFIRMED from `refresh_cmc_ema_multi_tf_from_bars.py` and `refresh_cmc_ema_multi_tf_cal_from_bars.py`:**
```
DEFAULT_PERIODS = [6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365]
```

Period 20 **already exists** in `DEFAULT_PERIODS`. No EMA pipeline changes needed for period 20.

### Calendar EMA Tables

`cmc_ema_multi_tf_cal_iso` and `cmc_ema_multi_tf_cal_us` — confirmed DDL:
- PK: `(id, tf, ts, period)`
- Columns: `id, tf, ts, period, tf_days, roll, ema, d1, d2, d1_roll, d2_roll, ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar`
- Weekly TFs: `tf = '1W'` (ISO) or US-calendar equivalent
- Monthly TFs: `tf = '1M'`
- NOTE: `d1` column is the first derivative (NOT `ema_d1` — no prefix)

### Installation

No new packages required. All dependencies already present.

---

## Architecture Patterns

### Data Flow for refresh_cmc_regimes.py

```
DB Query                   Python                           DB Write
────────                   ──────                           ────────
cmc_price_bars_multi_tf    pivot_emas_to_wide()             cmc_regimes
cmc_ema_multi_tf_cal_iso   assess_data_budget()             cmc_regime_flips
cmc_ema_multi_tf_cal_us    label_layer_monthly()            cmc_regime_stats
                           label_layer_weekly()
                           label_layer_daily()
                           resolve_policy()
                           detect_flips() [for flips table]
                           regime_stats() [for stats table]
```

### Recommended Project Structure

```
src/ta_lab2/scripts/regimes/
├── __init__.py
├── refresh_cmc_regimes.py      # Main refresh script (NEW)
└── regime_inspect.py           # Move from regimes/ module (or symlink)

sql/regimes/
├── 080_cmc_regimes.sql         # Main regime table DDL (NEW)
├── 081_cmc_regime_flips.sql    # Flips table DDL (NEW)
└── 082_cmc_regime_stats.sql    # Stats table DDL (NEW)
```

### Pattern 1: EMA Pivot (CRITICAL — not pre-built)

The labelers expect wide-format columns (`close_ema_20`, `close_ema_50`, `close_ema_200`), but the DB stores EMAs long-format with a `period` column. A pivot is required before calling labelers.

```python
# Source: inferred from labels.py:13-15, cmc_ema_multi_tf_cal_iso DDL
def pivot_emas_to_wide(
    ema_df: pd.DataFrame,   # from cmc_ema_multi_tf_cal_iso/us, filtered to tf
    periods: list[int],     # e.g. [12, 24, 48] for monthly, [20, 50, 200] for weekly
    price_col: str = "close",
) -> pd.DataFrame:
    """
    Pivot long EMA rows to wide format and rename to close_ema_N convention.
    ema_df has columns: id, ts, period, ema
    Output: DataFrame with columns id, ts, close_ema_12, close_ema_24, ...
    """
    pivot = (
        ema_df[ema_df["period"].isin(periods)]
        .pivot_table(index=["id", "ts"], columns="period", values="ema")
        .reset_index()
    )
    pivot.columns = ["id", "ts"] + [f"{price_col}_ema_{p}" for p in sorted(periods)]
    return pivot
```

### Pattern 2: DB-Backed Labeling Flow (Per Asset, Per TF Set)

```python
# Source: regime_inspect.py:41-63, data_budget.py, labels.py
def compute_regimes_for_id(
    asset_id: int,
    engine: Engine,
    policy_table: dict,
    min_bars_overrides: dict,
) -> pd.DataFrame:
    """Returns rows ready to insert into cmc_regimes."""
    # 1. Load bars per TF
    monthly = load_bars(engine, asset_id, tf="1M")  # from cmc_price_bars_multi_tf_cal_iso
    weekly  = load_bars(engine, asset_id, tf="1W")
    daily   = load_bars(engine, asset_id, tf="1D")  # from cmc_price_bars_multi_tf

    # 2. Load + pivot EMAs
    monthly_emas = load_and_pivot_emas(engine, asset_id, tf="1M", periods=[12, 24, 48])
    weekly_emas  = load_and_pivot_emas(engine, asset_id, tf="1W", periods=[20, 50, 200])
    daily_emas   = load_and_pivot_emas(engine, asset_id, tf="1D", periods=[20, 50, 100])

    # 3. Merge bars + EMAs on (id, ts)
    monthly = monthly.merge(monthly_emas, on=["id", "ts"], how="left")
    weekly  = weekly.merge(weekly_emas, on=["id", "ts"], how="left")
    daily   = daily.merge(daily_emas, on=["id", "ts"], how="left")

    # 4. Assess data budget
    ctx = assess_data_budget(monthly=monthly, weekly=weekly, daily=daily)
    mode = ctx.feature_tier

    # 5. Label each layer (respects data budget)
    L0 = label_layer_monthly(monthly, mode=mode) if ctx.enabled_layers["L0"] else None
    L1 = label_layer_weekly(weekly, mode=mode)   if ctx.enabled_layers["L1"] else None
    L2 = label_layer_daily(daily, mode=mode)     if ctx.enabled_layers["L2"] else None

    # 6. Resolve policy per daily row (align upper TFs forward via merge_asof)
    # L0, L1 are lower-frequency — merge_asof forward-fill to daily index
    ...
    # 7. Apply hysteresis (REAL, not stub — needs counter implementation)
    ...
    # 8. Build output DataFrame with all cmc_regimes columns
    ...
```

### Pattern 3: Scoped DELETE + INSERT (same as BaseFeature)

```python
# Source: base_feature.py:354-371
with engine.begin() as conn:
    conn.execute(
        text("DELETE FROM public.cmc_regimes WHERE id = ANY(:ids) AND tf = :tf"),
        {"ids": ids, "tf": "1D"},
    )
df.to_sql("cmc_regimes", engine, schema="public", if_exists="append",
          index=False, method="multi", chunksize=5000)
```

### Pattern 4: Standard CLI Structure (follows existing scripts)

```python
# Source: run_all_feature_refreshes.py:326-400, run_all_signal_refreshes.py:332-368
parser = argparse.ArgumentParser(...)
parser.add_argument("--all", action="store_true")
parser.add_argument("--ids", help="Comma-separated IDs")
parser.add_argument("--tf", default="1D")
parser.add_argument("--full-refresh", action="store_true")
parser.add_argument("--policy-file", type=Path, help="YAML policy overlay")
parser.add_argument("--no-regime", action="store_true")   # for signal generators
parser.add_argument("--min-bars-l0", type=int, default=60)
parser.add_argument("--min-bars-l1", type=int, default=52)
parser.add_argument("--min-bars-l2", type=int, default=120)
```

### Pattern 5: Incremental Watermark Pattern

```python
# Source: daily_features_view.py:138-181, base_feature.py:320-371
# Watermark: track last-computed ts per (id, tf) in a state table
# cmc_regime_state (id, tf, last_ts, updated_at) — same pattern as cmc_feature_state
```

### Anti-Patterns to Avoid

- **Resampling bars in Python**: Do NOT resample daily bars to weekly/monthly in Python. Use the calendar bar tables (`cmc_price_bars_multi_tf_cal_iso`, `_cal_us`) — they already exist with the right OHLCV aggregation.
- **Long-format EMAs passed to labelers**: Labels.py uses `df.get("close_ema_20")` — it must receive wide-format DataFrames.
- **Using `alignment_source` in PK**: `cmc_ema_multi_tf_u` has `alignment_source` column but it is NOT part of PK. Filter queries carefully.
- **Hardcoding `d1` as `ema_d1`**: Calendar EMA tables use column `d1` not `ema_d1` (MEMORY.md critical note confirmed by DDL).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| EMA column naming | Custom naming convention | `feature_utils.add_ema_pack(df, tf="W")` from `feature_utils.py` | Already adds correct close_ema_N names per TF |
| ATR computation | Custom ATR | `feature_utils.add_atr14(df)` | Uses true range with high/low, falls back to proxy |
| Label composition | Custom string builder | `compose_regime_key(trend, vol, liq)` from labels.py | Returns "Up-Normal-Normal" format resolver expects |
| Policy matching | Regex/exact match | `_match_policy(regime_key, table)` (private, but resolver.py:64-78) | Substring-token matching already implemented |
| YAML policy loading | YAML parser | `load_policy_table(yaml_path)` from policy_loader.py | Merges over DEFAULT_POLICY_TABLE gracefully |
| Data budget | Manual bar counting | `assess_data_budget(monthly, weekly, daily, intraday)` | Returns `DataBudgetContext` with enabled_layers |
| Flip detection | Custom diff logic | `detect_flips(df, sign_col, min_separation)` from flips.py | Handles min_separation deduplication |
| Regime stats | Custom groupby | `regime_stats(df, regime_col, ret_col)` from flips.py | Handles cumret, duration correctly |
| EMA comovement | Custom correlation | `compute_ema_comovement_stats(df, ema_cols)` from comovement.py | Returns corr + agree dict |
| Proxy tightening | Manual cap logic | `infer_cycle_proxy(ProxyInputs(...))` from proxies.py | Returns `ProxyOutcome` with l0_cap |
| Policy resolution | Manual tighten logic | `resolve_policy_from_table(table, L0, L1, L2)` | Handles tighten-only semantics correctly |

**Key insight:** The entire regime logic stack is built. The integration task is writing the DB I/O glue — queries, pivots, output DDL, and signal generator hooks.

---

## Common Pitfalls

### Pitfall 1: Labeler Column Name Mismatch (CRITICAL)

**What goes wrong:** `label_layer_weekly()` calls `df.get("close_ema_20", np.nan)` at labels.py:24-27. If the DataFrame has `ema` (long format) or `ema_20` (no prefix), the labeler silently uses NaN and produces all-"Sideways" labels.

**Why it happens:** DB stores EMAs long-format. Labelers expect wide-format with `close_ema_N` naming per `feature_utils.add_ema_pack()` convention.

**How to avoid:** Always pivot EMAs to wide format and rename columns before calling labelers. Use the mapping:
- Monthly: periods [12, 24, 48] -> `close_ema_12`, `close_ema_24`, `close_ema_48`
- Weekly: periods [20, 50, 200] -> `close_ema_20`, `close_ema_50`, `close_ema_200`
- Daily: periods [20, 50, 100] -> `close_ema_20`, `close_ema_50`, `close_ema_100`

**Warning signs:** All L0/L1/L2 labels are "Sideways-Normal-Normal" for every asset on every day.

### Pitfall 2: Calendar Bar Table PK vs Time Column

**What goes wrong:** `cmc_price_bars_multi_tf_cal_iso` has PK `(id, tf, bar_seq)` with `time_close` as the timestamp. The signal generators and feature tables use `ts` as their timestamp column name.

**Why it happens:** Calendar bar tables use `time_close` not `ts`. If you JOIN on `ts` without aliasing, you get empty results or wrong matches.

**How to avoid:** Always alias: `SELECT time_close AS ts FROM cmc_price_bars_multi_tf_cal_iso`.

### Pitfall 3: Hysteresis Stub in resolver.py

**What goes wrong:** `apply_hysteresis()` (resolver.py:81-92) is a minimal stub — it only compares `prev_key == new_key`. The min_change counter is never tracked externally. If called naively it provides no real hysteresis.

**Why it happens:** The stub was intentional scaffolding. Real hysteresis requires per-asset counter state (how many bars since last flip).

**How to avoid:** Implement a `HysteresisCounter` class that tracks `bars_since_flip` per (id, tf, layer). Only pass `new_key` through when `bars_since_flip >= min_bars`. Store the counter state in a Python dict during batch processing (not DB — it's transient per run).

```python
# Pattern for real hysteresis during row-by-row processing
class HysteresisTracker:
    def __init__(self, min_bars: int = 3):
        self.min_bars = min_bars
        self._state: dict[str, tuple[str, int]] = {}  # key -> (prev_key, bars_since_flip)

    def update(self, asset_key: str, new_label: str) -> str:
        prev_label, count = self._state.get(asset_key, (None, 0))
        if prev_label is None or new_label == prev_label:
            self._state[asset_key] = (new_label, 0)
            return new_label
        count += 1
        if count >= self.min_bars:
            self._state[asset_key] = (new_label, 0)
            return new_label
        else:
            self._state[asset_key] = (prev_label, count)
            return prev_label
```

### Pitfall 4: tz-aware Timestamp Pitfall (from MEMORY.md)

**What goes wrong:** `series.values` on tz-aware datetime Series returns tz-NAIVE `numpy.datetime64` on this system.

**How to avoid:** Use `.tz_localize("UTC")` on DatetimeIndex, or `.tolist()` for tz-aware objects. Confirmed critical from MEMORY.md.

### Pitfall 5: Signal Generator `feature_snapshot` Bug (Pre-existing)

**What goes wrong:** RSI signal generator has a known bug: `can't adapt type 'dict'` for `feature_snapshot` when writing to PostgreSQL (from MEMORY.md Signal Pipeline Status).

**Why it happens:** `df_records["feature_snapshot"]` contains Python dicts but `to_sql()` with `method="multi"` doesn't serialize them to JSONB.

**How to avoid:** Serialize `feature_snapshot` dict to JSON string before writing:
```python
import json
df_records["feature_snapshot"] = df_records["feature_snapshot"].apply(
    lambda x: json.dumps(x) if isinstance(x, dict) else x
)
```
This fix is needed before regime context can be added to signals.

### Pitfall 6: align_source Filter on cmc_ema_multi_tf_u

**What goes wrong:** `cmc_ema_multi_tf_u` has an `alignment_source` column (values like `'multi_tf'`, `'multi_tf_cal_us'`). For daily regimes, you want `alignment_source = 'multi_tf'`. Without filtering, you may get duplicate rows per (id, ts, tf, period).

**Warning signs:** Pivot produces MultiIndex columns or duplicate rows.

### Pitfall 7: cmc_features EMA Columns are Sparse

**What goes wrong:** `cmc_features` only contains EMAs 9, 10, 21, 50, 200 (from the join in `daily_features_view.py`). For daily regime labeling that needs period 100, `cmc_features.ema_100` does not exist.

**How to avoid:** Query `cmc_ema_multi_tf_u` directly for regime computation. Do not rely on `cmc_features` for EMA data beyond the 5 periods it stores.

### Pitfall 8: Policy Table Pattern Matching (substring, not exact)

**What goes wrong:** `DEFAULT_POLICY_TABLE` keys like `"Up-Low-"` use trailing hyphens. `_match_policy` splits on `-` and ignores empty tokens. The key `"Down-"` matches any regime containing "Down". Order of iteration matters — Python dict order is preserved (insertion order in 3.7+), so first match wins.

**Warning signs:** Unexpected policy values when a regime like "Down-Low-Normal" matches "Down-" instead of a more specific entry.

**How to avoid:** When adding YAML overrides, put more specific keys before less specific ones. Document this in the policy YAML comments.

---

## Code Examples

### Loading Calendar Bars (Weekly)

```python
# Source: cmc_price_bars_multi_tf_cal_iso DDL (sql/features/031_cmc_price_bars_multi_tf_cal_iso.sql)
sql = text("""
    SELECT id, time_close AS ts, open, high, low, close, volume
    FROM public.cmc_price_bars_multi_tf_cal_iso
    WHERE id = ANY(:ids) AND tf = '1W'
    ORDER BY id, time_close
""")
with engine.connect() as conn:
    weekly_bars = pd.read_sql(sql, conn, params={"ids": ids})
weekly_bars["ts"] = pd.to_datetime(weekly_bars["ts"], utc=True)
```

### Loading and Pivoting Calendar EMAs (Weekly)

```python
# Source: cmc_ema_multi_tf_cal_iso DDL, labels.py:144-169
sql = text("""
    SELECT id, ts, period, ema
    FROM public.cmc_ema_multi_tf_cal_iso
    WHERE id = ANY(:ids) AND tf = '1W'
      AND period IN (20, 50, 200)
      AND roll = FALSE
    ORDER BY id, ts, period
""")
with engine.connect() as conn:
    emas_long = pd.read_sql(sql, conn, params={"ids": ids})
emas_long["ts"] = pd.to_datetime(emas_long["ts"], utc=True)

# Pivot to wide format with close_ema_N naming
emas_wide = (
    emas_long
    .pivot_table(index=["id", "ts"], columns="period", values="ema")
    .reset_index()
)
emas_wide.columns = ["id", "ts", "close_ema_20", "close_ema_50", "close_ema_200"]
```

### Calling the Label Stack (one asset)

```python
# Source: regime_inspect.py:41-63, labels.py
from ta_lab2.regimes import (
    assess_data_budget, label_layer_monthly, label_layer_weekly,
    label_layer_daily, resolve_policy_from_table
)

# Merge bars and EMAs
weekly = weekly_bars.merge(emas_wide, on=["id", "ts"], how="left")

ctx = assess_data_budget(monthly=monthly_df, weekly=weekly, daily=daily_df)
mode = ctx.feature_tier  # "full" or "lite"

L0 = label_layer_monthly(monthly_df, mode=mode) if ctx.enabled_layers["L0"] else None
L1 = label_layer_weekly(weekly, mode=mode)       if ctx.enabled_layers["L1"] else None
L2 = label_layer_daily(daily_df, mode=mode)      if ctx.enabled_layers["L2"] else None

# resolve_policy_from_table takes scalar label strings (one per timestamp)
# For full-history computation: call per row or use vectorized forward-fill approach
policy = resolve_policy_from_table(
    policy_table,
    L0=L0.iloc[-1] if L0 is not None else None,
    L1=L1.iloc[-1] if L1 is not None else None,
    L2=L2.iloc[-1] if L2 is not None else None,
)
```

### Forward-Fill Multi-TF Labels to Daily Index

```python
# Source: comovement.py:34-59 (build_alignment_frame uses merge_asof)
# Lower-freq labels (L0 monthly, L1 weekly) need forward-fill to daily timestamps
from ta_lab2.regimes import build_alignment_frame

# daily_index: DataFrame with daily ts column
# l0_series: Series indexed by monthly ts
# l1_series: Series indexed by weekly ts

daily_with_l0 = pd.merge_asof(
    daily_index.sort_values("ts"),
    l0_series.reset_index().rename(columns={0: "l0_label"}).sort_values("ts"),
    on="ts",
    direction="backward",
)
daily_with_l1 = pd.merge_asof(
    daily_with_l0,
    l1_series.reset_index().rename(columns={0: "l1_label"}).sort_values("ts"),
    on="ts",
    direction="backward",
)
```

### Signal Generator Regime Hook (EMA example)

```python
# Source: generate_signals_ema.py:66-160 (generate_for_ids signature)
# Add regime_context as optional parameter

@dataclass
class EMASignalGenerator:
    engine: Engine
    state_manager: SignalStateManager
    signal_version: str = "1.0"

    def generate_for_ids(
        self,
        ids: list[int],
        signal_config: dict,
        full_refresh: bool = False,
        dry_run: bool = False,
        regime_context: Optional[dict] = None,  # NEW: {asset_id -> TightenOnlyPolicy}
        no_regime: bool = False,                  # NEW: --no-regime flag bypass
    ) -> int:
        ...
        # In _transform_signals_to_records, for each entry signal:
        if regime_context and not no_regime:
            policy = regime_context.get(asset_id)
            if policy:
                # Tighten-only: apply policy fields
                effective_size = params.get("risk_pct", 0.5) * policy.size_mult
                # Filter by allowed setups
                if policy.setups and signal_type_name not in (policy.setups or []):
                    continue  # skip signal not in allowed setups
                # Record regime key in signal record
                record["regime_key"] = regime_key_at_ts
```

### Writing cmc_regimes (Scoped DELETE + INSERT)

```python
# Source: base_feature.py:320-371 (confirmed write pattern)
def write_regimes_to_db(engine: Engine, df: pd.DataFrame, ids: list[int], tf: str) -> int:
    fq = "public.cmc_regimes"
    # Scoped delete for this (ids, tf) batch
    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {fq} WHERE id = ANY(:ids) AND tf = :tf"),
            {"ids": ids, "tf": tf}
        )
    df.to_sql("cmc_regimes", engine, schema="public",
              if_exists="append", index=False, method="multi", chunksize=5000)
    return len(df)
```

---

## Output Table Design

### cmc_regimes (main table)

```sql
CREATE TABLE IF NOT EXISTS public.cmc_regimes (
    id              INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    tf              TEXT NOT NULL,          -- '1D' for daily regime rows

    -- Layer labels (NULL if layer disabled by data budget)
    l0_label        TEXT,                   -- Monthly cycle: e.g. "Up-Normal-Normal"
    l1_label        TEXT,                   -- Weekly macro
    l2_label        TEXT,                   -- Daily tactical
    l3_label        TEXT,                   -- Intraday (NULL until intraday data)
    l4_label        TEXT,                   -- Execution (reserved)
    regime_key      TEXT,                   -- Composite or L2 as primary

    -- Resolved policy fields (denormalized for query convenience)
    size_mult       DOUBLE PRECISION,
    stop_mult       DOUBLE PRECISION,
    orders          TEXT,
    gross_cap       DOUBLE PRECISION,
    pyramids        BOOLEAN,

    -- Data budget context
    feature_tier    TEXT,                   -- 'full' | 'lite'
    l0_enabled      BOOLEAN,
    l1_enabled      BOOLEAN,
    l2_enabled      BOOLEAN,

    -- Reproducibility
    regime_version_hash TEXT,               -- Hash of policy_table + labeler params

    -- Metadata
    updated_at      TIMESTAMPTZ DEFAULT now(),

    PRIMARY KEY (id, ts, tf)
);
```

### cmc_regime_flips (separate table)

```sql
CREATE TABLE IF NOT EXISTS public.cmc_regime_flips (
    id              INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,   -- timestamp of the flip
    tf              TEXT NOT NULL,
    layer           TEXT NOT NULL,          -- 'L0', 'L1', 'L2'
    old_regime      TEXT NOT NULL,
    new_regime      TEXT NOT NULL,
    duration_bars   INTEGER,                -- bars in previous regime
    PRIMARY KEY (id, ts, tf, layer)
);
```

### cmc_regime_stats (materialized stats)

```sql
CREATE TABLE IF NOT EXISTS public.cmc_regime_stats (
    id              INTEGER NOT NULL,
    tf              TEXT NOT NULL,
    regime_key      TEXT NOT NULL,
    n_bars          INTEGER,
    pct_of_history  DOUBLE PRECISION,
    avg_ret_1d      DOUBLE PRECISION,
    computed_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, tf, regime_key)
);
```

---

## Signal Integration Design

### dim_signals Extension (new column per CONTEXT.md)

Add `regime_enabled BOOLEAN DEFAULT TRUE` to `dim_signals` to allow per-signal opt-out:

```sql
ALTER TABLE public.dim_signals ADD COLUMN IF NOT EXISTS regime_enabled BOOLEAN DEFAULT TRUE;
```

### Signal Table Extension (add regime_key column)

```sql
ALTER TABLE public.cmc_signals_ema_crossover ADD COLUMN IF NOT EXISTS regime_key TEXT;
ALTER TABLE public.cmc_signals_rsi_mean_revert ADD COLUMN IF NOT EXISTS regime_key TEXT;
ALTER TABLE public.cmc_signals_atr_breakout ADD COLUMN IF NOT EXISTS regime_key TEXT;
```

### Regime Lookup in Signal Generators

Signal generators query `cmc_regimes` for the current regime at signal entry time:

```python
# Option A: SQL JOIN (simpler, no memory overhead)
# In _load_features(), add regime columns via LEFT JOIN:
"""
LEFT JOIN public.cmc_regimes reg
  ON f.id = reg.id AND f.ts = reg.ts AND reg.tf = '1D'
"""
# Then extract: reg.regime_key, reg.size_mult, reg.stop_mult, reg.gross_cap, reg.pyramids

# Option B: Separate load + merge in Python (more explicit)
# Load cmc_regimes for same (ids, tf, date range)
# Merge on (id, ts)
```

**Recommendation:** Option A (SQL JOIN) — consistent with how `daily_features_view.py` already builds `cmc_features` via JOINs. Avoids separate round trip.

---

## EMA Period Mapping Summary

| Layer | TF | EMA Periods Needed | Column Names (labeler expects) | DB Source |
|-------|-----|-------------------|-------------------------------|-----------|
| L0 (Monthly) | 1M | 12, 24, 48 | close_ema_12, close_ema_24, close_ema_48 | cmc_ema_multi_tf_cal_iso/us |
| L1 (Weekly) | 1W | 20, 50, 200 | close_ema_20, close_ema_50, close_ema_200 | cmc_ema_multi_tf_cal_iso/us |
| L2 (Daily) | 1D | 20, 50, 100 | close_ema_20, close_ema_50, close_ema_100 | cmc_ema_multi_tf_u (or cal) |
| L3 (Intraday) | n/a | 34, 55, 89 | n/a (auto-disabled, no intraday data) | n/a |

All required periods (12, 20, 24, 48, 50, 100, 200) exist in `DEFAULT_PERIODS = [6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365]`. No EMA pipeline changes needed.

---

## DEFAULT_POLICY_TABLE Review

**Source:** resolver.py:7-51

| Key | size_mult | stop_mult | setups | orders | Notes |
|-----|-----------|-----------|--------|--------|-------|
| "Up-Normal-Normal" | 1.00 | 1.50 | breakout, pullback | mixed | Base case |
| "Up-Low-" | 1.10 | 1.25 | breakout, pullback | mixed | Low vol trending — slightly oversized |
| "Up-High-" | 0.75 | 1.75 | pullback | conservative | Volatile uptrend |
| "Sideways-Low-" | 0.70 | 1.25 | mean_revert | passive | Range-bound low vol |
| "Sideways-High-" | 0.40 | 2.00 | stand_down, mean_revert | passive | Chop — avoid |
| "Down-" | 0.60 | 1.60 | short_rallies, hedge | mixed | Bear mode |
| "-Stressed" | 0.60 | 1.25 | None | passive | Liquidity override |
| (fallback) | 0.80 | 1.50 | pullback | mixed | Any unmatched |

**Assessment vs quant conventions:** The `size_mult = 1.10` for "Up-Low-" is a mild oversize in low-vol trending conditions — this is quant-conventional (Kelly criterion supports sizing up in high-Sharpe regimes). The `stop_mult = 2.00` for "Sideways-High-" is wide — appropriate for high-vol chop where tight stops get hit repeatedly. The `gross_cap = 1.0` field exists in `TightenOnlyPolicy` but is missing from most `DEFAULT_POLICY_TABLE` entries (will use class default of 1.0). All values are reasonable for initial deployment. Flag for review after first backtest run.

---

## Orchestration Integration

### Where regime refresh fits in run_daily_refresh.py

Current order: bars -> EMAs -> (features not in run_daily_refresh.py)
Required order: bars -> EMAs -> features -> **regimes** -> signals

The `run_daily_refresh.py` orchestrates via subprocess. Add a regime step:

```python
# After EMAs, add regime refresh
if run_regimes:  # new --regimes flag
    regime_result = run_regime_refresh(args, db_url, ids_for_regimes)
    results.append(("regimes", regime_result))
```

The regime refresh script should also work standalone:
```bash
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --all --tf 1D
python -m ta_lab2.scripts.regimes.refresh_cmc_regimes --ids 1,52 --policy-file configs/regime_policies.yaml
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| CSV-based regime logging (telemetry.py) | DB table cmc_regimes | Replace append_snapshot() with DB writes |
| File-based policy (hardcoded) | YAML overlay via load_policy_table() | Already supported — just needs --policy-file wiring |
| Single-asset BTC pipeline (old_run_btc_pipeline.py) | Multi-asset batch via DB | Simplified: no resample needed (bars already exist) |
| Hysteresis stub (resolver.py:81-92) | Real hysteresis with HysteresisTracker | Must implement — stub does nothing useful |
| regime_inspect.py reads CSV files | DB-backed query with --live flag | Move to scripts/regimes/; add DB query mode |

**Deprecated:**
- `telemetry.py:append_snapshot()` — will not be called from new pipeline; CSV telemetry replaced by DB
- `old_run_btc_pipeline.py` — reference only; all CSV/resample code irrelevant for DB pipeline

---

## Open Questions

1. **Weekly ATR for vol labeling**
   - What we know: `label_vol_bucket()` (labels.py:59-84) uses `atr_col` if provided; otherwise falls back to rolling absolute return proxy. The ATR proxy is adequate for labeling.
   - What's unclear: CONTEXT.md says "Pre-compute weekly ATR in feature pipeline (add to cmc_ta for weekly TF via existing TAFeature class)". The current `cmc_ta` DDL has `atr_14` for whatever TF it's computed at. Weekly `cmc_ta` may not yet be populated.
   - Recommendation: Use the ATR proxy fallback (`atrp = df[price_col].pct_change().abs().rolling(14).mean()`) initially. This avoids a dependency on weekly feature pipeline readiness. Add real weekly ATR as a follow-up.

2. **Which calendar variant to use (ISO vs US)**
   - What we know: Both `cmc_price_bars_multi_tf_cal_iso` and `_cal_us` exist. L0 is monthly, L1 is weekly — both have ISO and US variants.
   - Recommendation: Use ISO by default (Monday-anchored weeks, Jan-anchored months). Add `--cal-scheme iso|us` CLI flag to allow experimentation. Document that ISO is default.

3. **Incremental refresh boundary for regime**
   - What we know: Feature pipeline uses `cmc_feature_state` with watermarks. Regime needs same pattern.
   - What's unclear: Regime is a function of ALL history (hysteresis, rolling statistics). A true incremental refresh must recompute from the earliest dirty window, which may be the entire history if EMA data changed.
   - Recommendation: For v0.7.0, implement full-refresh-per-asset on each run (complete recompute). Add watermark tracking as Phase 28 optimization. Regime computation is fast enough for full-recompute per daily run.

4. **Comovement table placement**
   - What we know: `compute_ema_comovement_stats()` returns corr + agree + meta DataFrames.
   - What's unclear: CONTEXT.md marks this as "Claude's Discretion" — separate `cmc_regime_comovement` vs inline stats.
   - Recommendation: Separate `cmc_regime_comovement` table with PK `(id, tf, computed_at)`. Comovement is pair-wise (one row per EMA pair per asset) which doesn't fit cleanly into `cmc_regimes` columns.

---

## Sources

### Primary (HIGH confidence — direct source code inspection)

| File | Key Finding |
|------|-------------|
| `src/ta_lab2/regimes/labels.py` | All labeler signatures, exact column names required |
| `src/ta_lab2/regimes/resolver.py` | DEFAULT_POLICY_TABLE, TightenOnlyPolicy fields, resolve_policy_from_table() |
| `src/ta_lab2/regimes/data_budget.py` | assess_data_budget() signature, _MIN_BARS thresholds |
| `src/ta_lab2/regimes/flips.py` | detect_flips(), regime_stats() signatures |
| `src/ta_lab2/regimes/comovement.py` | compute_ema_comovement_stats() return structure |
| `src/ta_lab2/regimes/proxies.py` | ProxyInputs, ProxyOutcome, infer_cycle_proxy() |
| `src/ta_lab2/regimes/policy_loader.py` | YAML loading, default path, merge logic |
| `src/ta_lab2/regimes/feature_utils.py` | add_ema_pack() TF-to-period mapping |
| `src/ta_lab2/regimes/regime_inspect.py` | Complete working reference for single-asset flow |
| `sql/features/040_cmc_returns.sql` | cmc_returns schema (PK, columns) |
| `sql/features/041_cmc_vol.sql` | cmc_vol schema, atr_14 column confirmed |
| `sql/features/042_cmc_ta.sql` | cmc_ta schema, atr_14 + adx_14 confirmed |
| `sql/views/050_cmc_features.sql` | cmc_features schema — only EMAs 9,10,21,50,200 |
| `sql/features/030_cmc_ema_multi_tf_u_create.sql` | cmc_ema_multi_tf_u schema, alignment_source |
| `sql/ddl/create_cmc_ema_multi_tf_cal_tables.sql` | Calendar EMA schema, d1/d2 column names (NOT ema_d1) |
| `sql/features/031_cmc_price_bars_multi_tf_cal_iso.sql` | Calendar bar schema, PK uses bar_seq not ts |
| `sql/signals/060-062_cmc_signals_*.sql` | Signal table schemas — no regime_key yet |
| `sql/lookups/030_dim_signals.sql` | dim_signals schema — no regime_enabled yet |
| `src/ta_lab2/scripts/signals/generate_signals_rsi.py` | RSI generator, feature_snapshot dict bug confirmed |
| `src/ta_lab2/scripts/signals/generate_signals_ema.py` | EMA generator, entry point, write pattern |
| `src/ta_lab2/scripts/signals/generate_signals_atr.py` | ATR generator, structure |
| `src/ta_lab2/scripts/signals/signal_state_manager.py` | State table schema, dirty window pattern |
| `src/ta_lab2/scripts/features/base_feature.py` | write_to_db(), scoped DELETE+INSERT, _get_table_columns() |
| `src/ta_lab2/scripts/features/daily_features_view.py` | FeaturesStore, JOIN query pattern, watermarks |
| `src/ta_lab2/scripts/features/run_all_feature_refreshes.py` | Orchestration pattern, CLI structure |
| `src/ta_lab2/scripts/run_daily_refresh.py` | Top-level orchestrator, subprocess pattern |
| `src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py` | DEFAULT_PERIODS confirmed |
| `src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_cal_from_bars.py` | Calendar DEFAULT_PERIODS confirmed |

---

## Metadata

**Confidence breakdown:**
- Regime module internals: HIGH — all 13 files read directly
- DB table schemas: HIGH — all DDL files read directly
- Signal generator internals: HIGH — all 3 generator files read directly
- EMA periods in pipeline: HIGH — confirmed from both refresh scripts
- Labeler column mapping gap: HIGH — confirmed from feature_utils.py add_ema_pack() vs labels.py df.get()
- Hysteresis stub limitation: HIGH — confirmed from resolver.py code
- Write pattern: HIGH — confirmed from BaseFeature
- Policy table quant assessment: MEDIUM — reasonable conventions, unverified against backtests

**Research date:** 2026-02-20
**Valid until:** 2026-03-22 (stable codebase, 30 day window)
