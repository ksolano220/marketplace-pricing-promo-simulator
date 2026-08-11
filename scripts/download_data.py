"""
Downloads the UCI "Online Retail II" dataset (public, no login required).
Source: https://archive.ics.uci.edu/dataset/502/online+retail+ii
License: CC BY 4.0

Real transaction-level order data from a UK-based online retailer,
Dec 2009 - Dec 2011: invoice, SKU, quantity, unit price, customer ID,
country, and timestamp for every line item, including cancellations.
"""

import io
import zipfile
from pathlib import Path

import requests

URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    target = RAW_DIR / "online_retail_II.xlsx"
    if target.exists():
        print(f"Already downloaded: {target}")
        return

    print("Downloading Online Retail II dataset from UCI...")
    resp = requests.get(URL, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(RAW_DIR)

    print(f"Saved to {target}")


if __name__ == "__main__":
    main()
