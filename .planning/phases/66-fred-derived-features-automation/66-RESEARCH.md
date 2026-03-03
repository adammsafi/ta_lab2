# Phase 66: FRED Derived Features & Automation - Research

**Researched:** 2026-03-02
**Domain:** Python/pandas macro feature computation, FRED series processing, PostgreSQL Alembic migrations, daily refresh orchestration
**Confidence:** HIGH

---

## Summary

Phase 66 extends the Phase 65 foundation (`ta_lab2.macro`) to add seven more feature groups
(FRED-08 through FRED-17) and completes the automation loop. The codebase is well-understood
through direct inspection: all existing patterns, conventions, and extension points are confirmed
from source files.

The work divides into three tightly coupled areas:
1. **Database**: one new Alembic migration adding ~30 columns to `fred.fred_macro_features`
2. **Computation**: extend `feature_computer.py` with a new function for FRED-08 to FRED-16;
   update `fred_reader.py` (SERIES_TO_LOAD), `forward_fill.py` (FFILL_LIMITS), and
   the warmup constant in `refresh_macro_features.py`
3. **Automation**: FRED-17 is largely already done — `run_daily_refresh.py` has
   `run_macro_features()` wired into `--all` mode at the correct position (after desc_stats,
   before regimes). Verification confirms correct ordering; only the summary log is missing.

**Primary recommendation:** Add a `compute_derived_features_66()` function in
`feature_computer.py` (separate from the existing `compute_derived_features()` so Phase 65
features stay testable in isolation). Call it from `compute_macro_features()` after the
existing computation. Add the new series to SERIES_TO_LOAD, FFILL_LIMITS, and the db_columns
whitelist in one consistent pass.

---

## Standard Stack

All tools are already present in the project — no new dependencies.

### Core
| Library | Version (project) | Purpose | Why Standard |
|---------|------------------|---------|--------------|
| pandas | 2.x | Rolling windows, z-scores, pct_change, ffill | All existing feature code uses pandas |
| sqlalchemy | 2.x | Engine, text(), temp table upserts | Project-wide DB convention |
| psycopg2 | installed | DB driver for upserts | Existing convention (`_to_python`, `_sanitize_dataframe`) |
| alembic | installed | Schema migration | All schema changes go through Alembic |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | installed | NaN checks, `hasattr(v, 'item')` guard | Already used in `_to_python()` |

**Installation:** No new packages needed.

---

## Architecture Patterns

### Existing Module Structure (established by Phase 65)
```
src/ta_lab2/macro/
├── __init__.py           # Exports load_series_wide, forward_fill_with_limits, compute_macro_features
├── fred_reader.py        # SERIES_TO_LOAD, load_series_wide() -- add 7 new series here
├── forward_fill.py       # FFILL_LIMITS, SOURCE_FREQ -- add entries for new series here
└── feature_computer.py   # compute_derived_features(), compute_macro_features() -- extend here

src/ta_lab2/scripts/macro/
└── refresh_macro_features.py  # CLI: WARMUP_DAYS needs increasing; summary log to add

alembic/versions/
└── a1b2c3d4e5f6_fred_macro_features.py  # Phase 65 migration (revision: b3c4d5e6f7a8)
    # Phase 66 migration revises this
```

### Pattern 1: Extending compute_derived_features (CONFIRMED)

Add `compute_derived_features_66()` that accepts the same wide DataFrame (uppercase FRED IDs
as columns) and returns it with new columns appended. Then call it from `compute_macro_features()`.
Keep `compute_derived_features()` (Phase 65) unchanged to preserve test isolation.

