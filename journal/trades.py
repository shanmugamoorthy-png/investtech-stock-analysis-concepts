"""Fetch Dhan trade history and match fills into round trips (FIFO). No predictions, just your record."""
import os
import sys
import time
from collections import deque
from datetime import date, timedelta

import warnings

import pandas as pd
import requests

warnings.filterwarnings("ignore", message="Could not infer format")

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
    sym = pd.Series("", index=df.index, dtype=object)
    for c in ("tradingSymbol", "customSymbol", "symbol"):
        if c in df:
            sym = sym.where(sym != "", df[c].fillna("").astype(str).replace("NA", ""))
    df["symbol"] = sym.where(sym != "", df["securityId"].astype(str))
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
                "symbol": t["symbol"], "securityId": sid,
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
                         "time": t["time"], "symbol": t["symbol"],
                         "option": t.get("drvOptionType"), "strike": t.get("drvStrikePrice")})
    open_lots = [dict(securityId=k, **l) for k, b in lots.items() for l in b]
    return pd.DataFrame(out), pd.DataFrame(open_lots)


def load_zerodha(path: str) -> pd.DataFrame:
    """Read a Zerodha Console tradebook (.csv or .xlsx) and shape it like the Dhan data. Charges are not in this file, so they are 0."""
    if str(path).lower().endswith((".xlsx", ".xls")):
        raw = pd.read_excel(path, header=None, dtype=str)
    else:
        import csv
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        width = max((len(r) for r in rows), default=0)
        raw = pd.DataFrame([r + [None] * (width - len(r)) for r in rows], dtype=object)
    hdr = None
    for i in range(min(len(raw), 60)):
        vals = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if "symbol" in vals and "trade_type" in vals:
            hdr = i
            break
    if hdr is None:
        sys.exit("This does not look like a Zerodha tradebook (no 'symbol' and 'trade_type' columns).")
    df = raw.iloc[hdr + 1:].copy()
    df.columns = [str(v).strip().lower() for v in raw.iloc[hdr].tolist()]
    df = df.dropna(subset=["symbol"])
    df = df[df["trade_type"].astype(str).str.lower().isin(["buy", "sell"])]
    sym = df["symbol"].astype(str).str.strip()
    opt = sym.str.extract(r"(CE|PE)$")[0].map({"CE": "CALL", "PE": "PUT"})
    seg = df["segment"].astype(str).str.upper() if "segment" in df else pd.Series("", index=df.index)
    when = df["order_execution_time"] if "order_execution_time" in df else df["trade_date"]
    out = pd.DataFrame({
        "orderId": df["order_id"].astype(str) if "order_id" in df else "",
        "exchangeTradeId": df["trade_id"].astype(str) if "trade_id" in df else range(len(df)),
        "transactionType": df["trade_type"].astype(str).str.upper(),
        "exchangeSegment": seg,
        "customSymbol": sym,
        "securityId": sym,
        "tradedQuantity": df["quantity"],
        "tradedPrice": df["price"],
        "instrument": seg.where(~seg.isin(["FO", "NFO"]), "OPTSTK"),
        "drvOptionType": opt,
        "drvStrikePrice": "",
        "exchangeTime": pd.to_datetime(when, errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S"),
    }, index=df.index).reset_index(drop=True)
    return out
