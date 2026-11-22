import numpy as np
import pandas as pd
import pytest

from evaluate import evaluate
from panel import adjust, build_panel
from portfolio import SCORES, Cfg, K, Run, after_tax, side_costs, stats
from synthetic import make_long


@pytest.fixture(scope="module")
def panel():
    return build_panel(make_long())


def test_split_is_adjusted_away():
    long = make_long()
    adj, n, _ = adjust(long)
    s0 = adj[adj["symbol"] == "S0"].reset_index(drop=True)
    r = s0["close"].pct_change().abs().max()
    raw = long[long["symbol"] == "S0"]["close"].pct_change().abs().max()
    assert n >= 1 and raw > 0.4 and r < 0.15


def test_diagnostics_and_delisting(panel):
    assert panel.diag["stocks_that_stopped_trading"] >= 1
    assert panel.diag["split_or_bonus_adjustments"] >= 1


def test_delisted_stock_gets_haircut(panel):
    run0, run30 = Run(panel, Cfg(haircut=0.0)), Run(panel, Cfg(haircut=0.30))
    sym = list(panel.symbols).index("S1")
    k = next(i for i, (a, b) in enumerate(run0.periods) if panel.dates[b] > panel.last_date["S1"] and panel.dates[a] <= panel.last_date["S1"] and not np.isnan(run0.rets[i][sym]))
    assert run30.rets[k][sym] == pytest.approx((1 + run0.rets[k][sym]) * 0.7 - 1)


def test_picks_use_only_past_data(panel):
    run = Run(panel, Cfg())
    base = run.picks("Momentum 12-1 months")
    a = run.periods[40][0]
    p2 = build_panel(make_long())
    p2.C, p2.O = p2.C.copy(), p2.O.copy()
    p2.C[a:] = p2.C[a:] * np.random.default_rng(1).uniform(0.5, 2, p2.C[a:].shape)   # scramble the future
    p2.O[a:] = p2.O[a:] * 1.3
    again = Run(p2, Cfg()).picks("Momentum 12-1 months")
    assert all(set(x) == set(y) for x, y in zip(base[:40], again[:40]))


def test_costs_and_tax():
    buy, sell = side_costs(Cfg(slippage=0.0))
    assert buy == pytest.approx(0.001 + 0.00015 + 0.0000297 * 1.18 + 1e-6)
    assert sell > buy - 0.00015 + 15.34 / 50000 - 1e-6
    me = pd.to_datetime(["2020-02-03", "2020-03-02", "2020-04-01", "2020-05-04"])
    post = after_tax([0.1, 0.1, 0.1, 0.0], me, 0.2)
    eq_before_tax = 1.1 ** 3
    assert (1 + post[:3]).prod() == pytest.approx(eq_before_tax - 0.2 * (eq_before_tax - 1))   # tax taken in the April period
    loss = after_tax([-0.1, -0.1, 0.0], me[:3], 0.2)
    assert (1 + loss).prod() == pytest.approx(0.81)                                            # no tax on a loss


def test_noise_market_passes_nothing(panel):
    res, series, bench, cut, base = evaluate(panel, Cfg(), draws=200)
    assert len(res) == len(SCORES) and (res["verdict"] == "PASSES all checks").sum() == 0


def test_split_found_even_if_previous_close_is_not_adjusted():
    long = make_long(adjusted_prev=False)
    adj, n, guessed = adjust(long)
    s0 = adj[adj["symbol"] == "S0"].reset_index(drop=True)
    assert n == 0 and guessed >= 1 and s0["close"].pct_change().abs().max() < 0.15
