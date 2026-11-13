"""Download hourly history of the largest US stock CFDs from MT5 (read-only).

    python fetch_mt5_stocks.py [--refresh]   # -> data/mt5/stocks/<name>_H1.csv (skips existing)

Two lists: the biggest companies today, and the biggest at the start of 2013 (what someone
choosing "top companies" would have picked when the data begins). Used by run_stocks.py.
"""
import os
import sys

sys.path.insert(0, os.getcwd())
import MetaTrader5 as mt5
import pandas as pd

from fxbot.data import server_ts_to_utc

TOP_NOW = ["Nvidia", "Apple", "Microsoft", "Alphabet Inc A", "Amazon", "Meta Platforms Inc", "Broadcom Ltd",
           "Tesla Motors", "Berkshire Hathaway - Class B", "Eli Lilly", "Visa", "Oracle"]
TOP_2013 = ["Apple", "Exxon Mobil", "Alphabet Inc A", "Walmart", "Microsoft", "Berkshire Hathaway - Class B",
            "General Electric", "IBM", "Chevron Corp", "Johnson & Johnson", "Procter and Gamble", "AT&T",
            "Pfizer", "Wells Fargo and Co"]
# second halves of the pairs in run_stock_edges.py
PAIR_EXTRA = ["Mastercard", "Coca Cola Co", "PepsiCo", "J.P. Morgan", "Bank Of America", "Goldman Sachs",
              "Morgan Stanley", "Costco", "Merck and Co"]


def fname(n):
    return "data/mt5/stocks/" + "".join(ch for ch in n if ch.isalnum()) + "_H1.csv"


if __name__ == "__main__":
    os.makedirs("data/mt5/stocks", exist_ok=True)
    mt5.initialize()
    for n in dict.fromkeys(TOP_NOW + TOP_2013 + PAIR_EXTRA):
        if os.path.exists(fname(n)) and "--refresh" not in sys.argv:
            continue
        mt5.symbol_select(n, True)
        r = mt5.copy_rates_from_pos(n, mt5.TIMEFRAME_H1, 0, 99000)
        if r is None or not len(r):
            print(n, "none", mt5.last_error())
            continue
        df = pd.DataFrame(r)
        df.index = server_ts_to_utc(df["time"].values)
        df = df[df.index.notna()]
        df = df[~df.index.duplicated()].sort_index()
        info = mt5.symbol_info(n)
        out = pd.DataFrame({"open": df.open, "high": df.high, "low": df.low, "close": df.close,
                            "spread_pts": df.spread, "point": info.point})
        out.to_csv(fname(n), index_label="time")
        print(f"{n:30s} {len(out):6d} {out.index[0]} -> {out.index[-1]}  med spread {df.spread.median()} pts")
