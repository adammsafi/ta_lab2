# Phase 99: Backtest Scaling - Research

**Researched:** 2026-03-31
**Domain:** Walk-forward backtest orchestration, PostgreSQL partitioning, Monte Carlo CI, CTF signal registration, Streamlit leaderboard dashboard
**Confidence:** HIGH

---

## Summary

Phase 99 builds on a mature, working backtest infrastructure. The existing `BakeoffOrchestrator` in `src/ta_lab2/backtests/bakeoff_orchestrator.py` already handles walk-forward CV (purged K-fold + CPCV), NullPool multiprocessing, and upserts into `strategy_bakeoff_results`. The key Phase 99 additions are: (1) a **new state table** (`mass_backtest_state`) for resume-safe orchestration; (2) PostgreSQL **list partitioning** of `backtest_trades` by `strategy_name`; (3) populating `mc_sharpe_lo/hi/median` on `backtest_metrics`; (4) registering CTF threshold signals in `signals/registry.py`; (5) expanding param grids (currently 3-4 per strategy, need 3x); (6) a new Streamlit dashboard page (18_strategy_leaderboard.py).

The **critical architecture insight**: `strategy_bakeoff_results` is the primary result store for the mass bakeoff (not `backtest_runs`/`backtest_trades`/`backtest_metrics`). The legacy tables (`backtest_runs`, `backtest_trades`, `backtest_metrics`) exist but were the v0-era schema; `strategy_bakeoff_results` is the Phase 82+ production table. The `backtest_metrics.mc_sharpe_lo/hi/median` columns were added via migration `c3d4e5f6a1b2` but remain NULL — they need a backfill pass using `monte_carlo_trades()`. The partitioning requirement in BT-02 applies to `backtest_trades` (the legacy table that will receive mass run trades).

**Primary recommendation:** Build `run_mass_backtest.py` as a thin orchestration wrapper around the existing `BakeoffOrchestrator`, adding a `mass_backtest_state` state table with a params hash key and `--resume` flag. Partition `backtest_trades` by `strategy_name` using PostgreSQL list partitioning. Use `monte_carlo_trades()` from `analysis/monte_carlo.py` to populate MC columns.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | Project standard | DB ORM + NullPool | All DB access uses this; NullPool required for multiprocessing |
| vectorbt | 0.28.1 | Walk-forward portfolio simulation | Already wired in `bakeoff_orchestrator.py`; has known UTC gotchas |
| numpy | Project standard | Bootstrap resampling in monte_carlo | Used in `_bootstrap_sharpe()` |
| pandas | Project standard | DataFrame operations | Already in bakeoff_orchestrator |
| Alembic | Project standard | Schema migrations | Baseline `25f2b3c90f65`, latest `r2s3t4u5v6w7` |
| streamlit | Project standard | Dashboard | Multi-page app via `app.py` navigation |
| plotly | Project standard | Charts (equity sparklines) | Used in existing backtest dashboard page |
| yaml | stdlib | Parameter grid configs | Already used for `feature_selection.yaml` and experiments YAML |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| multiprocessing | stdlib | Parallel workers | Always use `maxtasksperchild=1` on Windows |
| hashlib | stdlib | params_hash computation | SHA256 of sorted JSON params |
| json | stdlib | params_json serialization | Already used in BakeoffOrchestrator |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PostgreSQL list partition | Range partition by date | List partition by strategy_name matches query patterns better for strategy-level analysis |
| Bootstrap resampling | Block bootstrap | Simple i.i.d. resampling is already implemented and sufficient; block bootstrap adds complexity without clear benefit at this scale |
| New leaderboard page | Modify page 11 | Spec requires a separate leaderboard page (BT-07); page 11 is the existing results page |

**Installation:**
```bash
# All dependencies already installed in project
# No new packages required
```

