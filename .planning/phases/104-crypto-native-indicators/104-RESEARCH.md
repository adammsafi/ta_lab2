# Phase 104: Crypto-Native Indicators - Research

**Researched:** 2026-04-01
**Domain:** Venue-agnostic normalized input layer for futures/derivatives data (OI, funding rates, volume), 8+ derivatives indicators, Phase 102 harness integration
**Confidence:** HIGH (all patterns verified directly against local codebase; formulas verified against Kaufman and Elder primary sources cited in existing codebase)

---

## Summary

Phase 104 builds a normalized input layer that maps Hyperliquid-specific tables into a unified schema, derives 8+ futures/derivatives indicators, and runs them through the Phase 102 IC + FDR harness.

**What was researched:** (1) All four Hyperliquid tables (`hl_candles`, `hl_funding_rates`, `hl_open_interest`, `hl_oi_snapshots`) — exact schemas read from Alembic migration `f7a8b9c0d1e2`. (2) The critical namespace difference between HL `asset_id` (SmallInteger in `hyperliquid.hl_assets`) and CMC-origin `id` (Integer in `features`, `ic_results`, `price_bars_multi_tf`). (3) The `BaseFeature` / `TAFeature` / `indicators.py` / `indicators_extended.py` pattern stack — full read of `base_feature.py`, `ta_feature.py`, `indicators.py`. (4) The IC sweep pipeline: `run_ic_sweep.py` reads from `public.features` using column `id` (not `asset_id`), writes to `ic_results`. (5) `dim_feature_registry` uses `lifecycle` column (`'promoted'`, `'deprecated'`, `'experimental'`), NOT an `is_active` boolean. (6) The Alembic HEAD is `s3t4u5v6w7x8` (Phase 99); Phase 103 migrations have not yet been created.

**Standard approach:** Python adapter class per venue following `BaseFeature` conventions. Indicators implemented hand-rolled in NumPy/pandas (no new dependencies), following the `indicators_extended.py` API established in Phase 103. Unified schema keyed on CMC `id` (INTEGER) and `venue_id`, not HL `asset_id`. Feature values write to the existing `public.features` table via the `BaseFeature.write_to_db()` pattern with `_get_table_columns()` column filtering.

**Primary recommendation:** Model the normalized input layer as a standalone module `src/ta_lab2/features/derivatives_input.py` that converts HL tables into a `DerivativesFrame` (standard DataFrame schema). The indicator functions live in a new `src/ta_lab2/features/indicators_derivatives.py` file. A `DerivativesFeature` class (extending `BaseFeature`) orchestrates loading, computing, and writing.

---

## Standard Stack

### Core (no new dependencies required)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | 2.4.1 (installed) | Rolling math, z-score computation, momentum | Used everywhere in indicators.py |
| pandas | 2.3.3 (installed) | DataFrame operations, rolling windows, groupby per asset | Standard throughout features/ |
| sqlalchemy.text | (installed) | All DB reads from hyperliquid schema and writes to public.features | Project convention for all DB operations |
| scipy.stats | 1.17.0 (installed) | Spearman IC (via run_ic_sweep.py calling ic.py) | Already the IC sweep standard |
| statsmodels 0.14.6 | (installed) | FDR control (via multiple_testing.py from Phase 102) | Already installed, same as Phase 103 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pandas.DataFrame.merge | (built-in) | Join HL native OI + Coinalyze OI in adapter | Combining two OI sources with date alignment |

**Installation:**
```bash
# Nothing to install — all required libraries are already installed
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled indicators (numpy/pandas) | pandas-ta or TA-Lib | Phase 103 pattern: no TA libraries installed, project owns all indicator logic. No exception for Phase 104. |
| Python adapter class | SQL VIEW over hyperliquid tables | CONTEXT.md decision: Python adapters, not SQL views. One adapter per venue. |
| Writing to public.features | Separate crypto_features table | CONTEXT.md decision: unified features table. Adds columns via Alembic ALTER TABLE. |
| CMC `id` as the join key | HL `asset_id` as the join key | The IC sweep, `load_feature_series()`, and all downstream analysis uses CMC `id`. HL `asset_id` is a different INTEGER namespace. The adapter must resolve HL asset_id -> CMC id via `dim_listings` or `dim_asset_identifiers`. |

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/features/
├── indicators.py              # existing — 8 functions — DO NOT MODIFY
├── indicators_extended.py     # Phase 103 — 20 functions
├── indicators_derivatives.py  # NEW Phase 104 — 8+ derivatives/futures indicators

src/ta_lab2/features/
├── derivatives_input.py       # NEW Phase 104 — normalized input layer (adapters)

src/ta_lab2/scripts/features/
├── derivatives_feature.py     # NEW Phase 104 — DerivativesFeature class (BaseFeature subclass)

src/ta_lab2/scripts/analysis/
├── run_phase104_ic.py         # NEW Phase 104 — IC sweep + FDR + promotion for derivatives indicators

alembic/versions/
└── p104_derivatives_features.py  # NEW — adds derivatives columns to public.features
```

### Pattern 1: Hyperliquid Asset ID -> CMC ID Mapping

**This is the most critical technical challenge in Phase 104.**

The `hyperliquid.hl_assets` table uses `asset_id SMALLINT` (e.g., 0 for BTC-PERP) while `public.features` uses `id INTEGER` (e.g., 1 for BTC from CMC). These are different namespaces.

