"""The daily RSI-2 pullback (GBPUSD live settings, untuned) on CHFJPY: the broker's
full hourly history 2011-2026, year by year. Found by run_new_markets.py round 2
(13 Nov 2026); this is the long-history check before it is taken seriously.

    python run_chfjpy_pullback.py
"""
import copy
import pandas as pd
from run_new_markets import MARKETS, STRATS, load, make_cfg, _v
from fxbot.backtest import run_backtest
from run_validate import per_year, summarize

DPB = STRATS["Pullback (GBP live)"]
VARS = {"CHFJPY pullback (GBP live)": DPB,
        "CHFJPY pullback long-only": _v(DPB, long_only=True),
        "CHFJPY pullback SMA100": _v(DPB, trend_sma=100),
        "CHFJPY pullback 3xATR stop": _v(DPB, stop_atr=3.0),
        "CHFJPY pullback RSI<5/>95": _v(DPB, oversold=5, overbought=95)}
sym = "CHFJPY"
path, floor, _ = MARKETS[sym]
df = pd.read_csv(path, index_col=0)
df.index = pd.to_datetime(df.index, utc=True)
df = df[["open", "high", "low", "close", "spread_pts"]].rename(columns={"spread_pts": "data_spread_pips"})
df["data_spread_pips"] = df["data_spread_pips"].clip(lower=floor)
df = df[df.index >= "2011-01-01"]
rows = []
for name, spec in VARS.items():
    c = make_cfg(sym, spec)
    c["instrument"]["min_units"] = 1000
    se = c["account"]["starting_equity"]
    t, eq = run_backtest(df, c)
    t["entry_time"] = pd.to_datetime(t["entry_time"])
    m = summarize(t, eq, se)
    py = per_year(t, eq, se)
    yrs = dict(zip(py.year, py["ret%"]))
    rows.append(dict(variant=name, trades_yr=round(len(t) / 15.9, 1), pf=m["pf"], avgR=m["avgR"], win=m["win%"],
                     dd=m["dd%"], yrs_up=f"{sum(v > 0 for v in yrs.values())}/{len(yrs)}",
                     **{str(y): v for y, v in yrs.items()}))
    print(rows[-1], flush=True)
out = pd.DataFrame(rows)
out.to_csv("results/chfjpy_pullback.csv", index=False)
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30)
print(out.to_string(index=False))
