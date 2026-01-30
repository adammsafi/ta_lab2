# Phase 6: ta_lab2 Time Model - Research

**Researched:** 2026-01-29
**Domain:** Time dimension tables, multi-timeframe EMA unification, PostgreSQL dimension patterns
**Confidence:** HIGH

## Summary

This research investigated the ta_lab2 time model infrastructure to support Phase 6 planning: unifying EMA tables, creating formal time dimension tables, and establishing incremental refresh patterns.

**Key Findings:**
1. **Four EMA variants exist by design** — Each serves a distinct alignment strategy (tf_day rolling, calendar-aligned, calendar-anchored), not accidental duplication
2. **dim_timeframe and dim_sessions already architected** — Comprehensive TFMeta and SessionMeta dataclasses exist with DST-safe methods
3. **sync_cmc_ema_multi_tf_u.py is production-ready** — Unified table (cmc_ema_multi_tf_u) with alignment_source discriminator already working
4. **Refresh scripts already reference dim_timeframe** — All recent EMA refresh scripts call list_tfs() and get_tf_days() from dim_timeframe
5. **State tracking pattern is mature** — EMAStateManager with idempotent upsert logic, checkpoint-based recovery, watermarking per (id, tf, period)

**Primary recommendation:** Build on existing infrastructure. The codebase already has sophisticated time handling — Phase 6 should focus on populating dimension tables, validating existing patterns, and incremental improvements rather than reimplementation.

## Standard Stack

### Core Infrastructure (Already Exists)

| Component | Location | Purpose | Status |
|-----------|----------|---------|--------|
| dim_timeframe.py | ta_lab2/time/ | TF metadata with calendar schemes, partial periods, alignment types | PRODUCTION |
| dim_sessions.py | ta_lab2/time/ | Session windows with DST-safe UTC conversion | PRODUCTION |
| EMAStateManager | scripts/emas/ | Incremental refresh state tracking | PRODUCTION |
| sync_cmc_ema_multi_tf_u.py | scripts/emas/ | EMA table unification | PRODUCTION |

### Supporting Libraries

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | ~2.0 | Database ORM + engine | Industry standard for Python DB access |
| Pandas | ~2.x | Time series manipulation | De facto standard for financial data |
| PostgreSQL | 15+ | Database with TIMESTAMPTZ, generate_series | Best timezone support in open-source RDBMS |
| Polars | ~0.x | Fast dataframe operations | Used in polars_helpers.py for performance |

**Installation:**
Already installed in ta_lab2 environment.

## Architecture Patterns

### Existing Dimension Table Pattern

**dim_timeframe architecture:**
```python
# From dim_timeframe.py (lines 10-31)
@dataclass(frozen=True)
class TFMeta:
    # Core identification
    tf: str                          # "1D", "7D", "1M_CAL", "1M_CAL_ANCHOR_US"
    label: str                       # Human-readable label
    base_unit: str                   # "D", "W", "M", "Y"
    tf_qty: int                      # Quantity of base units
    tf_days_nominal: int             # Nominal days (e.g., 30 for 1M)

    # Alignment strategy
    alignment_type: str              # "tf_day" or "calendar"
    calendar_anchor: Optional[str]   # "EOM", "EOQ", "EOY", "ISO-WEEK"
    roll_policy: str                 # "tf_day", "calendar", "calendar_anchor"
    has_roll_flag: bool              # Whether this TF supports roll detection

    # Metadata
    is_intraday: bool
    sort_order: int
    is_canonical: bool

    # Calendar schemes and partial periods
    calendar_scheme: Optional[str]   # "US", "ISO"
    allow_partial_start: bool
    allow_partial_end: bool
    tf_days_min: Optional[int]       # Bounds for validation
    tf_days_max: Optional[int]
```

