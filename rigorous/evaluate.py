"""Pre-set checks. Rules were fixed before any results were seen; the last 40% of months is the hold-out."""
import numpy as np
import pandas as pd

from portfolio import SCORES, Cfg, Run, after_tax, by_year, stats

HOLDOUT = 0.4
MIN_YEARS_BEAT = 0.6


def evaluate(p, cfg: Cfg, draws=500):
    base = Run(p, cfg)
    stress = Run(p, Cfg(**{**cfg.__dict__, "slippage": max(cfg.slippage, 0.0025), "haircut": 0.30}))
    n = len(base.periods)
    cut = int(n * (1 - HOLDOUT))
    ins, hold = list(range(cut)), list(range(cut, n))
    bench = base.benchmark()
    rand = base.random_means(hold, draws)
    rows, series = [], {}
    for name in SCORES:
        pk, pk_s = base.picks(name), stress.picks(name)
        gross, net = base.gross(pk), base.net(pk)
        net_s = stress.net(pk_s)
        me = np.array(base.month_end)
        post = after_tax(net, me, cfg.tax)
        post_s = after_tax(net_s, me, cfg.tax)
        series[name] = pd.Series(post, index=me)
        h = lambda x: np.asarray(x)[hold]
        i_ = lambda x: np.asarray(x)[ins]
        hold_post = after_tax(h(net), me[hold], cfg.tax)
        hold_post_s = after_tax(h(net_s), me[hold], cfg.tax)
        st_h, st_i = stats(hold_post, hold), stats(after_tax(i_(net), me[ins], cfg.tax), ins)
        st_b = stats(h(bench), hold)
        gross_mean = float(h(gross).mean())
        r95 = float(np.percentile(rand, 95))
        yr, cnt = by_year(post, me)
        yb, _ = by_year(bench, me)
        full = cnt[cnt >= 6].index
        beat = float((yr[full] > yb[full]).mean()) if len(full) else np.nan
        stress_cagr = stats(hold_post_s, hold)["cagr_%"]
        fails = []
        if not gross_mean > r95:
            fails.append("signal no better than random picks")
        if not (st_h["cagr_%"] > 0 and st_h["cagr_%"] > st_b["cagr_%"]):
            fails.append("after costs and tax does not beat the passive benchmark in the hold-out")
        if not (beat >= MIN_YEARS_BEAT):
            fails.append("beats benchmark in fewer than 60% of years")
        if not stress_cagr > 0:
            fails.append("loses money under stress costs and delisting losses")
        rows.append({"strategy": name, "in_sample_cagr_%": st_i["cagr_%"], "holdout_cagr_%": st_h["cagr_%"],
                     "holdout_maxdd_%": st_h["max_drawdown_%"], "benchmark_cagr_%": st_b["cagr_%"],
                     "gross_monthly_%": round(gross_mean * 100, 2), "random_95th_%": round(r95 * 100, 2),
                     "years_beating_bench_%": round(beat * 100) if beat == beat else np.nan, "stress_cagr_%": stress_cagr,
                     "verdict": "PASSES all checks" if not fails else "fails: " + "; ".join(fails)})
    return pd.DataFrame(rows), series, bench, me[cut], base
