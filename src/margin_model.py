"""
Contribution-margin model for the pricing/promo simulator.

ACCOUNTING CONVENTION (read this before changing any formula below)
---------------------------------------------------------------------
Every dollar in a promo-exposed transaction is accounted for as:

    gross basket value (list price, pre-discount)
    - promotional discount
    = customer-paid value

The promotional discount is itself split between whoever funds it:

    promotional discount = platform-funded subsidy + merchant-funded subsidy

This simulator applies take rate and payment-processing fees to
CUSTOMER-PAID VALUE, not gross basket value. That's a deliberate,
stated modeling choice, not a claim about industry-wide practice --
marketplace revenue recognition and promo accounting vary by business
model and contract structure. Other conventions (e.g. take rate on
pre-discount list price) are equally legitimate; this simulator just
doesn't use them.

Only the PLATFORM-funded share of the discount is a cost to contribution
margin. The merchant/vendor-funded share is reported for transparency
(so a user can see who is actually paying for the promo) but is not
subtracted from contribution margin, because it isn't the platform's
money.

Order volume and list-price AOV come from real Online Retail II
transactions (see `baseline_metrics`, which reads the processed
dataset). Take rate, fulfillment cost, payment fee, promo-exposed GMV
share, promo depth, and the platform/merchant funding split are not
present in that single-retailer data, so they're modeled as explicit,
adjustable assumptions representing a marketplace operator sitting on
top of this order flow, exactly the inputs an exec would tune when
asked "if margins are low, what would you do?"

This is a decision simulator, not a causal demand model: the
incremental order lift among promo-exposed demand is an assumption the
user supplies and stress-tests, not an estimate inferred from
observational pricing data.
"""

from dataclasses import dataclass, replace

import pandas as pd


@dataclass
class ScenarioInputs:
    take_rate: float  # platform's share of customer-paid value, e.g. 0.15
    payment_fee_pct: float  # payment processing cost on customer-paid value, e.g. 0.029
    fulfillment_cost_per_order: float  # $ per order, e.g. 4.50
    promo_exposed_gmv_share: float  # share of gross basket value that is promo-touched, e.g. 0.10
    promo_depth: float  # discount rate applied to promo-exposed basket value, e.g. 0.15
    incremental_lift_promo_exposed: float  # assumed extra order volume among promo-exposed demand, e.g. 0.08
    platform_funding_share: float = 1.0  # share of the promotional discount the platform funds, vs. merchant/vendor


@dataclass
class ScenarioResult:
    orders: float
    gross_basket_value: float  # pre-discount, list-price value of the scenario's order volume
    customer_paid_value: float  # gross_basket_value - promotional_discount; the take-rate/payment-fee basis
    promotional_discount: float  # total discount across all promo-exposed orders
    platform_funded_subsidy: float  # the share of promotional_discount that hits contribution margin
    merchant_funded_subsidy: float  # the share funded by the merchant/vendor, not a platform cost
    platform_revenue: float
    payment_fees: float
    fulfillment_costs: float
    contribution_margin: float
    contribution_margin_pct: float  # contribution_margin / customer_paid_value


def baseline_metrics(df: pd.DataFrame) -> dict:
    """
    Computes real, observed baseline figures from the processed
    transaction data. `list_value` uses each line's own SKU reference
    price (see data_prep.py) rather than the price actually paid, so it
    approximates gross/pre-discount basket value; `gross_sales_value`
    uses the price actually paid, so it's the real historical revenue
    before netting out cancellations.

    promo_exposed_gmv_share and gmv_weighted_promo_depth are GMV-weighted
    (weighted by each line's list_value), not order-count-based or
    line-count-based: an order with one discounted item and four
    full-price items should barely move these numbers, not count as
    fully "promo-exposed."
    """
    sales = df[~df["is_cancelled"]].copy()
    cancels = df[df["is_cancelled"]]

    sales["list_value"] = sales["Quantity"] * sales["reference_price"]

    orders = sales["Invoice"].nunique()
    cancelled_orders = cancels["Invoice"].nunique()

    gross_sales_value = sales["revenue"].sum()  # actual price paid, before netting cancellations
    cancelled_value = cancels["revenue"].abs().sum()
    net_sales_value = gross_sales_value - cancelled_value

    list_value = sales["list_value"].sum()

    promo_lines = sales[sales["is_promo"]]
    promo_list_value = promo_lines["list_value"].sum()
    promo_exposed_gmv_share = promo_list_value / list_value if list_value else 0

    gmv_weighted_promo_depth = (
        (promo_lines["promo_depth"] * promo_lines["list_value"]).sum() / promo_list_value
        if promo_list_value
        else 0
    )

    return {
        "orders": orders,
        "gross_sales_value": gross_sales_value,
        "cancelled_value": cancelled_value,
        "net_sales_value": net_sales_value,
        "aov": gross_sales_value / orders if orders else 0,
        "list_value": list_value,
        "list_aov": list_value / orders if orders else 0,
        "promo_exposed_gmv_share": promo_exposed_gmv_share,
        "gmv_weighted_promo_depth": gmv_weighted_promo_depth,
        "cancellation_invoice_rate": cancelled_orders / (orders + cancelled_orders) if (orders + cancelled_orders) else 0,
        "unique_customers": sales["Customer_ID"].nunique(),
        "monthly_gross_sales_value": sales.groupby("month")["revenue"].sum(),
        "monthly_orders": sales.groupby("month")["Invoice"].nunique(),
    }


