# Marketplace Pricing & Promotion Simulator

An interactive contribution-margin model for a marketplace/e-commerce
operator, built to answer the question every operator eventually gets
asked: **"if margins are low, what would you do?"**

Order volume, AOV, and promo frequency/depth are computed from real
transactions. Take rate, fulfillment cost, and payment processing fee
aren't in that data (it's a single retailer, not a marketplace), so
they're modeled as an explicit, adjustable layer on top -- the exact
levers a marketplace operator actually controls.

## What it answers

- What's the real contribution margin today, decomposed into take
  rate, payment fees, fulfillment cost, and promo cost?
- If we run a promo at X% penetration and Y% depth, how much order
  volume does it need to generate before it pays for itself?
- Which lever -- take rate, fulfillment cost, or promo depth -- moves
  margin the most from here?

## Data

[UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)
(CC BY 4.0, no login required): 824K real order line items / ~37K
orders from a UK-based online retailer, Dec 2009-Dec 2011, including
cancellations. `scripts/download_data.py` pulls it directly from
UCI's servers.

Promotions aren't labeled in the source data, so a line item is
flagged as a promo when its unit price sits 10%+ below that SKU's own
median price (`src/data_prep.py`) -- a real, order-level promo signal
derived from actual price variation, not a synthetic assumption.

## How the model works

```
GMV                  = real order volume x real AOV, adjusted for promo-driven demand lift
Platform revenue     = GMV x take rate
Payment fees         = GMV x payment fee %
Fulfillment cost     = orders x fulfillment cost per order
Promo cost           = GMV x promo penetration x promo depth
Contribution margin  = Platform revenue - Payment fees - Fulfillment cost - Promo cost
```

Every input on the right is a slider in the app. See
`src/margin_model.py` for the full logic.

## Run it

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python scripts/download_data.py
python src/data_prep.py
streamlit run app.py
```

## Structure

```
scripts/download_data.py   pulls the raw dataset from UCI (no login)
src/data_prep.py           cleans transactions, derives promo flags
src/margin_model.py        contribution-margin scenario engine
app.py                     Streamlit dashboard
```
