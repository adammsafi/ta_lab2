"""Batch convert ProjectTT DOCX files to Markdown.

Converts all ProjectTT .docx files from the inventory to Markdown format
with YAML front matter, organized into docs/ subdirectories by category.
"""
import json
import logging
import sys
import re
from pathlib import Path
from typing import Dict, List

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ta_lab2.tools.docs.convert_docx import convert_docx_to_markdown, ConversionResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Convert filename to lowercase-hyphen convention.

    Examples:
        CoreComponents.docx -> core-components.md
        ta_lab2 Workspace v.1.1.docx -> ta-lab2-workspace-v1-1.md
        Chat Gpt Export Processing – End-to-end Process.docx -> chat-gpt-export-processing-end-to-end-process.md
    """
    # Remove extension
    name = Path(name).stem

    # Convert to lowercase
    name = name.lower()

    # Replace spaces, underscores, and special chars with hyphens
    name = re.sub(r'[_\s]+', '-', name)
    name = re.sub(r'[^\w\-.]', '-', name)

    # Remove multiple consecutive hyphens
    name = re.sub(r'-+', '-', name)

    # Remove leading/trailing hyphens
    name = name.strip('-')

    return name + '.md'


def map_category_to_directory(category: str, base_path: Path) -> Path:
    """Map inventory category to output directory."""
    category_map = {
        'architecture': base_path / 'architecture',
        'features/emas': base_path / 'features' / 'emas',
        'features/bars': base_path / 'features' / 'bars',
        'features/memory': base_path / 'features' / 'memory',
        'features': base_path / 'features',  # Generic features
        'planning': base_path / 'planning',
        'reference': base_path / 'reference',
    }

    return category_map.get(category, base_path / 'reference')


def batch_convert_docx(
    inventory_path: Path,
    docs_base: Path,
    checkpoint_path: Path,
    error_log_path: Path,
    dry_run: bool = False
) -> ConversionResult:
    """Batch convert all DOCX files from inventory.

    Args:
        inventory_path: Path to projecttt_inventory.json
        docs_base: Base docs/ directory
        checkpoint_path: Path to save conversion progress
        error_log_path: Path to save error details
        dry_run: If True, simulate without writing files

    Returns:
        ConversionResult with conversion statistics
    """
    logger.info("Loading inventory from %s", inventory_path)

    with open(inventory_path, 'r') as f:
        inventory = json.load(f)

    # Load checkpoint if exists
    completed = set()
    if checkpoint_path.exists():
        with open(checkpoint_path, 'r') as f:
            checkpoint = json.load(f)
            completed = set(checkpoint.get('completed', []))
        logger.info("Loaded checkpoint: %d files already converted", len(completed))

    # Filter for .docx files only and sort by priority
    all_files = []
    for priority_group in ['1', '2', '3']:
        if priority_group in inventory['by_priority']:
            files = [f for f in inventory['by_priority'][priority_group]
                    if f['extension'] == 'docx']
            all_files.extend(files)

    total_files = len(all_files)
    logger.info("Found %d DOCX files to convert", total_files)

    # Track results
    converted = 0
    skipped = 0
    errors = 0
    error_details = []

    # Process each file
    for i, file_info in enumerate(all_files, 1):
        source_path = Path(file_info['path'])

        # Skip if already converted
        if str(source_path) in completed:
            logger.info("[%d/%d] SKIP (checkpoint): %s", i, total_files, source_path.name)
            skipped += 1
            continue

        # Determine output path
        category = file_info['category']

        # For features, check subdirectory to determine subcategory
        if category == 'features':
            subdirname = file_info.get('subdirectory', '')
            if 'EMA' in subdirname:
                category = 'features/emas'
            elif 'Bar' in subdirname:
                category = 'features/bars'
            elif 'Memory' in subdirname:
                category = 'features/memory'

        output_dir = map_category_to_directory(category, docs_base)
        output_filename = sanitize_filename(file_info['name'])
        output_path = output_dir / output_filename

        # Skip if output already exists (not from checkpoint)
        if output_path.exists() and not dry_run:
            logger.info("[%d/%d] SKIP (exists): %s -> %s",
                       i, total_files, source_path.name, output_path.name)
            skipped += 1
            completed.add(str(source_path))
            continue

        # Convert
        logger.info("[%d/%d] Converting: %s", i, total_files, source_path.name)
        logger.info("            -> %s", output_path.relative_to(docs_base.parent))

        result = convert_docx_to_markdown(
            source_path,
            output_path,
            extract_media=True,
            dry_run=dry_run
        )

        if 'error' in result:
            logger.error("[%d/%d] ERROR: %s - %s",
                        i, total_files, source_path.name, result['error'])
            errors += 1
            error_details.append({
                'file': str(source_path),
                'output': str(output_path),
                'error': result['error']
            })
        else:
            logger.info("[%d/%d] Complete: %s (%d media files)",
                       i, total_files, output_path.name, result['media_count'])
            converted += 1
            completed.add(str(source_path))

            # Save checkpoint every 5 files
            if converted % 5 == 0 and not dry_run:
                with open(checkpoint_path, 'w') as f:
                    json.dump({'completed': list(completed)}, f, indent=2)
                logger.info("Checkpoint saved: %d files converted", converted)

    # Final checkpoint save
    if not dry_run:
        with open(checkpoint_path, 'w') as f:
            json.dump({'completed': list(completed)}, f, indent=2)
        logger.info("Final checkpoint saved")

        # Save error log if any errors
        if error_details:
            with open(error_log_path, 'w') as f:
                json.dump({'errors': error_details}, f, indent=2)
            logger.info("Error log saved: %s", error_log_path)

    return ConversionResult(
        total=total_files,
        converted=converted,
        skipped=skipped,
        errors=errors,
        error_paths=[e['file'] for e in error_details]
    )


def main():
    """Run batch conversion."""
    # Paths
    base_dir = Path(__file__).parent
    inventory_path = base_dir / '.planning' / 'phases' / '13-documentation-consolidation' / 'projecttt_inventory.json'
    docs_base = base_dir / 'docs'
    checkpoint_path = docs_base / 'conversion_checkpoint.json'
    error_log_path = docs_base / 'conversion_errors.json'

    # Run conversion
    logger.info("Starting batch conversion")
    logger.info("Inventory: %s", inventory_path)
    logger.info("Output base: %s", docs_base)

    result = batch_convert_docx(
        inventory_path=inventory_path,
        docs_base=docs_base,
        checkpoint_path=checkpoint_path,
        error_log_path=error_log_path,
        dry_run=False
    )

    # Print summary
    logger.info("=" * 60)
    logger.info("CONVERSION COMPLETE")
    logger.info("=" * 60)
    print(result)

    if result.errors > 0:
        logger.warning("Some files failed to convert. See: %s", error_log_path)
        sys.exit(1)


if __name__ == '__main__':
    main()
