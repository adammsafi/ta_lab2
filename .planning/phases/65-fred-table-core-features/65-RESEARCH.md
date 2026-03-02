# Phase 65: FRED Table & Core Features - Research

**Researched:** 2026-03-02
**Domain:** FRED macro feature table — daily-aligned wide table in `fred` schema of marketdata DB
**Confidence:** HIGH

---

## Summary

Phase 65 builds `fred_macro_features` — a single wide daily table in the marketdata database's `fred` schema. The table is the read surface for all downstream macro consumers (macro regime classifier in Phase 67, risk gates in Phase 71, dashboard in Phase 72). It aggregates 39 FRED raw series from `fred.series_values` (already synced via `sync_fred_from_vm.py`) into forward-filled, derived, provenance-tracked daily rows.

The core infrastructure is almost entirely in place. The `fred` schema already exists in marketdata (proven by `sync_fred_from_vm.py` writing to `fred.series_values`, `fred.releases`, and `fred.sync_log` successfully). Alembic migrations operate on this same DB. The sync pipeline is functional and incremental. What is missing is: (1) WTREGEN in the VM series list, (2) the `fred_macro_features` table itself (Alembic migration required), (3) the Python module that reads `fred.series_values`, forward-fills, and computes derived features, and (4) the `--macro` stage in `run_daily_refresh.py`.

**Primary recommendation:** Wide table (one row per date, one column per feature) in `fred` schema of marketdata. Use pandas `ffill(limit=N)` on a full calendar date range at compute time. Write to DB with `ON CONFLICT (date) DO UPDATE`. Add `ingested_at` and `days_since_source` provenance columns. Defer FRED-12 (net liquidity z-score) to Phase 66 per roadmap.

---

## Standard Stack

No new pip dependencies are needed. Everything is available in the current venv.

### Core (already installed)

| Library | Installed Version | Purpose | Why Standard |
|---------|------------------|---------|--------------|
| pandas | 2.3.3 | Time-series pivot, reindex to daily, ffill with limit | Project standard; `ffill(limit=N)` on DatetimeIndex is the right tool |
| numpy | 2.4.1 | Threshold arithmetic for VIX regime and rate spreads | Project standard |
| SQLAlchemy | 2.0+ | Read `fred.series_values`, write `fred.fred_macro_features` | Project standard; all DB writes use this |
| psycopg2 (raw) | installed | COPY-based bulk upsert when needed | Used in `sync_fred_from_vm.py` already |
| Alembic | 1.18+ | Schema migration (required per CONTEXT.md) | Project standard; all table creation goes through Alembic |

### No New Dependencies

The existing stack covers 100% of the Phase 65 domain:

| Capability | How Covered | Library |
|-----------|-------------|---------|
| Forward-fill with limit | `df.ffill(limit=N)` | pandas 2.3.3 (already installed) |
| Full calendar date range | `pd.date_range(start, end, freq='D')` + `.reindex()` | pandas |
| Rolling delta (5d slope change) | `df['T10Y2Y'].diff(5)` | pandas |
| VIX threshold labeling | `pd.cut()` or `np.where()` | pandas/numpy |
| Rate spread arithmetic | Column subtraction after ffill | pandas |
| DB reads/writes | `pd.read_sql()`, `engine.begin()` + `op.execute()` | SQLAlchemy |
| Schema migration | `op.create_table()` with schema param | Alembic |
| Incremental watermark | `SELECT MAX(date) FROM fred.fred_macro_features` | SQLAlchemy text() |

**Installation:** No new packages. Zero changes to `pyproject.toml`.

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
└── macro/
    ├── __init__.py
    ├── fred_reader.py         # Reads fred.series_values -> wide pandas DataFrame
    ├── forward_fill.py        # ffill with limit, source_freq tagging, staleness
    └── feature_computer.py   # Derived feature computation (spreads, VIX regime, etc.)

src/ta_lab2/scripts/
└── macro/
    ├── __init__.py
    └── refresh_macro_features.py  # CLI entry: incremental compute + upsert

