"""Fetch Dhan trade history and match fills into round trips (FIFO). No predictions, just your record."""
import os
import sys
import time
from collections import deque
from datetime import date, timedelta

import re
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
        "instrument": opt.notna().map({True: "OPTION", False: "FUTURE"}),
        "drvOptionType": opt,
        "drvStrikePrice": "",
        "exchangeTime": pd.to_datetime(when, errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S"),
    }, index=df.index).reset_index(drop=True)
    return add_zerodha_charges(out)


# Zerodha rates (zerodha.com/charges, checked Nov 2026); STT and exchange fee are stepped by date for older trades.
# These are ESTIMATES; your contract note is the truth.
NSE_OPT_TXN, BSE_OPT_TXN = 0.000311, 0.000325
STT_OPT_SELL, STT_FUT_SELL = 0.0015, 0.0005
SEBI, STAMP_OPT, STAMP_FUT, GST = 1e-6, 0.00003, 0.00002, 0.18


def add_zerodha_charges(d: pd.DataFrame) -> pd.DataFrame:
    """Estimate charges per fill. Options: Rs 20 per executed order; futures: lower of Rs 20 or 0.03%."""
    d = d.copy()
    q = pd.to_numeric(d["tradedQuantity"], errors="coerce")
    p = pd.to_numeric(d["tradedPrice"], errors="coerce")
    turn = (q * p).fillna(0.0)
    is_opt = d["drvOptionType"].notna()
    sell = d["transactionType"] == "SELL"
    order_turn = turn.groupby(d["orderId"]).transform("sum")
    cap = pd.Series(20.0, index=d.index).where(is_opt, (order_turn * 0.0003).clip(upper=20.0))
    share = (turn / order_turn.where(order_turn > 0, 1.0))
    brokerage = cap * share
    bse = d["customSymbol"].astype(str).str.upper().str.startswith(("SENSEX", "BANKEX"))
    when = pd.to_datetime(d["exchangeTime"] if "exchangeTime" in d else pd.Series(pd.NaT, index=d.index), errors="coerce")
    nse_rate = pd.Series(NSE_OPT_TXN, index=d.index)
    nse_rate = nse_rate.mask(when < "2026-04-01", 0.00035).mask(when < "2024-10-01", 0.000495)
    txn = turn * nse_rate.where(~bse, BSE_OPT_TXN).where(is_opt, 0.0000183)
    sebi = turn * SEBI
    d["brokerageCharges"] = brokerage
    d["exchangeTransactionCharges"] = txn
    d["sebiTax"] = sebi
    d["serviceTax"] = GST * (brokerage + txn + sebi)
    stt_opt = pd.Series(STT_OPT_SELL, index=d.index).mask(when < "2026-04-01", 0.001).mask(when < "2024-10-01", 0.000625)
    stt_fut = pd.Series(STT_FUT_SELL, index=d.index).mask(when < "2026-04-01", 0.0002).mask(when < "2024-10-01", 0.000125)
    d["stt"] = turn.where(sell, 0.0) * stt_opt.where(is_opt, stt_fut)
    d["stampDuty"] = turn.where(~sell, 0.0) * pd.Series(STAMP_OPT, index=d.index).where(is_opt, STAMP_FUT)
    return d


_MONTH = {**{str(i): i for i in range(1, 10)}, "O": 10, "N": 11, "D": 12}
_MON3 = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def parse_expiry(symbol: str):
    """Expiry date from a Zerodha option symbol, or None. Monthly symbols use the month end (approximate)."""
    s = str(symbol).upper()
    m = re.match(r"^[A-Z]+?(\d{2})([1-9OND])(\d{2})\d+(CE|PE)$", s)
    if m:
        try:
            return date(2000 + int(m.group(1)), _MONTH[m.group(2)], int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^[A-Z]+?(\d{2})([A-Z]{3})\d+(CE|PE)$", s)
    if m and m.group(2) in _MON3:
        y, mo = 2000 + int(m.group(1)), _MON3[m.group(2)]
        nxt = date(y + (mo == 12), mo % 12 + 1, 1)
        return nxt - timedelta(days=1)
    return None


def classify_open(open_lots: pd.DataFrame, today: date = None) -> pd.DataFrame:
    """Add expiry, expired flag, and the P&L if the option expired worth zero (an assumption, see report)."""
    if open_lots.empty:
        return open_lots
    today = today or date.today()
    o = open_lots.copy()
    o["expiry"] = o["symbol"].map(parse_expiry)
    o["expired"] = o["expiry"].map(lambda e: e is not None and e < today)
    o["side"] = o["sign"].map({1: "BOUGHT", -1: "SOLD"})
    o["pnl_if_zero"] = -o["sign"] * o["price"] * o["qty"]
    return o


def load_zerodha_many(paths) -> pd.DataFrame:
    """Read several tradebook files (or folders of them) and join them; repeated trades are dropped."""
    import glob
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "*.csv")) + glob.glob(os.path.join(p, "*.xlsx")))
        else:
            files += sorted(glob.glob(p)) or [p]
    if not files:
        sys.exit("No tradebook files found.")
    frames = []
    for f in files:
        d = load_zerodha(f)
        print(f"  read {os.path.basename(f)}: {len(d)} fills")
        frames.append(d)
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(subset=["exchangeTradeId", "orderId", "exchangeTime"], keep="first").reset_index(drop=True)