**dim_sessions architecture:**
```python
# From dim_sessions.py (lines 14-30)
@dataclass(frozen=True)
class SessionKey:
    asset_class: str     # "CRYPTO", "EQUITY", "FUTURES"
    region: str          # "GLOBAL", "US", "EU", "ASIA"
    venue: str           # "COINBASE", "NYSE", "CME"
    asset_key_type: str  # "SYMBOL", "ID"
    asset_key: str       # "BTC", "1", etc.
    session_type: str    # "PRIMARY", "EXTENDED", "PRE_MARKET"

@dataclass(frozen=True)
class SessionMeta:
    asset_id: Optional[int]
    timezone: str                    # IANA timezone: "America/New_York"
    session_open_local: str          # "09:30:00"
    session_close_local: str         # "16:00:00"
    is_24h: bool
```

**Key pattern:** In-memory class wraps database table, loads once per process, provides accessors.

### EMA Table Unification Pattern

**Existing unified table (cmc_ema_multi_tf_u):**
```sql
-- From sync_cmc_ema_multi_tf_u.py (lines 233-248)
PRIMARY KEY (id, ts, tf, period, alignment_source)

Columns:
  id, ts, tf, period, ema              -- Common to all variants
  ingested_at                          -- Watermarking timestamp
  d1, d2                               -- Canonical derivatives
  tf_days                              -- From dim_timeframe
  roll                                 -- Canonical flag
  d1_roll, d2_roll                     -- Rolling derivatives
  alignment_source                     -- Discriminator: "multi_tf_v2", "multi_tf_cal_us", etc.
  ema_bar, d1_bar, d2_bar              -- Bar-space EMAs (cal variants only)
  roll_bar, d1_roll_bar, d2_roll_bar   -- Bar-space derivatives
```

**Unification strategy:**
- Single target table with all possible columns
- alignment_source discriminates between EMA calculation methods
- NULL for columns not applicable to that alignment_source
- ON CONFLICT DO NOTHING prevents duplicates
- Watermarking per alignment_source for incremental sync

### State Tracking Pattern

**From EMAStateManager (lines 76-97):**
```sql
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    -- Primary key
    id                  INTEGER         NOT NULL,
    tf                  TEXT            NOT NULL,
    period              INTEGER         NOT NULL,

    -- Timestamp range
    daily_min_seen      TIMESTAMPTZ     NULL,
    daily_max_seen      TIMESTAMPTZ     NULL,
    last_time_close     TIMESTAMPTZ     NULL,
    last_canonical_ts   TIMESTAMPTZ     NULL,

    -- Bar sequence
    last_bar_seq        INTEGER         NULL,

    -- Metadata
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period)
);
```

**Watermarking logic:**
- Per (id, tf, period) granularity
- Tracks both timestamp-based (last_canonical_ts, last_time_close) and sequence-based (last_bar_seq) progress
- Idempotent upsert: `ON CONFLICT (id, tf, period) DO UPDATE SET ...`
- Supports both full refresh (ignore state) and incremental (use watermark)

### DST-Safe Session Window Pattern

**From dim_sessions.py (lines 87-150):**
```python
def session_windows_utc_by_key(
    self,
    *,
    key: SessionKey,
    start_date: date,
    end_date: date,
    db_url: Optional[str] = None,
) -> pd.DataFrame:
    """
    Returns session windows with DST-safe UTC timestamps.

    Uses database function dim_session_instants_for_date() which:
    1. Takes local session time (09:30-16:00 ET)
    2. Converts to UTC for each day using PostgreSQL timezone functions
    3. Handles DST transitions automatically via IANA timezone database

    Returns DataFrame with:
      - session_date (local date)
      - open_utc, close_utc (DST-corrected UTC timestamps)
    """
```

**Key insight:** Offload DST calculation to PostgreSQL's timezone functions, which use IANA database for historical and future DST transitions.

## Don't Hand-Roll

