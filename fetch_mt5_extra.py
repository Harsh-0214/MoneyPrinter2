"""Extra broker history for run_carry.py and run_news_reaction.py (read-only MT5).

    python fetch_mt5_extra.py
      data/cot/NZD_D1.csv               NZDUSD daily (the other currencies come from fetch_cot.py)
      data/mt5/<SYM>_M5_2026.csv        5-minute bars Jan 1 2026 -> now, UTC, for the news test
"""
import os
import sys

sys.path.insert(0, os.getcwd())
import MetaTrader5 as mt5
import pandas as pd

from fxbot.data import server_ts_to_utc


def frame(r):
    df = pd.DataFrame(r)
    df.index = server_ts_to_utc(df["time"].values)
    df = df[df.index.notna()]
    return df[~df.index.duplicated()].sort_index()


if __name__ == "__main__":
    mt5.initialize()
    mt5.symbol_select("NZDUSD.", True)
    d = frame(mt5.copy_rates_from_pos("NZDUSD.", mt5.TIMEFRAME_D1, 0, 9000))
    d.index = (d.index + pd.Timedelta(hours=3)).normalize().tz_localize(None)   # server-day label
    d[["open", "high", "low", "close"]].to_csv("data/cot/NZD_D1.csv", index_label="date")
    print("NZD", len(d), d.index[0].date(), d.index[-1].date())
    os.makedirs("data/mt5", exist_ok=True)
    for s in ["EURUSD.", "GBPUSD.", "USDJPY.", "XAUUSD"]:
        mt5.symbol_select(s, True)
        r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M5, 0, 99000)     # ~15 months
        m = frame(r)[["open", "high", "low", "close", "spread"]]
        m = m[m.index >= "2025-12-01"]
        fn = f"data/mt5/{s.replace('.', '')}_M5_2026.csv"
        m.to_csv(fn, index_label="time")
        print(s, len(m), m.index[0], m.index[-1])
