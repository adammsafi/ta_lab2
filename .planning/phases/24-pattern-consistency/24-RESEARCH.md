# Phase 24: Pattern Consistency - Research

**Researched:** 2026-02-05
**Domain:** Code refactoring, pattern extraction, template method pattern
**Confidence:** HIGH

## Summary

Phase 24 standardizes patterns across 6 EMA variants and 6 bar builders where Phase 21 gap analysis identified duplication worth addressing. The codebase already has strong patterns established in Phases 6-7 and 22-23 that provide proven templates to follow.

**Key findings:**
- BaseEMARefresher and EMAStateManager already provide 80% code sharing across EMAs (Lines 1-1112 in base_ema_refresher.py)
- Bar builders have ~8691 total LOC with ~80% duplication opportunity (Phase 21 GAP-M01)
- Phase 22 already added shared validation (detect_ohlc_violations, log_to_rejects in common_snapshot_contract.py)
- polars_bar_operations.py already extracts 100% identical Polars operations (120+ lines of shared code)
- EMA validation infrastructure complete with EMA_REJECTS_TABLE_DDL and validate_ema_output (Lines 67-387 in base_ema_refresher.py)

**Primary recommendation:** Follow BaseEMARefresher template method pattern for BaseBarBuilder - proven 70% LOC reduction, already demonstrates 80% shared code / 20% variant-specific split that Phase 21 identified as the target ratio.

## Standard Stack

The established libraries/tools already in use for pattern consistency:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python ABC | 3.11+ | Abstract Base Classes | Template method pattern foundation, used by BaseEMARefresher |
| dataclasses | stdlib | Configuration objects | Immutable config pattern (EMARefresherConfig, EMAStateConfig) |
| argparse | stdlib | CLI argument parsing | Standard CLI interface across all refreshers |
| SQLAlchemy | 2.x | Database operations | Engine management, text() queries, already used universally |
| pandas | latest | DataFrame operations | State management, result processing |
| polars | latest | High-performance aggregations | Already extracted to polars_bar_operations.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| typing.Protocol | 3.8+ | Structural subtyping | Alternative to ABC inheritance (Python-specific option) |
| psycopg | 3.x | Direct DB operations | Bar builders use this for performance (fallback to psycopg2) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ABC classes | typing.Protocol | Protocol = structural subtyping (duck typing), ABC = explicit contracts; ABC already used successfully |
| SQLAlchemy text() | SQLAlchemy Core | Core = ORM-style, text() = raw SQL control; codebase prefers text() for performance |
| Module-level functions | Class-based utilities | Functions = simpler for stateless operations, Classes = better for shared state; use both as appropriate |

**Installation:**
```bash
# Already installed - no new dependencies needed
# BaseBarBuilder will use existing stack
```

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/scripts/
├── bars/
│   ├── base_bar_builder.py         # NEW: Template method base class
│   ├── common_snapshot_contract.py # EXISTING: Shared utilities, validation
│   ├── polars_bar_operations.py    # EXISTING: Shared Polars operations
│   ├── refresh_cmc_price_bars_1d.py          # Refactor to use BaseBarBuilder
│   ├── refresh_cmc_price_bars_multi_tf.py    # Refactor to use BaseBarBuilder
│   └── (4 more calendar builders to refactor)
└── emas/
    ├── base_ema_refresher.py       # EXISTING: Template method success story
    ├── ema_state_manager.py        # EXISTING: State management pattern
    └── (6 EMA refreshers already using base)
