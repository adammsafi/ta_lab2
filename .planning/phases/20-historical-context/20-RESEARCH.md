# Phase 20: Historical Context - Research

**Researched:** 2026-02-05
**Domain:** Software archaeology, historical analysis, documentation inventory
**Confidence:** HIGH

## Summary

Phase 20 requires conducting a comprehensive historical review of GSD phases 1-10 to understand how bar builders and EMAs evolved, inventorying existing documentation to identify leverage-worthy materials, and assessing the current state of features. This is a **read-only analysis phase** - no code changes, purely investigative work before v0.6.0 standardization begins.

The research reveals that this is fundamentally a **software archaeology** task combined with **knowledge transfer documentation** and **technical debt assessment**. The standard approach involves three parallel tracks: (1) Git history mining to reconstruct the evolution narrative, (2) Documentation inventory using multi-dimensional categorization, and (3) Current state assessment using feature-level health metrics.

**Primary recommendation:** Use Git log analysis combined with systematic documentation review and feature-level testing to create a layered historical narrative that serves as the foundation for v0.6.0 planning. Structure output as a hybrid document with thematic sections (Bars, EMAs, State) containing chronological decision records.

## Standard Stack

The established tools for software archaeology and historical analysis:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Git (native) | 2.x+ | VCS history mining | Universal, complete commit history, built-in filtering |
| Python (stdlib) | 3.8+ | Analysis scripts | No dependencies, file/text processing |
| Markdown | CommonMark | Documentation format | Already used project-wide, readable as code |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| PyDriller | 2.x | Git repository mining | If advanced commit analysis needed (50% less code than GitPython) |
| GitPython | 3.x | Programmatic Git access | If repository object manipulation needed |
| pandas | 1.x+ | Data analysis/aggregation | If quantitative metrics analysis needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Git native | PyDriller | PyDriller simpler API but adds dependency; use for complex analysis |
| Manual review | GitEvo (2026) | GitEvo offers CST-level evolution tracking but overkill for document review |
| Markdown | Dedicated tools (MkDocs, Sphinx) | These add build complexity; Markdown sufficient for read-only review |

**Installation:**
```bash
# Optional - only if programmatic analysis needed
pip install pydriller  # For advanced Git mining
pip install gitpython  # For Git object manipulation
pip install pandas     # For metrics aggregation
```

**Note:** This phase can be completed with zero additional dependencies using Git CLI and manual review.

## Architecture Patterns

### Recommended Analysis Structure

```
.planning/phases/20-historical-context/
├── 20-RESEARCH.md           # This file
├── 20-CONTEXT.md            # User decisions (already exists)
├── 20-HISTORICAL-REVIEW.md  # Main output: Evolution narrative + decisions
├── 20-DOCUMENTATION-INVENTORY.md  # Categorized documentation catalog
├── 20-CURRENT-STATE.md      # Feature-level health assessment
└── analysis/                # Optional: Supporting analysis artifacts
    ├── git_timeline.txt     # Commit log excerpts
    ├── decision_log.csv     # Structured decision records
    └── metrics.txt          # Quantitative findings
```

**Rationale:** Hybrid structure balances single-document accessibility with logical separation of concerns. User requested "single or multiple documents at Claude's discretion" - multiple documents prevent overwhelming length while maintaining clear boundaries.

### Pattern 1: Git History Mining

**What:** Extract commit history filtered by file paths, dates, and patterns to reconstruct evolution timeline.

**When to use:** For understanding "how we got here" - what changed, when, and why.

**Example:**
```bash
# Source: Git official documentation
# https://git-scm.com/docs/git-log

# Get commit history for bar-related files
git log --oneline --since="2024-01-01" -- \
  src/ta_lab2/scripts/bars/ \
  src/ta_lab2/features/bars/ \
  sql/ddl/*bar*.sql

# Get detailed commits with diffs for specific date range
git log --stat --since="2024-06-01" --until="2024-08-31" -- \
  src/ta_lab2/features/emas/

# Filter commits by message pattern (decisions, refactors)
git log --grep="refactor\|decision\|migrate" -i --oneline

# Combine filters for targeted analysis
git log --author="Claude" --grep="EMA" --since="2024-09-01" -- \
  src/ta_lab2/features/emas/ \
  docs/features/emas/
```