alembic/versions/
└── [hash]_fred_macro_features.py  # Creates fred.fred_macro_features table
```

### Pattern 1: Wide Table, fred Schema

**What:** `fred.fred_macro_features` stores one row per calendar date. Each feature is a separate column (not a long EAV format).

**When to use:** Always for this phase. The requirements name specific columns (T10Y2Y, VIX_REGIME, NET_LIQUIDITY, etc.). Downstream consumers (macro regime classifier in Phase 67) will write SQL like `SELECT date, T10Y2Y, VIX_REGIME FROM fred.fred_macro_features WHERE date = CURRENT_DATE`. Wide format enables direct, readable queries. The long format would require pivoting on every read.

**Why not long (series_id, date, value):** That is what `fred.series_values` already is — the raw staging table. `fred_macro_features` is the computed, derived, forward-filled read surface. Wide = computed output. Long = raw input.

**Why fred schema, not public:** `fred.series_values`, `fred.releases`, and `fred.sync_log` already live in the `fred` schema. `fred_macro_features` logically belongs with its sibling tables. The `public` schema is reserved for per-asset tables (`cmc_*`). Keeping FRED tables in `fred` schema maintains clear separation.

**Table schema (decided):**
```sql
-- via Alembic migration
CREATE TABLE fred.fred_macro_features (
    date               DATE        NOT NULL,

    -- Forward-filled raw series (used directly as features)
    walcl              DOUBLE PRECISION,  -- weekly, ffill(limit=10)
    wtregen            DOUBLE PRECISION,  -- weekly TGA, ffill(limit=10)
    rrpontsyd          DOUBLE PRECISION,  -- daily (no ffill needed)
    dff                DOUBLE PRECISION,  -- daily
    dgs10              DOUBLE PRECISION,  -- daily
    t10y2y             DOUBLE PRECISION,  -- daily (stored directly per FRED-05)
    vixcls             DOUBLE PRECISION,  -- daily
    dtwexbgs           DOUBLE PRECISION,  -- daily
    ecbdfr             DOUBLE PRECISION,  -- daily
    irstci01jpm156n    DOUBLE PRECISION,  -- monthly, ffill(limit=45)
    irltlt01jpm156n    DOUBLE PRECISION,  -- monthly, ffill(limit=45)

    -- Net Liquidity (FRED-03)
    net_liquidity           DOUBLE PRECISION,  -- WALCL - WTREGEN - RRPONTSYD

    -- Rate spread features (FRED-04)
    us_jp_rate_spread       DOUBLE PRECISION,  -- DFF - ffill(IRSTCI01JPM156N)
    us_ecb_rate_spread      DOUBLE PRECISION,  -- DFF - ECBDFR
    us_jp_10y_spread        DOUBLE PRECISION,  -- DGS10 - ffill(IRLTLT01JPM156N)

    -- Yield curve features (FRED-05)
    yc_slope_change_5d      DOUBLE PRECISION,  -- T10Y2Y - T10Y2Y[5d ago]

    -- VIX regime (FRED-06)
    vix_regime              TEXT,              -- 'calm' / 'elevated' / 'crisis'

    -- Dollar strength (FRED-07)
    dtwexbgs_5d_change      DOUBLE PRECISION,  -- 5-day change in DTWEXBGS
    dtwexbgs_20d_change     DOUBLE PRECISION,  -- 20-day change in DTWEXBGS

    -- Provenance columns (FRED-02)
    source_freq_walcl       TEXT,  -- 'weekly'
    source_freq_wtregen     TEXT,  -- 'weekly'
    source_freq_irstci01    TEXT,  -- 'monthly'
    source_freq_irltlt01    TEXT,  -- 'monthly'
    days_since_walcl        INTEGER,  -- days since last WALCL observation
    days_since_wtregen      INTEGER,  -- days since last WTREGEN observation

    -- Metadata
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (date)
);
```

**Note on scope for Phase 65:** Only include the raw series columns needed for FRED-03 through FRED-07. Phase 66 adds BAMLH0A0HYM2, NFCI, M2SL, DEXJPUS, etc. Design the migration to accept future ALTER TABLE ADD COLUMN commands without structural change.

### Pattern 2: Compute-Time Forward-Fill (not storage-time)

**What:** Forward-fill happens in Python at feature compute time, not when raw series are written to `fred.series_values`. The raw table stays sparse (actual observation dates only). The wide feature table is the dense, filled output.

**When to use:** Always. This is the pattern chosen in CONTEXT.md.

**Example:**
```python
# Source: compute-time forward-fill pattern
import pandas as pd
from sqlalchemy import text

