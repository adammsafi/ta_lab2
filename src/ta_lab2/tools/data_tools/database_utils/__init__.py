"""
Database utilities migrated from Data_Tools.

MOVED: EMA runner utilities have been relocated to ta_lab2.scripts.emas.ema_runners
to fix layering violations (tools should not import from features).

The following functions are now available at ta_lab2.scripts.emas.ema_runners:
- write_daily_emas
- write_multi_tf_emas
- write_ema_multi_tf_cal
- upsert_new_emas

Usage:
    # Import from new location
    from ta_lab2.scripts.emas.ema_runners import write_daily_emas

    # CLI
    python -m ta_lab2.scripts.emas.ema_runners daily --ids 1 1027

Note:
    This package is now empty. Future database utilities that don't violate
    layering constraints (tools importing from features) can be added here.
"""

__all__ = []
