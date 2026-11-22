"""Fetch NIFTY 15-minute candles and expired weekly option prices from Dhan. Cached as CSV so reruns are fast."""
import os
import sys
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

BASE = "https://api.dhan.co/v2/charts"
CLOCKS = {"unix_utc": 0, "unix_ist": 19800, "dhan1980_utc": 315532800, "dhan1980_ist": 315532800 + 19800}


def _headers():
    token = os.environ.get("DHAN_ACCESS_TOKEN")
    if not token:
        sys.exit("Set DHAN_ACCESS_TOKEN first.")
    return {"Accept": "application/json", "Content-Type": "application/json", "access-token": token}


def _post(path, body):
    for attempt in range(4):
        r = requests.post(f"{BASE}/{path}", json=body, headers=_headers(), timeout=90)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        print(f"  {path} {body.get('fromDate')}: HTTP {r.status_code} {r.text[:150]}", file=sys.stderr)
        return None
    return None


def detect_clock(epoch) -> str:
    """Dhan epoch values can be unix or 1980-based, UTC or IST. Pick the reading where days start at 09:15."""
    epoch = np.asarray(epoch, dtype="int64")
    best, best_score = None, -1.0
    for name, off in CLOCKS.items():
        t = pd.Series(pd.to_datetime(epoch + off, unit="s", errors="coerce"))
        if t.isna().any():
            continue
        first = t.groupby(t.dt.date).min()
        score = float((first.dt.strftime("%H:%M") == "09:15").mean())
        if score > best_score:
            best, best_score = name, score
    if best is None or best_score < 0.5:
        raise SystemExit(f"Could not read Dhan timestamps (first values: {list(epoch[:3])}). Send me this line.")
    return best


def to_time(epoch, clock: str) -> pd.Series:
    return pd.Series(pd.to_datetime(np.asarray(epoch, dtype="int64") + CLOCKS[clock], unit="s"))


def fetch_index(days: int, interval: int = 15) -> pd.DataFrame:
    rows, end = [], date.today()
    start_all = end - timedelta(days=days)
    while end >= start_all:
        start = max(start_all, end - timedelta(days=84))
        body = {"securityId": "13", "exchangeSegment": "IDX_I", "instrument": "INDEX", "interval": interval,
                "oi": False, "fromDate": f"{start} 09:15:00", "toDate": f"{end} 15:30:00"}
        j = _post("intraday", body)
        if j and j.get("timestamp"):
            rows.append(pd.DataFrame({k: j[k] for k in ("timestamp", "open", "high", "low", "close", "volume") if k in j}))
        time.sleep(0.4)
        end = start - timedelta(days=1)
    if not rows:
        sys.exit("No index candles returned.")
    d = pd.concat(rows, ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
    return d.reset_index(drop=True)


def fetch_rolling(days: int, side: str, offset: int, interval: int, expiry_flag: str, expiry_code: int) -> pd.DataFrame:
    strike = "ATM" if offset == 0 else f"ATM{offset:+d}"
    key = "ce" if side == "CALL" else "pe"
    rows, today = [], date.today()
    s = today - timedelta(days=days)
    while s <= today:
        e = min(s + timedelta(days=29), today + timedelta(days=1))
        body = {"exchangeSegment": "NSE_FNO", "interval": interval, "securityId": "13", "instrument": "OPTIDX",
                "expiryFlag": expiry_flag, "expiryCode": expiry_code, "strike": strike, "drvOptionType": side,
                "requiredData": ["open", "high", "low", "close", "volume", "strike", "spot"],
                "fromDate": str(s), "toDate": str(e)}
        j = _post("rollingoption", body)
        blk = ((j or {}).get("data") or {}).get(key)
        if blk and blk.get("timestamp"):
            rows.append(pd.DataFrame({k: blk[k] for k in ("timestamp", "open", "high", "low", "close", "strike", "spot") if k in blk}))
        time.sleep(0.4)
        s = e
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def load_all(days, interval, out_dir, offsets, expiry_flag, expiry_code, want_options, refresh=False):
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, f"index_{interval}m.csv")
    if refresh or not os.path.exists(p):
        print("Fetching NIFTY index candles ...")
        fetch_index(days, interval).to_csv(p, index=False)
    idx = pd.read_csv(p)
    clock = detect_clock(idx["timestamp"])
    print(f"Index candles: {len(idx)} bars, clock reading = {clock}")
    idx["time"] = to_time(idx["timestamp"], clock)
    idx = idx.drop(columns=["timestamp"])
    idx = idx[(idx["time"].dt.hour * 60 + idx["time"].dt.minute).between(9 * 60 + 15, 15 * 60 + 15)].reset_index(drop=True)
    opt = {}
    if want_options:
        for side in ("CALL", "PUT"):
            for off in offsets:
                q = os.path.join(out_dir, f"opt_{side}_{off:+d}_{interval}m_{expiry_flag}{expiry_code}.csv")
                if refresh or not os.path.exists(q):
                    print(f"Fetching {side} ATM{off:+d} ...")
                    fetch_rolling(days, side, off, interval, expiry_flag, expiry_code).to_csv(q, index=False)
                try:
                    d = pd.read_csv(q)
                except pd.errors.EmptyDataError:
                    d = pd.DataFrame()
                if d.empty:
                    continue
                d["time"] = to_time(d["timestamp"], clock)
                opt[(side, off)] = d.drop(columns=["timestamp"]).drop_duplicates("time").set_index("time")
    return idx, opt
