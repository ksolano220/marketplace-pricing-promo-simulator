from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from scripts.download_data import RAW_DIR
from scripts.download_data import main as download_raw_data
from src.data_prep import main as build_processed_data
from src.margin_model import ScenarioInputs, baseline_metrics, find_breakeven_lift, run_scenario, sensitivity_ranking

PROCESSED_PATH = Path(__file__).parent / "data" / "processed" / "orders.parquet"

# Illustrative scenario presets only -- not any company's actual fulfillment economics.
FULFILLMENT_PRESETS = {
    "Owned fulfillment": 6.00,
    "Partner-fulfilled": 3.00,
}

st.set_page_config(page_title="Marketplace Pricing & Promotion Simulator", layout="wide")


@st.cache_data
def load_data() -> pd.DataFrame:
    # data/ is gitignored (raw + processed are both derived, not source-controlled),
    # so a fresh clone -- e.g. a cold Streamlit Cloud deploy -- has neither file yet.
    # Build them once here rather than requiring a manual pre-deploy step.
    if not PROCESSED_PATH.exists():
        with st.spinner("First run: downloading and processing the UCI dataset (~30s)..."):
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            download_raw_data()
            build_processed_data()
    return pd.read_parquet(PROCESSED_PATH)


df = load_data()
base = baseline_metrics(df)

st.title("Marketplace Pricing & Promotion Simulator")
st.caption(
    "Order volume and list-price AOV are computed from real transactions "
    "([UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii), "
    "37K real orders, 2009-2011). A line item counts as an **inferred promotional-pricing "
    "proxy** -- not proof a promotion ran -- when its price sits 10%+ below that SKU's own "
    "median observed price; a genuine price change over the two-year window could also "
    "trigger it. Take rate and payment fees apply to **customer-paid value** (post-discount), "
    "which is the convention this simulator uses. Fulfillment cost, promo economics, and the "
    "platform/merchant funding split are modeled as an adjustable marketplace-operator layer "
    "on top of that real order flow -- illustrative assumptions, not any specific company's "
    "figures. **This is a decision simulator, not a causal demand model:** incremental order "
    "lift among promo-exposed demand is an assumption you stress-test below, not an estimate "
    "inferred from the data."
)

st.subheader("Real baseline, from the data")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Orders", f"{base['orders']:,}")
c2.metric("Gross sales value", f"${base['gross_sales_value']:,.0f}", help="Actual price paid, before netting out cancellations.")
c3.metric("Net sales value", f"${base['net_sales_value']:,.0f}", f"-${base['cancelled_value']:,.0f} cancelled", help="Gross sales value minus cancelled-order value.")
c4.metric("AOV", f"${base['aov']:,.2f}")
c5.metric("Cancellation invoice rate", f"{base['cancellation_invoice_rate']:.1%}", help="Cancelled invoices / (sales invoices + cancelled invoices). Not a match-back rate against originating orders.")

st.line_chart(base["monthly_gross_sales_value"], x_label="Month", y_label="Gross sales value ($)")

st.divider()
st.subheader("Scenario: tune the marketplace economics")

col_left, col_right = st.columns([1, 2])

with col_left:
    st.markdown("**Platform economics**")
    take_rate_slider_pct = st.slider("Take rate", 5, 30, 15, 1, format="%d%%", help="Applied to customer-paid value.")
    take_rate = take_rate_slider_pct / 100
    payment_fee_slider_pct = st.slider("Payment processing fee", 1.0, 4.5, 2.9, 0.1, format="%.1f%%", help="Applied to customer-paid value.")
    payment_fee = payment_fee_slider_pct / 100

    fulfillment_preset = st.radio(
        "Fulfillment model", list(FULFILLMENT_PRESETS) + ["Custom"], index=2, horizontal=True,
    )
    if fulfillment_preset == "Custom":
        fulfillment_cost = st.slider("Fulfillment cost per order ($)", 0.0, 12.0, 4.5, 0.25)
    else:
        fulfillment_cost = FULFILLMENT_PRESETS[fulfillment_preset]
        st.caption(
            f"Illustrative assumption: \\${fulfillment_cost:.2f}/order for "
            f"{fulfillment_preset.lower()} -- a scenario preset, not a real company's figure."
        )

    st.markdown("**Promotion**")
    promo_exposed_gmv_share = st.slider(
        "Promo-exposed GMV share", 0.0, 0.50,
        float(round(base["promo_exposed_gmv_share"], 2)), 0.01,
        help="Share of gross basket value that is promo-exposed, weighted by dollars -- not the "
        "share of orders that merely contain a discounted item.",
    )
    promo_depth = st.slider(
        "Promo depth (discount on promo-exposed value)", 0.0, 0.50,
        float(round(base["gmv_weighted_promo_depth"], 2)), 0.01,
    )
    platform_funding_share = st.slider(
        "Platform-funded share of the discount", 0.0, 1.0, 1.0, 0.05,
        help="1.0 = platform funds the entire discount. Lower it to model a merchant- or "
        "vendor-co-funded promo, where the platform only absorbs part of it.",
    )
    incremental_lift = st.slider(
        "Incremental order lift among promo-exposed demand", 0.0, 0.50, 0.10, 0.01,
        help="Assumed extra order volume generated among promo-exposed demand specifically -- "
        "an assumption you're stress-testing, not a measured effect.",
    )

