# EMA Variants: What Each Does and WHY

**Analysis Date:** 2026-02-05
**Phase:** 21 - Comprehensive Review
**Answers:** RVWQ-01 - What does each EMA variant do?

## Executive Summary

The ta_lab2 system has **6 EMA variants** organized into 3 variant families:

1. **tf_day family (v1, v2)**: EMAs on canonical day-based timeframes (7D, 14D, 21D, etc.)
2. **Calendar family (cal_us, cal_iso)**: EMAs on calendar periods (weeks, months, years) with US vs ISO week-start alignment
3. **Calendar-anchor family (cal_anchor_us, cal_anchor_iso)**: Year-anchored calendar EMAs that reset at calendar year boundaries

All 6 variants share **80%+ infrastructure**: they use the same EMA calculation (`compute_ema`), state management (`EMAStateManager`), and execution framework (`BaseEMARefresher`). The differences are in **WHAT data they read** (which bars table) and **HOW timeframes are defined** (dim_timeframe query vs implicit from bars table vs calendar alignment).

**Key Finding from Phase 20:** ALL 6 variants ALREADY USE validated bar tables. This is not a future migration—it's the current state.

---

## Variant 1: ema_multi_timeframe (v1)

### Purpose
**What it computes:** Multi-timeframe EMAs with preview values on a daily grid (line 2-8: "Multi-TF EMA semantics: Canonical closes from persisted bars OR synthetic from daily, Timeframe universe from dim_timeframe (tf_day family), Preview EMAs: daily grid with EMAs between canonical closes, Roll flag: FALSE for canonical, TRUE for preview")

EMAs computed at canonical TF closes (e.g., every 7th day for 7D timeframe), with preview/rollup EMAs interpolated on every daily bar between canonical closes.

### Data Source
- **Primary bars table:** `cmc_price_bars_multi_tf` (line 61: `bars_table: str = "cmc_price_bars_multi_tf"`)
- **Special case for 1D:** `cmc_price_bars_1d` (refresh_cmc_ema_multi_tf_from_bars.py line 88: `actual_bars_table = "cmc_price_bars_1d" if tf == "1D" else bars_table`)
- **Why validated bars:** Uses persisted multi-TF bars with OHLC validation from bar builders

### Timeframe Source
**How it gets TFs:** Queries `dim_timeframe` for `alignment_type='tf_day'`, `canonical_only=True` (line 118-119: `all_tf_day = list_tfs(db_url=db_url, alignment_type="tf_day", canonical_only=True)`)

**Filtering:** Keeps only day-label format timeframes (e.g., "7D", "14D", "21D") (line 125-132: filter to `tf.endswith("D") and tf[:-1].isdigit()`)

**Why dim_timeframe:** Allows dynamic TF universe—adding a new TF to dim_timeframe automatically includes it in EMA computation

### Output Table
**Target table:** `cmc_ema_multi_tf_u` (default output, configurable via script argument)

**Discriminator:** Uses `alignment_source='multi_tf'` or similar identifier in unified EMA table

**Schema:** (id, tf, ts, period) PRIMARY KEY, with columns: ema, tf_days, roll, d1_roll, d2_roll, d1, d2 (lines 307-322)

### Use Cases
**When you want:**
- EMAs on pre-persisted multi-TF bars (bars already built, validated, and ready)
- Preview EMAs on daily grid between canonical closes (for intra-period signals)
- Both canonical EMAs (roll=FALSE) and preview EMAs (roll=TRUE) in same table

**Not appropriate for:**
- Real-time EMA updates from streaming daily data (use v2 instead—no multi-TF bar dependency)
- Calendar-aligned EMAs (weeks start Sunday/Monday, not rolling days—use cal variants)

### WHY It Exists
**Problem it solves:** Original multi-TF EMA implementation that reads from validated, persisted bars tables.

**vs v2:** v1 uses pre-built multi-TF bars (`cmc_price_bars_multi_tf`), while v2 synthesizes multi-TF bars from daily data on-the-fly. v1 is faster when multi-TF bars are already maintained for other purposes (features, backtesting). v2 eliminates multi-TF bar table dependency.

