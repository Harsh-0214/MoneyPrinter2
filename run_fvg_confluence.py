"""Does a breakout candle that leaves a fair value gap ("displacement") work better?

    python run_fvg_confluence.py

For every live London Sweep / Breakout (EURUSD 15 min, GBPUSD 5 min) and USDJPY breakout
trade (portfolio caches: histdata 2021-25 + broker 2026), look at the signal candle t:
a bullish FVG if low[t] > high[t-2] (sell: high[t] < low[t-2]) - known when the trade is entered.
Compare the trades' R with and without the gap, per period. A filter is only worth a portfolio
test if the gap trades are better in all three periods.
"""
import copy
import os
import sys

import pandas as pd
import yaml

import run_portfolio as rp

TF = {"EURUSD": "15min", "GBPUSD": "5min", "USDJPY": "15min"}


def main():
    cfg = yaml.safe_load(open("config.yaml"))
    base = copy.deepcopy(cfg)
    from run_validate import load_pairs
    bars = {"hist": load_pairs(base), "mt5": rp._mt5_bars(base)}
    rows = []
    for src in ("hist", "mt5"):
        t = rp.load_trades(cfg, src)
        t = t[t.unit.isin(TF)]
        t = t[(t.entry_time >= "2021-01-01") & (t.entry_time < "2026-01-01")] if src == "hist" else t[t.entry_time >= "2026-01-01"]
        for u, g in t.groupby("unit"):
            b = bars[src][u]
            dt = pd.Timedelta(TF[u])
            for r in g.itertuples():
                i = b.index.searchsorted(r.entry_time - dt)      # signal candle = the one closing at entry
                if i < 2 or i >= len(b) or abs(b.index[i] - (r.entry_time - dt)) > pd.Timedelta("1min"):
                    continue
                hi, lo = b.high.to_numpy(), b.low.to_numpy()
                gap = lo[i] > hi[i - 2] if r.side == 1 else hi[i] < lo[i - 2]
                y = r.entry_time.year
                rows.append(dict(unit=u, kind=str(r.tag).split("_")[0], R=r.r_multiple, fvg=bool(gap),
                                 period="2021-23" if y <= 2023 else "2024-25" if y <= 2025 else "2026"))
    d = pd.DataFrame(rows)
    print(f"{len(d)} trades matched to their signal candle")
    s = d.groupby(["unit", "kind", "period", "fvg"]).R.agg(["size", "mean"]).round(2).unstack("fvg")
    s.columns = [f"{a} {'FVG' if b else 'no FVG'}" for a, b in s.columns]
    pd.set_option("display.width", 220)
    print(s.to_string())
    d.to_csv("results/fvg_confluence.csv", index=False)


if __name__ == "__main__":
    main()
