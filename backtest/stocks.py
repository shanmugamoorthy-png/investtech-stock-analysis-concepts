"""Backtest the six strategies on many F&O stocks (15-minute candles). Records and statistics only; no predictions.

python stocks.py --limit 50 --out-dir /content/drive/MyDrive/backtest_stocks
python stocks.py --demo
Results are basis points (bps, 1 bp = 0.01%) per trade of the stock's own price move, after a round-trip cost.
This tests trading the stock itself (or its future). Stock OPTIONS add wider spreads and time decay, so they would do worse.
"""
import argparse
import io
import os
import sys

import numpy as np
import pandas as pd
import requests

from data import detect_clock, fetch_index, to_time
from demo import make_demo
from engine import MIN_PF, MIN_TRADES, WINDOWS, Market, metrics, random_pool, run_strategy, verdict
from strategies import STRATEGIES

MASTER = "https://images.dhan.co/api-data/api-scrip-master.csv"


def fno_universe(master_src=MASTER) -> pd.DataFrame:
    """Stocks with futures today, with their NSE equity security ids. Uses Dhan's public instrument list."""
    if master_src.startswith("http"):
        r = requests.get(master_src, timeout=90)
        r.raise_for_status()
        master_src = io.StringIO(r.text)
    m = pd.read_csv(master_src, low_memory=False, on_bad_lines="skip")
    need = {"SEM_EXM_EXCH_ID", "SEM_SEGMENT", "SEM_SMST_SECURITY_ID", "SEM_INSTRUMENT_NAME", "SEM_TRADING_SYMBOL"}
    if not need <= set(m.columns):
        sys.exit(f"Unexpected instrument list columns: {list(m.columns)[:12]}")
    fut = m[(m["SEM_EXM_EXCH_ID"] == "NSE") & (m["SEM_INSTRUMENT_NAME"] == "FUTSTK")]
    ts = fut["SEM_TRADING_SYMBOL"].astype(str).str.upper()
    base = ts.str.replace(r"-[A-Z]{3}\d{4}-FUT$", "", regex=True)      # BAJAJ-AUTO-NOV2026-FUT -> BAJAJ-AUTO
    base = base.where(base != ts, ts.str.split("-").str[0])
    names = sorted(set(base))
    if not names:
        sys.exit("Could not find stock futures in Dhan's instrument list.")
    eq = m[(m["SEM_EXM_EXCH_ID"] == "NSE") & (m["SEM_SEGMENT"] == "E")]
    if "SEM_INSTRUMENT_NAME" in eq:
        eq = eq[eq["SEM_INSTRUMENT_NAME"] == "EQUITY"]
    if "SEM_SERIES" in eq:
        eq = eq[eq["SEM_SERIES"] == "EQ"]
    eq = eq.assign(sym=eq["SEM_TRADING_SYMBOL"].astype(str).str.upper()).drop_duplicates("sym").set_index("sym")
    rows = [(n, str(int(eq.loc[n, "SEM_SMST_SECURITY_ID"]))) for n in names if n in eq.index]
    if not rows:
        sys.exit(f"No futures name matched an NSE equity. Sample futures symbols: {list(ts.head(5))}. Send me this line.")
    return pd.DataFrame(rows, columns=["symbol", "securityId"])


def load_stock(sym, sec, days, interval, out_dir, refresh=False):
    p = os.path.join(out_dir, f"stk_{sym}_{interval}m.csv")
    if refresh or not os.path.exists(p) or os.path.getsize(p) < 50:
        d = fetch_index(days, interval, sec, "NSE_EQ", "EQUITY")
        if d.empty:
            return None
        d.to_csv(p, index=False)
    d = pd.read_csv(p)
    try:
        d["time"] = to_time(d["timestamp"], detect_clock(d["timestamp"]))
    except SystemExit:
        return None
    d = d.drop(columns=["timestamp"])
    mins = d["time"].dt.hour * 60 + d["time"].dt.minute
    d = d[mins.between(9 * 60 + 15, 15 * 60 + 15)].reset_index(drop=True)
    return d if len(d) > 2000 else None


