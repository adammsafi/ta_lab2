"""Quick test for ema_multi_tf_cal.py refactored version"""

from ta_lab2.features.m_tf.ema_multi_tf_cal import CalendarEMAFeature
from ta_lab2.features.m_tf.base_ema_feature import EMAFeatureConfig
from ta_lab2.io import _get_marketdata_engine

# Test instantiation
engine = _get_marketdata_engine()

config = EMAFeatureConfig(
    periods=[6, 9, 12, 20, 50, 100, 200],
    output_schema="public",
    output_table="cmc_ema_multi_tf_cal_us",
)

print("Testing Calendar EMA Feature (US scheme)...")
feature_us = CalendarEMAFeature(
    engine=engine,
    config=config,
    scheme="us",
    alpha_schema="public",
    alpha_table="ema_alpha_lookup",
)

print(f"Created: {feature_us}")
print(f"Scheme: {feature_us.scheme}")
print(f"Bars table: {feature_us.bars_table}")

# Test TF specs loading
try:
    tf_specs = feature_us.get_tf_specs()
    print(f"\nLoaded {len(tf_specs)} calendar TF specs (US):")
    for spec in tf_specs[:10]:  # Show first 10
        print(f"  {spec.tf}: {spec.tf_days} days")
    if len(tf_specs) > 10:
        print(f"  ... and {len(tf_specs) - 10} more")

    # Test alpha lookup
    alpha_lut = feature_us._load_alpha_lookup()
    print(f"\n[PASS] Loaded {len(alpha_lut)} alpha lookup entries")

    print("\n[PASS] Calendar EMA (US) basic checks PASSED")
except Exception as e:
    print(f"\n[FAIL] Error: {e}")
    import traceback
    traceback.print_exc()

# Test ISO scheme
print("\n" + "="*60)
print("Testing Calendar EMA Feature (ISO scheme)...")

config_iso = EMAFeatureConfig(
    periods=[6, 9, 12, 20, 50, 100, 200],
    output_schema="public",
    output_table="cmc_ema_multi_tf_cal_iso",
)

feature_iso = CalendarEMAFeature(
    engine=engine,
    config=config_iso,
    scheme="iso",
)

try:
    tf_specs_iso = feature_iso.get_tf_specs()
    print(f"\nLoaded {len(tf_specs_iso)} calendar TF specs (ISO):")
    for spec in tf_specs_iso[:10]:
        print(f"  {spec.tf}: {spec.tf_days} days")
    if len(tf_specs_iso) > 10:
        print(f"  ... and {len(tf_specs_iso) - 10} more")

    print("\n[PASS] Calendar EMA (ISO) basic checks PASSED")
except Exception as e:
    print(f"\n[FAIL] Error: {e}")
    import traceback
    traceback.print_exc()
