from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.margin_model import ScenarioInputs, baseline_metrics, run_scenario

PROCESSED_PATH = Path(__file__).parent / "data" / "processed" / "orders.parquet"

st.set_page_config(page_title="Marketplace Pricing & Promotion Simulator", layout="wide")


@st.cache_data
def load_data() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_PATH)


df = load_data()
base = baseline_metrics(df)

st.title("Marketplace Pricing & Promotion Simulator")
st.caption(
    "Order volume, AOV, and promo frequency/depth are computed from real transactions "
    "([UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii), "
    "824K line items / 37K orders, 2009-2011). Take rate, fulfillment cost, and payment "
    "fees aren't in that dataset, so they're modeled here as an adjustable marketplace-"
    "operator layer on top of the real order flow."
)

st.subheader("Real baseline, from the data")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Orders", f"{base['orders']:,}")
c2.metric("GMV", f"${base['gmv']:,.0f}")
c3.metric("AOV", f"${base['aov']:,.2f}")
c4.metric("Cancellation rate", f"{base['cancellation_rate']:.1%}")

st.line_chart(base["monthly_gmv"], x_label="Month", y_label="GMV ($)")

st.divider()
st.subheader("Scenario: tune the marketplace economics")

col_left, col_right = st.columns([1, 2])

with col_left:
    st.markdown("**Platform economics**")
    take_rate = st.slider("Take rate", 0.05, 0.30, 0.15, 0.01, format="%.0f%%".replace("%.0f", "%d"))
    payment_fee = st.slider("Payment processing fee", 0.010, 0.045, 0.029, 0.001)
    fulfillment_cost = st.slider("Fulfillment cost per order ($)", 0.0, 12.0, 4.5, 0.25)

    st.markdown("**Promotion**")
    promo_penetration = st.slider(
        "Promo penetration (% of orders)", 0.0, 0.50,
        float(round(base["promo_penetration"], 2)), 0.01,
    )
    promo_depth = st.slider(
        "Promo depth (avg discount)", 0.0, 0.50,
        float(round(base["avg_promo_depth"], 2)), 0.01,
    )
    demand_lift = st.slider(
        "Assumed demand lift from promo", 0.0, 0.50, 0.10, 0.01,
        help="Extra order volume the promo is assumed to generate, applied to the share of orders it touches.",
    )

inputs = ScenarioInputs(
    take_rate=take_rate,
    payment_fee_pct=payment_fee,
    fulfillment_cost_per_order=fulfillment_cost,
    promo_penetration=promo_penetration,
    promo_depth=promo_depth,
    promo_demand_lift=demand_lift,
)
no_promo_inputs = ScenarioInputs(
    take_rate=take_rate,
    payment_fee_pct=payment_fee,
    fulfillment_cost_per_order=fulfillment_cost,
    promo_penetration=0.0,
    promo_depth=0.0,
    promo_demand_lift=0.0,
)

with_promo = run_scenario(base, inputs)
without_promo = run_scenario(base, no_promo_inputs)

with col_right:
    st.markdown("**Contribution margin: no promo vs. this scenario**")
    m1, m2, m3 = st.columns(3)
    m1.metric(
        "Contribution margin",
        f"${with_promo.contribution_margin:,.0f}",
        f"{with_promo.contribution_margin - without_promo.contribution_margin:,.0f}",
    )
    m2.metric(
        "Contribution margin %",
        f"{with_promo.contribution_margin_pct:.1%}",
        f"{(with_promo.contribution_margin_pct - without_promo.contribution_margin_pct) * 100:.1f} pts",
    )
    m3.metric(
        "Orders",
        f"{with_promo.orders:,.0f}",
        f"{with_promo.orders - without_promo.orders:,.0f}",
    )

    waterfall = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=["absolute", "relative", "relative", "relative", "total"],
            x=["Platform revenue", "Payment fees", "Fulfillment cost", "Promo cost", "Contribution margin"],
            y=[
                with_promo.platform_revenue,
                -with_promo.payment_fees,
                -with_promo.fulfillment_costs,
                -with_promo.promo_cost,
                0,
            ],
            connector={"line": {"color": "rgba(120,120,120,0.4)"}},
        )
    )
    waterfall.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=380,
        yaxis_title="$",
    )
    st.plotly_chart(waterfall, use_container_width=True)

st.divider()
st.caption(
    "Contribution margin = platform revenue (GMV x take rate) - payment fees - fulfillment "
    "cost - promo cost, where promo cost = GMV x promo penetration x promo depth, and order "
    "volume responds to promo penetration x demand lift. See src/margin_model.py."
)
