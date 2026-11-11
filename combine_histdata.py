"""Combine histdata.com MetaTrader M1 CSV files into one clean UTC CSV.

Histdata MetaTrader format:
  - No header row
  - Columns: Date, Time, Open, High, Low, Close, Volume
  - Date format: YYYY.MM.DD
  - Time format: HH:MM
  - Timestamps in New York time (fixed UTC-5, no DST)

Usage:
    python combine_histdata.py                   # EURUSD  → data/EURUSD_M1_histdata.csv
    python combine_histdata.py --symbol GBPUSD   # GBPUSD  → data/GBPUSD_M1_histdata.csv

Input directory convention:
    data/histdata/<SYMBOL>/DAT_MT_<SYMBOL>_M1_<year>.csv   (gap reports in <SYMBOL>/reports/)
"""
import argparse
from pathlib import Path
import pandas as pd

NY_OFFSET = pd.Timedelta(hours=5)   # histdata uses fixed UTC-5


def histdata_dir(symbol: str) -> Path:
    # One folder per market: data/histdata/<SYMBOL>/DAT_MT_<SYMBOL>_M1_<year>.csv
    # (histdata's .txt gap reports go in data/histdata/<SYMBOL>/reports/).
    # Older layouts (all files loose in data/histdata/, or data/histdata_<symbol>/) still work.
    sym = symbol.upper()
    for d in (Path("data/histdata") / sym, Path("data/histdata"), Path(f"data/histdata_{symbol.lower()}")):
        if list(d.glob(f"DAT_MT_{sym}_M1_*.csv")):
            return d
    return Path("data/histdata") / sym


def output_path(symbol: str) -> Path:
    return Path(f"data/{symbol.upper()}_M1_histdata.csv")


def load_one(path):
    df = pd.read_csv(
        path,
        header=None,
        names=["date", "time_str", "open", "high", "low", "close", "volume"],
        dtype={"date": str, "time_str": str},
    )
    raw = pd.to_datetime(df["date"] + " " + df["time_str"], format="%Y.%m.%d %H:%M")
    ts = raw + NY_OFFSET
    ts = ts.dt.tz_localize("UTC")
    df.index = ts
    df.index.name = "time"
    return df[["open", "high", "low", "close"]].astype(float)


def combine(symbol: str):
    src = histdata_dir(symbol)
    out = output_path(symbol)
    pattern = f"DAT_MT_{symbol.upper()}_M1_*.csv"
    files = sorted(src.glob(pattern))
    if not files:
        raise SystemExit(
            f"No files matching {pattern} found in {src}\n"
            f"Download {symbol} M1 data from histdata.com (MetaTrader format) "
            f"and place the CSV files in {src}/"
        )

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

    out.parent.mkdir(exist_ok=True)
    combined.to_csv(out)
    print(f"Saved: {out}")
    return out


def main():
    parser = argparse.ArgumentParser(description="Combine histdata.com M1 CSV files")
    parser.add_argument("--symbol", default="EURUSD", help="Currency pair (default: EURUSD)")
    args = parser.parse_args()
    combine(args.symbol)


if __name__ == "__main__":
    main()
