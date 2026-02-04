"""Duplicate detection with three-tier similarity thresholds.

Detects duplicate/similar functions using difflib.SequenceMatcher:
- 95%+ (exact): Flag for consolidation, recommend canonical version
- 85-95% (very_similar): Flag for review, assess if variation meaningful
- 70-85% (related): Document in appendix, informational only

Usage:
    from ta_lab2.tools.ai_orchestrator.memory.similarity import (
        detect_duplicates,
        suggest_canonical
    )

    # Detect duplicates across extracted functions
    report = detect_duplicates(functions)
    print(report.markdown_summary())

    # Get canonical version suggestion for exact duplicates
    for dup in report.exact_duplicates:
        suggestion = suggest_canonical(dup)
"""
import difflib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .indexing import FunctionInfo


class SimilarityTier(Enum):
    """Classification tiers for function similarity."""

    EXACT = "exact"  # 95%+
    VERY_SIMILAR = "very_similar"  # 85-95%
    RELATED = "related"  # 70-85%


@dataclass
class SimilarityResult:
    """Result of comparing two functions for similarity.

    Attributes:
        func_a_name: First function name
        func_a_file: First function file path
        func_a_lineno: First function line number
        func_b_name: Second function name
        func_b_file: Second function file path
        func_b_lineno: Second function line number
        similarity: Similarity ratio [0, 1]
        tier: Classification tier
        func_a_source: First function source code (for canonical suggestion)
        func_b_source: Second function source code
    """

    func_a_name: str
    func_a_file: str
    func_a_lineno: int
    func_b_name: str
    func_b_file: str
    func_b_lineno: int
    similarity: float
    tier: SimilarityTier
    func_a_source: str = ""
    func_b_source: str = ""


@dataclass
class CanonicalSuggestion:
    """Suggestion for which version to keep in duplicate pair.

    Attributes:
        canonical_file: File path of recommended canonical version
        canonical_function: Name of recommended canonical function
        reason: Human-readable explanation for recommendation
        remove_file: File path of suggested removal candidate
        remove_function: Name of function to remove
        confidence: Confidence level (high, medium, low)
    """

    canonical_file: str
    canonical_function: str
    reason: str
    remove_file: str
    remove_function: str
    confidence: str