### Problems with Existing Solutions

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DST conversion | Python datetime with manual offset | PostgreSQL `AT TIME ZONE` + database function | IANA timezone database in PG handles historical DST changes, leap seconds, political timezone changes |
| EMA variant reconciliation | Custom merge logic | sync_cmc_ema_multi_tf_u.py | Already handles 6 source tables, watermarking, conflict resolution, alignment_source discrimination |
| Timeframe metadata | Hardcoded TF dictionaries | dim_timeframe.from_db() | Centralized truth, supports calendar schemes, partial periods, validation bounds |
| State table per script | Per-script state schemas | Unified EMAStateManager | Single schema, reusable, tested watermarking logic |
| Manual incremental refresh | Custom SQL per table | EMAStateManager.update_state_from_output() | Handles both timestamp-based and sequence-based watermarking, idempotent |

**Critical insight:** The codebase already solved these problems. Phase 6 should validate and document, not reimplement.

## Common Pitfalls

### Pitfall 1: Multiple EMA Tables Are Redundant
**What goes wrong:** Planner assumes 4 EMA variants should be merged into one table with unified logic.

**Why it happens:** Lack of understanding that each variant represents a fundamentally different alignment strategy:
- **multi_tf**: Rolling tf_day windows (7D, 14D) from persisted bars
- **multi_tf_v2**: Horizon-based EMAs computed from daily data only
- **multi_tf_cal_us/iso**: Calendar-aligned (month/quarter ends) with US/ISO week schemes
- **multi_tf_cal_anchor_us/iso**: Calendar-anchored (partial periods allowed)

**How to avoid:** Keep separate source tables, unify via cmc_ema_multi_tf_u with alignment_source discriminator. Each variant needs different calculation logic.

**Warning signs:**
- Plan proposes merging ema_multi_tf_cal.py into ema_multi_timeframe.py
- Plan removes alignment_source column from unified table
- Plan eliminates ema_bar columns (needed for calendar variants)

### Pitfall 2: Timezone Stored as Offset Instead of IANA Name
**What goes wrong:** dim_sessions stores timezone as "+05:00" instead of "America/New_York". DST transitions fail silently.

**Why it happens:** Fixed offsets are simpler to understand initially, but don't handle DST.

**How to avoid:** Always store IANA timezone names ("America/New_York", "Europe/London"). Use PostgreSQL's `AT TIME ZONE` for conversions.

**Warning signs:**
- Plan uses INTEGER offset columns instead of TEXT timezone
- Plan computes DST offsets in Python instead of delegating to PostgreSQL
- Plan hardcodes UTC offsets for "ET" or "PT"

### Pitfall 3: Refreshing All History on Incremental Refresh
**What goes wrong:** Incremental refresh recomputes all EMAs from 2010 instead of using watermark.

**Why it happens:** State table not consulted, or watermark logic broken.

**How to avoid:** Always load state first, compute dirty_window_start, only refresh from watermark - lookback. Validate state table is updated after each run.

**Warning signs:**
- EMA refresh takes same time on second run as first run
- State table shows no updated_at changes
- Database I/O metrics show full table scans on every run

### Pitfall 4: Off-By-One Errors in TF Alignment
**What goes wrong:** 7D EMAs have 8 or 6 day gaps instead of 7. Calendar month EMAs include partial months.

**Why it happens:** Fencepost errors in bar selection, inclusive vs exclusive date ranges, partial period handling.

**How to avoid:**
- Use dim_timeframe.allow_partial_start/end flags
- Filter with `is_partial_end = FALSE` for canonical closes
- Validate tf_days_realized against tf_days_min/max bounds
- Property-based tests: every Nth day should be canonical

**Warning signs:**
- Audit shows irregular spacing between canonical closes
- tf_days_realized outside (tf_days_min, tf_days_max) bounds
- First/last bars of dataset have different tf_days than middle

### Pitfall 5: Race Conditions in Parallel Refresh
**What goes wrong:** Two workers update same (id, tf, period) simultaneously, one overwrites the other's progress.

**Why it happens:** State updates not atomic, or missing ON CONFLICT handling.

**How to avoid:**
- Use `ON CONFLICT (id, tf, period) DO UPDATE SET` for idempotent upserts
- Partition work by ID (not by TF or period)
- Each worker gets exclusive set of IDs

