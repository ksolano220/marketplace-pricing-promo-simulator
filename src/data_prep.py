"""
Cleans the raw Online Retail II export and derives the fields the
pricing/promo model needs: real order economics plus an inferred
promotional-pricing proxy (no promo field exists in the source data,
so a line item is flagged when its unit price sits at least 10%
below that SKU's own median observed price across the dataset). This
is a proxy, not proof a promotion ran -- a price difference could
also reflect a bulk-order discount, a data-entry variance, or a
genuine list-price change over the two-year window.
"""

from pathlib import Path

import pandas as pd

RAW_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "online_retail_II.xlsx"
PROCESSED_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "orders.parquet"

PROMO_DISCOUNT_THRESHOLD = 0.10  # >=10% below a SKU's reference price counts as a promo


def load_raw() -> pd.DataFrame:
    sheets = pd.read_excel(RAW_PATH, sheet_name=["Year 2009-2010", "Year 2010-2011"])
    df = pd.concat(sheets.values(), ignore_index=True)
    df.columns = [c.strip().replace(" ", "_") for c in df.columns]
    df["StockCode"] = df["StockCode"].astype(str)
    df["Description"] = df["Description"].astype(str)
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=["Customer_ID"]).copy()
    df["Invoice"] = df["Invoice"].astype(str)
    df["is_cancelled"] = df["Invoice"].str.startswith("C")

    # Genuine order lines only: positive qty/price for sales, negative qty for cancellations
    sales = df[(~df["is_cancelled"]) & (df["Quantity"] > 0) & (df["Price"] > 0)].copy()
    cancels = df[df["is_cancelled"] & (df["Quantity"] < 0)].copy()
    df = pd.concat([sales, cancels], ignore_index=True)

    df["revenue"] = df["Quantity"] * df["Price"]
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    df["month"] = df["InvoiceDate"].dt.to_period("M").dt.to_timestamp()
    return df


def flag_promos(df: pd.DataFrame) -> pd.DataFrame:
    sales = df[~df["is_cancelled"]].copy()
    ref_price = (
        sales.groupby("StockCode")["Price"]
        .median()
        .rename("reference_price")
    )
    df = df.merge(ref_price, on="StockCode", how="left")
    df["promo_depth"] = 1 - (df["Price"] / df["reference_price"])
    df["is_promo"] = (~df["is_cancelled"]) & (df["promo_depth"] >= PROMO_DISCOUNT_THRESHOLD)
    df["promo_depth"] = df["promo_depth"].clip(lower=0)
    return df


def main() -> None:
    df = load_raw()
    df = clean(df)
    df = flag_promos(df)
    PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PROCESSED_PATH, index=False)
    print(f"Processed {len(df):,} line items -> {PROCESSED_PATH}")
    print(f"Orders: {df.loc[~df.is_cancelled, 'Invoice'].nunique():,}")
    print(f"Promo-flagged line items: {df['is_promo'].sum():,} ({df['is_promo'].mean():.1%})")


if __name__ == "__main__":
    main()
