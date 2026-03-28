# Phase 89: CTF Schema & Dimension Table - Research

**Researched:** 2026-03-23
**Domain:** PostgreSQL schema design, Alembic migrations, YAML config conventions
**Confidence:** HIGH

---

## Summary

Phase 89 establishes the database foundation for the cross-timeframe (CTF) feature
infrastructure. Research investigated all four source tables (`ta`, `vol`,
`returns_bars_multi_tf_u`, `features`) to produce exact column names and types for
seeding `dim_ctf_indicators`. It also examined the most recent Alembic migrations to
confirm the exact authoring pattern, and the existing `configs/` directory to determine
how the `ctf_config.yaml` should be structured.

The standard approach is: one Alembic migration file (Python, uses `conn.execute(text(...))`)
creates both tables and seeds `dim_ctf_indicators`. No ORM models. All SQL is inline text.
The YAML config follows the style of `cross_asset_config.yaml` — plain YAML with nested
sections per logical concern.

**Primary recommendation:** Write a single Alembic migration (revision ID `j4k5l6m7n8o9`,
down_revision `i3j4k5l6m7n8`) that creates `dim_ctf_indicators`, `ctf`, their indexes,
and seeds the full indicator set. Write `configs/ctf_config.yaml` alongside.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PostgreSQL | 14+ | Storage | Project database |
| SQLAlchemy | 2.x | Connection + text() | All scripts use it |
| Alembic | 1.x | Schema migrations | Established project pattern |
| PyYAML | 6.x | YAML config loading | Used by all existing configs |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `sqlalchemy.text` | same | Inline SQL in migrations | ALL migration SQL goes through this |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Alembic migration | Raw SQL file in `sql/` | SQL files exist for reference only; alembic is the live migration path |
| YAML config | DB-only config | YAML is the declarative layer; DB dim table is the runtime layer |

**Installation:** No new packages needed. All dependencies already installed.

---

## Architecture Patterns

### Recommended Project Structure

```
alembic/versions/
    j4k5l6m7n8o9_ctf_schema.py     # new migration (HEAD after i3j4k5l6m7n8)

configs/
    ctf_config.yaml                 # new config (alongside cross_asset_config.yaml)

sql/features/
    089_ctf.sql                     # reference DDL (not executed by Alembic, docs only)
```

### Pattern 1: Alembic Migration Structure

**What:** All migrations use `conn = op.get_bind()` then `conn.execute(text(...))` with
inline SQL strings. No `op.create_table()` helper — raw SQL only. ASCII-only comments
mandatory (Windows cp1252).

**When to use:** Always for new tables in this project.

**Example (from `i3j4k5l6m7n8_garch_tables.py`):**

```python
# Source: alembic/versions/i3j4k5l6m7n8_garch_tables.py
revision: str = "j4k5l6m7n8o9"
down_revision: Union[str, Sequence[str], None] = "i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS public.dim_ctf_indicators (
            ...
        )
    """))
```

### Pattern 2: Dimension Table (SMALLINT PK with SERIAL)

**What:** Use `SMALLSERIAL PRIMARY KEY` for compact integer PK on small dimension tables.
Foreign keys in fact tables reference the `SMALLINT` PK directly.

**Example (from `dim_feature_selection` and architecture decision in ROADMAP):**