@dataclass
class DuplicateReport:
    """Report of duplicate/similar functions found in codebase.

    Attributes:
        exact_duplicates: Functions with 95%+ similarity
        very_similar: Functions with 85-95% similarity
        related: Functions with 70-85% similarity
        canonical_suggestions: Recommendations for exact duplicates
        comparison_count: Total pairs compared
        duration_seconds: Time taken for analysis
    """

    exact_duplicates: List[SimilarityResult] = field(default_factory=list)
    very_similar: List[SimilarityResult] = field(default_factory=list)
    related: List[SimilarityResult] = field(default_factory=list)
    canonical_suggestions: List[CanonicalSuggestion] = field(default_factory=list)
    comparison_count: int = 0
    duration_seconds: float = 0.0

    def markdown_summary(self) -> str:
        """Generate markdown summary for VALIDATION.md.

        Returns:
            Markdown-formatted report with tables for each tier
        """
        lines = ["# Duplicate Function Detection Report", ""]

        # Summary stats
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Comparisons:** {self.comparison_count:,}")
        lines.append(f"- **Duration:** {self.duration_seconds:.2f}s")
        lines.append(f"- **Exact duplicates (95%+):** {len(self.exact_duplicates)}")
        lines.append(f"- **Very similar (85-95%):** {len(self.very_similar)}")
        lines.append(f"- **Related (70-85%):** {len(self.related)}")
        lines.append("")

        # Exact duplicates with canonical suggestions
        if self.exact_duplicates:
            lines.append("## Exact Duplicates (95%+ similarity)")
            lines.append("")
            lines.append(
                "These functions are nearly identical and should be consolidated."
            )
            lines.append("")
            lines.append(self._format_tier(self.exact_duplicates))
            lines.append("")

            if self.canonical_suggestions:
                lines.append("### Canonical Version Recommendations")
                lines.append("")
                lines.append("| Keep | Remove | Reason | Confidence |")
                lines.append("|------|--------|--------|------------|")
                for sug in self.canonical_suggestions:
                    keep_loc = f"{sug.canonical_function} ({sug.canonical_file})"
                    remove_loc = f"{sug.remove_function} ({sug.remove_file})"
                    lines.append(
                        f"| {keep_loc} | {remove_loc} | {sug.reason} | {sug.confidence} |"
                    )
                lines.append("")
        else:
            lines.append("## Exact Duplicates (95%+ similarity)")
            lines.append("")
            lines.append("No exact duplicates found.")
            lines.append("")

        # Very similar
        if self.very_similar:
            lines.append("## Very Similar Functions (85-95% similarity)")
            lines.append("")
            lines.append(
                "These functions are highly similar. Review to determine if variations are meaningful."
            )
            lines.append("")
            lines.append(self._format_tier(self.very_similar, limit=20))
            lines.append("")
        else:
            lines.append("## Very Similar Functions (85-95% similarity)")
            lines.append("")
            lines.append("No very similar functions found.")
            lines.append("")

        # Related
        if self.related:
            lines.append("## Related Functions (70-85% similarity)")
            lines.append("")
            lines.append(
                "These functions share patterns but have distinct implementations. Informational only."
            )
            lines.append("")
            if len(self.related) > 50:
                lines.append(f"*Showing first 50 of {len(self.related)} related pairs*")
                lines.append("")
            lines.append(self._format_tier(self.related, limit=50))
            lines.append("")
        else:
            lines.append("## Related Functions (70-85% similarity)")
            lines.append("")
            lines.append("No related functions found.")
            lines.append("")

        return "\n".join(lines)

    def _format_tier(
        self, pairs: List[SimilarityResult], limit: Optional[int] = None
    ) -> str:
        """Format similarity results as markdown table.

        Args:
            pairs: List of similarity results to format
            limit: Maximum number of pairs to include (None = all)

        Returns:
            Markdown table string
        """
        lines = ["| Function A | Function B | Similarity |"]
        lines.append("|------------|------------|------------|")

        display_pairs = pairs[:limit] if limit else pairs

        for pair in display_pairs:
            func_a = f"{pair.func_a_name} ({pair.func_a_file}:{pair.func_a_lineno})"
            func_b = f"{pair.func_b_name} ({pair.func_b_file}:{pair.func_b_lineno})"
            similarity = f"{pair.similarity:.1%}"
            lines.append(f"| {func_a} | {func_b} | {similarity} |")

        return "\n".join(lines)


def compute_similarity(source_a: str, source_b: str) -> float:
    """Compute similarity ratio between two function source strings.

    Uses difflib.SequenceMatcher for text-based similarity comparison.

    Args:
        source_a: First function source code
        source_b: Second function source code

    Returns:
        Similarity ratio in [0, 1] where 1.0 is identical

    Example:
        >>> src1 = "def foo():\\n    return 42"
        >>> src2 = "def bar():\\n    return 42"
        >>> similarity = compute_similarity(src1, src2)
        >>> similarity > 0.8  # Very similar despite different names
        True
    """
    matcher = difflib.SequenceMatcher(None, source_a, source_b)
    return matcher.ratio()


def classify_tier(similarity: float) -> Optional[SimilarityTier]:
    """Classify similarity score into tier.

    Args:
        similarity: Similarity ratio [0, 1]

    Returns:
        SimilarityTier if >= 0.70, None if below threshold

    Example:
        >>> classify_tier(0.96)
        <SimilarityTier.EXACT: 'exact'>
        >>> classify_tier(0.88)
        <SimilarityTier.VERY_SIMILAR: 'very_similar'>
        >>> classify_tier(0.65)
        None
    """
    if similarity >= 0.95:
        return SimilarityTier.EXACT
    elif similarity >= 0.85:
        return SimilarityTier.VERY_SIMILAR
    elif similarity >= 0.70:
        return SimilarityTier.RELATED
    else:
        return None


