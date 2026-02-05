# Phase 21: Comprehensive Review - Research

**Researched:** 2026-02-05
**Domain:** Codebase analysis, documentation generation, system comprehension
**Confidence:** HIGH

## Summary

Phase 21 requires comprehensive read-only analysis of all bar/EMA components to answer 4 key questions (EMA variants, incremental refresh, validation points, new asset process) and deliver 4 structured documents (script inventory, data flow diagram, variant comparison, gap analysis). This research identifies proven methodologies for deep codebase analysis, documentation generation patterns, and gap prioritization frameworks.

**Key Findings:**
- Modern codebase analysis uses multi-perspective approach (architecture, implementation, operations)
- Static analysis tools trace imports/dependencies to create system graphs
- Data flow diagrams use layered views (L0/L1/L2) with hybrid format (visual + narrative)
- Gap analysis uses severity tiers (CRITICAL/HIGH/MEDIUM/LOW) based on impact dimensions
- Incremental refresh patterns use watermarking for state management
- Validation patterns for financial data emphasize temporal consistency and invariant enforcement

**Primary recommendation:** Use static analysis to build dependency graphs, layer data flow diagrams from high-level to detailed, document variants with comparison matrices highlighting WHAT and WHY, and prioritize gaps by data quality risk and system reliability impact.

## Standard Stack

The established libraries/tools for comprehensive codebase analysis:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ast (Python stdlib) | 3.x | Parse Python source to AST for static analysis | Native Python support, no dependencies, industry standard for code analysis |
| importlib.metadata | 3.x | Inspect installed packages and dependencies | Standard library, reliable package introspection |
| Mermaid | 10.x+ | Text-based diagram generation (flowcharts, graphs) | Industry standard for docs-as-code, renders in GitHub/GitLab, version-controllable |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| findimports | Latest | Extract Python module dependencies from source | When mapping import relationships, detecting unused imports |
| graphviz (optional) | Latest | Generate complex dependency graphs visually | When Mermaid graphs become too large (100+ nodes) |
| Great Expectations | 0.18.x+ | Define data quality "expectations" (rules) | When validating financial data invariants (OHLC relationships) |
| pandas profiling | Latest | Automated data quality reports | When analyzing bar/EMA table data quality |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Mermaid | PlantUML | PlantUML has more diagram types but harder syntax, not as well supported in modern docs |
| ast module | Pyan (call graphs) | Pyan generates call graphs, not import graphs - use for inter-function analysis |
| Manual dependency tracing | Importlab (Google) | Importlab auto-infers dependencies but adds external dependency, overkill for focused analysis |

**Installation:**
```bash
# Core tools (if needed beyond stdlib)
pip install mermaid-py

# Supporting tools (optional, install as needed)
pip install findimports great-expectations pandas-profiling
```

## Architecture Patterns

### Recommended Analysis Structure
```
.planning/phases/21-comprehensive-review/
├── 21-CONTEXT.md           # User decisions (already exists)
├── 21-RESEARCH.md          # This file
├── deliverables/
│   ├── script-inventory.md       # RVWD-01: Every script cataloged
│   ├── data-flow-diagram.md      # RVWD-02: Visual + narrative flows
│   ├── variant-comparison.md     # RVWD-03: Side-by-side matrix
│   └── gap-analysis.md           # RVWD-04: Severity-tiered gaps
└── findings/
    ├── ema-variants.md           # RVWQ-01: What each variant does
    ├── incremental-refresh.md    # RVWQ-02: How refresh works
    ├── validation-points.md      # RVWQ-03: Where validation happens
    └── new-asset-guide.md        # RVWQ-04: Step-by-step onboarding
```