**Resolution strategy:** `seed_hl_assets.py` already matches HL symbols to CMC IDs using `dim_listings` and `dim_asset_identifiers`. The adapter must perform a JOIN to get CMC id for each HL asset_id.

```python
# Source: read from seed_hl_assets.py and hyperliquid schema
# Query to get HL asset_id -> CMC id mapping (HIGH confidence — same approach as seed_hl_assets.py)

def _get_hl_to_cmc_id_map(conn) -> dict[int, int]:
    """Map HL asset_id (SmallInteger) to CMC id (Integer) via dim_listings."""
    rows = conn.execute(text("""
        SELECT DISTINCT
            ha.asset_id   AS hl_asset_id,
            dl.id         AS cmc_id
        FROM hyperliquid.hl_assets ha
        JOIN dim_listings dl
          ON dl.symbol = ha.symbol
         AND dl.venue = 'HYPERLIQUID'
        WHERE ha.asset_type = 'perp'
    """)).fetchall()
    return {r[0]: r[1] for r in rows}
```

**Warning:** Not all HL assets will have a CMC match (km assets like USOIL, indices, FX). The adapter should return only assets that have a CMC id match when writing to `public.features` (which uses CMC `id`). The unified schema intermediate DataFrame can use HL `asset_id` internally; only the final write to `public.features` requires CMC `id`.

### Pattern 2: Unified DerivativesFrame Schema

**What:** The normalized layer returns a standard DataFrame that all indicator functions accept.
**When to use:** Every time derivatives indicators are computed.

```python
# Source: derived from CONTEXT.md decisions + hl_candles schema (f7a8b9c0d1e2 migration)
# Column types verified against Alembic migration

# DerivativesFrame columns (unified schema):
#   asset_id   INTEGER     -- CMC id (NOT HL asset_id after resolution)
#   venue_id   SMALLINT    -- 2 = HYPERLIQUID
#   ts         TIMESTAMPTZ -- bar close timestamp, UTC
#   oi         FLOAT       -- open interest (in base asset units)
#   funding_rate FLOAT     -- per-period funding rate (e.g. 0.0001 = 0.01%)
#   volume     FLOAT       -- trading volume in base asset (from hl_candles.volume)
#   close      FLOAT       -- close price (from hl_candles.close)
#   mark_px    FLOAT       -- mark price (from hl_oi_snapshots.mark_px, nullable)
#   liq_proxy  FLOAT       -- liquidation pressure proxy (derived, nullable)

# NOTE: 'asset_id' here is CMC id to match public.features column 'id'.
# The normalized frame uses 'id' (not 'asset_id') for consistency with features table.
```

### Pattern 3: HyperliquidAdapter Class

**What:** Converts HL-specific tables into DerivativesFrame. Handles HL-native OI (primary) + Coinalyze OI (gap fill).
**Source tables used:**
- `hyperliquid.hl_candles` — close, volume, open_oi, close_oi (OI at bar boundaries)
- `hyperliquid.hl_funding_rates` — funding_rate (1h granularity; resample to daily if needed)
- `hyperliquid.hl_oi_snapshots` — mark_px (fallback if not in hl_candles)
- `hyperliquid.hl_open_interest` — Coinalyze OI OHLC (for gap filling only)

```python
# Source: verified pattern from base_feature.py, hl schema from migration f7a8b9c0d1e2

class HyperliquidAdapter:
    """Returns normalized DerivativesFrame for Hyperliquid perp assets."""

    VENUE_ID = 2  # HYPERLIQUID in dim_venues

    def __init__(self, engine: Engine):
        self.engine = engine

    def load(
        self,
        cmc_ids: list[int],
        start: str | None = None,
        end: str | None = None,
        tf: str = "1D",
    ) -> pd.DataFrame:
        """
        Returns DataFrame with columns: id, venue_id, ts, oi, funding_rate, volume, close, mark_px
        'id' = CMC id (for compatibility with public.features 'id' column)
        Empty DataFrame (not error) if venue has no data for requested ids.
        """
        ...
```

### Pattern 4: MockAdapter for SC-4 Testing

**What:** Returns empty DataFrame without hitting the database. Tests graceful degradation.
**When to use:** Unit testing SC-4 (missing venue behavior).

```python
# Source: CONTEXT.md decision — simple fixture, not database-backed

class MockAdapter:
    """Mock venue adapter for testing graceful degradation (SC-4)."""

    VENUE_ID = 99  # Not a real venue

    def load(self, cmc_ids: list[int], **kwargs) -> pd.DataFrame:
        """Always returns empty DataFrame — tests that indicators handle missing venue."""
        return pd.DataFrame(
            columns=["id", "venue_id", "ts", "oi", "funding_rate", "volume", "close", "mark_px"]
        )
```

### Pattern 5: DerivativesFeature Class (BaseFeature Subclass)

**What:** Orchestrates: load normalized frame -> compute indicators -> write to public.features.
**Pattern source:** `TAFeature` in `ta_feature.py` (read directly from codebase).

Key difference from TAFeature: `load_source_data()` calls the adapter instead of reading `price_bars_multi_tf_u`.

