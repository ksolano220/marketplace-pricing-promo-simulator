"""
Contribution-margin model for the pricing/promo simulator.

Order volume, AOV, and promo frequency/depth come straight from the
real Online Retail II transactions. Take rate, fulfillment cost, and
payment processing fee are not present in single-retailer data, so
they're modeled as explicit, adjustable assumptions representing a
marketplace operator sitting on top of this order flow -- exactly the
inputs an exec would tune when asked "if margins are low, what would
you do?"

This is a decision simulator, not a causal demand model: promo-driven
demand lift is an assumption the user supplies and can stress-test,
not an estimate inferred from observational pricing data.
"""

from dataclasses import dataclass, replace

import pandas as pd


@dataclass
class ScenarioInputs:
    take_rate: float  # platform's share of GMV, e.g. 0.15
    payment_fee_pct: float  # payment processing cost, e.g. 0.029
    fulfillment_cost_per_order: float  # $ per order, e.g. 4.50
    promo_penetration: float  # share of orders that carry a promo, e.g. 0.10
    promo_depth: float  # avg discount on promo'd orders, e.g. 0.15
    promo_demand_lift: float  # extra order volume promo is assumed to generate, e.g. 0.08
    platform_funding_share: float = 1.0  # share of the promo cost the platform eats, e.g. 1.0 = fully platform-funded


@dataclass
class ScenarioResult:
    orders: float
    gmv: float
    platform_revenue: float
    payment_fees: float
    fulfillment_costs: float
    promo_cost: float
    contribution_margin: float
    contribution_margin_pct: float


def baseline_metrics(df: pd.DataFrame) -> dict:
    sales = df[~df["is_cancelled"]]
    orders = sales["Invoice"].nunique()
    gmv = sales["revenue"].sum()
    promo_orders = sales.loc[sales["is_promo"], "Invoice"].nunique()
    cancelled_orders = df.loc[df["is_cancelled"], "Invoice"].nunique()

    return {
        "orders": orders,
        "gmv": gmv,
        "aov": gmv / orders if orders else 0,
        "promo_penetration": promo_orders / orders if orders else 0,
        "avg_promo_depth": sales.loc[sales["is_promo"], "promo_depth"].mean() or 0,
        "cancellation_rate": cancelled_orders / (orders + cancelled_orders) if orders else 0,
        "unique_customers": sales["Customer_ID"].nunique(),
        "monthly_gmv": sales.groupby("month")["revenue"].sum(),
        "monthly_orders": sales.groupby("month")["Invoice"].nunique(),
    }


def run_scenario(base: dict, inputs: ScenarioInputs) -> ScenarioResult:
    base_orders = base["orders"]
    aov = base["aov"]

    lifted_orders = base_orders * (1 + inputs.promo_penetration * inputs.promo_demand_lift)
    gmv = lifted_orders * aov

    promo_gmv = gmv * inputs.promo_penetration
    promo_cost = promo_gmv * inputs.promo_depth * inputs.platform_funding_share

    platform_revenue = gmv * inputs.take_rate
    payment_fees = gmv * inputs.payment_fee_pct
    fulfillment_costs = lifted_orders * inputs.fulfillment_cost_per_order

    contribution_margin = platform_revenue - payment_fees - fulfillment_costs - promo_cost
    cm_pct = contribution_margin / gmv if gmv else 0

    return ScenarioResult(
        orders=lifted_orders,
        gmv=gmv,
        platform_revenue=platform_revenue,
        payment_fees=payment_fees,
        fulfillment_costs=fulfillment_costs,
        promo_cost=promo_cost,
        contribution_margin=contribution_margin,
        contribution_margin_pct=cm_pct,
    )


def find_breakeven_lift(base: dict, inputs: ScenarioInputs, max_lift: float = 10.0) -> dict:
    """
    Solves for the minimum promo_demand_lift at which running the promo
    (at the given penetration/depth/funding split) produces contribution
    margin at least as good as running no promo at all. Reuses
    run_scenario as the only source of truth for the margin math, so
    this can never drift out of sync with what the sliders compute.
    """
    if inputs.promo_penetration <= 0:
        return {"reachable": False, "lift": None, "reason": "no promo penetration set"}

    no_promo = replace(inputs, promo_penetration=0.0, promo_depth=0.0, promo_demand_lift=0.0)
    baseline_cm = run_scenario(base, no_promo).contribution_margin

    def cm_at(lift: float) -> float:
        return run_scenario(base, replace(inputs, promo_demand_lift=lift)).contribution_margin

    cm_lo, cm_hi = cm_at(0.0), cm_at(max_lift)

    if cm_lo >= baseline_cm:
        return {"reachable": True, "lift": 0.0, "reason": None}
    if cm_hi < baseline_cm:
        return {
            "reachable": False,
            "lift": None,
            "reason": f"not reachable even at {max_lift:.0%} demand lift -- promo cost structurally exceeds what volume can offset at these settings",
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
    Standardized one-unit bumps to each lever, ranked by contribution-
    margin impact, reusing run_scenario so the ranking always matches
    what the sliders actually compute.
    """
    baseline_cm = run_scenario(base, inputs).contribution_margin

    bumps = {
        "Take rate (+1 pt)": replace(inputs, take_rate=inputs.take_rate + 0.01),
        "Fulfillment cost (-$1/order)": replace(
            inputs, fulfillment_cost_per_order=max(0.0, inputs.fulfillment_cost_per_order - 1.0)
        ),
        "Payment fee (-1 pt)": replace(inputs, payment_fee_pct=max(0.0, inputs.payment_fee_pct - 0.01)),
        "Promo depth (-1 pt)": replace(inputs, promo_depth=max(0.0, inputs.promo_depth - 0.01)),
        "Promo penetration (-1 pt)": replace(inputs, promo_penetration=max(0.0, inputs.promo_penetration - 0.01)),
    }

    rows = []
    for label, scenario_inputs in bumps.items():
        cm = run_scenario(base, scenario_inputs).contribution_margin
        rows.append({"lever": label, "cm_delta": cm - baseline_cm})

    rows.sort(key=lambda r: -abs(r["cm_delta"]))
    return rows
