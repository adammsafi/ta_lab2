"""Excel to Markdown table conversion utilities.

Converts Excel workbooks to Markdown format with proper table formatting,
handling multi-sheet workbooks and unnamed columns gracefully.
"""
import logging
from pathlib import Path
from typing import Optional, List

try:
    import pandas as pd
except ImportError:
    pd = None

from ta_lab2.tools.docs.convert_docx import ConversionResult

# Set up logger
logger = logging.getLogger(__name__)


def convert_excel_to_markdown(
    excel_path: Path,
    output_path: Path,
    sheet_names: Optional[List[str]] = None,
    include_index: bool = False,
    dry_run: bool = False,
) -> dict:
    """Convert Excel file to Markdown tables.

    Reads an Excel workbook and converts each sheet to a Markdown table.
    Handles multi-sheet workbooks by creating H2 headings per sheet.
    Skips empty sheets with logging.

    Args:
        excel_path: Path to source Excel file (.xlsx, .xls)
        output_path: Path to output Markdown file
        sheet_names: List of sheet names to convert (None = all sheets)
        include_index: If True, include DataFrame index in output
        dry_run: If True, simulate operation without writing files

    Returns:
        Dictionary with keys: source, output, sheets_converted,
        total_sheets, sheet_stats

    Example:
        >>> result = convert_excel_to_markdown(
        ...     Path("data/report.xlsx"),
        ...     Path("docs/report.md")
        ... )
        >>> print(f"Converted {result['sheets_converted']} sheets")
    """
    if pd is None:
        logger.error("pandas not installed, cannot convert Excel")
        return {
            "source": str(excel_path),
            "output": str(output_path),
            "sheets_converted": 0,
            "total_sheets": 0,
            "sheet_stats": {},
            "error": "pandas not installed",
        }

    if not excel_path.exists():
        logger.error(f"Source file not found: {excel_path}")
        return {
            "source": str(excel_path),
            "output": str(output_path),
            "sheets_converted": 0,
            "total_sheets": 0,
            "sheet_stats": {},
            "error": "Source file not found",
        }

    logger.info(
        f"Converting {excel_path.name} to Markdown{' (dry run)' if dry_run else ''}"
    )

    try:
        # Read workbook
        excel_file = pd.ExcelFile(excel_path)
        all_sheet_names = excel_file.sheet_names

        # Filter sheet names if specified
        sheets_to_convert = sheet_names if sheet_names else all_sheet_names
        total_sheets = len(sheets_to_convert)

        logger.debug(f"Found {len(all_sheet_names)} sheets, converting {total_sheets}")

        # Build markdown content
        markdown_lines = []

        # Add document title (H1) from filename
        doc_title = excel_path.stem.replace("_", " ").replace("-", " ").title()
        markdown_lines.append(f"# {doc_title}")
        markdown_lines.append("")

        # Add conversion note
        markdown_lines.append(f"*Converted from: {excel_path.name}*")
        markdown_lines.append("")

        sheets_converted = 0
        sheet_stats = {}

        for sheet_name in sheets_to_convert:
            if sheet_name not in all_sheet_names:
                logger.warning(f"Sheet '{sheet_name}' not found in workbook, skipping")
                continue

            try:
                # Read sheet
                df = pd.read_excel(excel_path, sheet_name=sheet_name)

                # Skip empty sheets
                if df.empty:
                    logger.warning(f"Sheet '{sheet_name}' is empty, skipping")
                    sheet_stats[sheet_name] = {"rows": 0, "columns": 0, "skipped": True}
                    continue

                # Clean up unnamed columns
                df.columns = [
                    "" if str(col).startswith("Unnamed:") else str(col)
                    for col in df.columns
                ]

                # Add sheet heading (H2)
                markdown_lines.append(f"## {sheet_name}")
                markdown_lines.append("")

                # Convert to markdown table
                try:
                    table_markdown = df.to_markdown(index=include_index)
                    markdown_lines.append(table_markdown)
                except Exception as e:
                    # Fallback: Try basic formatting if to_markdown fails
                    logger.warning(
                        f"to_markdown failed for '{sheet_name}', using fallback: {e}"
                    )
                    # Add HTML comment about limitations
                    markdown_lines.append(
                        "<!-- Complex formatting may not be preserved -->"
                    )
                    markdown_lines.append("")
                    # Simple table fallback
                    markdown_lines.append(
                        "| " + " | ".join(str(col) for col in df.columns) + " |"
                    )
                    markdown_lines.append(
                        "| " + " | ".join("---" for _ in df.columns) + " |"
                    )
                    for _, row in df.iterrows():
                        markdown_lines.append(
                            "| " + " | ".join(str(val) for val in row.values) + " |"
                        )

                markdown_lines.append("")

                sheets_converted += 1
                sheet_stats[sheet_name] = {
                    "rows": len(df),
                    "columns": len(df.columns),
                    "skipped": False,
                }

                logger.debug(
                    f"Converted sheet '{sheet_name}': {len(df)} rows x {len(df.columns)} columns"
                )

            except Exception as e:
                logger.error(f"Failed to convert sheet '{sheet_name}': {e}")
                sheet_stats[sheet_name] = {"rows": 0, "columns": 0, "error": str(e)}

        # Write output file
        full_content = "\n".join(markdown_lines)

        if not dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(full_content, encoding="utf-8")
            logger.info(f"Converted: {output_path.name} ({sheets_converted} sheets)")
        else:
            logger.info(
                f"[DRY RUN] Would write: {output_path} ({sheets_converted} sheets)"
            )

        return {
            "source": str(excel_path),
            "output": str(output_path),
            "sheets_converted": sheets_converted,
            "total_sheets": total_sheets,
            "sheet_stats": sheet_stats,
        }

    except Exception as e:
        logger.error(f"Failed to convert {excel_path}: {e}")
        return {
            "source": str(excel_path),
            "output": str(output_path),
            "sheets_converted": 0,
            "total_sheets": 0,
            "sheet_stats": {},
            "error": str(e),
        }


