# NIFTY options trade journal (Dhan API)

Pulls **your own** trade history from Dhan, matches buys and sells into round trips (first in, first out) and produces a plain report: win rate, average win vs loss, profit factor, charges, drawdown, results by weekday, entry hour, holding time, calls vs puts, and trades opened quickly after a loss. It makes no predictions. Educational only, not investment advice.

## Run in Google Colab
```
import os
from google.colab import userdata
os.environ["DHAN_ACCESS_TOKEN"] = userdata.get("DHAN_ACCESS_TOKEN")
%cd /content/investtech-stock-analysis-concepts/journal
!python journal.py --days 180 --filter NIFTY --out-dir /content/drive/MyDrive/journal
```
Mount Google Drive first (`from google.colab import drive; drive.mount("/content/drive")`) so the report is kept. Your trade data stays in your Drive; nothing is uploaded elsewhere.

## Notes and limits
- Uses `GET /v2/trades/{from-date}/{to-date}/{page}`. Dhan's docs don't state a page size or a date-range limit, so the script requests 31-day windows and reads pages until one is empty.
- Options that expire worthless have no sell trade, so they appear under "no closing trade found" and are **not** in the P&L. Check that section: your real result can be worse than the summary.
- Charges are the sum of the fields Dhan reports (brokerage, STT, exchange charges, SEBI, stamp duty, service tax). Check them against your contract notes.
- FIFO matching per contract; partial exits are split. Tests are in `test_journal.py` (`python -m pytest -q`).
- Not yet run against a real Dhan account.

## Rule check

The report compares trades that broke three personal rules (no entry before 10:00, wait 15 min after a loss, stop after 2 losses a day) with trades that followed them. Add `--rules-from YYYY-MM-DD` to look only at trades since you started following them.

## Zerodha users

Download your tradebook from Zerodha Console (Reports > Tradebook, segment F&O, pick the date range), upload the file to Colab and run:

    python journal.py --zerodha /content/tradebook.csv --filter NIFTY --out-dir /content/drive/MyDrive/journal

The tradebook has no charges, so the journal estimates them from Zerodha's published rates (Rs 20 per order, STT, exchange fees, GST, stamp duty). Treat that as an estimate and check against your contract notes. Futures are left out unless you add --include-futures. Options that expired with no closing trade are listed separately with a "if worthless" figure.

For a long history, download the tradebook in pieces (for example one file per financial year), put all files in one folder, and pass the folder: `--zerodha /content/tradebooks`. Repeated trades across files are dropped. STT and exchange fees are stepped by date for older trades; still estimates.