```python
# Source: feature_computer.py (existing pattern)

def compute_derived_features_66(df: pd.DataFrame) -> pd.DataFrame:
    """Compute FRED-08 through FRED-16 derived columns."""
    result = df.copy()

    # FRED-08: Credit stress (BAMLH0A0HYM2)
    if "BAMLH0A0HYM2" in result.columns:
        hy = result["BAMLH0A0HYM2"]
        result["hy_oas_level"] = hy
        result["hy_oas_5d_change"] = hy.diff(5)
        # 30d z-score with 80% fill requirement (24/30 days)
        min_periods = int(0.80 * 30)  # = 24
        roll_mean = hy.rolling(30, min_periods=min_periods).mean()
        roll_std = hy.rolling(30, min_periods=min_periods).std()
        result["hy_oas_30d_zscore"] = (hy - roll_mean) / roll_std
    else:
        result["hy_oas_level"] = float("nan")
        result["hy_oas_5d_change"] = float("nan")
        result["hy_oas_30d_zscore"] = float("nan")

    # FRED-09: Financial conditions (NFCI -- weekly)
    if "NFCI" in result.columns:
        nfci = result["NFCI"]
        result["nfci_level"] = nfci
        # 4-week direction: compare to value 28 days ago
        result["nfci_4wk_direction"] = nfci.diff(28).apply(
            lambda x: "rising" if x > 0 else ("falling" if x < 0 else None)
            if x == x else None  # NaN check
        )
    else:
        result["nfci_level"] = float("nan")
        result["nfci_4wk_direction"] = None

    # FRED-10: M2 money supply YoY (M2SL -- monthly, forward-filled)
    if "M2SL" in result.columns:
        m2 = result["M2SL"]
        # YoY = pct change vs 365 days ago
        result["m2_yoy_pct"] = m2.pct_change(365) * 100.0
    else:
        result["m2_yoy_pct"] = float("nan")

    # FRED-11: Carry trade (DEXJPUS -- daily)
    if "DEXJPUS" in result.columns:
        jpy = result["DEXJPUS"]
        result["dexjpus_level"] = jpy
        result["dexjpus_5d_pct_change"] = jpy.pct_change(5) * 100.0
        result["dexjpus_20d_vol"] = jpy.pct_change(1).rolling(20, min_periods=16).std() * 100.0
        # Daily z-score of 1d move
        daily_move = jpy.pct_change(1) * 100.0
        roll_mean_dm = daily_move.rolling(20, min_periods=16).mean()
        roll_std_dm = daily_move.rolling(20, min_periods=16).std()
        result["dexjpus_daily_zscore"] = (daily_move - roll_mean_dm) / roll_std_dm
    else:
        result["dexjpus_level"] = float("nan")
        result["dexjpus_5d_pct_change"] = float("nan")
        result["dexjpus_20d_vol"] = float("nan")
        result["dexjpus_daily_zscore"] = float("nan")

    # FRED-12: Net liquidity z-score (net_liquidity must exist from Phase 65)
    if "net_liquidity" in result.columns:
        nl = result["net_liquidity"]
        min_periods_365 = int(0.80 * 365)  # = 292
        roll_mean_nl = nl.rolling(365, min_periods=min_periods_365).mean()
        roll_std_nl = nl.rolling(365, min_periods=min_periods_365).std()
        result["net_liquidity_365d_zscore"] = (nl - roll_mean_nl) / roll_std_nl
        # Dual-window trend: 30d MA vs 150d MA
        ma30 = nl.rolling(30, min_periods=24).mean()
        ma150 = nl.rolling(150, min_periods=120).mean()
        trend = (ma30 - ma150).apply(
            lambda x: "expanding" if x > 0 else ("contracting" if x < 0 else None)
            if x == x else None
        )
        result["net_liquidity_trend"] = trend
    else:
        result["net_liquidity_365d_zscore"] = float("nan")
        result["net_liquidity_trend"] = None

    # FRED-13 + FRED-16: Fed regime + TARGET_MID/TARGET_SPREAD (DFEDTARU, DFEDTARL)
    _compute_fed_regime(result)  # modifies result in-place

    # FRED-14: Carry momentum indicator
    if "dexjpus_20d_vol" in result.columns and "dexjpus_daily_zscore" in result.columns:
        # carry spread = us_jp_rate_spread (computed in Phase 65, now lowercase)
        carry_spread = result.get("us_jp_rate_spread")
        base_z = result["dexjpus_daily_zscore"]
        if carry_spread is not None:
            # Elevated threshold (2.0) when carry spread is positive
            threshold = carry_spread.apply(lambda x: 2.0 if x > 0 else 1.5 if x == x else 1.5)
            result["carry_momentum"] = (base_z.abs() > threshold).astype(float)
            result["carry_momentum"] = result["carry_momentum"].where(base_z.notna(), other=None)
        else:
            result["carry_momentum"] = (base_z.abs() > 2.0).astype(float)
            result["carry_momentum"] = result["carry_momentum"].where(base_z.notna(), other=None)
    else:
        result["carry_momentum"] = float("nan")

    # FRED-15: CPI surprise proxy (CPIAUCSL -- monthly)
    if "CPIAUCSL" in result.columns:
        cpi = result["CPIAUCSL"]
        cpi_mom = cpi.pct_change(30) * 100.0  # approx MoM from monthly ffilled data
        baseline = cpi_mom.rolling(90, min_periods=72).mean()  # 3-month trend
        result["cpi_surprise_proxy"] = cpi_mom - baseline
    else:
        result["cpi_surprise_proxy"] = float("nan")

    return result


def _compute_fed_regime(df: pd.DataFrame) -> None:
    """Compute FRED-13 (fed regime) and FRED-16 (TARGET_MID, TARGET_SPREAD) in-place."""
    has_upper = "DFEDTARU" in df.columns
    has_lower = "DFEDTARL" in df.columns
    has_dff = "DFF" in df.columns

    if has_upper and has_lower:
        upper = df["DFEDTARU"]
        lower = df["DFEDTARL"]

        # FRED-16: TARGET_MID and TARGET_SPREAD
        df["target_mid"] = (upper + lower) / 2.0
        df["target_spread"] = upper - lower

        # FRED-13: Structure-based regime classification
        # Zero-bound: DFEDTARU <= 0.25 (context decision)
        # Single-target: DFEDTARU == DFEDTARL (spread = 0) and not zero-bound
        # Target-range: spread > 0 and not zero-bound
        def classify_structure(row_upper, row_lower):
            if row_upper != row_upper:  # NaN
                return None
            if row_upper <= 0.25:
                return "zero-bound"
            if abs(row_upper - row_lower) < 0.001:
                return "single-target"
            return "target-range"

        df["fed_regime_structure"] = [
            classify_structure(u, l)
            for u, l in zip(upper, lower)
        ]
    else:
        df["target_mid"] = float("nan")
        df["target_spread"] = float("nan")
        df["fed_regime_structure"] = None

    # FRED-13: Trajectory-based regime (hiking/holding/cutting) from DFF 90d change
    if has_dff:
        dff = df["DFF"]
        change_90d = dff.diff(90)
        def classify_trajectory(delta):
            if delta != delta:  # NaN
                return None
            if delta > 0.25:
                return "hiking"
            if delta < -0.25:
                return "cutting"
            return "holding"
        df["fed_regime_trajectory"] = change_90d.apply(classify_trajectory)
    else:
        df["fed_regime_trajectory"] = None
```

