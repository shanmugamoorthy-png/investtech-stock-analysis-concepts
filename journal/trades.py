"""Fetch Dhan trade history and match fills into round trips (FIFO). No predictions, just your record."""
import os
import sys
import time
from collections import deque
from datetime import date, timedelta

import pandas as pd
import requests

BASE = "https://api.dhan.co/v2/trades"
CHARGE_COLS = ["sebiTax", "stt", "brokerageCharges", "serviceTax", "exchangeTransactionCharges", "stampDuty"]


def fetch_trades(days: int = 180, chunk: int = 31) -> pd.DataFrame:
    token = os.environ.get("DHAN_ACCESS_TOKEN")
    if not token:
        sys.exit("Set DHAN_ACCESS_TOKEN first.")
    headers = {"Accept": "application/json", "access-token": token}
    rows, end = [], date.today()
    start_all = end - timedelta(days=days)
    while end >= start_all:
        start = max(start_all, end - timedelta(days=chunk - 1))
        for page in range(0, 200):
            r = requests.get(f"{BASE}/{start}/{end}/{page}", headers=headers, timeout=30)
            if r.status_code != 200:
                print(f"{start}..{end} page {page}: HTTP {r.status_code} {r.text[:150]}", file=sys.stderr)
                break
            data = r.json()
            if not isinstance(data, list) or not data:
                break
            rows.extend(data)
            time.sleep(0.4)
        end = start - timedelta(days=1)
    return pd.DataFrame(rows)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise types. Keeps the first of any duplicated exchangeTradeId."""
    if df.empty:
        return df
    df = df.copy()
    if "exchangeTradeId" in df:
        df = df.drop_duplicates(subset=["exchangeTradeId", "orderId"], keep="first")
    for c in CHARGE_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0) if c in df else 0.0
    df["charges"] = df[CHARGE_COLS].sum(axis=1)
    df["tradedQuantity"] = pd.to_numeric(df["tradedQuantity"], errors="coerce")
    df["tradedPrice"] = pd.to_numeric(df["tradedPrice"], errors="coerce")
    t = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for alt in ("exchangeTime", "updateTime", "createTime"):
        if alt in df:
            t = t.fillna(pd.to_datetime(df[alt], errors="coerce"))  # "NA" strings become NaT
    df["time"] = t
    df = df.dropna(subset=["tradedQuantity", "tradedPrice"])
    return df.sort_values(["time", "exchangeTradeId"], kind="stable").reset_index(drop=True)


def round_trips(df: pd.DataFrame):
    """FIFO match per contract. Returns (closed round trips, still-open lots)."""
    lots, out = {}, []
    for _, t in df.iterrows():
        sid = str(t["securityId"])
        sign = 1 if str(t["transactionType"]).upper() == "BUY" else -1
        q = float(t["tradedQuantity"])
        unit_chg = float(t["charges"]) / q if q else 0.0
        book = lots.setdefault(sid, deque())
        while q > 0 and book and book[0]["sign"] == -sign:
            lot = book[0]
            m = min(q, lot["qty"])
            gross = (t["tradedPrice"] - lot["price"]) * m * lot["sign"]
            chg = (lot["unit_chg"] + unit_chg) * m
            out.append({
                "symbol": t.get("tradingSymbol") or t.get("customSymbol"), "securityId": sid,
                "direction": "LONG" if lot["sign"] == 1 else "SHORT",
                "option": t.get("drvOptionType"), "strike": t.get("drvStrikePrice"),
                "qty": m, "entry_time": lot["time"], "exit_time": t["time"],
                "entry_price": lot["price"], "exit_price": t["tradedPrice"],
                "gross": gross, "charges": chg, "net": gross - chg})
            lot["qty"] -= m
            q -= m
            if lot["qty"] <= 1e-9:
                book.popleft()
        if q > 0:
            book.append({"sign": sign, "qty": q, "price": t["tradedPrice"], "unit_chg": unit_chg,
                         "time": t["time"], "symbol": t.get("tradingSymbol") or t.get("customSymbol"),
                         "option": t.get("drvOptionType"), "strike": t.get("drvStrikePrice")})
    open_lots = [dict(securityId=k, **l) for k, b in lots.items() for l in b]
    return pd.DataFrame(out), pd.DataFrame(open_lots)
