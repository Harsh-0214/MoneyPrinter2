"""The London stack (Sweep + Breakout, live settings) on pairs it has never traded, using
the broker's own 15-minute feed (~2.4 years, mid-2024 -> now; fetch_mt5_more.py).

    python run_london_crosses.py

EURUSD / GBPUSD on the same feed are the reference rows. Only 15-min bars exist this far
back, so GBPUSD runs on 15-min here (live: 5-min). No SMT partner for the new pairs (the
filter passes). Spread = the bar's recorded spread, floored at the pair's typical spread.
Judged per year; a pair needs PF >= 1.15 and no losing year to be worth a longer look.
"""
import copy
import os

import pandas as pd
import yaml

from fxbot.backtest import pair_config, run_backtest
from run_validate import per_year, summarize

BASE = yaml.safe_load(open("config.yaml"))
EUR = next(p for p in BASE["pairs"] if p["symbol"] == "EURUSD")
FLOOR = {"EURUSD": 1.4, "GBPUSD": 2.0, "AUDUSD": 1.5, "USDCAD": 1.6, "USDCHF": 1.8, "NZDUSD": 2.0,
         "EURGBP": 1.5}


def bars(sym):
    fn = f"data/mt5/{sym}_M15.csv"
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    out = df[["open", "high", "low", "close"]].copy()
    out["data_spread_pips"] = (df["spread_pts"] * float(df["point"].iloc[0]) / 0.0001).clip(lower=FLOOR[sym])
    return out


rows, years = [], []
for sym in FLOOR:
    b = bars(sym)
    if b is None:
        print(f"  {sym}: no M15 file yet")
        continue
    pe = copy.deepcopy(EUR)
    pe["symbol"], pe["spread_pips"] = sym, FLOOR[sym]
    pe["data"]["timeframe"] = "15min"
    c = pair_config(BASE, pe)
    c["smt"] = {}
    c["account"]["starting_equity"] = 1_000_000
    c["risk"]["risk_per_trade_pct"] = 1.0
    c["risk"]["max_leverage"] = 1000
    if sym in ("USDCAD", "USDCHF"):
        c["instrument"] = {"pip": 0.0001, "min_units": 1000, "inverse_quote": True}
    se = c["account"]["starting_equity"]
    t, eq = run_backtest(b, c)
    m = summarize(t, eq, se)
    py = per_year(t, eq, se)
    rows.append(dict(pair=sym, trades_yr=round(len(t) / ((eq.index[-1] - eq.index[0]).days / 365.25), 1), **m,
                     **{str(y): r for y, r in zip(py.year, py["ret%"])}))
    print(f"  {sym:<7} {rows[-1]}", flush=True)
df = pd.DataFrame(rows)
df.to_csv("results/london_crosses.csv", index=False)
pd.set_option("display.width", 250)
print(df.to_string(index=False))
