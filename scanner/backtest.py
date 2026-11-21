"""Walk-forward check of the scanner's 'read' labels. Educational only.

For every `--step` bars, uses ONLY data up to that bar to compute the label, then
measures the forward `--horizon`-bar return and compares it with the benchmark
(NIFTY 50) over the same dates. Overlapping windows make observations correlated,
so treat the averages as rough, not statistically strong.

Usage:
  python backtest.py --csv-dir ./candles          # <symbol>.csv incl. "NIFTY 50.csv"
  python backtest.py                              # fetch from Dhan (needs DHAN_ACCESS_TOKEN)
"""
import argparse
import os
import time

import pandas as pd

from dhan_scanner import fetch_dhan, load_csv
from indicators import read, trend_channel, volume_balance

WINDOW = 375


def signals(df: pd.DataFrame, step: int, horizon: int) -> pd.DataFrame:
    rows = []
    for i in range(WINDOW, len(df) - horizon, step):
        hist = df.iloc[: i + 1]  # no lookahead
        t = trend_channel(hist["close"], window=WINDOW)
        label = read(t, volume_balance(hist))
        fwd = df["close"].iloc[i + horizon] / df["close"].iloc[i] - 1
        rows.append({"date": df.index[i], "label": label, "fwd": fwd,
                     "end": df.index[i + horizon]})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="symbols.csv")
    ap.add_argument("--csv-dir")
    ap.add_argument("--benchmark", default="NIFTY 50")
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--horizon", type=int, default=66)
    ap.add_argument("--out", default="backtest.csv")
    a = ap.parse_args()

    rows = list(pd.read_csv(a.symbols, dtype=str).itertuples())
    data = {}
    for r in rows:
        try:
            data[r.symbol] = (load_csv(os.path.join(a.csv_dir, f"{r.symbol}.csv"))
                              if a.csv_dir else fetch_dhan(r, days=3650))
        except Exception as e:
            print(f"{r.symbol}: skipped ({e})")
        if not a.csv_dir:
            time.sleep(1)
    bench = data[a.benchmark]["close"]

    out = []
    for sym, df in data.items():
        if sym == a.benchmark:
            continue
        s = signals(df, a.step, a.horizon)
        b0 = bench.reindex(s["date"], method="ffill").to_numpy()
        b1 = bench.reindex(s["end"], method="ffill").to_numpy()
        s["bench"] = b1 / b0 - 1
        s["excess"] = s["fwd"] - s["bench"]
        s.insert(0, "symbol", sym)
        out.append(s)
    res = pd.concat(out)
    res.to_csv(a.out, index=False)
    g = res.groupby("label").agg(n=("fwd", "size"), avg_fwd_pct=("fwd", lambda x: x.mean() * 100),
                                 avg_excess_pct=("excess", lambda x: x.mean() * 100),
                                 hit_rate_pct=("excess", lambda x: (x > 0).mean() * 100)).round(1)
    print(f"Forward {a.horizon}-bar return vs {a.benchmark}, sampled every {a.step} bars")
    print(g.sort_values("avg_excess_pct", ascending=False).to_string())


if __name__ == "__main__":
    main()