```python
# Source: base_feature.py pattern, verified

class DerivativesFeature(BaseFeature):
    SOURCE_TABLE = "hyperliquid.hl_candles"  # informational only
    TS_COLUMN = "ts"

    def __init__(self, engine: Engine, config: DerivativesConfig, adapter: HyperliquidAdapter):
        super().__init__(engine, config)
        self.adapter = adapter

    def load_source_data(self, ids, start=None, end=None) -> pd.DataFrame:
        # ids here are CMC ids
        df = self.adapter.load(ids, start=start, end=end, tf=self.config.tf)
        return df  # Empty DataFrame if no data (not an error)

    def compute_features(self, df_source: pd.DataFrame) -> pd.DataFrame:
        # df_source has: id, venue_id, ts, oi, funding_rate, volume, close, mark_px
        # Process each (id, venue_id) group
        results = []
        for (id_val, venue_id_val), df_g in df_source.groupby(["id", "venue_id"]):
            df_g = df_g.sort_values("ts").copy()
            # Call indicator functions from indicators_derivatives.py
            # with inplace=True pattern
            ...
            results.append(df_g)
        return pd.concat(results, ignore_index=True) if results else pd.DataFrame()
```

### Pattern 6: Indicator Function API Convention

**What:** All 8+ indicator functions follow the same API as `indicators.py` and `indicators_extended.py`.
**Source:** `indicators_extended.py` from Phase 103 (pattern directly verified from `indicators.py`).

```python
# Source: src/ta_lab2/features/indicators.py API pattern

def oi_momentum(
    df: pd.DataFrame,
    window: int = 14,
    *,
    oi_col: str = "oi",
    out_col: str | None = None,
    inplace: bool = False,
) -> pd.Series | pd.DataFrame:
    """
    OI momentum: rate of change of open interest over N periods.
    Generic name — applies to any futures/derivatives market.
    """
    if out_col is None:
        out_col = f"oi_mom_{window}"
    s = df[oi_col].astype(float)
    result = s.pct_change(window)
    if inplace:
        df[out_col] = result
        return df
    return result.rename(out_col)
```

### Pattern 7: Features Table Column Addition (Alembic Migration)

**What:** New derivatives indicator columns added to `public.features` via ALTER TABLE.
**Pattern source:** Phase 103 migration `p103_seed_extended_indicators.py` (exact pattern reference) and Phase 98 migration `r2s3t4u5v6w7` (confirms ALTER TABLE features is the approach).

```python
# Source: Phase 98 migration r2s3t4u5v6w7 — verified pattern for adding columns to features

from alembic import op
import sqlalchemy as sa

# In upgrade():
NEW_COLS = [
    ("oi_mom_14",          sa.Float()),
    ("oi_price_div_z",     sa.Float()),
    ("funding_z_14",       sa.Float()),
    ("funding_mom_14",     sa.Float()),
    ("vol_oi_regime",      sa.SmallInteger()),  # 1-6 classifier
    ("force_idx_deriv_13", sa.Float()),
    ("oi_conc_ratio",      sa.Float()),
    ("liq_pressure",       sa.Float()),
]
for col_name, col_type in NEW_COLS:
    op.add_column("features", sa.Column(col_name, col_type, nullable=True), schema="public")
```

**CRITICAL:** `BaseFeature._get_table_columns()` queries `information_schema.columns` at runtime to filter DataFrame to only existing columns. Adding columns to the features table via migration is sufficient — no separate CREATE TABLE needed.

### Pattern 8: Features Table Write (existing column filtering)

**What:** `BaseFeature.write_to_db()` uses `_get_table_columns()` to filter to only columns present in the DB table. This means new derivative indicator columns will only be written after the migration runs.
**Warning sign:** If migration has not run, derivative columns are silently dropped on write (no error, but data is lost). Verify migration ran before running DerivativesFeature.

### Pattern 9: dim_feature_registry Promotion

**What:** Survivors from FDR go to `dim_feature_registry` with `lifecycle='promoted'`. Rejects get `lifecycle='deprecated'`.
**Source:** `103-RESEARCH.md` Pattern 3 (confirmed — uses `lifecycle` column, NOT `is_active`).

```python
# Source: established in Phase 103 research — dim_feature_registry schema from 6f82e9117c58 migration
# lifecycle values: 'experimental', 'promoted', 'deprecated'
# source_type: use the 'tags' column (TEXT[]) to store ['source_type:derivatives', 'venue:hyperliquid']
# Rationale: dim_feature_registry has no source_type column; tags is the flexible classification field
```

### Anti-Patterns to Avoid

- **Using HL `asset_id` as `id` in `public.features`:** The `features` table `id` column is CMC id (INTEGER). HL `asset_id` is a separate SmallInteger namespace. Always resolve via `dim_listings` join before writing.
- **Reading from `hl_candles` without specifying `interval`:** `hl_candles` PK is `(asset_id, interval, ts)`. Omitting the `interval` filter returns all intervals (daily, 4h, 1h, etc.) duplicated. Always filter `WHERE interval = '1d'` for daily features.
- **Treating Coinalyze OI as the primary source:** `hl_open_interest` (Coinalyze) has gaps. `hl_candles.open_oi` / `hl_candles.close_oi` are the HL-native OI columns and are more complete. Use Coinalyze only to fill gaps in HL-native OI.
- **Computing z-scores using global mean/std across all assets:** Z-scores must be per-asset rolling windows (PARTITION BY id), same as existing `add_zscore_util()` in `feature_utils.py`. Never cross-sectional for time-series features.
- **Normalizing funding rates before computing indicators:** Raw funding rate z-scores should be computed on the raw rate, not on a pre-normalized version. The rolling z-score IS the normalization step.
- **Creating a separate `crypto_features` table:** CONTEXT.md decision: write to `public.features` (the unified features table). Use Alembic ALTER TABLE to add new columns.
- **Volume-OI regime as a continuous float:** The regime classifier returns INTEGER categories 1-6, not a continuous value. Store as `SMALLINT`. This makes it readable as a regime label in IC sweeps (treat as ordinal).
- **Skipping the features table entirely and running IC directly from HL tables:** The IC sweep (`run_ic_sweep.py`) reads from `public.features`. Derivatives indicators must be written to `public.features` first before IC sweep picks them up.

