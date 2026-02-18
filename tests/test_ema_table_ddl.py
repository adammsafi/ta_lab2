"""
Test script to verify EMA table DDL generation.

This script generates CREATE TABLE DDL for all EMA table types
without connecting to the database.
"""

from ta_lab2.scripts.emas.base_ema_refresher import _generate_ema_table_ddl

# Test all EMA table types
tables = [
    ("cmc_ema_multi_tf", "multi_tf"),
    ("cmc_ema_multi_tf_v2", "v2"),
    ("cmc_ema_multi_tf_cal_iso", "cal"),
    ("cmc_ema_multi_tf_cal_us", "cal"),
    ("cmc_ema_multi_tf_cal_anchor_iso", "cal_anchor"),
    ("cmc_ema_multi_tf_cal_anchor_us", "cal_anchor"),
]

print("=" * 80)
print("EMA Table DDL Generation Test")
print("=" * 80)

for table_name, table_type in tables:
    print(f"\n\n{'=' * 80}")
    print(f"Table: {table_name}")
    print(f"Type: {table_type}")
    print("=" * 80)

    try:
        ddl = _generate_ema_table_ddl(
            table_name, table_type=table_type, schema="public"
        )
        print(ddl)
        print(f"\n[SUCCESS] DDL generated successfully for {table_name}")
    except Exception as e:
        print(f"\n[ERROR] {e}")

print("\n\n" + "=" * 80)
print("Test Complete")
print("=" * 80)