```sql
-- dim_ctf_indicators pattern
CREATE TABLE IF NOT EXISTS public.dim_ctf_indicators (
    indicator_id    SMALLSERIAL PRIMARY KEY,
    indicator_name  TEXT NOT NULL UNIQUE,
    source_table    TEXT NOT NULL,
    source_column   TEXT NOT NULL,
    is_directional  BOOLEAN NOT NULL DEFAULT TRUE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Pattern 3: Fact Table PK Convention

**What:** The `ctf` fact table PK must include `venue_id` per project standard.
The pattern for analytics tables with `alignment_source` adds it to the PK as well.

```sql
-- ctf fact table PK (matches ROADMAP spec)
PRIMARY KEY (id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source)
```

**Important:** `indicator_id` is `SMALLINT` (not TEXT) to minimize index bloat.

### Pattern 4: Seeding via INSERT...ON CONFLICT DO NOTHING

**What:** All dimension table seeding in migrations uses `ON CONFLICT DO NOTHING`
for idempotency. Use `text().bindparams()` only for large TEXT values. Simple seed
rows use inline string formatting.

```python
# Source: alembic/versions/h2i3j4k5l6m7_dim_feature_selection.py (pattern)
conn.execute(text("""
    INSERT INTO public.dim_ctf_indicators
        (indicator_name, source_table, source_column, is_directional, description)
    VALUES
        ('rsi_14', 'ta', 'rsi_14', FALSE, 'RSI 14-period'),
        ...
    ON CONFLICT (indicator_name) DO NOTHING
"""))
```

### Pattern 5: YAML Config Structure

**What:** YAML configs are flat or shallow-nested. They follow `key: value` with
grouped sections. See `cross_asset_config.yaml` as the canonical template.

```yaml
# configs/ctf_config.yaml pattern
timeframe_pairs:
  - base_tf: "1D"
    ref_tfs: ["7D", "14D", "30D", "90D", "180D", "365D"]
  - base_tf: "7D"
    ref_tfs: ["30D", "90D", "180D", "365D"]
  ...

indicators:
  ta:
    - name: rsi_14
      column: rsi_14
      is_directional: false
    ...
  vol:
    - name: vol_parkinson_20
      column: vol_parkinson_20
      is_directional: false
    ...
  returns:
    - name: ret_arith
      column: ret_arith
      is_directional: true
    ...
  features:
    - name: close_fracdiff
      column: close_fracdiff
      is_directional: false
    ...

composite_params:
  slope_window: 5
  divergence_zscore_window: 63
```

### Anti-Patterns to Avoid

- **Using `op.create_table()` helper:** Project never uses it. Always use raw SQL via `conn.execute(text(...))`.
- **UTF-8 box-drawing characters in comments:** Windows cp1252 will raise `UnicodeDecodeError`. Use ASCII only (`=`, `-`, `*`).
- **TEXT indicator_id in ctf:** ROADMAP specifies SMALLINT FK. Do not use TEXT.
- **Missing `IF NOT EXISTS`:** All `CREATE TABLE` statements use `IF NOT EXISTS` for idempotency.
- **Missing `IF NOT EXISTS` on indexes:** Same rule applies to `CREATE INDEX`.

---

## Source Table Column Inventory

This is the exact set of columns available for seeding `dim_ctf_indicators`.

### `ta` table columns (source_table = 'ta')

All confirmed from `sql/features/042_ta.sql` and `src/ta_lab2/scripts/features/ta_feature.py`:

```
-- PK columns (not for CTF)
id, ts, tf, alignment_source, tf_days

-- Price context
close

-- RSI
rsi_7          (is_directional=FALSE)
rsi_14         (is_directional=FALSE)
rsi_21         (is_directional=FALSE)

-- MACD
macd_12_26            (is_directional=TRUE)
macd_signal_9         (is_directional=TRUE)
macd_hist_12_26_9     (is_directional=TRUE)
macd_8_17             (is_directional=TRUE)
macd_signal_9_fast    (is_directional=TRUE)
macd_hist_8_17_9      (is_directional=TRUE)

-- Stochastic
stoch_k_14     (is_directional=FALSE)
stoch_d_3      (is_directional=FALSE)

-- Bollinger Bands
bb_ma_20       (is_directional=TRUE)
bb_up_20_2     (is_directional=FALSE)
bb_lo_20_2     (is_directional=FALSE)
bb_width_20    (is_directional=FALSE)

-- ATR and ADX
atr_14         (is_directional=FALSE)
adx_14         (is_directional=FALSE)

-- Normalized
rsi_14_zscore  (is_directional=FALSE)
```

Note: `ta` table PK is `(id, ts, tf, alignment_source)` - no `venue_id` in PK, but
`venue_id SMALLINT NOT NULL DEFAULT 1` was added as a column via migration
`a0b1c2d3e4f5_strip_cmc_prefix_add_venue_id.py`.

### `vol` table columns (source_table = 'vol')

All confirmed from `sql/features/041_vol.sql` and `src/ta_lab2/scripts/features/vol_feature.py`:

```
-- PK columns (not for CTF)
id, ts, tf, alignment_source, tf_days