```

### Pattern 1: Template Method Pattern (BaseEMARefresher Success Story)

**What:** Abstract base class defines execution flow, subclasses implement variant-specific behavior

**When to use:** 80%+ shared logic with 20% intentional differences (exact match for bar builders per Phase 21)

**Example from BaseEMARefresher:**
```python
# Source: /src/ta_lab2/scripts/emas/base_ema_refresher.py lines 443-467
class BaseEMARefresher(ABC):
    """
    Template Method Pattern:
    - Defines the execution flow (run → _run_incremental/_run_full_refresh)
    - Delegates script-specific behavior to abstract methods
    - Standardizes state management, logging, multiprocessing
    """

    def run(self) -> None:
        """Template Method: defines skeleton, calls abstract methods"""
        self.state_manager.ensure_state_table()
        tfs = self.get_timeframes()  # Abstract - subclass implements
        if self.config.full_refresh:
            self._run_full_refresh()  # Concrete - shared logic
        else:
            self._run_incremental()   # Concrete - shared logic

    @abstractmethod
    def get_timeframes(self) -> list[str]:
        """Subclass implements variant-specific TF loading"""

    @abstractmethod
    def compute_emas_for_id(self, id_: int, ...) -> int:
        """Subclass implements core computation logic"""
```

**Result:** EMA scripts reduced from ~500 LOC to ~150 LOC (70% reduction) per Phase 21 lines 369-389

### Pattern 2: Shared State Management (EMAStateManager)

**What:** Object-oriented state manager with unified schema across all variants

**When to use:** Multiple scripts need identical state tracking with different table names

**Example:**
```python
# Source: /src/ta_lab2/scripts/emas/ema_state_manager.py lines 78-99
UNIFIED_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    id                  INTEGER         NOT NULL,
    tf                  TEXT            NOT NULL,
    period              INTEGER         NOT NULL,
    daily_min_seen      TIMESTAMPTZ     NULL,
    daily_max_seen      TIMESTAMPTZ     NULL,
    last_time_close     TIMESTAMPTZ     NULL,
    last_canonical_ts   TIMESTAMPTZ     NULL,
    last_bar_seq        INTEGER         NULL,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    PRIMARY KEY (id, tf, period)
);
"""
```

**Key insight:** Schema is identical, only table name differs - perfect for class-based encapsulation

### Pattern 3: Shared Validation with Optional Reject Logging

**What:** Validation functions in common module, integrated into shared write operations

**When to use:** Multiple builders need identical validation logic

**Example from Phase 22:**
```python
# Source: Phase 22-01 summary - common_snapshot_contract.py
def detect_ohlc_violations(df: pd.DataFrame) -> pd.DataFrame:
    """Detect 3 violation types: high_lt_low, high_lt_oc_max, low_gt_oc_min"""
    # Returns rows that violate OHLC invariants

def upsert_bars(df, ..., keep_rejects=False, rejects_table=None):
    """Shared write function with optional reject logging"""
    if keep_rejects:
        violations = detect_ohlc_violations(df)
        log_to_rejects(violations, rejects_table)
    # Then write valid bars
```

**Result:** All 5 multi-TF builders inherited reject logging automatically via shared upsert_bars (Phase 22)

### Pattern 4: Extract Then Inject (Polars Operations)

**What:** Extract 100% identical operations to module, import and call from builders

**When to use:** Non-trivial logic duplicated verbatim across multiple scripts

**Example:**
```python
# Source: /src/ta_lab2/scripts/bars/polars_bar_operations.py lines 1-23
"""
Contains 100% identical Polars operations extracted from all 5 multi-tf bar builders.
All functions are pure, stateless, and operate on Polars DataFrames.
"""

def apply_standard_polars_pipeline(pl_df, include_missing_days=True):
    """Full pipeline (replaces 120+ lines of duplicated code)"""
    pl_df = apply_ohlcv_cumulative_aggregations(pl_df)
    pl_df = compute_extrema_timestamps_with_new_extreme_detection(pl_df)
    # ... more operations
    return pl_df
```

**Result:** 120+ lines of duplicated Polars code now shared across 5 builders

### Anti-Patterns to Avoid

- **Premature abstraction:** Don't extract until duplication confirmed (Phase 21 gap analysis required first)
- **Parameter threading:** Don't pass parameters through 5+ function layers - use module-level state or config objects (Phase 22 lesson: module-level _KEEP_REJECTS cleaner than parameter threading)
- **Forced consolidation:** Don't merge variants that have semantic differences (Phase 21: keep all 6 EMA variants - they exist for legitimate reasons)
- **Inheritance for code reuse:** Don't use inheritance solely to share code - use composition or utility modules when behavior isn't truly "is-a" relationship

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Template method pattern | Custom base class from scratch | Follow BaseEMARefresher | Proven pattern, 70% LOC reduction already demonstrated |
| State table management | Separate functions per table | EMAStateManager pattern | Unified schema, encapsulated operations, handles backfill detection |
| CLI argument parsing | Custom argparse setup | create_base_argument_parser() | Standard args (--db-url, --ids, --periods, logging) already defined |
| Reject table schema | Builder-specific schema | create_rejects_table_ddl() | Phase 22 established shared schema with violation_type + repair_action |
| OHLC validation | Per-builder checks | detect_ohlc_violations() | Phase 22 extracted 3 violation types, matches enforce_ohlc_sanity |
| EMA output validation | Custom bounds checks | validate_ema_output() | Phase 22 implemented hybrid bounds (price + statistical), handles NaN/infinity/negative/range |
| Query builder abstraction | Hand-rolled SQL generation | SQLAlchemy text() with f-strings | Codebase pattern: parameterized f-strings for clarity, text() for execution |

**Key insight:** Phase 22 already extracted validation. Phase 24 organizes existing code, doesn't rebuild validation from scratch.

## Common Pitfalls

### Pitfall 1: Extracting Base Class Without Checking Existing Patterns

**What goes wrong:** Create BaseBarBuilder that doesn't follow BaseEMARefresher pattern, duplicating design decisions

**Why it happens:** Not reviewing Phases 6-7 work before designing new base class

**How to avoid:**
1. Read base_ema_refresher.py lines 1-1112 completely
2. Identify abstract methods pattern: get_timeframes(), compute_emas_for_id(), get_source_table_info(), get_worker_function(), from_cli_args(), create_argument_parser()
3. Map to bar builder equivalents: get_timeframes() → not needed (bars are daily), compute_emas_for_id() → build_bars_for_id(), etc.
4. Copy successful patterns: EMARefresherConfig → BarBuilderConfig, template methods, CLI helpers

**Warning signs:**
- Designing base class API without referencing BaseEMARefresher
- Different naming conventions for similar concepts
- Not using dataclass for config objects

### Pitfall 2: Over-Extracting Variant-Specific Logic

**What goes wrong:** Force variant-specific code (calendar alignment, anchoring) into base class via complex parameters

**Why it happens:** Misinterpreting "80% shared" to mean "all logic should be shared"

**How to avoid:**
- Phase 21 key finding: "20% differences are intentional" (lines 78-83 in gap-analysis.md)
- Keep variant logic in subclasses: bar_seq assignment, window membership, calendar alignment
- Shared code = infrastructure: DB connection, CLI parsing, state loading, table creation
- Rule: If parameter controls algorithmic behavior (not just configuration), it belongs in subclass

**Warning signs:**
- Base class methods with mode="calendar_us" or mode="anchor_iso" parameters
- Complex conditional logic in base class based on variant type
- Subclasses that only set configuration, no actual implementation

### Pitfall 3: Breaking Working Validation Code

**What goes wrong:** Refactor validation code that Phase 22 added, introduce bugs, break audit trail

**Why it happens:** Not checking what Phase 22 already completed before refactoring

**How to avoid:**
1. Read Phase 22 summaries (22-01-SUMMARY.md shows validation already in common_snapshot_contract.py)
2. Check existing functions: detect_ohlc_violations(), log_to_rejects(), validate_ema_output()
3. Only organize/rename - don't change behavior
4. Keep reject table schema unchanged (violation_type, repair_action, original OHLCV)

**Warning signs:**
- Changing detect_ohlc_violations logic
- Modifying reject table schema
- Moving validation out of common_snapshot_contract.py

### Pitfall 4: Module Location Bike-Shedding

**What goes wrong:** Spend hours debating where to put shared utilities, delay actual refactoring

**Why it happens:** No clear module organization guidelines

**How to avoid:**
- Follow existing pattern: common_snapshot_contract.py for bar-related shared code
- Rule: If 100% of builders use it, put it in common file
- Rule: If it's algorithmic logic (not infrastructure), keep it in module with semantic name (polars_bar_operations.py, not "utils.py")
- Don't create new directories - use existing scripts/bars/ and scripts/emas/ structure

**Warning signs:**
- Creating "utils/", "helpers/", "shared/" directories
- Moving files multiple times
- Spending more than 5 minutes deciding where to put a module

## Code Examples

Verified patterns from official sources:

### Template Method: run() orchestrates abstract methods
```python
# Source: base_ema_refresher.py lines 749-805
def run(self) -> None:
    """
    Main execution: Orchestrate full refresh flow.
    Template Method:
    1. Ensure state table exists
    2. Load timeframes
    3. Execute full refresh or incremental refresh
    4. Update state table
    """
    self.logger.info(f"Starting EMA refresh: {self.__class__.__name__}")

    # Ensure state table exists
    self.state_manager.ensure_state_table()

    # Load timeframes - ABSTRACT METHOD (subclass implements)
    tfs = self.get_timeframes()
    self.logger.info(f"Loaded {len(tfs)} timeframes: {tfs}")

    # Log source table info - ABSTRACT METHOD (subclass implements)
    source_info = self.get_source_table_info()
    self.logger.info(f"Source: {source_info['bars_schema']}.{source_info['bars_table']}")

    # Execute - CONCRETE METHODS (base class implements)
    if self.config.full_refresh:
        self._run_full_refresh()
    else:
        self._run_incremental()
```

**Pattern:** Base class controls flow, calls abstract methods at decision points

### State Manager: Unified schema with configuration-driven behavior
```python
# Source: ema_state_manager.py lines 102-125, 209-236
class EMAStateManager:
    def __init__(self, engine: Engine, config: EMAStateConfig):
        self.engine = engine
        self.config = config

    def ensure_state_table(self) -> None:
        """Create unified EMA state table if it doesn't exist."""
        sql = UNIFIED_STATE_SCHEMA.format(
            schema=self.config.state_schema,
            table=self.config.state_table,
        )
        with self.engine.begin() as conn:
            conn.execute(text(sql))

    def update_state_from_output(self, output_table: str, output_schema: str) -> int:
        """Update state table from EMA output table and optionally bars table."""
        if self.config.use_canonical_ts:
            return self._update_canonical_ts_mode(output_table, output_schema)
        else:
            return self._update_multi_tf_mode(output_table, output_schema)
