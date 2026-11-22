"""Monthly-rebalanced stock portfolios built from simple, fixed rules, with Indian costs and tax.
Every choice at a rebalance uses data up to the day BEFORE the rebalance; trades happen at that day's open."""
from dataclasses import dataclass

import warnings

import numpy as np
import pandas as pd

from panel import Panel

warnings.filterwarnings("ignore", category=RuntimeWarning)   # empty windows give NaN on purpose

K = 20
SCORES = {}


def score(name):
    def deco(f):
        SCORES[name] = f
        return f
    return deco


# Each score function gets (C, j): adjusted closes C[date, symbol] and the last day j it may look at. Higher = picked.
@score("Momentum 12-1 months")
def mom(C, j):
    return C[j - 21] / C[j - 252] - 1


@score("Near 52-week high")
def near_high(C, j):
    return C[j] / np.nanmax(C[j - 251:j + 1], axis=0)


@score("Trend: above 200-day average, 50 above 200")
def trend(C, j):
    sma200, sma50 = np.nanmean(C[j - 199:j + 1], axis=0), np.nanmean(C[j - 49:j + 1], axis=0)
    s = C[j] / sma200 - 1
    return np.where((C[j] > sma200) & (sma50 > sma200), s, np.nan)


@score("Reversal: worst last month")
def reversal(C, j):
    return -(C[j] / C[j - 21] - 1)


@score("Low volatility (60 days)")
def lowvol(C, j):
    r = C[j - 59:j + 1] / C[j - 60:j] - 1
    return -np.nanstd(r, axis=0)


@dataclass
class Cfg:
    top: int = 300                  # liquid universe size, rebalanced monthly
    min_value: float = 5e7          # median daily traded value, rupees (5 crore)
    capital: float = 1_000_000
    slippage: float = 0.001         # per side, fraction of price
    haircut: float = 0.0            # loss assumed on stocks that stop trading while held
    tax: float = 0.208              # 20% short-term capital gains tax + 4% cess
    seed: int = 0


def month_starts(p: Panel, warmup=260):
    idx = pd.Series(np.arange(len(p.dates)), index=p.dates)
    first = idx.groupby([p.dates.year, p.dates.month]).first()
    return [int(i) for i in first.values if i >= warmup]


def eligible(p: Panel, i0, cfg: Cfg):
    j = i0 - 1
    ok = ~np.isnan(p.C[j]) & ~np.isnan(p.O[i0])
    ok &= np.sum(~np.isnan(p.C[j - 252:j + 1]), axis=0) >= 240
    med = np.nanmedian(p.V[j - 59:j + 1], axis=0)
    ok &= np.nan_to_num(med) >= cfg.min_value
    cand = np.flatnonzero(ok)
    return cand[np.argsort(-med[cand])][:cfg.top]


def hold_returns(p: Panel, i0, i1, haircut):
    """Return of every stock from the open of i0 to the open of i1. A stock that stops trading is exited at its last close (less haircut)."""
    o0, o1 = p.O[i0], p.O[i1]
    gone = (p.last_date.to_numpy() < np.datetime64(p.dates[i1])) & (p.last_date.to_numpy() < np.datetime64(p.end - pd.Timedelta(days=20)))
    end_px = np.where(np.isnan(o1), p.CF[i1], o1)
    end_px = np.where(np.isnan(o1) & gone, end_px * (1 - haircut), end_px)
    return end_px / o0 - 1


def side_costs(cfg: Cfg):
    pos = cfg.capital / K
    txn = 0.0000297 * 1.18 + 1e-6              # exchange fee with GST, plus SEBI fee
    buy = 0.001 + 0.00015 + txn + cfg.slippage                 # STT 0.1%, stamp duty 0.015%
    sell = 0.001 + txn + 15.34 / pos + cfg.slippage            # STT 0.1%, DP charge Rs 15.34 per stock sold
    return buy, sell


class Run:
    """All months of one scenario: who was eligible, what each stock returned."""
    def __init__(self, p: Panel, cfg: Cfg):
        self.p, self.cfg = p, cfg
        self.starts = month_starts(p)
        self.periods = [(a, b) for a, b in zip(self.starts[:-1], self.starts[1:])]
        self.elig = [eligible(p, a, cfg) for a, _ in self.periods]
        self.rets = [hold_returns(p, a, b, cfg.haircut) for a, b in self.periods]
        self.month_end = [p.dates[b] for _, b in self.periods]

    def picks(self, name):
        out = []
        for (a, _), el in zip(self.periods, self.elig):
            s = SCORES[name](self.p.C, a - 1)[el]
            good = np.flatnonzero(np.isfinite(s))
            out.append(el[good[np.argsort(-s[good])][:K]])
        return out

    def gross(self, picks):
        return np.array([np.nanmean(r[pk]) if len(pk) else 0.0 for r, pk in zip(self.rets, picks)])

    def net(self, picks):
        buy, sell = side_costs(self.cfg)
        out, prev = [], set()
        for r, pk in zip(self.rets, picks):
            cur = set(pk.tolist())
            n_in, n_out = len(cur - prev), len(prev - cur)
            k = max(len(cur), 1)
            out.append((np.nanmean(r[pk]) if len(pk) else 0.0) - (n_in * buy + n_out * sell) / k)
            prev = cur
        return np.array(out)

    def benchmark(self):
        return np.array([np.nanmean(r[el]) if len(el) else 0.0 for r, el in zip(self.rets, self.elig)])

    def random_means(self, idx, draws=500):
        rng = np.random.default_rng(self.cfg.seed)
        sums = np.zeros(draws)
        for m in idx:
            el, r = self.elig[m], self.rets[m]
            for d in range(draws):
                sums[d] += np.nanmean(r[rng.choice(el, size=min(K, len(el)), replace=False)])
        return sums / max(len(idx), 1)


def after_tax(net, month_end, rate):
    """Monthly returns after tax. Tax is taken at each financial year end (the period ending at the first April
    rebalance): rate x that year's gain. Loss carry-forward is ignored, which is slightly harsh."""
    eq, fy_start, res = 1.0, 1.0, []
    for r, d in zip(net, month_end):
        before = eq
        eq *= 1 + r
        if d.month == 4:
            eq -= rate * max(0.0, eq - fy_start)
            fy_start = eq
        res.append(eq / before - 1)
    return np.array(res)


def stats(r, months):
    r = np.asarray(r, float)
    if len(r) == 0:
        return {}
    eq = np.cumprod(1 + r)
    n = len(r)
    return {"cagr_%": round((eq[-1] ** (12 / n) - 1) * 100, 1), "vol_%": round(r.std() * np.sqrt(12) * 100, 1),
            "max_drawdown_%": round(float((1 - eq / np.maximum.accumulate(eq)).max() * 100), 1),
            "months": n}


def by_year(r, month_end):
    s = pd.Series(np.asarray(r, float), index=pd.DatetimeIndex(month_end))
    g = s.groupby(s.index.year)
    return (1 + g.apply(lambda x: (1 + x).prod() - 1)).sub(1), g.size()