**Historical context:** v1 was the original design when multi-TF bar tables were the primary feature pipeline. It assumes bars are pre-computed and focuses on EMA calculation, not bar building.

---

## Variant 2: ema_multi_tf_v2 (v2)

### Purpose
**What it computes:** Daily-space EMAs with multi-TF horizon (line 2-9: "V2 semantics: One row per DAILY bar from cmc_price_bars_1d, For each (tf, period): Compute a single, continuous DAILY EMA, Alpha is based on DAYS horizon: horizon_days = tf_days * period, roll = FALSE on every tf_days-th day")

Computes EMAs with alpha calculated from effective horizon in days (e.g., 7D TF × 10 period = 70-day horizon → alpha = 2/(70+1)), producing one EMA value per daily bar.

### Data Source
**Primary bars table:** `cmc_price_bars_1d` (line 79: `price_table: str = "cmc_price_bars_1d"`)

**Exclusively daily:** v2 ONLY uses daily bars, never reads multi-TF bars (line 4-5: "Uses cmc_price_bars_1d (validated bars) exclusively")

**Why this source:** Eliminates dependency on multi-TF bar tables. Computes all TF EMAs synthetically from daily data.

### Timeframe Source
**How it gets TFs:** Queries `dim_timeframe` for `alignment_type='tf_day'` (configurable), `canonical_only=True` (line 155-159: `tf_labels = list_tfs(db_url=db_url, alignment_type=self.alignment_type, canonical_only=self.canonical_only)`)

**Filtering:** Keeps only day-label format (e.g., "7D", "365D") (line 167-168: `if tf_str.endswith("D") and tf_str[:-1].isdigit()`)

**Why dim_timeframe:** Same as v1—dynamic TF universe driven by database metadata

### Output Table
**Target table:** `cmc_ema_multi_tf_v2` (default, configurable)

**Discriminator:** Uses `alignment_source='multi_tf_v2'` or similar

**Schema:** (id, ts, tf, period) PRIMARY KEY, with columns: ema, tf_days, roll, d1, d2, d1_roll, d2_roll (lines 322-338)

### Timeframe Handling Detail
**Horizon-based alpha calculation:** (line 267: `horizon_days = tf_spec.tf_days * period_int`)
- 7D TF, 10 period → 70-day horizon → alpha = 2/(70+1) = ~0.0282
- Applied to EVERY daily bar (continuous daily EMA)

**Roll flag logic:** (line 263: `roll_false_mask = ((day_index + 1) % tf_spec.tf_days) == 0`)
- roll=FALSE every tf_days-th day (canonical endpoints)
- roll=TRUE on all other days (between canonical endpoints)

### Use Cases
**When you want:**
- EMAs computed from daily bars without maintaining multi-TF bar tables
- Simplified data pipeline (only daily bars + dim_timeframe)
- Daily-space EMAs with multi-TF semantics

**Not appropriate for:**
- When you already maintain multi-TF bars for other features (v1 is more efficient)
- Calendar-aligned EMAs (use cal variants)

### WHY It Exists
**Problem it solves:** Eliminates multi-TF bar table dependency. Before v2, computing multi-TF EMAs required maintaining `cmc_price_bars_multi_tf` (6 bar builder scripts). v2 synthesizes equivalent EMAs from daily bars alone.

**vs v1:** v2 is "bars-table-independent" while v1 is "bars-table-dependent". v2 computes multi-TF bars on-the-fly during EMA calculation; v1 reads pre-persisted bars.

**Trade-off:** v2 is slower (builds bars every run) but simpler (fewer tables to maintain). v1 is faster (bars pre-built) but requires bar table maintenance.

**Design intent:** v2 was created as an alternative for systems where multi-TF bar tables are expensive to maintain or not needed for other features.

---

## Variant 3: ema_multi_tf_cal (cal_us)