### Pattern 2: SERIES_TO_LOAD Extension (CONFIRMED)

```python
# Source: fred_reader.py (existing pattern)
SERIES_TO_LOAD: list[str] = [
    # ... existing Phase 65 series ...

    # Phase 66 additions:
    # FRED-08: Credit stress
    "BAMLH0A0HYM2",   # HY OAS spread (daily)
    # FRED-09: Financial conditions
    "NFCI",           # Chicago Fed NFCI (weekly)
    # FRED-10: M2 money supply
    "M2SL",           # M2 (monthly)
    # FRED-11: Carry trade FX
    "DEXJPUS",        # Yen/Dollar (daily)
    # FRED-13/16: Fed regime
    "DFEDTARU",       # Fed Funds target upper bound (daily)
    "DFEDTARL",       # Fed Funds target lower bound (daily)
    # FRED-15: CPI proxy
    "CPIAUCSL",       # CPI All Items (monthly)
]
```

### Pattern 3: FFILL_LIMITS Extension (CONFIRMED)

```python
# Source: forward_fill.py (existing pattern)
# Add to existing FFILL_LIMITS dict:
FFILL_LIMITS_ADDITIONS = {
    "BAMLH0A0HYM2": 5,    # daily -- same as other daily series
    "NFCI": 10,           # weekly -- same as WALCL, WTREGEN
    "M2SL": 45,           # monthly -- same as IRSTCI01JPM156N
    "DEXJPUS": 5,         # daily
    "DFEDTARU": 5,        # daily (policy rate -- doesn't change often but is daily data)
    "DFEDTARL": 5,        # daily
    "CPIAUCSL": 45,       # monthly
}
```

### Pattern 4: Alembic ALTER TABLE Migration (CONFIRMED PATTERN)

