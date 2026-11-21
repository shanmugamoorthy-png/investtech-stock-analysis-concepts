"""Scan symbols with Dhan daily candles. Educational, not investment advice.

Usage:
  export DHAN_ACCESS_TOKEN=...        # never commit this
  export DHAN_CLIENT_ID=...           # optional, sent as client-id header
  python dhan_scanner.py --symbols symbols.csv --out results.csv
  python dhan_scanner.py --csv-dir ./candles   # offline: <symbol>.csv with date,open,high,low,close,volume
"""
import argparse
import os
import sys
import time
from datetime import date, timedelta

import pandas as pd
import requests

from indicators import range_break, read, trend_channel, volume_balance

URL = "https://api.dhan.co/v2/charts/historical"


def fetch_dhan(row, days: int = 700) -> pd.DataFrame:
    token = os.environ.get("DHAN_ACCESS_TOKEN")
    if not token:
        sys.exit("Set DHAN_ACCESS_TOKEN (see README).")
    headers = {"Content-Type": "application/json", "access-token": token}
    if os.environ.get("DHAN_CLIENT_ID"):
        headers["client-id"] = os.environ["DHAN_CLIENT_ID"]
    body = {
        "securityId": str(row.securityId),
        "exchangeSegment": row.exchangeSegment,
        "instrument": row.instrument,
        "expiryCode": 0,
        "oi": False,
        "fromDate": (date.today() - timedelta(days=days)).isoformat(),
        "toDate": date.today().isoformat(),
    }
    r = requests.post(URL, json=body, headers=headers, timeout=30)
    r.raise_for_status()
    d = r.json()
    if "close" not in d or not d["close"]:
        raise RuntimeError(f"no candles returned: {str(d)[:200]}")
    df = pd.DataFrame({k: d[k] for k in ("open", "high", "low", "close", "volume")})
    df.index = pd.to_datetime(d["timestamp"], unit="s")
    return df


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"], index_col="date").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def analyse(df: pd.DataFrame) -> dict:
    t = trend_channel(df["close"])
    vb = volume_balance(df)
    return {
        "last_close": round(float(df["close"].iloc[-1]), 2),
        "trend": t["direction"], "slope_ann_%": t["slope_ann_pct"], "r2": t["r2"],
        "channel_pos": t["channel_pos"], "floor": t["floor"], "ceiling": t["ceiling"],
        "outside_channel": t["outside"], "vol_balance": vb,
        "60d_break": range_break(df), "read": read(t, vb),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="symbols.csv")
    ap.add_argument("--csv-dir")
    ap.add_argument("--out", default="results.csv")
    a = ap.parse_args()
    rows = pd.read_csv(a.symbols, dtype=str).itertuples()
    out = []
    for row in rows:
        try:
            df = load_csv(os.path.join(a.csv_dir, f"{row.symbol}.csv")) if a.csv_dir else fetch_dhan(row)
            out.append({"symbol": row.symbol, **analyse(df)})
        except Exception as e:  # keep scanning other symbols
            print(f"{row.symbol}: skipped ({e})", file=sys.stderr)
        if not a.csv_dir:
            time.sleep(1)  # be gentle with rate limits
    res = pd.DataFrame(out)
    res.to_csv(a.out, index=False)
    show = ["symbol", "last_close", "trend", "channel_pos", "vol_balance", "60d_break", "read"]
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 60):
        print(res[show].to_string(index=False))
    print(f"\nFull details saved to {a.out}")


if __name__ == "__main__":
    main()