---

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/
├── scripts/backtests/
│   ├── run_mass_backtest.py      # NEW: mass orchestrator with resume logic
│   ├── run_bakeoff.py            # EXISTING: kept as-is
│   └── backfill_mc_bands.py     # NEW: post-run MC CI population pass
├── signals/
│   ├── registry.py               # MODIFY: add ctf_threshold_signal
│   └── ctf_threshold.py          # NEW: CTF threshold signal adapter
├── dashboard/pages/
│   └── 18_strategy_leaderboard.py  # NEW: MC bands + PBO heatmap + lineage
└── backtests/
    └── bakeoff_orchestrator.py   # EXISTING: no changes needed
alembic/versions/
└── s3t4u5v6w7x8_phase99_backtest_scaling.py  # NEW: migration
configs/
└── mass_backtest_grids.yaml      # NEW: expanded param grids
```

### Pattern 1: Resume-Safe State Table

**What:** Before running each (strategy, asset, params_hash, tf, cost_bps) combination, check `mass_backtest_state` table. Skip if `status = 'done'`.

**When to use:** All mass backtest runs.

**Key design:** `params_hash` is the MD5/SHA256 of `json.dumps(params, sort_keys=True)`. The state key is `(strategy_name, asset_id, params_hash, tf, cost_bps)`.

```python
# Source: project patterns from bakeoff_orchestrator.py _batch_existing_keys()
import hashlib, json

def compute_params_hash(params: dict) -> str:
    """Compute stable 8-char hex hash of sorted params JSON."""
    params_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(params_str.encode()).hexdigest()[:16]

# State table DDL (in Alembic migration):
"""
CREATE TABLE IF NOT EXISTS public.mass_backtest_state (
    id              SERIAL PRIMARY KEY,
    strategy_name   TEXT NOT NULL,
    asset_id        INTEGER NOT NULL,
    params_hash     TEXT NOT NULL,
    tf              TEXT NOT NULL,
    cost_bps        NUMERIC NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'running', 'done', 'error'
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_msg       TEXT,
    UNIQUE(strategy_name, asset_id, params_hash, tf, cost_bps)
);
"""
```

### Pattern 2: NullPool + maxtasksperchild=1

**What:** Workers create their own NullPool engine; parent uses maxtasksperchild=1.

**When to use:** All multiprocessing runs on Windows.

```python
# Source: src/ta_lab2/backtests/bakeoff_orchestrator.py lines 161-172, 1586-1587
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
import multiprocessing

# In worker function (module-level, picklable):
engine = create_engine(task.db_url, poolclass=NullPool)

# In parent:
with multiprocessing.Pool(processes=workers, maxtasksperchild=1) as pool:
    for result in pool.imap_unordered(worker_fn, tasks):
        ...
```

### Pattern 3: Monte Carlo CI via monte_carlo_trades()

**What:** After each bakeoff run, call `monte_carlo_trades()` with the `backtest_trades` rows and write `mc_sharpe_lo/hi/median` back to `backtest_metrics`.

**When to use:** BT-04 requirement — every `backtest_metrics` row needs non-null MC columns.

```python
# Source: src/ta_lab2/analysis/monte_carlo.py
from ta_lab2.analysis.monte_carlo import monte_carlo_trades

# trades_df must have 'pnl_pct' column (percentage, e.g. 2.5 for +2.5%)
result = monte_carlo_trades(trades_df, n_samples=1000, seed=42)
# result = {'mc_sharpe_lo': float, 'mc_sharpe_hi': float, 'mc_sharpe_median': float, ...}
# Returns None values when < 10 trades
```

### Pattern 4: PostgreSQL List Partitioning

**What:** Convert `backtest_trades` to a partitioned table using `PARTITION BY LIST (strategy_name)`.

**When to use:** Before mass run to handle 20-40M rows.

```sql
-- Source: observability schema uses RANGE partitioning; same concept
-- Step 1: Rename existing table
ALTER TABLE public.backtest_trades RENAME TO backtest_trades_default;