def load_series_wide(engine, series_ids: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    """Load fred.series_values for requested series, pivot to wide, ffill to daily cadence."""
    query = text("""
        SELECT series_id, date, value
        FROM fred.series_values
        WHERE series_id = ANY(:ids)
          AND date >= :start_date
          AND date <= :end_date
        ORDER BY series_id, date
    """)
    with engine.connect() as conn:
        df_long = pd.read_sql(query, conn, params={
            "ids": series_ids,
            "start_date": start_date,
            "end_date": end_date,
        })

    # Pivot to wide: index=date, columns=series_id, values=value
    df_wide = df_long.pivot(index="date", columns="series_id", values="value")
    df_wide.index = pd.to_datetime(df_wide.index)

    # Reindex to full calendar date range (fill weekends/holidays)
    full_range = pd.date_range(df_wide.index.min(), df_wide.index.max(), freq="D")
    df_wide = df_wide.reindex(full_range)

    return df_wide


def forward_fill_with_limits(df_wide: pd.DataFrame) -> pd.DataFrame:
    """Apply frequency-appropriate forward-fill limits per series."""
    FFILL_LIMITS = {
        # Weekly series: 10-day limit
        "WALCL": 10, "WTREGEN": 10, "NFCI": 10, "STLFSI4": 10, "ICSA": 10,
        # Monthly series: 45-day limit
        "IRSTCI01JPM156N": 45, "IRLTLT01JPM156N": 45, "CPIAUCSL": 45, "M2SL": 45,
        "IRSTCI01GBM156N": 45, "IR3TIB01CHM156N": 45, "IRLTLT01DEM156N": 45,
        # Daily series: no limit (already daily, but apply small limit for calendar gaps)
        "DFF": 5, "DGS10": 5, "T10Y2Y": 5, "VIXCLS": 5, "DTWEXBGS": 5,
        "ECBDFR": 5, "RRPONTSYD": 5,
    }
    for col in df_wide.columns:
        limit = FFILL_LIMITS.get(col, 5)
        df_wide[col] = df_wide[col].ffill(limit=limit)
    return df_wide
```

### Pattern 3: Incremental Computation

**What:** On each refresh run, compute only dates after `MAX(date)` in `fred_macro_features`. Use the watermark query pattern (same as EMA refreshers and AMA refreshers). However, because forward-fill requires lookback context (e.g., 5-day slope change needs 5 prior dates, and forward-fill needs prior observations), load a warm-up window of max(45 + rolling_window) days before the watermark.

**When to use:** Every refresh run.

**Example:**
```python
# Source: project pattern from AMA/EMA refreshers
def get_compute_start(engine) -> str:
    """Get the date from which to recompute. Returns watermark - warmup window."""
    WARMUP_DAYS = 60  # covers 45d monthly ffill + 20d rolling window
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT MAX(date) FROM fred.fred_macro_features"
        ))
        max_date = result.scalar()
    if max_date is None:
        # First run: start from earliest available FRED data
        return "2000-01-01"
    # Load warmup window so ffill and rolling windows have context
    start = pd.Timestamp(max_date) - pd.Timedelta(days=WARMUP_DAYS)
    return start.strftime("%Y-%m-%d")


def upsert_macro_features(engine, df: pd.DataFrame) -> int:
    """Upsert rows into fred.fred_macro_features. Returns row count written."""
    rows = df.reset_index().rename(columns={"index": "date"})
    rows["date"] = rows["date"].dt.date  # ensure date type, not timestamp

    with engine.begin() as conn:
        # Use temp table + INSERT...ON CONFLICT pattern (project standard)
        conn.execute(text("""
            CREATE TEMP TABLE _macro_staging (LIKE fred.fred_macro_features INCLUDING DEFAULTS)
            ON COMMIT DROP
        """))
        rows.to_sql("_macro_staging", conn, if_exists="append", index=False, method="multi")
        result = conn.execute(text("""
            INSERT INTO fred.fred_macro_features
            SELECT * FROM _macro_staging
            ON CONFLICT (date) DO UPDATE SET
                walcl = EXCLUDED.walcl,
                wtregen = EXCLUDED.wtregen,
                net_liquidity = EXCLUDED.net_liquidity,
                us_jp_rate_spread = EXCLUDED.us_jp_rate_spread,
                us_ecb_rate_spread = EXCLUDED.us_ecb_rate_spread,
                us_jp_10y_spread = EXCLUDED.us_jp_10y_spread,
                t10y2y = EXCLUDED.t10y2y,
                yc_slope_change_5d = EXCLUDED.yc_slope_change_5d,
                vix_regime = EXCLUDED.vix_regime,
                dtwexbgs = EXCLUDED.dtwexbgs,
                dtwexbgs_5d_change = EXCLUDED.dtwexbgs_5d_change,
                dtwexbgs_20d_change = EXCLUDED.dtwexbgs_20d_change,
                days_since_walcl = EXCLUDED.days_since_walcl,
                days_since_wtregen = EXCLUDED.days_since_wtregen,
                ingested_at = now()
        """))
    return result.rowcount
