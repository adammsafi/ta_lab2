"""
Refresh ama_multi_tf_u - Main multi-TF AMA refresh script.

Computes KAMA, DEMA, TEMA, HMA for all 18 parameter sets across all
109 timeframes from price_bars_multi_tf.

Data source:  public.price_bars_multi_tf
State table:  public.ama_multi_tf_state
Output table: public.ama_multi_tf_u  (alignment_source='multi_tf')
Indicators:   KAMA x3, DEMA x5, TEMA x5, HMA x5 (18 param sets total)
Derivatives:  d1, d2, d1_roll, d2_roll per (id, ts, tf, indicator, params_hash)

Writes directly to the unified ama_multi_tf_u table with alignment_source='multi_tf'.
The sync script (sync_ama_multi_tf_u.py) is now a no-op.

Incremental by default: uses last_canonical_ts watermark from state table.
Use --full-rebuild to clear state and recompute all rows.

Usage:
    # Single asset, single TF
    python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids 1 --tf 1D

    # All assets, all TFs (incremental)
    python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids all --all-tfs

    # KAMA only for assets 1 and 52
    python -m ta_lab2.scripts.amas.refresh_ama_multi_tf \\
        --ids 1,52 --all-tfs --indicators KAMA

    # Full rebuild for asset 1
    python -m ta_lab2.scripts.amas.refresh_ama_multi_tf \\
        --ids 1 --all-tfs --full-rebuild

    # Dry run (no DB writes)
    python -m ta_lab2.scripts.amas.refresh_ama_multi_tf --ids 1 --tf 1D --dry-run

    # With explicit DB URL and debug logging
    python -m ta_lab2.scripts.amas.refresh_ama_multi_tf \\
        --ids 1 --tf 1D --db-url postgresql://user:pass@host/db --log-level DEBUG
"""

from __future__ import annotations

from ta_lab2.scripts.amas.base_ama_refresher import BaseAMARefresher


# =============================================================================
# Concrete Refresher
# =============================================================================

ALIGNMENT_SOURCE = "multi_tf"


class MultiTFAMARefresher(BaseAMARefresher):
    """
    AMA refresher for ama_multi_tf_u (multi-timeframe canonical bars).

    Writes directly to ama_multi_tf_u with alignment_source='multi_tf'.
    Inherits all CLI, multiprocessing, and state management logic from
    BaseAMARefresher. Overrides only table names, alignment_source, and description.

    Data source: price_bars_multi_tf
    Output:      ama_multi_tf_u  (alignment_source='multi_tf')
    State:       public.ama_multi_tf_state
    """

    def get_default_output_table(self) -> str:
        return "ama_multi_tf_u"

    def get_default_state_table(self) -> str:
        return "public.ama_multi_tf_state"

    def get_description(self) -> str:
        return (
            "Refresh ama_multi_tf_u (alignment_source='multi_tf') with KAMA, DEMA, "
            "TEMA, HMA across all 109 timeframes from price_bars_multi_tf."
        )

    def get_bars_table(self) -> str:
        return "price_bars_multi_tf"

    def get_bars_schema(self) -> str:
        return "public"

    def get_alignment_source(self) -> str:
        return ALIGNMENT_SOURCE


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    MultiTFAMARefresher.main()
