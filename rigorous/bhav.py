"""Download NSE daily price files (bhavcopy). They list every stock that traded each day, so stocks that were
later delisted are included. Files are cached, and the download can be stopped and restarted."""
import gzip
import io
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import requests

NEW_FROM = date(2024, 7, 8)
NEW = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
OLD = ["https://nsearchives.nseindia.com/content/historical/EQUITIES/{y}/{mon}/cm{dd}{mon}{y}bhav.csv.zip",
       "https://archives.nseindia.com/content/historical/EQUITIES/{y}/{mon}/cm{dd}{mon}{y}bhav.csv.zip"]
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
           "Accept": "*/*"}
COLS = ["date", "symbol", "open", "high", "low", "close", "prev", "value"]


def urls_for(d: date):
    if d >= NEW_FROM:
        return [NEW.format(ymd=d.strftime("%Y%m%d"))]
    mon = d.strftime("%b").upper()
    return [u.format(y=d.year, mon=mon, dd=f"{d.day:02d}") for u in OLD]


def parse(raw: bytes, d: date) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(raw))
    df = pd.read_csv(z.open(z.namelist()[0]), low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    if "TckrSymb" in df.columns:                                  # new format (from 8 July 2024)
        if "Sgmt" in df:
            df = df[df["Sgmt"] == "CM"]
        df = df[df["SctySrs"].astype(str).str.strip() == "EQ"]
        out = pd.DataFrame({"symbol": df["TckrSymb"].astype(str).str.strip(), "open": df["OpnPric"], "high": df["HghPric"],
                            "low": df["LwPric"], "close": df["ClsPric"], "prev": df["PrvsClsgPric"], "value": df["TtlTrfVal"]})
    else:                                                         # old format
        df = df[df["SERIES"].astype(str).str.strip() == "EQ"]
        out = pd.DataFrame({"symbol": df["SYMBOL"].astype(str).str.strip(), "open": df["OPEN"], "high": df["HIGH"],
                            "low": df["LOW"], "close": df["CLOSE"], "prev": df["PREVCLOSE"], "value": df["TOTTRDVAL"]})
    out.insert(0, "date", pd.Timestamp(d))
    return out[COLS]


def fetch_day(d: date, cache: str):
    p, none = os.path.join(cache, f"{d}.csv.gz"), os.path.join(cache, f"{d}.none")
    if os.path.exists(p):
        return "cached"
    if os.path.exists(none):
        return "holiday"
    err = None
    for url in urls_for(d):
        for attempt in range(3):
            try:
                r = requests.get(url, headers=HEADERS, timeout=40)
            except requests.RequestException as e:
                err = str(e)[:80]
                time.sleep(1 + attempt)
                continue
            if r.status_code == 200:
                try:
                    parse(r.content, d).to_csv(p, index=False, compression="gzip")
                    return "ok"
                except Exception as e:                            # unreadable file: report, do not cache
                    return f"error: could not read file ({type(e).__name__}: {str(e)[:60]})"
            if r.status_code == 404:
                err = "404"
                break
            err = f"HTTP {r.status_code}"
            time.sleep(1 + attempt)
    if err == "404":
        open(none, "w").close()                                   # no file that day: weekend/holiday/not published
        return "holiday"
    return f"error: {err}"


def fetch_range(start: date, end: date, cache: str, workers: int = 6):
    os.makedirs(cache, exist_ok=True)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]
    stats, errors = {}, []
    with ThreadPoolExecutor(workers) as ex:
        for n, (d, r) in enumerate(zip(days, ex.map(lambda x: fetch_day(x, cache), days)), 1):
            key = r if not r.startswith("error") else "error"
            stats[key] = stats.get(key, 0) + 1
            if key == "error" and len(errors) < 5:
                errors.append(f"{d}: {r}")
            if n % 250 == 0:
                print(f"  {n}/{len(days)} days checked ...")
    print(f"Price files: {stats.get('ok', 0)} downloaded, {stats.get('cached', 0)} already saved, "
          f"{stats.get('holiday', 0)} holidays or no file, {stats.get('error', 0)} failed.")
    for e in errors:
        print("  failed:", e)
    return stats


def load_long(cache: str) -> pd.DataFrame:
    frames = [pd.read_csv(os.path.join(cache, f), parse_dates=["date"]) for f in sorted(os.listdir(cache)) if f.endswith(".csv.gz")]
    if not frames:
        raise SystemExit("No price files were downloaded. Send me the 'failed' lines above.")
    df = pd.concat(frames, ignore_index=True)
    for c in ("open", "high", "low", "close", "prev", "value"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["close"]).drop_duplicates(["date", "symbol"]).reset_index(drop=True)
