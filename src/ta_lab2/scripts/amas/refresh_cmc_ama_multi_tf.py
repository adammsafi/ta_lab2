"""
Refresh cmc_ama_multi_tf - Main multi-TF AMA refresh script.

Computes KAMA, DEMA, TEMA, HMA for all 18 parameter sets across all
109 timeframes from cmc_price_bars_multi_tf.

Data source:  public.cmc_price_bars_multi_tf
State table:  public.cmc_ama_multi_tf_state
Output table: public.cmc_ama_multi_tf
Indicators:   KAMA x3, DEMA x5, TEMA x5, HMA x5 (18 param sets total)
Derivatives:  d1, d2, d1_roll, d2_roll per (id, ts, tf, indicator, params_hash)

Incremental by default: uses last_canonical_ts watermark from state table.
Use --full-rebuild to clear state and recompute all rows.

Usage:
    # Single asset, single TF
    python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf --ids 1 --tf 1D

    # All assets, all TFs (incremental)
    python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf --ids all --all-tfs

    # KAMA only for assets 1 and 52
    python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf \\
        --ids 1,52 --all-tfs --indicators KAMA

    # Full rebuild for asset 1
    python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf \\
        --ids 1 --all-tfs --full-rebuild

    # Dry run (no DB writes)
    python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf --ids 1 --tf 1D --dry-run

    # With explicit DB URL and debug logging
    python -m ta_lab2.scripts.amas.refresh_cmc_ama_multi_tf \\
        --ids 1 --tf 1D --db-url postgresql://user:pass@host/db --log-level DEBUG
"""

from __future__ import annotations

from ta_lab2.scripts.amas.base_ama_refresher import BaseAMARefresher


# =============================================================================
# Concrete Refresher
# =============================================================================


class MultiTFAMARefresher(BaseAMARefresher):
    """
    AMA refresher for cmc_ama_multi_tf (multi-timeframe canonical bars).

    Inherits all CLI, multiprocessing, and state management logic from
    BaseAMARefresher. Overrides only table names and description.

    Data source: cmc_price_bars_multi_tf
    Output:      cmc_ama_multi_tf
    State:       public.cmc_ama_multi_tf_state
    """

    def get_default_output_table(self) -> str:
        return "cmc_ama_multi_tf"

    def get_default_state_table(self) -> str:
        return "public.cmc_ama_multi_tf_state"

    def get_description(self) -> str:
        return (
            "Refresh cmc_ama_multi_tf with KAMA, DEMA, TEMA, HMA across all "
            "109 timeframes from cmc_price_bars_multi_tf."
        )

    def get_bars_table(self) -> str:
        return "cmc_price_bars_multi_tf"

    def get_bars_schema(self) -> str:
        return "public"


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    MultiTFAMARefresher.main()