def batch_convert_excel(
    input_dir: Path, output_dir: Path, pattern: str = "*.xlsx", dry_run: bool = False
) -> ConversionResult:
    """Batch convert all Excel files matching pattern.

    Converts all Excel files in input directory matching the pattern.
    Skips existing files (idempotent operation).

    Args:
        input_dir: Directory containing Excel files
        output_dir: Directory for output Markdown files
        pattern: Glob pattern for Excel files (default: "*.xlsx")
        dry_run: If True, simulate operation without writing files

    Returns:
        ConversionResult with totals and error tracking

    Example:
        >>> result = batch_convert_excel(
        ...     Path("docs/excel"),
        ...     Path("docs/markdown"),
        ...     pattern="*.xlsx"
        ... )
        >>> print(result)
    """
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        return ConversionResult(
            total=0, converted=0, skipped=0, errors=1, error_paths=[str(input_dir)]
        )

    logger.info(
        f"Batch converting Excel files from {input_dir}{' (dry run)' if dry_run else ''}"
    )

    # Find all matching files
    excel_files = list(input_dir.glob(pattern))
    total = len(excel_files)

    if total == 0:
        logger.warning(f"No files found matching pattern '{pattern}' in {input_dir}")
        return ConversionResult(total=0, converted=0, skipped=0, errors=0)

    logger.info(f"Found {total} Excel files to convert")

    converted = 0
    skipped = 0
    errors = 0
    error_paths = []

    for excel_path in excel_files:
        # Generate output path
        output_path = output_dir / f"{excel_path.stem}.md"

        # Skip if output already exists (idempotent)
        if output_path.exists() and not dry_run:
            logger.debug(f"Skipping {excel_path.name} (already exists)")
            skipped += 1
            continue

        # Convert file
        result = convert_excel_to_markdown(excel_path, output_path, dry_run=dry_run)

        if "error" in result:
            errors += 1
            error_paths.append(str(excel_path))
        else:
            converted += 1

    return ConversionResult(
        total=total,
        converted=converted,
        skipped=skipped,
        errors=errors,
        error_paths=error_paths,
    )


__all__ = [
    "convert_excel_to_markdown",
    "batch_convert_excel",
]
