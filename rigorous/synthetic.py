"""Synthetic stock market for tests: pure noise, with one split, one delisting and one stock that is suspended and returns."""
import numpy as np
import pandas as pd


def make_long(n=80, years=7, seed=0, split_symbol="S0", delist_symbol="S1", adjusted_prev=True):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2017-01-02", periods=int(years * 252))
    rows = []
    for k in range(n):
        sym = f"S{k}"
        px = 100 * np.exp(rng.normal(0, 0.3))
        start = 0 if k % 5 else int(rng.integers(0, 300))
        stop = len(dates)
        if sym == delist_symbol:
            stop = len(dates) // 2
        prev_close = None
        split_day = len(dates) // 3 if sym == split_symbol else None
        for t in range(start, stop):
            ret = rng.normal(0, 0.02)
            o = px * (1 + rng.normal(0, 0.003))
            c = px * (1 + ret)
            factor = 1.0
            if t == split_day:                         # 1:2 split: raw prices halve, NSE's previous close is adjusted
                factor = 0.5
            o, c = o * factor, c * factor
            prev = (prev_close * (factor if adjusted_prev else 1.0)) if prev_close is not None else c / (1 + ret)
            rows.append((dates[t], sym, o, max(o, c) * 1.002, min(o, c) * 0.998, c, prev, 2e8 * (1 + rng.random())))
            prev_close, px = c, c * 1.0
            if factor != 1.0:
                px = c
            prev_close = c
    return pd.DataFrame(rows, columns=["date", "symbol", "open", "high", "low", "close", "prev", "value"])