### Pattern 2: Documentation Inventory with Multi-Dimensional Categorization

**What:** Catalog existing documentation using multiple orthogonal dimensions: topic, quality, source, leverage-worthiness.

**When to use:** For identifying what documentation exists, what's useful, and what's missing.

**Example structure:**
```markdown
# Documentation Inventory

## Matrix: Topic × Quality × Source

| Document | Topic | Quality | Source (Phase) | Leverage-Worthy? | Rationale |
|----------|-------|---------|----------------|------------------|-----------|
| docs/features/bar-implementation.md | Bars | Complete | Pre-GSD | YES | Architecture + implementation details + rationale |
| docs/features/ema-study.md | EMAs | Partial | ~Phase 6 | PARTIAL | Good math, missing state management |
| .planning/phases/06-.../06-RESEARCH.md | Time Model | Complete | Phase 6 | YES | Explains trading sessions design |
| docs/time/ema_model.md | EMAs | Outdated | Pre-GSD | NO | Superseded by later decisions |

## By Topic
### Bars
- **Complete & Leverage-Worthy**: bar-implementation.md, bar-creation.md
- **Partial**: Data Pipeline.md (mixed topics)
- **Missing**: Gap handling decision rationale, quality flag evolution

### EMAs
- **Complete & Leverage-Worthy**: ema-study.md (math), ema-multi-tf-cal-anchor.md (timeframes)
- **Partial**: ema-overview.md (missing state patterns)
- **Missing**: State management standardization decisions

### State Management
- **Complete & Leverage-Worthy**: EMA_STATE_STANDARDIZATION.md
- **Missing**: Bar state patterns, gap state decisions
```

**Criteria for Leverage-Worthy (ALL must apply):**
1. **Explains current architecture** - documents how bars/EMAs work now
2. **Contains implementation details** - validation logic, state patterns, algorithms
3. **Shows design rationale** - why decisions were made, alternatives considered
4. **Has actionable information** - can directly inform v0.6.0 standardization work

### Pattern 3: Feature-Level Current State Assessment

**What:** Assess each feature component as "Works", "Unclear", or "Broken" using three-dimensional health criteria.

**When to use:** For understanding what's solid, what needs investigation, and what needs fixing.

**Example:**
```markdown
# Current State Assessment

## Health Criteria
- **Works** = Functionally correct + Maintainable + Scalable
  - Functionally correct: Scripts run, data updates, calculations accurate
  - Maintainable: Code clear, consistent, documented, safe to modify
  - Scalable: Ready for 50+ assets without major changes
- **Unclear** = Partially works but inconsistent, undocumented, or untested
- **Broken** = Does not work, crashes, produces wrong results

## Bar Builders

| Component | Status | Functional | Maintainable | Scalable | Notes |
|-----------|--------|------------|--------------|----------|-------|
| OHLC calculation | WORKS | ✓ Pass | ✓ Clear | ✓ Ready | Test coverage, clear logic |
| Gap detection | UNCLEAR | ✓ Runs | ✗ Inconsistent | ? Untested | Logic works but implementation varies by script |
| Quality flags | UNCLEAR | ~ Partial | ✗ Undocumented | ? Unknown | Some scripts use, some don't |
| Incremental refresh | BROKEN | ✗ Fails | ✗ Complex | ✗ N/A | Crashes on session boundaries |

## EMAs

| Component | Status | Functional | Maintainable | Scalable | Notes |
|-----------|--------|------------|--------------|----------|-------|
| Single-TF calculation | WORKS | ✓ Accurate | ✓ Clear | ✓ Tested | Solid foundation |
| Multi-TF anchoring | UNCLEAR | ✓ Runs | ~ Partial docs | ? Unknown | Works but rationale unclear |
| State management | UNCLEAR | ~ Varies | ✗ Inconsistent | ✗ No | Multiple competing patterns |
| Data loading | BROKEN | ✗ Wrong source | ✗ Hardcoded | ✗ No | Uses price_histories not bar tables |
```