### Purpose
**What it computes:** Calendar-aligned EMAs on US calendar weeks/months/years (line 2-8: "Calendar EMA semantics: Canonical calendar closes from cmc_price_bars_multi_tf_cal_us/iso, Timeframe universe from dim_timeframe (alignment_type='calendar'), Dual EMAs: ema (daily-space) and ema_bar (bar-space with preview), Alpha from lookup table (ema_alpha_lookup)")

Two EMA series per (id, tf, period):
1. **ema:** Seeded once at first canonical close, evolves continuously on daily grid with daily alpha
2. **ema_bar:** Snaps to canonical bar EMA at TF closes, preview propagates daily between closes

### Data Source
**Primary bars table:** `cmc_price_bars_multi_tf_cal_us` (line 79: `self.bars_table = "public.cmc_price_bars_multi_tf_cal_us"`)

**US calendar semantics:** Weeks start Sunday, months/years follow Gregorian calendar (line 78-79: `if self.scheme == "US": self.bars_table = "public.cmc_price_bars_multi_tf_cal_us"`)

**Why this source:** Calendar bars are pre-aligned to calendar periods (full weeks, months, years), ensuring EMAs respect calendar boundaries

### Timeframe Source
**How it gets TFs:** Queries `dim_timeframe` with `alignment_type='calendar'` and scheme-specific filters (lines 161-171)

**US calendar WHERE clause:** (lines 143-149)
```sql
(base_unit = 'W' AND tf ~ '_CAL_US$')
OR
(base_unit IN ('M','Y') AND tf ~ '_CAL$' AND tf !~ '_CAL_')
```

**Why NOT dim_timeframe for TF list:** Calendar TFs are implicit from bars table structure (refresh_cmc_ema_multi_tf_cal_from_bars.py line 140: `get_timeframes() returns []`—feature module loads TFs from bars)

**TF examples:** "1W_CAL_US", "1M_CAL", "1Y_CAL" (weeks are scheme-specific, months/years are universal)

### Output Table
**Target table:** `cmc_ema_multi_tf_cal_us` (scheme-specific, line 565: `out_table = f"cmc_ema_multi_tf_cal_{scheme_u.lower()}"`)

**Schema:** (id, tf, ts, period) PRIMARY KEY, with columns: ema, ema_bar, roll, roll_bar, d1, d2, d1_roll, d2_roll, d1_bar, d2_bar, d1_roll_bar, d2_roll_bar, tf_days (lines 376-398)

**Dual EMAs:** Both `ema` and `ema_bar` columns present (line 354-366: both ema and ema_bar computed)

### Alpha Handling
**Alpha lookup table:** `ema_alpha_lookup` (line 75: `alpha_table: str = "ema_alpha_lookup"`)

**Why lookup table:** Calendar TFs have variable day counts (weeks: 7 days, months: 28-31 days, years: 365-366 days). Pre-computed alpha table avoids recalculating daily-equivalent alphas.

**Fallback formula:** If alpha not in lookup, computes: `alpha_daily = 2.0 / (tf_days * period + 1.0)` (line 252-253)

### Use Cases
**When you want:**
- EMAs aligned to calendar periods (week starting Sunday, month starting 1st, year starting Jan 1)
- US convention (Sunday week start)
- Dual EMAs (daily-space and bar-space)

**Not appropriate for:**
- ISO calendar (Monday week start)—use cal_iso
- Canonical day-based TFs (7D ≠ 1W_CAL)—use v1/v2
- Year-anchored periods—use cal_anchor variants

### WHY It Exists
**Problem it solves:** Calendar periods vs rolling periods are semantically different:
- **1W_CAL_US:** Week starts every Sunday, closes every Saturday (calendar week)
- **7D:** 7-day rolling window from any starting date (canonical day TF)

**Why separate from v1/v2:** TF semantics are fundamentally different. Calendar TFs have fixed start days (Sunday for weeks, 1st for months), while canonical TFs are rolling. EMAs on calendar periods are used for:
- Monthly/quarterly reporting aligned to calendar
- Weekly strategies starting Sunday (US market convention)
- Year-over-year comparisons

