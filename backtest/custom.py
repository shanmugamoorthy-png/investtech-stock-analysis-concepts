"""Test ONE rule set of your own on NIFTY candles. Records and statistics only; not a prediction.

Example: buy when price closes above the first 15 minutes' high, sell when below its low, stop 30 points, target 45.
python custom.py --entry orb --range-minutes 15 --stop 30 --target 45 --out-dir /content/drive/MyDrive/backtest
"""
import argparse
import os

import numpy as np
import pandas as pd

from data import load_all
from demo import make_demo
from engine import MIN_PF, MIN_TRADES, Market, metrics, random_pool, run_strategy, split_date, verdict
from strategies import WARMUP, prev_day_break


def orb_n(df, n_bars):
    """First close beyond the high/low of the first n_bars of the day (once per direction per day)."""
    sig = np.zeros(len(df))
    c, h, l = df["close"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
    for _, idx in df.groupby("date").indices.items():
        if len(idx) <= n_bars + 1:
            continue
        hi, lo = h[idx[:n_bars]].max(), l[idx[:n_bars]].min()
        up = dn = False
        for i in idx[n_bars:]:
            if not up and c[i] > hi:
                sig[i], up = 1, True
            elif not dn and c[i] < lo:
                sig[i], dn = -1, True
    sig[:WARMUP] = 0
    return sig.astype(np.int8)


def max_drawdown(p):
    cum = p.cumsum()
    return float((cum.cummax() - cum).max()) if len(p) else 0.0


def describe(p):
    m = metrics(p)
    w, lo = p[p > 0], p[p <= 0]
    m["avg_win"] = round(float(w.mean()), 1) if len(w) else 0.0
    m["avg_loss"] = round(float(lo.mean()), 1) if len(lo) else 0.0
    m["max_drawdown"] = round(max_drawdown(p), 0)
    return m


def hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", choices=["orb", "prevday"], default="orb", help="orb = break of the opening range; prevday = break of previous day high/low")
    ap.add_argument("--range-minutes", type=int, default=15, help="opening range length in minutes (orb)")
    ap.add_argument("--stop", type=float, default=30.0, help="stop distance in index points")
    ap.add_argument("--target", type=float, default=45.0, help="target distance in index points")
    ap.add_argument("--max-hold-minutes", type=int, default=120)
    ap.add_argument("--earliest", default="10:00", help="earliest entry time HH:MM")
    ap.add_argument("--latest", default="14:30", help="latest entry time HH:MM")
    ap.add_argument("--max-trades-per-day", type=int, default=2)
    ap.add_argument("--direction", choices=["both", "long", "short"], default="both", help="long = calls only, short = puts only")
    ap.add_argument("--timeframe", type=int, default=5, choices=[5, 15])
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--cost-points", type=float, default=4.0)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out-dir", default="out")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    if a.demo:
        idx, _ = make_demo()
        a.timeframe = 15
    else:
        idx, _ = load_all(a.days, a.timeframe, a.out_dir, [0], "WEEK", 1, False, a.refresh)
    mk = Market(idx, None, "index", a.cost_points, interval=a.timeframe, stop_pts=a.stop, tgt_pts=a.target,
                max_hold=max(1, a.max_hold_minutes // a.timeframe), max_per_day=a.max_trades_per_day, last_entry=hhmm(a.latest))
    n_bars = max(1, a.range_minutes // a.timeframe)
    sig = orb_n(mk.df, n_bars) if a.entry == "orb" else prev_day_break(mk.df)
    if a.direction == "long":
        sig = np.where(sig == 1, sig, 0)
    elif a.direction == "short":
        sig = np.where(sig == -1, sig, 0)
    start = hhmm(a.earliest)
    t = run_strategy(mk, sig, start)
    if t.empty:
        raise SystemExit("No trades were taken with these rules.")
    cut = split_date(mk)
    d = pd.to_datetime(t["entry_time"]).dt.date
    first, last = t[d < cut]["pnl"], t[d >= cut]["pnl"]
    pool = random_pool(mk)
    pt = pd.to_datetime(pool["entry_time"])
    pool = pool[(pt.dt.hour * 60 + pt.dt.minute >= start)]
    pool_last = pool[pt[pool.index].dt.date >= cut]["pnl"].to_numpy()
    rng = np.random.default_rng(0)
    r95 = float(np.percentile(rng.choice(pool_last, size=(1000, max(1, len(last)))).mean(axis=1), 95)) if len(pool_last) and len(last) else np.nan
    rmean = float(pool_last.mean()) if len(pool_last) else np.nan
    rows = {"all": describe(t["pnl"]), "first 70% of days": describe(first), "last 30% of days": describe(last)}
    tab = pd.DataFrame(rows).T[["trades", "win_%", "avg_win", "avg_loss", "pf", "net", "expectancy", "max_drawdown"]]
    tab = tab.rename(columns={"net": "net_points", "expectancy": "avg_per_trade", "pf": "profit_factor"})
    print(f"\nYour rules: {a.entry}, stop {a.stop}, target {a.target}, entries {a.earliest}-{a.latest}, "
          f"{a.timeframe}-minute candles, max hold {a.max_hold_minutes} min, direction {a.direction}.")
    print(f"Results in NIFTY index points after {a.cost_points} points cost per trade (about Rs 32 per lot per point). First period before {cut}.\n")
    print(tab.to_string())
    print(f"\nExit reasons: {dict(t['reason'].value_counts())}")
    print(f"Random entries with the same stop, target and times, last period: average {rmean:.1f} per trade; "
          f"a strategy needs more than {r95:.1f} to beat 95% of them.")
    print(f"Check: {verdict(describe(first), describe(last), r95)}")
    m = t.copy(); m["month"] = pd.to_datetime(m["entry_time"]).dt.to_period("M").astype(str)
    mm = m.groupby("month")["pnl"].agg(trades="size", net_points="sum").round(0)
    print(f"\nProfitable months: {int((mm['net_points'] > 0).sum())} of {len(mm)}")
    print(mm.to_string())
    t.to_csv(os.path.join(a.out_dir, "custom_trades.csv"), index=False)
    print("\nNo single rule set proves anything: trying many numbers until one looks good just finds luck. Test your rules once, then follow them for a month.")


if __name__ == "__main__":
    main()