inputs = ScenarioInputs(
    take_rate=take_rate,
    payment_fee_pct=payment_fee,
    fulfillment_cost_per_order=fulfillment_cost,
    promo_exposed_gmv_share=promo_exposed_gmv_share,
    promo_depth=promo_depth,
    incremental_lift_promo_exposed=incremental_lift,
    platform_funding_share=platform_funding_share,
)
no_promo_inputs = ScenarioInputs(
    take_rate=take_rate,
    payment_fee_pct=payment_fee,
    fulfillment_cost_per_order=fulfillment_cost,
    promo_exposed_gmv_share=0.0,
    promo_depth=0.0,
    incremental_lift_promo_exposed=0.0,
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
            x=["Platform revenue", "Payment fees", "Fulfillment cost", "Platform-funded subsidy", "Contribution margin"],
            y=[
                with_promo.platform_revenue,
                -with_promo.payment_fees,
                -with_promo.fulfillment_costs,
                -with_promo.platform_funded_subsidy,
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

    if with_promo.promotional_discount > 0:
        st.caption(
            f"**Who funds the promo:** \\${with_promo.promotional_discount:,.0f} total discount = "
            f"\\${with_promo.platform_funded_subsidy:,.0f} platform-funded (the cost above) + "
            f"\\${with_promo.merchant_funded_subsidy:,.0f} merchant/vendor-funded (not a platform cost)."
        )

st.divider()
st.subheader("Does this promo pay for itself?")

breakeven = find_breakeven_lift(base, inputs)
if not breakeven["reachable"] and "no promo-exposed" in (breakeven["reason"] or ""):
    st.info("Set a promo-exposed GMV share above 0% to see breakeven analysis.")
elif not breakeven["reachable"]:
    st.error(
        f"At a {promo_depth:.0%} discount on {promo_exposed_gmv_share:.0%} of gross basket value "
        f"({platform_funding_share:.0%} platform-funded), this promo is **not reachable** "
        f"break-even: {breakeven['reason']}."
    )
elif breakeven["lift"] == 0.0:
    st.success("At these settings, the promo is contribution-margin-positive even with **zero** incremental demand lift.")
else:
    required = breakeven["lift"]
    assumed = incremental_lift
    verdict = "meets" if assumed >= required else "falls short of"
    caution = (
        " This scenario requires more than doubling promo-exposed demand to break even; "
        "assess whether that assumption is commercially realistic for your context."
        if required > 1.0
        else ""
    )
    st.markdown(
        f"At a **{promo_depth:.0%} discount** applied to **{promo_exposed_gmv_share:.0%} of gross "
        f"basket value** ({platform_funding_share:.0%} platform-funded), promoted demand needs to "
        f"generate at least **{required:.1%} incremental order lift** to break even on contribution "
        f"margin.{caution} Your assumed lift of **{assumed:.0%} {verdict}** that bar."
    )

st.subheader("Impact of practical operating changes")
st.caption(
    "Each row is one specific, independently-tested change from the current scenario -- not "
    "standardized units, so a \\$1/order fulfillment move and a 1-point take-rate move aren't "
    "directly comparable in size. The % column expresses each scenario's impact relative to "
    "current contribution margin. Because the tested input changes differ in magnitude, this "
    "should not be interpreted as normalized sensitivity. The promo-exposed GMV share row "
    "deliberately moves two things at once -- less promo cost and less assumed incremental "
    "volume -- because that's what the model says actually happens when exposure changes."
)
sens = sensitivity_ranking(base, inputs)
sens_df = pd.DataFrame(sens)
sens_df["label"] = sens_df["lever"] + " (" + sens_df["change"] + ")"
sens_fig = px.bar(sens_df, x="cm_delta", y="label", orientation="h")
sens_fig.update_layout(
    margin=dict(l=10, r=10, t=10, b=10), height=280,
    xaxis_title="Contribution margin impact ($)", yaxis_title="",
)
st.plotly_chart(sens_fig, use_container_width=True)
st.dataframe(
    sens_df[["lever", "change", "cm_delta", "cm_delta_pct_of_baseline"]].rename(
        columns={"cm_delta": "CM impact ($)", "cm_delta_pct_of_baseline": "CM impact (% of current CM)"}
    ).style.format({"CM impact ($)": "{:,.0f}", "CM impact (% of current CM)": "{:.1%}"}),
    use_container_width=True, hide_index=True,
)

st.divider()
st.caption(
    "Contribution margin = platform revenue - payment fees - fulfillment cost - platform-funded "
    "subsidy, where platform revenue and payment fees are computed on customer-paid value "
    "(gross basket value minus the total promotional discount), and only the platform-funded "
    "share of the discount is a cost to contribution margin. See src/margin_model.py."
)
