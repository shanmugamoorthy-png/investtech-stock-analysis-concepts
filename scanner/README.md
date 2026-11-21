# NIFTY trend + volume scanner (Dhan API)

Applies simple versions of the concepts in this repo (trend channel, volume confirmation, range break) to daily candles from the DhanHQ v2 API. **Educational only, not investment advice.** The indicators are my own basic approximations, not Investtech's algorithms.

## What it computes
- **Trend channel:** regression line on log price over ~375 bars (about 18 months), floor/ceiling at +/-2 residual std. Reports direction, annualised slope, R², and position in the channel (0 floor, 1 ceiling).
- **Volume balance (approx.):** (up-day volume - down-day volume) / total over 22 days, scaled -100..100.
- **60-day range break:** close beyond the prior 60-day high/low, flagged if volume is above 1.5x the 22-day average.
- **Read:** trend first, volume confirms.

## Setup
```
pip install pandas numpy requests pytest
export DHAN_ACCESS_TOKEN=...   # from your Dhan account; never commit it
export DHAN_CLIENT_ID=...      # optional
python dhan_scanner.py --symbols symbols.csv --out results.csv
```
Historical candles use `POST https://api.dhan.co/v2/charts/historical`, which is part of Dhan's Data APIs and may need an active data plan. Add stocks to `symbols.csv` using Dhan's security ID list (the four included IDs come from Dhan docs and forum examples; confirm them).

Offline mode: `python dhan_scanner.py --csv-dir ./candles` with `<symbol>.csv` files (columns `date,open,high,low,close,volume`).

## Tests
`python -m pytest -q` (runs on synthetic data). The live Dhan call has not been tested against a real account.
