"""Simple, transparent versions of ideas from Investtech's concepts.

These are my own approximations for learning. They are NOT Investtech's
algorithms (which are not published): trend scoring, volume balance and
support/resistance detection here are deliberately basic.
"""
import numpy as np
import pandas as pd


def trend_channel(close: pd.Series, window: int = 375, k: float = 2.0,
                  flat_pct: float = 10.0) -> dict:
    """Regression channel on log price over the last `window` bars.

    Floor/ceiling = regression line -/+ k * residual std.
    direction: rising / falling / sideways using the annualised slope.
    position: 0 = floor, 1 = ceiling; <0.2 near floor, >0.8 near ceiling.
    """
    y = np.log(close.dropna().to_numpy()[-window:])
    n = len(y)
    if n < 60:
        raise ValueError("need at least 60 bars")
    x = np.arange(n)
    slope, intercept = np.polyfit(x, y, 1)
    fit = slope * x + intercept
    resid = y - fit
    sd = resid.std()
    r2 = 1 - resid.var() / y.var() if y.var() > 0 else 0.0
    ann_pct = (np.exp(slope * 252) - 1) * 100
    floor, ceil = fit[-1] - k * sd, fit[-1] + k * sd
    pos = (y[-1] - floor) / (ceil - floor) if ceil > floor else 0.5
    if ann_pct > flat_pct:
        direction = "rising"
    elif ann_pct < -flat_pct:
        direction = "falling"
    else:
        direction = "sideways"
    return {
        "direction": direction,
        "slope_ann_pct": round(float(ann_pct), 1),
        "r2": round(float(r2), 2),
        "channel_pos": round(float(pos), 2),
        "floor": round(float(np.exp(floor)), 2),
        "ceiling": round(float(np.exp(ceil)), 2),
        "outside": bool(pos < 0 or pos > 1),
    }


def volume_balance(df: pd.DataFrame, window: int = 22) -> float:
    """Approximation: (up-day volume - down-day volume) / total, scaled -100..100."""
    d = df.tail(window + 1)
    change = d["close"].diff().iloc[1:]
    vol = d["volume"].iloc[1:]
    up, down = vol[change > 0].sum(), vol[change < 0].sum()
    total = up + down
    return 0.0 if total == 0 else round(float((up - down) / total * 100), 1)


def range_break(df: pd.DataFrame, lookback: int = 60, vol_mult: float = 1.5) -> str:
    """Close beyond the prior `lookback`-day high/low, flagged if volume is elevated."""
    prior = df.iloc[-lookback - 1:-1]
    last = df.iloc[-1]
    avg_vol = df["volume"].iloc[-23:-1].mean()
    strong = bool(avg_vol and last["volume"] > vol_mult * avg_vol)
    if last["close"] > prior["high"].max():
        return "break up (volume confirmed)" if strong else "break up (weak volume)"
    if last["close"] < prior["low"].min():
        return "break down (volume confirmed)" if strong else "break down (weak volume)"
    return "none"


def read(trend: dict, vb: float) -> str:
    """Trend first, volume confirms (the order Investtech describes)."""
    if trend["direction"] == "rising":
        return "trend + volume positive" if vb > 0 else "rising trend, volume NOT confirming - watch"
    if trend["direction"] == "falling":
        return "trend + volume negative" if vb < 0 else "falling trend, volume improving - watch"
    return "sideways - levels matter most"
