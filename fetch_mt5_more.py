"""More broker history (read-only MT5) for run_more_markets.py / run_more_trades.py.

    python fetch_mt5_more.py
      data/mt5/<SYM>_H1.csv    hourly from ~mid-2018: commodities, more indices, FX crosses
      data/mt5/<SYM>_M15.csv   15-minute, ~60k bars (~2.4 years): live pairs + a few crosses
"""
import os
import sys

sys.path.insert(0, os.getcwd())
import MetaTrader5 as mt5
import pandas as pd

from fxbot.data import server_ts_to_utc

H1 = ["Copper", "US Natural Gas", "Heating Oil", "UK Oil", "Sugar - Cash", "Coffee C",
      "US2000", "HK50", "AUS200", "CHINAA50", "FRA40", "ESP35", "SWISS20",
      "USDCAD.", "USDCHF.", "NZDUSD.", "EURGBP.", "EURAUD.", "GBPAUD.", "EURCAD.", "GBPCAD.",
      "AUDNZD.", "EURCHF.", "GBPCHF.", "AUDCAD.", "NZDJPY.", "CHFJPY.", "EURNZD.", "GBPNZD."]
M15 = ["EURUSD.", "GBPUSD.", "USDJPY.", "XAUUSD", "AUDUSD.", "USDCAD.", "USDCHF.", "NZDUSD.", "EURGBP."]


def fetch(n, tf, count, suffix):
    if not mt5.symbol_select(n, True):
        print(n, "not selectable", mt5.last_error()); return
    r = mt5.copy_rates_from_pos(n, tf, 0, count)
    if r is None or not len(r):
        print(n, "none", mt5.last_error()); return
    df = pd.DataFrame(r)
    df.index = server_ts_to_utc(df["time"].values)
    df = df[df.index.notna()]
    df = df[~df.index.duplicated()].sort_index()
    info = mt5.symbol_info(n)
    out = pd.DataFrame({"open": df.open, "high": df.high, "low": df.low, "close": df.close,
                        "spread_pts": df.spread, "point": info.point})
    fn = "data/mt5/" + n.replace(" ", "").replace(".", "").replace("-", "") + f"_{suffix}.csv"
    out.to_csv(fn, index_label="time")
    print(f"{n:<16} {suffix} {len(out):6d} {out.index[0].date()} .. {out.index[-1].date()} "
          f"median spread pts {df.spread.median():.0f}  point {info.point}  "
          f"contract {info.trade_contract_size}  swap L/S {info.swap_long}/{info.swap_short}  {fn}")


if __name__ == "__main__":
    mt5.initialize()
    os.makedirs("data/mt5", exist_ok=True)
    for n in H1:
        fetch(n, mt5.TIMEFRAME_H1, 99000, "H1")
    for n in M15:
        fetch(n, mt5.TIMEFRAME_M15, 99000, "M15")
    mt5.shutdown()
