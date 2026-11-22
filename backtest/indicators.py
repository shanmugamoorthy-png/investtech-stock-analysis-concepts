"""Standard indicators. Every value at bar i uses only bars up to i (no lookahead)."""
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    au = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    ad = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    out = 100 - 100 / (1 + au / ad.replace(0, np.nan))
    return out.where(ad != 0, 100.0)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    pc = close.shift()
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def supertrend_dir(high, low, close, n: int = 10, mult: float = 3.0) -> np.ndarray:
    """+1 while in an uptrend, -1 in a downtrend."""
    a = atr(high, low, close, n).to_numpy()
    h, l, c = high.to_numpy(), low.to_numpy(), close.to_numpy()
    mid = (h + l) / 2
    ub, lb = mid + mult * a, mid - mult * a
    fub, flb, d = ub.copy(), lb.copy(), np.ones(len(c))
    for i in range(1, len(c)):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if d[i - 1] == 1:
            d[i] = -1 if c[i] < flb[i] else 1
        else:
            d[i] = 1 if c[i] > fub[i] else -1
    return d


def swings(high: np.ndarray, low: np.ndarray, k: int = 2):
    """Last two confirmed swing highs / lows as known at each bar. A pivot at j is confirmed at j+k."""
    n = len(high)
    cur_h = prev_h = cur_l = prev_l = np.nan
    out = np.full((4, n), np.nan)  # cur_h, prev_h, cur_l, prev_l
    for i in range(n):
        j = i - k
        if j >= k:
            wh, wl = high[j - k:j + k + 1], low[j - k:j + k + 1]
            if high[j] == wh.max() and (wh == high[j]).sum() == 1:
                prev_h, cur_h = cur_h, high[j]
            if low[j] == wl.min() and (wl == low[j]).sum() == 1:
                prev_l, cur_l = cur_l, low[j]
        out[:, i] = (cur_h, prev_h, cur_l, prev_l)
    return out
