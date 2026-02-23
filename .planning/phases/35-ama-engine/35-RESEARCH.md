# Phase 35: AMA Engine - Research

**Researched:** 2026-02-23
**Domain:** Adaptive Moving Averages (KAMA, DEMA, TEMA, HMA) — computation, DDL, pipeline wiring
**Confidence:** HIGH (codebase read directly; formulas verified from canonical sources)

---

## Summary

Phase 35 extends the existing EMA table family with a new AMA (Adaptive Moving Average) table family. The implementation is a close structural sibling of the EMA infrastructure: same table naming conventions, same sync_utils.py pattern, same BaseEMARefresher orchestration template, same z-score post-processing via refresh_returns_zscore.py.

The primary divergence from EMAs is the PK: AMA tables include `indicator TEXT` (e.g., "KAMA", "DEMA", "TEMA", "HMA") and `params_hash TEXT` (MD5 of sorted params dict) alongside `(id, ts, tf)`. This allows multiple parameter sets per indicator type to coexist in a single table without collision. The EMA PK used `period INTEGER`; the AMA PK replaces period with `(indicator, params_hash)`.

DEMA and TEMA are compositional EMAs (they build on standard EWM), while KAMA and HMA require custom iterative loops that cannot use pandas `ewm()`. This creates two implementation tracks within the AMA feature module. The warmup requirement is the most significant per-indicator difference: HMA needs `sqrt(period)` bars minimum, KAMA needs `er_period` bars, DEMA needs `2*period`, TEMA needs `3*period`.

**Primary recommendation:** Build `BaseAMAFeature` as a sibling class to `BaseEMAFeature` (not a subclass — different PK columns require different `_get_pk_columns()` and `_pg_upsert()` logic). Reuse `EMAComputationOrchestrator`, `WorkerTask`, `sync_utils.py`, and `refresh_returns_zscore.py` unmodified.

---

## Standard Stack

The AMA engine uses no new external libraries. All dependencies are already installed.

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | installed | DataFrame operations, rolling windows, EWM for DEMA/TEMA base | All existing feature code uses pandas |
| numpy | installed | Vectorized KAMA and HMA loops (faster than Python for-loop) | EMA operations already vectorized with numpy |
| sqlalchemy | installed | DB connections, upsert via pg_insert | Existing pattern throughout |
| psycopg2 | installed | PostgreSQL driver | Existing pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| hashlib (stdlib) | stdlib | MD5 for params_hash | Computing params_hash from indicator params dict |
| json (stdlib) | stdlib | Serialize params dict before hashing | Canonical JSON for consistent hash |
| multiprocessing (stdlib) | stdlib | NullPool parallel workers | Same pattern as EMA refreshers |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Single `cmc_ama_multi_tf` table with `indicator` column | Separate tables per indicator | Single table is easier to sync, query, and maintain; no JOIN needed to compare KAMA vs HMA |
| MD5 for params_hash | SHA256 | MD5 is sufficient (32 chars, no security concern); SHA256 is 64 chars. MD5 chosen for brevity. |
| New BaseAMARefresher | Extend BaseEMARefresher | BaseEMARefresher hardcodes `periods: list[int]` in WorkerTask — AMA needs `indicators + param_sets` instead. Sibling class reuses orchestrator/state patterns without fighting the base. |

**Installation:** No new packages needed. All dependencies present.

---

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/
├── features/
│   └── ama/                           # NEW — mirrors features/m_tf/
│       ├── __init__.py
│       ├── base_ama_feature.py        # BaseAMAFeature (sibling of BaseEMAFeature)
│       ├── ama_computations.py        # Pure functions: compute_kama(), compute_dema(), compute_tema(), compute_hma()
│       ├── ama_params.py              # AMAParamSet dataclass + params_hash computation
│       └── ama_multi_timeframe.py     # MultiTFAMAFeature (first concrete subclass)
│
└── scripts/
    └── amas/                          # NEW — mirrors scripts/emas/
        ├── __init__.py
        ├── base_ama_refresher.py      # BaseAMARefresher (mirrors BaseEMARefresher)
        ├── ama_state_manager.py       # AMAStateManager (mirrors EMAStateManager)
        ├── refresh_cmc_ama_multi_tf.py
        ├── refresh_cmc_ama_multi_tf_cal_from_bars.py
        ├── refresh_cmc_ama_multi_tf_cal_anchor_from_bars.py
        ├── sync_cmc_ama_multi_tf_u.py
        └── run_all_ama_refreshes.py

