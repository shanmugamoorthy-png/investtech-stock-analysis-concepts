"""Daily watchlist: scan, save a dated snapshot, and print what changed since the last one.

python watchlist.py                              # uses Dhan (needs DHAN_ACCESS_TOKEN)
python watchlist.py --history-dir /content/drive/MyDrive/watchlist   # keep history in Google Drive
Educational only, not investment advice. The labels did not show predictive power in my backtest;
this is a chart-reading summary.
"""
import argparse
import glob
import os
import sys
import time
from datetime import date

import pandas as pd

from dhan_scanner import analyse, fetch_dhan, load_csv


def zone(pos: float) -> str:
    if pos > 1:
        return "above channel"
    if pos < 0:
        return "below channel"
    if pos > 0.8:
        return "near ceiling"
    if pos < 0.2:
        return "near floor"
    return "middle"


def scan(rows, csv_dir=None) -> pd.DataFrame:
    out = []
    for row in rows:
        try:
            df = load_csv(os.path.join(csv_dir, f"{row.symbol}.csv")) if csv_dir else fetch_dhan(row)
            r = analyse(df)
            out.append({"symbol": row.symbol, "last_close": r["last_close"], "trend": r["trend"],
                        "zone": zone(r["channel_pos"]), "vol_balance": r["vol_balance"],
                        "break_60d": r["60d_break"], "read": r["read"]})
        except Exception as e:
            print(f"{row.symbol}: skipped ({e})", file=sys.stderr)
        if not csv_dir:
            time.sleep(1)
    return pd.DataFrame(out)


def changes(old: pd.DataFrame, new: pd.DataFrame):
    m = new.merge(old, on="symbol", suffixes=("", "_old"))
    lines = []
    for _, r in m.iterrows():
        notes = []
        if r["trend"] != r["trend_old"]:
            notes.append(f"trend {r['trend_old']} -> {r['trend']}")
        if r["zone"] != r["zone_old"]:
            notes.append(f"channel position {r['zone_old']} -> {r['zone']}")
        if r["break_60d"] != r["break_60d_old"] and r["break_60d"] != "none":
            notes.append(f"new 60-day range break: {r['break_60d']}")
        if notes:
            lines.append(f"{r['symbol']}: " + "; ".join(notes))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="symbols.csv")
    ap.add_argument("--history-dir", default="history")
    ap.add_argument("--csv-dir")
    ap.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args()

    os.makedirs(a.history_dir, exist_ok=True)
    prev_files = sorted(f for f in glob.glob(os.path.join(a.history_dir, "*.csv"))
                        if os.path.basename(f)[:-4] < a.date)
    rows = list(pd.read_csv(a.symbols, dtype=str).itertuples())
    new = scan(rows, a.csv_dir)
    path = os.path.join(a.history_dir, f"{a.date}.csv")
    new.to_csv(path, index=False)

    print(f"Snapshot saved: {path} ({len(new)} symbols)\n")
    if not prev_files:
        print("First snapshot, nothing to compare yet. Run again on another day.")
    else:
        prev = prev_files[-1]
        ch = changes(pd.read_csv(prev), new)
        print(f"Changes since {os.path.basename(prev)[:-4]}:")
        print("\n".join("  " + l for l in ch) if ch else "  none")
    counts = new["trend"].value_counts()
    print("\nTrend counts:", ", ".join(f"{k}: {v}" for k, v in counts.items()))
    with pd.option_context("display.width", 250, "display.max_colwidth", 60):
        print("\n" + new.to_string(index=False))


if __name__ == "__main__":
    main()