```

**Pattern:** Configuration object controls behavior, single class supports multiple variants

### Factory Pattern: from_cli_args() creates instances
```python
# Source: BaseEMARefresher pattern (abstract method lines 709-728)
@classmethod
@abstractmethod
def from_cli_args(cls, args: argparse.Namespace) -> "BaseEMARefresher":
    """
    Factory method: Create refresher from CLI arguments.

    Subclasses implement this to:
    1. Resolve db_url from args.db_url
    2. Create engine
    3. Load IDs from args.ids (using load_ids helper)
    4. Load periods from args.periods (using load_periods helper)
    5. Build EMARefresherConfig and EMAStateConfig
    6. Return instance
    """

# Example implementation in subclass:
@classmethod
def from_cli_args(cls, args: argparse.Namespace) -> "MultiTFEMARefresher":
    db_url = resolve_db_url(args.db_url)
    engine = create_engine(db_url)

    refresher = cls.__new__(cls)  # Create instance without __init__
    BaseEMARefresher.__init__(refresher, ...)  # Call base __init__ manually

    ids = refresher.load_ids(args.ids)  # Use helper method
    periods = refresher.load_periods(args.periods)

    config = EMARefresherConfig(
        db_url=db_url,
        ids=ids,
        periods=periods,
        # ... more config
    )

    return cls(config, state_config, engine)
