"""Backtest six price-action / indicator strategies on NIFTY. Records and statistics only; no predictions.

python run.py --mode options --days 730 --out-dir /content/drive/MyDrive/backtest
python run.py --demo            # synthetic data, to check that everything runs
"""
import argparse
import html
import os

import pandas as pd

from data import load_all
from demo import make_demo
from engine import MIN_PF, MIN_TRADES, Market, evaluate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--mode", choices=["index", "options"], default="options")
    ap.add_argument("--interval", type=int, default=15, choices=[5, 15, 25, 60])
    ap.add_argument("--offsets", type=int, default=2, help="how many strikes either side of ATM to load for options")
    ap.add_argument("--expiry-flag", default="WEEK")
    ap.add_argument("--expiry-code", type=int, default=1)
    ap.add_argument("--cost-points", type=float, default=2.0, help="index mode: cost per trade in index points")
    ap.add_argument("--slip", type=float, default=0.5, help="options mode: slippage in premium points per side")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out-dir", default="out")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    if a.demo:
        idx, opt = make_demo()
    else:
        offs = [0] + [s * k for k in range(1, a.offsets + 1) for s in (1, -1)]
        idx, opt = load_all(a.days, a.interval, a.out_dir, offs, a.expiry_flag, a.expiry_code, a.mode == "options", a.refresh)
    print(f"Bars: {len(idx)}, days: {idx['time'].dt.date.nunique()}, {idx['time'].min()} to {idx['time'].max()}")
    if a.mode == "options":
        c0 = opt.get(("CALL", 0))
        if c0 is not None:
            print(f"ATM call loaded: {len(c0)} bars, median price {c0['close'].median():.0f} "
                  "(weekly NIFTY ATM is usually about 50-250; send me this line if it looks very different)")
    mk = Market(idx, opt, a.mode, a.cost_points, a.slip)
    res, trades, cut = evaluate(mk)
    unit = "Rs per lot of 65" if a.mode == "options" else "index points"
    res.to_csv(os.path.join(a.out_dir, "backtest_results.csv"), index=False)
    trades.to_csv(os.path.join(a.out_dir, "backtest_trades.csv"), index=False)
    print(f"\nFirst period: before {cut}. Last period: {cut} onward. Results are net of costs, in {unit}.\n")
    show = res.drop(columns=["verdict"]).copy()
    print(show.to_string(index=False))
    print("\nChecks:")
    for _, r in res.iterrows():
        print(f"  {r['strategy']} / {r['entries']}: {r['verdict']}")
    passed = int((res["verdict"] == "PASSES all checks").sum())
    print(f"\n{passed} of {len(res)} combinations passed. With {len(res)} tried, one or two passing by luck is expected.")
    page = (f"<h1>Strategy backtest (NIFTY)</h1><p>Net of estimated costs, in {unit}. First period: before {cut}; last period: {cut} onward. "
            f"A combination passes only if it has at least {MIN_TRADES} trades in each period, is profitable with profit factor "
            f">= {MIN_PF} in both, and the last period beats 95% of random entries. {len(res)} combinations were tried, so a few passing by luck is expected. "
            "Past results do not predict future results. Not investment advice.</p>" + res.to_html(index=False, border=0, classes="t"))
    css = "body{font-family:system-ui;max-width:1100px;margin:auto;padding:12px}table.t{border-collapse:collapse;font-size:13px}table.t td,table.t th{padding:4px 8px;border-bottom:1px solid #ddd;text-align:right}"
    open(os.path.join(a.out_dir, "backtest_report.html"), "w").write(f"<!DOCTYPE html><meta charset=utf-8><style>{css}</style>{page}")
    print(f"\nSaved report to {os.path.join(a.out_dir, 'backtest_report.html')}")


if __name__ == "__main__":
    main()
