"""Unified runner for all analysis tools.

Runs tree structure, function map, and script summaries in one command,
writing outputs to a timestamped artifacts directory.

Usage:
    # Run everything
    python -m ta_lab2.tools.data_tools.analysis --all

    # Run everything with LLM enrichment
    python -m ta_lab2.tools.data_tools.analysis --all --enrich

    # Run only tree structure
    python -m ta_lab2.tools.data_tools.analysis --tree-only

    # Run only function map
    python -m ta_lab2.tools.data_tools.analysis --function-map-only

    # Run only script summaries
    python -m ta_lab2.tools.data_tools.analysis --script-summary-only

    # Custom output directory
    python -m ta_lab2.tools.data_tools.analysis --all --output-dir artifacts/custom
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def main() -> int:
    """CLI entry point for unified analysis runner."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Unified analysis tool runner for ta_lab2 codebase."
    )

    # What to run
    ap.add_argument("--all", action="store_true", help="Run all analysis tools")
    ap.add_argument("--tree-only", action="store_true", help="Run tree structure only")
    ap.add_argument(
        "--function-map-only", action="store_true", help="Run function map only"
    )
    ap.add_argument(
        "--script-summary-only",
        action="store_true",
        help="Run script summaries only",
    )

    # Common options
    ap.add_argument("--root", default=".", help="Repository root directory")
    ap.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: artifacts/YYYYMMDD/)",
    )
    ap.add_argument("--package", default="ta_lab2", help="Package name for API map")

    # Passthrough to function map
    ap.add_argument("--enrich", action="store_true", help="Enable LLM enrichment")
    ap.add_argument("--model", default="gpt-4o-mini", help="Model for LLM enrichment")
    ap.add_argument(
        "--batch-size", type=int, default=15, help="Functions per LLM batch"
    )
    ap.add_argument(
        "--enrich-dry-run",
        action="store_true",
        help="Show what would be enriched without API calls",
    )
    ap.add_argument(
        "--simple", action="store_true", help="Simple function map output (no purpose)"
    )
    ap.add_argument(
        "--include", nargs="*", default=[], help="Include globs for Python files"
    )
    ap.add_argument(
        "--exclude", nargs="*", default=None, help="Exclude globs for Python files"
    )

    # Diff
    ap.add_argument("--diff", type=str, default=None, help="Previous CSV for diff mode")

    args = ap.parse_args()

    # Determine what to run
    run_tree = args.all or args.tree_only
    run_fmap = args.all or args.function_map_only
    run_scripts = args.all or args.script_summary_only

    # Default to --all if nothing specified
    if not any([run_tree, run_fmap, run_scripts]):
        run_tree = run_fmap = run_scripts = True

    # Determine output directory
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        datestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        out_dir = Path("artifacts") / datestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, object] = {}

    if run_tree:
        from ta_lab2.tools.data_tools.analysis.tree_structure import (
            generate_tree_structure,
        )

        logger.info("Generating tree structure...")
        generate_tree_structure(
            args.root,
            output_prefix="structure",
            pkg_name=args.package,
            generate_api_map=True,
            output_dir=str(out_dir),
        )
        results["tree"] = "done"

    if run_fmap:
        from ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose import (
            generate_diff_report,
            generate_function_map_with_purpose,
        )

        logger.info("Generating function map...")
        fmap_output = out_dir / "function_map.csv"
        count = generate_function_map_with_purpose(
            root=args.root,
            output=str(fmap_output),
            include_globs=args.include,
            exclude_globs=args.exclude,
            simple=args.simple,
            enrich=args.enrich,
            model=args.model,
            batch_size=args.batch_size,
            enrich_dry_run=args.enrich_dry_run,
        )
        results["function_map"] = f"{count} rows"

        # Diff report
        if args.diff:
            diff_result = generate_diff_report(
                current_csv=fmap_output,
                previous_csv=Path(args.diff),
                output=out_dir / "diff_report.md",
            )
            results["diff"] = (
                f"+{diff_result['added']} -{diff_result['removed']} "
                f"~{diff_result['changed']}"
            )

    if run_scripts:
        from ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose import (
            generate_script_summaries,
        )

        logger.info("Generating script summaries...")
        sc = generate_script_summaries(
            root=args.root,
            output_csv=str(out_dir / "script_summary.csv"),
            output_md=str(out_dir / "script_summary.md"),
            include_globs=args.include,
            exclude_globs=args.exclude,
        )
        results["script_summary"] = f"{sc} modules"

    print(f"\nAll outputs written to: {out_dir}")
    for k, v in results.items():
        print(f"  {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
