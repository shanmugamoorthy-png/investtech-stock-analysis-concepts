# Rigorous stock test (NSE, including delisted stocks)

Tests five simple, fixed stock-picking rules on NSE shares with more care than the earlier scans. Records and statistics only. Not investment advice; past results do not predict the future.

## What makes it more rigorous
- **Stocks that were later delisted are included.** Prices come from NSE's own daily files (bhavcopy), which list every stock that traded each day. The stock list at each month is rebuilt from that month's data, so no stock is added because it survived.
- **Splits and bonuses are adjusted** using NSE's adjusted previous close, with a fallback that spots one-day jumps matching standard split ratios. Dividends are not included.
- **Costs and tax:** STT on both sides, stamp duty, exchange and SEBI fees, GST, DP charge per stock sold, slippage (0.10% per side), and 20.8% short-term capital gains tax (20% plus 4% cess) on each financial year's gain. Loss carry-forward is ignored.
- **Hold-out:** the last 40% of months are judged separately.
- **Random baseline:** 500 random portfolios per test, drawn from the same stocks each month.
- **Stress case:** 0.25% slippage and a 30% loss on any stock that stops trading while held.

## Rules (fixed in advance, never tuned)
Each month, buy the top 20 by one rule among the 300 most traded stocks (median daily value of at least 5 crore), at that day's open, using only data up to the day before: momentum 12-1 months, near 52-week high, trend (above 200-day average, 50-day above 200-day), reversal of the worst last month, low volatility.

## A rule passes only if
1. Its picks beat 95% of random portfolios (before costs, hold-out).
2. After costs and tax, hold-out growth is positive and beats the passive benchmark (equal-weight of the same stocks, before any cost or tax).
3. It beats that benchmark in at least 60% of calendar years.
4. It still makes money under the stress case.

## Run
    python run.py --start 2018-01-01 --out-dir /content/drive/MyDrive/rigorous
    python run.py --demo

The first run downloads about 2,000 daily files from NSE (resumable; run again if some fail).

## Known limits
A symbol that changes name looks like a delisting plus a new listing. Delisting losses are unknown, hence the stress case. Position sizes assume Rs 10 lakh across 20 stocks. Dividends are left out, which understates buy-and-hold returns.
