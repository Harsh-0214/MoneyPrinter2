"""Download EUR/USD 1-minute BID candles directly from Dukascopy's data server.

No account needed. Downloads the same data as their website, but automated.

    python download_dukascopy.py --start 2021-01-01 --end 2025-12-31

Output: data/EURUSD_M1.csv  (source_tz: UTC — timestamps are already UTC)
After running, set data.source_tz: "UTC" in config.yaml.
"""
import argparse
import logging
import lzma
import struct
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

# Dukascopy stores months 0-indexed in the URL (Jan=00, Dec=11)
URL = "https://datafeed.dukascopy.com/datafeed/{instrument}/{year}/{month:02d}/{day:02d}/BID_candles_min_1.bi5"
INSTRUMENT = "EURUSD"
POINT = 100_000   # 5-decimal EUR/USD prices stored as integers


def _setup_logging():
    Path("logs").mkdir(exist_ok=True)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"logs/dukascopy_download_{stamp}.log"
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(
        level=logging.INFO, format=fmt,
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
    )
    return logging.getLogger("duka"), log_path


def _parse_bi5(raw_bytes, day_date):
    """Decompress and parse one day's bi5 candle file.

    Each record is 24 bytes:
      uint32 BE  time_ms  — milliseconds from midnight UTC of day_date
      uint32 BE  open     — price * POINT
      uint32 BE  high
      uint32 BE  low
      uint32 BE  close
      float32 BE volume   — tick volume (unused by our strategy)
    """
    try:
        data = lzma.decompress(raw_bytes)
    except Exception:
        return None

    record_size = 24   # 5 × uint32 + 1 × float32
    n = len(data) // record_size
    if n == 0:
        return None

    base = pd.Timestamp(day_date, tz="UTC")
    rows = []
    for i in range(n):
        b = data[i * record_size: (i + 1) * record_size]
        t_ms, o, h, l, c = struct.unpack(">IIIII", b[:20])
        ts = base + pd.Timedelta(milliseconds=int(t_ms))
        rows.append({
            "time": ts,
            "open":  o / POINT,
            "high":  h / POINT,
            "low":   l / POINT,
            "close": c / POINT,
        })
    return pd.DataFrame(rows)


def _download_day(session, day_date, instrument=INSTRUMENT, retries=3):
    url = URL.format(
        instrument=instrument,
        year=day_date.year,
        month=day_date.month - 1,   # Dukascopy months are 0-indexed
        day=day_date.day,
    )
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 404 or len(r.content) == 0:
                return None   # weekend or holiday — normal
            if r.status_code == 200:
                return _parse_bi5(r.content, day_date)
        except requests.RequestException as e:
            if attempt == retries:
                return None
            time.sleep(2 ** attempt)
    return None


def main():
    log, log_path = _setup_logging()
    log.info("Log: %s", log_path)

    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end",   default="2025-12-31")
    ap.add_argument("--instrument", default=INSTRUMENT,
                    help="Dukascopy symbol, e.g. EURUSD, GBPUSD, AUDUSD (USD-quoted pairs only)")
    ap.add_argument("--out",   default=None, help="default: data/<INSTRUMENT>_M1_duka.csv")
    ap.add_argument("--delay", type=float, default=0.1,
                    help="Seconds between requests (be polite to their server)")
    args = ap.parse_args()

    instrument = args.instrument.upper()
    args.out = args.out or f"data/{instrument}_M1_duka.csv"
    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    total_days = (end - start).days + 1

    log.info("Downloading %s M1 BID  %s -> %s  (%d days)", instrument, start, end, total_days)
    log.info("Output: %s", args.out)

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"

    frames = []
    done = skipped = errors = 0
    current = start

    while current <= end:
        df = _download_day(session, current, instrument)
        if df is not None and len(df) > 0:
            frames.append(df)
            done += 1
        else:
            skipped += 1   # weekend / holiday

        if (done + skipped) % 50 == 0:
            pct = (done + skipped) / total_days * 100
            log.info("Progress: %.0f%%  days_with_data=%d  skipped=%d", pct, done, skipped)

        current += timedelta(days=1)
        time.sleep(args.delay)

    if not frames:
        raise SystemExit("No data downloaded. Check your internet connection.")

    log.info("Combining %d days...", done)
    df_all = pd.concat(frames, ignore_index=True)
    df_all = df_all.drop_duplicates("time").sort_values("time")

    # Save with time as a plain UTC string so load_csv handles it correctly
    df_all["time"] = df_all["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df_all.to_csv(args.out, index=False)

    log.info("Saved %s bars to %s", f"{len(df_all):,}", args.out)
    log.info("Done. Set data.source_tz: 'UTC' in config.yaml before backtesting.")
    log.info("Then run: python check_weekly_open.py")


if __name__ == "__main__":
    main()