def suggest_canonical(result: SimilarityResult) -> CanonicalSuggestion:
    """Suggest which function should be canonical in duplicate pair.

    Heuristics (in priority order):
    1. Prefer function WITH docstring over without
    2. Prefer function WITH type hints over without
    3. Prefer function in src/ over tests/
    4. Prefer function in core modules (features/, signals/) over utils/scripts/
    5. Prefer shorter file path (less deeply nested)
    6. Prefer alphabetically first if all else equal

    Args:
        result: SimilarityResult for pair to analyze

    Returns:
        CanonicalSuggestion with recommended keep/remove and reasoning
    """
    # Score each function (higher = better canonical candidate)
    score_a = 0
    score_b = 0
    reasons = []

    # 1. Docstring presence (weight: 3)
    has_docstring_a = '"""' in result.func_a_source or "'''" in result.func_a_source
    has_docstring_b = '"""' in result.func_b_source or "'''" in result.func_b_source

    if has_docstring_a and not has_docstring_b:
        score_a += 3
        reasons.append("has docstring")
    elif has_docstring_b and not has_docstring_a:
        score_b += 3
        reasons.append("has docstring")

    # 2. Type hints presence (weight: 2)
    has_hints_a = (
        "->" in result.func_a_source or ":" in result.func_a_source.split(")")[0]
    )
    has_hints_b = (
        "->" in result.func_b_source or ":" in result.func_b_source.split(")")[0]
    )

    if has_hints_a and not has_hints_b:
        score_a += 2
        reasons.append("has type hints")
    elif has_hints_b and not has_hints_a:
        score_b += 2
        reasons.append("has type hints")

    # 3. Location: src/ preferred over tests/ (weight: 2)
    in_src_a = "/src/" in result.func_a_file or "\\src\\" in result.func_a_file
    in_src_b = "/src/" in result.func_b_file or "\\src\\" in result.func_b_file
    in_tests_a = "/tests/" in result.func_a_file or "\\tests\\" in result.func_a_file
    in_tests_b = "/tests/" in result.func_b_file or "\\tests\\" in result.func_b_file

    if in_src_a and in_tests_b:
        score_a += 2
        reasons.append("in src/ not tests/")
    elif in_src_b and in_tests_a:
        score_b += 2
        reasons.append("in src/ not tests/")

    # 4. Core module preference (weight: 1)
    core_modules = ["features", "signals", "pipelines", "regimes"]
    is_core_a = any(
        f"/{mod}/" in result.func_a_file or f"\\{mod}\\" in result.func_a_file
        for mod in core_modules
    )
    is_core_b = any(
        f"/{mod}/" in result.func_b_file or f"\\{mod}\\" in result.func_b_file
        for mod in core_modules
    )

    if is_core_a and not is_core_b:
        score_a += 1
        reasons.append("in core module")
    elif is_core_b and not is_core_a:
        score_b += 1
        reasons.append("in core module")

    # 5. Shorter path (less nested) (weight: 1)
    depth_a = result.func_a_file.count("/") + result.func_a_file.count("\\")
    depth_b = result.func_b_file.count("/") + result.func_b_file.count("\\")

    if depth_a < depth_b:
        score_a += 1
        reasons.append("less deeply nested")
    elif depth_b < depth_a:
        score_b += 1
        reasons.append("less deeply nested")

    # 6. Alphabetical tiebreaker
    if score_a == score_b:
        if result.func_a_file < result.func_b_file:
            score_a += 0.5
            reasons.append("alphabetically first")
        else:
            score_b += 0.5
            reasons.append("alphabetically first")

    # Determine confidence
    score_diff = abs(score_a - score_b)
    if score_diff >= 3:
        confidence = "high"
    elif score_diff >= 1:
        confidence = "medium"
    else:
        confidence = "low"

    # Select canonical
    if score_a >= score_b:
        return CanonicalSuggestion(
            canonical_file=result.func_a_file,
            canonical_function=result.func_a_name,
            reason=", ".join(reasons) if reasons else "identical functions",
            remove_file=result.func_b_file,
            remove_function=result.func_b_name,
            confidence=confidence,
        )
    else:
        return CanonicalSuggestion(
            canonical_file=result.func_b_file,
            canonical_function=result.func_b_name,
            reason=", ".join(reasons) if reasons else "identical functions",
            remove_file=result.func_a_file,
            remove_function=result.func_a_name,
            confidence=confidence,
        )