```python
# Source: alembic/versions/a1b2c3d4e5f6_fred_macro_features.py (existing pattern)
# New Phase 66 migration: revision c4d5e6f7a8b9, down_revision b3c4d5e6f7a8

def upgrade() -> None:
    # FRED-08: Credit stress
    op.add_column("fred_macro_features", sa.Column("hy_oas_level", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("hy_oas_5d_change", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("hy_oas_30d_zscore", sa.Float(), nullable=True), schema="fred")
    # FRED-09: Financial conditions
    op.add_column("fred_macro_features", sa.Column("nfci_level", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("nfci_4wk_direction", sa.Text(), nullable=True), schema="fred")
    # FRED-10: M2
    op.add_column("fred_macro_features", sa.Column("m2_yoy_pct", sa.Float(), nullable=True), schema="fred")
    # FRED-11: Carry trade
    op.add_column("fred_macro_features", sa.Column("dexjpus_level", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("dexjpus_5d_pct_change", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("dexjpus_20d_vol", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("dexjpus_daily_zscore", sa.Float(), nullable=True), schema="fred")
    # FRED-12: Net liquidity z-score + trend
    op.add_column("fred_macro_features", sa.Column("net_liquidity_365d_zscore", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("net_liquidity_trend", sa.Text(), nullable=True), schema="fred")
    # FRED-13: Fed regime classification
    op.add_column("fred_macro_features", sa.Column("fed_regime_structure", sa.Text(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("fed_regime_trajectory", sa.Text(), nullable=True), schema="fred")
    # FRED-14: Carry momentum
    op.add_column("fred_macro_features", sa.Column("carry_momentum", sa.Float(), nullable=True), schema="fred")
    # FRED-15: CPI surprise proxy
    op.add_column("fred_macro_features", sa.Column("cpi_surprise_proxy", sa.Float(), nullable=True), schema="fred")
    # FRED-16: TARGET_MID and TARGET_SPREAD (also raw series columns)
    op.add_column("fred_macro_features", sa.Column("target_mid", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("target_spread", sa.Float(), nullable=True), schema="fred")
    # Raw series columns for the 7 new series (forward-filled values)
    op.add_column("fred_macro_features", sa.Column("bamlh0a0hym2", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("nfci", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("m2sl", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("dexjpus", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("dfedtaru", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("dfedtarl", sa.Float(), nullable=True), schema="fred")
    op.add_column("fred_macro_features", sa.Column("cpiaucsl", sa.Float(), nullable=True), schema="fred")
```

### Pattern 5: WARMUP_DAYS Increase (CONFIRMED)

The 365d z-score (FRED-12) requires 365 days of data. With 80% minimum fill, need at minimum
292 days, but for boundary correctness on incremental runs, need warmup to cover the full
window plus the existing Phase 65 warmup needs.

```python
# Source: refresh_macro_features.py (existing)
# Current: WARMUP_DAYS = 60
# Required: at least 365 + buffer for incremental safety
WARMUP_DAYS = 400  # covers 365d z-score window + margin
```

### Pattern 6: Summary Log in refresh_macro_features.py (NEW)

After upsert completes, log a structured summary per the CONTEXT.md requirement:

```python
# After upsert, print a summary log
print(
    f"\n[SUMMARY] Macro feature refresh complete:\n"
    f"  Feature groups: credit_stress (FRED-08), fin_conditions (FRED-09), "
    f"m2 (FRED-10), carry_trade (FRED-11), net_liq_zscore (FRED-12), "
    f"fed_regime (FRED-13/16), carry_momentum (FRED-14), cpi_proxy (FRED-15)\n"
    f"  Rows computed: {rows_computed}\n"
    f"  Rows upserted: {rows_upserted}\n"
    f"  Date range: {start_date} to {end_date}"
)
# Staleness warning if any required series are all-NaN in recent window
```

### Pattern 7: FRED-17 Orchestration (ALREADY DONE)

Confirmed by reading `run_daily_refresh.py` directly:
- `run_macro_features()` function exists (lines 1629-1738)
- `--macro` flag wired (lines 1824-1831)
- `--no-macro` flag exists (lines 1828-1831)
- `run_macro = (args.macro or args.all) and not getattr(args, "no_macro", False)` (line 2072)
- Macro runs after desc_stats (line 2199), before regimes (line 2212) -- correct position
- Invokes `ta_lab2.scripts.macro.refresh_macro_features` module

**FRED-17 only requires verifying this wiring is correct and that the summary log is implemented.**

