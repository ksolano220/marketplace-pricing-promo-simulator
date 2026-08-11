# Marketplace Pricing & Promotion Simulator

An interactive contribution-margin model for a marketplace/e-commerce
operator, built to answer the question every operator eventually gets
asked: **"if margins are low, what would you do?"**

![Dashboard screenshot](assets/dashboard.png)

Order volume, AOV, and promo frequency/depth are computed from real
transactions. Take rate, fulfillment cost, payment processing fee, and
promo funding split aren't in that data (it's a single retailer, not a
marketplace), so they're modeled as an explicit, adjustable layer on
top -- the exact levers a marketplace operator actually controls.

**This is a decision simulator, not a causal demand model.**
Promo-driven demand lift is an assumption you supply and stress-test,
not an estimate inferred from observational pricing data.

## What it answers

- What's the real contribution margin today, decomposed into take
  rate, payment fees, fulfillment cost, and promo cost?
- If we run a promo at X% penetration and Y% depth, how much
  incremental order volume does it actually need to break even on
  contribution margin -- computed directly, not eyeballed off a slider?
- Which lever -- take rate, fulfillment cost, payment fee, or promo
  depth/penetration -- moves margin the most from here, ranked by a
  standardized one-unit bump to each?
- How does the picture change if a promo is fully platform-funded vs.
  shared with a merchant/vendor, or if fulfillment is owned vs.
  partner-fulfilled?

## Data

[UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)
(CC BY 4.0, no login required): 824K real order line items / ~37K
orders from a UK-based online retailer, Dec 2009-Dec 2011, including
cancellations. `scripts/download_data.py` pulls it directly from
UCI's servers.

Promotions aren't labeled in the source data, so a line item is
flagged as an **inferred promotional-pricing proxy** when its unit
price sits 10%+ below that SKU's own median observed price across the
dataset (`src/data_prep.py`). That's a real, order-level pricing
signal, but it's a proxy, not proof a promotion ran -- a price
difference could also reflect a bulk-order discount or a genuine
list-price change over the two-year window.

## How the model works

```
GMV                  = real order volume x real AOV, adjusted for promo-driven demand lift
Platform revenue     = GMV x take rate
Payment fees         = GMV x payment fee %
Fulfillment cost     = orders x fulfillment cost per order
Promo cost           = GMV x promo penetration x promo depth x platform-funded share
Contribution margin  = Platform revenue - Payment fees - Fulfillment cost - Promo cost
```

Every input on the right is a slider in the app, including fulfillment
model presets (owned vs. partner-fulfilled, both illustrative
assumptions, not company-specific figures) and a platform-funded-share
slider for modeling co-funded promos. See `src/margin_model.py` for
the full logic, including `find_breakeven_lift` (solves for the
minimum demand lift a promo needs to break even, reusing the same
scenario function the sliders call, so it can't drift out of sync) and
`sensitivity_ranking` (standardized one-unit bumps to each lever,
ranked by contribution-margin impact).

## Run it

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python scripts/download_data.py
python src/data_prep.py
streamlit run app.py
```

## Tests

```bash
pytest tests/
```

Covers: zero promo penetration produces zero promo cost, a fulfillment
cost bump reduces contribution margin by exactly the expected amount, a
take-rate bump increases platform revenue by exactly the expected
amount, zero GMV doesn't divide by zero, platform funding share scales
promo cost linearly, breakeven-lift solves to the actual CM-parity
crossing point, breakeven correctly reports "unreachable" when a promo
is structurally margin-dilutive at any volume, and the sensitivity
ranking sorts by impact magnitude.

## Structure

```
scripts/download_data.py   pulls the raw dataset from UCI (no login)
src/data_prep.py           cleans transactions, derives the promo proxy
src/margin_model.py        contribution-margin scenario engine, breakeven solver, sensitivity ranking
app.py                     Streamlit dashboard
tests/test_margin_model.py unit tests
```