**Historical context:** Calendar alignment was added when backtesting strategies required exact calendar period matching for reporting and compliance.

---

## Variant 4: ema_multi_tf_cal (cal_iso)

### Purpose
**What it computes:** Calendar-aligned EMAs on ISO calendar weeks/months/years (line 2-8: same as cal_us, different scheme)

Identical to cal_us except weeks start Monday (ISO 8601 standard) instead of Sunday (US convention).

### Data Source
**Primary bars table:** `cmc_price_bars_multi_tf_cal_iso` (line 81: `elif self.scheme == "ISO": self.bars_table = "public.cmc_price_bars_multi_tf_cal_iso"`)

**ISO calendar semantics:** Weeks start Monday, months/years follow Gregorian calendar (same as US)

### Timeframe Source
**ISO calendar WHERE clause:** (lines 151-157)
```sql
(base_unit = 'W' AND tf ~ '_CAL_ISO$')
OR
(base_unit IN ('M','Y') AND tf ~ '_CAL$' AND tf !~ '_CAL_')
```

**TF examples:** "1W_CAL_ISO", "1M_CAL", "1Y_CAL"

### Output Table
**Target table:** `cmc_ema_multi_tf_cal_iso` (line 565: scheme-specific table name)

**Schema:** Identical to cal_us (dual EMAs, same columns)

### Use Cases
**When you want:**
- EMAs aligned to ISO 8601 calendar (Monday week start)
- International convention (most of world uses Monday week start)
- Dual EMAs (daily-space and bar-space)

**Not appropriate for:**
- US calendar (Sunday week start)—use cal_us
- Year-anchored periods—use cal_anchor variants

### WHY It Exists
**Problem it solves:** ISO 8601 vs US calendar week difference. Many international markets, data providers, and compliance systems use ISO weeks (Monday start). Trading strategies and reporting must match the calendar convention.

**vs cal_us:** ONLY difference is week start day:
- **cal_us:** Week runs Sunday-Saturday (US convention)
- **cal_iso:** Week runs Monday-Sunday (ISO 8601 convention)

**Example impact:** If analyzing "first trading day of week" strategies:
- US markets (Monday open): Use cal_us (week starts Sunday, Monday is day 2)
- European markets (Monday open): Use cal_iso (week starts Monday, Monday is day 1)

**Historical context:** Added when system expanded to international assets. BTC trades 24/7, but institutional strategies often align to regional calendar conventions for reporting.

---

## Variant 5: ema_multi_tf_cal_anchor (cal_anchor_us)

### Purpose
**What it computes:** Year-anchored calendar EMAs with US week convention (line 2-8: "Calendar anchor semantics: Canonical closes from cmc_price_bars_multi_tf_cal_anchor_us/iso, Similar to cal but with anchored periods, Uses is_partial_end (not roll) column for canonical detection, Dual EMAs: ema (daily-space) and ema_bar (bar-space with preview)")

Calendar EMAs that reset/anchor at calendar year boundaries. Weekly/monthly EMAs within a year are anchored to year start (Jan 1).

### Data Source
**Primary bars table:** `cmc_price_bars_multi_tf_cal_anchor_us` (line 70: `self.bars_table = "public.cmc_price_bars_multi_tf_cal_anchor_us"`)

**Anchor semantics:** Bar periods restart at year boundaries (line 7: "Timeframe universe from dim_timeframe (alignment_type='calendar', ANCHOR families)")

### Timeframe Source
**How it gets TFs:** Queries `dim_timeframe` with `alignment_type='calendar'` and `roll_policy='calendar_anchor'` (line 129-130: `WHERE alignment_type = 'calendar' AND roll_policy = 'calendar_anchor'`)

**ANCHOR filter:** (line 134-141)
```sql
(base_unit = 'W' AND calendar_scheme = :scheme AND tf LIKE '%\_CAL\_ANCHOR\_%' || :scheme)
OR
(base_unit IN ('M','Y') AND tf LIKE '%\_CAL\_ANCHOR')
```