### Pattern 4: Evolution Narrative Construction

**What:** Thematic organization with timeline noted - tell the story of how bars/EMAs evolved.

**When to use:** For understanding the journey, not just the destination.

**Example:**
```markdown
# Evolution Narrative: Bars

## Timeline Overview
- **Pre-GSD (before Phase 1):** Initial bar creation, ad-hoc scripts
- **Phase 6 (Time Model):** Trading sessions standardization
- **Phase 7 (Feature Pipeline):** Bar validation framework
- **Phase 10 (Release Validation):** Quality flags introduced

## Key Decisions

### Decision: Validate Bars Against Price Histories (Phase 7, ~Aug 2024)
**What was decided:** Add OHLC validation comparing bar tables to raw price_histories.

**Context:** Bar creation was working but no systematic verification. Trust issues.

**Alternatives considered:**
1. Trust bar creation logic without validation
2. Spot-check random samples
3. Comprehensive validation suite (chosen)

**Why chosen:** v0.4.0 needed confidence in data quality. Comprehensive validation catches edge cases.

**Outcome:** ✓ SUCCESS - Caught OHLC calculation bugs, established trust in bar data.

**Impact on v0.6.0:** Validation patterns can extend to gap detection, quality flags. Framework exists.

### Decision: Introduce Gap Flags (Phase 7, ~Aug 2024)
**What was decided:** Add `has_gap` boolean to bar records when sessions have missing data.

**Context:** EMAs failing when data gaps existed. Needed to track data quality.

**Alternatives considered:**
1. Gap detection at query time (too slow)
2. Separate gap tracking table (complex joins)
3. Inline boolean flag (chosen)

**Why chosen:** Simplest, fastest at query time, denormalization acceptable for read-heavy workload.

**Outcome:** ~ PARTIAL - Flag exists but gap detection logic inconsistent across scripts.

**Impact on v0.6.0:** Standardize gap detection logic. Currently each bar builder has variation.
```

### Pattern 5: Layered Detail

**What:** Summary-first structure allowing quick scanning or deep diving.

**When to use:** For documents that serve both executive overview and technical reference needs.

**Example:**
```markdown
# Historical Review

## Executive Summary
[2-3 paragraph overview]
- Bars evolved from ad-hoc scripts to validated pipeline
- EMAs achieved multi-timeframe anchoring but state management inconsistent
- Key gap: no unified state pattern across features

## Detailed Findings

### Bars: Evolution & Decisions
**Summary:** Bar builders progressed from basic OHLC to comprehensive validation framework. Quality flags introduced but inconsistently applied. Gap detection works but implementation varies.

<details>
<summary>Full Detail: Bar Validation Framework (Phase 7)</summary>

[Detailed decision record with code examples, commit references, test results]

</details>

<details>
<summary>Full Detail: Gap Detection Patterns (Phase 7-10)</summary>

[Detailed analysis of gap detection evolution]

</details>
```

### Anti-Patterns to Avoid

- **Confirmation bias archaeology:** Don't search for evidence of specific conclusions. Let evidence drive findings.
- **Analysis paralysis:** Don't get lost in commit-by-commit review. Focus on decision points, inflection points.
- **Present-centric evaluation:** Don't judge past decisions by current knowledge. Assess in historical context.
- **Documentation as truth:** Don't assume documentation is accurate. Verify against code and commit history.
- **Completeness theater:** Don't pad findings to appear thorough. "Couldn't determine X" is valuable.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Git history analysis | Custom commit parser | `git log` with filters | Git's filtering is battle-tested, handles edge cases (merges, rebases, renames) |
| Commit message parsing | Regex on log output | `--grep` with patterns | Git's grep handles multiline, encodings, special chars |
| File history tracking | Manual diff comparison | `git log -- path/to/file` | Git tracks renames, handles binary files |
| Timeline visualization | Custom date aggregator | `git log --since/--until` | Git's date parsing is robust (relative dates, timezones) |
| Quantitative metrics | Manual counting | `git shortlog -s -n` | Built-in aggregation by author, fast |
| Documentation search | Manual grep | Multi-tool approach | Combine `git log`, file glob, content grep |