**Warning signs:**
- State table has missing IDs after parallel run completes
- Logs show duplicate work across workers
- Database deadlocks or lock timeouts in state table updates

## Code Examples

### Pattern 1: Load Timeframes from dim_timeframe

```python
# Source: dim_timeframe.py (lines 278-294)
# Used by: refresh_cmc_ema_multi_tf_from_bars.py (line 78)

from ta_lab2.time.dim_timeframe import list_tfs, get_tf_days

db_url = "postgresql://..."

# Get canonical tf_day timeframes
tfs = list_tfs(
    db_url=db_url,
    alignment_type="tf_day",
    canonical_only=True,
)
# Returns: ["1D", "7D", "14D", "30D", "90D", "365D"]

# Get nominal days for a timeframe
tf_days = get_tf_days("7D", db_url=db_url)
# Returns: 7
```

### Pattern 2: DST-Safe Session Windows

```python
# Source: dim_sessions.py (lines 87-150)
from ta_lab2.time.dim_sessions import DimSessions, SessionKey
from datetime import date

sessions = DimSessions.from_db(db_url)

key = SessionKey(
    asset_class="EQUITY",
    region="US",
    venue="NYSE",
    asset_key_type="SYMBOL",
    asset_key="AAPL",
    session_type="PRIMARY",
)

# Get DST-safe UTC windows for date range
windows = sessions.session_windows_utc_by_key(
    key=key,
    start_date=date(2024, 3, 10),  # DST transition day
    end_date=date(2024, 3, 11),
    db_url=db_url,
)

# Returns DataFrame with columns:
# session_date, timezone, session_open_local, session_close_local,
# open_utc, close_utc
#
# open_utc and close_utc are correctly adjusted for DST transition
```

### Pattern 3: Incremental Refresh with State Tracking

```python
# Source: ema_state_manager.py (lines 113-198)
# Used by: refresh_cmc_ema_multi_tf_from_bars.py

from ta_lab2.scripts.emas.ema_state_manager import (
    EMAStateManager,
    EMAStateConfig,
)

config = EMAStateConfig(
    state_schema="public",
    state_table="cmc_ema_multi_tf_state",
    ts_column="ts",
    roll_filter="roll = FALSE",
    use_canonical_ts=False,
    bars_table="cmc_price_bars_multi_tf",
    bars_schema="public",
    bars_partial_filter="is_partial_end = FALSE",
)

manager = EMAStateManager(engine, config)

# Ensure state table exists
manager.ensure_state_table()

# Load existing state for incremental refresh
state_df = manager.load_state(ids=[1, 52], periods=[9, 10])

# After computing EMAs, update state
manager.update_state_from_output(
    output_table="cmc_ema_multi_tf",
    output_schema="public",
)
# Returns: number of state rows upserted
```

### Pattern 4: EMA Table Unification

```python
# Source: sync_cmc_ema_multi_tf_u.py (lines 201-270)
# Run incrementally to sync source tables into unified table

# Watermarking per alignment_source
def get_watermark(engine, alignment_source, prefer_ingested_at):
    """
    Returns max watermark in _u for this alignment_source.
    If prefer_ingested_at=True -> MAX(ingested_at), else MAX(ts).
    """
    if prefer_ingested_at:
        q = text(f"""
            SELECT MAX(ingested_at) AS wm
            FROM {U_TABLE}
            WHERE alignment_source = :a
        """)
    else:
        q = text(f"""
            SELECT MAX(ts) AS wm
            FROM {U_TABLE}
            WHERE alignment_source = :a
        """)
    # ...

# Idempotent insert with ON CONFLICT DO NOTHING
sql = f"""
WITH ins AS (
  INSERT INTO {U_TABLE} (
    id, ts, tf, period,
    ema, ingested_at, d1, d2, tf_days, roll, d1_roll, d2_roll,
    alignment_source,
    ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar
  )
  {select_sql}
  FROM {src_table}
  {where_clause}
  ON CONFLICT (id, ts, tf, period, alignment_source) DO NOTHING
  RETURNING 1
)
SELECT COUNT(*)::bigint AS n_inserted FROM ins;
"""
```