### Anti-Patterns to Avoid

- **Computing z-scores without min_periods**: Will produce NaN-riddled output at series start. Always use `min_periods=int(0.80 * window)`.
- **Applying pct_change on forward-filled monthly data without awareness**: For M2SL (monthly ffilled to daily), `pct_change(1)` gives 0.0 for all non-release days. Use `pct_change(365)` for YoY.
- **Operating on renamed columns inside compute_derived_features_66**: The function receives uppercase FRED IDs (before renaming). But `net_liquidity` is a derived column added by Phase 65 `compute_derived_features()`. Confirm that `compute_derived_features_66()` is called *after* `compute_derived_features()` and on the pre-renamed DataFrame.
- **Fed trajectory threshold too sensitive**: Using 0.1 instead of 0.25 will label every quarter as hiking/cutting. The 0.25 threshold (one standard 25bp move) aligns with Fed policy convention.
- **Not extending db_columns whitelist**: If new columns aren't added to `db_columns` in `compute_macro_features()`, they get silently dropped before upsert.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rolling z-score | Custom loop | `pandas.Series.rolling().mean()` + `rolling().std()` | Pandas handles NaN, min_periods, boundary correctly |
| Categorical text from numeric thresholds | if/elif chains on scalars | `pd.cut()` (for bins) or vectorized `.apply()` on scalar | Consistent with Phase 65 VIX regime pattern |
| NaN-safe psycopg2 binding | Custom conversion | Existing `_to_python()` + `_sanitize_dataframe()` in `refresh_macro_features.py` | Already handles numpy scalars and float NaN |
| Upsert with new columns | Rewrite upsert | Existing `upsert_macro_features()` | Dynamic SET clause auto-adapts to new columns -- no changes needed |

**Key insight:** The upsert logic (`upsert_macro_features()`) dynamically builds its SET clause
from `df.columns` (line 243: `non_date_cols = [c for c in df.columns if c != "date"]`).
Adding new columns to the DataFrame is sufficient -- the upsert adapts automatically.

---

## Common Pitfalls

### Pitfall 1: net_liquidity ordering dependency

**What goes wrong:** `compute_derived_features_66()` references `result["net_liquidity"]` for
FRED-12. But `net_liquidity` is a derived column added by `compute_derived_features()` (Phase 65).
If `compute_derived_features_66()` is called on the raw wide DataFrame, `net_liquidity` won't
exist yet.

**Why it happens:** The two compute functions are separate, and the execution order matters.

**How to avoid:** In `compute_macro_features()`, call Phase 65 compute first, then Phase 66:
```python
df_derived = compute_derived_features(df_filled)    # adds net_liquidity
df_derived = compute_derived_features_66(df_derived) # reads net_liquidity
```

**Warning signs:** `KeyError: 'net_liquidity'` or `net_liquidity_365d_zscore` always NaN.

### Pitfall 2: DFEDTARU/DFEDTARL are already in fred.series_values (verify)

**What goes wrong:** Assuming these need to be added to the VM collection. The VM-STRATEGY.md
confirms DFEDTARU and DFEDTARL are "Already Collecting" (3 original series: FEDFUNDS, DFEDTARU,
DFEDTARL). They should already be in `fred.series_values`.

**Why it matters:** If the planner creates a task to add them to VM collection, that's wasted work.

**How to avoid:** The only addition needed is to SERIES_TO_LOAD in `fred_reader.py` and
FFILL_LIMITS in `forward_fill.py`. The data is already there.

### Pitfall 3: WARMUP_DAYS too small for 365d z-score

**What goes wrong:** Current WARMUP_DAYS=60 means incremental runs only recompute 60 days back.
The 365d rolling window requires at least 365 days of data to produce non-NaN z-scores.
On incremental runs with a short warmup, the boundary rows will have NaN z-scores even though
enough history exists in the database.

**Why it happens:** The watermark-based window (`watermark - WARMUP_DAYS` to `today`) doesn't
load enough history for the rolling computation.

**How to avoid:** Set `WARMUP_DAYS = 400`. This ensures enough history is loaded on every
incremental run to produce correct z-scores at the boundary.

**Warning signs:** `net_liquidity_365d_zscore` is NaN for recent dates but not-NaN for dates
computed during a `--full` run.

### Pitfall 4: M2SL pct_change with forward-filled daily data

