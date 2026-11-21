"""Build symbols.csv from stock names using Dhan's public instrument list.

python make_symbols.py [names.txt] [--master PATH_OR_URL]
Looks up each NSE equity by trading symbol, so you don't have to find security IDs.
Names it can't find are listed so you can check them. Always adds NIFTY 50 (index, id 13).
"""
import argparse
import io

import pandas as pd
import requests

MASTER = "https://images.dhan.co/api-data/api-scrip-master.csv"


def load_master(src: str) -> pd.DataFrame:
    if src.startswith("http"):
        r = requests.get(src, timeout=60)
        r.raise_for_status()
        src = io.StringIO(r.text)
    return pd.read_csv(src, low_memory=False, on_bad_lines="skip")


def build(names, master: pd.DataFrame):
    need = {"SEM_EXM_EXCH_ID", "SEM_SEGMENT", "SEM_SMST_SECURITY_ID", "SEM_TRADING_SYMBOL"}
    if not need <= set(master.columns):
        raise SystemExit(f"Unexpected instrument list columns: {list(master.columns)[:12]}")
    m = master[(master["SEM_EXM_EXCH_ID"] == "NSE") & (master["SEM_SEGMENT"] == "E")]
    if "SEM_INSTRUMENT_NAME" in m:
        m = m[m["SEM_INSTRUMENT_NAME"] == "EQUITY"]
    if "SEM_SERIES" in m:
        m = m[m["SEM_SERIES"] == "EQ"]
    rows = [("NIFTY 50", "13", "IDX_I", "INDEX")]
    missing = []
    for n in names:
        hit = m[m["SEM_TRADING_SYMBOL"].astype(str).str.upper() == n.upper()]
        if hit.empty:
            missing.append(n)
        else:
            rows.append((n, str(int(hit.iloc[0]["SEM_SMST_SECURITY_ID"])), "NSE_EQ", "EQUITY"))
    return pd.DataFrame(rows, columns=["symbol", "securityId", "exchangeSegment", "instrument"]), missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="?", default="large_caps.txt")
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--out", default="symbols.csv")
    a = ap.parse_args()
    names = [l.strip() for l in open(a.names) if l.strip()]
    df, missing = build(names, load_master(a.master))
    df.to_csv(a.out, index=False)
    print(f"Wrote {len(df)} symbols to {a.out}")
    if missing:
        print("Not found (skipped):", ", ".join(missing))


if __name__ == "__main__":
    main()
