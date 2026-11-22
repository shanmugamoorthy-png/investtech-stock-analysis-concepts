import numpy as np
import pandas as pd
import pytest

from costs import round_trip_cost
from data import detect_clock, to_time
from demo import make_demo
from engine import Market, evaluate, metrics, verdict
from indicators import ema, rsi, swings
from strategies import STRATEGIES


def test_no_lookahead_in_any_strategy():
    idx, _ = make_demo(days=60)
    idx["date"] = idx["time"].dt.date
    for name, fn in STRATEGIES.items():
        full = fn(idx)
        for k in (777, 1203):
            part = fn(idx.iloc[:k].reset_index(drop=True))
            assert (full[:k - 1] == part[:k - 1]).all(), name


def test_indicator_basics():
    s = pd.Series([5.0] * 50)
    assert ema(s, 9).iloc[-1] == pytest.approx(5.0)
    assert rsi(pd.Series(np.arange(1.0, 60))).iloc[-1] == 100.0


def test_swing_confirmed_late():
    h = np.array([1, 2, 5, 2, 1, 1, 1, 1.0])
    out = swings(h, h, k=2)
    assert np.isnan(out[0, 3]) and out[0, 4] == 5          # pivot at bar 2 is known only at bar 4


def _flat_market(n=25):
    t = pd.Timestamp("2025-03-03 09:15") + pd.to_timedelta(np.arange(n) * 15, unit="m")
    df = pd.DataFrame({"time": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0})
    return df


def test_stop_target_and_time_exits():
    df = _flat_market()
    df.loc[6, "low"] = 89.0                                   # touches a long's stop at 90
    mk = Market(df, mode="index", cost_points=0)
    mk.atr[:] = 10.0
    assert mk.pnl(2, 1)[0] == -10.0 and mk.pnl(2, 1)[3] == "stop"
    df = _flat_market(); df.loc[5, "high"] = 120.0           # touches target at 115
    mk = Market(df, mode="index", cost_points=0); mk.atr[:] = 10.0
    r = mk.pnl(2, 1)
    assert r[0] == 15.0 and r[3] == "target"
    df = _flat_market(); df.loc[3:, "close"] = 101.0          # nothing touched: exits after 8 bars at the close
    mk = Market(df, mode="index", cost_points=0); mk.atr[:] = 10.0
    r = mk.pnl(2, 1)
    assert r[3] == "time" and r[2] - r[1] == 7 and r[0] == 1.0


def test_both_touched_counts_as_stop():
    df = _flat_market(); df.loc[4, "low"], df.loc[4, "high"] = 89.0, 120.0
    mk = Market(df, mode="index", cost_points=0); mk.atr[:] = 10.0
    assert mk.pnl(2, 1)[3] == "stop"


def test_cost_formula():
    c = round_trip_cost(100, 110, "2026-11-10")
    assert c == pytest.approx(40 + 7150 * 0.0015 + 13650 * 0.000311 + 13650e-6 + 0.18 * (40 + 13650 * 0.000311 + 13650e-6) + 6500 * 0.00003)


def test_clock_detection():
    days = pd.bdate_range("2025-01-01", periods=6)
    ist = [d + pd.Timedelta(minutes=9 * 60 + 15 + 15 * k) for d in days for k in range(5)]
    unix = ((pd.DatetimeIndex(ist) - pd.Timestamp("1970-01-01")).total_seconds() - 19800).astype("int64")
    assert detect_clock(unix) == "unix_ist"
    assert to_time(unix, "unix_ist").iloc[0] == ist[0]


def test_verdict_rules():
    good = {"trades": 100, "net": 5000.0, "pf": 1.3, "expectancy": 50.0}
    assert verdict(good, good, 10.0) == "PASSES all checks"
    assert "random" in verdict(good, good, 60.0)
    assert "too few" in verdict({**good, "trades": 5}, good, 0)
    assert "not profitable" in verdict(good, {**good, "pf": 1.0}, 0)


def test_pure_noise_does_not_pass_in_index_mode():
    idx, opt = make_demo(days=300, seed=3)
    res, trades, _ = evaluate(Market(idx, opt, "index", 2.0), draws=200)
    assert (res["verdict"] == "PASSES all checks").sum() == 0 and len(trades) > 0