---

## Indicator Formulas Reference

All 8 required indicators with verified formulas. Source: Kaufman "Trading Systems and Methods" (referenced in Phase 103 for Force Index), Elder "Trading for a Living" (Force Index), and first-principles derivation for crypto-native concepts.

### 1. OI Momentum (oi_mom_N)
```
oi_mom_N = (oi_t - oi_{t-N}) / oi_{t-N}  # percent change
```
Output col: `oi_mom_14` (default window=14)
Use hl_candles.close_oi as the OI source (HL-native, most complete).

### 2. OI-Price Divergence Z-Score (oi_price_div_z)
```
oi_change = oi_t / oi_{t-1} - 1        # OI % change
px_change = close_t / close_{t-1} - 1  # Price % change
divergence = oi_change - px_change      # raw divergence
oi_price_div_z = rolling_zscore(divergence, window=20)
```
Output col: `oi_price_div_z` (single window, 20-period rolling z-score)
Interpretation: Positive = OI growing faster than price (crowding). Negative = price rising on falling OI (short squeeze potential).

### 3. Funding Rate Z-Score (funding_z_N)
```
funding_z_N = rolling_zscore(funding_rate, window=N)
             = (funding_rate - rolling_mean(N)) / rolling_std(N)
```
Output col: `funding_z_14` (window=14, approximately 2 weeks of daily data)
Source: `hl_funding_rates.funding_rate` aggregated to daily (sum of hourly rates or last rate of day). Funding is 1h on HL; aggregate to daily by summing 8 periods (8h equivalent) or taking the end-of-day value.

### 4. Funding Rate Momentum (funding_mom_N)
```
funding_mom_N = funding_z_t - funding_z_{t-N}
```
Output col: `funding_mom_14` (rate of change of the z-scored funding rate)
This measures acceleration of funding sentiment, not just level.

### 5. Volume-OI Regime Classifier (vol_oi_regime) — Kaufman Ch. 12
Kaufman's 4-quadrant matrix: (OI direction) x (Volume direction), extended with price direction.

```
6 regimes (INTEGER 1-6):
  1: OI up,   Volume up,   Price up   -- new longs entering (bullish accumulation)
  2: OI up,   Volume up,   Price down -- new shorts entering (bearish accumulation)
  3: OI down, Volume up,   Price up   -- shorts covering (short squeeze / rally)
  4: OI down, Volume up,   Price down -- longs liquidating (capitulation)
  5: OI up,   Volume down, any        -- low-conviction directional build
  6: OI down, Volume down, any        -- position unwinding, low conviction

Implementation:
  oi_dir = sign(oi_t - oi_{t-1})       # 1 if up, -1 if down
  vol_dir = sign(vol_t - vol_{t-1})    # 1 if up, -1 if down
  px_dir = sign(close_t - close_{t-1}) # 1 if up, -1 if down
```
Output col: `vol_oi_regime` (SMALLINT 1-6)

### 6. Force Index (force_idx_deriv_N) — Elder
Adapted from Elder's Force Index for derivatives: uses OI-weighted volume instead of raw volume.

