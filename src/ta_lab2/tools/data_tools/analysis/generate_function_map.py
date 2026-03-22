"""Backward-compatible thin wrapper around generate_function_map_with_purpose.

Use ``generate_function_map_with_purpose`` directly for full features.
This module is kept for backward compatibility of imports and CLI usage.

Usage:
    python -m ta_lab2.tools.data_tools.analysis.generate_function_map \\
        --root . --include "src/ta_lab2/**/*.py" --output function_map.csv
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List, Optional

from ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose import (
    generate_function_map_with_purpose,
)

logger = logging.getLogger(__name__)


def generate_function_map(
    root: Path,
    output: Path,
    include_globs: Optional[List[str]] = None,
    exclude_globs: Optional[List[str]] = None,
) -> int:
    """Generate function map CSV (simple format, no purpose inference).

    Delegates to ``generate_function_map_with_purpose`` with ``simple=True``.
    """
    return generate_function_map_with_purpose(
        root=str(root),
        output=str(output),
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        simple=True,
    )


def main() -> int:
    """CLI entry point (backward-compatible)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Generate a CSV map of all functions/methods in a repo (simple mode)."
    )
    ap.add_argument("--root", type=str, default=".", help="Repository root directory")
    ap.add_argument(
        "--output", type=str, default="function_map.csv", help="Output CSV path"
    )
    ap.add_argument(
        "--include", type=str, nargs="*", default=[], help="Glob(s) to include"
    )
    ap.add_argument(
        "--exclude", type=str, nargs="*", default=None, help="Glob(s) to exclude"
    )
    args = ap.parse_args()

    count = generate_function_map(
        root=Path(args.root).resolve(),
        output=Path(args.output),
        include_globs=args.include,
        exclude_globs=args.exclude,
    )
    print(f"Wrote {count} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
