"""
DEPRECATED: sync_returns_ema_multi_tf_u.py

This script is now a no-op. As of Phase 77, EMA returns builders write
directly to returns_ema_multi_tf_u with alignment_source stamped.
This script is retained for CLI discoverability only.
Will be removed in Phase 78.
"""

import sys


def main() -> None:
    print(
        "[ret_ema_u_sync] DEPRECATED: direct-write active. "
        "Builders now write to returns_ema_multi_tf_u directly. "
        "This sync script is a no-op and will be removed in a future phase."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