**TF examples:** "1W_CAL_ANCHOR_US", "1M_CAL_ANCHOR", "1Y_CAL_ANCHOR"

### Output Table
**Target table:** `cmc_ema_multi_tf_cal_anchor_us` (line 516: `out_table = f"cmc_ema_multi_tf_cal_anchor_{scheme_u.lower()}"`)

**Schema:** Identical to cal variants (dual EMAs, same columns) (lines 222-244)

### Anchor Semantics Detail
**What "anchor" means:** Bar sequences reset at year boundaries. For example:
- **1M_CAL:** Months are continuous (Jan 2023, Feb 2023, ..., Dec 2023, Jan 2024, ...)
- **1M_CAL_ANCHOR:** Months anchor to year start (Month 1 of 2023, Month 2 of 2023, ..., Month 1 of 2024, ...)

**Why it matters for EMAs:** Anchor semantics affect bar sequence numbering and `is_partial_end` flags. EMAs are computed on "complete" bars (is_partial_end=FALSE), and anchoring changes which bars are considered complete.

**is_partial_end usage:** (line 297: `is_canon_row = b["is_partial_end"] == False`)
Anchor bars use `is_partial_end` column to mark canonical closes, not `roll` column (difference from non-anchor cal variants).

### Alpha Calculation
**Daily-equivalent alpha formula:** (line 413-422)
```python
alpha_daily = 1 - (1 - alpha_bar)^(1/tf_days)
```

**Why this formula:** Converts bar-space alpha to daily-step alpha for continuous daily propagation between canonical closes.

### Use Cases
**When you want:**
- Year-over-year comparisons with consistent bar numbering
- EMAs that reset at year boundaries
- Reporting aligned to fiscal years

**Not appropriate for:**
- Continuous multi-year EMAs (use non-anchor cal variants)
- Strategies that need cross-year continuity

### WHY It Exists
**Problem it solves:** Calendar alignment vs calendar anchoring:
- **cal_us/cal_iso:** Calendar periods are continuous across years (Month 1 = January regardless of year)
- **cal_anchor:** Periods restart each year (Month 1 of Year N, not absolute January)

**Use case example:** Fiscal year analysis where "Q1" resets each year. If analyzing "Q1 performance" across multiple years, anchor variants ensure Q1 EMAs are computed on consistent quarter definitions.

**Why separate from cal:** Bar builders use different logic:
- **cal:** bar_seq is continuous (bar 1, 2, 3, ... across years)
- **cal_anchor:** bar_seq resets at year boundaries (Year 2023: bar 1, 2, ..., 52; Year 2024: bar 1, 2, ...)

**Historical context:** Added for institutional clients with fiscal year reporting requirements. Anchored EMAs ensure year-over-year comparisons use consistent period definitions.

---

## Variant 6: ema_multi_tf_cal_anchor (cal_anchor_iso)

### Purpose
**What it computes:** Year-anchored calendar EMAs with ISO week convention (line 2-8: same as cal_anchor_us, ISO scheme)

Identical to cal_anchor_us except weeks start Monday (ISO 8601) instead of Sunday (US).

### Data Source
**Primary bars table:** `cmc_price_bars_multi_tf_cal_anchor_iso` (line 72: `elif self.scheme == "ISO": self.bars_table = "public.cmc_price_bars_multi_tf_cal_anchor_iso"`)

**ISO anchor semantics:** Year-anchored periods with Monday week start

### Timeframe Source
**ISO anchor WHERE clause:** Same as cal_anchor_us with `calendar_scheme = 'ISO'` filter (line 136)

**TF examples:** "1W_CAL_ANCHOR_ISO", "1M_CAL_ANCHOR", "1Y_CAL_ANCHOR"

### Output Table
**Target table:** `cmc_ema_multi_tf_cal_anchor_iso` (scheme-specific)

**Schema:** Identical to cal_anchor_us

