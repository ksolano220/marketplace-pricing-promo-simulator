"""
Contribution-margin model for the pricing/promo simulator.

Order volume, AOV, and promo frequency/depth come straight from the
real Online Retail II transactions. Take rate, fulfillment cost, and
payment processing fee are not present in single-retailer data, so
they're modeled as explicit, adjustable assumptions representing a
marketplace operator sitting on top of this order flow -- exactly the
inputs an exec would tune when asked "if margins are low, what would
you do?"
"""

from dataclasses import dataclass

import pandas as pd


@dataclass
class ScenarioInputs:
    take_rate: float  # platform's share of GMV, e.g. 0.15
    payment_fee_pct: float  # payment processing cost, e.g. 0.029
    fulfillment_cost_per_order: float  # $ per order, e.g. 4.50
    promo_penetration: float  # share of orders that carry a promo, e.g. 0.10
    promo_depth: float  # avg discount on promo'd orders, e.g. 0.15
    promo_demand_lift: float  # extra order volume promo is assumed to generate, e.g. 0.08


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
    promo_cost = promo_gmv * inputs.promo_depth

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
