# EMA Variant Comparison Matrix

**Deliverable:** RVWD-03 - Side-by-side variant comparison matrix
**Created:** 2026-02-05
**Phase:** 21 - Comprehensive Review

## Quick Reference Matrix

| Dimension | v1 (multi_tf) | v2 | cal_us | cal_iso | cal_anchor_us | cal_anchor_iso |
|-----------|---------------|----|---------|---------|--------------------|---------------------|
| **Data Source** |
| Bars table | cmc_price_bars_multi_tf | cmc_price_bars_1d | cmc_price_bars_multi_tf_cal_us | cmc_price_bars_multi_tf_cal_iso | cmc_price_bars_multi_tf_cal_anchor_us | cmc_price_bars_multi_tf_cal_anchor_iso |
| 1D special handling | Uses cmc_price_bars_1d for "1D" TF | N/A (synthesizes from 1D) | N/A | N/A | N/A | N/A |
| Data validated | Yes (bar builders) | Yes (bar builders) | Yes (bar builders) | Yes (bar builders) | Yes (bar builders) | Yes (bar builders) |
| **Timeframe Handling** |
| TF source | dim_timeframe query | dim_timeframe query | dim_timeframe query | dim_timeframe query | dim_timeframe query | dim_timeframe query |
| TF family | alignment_type='tf_day' | alignment_type='tf_day' | alignment_type='calendar' | alignment_type='calendar' | alignment_type='calendar' (ANCHOR) | alignment_type='calendar' (ANCHOR) |
| TF examples | 7D, 14D, 21D, 30D, 365D | 7D, 14D, 21D, 30D, 365D | 1W_CAL_US, 1M_CAL, 1Y_CAL | 1W_CAL_ISO, 1M_CAL, 1Y_CAL | 1W_CAL_ANCHOR_US, 1M_CAL_ANCHOR | 1W_CAL_ANCHOR_ISO, 1M_CAL_ANCHOR |
| TF filter | canonical_only=True, day-label format | canonical_only=True, day-label format | base_unit IN ('W','M','Y'), scheme-specific regex | base_unit IN ('W','M','Y'), scheme-specific regex | roll_policy='calendar_anchor' | roll_policy='calendar_anchor' |
| **Calendar Alignment** |
| Week start | N/A (rolling days) | N/A (rolling days) | Sunday (US convention) | Monday (ISO 8601) | Sunday (US convention) | Monday (ISO 8601) |
| Month/Year | N/A (rolling periods) | N/A (rolling periods) | Calendar months/years | Calendar months/years | Calendar months/years | Calendar months/years |
| Year anchoring | No | No | No | No | Yes (resets at Jan 1) | Yes (resets at Jan 1) |
| **EMA Calculation** |
| Core function | compute_ema | compute_ema | compute_ema | compute_ema | compute_ema | compute_ema |
| Alpha formula | 2/(period+1) | 2/(horizon_days+1) where horizon=tf_days*period | From ema_alpha_lookup table | From ema_alpha_lookup table | 1-(1-alpha_bar)^(1/tf_days) | 1-(1-alpha_bar)^(1/tf_days) |
| EMA types | ema (single series with preview) | ema (single daily series) | ema + ema_bar (dual series) | ema + ema_bar (dual series) | ema + ema_bar (dual series) | ema + ema_bar (dual series) |
| Preview EMAs | Yes (roll=TRUE for intra-period) | No (daily continuous) | Yes (daily propagation) | Yes (daily propagation) | Yes (daily propagation) | Yes (daily propagation) |
| **Roll Flag Semantics** |
| roll column | FALSE at canonical TF closes, TRUE between | FALSE every tf_days-th day, TRUE between | FALSE at calendar closes, TRUE between | FALSE at calendar closes, TRUE between | FALSE at canonical closes (is_partial_end=FALSE) | FALSE at canonical closes (is_partial_end=FALSE) |
| roll_bar column | No | No | Yes (FALSE at bar closes) | Yes (FALSE at bar closes) | Yes (FALSE at bar closes) | Yes (FALSE at bar closes) |
| **Refresh Logic** |
| Base class | BaseEMARefresher | BaseEMARefresher | BaseEMARefresher | BaseEMARefresher | BaseEMARefresher | BaseEMARefresher |
| State manager | EMAStateManager | EMAStateManager | EMAStateManager | EMAStateManager | EMAStateManager | EMAStateManager |
| State table | cmc_ema_multi_tf_state | cmc_ema_multi_tf_v2_state | cmc_ema_multi_tf_cal_us_state | cmc_ema_multi_tf_cal_iso_state | cmc_ema_multi_tf_cal_anchor_us_state | cmc_ema_multi_tf_cal_anchor_iso_state |
| State granularity | (id, tf, period) | (id, tf, period) | (id, tf, period) | (id, tf, period) | (id, tf, period) | (id, tf, period) |
| Incremental | Yes | Yes | Yes | Yes | Yes | Yes |
| Multiprocessing | Yes (per-ID workers) | Yes (per-ID workers) | Yes (per-ID workers) | Yes (per-ID workers) | Yes (per-ID workers) | Yes (per-ID workers) |
| **Output** |
| Target table | cmc_ema_multi_tf_u (default) | cmc_ema_multi_tf_v2 | cmc_ema_multi_tf_cal_us | cmc_ema_multi_tf_cal_iso | cmc_ema_multi_tf_cal_anchor_us | cmc_ema_multi_tf_cal_anchor_iso |
| Output schema | (id, tf, ts, period) PK | (id, ts, tf, period) PK | (id, tf, ts, period) PK | (id, tf, ts, period) PK | (id, tf, ts, period) PK | (id, tf, ts, period) PK |
| alignment_source | 'multi_tf' | 'multi_tf_v2' | 'cal_us' | 'cal_iso' | 'cal_anchor_us' | 'cal_anchor_iso' |
| ema column | Yes | Yes | Yes | Yes | Yes | Yes |
| ema_bar column | No | No | Yes | Yes | Yes | Yes |
| Derivatives | d1, d2, d1_roll, d2_roll | d1, d2, d1_roll, d2_roll | d1, d2, d1_roll, d2_roll, d1_bar, d2_bar, d1_roll_bar, d2_roll_bar | d1, d2, d1_roll, d2_roll, d1_bar, d2_bar, d1_roll_bar, d2_roll_bar | d1, d2, d1_roll, d2_roll, d1_bar, d2_bar, d1_roll_bar, d2_roll_bar | d1, d2, d1_roll, d2_roll, d1_bar, d2_bar, d1_roll_bar, d2_roll_bar |
| **Code Structure** |
| Feature module | ema_multi_timeframe.py | ema_multi_tf_v2.py | ema_multi_tf_cal.py | ema_multi_tf_cal.py (scheme='iso') | ema_multi_tf_cal_anchor.py | ema_multi_tf_cal_anchor.py (scheme='iso') |
| Refresh script | refresh_cmc_ema_multi_tf_from_bars.py | refresh_cmc_ema_multi_tf_v2.py | refresh_cmc_ema_multi_tf_cal_from_bars.py | refresh_cmc_ema_multi_tf_cal_from_bars.py (--scheme=iso) | refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py | refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py (--scheme=iso) |
| Lines of code (LOC) | ~350 (feature), ~150 (refresh) | ~180 (feature), ~150 (refresh) | ~480 (feature), ~150 (refresh) | Same feature module | ~430 (feature), ~150 (refresh) | Same feature module |
| Shared code % | ~80% (base class + state + compute_ema) | ~80% | ~80% | ~80% | ~80% | ~80% |