```

### Pattern 4: Calendar Coverage — Fill Weekends and Holidays

**What:** Fill all calendar days (Monday through Sunday), not just business days. This is the correct choice for crypto (24/7 trading) and for macro-crypto regime consumers.

**Rationale:** The regime classifier (Phase 67), risk engine (Phase 71), and dashboard (Phase 72) run against crypto bars that include weekends. If `fred_macro_features` only has business days, joins on Saturday and Sunday dates fail. Forward-filled values on weekends are the correct representation (WALCL from last Wednesday is the best available estimate on Saturday).

**Implementation:** `pd.date_range(start, end, freq='D')` then `df.reindex(full_range)` then `ffill(limit=N)`.

### Pattern 5: WTREGEN VM Addition

**What:** WTREGEN (Treasury General Account, FRED series ID: WTREGEN) must be added to the VM's FRED pull list before Phase 65 can compute the full net liquidity formula. WTREGEN is a weekly H.4.1 release (same release as WALCL — published every Thursday for the prior Wednesday). TGA can be backfilled from 2000 via the FRED API.

**How VM update works:**
The VM runs `~/fred_pull.py` via systemd timer with `FRED_SERIES` env var listing series to collect. Adding WTREGEN requires:
1. SSH into VM: `ssh -i ~/.ssh/google_compute_engine adammsafi_gmail_com@104.196.168.124`
2. Update the FRED_SERIES list in the systemd service or the env file
3. Run a one-time backfill: `python fred_pull.py series` (incremental from last known date, or full since start=2000-01-01)
4. Run `sync_fred_from_vm.py` locally to pull the new series into `fred.series_values`

**Series to add:** WTREGEN only (per CONTEXT.md — the 39 existing series already include WALCL and RRPONTSYD).

### Anti-Patterns to Avoid

- **Long format for fred_macro_features:** The raw series are already long in `fred.series_values`. Don't repeat that structure in the derived features table. Wide = readable, queryable by downstream SQL.
- **DDL-in-code (no Alembic):** CONTEXT.md explicitly requires Alembic migration. Do not use `CREATE TABLE IF NOT EXISTS` in Python scripts.
- **Storage-time forward-fill:** Do not modify `fred.series_values` rows. Keep raw data raw. Fill at compute time.
- **Recomputing all history on every refresh:** Use watermark + warmup window. 208K raw rows across 39 series is small, but the pattern matters for Phase 66+ when derived series multiply.
- **Blocking daily refresh on SSH failure:** FRED sync failure should warn-and-continue. If FRED data is stale by less than 48h, proceed with cached values. Only error if data is completely absent.
- **Computing net liquidity without WTREGEN:** The formula must be WALCL - WTREGEN - RRPONTSYD (not just WALCL - RRPONTSYD). The phase spec is explicit. Adding WTREGEN to VM is a pre-step, not optional.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Time-series reindex to daily | Custom calendar generator | `pd.date_range(freq='D')` + `.reindex()` | pandas built-in, handles all edge cases |
| Forward-fill with limits | Custom rolling fill | `df.ffill(limit=N)` | pandas built-in, O(N), zero bugs |
| Upsert / ON CONFLICT | Custom DELETE+INSERT | Temp table + `INSERT ... ON CONFLICT DO UPDATE` | Project-standard pattern from EMA/AMA refreshers |
| Rolling delta (5d change) | Manual offset indexing | `df['col'].diff(5)` | pandas built-in, handles NaN at start |
| VIX regime binning | If/elif chain | `pd.cut(df['vixcls'], bins=[0,15,25,float('inf')], labels=['calm','elevated','crisis'])` | Handles edges correctly |
| DB connection management | Custom connection pool | `engine.begin()` context manager | Project-standard; NullPool for scripts |
| Alembic migration writing | Raw psql DDL | `op.create_table()` with `schema="fred"` | Required by CONTEXT.md; enables downgrade() |

**Key insight:** The 39-series FRED dataset is small (208K rows). Performance is not the constraint. Correctness of forward-fill limits and stale-input handling is.

---

## Common Pitfalls

### Pitfall 1: Missing Warmup Window in Incremental Mode

**What goes wrong:** If you compute from `MAX(date)` in `fred_macro_features`, the `YC_SLOPE_CHANGE_5D` (5-day delta of T10Y2Y) will be NULL for the first 5 days of any incremental run. Similarly, forward-fill of monthly series (limit=45) requires up to 45 prior calendar days of context.

**Why it happens:** Rolling operations on a windowed DataFrame start producing NaN at the beginning of the window.

**How to avoid:** Load a warm-up window of at least `max(45, rolling_window_max) + 5` calendar days before the watermark. Compute features over the full window, but only upsert rows `>= watermark` (or upsert all — ON CONFLICT DO UPDATE idempotently overwrites).

**Warning signs:** `YC_SLOPE_CHANGE_5D` is NULL for the most recent dates after an incremental run.

### Pitfall 2: Alembic Schema Targeting for Non-Default Schema

**What goes wrong:** Alembic migrations that don't specify `schema="fred"` will create tables in `public` by default. `op.create_table("fred_macro_features", ...)` creates `public.fred_macro_features`, not `fred.fred_macro_features`.

**Why it happens:** Alembic's `op.create_table()` defaults to `search_path` schema (usually `public`).

**How to avoid:** Always pass `schema="fred"` to `op.create_table()`, `op.create_index()`, `op.add_column()`, and `op.drop_table()`.

**Example:**
```python
# Correct
op.create_table(
    "fred_macro_features",
    sa.Column("date", sa.Date(), nullable=False),
    # ... columns ...
    schema="fred",           # <-- required
)
op.create_unique_constraint("uq_fred_macro_date", "fred_macro_features", ["date"], schema="fred")

