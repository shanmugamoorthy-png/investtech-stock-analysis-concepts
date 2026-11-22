"""Trade simulation, random-entry baseline and pre-set pass/fail checks."""
import numpy as np
import pandas as pd

from costs import LOT, round_trip_cost
from indicators import atr
from strategies import STRATEGIES

STOP_ATR, TARGET_ATR, MAX_HOLD = 1.0, 1.5, 8     # fixed exit rules, in 15-minute bars
LAST_ENTRY = 14 * 60 + 30                         # no entries after 14:30
LAST_BAR_START = 15 * 60                          # force exit by the close of the 15:00 bar (15:15)
MAX_PER_DAY = 2
WINDOWS = {"any time": 9 * 60 + 30, "after 10:00 only": 10 * 60}
MIN_TRADES, MIN_PF = 60, 1.15                     # pre-set checks, see README


class Market:
    def __init__(self, df, opt=None, mode="index", cost_points=2.0, slip=0.5):
        df = df.sort_values("time").reset_index(drop=True).copy()
        df["date"] = df["time"].dt.date
        self.df, self.mode, self.cost_points, self.slip = df, mode, cost_points, slip
        self.o, self.h, self.l, self.c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.time = df["time"].to_numpy()
        self.day = pd.factorize(df["date"])[0]
        self.minute = (df["time"].dt.hour * 60 + df["time"].dt.minute).to_numpy()
        self.atr = atr(df["high"], df["low"], df["close"], 14).to_numpy(dtype=float).copy()
        self.n = len(df)
        self.opt = {}
        if mode == "options":
            for side in ("CALL", "PUT"):
                offs = sorted(o for (s, o) in (opt or {}) if s == side)
                if 0 not in offs:
                    raise SystemExit(f"No ATM {side} option data was loaded.")
                st = np.vstack([opt[(side, o)]["strike"].reindex(df["time"]).to_numpy(float) for o in offs])
                cl = np.vstack([opt[(side, o)]["close"].reindex(df["time"]).to_numpy(float) for o in offs])
                op0 = opt[(side, 0)]["open"].reindex(df["time"]).to_numpy(float)
                self.opt[side] = (st, cl, op0, offs.index(0))

    def exit_bar(self, i, d):
        """Walk forward from the entry bar. Returns (entry_bar, exit_bar, index_entry, index_exit, reason) or None."""
        e = i + 1
        if e >= self.n or self.day[e] != self.day[i] or self.minute[e] > LAST_ENTRY:
            return None
        a = self.atr[i]
        if not a > 0:
            return None
        ref = self.o[e]
        stop, tgt = ref - d * STOP_ATR * a, ref + d * TARGET_ATR * a
        j = e
        while True:
            hit_stop = self.l[j] <= stop if d == 1 else self.h[j] >= stop
            hit_tgt = self.h[j] >= tgt if d == 1 else self.l[j] <= tgt
            if hit_stop:                      # stop wins if both are touched in one bar
                return e, j, ref, stop, "stop"
            if hit_tgt:
                return e, j, ref, tgt, "target"
            nxt = j + 1
            if nxt >= self.n or self.day[nxt] != self.day[e] or self.minute[nxt] > LAST_BAR_START or nxt - e >= MAX_HOLD:
                return e, j, ref, self.c[j], "time"
            j = nxt

    def pnl(self, i, d):
        """Net result of one trade (points in index mode, rupees per lot in options mode) or None if it cannot be priced."""
        x = self.exit_bar(i, d)
        if x is None:
            return None
        e, j, ref, px, reason = x
        if self.mode == "index":
            return d * (px - ref) - self.cost_points, e, j, reason
        side = "CALL" if d == 1 else "PUT"
        st, cl, op0, k0 = self.opt[side]
        entry, strike = op0[e], st[k0, e]
        if not (entry >= 1.0) or np.isnan(strike):
            return None
        row = np.flatnonzero(st[:, j] == strike)
        if not len(row) or np.isnan(cl[row[0], j]):
            return None
        exit_ = cl[row[0], j]
        gross = (exit_ - entry - 2 * self.slip) * LOT
        day = str(pd.Timestamp(self.time[e]).date())
        return gross - round_trip_cost(entry, exit_, day), e, j, reason


