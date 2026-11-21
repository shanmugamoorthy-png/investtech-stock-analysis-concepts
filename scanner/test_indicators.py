import numpy as np
import pandas as pd

from indicators import range_break, read, trend_channel, volume_balance


def make(drift, n=400, seed=1, vol_up=1.0):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(drift * np.arange(n) + rng.normal(0, 0.02, n))
    ret = np.diff(close, prepend=close[0])
    vol = np.where(ret > 0, 1000 * vol_up, 1000.0)
    return pd.DataFrame({"open": close, "high": close * 1.005, "low": close * 0.995,
                         "close": close, "volume": vol})


def test_rising_and_falling_trend():
    assert trend_channel(make(0.001)["close"])["direction"] == "rising"
    assert trend_channel(make(-0.001)["close"])["direction"] == "falling"


def test_sideways():
    assert trend_channel(make(0.0, seed=3)["close"], flat_pct=60)["direction"] == "sideways"


def test_volume_balance_sign():
    assert volume_balance(make(0.001, vol_up=3.0)) > 0
    assert volume_balance(make(0.001, vol_up=0.3)) < 0


def test_range_break_up_with_volume():
    df = make(0.0, seed=5)
    df.loc[df.index[-1], ["close", "high"]] = df["high"].max() * 1.05
    df.loc[df.index[-1], "volume"] = 10000
    assert range_break(df) == "break up (volume confirmed)"


def test_read_order_trend_first():
    t = {"direction": "rising"}
    assert "NOT confirming" in read(t, -5)