# Wrong -- creates in public schema
op.create_table("fred_macro_features", ...)
```

### Pitfall 3: NaN in Derived Features When One Input is NaN

**What goes wrong:** `net_liquidity = walcl - wtregen - rrpontsyd`. If WTREGEN has a gap (newly added series, or temporary FRED API delay), the entire net_liquidity column becomes NaN even though WALCL and RRPONTSYD are fine.

**Why it happens:** Pandas arithmetic propagates NaN.

**How to avoid:** Per CONTEXT.md decision: "Use last known (forward-fill) when a component is temporarily missing." Apply `ffill(limit=10)` to WTREGEN before computing the formula. Net liquidity is undefined only if ALL three inputs are stale, or if a single input has been stale for longer than its fill limit.

**Warning signs:** `net_liquidity` is NULL for multiple consecutive dates when WALCL/RRPONTSYD are not NULL.

### Pitfall 4: VIX Regime on NaN VIX

**What goes wrong:** `pd.cut()` on a Series containing NaN returns NaN for those positions. The VIX (VIXCLS) is daily but has weekends as NaN before forward-fill. If VIX forward-fill is applied after regime labeling, labels are wrong on weekends.

**Why it happens:** Operation ordering matters: ffill must precede derived feature computation.

**How to avoid:** Always apply all forward-fills before computing any derived column. Order: (1) load raw series, (2) reindex to daily, (3) ffill with limits, (4) compute derived features.

### Pitfall 5: Duplicate Revision IDs in Alembic Chain

**What goes wrong:** The new migration file's `down_revision` must point to the current head (`f6a7b8c9d0e1`). If it points elsewhere, `alembic upgrade head` skips the new migration or creates a branch.

**Why it happens:** Manually editing the template without checking `alembic heads`.

**How to avoid:** Run `alembic heads` before creating the migration. Set `down_revision = "f6a7b8c9d0e1"` (current head as of 2026-03-02).

### Pitfall 6: WTREGEN Backfill Missing from VM Before Sync

**What goes wrong:** `sync_fred_from_vm.py` runs and correctly reports WTREGEN as a "new series" with 0 rows synced because the VM hasn't collected any WTREGEN data yet.

**Why it happens:** The VM only collects what is in its `FRED_SERIES` env list.

**How to avoid:** The VM update (add WTREGEN to series list + run backfill) must happen BEFORE `sync_fred_from_vm.py` runs and BEFORE `refresh_macro_features.py` runs. This is a dependency ordering constraint within Phase 65.

### Pitfall 7: `days_since_publication` Miscalculation for Forward-Filled Rows

**What goes wrong:** After forward-fill, a row for date 2026-03-05 might be using WALCL data from 2026-02-26 (7 days old). The `days_since_walcl` column should reflect 7, not 0. Computing this as `date - max_walcl_date_in_series_values` requires a join or pre-computation step.

**How to avoid:** When forward-filling, track the "source date" alongside the value. A clean approach: create a `walcl_source_date` column (the actual FRED observation date that was forward-filled), then compute `days_since_walcl = (date - walcl_source_date).dt.days`.

```python
# Source: pattern for tracking ffill source date
def ffill_with_source_date(series: pd.Series, limit: int) -> tuple[pd.Series, pd.Series]:
    """Forward-fill a series and track the source observation date."""
    # Make a date series aligned with the series' index
    source_date = series.copy()
    source_date[:] = pd.NaT
    source_date[series.notna()] = series.index[series.notna()]  # date of actual observation
    filled_value = series.ffill(limit=limit)
    filled_source = source_date.ffill(limit=limit)
    return filled_value, filled_source
```

---

## Code Examples

### Full Feature Computation Pipeline

```python
# Source: pattern derived from project conventions + CONTEXT.md requirements

SERIES_TO_LOAD = [
    # Net liquidity components (FRED-03)
    "WALCL", "WTREGEN", "RRPONTSYD",
    # Rate spread components (FRED-04)
    "DFF", "IRSTCI01JPM156N", "ECBDFR", "DGS10", "IRLTLT01JPM156N",
    # Yield curve (FRED-05)
    "T10Y2Y",
    # VIX regime (FRED-06)
    "VIXCLS",
    # Dollar strength (FRED-07)
    "DTWEXBGS",
]

FFILL_LIMITS = {
    "WALCL": 10, "WTREGEN": 10, "RRPONTSYD": 5,
    "DFF": 5, "ECBDFR": 5, "DGS10": 5, "T10Y2Y": 5,
    "VIXCLS": 5, "DTWEXBGS": 5,
    "IRSTCI01JPM156N": 45, "IRLTLT01JPM156N": 45,
}

SOURCE_FREQ = {
    "WALCL": "weekly", "WTREGEN": "weekly", "NFCI": "weekly", "STLFSI4": "weekly",
    "IRSTCI01JPM156N": "monthly", "IRLTLT01JPM156N": "monthly",
    # All others: "daily"
}