---

## Dimension-by-Dimension Analysis

### Data Sources

| Variant | Bars Table | Why This Source |
|---------|-----------|-----------------|
| v1 | cmc_price_bars_multi_tf | Persisted multi-TF bars already maintained for other features (backtesting, signals) |
| v2 | cmc_price_bars_1d | Eliminates multi-TF bar table dependency (synthesizes on-the-fly from daily) |
| cal_us | cmc_price_bars_multi_tf_cal_us | Pre-aligned to US calendar periods (Sunday-start weeks) |
| cal_iso | cmc_price_bars_multi_tf_cal_iso | Pre-aligned to ISO calendar periods (Monday-start weeks) |
| cal_anchor_us | cmc_price_bars_multi_tf_cal_anchor_us | Year-anchored US calendar periods (bar_seq resets at Jan 1) |
| cal_anchor_iso | cmc_price_bars_multi_tf_cal_anchor_iso | Year-anchored ISO calendar periods (bar_seq resets at Jan 1) |

**WHY sources differ:**
- **v1 vs v2:** Architectural choice—bars-dependent vs bars-independent pipeline
- **Calendar variants:** Calendar alignment MUST happen at bar-building stage (can't retrofit canonical TF bars to calendar periods)
- **Anchor variants:** Year-anchor semantics require different bar_seq numbering (reset at year boundaries)

**All sources validated:** Every bars table uses OHLC validation from bar builders (Phase 20 confirmation: "All 6 variants ALREADY USE validated bar tables").

---

### Timeframe Handling

#### TF Source: All variants use dim_timeframe

**v1 and v2:** Query `dim_timeframe` with `alignment_type='tf_day'`, filter to day-label format (7D, 14D, etc.)

Evidence:
- v1: ema_multi_timeframe.py line 118-119: `list_tfs(db_url=db_url, alignment_type="tf_day", canonical_only=True)`
- v2: ema_multi_tf_v2.py line 155-158: `list_tfs(db_url=db_url, alignment_type=self.alignment_type, canonical_only=self.canonical_only)`

**Calendar variants:** Query `dim_timeframe` with `alignment_type='calendar'`, filter by base_unit and scheme-specific regex

Evidence:
- cal: ema_multi_tf_cal.py lines 161-171: WHERE clause filters to W/M/Y with scheme suffix (_CAL_US or _CAL_ISO)
- cal_anchor: ema_multi_tf_cal_anchor.py lines 124-141: Additional filter `roll_policy='calendar_anchor'`

**WHY dim_timeframe:** Dynamic TF universe. Adding a new TF to dim_timeframe automatically includes it in EMA computation (no code changes needed).

#### TF Families: tf_day vs calendar vs calendar_anchor

**tf_day (v1, v2):**
- Rolling day-based periods (7D = any 7-day window)
- No fixed start day (7D can start Monday, Tuesday, etc.)
- TF examples: 1D, 7D, 14D, 21D, 30D, 90D, 365D

**calendar (cal_us, cal_iso):**
- Fixed-start calendar periods (weeks start Sunday/Monday, months start 1st, years start Jan 1)
- TF examples: 1W_CAL_US, 1W_CAL_ISO, 1M_CAL, 1Q_CAL, 1Y_CAL
- Continuous across years (Month 1 = January always)

**calendar_anchor (cal_anchor_us, cal_anchor_iso):**
- Calendar periods that reset at year boundaries
- TF examples: 1W_CAL_ANCHOR_US, 1M_CAL_ANCHOR, 1Y_CAL_ANCHOR
- bar_seq resets each year (Year 2023: bars 1-52, Year 2024: bars 1-52)

**Key semantic difference:** 7D ≠ 1W_CAL:
- 7D: 7-day rolling window, can start any day
- 1W_CAL: Calendar week (Sunday-Saturday or Monday-Sunday), fixed start day

---

### Calendar Alignment

**Why calendar alignment matters:**

1. **Week start day:**
   - US markets: Week conceptually starts Sunday (Monday is first trading day)
   - International: ISO 8601 standard starts Monday
   - Trading strategies: "First day of week" means different days

2. **Month/quarter/year boundaries:**
   - Financial reporting aligns to calendar months/quarters/years
   - "Monthly returns" means Jan 1-31, not rolling 30-day periods
   - Year-over-year comparisons require calendar year alignment

3. **Anchoring:**
   - Fiscal year analysis: "Q1 of 2023" vs "Q1 of 2024" must use same quarter definition
   - Year-anchored EMAs reset at Jan 1 (seeded fresh each year)
   - Continuous calendar EMAs carry across year boundaries

**Variant matrix:**

|                | Continuous (no anchor) | Year-Anchored |
|----------------|------------------------|---------------|
| US Calendar    | cal_us                 | cal_anchor_us |
| ISO Calendar   | cal_iso                | cal_anchor_iso |

**Trade-offs:**
- **Continuous (cal):** EMAs evolve smoothly across years (historical continuity)
- **Anchored (cal_anchor):** EMAs reset at Jan 1 (fiscal year isolation, year-over-year comparability)

---

### Alpha Calculation: Three Approaches

#### 1. Standard Alpha (v1)
**Formula:** `alpha = 2 / (period + 1)`

**When used:** Bar-space EMAs on canonical TF closes

**Example:** 10-period EMA on 7D bars → alpha = 2/(10+1) = 0.182

**Evidence:** compute_ema function (ema.py line 81)

#### 2. Horizon Alpha (v2)
**Formula:** `alpha = 2 / (horizon_days + 1)` where `horizon_days = tf_days * period`

**When used:** Daily-space EMAs with multi-TF semantics

**Example:** 10-period EMA on 7D TF → horizon_days = 7*10 = 70 → alpha = 2/71 = 0.028

**Evidence:** ema_multi_tf_v2.py line 267-274

**Why different:** v2 computes one EMA value per daily bar (not per TF bar). Horizon converts TF period to daily-equivalent alpha.

#### 3. Lookup Table Alpha (cal variants)
**Formula:** Pre-computed in `ema_alpha_lookup` table, fallback to `alpha = 2 / (effective_days + 1)`

**When used:** Calendar TFs with variable day counts (months: 28-31 days, years: 365-366 days)

**Why lookup table:** Calendar periods have variable lengths. Pre-computing alphas avoids recalculating daily-equivalent alphas every run.

**Evidence:** ema_multi_tf_cal.py lines 209-213 (load lookup), lines 250-253 (fallback formula)

#### 4. Daily-Equivalent Alpha (cal_anchor variants)
**Formula:** `alpha_daily = 1 - (1 - alpha_bar)^(1/tf_days)`

**When used:** Calendar-anchor dual EMAs (ema + ema_bar), converting bar-space alpha to daily-step alpha

**Why this formula:** Continuous daily propagation between canonical closes requires alpha that compounds correctly over tf_days.

**Evidence:** ema_multi_tf_cal_anchor.py lines 413-422

---

### Refresh Logic: 80%+ Shared

**Shared infrastructure (ALL variants):**
- BaseEMARefresher: Template method pattern (execution flow, CLI parsing, DB connection, state management)
- EMAStateManager: Unified state schema (id, tf, period) PRIMARY KEY, incremental watermarks
- compute_ema: Core EMA calculation (exponential smoothing formula)
- Multiprocessing: Per-ID worker pattern with NullPool connections

**Evidence:**
- refresh_cmc_ema_multi_tf_from_bars.py line 122: `class MultiTFEMARefresher(BaseEMARefresher)`
- refresh_cmc_ema_multi_tf_v2.py line 110: `class V2EMARefresher(BaseEMARefresher)`
- refresh_cmc_ema_multi_tf_cal_from_bars.py line 105: `class CalEMARefresher(BaseEMARefresher)`
- refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py line 107: `class CalAnchorEMARefresher(BaseEMARefresher)`

**Variant-specific logic (20%):**
- `get_timeframes()`: TF loading (dim_timeframe query with different filters)
- `compute_emas_for_id()`: Feature module invocation (which bars table, which alpha, which output columns)
- `get_source_table_info()`: Metadata (bars table name)

**Code reduction:** Refactor to BaseEMARefresher reduced refresh scripts from ~500 LOC to ~150 LOC (70% reduction), per module docstrings.

---

### Output Schema: Consistent with Variants

**Common columns (ALL variants):**
- `id`: Cryptocurrency ID (INTEGER NOT NULL)
- `tf`: Timeframe label (TEXT NOT NULL)
- `ts`: Timestamp (TIMESTAMPTZ NOT NULL)
- `period`: EMA period (INTEGER NOT NULL)
- `ema`: EMA value (DOUBLE PRECISION)
- `tf_days`: Days per TF (INTEGER)
- `roll`: Canonical flag (BOOLEAN, FALSE at TF closes)
- `d1`, `d2`: Canonical derivatives (first/second diffs on roll=FALSE rows)
- `d1_roll`, `d2_roll`: Daily derivatives (first/second diffs on ALL rows)
- `ingested_at`: Ingestion timestamp (TIMESTAMPTZ DEFAULT now())
- PRIMARY KEY: `(id, tf, ts, period)` or `(id, ts, tf, period)` (column order varies)

**Calendar-specific columns (cal, cal_anchor variants):**
- `ema_bar`: Bar-space EMA (snaps at TF closes, preview between)
- `roll_bar`: Bar-space canonical flag (FALSE at bar closes)
- `d1_bar`, `d2_bar`: Bar-space canonical derivatives
- `d1_roll_bar`, `d2_roll_bar`: Bar-space daily derivatives

**WHY dual EMAs in calendar variants:** Calendar TFs have two natural EMA spaces:
1. **ema (daily-space):** Seeded once, evolves continuously on daily grid (smooth across TF boundaries)
2. **ema_bar (bar-space):** Snaps to bar EMA at TF closes, propagates preview between (distinct bar-level EMAs)

Both are useful for different strategies (daily-space for intra-period signals, bar-space for period-close strategies).

**Evidence:**
- v1/v2: ema_multi_timeframe.py lines 307-322, ema_multi_tf_v2.py lines 322-338 (single ema)
- cal: ema_multi_tf_cal.py lines 376-398 (dual ema + ema_bar)
- cal_anchor: ema_multi_tf_cal_anchor.py lines 222-244 (dual ema + ema_bar)

---

## Key Insights

### What's Shared (80%+ Common)

1. **EMA calculation:** All variants use `compute_ema` function (ema.py lines 32-100)
   - Same exponential smoothing formula
   - Same seeding logic (SMA of first min_periods values)
   - Same NaN handling

2. **State management:** All variants use `EMAStateManager` with unified schema (ema_state_manager.py lines 78-99)
   - Same PRIMARY KEY: (id, tf, period)
   - Same state columns: daily_min_seen, daily_max_seen, last_time_close, last_canonical_ts, last_bar_seq
   - Same incremental refresh watermarking

3. **Execution framework:** All variants inherit `BaseEMARefresher` template (base_ema_refresher.py lines 108-150)
   - Same CLI parsing
   - Same multiprocessing orchestration (per-ID workers)
   - Same full-refresh vs incremental logic

4. **Derivatives:** All variants compute d1/d2 (canonical) and d1_roll/d2_roll (daily)
   - d1 = first difference on canonical closes (roll=FALSE)
   - d2 = second difference on canonical closes
   - d1_roll = first difference on ALL daily rows
   - d2_roll = second difference on ALL daily rows

### What's Legitimately Different (20%)

1. **Data source selection:**
   - v1: Persisted multi-TF bars (bars table already maintained)
   - v2: Synthetic multi-TF bars from daily (eliminates bar table dependency)
   - cal: Calendar-aligned bars (weeks/months/years)
   - cal_anchor: Year-anchored calendar bars (reset at Jan 1)

2. **Calendar alignment semantics:**
   - tf_day: Rolling day-based periods (no fixed start day)
   - calendar: Fixed-start periods (Sunday/Monday week start, 1st month start)
   - calendar_anchor: Year-boundary reset (bar_seq restarts each year)

3. **Timeframe source:**
   - v1/v2: dim_timeframe with alignment_type='tf_day'
   - cal: dim_timeframe with alignment_type='calendar', scheme-specific filters
   - cal_anchor: dim_timeframe with roll_policy='calendar_anchor'

4. **Alpha calculation approach:**
   - v1: Standard alpha (bar-space)
   - v2: Horizon alpha (daily-space with multi-TF semantics)
   - cal: Lookup table alpha (variable-length calendar periods)
   - cal_anchor: Daily-equivalent alpha formula (bar-to-daily conversion)

5. **Output columns:**
   - v1/v2: Single ema series
   - cal/cal_anchor: Dual ema + ema_bar series (daily-space and bar-space)

### Open Questions (NOT Consolidation Recommendations)

#### Question 1: v1 and v2 - Bars vs synthetic only difference?

**Similarity:** v1 and v2 have identical output schemas, same TF loading (dim_timeframe, alignment_type='tf_day'), same state management (per-(id, tf, period) watermarks), same derivatives (d1/d2, d1_roll/d2_roll).

**Difference:** ONLY data source:
- v1: Reads persisted bars from `cmc_price_bars_multi_tf` (line 368-403 in ema_multi_timeframe.py)
- v2: Synthesizes bars from `cmc_price_bars_1d` (line 214-275 in ema_multi_tf_v2.py, compute horizon alpha and apply to daily)

**Question:** Is this intentional architectural choice (bars-dependent vs bars-independent), or is v2 a migration path to deprecate v1? If multi-TF bars are maintained for other features anyway, is v2 redundant?

**Evidence for intentional:** v1 has fallback to synthetic bars if persisted bars missing (ema_multi_timeframe.py line 212: `_synthetic_tf_day_bars_from_daily` fallback). This suggests v1 and v2 were designed to coexist.

**Not recommending consolidation:** Both exist for legitimate reasons, just noting 95%+ code similarity.

#### Question 2: cal_us and cal_iso - Only week start differs?

**Similarity:** cal_us and cal_iso use identical feature module (`ema_multi_tf_cal.py`) with `scheme` parameter (line 58). Same refresh script with `--scheme` flag. ~95%+ code shared.

**Difference:** ONLY week start day:
- US: Sunday-Saturday weeks (lines 143-149: WHERE clause `tf ~ '_CAL_US$'`)
- ISO: Monday-Sunday weeks (lines 151-157: WHERE clause `tf ~ '_CAL_ISO$'`)

**Question:** Is week start day significant enough to warrant separate bars tables, state tables, and output tables? Or could this be a runtime parameter with single table design?

**Evidence for separation:** Week start day is semantically significant for calendar alignment. Trading strategies based on "first day of week" differ between US and ISO conventions. Separate tables allow independent backfills.

**Not recommending consolidation:** Semantic difference justifies separation, but noting high code similarity.

#### Question 3: Anchor variants - Specialized use case?

**Similarity:** cal_anchor variants use identical code to cal variants except for:
- TF query: Additional filter `roll_policy='calendar_anchor'` (ema_multi_tf_cal_anchor.py lines 129-130)
- Alpha formula: Daily-equivalent conversion (line 413: `1 - (1 - alpha_bar)^(1/tf_days)`)
- is_partial_end usage: Uses is_partial_end column instead of roll (line 297)

**Difference:** Year-boundary reset semantics (bar_seq restarts each Jan 1)

**Question:** How common are year-anchored EMA use cases in production? Anchor semantics require sophisticated infrastructure (separate bars tables, TF families, state tables, is_partial_end column logic). Is this justified by usage frequency?

**Evidence for specialized:** Anchor logic added for "fiscal year analysis" and "year-over-year comparisons" per variant documentation. This suggests specific client needs rather than general-purpose feature.

**Not recommending consolidation:** Anchoring is a legitimate semantic difference. Question is whether infrastructure complexity matches usage.

#### Question 4: Six state tables - Could be one unified?

**Similarity:** All 6 variants use identical state schema defined in `ema_state_manager.py` lines 78-99:
```sql
PRIMARY KEY (id, tf, period)
Columns: daily_min_seen, daily_max_seen, last_time_close, last_canonical_ts, last_bar_seq, updated_at
```

**Current design:** Each variant has separate state table:
- cmc_ema_multi_tf_state
- cmc_ema_multi_tf_v2_state
- cmc_ema_multi_tf_cal_us_state
- cmc_ema_multi_tf_cal_iso_state
- cmc_ema_multi_tf_cal_anchor_us_state
- cmc_ema_multi_tf_cal_anchor_iso_state

**Alternative design:** Single unified state table with `alignment_source` discriminator column (like unified output table design):
```sql
PRIMARY KEY (id, tf, period, alignment_source)
```

**Question:** Could all variants share one state table? Or is operational isolation (backfill one variant without affecting others) worth the complexity?

**Evidence for separation:** No schema conflicts (identical columns), but separate tables enable independent state management. If v1 backfill corrupts state, v2 is unaffected.

**Not recommending consolidation:** Separation may be intentional for operational safety. Question whether isolation benefit outweighs table proliferation.

---

## Conclusion

All 6 EMA variants exist for **legitimate semantic differences**, not code duplication:

1. **v1 vs v2:** Architectural choice (bars-dependent vs bars-independent)
2. **cal_us vs cal_iso:** Week start convention (US vs ISO standard)
3. **cal vs cal_anchor:** Year-boundary semantics (continuous vs anchored)

The high code sharing (80%+) via BaseEMARefresher, EMAStateManager, and compute_ema confirms this: the infrastructure is well-abstracted, and the 20% differences are intentional.

**Key finding:** All 6 variants ALREADY USE validated bar tables (Phase 20 verification). No data source migration work needed.