### Pattern 1: Multi-Perspective Code Analysis
**What:** Analyze codebase from three complementary perspectives
**When to use:** When performing comprehensive reviews of complex systems
**Example:**
```python
# Perspective 1: Architecture (system design, component relationships)
# - What tables exist? How do they relate?
# - What are the major subsystems? (bar builders, EMA calculators, state managers)

# Perspective 2: Implementation (code structure, patterns, quality)
# - How is OHLC calculated? What edge cases are handled?
# - Which scripts use BaseEMARefresher? Is pattern consistent?

# Perspective 3: Operations (runtime behavior, state, observability)
# - How does incremental refresh work? What state is tracked?
# - What happens when a script fails? How is recovery handled?
```
**Source:** [DEV Community - Multi-Perspective Analysis](https://dev.to/tonegabes/prompt-for-comprehensive-codebase-exploration-and-documentation-from-multi-perspective-analysis-1h55)

### Pattern 2: Layered Data Flow Diagrams
**What:** Create hierarchical views (L0 = context, L1 = system, L2 = detailed process)
**When to use:** When mapping complex data pipelines with multiple transformations
**Example:**
```mermaid
# Level 0 - Context Diagram (external entities + system boundary)
graph LR
    CMC[CoinMarketCap API] --> System[ta_lab2]
    System --> Backtest[Backtesting Engine]

# Level 1 - System Overview (major components)
graph LR
    PH[price_histories7] --> Bars[Bar Builders]
    Bars --> EMAs[EMA Calculators]
    EMAs --> Features[Feature Pipeline]
    Features --> Signals[Signal Generation]

# Level 2 - Detailed Process (specific script flows)
graph TB
    Start[refresh_cmc_price_bars_1d.py] --> LoadState[Load State Table]
    LoadState --> Query[Query price_histories7 WHERE ts > last_src_ts]
    Query --> Calc[Calculate OHLC with invariant checks]
    Calc --> Validate[Validate gaps/outliers/NULL ratios]
    Validate --> Write[Upsert to cmc_price_bars_1d]
    Write --> UpdateState[Update state table]
```
**Source:** [Lucidchart - Data Flow Diagrams](https://www.lucidchart.com/pages/data-flow-diagram), [IBM - DFD Topics](https://www.ibm.com/think/topics/data-flow-diagram)

### Pattern 3: Hybrid Diagram Format (Visual + Narrative)
**What:** Combine Mermaid visual with detailed textual explanation
**When to use:** When diagrams alone can't capture edge cases, state transitions, or business logic
**Example:**
```markdown
## Data Flow: price_histories7 → bars → EMAs

### Visual Overview
[Mermaid diagram here - shows boxes and arrows]

### Detailed Narrative
**Step 1: Bar Creation**
- Script: `refresh_cmc_price_bars_1d.py`
- Input: Raw price data from `price_histories7` table
- Validation: NOT NULL checks on OHLCV columns, OHLC invariants (high >= low, etc.)
- Quality flags: Sets `is_partial_start=FALSE` (1D bars are always complete)
- Output: Validated bars written to `cmc_price_bars_1d`
- State: Updates `last_src_ts` in `cmc_price_bars_1d_state` per asset

**Step 2: EMA Calculation**
[Continue detailed walkthrough...]
```
**Source:** [RudderStack - DFD Components](https://www.rudderstack.com/blog/data-flow-diagram/)

### Pattern 4: Variant Comparison Matrix
**What:** Side-by-side comparison table highlighting dimensions of difference
**When to use:** When documenting multiple implementations of similar functionality (6 EMA variants, 6 bar builders)
**Example:**
```markdown
## EMA Variant Comparison

| Dimension | v1 (multi_tf) | v2 | cal_us | cal_iso | cal_anchor_us | cal_anchor_iso |
|-----------|---------------|----|---------|---------|--------------------|---------------------|
| **Data Source** | cmc_price_bars_multi_tf | cmc_price_bars_1d | cmc_price_bars_multi_tf_cal_us | cmc_price_bars_multi_tf_cal_iso | cmc_price_bars_multi_tf_cal_anchor_us | cmc_price_bars_multi_tf_cal_anchor_iso |
| **Timeframe Source** | dim_timeframe (tf_day) | dim_timeframe (tf_day) | Implicit from bars table | Implicit from bars table | Implicit from bars table | Implicit from bars table |
| **Calendar Alignment** | No (canonical days) | No (synthetic multi-TF) | Yes (US Sunday weeks) | Yes (ISO Monday weeks) | Yes (US + year anchor) | Yes (ISO + year anchor) |
| **State Schema** | (id, tf, period) | (id, tf, period) | (id, tf, period) | (id, tf, period) | (id, tf, period) | (id, tf, period) |
| **WHY it exists** | Original multi-TF EMAs from persisted bars | Compute multi-TF synthetically from daily | Weekly/monthly EMAs aligned to US calendar | Weekly/monthly EMAs aligned to ISO calendar | Year-anchored calendar EMAs (US) | Year-anchored calendar EMAs (ISO) |

**Key Insight:** All 6 variants share EMA calculation logic (compute_ema), state management (EMAStateManager), and base class (BaseEMARefresher). Differences are WHAT data they read and HOW timeframes are aligned.
```
**Source:** [Refactoring Guru - Abstract Factory](https://refactoring.guru/design-patterns/abstract-factory)

### Pattern 5: Severity-Tiered Gap Analysis
**What:** Categorize gaps by impact dimensions (data quality, system reliability, development velocity)
**When to use:** When prioritizing technical debt, bugs, and architectural issues for phased remediation
**Example:**
```markdown
## Gap Analysis with Severity Tiers

### CRITICAL (Data Quality Risk OR System Reliability Threats)
**Definition:** Could lead to incorrect calculations, silent errors, bad trading signals, crashes, data loss, or inability to run daily refresh

1. **Bar tables missing NOT NULL constraints on OHLCV columns**
   - Impact: NULL values can enter pipeline silently → incorrect EMA calculations → bad signals
   - Evidence: information_schema query shows no NOT NULL constraints
   - Remediation: Phase 22 - add constraints, backfill/delete invalid rows

### HIGH (Architectural Inconsistency, Manual Workarounds Required)
**Definition:** Violates established patterns, requires manual intervention, or blocks scalability

2. **Bar builders don't use dim_timeframe (hardcoded TF logic)**
   - Impact: Inconsistent with EMAs, hard to extend, maintenance burden
   - Evidence: Bar scripts have hardcoded TF arrays vs EMAs query dim_timeframe
   - Remediation: Phase 23 - migrate bar builders to query dim_timeframe

### MEDIUM (Code Duplication, Missing Documentation)
**Definition:** Maintainability issues, but system functions correctly

3. **No BaseBarBuilder template class (duplication across 6 builders)**
   - Impact: 80% code duplication, inconsistent CLI parsing, hard to maintain
   - Evidence: Common patterns (DB connection, state loading) copied 6 times
   - Remediation: Phase 24 - extract BaseBarBuilder following BaseEMARefresher pattern

### LOW (Cosmetic, Nice-to-Have Improvements)
**Definition:** Doesn't affect correctness or maintainability, quality-of-life improvements

4. **Incremental refresh observability low (no summary logging)**
   - Impact: Operational convenience, harder to debug
   - Evidence: Scripts complete silently, no "Refreshed 50 assets, 10K rows" logs
   - Remediation: Phase 24 - add refresh telemetry
```
**Source:** [Qodo - Gap Analysis in Testing](https://www.qodo.ai/blog/gap-analysis-in-software-testing/), [E-Informatyka - AIODC Framework](https://www.e-informatyka.pl/EISEJ/papers/2026/1/2/)

### Anti-Patterns to Avoid
- **Analysis paralysis:** Don't trace every function call - focus on data flows, state management, and validation points
- **Documentation without evidence:** Don't claim "Script X does Y" without citing line numbers or code snippets
- **Variant consolidation bias:** Don't recommend merging variants based on similarity - they exist for reasons (calendar alignment, ISO vs US)
- **Flat gap lists:** Don't create unordered gap lists - severity tiers enable prioritization for Phase 22-24

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Python import dependency graphs | Custom AST walker | findimports, importlab, Scalpel | Handles edge cases (relative imports, circular deps, dynamic imports), battle-tested |
| Data flow diagrams | PowerPoint/draw.io | Mermaid (text-based) | Version-controllable, renders in GitHub, docs-as-code, AI-friendly |
| Data quality validation rules | Custom assert statements | Great Expectations | Declarative expectations (YAML/Python), extensive rule library (temporal validity, OHLC invariants), integrates with dbt/Airflow |
| Gap prioritization frameworks | Ad-hoc severity labels | Standardized impact dimensions | Consistent criteria (data quality risk, system reliability, dev velocity), enables phase assignment |
| Code quality metrics | Manual code review | Static analysis tools (Flake8, MyPy) | Automated, catches edge cases (unused imports, type errors), CI-integrable |

**Key insight:** Comprehensive analysis is 80% methodology, 20% tools. The methodology (multi-perspective analysis, layered diagrams, severity-tiered gaps) matters more than the tools used.

## Common Pitfalls

### Pitfall 1: Skipping Evidence Citations
**What goes wrong:** Documentation claims "Script X reads from table Y" without line numbers or code snippets
**Why it happens:** Assumption that reading code once is enough to remember details
**How to avoid:** ALWAYS cite evidence (file paths, line numbers, code snippets) for every factual claim
**Warning signs:** Vague statements like "probably uses", "seems to", "might be"
**Example:**
```markdown
# BAD
"The bar builder reads from price_histories7"

# GOOD
"The bar builder reads from price_histories7 (refresh_cmc_price_bars_1d.py lines 670-778:
query = f'SELECT * FROM price_histories7 WHERE ts > {last_src_ts}')"
```

### Pitfall 2: Conflating "Similar" with "Duplicate"
**What goes wrong:** Recommending consolidation of 6 EMA variants because they "look the same"
**Why it happens:** Focus on WHAT code does (EMA calculation) vs WHY it exists (calendar alignment)
**How to avoid:** Document both WHAT and WHY for each variant, flag questions but don't recommend merging
**Warning signs:** "These scripts are 90% identical, should merge"
**Example:**
From Phase 20 Historical Review: "All 6 EMA variants share compute_ema logic BUT exist for legitimate reasons: calendar alignment (US vs ISO weeks), timeframe source (dim_timeframe vs implicit from bars), anchoring semantics (year boundaries)"

### Pitfall 3: Analysis Without Depth Levels
**What goes wrong:** Creating single-level data flow diagrams that are either too high-level (no details) or too detailed (overwhelming)
**Why it happens:** Trying to capture everything in one diagram
**How to avoid:** Use layered approach (L0 = context, L1 = system overview, L2 = detailed process flows)
**Warning signs:** Diagram has 50+ boxes, or diagram shows "data flows somewhere" without specifics
**Example:** Price_histories7 → bars → EMAs (L1) drills down to "refresh_cmc_price_bars_1d.py: load state → query with watermark → calculate OHLC → validate → write → update state" (L2)

### Pitfall 4: Gap Analysis Without Severity Criteria
**What goes wrong:** Creating flat list of 50 gaps with no prioritization
**Why it happens:** Identifying issues is easier than prioritizing them
**How to avoid:** Establish clear CRITICAL/HIGH/MEDIUM/LOW criteria BEFORE cataloging gaps
**Warning signs:** All gaps labeled HIGH, or gaps ordered alphabetically instead of by impact
**Example from CONTEXT.md:**
- CRITICAL = "Data quality risk OR system reliability threats - could lead to incorrect calculations, crashes, data loss"
- HIGH = "Architectural inconsistency, manual workarounds"
- MEDIUM = "Code duplication, missing docs"
- LOW = "Cosmetic, nice-to-have"

### Pitfall 5: Treating All State Management as "The Same"
**What goes wrong:** Assuming bar state and EMA state should be identical
**Why it happens:** Pattern matching without understanding domain differences
**How to avoid:** Document WHY state schemas differ (1D bars: simple watermark, multi-TF bars: backfill detection, EMAs: per-period granularity)
**Warning signs:** "Inconsistent state patterns" flagged as HIGH severity gap
**Example from Phase 20 Current State:** "Bar builders: 1D uses last_src_ts (simple), multi-TF uses daily_min_seen/daily_max_seen (backfill detection), calendar adds tz (timezone tracking). Variation is JUSTIFIED by different builder needs."

### Pitfall 6: Missing the "Already Done" Work
**What goes wrong:** Documenting "migrate EMAs to bar tables" as critical gap when it's already complete
**Why it happens:** Relying on old documentation instead of reading current code
**How to avoid:** Read actual source code, verify with grep/static analysis, cite current line numbers
**Warning signs:** Gap based on Phase 1-10 docs without verifying current state
**Example from Phase 20 Current State:** "CRITICAL FINDING: All 6 EMA variants ALREADY USE validated bar tables (evidence: refresh_cmc_ema_multi_tf_from_bars.py line 70: bars_table = 'cmc_price_bars_multi_tf'). Phase 22 assumption invalid."

## Code Examples

Verified patterns from domain analysis:

### Static Analysis: Import Graph Construction
```python
# Source: Based on findimports and Scalpel patterns
import ast
import os
from pathlib import Path
from typing import Dict, Set, List

def build_import_graph(script_dir: Path) -> Dict[str, Set[str]]:
    """
    Build import dependency graph from Python scripts.

    Returns: {script_name: {imported_modules...}}
    """
    graph = {}

    for py_file in script_dir.rglob("*.py"):
        if "old" in py_file.parts or "__pycache__" in py_file.parts:
            continue  # Skip archived code

        with open(py_file, 'r', encoding='utf-8') as f:
            try:
                tree = ast.parse(f.read(), filename=str(py_file))
            except SyntaxError:
                continue  # Skip unparseable files

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)

        rel_path = py_file.relative_to(script_dir)
        graph[str(rel_path)] = imports

    return graph

# Example output for script inventory:
# {
#   "refresh_cmc_price_bars_1d.py": {
#       "pandas", "sqlalchemy", "ta_lab2.db.connection",
#       "ta_lab2.bars.common_snapshot_contract"
#   },
#   "refresh_cmc_ema_multi_tf_from_bars.py": {
#       "ta_lab2.scripts.emas.base_ema_refresher",
#       "ta_lab2.scripts.emas.ema_state_manager",
#       "ta_lab2.features.ema"
#   }
# }
```

### SQL Query Analysis: Table Dependencies
```python
# Source: Pattern for analyzing SQL queries in scripts
import re
from typing import Set

def extract_table_references(sql_query: str) -> Set[str]:
    """
    Extract table names from SQL query (FROM/JOIN/INSERT INTO clauses).

    Handles common patterns:
    - FROM table_name
    - JOIN table_name
    - INSERT INTO table_name
    - UPDATE table_name
    """
    tables = set()

    # Pattern: FROM/JOIN/INSERT INTO/UPDATE followed by table name
    patterns = [
        r'\bFROM\s+([a-z_0-9]+)',
        r'\bJOIN\s+([a-z_0-9]+)',
        r'\bINSERT\s+INTO\s+([a-z_0-9]+)',
        r'\bUPDATE\s+([a-z_0-9]+)',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, sql_query, re.IGNORECASE)
        tables.update(matches)

    return tables

# Example: Trace data flow for script inventory
script_path = "src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py"
with open(script_path, 'r') as f:
    content = f.read()

# Extract SQL queries (multi-line strings)
sql_queries = re.findall(r'"""(.*?)"""', content, re.DOTALL)
sql_queries += re.findall(r"'''(.*?)'''", content, re.DOTALL)

all_tables = set()
for query in sql_queries:
    all_tables.update(extract_table_references(query))

print(f"Tables accessed by {script_path.split('/')[-1]}:")
print(all_tables)
# Output: {'price_histories7', 'cmc_price_bars_1d', 'cmc_price_bars_1d_state'}
```

### Mermaid Diagram Generation
```python
# Source: Pattern for programmatic diagram generation
from typing import List, Tuple

def generate_data_flow_mermaid(
    nodes: List[str],
    edges: List[Tuple[str, str, str]]
) -> str:
    """
    Generate Mermaid flowchart from nodes and edges.

    Args:
        nodes: List of node identifiers
        edges: List of (from, to, label) tuples

    Returns: Mermaid diagram as string
    """
    lines = ["graph LR"]

    # Add edges with labels
    for from_node, to_node, label in edges:
        sanitized_label = label.replace('"', "'")
        lines.append(f'    {from_node}["{from_node}"] -->|{sanitized_label}| {to_node}["{to_node}"]')

    return "\n".join(lines)

# Example: Data flow for bars → EMAs
nodes = ["price_histories7", "bars_1d", "bars_multi_tf", "emas_v1", "emas_v2"]
edges = [
    ("price_histories7", "bars_1d", "refresh_cmc_price_bars_1d.py"),
    ("price_histories7", "bars_multi_tf", "refresh_cmc_price_bars_multi_tf.py"),
    ("bars_multi_tf", "emas_v1", "refresh_cmc_ema_multi_tf_from_bars.py"),
    ("bars_1d", "emas_v2", "refresh_cmc_ema_multi_tf_v2.py"),
]

diagram = generate_data_flow_mermaid(nodes, edges)
print(diagram)
# Output renders as flowchart in Mermaid-compatible viewers
```

### Gap Severity Classification
```python
# Source: Pattern for systematic gap analysis
from dataclasses import dataclass
from enum import Enum
from typing import List

class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

@dataclass
class Gap:
    title: str
    description: str
    impact: str
    evidence: str
    severity: Severity
    phase_assignment: int  # Which phase should fix this (22/23/24)

def classify_gap_severity(
    affects_data_quality: bool,
    affects_system_reliability: bool,
    requires_manual_intervention: bool,
    affects_maintainability: bool
) -> Severity:
    """
    Classify gap severity based on impact dimensions.

    Decision tree from Phase 21 CONTEXT.md:
    - CRITICAL: Data quality risk OR system reliability threats
    - HIGH: Architectural inconsistency, manual workarounds
    - MEDIUM: Code duplication, missing docs
    - LOW: Cosmetic, nice-to-have
    """
    if affects_data_quality or affects_system_reliability:
        return Severity.CRITICAL
    elif requires_manual_intervention:
        return Severity.HIGH
    elif affects_maintainability:
        return Severity.MEDIUM
    else:
        return Severity.LOW

# Example: Classify "Bar tables missing NOT NULL constraints"
gap = Gap(
    title="Bar tables missing NOT NULL constraints on OHLCV columns",
    description="NULL values can enter pipeline silently",
    impact="Could lead to incorrect EMA calculations → bad trading signals",
    evidence="information_schema query shows no NOT NULL constraints",
    severity=classify_gap_severity(
        affects_data_quality=True,  # NULL OHLCs corrupt downstream
        affects_system_reliability=False,
        requires_manual_intervention=False,
        affects_maintainability=False
    ),
    phase_assignment=22  # Phase 22: Critical Data Quality Fixes
)

assert gap.severity == Severity.CRITICAL
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual code archaeology (read commits one-by-one) | AI-powered graph-based analysis (Greptile builds function/class graphs) | 2025-2026 | Holistic architectural visibility, faster onboarding |
| Static diagrams (draw.io, PowerPoint) | Text-based diagrams (Mermaid, PlantUML) | 2020+ | Version-controllable, docs-as-code, renders in GitHub |
| Manual gap identification | AI-driven autonomous quality control (self-detect anomalies) | 2026 | Proactive data quality, real-time feedback |
| Single-perspective code review | Multi-perspective analysis (architect/developer/product) | 2024+ | Comprehensive coverage, addresses multiple stakeholder concerns |
| Flat severity lists | Impact dimension matrices (security/performance/stability/velocity) | 2025+ | Systematic prioritization, enables phase assignment |
| Batch validation (run tests) | Continuous validity checks (real-time streaming) | 2025-2026 | Immediate feedback, proactive issue detection |

**Deprecated/outdated:**
- Monolithic documentation: Modern approach splits by deliverable type (inventory, diagrams, comparisons, gaps)
- PowerPoint/Visio diagrams: Text-based formats (Mermaid) preferred for version control
- Unstructured gap lists: Severity tiers with clear criteria required for actionable planning

## Open Questions

Things that couldn't be fully resolved:

1. **What is the optimal Mermaid diagram size before splitting?**
   - What we know: Best practices recommend "avoiding overloading diagrams", breaking down complex diagrams
   - What's unclear: Specific node count threshold (50 nodes? 100 nodes? depends on edge density?)
   - Recommendation: Start with L0/L1/L2 layering, split L2 if diagram exceeds screen width when rendered

2. **How deep should import tracing go?**
   - What we know: Phase 21 CONTEXT says "trace every import", but also "no pattern analysis across scripts (that's Phase 24)"
   - What's unclear: Trace 1-level deep (direct imports) or N-levels deep (transitive dependencies)?
   - Recommendation: Trace 2 levels for script inventory (script → direct imports → their key dependencies), flag deep chains (5+ levels) as complexity signals

3. **Should bar builders and EMA calculators use identical state schemas?**
   - What we know: Phase 20 Current State says "variation is justified by different needs" (1D simple, multi-TF backfill detection, calendar adds timezone)
   - What's unclear: Is this technical debt or intentional design?
   - Recommendation: Document WHY schemas differ, flag as question in variant comparison, but NOT as gap (current state analysis says WORKS)

4. **How to handle "old" directories in script inventory?**
   - What we know: Many old/ subdirectories with archived code exist
   - What's unclear: Include in inventory (comprehensive) or exclude (noise)?
   - Recommendation: Exclude from main inventory, create separate section "Archived Scripts" with counts only, investigate thoroughly if user mentions or git history references

## Sources

### Primary (HIGH confidence)
- [Databricks - Watermarks for Stateful Processing](https://docs.databricks.com/aws/en/ldp/stateful-processing) - Incremental refresh patterns
- [Lucidchart - What is a DFD](https://www.lucidchart.com/pages/data-flow-diagram) - Data flow diagram methodology
- [IBM - Data Flow Diagram Topics](https://www.ibm.com/think/topics/data-flow-diagram) - DFD components and layering
- [Qodo - Gap Analysis in Testing](https://www.qodo.ai/blog/gap-analysis-in-software-testing/) - Severity levels and risk prioritization
- Phase 20 outputs (20-HISTORICAL-REVIEW.md, 20-CURRENT-STATE.md) - Project-specific context and proven patterns

### Secondary (MEDIUM confidence)
- [DEV Community - Multi-Perspective Analysis](https://dev.to/tonegabes/prompt-for-comprehensive-codebase-exploration-and-documentation-from-multi-perspective-analysis-1h55) - Analysis methodology
- [Dataconomy - Data Integrity at Scale](https://dataconomy.com/2026/01/30/data-integrity-at-scale-building-resilient-validation-engines-for-high-stakes-financial-platforms/) - Financial data validation patterns (2026)
- [Airbyte - Full Refresh vs Incremental](https://airbyte.com/data-engineering-resources/full-refresh-vs-incremental-refresh) - Refresh pattern tradeoffs
- [Mermaid Diagrams - AI Best Practices](https://docs.mermaidchart.com/blog/posts/ai-diagram-generators-and-data-visualization-best-practices) - Diagram generation (2025)
- [JIT - Python Code Analysis Tools 2026](https://www.jit.io/resources/appsec-tools/top-python-code-analysis-tools-to-improve-code-quality) - Static analysis tooling

### Tertiary (LOW confidence)
- [GitHub - findimports](https://github.com/mgedmin/findimports) - Import tracing tool
- [GitHub - Scalpel](https://github.com/SMAT-Lab/Scalpel) - Python static analysis framework
- [Refactoring Guru - Abstract Factory](https://refactoring.guru/design-patterns/abstract-factory) - Variant comparison pattern
- [E-Informatyka - AIODC Framework](https://www.e-informatyka.pl/EISEJ/papers/2026/1/2/) - Catastrophic severity level (AI systems)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Python stdlib (ast, importlib) and Mermaid are industry standards
- Architecture patterns: HIGH - Multi-perspective analysis, layered DFDs, severity tiers are proven methodologies
- Pitfalls: HIGH - Derived from Phase 20 findings (EMA migration already done, state schema variation justified)

**Research date:** 2026-02-05
**Valid until:** 30 days (methodologies stable, tools evolve slowly)