def detect_duplicates(
    functions: List[FunctionInfo], min_threshold: float = 0.70
) -> DuplicateReport:
    """Detect duplicate and similar functions across codebase.

    Compares all function pairs using difflib.SequenceMatcher and classifies
    by similarity tier. Generates canonical suggestions for exact duplicates.

    Args:
        functions: List of FunctionInfo objects to analyze
        min_threshold: Minimum similarity to report (default: 0.70)

    Returns:
        DuplicateReport with categorized duplicates and recommendations

    Example:
        >>> from ta_lab2.tools.ai_orchestrator.memory.indexing import extract_functions
        >>> from pathlib import Path
        >>> functions = extract_functions(Path("module.py"))
        >>> report = detect_duplicates(functions)
        >>> print(f"Found {len(report.exact_duplicates)} exact duplicates")
    """
    start_time = time.time()

    exact_duplicates = []
    very_similar = []
    related = []
    comparison_count = 0

    # Compare all pairs
    n = len(functions)
    for i in range(n):
        for j in range(i + 1, n):
            func_a = functions[i]
            func_b = functions[j]

            # Skip comparing function to itself
            if (
                func_a.file_path == func_b.file_path
                and func_a.name == func_b.name
                and func_a.lineno == func_b.lineno
            ):
                continue

            # Skip very short functions to avoid false positives
            if len(func_a.source) < 20 or len(func_b.source) < 20:
                continue

            # Compute similarity
            similarity = compute_similarity(func_a.source, func_b.source)
            comparison_count += 1

            # Classify and store if above threshold
            tier = classify_tier(similarity)
            if tier is None:
                continue

            result = SimilarityResult(
                func_a_name=func_a.name,
                func_a_file=func_a.file_path,
                func_a_lineno=func_a.lineno,
                func_b_name=func_b.name,
                func_b_file=func_b.file_path,
                func_b_lineno=func_b.lineno,
                similarity=similarity,
                tier=tier,
                func_a_source=func_a.source,
                func_b_source=func_b.source,
            )

            if tier == SimilarityTier.EXACT:
                exact_duplicates.append(result)
            elif tier == SimilarityTier.VERY_SIMILAR:
                very_similar.append(result)
            elif tier == SimilarityTier.RELATED:
                related.append(result)

    # Generate canonical suggestions for exact duplicates
    canonical_suggestions = [suggest_canonical(dup) for dup in exact_duplicates]

    duration = time.time() - start_time

    return DuplicateReport(
        exact_duplicates=exact_duplicates,
        very_similar=very_similar,
        related=related,
        canonical_suggestions=canonical_suggestions,
        comparison_count=comparison_count,
        duration_seconds=duration,
    )


if __name__ == "__main__":
    from pathlib import Path

    from .indexing import extract_functions

    # Test similarity computation
    source_a = '''def foo(x: int) -> int:
    """Return x squared."""
    return x * x
'''
    source_b = '''def bar(x: int) -> int:
    """Return x squared."""
    return x * x
'''
    source_c = '''def baz(x: int) -> int:
    """Return x cubed."""
    return x * x * x
'''

    print("Similarity tests:")
    print(
        f"  foo vs bar (identical logic): {compute_similarity(source_a, source_b):.2%}"
    )
    print(
        f"  foo vs baz (different logic): {compute_similarity(source_a, source_c):.2%}"
    )

    # Test on actual codebase (memory module)
    memory_dir = Path(__file__).parent
    all_functions = []
    for py_file in memory_dir.glob("*.py"):
        all_functions.extend(extract_functions(py_file))

    print(f"\nAnalyzing {len(all_functions)} functions from memory module...")
    report = detect_duplicates(all_functions)

    print("\nDuplicate Detection Report:")
    print(f"  Comparisons: {report.comparison_count}")
    print(f"  Duration: {report.duration_seconds:.2f}s")
    print(f"  Exact duplicates (95%+): {len(report.exact_duplicates)}")
    print(f"  Very similar (85-95%): {len(report.very_similar)}")
    print(f"  Related (70-85%): {len(report.related)}")

    if report.exact_duplicates:
        print("\n  Exact duplicates found:")
        for dup in report.exact_duplicates[:3]:
            print(
                f"    - {dup.func_a_name} <-> {dup.func_b_name}: {dup.similarity:.1%}"
            )
