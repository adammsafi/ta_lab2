"""Convert ProjectTT Excel files to Markdown tables for plan 13-04.

This script systematically converts priority Excel files from ProjectTT
to Markdown tables in the appropriate docs/ directories.
"""
import json
import logging
from pathlib import Path
from typing import Dict

from src.ta_lab2.tools.docs.convert_excel import convert_excel_to_markdown

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_inventory(inventory_path: Path) -> Dict:
    """Load the ProjectTT inventory JSON."""
    with open(inventory_path, "r", encoding="utf-8") as f:
        return json.load(f)


def convert_priority_files(inventory: Dict, dry_run: bool = False) -> Dict[str, Dict]:
    """Convert priority Excel files to Markdown.

    Returns dict mapping source_path -> conversion_result
    """
    results = {}

    # Define priority conversions with target paths
    conversions = [
        # Architecture files
        {
            "source": "Schemas_20260114.xlsx",
            "target": Path("docs/architecture/schemas.md"),
            "category": "architecture",
            "priority": 1,
        },
        {
            "source": "db_schemas_keys.xlsx",
            "target": Path("docs/architecture/db-keys.md"),
            "category": "architecture",
            "priority": 1,
        },
        # Feature files - EMAs
        {
            "source": "EMA Study.xlsx",
            "target": Path("docs/features/emas/ema-study.md"),
            "category": "architecture",
            "priority": 1,
        },
        {
            "source": "EMA_Alpha_LUT_Comparisson.xlsx",
            "target": Path("docs/features/emas/ema-alpha-comparison.md"),
            "category": "reference",
            "priority": 2,
        },
        # Reference files
        {
            "source": "assets_exchanges_info.xlsx",
            "target": Path("docs/reference/exchanges-info.md"),
            "category": "reference",
            "priority": 2,
        },
        {
            "source": "ta_lab2_TimeFramesChart_20251111.xlsx",
            "target": Path("docs/reference/timeframes-chart.md"),
            "category": "reference",
            "priority": 3,
        },
        {
            "source": "new_12wk_plan_table.xlsx",
            "target": Path("docs/planning/12-week-plan-table.md"),
            "category": "planning",
            "priority": 3,
        },
    ]

    # Find files in inventory
    all_files = []
    for category_files in inventory["by_category"].values():
        all_files.extend(category_files)

    # Convert each file
    for conv in conversions:
        # Find file in inventory
        source_file = None
        for file_info in all_files:
            if file_info["name"] == conv["source"]:
                source_file = file_info
                break

        if not source_file:
            logger.warning(f"File not found in inventory: {conv['source']}")
            results[conv["source"]] = {"error": "Not found in inventory"}
            continue

        source_path = Path(source_file["path"])
        target_path = conv["target"]

        if not source_path.exists():
            logger.warning(f"Source file does not exist: {source_path}")
            results[conv["source"]] = {"error": "Source file not found"}
            continue

        logger.info(f"Converting {conv['source']} -> {target_path}")

        # Convert
        result = convert_excel_to_markdown(
            excel_path=source_path, output_path=target_path, dry_run=dry_run
        )

        results[conv["source"]] = result

        if "error" in result:
            logger.error(f"Failed to convert {conv['source']}: {result['error']}")
        else:
            logger.info(f"  ✓ Converted {result['sheets_converted']} sheets")

    return results


def handle_complex_files(inventory: Dict, dry_run: bool = False) -> Dict[str, str]:
    """Handle complex Excel files with fallback strategies.

    Returns dict mapping source_name -> quality_status
    """
    quality_tracking = {}

    # TV_DataExportPlay.xlsx - likely data export, skip
    tv_export = None
    for file_info in inventory["by_category"]["reference"]:
        if file_info["name"] == "TV_DataExportPlay.xlsx":
            tv_export = file_info
            break

    if tv_export:
        logger.info(
            "Skipping TV_DataExportPlay.xlsx (1.5MB data export, not documentation)"
        )
        quality_tracking["TV_DataExportPlay.xlsx"] = "skipped - data export"

    # compare_3_emas'.xlsx - complex comparison
    compare_3 = None
    for file_info in inventory["by_category"]["reference"]:
        if file_info["name"] == "compare_3_emas'.xlsx":
            compare_3 = file_info
            break

    if compare_3:
        logger.info(
            "Skipping compare_3_emas'.xlsx (complex comparison, likely has charts)"
        )
        quality_tracking["compare_3_emas'.xlsx"] = "skipped - complex charts"

    # github_code_frequency.xlsx, time_scrap.xlsx - minor files
    for skip_file in [
        "github_code_frequency.xlsx",
        "time_scrap.xlsx",
        "ChatGPT_Convos_Manually_Desc.xlsx",
        "ChatGPT_Convos_Manually_Desc2.xlsx",
    ]:
        logger.info(f"Skipping {skip_file} (low priority tracking file)")
        quality_tracking[skip_file] = "skipped - low priority"

    return quality_tracking


def main():
    """Execute Excel to Markdown conversion for plan 13-04."""
    logger.info("=== Excel to Markdown Conversion (Plan 13-04) ===")

    # Load inventory
    inventory_path = Path(
        ".planning/phases/13-documentation-consolidation/projecttt_inventory.json"
    )
    if not inventory_path.exists():
        logger.error(f"Inventory not found: {inventory_path}")
        return

    logger.info(f"Loading inventory from {inventory_path}")
    inventory = load_inventory(inventory_path)
    logger.info(
        f"Loaded {inventory['total_files']} files ({inventory['xlsx_count']} Excel)"
    )

    # Convert priority files
    logger.info("\n=== Task 1: Converting priority Excel files ===")
    conversion_results = convert_priority_files(inventory, dry_run=False)

    # Handle complex files
    logger.info("\n=== Task 2: Handling complex Excel files ===")
    quality_tracking = handle_complex_files(inventory, dry_run=False)

    # Summary
    logger.info("\n=== Conversion Summary ===")
    successful = sum(1 for r in conversion_results.values() if "error" not in r)
    failed = sum(1 for r in conversion_results.values() if "error" in r)
    skipped = len(quality_tracking)

    logger.info(f"Successful conversions: {successful}")
    logger.info(f"Failed conversions: {failed}")
    logger.info(f"Skipped files: {skipped}")

    total_sheets = sum(
        r.get("sheets_converted", 0)
        for r in conversion_results.values()
        if "error" not in r
    )
    logger.info(f"Total sheets converted: {total_sheets}")

    if failed > 0:
        logger.error("\nFailed conversions:")
        for name, result in conversion_results.items():
            if "error" in result:
                logger.error(f"  - {name}: {result['error']}")


if __name__ == "__main__":
    main()
