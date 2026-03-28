---
phase: 89-ctf-schema-dimension-table
verified: 2026-03-23T19:03:06Z
status: passed
score: 6/6 must-haves verified
re_verification: false
---

# Phase 89: CTF Schema + Dimension Table Verification Report

**Phase Goal:** Establish the database foundation for cross-timeframe feature infrastructure -- dimension table, fact table, seed data, and declarative YAML config
**Verified:** 2026-03-23T19:03:06Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | dim_ctf_indicators table exists with SMALLSERIAL PK and 22 seeded indicator rows | VERIFIED | DB query: count=22; indicator_id uses nextval sequence (SMALLSERIAL); all 22 rows confirmed |
| 2  | ctf fact table exists with composite PK (id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source) | VERIFIED | information_schema confirms 14 columns, ctf_pkey index covers all 7 PK columns |
| 3  | ctf has FK references to dim_venues and dim_ctf_indicators | VERIFIED | FK constraints: ctf_venue_id_fkey -> dim_venues.venue_id; ctf_indicator_id_fkey -> dim_ctf_indicators.indicator_id |
| 4  | ix_ctf_lookup and ix_ctf_indicator indexes exist | VERIFIED | pg_indexes confirms both: ix_ctf_lookup (id, base_tf, ref_tf, indicator_id, ts); ix_ctf_indicator (indicator_id, base_tf) |
| 5  | configs/ctf_config.yaml defines tf_pairs, indicators by source, and composite params | VERIFIED | yaml.safe_load: 4 tf_pair groups, 4 indicator source sections (ta=11, vol=7, returns=2, features=2 = 22 total), composite_params {slope_window:5, divergence_zscore_window:63} |
| 6  | alembic upgrade head runs without error | VERIFIED | alembic_version table shows current head = j4k5l6m7n8o9; chain intact: 440fdfb3e8e1 -> j4k5l6m7n8o9 |

**Score:** 6/6 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `alembic/versions/j4k5l6m7n8o9_ctf_schema.py` | Alembic migration creating dim_ctf_indicators, ctf, indexes, seed data (min 100 lines) | VERIFIED | 145 lines; substantive -- creates 2 tables, seeds 22 rows, creates 2 indexes, implements downgrade; no stub patterns |
| `configs/ctf_config.yaml` | Declarative CTF configuration with tf_pairs, indicators, composite_params (min 40 lines) | VERIFIED | 95 lines; substantive -- all required keys present with correct structure; validates cleanly with yaml.safe_load |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `j4k5l6m7n8o9_ctf_schema.py` | `dim_venues` | FK REFERENCES public.dim_venues(venue_id) on ctf.venue_id | WIRED | Line 103: `REFERENCES public.dim_venues(venue_id)`; confirmed active by DB constraint ctf_venue_id_fkey |
| `j4k5l6m7n8o9_ctf_schema.py` | `dim_ctf_indicators` | FK REFERENCES public.dim_ctf_indicators(indicator_id) on ctf.indicator_id | WIRED | Line 108: `REFERENCES public.dim_ctf_indicators(indicator_id)`; confirmed active by DB constraint ctf_indicator_id_fkey |
| `configs/ctf_config.yaml` | `dim_ctf_indicators` | indicator names match seeded rows | WIRED | All 22 YAML indicator names exactly match DB indicator_name values (set equality verified programmatically) |

---

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| dim_ctf_indicators table with SMALLINT PK, required columns | SATISFIED | None |
| 20+ indicators seeded (TA, vol, returns, features) | SATISFIED | 22 rows seeded covering all required source categories |
| ctf fact table with correct PK and FK columns | SATISFIED | All 7 PK columns present, both FKs active |
| ix_ctf_lookup and ix_ctf_indicator indexes | SATISFIED | Both indexes confirmed in pg_indexes |
| configs/ctf_config.yaml with tf_pairs, indicators, composite_params | SATISFIED | 4 TF pair groups, 22 indicators, slope_window=5, divergence_zscore_window=63 |
| Alembic migration passes upgrade head cleanly | SATISFIED | DB at head j4k5l6m7n8o9; chain unbroken |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | No TODO/FIXME/placeholder patterns found | - | - |

---

### Human Verification Required

None. All goal criteria are verifiable programmatically:
- Table structure is confirmed via information_schema queries.
- FK constraints confirmed via constraint catalog queries.
- Seed data row count and values confirmed via direct SELECT.
- Index definitions confirmed via pg_indexes.
- YAML structure and counts confirmed via yaml.safe_load.
- Alembic chain confirmed via alembic history and alembic_version table.

---

### Verification Detail

#### dim_ctf_indicators -- 22 seeded rows confirmed

All 22 rows present with correct indicator_name, source_table, source_column, is_directional values:
- TA (11): rsi_14, rsi_7, rsi_21, macd_12_26, macd_hist_12_26_9, macd_8_17, macd_hist_8_17_9, adx_14, bb_width_20, stoch_k_14, atr_14
- Vol (7): vol_parkinson_20, vol_gk_20, vol_rs_20, vol_log_roll_20, vol_parkinson_63, vol_gk_63, vol_log_roll_63
- Returns (2): ret_arith, ret_log (source_table=returns_bars_multi_tf_u)
- Features (2): close_fracdiff, sadf_stat

#### ctf table -- all 14 columns present, 7-column composite PK

Columns: id (int, NOT NULL), venue_id (smallint, NOT NULL), ts (timestamptz, NOT NULL),
base_tf (text, NOT NULL), ref_tf (text, NOT NULL), indicator_id (smallint, NOT NULL),
alignment_source (text, NOT NULL), ref_value (float8, nullable), base_value (float8, nullable),
slope (float8, nullable), divergence (float8, nullable), agreement (float8, nullable),
crossover (float8, nullable), computed_at (timestamptz, NOT NULL).

#### Alembic chain

440fdfb3e8e1 (add_experiment_name_to_strategy_bakeoff_results) -> j4k5l6m7n8o9 (head, ctf schema).
down_revision correctly set to 440fdfb3e8e1 as specified in plan.

---

_Verified: 2026-03-23T19:03:06Z_
_Verifier: Claude (gsd-verifier)_
