"""Combine histdata.com MetaTrader M1 CSV files into one clean UTC CSV.

Histdata MetaTrader format:
  - No header row
  - Columns: Date, Time, Open, High, Low, Close, Volume
  - Date format: YYYY.MM.DD
  - Time format: HH:MM
  - Timestamps in New York time (fixed UTC-5, no DST)

Usage:
    python combine_histdata.py

Output: data/EURUSD_M1_histdata.csv
  - header: time,open,high,low,close
  - timestamps in UTC
  - ready for: source_tz: UTC  in config.yaml
"""
from pathlib import Path
import pandas as pd

HISTDATA_DIR = Path("data/histdata")
OUTPUT      = Path("data/EURUSD_M1_histdata.csv")
NY_OFFSET   = pd.Timedelta(hours=5)   # histdata uses fixed UTC-5


def load_one(path):
    df = pd.read_csv(
        path,
        header=None,
        names=["date", "time_str", "open", "high", "low", "close", "volume"],
        dtype={"date": str, "time_str": str},
    )
    # Parse datetime and shift to UTC
    raw = pd.to_datetime(df["date"] + " " + df["time_str"], format="%Y.%m.%d %H:%M")
    ts = raw + NY_OFFSET                     # fixed UTC-5 → UTC
    ts = ts.dt.tz_localize("UTC")
    df.index = ts
    df.index.name = "time"
    return df[["open", "high", "low", "close"]].astype(float)


def main():
    files = sorted(HISTDATA_DIR.glob("DAT_MT_EURUSD_M1_*.csv"))
    if not files:
        raise SystemExit(f"No CSV files found in {HISTDATA_DIR}")

    frames = []
    for f in files:
        print(f"  Loading {f.name} ...", end=" ", flush=True)
        df = load_one(f)
        print(f"{len(df):,} bars  {df.index[0].date()} to {df.index[-1].date()}")
        frames.append(df)

    combined = pd.concat(frames)
    combined = combined[~combined.index.duplicated(keep="first")].sort_index()

    print(f"\nCombined: {len(combined):,} bars")
    print(f"Range:    {combined.index[0]} to {combined.index[-1]}")

    OUTPUT.parent.mkdir(exist_ok=True)
    combined.to_csv(OUTPUT)
    print(f"Saved: {OUTPUT}")
    print("\nNext: update config.yaml")
    print("  data:")
    print(f"    path: {OUTPUT}")
    print("    source_tz: UTC")
    print("    timeframe: 5min")


if __name__ == "__main__":
    main()