-- Step 2: Create new partitioned table
CREATE TABLE public.backtest_trades (
    trade_id    UUID NOT NULL DEFAULT gen_random_uuid(),
    run_id      UUID NOT NULL,
    strategy_name TEXT NOT NULL,  -- NEW column required for partitioning
    entry_ts    TIMESTAMPTZ NOT NULL,
    -- ... all existing columns ...
    FOREIGN KEY (run_id) REFERENCES public.backtest_runs(run_id) ON DELETE CASCADE
) PARTITION BY LIST (strategy_name);

-- Step 3: Create default partition for unrecognized strategy names
CREATE TABLE public.backtest_trades_default_part
    PARTITION OF public.backtest_trades DEFAULT;

-- Step 4: Re-insert data from old table
INSERT INTO public.backtest_trades SELECT *, signal_type as strategy_name FROM public.backtest_trades_default;
```

**IMPORTANT CONSTRAINT:** `backtest_trades` currently has a UUID PK `trade_id`. When creating a partitioned table in PostgreSQL, the partition key column (`strategy_name`) must be included in the unique constraint. This means the existing PK must change to `(trade_id, strategy_name)`. The Alembic migration must handle this carefully.

**Simpler alternative that avoids PK complexity:** Add `strategy_name` as a column and create partitions without touching the PK (just use range partitioning by date instead). However, BT-02 specifies partition by `strategy_name`, so list partitioning is required.

### Pattern 5: CTF Threshold Signal Registration

**What:** Create a new signal adapter `signals/ctf_threshold.py` following the same signature as `ema_trend.py` etc., then register it in `registry.py`.

**Signal signature (all adapters must match):**
```python
# Source: src/ta_lab2/signals/registry.py line 57
# Signature: (df, **params) -> (entries: Series[bool], exits: Series[bool], size: Optional[Series[float]])
def make_signals(df: pd.DataFrame, **params) -> tuple[pd.Series, pd.Series, Optional[pd.Series]]:
    """CTF threshold signal: entry when CTF feature crosses threshold."""
    feature_col = params.get("feature_col")   # e.g. "ret_arith_365d_divergence"
    entry_threshold = params.get("entry_threshold", 0.0)
    exit_threshold = params.get("exit_threshold", 0.0)
    direction = params.get("direction", "long")
    ...