**Key insight:** Git already contains the complete project history with powerful query capabilities. Use Git's built-in filtering before writing custom analysis code. For this phase, manual review with Git CLI is sufficient.

## Common Pitfalls

### Pitfall 1: Scope Creep into Code Changes
**What goes wrong:** Historical review phase morphs into "let's fix this while we're here."

**Why it happens:** Finding broken features creates temptation to fix immediately.

**How to avoid:**
- Treat this as strictly read-only investigation
- Document findings in "Current State" section with severity
- Defer all fixes to subsequent v0.6.0 phases
- If urgent issue found, create separate issue but don't fix in this phase

**Warning signs:** Opening code files in editor, running tests that modify data, creating new branches.

### Pitfall 2: Git History as Authoritative Source
**What goes wrong:** Trusting commit messages and code comments without verification.

**Why it happens:** Commit messages can be wrong, incomplete, or reflect intent not reality.

**How to avoid:**
- Cross-reference commits with actual code changes (use `--stat` or `--patch`)
- Verify claimed outcomes by testing current code
- Check if documentation matches implementation
- Note contradictions: "Commit says X but code does Y"

**Warning signs:** Accepting commit message at face value, not checking diffs, ignoring code-doc mismatches.

### Pitfall 3: Analysis Paralysis
**What goes wrong:** Getting lost in exhaustive commit-by-commit review, never finishing.

**Why it happens:** 608+ commits since 2024, temptation to be "complete."

**How to avoid:**
- Focus on **decision points** not every commit
- Use `--grep` to find important commits (refactor, decision, migrate, fix)
- Filter by file paths relevant to bars/EMAs
- Time-box analysis: "Phase 1-10 review should take 2-4 hours max"

**Warning signs:** Reading every commit message, analyzing trivial changes, no progress on documentation inventory.

### Pitfall 4: Treating Documentation as Ground Truth
**What goes wrong:** Assuming existing docs accurately reflect current implementation.

**Why it happens:** Documentation often lags code, especially in fast-moving projects.

**How to avoid:**
- **Verify** documentation claims against current code
- Check document creation/modification dates
- Mark docs as "Outdated" if superseded
- Note where docs contradict implementation: "Doc says X, code does Y"

**Warning signs:** Not checking code when reviewing docs, assuming old docs still valid, missing contradictions.

### Pitfall 5: Present-Centric Bias
**What goes wrong:** Judging past decisions harshly based on current knowledge.

**Why it happens:** Hindsight bias - we know now what was unknown then.

**How to avoid:**
- Assess decisions in **historical context**: what was known at the time?
- Distinguish "bad decision with info available" from "good decision, context changed"
- Note when context shifted: "Made sense pre-Phase 6, obsoleted by trading sessions"
- Celebrate learning: "Tried X, learned Y, led to better Z"

**Warning signs:** Criticism without context, ignoring timeline, "why didn't they just..." commentary.

### Pitfall 6: Mixing Gap Identification with Phase Scope
**What goes wrong:** Unclear whether documenting missing docs belongs in Phase 20 or Phase 21.

**Why it happens:** User marked this as "Claude's discretion."

**How to avoid:**
- **Recommendation:** Include gap identification in Phase 20's Documentation Inventory
- Rationale: Can't assess "leverage-worthy" without noting what's missing
- Format: "Missing: [topic] - needed for [purpose]" in inventory
- Clear handoff: Phase 21 can use gap list to plan documentation work

**Warning signs:** Skipping gap analysis entirely, spending time creating docs instead of listing gaps.

### Pitfall 7: Undefined "Unclear" vs "Broken"
**What goes wrong:** Inconsistent feature state categorization.

**Why it happens:** User marked this as "Claude's discretion."