def run_scenario(base: dict, inputs: ScenarioInputs) -> ScenarioResult:
    base_orders = base["orders"]
    list_aov = base["list_aov"]

    lifted_orders = base_orders * (1 + inputs.promo_exposed_gmv_share * inputs.incremental_lift_promo_exposed)
    gross_basket_value = lifted_orders * list_aov

    promo_exposed_basket_value = gross_basket_value * inputs.promo_exposed_gmv_share
    promotional_discount = promo_exposed_basket_value * inputs.promo_depth
    customer_paid_value = gross_basket_value - promotional_discount

    platform_funded_subsidy = promotional_discount * inputs.platform_funding_share
    merchant_funded_subsidy = promotional_discount - platform_funded_subsidy

    platform_revenue = customer_paid_value * inputs.take_rate
    payment_fees = customer_paid_value * inputs.payment_fee_pct
    fulfillment_costs = lifted_orders * inputs.fulfillment_cost_per_order

    contribution_margin = platform_revenue - payment_fees - fulfillment_costs - platform_funded_subsidy
    cm_pct = contribution_margin / customer_paid_value if customer_paid_value else 0

    return ScenarioResult(
        orders=lifted_orders,
        gross_basket_value=gross_basket_value,
        customer_paid_value=customer_paid_value,
        promotional_discount=promotional_discount,
        platform_funded_subsidy=platform_funded_subsidy,
        merchant_funded_subsidy=merchant_funded_subsidy,
        platform_revenue=platform_revenue,
        payment_fees=payment_fees,
        fulfillment_costs=fulfillment_costs,
        contribution_margin=contribution_margin,
        contribution_margin_pct=cm_pct,
    )


def find_breakeven_lift(base: dict, inputs: ScenarioInputs, max_lift: float = 10.0) -> dict:
    """
    Solves for the minimum incremental_lift_promo_exposed at which
    running the promo (at the given exposure/depth/funding split)
    produces contribution margin at least as good as running no promo
    at all. Reuses run_scenario as the only source of truth for the
    margin math, so this can never drift out of sync with what the
    sliders compute.

    max_lift=10.0 (1000% incremental lift among promo-exposed demand)
    is a search ceiling for the solver, not a claim about what's
    commercially plausible; the UI classifies the result separately.
    """
    if inputs.promo_exposed_gmv_share <= 0:
        return {"reachable": False, "lift": None, "reason": "no promo-exposed GMV share set"}

    no_promo = replace(inputs, promo_exposed_gmv_share=0.0, promo_depth=0.0, incremental_lift_promo_exposed=0.0)
    baseline_cm = run_scenario(base, no_promo).contribution_margin

    def cm_at(lift: float) -> float:
        return run_scenario(base, replace(inputs, incremental_lift_promo_exposed=lift)).contribution_margin

    cm_lo, cm_hi = cm_at(0.0), cm_at(max_lift)

    if cm_lo >= baseline_cm:
        return {"reachable": True, "lift": 0.0, "reason": None}
    if cm_hi < baseline_cm:
        return {
            "reachable": False,
            "lift": None,
            "reason": f"not reachable even at {max_lift:.0%} incremental lift: promo cost structurally exceeds what volume can offset at these settings",
        }

    lo, hi = 0.0, max_lift
    for _ in range(60):
        mid = (lo + hi) / 2
        if cm_at(mid) < baseline_cm:
            lo = mid
        else:
            hi = mid
    return {"reachable": True, "lift": hi, "reason": None}


def sensitivity_ranking(base: dict, inputs: ScenarioInputs) -> list[dict]:
    """
    Tests five specific, practical operating changes from the current
    scenario and ranks them by contribution-margin impact. These are
    NOT standardized units: a $1/order fulfillment change and a 1
    percentage-point take-rate change are not economically equivalent
    sized moves, which is exactly why cm_delta_pct_of_baseline is
    included: it expresses each change as a % of the current
    scenario's contribution margin, which IS comparable across levers.

    The "Promo-exposed GMV share" row intentionally changes two things
    at once, less promo cost AND less assumed incremental volume,
    per the demand equation in run_scenario, because that's what
    actually happens when exposure changes. That's a feature of the
    model, not a bug.
    """
    baseline_cm = run_scenario(base, inputs).contribution_margin

    bumps = [
        ("Take rate", "+1 pt", replace(inputs, take_rate=inputs.take_rate + 0.01)),
        (
            "Fulfillment cost",
            "-$1/order",
            replace(inputs, fulfillment_cost_per_order=max(0.0, inputs.fulfillment_cost_per_order - 1.0)),
        ),
        ("Payment fee", "-1 pt", replace(inputs, payment_fee_pct=max(0.0, inputs.payment_fee_pct - 0.01))),
        ("Promo depth", "-1 pt", replace(inputs, promo_depth=max(0.0, inputs.promo_depth - 0.01))),
        (
            "Promo-exposed GMV share",
            "-1 pt",
            replace(inputs, promo_exposed_gmv_share=max(0.0, inputs.promo_exposed_gmv_share - 0.01)),
        ),
    ]

    rows = []
    for lever, change, scenario_inputs in bumps:
        cm = run_scenario(base, scenario_inputs).contribution_margin
        delta = cm - baseline_cm
        rows.append(
            {
                "lever": lever,
                "change": change,
                "cm_delta": delta,
                "cm_delta_pct_of_baseline": delta / baseline_cm if baseline_cm else 0,
            }
        )

    rows.sort(key=lambda r: -abs(r["cm_delta"]))
    return rows
