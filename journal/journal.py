"""NIFTY options trade journal from your Dhan trade history. Records and statistics only; no predictions.

python journal.py --days 180 --out-dir /content/drive/MyDrive/journal
python journal.py --raw trades.json          # offline: a saved list of Dhan trade objects
"""
import argparse
import html
import json
import os

import pandas as pd

from metrics import breakdown, revenge_check, summary
from trades import classify_open, clean, fetch_trades, load_zerodha, round_trips


def equity_svg(rt: pd.DataFrame, w=760, h=220) -> str:
    cum = rt.sort_values("exit_time")["net"].cumsum().to_numpy()
    if len(cum) < 2:
        return ""
    lo, hi = min(0, cum.min()), max(0, cum.max())
    span = (hi - lo) or 1
    pts = " ".join(f"{10 + i * (w - 20) / (len(cum) - 1):.1f},{h - 10 - (v - lo) / span * (h - 20):.1f}" for i, v in enumerate(cum))
    zero = h - 10 - (0 - lo) / span * (h - 20)
    return (f'<svg viewBox="0 0 {w} {h}" width="100%"><line x1="10" x2="{w-10}" y1="{zero:.1f}" y2="{zero:.1f}" '
            f'stroke="#999" stroke-dasharray="4"/><polyline fill="none" stroke="#0b5cad" stroke-width="2" points="{pts}"/></svg>')


def table(d, **kw):
    return d.to_html(border=0, classes="t", **kw)