sql/ddl/
├── create_cmc_ama_multi_tf.sql        # Value table + state table
├── create_cmc_ama_multi_tf_cal.sql    # cal_us + cal_iso value tables
├── create_cmc_ama_multi_tf_cal_anchor.sql  # cal_anchor_us + cal_anchor_iso
├── create_cmc_ama_multi_tf_u.sql      # Unified _u value table
├── create_cmc_returns_ama_multi_tf.sql
├── create_cmc_returns_ama_multi_tf_cal.sql
├── create_cmc_returns_ama_multi_tf_cal_anchor.sql
└── create_cmc_returns_ama_multi_tf_u.sql
```

### Pattern 1: params_hash Computation

**What:** MD5 of a canonical JSON representation of the indicator's parameters dict, sorted by key.

**When to use:** Every time a row is written to cmc_ama_multi_tf. Used as the PK discriminator for multiple parameter sets.

**Example:**
```python
# Source: hashlib stdlib + json stdlib
import hashlib
import json

def compute_params_hash(params: dict) -> str:
    """
    Compute stable MD5 hash of params dict.
    Keys sorted for canonicality. Returns 32-char hex string.

    Examples:
        compute_params_hash({"er_period": 10, "fast": 2, "slow": 30}) -> "a3f..."
        compute_params_hash({"period": 21}) -> "b7c..."
    """
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(canonical.encode()).hexdigest()

# Usage per indicator:
KAMA_CANONICAL = {"er_period": 10, "fast_period": 2, "slow_period": 30}
KAMA_FAST      = {"er_period": 5,  "fast_period": 2, "slow_period": 15}
KAMA_SLOW      = {"er_period": 20, "fast_period": 2, "slow_period": 50}

# DEMA/TEMA/HMA — period is the only param:
DEMA_21 = {"period": 21}
HMA_50  = {"period": 50}
```

**CRITICAL:** The params dict must be the FULL canonical form. Never use subsets. Once in production, changing the dict structure changes the hash and orphans historical rows.

### Pattern 2: AMA PK vs EMA PK

EMA PK: `(id, tf, ts, period)` — period is an integer.
AMA PK: `(id, ts, tf, indicator, params_hash)` — indicator is text, params_hash is text.

The `period` concept is embedded inside the params_hash for DEMA/TEMA/HMA. For KAMA, the equivalent is `er_period`. There is NO `period` column in AMA tables — querying "all DEMA-21" means `WHERE indicator = 'DEMA' AND params_hash = '<hash_of_period_21>'`.

**Implication for dim_ama_params:** Create a `dim_ama_params` lookup table (Claude's discretion in CONTEXT.md). This is strongly recommended because params_hash is opaque — without a lookup table, there is no human-readable way to identify what "a3f7..." means.

```sql
-- Recommended: dim_ama_params lookup table
CREATE TABLE IF NOT EXISTS public.dim_ama_params (
    indicator   TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    params_json JSONB NOT NULL,   -- full params as JSON for inspection
    label       TEXT,             -- human label e.g. "KAMA(10,2,30)"
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (indicator, params_hash)
);
```

### Pattern 3: KAMA Computation (numpy vectorized loop)

**What:** Kaufman Adaptive Moving Average — efficiency ratio scales the smoothing constant dynamically.

**When to use:** Wherever KAMA rows are needed. Warmup: `er_period` bars minimum (NULL guard until enough bars).

**Exact formula:**
```python
# Source: Kaufman (1995) "Smarter Trading", verified against investopedia/pandas-ta reference
import numpy as np

