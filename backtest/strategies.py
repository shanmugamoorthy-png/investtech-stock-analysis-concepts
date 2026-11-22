"""Six fixed strategies. Each returns an int array: +1 buy signal, -1 sell signal, 0 none.
A signal at bar i is decided at the CLOSE of bar i; the engine enters at the open of bar i+1.
No parameters are tuned; these are common textbook settings chosen before looking at any results."""
import numpy as np
import pandas as pd

from indicators import atr, ema, rsi, supertrend_dir, swings

WARMUP = 60


def _cross_up(x, level):
    return (x > level) & (np.roll(x, 1) <= np.roll(level, 1))


def _cross_dn(x, level):
    return (x < level) & (np.roll(x, 1) >= np.roll(level, 1))


def _finish(sig, n):
    sig[:WARMUP] = 0
    sig[0] = 0
    return sig.astype(np.int8)


def orb(df):
    """Opening range breakout: first 30 minutes (2 bars of 15 min); first close beyond it."""
    n = len(df)
    sig = np.zeros(n)
    c, h, l = df["close"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
    for _, idx in df.groupby("date").indices.items():
        if len(idx) < 4:
            continue
        hi, lo = h[idx[:2]].max(), l[idx[:2]].min()
        up = dn = False
        for i in idx[2:]:
            if not up and c[i] > hi:
                sig[i], up = 1, True
            elif not dn and c[i] < lo:
                sig[i], dn = -1, True
    return _finish(sig, n)


def prev_day_break(df):
    """Close crosses above previous day's high (buy) or below previous day's low (sell)."""
    n = len(df)
    day_hi = df.groupby("date")["high"].max()
    day_lo = df.groupby("date")["low"].min()
    dates = list(day_hi.index)
    prev = {d: p for p, d in zip(dates[:-1], dates[1:])}
    pdh = df["date"].map(lambda d: day_hi.get(prev.get(d), np.nan)).to_numpy(float)
    pdl = df["date"].map(lambda d: day_lo.get(prev.get(d), np.nan)).to_numpy(float)
    c = df["close"].to_numpy()
    sig = np.zeros(n)
    sig[_cross_up(c, pdh)] = 1
    sig[_cross_dn(c, pdl)] = -1
    return _finish(np.nan_to_num(sig), n)


def ema_cross(df):
    """EMA 9 crosses EMA 21."""
    f, s = ema(df["close"], 9).to_numpy(), ema(df["close"], 21).to_numpy()
    sig = np.zeros(len(df))
    sig[_cross_up(f, s)] = 1
    sig[_cross_dn(f, s)] = -1
    return _finish(sig, len(df))


def rsi_pullback(df):
    """Trend filter EMA20/EMA50. Buy when RSI(14) climbs back above 40 in an uptrend; sell when it falls below 60 in a downtrend."""
    c = df["close"]
    e20, e50, r = ema(c, 20).to_numpy(), ema(c, 50).to_numpy(), rsi(c).to_numpy()
    cc, rp = c.to_numpy(), np.roll(r, 1)
    sig = np.zeros(len(df))
    sig[(cc > e50) & (e20 > e50) & (rp <= 40) & (r > 40)] = 1
    sig[(cc < e50) & (e20 < e50) & (rp >= 60) & (r < 60)] = -1
    return _finish(sig, len(df))


def supertrend_flip(df):
    """Supertrend(10, 3) changes direction."""
    d = supertrend_dir(df["high"], df["low"], df["close"], 10, 3.0)
    sig = np.zeros(len(df))
    sig[(d == 1) & (np.roll(d, 1) == -1)] = 1
    sig[(d == -1) & (np.roll(d, 1) == 1)] = -1
    return _finish(sig, len(df))


def swing_break(df):
    """Price structure: close breaks the last swing high while swing lows are rising (buy),
    or breaks the last swing low while swing highs are falling (sell). Swings use 2 bars each side, confirmed late."""
    sh, psh, sl, psl = swings(df["high"].to_numpy(), df["low"].to_numpy(), 2)
    c = df["close"].to_numpy()
    sig = np.zeros(len(df))
    with np.errstate(invalid="ignore"):
        sig[_cross_up(c, np.nan_to_num(sh, nan=1e12)) & (sl > psl)] = 1
        sig[_cross_dn(c, np.nan_to_num(sl, nan=-1e12)) & (sh < psh)] = -1
    return _finish(sig, len(df))


STRATEGIES = {
    "Opening range breakout": orb,
    "Previous day high/low break": prev_day_break,
    "EMA 9/21 cross": ema_cross,
    "RSI pullback in trend": rsi_pullback,
    "Supertrend flip": supertrend_flip,
    "Swing high/low break": swing_break,
}