def build_report(rt: pd.DataFrame, open_lots: pd.DataFrame, raw_n: int) -> str:
    s = summary(rt)
    rt = rt.copy()
    hold = (rt["exit_time"] - rt["entry_time"]).dt.total_seconds() / 60
    rt["weekday"] = rt["entry_time"].dt.day_name()
    rt["entry_hour"] = rt["entry_time"].dt.hour
    rt["holding"] = pd.cut(hold, [-1, 5, 30, 120, 1e9], labels=["<5 min", "5-30 min", "30-120 min", ">2 h"])
    parts = [
        "<h1>Options trade journal</h1>",
        f"<p>{raw_n} fills matched into {len(rt)} round trips (FIFO). Charges are as reported by Dhan, or estimated for Zerodha files. "
        "Statistics describe your own past trades; they do not predict future results. Not investment advice.</p>",
        "<h2>Summary</h2>", table(pd.Series(s, name="value").to_frame()),
        "<h2>Cumulative net P&L</h2>", equity_svg(rt),
        "<h2>By weekday</h2>", table(breakdown(rt, rt["weekday"], "weekday")),
        "<h2>By entry hour</h2>", table(breakdown(rt, rt["entry_hour"], "hour")),
        "<h2>By holding time</h2>", table(breakdown(rt, rt["holding"], "holding")),
        "<h2>Calls vs puts, long vs short</h2>",
        table(breakdown(rt, rt["option"].fillna("?").astype(str) + " " + rt["direction"], "type")),
        "<h2>Trades opened quickly after a loss (within 10 minutes)</h2>",
        table(pd.Series(revenge_check(rt), name="value").to_frame()),
        "<h2>Five biggest losses</h2>",
        table(rt.nsmallest(5, "net")[["symbol", "direction", "qty", "entry_time", "exit_time", "net"]], index=False),
    ]
    if len(open_lots):
        exp, still = open_lots[open_lots["expired"]], open_lots[~open_lots["expired"]]
        if len(exp):
            lost = -exp.loc[exp["sign"] == 1, "pnl_if_zero"].sum() * -1
            kept = exp.loc[exp["sign"] == -1, "pnl_if_zero"].sum()
            parts += ["<h2>Expired with no closing trade</h2>",
                      "<p>These options expired and have no sell/buy trade. <b>They are not in the P&amp;L above.</b> "
                      "If they expired worthless, bought ones lose the full premium and sold ones keep it. "
                      "Options that expired in the money were settled at their value instead, so check your contract note.</p>",
                      f"<p>If worthless: bought options {lost:,.0f}, sold options +{kept:,.0f}, "
                      f"total {lost + kept:,.0f} (before charges).</p>",
                      table(exp[["symbol", "side", "qty", "price", "expiry", "pnl_if_zero"]], index=False)]
        if len(still):
            parts += ["<h2>Positions still open</h2>", table(still[["symbol", "side", "qty", "price", "time"]], index=False)]
    css = ("body{font-family:system-ui;max-width:860px;margin:auto;padding:12px}table.t{border-collapse:collapse}"
           "table.t td,table.t th{padding:4px 10px;border-bottom:1px solid #ddd;text-align:right}h2{margin-top:28px}")
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Trade journal</title><style>{css}</style></head><body>{''.join(parts)}</body></html>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--filter", default="", help="keep trades whose symbol contains this text (e.g. NIFTY)")
    ap.add_argument("--only-derivatives", action="store_true", default=True)
    ap.add_argument("--raw", help="JSON file of trade objects instead of calling Dhan")
    ap.add_argument("--include-futures", action="store_true", help="also include futures (default: options only)")
    ap.add_argument("--zerodha", help="Zerodha Console tradebook file (.csv or .xlsx)")
    ap.add_argument("--out-dir", default="out")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    raw = load_zerodha(a.zerodha) if a.zerodha else (pd.DataFrame(json.load(open(a.raw))) if a.raw else fetch_trades(a.days))
    if raw.empty:
        raise SystemExit("No trades returned for that period.")
    raw.to_csv(os.path.join(a.out_dir, "raw_trades.csv"), index=False)
    df = clean(raw)
    print("Columns from Dhan:", ", ".join(raw.columns))
    print(f"\nDhan returned {len(raw)} fills ({len(df)} after cleaning).")
    for c in ("instrument", "exchangeSegment", "productType", "drvOptionType"):
        if c in df:
            print(f"  {c}: {dict(df[c].astype(str).value_counts())}")
    if "time" in df and df["time"].notna().any():
        print(f"  dates: {df['time'].min().date()} to {df['time'].max().date()}")
    print("  sample symbols:", ", ".join(df["symbol"].astype(str).drop_duplicates().head(6)))
    if a.only_derivatives:
        is_opt = df["drvOptionType"].astype(str).str.upper().isin(["CALL", "PUT"]) if "drvOptionType" in df else False
        is_der = df["instrument"].astype(str).str.upper().str.contains("DERIV|OPT|FUT") if "instrument" in df else False
        df = df[is_opt | is_der]
    if not a.include_futures and "drvOptionType" in df:
        ok = df["drvOptionType"].astype(str).str.upper().isin(["CALL", "PUT"])
        if (~ok).any():
            print(f"Left out {int((~ok).sum())} futures fills (use --include-futures to keep them).")
        df = df[ok]
    if a.filter:
        df = df[df["symbol"].str.upper().str.contains(a.filter.upper(), regex=False)]
    if df.empty:
        raise SystemExit("\nNo matching option trades. Send me the lines printed above (counts and sample symbols; no prices).")
    print("Contracts found:", ", ".join(sorted(set(df["symbol"])))[:300])
    rt, open_lots = round_trips(df)
    open_lots = classify_open(open_lots)
    if rt.empty:
        raise SystemExit("No closed round trips found.")
    rt.to_csv(os.path.join(a.out_dir, "round_trips.csv"), index=False)
    path = os.path.join(a.out_dir, "journal_report.html")
    open(path, "w").write(build_report(rt, open_lots, len(df)))
    print(f"\nSaved: {path}")
    for k, v in summary(rt).items():
        print(f"  {k}: {v}")
    if len(open_lots):
        exp = open_lots[open_lots["expired"]]
        print(f"\n{len(exp)} expired position(s) and {len(open_lots) - len(exp)} open position(s) have no closing trade and are NOT in the P&L.")
        if len(exp):
            print(f"  If the expired ones finished worthless: {exp['pnl_if_zero'].sum():,.0f} (bought lose premium, sold keep it), before charges.")


if __name__ == "__main__":
    main()
