"""
Test script to verify bar table DDL generation.

This script generates CREATE TABLE DDL for all 6 bar table types
without connecting to the database.
"""

from ta_lab2.scripts.bars.common_snapshot_contract import _generate_bar_table_ddl

# Test all 6 table types
tables = [
    ("cmc_price_bars_1d", "1d"),
    ("cmc_price_bars_multi_tf", "multi_tf"),
    ("cmc_price_bars_multi_tf_cal_iso", "cal"),
    ("cmc_price_bars_multi_tf_cal_us", "cal"),
    ("cmc_price_bars_multi_tf_cal_anchor_iso", "cal_anchor"),
    ("cmc_price_bars_multi_tf_cal_anchor_us", "cal_anchor"),
]

print("=" * 80)
print("Bar Table DDL Generation Test")
print("=" * 80)

for table_name, table_type in tables:
    print(f"\n\n{'=' * 80}")
    print(f"Table: {table_name}")
    print(f"Type: {table_type}")
    print("=" * 80)

    try:
        ddl = _generate_bar_table_ddl(
            table_name, table_type=table_type, schema="public"
        )
        print(ddl)
        print(f"\n[SUCCESS] DDL generated successfully for {table_name}")
    except Exception as e:
        print(f"\n[ERROR] {e}")

print("\n\n" + "=" * 80)
print("Test Complete")
print("=" * 80)