## State of the Art

### Existing vs Planned Approaches

| Area | Current Approach | Status | Notes |
|------|------------------|--------|-------|
| TF definitions | dim_timeframe table + TFMeta dataclass | PRODUCTION | Already supports calendar schemes, partial periods |
| Session metadata | dim_sessions table + SessionMeta dataclass | PRODUCTION | DST-safe via database function |
| EMA unification | cmc_ema_multi_tf_u with alignment_source | PRODUCTION | Handles 6 source tables incrementally |
| State tracking | Unified EMAStateManager with watermarking | PRODUCTION | Per (id, tf, period) granularity |
| Incremental refresh | Watermark-based with lookback | PRODUCTION | Idempotent upserts, checkpoint recovery |

**Deprecated patterns:**
- Hardcoded TF dictionaries in scripts: Replaced by dim_timeframe.list_tfs()
- Per-script state schemas: Replaced by unified state table
- Manual SQL for state updates: Replaced by EMAStateManager

### Migration Status

**What already references dim_timeframe:**
- refresh_cmc_ema_multi_tf_from_bars.py (line 78, 149-154)
- refresh_cmc_ema_multi_tf_v2.py (line 137-144)
- ema_multi_timeframe.py (line 118)
- ema_multi_tf_v2.py (line 186-187)
- ema_multi_tf_cal.py (line 160-185)
- ema_multi_tf_cal_anchor.py (line 122-157)

**Confidence:** HIGH - All active EMA refresh scripts call dim_timeframe functions.

## Open Questions

### Question 1: EMA Variant Consolidation Strategy

**What we know:**
- Four EMA variants exist: multi_tf, multi_tf_v2, multi_tf_cal, multi_tf_cal_anchor
- Each represents distinct alignment strategy (tf_day rolling, horizon-based, calendar-aligned, calendar-anchored)
- sync_cmc_ema_multi_tf_u.py already unifies them into cmc_ema_multi_tf_u
- Different downstream consumers may prefer different alignment strategies

**What's unclear:**
- Should source tables remain separate indefinitely, or eventually deprecate some?
- Is alignment_source sufficient discriminator, or do downstream queries need better indexing?
- Are all four variants actively used by downstream consumers, or can some be retired?

**Recommendation:**
1. Keep source tables separate for now (different computation logic)
2. Validate cmc_ema_multi_tf_u covers all use cases
3. Add index on (alignment_source, id, tf, ts, period) if query performance poor
4. Survey downstream consumers to identify unused variants before deprecation

### Question 2: dim_timeframe and dim_sessions Population

**What we know:**
- Classes exist (DimTimeframe, DimSessions) with comprehensive schemas
- Classes have from_db() classmethods expecting tables to exist
- No SQL DDL files found in sql/ddl/ for these tables
- Python code suggests tables already exist in database

**What's unclear:**
- Do dim_timeframe and dim_sessions tables already exist and are populated?
- If not, what's the canonical source for initial population?
- Should new TFs be added via SQL INSERT or Python migration?

**Recommendation:**
1. Check if tables exist: `SELECT * FROM dim_timeframe LIMIT 1`
2. If exist: Document current population, add validation tests
3. If not exist: Create SQL seed file with initial TFs and sessions
4. For future additions: Hybrid approach (SQL for static data, Python for derived/computed data)

### Question 3: Incremental Refresh Lookback Window

**What we know:**
- State table tracks watermarks per (id, tf, period)
- Different TFs have different sensitivity to late-arriving data
- 1D data rarely backfilled, but 1M data may have late corrections

**What's unclear:**
- Should lookback window be TF-dependent? (e.g., 1D: 2 days, 1M: 60 days)
- Fixed lookback vs dynamic based on data volatility?
- How to handle upstream bar corrections (bars table updated retroactively)?

