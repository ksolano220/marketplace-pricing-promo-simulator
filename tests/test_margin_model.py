from dataclasses import replace

import pandas as pd
import pytest

from src.margin_model import ScenarioInputs, baseline_metrics, find_breakeven_lift, run_scenario, sensitivity_ranking

BASE = {"orders": 1000, "list_aov": 100.0}

DEFAULT_INPUTS = ScenarioInputs(
    take_rate=0.15,
    payment_fee_pct=0.029,
    fulfillment_cost_per_order=4.5,
    promo_exposed_gmv_share=0.10,
    promo_depth=0.15,
    incremental_lift_promo_exposed=0.10,
    platform_funding_share=1.0,
)


# ---------------------------------------------------------------------------
# Promo accounting: zero/full exposure, funding split, reconciliation
# ---------------------------------------------------------------------------


def test_zero_promo_exposure_means_zero_discount_and_subsidy():
    inputs = replace(DEFAULT_INPUTS, promo_exposed_gmv_share=0.0, promo_depth=0.0)
    result = run_scenario(BASE, inputs)
    assert result.promotional_discount == 0.0
    assert result.platform_funded_subsidy == 0.0
    assert result.merchant_funded_subsidy == 0.0
    assert result.orders == BASE["orders"]  # no lift possible with zero exposure


def test_zero_platform_funding_means_zero_platform_subsidy():
    result = run_scenario(BASE, replace(DEFAULT_INPUTS, platform_funding_share=0.0))
    assert result.platform_funded_subsidy == 0.0
    assert result.merchant_funded_subsidy == pytest.approx(result.promotional_discount, rel=1e-9)


def test_full_platform_funding_means_platform_bears_entire_discount():
    result = run_scenario(BASE, replace(DEFAULT_INPUTS, platform_funding_share=1.0))
    assert result.platform_funded_subsidy == pytest.approx(result.promotional_discount, rel=1e-9)
    assert result.merchant_funded_subsidy == pytest.approx(0.0, abs=1e-6)


def test_customer_paid_value_reconciles_to_gross_minus_discount():
    result = run_scenario(BASE, DEFAULT_INPUTS)
    assert result.customer_paid_value == pytest.approx(
        result.gross_basket_value - result.promotional_discount, rel=1e-9
    )


def test_platform_and_merchant_funding_sum_to_total_discount():
    result = run_scenario(BASE, replace(DEFAULT_INPUTS, platform_funding_share=0.4))
    assert result.platform_funded_subsidy + result.merchant_funded_subsidy == pytest.approx(
        result.promotional_discount, rel=1e-9
    )


# ---------------------------------------------------------------------------
# Individual lever effects, holding everything else constant
# ---------------------------------------------------------------------------


def test_take_rate_increases_platform_revenue_and_cm():
    inputs = replace(DEFAULT_INPUTS, promo_exposed_gmv_share=0.0, promo_depth=0.0)
    base_result = run_scenario(BASE, inputs)
    bumped = run_scenario(BASE, replace(inputs, take_rate=inputs.take_rate + 0.01))
    expected_delta = base_result.customer_paid_value * 0.01
    assert bumped.platform_revenue - base_result.platform_revenue == pytest.approx(expected_delta, rel=1e-9)
    assert bumped.contribution_margin > base_result.contribution_margin


def test_fulfillment_cost_reduces_cm_by_expected_amount():
    inputs = replace(DEFAULT_INPUTS, promo_exposed_gmv_share=0.0, promo_depth=0.0)
    base_result = run_scenario(BASE, inputs)
    bumped = run_scenario(BASE, replace(inputs, fulfillment_cost_per_order=inputs.fulfillment_cost_per_order + 1.0))
    assert base_result.orders == bumped.orders  # no promo, so orders are fixed
    assert bumped.contribution_margin == pytest.approx(base_result.contribution_margin - base_result.orders, rel=1e-9)


def test_payment_fee_reduces_cm():
    inputs = replace(DEFAULT_INPUTS, promo_exposed_gmv_share=0.0, promo_depth=0.0)
    base_result = run_scenario(BASE, inputs)
    bumped = run_scenario(BASE, replace(inputs, payment_fee_pct=inputs.payment_fee_pct + 0.01))
    assert bumped.contribution_margin < base_result.contribution_margin


def test_zero_orders_does_not_divide_by_zero():
    zero_base = {"orders": 0, "list_aov": 0.0}
    result = run_scenario(zero_base, DEFAULT_INPUTS)
    assert result.gross_basket_value == 0.0
    assert result.contribution_margin_pct == 0.0  # guarded, not NaN/inf


# ---------------------------------------------------------------------------
# Breakeven solver
# ---------------------------------------------------------------------------