**What goes wrong:** M2SL is monthly, forward-filled to daily. `pct_change(1)` returns 0.0 for
all non-release days and a large step on release days. This is not the YoY figure.

**How to avoid:** Use `pct_change(365)` to compare today's forward-filled M2 value to 365 days
ago. Since M2SL is forward-filled from monthly observations, this gives the correct YoY at
observation points and holds stable between releases.

**Warning signs:** `m2_yoy_pct` shows 0.0 for most days with periodic large spikes.

### Pitfall 5: nfci_4wk_direction using diff on weekly ffilled data

**What goes wrong:** NFCI is weekly, forward-filled up to 10 days. `diff(28)` (4 weeks × 7 days)
compares the current forward-filled value to 28 days ago. If both were filled from the same
observation, `diff(28)` = 0 → "neither rising nor falling" (returns None).

**How to avoid:** This is acceptable and correct behavior. When data is stale (>10 days gap),
NFCI will be NaN, so `diff(28)` will also be NaN, which maps to None in the classification.
The 4-week direction is only meaningful at weekly release intervals.

### Pitfall 6: carry_momentum operates on renamed columns

**What goes wrong:** `compute_derived_features_66()` reads `result["us_jp_rate_spread"]` to
check carry spread for the elevated threshold. But `us_jp_rate_spread` is a derived column
added by Phase 65 as `"us_jp_rate_spread"` (already lowercase in the derived output). However,
`compute_derived_features_66()` receives the DataFrame *before the uppercase→lowercase rename*.
So `"DFF"`, `"WALCL"` etc. are uppercase, but `"net_liquidity"` and `"us_jp_rate_spread"` are
lowercase (added by Phase 65 compute, already named lowercase in the derived step).

**How to avoid:** Confirm: `compute_derived_features()` adds lowercase derived columns to the
uppercase-keyed DataFrame. `compute_derived_features_66()` can read these lowercase derived
columns directly. The rename pass at the end of `compute_macro_features()` only renames
uppercase FRED IDs to lowercase, leaving derived columns (already lowercase) unchanged.

---

## Code Examples

### Rolling Z-Score with 80% min_periods

```python
# Source: direct codebase inspection (pattern from Phase 65 VIX regime + pandas docs)

def _rolling_zscore(series: pd.Series, window: int, min_fill_pct: float = 0.80) -> pd.Series:
    """Compute rolling z-score with minimum fill requirement.

    Args:
        series: Input series (can contain NaN from ffill limits)
        window: Rolling window size in days
        min_fill_pct: Minimum fraction of non-NaN rows required (default: 0.80)

    Returns:
        Z-score series. NaN where insufficient data.
    """
    min_periods = max(1, int(min_fill_pct * window))
    roll_mean = series.rolling(window, min_periods=min_periods).mean()
    roll_std = series.rolling(window, min_periods=min_periods).std()
    return (series - roll_mean) / roll_std
```

### Fed Regime Structure Classification

```python
# Source: fedtools2/etl.py (archive reference) + CONTEXT.md decisions
# fedtools2 used pd.cut on date ranges (era-based). Phase 66 uses data-based classification.

# Zero-bound: DFEDTARU <= 0.25 (CONTEXT.md locked decision)
# Single-target: spread (DFEDTARU - DFEDTARL) effectively zero
# Target-range: spread > 0 (post-2008)

# Historical reference from VM-STRATEGY.md:
# "Already Collecting: FEDFUNDS (monthly), DFEDTARU (daily), DFEDTARL (daily)"
# Phase 66 adds DFEDTARU and DFEDTARL to SERIES_TO_LOAD for local computation.

ZERO_BOUND_THRESHOLD = 0.25  # CONTEXT.md: "Zero-bound defined as DFEDTARU <= 0.25%"
SINGLE_TARGET_SPREAD_TOL = 0.001  # floats: treat as single-target if spread < 0.001
HIKING_THRESHOLD_90D = 0.25   # 90d DFF change > 0.25pp = hiking (one standard Fed move)
CUTTING_THRESHOLD_90D = -0.25  # 90d DFF change < -0.25pp = cutting
```

### Summary Log Pattern (matching existing code style)