-- OHLC context (not for CTF seed)
open, high, low, close

-- Parkinson volatility (3 windows)
vol_parkinson_20    (is_directional=FALSE)
vol_parkinson_63    (is_directional=FALSE)
vol_parkinson_126   (is_directional=FALSE)

-- Garman-Klass volatility (3 windows)
vol_gk_20           (is_directional=FALSE)
vol_gk_63           (is_directional=FALSE)
vol_gk_126          (is_directional=FALSE)

-- Rogers-Satchell volatility (3 windows)
vol_rs_20           (is_directional=FALSE)
vol_rs_63           (is_directional=FALSE)
vol_rs_126          (is_directional=FALSE)

-- Rolling historical volatility
vol_log_roll_20     (is_directional=FALSE)
vol_log_roll_63     (is_directional=FALSE)
vol_log_roll_126    (is_directional=FALSE)

-- ATR (also in ta, but sourced from vol here)
atr_14              (is_directional=FALSE)
```

Note: `vol` table PK is `(id, ts, tf, alignment_source)` - same as `ta`.

### `returns_bars_multi_tf_u` columns (source_table = 'returns_bars_multi_tf_u')

All confirmed from `src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf.py`:

```
-- Key filter columns
roll    BOOLEAN   -- filter WHERE roll = FALSE for canonical returns

-- Canonical returns (roll=FALSE rows)
ret_arith          (is_directional=TRUE)
ret_log            (is_directional=TRUE)
delta_ret_arith    (is_directional=TRUE)
delta_ret_log      (is_directional=TRUE)
delta1             (is_directional=TRUE)
delta2             (is_directional=TRUE)
range              (is_directional=FALSE)
range_pct          (is_directional=FALSE)

-- Roll columns (unified LAG, all rows)
ret_arith_roll         (is_directional=TRUE)
ret_log_roll           (is_directional=TRUE)
```

The CTF phase 89 spec mentions `ret_arith` and `ret_log` as the two from returns.
The PK is `(id, ts, tf, venue_id, alignment_source)` with `roll` as a regular column.

### `features` table columns (source_table = 'features')

All confirmed from `sql/views/050_features.sql` and
`sql/migration/add_microstructure_to_features.sql`:

```
-- Microstructure (MICRO-01)
close_fracdiff      (is_directional=TRUE)
close_fracdiff_d    (is_directional=FALSE)   -- fractional diff order d

-- SADF (MICRO-03)
sadf_stat           (is_directional=FALSE)
sadf_is_explosive   BOOLEAN (not suitable for CTF numeric value)

-- Liquidity (MICRO-02) - not in phase 89 spec
kyle_lambda         (is_directional=FALSE)
amihud_lambda       (is_directional=FALSE)