```

**Pattern:** Factory method handles construction complexity, uses helper methods from base class

### Shared Validation: detect + log pattern
```python
# Source: Phase 22 implementation (common_snapshot_contract.py per summary)
def detect_ohlc_violations(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect OHLC invariant violations.

    Returns DataFrame with violation rows containing:
    - violation_type: 'high_lt_low' | 'high_lt_oc_max' | 'low_gt_oc_min'
    - original OHLCV values before repair
    """
    violations = []

    # Check 1: high >= low
    mask_high_lt_low = df['high'] < df['low']
    if mask_high_lt_low.any():
        violations.append(
            df[mask_high_lt_low].assign(violation_type='high_lt_low')
        )

    # Check 2: high >= max(open, close)
    oc_max = df[['open', 'close']].max(axis=1)
    mask_high_lt_oc_max = df['high'] < oc_max
    if mask_high_lt_oc_max.any():
        violations.append(
            df[mask_high_lt_oc_max].assign(violation_type='high_lt_oc_max')
        )

    # Check 3: low <= min(open, close)
    oc_min = df[['open', 'close']].min(axis=1)
    mask_low_gt_oc_min = df['low'] > oc_min
    if mask_low_gt_oc_min.any():
        violations.append(
            df[mask_low_gt_oc_min].assign(violation_type='low_gt_oc_min')
        )

    return pd.concat(violations) if violations else pd.DataFrame()

def upsert_bars(df, engine, table, keep_rejects=False, rejects_table=None):
    """Shared write function with optional reject logging."""
    if keep_rejects:
        violations = detect_ohlc_violations(df)
        if not violations.empty:
            log_to_rejects(engine, violations, rejects_table)

    # Write valid bars (after enforce_ohlc_sanity repairs)
    df.to_sql(table, engine, if_exists='append', index=False)
```

**Pattern:** Detect violations before repair, log to separate table, continue processing

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Duplicated bar builder code (~850 LOC each) | Emerging: polars_bar_operations.py (120+ lines shared) | Phase 22, Jan 2026 | Partial extraction started, full BaseBarBuilder needed |
| Manual EMA refresh scripts | BaseEMARefresher template (150 LOC per script) | Phase 6-7, Dec 2025 | 70% LOC reduction, 80% code sharing |
| No validation audit trail | Reject tables with violation_type + repair_action | Phase 22, Feb 2026 | Complete audit trail for OHLC repairs |
| EMA values written without validation | validate_ema_output() with hybrid bounds | Phase 22, Feb 2026 | Catches NaN/infinity/range violations |
| Per-script state management | EMAStateManager with unified schema | Phase 6-7, Dec 2025 | Consistent state tracking, backfill detection |
| Parameter threading for config | Dataclass config objects | Phase 6-7, Dec 2025 | Immutable, type-safe configuration |

**Deprecated/outdated:**
- Row-by-row iteration for bar aggregations: Replaced by Polars vectorized operations (20-30% faster)
- Inline validation code: Phase 22 extracted to common_snapshot_contract.py
- Per-script CLI parsing: BaseEMARefresher provides create_base_argument_parser() with standard args

## Open Questions

Things that couldn't be fully resolved:

1. **Bar state management consolidation**
   - What we know: EMAs use EMAStateManager with unified schema (id, tf, period) PRIMARY KEY
   - What's unclear: Bars have different state schemas - 1D uses (id), multi-TF uses (id, tf)
   - Recommendation: Phase 21 line 219-240 documents this is JUSTIFIED (intentional design). Check if BarStateManager exists from Phase 6-7. If not, create separate state managers (Bar1DStateManager, BarMultiTFStateManager) - don't force unification where schemas serve different purposes

2. **Query builder extraction scope**
   - What we know: User wants query builder functions extracted (CONTEXT.md decision)
   - What's unclear: Whether to extract full queries or composable query fragments
   - Recommendation: Start conservative - extract table name mapping (variant_to_table_name dict) and parameterized query templates. Don't build query DSL unless duplication is extreme

3. **NULL handling and gap detection complexity**
   - What we know: Gap detection sets is_missing_days flag (common_snapshot_contract.py line 156-182)
   - What's unclear: Whether NULL/gap validation is simple enough to inline or complex enough to extract
   - Recommendation: Keep inline - simple 1-2 line checks. Phase 21 line 410-435 (GAP-M04) says gap-fill strategy needs documentation, not extraction

4. **BaseBarBuilder abstract method signatures**
   - What we know: BaseEMARefresher uses compute_emas_for_id(id_, periods, start, end, **extra_args)
   - What's unclear: What bar builder equivalent should be - build_bars_for_id()? process_id()? Different signature?
   - Recommendation: Map after reading 1D builder completely - signature depends on whether builders process one ID at a time or all IDs together

## Sources

### Primary (HIGH confidence)
- `/src/ta_lab2/scripts/emas/base_ema_refresher.py` - BaseEMARefresher template method implementation (1112 lines)
- `/src/ta_lab2/scripts/emas/ema_state_manager.py` - EMAStateManager unified state schema (450 lines)
- `.planning/phases/21-comprehensive-review/deliverables/gap-analysis.md` - GAP-M01 (BaseBarBuilder missing, 80% duplication)
- `.planning/phases/22-critical-data-quality-fixes/22-01-SUMMARY.md` - Phase 22 validation extraction
- `/src/ta_lab2/scripts/bars/polars_bar_operations.py` - Existing shared bar operations (120+ lines)
- `/src/ta_lab2/scripts/bars/common_snapshot_contract.py` - Shared validation and utilities

### Secondary (MEDIUM confidence)
- [Template Method in Python / Design Patterns](https://refactoring.guru/design-patterns/template-method/python/example) - Template method pattern reference
- [Refactoring with Design Patterns](https://www.mindfulchase.com/deep-dives/the-art-of-design-patterns/refactoring-with-design-patterns-how-patterns-improve-legacy-code.html) - Legacy code refactoring patterns
- [Code Refactoring: When to Refactor](https://www.tembo.io/blog/code-refactoring) - Extract vs inline decision framework
- [Top 8 Python Libraries for Data Quality Checks](https://www.telm.ai/blog/8-essential-python-libraries-for-mastering-data-quality-checks/) - Validation patterns 2026

### Tertiary (LOW confidence)
- [Escaping the template pattern hellscape in Python](https://rednafi.com/python/escape-template-pattern/) - Alternative to ABC using functions (not applicable - ABC already successful)
- [SQLAlchemy ORM Tutorial](https://auth0.com/blog/sqlalchemy-orm-tutorial-for-python-developers/) - General SQLAlchemy patterns (codebase already established patterns)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All tools already in use, verified in codebase
- Architecture: HIGH - BaseEMARefresher provides proven template, Phase 22 established validation patterns
- Pitfalls: HIGH - Derived from Phase 21 analysis, Phase 22 lessons, codebase review

**Research date:** 2026-02-05
**Valid until:** 30 days (stable codebase patterns, unlikely to change rapidly)

**Key constraints from CONTEXT.md:**
- User decided: Extract query builder functions (line 30)
- User decided: Variant-aware table abstraction - centralized mapping (line 32)
- User decided: Allow refactoring - variants can be updated (line 24)
- Claude decides: Query implementation approach (SQL strings vs SQLAlchemy Core) (line 31)
- Claude decides: State schema standardization level (line 40)
- Claude decides: NULL/gap validation approach (line 50)

**Critical finding:** Phase 6-7 and Phase 22 already completed 60% of Phase 24 work:
1. BaseEMARefresher template ✅ (mirror for bars)
2. EMAStateManager pattern ✅ (check if BarStateManager exists)
3. Validation extraction ✅ (detect_ohlc_violations, validate_ema_output)
4. Polars operations extraction ✅ (polars_bar_operations.py)

**Remaining work:** BaseBarBuilder creation, state manager check/creation, query builder extraction, reject logging organization
