"""Download EUR/USD 1-minute bars from your MetaTrader 5 terminal (Windows only).

    python fetch_mt5_data.py --start 2021-01-01 --end 2025-12-31

The MT5 terminal must be installed, running and logged in (a demo account is fine).
Timestamps come out in your broker's SERVER time: set data.source_tz in
config.yaml accordingly (often "Europe/Helsinki" = UTC+2 / UTC+3).
"""
import argparse
from datetime import datetime, timezone

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD")   # some brokers use a suffix, e.g. EURUSD.a
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="data/EURUSD_M1.csv")
    args = ap.parse_args()

    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise SystemExit(f"Could not connect to MT5: {mt5.last_error()}. Is the terminal open and logged in?")
    if not mt5.symbol_select(args.symbol, True):
        raise SystemExit(f"Symbol {args.symbol} not found. Check the exact name in Market Watch.")

    months = pd.date_range(args.start, args.end, freq="MS").tolist()
    edges = [pd.Timestamp(args.start)] + [m for m in months if m > pd.Timestamp(args.start)] \
            + [pd.Timestamp(args.end) + pd.Timedelta(days=1)]
    frames = []
    for a, b in zip(edges[:-1], edges[1:]):
        rates = mt5.copy_rates_range(args.symbol, mt5.TIMEFRAME_M1,
                                     a.to_pydatetime().replace(tzinfo=timezone.utc),
                                     b.to_pydatetime().replace(tzinfo=timezone.utc))
        n = 0 if rates is None else len(rates)
        print(f"{a.date()} -> {b.date()}: {n:,} bars")
        if n:
            frames.append(pd.DataFrame(rates))
    mt5.shutdown()

    if not frames:
        raise SystemExit("No data returned. Your broker may not keep M1 history that far back.")
    df = pd.concat(frames).drop_duplicates("time")
    df["time"] = pd.to_datetime(df["time"], unit="s")          # broker server time
    df[["time", "open", "high", "low", "close", "tick_volume", "spread"]].to_csv(args.out, index=False)
    print(f"Saved {len(df):,} bars to {args.out}")


if __name__ == "__main__":
    main()