-- Entropy (MICRO-04) - not in phase 89 spec
entropy_shannon     (is_directional=FALSE)
```

Phase 89 spec seeds `fracdiff` and `sadf_stat` from features.
The `features` table PK is `(id, ts, tf, alignment_source)` - no `venue_id` in PK.

---

## Exact Seed Set for dim_ctf_indicators

Based on the ROADMAP spec ("~20+ indicators"):

| indicator_name | source_table | source_column | is_directional |
|----------------|-------------|---------------|----------------|
| rsi_14 | ta | rsi_14 | FALSE |
| rsi_7 | ta | rsi_7 | FALSE |
| rsi_21 | ta | rsi_21 | FALSE |
| macd_12_26 | ta | macd_12_26 | TRUE |
| macd_hist_12_26_9 | ta | macd_hist_12_26_9 | TRUE |
| macd_8_17 | ta | macd_8_17 | TRUE |
| macd_hist_8_17_9 | ta | macd_hist_8_17_9 | TRUE |
| adx_14 | ta | adx_14 | FALSE |
| bb_width_20 | ta | bb_width_20 | FALSE |
| stoch_k_14 | ta | stoch_k_14 | FALSE |
| atr_14 | ta | atr_14 | FALSE |
| vol_parkinson_20 | vol | vol_parkinson_20 | FALSE |
| vol_gk_20 | vol | vol_gk_20 | FALSE |
| vol_rs_20 | vol | vol_rs_20 | FALSE |
| vol_log_roll_20 | vol | vol_log_roll_20 | FALSE |
| vol_parkinson_63 | vol | vol_parkinson_63 | FALSE |
| vol_gk_63 | vol | vol_gk_63 | FALSE |
| vol_log_roll_63 | vol | vol_log_roll_63 | FALSE |
| ret_arith | returns_bars_multi_tf_u | ret_arith | TRUE |
| ret_log | returns_bars_multi_tf_u | ret_log | TRUE |
| close_fracdiff | features | close_fracdiff | TRUE |
| sadf_stat | features | sadf_stat | FALSE |

Total: 22 indicators. Matches "~20+" spec.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Migration revision ID generation | Custom random hex | Follow project naming: `j4k5l6m7n8o9` (continue alphabet sequence) | Consistent with `g1h2...`, `h2i3...`, `i3j4...` pattern |
| YAML loading | Custom parser | `yaml.safe_load()` from PyYAML | Already used everywhere |
| ON CONFLICT seed | Manual DELETE+INSERT | `ON CONFLICT (indicator_name) DO NOTHING` | Project standard |

**Key insight:** The project's Alembic revision IDs follow a sequential alphabetic
pattern: `g1h2i3j4k5l6`, `h2i3j4k5l6m7`, `i3j4k5l6m7n8`. The next revision should
be `j4k5l6m7n8o9` and the file named `j4k5l6m7n8o9_ctf_schema.py`.

---

## Common Pitfalls

### Pitfall 1: UTF-8 Characters in Migration Comments

**What goes wrong:** Windows cp1252 raises `UnicodeDecodeError` when alembic reads
migration files with box-drawing characters (UTF-8 `═`, `─`, etc.) or non-ASCII chars.

**Why it happens:** alembic.ini uses `fileConfig` which defaults to system encoding
on Windows. The `alembic/env.py` passes `encoding="utf-8"` to `fileConfig` but this
only covers the `.ini` file, not the migration Python files themselves.

**How to avoid:** Use only ASCII in migration file comments and docstrings.
Use `=`, `-`, `*` instead of `═`, `─`, `*`. The `i3j4k5l6m7n8_garch_tables.py`
docstring explicitly notes: "All comments use ASCII only (Windows cp1252 compatibility)."

**Warning signs:** `UnicodeDecodeError` during `alembic upgrade head`.

### Pitfall 2: venue_id in PK vs Column-Only

**What goes wrong:** Assuming `ta` and `vol` tables have `venue_id` in their PK —
they do not. `venue_id` was added as a column-only via `VENUE_ID_COLUMN_ONLY` list
in migration `a0b1c2d3e4f5`. The `ctf` fact table queries will need to handle this.

**Why it happens:** The project migration added `venue_id` as column-only to many
tables that predate the venue refactor. The `ta` and `vol` PKs are
`(id, ts, tf, alignment_source)` — four columns, no `venue_id`.

**How to avoid:** When the CTF computation module (Phase 90) JOINs `ta`/`vol`, join
on `(id, ts, tf, alignment_source)` only. The `ctf` fact table itself has `venue_id`
in its PK (inherited from the caller, not sourced from `ta`/`vol`).

**Warning signs:** JOIN producing fan-out if you include `venue_id` in the ta/vol join.

### Pitfall 3: Missing alignment_source in ctf FK Join

**What goes wrong:** The `ctf` fact table PK includes `alignment_source`. When
seeding from `ta`/`vol`, the alignment_source must be explicitly passed to the
INSERT, since `ta` and `vol` carry it but it is not part of their PK.

**How to avoid:** Include `alignment_source` in the ctf write path explicitly.

### Pitfall 4: Forgetting `IF NOT EXISTS` on Indexes

**What goes wrong:** `alembic upgrade head` fails on re-run because index already exists.

**How to avoid:** Always `CREATE INDEX IF NOT EXISTS` in migrations.

### Pitfall 5: SMALLSERIAL vs SMALLINT for indicator_id

**What goes wrong:** Using `SMALLINT` without `SERIAL` means no auto-increment;
using `INTEGER SERIAL` wastes 2 bytes per ctf row vs `SMALLINT`.

**How to avoid:** Use `SMALLSERIAL PRIMARY KEY` in `dim_ctf_indicators`.
The ctf fact table references it as `SMALLINT NOT NULL REFERENCES dim_ctf_indicators(indicator_id)`.

---

## Code Examples

### Migration File Header (exact template)

```python
# Source: pattern from alembic/versions/i3j4k5l6m7n8_garch_tables.py
"""CTF schema -- dim_ctf_indicators dimension table and ctf fact table

Creates:
  dim_ctf_indicators  - dimension table mapping indicator_id to source
  ctf                 - fact table storing cross-timeframe computed values

Note: All comments use ASCII only (Windows cp1252 compatibility).

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-03-23
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "j4k5l6m7n8o9"
down_revision: Union[str, Sequence[str], None] = "i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```

### dim_ctf_indicators DDL

```sql
-- Source: ROADMAP.md Phase 89 spec + research
CREATE TABLE IF NOT EXISTS public.dim_ctf_indicators (
    indicator_id    SMALLSERIAL PRIMARY KEY,
    indicator_name  TEXT NOT NULL UNIQUE,
    source_table    TEXT NOT NULL,
    source_column   TEXT NOT NULL,
    is_directional  BOOLEAN NOT NULL DEFAULT TRUE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### ctf Fact Table DDL

```sql
-- Source: ROADMAP.md Phase 89 spec
CREATE TABLE IF NOT EXISTS public.ctf (
    id              INTEGER NOT NULL,
    venue_id        SMALLINT NOT NULL
                    REFERENCES public.dim_venues(venue_id),
    ts              TIMESTAMPTZ NOT NULL,
    base_tf         TEXT NOT NULL,
    ref_tf          TEXT NOT NULL,
    indicator_id    SMALLINT NOT NULL
                    REFERENCES public.dim_ctf_indicators(indicator_id),
    alignment_source TEXT NOT NULL,

    -- Values
    ref_value       DOUBLE PRECISION,
    base_value      DOUBLE PRECISION,
    slope           DOUBLE PRECISION,
    divergence      DOUBLE PRECISION,
    agreement       DOUBLE PRECISION,
    crossover       DOUBLE PRECISION,

    -- Metadata
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (id, venue_id, ts, base_tf, ref_tf, indicator_id, alignment_source)
);

CREATE INDEX IF NOT EXISTS ix_ctf_lookup
    ON public.ctf (id, base_tf, ref_tf, indicator_id, ts);

CREATE INDEX IF NOT EXISTS ix_ctf_indicator
    ON public.ctf (indicator_id, base_tf);
```

### Seed INSERT Pattern

```python
# Source: pattern from alembic/versions/g1h2i3j4k5l6_dim_data_sources_and_alignment_checks.py
conn.execute(text("""
    INSERT INTO public.dim_ctf_indicators
        (indicator_name, source_table, source_column, is_directional, description)
    VALUES
        ('rsi_14',          'ta',  'rsi_14',          FALSE, 'RSI 14-period'),
        ('rsi_7',           'ta',  'rsi_7',           FALSE, 'RSI 7-period'),
        ('rsi_21',          'ta',  'rsi_21',          FALSE, 'RSI 21-period'),
        ('macd_12_26',      'ta',  'macd_12_26',      TRUE,  'MACD line 12/26'),
        ('macd_hist_12_26_9','ta', 'macd_hist_12_26_9',TRUE, 'MACD histogram 12/26/9'),
        ('macd_8_17',       'ta',  'macd_8_17',       TRUE,  'MACD line 8/17'),
        ('macd_hist_8_17_9','ta',  'macd_hist_8_17_9',TRUE,  'MACD histogram 8/17/9'),
        ('adx_14',          'ta',  'adx_14',          FALSE, 'ADX 14-period'),
        ('bb_width_20',     'ta',  'bb_width_20',     FALSE, 'Bollinger width 20-period'),
        ('stoch_k_14',      'ta',  'stoch_k_14',      FALSE, 'Stochastic K 14-period'),
        ('atr_14',          'ta',  'atr_14',          FALSE, 'ATR 14-period'),
        ('vol_parkinson_20','vol', 'vol_parkinson_20',FALSE, 'Parkinson vol 20-bar'),
        ('vol_gk_20',       'vol', 'vol_gk_20',       FALSE, 'Garman-Klass vol 20-bar'),
        ('vol_rs_20',       'vol', 'vol_rs_20',       FALSE, 'Rogers-Satchell vol 20-bar'),
        ('vol_log_roll_20', 'vol', 'vol_log_roll_20', FALSE, 'Log-return vol 20-bar'),
        ('vol_parkinson_63','vol', 'vol_parkinson_63',FALSE, 'Parkinson vol 63-bar'),
        ('vol_gk_63',       'vol', 'vol_gk_63',       FALSE, 'Garman-Klass vol 63-bar'),
        ('vol_log_roll_63', 'vol', 'vol_log_roll_63', FALSE, 'Log-return vol 63-bar'),
        ('ret_arith',       'returns_bars_multi_tf_u', 'ret_arith', TRUE, 'Arithmetic return'),
        ('ret_log',         'returns_bars_multi_tf_u', 'ret_log',   TRUE, 'Log return'),
        ('close_fracdiff',  'features', 'close_fracdiff',  TRUE,  'Fractional diff close'),
        ('sadf_stat',       'features', 'sadf_stat',       FALSE, 'SADF structural break stat')
    ON CONFLICT (indicator_name) DO NOTHING