```python
# Source: refresh_macro_features.py main() -- matches existing [OK]/[WARN] print style

# After upsert completes, add:
feature_groups = [
    ("FRED-08 credit_stress", ["hy_oas_level", "hy_oas_5d_change", "hy_oas_30d_zscore"]),
    ("FRED-09 fin_conditions", ["nfci_level", "nfci_4wk_direction"]),
    ("FRED-10 m2", ["m2_yoy_pct"]),
    ("FRED-11 carry_trade", ["dexjpus_level", "dexjpus_5d_pct_change", "dexjpus_20d_vol", "dexjpus_daily_zscore"]),
    ("FRED-12 net_liq", ["net_liquidity_365d_zscore", "net_liquidity_trend"]),
    ("FRED-13/16 fed_regime", ["fed_regime_structure", "fed_regime_trajectory", "target_mid", "target_spread"]),
    ("FRED-14 carry_momentum", ["carry_momentum"]),
    ("FRED-15 cpi_proxy", ["cpi_surprise_proxy"]),
]
print(f"\n[SUMMARY] Feature groups computed: {len(feature_groups)}")
for name, cols in feature_groups:
    populated = sum(1 for c in cols if c in df.columns and df[c].notna().any())
    print(f"  {name}: {populated}/{len(cols)} columns populated")
# Staleness check: warn if critical columns are all-NaN in last 7 days
recent = df.tail(7)
for col in ["hy_oas_level", "nfci_level", "dexjpus_level"]:
    if col in recent.columns and recent[col].isna().all():
        print(f"[WARN] {col} is all-NaN in last 7 rows -- check FRED sync for source series")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `fedtools2` date-range-based regime (era bins) | Data-driven: DFEDTARU structure + DFF trajectory | Phase 66 | More robust; handles current policy correctly |
| WARMUP_DAYS=60 (Phase 65) | WARMUP_DAYS=400 | Phase 66 | Covers 365d z-score boundary correctly |
| No summary log | Structured summary with feature group breakdown | Phase 66 | CONTEXT.md requirement |

**No deprecated items in this phase.** Phase 65 patterns are extended, not replaced.

---

## Open Questions

1. **nfci_4wk_direction NULL vs "neutral" label**
   - What we know: CONTEXT.md says "4-week direction (rising/falling)" -- only two values mentioned
   - What's unclear: What to label when diff == 0.0 exactly (rare but possible)
   - Recommendation: Return None (NULL in DB) for exact-zero; "rising"/"falling" for non-zero. Matches project convention of NULL over spurious labels.

2. **carry_momentum as binary (0/1) vs continuous zscore**
   - What we know: FRED-14 spec says "carry momentum indicator" with "elevated threshold at 2.0 when carry spread positive". Could be binary flag or continuous zscore.
   - What's unclear: Whether Phase 67 wants a binary flag or the raw normalized value
   - Recommendation: Store as Float (the raw z-score of the daily move), not a 0/1 flag. Downstream can apply their own threshold. The "elevated threshold" logic should inform column documentation, not limit stored precision.

3. **CPI surprise proxy fill on non-release days**
   - What we know: CPIAUCSL is monthly, forward-filled to daily. CPI MoM computed on forward-filled data will show 0.0 change on non-release days.
   - What's unclear: CONTEXT.md marks this as Claude's discretion.
   - Recommendation: Forward-fill the last computed `cpi_surprise_proxy` value (same limit as CPIAUCSL: 45 days). This gives the "most recently known CPI surprise" on non-release days, which is what a trader would use.

---

## Sources

### Primary (HIGH confidence)

- `src/ta_lab2/macro/feature_computer.py` -- Full existing implementation, confirmed patterns
- `src/ta_lab2/macro/fred_reader.py` -- SERIES_TO_LOAD confirmed, extension point clear
- `src/ta_lab2/macro/forward_fill.py` -- FFILL_LIMITS confirmed; SOURCE_FREQ already has NFCI, CPIAUCSL, M2SL entries
- `src/ta_lab2/scripts/macro/refresh_macro_features.py` -- WARMUP_DAYS=60, upsert pattern, staleness check
- `src/ta_lab2/scripts/run_daily_refresh.py` -- run_macro_features() confirmed wired at line 2203 (after desc_stats, before regimes)
- `alembic/versions/a1b2c3d4e5f6_fred_macro_features.py` -- Existing migration, revision b3c4d5e6f7a8; Phase 66 migration revises this
- `.archive/external-packages/2026-02-03/fedtools2/src/fedtools2/etl.py` -- Reference for TARGET_MID/TARGET_SPREAD/regime computation logic
- `.planning/VM-STRATEGY.md` -- Confirms DFEDTARU/DFEDTARL already collected; all 7 new series confirmed in VM

### Secondary (MEDIUM confidence)

- `.planning/phases/66-fred-derived-features-automation/66-CONTEXT.md` -- Zero-bound threshold (0.25), hiking/holding/cutting thresholds (Claude's discretion), 80% min_periods policy

### Tertiary (LOW confidence)

- None -- all findings are from direct codebase inspection.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries are project-existing, no new dependencies
- Architecture: HIGH -- all extension points confirmed from source code
- Pitfalls: HIGH -- identified from actual code paths and existing pattern analysis
- Fed regime classification: MEDIUM -- threshold values are Claude's discretion per CONTEXT.md; recommended values (0.25pp 90d change) are conventional Fed policy increments
- CPI surprise fill behavior: MEDIUM -- Claude's discretion per CONTEXT.md; recommendation follows forward-fill convention established in Phase 65

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (stable domain -- 30 days)

---

## Complete Column Inventory for Phase 66

### New raw series columns (7 series, lowercase)
| Column | Source | Type |
|--------|--------|------|
| `bamlh0a0hym2` | BAMLH0A0HYM2 (daily) | Float |
| `nfci` | NFCI (weekly, ffill=10) | Float |
| `m2sl` | M2SL (monthly, ffill=45) | Float |
| `dexjpus` | DEXJPUS (daily) | Float |
| `dfedtaru` | DFEDTARU (daily) | Float |
| `dfedtarl` | DFEDTARL (daily) | Float |
| `cpiaucsl` | CPIAUCSL (monthly, ffill=45) | Float |

### New derived columns (FRED-08 through FRED-16)
| Column | FRED Req | Source | Type |
|--------|----------|--------|------|
| `hy_oas_level` | FRED-08 | BAMLH0A0HYM2 | Float |
| `hy_oas_5d_change` | FRED-08 | BAMLH0A0HYM2 diff(5) | Float |
| `hy_oas_30d_zscore` | FRED-08 | BAMLH0A0HYM2 rolling z | Float |
| `nfci_level` | FRED-09 | NFCI | Float |
| `nfci_4wk_direction` | FRED-09 | NFCI diff(28) sign | Text |
| `m2_yoy_pct` | FRED-10 | M2SL pct_change(365) | Float |
| `dexjpus_level` | FRED-11 | DEXJPUS | Float |
| `dexjpus_5d_pct_change` | FRED-11 | DEXJPUS pct_change(5) | Float |
| `dexjpus_20d_vol` | FRED-11 | DEXJPUS 20d rolling vol | Float |
| `dexjpus_daily_zscore` | FRED-11 | DEXJPUS 1d move z-score | Float |
| `net_liquidity_365d_zscore` | FRED-12 | net_liquidity 365d z | Float |
| `net_liquidity_trend` | FRED-12 | MA30 vs MA150 direction | Text |
| `fed_regime_structure` | FRED-13 | DFEDTARU/DFEDTARL rules | Text |
| `fed_regime_trajectory` | FRED-13 | DFF 90d change | Text |
| `carry_momentum` | FRED-14 | dexjpus_daily_zscore vs threshold | Float |
| `cpi_surprise_proxy` | FRED-15 | CPIAUCSL MoM - 3mo baseline | Float |
| `target_mid` | FRED-16 | (DFEDTARU+DFEDTARL)/2 | Float |
| `target_spread` | FRED-16 | DFEDTARU-DFEDTARL | Float |

### Total Phase 66 additions: 25 columns (7 raw + 18 derived)
### Total fred_macro_features after Phase 66: ~52 columns

---

## FRED-17 Wiring Verification

Confirmed from `run_daily_refresh.py` direct inspection:

```
Pipeline order in --all mode (lines 2124-2299):
1. bars (optional)
2. emas (optional)
3. amas (optional)
4. desc_stats (optional)
5. MACRO FEATURES (lines 2199-2210)  <- correct position
6. regimes (optional)
7. features
8. signals
9. portfolio
10. executor
11. drift
12. stats
```

**FRED-17 is complete except for the summary log.** The planner only needs to add the
summary log to `refresh_macro_features.py` -- no orchestration wiring work is needed.
