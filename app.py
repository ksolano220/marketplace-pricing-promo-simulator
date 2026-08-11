from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.margin_model import ScenarioInputs, baseline_metrics, find_breakeven_lift, run_scenario, sensitivity_ranking

PROCESSED_PATH = Path(__file__).parent / "data" / "processed" / "orders.parquet"

FULFILLMENT_PRESETS = {
    "Owned fulfillment": 6.00,
    "Partner-fulfilled": 3.00,
}

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
    "824K line items / 37K orders, 2009-2011). A line item counts as an **inferred "
    "promotional-pricing proxy** when its price sits 10%+ below that SKU's own median "
    "price -- a proxy, not proof a promotion ran. Take rate, fulfillment cost, payment "
    "fees, and promo funding are modeled as an adjustable marketplace-operator layer on "
    "top of that real order flow. **This is a decision simulator, not a causal demand "
    "model:** promo-driven demand lift is an assumption you stress-test below, not an "
    "estimate inferred from the data."
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
    take_rate_slider_pct = st.slider("Take rate", 5, 30, 15, 1, format="%d%%")
    take_rate = take_rate_slider_pct / 100
    payment_fee_slider_pct = st.slider("Payment processing fee", 1.0, 4.5, 2.9, 0.1, format="%.1f%%")
    payment_fee = payment_fee_slider_pct / 100

    fulfillment_preset = st.radio(
        "Fulfillment model", list(FULFILLMENT_PRESETS) + ["Custom"], index=2, horizontal=True,
    )
    if fulfillment_preset == "Custom":
        fulfillment_cost = st.slider("Fulfillment cost per order ($)", 0.0, 12.0, 4.5, 0.25)
    else:
        fulfillment_cost = FULFILLMENT_PRESETS[fulfillment_preset]
        st.caption(
            f"Illustrative assumption: ${fulfillment_cost:.2f}/order for "
            f"{fulfillment_preset.lower()} (not company-specific figures)."
        )

    st.markdown("**Promotion**")
    promo_penetration = st.slider(
        "Promo penetration (% of orders)", 0.0, 0.50,
        float(round(base["promo_penetration"], 2)), 0.01,
    )
    promo_depth = st.slider(
        "Promo depth (avg discount)", 0.0, 0.50,
        float(round(base["avg_promo_depth"], 2)), 0.01,
    )
    platform_funding_share = st.slider(
        "Platform-funded share of promo cost", 0.0, 1.0, 1.0, 0.05,
        help="1.0 = platform eats the full discount. Lower it to model a merchant- or "
        "vendor-co-funded promo, where the platform only absorbs part of the cost.",
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
    platform_funding_share=platform_funding_share,
)
no_promo_inputs = ScenarioInputs(
    take_rate=take_rate,
    payment_fee_pct=payment_fee,
    fulfillment_cost_per_order=fulfillment_cost,
    promo_penetration=0.0,
    promo_depth=0.0,
    promo_demand_lift=0.0,
    platform_funding_share=platform_funding_share,
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
st.subheader("Does this promo pay for itself?")

breakeven = find_breakeven_lift(base, inputs)
if not breakeven["reachable"]:
    st.error(
        f"At a {promo_depth:.0%} discount on {promo_penetration:.0%} of orders "
        f"({platform_funding_share:.0%} platform-funded), this promo is **not reachable** "
        f"break-even: {breakeven['reason']}."
    )
elif breakeven["lift"] == 0.0:
    st.success(
        f"At these settings, the promo is contribution-margin-positive even with **zero** "
        f"incremental demand lift."
    )
else:
    required = breakeven["lift"]
    assumed = demand_lift
    verdict = "meets" if assumed >= required else "falls short of"
    st.markdown(
        f"At a **{promo_depth:.0%} discount** applied to **{promo_penetration:.0%} of orders** "
        f"({platform_funding_share:.0%} platform-funded), promoted orders need to generate at "
        f"least **{required:.1%} incremental volume** to break even on contribution margin. "
        f"Your assumed demand lift of **{assumed:.0%} {verdict}** that bar."
    )

st.subheader("Which lever moves margin the most?")
st.caption("Standardized one-unit bumps from the current scenario, ranked by contribution-margin impact.")
sens = sensitivity_ranking(base, inputs)
sens_df = pd.DataFrame(sens)
sens_fig = px.bar(sens_df, x="cm_delta", y="lever", orientation="h")
sens_fig.update_layout(
    margin=dict(l=10, r=10, t=10, b=10), height=280,
    xaxis_title="Contribution margin impact ($)", yaxis_title="",
)
st.plotly_chart(sens_fig, use_container_width=True)

st.divider()
st.caption(
    "Contribution margin = platform revenue (GMV x take rate) - payment fees - fulfillment "
    "cost - promo cost, where promo cost = GMV x promo penetration x promo depth x platform-"
    "funded share, and order volume responds to promo penetration x demand lift. "
    "See src/margin_model.py."
)
