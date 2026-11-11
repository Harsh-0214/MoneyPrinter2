"""True out-of-sample check: run the live portfolio on recent data straight from MT5.

    python run_oos_mt5.py                  # 2026-01-01 .. today
    python run_oos_mt5.py --since 2026-06-01

Every setting was chosen on 2021-2025 histdata, so anything from 2026 on is data the
strategies have never seen. Uses ~99k M5 / 12k H1 bars from the MT5 terminal (read-only,
no orders). Bars before --since are only used to warm up indicators.
Nov 2026 result (2026-01-01 .. 2026-11-11): +17.0%, max DD -4.7%, PF 2.60, 59 trades.
"""
import argparse
import sys, os, copy
sys.path.insert(0, os.getcwd())
import pandas as pd, yaml, MetaTrader5 as mt5
from datetime import datetime
from fxbot.data import server_ts_to_utc
from fxbot.backtest import expand_units, pair_config, run_backtest
from run_validate import summarize

cfg = yaml.safe_load(open("config.yaml"))
mt5.initialize()
TF = {"5min": mt5.TIMEFRAME_M5, "1h": mt5.TIMEFRAME_H1}
BROKER = {"EURUSD": "EURUSD.", "GBPUSD": "GBPUSD.", "XAUUSD": "XAUUSD"}
cache = {}


def bars(sym, tf):
    if (sym, tf) not in cache:
        r = mt5.copy_rates_from_pos(BROKER[sym], TF[tf], 0, 99000 if tf == "5min" else 12000)
        if r is None or len(r) == 0:
            raise SystemExit(f"no MT5 history for {sym} {tf}: {mt5.last_error()}")
        df = pd.DataFrame(r)
        df.index = server_ts_to_utc(df["time"].values)
        df = df[df.index.notna()][["open", "high", "low", "close"]]
        df = df[~df.index.duplicated()].sort_index()
        print(f"{sym} {tf}: {len(df)} bars from {df.index[0]} to {df.index[-1]}")
        cache[(sym, tf)] = df
    return cache[(sym, tf)]


ap = argparse.ArgumentParser()
ap.add_argument("--since", default="2026-01-01")
args = ap.parse_args()
SINCE = pd.Timestamp(args.since, tz="UTC")
se = cfg["account"]["starting_equity"]
rows, pnl, allt = [], None, []
for u in expand_units(cfg):
    c = pair_config(cfg, u)
    tf = c["data"]["timeframe"]
    b = bars(u["market"], tf).copy()
    if u.get("smt") and u["market"] in ("EURUSD", "GBPUSD"):
        other = "GBPUSD" if u["market"] == "EURUSD" else "EURUSD"
        s = bars(other, tf)[["high", "low"]].reindex(b.index)
        b["smt_high"], b["smt_low"] = s["high"], s["low"]
    c["smt"] = {}
    t, eq = run_backtest(b, c)            # warm-up from mid-2025, score 2026 only
    t = t[pd.to_datetime(t.entry_time) >= SINCE] if len(t) else t
    e26 = eq[eq.index >= SINCE]
    e26 = e26 - e26.iloc[0] + se
    m = summarize(t, e26, se)
    rows.append(dict(unit=u["key"], **m))
    p = (e26 - se)
    pnl = p if pnl is None else pnl.add(p.reindex(pnl.index, method="ffill").fillna(0), fill_value=0)
    allt.append(t)
mt5.shutdown()
print(f"{args.since} .. today, live config, true out-of-sample\n")
print(pd.DataFrame(rows).to_string(index=False))
eq = (pnl.sort_index().ffill() + se)
m = summarize(pd.concat(allt), eq, se)
print(f"\nPORTFOLIO since {args.since}: {m}")
print("monthly %:", ((eq.resample("ME").last() / eq.resample("ME").last().shift(1).fillna(se)) - 1).mul(100).round(2).to_dict())