def evaluate_many(markets, seed=0, draws=1000):
    days = sorted({dd for mk in markets.values() for dd in mk.df["date"]})
    cut = days[int(len(days) * 0.7)]
    trades, pools = [], []
    for sym, mk in markets.items():
        for name, fn in STRATEGIES.items():
            sig = fn(mk.df)
            for wname, wstart in WINDOWS.items():
                t = run_strategy(mk, sig, wstart)
                if len(t):
                    t["stock"], t["strategy"], t["window"] = sym, name, wname
                    trades.append(t)
        p = random_pool(mk)
        p["stock"] = sym
        pools.append(p)
    trades = pd.concat(trades, ignore_index=True)
    trades["date"] = pd.to_datetime(trades["entry_time"]).dt.date
    pool = pd.concat(pools, ignore_index=True)
    pool["date"] = pd.to_datetime(pool["entry_time"]).dt.date
    rng = np.random.default_rng(seed)
    out = []
    for name in STRATEGIES:
        for wname, wstart in WINDOWS.items():
            t = trades[(trades["strategy"] == name) & (trades["window"] == wname)]
            a, b = t[t["date"] < cut], t[t["date"] >= cut]
            pm = pool[(pool["date"] >= cut) & (pool["minute"] >= wstart)]["pnl"].to_numpy()
            if len(b) and len(pm):
                means = rng.choice(pm, size=(draws, len(b))).mean(axis=1)
                r95, rmean = float(np.percentile(means, 95)), float(means.mean())
            else:
                r95 = rmean = np.nan
            per = b.groupby("stock")["pnl"].agg(["size", "sum"])
            per = per[per["size"] >= 5]
            pos = round(float((per["sum"] > 0).mean() * 100), 0) if len(per) else np.nan
            ma, mb = metrics(a["pnl"]), metrics(b["pnl"])
            out.append({"strategy": name, "entries": wname,
                        "first_n": ma["trades"], "first_avg_bps": ma["expectancy"], "first_pf": ma["pf"],
                        "last_n": mb["trades"], "last_avg_bps": mb["expectancy"], "last_pf": mb["pf"],
                        "random_avg": round(rmean, 2), "random_95th": round(r95, 2), "stocks_positive_%": pos,
                        "verdict": verdict(ma, mb, r95)})
    return pd.DataFrame(out), trades, cut


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50, help="how many F&O stocks (picked at random, fixed seed, not by performance); 0 = all")
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--cost-bps", type=float, default=8.0, help="round-trip cost in basis points of price")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out-dir", default="out_stocks")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    markets = {}
    if a.demo:
        for s in range(4):
            idx, _ = make_demo(days=300, seed=10 + s)
            markets[f"DEMO{s}"] = Market(idx, None, "return", cost_bps=a.cost_bps)
    else:
        uni = fno_universe()
        print(f"F&O stocks found: {len(uni)}")
        if a.limit and a.limit < len(uni):
            uni = uni.sample(a.limit, random_state=0).sort_values("symbol")
        done = skipped = 0
        for _, r in uni.iterrows():
            d = load_stock(r["symbol"], r["securityId"], a.days, 15, a.out_dir, a.refresh)
            if d is None:
                skipped += 1
                continue
            markets[r["symbol"]] = Market(d, None, "return", cost_bps=a.cost_bps)
            done += 1
            if done % 10 == 0:
                print(f"  loaded {done} stocks ...")
        print(f"Loaded {done} stocks, skipped {skipped} (no data).")
    if not markets:
        sys.exit("No stock data loaded.")
    res, trades, cut = evaluate_many(markets)
    res.to_csv(os.path.join(a.out_dir, "stocks_results.csv"), index=False)
    trades.drop(columns=["date"]).to_csv(os.path.join(a.out_dir, "stocks_trades.csv"), index=False)
    print(f"\n{len(markets)} stocks, first period before {cut}, last period {cut} onward.")
    print(f"Average result per trade in basis points (1 bp = 0.01% of the stock price) after {a.cost_bps} bps round-trip cost.\n")
    print(res.drop(columns=["verdict"]).to_string(index=False))
    print("\nChecks:")
    for _, r in res.iterrows():
        print(f"  {r['strategy']} / {r['entries']}: {r['verdict']}")
    passed = int((res["verdict"] == "PASSES all checks").sum())
    print(f"\n{passed} of {len(res)} combinations passed. With {len(res)} tried, one or two passing by luck is expected.")
    print("Stocks were picked at random from today's F&O list, so stocks that joined it because they did well are over-represented.")


if __name__ == "__main__":
    main()
