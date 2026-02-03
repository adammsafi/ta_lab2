# tests/regimes/test_regime_policy_resolution_tighten_only_and_hysteresis.py
import pytest

from ta_lab2.regimes import (
    resolve_policy,
    apply_hysteresis,
    DEFAULT_POLICY_TABLE,
)


def test_tighten_only_merges_layers_and_forces_passive_on_stressed_liquidity():
    """
    L2 grants generous defaults, L1 tightens due to High vol, and L3 forces passive orders
    when liquidity is Stressed. Size must go down (<= 1.0), stop must go up (>= 1.5),
    and orders must become passive.
    """
    pol = resolve_policy(
        L2="Up-Normal-Normal",  # meso: generous base
        L1="Up-High-Normal",  # weekly: high vol → tighten size/stop
        L0=None,
        L3="Up-Normal-Stressed",  # micro-liq: stressed → passive orders
        L4=None,
    )
    assert pol.size_mult <= 1.0
    assert pol.stop_mult >= 1.5
    assert pol.orders in ("passive", "conservative")
    # Because we mark stressed liquidity we explicitly flip orders to passive:
    assert pol.orders == "passive"


def test_downside_weekly_tightens_even_if_daily_uptrend():
    """
    If the weekly layer is 'Down-', the resolver should tighten risk even if daily is friendly.
    """
    pol = resolve_policy(
        L2="Up-Low-Normal",
        L1="Down-High-Normal",
        L0=None,
        L3=None,
        L4=None,
    )
    # From defaults, Down- uses size <= 0.60 and stop >= 1.60 (or tighter if overlaid).
    assert pol.size_mult <= DEFAULT_POLICY_TABLE.get("Down-", {}).get("size_mult", 0.8)
    assert pol.stop_mult >= DEFAULT_POLICY_TABLE.get("Down-", {}).get("stop_mult", 1.5)


def test_hysteresis_returns_previous_on_no_change_requirement():
    """
    Minimal hysteresis smoke: when prev == new and min_change gate is active,
    returned key should remain previous.
    """
    prev = "Up-Normal-Normal"
    new = "Up-Normal-Normal"
    kept = apply_hysteresis(prev_key=prev, new_key=new, min_change=1)
    assert kept == prev


@pytest.mark.parametrize(
    "regime_fragment, expected_field",
    [
        ("Up-Low-", "size_mult"),
        ("Up-High-", "stop_mult"),
        ("Sideways-Low-", "setups"),
        ("Sideways-High-", "orders"),
        ("-Stressed", "orders"),
    ],
)
def test_default_policy_fragments_exist(regime_fragment, expected_field):
    """
    Sanity check that our DEFAULT_POLICY_TABLE exposes the core fragments we rely on.
    Avoids silent regressions if the defaults are edited.
    """
    # Find at least one rule whose key contains the fragment
    matches = [v for k, v in DEFAULT_POLICY_TABLE.items() if regime_fragment in k]
    assert matches, f"No default policy rules found for fragment: {regime_fragment}"
    # And the expected field is present in at least one of the matches
    assert any(
        expected_field in m for m in matches
    ), f"Expected field '{expected_field}' missing for fragment '{regime_fragment}'"


def test_liquidity_override_keeps_pyramids_setting_tight():
    """
    Liquidity override shouldn't *loosen* pyramids if a higher layer already disabled them.
    We simulate by composing a 'Sideways-High-' (often disables pyramids) with '-Stressed'.
    """
    pol = resolve_policy(
        L2="Sideways-High-Normal",
        L1=None,
        L0=None,
        L3="Up-Normal-Stressed",
        L4=None,
    )
    # Orders must be passive due to stressed liquidity
    assert pol.orders == "passive"
    # If the default overlay disables pyramids for Sideways-High-, ensure they are not re-enabled
    side_high = DEFAULT_POLICY_TABLE.get("Sideways-High-", {})
    if "pyramids" in side_high:
        assert pol.pyramids <= bool(side_high["pyramids"])
