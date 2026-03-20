from __future__ import annotations

"""
sync_returns_bars_multi_tf_u.py

DEPRECATED - This script is a no-op and will be removed in Phase 78.

Reason: All 5 bar returns builders (refresh_returns_bars_multi_tf*.py) now write
directly to public.returns_bars_multi_tf_u with alignment_source stamped on every
row. The separate sync step is no longer needed.

Migration completed in Phase 77-01 (2026-03-20).

Previously: Synced rows from 5 siloed returns tables into returns_bars_multi_tf_u.
Now:        Each builder writes directly to _u with ALIGNMENT_SOURCE constant.
"""

import warnings


def main() -> None:
    warnings.warn(
        "sync_returns_bars_multi_tf_u is DEPRECATED and has no effect. "
        "All 5 bar returns builders write directly to returns_bars_multi_tf_u. "
        "This script will be removed in Phase 78.",
        DeprecationWarning,
        stacklevel=2,
    )
    print(
        "[ret_bars_u] DEPRECATED: This sync script is a no-op. "
        "Builders write directly to returns_bars_multi_tf_u. "
        "Remove from scheduler. Will be deleted in Phase 78."
    )


if __name__ == "__main__":
    main()
