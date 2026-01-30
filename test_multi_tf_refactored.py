"""Quick test for ema_multi_timeframe_refactored.py"""

from ta_lab2.features.m_tf.ema_multi_timeframe_refactored import MultiTFEMAFeature
from ta_lab2.features.m_tf.base_ema_feature import EMAFeatureConfig
from ta_lab2.io import _get_marketdata_engine

# Test instantiation
engine = _get_marketdata_engine()

config = EMAFeatureConfig(
    periods=[6, 9, 12, 20, 50, 100, 200],
    output_schema="public",
    output_table="cmc_ema_multi_tf",
)

feature = MultiTFEMAFeature(
    engine=engine,
    config=config,
    bars_schema="public",
    bars_table="cmc_price_bars_multi_tf",
)

print(f"Created: {feature}")
print(f"Config periods: {config.periods}")

# Test TF specs loading
try:
    tf_specs = feature.get_tf_specs()
    print(f"\nLoaded {len(tf_specs)} TF specs:")
    for spec in tf_specs[:10]:  # Show first 10
        print(f"  {spec.tf}: {spec.tf_days} days")
    if len(tf_specs) > 10:
        print(f"  ... and {len(tf_specs) - 10} more")
    print("\n[PASS] Multi-TF refactored version basic checks PASSED")
except Exception as e:
    print(f"\n[FAIL] Error loading TF specs: {e}")
    import traceback
    traceback.print_exc()
