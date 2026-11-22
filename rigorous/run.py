"""Rigorous test of simple stock-picking rules on NSE stocks, including stocks that were later delisted.

python run.py --start 2018-01-01 --out-dir /content/drive/MyDrive/rigorous
python run.py --demo        # synthetic market, checks that everything runs
Records and statistics only; past results do not predict the future. Not investment advice.
"""
import argparse
import os
import warnings
from datetime import date

import pandas as pd

from bhav import fetch_range, load_long
from evaluate import HOLDOUT, MIN_YEARS_BEAT, evaluate
from panel import build_panel
from portfolio import K, Cfg
from synthetic import make_long

warnings.filterwarnings("ignore", category=RuntimeWarning)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default=str(date.today()))
    ap.add_argument("--top", type=int, default=300, help="liquid stocks considered each month")
    ap.add_argument("--min-value-cr", type=float, default=5.0, help="minimum median daily traded value, crore rupees")
    ap.add_argument("--capital", type=float, default=1_000_000)
    ap.add_argument("--slippage", type=float, default=0.001, help="per side, as a fraction (0.001 = 0.10%%)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--out-dir", default="out")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    if a.demo:
        long = make_long()
    else:
        cache = os.path.join(a.out_dir, "nse_daily")
        fetch_range(date.fromisoformat(a.start), date.fromisoformat(a.end), cache, a.workers)
        long = load_long(cache)
    p = build_panel(long)
    print("\nData checks:")
    for k, v in p.diag.items():
        print(f"  {k.replace('_', ' ')}: {v}")
    print(f"  period: {p.dates[0].date()} to {p.dates[-1].date()}")
    cfg = Cfg(top=a.top, min_value=a.min_value_cr * 1e7, capital=a.capital, slippage=a.slippage)
    res, series, bench, cut, base = evaluate(p, cfg)
    res.to_csv(os.path.join(a.out_dir, "rigorous_results.csv"), index=False)
    pd.DataFrame(series).assign(benchmark_gross=bench).to_csv(os.path.join(a.out_dir, "monthly_returns.csv"))
    print(f"\n{len(base.periods)} monthly periods. Hold-out = last {int(HOLDOUT * 100)}% of months, from {cut.date()}.")
    print(f"Each month: top {K} by the rule among the {a.top} most traded stocks of that time (stocks later delisted included).")
    print(f"Costs: STT, stamp duty, exchange fees, DP charges, {a.slippage * 100:.2f}% slippage per side. Tax: 20.8% on each year's gain.")
    print("CAGR = yearly growth rate. Benchmark = equal-weight of the same stocks, before any cost or tax.\n")
    print(res.drop(columns=["verdict"]).to_string(index=False))
    print("\nChecks:")
    for _, r in res.iterrows():
        print(f"  {r['strategy']}: {r['verdict']}")
    n = int((res["verdict"] == "PASSES all checks").sum())
    print(f"\n{n} of {len(res)} rules passed. A pass needs: picks beat 95% of random portfolios, the hold-out beats the passive "
          f"benchmark after costs and tax, beats it in {int(MIN_YEARS_BEAT * 100)}% of years, and still makes money under stress "
          "(0.25% slippage, 30% loss on delisted stocks).")
    print("Dividends are not included. Stock symbols that change name are treated as a delisting plus a new listing.")
    print(f"Saved results to {a.out_dir}")


if __name__ == "__main__":
    main()
