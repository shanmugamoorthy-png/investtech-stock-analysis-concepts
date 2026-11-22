# NIFTY strategy backtest (price action and indicators)

Tests six fixed strategies on NIFTY 15-minute candles, buying a weekly ATM call (buy signal) or put (sell signal), using Dhan's historical data. Records and statistics only. Past results do not predict the future. Not investment advice.

## Strategies (settings fixed in advance, never tuned)
1. Opening range breakout (first 30 minutes)
2. Previous day high/low break
3. EMA 9/21 cross
4. RSI(14) pullback in an EMA20/50 trend
5. Supertrend(10, 3) flip
6. Swing high/low break with rising lows / falling highs

Each is run two ways: entries any time from 9:30, or only from 10:00 (the 9 AM hour lost money in the trade journal). 12 combinations in all.

## Fixed rules
Signal at bar close, entry at next bar open. Stop 1 ATR, target 1.5 ATR on the index, exit after 8 bars or 15:15. Max 2 trades a day, one at a time, no entries after 14:30. Stop wins if both are touched in one bar.

## Money
Options mode prices the real weekly ATM contract from Dhan's expired-options data, with 0.5 point slippage each side and estimated Zerodha charges (Rs 20 per order, STT, exchange fee, GST, stamp duty), per lot of 65. Exit premium is the option's close at the exit bar. Index mode (the default) uses NIFTY index points with a flat cost of 4 points per trade (about 1.6 for charges and 2 for slippage on a 65-qty at-the-money option, with each index point worth about Rs 32 per lot). Option time decay is not included, so real option results would be lower.

## How a combination can pass
Data is split 70% first, 30% last by date. Nothing is chosen using the last 30%. A combination passes only if it has at least 60 trades in each part, is profitable with profit factor of at least 1.15 in both, and the last part beats 95% of random entries (same exit rules, same time window). Because 12 combinations are tried, one or two passing by luck is expected, so a pass is a reason to look closer, not proof.

## Run
    python run.py --mode index --days 730 --out-dir /content/drive/MyDrive/backtest
    python run.py --demo          # synthetic data, checks the plumbing

## Test your own rule
    python custom.py --entry orb --range-minutes 15 --stop 30 --target 45 --earliest 10:00 --out-dir /content/drive/MyDrive/backtest
Options: `--entry orb|prevday`, `--direction both|long|short`, `--timeframe 5|15`, `--max-hold-minutes`, `--latest`, `--max-trades-per-day`. Test a rule once; trying many numbers until one looks good only finds luck.

## F&O stocks
    python stocks.py --limit 50 --out-dir /content/drive/MyDrive/backtest_stocks
Runs the same six strategies (and the same pass checks) over a random sample of today's F&O stocks, trading the stock's own price move, with results in basis points per trade after an 8 bp round-trip cost. Stock options would add wider spreads and time decay, so they would do worse. Today's F&O list over-represents stocks that grew into it (survivorship).