def run_strategy(mk: Market, sig, start_minute):
    trades, busy, per_day = [], -1, {}
    for i in np.flatnonzero(sig):
        if i < busy or per_day.get(mk.day[i], 0) >= MAX_PER_DAY:
            continue
        e = i + 1
        if e >= mk.n or mk.minute[e] < start_minute:
            continue
        r = mk.pnl(i, int(sig[i]))
        if r is None:
            continue
        v, e, j, reason = r
        busy = j
        per_day[mk.day[i]] = per_day.get(mk.day[i], 0) + 1
        trades.append({"entry_time": mk.time[e], "exit_time": mk.time[j], "dir": int(sig[i]), "pnl": v, "reason": reason})
    return pd.DataFrame(trades, columns=["entry_time", "exit_time", "dir", "pnl", "reason"])


def random_pool(mk: Market):
    """Outcome of entering at every bar in either direction with the same exit rules. Used as the do-nothing-clever baseline."""
    rows = []
    for i in range(60, mk.n - 1):
        for d in (1, -1):
            r = mk.pnl(i, d)
            if r is not None:
                rows.append((mk.time[r[1]], mk.minute[r[1]], r[0]))
    return pd.DataFrame(rows, columns=["entry_time", "minute", "pnl"])


def metrics(p: pd.Series, times=None) -> dict:
    n = len(p)
    if n == 0:
        return {"trades": 0, "net": 0.0, "pf": np.nan, "win_%": np.nan, "expectancy": np.nan}
    w, lo = p[p > 0].sum(), -p[p <= 0].sum()
    return {"trades": n, "net": round(float(p.sum()), 0), "pf": round(w / lo, 2) if lo > 0 else np.inf,
            "win_%": round(float((p > 0).mean() * 100), 1), "expectancy": round(float(p.mean()), 1)}


def split_date(mk: Market, frac=0.7):
    days = sorted(set(mk.df["date"]))
    return days[int(len(days) * frac)]


def verdict(a: dict, b: dict, rand95: float) -> str:
    """a = first 70% of days, b = last 30% (never used to choose anything)."""
    fails = []
    for name, m in (("first period", a), ("last period", b)):
        if m["trades"] < MIN_TRADES:
            fails.append(f"too few trades in {name}")
        elif not (m["net"] > 0 and m["pf"] >= MIN_PF):
            fails.append(f"{name} not profitable enough")
    if not fails and not (b["expectancy"] > rand95):
        fails.append("last period no better than random entries")
    return "PASSES all checks" if not fails else "fails: " + "; ".join(fails)


def evaluate(mk: Market, seed=0, draws=1000):
    cut = split_date(mk)
    pool = random_pool(mk)
    pool["date"] = pd.to_datetime(pool["entry_time"]).dt.date
    rng = np.random.default_rng(seed)
    out, all_trades = [], []
    for name, fn in STRATEGIES.items():
        sig = fn(mk.df)
        for wname, wstart in WINDOWS.items():
            t = run_strategy(mk, sig, wstart)
            t["strategy"], t["window"] = name, wname
            all_trades.append(t)
            d = pd.to_datetime(t["entry_time"]).dt.date
            a, b = t[d < cut]["pnl"], t[d >= cut]["pnl"]
            pm = pool[(pool["date"] >= cut) & (pd.to_datetime(pool["entry_time"]).dt.hour * 60 + pd.to_datetime(pool["entry_time"]).dt.minute >= wstart)]["pnl"].to_numpy()
            if len(b) and len(pm):
                means = rng.choice(pm, size=(draws, len(b))).mean(axis=1)
                r95, rmean = float(np.percentile(means, 95)), float(means.mean())
            else:
                r95 = rmean = np.nan
            ma, mb = metrics(a), metrics(b)
            out.append({"strategy": name, "entries": wname,
                        "first_n": ma["trades"], "first_net": ma["net"], "first_pf": ma["pf"],
                        "last_n": mb["trades"], "last_net": mb["net"], "last_pf": mb["pf"],
                        "last_avg": mb["expectancy"], "random_avg": round(rmean, 1), "random_95th": round(r95, 1),
                        "verdict": verdict(ma, mb, r95)})
    return pd.DataFrame(out), pd.concat(all_trades, ignore_index=True), cut
