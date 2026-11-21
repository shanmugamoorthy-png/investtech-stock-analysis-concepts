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