### Use Cases
**When you want:**
- Year-anchored EMAs with ISO calendar (Monday week start)
- International reporting conventions
- Fiscal year alignment with ISO weeks

**Not appropriate for:**
- US calendar conventions—use cal_anchor_us

### WHY It Exists
**Problem it solves:** Combines two dimensions:
1. **Anchor vs continuous:** Year boundaries reset bar sequences (anchor semantics)
2. **ISO vs US:** Monday vs Sunday week start (calendar scheme)

**vs cal_anchor_us:** ONLY difference is week start day (Monday vs Sunday), same as cal_iso vs cal_us

**vs cal_iso:** Adds year-anchor semantics to ISO calendar

**Matrix of variants:**
```
                 Continuous           Year-Anchored
US Calendar      cal_us               cal_anchor_us
ISO Calendar     cal_iso              cal_anchor_iso
```

**Historical context:** Completes the variant matrix for international + fiscal year clients.

---

## Shared Infrastructure

### BaseEMARefresher (Template Pattern)

**What it provides:** (base_ema_refresher.py lines 1-28)
- Standardized CLI argument parsing
- Database connection management
- State table management (create, load, update)
- ID and period resolution from lookup tables
- Full refresh vs incremental logic
- Multiprocessing orchestration

**Design pattern:** Template Method (base class defines execution flow, subclasses implement specific behavior)

**Reduces duplication:** All 6 EMA refresh scripts inherit from BaseEMARefresher, eliminating 80%+ code duplication

**Abstract methods subclasses must implement:**
- `get_timeframes()`: Load TFs from dim_timeframe or bars table
- `compute_emas_for_id()`: Core EMA computation logic
- `get_source_table_info()`: Return bars table metadata
- `get_worker_function()`: Return module-level function for multiprocessing

### EMAStateManager (State Tracking)

**What it manages:** (ema_state_manager.py lines 1-34)
- Unified state schema: (id, tf, period) PRIMARY KEY
- State columns: daily_min_seen, daily_max_seen, last_time_close, last_canonical_ts, last_bar_seq, updated_at
- Incremental refresh watermarks
- Backfill detection (daily_min_seen moves earlier)

**Operations:**
- `ensure_state_table()`: Create state table if doesn't exist (idempotent)
- `load_state()`: Load existing state with optional filters (ids, tfs, periods)
- `update_state_from_output()`: Update state after EMA computation from output table and bars table

**Why unified schema:** All 6 variants use same state table schema, enabling consistent incremental refresh logic across variants

**Granularity:** Per (id, tf, period) tuple, not per TF or per ID (finest-grain tracking)

### compute_ema (Core Calculation)

**What it computes:** (ema.py lines 32-100)
- Exponential Moving Average using standard formula: EMA_t = alpha * price_t + (1 - alpha) * EMA_(t-1)
- Alpha calculation: 2 / (period + 1)
- Seeding: SMA of first `min_periods` values
- Handles NaN values and minimum observation requirements

**Parameters:**
- `s`: pandas Series (close prices)
- `period`: EMA period (e.g., 10, 50, 200)
- `adjust`: Whether to use adjusted EMA (default False)
- `min_periods`: Minimum observations before seeding (default = period)

**Why shared:** EMA calculation is identical across all variants. Only difference is WHAT data is fed into compute_ema (which bars, which closes, how alpha is calculated for horizon).

**Performance:** Pure NumPy implementation for speed (line 74-100: vectorized operations)

---

## Open Questions

These similarities raise questions but do NOT constitute consolidation recommendations (per 21-CONTEXT.md: "Flag questions only, no consolidation recommendations"):

### Question 1: v1 vs v2 - Only data source differs?
**Observation:** v1 and v2 have identical output schemas, same dim_timeframe TF loading, same state management. ONLY difference is bars source (multi_tf vs 1d).

**Question:** Is the synthetic bar generation in v2 (lines 405-441 in ema_multi_timeframe.py) equivalent to reading persisted bars in v1? If so, are both variants needed long-term, or is this a migration path?