def compute_macro_features(engine, start_date: str, end_date: str) -> pd.DataFrame:
    """Load FRED series, forward-fill, compute Phase 65 derived features."""

    # 1. Load raw series from fred.series_values
    query = text("""
        SELECT series_id, date, value
        FROM fred.series_values
        WHERE series_id = ANY(:ids)
          AND date >= :start_date
          AND date <= :end_date
        ORDER BY series_id, date
    """)
    with engine.connect() as conn:
        df_long = pd.read_sql(
            query, conn,
            params={"ids": SERIES_TO_LOAD, "start_date": start_date, "end_date": end_date}
        )
    df_long["date"] = pd.to_datetime(df_long["date"])

    # 2. Pivot to wide
    df = df_long.pivot(index="date", columns="series_id", values="value")
    df.index.name = "date"

    # 3. Reindex to full calendar range
    full_range = pd.date_range(df.index.min(), df.index.max(), freq="D")
    df = df.reindex(full_range)

    # 4. Forward-fill with frequency-appropriate limits
    for col in df.columns:
        limit = FFILL_LIMITS.get(col, 5)
        df[col] = df[col].ffill(limit=limit)

    # 5. Compute provenance: days_since per tracked weekly/monthly series
    for col in ["WALCL", "WTREGEN"]:
        if col in df.columns:
            source_dates = df[col].copy()
            source_dates[:] = pd.NaT
            notna_mask = df_long[df_long["series_id"] == col].set_index("date")["value"].notna()
            actual_dates = notna_mask.index[notna_mask]
            source_dates[actual_dates] = actual_dates
            source_dates = source_dates.ffill(limit=FFILL_LIMITS[col])
            df[f"days_since_{col.lower()}"] = (df.index - source_dates).dt.days

    # 6. Compute derived features

    # FRED-03: Net Liquidity Proxy
    df["net_liquidity"] = df["WALCL"] - df["WTREGEN"] - df["RRPONTSYD"]

    # FRED-04: Rate Spreads
    df["us_jp_rate_spread"] = df["DFF"] - df["IRSTCI01JPM156N"]
    df["us_ecb_rate_spread"] = df["DFF"] - df["ECBDFR"]
    df["us_jp_10y_spread"] = df["DGS10"] - df["IRLTLT01JPM156N"]

    # FRED-05: Yield Curve Features (T10Y2Y level is already stored; compute slope change)
    df["yc_slope_change_5d"] = df["T10Y2Y"].diff(5)

    # FRED-06: VIX Regime
    df["vix_regime"] = pd.cut(
        df["VIXCLS"],
        bins=[0, 15, 25, float("inf")],
        labels=["calm", "elevated", "crisis"],
        right=True,
    ).astype(str)
    df.loc[df["VIXCLS"].isna(), "vix_regime"] = None

    # FRED-07: Dollar Strength Changes
    df["dtwexbgs_5d_change"] = df["DTWEXBGS"].diff(5)
    df["dtwexbgs_20d_change"] = df["DTWEXBGS"].diff(20)

    # 7. Rename columns to lowercase (DB convention)
    rename_map = {
        "WALCL": "walcl", "WTREGEN": "wtregen", "RRPONTSYD": "rrpontsyd",
        "DFF": "dff", "DGS10": "dgs10", "T10Y2Y": "t10y2y",
        "VIXCLS": "vixcls", "DTWEXBGS": "dtwexbgs", "ECBDFR": "ecbdfr",
        "IRSTCI01JPM156N": "irstci01jpm156n", "IRLTLT01JPM156N": "irltlt01jpm156n",
    }
    df = df.rename(columns=rename_map)

    # 8. Add source_freq provenance columns
    for col in ["walcl", "wtregen"]:
        df[f"source_freq_{col}"] = "weekly"
    for col in ["irstci01jpm156n", "irltlt01jpm156n"]:
        df[f"source_freq_{col}"] = "monthly"

    return df
