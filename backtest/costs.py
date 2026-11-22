"""Estimated Zerodha option costs for one buy-then-sell round trip. Estimates; contract notes are the truth."""
LOT = 65            # current NIFTY lot size
BROKERAGE = 20.0   # per executed order, flat for options
SEBI, STAMP, GST = 1e-6, 0.00003, 0.18


def _rates(day):
    """(STT on sell premium, NSE exchange fee) stepped by date."""
    if day < "2024-10-01":
        return 0.000625, 0.000495
    if day < "2026-04-01":
        return 0.001, 0.00035
    return 0.0015, 0.000311


def round_trip_cost(entry_price: float, exit_price: float, day: str, lot: int = LOT) -> float:
    buy, sell = entry_price * lot, exit_price * lot
    stt_rate, txn_rate = _rates(str(day))
    txn = (buy + sell) * txn_rate
    sebi = (buy + sell) * SEBI
    brokerage = 2 * BROKERAGE
    return brokerage + sell * stt_rate + txn + sebi + GST * (brokerage + txn + sebi) + buy * STAMP
