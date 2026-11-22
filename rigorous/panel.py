"""Turn raw daily prices into split-adjusted price tables. Uses NSE's own adjusted previous close to find splits and bonuses."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

JUMP = 0.04          # a gap this big between yesterday's close and today's adjusted previous close is a split/bonus/large payout


@dataclass
class Panel:
    dates: pd.DatetimeIndex
    symbols: np.ndarray
    O: np.ndarray        # adjusted open  [date, symbol]
    C: np.ndarray        # adjusted close
    CF: np.ndarray       # adjusted close, carried forward over gaps
    V: np.ndarray        # traded value in rupees
    last_date: pd.Series  # last day each symbol traded
    suspect: np.ndarray   # True for stocks with a guessed split adjustment or an extreme daily move left after adjusting
    end: pd.Timestamp
    diag: dict


STANDARD = np.array([0.5, 1 / 3, 0.25, 0.2, 0.1, 0.05, 2 / 3, 0.75, 2.0, 3.0, 4.0, 5.0, 10.0])   # common split/bonus/consolidation ratios


def adjust(long: pd.DataFrame):
    """Split-adjust prices. Main method: NSE's previous close is already adjusted on the ex-date, so the gap between
    yesterday's close and today's 'previous close' is the adjustment. Fallback for days where that is missing: a one-day
    price change that matches a standard split ratio (a normal stock cannot move that far in one day)."""
    d = long.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = d.groupby("symbol", sort=False)
    prior = g["close"].shift(1)
    ratio = (d["prev"] / prior).where(lambda x: x > 0)
    event = ratio.notna() & (np.log(ratio).abs() > JUMP)
    r = ratio.where(event, 1.0)
    raw = (d["close"] / prior).to_numpy()
    cand = np.flatnonzero(~event.to_numpy() & ((raw < 0.65) | (raw > 1.6)))
    guessed = 0
    if len(cand):
        err = np.abs(raw[cand][:, None] / STANDARD[None, :] - 1)
        best, ok = err.argmin(axis=1), err.min(axis=1) < 0.08
        r.iloc[cand[ok]] = STANDARD[best[ok]]
        guessed = int(ok.sum())
    lr = np.log(r).fillna(0.0)
    cs = lr.groupby(d["symbol"], sort=False).cumsum()
    tot = lr.groupby(d["symbol"], sort=False).transform("sum")
    fac = np.exp(tot - cs)                    # product of later adjustments
    for c in ("open", "high", "low", "close"):
        d[c] = d[c] * fac
    return d, int(event.sum()), guessed, set(d.loc[r.index[(~event) & (r != 1.0)], "symbol"])


def build_panel(long: pd.DataFrame) -> Panel:
    d, n_events, guessed, guessed_syms = adjust(long)
    dates = pd.DatetimeIndex(sorted(d["date"].unique()))
    wide = {k: d.pivot(index="date", columns="symbol", values=k).reindex(dates) for k in ("open", "close", "value")}
    symbols = wide["close"].columns.to_numpy()
    C = wide["close"].to_numpy(float)
    last = d.groupby("symbol")["date"].max().reindex(symbols)
    ret = pd.DataFrame(C).pct_change(fill_method=None)
    ext = ((ret < -0.5) | (ret > 1.0)).to_numpy()
    extreme = int(ext.sum())
    suspect = ext.any(axis=0) | np.isin(symbols, list(guessed_syms))
    diag = {"stocks": len(symbols), "days": len(dates), "split_or_bonus_adjustments": n_events, "adjustments_guessed_from_price_jump": guessed,
            "extreme_daily_moves_after_adjusting": extreme,
            "stocks_that_stopped_trading": int((last < dates[-1] - pd.Timedelta(days=20)).sum())}
    return Panel(dates, symbols, wide["open"].to_numpy(float), C, wide["close"].ffill().to_numpy(float),
                 wide["value"].to_numpy(float), last, suspect, dates[-1], diag)