**How to avoid:**
- **Recommendation:** Use crisp definitions:
  - **Works:** All three criteria met (functional + maintainable + scalable)
  - **Unclear:** Works functionally but maintenance/scale uncertain (inconsistent, undocumented, untested)
  - **Broken:** Functional failure (crashes, wrong results, doesn't run)
- Test by asking: "If I needed to modify this tomorrow, what's the risk?"
  - Works: Low risk, safe to modify
  - Unclear: Medium risk, needs investigation before modification
  - Broken: High risk, requires fixing before modification

**Warning signs:** Using categories interchangeably, unable to justify categorization, too many "unclear" items.

## Code Examples

Verified patterns from Git documentation and software archaeology best practices:

### Example 1: Timeline Reconstruction for Specific Feature
```bash
# Source: Git documentation - https://git-scm.com/docs/git-log

# Get chronological evolution of EMA state management
git log --reverse --oneline --since="2024-06-01" -- \
  src/ta_lab2/features/emas/ \
  sql/ddl/*ema*.sql \
  docs/features/emas/

# Output format: <commit-hash> <commit-message>
# Use --reverse to see chronologically (oldest first)
# Add --stat to see which files changed in each commit
# Add --patch to see actual code changes

# Example analysis workflow:
# 1. Run command, save to git_timeline.txt
# 2. Identify decision points (big commits, "refactor", "decision" in message)
# 3. For each decision point, run git show <hash> to see details
# 4. Extract: what changed, why (from message/PR), outcome (from later commits)
```

### Example 2: Finding Key Decisions by Pattern
```bash
# Source: Git documentation - https://git-scm.com/docs/git-log

# Find commits that likely document decisions
git log --grep="decision\|refactor\|standardize\|migrate" -i \
  --since="2024-01-01" --oneline

# Find commits that introduce new patterns
git log --grep="introduce\|add.*pattern\|new.*approach" -i \
  --since="2024-01-01" --oneline

# Find commits that fix broken features (failures)
git log --grep="fix\|broken\|bug" -i \
  --since="2024-01-01" --oneline -- \
  src/ta_lab2/features/emas/ \
  src/ta_lab2/scripts/bars/

# Combine multiple patterns
git log --grep="EMA\|ema" --grep="state\|State" --all-match \
  --since="2024-06-01" --oneline
```

### Example 3: Cross-Referencing Planning Docs with Implementation
```bash
# Source: Git documentation - https://git-scm.com/docs/git-log

# Find commits related to Phase 7 (Feature Pipeline)
git log --oneline --since="2024-07-01" --until="2024-09-30" -- \
  .planning/phases/07-ta_lab2-feature-pipeline/

# For each PLAN file, find when it was created and executed
# Example: Find implementation commits following a plan
PLAN_DATE=$(git log -1 --format=%ai -- .planning/phases/07-.../07-01-PLAN.md)
git log --since="$PLAN_DATE" --until="$PLAN_DATE + 2 weeks" -- \
  src/ta_lab2/features/

# This reveals: Did implementation follow plan? What diverged?
```

### Example 4: Author-Specific Evolution Tracking
```bash
# Source: Git documentation - https://git-scm.com/docs/git-log

# Track how a feature evolved across different authors
git shortlog -s -n --since="2024-06-01" -- src/ta_lab2/features/emas/
# Output: commit count by author for EMA feature

# See detailed commits by specific author
git log --author="Claude" --oneline --since="2024-06-01" -- \
  src/ta_lab2/features/emas/

# Cross-author pattern: Who worked on what, when?
# Useful for understanding collaboration, knowledge distribution
```

### Example 5: Documentation Inventory with File Metadata
```bash
# Source: Standard Unix/Git tools

# List all markdown docs with modification dates
find docs/ -name "*.md" -type f -exec ls -lh {} \; | \
  awk '{print $9, $6, $7, $8}' | sort

# For each doc, check when it was last modified
for doc in docs/features/emas/*.md; do
  echo "=== $doc ==="
  git log -1 --format="%ai - %s" -- "$doc"
done

# This reveals: Which docs are stale? When were they last updated?
```

### Example 6: Multi-Dimensional Documentation Analysis (Python)
```python
# Source: Software archaeology best practices
# Optional: Use if systematic categorization needed

import os
from pathlib import Path
from datetime import datetime

def analyze_documentation(docs_root="docs/"):
    """Analyze documentation with multi-dimensional categorization."""

    inventory = []

    for md_file in Path(docs_root).rglob("*.md"):
        # Get file metadata
        stat = md_file.stat()
        modified = datetime.fromtimestamp(stat.st_mtime)
        size = stat.st_size

        # Categorize by directory (topic)
        topic = md_file.parent.name

        # Read content for quality assessment
        content = md_file.read_text(encoding='utf-8')

        # Heuristic quality indicators
        has_code_examples = "```" in content
        has_diagrams = "graph" in content or "![" in content
        word_count = len(content.split())

        # Quality score (simple heuristic)
        quality = "Unknown"
        if word_count > 500 and has_code_examples:
            quality = "Complete"
        elif word_count > 200:
            quality = "Partial"
        elif word_count < 100:
            quality = "Stub"

        inventory.append({
            'path': str(md_file),
            'topic': topic,
            'quality': quality,
            'modified': modified.isoformat()[:10],
            'size': size,
            'word_count': word_count,
            'has_code': has_code_examples,
            'has_diagrams': has_diagrams
        })

    return inventory

# Usage
if __name__ == "__main__":
    docs = analyze_documentation()

    # Group by topic
    by_topic = {}
    for doc in docs:
        topic = doc['topic']
        if topic not in by_topic:
            by_topic[topic] = []
        by_topic[topic].append(doc)

    # Print inventory
    for topic, docs_list in sorted(by_topic.items()):
        print(f"\n## {topic}")
        for doc in sorted(docs_list, key=lambda x: x['modified'], reverse=True):
            print(f"  - {doc['path']} [{doc['quality']}] - {doc['modified']}")
```

### Example 7: Current State Testing Pattern
```bash
# Source: Software project health assessment best practices

# Feature-level testing for current state assessment
# Test bars: Do they work?

# 1. Functional correctness: Run bar builder
python -m src.ta_lab2.scripts.bars.build_cmc_bars_1d

# 2. Check results: Do OHLC values match price_histories?
psql -d ta_lab2 -c "
SELECT
  COUNT(*) as total_bars,
  COUNT(CASE WHEN has_gap THEN 1 END) as gap_count,
  MAX(bar_datetime) as latest_bar
FROM cmc_price_bars_1d
WHERE asset_id = 1;
"

# 3. Maintainability: Can we understand the code?
# - Open build_cmc_bars_1d.py
# - Check: Clear function names? Documented? Consistent style?
# - Manual review, subjective but systematic

# 4. Scalability: Will it handle 50 assets?
# - Check: Hard-coded asset IDs? O(n²) queries? Memory issues?
# - Code review for anti-patterns

# Result: "WORKS" if all pass, "UNCLEAR" if partial, "BROKEN" if fails
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual code review | Software archaeology with Git mining | 2015+ | Systematic, repeatable, less bias |
| Single-document handoff | Multi-dimensional documentation inventory | 2020+ | Better categorization, gap identification |
| Pass/fail assessment | Three-tier health metrics (functional/maintainable/scalable) | 2020+ | Granular, actionable insights |
| Chronological narrative | Thematic with timeline noted | 2024+ | Easier to navigate, better for decision lookup |
| Plain text logs | Layered detail with collapsible sections | 2025+ (Markdown features) | Scannable summaries, deep-dive details |
| VR archaeology (GitEvo 2024) | Emerging for complex systems | 2024-2026 | Overkill for this project, watch for future |

**Recent innovations:**
- **GitEvo (2026):** Multi-language CST-level evolution tracking - very new, powerful but complex
- **Layered documentation:** Summary + collapsible details pattern from 2025+ best practices
- **Multi-dimensional categorization:** Topic × Quality × Source matrix approach gaining traction

**Deprecated/outdated:**
- Single "README.txt" handoff documents (too coarse)
- Purely chronological narratives (hard to navigate)
- Binary good/bad assessments (not actionable)
- Assumptions that documentation is current (verify against code)

## Open Questions

Things that couldn't be fully resolved:

1. **Optimal granularity for decision records**
   - What we know: User wants "decision-level detail", not just summaries
   - What's unclear: How deep? Every minor refactor or just architectural decisions?
   - Recommendation: Focus on decisions that impact v0.6.0 standardization. If decision doesn't inform standardization, summary sufficient.

2. **Cross-referencing value**
   - What we know: User marked as "Claude's discretion"
   - What's unclear: Do benefits (navigability) outweigh costs (maintenance)?
   - Recommendation: Use relative links sparingly for high-value connections (e.g., "Decision X led to Decision Y"). Avoid creating web of links that break.

3. **Phase 20 vs Phase 21 boundary for gaps**
   - What we know: Phase 20 is historical review, Phase 21 is documentation work
   - What's unclear: Should Phase 20 identify missing docs or defer entirely?
   - Recommendation: Phase 20 identifies gaps in inventory ("Missing: [topic]"), Phase 21 fills them. Clear handoff.

4. **Quantitative vs qualitative analysis**
   - What we know: Need to assess current state, understand evolution
   - What's unclear: Are commit counts, churn metrics, complexity scores valuable here?
   - Recommendation: Primarily qualitative (narrative, decisions). Use quantitative sparingly (e.g., "12 commits touched gap detection logic" establishes evolution scope).

## Sources

### Primary (HIGH confidence)
- [Git official documentation](https://git-scm.com/docs/git-log) - Command reference and filtering options
- [Architecture Decision Records (ADRs) - adr.github.io](https://adr.github.io/) - ADR format and retrospective analysis
- [Microsoft Azure Well-Architected Framework - ADR](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record) - ADR process and maintenance
- [Working Effectively with Legacy Code concepts](https://understandlegacycode.com/) - Software archaeology techniques
- [GitEvo: Code Evolution Analysis (2026)](https://arxiv.org/html/2602.00410v1) - Recent Git mining research

### Secondary (MEDIUM confidence)
- [Software Archaeology - Lattix](https://www.lattix.com/software-archaeology-software-architectural-recovery-for-legacy-code/) - Architectural recovery methodology
- [Project Handover Documentation Checklist - Praxent](https://praxent.com/blog/software-handover-documentation-checklist) - Knowledge transfer best practices
- [Technical Debt Assessment - Code Climate](https://codeclimate.com/blog/10-point-technical-debt-assessment) - Current state assessment patterns
- [Git History Visualization - Gitready](https://gitready.com/visualizing-commit-history-and-analyzing-project-evolution-with-git/) - Timeline visualization techniques
- [Markdown Documentation Best Practices 2026](https://medium.com/@rosgluk/building-a-markdown-based-documentation-system-72bef3cb1db3) - Structure and organization

### Tertiary (LOW confidence - flagged for validation)
- Various blog posts on retrospectives and refactoring patterns - concepts sound but need verification against official sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Git is universally used, Markdown is project standard, Python is installed
- Architecture patterns: HIGH - Based on established software archaeology and Git documentation practices, verified with official sources
- Pitfalls: HIGH - Based on common software archaeology challenges documented across multiple authoritative sources
- Code examples: HIGH - All examples use official Git CLI documented in git-scm.com
- Tools (PyDriller/GitEvo): MEDIUM - Recent tools with limited production track record, optional for this phase

**Research date:** 2026-02-05
**Valid until:** ~2026-03-05 (30 days - stable domain, best practices evolve slowly)

**Key findings summary:**
1. This is a **read-only analysis phase** - no code changes, purely investigative
2. **Git native tools** are sufficient - no additional dependencies required
3. **Three parallel tracks**: Git history mining + documentation inventory + current state assessment
4. **Hybrid output structure**: Multiple documents prevent overwhelming length while maintaining clarity
5. **Layered detail**: Summary-first with collapsible deep dives serves both scanning and reference needs
6. **Multi-dimensional categorization**: Topic × Quality × Source × Leverage-worthiness for documentation inventory
7. **Three-tier health metrics**: Functional × Maintainable × Scalable for current state assessment
8. **Evolution narrative**: Thematic sections with timeline noted, decision-level detail with context + rationale + outcome

**Ready for planning:** This research provides sufficient methodology and tooling guidance to create detailed PLAN files for Phase 20 execution.