def test_breakeven_lift_reproduces_the_no_promo_cm_target():
    inputs = replace(DEFAULT_INPUTS, incremental_lift_promo_exposed=0.0)
    breakeven = find_breakeven_lift(BASE, inputs)
    assert breakeven["reachable"]

    no_promo = replace(inputs, promo_exposed_gmv_share=0.0, promo_depth=0.0, incremental_lift_promo_exposed=0.0)
    baseline_cm = run_scenario(BASE, no_promo).contribution_margin

    at_breakeven = run_scenario(BASE, replace(inputs, incremental_lift_promo_exposed=breakeven["lift"]))
    assert at_breakeven.contribution_margin == pytest.approx(baseline_cm, abs=1.0)


def test_breakeven_unreachable_when_promo_is_structurally_dilutive():
    inputs = replace(DEFAULT_INPUTS, take_rate=0.05, promo_depth=0.45, promo_exposed_gmv_share=0.40)
    breakeven = find_breakeven_lift(BASE, inputs, max_lift=2.0)
    assert not breakeven["reachable"]
    assert breakeven["lift"] is None


def test_breakeven_undefined_when_no_promo_exposure():
    inputs = replace(DEFAULT_INPUTS, promo_exposed_gmv_share=0.0)
    breakeven = find_breakeven_lift(BASE, inputs)
    assert not breakeven["reachable"]
    assert "no promo-exposed" in breakeven["reason"]


# ---------------------------------------------------------------------------
# Promo exposure's dual effect (cost + demand), and sensitivity ranking
# ---------------------------------------------------------------------------


def test_promo_exposure_affects_both_discount_cost_and_incremental_volume():
    low = run_scenario(BASE, replace(DEFAULT_INPUTS, promo_exposed_gmv_share=0.05))
    high = run_scenario(BASE, replace(DEFAULT_INPUTS, promo_exposed_gmv_share=0.20))
    assert high.orders > low.orders  # more exposure -> more assumed incremental volume
    assert high.promotional_discount > low.promotional_discount  # and more discount cost


def test_sensitivity_ranking_reproduces_direct_run_scenario_deltas():
    rows = sensitivity_ranking(BASE, DEFAULT_INPUTS)
    baseline_cm = run_scenario(BASE, DEFAULT_INPUTS).contribution_margin

    take_rate_row = next(r for r in rows if r["lever"] == "Take rate")
    bumped_cm = run_scenario(BASE, replace(DEFAULT_INPUTS, take_rate=DEFAULT_INPUTS.take_rate + 0.01)).contribution_margin
    assert take_rate_row["cm_delta"] == pytest.approx(bumped_cm - baseline_cm, rel=1e-9)


def test_sensitivity_ranking_orders_by_magnitude_descending():
    rows = sensitivity_ranking(BASE, DEFAULT_INPUTS)
    deltas = [abs(r["cm_delta"]) for r in rows]
    assert deltas == sorted(deltas, reverse=True)
    assert len(rows) == 5


# ---------------------------------------------------------------------------
# baseline_metrics: GMV-weighted promo exposure/depth on a small known fixture
# ---------------------------------------------------------------------------


def _fixture_df() -> pd.DataFrame:
    month = pd.Timestamp("2010-01-01")
    rows = [
        # Invoice, Quantity, reference_price, revenue, is_promo, promo_depth, is_cancelled, Customer_ID
        ("1", 2, 10.0, 20.0, False, 0.0, False, 100.0),   # full price: list_value=20
        ("2", 1, 100.0, 80.0, True, 0.20, False, 101.0),  # 20% off: list_value=100
        ("3", 5, 4.0, 10.0, True, 0.50, False, None),      # 50% off: list_value=20, missing Customer_ID kept
        ("C1", -1, 100.0, -80.0, False, 0.0, True, 101.0),  # cancellation of invoice 2's line
    ]
    df = pd.DataFrame(rows, columns=["Invoice", "Quantity", "reference_price", "revenue", "is_promo", "promo_depth", "is_cancelled", "Customer_ID"])
    df["month"] = month
    return df


def test_promo_exposed_gmv_share_on_known_fixture():
    base = baseline_metrics(_fixture_df())
    # list_value: 20 (not promo) + 100 (promo) + 20 (promo) = 140; promo list_value = 100 + 20 = 120
    assert base["list_value"] == pytest.approx(140.0)
    assert base["promo_exposed_gmv_share"] == pytest.approx(120 / 140, rel=1e-9)


def test_gmv_weighted_promo_depth_on_known_fixture():
    base = baseline_metrics(_fixture_df())
    # weighted by list_value: (0.20*100 + 0.50*20) / (100+20) = 30/120 = 0.25
    assert base["gmv_weighted_promo_depth"] == pytest.approx(0.25, rel=1e-9)


def test_baseline_metrics_nets_out_cancellations():
    base = baseline_metrics(_fixture_df())
    assert base["gross_sales_value"] == pytest.approx(20 + 80 + 10)
    assert base["cancelled_value"] == pytest.approx(80)
    assert base["net_sales_value"] == pytest.approx(20 + 80 + 10 - 80)


def test_baseline_metrics_unique_customers_ignores_missing_id():
    base = baseline_metrics(_fixture_df())
    assert base["unique_customers"] == 2  # invoice 3's missing Customer_ID isn't counted, row is still kept
