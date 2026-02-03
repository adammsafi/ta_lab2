"""Quick test for ema_multi_tf_cal_anchor.py refactored version"""

from ta_lab2.features.m_tf.ema_multi_tf_cal_anchor import CalendarAnchorEMAFeature
from ta_lab2.features.m_tf.base_ema_feature import EMAFeatureConfig
from ta_lab2.io import _get_marketdata_engine

# Test instantiation
engine = _get_marketdata_engine()

config = EMAFeatureConfig(
    periods=[6, 9, 12, 20, 50, 100, 200],
    output_schema="public",
    output_table="cmc_ema_multi_tf_cal_anchor_us",
)

print("Testing Calendar Anchor EMA Feature (US scheme)...")
feature_us = CalendarAnchorEMAFeature(
    engine=engine,
    config=config,
    scheme="us",
)

print(f"Created: {feature_us}")
print(f"Scheme: {feature_us.scheme}")
print(f"Bars table: {feature_us.bars_table}")

# Test TF specs loading
try:
    tf_specs = feature_us.get_tf_specs()
    print(f"\nLoaded {len(tf_specs)} calendar anchor TF specs (US):")
    for spec in tf_specs[:10]:  # Show first 10
        print(f"  {spec.tf}: {spec.tf_days} days")
    if len(tf_specs) > 10:
        print(f"  ... and {len(tf_specs) - 10} more")

    # Test alpha calculation
    alpha_d = feature_us._alpha_daily_equivalent(tf_days=7, period=20)
    print(f"\nDaily-equivalent alpha (7D TF, period=20): {alpha_d:.6f}")

    print("\n[PASS] Calendar Anchor EMA (US) basic checks PASSED")
except Exception as e:
    print(f"\n[FAIL] Error: {e}")
    import traceback
    traceback.print_exc()

# Test ISO scheme
print("\n" + "="*60)
print("Testing Calendar Anchor EMA Feature (ISO scheme)...")

config_iso = EMAFeatureConfig(
    periods=[6, 9, 12, 20, 50, 100, 200],
    output_schema="public",
    output_table="cmc_ema_multi_tf_cal_anchor_iso",
)

feature_iso = CalendarAnchorEMAFeature(
    engine=engine,
    config=config_iso,
    scheme="iso",
)

try:
    tf_specs_iso = feature_iso.get_tf_specs()
    print(f"\nLoaded {len(tf_specs_iso)} calendar anchor TF specs (ISO):")
    for spec in tf_specs_iso[:10]:
        print(f"  {spec.tf}: {spec.tf_days} days")
    if len(tf_specs_iso) > 10:
        print(f"  ... and {len(tf_specs_iso) - 10} more")

    print("\n[PASS] Calendar Anchor EMA (ISO) basic checks PASSED")
except Exception as e:
    print(f"\n[FAIL] Error: {e}")
    import traceback
    traceback.print_exc()