"""))
```

### ctf_config.yaml

```yaml
# configs/ctf_config.yaml
# Cross-timeframe feature configuration.
# Changing any value here changes behavior without code changes.

timeframe_pairs:
  - base_tf: "1D"
    ref_tfs: ["7D", "14D", "30D", "90D", "180D", "365D"]
  - base_tf: "7D"
    ref_tfs: ["30D", "90D", "180D", "365D"]
  - base_tf: "14D"
    ref_tfs: ["90D", "180D", "365D"]
  - base_tf: "30D"
    ref_tfs: ["180D", "365D"]

indicators:
  ta:
    - name: rsi_14
      column: rsi_14
      is_directional: false
    - name: rsi_7
      column: rsi_7
      is_directional: false
    - name: rsi_21
      column: rsi_21
      is_directional: false
    - name: macd_12_26
      column: macd_12_26
      is_directional: true
    - name: macd_hist_12_26_9
      column: macd_hist_12_26_9
      is_directional: true
    - name: macd_8_17
      column: macd_8_17
      is_directional: true
    - name: macd_hist_8_17_9
      column: macd_hist_8_17_9
      is_directional: true
    - name: adx_14
      column: adx_14
      is_directional: false
    - name: bb_width_20
      column: bb_width_20
      is_directional: false
    - name: stoch_k_14
      column: stoch_k_14
      is_directional: false
    - name: atr_14
      column: atr_14
      is_directional: false

  vol:
    - name: vol_parkinson_20
      column: vol_parkinson_20
      is_directional: false
    - name: vol_gk_20
      column: vol_gk_20
      is_directional: false
    - name: vol_rs_20
      column: vol_rs_20
      is_directional: false
    - name: vol_log_roll_20
      column: vol_log_roll_20
      is_directional: false
    - name: vol_parkinson_63
      column: vol_parkinson_63
      is_directional: false
    - name: vol_gk_63
      column: vol_gk_63
      is_directional: false
    - name: vol_log_roll_63
      column: vol_log_roll_63
      is_directional: false

  returns:
    source_table: returns_bars_multi_tf_u
    roll_filter: false               # WHERE roll = FALSE
    - name: ret_arith
      column: ret_arith
      is_directional: true
    - name: ret_log
      column: ret_log
      is_directional: true

  features:
    - name: close_fracdiff
      column: close_fracdiff
      is_directional: true
    - name: sadf_stat
      column: sadf_stat
      is_directional: false

composite_params:
  slope_window: 5                    # bars for rolling polyfit slope
  divergence_zscore_window: 63       # bars for divergence z-score denominator
```

**Note on YAML returns section:** The `- name:` list syntax under `returns:` conflicts
with the `source_table:` key. The planner should restructure `returns:` as:
```yaml
  returns:
    source_table: returns_bars_multi_tf_u
    roll_filter: false
    indicators:
      - name: ret_arith
        ...
```
or flatten the roll_filter into each entry. This is a detail for the planning step.

### Downgrade Pattern

```python
def downgrade() -> None:
    conn = op.get_bind()
    # Drop fact table first (has FK to dim_ctf_indicators)
    conn.execute(text("DROP TABLE IF EXISTS public.ctf"))
    conn.execute(text("DROP TABLE IF EXISTS public.dim_ctf_indicators"))
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| TEXT indicator keys in fact tables | SMALLINT FK to dimension table | Phase 89 design | Smaller indexes, faster joins |
| Per-indicator queries in CTF | Batch load all indicators per source table | Phase 90 design | Prevents N+1 query pattern |

---

## Open Questions

1. **YAML returns section structure**
   - What we know: `returns_bars_multi_tf_u` requires a `roll = FALSE` filter that other source tables don't need
   - What's unclear: Whether the YAML config should embed this as a field (`roll_filter: false`) or as a special source type
   - Recommendation: Add `roll_filter: false` as an optional field at the source-table level; default to `null` (no filter). Phase 90 reads this field.

2. **ctf table `computed_at` column naming**
   - What we know: ROADMAP spec lists `ref_value, base_value, slope, divergence, agreement, crossover` value columns but does not name the metadata timestamp column
   - What's unclear: Whether it should be `computed_at` or `updated_at` (used by `ta`, `vol`, `features`)
   - Recommendation: Use `computed_at` to distinguish from "incremental refresh" semantics. The `ctf` table is a derived fact, not a raw measurement.

3. **Timeframe pair definition**
   - What we know: Phase 91 estimates ~11 TF pairs for Phase 91's disk estimate ("20 indicators x 11 TF pairs")
   - What's unclear: Exact TF pair list is not locked — it is in the YAML config
   - Recommendation: The 4 base_tf x ref_tf combinations above yield: 6+4+3+2 = 15 pairs. Adjust to 11 by removing 14D base_tf group or reducing 1D ref_tfs. Use the YAML as the source of truth; Phase 91 can prune.

---

## Sources

### Primary (HIGH confidence)
- `alembic/versions/i3j4k5l6m7n8_garch_tables.py` - migration structure template
- `alembic/versions/h2i3j4k5l6m7_dim_feature_selection.py` - dimension table pattern
- `alembic/versions/g1h2i3j4k5l6_dim_data_sources_and_alignment_checks.py` - seed INSERT + bindparams pattern
- `sql/features/042_ta.sql` - exact ta table column names
- `sql/features/041_vol.sql` - exact vol table column names
- `sql/views/050_features.sql` - exact features table column names (incl. microstructure)
- `src/ta_lab2/scripts/returns/refresh_returns_bars_multi_tf.py` - returns table column names
- `alembic/versions/a0b1c2d3e4f5_strip_cmc_prefix_add_venue_id.py` - confirms ta/vol have venue_id as column-only
- `configs/cross_asset_config.yaml` - YAML config style reference
- `.planning/ROADMAP.md` lines 1560-1570 - Phase 89 success criteria

### Secondary (MEDIUM confidence)
- `src/ta_lab2/scripts/features/ta_feature.py` - indicator params cross-reference
- `src/ta_lab2/scripts/features/vol_feature.py` - vol columns cross-reference
- `src/ta_lab2/scripts/features/microstructure_feature.py` - fracdiff/sadf columns
- `sql/lookups/021_dim_indicators.sql` - existing dimension table design pattern

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Verified from multiple migration files and project code
- Architecture patterns: HIGH - Directly copied from most recent migrations
- Column inventory: HIGH - Cross-verified between SQL DDL files and Python source code
- Pitfalls: HIGH - ta/vol venue_id issue verified from migration VENUE_ID_COLUMN_ONLY list
- YAML format: HIGH - Derived from cross_asset_config.yaml directly

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable schema; changes require new migrations anyway)
