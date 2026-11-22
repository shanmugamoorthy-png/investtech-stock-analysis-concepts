import pandas as pd

from metrics import revenge_check, summary
from trades import clean, round_trips


def T(i, side, qty, price, time, sid="1", chg=0.0, opt="CALL"):
    return {"exchangeTradeId": str(i), "orderId": str(i), "transactionType": side, "tradedQuantity": qty,
            "tradedPrice": price, "exchangeTime": time, "securityId": sid, "customSymbol": "NIFTY 25800 CE",
            "drvOptionType": opt, "drvStrikePrice": 25800, "brokerageCharges": chg, "instrument": "DERIVATIVES"}


def rts(rows):
    return round_trips(clean(pd.DataFrame(rows)))


def test_simple_long_win():
    rt, op = rts([T(1, "BUY", 75, 100, "2026-11-20 09:30:00", chg=20), T(2, "SELL", 75, 110, "2026-11-20 10:00:00", chg=20)])
    assert len(rt) == 1 and op.empty
    assert rt.loc[0, "gross"] == 750 and rt.loc[0, "charges"] == 40 and rt.loc[0, "net"] == 710


def test_short_first_and_partial_exits():
    rt, op = rts([T(1, "SELL", 150, 100, "2026-11-20 09:30:00"), T(2, "BUY", 75, 90, "2026-11-20 09:40:00"),
                  T(3, "BUY", 75, 120, "2026-11-20 09:50:00")])
    assert len(rt) == 2 and op.empty
    assert list(rt["gross"]) == [750, -1500] and set(rt["direction"]) == {"SHORT"}


def test_unmatched_is_reported_not_pnl():
    rt, op = rts([T(1, "BUY", 75, 100, "2026-11-20 09:30:00"), T(2, "BUY", 75, 50, "2026-11-20 09:35:00", sid="2"),
                  T(3, "SELL", 75, 105, "2026-11-20 10:00:00")])
    assert len(rt) == 1 and len(op) == 1 and op.loc[0, "securityId"] == "2"


def test_duplicates_dropped_and_summary():
    rows = [T(1, "BUY", 75, 100, "2026-11-20 09:30:00"), T(1, "BUY", 75, 100, "2026-11-20 09:30:00"),
            T(2, "SELL", 75, 90, "2026-11-20 09:45:00"),
            T(3, "BUY", 75, 100, "2026-11-20 09:50:00"), T(4, "SELL", 75, 120, "2026-11-20 10:30:00")]
    rt, _ = rts(rows)
    s = summary(rt)
    assert s["round_trips"] == 2 and s["win_rate_%"] == 50.0 and s["net_pnl"] == 750.0
    assert s["payoff_ratio"] == 2.0 and s["longest_losing_streak"] == 1
    r = revenge_check(rt)
    assert r["quick_after_loss_trades"] == 1  # second trade opened 5 min after a loss


def test_works_without_tradingsymbol_column():
    rt, op = rts([T(1, "BUY", 75, 100, "2026-11-20 09:30:00"), T(2, "SELL", 75, 110, "2026-11-20 10:00:00")])
    assert rt.loc[0, "symbol"] == "NIFTY 25800 CE"


def test_symbol_falls_back_to_security_id():
    rows = [T(1, "BUY", 75, 100, "2026-11-20 09:30:00"), T(2, "SELL", 75, 110, "2026-11-20 10:00:00")]
    for r in rows:
        r.pop("customSymbol")
    rt, _ = rts(rows)
    assert rt.loc[0, "symbol"] == "1"


def test_parse_expiry_and_expired_scenario():
    from datetime import date
    from trades import classify_open, parse_expiry
    assert parse_expiry("NIFTY26N0323000CE") == date(2026, 11, 3)
    assert parse_expiry("NIFTY26NOV23000CE") == date(2026, 11, 30)
    assert parse_expiry("NIFTY26NOVFUT") is None
    rt, op = rts([T(1, "BUY", 75, 50, "2026-11-02 09:30:00")])
    op["symbol"] = "NIFTY26N0323000CE"
    o = classify_open(op, today=date(2026, 11, 22))
    assert bool(o.loc[0, "expired"]) and o.loc[0, "pnl_if_zero"] == -3750


def test_zerodha_charges_flat_brokerage_per_order():
    from trades import add_zerodha_charges
    d = pd.DataFrame({"orderId": ["1", "1", "2"], "transactionType": ["BUY", "BUY", "SELL"],
                      "tradedQuantity": [50, 25, 75], "tradedPrice": [100, 100, 110],
                      "drvOptionType": ["CALL"] * 3, "customSymbol": ["NIFTY26N0323000CE"] * 3,
                      "exchangeTime": ["2026-11-20 10:00:00"] * 3})
    c = add_zerodha_charges(d)
    assert abs(c["brokerageCharges"].sum() - 40) < 1e-9          # Rs 20 per order, split across fills
    assert abs(c.loc[2, "stt"] - 75 * 110 * 0.0015) < 1e-9 and c.loc[0, "stt"] == 0


def test_rule_check_flags():
    from metrics import rule_check
    rt, _ = rts([T(1, "BUY", 75, 100, "2026-11-20 09:30:00"), T(2, "SELL", 75, 90, "2026-11-20 09:40:00"),
                 T(3, "BUY", 75, 100, "2026-11-20 09:45:00"), T(4, "SELL", 75, 90, "2026-11-20 09:50:00"),
                 T(5, "BUY", 75, 100, "2026-11-20 14:00:00"), T(6, "SELL", 75, 120, "2026-11-20 14:30:00")])
    c = rule_check(rt)
    assert c.loc["entered before 10:00", "trades"] == 2
    assert c.loc["entered within 15 min of a loss", "trades"] == 1
    assert c.loc["entered after 2 losses that day", "trades"] == 1
    assert c.loc["followed all rules", "trades"] == 0 and c.loc["broke at least one rule", "trades"] == 3


def test_stt_rate_changes_with_date():
    from trades import add_zerodha_charges
    def stt(day):
        d = pd.DataFrame({"orderId": ["1"], "transactionType": ["SELL"], "tradedQuantity": [100], "tradedPrice": [100],
                          "drvOptionType": ["CALL"], "customSymbol": ["NIFTY"], "exchangeTime": [day]})
        return add_zerodha_charges(d).loc[0, "stt"]
    assert abs(stt("2024-05-10") - 10000 * 0.000625) < 1e-9
    assert abs(stt("2025-05-10") - 10000 * 0.001) < 1e-9
    assert abs(stt("2026-11-10") - 10000 * 0.0015) < 1e-9