def compute_kama(
    close: np.ndarray,
    er_period: int = 10,
    fast_period: int = 2,
    slow_period: int = 30,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute KAMA and Efficiency Ratio.

    Returns:
        (kama, er) — both arrays of length len(close), NaN for warmup rows.

    Formula:
        Direction = abs(close[i] - close[i - er_period])
        Volatility = sum(abs(close[j] - close[j-1]) for j in [i-er_period+1..i])
        ER[i] = Direction / Volatility  (0 when Volatility == 0)

        fast_sc = 2 / (fast_period + 1)   # e.g. 2/3 for fast=2
        slow_sc = 2 / (slow_period + 1)   # e.g. 2/31 for slow=30
        SC[i]   = (ER[i] * (fast_sc - slow_sc) + slow_sc) ** 2

        KAMA[er_period-1] = close[er_period-1]   # seed with first valid close
        KAMA[i]           = KAMA[i-1] + SC[i] * (close[i] - KAMA[i-1])
    """
    n = len(close)
    kama = np.full(n, np.nan)
    er   = np.full(n, np.nan)

    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)

    # Compute ER for all valid positions
    for i in range(er_period - 1, n):
        direction  = abs(close[i] - close[i - er_period + 1])
        volatility = np.sum(np.abs(np.diff(close[i - er_period + 1 : i + 1])))
        er[i]      = direction / volatility if volatility != 0 else 0.0

    # Seed and propagate KAMA
    kama[er_period - 1] = close[er_period - 1]
    for i in range(er_period, n):
        sc        = (er[i] * (fast_sc - slow_sc) + slow_sc) ** 2
        kama[i]   = kama[i-1] + sc * (close[i] - kama[i-1])

    return kama, er

# WARMUP GUARD: rows where kama is NaN stay NaN in DB (NULL).
# The SUCCESS CRITERION "rows with insufficient warmup data are NULL rather
# than computed from stale state" is satisfied by np.full(n, np.nan) init.
```

**Warmup threshold:** `er_period` bars. For canonical (10,2,30): 10 bars. This is the minimum before KAMA produces a valid value.

### Pattern 4: DEMA and TEMA Computation (compositional EWM)

**What:** Double and Triple EMA — built from pandas `ewm()`, no custom loop needed.

**When to use:** For DEMA/TEMA computation. Warmup: `2*period` for DEMA, `3*period` for TEMA (conservative; EWM technically has no hard cutoff but results are meaningless below these thresholds).

**Exact formula:**
```python
# Source: Mulloy (1994) "Smoothing Data with Faster Moving Averages" (Technical Analysis)
import pandas as pd

def compute_dema(close: pd.Series, period: int) -> pd.Series:
    """
    DEMA = 2 * EMA(close, period) - EMA(EMA(close, period), period)

    Uses pandas ewm(span=period, adjust=False) for EWM consistency with
    existing EMA infrastructure (adjust=False matches standard EMA definition).

    Warmup guard: first (2*period - 1) rows are NaN-seeded naturally by EWM.
    The explicit guard: set rows < (2*period - 1) to NaN to be safe.
    """
    alpha = 2.0 / (period + 1)
    ema1 = close.ewm(alpha=alpha, adjust=False).mean()
    ema2 = ema1.ewm(alpha=alpha, adjust=False).mean()
    dema = 2 * ema1 - ema2
    # Guard: insufficient warmup
    dema.iloc[:max(0, 2 * period - 1)] = np.nan
    return dema


def compute_tema(close: pd.Series, period: int) -> pd.Series:
    """
    TEMA = 3*EMA1 - 3*EMA2 + EMA3
    where EMA2 = EMA(EMA1), EMA3 = EMA(EMA2)

    Warmup guard: first (3*period - 1) rows set to NaN.
    """
    alpha = 2.0 / (period + 1)
    ema1 = close.ewm(alpha=alpha, adjust=False).mean()
    ema2 = ema1.ewm(alpha=alpha, adjust=False).mean()
    ema3 = ema2.ewm(alpha=alpha, adjust=False).mean()
    tema = 3 * ema1 - 3 * ema2 + ema3
    tema.iloc[:max(0, 3 * period - 1)] = np.nan
    return tema
```

**CRITICAL — alpha consistency:** The existing EMA infrastructure uses `alpha = 2/(period+1)` (see `ema_operations.py:calculate_alpha_from_period()`). DEMA/TEMA must use the same alpha convention for consistency. Do NOT use `ewm(span=period)` — use `ewm(alpha=alpha, adjust=False)` to match.

### Pattern 5: HMA Computation (WMA-based, not EWM)

**What:** Hull Moving Average — uses Weighted Moving Average (WMA), not EWM. Uses `sqrt(period)` for the final smoothing.

**When to use:** For HMA computation. Warmup: `period` bars minimum (the longest WMA window).

**Exact formula:**
```python
# Source: Alan Hull (2005) alanhull.com — verified against pandas-ta HMA implementation
import numpy as np
import pandas as pd

def _wma(series: pd.Series, period: int) -> pd.Series:
    """
    Weighted Moving Average: linearly weighted, more recent = more weight.
    weights = [1, 2, 3, ..., period] — period-th bar has highest weight.
    """
    weights = np.arange(1, period + 1, dtype=float)
    def _apply(x):
        return np.dot(x, weights) / weights.sum()
    return series.rolling(window=period, min_periods=period).apply(_apply, raw=True)


def compute_hma(close: pd.Series, period: int) -> pd.Series:
    """
    HMA(period):
        half_period = max(1, int(period / 2))
        sqrt_period = max(2, int(math.sqrt(period)))
        wma_half    = WMA(close, half_period)
        wma_full    = WMA(close, period)
        raw         = 2 * wma_half - wma_full
        hma         = WMA(raw, sqrt_period)

    Warmup guard: first (period - 1) rows are NaN from WMA rolling window.
    The sqrt_period WMA adds another (sqrt_period - 1) warmup rows.
    Total warmup: approximately period + sqrt(period) - 2 rows before first valid HMA.
    """
    import math
    half_period = max(1, int(period / 2))
    sqrt_period = max(2, int(math.sqrt(period)))

    wma_half = _wma(close, half_period)
    wma_full = _wma(close, period)
    raw      = 2 * wma_half - wma_full
    hma      = _wma(raw, sqrt_period)
    return hma
    # NaN is naturally produced by rolling min_periods — no explicit guard needed.
```

**CRITICAL — WMA not EWM:** HMA uses linear weights, not exponential decay. Do NOT use `pandas ewm()` for HMA. Rolling `apply()` with raw=True is the correct approach. This is slower than ewm() but mathematically correct.

**Performance note:** For 109 TFs x N assets, the rolling WMA apply() is the slowest computation. Profile first. If needed, switch to a numpy convolution-based WMA that avoids Python-level rolling.apply() overhead.

### Pattern 6: AMA Table DDL — Value Tables

The AMA value tables differ from EMA value tables in exactly two columns: `indicator TEXT` and `params_hash TEXT` replace `period INTEGER`. The `er` (Efficiency Ratio) column is added for KAMA rows (NULL for non-KAMA indicators).

**Example DDL for cmc_ama_multi_tf:**
```sql
CREATE TABLE IF NOT EXISTS public.cmc_ama_multi_tf (
    id            INTEGER NOT NULL,
    tf            TEXT    NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    indicator     TEXT    NOT NULL,   -- 'KAMA', 'DEMA', 'TEMA', 'HMA'
    params_hash   TEXT    NOT NULL,   -- MD5 of sorted params JSON
    tf_days       INTEGER,
    roll          BOOLEAN NOT NULL DEFAULT FALSE,
    ama           DOUBLE PRECISION,  -- the AMA value
    d1            DOUBLE PRECISION,
    d2            DOUBLE PRECISION,
    d1_roll       DOUBLE PRECISION,
    d2_roll       DOUBLE PRECISION,
    er            DOUBLE PRECISION,  -- Efficiency Ratio (KAMA only, NULL for others)
    is_partial_end BOOLEAN,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, ts, tf, indicator, params_hash)
);

CREATE INDEX IF NOT EXISTS ix_cmc_ama_multi_tf_indicator
    ON public.cmc_ama_multi_tf (indicator, params_hash, tf, ts);

CREATE INDEX IF NOT EXISTS ix_cmc_ama_multi_tf_roll_true
    ON public.cmc_ama_multi_tf (id, tf, indicator, params_hash, ts)
    WHERE roll = TRUE;
```

**Calendar variant tables** (cal_us, cal_iso, cal_anchor_us, cal_anchor_iso) have the same schema. No schema changes needed for calendar variants.

### Pattern 7: AMA Unified (_u) Table DDL

The _u table adds `alignment_source TEXT NOT NULL` to the PK (same as cmc_ema_multi_tf_u pattern, where alignment_source tracks origin table).

```sql
CREATE TABLE IF NOT EXISTS public.cmc_ama_multi_tf_u (
    id              INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    tf              TEXT NOT NULL,
    indicator       TEXT NOT NULL,
    params_hash     TEXT NOT NULL,
    alignment_source TEXT NOT NULL DEFAULT 'multi_tf',
    tf_days         INTEGER,
    roll            BOOLEAN NOT NULL DEFAULT FALSE,
    ama             DOUBLE PRECISION,
    d1              DOUBLE PRECISION,
    d2              DOUBLE PRECISION,
    d1_roll         DOUBLE PRECISION,
    d2_roll         DOUBLE PRECISION,
    er              DOUBLE PRECISION,
    is_partial_end  BOOLEAN,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, ts, tf, indicator, params_hash, alignment_source)
);
```

NOTE: The EMA _u table does NOT include alignment_source in its PK per the codebase note ("alignment_source is part of PK on _u tables but NOT on base tables"). The AMA _u table should follow this same convention.

### Pattern 8: AMA Returns Table DDL

The AMA returns tables differ from EMA returns tables in the PK: `indicator` and `params_hash` replace `period`. The AMA value column is `ama` (not `ema`), so return column names change from `ret_arith_ema` to `ret_arith_ama`.

**Simplified example:**
```sql
CREATE TABLE IF NOT EXISTS public.cmc_returns_ama_multi_tf (
    id          bigint NOT NULL,
    ts          timestamptz NOT NULL,
    tf          text NOT NULL,
    tf_days     integer NOT NULL,
    indicator   text NOT NULL,
    params_hash text NOT NULL,
    roll        boolean NOT NULL,

    gap_days              integer,
    gap_days_roll         integer,

    -- ama canonical (roll=FALSE)
    delta1_ama            double precision,
    delta2_ama            double precision,
    ret_arith_ama         double precision,
    delta_ret_arith_ama   double precision,
    ret_log_ama           double precision,
    delta_ret_log_ama     double precision,

    -- ama roll (ALL rows)
    delta1_ama_roll            double precision,
    delta2_ama_roll            double precision,
    ret_arith_ama_roll         double precision,
    delta_ret_arith_ama_roll   double precision,
    ret_log_ama_roll           double precision,
    delta_ret_log_ama_roll     double precision,

    -- Z-scores (30, 90, 365 — same pattern as EMA returns)
    ret_arith_ama_zscore_30       double precision,
    ret_log_ama_zscore_30         double precision,
    ret_arith_ama_roll_zscore_30  double precision,
    ret_log_ama_roll_zscore_30    double precision,
    -- ... _90, _365 variants ...

    is_outlier boolean,
    ingested_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (id, ts, tf, indicator, params_hash)
);
```

### Pattern 9: Sync Pattern via sync_utils.py

The existing `sync_utils.py:sync_sources_to_unified()` works for AMA tables WITHOUT MODIFICATION. The function discovers columns dynamically via `information_schema.columns` and builds the INSERT...SELECT from whatever columns the source and target share.

```python
# Source: src/ta_lab2/scripts/sync_utils.py:sync_sources_to_unified()
from ta_lab2.scripts.sync_utils import sync_sources_to_unified

AMA_U_TABLE = "public.cmc_ama_multi_tf_u"
AMA_SOURCES = [
    "public.cmc_ama_multi_tf",
    "public.cmc_ama_multi_tf_cal_us",
    "public.cmc_ama_multi_tf_cal_iso",
    "public.cmc_ama_multi_tf_cal_anchor_us",
    "public.cmc_ama_multi_tf_cal_anchor_iso",
]
AMA_PK_COLS = ["id", "ts", "tf", "indicator", "params_hash", "alignment_source"]
AMA_SOURCE_PREFIX = "cmc_ama_"

sync_sources_to_unified(
    engine=engine,
    u_table=AMA_U_TABLE,
    sources=AMA_SOURCES,
    pk_cols=AMA_PK_COLS,
    source_prefix=AMA_SOURCE_PREFIX,
    log_prefix="ama_sync",
)
# alignment_source is derived as: cmc_ama_multi_tf -> multi_tf
#                                  cmc_ama_multi_tf_cal_us -> multi_tf_cal_us
```

### Pattern 10: Z-score Extension

Adding AMA tables to `refresh_returns_zscore.py` requires:
1. Define `_AMA_CANONICAL_BASE` and `_AMA_ROLL_BASE` pairs (same structure as `_EMA_CANONICAL_BASE`)
2. Define `_AMA_TABLES` list of `TableConfig` objects for all 6 AMA returns tables
3. Add `"amas"` to the `--tables` choices
4. Extend the configs selection block

```python
# Source: src/ta_lab2/scripts/returns/refresh_returns_zscore.py pattern

_AMA_CANONICAL_BASE = [
    ("ret_arith_ama", "ret_arith_ama_zscore"),
    ("ret_log_ama", "ret_log_ama_zscore"),
]
_AMA_ROLL_BASE = [
    ("ret_arith_ama_roll", "ret_arith_ama_roll_zscore"),
    ("ret_log_ama_roll", "ret_log_ama_roll_zscore"),
]

_AMA_TABLES = [
    TableConfig(
        table="public.cmc_returns_ama_multi_tf",
        ts_col="ts",
        pk_cols=["id", "ts", "tf", "indicator", "params_hash"],
        key_cols=["id", "tf", "indicator", "params_hash"],
        canonical_base_pairs=_AMA_CANONICAL_BASE,
        roll_base_pairs=_AMA_ROLL_BASE,
    ),
    # ... repeat for cal_us, cal_iso, cal_anchor_us, cal_anchor_iso, _u
]
```

**CRITICAL:** The `_discover_keys()` function uses `key_cols` for GROUP BY. With AMA, `key_cols` must include `indicator` and `params_hash` — otherwise z-scores would aggregate across different AMA types and parameter sets.

### Pattern 11: run_daily_refresh.py Wiring

Add `--amas` stage between `--emas` and `--regimes`. Pipeline order per CONTEXT.md: bars -> EMAs -> AMAs -> regimes -> features.

```python
# Source: run_daily_refresh.py pattern — add analogous to run_ema_refreshers()

def run_ama_refreshers(args, db_url: str, ids_for_amas: list[int] | None) -> ComponentResult:
    """Run AMA orchestrator via subprocess."""
    script_dir = Path(__file__).parent / "amas"
    cmd = [sys.executable, str(script_dir / "run_all_ama_refreshes.py")]

    if ids_for_amas is None:
        ids_str = "all"
    elif len(ids_for_amas) == 0:
        return ComponentResult(component="amas", success=True, duration_sec=0.0, returncode=0)
    else:
        ids_str = ",".join(str(i) for i in ids_for_amas)

    cmd.extend(["--ids", ids_str])
    if args.verbose:
        cmd.append("--verbose")
    if args.num_processes:
        cmd.extend(["--num-processes", str(args.num_processes)])
    # ... subprocess.run() pattern identical to run_ema_refreshers()

# In main():
p.add_argument("--amas", action="store_true", help="Run AMA refreshers only")
# ...
run_amas = args.amas or args.all
# After EMAs complete:
if run_amas:
    ama_result = run_ama_refreshers(args, db_url, ids_for_emas)
    results.append(("amas", ama_result))
```

### Anti-Patterns to Avoid

- **Using `period` column for DEMA/TEMA/HMA:** Period must be embedded in params_hash and stored in `dim_ama_params`. No raw `period` column in AMA tables — it creates an inconsistency with KAMA which has multiple params.
- **Using `ewm()` for HMA:** HMA is WMA-based. Using EWM produces wrong values — looks plausible but diverges from true HMA.
- **Using `ewm(span=period)` instead of `ewm(alpha=..., adjust=False)`:** The existing EMA infrastructure uses `adjust=False` for consistency with standard EMA. DEMA/TEMA must match.
- **Sharing the `period INTEGER` state table columns:** AMA state table must key on `(id, tf, indicator, params_hash)` not `(id, tf, period)`.
- **Mutable params dict in params_hash:** Always use sorted `json.dumps(sort_keys=True)` before MD5. Never hash `str(dict)` — dict ordering is not guaranteed before Python 3.7 and the string repr is not canonical JSON.
- **Storing Efficiency Ratio in a separate table:** Per AMA-06, ER is a standalone column in `cmc_ama_multi_tf`. It must be queryable without a JOIN.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Parallel worker orchestration | Custom multiprocessing | `EMAComputationOrchestrator` + `WorkerTask` | Already handles NullPool, TF-level splits, error handling |
| _u table sync | Custom INSERT...SELECT | `sync_utils.sync_sources_to_unified()` | Handles watermarks, column discovery, ON CONFLICT DO NOTHING |
| Z-score computation | New z-score logic | Extend `refresh_returns_zscore.py` with `_AMA_TABLES` | Existing code handles window adaptation, outlier flags, UPDATE JOIN pattern |
| State table management | New state tracking | Mirror `EMAStateManager` pattern | Watermark-based incremental refresh already solved |
| DB connection management | Custom pool logic | `NullPool` per worker (existing pattern) | NullPool avoids "too many clients" in multiprocessing |
| Upsert logic | Manual ON CONFLICT | `_pg_upsert()` from `BaseEMAFeature` | PostgreSQL-specific insert with conflict handling |

**Key insight:** The AMA engine is largely a data-topology change (new PK columns) applied to a proven infrastructure. The computation algorithms (KAMA, DEMA, TEMA, HMA) are new, but everything around them is reused.

---

## Common Pitfalls

### Pitfall 1: params_hash Drift

**What goes wrong:** During development, the params dict structure changes (e.g., rename "fast" to "fast_period"). Old rows have hash A, new rows have hash B. Both coexist in the table — queries return incomplete histories silently.

**Why it happens:** MD5 hashes are opaque — no FK constraint enforces the canonical form.

**How to avoid:** Define params dicts as module-level constants in `ama_params.py`. Never construct them inline at call sites. Any dict change is a migration, not a refactor.

**Warning signs:** `dim_ama_params` contains more params_hash values than expected; AMA value counts don't sum to expected total.

### Pitfall 2: WMA Rolling Apply Performance

**What goes wrong:** HMA with `rolling().apply()` takes 10-100x longer than EWM-based indicators on 109 TFs. Full backfill stalls.

**Why it happens:** `rolling().apply()` calls Python for each window, bypassing numpy fast path.

**How to avoid:** Profile HMA on a 1D asset first. If >5s per (id, tf), switch to numpy convolution:
```python
def _wma_numpy(arr: np.ndarray, period: int) -> np.ndarray:
    weights = np.arange(1, period + 1, dtype=float)
    weights /= weights.sum()
    result = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        result[i] = np.dot(arr[i - period + 1 : i + 1], weights)
    return result
```

**Warning signs:** Worker processes timing out; HMA taking >1min per asset.

### Pitfall 3: AMA State Table PK Mismatch

**What goes wrong:** State table is created with `(id, tf, period)` PK (copy-paste from EMA state manager). AMA incremental refresh then reads wrong state or writes duplicate state records.

**Why it happens:** EMAStateManager has the period column hardcoded in its DDL (UNIFIED_STATE_SCHEMA).

**How to avoid:** Create `AMAStateManager` with its own DDL where PK = `(id, tf, indicator, params_hash)`. Do NOT instantiate EMAStateManager for AMA refreshers.

**Warning signs:** `AMAStateManager.load_state()` returns empty despite prior runs.

### Pitfall 4: ER Column NULL for Non-KAMA Rows

**What goes wrong:** A query `WHERE er IS NOT NULL` is assumed to return all KAMA rows, but some KAMA rows near warmup have er = NULL (not enough bars for ER).

**Why it happens:** The er column is NULL for both non-KAMA rows AND KAMA warmup rows. They are indistinguishable.

**How to avoid:** Filter by `indicator = 'KAMA'` first, then `er IS NOT NULL` for valid ER values. Document this in query patterns.

**Warning signs:** ER-based signals producing fewer rows than expected.

### Pitfall 5: Forgetting delta_ret in Returns Columns

**What goes wrong:** The returns table is built with `ret_arith_ama` and `ret_log_ama` but WITHOUT `delta_ret_arith_ama` and `delta_ret_log_ama`. The EMA returns tables include delta columns (second-order return deltas).

**Why it happens:** The minimal returns definition omits delta columns that are visible in `create_cmc_returns_ema_multi_tf.sql`.

**How to avoid:** Mirror the EMA returns DDL exactly: include `delta_ret_arith_ama`, `delta_ret_log_ama`, `delta_ret_arith_ama_roll`, `delta_ret_log_ama_roll`.

### Pitfall 6: Tz-Aware Timestamp in Workers

**What goes wrong:** Workers pass `task.start` as string "2010-01-01" but the state manager returns a tz-aware pandas Timestamp. Mixing naive and aware timestamps in comparisons raises exceptions.

**Why it happens:** `series.values` on tz-aware datetime Series returns tz-NAIVE numpy.datetime64 on Windows (documented in MEMORY.md critical pitfall).

**How to avoid:** In AMAStateManager, use `.tolist()` to get tz-aware Python datetime objects, or apply `.tz_localize("UTC")` on the DatetimeIndex before comparison.

---

## Code Examples

### Verified Pattern: WorkerTask Extension for AMA

The existing `WorkerTask` in `ema_computation_orchestrator.py` stores `periods: list[int]`. For AMA, the equivalent is a list of `(indicator, params_dict)` pairs. Pass them via `extra_config` to avoid modifying WorkerTask.

```python
# In AMA worker task:
extra_config = {
    "indicators": [
        ("KAMA", {"er_period": 10, "fast_period": 2, "slow_period": 30}),
        ("KAMA", {"er_period": 5,  "fast_period": 2, "slow_period": 15}),
        ("KAMA", {"er_period": 20, "fast_period": 2, "slow_period": 50}),
        ("DEMA", {"period": 9}),
        ("DEMA", {"period": 21}),
        ("DEMA", {"period": 50}),
        ("TEMA", {"period": 9}),
        ("TEMA", {"period": 21}),
        ("HMA",  {"period": 9}),
        ("HMA",  {"period": 21}),
        ("HMA",  {"period": 50}),
    ],
    "bars_table": "cmc_price_bars_multi_tf",
    "out_table": "cmc_ama_multi_tf",
}
```

### Verified Pattern: Warmup Guards Summary

```python
# Warmup minimums (rows before first valid AMA value):
WARMUP = {
    "KAMA": lambda params: params["er_period"],        # e.g. 10 for canonical
    "DEMA": lambda params: 2 * params["period"] - 1,  # e.g. 41 for period=21
    "TEMA": lambda params: 3 * params["period"] - 1,  # e.g. 62 for period=21
    "HMA":  lambda params: params["period"] + int(params["period"] ** 0.5) - 2,
}
# Any bars below warmup threshold produce NULL in the AMA column.
# This satisfies AMA-04 requirement explicitly.
```

### Verified Pattern: State Table DDL for AMA

```sql
-- AMA state table (mirrors cmc_ema_multi_tf_state but with indicator + params_hash)
CREATE TABLE IF NOT EXISTS public.cmc_ama_multi_tf_state (
    id            INTEGER NOT NULL,
    tf            TEXT NOT NULL,
    indicator     TEXT NOT NULL,
    params_hash   TEXT NOT NULL,
    last_canonical_ts  TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, tf, indicator, params_hash)
);
```

### Verified Pattern: run_all_ama_refreshes.py Structure

```python
# Mirrors run_all_ema_refreshes.py exactly:
ALL_AMA_REFRESHERS = [
    RefresherConfig(name="multi_tf",   script_path="refresh_cmc_ama_multi_tf.py",     ...),
    RefresherConfig(name="cal",        script_path="refresh_cmc_ama_multi_tf_cal_from_bars.py", supports_scheme=True),
    RefresherConfig(name="cal_anchor", script_path="refresh_cmc_ama_multi_tf_cal_anchor_from_bars.py", supports_scheme=True),
]
# After all refreshers: run sync to _u + run returns refresh + run z-scores
# This is the "all-in-one stage" from CONTEXT.md decisions.
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw EMA period column | params_hash + dim_ama_params lookup | Phase 35 (new) | Supports N parameter sets without schema changes |
| EMA-only infrastructure | AMA as sibling family | Phase 35 (new) | KAMA/DEMA/TEMA/HMA as first-class citizens |
| period-keyed state | (indicator, params_hash)-keyed state | Phase 35 (new) | Correct incremental refresh per param set |

---

## Open Questions

1. **`roll` column semantics for AMA tables**
   - What we know: EMA tables have `roll=TRUE` for inter-bar daily snapshots and `roll=FALSE` for canonical bar closes. The multi_tf AMA refresher reads from `cmc_price_bars_multi_tf`, which has both roll and non-roll rows.
   - What's unclear: Whether `ama_bar` (bar-space AMA) is meaningful for KAMA/HMA. EMA tables have both `ema` and `ema_bar` columns. AMA tables need a decision: carry both or just `ama`?
   - Recommendation: Carry only `ama` (not `ama_bar`) in AMA tables initially. KAMA/HMA are defined on close prices; the "bar-space" variant is an EMA-specific concept. This simplifies the DDL. Revisit if signal generators need bar-space AMAs.

2. **Calendar variant computation for KAMA**
   - What we know: Calendar variants load from `cmc_price_bars_multi_tf_cal_us/iso/anchor_us/anchor_iso`. These have the same close price structure as multi_tf bars.
   - What's unclear: Whether KAMA's ER and smoothing constant have meaningful semantics across calendar-aligned bars (which can have variable bar lengths). EWM-based DEMA/TEMA are less sensitive to bar-length variation.
   - Recommendation: Compute KAMA on calendar bars identically to multi_tf bars — the formula is bar-count agnostic. Flag in runbook that KAMA on calendar bars assumes uniform bar frequency.

3. **Exact warmup guard threshold for DEMA/TEMA**
   - What we know: EWM has infinite impulse response — technically all rows after the first have some value. The warmup guard is a quality threshold, not a mathematical necessity.
   - What's unclear: Should DEMA guard at `period`, `2*period-1`, or `2*period`? The 3 choices produce slightly different NULL coverage.
   - Recommendation: Use `2*period - 1` for DEMA and `3*period - 1` for TEMA (Claude's discretion from CONTEXT.md). This matches the intuition that you need at least `k*period` observations for a `k`-composition EMA.

---

## Sources

### Primary (HIGH confidence)
- `/c/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/emas/base_ema_refresher.py` — complete BaseEMARefresher implementation
- `/c/Users/asafi/Downloads/ta_lab2/src/ta_lab2/features/m_tf/base_ema_feature.py` — BaseEMAFeature with write_to_db, _pg_upsert, pk columns
- `/c/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/sync_utils.py` — sync_sources_to_unified(), _sync_one_source()
- `/c/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/returns/refresh_returns_zscore.py` — full z-score computation and table config pattern
- `/c/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/run_daily_refresh.py` — orchestrator pipeline and subprocess pattern
- `/c/Users/asafi/Downloads/ta_lab2/sql/ddl/create_cmc_ema_multi_tf_cal_tables.sql` — EMA cal table DDL (columns, PK, indexes)
- `/c/Users/asafi/Downloads/ta_lab2/sql/ddl/create_cmc_returns_ema_multi_tf.sql` — EMA returns DDL with z-score columns
- `/c/Users/asafi/Downloads/ta_lab2/sql/ddl/create_cmc_returns_ema_multi_tf_u.sql` — EMA returns _u DDL with alignment_source PK
- `/c/Users/asafi/Downloads/ta_lab2/sql/features/030_cmc_ema_multi_tf_u_create.sql` — cmc_ema_multi_tf_u schema (alignment_source in PK)
- `/c/Users/asafi/Downloads/ta_lab2/src/ta_lab2/features/m_tf/ema_operations.py` — alpha formula `2/(period+1)`, adjust=False pattern
- `/c/Users/asafi/Downloads/ta_lab2/.planning/phases/35-ama-engine/35-CONTEXT.md` — locked decisions for this phase

### Secondary (MEDIUM confidence)
- KAMA formula: Kaufman (1995) "Smarter Trading" — direction/volatility efficiency ratio, SC = (ER*(fast-slow)+slow)^2. Consistent with pandas-ta and TA-Lib implementations.
- DEMA formula: Mulloy (1994) "Smoothing Data with Faster Moving Averages" in Technical Analysis of Stocks & Commodities — DEMA = 2*EMA1 - EMA(EMA1).
- TEMA formula: Mulloy (1994) same source — TEMA = 3*EMA1 - 3*EMA2 + EMA3.
- HMA formula: Alan Hull (2005) alanhull.com — WMA(2*WMA(n/2) - WMA(n), sqrt(n)).

### Tertiary (LOW confidence)
- Warmup threshold recommendations: derived from first-principles analysis. The `2*period-1` and `3*period-1` thresholds for DEMA/TEMA are not in official sources but are a reasonable engineering choice. Validate empirically.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already present in codebase
- Architecture patterns: HIGH — read directly from codebase; AMA mirrors EMA exactly
- DDL patterns: HIGH — read from actual DDL files; AMA DDL is a structural extension
- Sync pattern: HIGH — sync_utils.py read directly; works without modification
- AMA formulas (KAMA, DEMA, TEMA, HMA): MEDIUM — formulas match canonical sources; Python implementation is new
- Warmup guard thresholds: MEDIUM (KAMA), LOW (DEMA/TEMA — empirically reasonable but not mandated)

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (30 days — stable codebase, no fast-moving dependencies)
