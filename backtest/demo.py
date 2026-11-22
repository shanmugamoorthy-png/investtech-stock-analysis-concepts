"""Synthetic market for testing the plumbing. Pure noise, so no strategy should pass."""
import numpy as np
import pandas as pd


def make_demo(days=400, seed=1):
    rng = np.random.default_rng(seed)
    times, o, h, l, c = [], [], [], [], []
    px = 20000.0
    for d in pd.bdate_range("2024-01-01", periods=days):
        for k in range(25):
            t = d + pd.Timedelta(minutes=9 * 60 + 15 + 15 * k)
            op = px
            path = op + np.cumsum(rng.normal(0, 8, 5))
            px = path[-1]
            times.append(t); o.append(op); h.append(max(path.max(), op)); l.append(min(path.min(), op)); c.append(px)
    idx = pd.DataFrame({"time": times, "open": o, "high": h, "low": l, "close": c})
    opt = {}
    for side in ("CALL", "PUT"):
        for off in (0, 1, -1, 2, -2):
            spot = idx["close"].to_numpy()
            atm = np.round(spot / 50) * 50
            k = atm + 50 * off
            intr = np.maximum(spot - k, 0) if side == "CALL" else np.maximum(k - spot, 0)
            prem = intr + 70 * np.exp(-(np.abs(spot - k) / 150))
            opt[(side, off)] = pd.DataFrame({"open": prem, "close": prem, "strike": k}, index=idx["time"])
    return idx, opt