```
raw_force = (close_t - close_{t-1}) * volume * oi_t / mean_oi
force_idx_deriv_N = EMA(raw_force, N)
```
Output col: `force_idx_deriv_13` (Elder's standard 13-period EMA)
Note: The existing `force_index()` function in `indicators_extended.py` (Phase 103) uses raw volume. This derivatives version incorporates OI weighting. Use `_ema()` from `indicators.py`.

### 7. OI Concentration Ratio (oi_conc_ratio)
**Claude's discretion: cross-asset within the same venue at each timestamp.**

```
For asset i at time t:
  oi_conc_ratio_i_t = oi_i_t / sum(oi_all_assets_t)
  oi_conc_ratio_z = rolling_zscore(oi_conc_ratio, window=30)
```
Output col: `oi_conc_ratio` (raw ratio) and/or `oi_conc_ratio_z` (z-scored)
**Rationale for cross-asset (not cross-venue):** A single venue (HL) is available. Cross-asset concentration tells how much of total HL perp OI is concentrated in a single asset — high values indicate crowding risk or dominance. This is more informative than a cross-venue ratio which would require two live venues.
**Implementation note:** Requires computing across all HL perp assets at each timestamp, then mapping back per-asset. This is a cross-sectional computation; must be done outside the per-asset groupby loop.

### 8. Liquidation Pressure Proxy (liq_pressure)
**Claude's discretion: three-factor composite score.**

```
Components:
  A = funding_z_14         -- extreme funding (high = crowded, likely to be squeezed)
  B = oi_mom_14            -- OI acceleration (rapid OI build = more trapped positions)
  C = oi_price_div_z       -- divergence (OI diverging from price = increasing imbalance)

liq_pressure = (
    A * sign_correction          # high positive funding → long squeeze risk
    + abs(B) * 0.5               # rapid OI change in either direction
    + abs(C) * 0.5               # OI-price divergence regardless of direction
) / 3

# sign_correction: if price is rising and funding is very negative, short squeeze
# if price is falling and funding is very positive, long liquidation
# Simplification: liq_pressure = |funding_z_14| * 0.4 + |oi_mom_14| * 0.3 + |oi_price_div_z| * 0.3
```
Output col: `liq_pressure` (composite float, higher = more liquidation risk)
**Rationale:** The liquidation proxy combines three independently validated signals (funding extremes, OI momentum, OI-price divergence) into one composite. Each component captures a different channel through which liquidations build. The absolute values ensure both long and short liquidation pressure are captured symmetrically.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Asset ID mapping (HL -> CMC) | Custom symbol lookup | JOIN via `dim_listings` on `(symbol, venue='HYPERLIQUID')` | Already populated by `seed_hl_assets.py`; same approach used throughout codebase |
| Funding rate daily aggregation | Custom hourly-to-daily rollup | GROUP BY DATE_TRUNC('day', ts) with SUM or LAST | Standard SQL; don't re-implement in pandas for the adapter query |
| Z-score computation | Custom rolling mean/std | `feature_utils.add_zscore()` (or inline rolling per existing pattern) | Project standard: `add_zscore_util(df, col, window, out_col)` |
| EMA for Force Index | Custom EWM | `_ema()` from `indicators.py` | Project standard; already imported in indicators_extended.py |
| FDR correction | Custom BH loop | `multiple_testing.fdr_control()` (Phase 102) | Already built and wired into IC sweep |
| Trial registry logging | Custom INSERT | `log_trials_to_registry()` from `multiple_testing.py` (Phase 102) | Already built and wired into IC sweep |
| dim_feature_registry upsert | Custom upsert | Follow Phase 103 `run_phase103_ic.py` pattern | `lifecycle` column, not `is_active` — established precedent |
| Features table column discovery | `SELECT *` assumptions | `BaseFeature._get_table_columns()` | Runtime column introspection; filters to actual DB columns |

**Key insight:** The primary implementation challenge is the HL asset_id -> CMC id namespace resolution and the daily aggregation of hourly funding rates. Both have clear existing patterns to follow.

---

## Common Pitfalls

### Pitfall 1: Using HL asset_id instead of CMC id in public.features

**What goes wrong:** Writes to `public.features` with `id` column containing HL asset_id (e.g., 0, 1, 2...) instead of CMC id (e.g., 1 for BTC, 1027 for ETH). This corrupts the features table.
**Why it happens:** `hyperliquid.hl_assets.asset_id` is the natural key when querying HL tables, but `public.features.id` expects CMC id.
**How to avoid:** The adapter must ALWAYS resolve HL asset_id to CMC id via `dim_listings` JOIN before returning data. Column in output DataFrame must be named `id` (not `asset_id`).
**Warning signs:** IC sweep for BTC (CMC id=1) finds no data in features; or IC results reference wrong assets.

### Pitfall 2: Not filtering hl_candles by interval

**What goes wrong:** Query returns multiple rows per asset per day (one per interval: '1d', '4h', '1h', etc.).
**Why it happens:** `hl_candles` PK is `(asset_id, interval, ts)` — all intervals are stored together.
**How to avoid:** Always add `WHERE interval = '1d'` to hl_candles queries in the daily adapter.
**Warning signs:** DataFrame has 24x expected rows; duplicate timestamps per asset.

### Pitfall 3: Coinalyze OI (hl_open_interest) and HL-native OI (hl_candles.close_oi) Have Different Coverage

**What goes wrong:** Treating `hl_open_interest` (Coinalyze) as the primary OI source when it has more gaps than `hl_candles.open_oi`/`close_oi`.
**Why it happens:** Coinalyze OI requires a paid API and has missing periods; HL-native OI in candles is sampled at each bar.
**How to avoid:** Use `hl_candles.close_oi` as primary. Fill nulls from `hl_open_interest.close` using a date-matched LEFT JOIN. If both are null, propagate NaN (do not forward-fill across multi-day gaps without flagging).
**Warning signs:** Large blocks of NaN in OI columns for certain date ranges.

### Pitfall 4: Funding Rate Aggregation Mismatch

**What goes wrong:** Daily features computed from hourly funding rates have inconsistent aggregation — sometimes 24 periods summed, sometimes just the last value.
**Why it happens:** Hyperliquid funding settles every 1h; "daily" funding can mean sum, last, or mean depending on context.
**How to avoid:** Use sum of 8h equivalent (last 8 hourly rates per day, matching HL's 8h settlement cycle convention) OR end-of-day value. Document the choice in the adapter. For IC testing, the specific aggregation method matters less than consistency — pick ONE and use it throughout.
**Warning signs:** Funding z-scores that look flat (mean aggregation cancels intraday spikes) or noisy (all 24 periods summed amplifies weekends).

### Pitfall 5: OI Concentration Ratio Requires Cross-Asset Batch Processing

**What goes wrong:** Computing `oi_conc_ratio` inside a per-asset groupby loop gives each asset its own denominator (always = 1.0).
**Why it happens:** The ratio requires dividing each asset's OI by the sum of ALL assets' OI at each timestamp.
**How to avoid:** Compute `oi_conc_ratio` in a dedicated cross-asset pass BEFORE the per-asset indicator loop. Load OI for all HL perp assets simultaneously, compute the total, then join back per asset.
**Warning signs:** `oi_conc_ratio` = 1.0 for all assets (per-asset denominator = self).

### Pitfall 6: Windows UTF-8 Box-Drawing Characters in Alembic

**What goes wrong:** `UnicodeDecodeError` on Windows when Alembic migration contains box-drawing characters or non-ASCII in SQL strings.
**Why it happens:** Alembic runs SQL files on Windows with cp1252 encoding by default.
**How to avoid:** Use ASCII-only comments in all Alembic migration files. Verified pattern from existing migrations (e.g., `a0b1c2d3e4f5_strip_cmc_prefix_add_venue_id.py` header: "All comments use ASCII only").
**Warning signs:** Migration fails on Windows with `UnicodeDecodeError` during `alembic upgrade head`.

### Pitfall 7: Volume-OI Regime as Float

**What goes wrong:** Storing the 6-category regime as DOUBLE PRECISION causes IC sweep to treat it as a continuous variable. IC computation on a {1,2,3,4,5,6} ordinal is meaningless as IC.
**Why it happens:** Default feature column type is DOUBLE PRECISION; regime classifier returns integers.
**How to avoid:** Store `vol_oi_regime` as SMALLINT in the migration. When running IC sweep, either (a) skip this column from the IC sweep and use it as a regime slicing variable instead, or (b) run IC on ordinal-coded dummies. Recommendation: add `vol_oi_regime` to `_EXTRA_NON_FEATURE_COLS` in `run_phase104_ic.py` and use it as a conditioning variable (like `regime_col`) instead of treating it as a feature.

### Pitfall 8: dim_feature_registry Uses lifecycle NOT is_active

**What goes wrong:** Code tries to set `is_active = True` on `dim_feature_registry` rows, getting `AttributeError` or SQL column error.
**Why it happens:** The success criteria mention "is_active = true" as shorthand, but the actual schema (migration `6f82e9117c58`) has a `lifecycle TEXT` column with CHECK constraint `IN ('experimental', 'promoted', 'deprecated')`.
**How to avoid:** Use `lifecycle='promoted'` for survivors and `lifecycle='deprecated'` for rejects. Confirmed in Phase 103 research. Source: migration `6f82e9117c58_feature_experiment_tables.py`.
**Warning signs:** `column "is_active" of relation "dim_feature_registry" does not exist`.

---

## Code Examples

### Normalized Input Layer — Core Query Pattern

```python
# Source: verified against hl schema migration f7a8b9c0d1e2 + dim_listings pattern from seed_hl_assets.py

def load_hl_derivatives(conn, cmc_ids: list[int], tf: str = "1D",
                         start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """
    Returns unified derivatives frame with CMC id as 'id' column.
    Empty DataFrame (not error) if no HL data for requested CMC ids.
    """
    date_filter = ""
    params: dict = {"ids": cmc_ids}
    if start:
        date_filter += " AND c.ts >= :start"
        params["start"] = start
    if end:
        date_filter += " AND c.ts <= :end"
        params["end"] = end

    sql = text(f"""
        SELECT
            dl.id           AS id,
            2               AS venue_id,
            c.ts            AS ts,
            COALESCE(c.close_oi, oi.close)  AS oi,
            f.daily_funding AS funding_rate,
            c.volume        AS volume,
            c.close         AS close,
            s.mark_px       AS mark_px
        FROM dim_listings dl
        JOIN hyperliquid.hl_assets ha
          ON ha.symbol = dl.symbol AND dl.venue = 'HYPERLIQUID'
        JOIN hyperliquid.hl_candles c
          ON c.asset_id = ha.asset_id AND c.interval = '1d'
        LEFT JOIN (
            SELECT asset_id, DATE_TRUNC('day', ts) AS day,
                   SUM(funding_rate) AS daily_funding
            FROM hyperliquid.hl_funding_rates
            GROUP BY asset_id, DATE_TRUNC('day', ts)
        ) f ON f.asset_id = ha.asset_id AND f.day = DATE_TRUNC('day', c.ts)
        LEFT JOIN hyperliquid.hl_open_interest oi
          ON oi.asset_id = ha.asset_id AND oi.ts = c.ts
        LEFT JOIN LATERAL (
            SELECT mark_px FROM hyperliquid.hl_oi_snapshots s2
            WHERE s2.asset_id = ha.asset_id
              AND s2.ts <= c.ts
            ORDER BY s2.ts DESC LIMIT 1
        ) s ON TRUE
        WHERE dl.id = ANY(:ids){date_filter}
          AND ha.asset_type = 'perp'
        ORDER BY id, ts
    """)

    df = pd.read_sql(sql, conn, params=params)
    if df.empty:
        return df

    # CRITICAL: fix tz-naive timestamps from pd.read_sql on Windows
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

### Z-Score Rolling Pattern (project standard)

```python
# Source: feature_utils.add_zscore pattern, verified from base_feature.py

import numpy as np

def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    """Rolling z-score: (x - rolling_mean) / rolling_std. NaN for first window-1 bars."""
    mean = s.rolling(window, min_periods=window).mean()
    std = s.rolling(window, min_periods=window).std()
    return (s - mean) / std.replace(0.0, np.nan)
```

### Volume-OI Regime Classifier

```python
# Source: Kaufman Ch.12 4-quadrant, extended with price direction per CONTEXT.md decision

def vol_oi_regime(
    df: pd.DataFrame,
    *,
    oi_col: str = "oi",
    vol_col: str = "volume",
    close_col: str = "close",
    out_col: str = "vol_oi_regime",
    inplace: bool = False,
) -> pd.Series | pd.DataFrame:
    """
    6-regime classifier: (OI direction) x (Volume direction) x (Price direction).
    Returns SMALLINT 1-6.
    """
    oi_dir  = df[oi_col].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    vol_dir = df[vol_col].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    px_dir  = df[close_col].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

    conditions = [
        (oi_dir == 1)  & (vol_dir == 1)  & (px_dir == 1),   # regime 1
        (oi_dir == 1)  & (vol_dir == 1)  & (px_dir == -1),  # regime 2
        (oi_dir == -1) & (vol_dir == 1)  & (px_dir == 1),   # regime 3
        (oi_dir == -1) & (vol_dir == 1)  & (px_dir == -1),  # regime 4
        (oi_dir == 1)  & (vol_dir <= 0),                     # regime 5
        (oi_dir == -1) & (vol_dir <= 0),                     # regime 6
    ]
    choices = [1, 2, 3, 4, 5, 6]
    import numpy as np
    result = pd.Series(np.select(conditions, choices, default=0),
                       index=df.index, name=out_col, dtype="Int16")
    if inplace:
        df[out_col] = result
        return df
    return result
```

### Alembic Migration Pattern (Phase 104)

```python
# Source: Phase 98 migration r2s3t4u5v6w7 pattern (ALTER TABLE features ADD COLUMN)
# Chain from: current Alembic HEAD depends on what Phase 103 migration ID is.
# If Phase 103 is NOT yet merged: chain from s3t4u5v6w7x8 (Phase 99 HEAD).
# If Phase 103 IS merged: chain from Phase 103 migration ID.

# ASCII-only comments required for Windows compatibility

revision = "u5v6w7x8y9z0"          # placeholder — generate with alembic revision
down_revision = "s3t4u5v6w7x8"     # Phase 99 HEAD (or Phase 103 ID if merged)

DERIVATIVES_COLS = [
    "oi_mom_14",
    "oi_price_div_z",
    "funding_z_14",
    "funding_mom_14",
    "vol_oi_regime",      # SMALLINT
    "force_idx_deriv_13",
    "oi_conc_ratio",
    "liq_pressure",
]
```

---

## Key Technical Decisions (Claude's Discretion — resolved)

### Missing Venue Behavior

**Decision:** Return empty DataFrame (not NaN rows, not error). Indicators that receive empty DataFrame return empty Series. The `compute_features()` groupby loop produces zero result rows. This propagates cleanly: `write_to_db()` skips the write; no NULL rows are inserted into `public.features`.
**Rationale:** NaN rows for a missing venue would incorrectly imply "we tried to compute this for this asset at this time and got NaN." An empty frame correctly conveys "this venue has no data for this asset."

### HL vs Coinalyze OI Priority

**Decision:** Use `hl_candles.close_oi` as primary (HL-native OI, directly from Hyperliquid). Use `hl_open_interest.close` (Coinalyze) to fill NULLs where `close_oi` is NULL. If both are NULL, propagate NaN.
**Rationale:** HL-native OI (`close_oi` in candles) is sampled at each bar boundary, same frequency as price. Coinalyze OI has external dependency and more gaps. Using `COALESCE(c.close_oi, oi.close)` in the query implements this efficiently.

### Z-Score Windows

**Decision:** Use three window sizes: 14 (approximately 2 weeks — captures recent regime), 30 (approximately 1 month — medium-term), 90 (approximately 3 months — long-term). Run IC sweep on all three windows per indicator and let FDR select survivors.
**Rationale:** Different assets have different signal decay rates. Rather than picking one window and potentially missing the optimal horizon, let the IC evidence decide. Phase 102 pattern.

### source_type Implementation

**Decision:** Use the `tags TEXT[]` column on `dim_feature_registry` to classify: `tags = ARRAY['source_type:derivatives', 'venue:hyperliquid']`. This avoids schema changes to `dim_feature_registry`.
**Rationale:** `dim_feature_registry` has no `source_type` column (verified from migration `6f82e9117c58`). The `tags` column is the flexible classification field designed for exactly this purpose.

### Funding Rate Daily Aggregation

**Decision:** Use sum of last 8 hourly funding rates per day (aligned to UTC midnight). This approximates the 8h settlement cycle Hyperliquid uses.
**Rationale:** HL funding settles 8h per cycle. Summing 8 hourly rates gives the 8h equivalent rate at end of day. This is more economically meaningful than summing all 24 rates (which overstates the daily cost) or taking the last rate only (which misses earlier rate variations).

---

## Alembic Chain Context

**Current HEAD:** `s3t4u5v6w7x8` (Phase 99 backtest scaling migration, verified from `alembic/versions/` listing)
**Phase 103 migrations:** NOT yet committed to `alembic/versions/` directory (verified — no `p103_*` files found). Phase 103 migrations will chain from `s3t4u5v6w7x8`.
**Phase 104 chain:**
- If planning Phase 104 before Phase 103 merges: create Phase 104 migration chaining from the Phase 103 migration ID (to be determined when Phase 103-02 executes)
- The planner should note Phase 104 migration depends on Phase 103 migration ID

---

## Open Questions

1. **dim_listings venue string for Hyperliquid**
   - What we know: `seed_hl_assets.py` uses `venue = 'HYPERLIQUID'` in dim_listings JOIN queries
   - What's unclear: Exact string value stored in `dim_listings.venue` — the query in Pattern 3 assumes `'HYPERLIQUID'`. Verify before implementing: `SELECT DISTINCT venue FROM dim_listings WHERE venue ILIKE 'hyper%'`
   - Recommendation: Planner should note this as a pre-flight check in plan 104-01 task 1.

2. **hl_candles.close_oi NULL coverage**
   - What we know: Schema has `close_oi NUMERIC nullable` — NULLs are expected
   - What's unclear: What fraction of rows have NULL `close_oi` vs populated. If >50% are NULL for major assets, Coinalyze becomes more important than assumed.
   - Recommendation: Add a pre-flight query in plan 104-01 to assess NULL coverage: `SELECT COUNT(*), COUNT(close_oi) FROM hyperliquid.hl_candles WHERE interval='1d'`

3. **Phase 103 Alembic ID for chain**
   - What we know: Phase 103 plan 02 creates `alembic/versions/p103_seed_extended_indicators.py` — the actual revision ID will be assigned at execution time
   - What's unclear: The actual revision ID string (not known until Phase 103-02 runs)
   - Recommendation: Phase 104 migration `down_revision` should reference Phase 103's migration ID. If Phase 104 is planned and executed before Phase 103, use `s3t4u5v6w7x8` as `down_revision` and update when Phase 103 merges.

4. **vol_oi_regime treatment in IC sweep**
   - What we know: The regime classifier produces integers 1-6, which make poor continuous IC targets
   - What's unclear: Whether to (a) skip it from IC sweep entirely and use as conditioning variable, or (b) treat ordinal regimes as features and compute IC vs forward returns
   - Recommendation: Include it in IC sweep to get empirical IC evidence, but note that IC for a 6-category ordinal variable is a rank correlation — this is still valid. The IC value will be meaningful. Add note in plan 104-03 that `vol_oi_regime` IC interpretation differs from continuous indicators.

---

## Sources

### Primary (HIGH confidence)
- `alembic/versions/f7a8b9c0d1e2_hyperliquid_tables.py` — exact HL table schemas (column names, types, PKs, NULLability)
- `src/ta_lab2/scripts/features/base_feature.py` — full template method pattern, `_get_table_columns()`, `write_to_db()` scoped DELETE + to_sql pattern
- `src/ta_lab2/scripts/features/ta_feature.py` — `TAFeature` dispatch pattern, `compute_for_ids()` flow
- `src/ta_lab2/features/indicators.py` — indicator function API (obj, window, *, col args, out_col, inplace)
- `src/ta_lab2/analysis/ic.py` — `load_feature_series()` uses `public.features` with `id` column (not `asset_id`)
- `src/ta_lab2/scripts/analysis/run_ic_sweep.py` — IC sweep reads `public.features`, `_NON_FEATURE_COLS`, `_EXTRA_NON_FEATURE_COLS` exclusion pattern
- `alembic/versions/6f82e9117c58_feature_experiment_tables.py` — `dim_feature_registry` schema: `lifecycle TEXT CHECK IN ('experimental','promoted','deprecated')`, `tags TEXT[]`
- `alembic/versions/r2s3t4u5v6w7_phase98_ctf_graduation_schema.py` — ALTER TABLE features ADD COLUMN pattern
- `alembic/versions/s3t4u5v6w7x8_phase99_backtest_scaling.py` — current Alembic HEAD revision
- `.planning/phases/103-traditional-ta-expansion/103-RESEARCH.md` — Phase 103 patterns (indicators_extended.py API, dim_feature_registry lifecycle, features table migration pattern)
- `.planning/phases/102-indicator-research-framework/102-RESEARCH.md` — Phase 102 patterns (trial_registry, multiple_testing.py, FDR pipeline)
- `src/ta_lab2/scripts/etl/seed_hl_assets.py` — HL asset_id to CMC id resolution via dim_listings

### Secondary (MEDIUM confidence)
- Kaufman "Trading Systems and Methods" Ch. 12 — Volume-OI regime classifier (4-quadrant framework; 6-regime extension derived from CONTEXT.md decision)
- Elder "Trading for a Living" — Force Index formula (EMA of direction * volume; derivatives variant adds OI weighting per Phase 104 scope)

### Tertiary (LOW confidence)
- First-principles derivation for liquidation pressure proxy formula — no single canonical source; composite of three sub-indicators whose individual validity is HIGH

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries locally verified; no new dependencies
- Architecture: HIGH — all patterns read directly from codebase (base_feature.py, ta_feature.py, migrations)
- HL table schemas: HIGH — read directly from Alembic migration f7a8b9c0d1e2
- ID namespace issue (HL vs CMC): HIGH — confirmed by reading seed_hl_assets.py and ic.py `load_feature_series()`
- Indicator formulas: HIGH for formulas 1-6 (standard derivatives concepts), MEDIUM for formulas 7-8 (Claude's discretion items with no single authoritative formula)
- Pitfalls: HIGH — all sourced from direct code inspection, not speculation

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable codebase patterns; HL schema stable since migration date 2026-03-11)
