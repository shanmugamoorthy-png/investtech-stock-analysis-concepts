"""Plain performance statistics from closed round trips."""
import numpy as np
import pandas as pd


def summary(rt: pd.DataFrame) -> dict:
    n = len(rt)
    wins, losses = rt[rt["net"] > 0], rt[rt["net"] <= 0]
    gl = -losses["net"].sum()
    cum = rt.sort_values("exit_time")["net"].cumsum()
    dd = (cum.cummax() - cum).max() if n else 0.0
    # longest losing streak by exit time
    streak = best = 0
    for v in rt.sort_values("exit_time")["net"]:
        streak = streak + 1 if v <= 0 else 0
        best = max(best, streak)
    return {
        "round_trips": n,
        "win_rate_%": round(len(wins) / n * 100, 1) if n else 0.0,
        "avg_win": round(wins["net"].mean(), 0) if len(wins) else 0.0,
        "avg_loss": round(losses["net"].mean(), 0) if len(losses) else 0.0,
        "payoff_ratio": round(wins["net"].mean() / -losses["net"].mean(), 2) if len(wins) and len(losses) and losses["net"].mean() else None,
        "profit_factor": round(wins["net"].sum() / gl, 2) if gl else None,
        "expectancy_per_trade": round(rt["net"].mean(), 0) if n else 0.0,
        "gross_pnl": round(rt["gross"].sum(), 0),
        "charges": round(rt["charges"].sum(), 0),
        "net_pnl": round(rt["net"].sum(), 0),
        "charges_as_%_of_gross_profit": round(rt["charges"].sum() / wins["gross"].sum() * 100, 1) if len(wins) and wins["gross"].sum() > 0 else None,
        "max_drawdown": round(dd, 0),
        "longest_losing_streak": best,
        "biggest_loss": round(rt["net"].min(), 0) if n else 0.0,
        "biggest_win": round(rt["net"].max(), 0) if n else 0.0,
    }


def breakdown(rt: pd.DataFrame, key: pd.Series, name: str) -> pd.DataFrame:
    g = rt.groupby(key, observed=False)["net"].agg(trades="size", net_pnl="sum", avg_pnl="mean",
                                  win_rate_pct=lambda x: (x > 0).mean() * 100)
    g.index.name = name
    return g.round(1)


def revenge_check(rt: pd.DataFrame, minutes: int = 10) -> dict:
    """Trades opened within `minutes` after the previous trade closed at a loss."""
    r = rt.sort_values("entry_time").reset_index(drop=True)
    exits = rt.sort_values("exit_time")[["exit_time", "net"]].reset_index(drop=True)
    flag = []
    for _, t in r.iterrows():
        prev = exits[exits["exit_time"] <= t["entry_time"]]
        if prev.empty:
            flag.append(False)
            continue
        last = prev.iloc[-1]
        flag.append(bool(last["net"] < 0 and (t["entry_time"] - last["exit_time"]) <= pd.Timedelta(minutes=minutes)))
    r["after_loss_quick"] = flag
    a, b = r[r["after_loss_quick"]], r[~r["after_loss_quick"]]
    return {"quick_after_loss_trades": len(a),
            "avg_net_quick_after_loss": round(a["net"].mean(), 0) if len(a) else None,
            "avg_net_other_trades": round(b["net"].mean(), 0) if len(b) else None,
            "win_rate_quick_%": round((a["net"] > 0).mean() * 100, 1) if len(a) else None,
            "win_rate_other_%": round((b["net"] > 0).mean() * 100, 1) if len(b) else None}


def rule_check(rt: pd.DataFrame, start_hour: int = 10, wait_minutes: int = 15, max_losses: int = 2) -> pd.DataFrame:
    """Compare trades that broke each personal rule with trades that did not. Describes the past; proves nothing."""
    r = rt.sort_values("entry_time").reset_index(drop=True).copy()
    exits = rt.sort_values("exit_time")[["exit_time", "net"]].reset_index(drop=True)
    early, quick, over = [], [], []
    for _, t in r.iterrows():
        e = t["entry_time"]
        early.append(e.hour < start_hour)
        prev = exits[exits["exit_time"] <= e]
        last = prev.iloc[-1] if len(prev) else None
        quick.append(bool(last is not None and last["net"] < 0 and (e - last["exit_time"]) <= pd.Timedelta(minutes=wait_minutes)))
        today = prev[prev["exit_time"].dt.date == e.date()]
        over.append(int((today["net"] < 0).sum()) >= max_losses)
    r["early"], r["quick"], r["over"] = early, quick, over
    r["any"] = r["early"] | r["quick"] | r["over"]
    rows = []
    for label, col, inv in [(f"entered before {start_hour}:00", "early", False),
                            (f"entered within {wait_minutes} min of a loss", "quick", False),
                            (f"entered after {max_losses} losses that day", "over", False),
                            ("broke at least one rule", "any", False),
                            ("followed all rules", "any", True)]:
        m = ~r[col] if inv else r[col]
        g = r[m]
        rows.append({"group": label, "trades": len(g), "net_pnl": round(g["net"].sum(), 0),
                     "avg_pnl": round(g["net"].mean(), 0) if len(g) else None,
                     "win_rate_%": round((g["net"] > 0).mean() * 100, 1) if len(g) else None})
    return pd.DataFrame(rows).set_index("group")
