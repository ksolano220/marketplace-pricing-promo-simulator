from dataclasses import replace

import pytest

from src.margin_model import ScenarioInputs, find_breakeven_lift, run_scenario, sensitivity_ranking

BASE = {"orders": 1000, "aov": 100.0}

DEFAULT_INPUTS = ScenarioInputs(
    take_rate=0.15,
    payment_fee_pct=0.029,
    fulfillment_cost_per_order=4.5,
    promo_penetration=0.10,
    promo_depth=0.15,
    promo_demand_lift=0.10,
    platform_funding_share=1.0,
)


def test_zero_promo_penetration_means_zero_promo_cost():
    inputs = replace(DEFAULT_INPUTS, promo_penetration=0.0, promo_depth=0.0)
    result = run_scenario(BASE, inputs)
    assert result.promo_cost == 0.0
    assert result.orders == BASE["orders"]  # no lift possible with zero penetration


def test_fulfillment_cost_reduces_cm_by_expected_amount():
    inputs = replace(DEFAULT_INPUTS, promo_penetration=0.0, promo_depth=0.0)
    base_result = run_scenario(BASE, inputs)
    bumped = run_scenario(BASE, replace(inputs, fulfillment_cost_per_order=inputs.fulfillment_cost_per_order + 1.0))
    assert base_result.orders == bumped.orders  # no promo, so orders are fixed
    assert bumped.contribution_margin == pytest.approx(base_result.contribution_margin - base_result.orders, rel=1e-9)


def test_take_rate_increases_platform_revenue_correctly():
    inputs = replace(DEFAULT_INPUTS, promo_penetration=0.0, promo_depth=0.0)
    base_result = run_scenario(BASE, inputs)
    bumped = run_scenario(BASE, replace(inputs, take_rate=inputs.take_rate + 0.01))
    expected_delta = base_result.gmv * 0.01
    assert bumped.platform_revenue - base_result.platform_revenue == pytest.approx(expected_delta, rel=1e-9)


def test_zero_gmv_does_not_divide_by_zero():
    zero_base = {"orders": 0, "aov": 0.0}
    result = run_scenario(zero_base, DEFAULT_INPUTS)
    assert result.gmv == 0.0
    assert result.contribution_margin_pct == 0.0  # guarded, not NaN/inf


def test_platform_funding_share_scales_promo_cost():
    full = run_scenario(BASE, DEFAULT_INPUTS)
    half = run_scenario(BASE, replace(DEFAULT_INPUTS, platform_funding_share=0.5))
    assert half.promo_cost == pytest.approx(full.promo_cost / 2, rel=1e-9)
    assert half.contribution_margin > full.contribution_margin


def test_breakeven_lift_solves_to_the_actual_crossing_point():
    inputs = replace(DEFAULT_INPUTS, promo_demand_lift=0.0)
    breakeven = find_breakeven_lift(BASE, inputs)
    assert breakeven["reachable"]

    no_promo = replace(inputs, promo_penetration=0.0, promo_depth=0.0, promo_demand_lift=0.0)
    baseline_cm = run_scenario(BASE, no_promo).contribution_margin

    at_breakeven = run_scenario(BASE, replace(inputs, promo_demand_lift=breakeven["lift"]))
    assert at_breakeven.contribution_margin == pytest.approx(baseline_cm, abs=1.0)


def test_breakeven_unreachable_when_promo_is_structurally_dilutive():
    # Deep discount, fully platform-funded, take rate too thin to ever recover it
    inputs = replace(DEFAULT_INPUTS, take_rate=0.05, promo_depth=0.45, promo_penetration=0.40)
    breakeven = find_breakeven_lift(BASE, inputs, max_lift=2.0)
    assert not breakeven["reachable"]
    assert breakeven["lift"] is None


def test_breakeven_zero_when_no_penetration():
    inputs = replace(DEFAULT_INPUTS, promo_penetration=0.0)
    breakeven = find_breakeven_lift(BASE, inputs)
    assert not breakeven["reachable"]
    assert "no promo penetration" in breakeven["reason"]


def test_sensitivity_ranking_orders_by_magnitude_descending():
    rows = sensitivity_ranking(BASE, DEFAULT_INPUTS)
    deltas = [abs(r["cm_delta"]) for r in rows]
    assert deltas == sorted(deltas, reverse=True)
    assert len(rows) == 5