**Recommendation:**
1. Start with TF-dependent lookback: `lookback_days = max(7, tf_days * 2)`
2. Add configuration parameter for override: `--lookback-days`
3. Log when backfill extends beyond lookback (indicates late data pattern)
4. Monitor metrics: backfill frequency, backfill distance, to tune lookback

### Question 4: Validation Test Coverage

**What we know:**
- Phase 6 requires time alignment validation tests
- Common error types: off-by-one, DST bugs, calendar roll misalignment
- Existing code has some validation (tf_days_realized checks)

**What's unclear:**
- How many validation tests are sufficient?
- Should tests be property-based (hypothesis) or example-based (pytest)?
- Where to store reference data for validation?

**Recommendation:**
1. Property-based tests for core invariants:
   - Canonical closes spaced by tf_days ± tolerance
   - No partial periods when allow_partial_end=FALSE
   - DST transitions don't create duplicate/missing timestamps
2. Example-based tests for known edge cases:
   - Leap year (2024-02-29)
   - DST spring forward (2024-03-10)
   - Month-end roll (2024-01-31 → 2024-02-29)
3. Reference data: Fixtures for 1 year of known-good EMAs per variant
4. Target: 20-30 tests covering all error types in requirements

## Sources

### Primary (HIGH confidence)
- Codebase analysis:
  - dim_timeframe.py (comprehensive TFMeta with calendar schemes)
  - dim_sessions.py (DST-safe session windows via database functions)
  - sync_cmc_ema_multi_tf_u.py (production EMA unification with watermarking)
  - ema_state_manager.py (mature state tracking with idempotent upserts)
  - All four EMA variant files (distinct alignment strategies confirmed)

### Secondary (MEDIUM confidence)
- [PostgreSQL Documentation: Date/Time Types](https://www.postgresql.org/docs/current/datatype-datetime.html) - TIMESTAMPTZ and timezone handling
- [Handling DST changes in PostgreSQL](https://www.keithf4.com/postgresql_dst/) - Keith Fiske's blog on DST patterns
- [Best practices for timestamps and time zones in databases](https://www.tinybird.co/blog/database-timestamps-timezones) - Industry best practices
- [dbt Incremental Models: Postgres Guide](https://blog.dataengineerthings.org/dbt-incremental-models-the-complete-guide-for-postgres-users-de18356a00a7) - Incremental refresh patterns
- [PostgreSQL Triggers in 2026](https://thelinuxcode.com/postgresql-triggers-in-2026-design-performance-and-production-reality/) - Idempotent trigger patterns

### Tertiary (LOW confidence)
- [Choosing the Right Schema Migration Tool](https://www.pingcap.com/article/choosing-the-right-schema-migration-tool-a-comparative-guide/) - Alembic vs Flyway comparison
- [Date Dimension Table in Postgres](https://vitessedata.com/blog/date_dimension/) - Dimension table patterns
- Web search results on multi-timeframe analysis (trading-focused, not data engineering)

## Metadata

**Confidence breakdown:**
- EMA variant architecture: HIGH - Direct code analysis shows distinct calculation logic per variant
- dim_timeframe/dim_sessions design: HIGH - Production code with comprehensive schemas
- sync_cmc_ema_multi_tf_u.py sufficiency: HIGH - Handles 6 sources, watermarking, conflict resolution
- State tracking patterns: HIGH - EMAStateManager is mature, idempotent, tested
- DST handling: HIGH - PostgreSQL IANA timezone database + database functions
- SQL seed vs Python migration: MEDIUM - Industry practices vary, project-specific
- Validation patterns: MEDIUM - Based on best practices, not ta_lab2-specific testing

**Research date:** 2026-01-29
**Valid until:** 60 days (stable infrastructure, slow-moving best practices)

**Key risk areas:**
- Assumption that dim_timeframe/dim_sessions tables exist: Needs verification
- EMA variant usage by downstream consumers: Needs stakeholder survey
- Lookback window tuning: Needs production monitoring data
- Validation test sufficiency: Needs team agreement on coverage targets