```

### Alembic Migration Pattern (fred schema)

```python
# Source: Alembic pattern from project -- note schema="fred" on all ops
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    # Ensure fred schema exists (idempotent)
    op.execute("CREATE SCHEMA IF NOT EXISTS fred")

    op.create_table(
        "fred_macro_features",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("walcl", sa.Float(), nullable=True),
        sa.Column("wtregen", sa.Float(), nullable=True),
        sa.Column("rrpontsyd", sa.Float(), nullable=True),
        sa.Column("dff", sa.Float(), nullable=True),
        sa.Column("dgs10", sa.Float(), nullable=True),
        sa.Column("t10y2y", sa.Float(), nullable=True),
        sa.Column("vixcls", sa.Float(), nullable=True),
        sa.Column("dtwexbgs", sa.Float(), nullable=True),
        sa.Column("ecbdfr", sa.Float(), nullable=True),
        sa.Column("irstci01jpm156n", sa.Float(), nullable=True),
        sa.Column("irltlt01jpm156n", sa.Float(), nullable=True),
        # Derived features
        sa.Column("net_liquidity", sa.Float(), nullable=True),
        sa.Column("us_jp_rate_spread", sa.Float(), nullable=True),
        sa.Column("us_ecb_rate_spread", sa.Float(), nullable=True),
        sa.Column("us_jp_10y_spread", sa.Float(), nullable=True),
        sa.Column("yc_slope_change_5d", sa.Float(), nullable=True),
        sa.Column("vix_regime", sa.Text(), nullable=True),
        sa.Column("dtwexbgs_5d_change", sa.Float(), nullable=True),
        sa.Column("dtwexbgs_20d_change", sa.Float(), nullable=True),
        # Provenance
        sa.Column("source_freq_walcl", sa.Text(), nullable=True),
        sa.Column("source_freq_wtregen", sa.Text(), nullable=True),
        sa.Column("source_freq_irstci01jpm156n", sa.Text(), nullable=True),
        sa.Column("source_freq_irltlt01jpm156n", sa.Text(), nullable=True),
        sa.Column("days_since_walcl", sa.Integer(), nullable=True),
        sa.Column("days_since_wtregen", sa.Integer(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("date"),
        schema="fred",  # <-- CRITICAL
    )

    op.create_index(
        "idx_fred_macro_features_date",
        "fred_macro_features",
        [sa.text("date DESC")],
        schema="fred",
    )


def downgrade() -> None:
    op.drop_index("idx_fred_macro_features_date", table_name="fred_macro_features", schema="fred")
    op.drop_table("fred_macro_features", schema="fred")
```

### Daily Refresh Stage Addition

```python
# Source: run_daily_refresh.py pattern — add macro stage before regimes

TIMEOUT_MACRO = 300  # 5 minutes -- small dataset, fast computation

def run_macro_feature_refresh(args, db_url: str) -> ComponentResult:
    """Run FRED macro feature refresh via subprocess. Runs before regimes."""
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.macro.refresh_macro_features",
    ]
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")

    # ... (same ComponentResult pattern as all other stages) ...
```

**Pipeline order in `run_daily_refresh.py` with Phase 65:**
```
bars -> EMAs -> AMAs -> desc_stats -> [FRED sync check] -> macro_features -> regimes -> features -> signals -> portfolio -> executor -> drift -> stats
```

FRED sync (via `sync_fred_from_vm.py`) runs on its own independent schedule. The daily refresh only checks staleness and warns if FRED data is >48h old. It does NOT block on FRED sync completing.

### Staleness Check Pattern

```python
# Source: pattern derived from refresh_utils.py bar freshness check

def check_fred_staleness(engine, warn_hours: float = 48.0) -> tuple[bool, str]:
    """Check if fred.series_values has recent data. Returns (is_fresh, message)."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT MAX(date) as max_date,
                   EXTRACT(EPOCH FROM (now() - MAX(date)::timestamp)) / 3600 as hours_ago
            FROM fred.series_values
            WHERE series_id = 'DFF'  -- daily series as freshness proxy
        """))
        row = result.fetchone()

    if row is None or row[0] is None:
        return False, "No FRED data in fred.series_values"

    hours_ago = float(row[1])
    if hours_ago > warn_hours:
        return False, f"FRED data is {hours_ago:.1f}h old (DFF max_date={row[0]})"
    return True, f"FRED data fresh ({hours_ago:.1f}h old)"
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| freddata_local FDW bridge | SSH COPY via sync_fred_from_vm.py | Phase 65 design | FDW was live-query only (fails when tunnel down). SSH COPY + local tables is durable. |
| WALCL - RRPONTSYD (2-component) | WALCL - WTREGEN - RRPONTSYD (3-component) | Post-2022 TGA buildup | WTREGEN (TGA) became significant (~$800B peak in 2023). Omitting it overstates net liquidity. |
| Long EAV table for derived features | Wide table (one column per feature) | Phase 65 design | Downstream SQL consumers (Phase 67 macro regime) are simpler and faster with wide format. |
| No macro data in marketdata | fred_macro_features table in fred schema | Phase 65 | Closes the dead-end in the component map (see ARCHITECTURE.md). |

**Not changing (deferred to Phase 66):**
- Net liquidity z-score (FRED-12): rolling 365d z-score and dual-window trend. Roadmap assigns this to Phase 66. Phase 65 stores raw net_liquidity.
- Credit stress (FRED-08), Financial conditions (FRED-09), M2 (FRED-10), Carry trade (FRED-11): Phase 66 adds these columns to fred_macro_features via ALTER TABLE.

---

## Open Questions

1. **Does `fred` schema already exist in marketdata?**
   - What we know: `sync_fred_from_vm.py` writes to `fred.series_values`, `fred.releases`, and `fred.sync_log` in the marketdata DB. The script would fail if the schema didn't exist.
   - What's unclear: Whether the schema was created manually (outside Alembic) or via some undocumented migration.
   - Recommendation: Add `op.execute("CREATE SCHEMA IF NOT EXISTS fred")` in the Alembic migration upgrade(). This is idempotent and safe even if the schema already exists.