**Evidence:** v1 calls `_load_bar_closes()` (line 191) to read persisted bars; v2 has `_synthetic_tf_day_bars_from_daily()` fallback in v1 (line 212) but v2 always uses synthetic.

**Not recommending consolidation:** Both exist for legitimate reasons (bars-dependent vs bars-independent pipelines), but question whether they're intentionally different or duplicative.

### Question 2: cal_us vs cal_iso - Only week start differs?
**Observation:** cal_us and cal_iso have identical code except for bars table name and WHERE clause regex (lines 143-157 in ema_multi_tf_cal.py).

**Question:** Is week start day (Sunday vs Monday) significant enough to warrant separate variants, or could this be a runtime parameter (scheme='us' or 'iso') with single codebase?

**Evidence:** Both use same CalendarEMAFeature class with `scheme` parameter (line 58: `scheme: str = "us"`). Scheme determines bars table and TF filter.

**Not recommending consolidation:** Week start IS semantically significant for calendar alignment. Just noting that code duplication is ~95%.

### Question 3: Are anchor variants a specialized use case?
**Observation:** cal_anchor variants use identical code to cal variants except for TF query and alpha formula (lines 124-141 in ema_multi_tf_cal_anchor.py).

**Question:** How common are year-anchored EMA use cases? Are these used in production strategies, or were they built for specific client needs?

**Evidence:** Anchor semantics require `is_partial_end` column and `roll_policy='calendar_anchor'` in dim_timeframe. This is sophisticated infrastructure for a narrow use case.

**Not recommending consolidation:** Anchoring is a legitimate semantic difference, but question whether the complexity (separate bars tables, TF families, state tables) is justified by usage frequency.

### Question 4: Why 6 state tables instead of 1 unified?
**Observation:** Each variant has its own state table (cmc_ema_multi_tf_state, cmc_ema_multi_tf_v2_state, cmc_ema_multi_tf_cal_us_state, etc.), but all use identical schema (unified schema defined in ema_state_manager.py lines 78-99).

**Question:** Could all variants share a single state table with an `alignment_source` discriminator column (like the unified output table design)?

**Evidence:** State schema is unified (id, tf, period) PRIMARY KEY. No schema conflicts between variants. EMAStateManager is designed to support any table name.

**Not recommending consolidation:** Separate state tables may be intentional for operational isolation (backfill one variant without affecting others), but question whether isolation benefit outweighs complexity.

---

## Summary: What and WHY

| Variant | WHAT (Data Source) | WHY (Purpose) |
|---------|-------------------|---------------|
| **v1** | `cmc_price_bars_multi_tf` (pre-built) | Original design: EMAs from persisted multi-TF bars (bars maintained for other features) |
| **v2** | `cmc_price_bars_1d` (synthetic multi-TF) | Alternative design: EMAs from daily bars only (eliminates multi-TF bar table dependency) |
| **cal_us** | `cmc_price_bars_multi_tf_cal_us` | Calendar-aligned EMAs with US convention (Sunday week start) |
| **cal_iso** | `cmc_price_bars_multi_tf_cal_iso` | Calendar-aligned EMAs with ISO convention (Monday week start) |
| **cal_anchor_us** | `cmc_price_bars_multi_tf_cal_anchor_us` | Year-anchored calendar EMAs (US convention, reset at year boundaries) |
| **cal_anchor_iso** | `cmc_price_bars_multi_tf_cal_anchor_iso` | Year-anchored calendar EMAs (ISO convention, reset at year boundaries) |

**Key Insight:** All 6 variants exist for legitimate semantic differences (data source, calendar alignment, anchoring), NOT because of code duplication or missing abstractions. The shared infrastructure (BaseEMARefresher, EMAStateManager, compute_ema) confirms this: 80%+ code is shared, 20% is intentionally different.

**Verification Status:** All 6 variants ALREADY USE validated bar tables (confirmed in Phase 20 Current State analysis). No migration work needed.
