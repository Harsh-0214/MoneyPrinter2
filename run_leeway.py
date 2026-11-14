"""Leeway test: loosen every London threshold by the same small percentage and see whether
the near-miss trades it lets in are worth taking.

    python run_leeway.py

Leeway L applies at once to: Sweep minimum reward/risk (1.5 x (1-L)), Sweep max stop
(25 x (1+L)), Breakout minimum range (22 x (1-L)), maximum range (80 x (1+L)) and the
"move already ran" cap (15 x (1+L)). EURUSD + GBPUSD, histdata 2021-23 and 2024-25,
1% risk, live settings otherwise. The extra trades are listed so their result is visible.
"""
import copy

import pandas as pd
import yaml

from run_validate import load_pairs, run_multi, summarize

cfg = yaml.safe_load(open("config.yaml"))
cfg["risk"]["risk_per_trade_pct"] = 1.0
bars = {k: v for k, v in load_pairs(cfg).items() if k in ("EURUSD", "GBPUSD")}
se = cfg["account"]["starting_equity"]


def loosen(c, L):
    c = copy.deepcopy(c)
    for s in c["strategies"]["morning"]:
        if s["name"] == "london_sweep":
            s["min_rr"] = s["min_rr"] * (1 - L)
            s["max_stop_pips"] = s["max_stop_pips"] * (1 + L)
        if s["name"] == "london_breakout":
            s["min_range_pips"] = s["min_range_pips"] * (1 - L)
            s["max_range_pips"] = s["max_range_pips"] * (1 + L)
            s["max_defer_extension_pips"] = s["max_defer_extension_pips"] * (1 + L)
    return c


rows, base_keys = [], None
for L in (0.0, 0.005, 0.02, 0.05, 0.10, 0.20):
    c = loosen(cfg, L)
    t, eq = run_multi(bars, c)
    t = t.copy()
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    keys = set(zip(t.symbol, t.entry_time))
    if base_keys is None:
        base_keys = keys
    extra = t[[k not in base_keys for k in zip(t.symbol, t.entry_time)]]
    r = dict(leeway=f"{L:.1%}", trades=len(t), extra=len(extra),
             extra_R=round(extra.r_multiple.sum(), 1) if len(extra) else 0.0,
             extra_won=int((extra.r_multiple > 0).sum()))
    for lab, s, e in (("21-23", "2021-01-01", "2023-12-31"), ("24-25", "2024-01-01", "2025-12-31")):
        tt, ee = run_multi(bars, c, s, e)
        m = summarize(tt, ee, se)
        r[f"ret {lab}"], r[f"pf {lab}"], r[f"dd {lab}"] = m["ret%"], m["pf"], m["dd%"]
    rows.append(r)
    print(r, flush=True)
df = pd.DataFrame(rows)
df.to_csv("results/leeway.csv", index=False)
pd.set_option("display.width", 220)
print(df.to_string(index=False))