2. **Does WTREGEN backfill need to happen before the migration or after?**
   - What we know: WTREGEN is weekly on FRED. The VM only collects what's in its series list. Series list update + backfill is a manual one-time step.
   - What's unclear: Whether WTREGEN data is already present in `fred.series_values` from a prior ad-hoc load.
   - Recommendation: The migration should proceed regardless. The compute script should handle the case where WTREGEN has no rows (log a WARNING, set net_liquidity to NULL for affected dates, don't fail the entire refresh).

3. **`source_freq` per-column vs one generic column?**
   - What we know: CONTEXT.md says "store source_freq column." The research note above stores individual `source_freq_walcl`, `source_freq_wtregen`, etc.
   - What's unclear: Whether downstream consumers need per-column provenance or just a generic staleness signal.
   - Recommendation: Store per-series provenance columns for the forward-filled series (WALCL, WTREGEN, IRSTCI01JPM156N, IRLTLT01JPM156N). The daily series don't need source_freq columns — their frequency is implicit. This satisfies the CONTEXT.md requirement without overcomplicating the schema.

---

## Sources

### Primary (HIGH confidence)

- Direct codebase analysis:
  - `src/ta_lab2/scripts/etl/sync_fred_from_vm.py` — existing FRED sync mechanism (SSH COPY, incremental, upsert pattern)
  - `src/ta_lab2/scripts/run_daily_refresh.py` — ComponentResult pattern, pipeline ordering
  - `alembic/versions/f6a7b8c9d0e1_portfolio_tables.py` — current Alembic head, migration structure
  - `alembic/env.py` — confirmed: no `include_schemas`, `target_metadata=None` (handwritten migrations only)
  - `src/ta_lab2/scripts/features/feature_state_manager.py` — watermark/incremental pattern
  - `.planning/VM-STRATEGY.md` — 39-series list, WTREGEN, VM infrastructure details
  - `.planning/REQUIREMENTS.md` — FRED-01 through FRED-17 requirements text
  - `.planning/research/STACK.md` — confirmed zero new pip dependencies needed
  - `.planning/research/ARCHITECTURE.md` — fred schema placement, component map, fred.series_values confirmed in marketdata
  - `.planning/research/FEATURES.md` — ffill limits (45d monthly, 10d weekly), VIX thresholds confirmed

### Secondary (MEDIUM confidence)

- `.planning/phases/65-fred-table-core-features/65-CONTEXT.md` — locked decisions: wide vs long (discretion), alembic required, derived-only in fred_macro_features, ffill limits, belt-and-suspenders refresh
- `.planning/phases/15-economic-data-strategy/` — Phase 15 research confirming fredapi bypass, postgresql as the read surface

### Tertiary (LOW confidence — not used for binding decisions)

- External: TradingView net liquidity formula, DurdenBTC (net liquidity = WALCL - TGA - RRP consensus formula). VIX thresholds (calm <15, elevated 15-25, crisis >25) are widely agreed upon in quantitative research.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies; existing stack verified from installed packages
- Table schema: HIGH — wide format and fred schema proven by existing code patterns
- Architecture patterns: HIGH — direct source code analysis of analogous phases (EMA refreshers, AMA refreshers)
- Pitfalls: HIGH — specific bugs (Alembic schema, NaN propagation, warmup window) derived from code analysis
- WTREGEN VM step: HIGH — VM infrastructure documented in VM-STRATEGY.md, series ID confirmed in FRED

**Research date:** 2026-03-02
**Valid until:** 2026-04-01 (stable ecosystem — pandas ffill API, Alembic schema ops, FRED series IDs are stable)

---

## Phase 65 Scope Boundary (Critical for Planning)

**In Phase 65 (FRED-01 through FRED-07):**
- fred_macro_features table creation (Alembic migration)
- WTREGEN added to VM collection (manual step + sync)
- 11 raw FRED columns stored (those needed for FRED-03 through FRED-07 derivations)
- 8 derived feature columns: net_liquidity, us_jp_rate_spread, us_ecb_rate_spread, us_jp_10y_spread, yc_slope_change_5d, vix_regime, dtwexbgs_5d_change, dtwexbgs_20d_change
- Provenance: days_since_walcl, days_since_wtregen, source_freq_* columns
- refresh_macro_features.py script (incremental compute + upsert)
- --macro stage added to run_daily_refresh.py (warn-and-continue on FRED staleness)
- Staleness check: warn if DFF max_date > 48h old

**Deferred to Phase 66 (FRED-08 through FRED-17):**
- Net liquidity 365d z-score and dual-window trend (FRED-12)
- Credit stress columns: BAMLH0A0HYM2 level, 5d change, 30d z-score (FRED-08)
- Financial conditions: NFCI level + 4-week direction (FRED-09)
- M2 money supply YoY change (FRED-10)
- Carry trade features: DEXJPUS level, 5d change, 20d vol, daily z-score (FRED-11)
- Fed regime classification (FRED-13)
- Carry momentum (FRED-14), CPI surprise proxy (FRED-15), TARGET_MID/SPREAD (FRED-16)
- run_daily_refresh.py wiring with FRED sync trigger (FRED-17)
