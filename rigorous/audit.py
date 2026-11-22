"""Audit a rule that passed: is it real, or caused by data errors, a few huge winners, lucky timing or optimistic costs?
Reads the prices already downloaded by run.py. Records and statistics only. Not investment advice.

python audit.py --out-dir /content/drive/MyDrive/rigorous
"""
import argparse
import os
import warnings

import numpy as np
import pandas as pd

from bhav import load_long
from evaluate import evaluate
from panel import build_panel
from portfolio import Cfg, Run, after_tax, by_year
from synthetic import make_long

warnings.filterwarnings("ignore", category=RuntimeWarning)
NAME = "Momentum 12-1 months"

SCENARIOS = [
    ("Reference (as in the first test)", {}),
    ("Hold 10 stocks instead of 20", {"k": 10}),
    ("Hold 30 stocks instead of 20", {"k": 30}),
    ("Only the 200 most traded stocks", {"top": 200}),
    ("The 500 most traded stocks", {"top": 500}),
    ("Trade 1 day later each month", {"offset": 1}),
    ("Trade 10 days later each month", {"offset": 10}),
    ("Slippage 0.5% per side", {"slippage": 0.005}),
    ("No stock counts for more than +100% a month", {"cap": 1.0}),
    ("Leave out stocks with suspect price data", {"exclude_suspect": True}),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    long = make_long() if a.demo else load_long(os.path.join(a.out_dir, "nse_daily"))
    p = build_panel(long)
    print(f"Stocks with suspect price data (guessed split or extreme one-day move): {int(p.suspect.sum())} of {p.diag['stocks']}")
    base = Run(p, Cfg())
    picks = base.picks(NAME)
    n = len(base.periods)
    cut = int(n * 0.6)
    rows = []
    for label, kw in SCENARIOS:
        res, *_ = evaluate(p, Cfg(**kw), draws=200, names=[NAME])
        r = res.iloc[0]
        rows.append({"scenario": label, "in_sample_cagr_%": r["in_sample_cagr_%"], "holdout_cagr_%": r["holdout_cagr_%"],
                     "benchmark_%": r["benchmark_cagr_%"], "holdout_maxdd_%": r["holdout_maxdd_%"],
                     "stress_%": r["stress_cagr_%"], "passes": "yes" if r["verdict"].startswith("PASSES") else "no"})
    print("\nMomentum 12-1 months under different assumptions (growth rates after costs and tax; hold-out = last 40% of months):\n")
    print(pd.DataFrame(rows).to_string(index=False))

    me = np.array(base.month_end)
    post = after_tax(base.net(picks), me, Cfg().tax)
    yr, cnt = by_year(post, me)
    yb, _ = by_year(base.benchmark(), me)
    print("\nBy calendar year: momentum after costs and tax vs the benchmark before any cost or tax (partial years marked *):")
    yt = pd.DataFrame({"momentum_%": (yr * 100).round(1), "benchmark_%": (yb * 100).round(1), "months": cnt})
    yt["momentum_%"] = yt["momentum_%"].astype(str) + np.where(yt["months"] < 11, "*", "")
    print(yt.to_string())

    big = []
    for (a0, b0), pk, r, d in zip(base.periods, picks, base.rets, base.month_end):
        for i in pk:
            big.append((r[i], str(p.symbols[i]), d.date(), bool(p.suspect[i])))
    big.sort(key=lambda x: -x[0] if np.isfinite(x[0]) else 1e9)
    print("\nBiggest single-stock monthly gains held by the strategy (a check for data errors):")
    for r, s, d, sus in big[:12]:
        print(f"  {s:<14} month ending {d}  {r * 100:+.0f}%{'   <- suspect price data' if sus else ''}")
    arr = np.array([b[0] for b in big if np.isfinite(b[0])])
    print(f"  {int((arr > 1).sum())} of {len(arr)} stock-months were gains above +100%; {int((arr < -0.5).sum())} were losses worse than -50%.")
    print("\nNote: this audit uses the same data and rules; it cannot find mistakes in NSE's files themselves.")


if __name__ == "__main__":
    main()