```

### Pattern 6: Dashboard Page Addition

**What:** Add a new page file `pages/18_strategy_leaderboard.py` and register it in `app.py` navigation.

**When to use:** New pages must be registered in `app.py`'s `pages` dict.

```python
# Source: src/ta_lab2/dashboard/app.py
# Add to "Research" section:
st.Page(
    "pages/18_strategy_leaderboard.py",
    title="Strategy Leaderboard",
    icon=":material/leaderboard:",
),
```

**Critical constraint:** `st.set_page_config()` is called only in `app.py`. Page files MUST NOT call it (raises `StreamlitAPIException`).

### Anti-Patterns to Avoid
- **Calling set_page_config in page files:** Already documented as a known issue in existing pages.
- **Ignoring maxtasksperchild=1:** Causes Windows Pool hang on multiprocessing; existing bakeoff_orchestrator.py already uses this pattern (line 1587).
- **Running DSR at 460K scale:** DSR requires all strategy SRs to compute E[max SR]. At 460K runs, computing DSR within workers is expensive and statistically misleading (inflated DSR benchmarks). Log this as a known limitation and compute DSR only on a representative subset (e.g., top 1000 runs by Sharpe).
- **Forgetting NullPool in workers:** The parent engine uses a pool, but workers must create their own NullPool engine (existing pattern in `_bakeoff_asset_worker`).
- **Upsert without temp table for mass updates:** Use `ON CONFLICT DO UPDATE` for state table (already established pattern), not temp table + INSERT SELECT which has transaction size risks.

---

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Monte Carlo Sharpe CI | Custom bootstrap loop | `monte_carlo_trades()` from `analysis/monte_carlo.py` | Already implemented with annualization, edge cases, min-trade guard |
| PSR/DSR | Custom formula | `compute_psr()`, `compute_dsr()` from `backtests/psr.py` | Pearson kurtosis (fisher=False) is subtle; already correctly implemented |
| Walk-forward CV | Custom fold logic | `PurgedKFoldSplitter` / `CPCVSplitter` from `backtests/cv.py` | Purge + embargo logic is complex; already implemented |
| Cost scenarios | Custom cost model | `CostModel`, `KRAKEN_COST_MATRIX`, `HYPERLIQUID_COST_MATRIX` from `backtests/costs.py` | 16 scenarios already defined and tested |
| Params deduplication | Custom hash | `json.dumps(params, sort_keys=True)` | Already used as params_json in strategy_bakeoff_results UNIQUE constraint |
| Strategy param grids | Inline dicts in script | `configs/mass_backtest_grids.yaml` | Phase requires YAML documentation; grid_for() in registry.py shows the pattern |
| Dashboard engine | New connection logic | `get_engine()` from `dashboard/db.py` | NullPool singleton already handles this |
| Signal registration | Direct REGISTRY manipulation | Pattern from `registry.py` try/except imports | Keeps backward compatibility; optional signals fall back gracefully |

**Key insight:** The main bakeoff machinery is complete. The work is orchestration (state table + resume) and surface area (more param combinations, CTF signal type, MC column population).

---

## Common Pitfalls

### Pitfall 1: DSR Over-inflation at Scale
**What goes wrong:** DSR computes `expected_max_SR` across N trials. At 460K runs, this benchmark becomes very high, making DSR close to 0 for nearly all strategies. The statistic loses discriminating power.
**Why it happens:** Bailey (2012) DSR was designed for N < 1000 independent trials. At 460K runs the formula's assumptions break down.
**How to avoid:** Document this limitation explicitly. Do not attempt to compute DSR across the full 460K run set. Either: (a) skip DSR for mass runs and only compute it within strategy-specific subgroups (<1000 runs each), or (b) set `dsr = NULL` for mass runs with a comment.
**Warning signs:** All DSR values converge to 0.0.

### Pitfall 2: Windows Pool Hang
**What goes wrong:** `multiprocessing.Pool` hangs on Windows when a worker process crashes with an unhandled exception.
**Why it happens:** Windows uses `spawn` (not `fork`) for new processes; exception handling behaves differently.
**How to avoid:** Use `maxtasksperchild=1` (kills/respawns worker after each task). Use `pool.imap_unordered()` not `pool.map()`. Wrap worker body in `try/except` that always returns a result (even empty list).
**Warning signs:** Script hangs after processing some assets with no output.

### Pitfall 3: PostgreSQL Partitioning Requires PK Change
**What goes wrong:** `backtest_trades` has `trade_id UUID PRIMARY KEY`. PostgreSQL requires that the partition key column be part of the primary key for partitioned tables.
**Why it happens:** PostgreSQL enforces this constraint for global uniqueness across partitions.
**How to avoid:** In the Alembic migration: DROP the existing PK, add `strategy_name NOT NULL` column, recreate PK as `(trade_id, strategy_name)`. Alternatively, use a foreign key constraint only (no UUID PK uniqueness enforcement across partitions).
**Warning signs:** `ERROR: insufficient columns in PRIMARY KEY for table "backtest_trades"`.

### Pitfall 4: backtest_metrics mc_sharpe_* Columns Already Exist
**What goes wrong:** Trying to ADD these columns via Alembic when they already exist from migration `c3d4e5f6a1b2_add_mc_ci_to_metrics.py`.
**Why it happens:** The columns were added in Phase 56 to `cmc_backtest_metrics`, then renamed to `backtest_metrics` in migration `a0b1c2d3e4f5_strip_cmc_prefix_add_venue_id.py`.
**How to avoid:** Check column existence before adding. Phase 99 migration should only add what's new: `mass_backtest_state` table + `backtest_trades` partitioning. The MC columns already exist in `backtest_metrics` and just need data populated via a backfill script.
**Warning signs:** `column "mc_sharpe_lo" of relation "backtest_metrics" already exists`.

### Pitfall 5: CTF Features in features Table vs. ctf Table
**What goes wrong:** CTF threshold signals need to read CTF feature values. They live in `public.features` (promoted by Phase 98) but the `load_strategy_data()` function only loads specific columns.
**Why it happens:** `load_strategy_data()` selects only `rsi_14`, `ta_is_outlier`, and OHLCV. CTF columns like `ret_arith_365d_divergence` are in `features` but not auto-loaded.
**How to avoid:** Either: (a) extend `load_strategy_data()` with an optional `ctf_cols` parameter, or (b) add CTF column loading into the signal function itself via a DB call, or (c) create a new `load_strategy_data_with_ctf()` function analogous to `load_strategy_data_with_ama()`.
**Warning signs:** KeyError when signal function tries to access `df["ret_arith_365d_divergence"]`.

### Pitfall 6: Strategy Name Inconsistency in Partitioning
**What goes wrong:** `backtest_trades` currently has no `strategy_name` column — it's linked only via `run_id` → `backtest_runs.signal_type`. List partitioning by strategy_name requires this column to be in the trades table.
**Why it happens:** The original schema used `run_id` FK to link trades to runs.
**How to avoid:** Add `strategy_name TEXT NOT NULL` to `backtest_trades` in the Alembic migration. Populate it from `backtest_runs.signal_type` for existing rows.
**Warning signs:** `column "strategy_name" of relation "backtest_trades" does not exist`.

---

## Code Examples

Verified patterns from official sources:

### State Table Upsert (resume-safe pattern)
```python
# Pattern: ON CONFLICT DO UPDATE for idempotent state management
# Source: bakeoff_orchestrator.py _persist_results() upsert pattern
sql = text("""
    INSERT INTO public.mass_backtest_state (
        strategy_name, asset_id, params_hash, tf, cost_bps, status, started_at
    )
    VALUES (:strategy_name, :asset_id, :params_hash, :tf, :cost_bps, 'running', now())
    ON CONFLICT (strategy_name, asset_id, params_hash, tf, cost_bps)
    DO UPDATE SET
        status = 'running',
        started_at = now(),
        error_msg = NULL
""")
```

### Resume Flag Pattern
```python
# Pattern: Load completed keys at startup, skip in loop
# Source: bakeoff_orchestrator.py _batch_existing_keys() + existing_keys set
def load_completed_keys(engine) -> set:
    """Load all completed (strategy, asset, params_hash, tf, cost_bps) tuples."""
    sql = text("""
        SELECT strategy_name, asset_id, params_hash, tf, cost_bps
        FROM public.mass_backtest_state
        WHERE status = 'done'
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return {(r[0], r[1], r[2], r[3], r[4]) for r in rows}

# Usage:
completed = load_completed_keys(engine) if args.resume else set()
for combo in all_combinations:
    key = (combo.strategy, combo.asset_id, combo.params_hash, combo.tf, combo.cost_bps)
    if key in completed:
        continue
    # ... run backtest ...
```

### CTF Signal Adapter (follow existing adapter pattern)
```python
# Source: signals/ema_trend.py pattern (same signature required)
# All signal adapters: (df, **params) -> (entries, exits, size)
def make_signals(
    df: pd.DataFrame,
    feature_col: str = "ret_arith_365d_divergence",
    entry_threshold: float = 0.0,
    exit_threshold: float = 0.0,
    direction: str = "long",
    **kwargs,
) -> tuple[pd.Series, pd.Series, None]:
    """CTF threshold crossover signal."""
    if feature_col not in df.columns:
        raise KeyError(f"CTF feature '{feature_col}' not in DataFrame columns")

    feature = df[feature_col].fillna(0.0)

    if direction == "long":
        entries = feature > entry_threshold
        exits = feature < exit_threshold
    else:  # short
        entries = feature < entry_threshold
        exits = feature > exit_threshold

    return entries.astype(bool), exits.astype(bool), None
```

### Registry Addition Pattern
```python
# Source: signals/registry.py lines 26-72
# CTF signal addition follows the same try/except optional import pattern

try:
    from .ctf_threshold import make_signals as ctf_threshold_signal
except Exception:  # pragma: no cover
    ctf_threshold_signal = None  # type: ignore[assignment]

REGISTRY: Dict[str, ...] = {
    "ema_trend": ema_trend_signal,
    # ... existing ...
    **({"ctf_threshold": ctf_threshold_signal} if ctf_threshold_signal else {}),
}
```

### Expanded Param Grid in YAML
```yaml
# Source: configs pattern (feature_selection.yaml, experiments YAML)
# configs/mass_backtest_grids.yaml
ema_crossover:
  fast_emas: [5, 10, 17, 21, 30, 50]    # was 4 combos, now 6 fast x 8 slow
  slow_emas: [50, 77, 100, 120, 150, 200, 250, 300]

rsi_mean_revert:
  rsi_ns: [7, 10, 14, 21, 28]           # was 3, now 5 periods
  rsi_buy: [20, 25, 30, 35, 40]         # was 3, now 5 levels
  rsi_sell: [55, 60, 65, 70, 75, 80]    # was 3, now 6 levels
  use_trend_filters: [true, false]       # was 2 variants

atr_breakout:
  lookbacks: [10, 20, 30, 40, 60]       # was 3, now 5
  trail_atr_mults: [1.5, 2.0, 2.5, 3.0] # was 2, now 4
```

### MC CI Backfill Query
```python
# Source: analysis/monte_carlo.py + SQL pattern from bakeoff_orchestrator.py
from ta_lab2.analysis.monte_carlo import monte_carlo_trades

# Load trades for a run_id, compute CI, write back to backtest_metrics
trades_sql = text("""
    SELECT pnl_pct FROM public.backtest_trades
    WHERE run_id = :run_id
""")
with engine.connect() as conn:
    trades_df = pd.read_sql(trades_sql, conn, params={"run_id": run_id})

result = monte_carlo_trades(trades_df, n_samples=1000, seed=42)

update_sql = text("""
    UPDATE public.backtest_metrics
    SET mc_sharpe_lo = :lo, mc_sharpe_hi = :hi, mc_sharpe_median = :median,
        mc_n_samples = :n_samples
    WHERE run_id = :run_id
""")
```

### Dashboard Page Navigation Addition
```python
# Source: src/ta_lab2/dashboard/app.py lines 42-71
# Add to the "Research" section:
st.Page(
    "pages/18_strategy_leaderboard.py",
    title="Strategy Leaderboard",
    icon=":material/leaderboard:",
),
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `cmc_backtest_*` table names | `backtest_*` (no cmc_ prefix) | Phase 98 Alembic migration `a0b1c2d3e4f5` | Must use new names everywhere |
| `cmc_features` table | `features` table | Same migration | load_strategy_data() already uses `features` |
| `run_bakeoff.py` (manual per-session) | `run_mass_backtest.py` (resume-safe) | Phase 99 | New orchestrator wraps existing BakeoffOrchestrator |
| `strategy_bakeoff_results` as primary result store | Same, plus `mass_backtest_state` for resume | Phase 99 | State table is new; results go to strategy_bakeoff_results as before |

**Deprecated/outdated:**
- `cmc_backtest_runs`/`cmc_backtest_trades`/`cmc_backtest_metrics`: renamed to `backtest_runs`/`backtest_trades`/`backtest_metrics`; do not use the `cmc_` prefix versions.
- `strategy_bakeoff_results.experiment_name` was NULL before Phase 82; now tracked.

---

## Open Questions

1. **PBO Heatmap Data Source**
   - What we know: `strategy_bakeoff_results` has `pbo_prob` (computed from CPCV). Page 11 already shows it as a column. The leaderboard page needs a heatmap (strategy x asset).
   - What's unclear: Whether `pbo_prob` values from the simplified CPCV approximation (fraction of folds below median) are meaningful enough for a heatmap, or if a proper path-matrix-based PBO should be computed.
   - Recommendation: Use existing `pbo_prob` from `strategy_bakeoff_results` for the heatmap. Plotly heatmap with `go.Heatmap` or `px.imshow`. Document the simplified approximation in the UI.

2. **Feature-to-Signal Lineage**
   - What we know: `strategy_bakeoff_results.experiment_name` tracks which experiment produced the results. CTF signals will have `feature_col` in `params_json`.
   - What's unclear: Whether a join against `dim_ctf_indicators` or `ic_results` is needed for the lineage display, or if `params_json.feature_col` is sufficient.
   - Recommendation: Parse `params_json` in the dashboard query to extract `feature_col`, join against `ic_results` for IC metadata. Start with simple `params_json ->> 'feature_col'` extraction.

3. **backtest_trades Partitioning Risk**
   - What we know: `backtest_trades` has UUID PK and FK to `backtest_runs`. Adding list partitioning requires `strategy_name` in PK, which is a breaking schema change.
   - What's unclear: Whether `backtest_trades` currently has any significant data that must be preserved through the migration.
   - Recommendation: The Alembic migration should: (1) check row count; (2) rename old table as backup; (3) create new partitioned schema; (4) re-insert data. Add `strategy_name` sourced from `backtest_runs.signal_type`.

4. **CTF Feature Column Loading in Bakeoff**
   - What we know: 40 CTF features were promoted to `features` table (see `configs/feature_selection.yaml` ctf_promoted section). `load_strategy_data()` does NOT load them automatically.
   - What's unclear: Whether to extend `load_strategy_data()` or create a new loader.
   - Recommendation: Create `load_strategy_data_with_ctf()` analogous to `load_strategy_data_with_ama()`. Takes a list of CTF column names, queries `features` table with those additional columns included. This avoids modifying the existing loader signature.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/backtests/bakeoff_orchestrator.py` — Full BakeoffOrchestrator, _bakeoff_asset_worker, multiprocessing pattern, NullPool, maxtasksperchild=1, strategy_bakeoff_results upsert
- `src/ta_lab2/backtests/psr.py` — PSR/DSR implementation, kurtosis convention (Pearson fisher=False)
- `src/ta_lab2/backtests/cv.py` — PurgedKFoldSplitter, CPCVSplitter, embargo logic
- `src/ta_lab2/backtests/costs.py` — CostModel, KRAKEN_COST_MATRIX (12 scenarios), HYPERLIQUID_COST_MATRIX (6 scenarios), COST_MATRIX_REGISTRY
- `src/ta_lab2/analysis/monte_carlo.py` — monte_carlo_trades(), monte_carlo_returns(), _bootstrap_sharpe(), pnl_pct input format, None result on <10 trades
- `src/ta_lab2/signals/registry.py` — REGISTRY structure, optional adapter import pattern, grid_for() helper
- `src/ta_lab2/scripts/backtests/run_bakeoff.py` — _BAKEOFF_PARAM_GRIDS (current small grids), _build_strategies(), CLI pattern
- `src/ta_lab2/dashboard/app.py` — Page navigation structure, Research section where leaderboard goes
- `src/ta_lab2/dashboard/pages/11_backtest_results.py` — Existing backtest page pattern; 16 cost scenarios; MC CI bootstrap implementation (_compute_mc_ci); @st.fragment pattern; do NOT call set_page_config()
- `src/ta_lab2/dashboard/queries/backtest.py` — load_bakeoff_leaderboard(), server-side filtering pattern, @st.cache_data(ttl=3600)
- `alembic/versions/e74f5622e710_add_strategy_bakeoff_results.py` — strategy_bakeoff_results DDL (SERIAL PK, UNIQUE constraint)
- `alembic/versions/c3d4e5f6a1b2_add_mc_ci_to_metrics.py` — mc_sharpe_lo/hi/median columns already in backtest_metrics (was cmc_backtest_metrics)
- `alembic/versions/r2s3t4u5v6w7_phase98_ctf_graduation_schema.py` — Latest migration (down_revision = q1r2s3t4u5v6); Phase 99 migration must use revision = "r2s3t4u5v6w7" as down_revision
- `sql/backtests/071_backtest_trades.sql` — backtest_trades DDL: UUID PK `trade_id`, FK to backtest_runs, NO strategy_name column
- `sql/backtests/072_backtest_metrics.sql` — backtest_metrics DDL: mc_sharpe_lo/hi/median columns already present post-migration
- `configs/feature_selection.yaml` — ctf_promoted section with 40 CTF features including ret_arith_365d_divergence, adx_14_365d_ref_value etc.
- `sql/ddl/create_observability_schema.sql` — Example of RANGE partitioning in this codebase

### Secondary (MEDIUM confidence)
- `src/ta_lab2/backtests/metrics.py` — Core metrics (cagr, sharpe, max_drawdown). Does not have MC CI.
- Phase 99 requirements context: "13 strategies x top assets x 16 costs = ~113K runs" — from the strategies in `_BAKEOFF_PARAM_GRIDS` (7 named strategies + potential perasset variant + future CTF variants; "13" likely reflects strategies x CV methods in the existing bakeoff)

### Tertiary (LOW confidence - needs validation)
- The "13 strategies" count in BT-03: the current `_BAKEOFF_PARAM_GRIDS` has 7 strategy names (`ema_trend`, `rsi_mean_revert`, `breakout_atr`, `macd_crossover`, `ama_momentum`, `ama_mean_reversion`, `ama_regime_conditional`). With perasset variant and some expression engine experiments, ~13 distinct strategy names may exist in `strategy_bakeoff_results` already. Plan assumes the count target of 113K includes existing + new results.
- The "16 costs" figure: confirmed from dashboard page `_COST_SCENARIOS` list (9 spot + 7 perps = 16 scenarios as displayed). Note this differs from costs.py KRAKEN_COST_MATRIX (12) — the dashboard shows a manually curated 16-scenario view. The actual costs to run for BT-03 need clarification; use `exchange=all` (18 scenarios) or Kraken+custom 16.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are already in the project
- Architecture: HIGH — patterns directly copied from existing working code
- Pitfalls: HIGH for Windows Pool hang and DSR inflation (explicitly noted in phase requirements); MEDIUM for partition PK issue (standard PostgreSQL behavior but not tested in this project)
- MC CI implementation: HIGH — function exists and is tested
- CTF signal registration: HIGH — pattern exactly mirrors existing adapters
- Dashboard leaderboard: MEDIUM — component patterns exist but PBO heatmap and lineage display are new combinations

**Research date:** 2026-03-31
**Valid until:** 2026-05-01 (stable infrastructure, no fast-moving dependencies)

---

## Quick Reference: Key Numbers

| Metric | Value | Source |
|--------|-------|--------|
| Current strategies in registry | 7 | signals/registry.py REGISTRY |
| Current cost scenarios (Kraken) | 12 | backtests/costs.py KRAKEN_COST_MATRIX |
| Current cost scenarios (dashboard) | 16 | pages/11_backtest_results.py _COST_SCENARIOS |
| CTF features promoted to features table | 40 | configs/feature_selection.yaml ctf_promoted section |
| Latest Alembic revision | r2s3t4u5v6w7 | alembic/versions/r2s3t4u5v6w7_phase98_ctf_graduation_schema.py |
| strategy_bakeoff_results current rows | 76,970+ | dashboard/queries/backtest.py comment |
| Monte Carlo min trades | 10 | analysis/monte_carlo.py _MIN_TRADES |
| Monte Carlo min returns | 30 | analysis/monte_carlo.py _MIN_RETURNS |
| maxtasksperchild setting | 1 | bakeoff_orchestrator.py line 1587 |
| BT-03 target run count | 113K distinct combos | Phase 99 requirements |
| BT-04 MC bootstrap samples | 1,000 | Phase 99 requirements |
