"""
DEPRECATED: sync_returns_ama_multi_tf_u.py

This script is now a no-op. As of Phase 77, refresh_returns_ama.py writes
directly to returns_ama_multi_tf_u with alignment_source stamped.
This script is retained for CLI discoverability only.
Will be removed in Phase 78.
"""

import sys


def main() -> None:
    print(
        "[ret_ama_u_sync] DEPRECATED: direct-write active. "
        "refresh_returns_ama.py now writes to returns_ama_multi_tf_u directly. "
        "This sync script is a no-op and will be removed in a future phase."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
